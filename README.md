# btc-race-bot

Dip-buy swing bot for make.fun "Race a BTC trading bot live for 24 hours"
(`btc-race-24h-20261113-2314`).

Trades Coinbase Wrapped BTC (cbBTC) against USDC, one minute at a time, on
$1,000 of paper money. Buys a dip from the rolling 45-bar high only when the
price is above its 60-bar moving average and has bounced 10 bps off the dip
low; exits at take-profit (+70 bps), stop-loss (−50 bps), max hold (180 bars),
or the end of the window. One position at a time, at most 4 round trips.

## Files

- `main.py` — the bot (Python 3.13, standard library only)
- `params.py` — strategy parameters
- `vendor/makefun_bars.py` — the kit's Python protocol shim
- `harness.py` — local replay of the official bars-replay/v1 engine
  (byte-identical scores vs the official grader on the kit baselines)
- `sweep.py` — parameter sweep used for tuning

## Dev gate (this race's dev window, 12 Nov 23:14 – 13 Nov 23:14 UTC)

- Net PnL: **+$2.38** (1 round trip, fees $0.80)
- Max drawdown: 0.45% (limit 25%)
- Deterministic: identical action log across two runs

BTC fell ~5% ($71,407 → $67,901) in the dev window; the bot made one
winning trade. Margin is thin — this passes the gate, it does not promise
a profit in the live race.
