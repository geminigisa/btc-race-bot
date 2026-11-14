"""Dip-buy swing bot for make.fun "Race a BTC trading bot live for 24 hours".

Strategy: buy cbBTC on a dip from the rolling N-bar high (with trend / RSI /
bounce / volatility filters), exit at a take-profit, a stop-loss, a max hold
time, or a no-recovery cut. One position at a time, 100% of cash per entry,
at most MAX_TRIPS round trips per window. Standard library only, fully
deterministic (no clock, no randomness, no environment, no files).

Protocol: agent-fun/bars-replay/v1 via the kit's Python shim (vendor/).
The harness flattens any open position at the last close, so no exit order
is needed on done.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import makefun_bars  # noqa: E402
import params  # noqa: E402

P = params.P
SYMBOL = "CBBTC"
BPS = 10_000
MAX_SLIPPAGE_BPS = 100

# ---- series state (closes only; ints) ----
closes = []          # closes, oldest first (unbounded is fine: 1440 bars)
highs = []           # bar highs
lows = []            # bar lows
first_gain = []      # RSI warm-up changes
rsi_gain = None      # Wilder avg gain
rsi_loss = None      # Wilder avg loss
last_close = None

# ---- trade state ----
trips_started = 0    # buy fills seen
entry_seq = None     # seq when the current position first appeared
peak_value = None    # highest position value since entry (for trailing stop)
dip_low = None       # lowest close since the dip condition first held
dip_age = 0          # bars since the dip condition first held


def push(bar):
    global last_close, rsi_gain, rsi_loss
    c = int(bar["c"])
    h = int(bar["h"])
    lo = int(bar["l"])
    closes.append(c)
    highs.append(h)
    lows.append(lo)
    if last_close is not None:
        ch = c - last_close
        up = ch if ch > 0 else 0
        dn = -ch if ch < 0 else 0
        if rsi_gain is None:
            first_gain.append(ch)
            if len(first_gain) == 14:
                rsi_gain = sum(x for x in first_gain if x > 0) / 14.0
                rsi_loss = sum(-x for x in first_gain if x < 0) / 14.0
        else:
            rsi_gain = (rsi_gain * 13 + up) / 14.0
            rsi_loss = (rsi_loss * 13 + dn) / 14.0
    last_close = c


def sma(n):
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / float(n)


def rsi():
    if rsi_gain is None:
        return None
    moved = rsi_gain + rsi_loss
    return 50.0 if moved == 0 else 100.0 * rsi_gain / moved


def atr_bps(n=20):
    if len(closes) < n:
        return None
    tot = 0.0
    for i in range(len(closes) - n, len(closes)):
        tot += (highs[i] - lows[i]) * 10000.0 / closes[i]
    return tot / n


def on_batch(state, batch):
    global trips_started, entry_seq, peak_value, dip_low, dip_age
    fresh = False
    for bar in batch["bars"]:
        if bar["symbol"] == SYMBOL:
            push(bar)
            fresh = True
    if not fresh:
        return []
    # Count buy fills (a buy starts a round trip) and track position appearance.
    for f in batch.get("fills", []):
        if f.get("symbol") == SYMBOL and f.get("status") == "filled" and f.get("side") == "buy":
            trips_started += 1
    held = state.positions.get(SYMBOL)
    if held is not None and entry_seq is None:
        entry_seq = state.seq
        peak_value = state.value(SYMBOL, held.qty)
    if held is None:
        entry_seq = None
        peak_value = None

    seq = state.seq
    n_bars = len(closes)
    close = closes[-1]

    # ---- exit logic ----
    if held is not None:
        value = state.value(SYMBOL, held.qty)
        cost = held.cost
        if value > peak_value:
            peak_value = value
        bars_held = seq - entry_seq if entry_seq is not None else 0
        sell = False
        if P["trail_bps"] is not None:
            # trailing stop: arms once the position reaches TP, then sells
            # when it falls trail_bps below its peak value
            armed = peak_value * BPS >= cost * (BPS + P["tp_bps"])
            if armed and value * BPS <= peak_value * (BPS - P["trail_bps"]):
                sell = True
        elif value * BPS >= cost * (BPS + P["tp_bps"]):
            sell = True
        if P["sl_bps"] is not None and value * BPS <= cost * (BPS - P["sl_bps"]):
            sell = True
        elif bars_held >= P["max_hold"]:
            sell = True
        elif (P["norecov_bars"] is not None and bars_held >= P["norecov_bars"]
                and value < cost):
            sell = True
        if sell:
            return [{"side": "sell", "symbol": SYMBOL, "qty": held.qty,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        return []

    # ---- entry logic ----
    if trips_started >= P["max_trips"]:
        return []
    if n_bars < P["high_n"]:
        return []
    # bars remaining in the window: batches are 0..1439; an order on batch k
    # fills at k+1, so entering later than 1439 - P["no_entry_last"] is useless.
    if seq >= 1440 - P["no_entry_last"]:
        return []
    high_n = max(closes[-P["high_n"]:])
    dip = close * BPS <= high_n * (BPS - P["dip_bps"])
    if dip:
        if dip_low is None:
            dip_low = close
            dip_age = 0
        else:
            dip_low = min(dip_low, close)
            dip_age += 1
    else:
        # Recovered above the dip line: reset the dip tracker.
        if close * BPS > high_n * (BPS - P["dip_bps"] // 2):
            dip_low = None
            dip_age = 0
        return []
    if dip_age > P["dip_max_age"]:
        return []
    # trend filter
    if P["trend_n"] is not None:
        t = sma(P["trend_n"])
        if t is None or close < t:
            return []
    # RSI filter
    if P["rsi_max"] is not None:
        r = rsi()
        if r is None or r > P["rsi_max"]:
            return []
    # volatility gate (ATR in bps over the last 20 bars)
    if P["min_atr_bps"] is not None:
        a = atr_bps(20)
        if a is None or a < P["min_atr_bps"]:
            return []
    # bounce confirmation: enter only once the price has bounced off the dip low
    if P["bounce_bps"] is not None:
        if close * BPS < dip_low * (BPS + P["bounce_bps"]):
            return []
    # enter with everything
    room = state.weight_room(SYMBOL)
    amount = state.cash
    if amount > room:
        amount = room
    if amount < int(state.hello["fees"]["min_notional_quote_units"]):
        return []
    return [{"side": "buy", "symbol": SYMBOL, "notional_quote_units": amount,
             "max_slippage_bps": MAX_SLIPPAGE_BPS}]


makefun_bars.run(on_batch)
