# ROADMAP — algotrade (multi-pasar)

## Visi

**Satu sistem riset → paper trading → live untuk crypto (CEX), saham US, dan DEX**,
dengan satu mesin backtest, satu lab riset, dan satu dashboard. Pasar lain (IDX, forex)
bisa ditambah sebagai adapter.

Apa yang kita ambil dari 3 repo referensi:

| Repo | Yang kita ambil | Yang tidak kita tiru |
|---|---|---|
| machine-learning-for-trading (ML4T) | Metodologi: walk-forward, biaya, risiko, anti-overfitting, ML; studi kasus crypto perps (funding rate) & saham US | Cakupan terlalu luas, data berbayar |
| awesome-quant | Pilihan library: ccxt (CEX), sumber data, backtest, optimasi portofolio | — (hanya daftar) |
| FinceptTerminal | Ide UX: satu dashboard semua pasar | Aplikasi C++ berat, fitur inti berbayar, lisensi AGPL |

**Keunggulan kita:** satu kerangka yang memodelkan **biaya nyata tiap pasar** dengan benar —
fee maker/taker + funding (CEX), spread (saham US), swap fee + gas + price impact + MEV (DEX).
Kebanyakan bot di internet mengabaikan ini, terutama di DEX, sehingga backtest-nya menipu.

## Prioritas pasar

1. **Crypto CEX** dulu — data gratis, 24/7, API & testnet tersedia lewat ccxt.
2. **Saham US** — data gratis, paper trading gratis (mis. Alpaca).
3. **DEX** terakhir — paling berisiko (rug pull, honeypot, MEV, likuiditas tipis,
   transaksi tidak bisa dibatalkan). Dimulai dari analisis & simulasi, bukan eksekusi.

## Aturan main (semua fase)

1. Satu fase selesai = tes lulus + hasil dilaporkan + commit + push. Baru lanjut.
2. Strategi harus mengalahkan **benchmark pasarnya** (BTC buy & hold, SPY, dsb.)
   secara **out-of-sample setelah biaya**. Yang gagal dicatat di `docs/research_log.md`.
3. Parameter pasar (fee, gas, funding, jam bursa) di config, bukan di-hardcode.
4. **Keamanan kunci:**
   - API key CEX: tanpa izin withdraw, aktifkan IP whitelist, simpan di `.env`.
   - Wallet DEX: wallet KHUSUS bot dengan dana kecil. Seed phrase/private key
     **tidak pernah** ditulis di kode, di chat, atau dibaca Claude Code.
5. Tidak ada uang sungguhan sebelum paper trading/testnet berjalan minimal 3 bulan.

Perkiraan waktu (paruh waktu): **4–5 bulan** sampai paper trading semua pasar.

---

## Fase 1 — Arsitektur multi-pasar & data (± 2–3 minggu)

**Tujuan:** satu cara seragam mengambil & menyimpan data dari pasar mana pun.

- Model `Instrument`: simbol, pasar (cex/us_equity/dex/idx), mata uang quote, jam bursa
  (24/7 vs NYSE), periods_per_year, tick/lot minimum, model biaya.
- Adapter data (satu interface `fetch_ohlcv`):
  - CEX → ccxt (Binance, Bybit, OKX, Indodax, dsb.), termasuk funding rate untuk perpetual.
  - Saham US → yfinance (awal), opsi Alpaca/Polygon nanti.
  - DEX → API publik (mis. GeckoTerminal/DexScreener) untuk OHLCV pool + data likuiditas pool.
  - IDX → yfinance `.JK` (sudah ada, jadi adapter opsional).
- Penyimpanan Parquet + DuckDB, update incremental, cek kualitas data (gap, outlier, volume nol).
- Waktu disimpan UTC; resampling ke timeframe yang diminta (1h, 4h, 1d).

**Referensi:** ML4T `02_financial_data_universe`; awesome-quant *Market Data* & *Trading*.
**Selesai jika:** `algotrade data update` mengambil BTC/ETH (CEX), 20 saham US + SPY,
dan 3 pool DEX likuid, lalu laporan kualitas data bersih.

## Fase 2 — Mesin backtest multi-aset realistis (± 3 minggu)

**Tujuan:** hasil backtest mendekati hasil eksekusi nyata di tiap pasar.

- Backtest portofolio lintas aset dengan modal bersama (base currency USD/USDT).
- Model biaya per pasar:
  - CEX spot: fee maker/taker + slippage. Perpetual: + funding rate tiap 8 jam, leverage,
    harga likuidasi.
  - Saham US: komisi (sering 0) + spread + jam bursa (tidak ada trading akhir pekan).
  - DEX: swap fee pool + gas + **price impact dari likuiditas pool** + buffer MEV/slippage.
- Mode event-driven untuk stop-loss/take-profit intrabar.
- Log transaksi + tear sheet (equity, drawdown, return bulanan, turnover, biaya per pasar).

**Referensi:** ML4T `16_strategy_simulation`, `18_transaction_costs`, case study `crypto_perps_funding`.
**Selesai jika:** buy & hold BTC dan SPY bisa direplikasi; tes membuktikan biaya funding,
gas, dan price impact terhitung benar.

## Fase 3 — Lab riset anti-overfitting (± 2 minggu)

**Tujuan:** membedakan edge nyata dari kebetulan.

- Library fitur: momentum, volatilitas, volume, funding rate, korelasi ke BTC/SPY,
  likuiditas pool (DEX).
- Label: forward return & triple-barrier.
- Purged walk-forward CV; Deflated Sharpe Ratio; Probability of Backtest Overfitting;
  jumlah percobaan dicatat otomatis.
- Pencatat eksperimen (DuckDB): setiap percobaan tersimpan, termasuk yang gagal.

**Referensi:** ML4T `07`, `08`, `11`.
**Selesai jika:** laporan riset otomatis per strategi berisi metrik OOS + uji overfitting.

## Fase 4 — Strategi & portofolio (± 4 minggu)

Dari sederhana ke kompleks, per pasar:

- **Crypto CEX:** trend following (multi-timeframe), momentum cross-sectional top-20 koin,
  funding-rate carry (long spot + short perp saat funding positif).
- **Saham US:** rotasi ETF/sektor berbasis momentum, momentum cross-sectional saham besar,
  filter tren SPY.
- **DEX:** fokus pasangan likuid (mis. ETH/USDC, SOL/USDC). Analisis selisih harga CEX-DEX
  sebagai riset dulu. Token baru/meme = spekulasi, bukan strategi; minimal wajib filter
  keamanan token (likuiditas, umur pool, holder, kontrak terverifikasi).
- **ML:** LightGBM untuk ranking aset (setelah baseline aturan lolos).
- **Portofolio:** alokasi lintas pasar (inverse volatility/risk parity), batas per aset,
  target volatilitas, kill switch drawdown, korelasi crypto-saham saat krisis.

**Referensi:** ML4T `12`, `17`, `19`, `20`; awesome-quant *Portfolio Optimization*.
**Selesai jika:** minimal satu strategi per pasar prioritas lolos aturan main.

## Fase 5 — Dashboard (± 1–2 minggu)

- Streamlit (`uv run streamlit run app.py`).
- Halaman: Ringkasan pasar (BTC, SPY, dominasi, funding) · Sinyal hari ini · Perbandingan
  strategi · Portofolio & risiko lintas pasar · Kualitas data · Status bot.

**Referensi:** FinceptTerminal (ide tampilan saja, tanpa menyalin kode).

## Fase 6 — Paper trading / testnet (minimal 3 bulan)

- Crypto: testnet exchange lewat ccxt (atau paper trading internal).
- Saham US: akun paper (mis. Alpaca paper).
- DEX: mode "dry-run" — ambil quote nyata dari aggregator, catat apa yang AKAN terjadi,
  tanpa mengirim transaksi.
- Scheduler (crypto per jam/hari, US setelah bursa tutup), notifikasi Telegram,
  monitoring paper vs ekspektasi backtest, aturan pause/retrain/pensiun strategi.

**Referensi:** ML4T `25_live_trading`, `26_mlops_governance`.
**Selesai jika:** 3 bulan berjalan dan performa dalam rentang ekspektasi.

## Fase 7 — Live dengan modal kecil (opsional)

Urutan: **CEX → saham US → DEX**.
- Mode live default OFF, butuh flag eksplisit + konfirmasi.
- Batas kerugian harian, ukuran order maksimum, kill switch manual & otomatis.
- DEX: wallet khusus, batas approve token (jangan unlimited), simulasi transaksi sebelum kirim,
  proteksi slippage/MEV (private RPC).

---

## Cara pakai dengan Claude Code

```
Baca ROADMAP.md dan CLAUDE.md. Kerjakan Fase <N>.
Mulai dengan rencana singkat (file yang dibuat/diubah, urutan kerja) dan tunggu persetujuan saya.
Setelah disetujui: kerjakan sampai kriteria "Selesai jika" terpenuhi, tambah tes,
jalankan pytest, commit, push, beri ringkasan bahasa Indonesia, dan update checklist.
Gunakan ..\referensi sebagai acuan metodologi, jangan menyalin kode mentah.
```

## Checklist progres

- [x] Fase 0 — Template awal (backtest satu ticker, walk-forward, tes look-ahead, compare)
- [x] Fase 1 — Arsitektur multi-pasar & data
- [x] Fase 2 — Backtest multi-aset realistis
- [ ] Fase 3 — Lab riset anti-overfitting
- [ ] Fase 4 — Strategi & portofolio
- [ ] Fase 5 — Dashboard
- [ ] Fase 6 — Paper trading / testnet (3 bulan)
- [ ] Fase 7 — Live modal kecil (opsional)
