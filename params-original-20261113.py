"""Strategy parameters for main.py (final, tuned on the dev window).
"""
P = {
    "dip_bps": 45,       # enter when close is >= 45 bps below the rolling 45-bar high
    "high_n": 45,        # rolling-high lookback in bars
    "tp_bps": 70,        # take profit: position value >= cost * 1.0070
    "sl_bps": 30,        # stop loss: position value <= cost * 0.9970
    "max_hold": 120,     # max bars to hold before a time exit
    "norecov_bps": None,  # (unused)
    "norecov_bars": None,  # no-recovery exit off
    "max_trips": 3,      # max round trips per window
    "no_entry_last": 60,  # do not enter in the last 60 bars
    "dip_max_age": 30,   # drop a dip signal older than 30 bars
    "trend_n": None,     # no trend filter
    "rsi_max": None,     # no RSI filter
    "min_atr_bps": None,  # no volatility gate
    "bounce_bps": None,  # no bounce confirmation
    "trail_bps": None,  # fixed TP, no trailing stop (trailing tested worse)
}
