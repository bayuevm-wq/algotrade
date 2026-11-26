# Catatan riset

Aturan: strategi lolos hanya jika mengalahkan benchmark pasarnya secara **out-of-sample setelah
biaya**. Yang gagal atau belum lolos tetap dicatat. Semua angka biaya saat ini masih
PERLU DICEK, jadi belum ada strategi yang bisa dinyatakan lolos.

| Tanggal | Strategi & data | Jenis uji | Hasil (strategi vs Buy & Hold) | Status |
|---|---|---|---|---|
| 2026-11-26 | `sma_cross`, BTC/USDT 1d, 9 kombinasi per jendela | walk-forward OOS 2022 - 25 Nov 2026 | return 58,6% vs 30,6%; Sharpe 0,45 vs 0,36; max DD -36% vs -67% | kandidat, belum lolos: satu aset, biaya belum dicek, kalah di 2023 dan 2024 |
| 2026-11-26 | `sma_cross` 20/100, BTC/USDT + SPY | backtest seluruh periode (bukan OOS) | return 446% vs 601%; Sharpe 0,90 vs 0,77 | belum diuji OOS |
| 2026-11-26 | `sma_cross` 20/100, BTC + ETH perpetual, 1x, boleh short | backtest, funding arsip Binance | return 583% vs spot 1339%; Sharpe 0,83 vs 0,95; funding x2: return 165% | gagal |
| 2026-11-26 | idem, 3x tanpa short | backtest, funding arsip Binance | return 744% vs 1339%; max DD -91%; funding x2: 44% dan 1 likuidasi | gagal |
| 2026-11-26 | `sma_cross` 20/100, BTC/USDT + SPY, stop 10% / take 30% | backtest | return 17% vs 601% | gagal |
| 2026-11-26 | `sma_cross` 20/100, 3 pool DEX 4h | backtest **indikatif**, 5 bulan | return 10,4% vs -4,9% | belum bisa dinilai: data terlalu pendek |
