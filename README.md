# algotrade

Satu sistem **riset → paper trading → live** untuk **crypto (CEX), saham US, dan DEX**, dengan
satu mesin backtest, satu lab riset, dan satu dashboard. Pasar lain (IDX, forex) bisa ditambah
sebagai adapter.

Fokus utamanya: memodelkan **biaya nyata tiap pasar** dengan benar, karena backtest yang
mengabaikan biaya (terutama di DEX) menipu.

> ## ⚠️ Disclaimer
> **Proyek ini untuk belajar dan riset. Bukan nasihat keuangan atau investasi**, dan bukan
> ajakan membeli atau menjual aset apa pun. Hasil backtest tidak menjamin hasil di masa depan.
> Trading crypto, saham, dan terutama DEX bisa menghabiskan seluruh modal. Semua keputusan dan
> risikonya ada pada pengguna. Data pihak ketiga bisa salah atau tidak lengkap.
> Belum ada fitur order live.

## Status

Rencana lengkap ada di [`ROADMAP.md`](ROADMAP.md).

| Fase | Isi | Status |
|---|---|---|
| 0 | Backtest satu aset, walk-forward, tes look-ahead, compare | ✅ selesai |
| 1 | Arsitektur multi-pasar & data | ✅ selesai |
| 2 | Backtest multi-aset dengan biaya per pasar | belum |
| 3 | Lab riset anti-overfitting | belum |
| 4 | Strategi & portofolio | belum |
| 5 | Dashboard | belum |
| 6 | Paper trading / testnet (minimal 3 bulan) | belum |
| 7 | Live modal kecil (opsional) | belum |

**Yang bisa dipakai sekarang:**

- Data crypto (OKX), saham US, dan DEX tersimpan di Parquet + DuckDB, dengan laporan kualitas.
  Lihat [`docs/data.md`](docs/data.md), termasuk cara update otomatis harian di Windows.
- Backtest satu aset dengan dua strategi (`sma_cross`, `rsi_meanrev`) dan satu model biaya
  persentase. Bagian ini **masih** memakai data harian yfinance dan config bawaan saham IDX;
  disambungkan ke data multi-pasar di Fase 2.

## 1. Persiapan (sekali saja)

Butuh Python 3.10+ dan [uv](https://docs.astral.sh/uv/) (disarankan).

```bash
# Install uv
# macOS/Linux:
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell):
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Ambil kode & install dependensi
git clone https://github.com/bayuevm-wq/algotrade.git
cd algotrade
uv sync --extra dev
```

Tanpa uv: `python -m venv .venv`, aktifkan, lalu `pip install -e ".[dev]"`.

**Wajib bila Anda akan commit:** aktifkan pemeriksa rahasia (sekali per komputer).

```bash
uv run pre-commit install
```

## 2. Coba jalankan

```bash
uv run pytest -q                                          # semua tes harus lulus
uv run python -m algotrade.cli backtest --synthetic       # tes offline
uv run python -m algotrade.cli backtest                   # ticker di config
uv run python -m algotrade.cli backtest --ticker BTC-USD
uv run python -m algotrade.cli backtest --ticker SPY --strategy rsi_meanrev
uv run python -m algotrade.cli walkforward                # hasil out-of-sample
uv run python -m algotrade.cli compare                    # banyak ticker -> reports/compare.csv
uv run python -m algotrade.cli compare --tickers BTC-USD SPY --strategy rsi_meanrev
```

Grafik tersimpan di `reports/`. Atur ticker, parameter, dan biaya di `config/default.yaml`.
Biaya dan `periods_per_year` bawaan disetel untuk saham IDX, jadi sesuaikan dulu sebelum
membaca hasil pasar lain.

### Data multi-pasar

```bash
uv run algotrade data update      # unduh & cek semua pasar (pertama kali sekitar 10 menit)
uv run algotrade data quality     # laporan kualitas saja
```

Exchange, simbol, dan timeframe diatur di `config/instruments.yaml`.

## 3. Cara membaca hasil

| Metrik | Arti | Patokan kasar (harian) |
|---|---|---|
| sharpe | return per unit risiko | < 0.5 lemah, 0.5–1 lumayan, > 2 curigai bug |
| max_drawdown | penurunan terdalam dari puncak | sanggupkah Anda menahannya? |
| cagr | pertumbuhan tahunan | bandingkan dengan benchmark |
| exposure | % waktu memegang posisi | |
| n_trades | jumlah perubahan posisi | makin banyak, makin besar biaya |

Buy & Hold juga membayar biaya beli dan baru mulai setelah masa pemanasan indikator, jadi
strategi dan pembandingnya dinilai pada tanggal yang sama. Strategi baru yang memakai
indikator perlu mengisi properti `warmup`.

Yang dipercaya adalah angka **walk-forward out-of-sample**, bukan backtest biasa.

## 4. Keamanan

Repo ini **publik**.

- Kunci hanya dibaca dari **environment variable**. `.env` tidak pernah di-commit.
- API key exchange: tanpa izin withdraw, aktifkan IP whitelist.
- Jangan commit alamat wallet pribadi atau data akun.
- Pre-commit hook menolak commit berisi API key, private key, seed phrase, atau file `.env`,
  wallet, data, dan laporan. Periksa manual: `uv run python scripts/check_secrets.py --all`.
- Hook bukan jaminan. Ia tidak mengenali alamat wallet pribadi atau data akun, bisa dilewati
  dengan `--no-verify`, dan tidak aktif di clone yang belum menjalankan perintah pemasangan.
  Kunci yang bocor harus **diganti**.
- Wallet DEX: wallet khusus bot dengan dana kecil. Seed phrase dan private key tidak pernah
  ditulis di kode atau chat.
- Tidak ada uang sungguhan sebelum paper trading/testnet berjalan minimal 3 bulan.

## 5. Alur kerja dengan Claude Code

```bash
claude
```

Claude Code otomatis membaca `CLAUDE.md` (aturan proyek). Untuk mengerjakan satu fase, pakai
contoh prompt di bagian akhir [`ROADMAP.md`](ROADMAP.md). `PROMPTS.md` berisi roadmap lama dan
sudah digantikan.

## Struktur

```
config/default.yaml        konfigurasi backtest
config/instruments.yaml    pasar, exchange, simbol, timeframe
src/algotrade/
  instruments.py           model Instrument
  data/                    adapter, penyimpanan, resampling, kualitas, update
  strategies/              strategi (tambah di sini)
  backtest.py              mesin backtest + biaya
  compare.py               banyak ticker vs Buy & Hold
  walkforward.py           optimasi out-of-sample
  metrics.py, report.py    metrik & grafik
  cli.py, data_cli.py      perintah terminal
scripts/check_secrets.py   pemeriksa rahasia (pre-commit)
scripts/data_update.ps1    update data terjadwal (Windows)
docs/data.md               panduan data
tests/                     tes (termasuk deteksi look-ahead)
```
