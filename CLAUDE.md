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
- Status sekarang: Fase 0, 1, dan 2 selesai. Fase 3 sebagian (pencatat, DSR, PBO); fitur,
  label, dan purged CV belum.

## Repo ini PUBLIK
Semua yang di-commit bisa dilihat siapa pun, selamanya.
- **Jangan pernah commit:** file `.env`, API key/secret/passphrase, token, private key, seed
  phrase, **alamat wallet pribadi**, atau **data akun** (saldo, posisi, riwayat order, ID akun,
  email, tangkapan layar akun). Data pasar dan laporan juga tidak di-commit.
- Alamat kontrak/pool **publik** di config boleh.
- **Kunci hanya dibaca dari environment variable** (`os.environ`). Tidak dari kode, file config,
  argumen perintah, atau log. Jangan mencetak nilainya.
- Claude Code tidak membuka `.env` atau file kunci/wallet. `.env.example` hanya berisi nama
  variabel tanpa nilai.
- Pre-commit hook harus aktif (`uv run pre-commit install`). **Jangan memakai
  `git commit --no-verify`.** Komentar `pragma: allowlist secret` hanya untuk salah deteksi
  yang sudah diperiksa dan disetujui pemilik proyek.
- Kalau rahasia terlanjur ter-commit atau ter-push: beri tahu pemilik proyek dan **ganti
  kuncinya**. Menghapus dari riwayat saja tidak cukup.

## Perintah
- Install: `uv sync --extra dev` (atau `pip install -e ".[dev]"`)
- Tes: `uv run pytest -q`
- Aktifkan hook (sekali per komputer): `uv run pre-commit install`
- Periksa rahasia: `uv run python scripts/check_secrets.py --all` (atau `--history`)
- Lint: `uv run ruff check . --fix`
- Backtest: `uv run algotrade backtest [--symbol X] [--market M] [--strategy Y]`
- Walk-forward: `uv run algotrade walkforward [--symbol X]`
- Banding banyak simbol: `uv run algotrade compare [--market M] [--symbols A B]`
- Offline: tambahkan `--synthetic`
- Riset: `uv run algotrade research validate [--case N]`, `... research trials`
- Portofolio: `uv run algotrade portfolio [--symbols A B] [--leverage N]`
- Data multi-pasar: `uv run algotrade data update [--market M] [--full]`, `... data quality`

## Struktur
- `src/algotrade/instruments.py` — model `Instrument` + pembaca `config/instruments.yaml`
- `src/algotrade/data/`         — adapter (`cex`, `equity`, `dex`, `archive`), `store`
  (Parquet + DuckDB), `resample`, `quality`, `update`
- `src/algotrade/data_cli.py`   — perintah `data update` / `data quality`
- `src/algotrade/strategies/`   — satu file per strategi, daftar di `strategies/__init__.py`
- `src/algotrade/backtest.py`   — backtester vektor (shift 1 bar + biaya)
- `src/algotrade/compare.py`    — tabel strategi vs Buy & Hold untuk banyak ticker
- `src/algotrade/walkforward.py`— optimasi parameter train/test bergulir
- `src/algotrade/metrics.py`    — Sharpe, CAGR, drawdown, dll.
- `src/algotrade/engine/`       — mesin portofolio, funding, pemuat data, biaya, likuiditas
- `src/algotrade/research/`     — pencatat percobaan (otomatis), DSR, PBO, validasi
- `config/research.yaml`        — kasus uji & ambang (pra-registrasi); `docs/research.md`
- `docs/backtest.md`            — aturan eksekusi, funding, DEX, dan keterbatasan
- `docs/research_log.md`        — catat setiap strategi yang diuji, termasuk yang gagal
- `config/default.yaml`         — instrumen & parameter backtest satu aset
- `config/backtest.yaml`        — pengaturan portofolio & DEX
- `config/instruments.yaml`     — pasar, exchange, simbol, timeframe, dan SEMUA biaya
- `docs/data.md`                — sumber data, batasannya, dan penjadwalan

## Referensi (baca saja, jangan diubah, jangan menyalin kode mentah)
- `..\referensi\machine-learning-for-trading` — buku *Machine Learning for Trading* (ML4T)
  edisi 3, lisensi MIT. Acuan metodologi: data (bab 02), walk-forward, backtest (bab 16),
  biaya transaksi (bab 18), risiko (bab 19), live trading (bab 25), studi kasus
  `case_studies/crypto_perps_funding`.
- `..\referensi\awesome-quant` — daftar library & sumber data quant.
- FinceptTerminal — hanya ide tampilan dashboard. Lisensinya AGPL: **dilarang menyalin kode**.

## Aturan riset
- Ambang dan grid di-commit **sebelum** hasil dilihat; jangan diubah sesudahnya.
- Jangan menghindari atau menghapus pencatat percobaan (`data/experiments.duckdb`).

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
   - Ikuti bagian "Repo ini PUBLIK": kunci hanya dari environment variable.
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
