"""Parameter sweep for the dip-buy bot: rewrites params.py, runs harness.run_once
per combo, prints a table sorted by dev-window net PnL. Run from bot/ dir.
"""
import itertools
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE = {
    "dip_bps": 50, "high_n": 45, "tp_bps": 80, "sl_bps": 30, "max_hold": 180,
    "norecov_bps": None, "norecov_bars": None, "max_trips": 4, "no_entry_last": 60,
    "dip_max_age": 30, "trend_n": None, "rsi_max": None, "min_atr_bps": None,
    "bounce_bps": None, "trail_bps": None,
}


def write_params(p):
    with open(os.path.join(BOT_DIR, "params.py"), "w") as f:
        f.write('"""Strategy parameters for main.py (written by sweep.py)."""\nP = ')
        f.write(repr(p))
        f.write("\n")


def run_grid(grid, label):
    results = []
    for combo in grid:
        p = dict(BASE)
        p.update(combo)
        write_params(p)
        try:
            rep, _ = harness.run_once(BOT_DIR)
        except Exception as e:
            print(f"FAIL {combo}: {e}")
            continue
        results.append((rep["net_pnl_usd"], rep["trades_filled"], rep["round_trips"],
                        rep["max_drawdown"], rep["total_fees_usd"], dict(combo)))
    results.sort(key=lambda r: -r[0])
    print(f"\n=== {label}: {len(results)} combos, top 15 ===")
    print(f"{'PnL$':>8} {'trd':>4} {'trips':>5} {'maxDD':>7} {'fees$':>7}  params")
    for pnl, trd, trips, dd, fees, combo in results[:15]:
        print(f"{pnl:8.2f} {trd:4d} {trips:5d} {dd:7.4f} {fees:7.2f}  {combo}")
    return results


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "1"
    if stage == "1":
        grid = [dict(zip(("dip_bps", "tp_bps", "sl_bps", "trend_n"), c))
                for c in itertools.product((40, 45, 50, 60), (50, 70, 80, 100),
                                           (30, 50, None), (None, 20, 60))]
        run_grid(grid, "stage1 dip x tp x sl x trend")
    elif stage == "2":
        # refine around the stage-1 winner: pass base combo as JSON on argv[2]
        base = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        grid = []
        for bounce in (None, 10, 15, 25):
            for rsi in (None, 35, 40, 45):
                grid.append(dict(base, bounce_bps=bounce, rsi_max=rsi))
        for atr in (None, 8, 12):
            grid.append(dict(base, min_atr_bps=atr))
        for mh in (60, 120, 240):
            grid.append(dict(base, max_hold=mh))
        for nr in (30, 60):
            grid.append(dict(base, norecov_bars=nr))
        for mt in (3, 6):
            grid.append(dict(base, max_trips=mt))
        for nel in (30, 120):
            grid.append(dict(base, no_entry_last=nel))
        for dma in (15, 60):
            grid.append(dict(base, dip_max_age=dma))
        for hn in (30, 60):
            grid.append(dict(base, high_n=hn))
        run_grid(grid, "stage2 refinements around " + json.dumps(base))
    elif stage == "single":
        p = dict(BASE)
        p.update(json.loads(sys.argv[2]) if len(sys.argv) > 2 else {})
        write_params(p)
        rep, _ = harness.run_once(BOT_DIR)
        print(json.dumps(rep, indent=2))
