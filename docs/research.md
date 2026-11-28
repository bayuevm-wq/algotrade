# Riset anti-overfitting

> Hasil backtest bukan jaminan hasil nyata. Bukan nasihat keuangan.

## Perintah

```bash
uv run algotrade research trials                    # jumlah percobaan yang tercatat
uv run algotrade research fingerprint --case NAMA   # sidik jari data untuk kasus baru
uv run algotrade research validate --case NAMA      # DSR, PBO, walk-forward
```

## Tabel riset: fitur, label, purged CV

```bash
uv run algotrade research dataset --symbol BTC/USDT       # -> data/research/*.parquet
uv run algotrade research validate --all                  # laporan semua kasus
```

**Fitur** (hanya data yang sudah diketahui saat bar tutup): momentum, volatilitas, skor volume,
rata-rata funding (satu sumber saja, tidak disambung), korelasi bergulir dengan BTC dan SPY,
likuiditas pool (kosong sebelum riwayatnya ada).

**Label** (sengaja melihat ke depan, hanya untuk target):

- *forward return*: dari buka bar berikutnya sampai tutup bar ke-N;
- *triple-barrier*: +1 / -1 menurut batas yang tersentuh dulu (jarak = kelipatan volatilitas),
  atau tanda return saat waktu habis. Dua batas di bar yang sama = batas bawah.

**Purged walk-forward:** data latih selalu sebelum data uji; sampel latih yang labelnya baru
diketahui setelah periode uji dimulai dibuang, ditambah jeda (*embargo*).

Pengaturannya di bagian `dataset` pada `config/research.yaml`. Perintah ini **tidak** menilai
daya prediksi fitur. Evaluasi fitur atau model nanti adalah percobaan baru: tetapkan dulu
ambangnya, dan pastikan tercatat.

## Alur untuk kasus baru

1. Tambahkan kasus di `config/research.yaml` (data, periode, grid parameter).
2. Jalankan `research fingerprint` dan isikan `data_fingerprint`.
3. **Commit** config sebelum melihat hasil (pra-registrasi).
4. Jalankan `research validate`, lalu catat putusannya di `docs/research_log.md`, lolos atau
   tidak.

Jangan mengubah ambang atau grid setelah melihat hasil.

## Pencatat percobaan

- Otomatis: setiap backtest atas data dari store (`backtest`, `compare`, `walkforward`,
  `portfolio`, `research`, dan skrip yang memakai `load_bars`) dicatat di
  `data/experiments.duckdb`, termasuk yang gagal. Data palsu tidak dicatat.
- **Variasi** = strategi + parameter + instrumen + timeframe + pengaturan posisi (short,
  leverage, stop, take-profit). Mengulang, mengganti periode, atau biaya tidak menambah
  variasi.
- Bila pencatatan gagal, backtest ikut gagal.
- Tidak tercatat: skrip yang memanggil mesin tingkat rendah (`run_portfolio`) langsung atau
  menghitung return sendiri, dan percobaan sebelum 28 Nov 2026.
- File ini tidak di-commit. **Cadangkan** sendiri; bila terhapus, hitungannya hilang.

## Deflated Sharpe Ratio (DSR)

Peluang bahwa Sharpe variasi terpilih berada di atas Sharpe tertinggi yang bisa muncul **karena
keberuntungan** setelah mencoba N variasi, dengan memperhitungkan skew dan kurtosis
(Bailey & López de Prado 2014; ML4T bab 16). DSR >= 0,95 dianggap meyakinkan.

DSR membandingkan dengan nol keunggulan, **bukan** dengan Buy & Hold. Pada aset yang naik,
strategi yang hanya ikut naik bisa tampak bagus, jadi pembanding Buy & Hold tetap wajib.

## Probability of Backtest Overfitting (PBO)

Data dibagi 16 blok. Untuk semua 12.870 cara memilih 8 blok sebagai masa lalu, pilih variasi
terbaik lalu lihat peringkatnya di 8 blok sisanya. PBO = porsi saat pilihan itu jatuh ke median
atau lebih buruk. Sekitar 0,5 berarti memilih parameter tidak lebih baik daripada acak. PBO
rendah **tidak** berarti strateginya menguntungkan; hanya berarti urutan parameternya stabil.

## Kriteria lolos

Ketiganya harus terpenuhi (angka di `config/research.yaml`):

1. DSR >= 0,95 dengan 50 percobaan.
2. PBO <= 0,20.
3. Sharpe walk-forward di atas Buy & Hold setelah biaya.

Selama biaya masih PERLU DICEK, strategi yang lolos pun baru berstatus kandidat.
