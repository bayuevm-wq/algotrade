# CLAUDE.md — aturan proyek untuk Claude Code

Sistem riset → paper trading → live (Python) untuk **crypto (CEX), saham US, dan DEX**.
Pasar lain (IDX, forex) ditambah sebagai adapter. Pemilik proyek masih belajar:
jelaskan perubahan dengan bahasa Indonesia yang sederhana.

## Roadmap & cara kerja
- `ROADMAP.md` adalah acuan utama: visi, prioritas pasar, fase, dan kriteria "Selesai jika".
- Prioritas pasar: crypto CEX → saham US → DEX (DEX mulai dari analisis & simulasi).
- Kerjakan satu fase pada satu waktu. Mulai dengan rencana singkat (file yang dibuat/diubah,
  urutan kerja) dan **tunggu persetujuan**.
- Satu fase selesai = kriteria "Selesai jika" terpenuhi + tes lulus + hasil dilaporkan +
  commit + push + checklist di `ROADMAP.md` diperbarui. Baru lanjut.
- Status sekarang: Fase 0 selesai. Kode masih satu sumber data (yfinance) dan satu aset.

## Perintah
- Install: `uv sync --extra dev` (atau `pip install -e ".[dev]"`)
- Tes: `uv run pytest -q`
- Lint: `uv run ruff check . --fix`
- Backtest: `uv run python -m algotrade.cli backtest [--ticker X] [--strategy Y]`
- Walk-forward: `uv run python -m algotrade.cli walkforward`
- Banding banyak ticker: `uv run python -m algotrade.cli compare [--tickers A B] [--strategy Y]`
- Offline: tambahkan `--synthetic`

## Struktur
- `src/algotrade/data.py`       — ambil data (yfinance) + cache CSV di `data/`
- `src/algotrade/strategies/`   — satu file per strategi, daftar di `strategies/__init__.py`
- `src/algotrade/backtest.py`   — backtester vektor (shift 1 bar + biaya)
- `src/algotrade/compare.py`    — tabel strategi vs Buy & Hold untuk banyak ticker
- `src/algotrade/walkforward.py`— optimasi parameter train/test bergulir
- `src/algotrade/metrics.py`    — Sharpe, CAGR, drawdown, dll.
- `config/default.yaml`         — ticker, parameter, biaya

## Referensi (baca saja, jangan diubah, jangan menyalin kode mentah)
- `..\referensi\machine-learning-for-trading` — buku *Machine Learning for Trading* (ML4T)
  edisi 3, lisensi MIT. Acuan metodologi: data (bab 02), walk-forward, backtest (bab 16),
  biaya transaksi (bab 18), risiko (bab 19), live trading (bab 25), studi kasus
  `case_studies/crypto_perps_funding`.
- `..\referensi\awesome-quant` — daftar library & sumber data quant.
- FinceptTerminal — hanya ide tampilan dashboard. Lisensinya AGPL: **dilarang menyalin kode**.

## Aturan WAJIB (jangan dilanggar)
1. **Tidak boleh look-ahead.** Sinyal di bar t hanya memakai data ≤ t. Dilarang `shift(-n)`,
   `center=True` pada rolling, atau normalisasi memakai statistik seluruh dataset.
   Strategi TIDAK melakukan shift sendiri — backtester yang menggeser 1 bar.
   Pengecualian: label untuk riset ML (forward return, triple-barrier) boleh melihat ke depan,
   tetapi hanya sebagai target, tidak pernah sebagai fitur atau sinyal.
2. **Setiap strategi baru** wajib: subclass `Strategy`, isi `warmup`, didaftarkan di
   `STRATEGIES`, dan otomatis ikut `test_no_lookahead`. Jalankan `pytest` setelah perubahan.
3. **Biaya transaksi selalu aktif** dalam hasil yang dilaporkan, sesuai pasarnya: fee
   maker/taker + slippage + funding (CEX), spread (saham US), swap fee + gas + price impact +
   buffer MEV (DEX). Jangan menyetel biaya = 0 kecuali di tes.
4. **Laporkan out-of-sample.** Kalau parameter dioptimasi, hasil yang dilaporkan adalah
   walk-forward OOS, bukan hasil in-sample. Sebutkan jumlah kombinasi parameter yang dicoba.
5. **Bandingkan dengan benchmark pasarnya** setiap kali melaporkan hasil: BTC buy & hold
   (crypto), SPY (saham US), atau buy & hold aset itu sendiri. Benchmark kena biaya dan
   dinilai pada tanggal yang sama. Strategi lolos hanya jika mengalahkannya secara
   out-of-sample setelah biaya; yang gagal dicatat di `docs/research_log.md`.
6. **Parameter pasar di config** (fee, gas, funding, jam bursa), bukan di-hardcode.
7. **Keamanan kunci:**
   - Jangan pernah menaruh API key di kode; pakai `.env` (sudah di .gitignore).
   - API key CEX: tanpa izin withdraw, IP whitelist aktif.
   - Seed phrase / private key wallet **tidak pernah** ditulis di kode atau di chat, dan
     **tidak boleh dibaca Claude Code**. Jangan membuka file yang berisinya. Wallet DEX
     harus wallet khusus bot dengan dana kecil.
8. **Jangan menulis kode order live** tanpa diminta eksplisit. Urutannya:
   backtest → walk-forward → paper trading/testnet (**minimal 3 bulan**) → live kecil.
   Tidak ada uang sungguhan sebelum itu. Mode live harus default OFF.
9. Hasil backtest yang terlalu bagus (Sharpe > 2 di data harian) dianggap BUG sampai terbukti
   tidak — cari look-ahead atau biaya yang hilang dulu.

## Gaya kode
- Python 3.10+, type hints, fungsi kecil, docstring singkat bahasa Indonesia.
- pandas/numpy vektor bila memungkinkan; loop boleh untuk logika berstatus (mis. stop-loss).
- Tambah tes di `tests/` untuk setiap logika baru. Tes tidak boleh butuh internet.
- Repo ini publik: jangan commit data, laporan, atau informasi pribadi.
