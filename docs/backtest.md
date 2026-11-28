# Backtest

> Hasil backtest bukan jaminan hasil nyata. Bukan nasihat keuangan.

## Dua mesin

| | `backtest`, `walkforward`, `compare` | `portfolio` |
|---|---|---|
| Aset | satu per satu | banyak, modal bersama |
| Eksekusi | posisi berlaku mulai bar berikutnya (close ke close) | order terisi di harga **buka** bar berikutnya |
| Perpetual | ditolak (funding tidak dihitung) | funding, leverage, likuidasi |
| DEX | gas & price impact sebagai persen modal awal | gas per swap, impact per order, batas order |
| Stop / take-profit | tidak ada | ada, dicek di dalam bar |
| Mata uang | mata uang quote aset | USD/USDT/USDC (IDX ditolak) |

Angka kedua mesin bisa berbeda karena model eksekusinya berbeda.

```bash
uv run algotrade portfolio                                      # config/backtest.yaml
uv run algotrade portfolio --symbols BTC/USDT:USDT ETH/USDT:USDT --leverage 2 --allow-short
uv run algotrade portfolio --symbols BTC/USDT SPY --stop-loss 10 --take-profit 30
uv run algotrade portfolio --symbols SOL-USDC-solana --timeframe 4h
```

Hasil disimpan di `reports/portfolio_*` (log transaksi, equity, return bulanan, grafik).

Opsi `--source indodax` pada mesin satu aset memakai data cadangan (lihat
[`data.md`](data.md)). Hasilnya tidak setara dengan data OKX.

## Aturan mesin portofolio

- Sinyal dari bar yang sudah tutup dieksekusi di harga buka bar berikutnya. Bar harian saham
  baru "diketahui" setelah bursa tutup menurut kalender.
- Order dibuat hanya saat sinyal berubah (tidak ada rebalancing rutin).
- Pada waktu yang sama, order jual diisi lebih dulu daripada order beli.
- Jumlah order dibulatkan ke bawah sesuai lot minimum.
- Setelah stop, take-profit, atau likuidasi, posisi tidak dibuka lagi sampai sinyal berubah.
- Bila stop dan take-profit tersentuh di bar yang sama, dianggap **stop**. Bila harga buka
  sudah melewati level (gap), eksekusi di harga buka.

## Biaya

Semua di `config/instruments.yaml`. Yang masih tebakan bertanda **PERLU DICEK** dan terdaftar
di `unverified`; laporan memperingatkannya. Angka yang kosong membuat backtest ditolak.

| Pasar | Komponen |
|---|---|
| Crypto spot | fee taker + slippage |
| Perpetual | fee taker + slippage + funding; likuidasi |
| Saham US | komisi + separuh spread per sisi + slippage |
| DEX | swap fee + slippage + buffer MEV + gas per swap + price impact |

Fee *maker* tercatat tetapi belum dipakai: semua order dianggap market order.

## Funding perpetual

1. Satu kali jalan memakai **satu sumber**; funding **tidak pernah disambung**.
2. Laporan dibagi dua periode yang berdiri sendiri, masing-masing mulai dari modal awal:
   - **ARSIP BINANCE (pengganti):** sebelum data OKX tersedia. Funding Binance dikenakan pada
     harga OKX.
   - **FUNDING ASLI EXCHANGE:** sejak data OKX tersedia.
3. Kedua sumber juga dijalankan terpisah pada periode tumpang tindih sebagai pembanding.
4. Uji funding lebih mahal: yang dibayar x2, yang diterima x0,5 (bisa diubah).
5. Funding yang bolong atau tidak menutup periode membuat backtest ditolak.

Margin **terisolasi**: funding dipotong dari margin posisi dan tidak ditambah dari kas lain,
sehingga posisi bisa terlikuidasi karena funding walaupun harganya masih di atas harga masuk.

## DEX

- Likuiditas = potret terbaru x `liquidity_haircut` (50%). Ini **asumsi yang melihat ke
  belakang** karena riwayatnya belum ada.
- Satu order maksimal 0,5% dari likuiditas tersebut; sisanya dicoba di bar berikutnya. Karena
  itu, asumsi likuiditas yang berbeda mengubah **besar posisi**, bukan hanya biaya, sehingga
  return bisa naik walaupun likuiditas lebih kecil.
- Sensitivitas dijalankan pada 25%, 50%, dan 100%.
- Hasil berlabel **INDIKATIF** sampai riwayat likuiditas asli minimal 90 hari, cukup rapat, dan
  mencakup awal periode backtest. Backtest yang dimulai sebelum riwayat itu tetap indikatif.
- Riwayat harga hanya 180 hari: terlalu pendek untuk walk-forward.

## Benchmark

Buy & Hold aset yang sama, bobot, biaya, dan tanggal yang sama, tanpa stop. Untuk perpetual
dipakai **spot** pasangan yang sama.

## Verifikasi (26 Nov 2026, data asli)

- Buy & Hold BTC/USDT dan SPY dari mesin sama dengan hitungan manual dari harga mentah.
- Total funding mesin sama dengan hitungan terpisah, pada periode arsip (sampai posisi
  terlikuidasi) dan periode OKX.
- Equity akhir portofolio spot sama dengan penjumlahan log transaksi.
- 17 eksekusi stop/take-profit cocok dengan harga mentah.
- `tests/test_portfolio.py` memeriksa funding, gas, price impact, batas order, likuidasi, dan
  stop dengan angka hitungan tangan.

## Keterbatasan

- Likuidasi memakai high/low harga transaksi, bukan *mark price*; hanya margin tier 1.
- Harga acuan funding = harga terakhir yang diketahui. Pada bar harian, funding pukul 08:00
  dan 16:00 memakai harga buka hari itu.
- Gas, spread, dan slippage dianggap tetap sepanjang waktu.
- Price impact memakai rumus constant-product; pool Uniswap v3 dan Orca berbeda.
- Tidak ada jeda antara tutup bar dan eksekusi pada pasar 24/7.
- Kas menganggur tidak berbunga; USDT dan USDC dianggap sama dengan USD.
