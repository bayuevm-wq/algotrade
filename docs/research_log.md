# Catatan riset

Aturan: strategi lolos hanya jika mengalahkan benchmark pasarnya secara **out-of-sample setelah
biaya**. Yang gagal atau belum lolos tetap dicatat. Semua angka biaya saat ini masih
PERLU DICEK, jadi belum ada strategi yang bisa dinyatakan lolos.

| Tanggal | Strategi & data | Jenis uji | Hasil (strategi vs Buy & Hold) | Status |
|---|---|---|---|---|
| 2026-11-26 | `sma_cross`, BTC/USDT 1d, 9 kombinasi per jendela | walk-forward OOS 2022 - 25 Nov 2026 | return 58,6% vs 30,6%; Sharpe 0,45 vs 0,36; max DD -36% vs -67% | **gugur** di uji overfitting 28 Nov 2026 (lihat bawah) |
| 2026-11-26 | `sma_cross` 20/100, BTC/USDT + SPY | backtest seluruh periode (bukan OOS) | return 446% vs 601%; Sharpe 0,90 vs 0,77 | belum diuji OOS |
| 2026-11-26 | `sma_cross` 20/100, BTC + ETH perpetual, 1x, boleh short | backtest, funding arsip Binance | return 583% vs spot 1339%; Sharpe 0,83 vs 0,95; funding x2: return 165% | gagal |
| 2026-11-26 | idem, 3x tanpa short | backtest, funding arsip Binance | return 744% vs 1339%; max DD -91%; funding x2: 44% dan 1 likuidasi | gagal |
| 2026-11-26 | `sma_cross` 20/100, BTC/USDT + SPY, stop 10% / take 30% | backtest | return 17% vs 601% | gagal |
| 2026-11-26 | `sma_cross` 20/100, 3 pool DEX 4h | backtest **indikatif**, 5 bulan | return 10,4% vs -4,9% | belum bisa dinilai: data terlalu pendek |
| 2026-11-28 | `sma_cross`, BTC/USDT 1d, 9 variasi (pra-registrasi `e2bf4f7`) | DSR, PBO, walk-forward | DSR(50) 0,904; PBO 0,682; Sharpe OOS 0,448 vs 0,356 | **tidak lolos** |

## Uji overfitting: `sma_cross_btc` (28 Nov 2026)

Data BTC/USDT harian 1 Jan 2019 - 27 Nov 2026, dinilai mulai 20 Jul 2019 (2688 bar). Ambang
ditetapkan dan di-commit sebelum hasil dihitung; tidak diubah sesudahnya.

| Kriteria | Hasil | Lolos |
|---|---|---|
| DSR dengan 50 percobaan >= 0,95 | 0,904 (9 percobaan: 0,934; 100: 0,892) | tidak |
| PBO <= 0,20 | 0,682 (12.870 pembagian) | tidak |
| Sharpe walk-forward > Buy & Hold | 0,448 vs 0,356 (2022 - 27 Nov 2026) | ya |

- Walk-forward: return 58,6% vs 29,4%; max drawdown -36,4% vs -66,9%.
- PBO 0,682: parameter terbaik di masa lalu lebih sering berada di median atau lebih buruk pada
  data lain. Memilih parameter tidak memberi keunggulan.
- Sharpe semua variasi 0,45 - 0,73 (positif, berdekatan). Rugi di luar sampel 11,6%.
- Keyakinan strategi lebih baik daripada Buy & Hold dari selisih return harian: 0,428. Rata-rata
  return hariannya tidak lebih tinggi; keunggulan walk-forward datang dari risiko lebih kecil.
- Biaya x2: DSR 0,897; Sharpe walk-forward 0,421 vs 0,355.
- DSR bila sebaran antar percobaan selebar ketidakpastian data: 0,389.
- Batasan: biaya belum diverifikasi; satu aset; percobaan sebelum 28 Nov 2026 tidak tercatat.
