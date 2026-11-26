# Roadmap & contoh prompt untuk Claude Code

Kerjakan berurutan. Selesaikan satu tahap (tes lulus, sudah di-commit) sebelum lanjut.
Setelah tiap tahap: `uv run pytest -q` lalu `git add . && git commit -m "..."`.

## Tahap 0 — Kenalan dengan kode
> Jelaskan alur proyek ini dari data sampai hasil backtest, dalam bahasa Indonesia sederhana.
> Tunjukkan di mana sinyal digeser 1 bar dan kenapa itu penting.

## Tahap 1 — Fondasi realistis
> Tambahkan dukungan multi-ticker: backtest strategi yang sama ke daftar ticker
> (mis. BBCA.JK, BBRI.JK, TLKM.JK, ASII.JK) dan tampilkan tabel perbandingan metrik.

> Tambahkan simulasi lot IDX: posisi dibulatkan ke kelipatan 100 lembar berdasarkan modal,
> dan hitung biaya dalam Rupiah. Tambahkan tes.

> Tambahkan log transaksi (tanggal masuk, keluar, harga, P/L per trade) dan simpan ke CSV
> di reports/. Hitung win rate per trade dan rata-rata untung vs rugi.

## Tahap 2 — Manajemen risiko
> Tambahkan stop-loss dan take-profit berbasis ATR sebagai lapisan terpisah yang bisa dipakai
> strategi apa pun. Pastikan tidak ada look-ahead (stop dicek dengan high/low bar berikutnya).

> Tambahkan position sizing berbasis volatilitas (target volatilitas tahunan, mis. 15%).

## Tahap 3 — Strategi baru (satu per satu)
> Buat strategi breakout Donchian channel (masuk di high 20 hari, keluar di low 10 hari).
> Daftarkan, jalankan tes look-ahead, lalu bandingkan dengan sma_cross via walk-forward.

> Buat strategi momentum cross-sectional untuk 20 saham LQ45: tiap bulan beli 5 saham dengan
> return 6 bulan tertinggi. (Catatan: perhatikan survivorship bias — daftar LQ45 hari ini
> berbeda dengan dulu.)

## Tahap 4 — Validasi anti-overfitting
> Tambahkan laporan: jumlah kombinasi parameter yang dicoba, Deflated Sharpe Ratio,
> dan uji Monte Carlo (acak urutan trade) untuk melihat rentang drawdown.

> Buat heatmap Sharpe untuk grid parameter. Saya ingin melihat apakah hasil bagus berada di
> "dataran" yang stabil atau hanya satu titik kebetulan.

## Tahap 5 — Paper trading (setelah tahap 4 meyakinkan)
> Buat modul paper trading yang tiap hari mengambil data terbaru, menghitung sinyal,
> dan mencatat order simulasi ke file. Tanpa koneksi broker sungguhan.

## Tahap 6 — Live (hanya kalau paper trading konsisten berbulan-bulan)
> (Diskusikan dulu: broker/exchange mana, API apa yang tersedia, batas risiko harian,
> kill switch.) Mode live default OFF, butuh flag eksplisit.

---

## Tips memakai Claude Code
- Minta **rencana dulu**: "Buat rencana dulu, jangan ubah kode sebelum saya setuju."
  (atau tekan Shift+Tab untuk *plan mode*).
- Satu fitur per permintaan. Permintaan besar = bug besar.
- Selalu tutup dengan: "Jalankan pytest dan tunjukkan hasilnya."
- Kalau hasil backtest tiba-tiba sangat bagus: "Audit kode ini untuk look-ahead bias
  dan biaya yang hilang."
- `/clear` untuk mulai percakapan baru saat ganti topik; CLAUDE.md tetap terbaca.
