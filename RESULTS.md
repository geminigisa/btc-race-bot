# BTC race bot — hasil dev-window

Bot: `main.py` + `params.py` + `vendor/makefun_bars.py` (shim Python kit, byte-identik).
Lokasi: `~/workspace/makefun/btc-race/bot/`

## Hasil akhir (dev window, 1.440 bar, 24 jam)

| Metrik | Nilai |
|---|---|
| Net PnL | **+$21,20** (21.203742 USDC) |
| Dev gate (> $0) | **LULUS** |
| Final cash | $1.021,20 dari $1.000 |
| Trade terisi | 6 (3 buy + 3 sell) |
| Round trip | 3: +$10,84 / +$8,05 / +$2,32 |
| Total fee | $2,43 |
| Max drawdown | 0,30% (batas 25%) |
| Order ditolak | 0 |
| Deterministik | YA — dua run menghasilkan action log byte-identik (sha256 `277f9cfa…`) |

Perintah grade yang dipakai:

```
python3 harness.py --bot . --twice --json-out /tmp/final-grade.json
```

## Strategi final

Dip-buy swing, long only, 1 posisi, 100% cash per entry:

- **Entry**: close turun >= **45 bps** dari rolling high **45 bar** terakhir.
  Tanpa filter tren / RSI / ATR / bounce (semuanya diuji dan memperburuk hasil).
- **Exit**: take profit **+70 bps** dari cost, stop loss **−30 bps**,
  atau time exit setelah **120 bar** ditahan.
- **Maks 3 round trip** per window; tidak entry di 60 bar terakhir.
- Sinyal dip yang berumur > 30 bar dibuang.
- `max_slippage_bps` = 100 pada semua order.
- Harness (engine resmi) yang menutup posisi di akhir window — bot tidak
  perlu order jual di `done`.

Semua trade terjadi di jam 0,8–6,5 window (fase naik); setelah 3 trip bot
diam dan tidak memaksakan trade di fase turun.

## Tabel sweep (ringkas)

Stage 1 — 144 kombinasi (dip 40/45/50/60 × TP 50/70/80/100 × SL 30/50/tanpa ×
tren tanpa/SMA20/SMA60):

| Peringkat | PnL | Parameter |
|---|---|---|
| 1 | +$14,20 | dip 45, TP 70/80, SL 30, tanpa tren, 4 trip |
| 2 | +$12,95 | dip 45, TP 70/80, SL 50, tanpa tren, 4 trip |
| 3 | +$11,60 | dip 45, TP 100, SL 30, tanpa tren, 4 trip |
| — | +$8,47 | dip 60, TP 70, SL 30, tren SMA60, 1 trip |

Stage 2 — 32 kombinasi di sekitar pemenang (bounce, RSI, ATR, max_hold,
no-recovery, max_trips, no_entry_last, dip_max_age, high_n):

| Peringkat | PnL | Parameter |
|---|---|---|
| 1 | +$19,24 | max_trips 3 (sisanya sama) |
| 2 | +$16,09 | max_hold 120, 4 trip |
| 3 | +$14,20 | baseline stage 1 |

Stage 3 — 33 kombinasi (max_hold × TP, dip × SL, bounce, high_n;
semua dengan max_trips 3):

| Peringkat | PnL | Parameter |
|---|---|---|
| 1 | +$21,20 | max_hold 120, TP 70/80, SL 30 |
| 2 | +$19,25 | max_hold 120, TP 100, SL 30 |
| 3 | +$19,24 | max_hold 180, TP 70/80, SL 25–50 |

Stage 4 — 16 kombinasi (trailing stop, fine max_hold, fine dip/high_n):

| Peringkat | PnL | Parameter |
|---|---|---|
| 1 | +$22,22 | max_hold 140 |
| 2 | +$21,51 | max_hold 100 |
| 3 | +$21,26 | max_hold 130 |
| 4 | +$21,20 | max_hold 120 (dipilih — tengah plateau 100–140) |
| — | +$10,93–14,84 | semua varian trailing stop — DITOLAK |
| — | +$6,86 | dip 48 — jauh lebih buruk |

**Robustness**: plateau datar +$19–22 di sekitar parameter final
(max_hold 100–140, TP 70–100, SL 25–50), bukan satu titik tajam.
Pengecualian: dip 45 adalah puncak yang cukup tajam (dip 42 → +$13,93;
dip 48 → +$6,86). Ini risiko overfit yang dicatat — tapi dip 45 juga
cocok dengan parameter pemenang leaderboard race 12 Nov (dip 45–50 bp).

Yang diuji dan DITOLAK karena memperburuk: filter tren (SMA20/60),
RSI <= 40, volatility gate ATR >= 8/12 bps, bounce confirmation
(+10/15/25 bp), trailing stop, max_trips 4–6 (trip ke-4+ rugi di
downtrend: trip ke-4 −$6,28; 6 trip total hanya +$4,34).

## Validasi harness (penting)

`grade-local --driver process` hanya menjalankan bot Node; bot Python
butuh Docker (tidak tersedia di VM ini). Karena itu saya menulis
`harness.py` — replay Python yang meniru `sim/bars/engine.ts` resmi
secara eksak (aritmetika integer, urutan cek decision, rumus fill
buy/sell + price impact constant-product, flatten di akhir, equity
points, max drawdown). Harness ini divalidasi terhadap grade resmi:

| Bot uji | Grade resmi | Harness saya |
|---|---|---|
| buy-and-hold (TS) | PnL −25.968237, 1 trade, fee 0.789769, maxDD 0.039400091 | PnL −25.968237, 1 trade, fee 0.789769, maxDD 0.039400091 — **identik** |
| ema-cross (TS) | PnL −95.880484, 68 trade, 1 reject, fee 26.072993, maxDD 0.099995497 | PnL −95.880484, 68 trade, 1 reject, fee 26.072993, maxDD 0.099995497 — **identik** |

Perintah validasi:

```
node cli/makefun.mjs grade-local --kit . --bot baselines/buy-and-hold --driver process --json
node cli/makefun.mjs grade-local --kit . --bot baselines/ema-cross --driver process --json
python3 harness.py --bot probe-bh        # replika Python buy-and-hold
python3 harness.py --bot probe-ema --twice  # replika Python ema-cross
```

Jebakan yang ditemukan saat sweep: Python memakai cache `__pycache__`
untuk `params.py`; penulisan ulang berurutan dengan ukuran sama bisa
memuat parameter basi. Diperbaiki dengan `python3 -B` +
`PYTHONDONTWRITEBYTECODE=1` di `harness.py`, dan semua hasil sweep
di atas adalah hasil setelah perbaikan (stage 1 diulang).

## Catatan dev window

- BTC turun $73.739 → $72.044 (−230 bps) dalam 24 jam; buy-and-hold
  rugi −$25,97. Satu bar hilang (gap, index 976) — dalam batas 2%.
- Strategi trend-following (ema-cross resmi) rugi −$95,88 dengan 34
  round trip — overtrading di pasar choppy.
- Bot ini lolos gate dengan margin sehat (+$21,20, setara dengan
  papan atas leaderboard race 12 Nov yang +$20–26).

## Siap submit?

**Ya.** Bot lolos dev gate (+$21,20), deterministik, tanpa reject,
drawdown 0,30%. Yang belum: repo GitHub + submit saat race BTC
berikutnya buka (race 12 Nov sudah tutup; pantauan 30 menit aktif).
