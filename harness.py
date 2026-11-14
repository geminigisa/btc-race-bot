"""Faithful local replay of the make.fun bars-replay/v1 harness (BTC race kit).

Mirrors /tmp/harness-src/sim/bars/engine.ts exactly (integer math, same check order,
same fill formulas, same flatten, same equity points and max-drawdown definition).
Used because grade-local --driver process runs node22 only and Docker is unavailable,
so a Python bot cannot be graded by the official CLI locally.

Usage:
  python3 harness.py --bot /path/to/bot-dir [--params k=v ...] [--seed N] [--twice]
    --bot: directory holding main.py (run as `python3 -P -s main.py`)
    --params: passed to the bot as JSON on... (not used: bot params are baked into main.py;
              sweep.py rewrites a params file instead)
    --twice: run the bot twice and compare action logs byte-for-byte (determinism)

Exit 0 with a JSON report on stdout. Non-zero on bot crash / protocol violation.
"""
import argparse
import gzip
import json
import math
import subprocess
import sys

BPS = 10_000
KIT = "/home/hatch/workspace/makefun/btc-race/btc-race-24h-20261113-2314-kit/btc-race-24h-20261113-2314-kit"
BARS_GZ = KIT + "/dataset/bars/CBBTC.ndjson.gz"

SYMBOL = "CBBTC"
MINT = "cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij"
PRICE_SCALE = 5
QTY_SCALE = 8
QUOTE_SCALE = 6
START_CASH = 1_000_000_000  # $1,000 in quote units (1e6 per USDC)
FEE_BPS = 4
SLIPPAGE_BPS = 2
MIN_NOTIONAL = 1_000_000  # $1
MAX_OPEN_POSITIONS = 1
MAX_ORDERS_PER_BAR = 16
MAX_WEIGHT_BPS = 10_000
STEP_MS = 60_000
WINDOW_START = 1794525240000
WINDOW_END = 1794611640000
N_BARS = 1440
FIRST_CLOSE = WINDOW_START + STEP_MS


def bars_value(q, p):
    return q * p * 10 ** QUOTE_SCALE // 10 ** (QTY_SCALE + PRICE_SCALE)


class BarsPool:
    """Exact port of sim/bars/engine.ts BarsPool (single-hop in our case, general code)."""

    def __init__(self, yn, yd, kn, kd, unit):
        g = math.gcd(yn, yd)
        self.yn, self.yd = yn // g, yd // g
        self.kn, self.kd = kn, kd
        self.unit = unit

    @classmethod
    def of(cls, depth, quote_scale):
        d = [x * 10 ** quote_scale for x in depth]
        prod = 1
        for x in d:
            prod *= x
        total = 0
        for i in range(len(d)):
            other = 1
            for j, x in enumerate(d):
                if j != i:
                    other *= x
            total += other
        g = math.gcd(prod, total)
        return cls(prod // g, total // g, (prod // g) ** 2, (total // g) ** 2, 10 ** 6)

    def buy(self, spend):
        yn2 = self.yn + spend * self.unit * self.yd
        num = self.yn * yn2 * self.kd
        den = self.yd * self.yd * self.kn
        return num, den, BarsPool(yn2, self.yd, self.kn, self.kd, self.unit)

    def sell(self, value):
        t = self.kn * self.yd + value * self.unit * self.yn * self.kd
        num = t * self.yd
        den = self.kd * self.yn * self.yn
        return num, den, BarsPool(self.kn * self.yn, t, self.kn, self.kd, self.unit)


def bars_buy_fill(notional, open_price, pool, fee_bps, slippage_bps):
    spend = notional * (BPS - fee_bps) // BPS
    num, den, after = pool.buy(spend)
    price = open_price * (BPS + slippage_bps) * num // (BPS * den)
    qty = spend * 10 ** (QTY_SCALE + PRICE_SCALE) // (price * 10 ** QUOTE_SCALE)
    return {"price": price, "spend": spend, "fee": notional - spend, "qty": qty, "after": after}


def bars_sell_fill(qty, open_price, pool, fee_bps, slippage_bps):
    value = bars_value(qty, open_price)
    num, den, after = pool.sell(value)
    slipped = open_price * (BPS - slippage_bps) * den // (BPS * num)
    price = slipped if slipped >= 1 else 1
    gross = bars_value(qty, price)
    proceeds = gross * (BPS - fee_bps) // BPS
    return {"price": price, "gross": gross, "fee": gross - proceeds, "proceeds": proceeds, "after": after}


def load_bars():
    bars = {}
    with gzip.open(BARS_GZ, "rt") as f:
        for line in f:
            b = json.loads(line)
            bars[int(b["t"])] = {
                "symbol": SYMBOL,
                "t": int(b["t"]),
                "o": int(b["o"]),
                "h": int(b["h"]),
                "l": int(b["l"]),
                "c": int(b["c"]),
                "v": None,
                "o_depth": [int(x) for x in b["o_depth"]],
                "c_depth": [int(x) for x in b["c_depth"]],
            }
    return bars


class Replay:
    def __init__(self, bars, seed="0"):
        self.bars = bars
        self.seed = seed
        self.cash = START_CASH
        self.qty = 0
        self.cost = 0
        self.close = None
        self.close_depth = []
        self.pending = []  # dicts: order, seq, index, decided_bar, fill_bar, reject, amount, close
        self.used_ids = set()
        self.equity_points = []  # equity ints in order
        self.fills = []  # filled order records
        self.rejects = []  # (seq, client_id, reason, at)
        self.round_trips = []  # pnl per closed trip (quote units)
        self.open_trip_pnl = None
        self.open_trip_bar = None
        self.total_fees = 0
        self.action_log = []  # reply lines (bytes) for determinism check
        self.seq = 0

    def equity_now(self):
        e = self.cash
        if self.qty > 0:
            e += bars_value(self.qty, self.close)
        return e

    def account(self):
        pos = []
        if self.qty > 0:
            pos.append({"symbol": SYMBOL, "qty": str(self.qty), "cost_quote_units": str(self.cost)})
        return {
            "cash_quote_units": str(self.cash),
            "positions": pos,
            "equity_quote_units": str(self.equity_now()),
        }

    def decide(self, reply):
        seq = self.seq
        is_last = seq == N_BARS - 1
        equity = self.equity_now()
        buys = 0
        bought = 0
        sold = 0
        open_syms = 1 if self.qty > 0 else 0
        orders = reply.get("orders", [])
        for index, order in enumerate(orders):
            side = order["side"]
            written = int(order["notional_quote_units"] if side == "buy" else order["qty"])
            amount = written
            reject = None
            if index >= MAX_ORDERS_PER_BAR:
                reject = "max_orders_per_bar"
            elif order["client_id"] in self.used_ids:
                reject = "duplicate_client_id"
            elif order.get("symbol") != SYMBOL:
                reject = "not_in_universe"
            elif written == 0:
                reject = "zero_amount"
            elif is_last:
                reject = "after_end"
            elif self.close is None:
                reject = "no_bar"
            elif side == "buy":
                cash_left = self.cash - buys
                held_value = bars_value(self.qty, self.close) if self.qty > 0 else 0
                if amount == 0:
                    reject = "insufficient_cash" if cash_left <= 0 else "max_weight"
                elif amount < MIN_NOTIONAL:
                    reject = "below_min_notional"
                elif amount > cash_left:
                    reject = "insufficient_cash"
                elif open_syms == 0 and 1 > MAX_OPEN_POSITIONS:
                    reject = "max_open_positions"
                elif (held_value + bought + amount) * BPS > MAX_WEIGHT_BPS * equity:
                    reject = "max_weight"
                if reject is None:
                    buys += amount
                    bought += amount
                    open_syms = 1
            else:  # sell
                available = self.qty - sold
                if amount == 0 or amount > available:
                    reject = "insufficient_position"
                elif amount != available and bars_value(amount, self.close) < MIN_NOTIONAL:
                    reject = "below_min_notional"
                if reject is None:
                    sold += amount
            self.used_ids.add(order["client_id"])
            self.pending.append({
                "order": order, "seq": seq, "index": index,
                "decided_bar": FIRST_CLOSE + seq * STEP_MS,
                "fill_bar": FIRST_CLOSE + (seq + 1) * STEP_MS,
                "reject": reject, "amount": amount, "close": self.close,
            })

    def resolve(self, bar):
        """Resolve pending orders at this bar's open; return protocol fills to deliver next batch."""
        pools = {}
        delivered = []
        for p in self.pending:
            if p["reject"] is not None:
                self.rejects.append((p["seq"], p["order"]["client_id"], p["reject"], "decision"))
                delivered.append(self._proto_fill(p, "rejected", p["reject"]))
                continue
            if bar is None:
                self.rejects.append((p["seq"], p["order"]["client_id"], "no_bar", "fill"))
                delivered.append(self._proto_fill(p, "rejected", "no_bar"))
                continue
            order = p["order"]
            close = p["close"]
            max_slip = int(order["max_slippage_bps"])
            pool = pools.get(SYMBOL)
            if pool is None:
                pool = BarsPool.of(bar["o_depth"], QUOTE_SCALE)
            if order["side"] == "buy":
                fill = bars_buy_fill(p["amount"], bar["o"], pool, FEE_BPS, SLIPPAGE_BPS)
                if fill["price"] * BPS > close * (BPS + max_slip):
                    self.rejects.append((p["seq"], order["client_id"], "max_slippage", "fill"))
                    delivered.append(self._proto_fill(p, "rejected", "max_slippage"))
                    continue
                if fill["qty"] == 0:
                    self.rejects.append((p["seq"], order["client_id"], "zero_amount", "fill"))
                    delivered.append(self._proto_fill(p, "rejected", "zero_amount"))
                    continue
                pools[SYMBOL] = fill["after"]
                self.cash -= p["amount"]
                if self.qty == 0:
                    self.open_trip_pnl = 0
                    self.open_trip_bar = bar["t"]
                self.qty += fill["qty"]
                self.cost += p["amount"]
                self.total_fees += fill["fee"]
                if self.open_trip_pnl is not None:
                    self.open_trip_pnl -= p["amount"]
                self.fills.append({"side": "buy", "seq": p["seq"], "price": fill["price"],
                                   "qty": fill["qty"], "notional": p["amount"], "fee": fill["fee"]})
                delivered.append(self._proto_fill(p, "filled", None, fill["price"], fill["qty"],
                                                  p["amount"], fill["fee"]))
            else:
                fill = bars_sell_fill(p["amount"], bar["o"], pool, FEE_BPS, SLIPPAGE_BPS)
                if fill["price"] * BPS < close * (BPS - max_slip):
                    self.rejects.append((p["seq"], order["client_id"], "max_slippage", "fill"))
                    delivered.append(self._proto_fill(p, "rejected", "max_slippage"))
                    continue
                pools[SYMBOL] = fill["after"]
                self.cash += fill["proceeds"]
                self.cost = self.cost * (self.qty - p["amount"]) // self.qty if self.qty else 0
                self.qty -= p["amount"]
                self.total_fees += fill["fee"]
                if self.open_trip_pnl is not None:
                    self.open_trip_pnl += fill["proceeds"]
                self.fills.append({"side": "sell", "seq": p["seq"], "price": fill["price"],
                                   "qty": p["amount"], "notional": fill["proceeds"], "fee": fill["fee"]})
                if self.qty == 0 and self.open_trip_pnl is not None:
                    self.round_trips.append(self.open_trip_pnl)
                    self.open_trip_pnl = None
                delivered.append(self._proto_fill(p, "filled", None, fill["price"], p["amount"],
                                                  fill["proceeds"], fill["fee"]))
        self.pending = []
        return delivered

    def _proto_fill(self, p, status, reason, price=0, qty=0, notional=0, fee=0):
        return {
            "client_id": p["order"]["client_id"], "symbol": SYMBOL, "side": p["order"]["side"],
            "status": status, "reason": reason, "decided_bar": p["decided_bar"],
            "fill_bar": p["fill_bar"], "price": str(price), "qty": str(qty),
            "notional_quote_units": str(notional), "fee_quote_units": str(fee),
        }

    def flatten(self, last_bar_t):
        if self.qty == 0:
            return
        fill = bars_sell_fill(self.qty, self.close, BarsPool.of(self.close_depth, QUOTE_SCALE),
                              FEE_BPS, SLIPPAGE_BPS)
        self.cash += fill["proceeds"]
        self.total_fees += fill["fee"]
        if self.open_trip_pnl is not None:
            self.open_trip_pnl += fill["proceeds"]
            self.round_trips.append(self.open_trip_pnl)
            self.open_trip_pnl = None
        self.qty = 0
        self.cost = 0

    def run(self, proc):
        def send(obj):
            line = json.dumps(obj, separators=(",", ":"))
            proc.stdin.write((line + "\n").encode())
            proc.stdin.flush()

        hello = {
            "type": "hello", "protocol": "agent-fun/bars-replay/v1", "seed": self.seed,
            "symbols": [{"symbol": SYMBOL, "mint": MINT, "price_scale": PRICE_SCALE, "qty_scale": QTY_SCALE}],
            "capital": {"quote": "USDC", "quote_scale": QUOTE_SCALE, "quote_units": str(START_CASH)},
            "bar_interval": "1m", "first_close_ms": FIRST_CLOSE,
            "caps": {"max_open_positions": MAX_OPEN_POSITIONS, "max_orders_per_bar": MAX_ORDERS_PER_BAR,
                     "max_weight_bps": MAX_WEIGHT_BPS, "shorts": False, "leverage": False},
            "fees": {"fee_bps": FEE_BPS, "slippage_bps": SLIPPAGE_BPS,
                     "min_notional_quote_units": str(MIN_NOTIONAL)},
            "latency_bars": 1,
        }
        send(hello)
        self.equity_points.append(START_CASH)
        undelivered = []
        for k in range(N_BARS):
            t = FIRST_CLOSE + k * STEP_MS
            bar = self.bars.get(t)
            undelivered = self.resolve(bar)
            if bar is not None:
                self.close = bar["c"]
                self.close_depth = bar["c_depth"]
            bars_out = []
            if bar is not None:
                bars_out.append({
                    "symbol": SYMBOL, "t": str(bar["t"]), "o": str(bar["o"]), "h": str(bar["h"]),
                    "l": str(bar["l"]), "c": str(bar["c"]), "v": None,
                    "o_depth": [str(x) for x in bar["o_depth"]],
                    "c_depth": [str(x) for x in bar["c_depth"]],
                })
            batch = {"type": "batch", "seq": k, "t": t, "bars": bars_out,
                     "fills": undelivered, "account": self.account()}
            undelivered = []
            send(batch)
            self.seq = k
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError(f"bot exited before reply to batch {k}")
            self.action_log.append(line)
            reply = json.loads(line)
            if reply.get("type") != "reply" or reply.get("seq") != k:
                raise RuntimeError(f"bad reply at batch {k}: {line[:200]!r}")
            if len(reply.get("orders", [])) > 64:
                raise RuntimeError(f"reply over 64 orders at batch {k}")
            self.decide(reply)
            self.equity_points.append(self.equity_now())
        # finish: reject pending (after_end decisions already recorded), flatten
        for p in self.pending:
            self.rejects.append((p["seq"], p["order"]["client_id"], p["reject"] or "after_end", "decision"))
        self.pending = []
        last_t = FIRST_CLOSE + (N_BARS - 1) * STEP_MS
        self.flatten(last_t)
        self.equity_points.append(self.cash)
        send({"type": "done", "seq": N_BARS, "reason": "end_of_data", "account": self.account()})
        proc.stdin.close()
        proc.wait(timeout=30)
        if proc.returncode != 0:
            raise RuntimeError(f"bot exited with code {proc.returncode} after done")

    def report(self):
        pnl = self.cash - START_CASH
        peak = 0
        worst = 0.0
        for e in self.equity_points:
            if e > peak:
                peak = e
            if peak > 0:
                dd = (peak - e) / peak
                if dd > worst:
                    worst = dd
        return {
            "net_pnl_usd": pnl / 1e6,
            "net_pnl_units": pnl,
            "final_cash_usd": self.cash / 1e6,
            "trades_filled": len(self.fills),
            "buys": sum(1 for f in self.fills if f["side"] == "buy"),
            "sells": sum(1 for f in self.fills if f["side"] == "sell"),
            "round_trips": len(self.round_trips),
            "round_trip_pnls_usd": [x / 1e6 for x in self.round_trips],
            "total_fees_usd": self.total_fees / 1e6,
            "max_drawdown": worst,
            "rejects": len(self.rejects),
            "reject_reasons": {},
            "meets_bar": len(self.fills) >= 1 and worst <= 0.25,
            "dev_gate_pass": pnl > 0,
        }


def run_once(bot_dir, seed="0"):
    bars = load_bars()
    replay = Replay(bars, seed=seed)
    # -B: never use/write bytecode caches, so a params.py rewritten between
    # runs cannot be shadowed by a stale __pycache__ entry (same size+mtime).
    env = dict(__import__("os").environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.Popen(
        ["python3", "-B", "-P", "-s", "main.py"],
        cwd=bot_dir, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env,
    )
    try:
        replay.run(proc)
    except Exception:
        err = proc.stderr.read().decode(errors="replace")[-2000:]
        try:
            proc.kill()
        except Exception:
            pass
        raise RuntimeError(f"bot run failed; stderr tail:\n{err}")
    rep = replay.report()
    from collections import Counter
    rep["reject_reasons"] = dict(Counter(r[2] for r in replay.rejects))
    rep["action_log_sha"] = __import__("hashlib").sha256(b"".join(replay.action_log)).hexdigest()
    return rep, replay


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", required=True)
    ap.add_argument("--seed", default="0")
    ap.add_argument("--twice", action="store_true")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()
    rep, _ = run_once(args.bot, seed=args.seed)
    if args.twice:
        rep2, _ = run_once(args.bot, seed=args.seed)
        rep["deterministic"] = rep["action_log_sha"] == rep2["action_log_sha"]
        rep["action_log_sha_2"] = rep2["action_log_sha"]
    else:
        rep["deterministic"] = None
    out = json.dumps(rep, indent=2)
    if args.json_out:
        with open(args.json_out, "w") as f:
            f.write(out)
    print(out)


if __name__ == "__main__":
    main()
