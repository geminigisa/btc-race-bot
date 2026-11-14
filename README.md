# BTC Dip-Buy Swing Bot

Bot trading untuk kompetisi make.fun "Race a BTC trading bot live for
24 hours" (btc-race-24h-20261113-2314). Bot memperdagangkan CBBTC/USDC
pada bar 1 menit dengan modal kertas $1.000 USDC.

## Strategi

Dip-buy swing, satu posisi long, 100% kas per entry, maksimal 4 trip
per jendela 24 jam:

1. **Dip**: close turun >= 40 bps dari tertinggi 45 bar terakhir.
2. **Pantulan**: close naik >= 10 bps dari harga terendah fase dip
   (dip_low), dalam umur dip maksimal 30 bar.
3. **Filter tren**: close harus di atas SMA 60.
4. **Exit**: take-profit +70 bps, stop-loss -50 bps, atau jual paksa
   setelah 180 bar memegang posisi.

Filter RSI(14) dan ATR(20) tersedia di kode tapi nonaktif di parameter
final. Detail lengkap ada di docstring `main.py` dan komentar
`params.py`.

## File

- `main.py` — bot (entrypoint). Berbicara protokol
  agent-fun/bars-replay/v1 lewat shim vendor: shim membaca hello lalu
  satu batch per menit dari stdin dan memanggil `on_batch(state,
  batch)`; balasan berupa list order (buy/sell), boleh kosong.
- `params.py` — satu dict `P` berisi seluruh parameter strategi.
- `vendor/makefun_bars.py` — shim protokol dari kit kompetisi
  (salinan byte-for-byte, tidak dihitung sebagai karya).
- `LICENSE` — MIT.

## Cara uji

Uji lokal pada dev window kompetisi dengan harness kit:

```bash
python3 /home/hatch/workspace/makefun/btc-race/bot/harness.py \
  --bot /home/hatch/workspace/makefun/btc-race/repo-build --twice
```

Lolos dev gate bila net PnL > $0, deterministik (dua eksekusi
menghasilkan log aksi yang sama persis), dan max drawdown <= 25%.

## Determinisme

Tanpa jam dinding, tanpa random, tanpa environment, tanpa file. Semua
keputusan hanya dari bar, fills, dan state yang dikirim harness.
Hanya standard library Python yang dipakai.
