# CLAUDE.md — aturan proyek untuk Claude Code

Proyek riset & backtest algoritma trading (Python). Pemilik proyek masih belajar:
jelaskan perubahan dengan bahasa Indonesia yang sederhana.

## Perintah
- Install: `uv sync --extra dev` (atau `pip install -e ".[dev]"`)
- Tes: `uv run pytest -q`
- Lint: `uv run ruff check . --fix`
- Backtest: `uv run python -m algotrade.cli backtest [--ticker X] [--strategy Y]`
- Walk-forward: `uv run python -m algotrade.cli walkforward`
- Offline: tambahkan `--synthetic`

## Struktur
- `src/algotrade/data.py`       — ambil data (yfinance) + cache CSV di `data/`
- `src/algotrade/strategies/`   — satu file per strategi, daftar di `strategies/__init__.py`
- `src/algotrade/backtest.py`   — backtester vektor (shift 1 bar + biaya)
- `src/algotrade/walkforward.py`— optimasi parameter train/test bergulir
- `src/algotrade/metrics.py`    — Sharpe, CAGR, drawdown, dll.
- `config/default.yaml`         — ticker, parameter, biaya

## Aturan WAJIB (jangan dilanggar)
1. **Tidak boleh look-ahead.** Sinyal di bar t hanya memakai data ≤ t. Dilarang `shift(-n)`,
   `center=True` pada rolling, atau normalisasi memakai statistik seluruh dataset.
   Strategi TIDAK melakukan shift sendiri — backtester yang menggeser 1 bar.
2. **Setiap strategi baru** wajib: subclass `Strategy`, didaftarkan di `STRATEGIES`,
   dan otomatis ikut `test_no_lookahead`. Jalankan `pytest` setelah perubahan.
3. **Biaya transaksi selalu aktif** dalam hasil yang dilaporkan. Jangan menyetel biaya = 0
   kecuali di tes.
4. **Laporkan out-of-sample.** Kalau parameter dioptimasi, hasil yang dilaporkan adalah
   walk-forward OOS, bukan hasil in-sample. Sebutkan jumlah kombinasi parameter yang dicoba.
5. **Bandingkan dengan Buy & Hold** setiap kali melaporkan hasil.
6. **Jangan pernah** menaruh API key di kode; pakai `.env` (sudah di .gitignore).
7. **Jangan menulis kode order live** tanpa diminta eksplisit. Urutannya:
   backtest → walk-forward → paper trading → live kecil. Mode live harus default OFF.
8. Hasil backtest yang terlalu bagus (Sharpe > 2 di data harian) dianggap BUG sampai terbukti
   tidak — cari look-ahead atau biaya yang hilang dulu.

## Gaya kode
- Python 3.10+, type hints, fungsi kecil, docstring singkat bahasa Indonesia.
- pandas/numpy vektor bila memungkinkan; loop boleh untuk logika berstatus (mis. stop-loss).
- Tambah tes di `tests/` untuk setiap logika baru.
