# algo-trading-starter

Template awal untuk riset dan backtest algoritma trading: saham IDX, crypto, dan forex
(data dari Yahoo Finance).

> ⚠️ Untuk belajar & riset. Hasil backtest bukan jaminan hasil nyata. Bukan nasihat keuangan.

## 1. Persiapan (sekali saja)

Butuh Python 3.10+ dan [uv](https://docs.astral.sh/uv/) (disarankan).

```bash
# Install uv
# macOS/Linux:
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell):
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Masuk folder proyek & install dependensi
cd algo-trading-starter
uv sync --extra dev

# Simpan ke git
git init && git add . && git commit -m "Template awal"
```

Tanpa uv: `python -m venv .venv`, aktifkan, lalu `pip install -e ".[dev]"`.

## 2. Coba jalankan

```bash
uv run pytest -q                                          # semua tes harus lulus
uv run python -m algotrade.cli backtest --synthetic       # tes offline
uv run python -m algotrade.cli backtest                   # BBCA.JK (lihat config)
uv run python -m algotrade.cli backtest --ticker BTC-USD
uv run python -m algotrade.cli backtest --ticker TLKM.JK --strategy rsi_meanrev
uv run python -m algotrade.cli walkforward                # hasil out-of-sample
uv run python -m algotrade.cli compare                    # banyak ticker -> reports/compare.csv
uv run python -m algotrade.cli compare --tickers BBCA.JK "^JKSE" --strategy rsi_meanrev
```

Grafik tersimpan di `reports/`. Atur ticker, parameter, dan biaya di `config/default.yaml`.

## 3. Cara membaca hasil

| Metrik | Arti | Patokan kasar (harian) |
|---|---|---|
| sharpe | return per unit risiko | < 0.5 lemah, 0.5–1 lumayan, > 2 curigai bug |
| max_drawdown | penurunan terdalam dari puncak | sanggupkah Anda menahannya? |
| cagr | pertumbuhan tahunan | bandingkan dengan Buy & Hold |
| exposure | % waktu memegang posisi | |
| n_trades | jumlah perubahan posisi | makin banyak, makin besar biaya |

Buy & Hold juga membayar biaya beli dan baru mulai setelah masa pemanasan indikator, jadi
strategi dan pembandingnya dinilai pada tanggal yang sama. Strategi baru yang memakai
indikator perlu mengisi properti `warmup`.

Yang dipercaya adalah angka **walk-forward out-of-sample**, bukan backtest biasa.

## 4. Alur kerja dengan Claude Code

```bash
cd algo-trading-starter
claude
```

Claude Code otomatis membaca `CLAUDE.md` (aturan proyek). Contoh prompt ada di `PROMPTS.md`.

## Struktur

```
config/default.yaml        konfigurasi
src/algotrade/
  data.py                  data + cache
  strategies/              strategi (tambah di sini)
  backtest.py              mesin backtest + biaya
  walkforward.py           optimasi out-of-sample
  metrics.py, report.py    metrik & grafik
  cli.py                   perintah terminal
tests/                     tes (termasuk deteksi look-ahead)
```
