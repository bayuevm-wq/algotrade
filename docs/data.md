# Data multi-pasar

## Perintah

```bash
uv run algotrade data update                  # unduh yang baru, lalu laporan kualitas
uv run algotrade data update --market dex     # satu pasar: cex, us_equity, dex, idx
uv run algotrade data update --full           # unduh ulang dari awal
uv run algotrade data quality                 # laporan saja, tanpa internet
```

Update pertama sekitar 10 menit; berikutnya sekitar 1 menit. Perintah berakhir dengan kode
error bila ada unduhan gagal atau dataset berstatus GAGAL.

Exchange, simbol, pool, dan timeframe diatur di [`config/instruments.yaml`](../config/instruments.yaml).

## Sumber

| Data | Sumber | Batas |
|---|---|---|
| Crypto OHLCV | OKX lewat ccxt | spot sejak 2019, perpetual sejak Des 2019 |
| Funding rate | OKX | hanya sekitar 3 bulan; terkumpul lewat update harian |
| Funding rate (riwayat) | arsip publik Binance (`data.binance.vision`) | sejak 2020, bulan berjalan belum ada |
| Saham US / IDX | yfinance | harga disesuaikan; seluruh riwayat diunduh ulang tiap update |
| DEX OHLCV & likuiditas | GeckoTerminal | riwayat 180 hari; likuiditas hanya potret saat update |

Funding OKX dan Binance **tidak sama**. Pada periode tumpang tindih saat pemeriksaan pertama
(199 titik), korelasinya hanya 0,59 (BTC) dan 0,68 (ETH). Keduanya disimpan terpisah; jangan
disambung tanpa alasan.

**Akses dari jaringan tertentu.** Sebagian operator memblokir `www.okx.com` dan mengalihkannya ke
halaman blokir; gejalanya `NetworkError` karena sertifikat tidak cocok. Jangan mematikan
pemeriksaan sertifikat. Data lama tidak rusak; update berikutnya dari jaringan yang bisa
mengakses OKX akan menyusul yang terlewat (funding OKX hanya tersedia sekitar 3 bulan).

## Exchange cadangan

Bila OHLCV OKX **tidak bisa dihubungi** (gangguan jaringan atau diblokir), `data update`
otomatis mengambil data spot dari **Indodax** (`sources.cex.fallback` di config).

- Disimpan di `data/market/cex/indodax/...`. **Tidak pernah disambung** dengan data OKX, dan
  data OKX tidak diubah.
- Hanya BTC/USDT dan ETH/USDT spot sejak 2021. Perpetual dan funding OKX **tidak tercakup**;
  keduanya menyusul saat OKX bisa diakses (funding OKX hanya tersedia sekitar 3 bulan).
- Backtest tidak pernah beralih sendiri. Pakai `--source indodax` bila memang diinginkan.
  `walkforward` dan `compare` juga menerima opsi itu; `portfolio` belum.
- `data quality` hanya memeriksa sumber utama; cadangan diperiksa saat dipakai oleh update.

**Mutunya jauh di bawah OKX.** Perbandingan harga tutup pada 28 Nov 2026 (2021 - sekarang):

| Pasangan | Selisih median / persentil 99 / maks | Bar bervolume nol |
|---|---|---|
| BTC/USDT 1h | 0,32% / 1,97% / 6,8% | 21% |
| ETH/USDT 1h | 0,46% / 3,78% / 43,3% | 36% |
| BTC/USDT 1d | 0,35% / 2,05% / 5,5% | 0,1% |
| ETH/USDT 1d | 0,49% / 3,88% / 11,3% | 0,2% |

Pakai data harian saja untuk riset, dan jangan menganggap hasilnya setara dengan OKX.

**Kode keluar `data update`:**

| Kode | Arti |
|---|---|
| 0 | semua beres |
| 2 | OKX tidak bisa diakses, cadangan berhasil, tidak ada masalah lain |
| 1 | selain itu (unduhan gagal, data GAGAL, atau cadangan juga gagal) |

## Penyimpanan

```
data/market/<pasar>/<sumber>/<simbol>/ohlcv_1h.parquet | funding.parquet | liquidity.parquet
data/market.duckdb       view: ohlcv, funding, liquidity + tabel instruments
data/logs/               log update terjadwal (30 hari)
reports/data_quality.csv laporan terakhir
```

Semuanya diabaikan git.

- `ts` = waktu **buka** bar dalam UTC. Bar harian saham diberi tanggal sesi pada 00:00 UTC,
  padahal bursa NYSE baru tutup sekitar 20:00-21:00 UTC. Perhatikan ini saat menggabungkan
  saham dengan crypto agar tidak look-ahead.
- Bar yang belum selesai tidak disimpan.
- 4h dan 1d untuk crypto/DEX dibuat dari 1h; kolom `n_bars` menunjukkan jumlah jam di dalamnya.
- Untuk perpetual, `lot_size` dihitung dalam **kontrak** (lihat `contract_size`).

Contoh kueri:

```python
import duckdb
con = duckdb.connect("data/market.duckdb", read_only=True)
con.execute("SET TimeZone='UTC'")
print(con.sql("SELECT symbol, count(*), max(ts) FROM ohlcv GROUP BY symbol").df())
```

## Status kualitas

- **GAGAL:** data kosong, ganda, urutan salah, waktu di masa depan, bar belum selesai, harga
  mustahil (`high < low`, harga <= 0), volume negatif, atau basi.
- **PERINGATAN:** celah waktu, lonjakan ekstrem, volume nol, riwayat mulai terlambat,
  likuiditas rendah. Data tidak pernah diubah atau dihapus otomatis.

Batasnya per pasar di bagian `quality` pada config. Bar rusak yang sudah diperiksa bisa
didaftarkan di `quality_exceptions` (simbol, tanggal, jenis cek, alasan). Hanya cek high/low
yang boleh dikecualikan. Kalender intraday saham belum diperiksa.

## Peringatan pada pemeriksaan pertama (26 Nov 2026)

| Peringatan | Penjelasan |
|---|---|
| Lonjakan crypto OKX | Semua bar yang ditandai bergerak **searah** dengan Binance spot pada waktu yang sama. Selisih harian maks 1,8%; per jam maks 3,4% (crash 12-13 Mar 2020). Perpetual dibandingkan dengan spot. Gerakan pasar nyata, bukan data rusak. |
| Volume nol OKX | Harga diam (`high = low`) di semua kasus; 9 jam pada 18 Des 2022. Kemungkinan exchange tidak memperdagangkan (belum diverifikasi). Backtest tidak boleh menganggap order terisi di jam ini. |
| Perpetual mulai Des 2019 | OKX tidak memberi data lebih awal. |
| Lonjakan saham (NVDA, META, TSLA, AVGO, UNH) | Volume 1,2x-8,7x median 20 hari. NVDA 23 Nov 2026 tidak tampak seperti artefak split/dividen (Close = Adj Close). **Belum dicocokkan dengan sumber kedua.** |
| Lonjakan DEX 19 Agu 2026 | +17,5% di dua pool ETH; OKX ETH/USDT mencatat harga yang hampir sama pada hari itu. |
| Celah DEX Base 25 Jun 2026 16:00 | Satu jam tanpa bar dari API; penyebab belum diketahui. |

Selisih harga per jam pool ETH terhadap OKX: median 0,08%, persentil 99 sekitar 0,32%, maksimum
1,8% (Ethereum) dan 5,1% (Base). Harga ekstrem sesaat di pool tidak selalu bisa dieksekusi.

## Keterbatasan

- Daftar saham dipilih dari perusahaan besar hari ini (**survivorship bias**).
- Biaya yang masih tebakan bertanda PERLU DICEK di config.
- `backtest`, `walkforward`, dan `compare` membaca data Parquet ini; dataset GAGAL ditolak.
- BBRI.JK dan TLKM.JK: pada 20 Apr 2016 Yahoo memberi harga buka di luar rentang high-low.
  Terdaftar di `quality_exceptions` sehingga menjadi PERINGATAN.

## Update otomatis harian (Windows Task Scheduler)

Skrip: [`scripts/data_update.ps1`](../scripts/data_update.ps1), diluncurkan oleh
[`scripts/run_hidden.pyw`](../scripts/run_hidden.pyw) agar tidak membuka jendela **dan** kode
errornya sampai ke Task Scheduler. Jalankan perintah di bawah ini sendiri di PowerShell,
**dari folder proyek**, setelah `uv sync --extra dev`.

Uji dulu secara manual:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\data_update.ps1
```

Pasang tugas harian pukul 07:30 (waktu komputer):

```powershell
$python   = (Resolve-Path .\.venv\Scripts\pythonw.exe).Path
$launcher = (Resolve-Path .\scripts\run_hidden.pyw).Path
$action   = New-ScheduledTaskAction -Execute $python -Argument "`"$launcher`"" `
            -WorkingDirectory (Get-Location).Path
$trigger  = New-ScheduledTaskTrigger -Daily -At 07:30
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "algotrade-data-update" -Action $action `
            -Trigger $trigger -Settings $settings
```

Jangan memakai `conhost.exe --headless` (kode error hilang, tugas selalu terlihat sukses) atau
`-WindowStyle Hidden` (jendela tetap muncul).

Cek, jalankan sekarang, lihat log, atau hapus:

```powershell
Start-ScheduledTask    -TaskName "algotrade-data-update"
Get-ScheduledTaskInfo  -TaskName "algotrade-data-update"   # LastTaskResult 0 = sukses
Get-Content ".\data\logs\data_update_$(Get-Date -Format yyyy-MM-dd).log" -Tail 20
Unregister-ScheduledTask -TaskName "algotrade-data-update" -Confirm:$false
```

Catatan:
- Tugas berjalan hanya saat Anda login. Bila komputer mati pada jadwalnya, tugas dijalankan
  saat komputer menyala lagi (`-StartWhenAvailable`).
- Komputer yang mati beberapa hari tidak masalah untuk DEX selama di bawah 180 hari. Riwayat
  likuiditas pada hari yang terlewat tidak bisa diambil kembali.
- Bila folder proyek dipindah, hapus tugasnya lalu pasang ulang.
