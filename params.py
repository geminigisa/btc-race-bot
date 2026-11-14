"""Parameter strategi dip-buy swing (lihat main.py).

dip_bps: seberapa jauh close harus turun dari tertinggi high_n bar
    terakhir agar dianggap dip (basis poin).
high_n: jendela tertinggi untuk mengukur dip (bar).
tp_bps: take-profit di atas cost (basis poin).
sl_bps: stop-loss di bawah cost (basis poin).
max_hold: jual paksa setelah sekian bar memegang posisi.
norecov_bps / norecov_bars: jual bila masih rugi setelah norecov_bars
    bar (nonaktif bila None).
max_trips: jumlah maksimum trip (buy fill) dalam satu jendela.
no_entry_last: jangan entry pada sekian bar terakhir jendela.
dip_max_age: umur maksimum fase dip agar entry masih diizinkan (bar).
trend_n: filter tren, close harus di atas SMA(n) (nonaktif bila None).
rsi_max: filter RSI, RSI(14) harus di bawah nilai ini (nonaktif bila None).
min_atr_bps: filter ATR, ATR(20) harus di atas nilai ini dalam bps
    (nonaktif bila None).
bounce_bps: konfirmasi pantulan, close harus naik sekian bps di atas
    dip_low (nonaktif bila None).
trail_bps: trailing stop setelah TP tercapai (nonaktif bila None).
"""

P = {'dip_bps': 40, 'high_n': 45, 'tp_bps': 70, 'sl_bps': 50, 'max_hold': 180, 'norecov_bps': None, 'norecov_bars': None, 'max_trips': 4, 'no_entry_last': 60, 'dip_max_age': 30, 'trend_n': 60, 'rsi_max': None, 'min_atr_bps': None, 'bounce_bps': 10, 'trail_bps': None}
