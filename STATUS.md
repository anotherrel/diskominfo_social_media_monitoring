# STATUS — DKIS_MONITORING_FACEBOOK_TIKTOK (Scraper Isu Kota Cirebon — TOPIK BEBAS)

> Folder: `D:\DKIS_MONITORING_FACEBOOK_TIKTOK` (WSL: `/mnt/d/DKIS_MONITORING_FACEBOOK_TIKTOK`)
> Dibuat: **17 Sep 2026** — proyek **turunan/generalisasi** dari `D:\DKIS_MONITORING(AMS_V2)`.
> Dokumen pegangan: `DESAIN.md` (baca bagian **"REVISI BESAR — 18 Sep 2026"** dulu) + `README.md`.
> Repo git: **belum** (`git init` belum dijalankan).
> Environment: **PowerShell Windows, tanpa venv**; `requirements.txt` = `requests`, `python-dotenv`.
> Isi folder (per 23 Sep 2026): `instagram/` (10 akun media **+ bot Telegram** di `instagram/bot/`) · `tiktok/` · `kaidah/` + `topik/` · `facebook/` (masih kosong) · `_arsip/`.

## Progress Keseluruhan: ~88%

| Bagian | Persen | Keterangan |
|--------|--------|------------|
| `DESAIN.md` | ✅ 100% | + bagian revisi 18 Sep (desain baru & angka uji) |
| `README.md` | ✅ 100% | **BARU 18 Sep** — cara pakai, struktur, kaidah, cara membaca laporan corong |
| `kaidah/kota_cirebon.json` **v3** | ✅ 100% | **Sederhana: 1 kata gerbang** + tanda lokal (petunjuk AI) + kata terlarang + keterangan wilayah. Arsip v2 di `kaidah/_arsip/` |
| Modul `tiktok/code/` (7 modul) | ✅ 100% | Ditulis ulang 18 Sep: `evaluator` = gerbang (tanggal + kata terlarang + kata wilayah), `rule_builder` = contoh + varian kata kunci, `llm_reviewer` = gate AI (YA/TIDAK/RAGU + label wilayah), `storage` = kandidat + ditolak + laporan corong + data mentah + run_id |
| Launcher root `main.py` | ✅ 100% | Menu + `--tiktok` / `--facebook` / `--semua` |
| Uji tanpa biaya | ✅ 100% | Dua tahap: tiruan (LLM+Apify palsu) dan **LLM asli** ke data tersimpan → 250 item → 45 kandidat → 40 YA / 1 TIDAK / 4 RAGU |
| Uji ulang topik "Becak Listrik" | ✅ 100% | 18 Sep 04:01 UTC: 103 video nyata (dibaca ulang dari dataset Apify lama, gratis) → **40 relevan** (desain lama: 12) |
| **Uji 4 TOPIK NYATA** (Next Action #1) | ✅ 100% | 18 Sep 11:18–15:18: Becak Listrik (run baru), **Banjir**, **Tower Rubuh**, **Maxim Demo** — 20 query, 1.250 item mentah, **173 YA** / 214 TIDAK / 34 RAGU, biaya Apify **$3,089**. Rincian: bagian "Hasil uji 4 topik 18 Sep" |
| **Modul `facebook/`** | ⬜ 0% | Belum dibuat (actor beda: `scraper_one~facebook-posts-search` + `location`) |
| **Modul `instagram/` + bot Telegram (`instagram/bot/`)** | ✅ ~99% | Dipindah dari AMS_V2 (10 media + 32 akun OPD). Bot TANPA LLM. Pemantauan OPD direvisi 14 Okt: Single OPD & komentar dihapus, pemeringkatan 32 akun keaktifan, multi-select download post per OPD di Telegram, struktur folder Usulan A, format dataset 11 kolom + skor minat masyarakat. |
| Uji bot tanpa biaya (`instagram/bot/`) | ✅ 100% | `uji_telegram.py` (kirim pesan + berkas) · `uji_tiruan_menu.py` **38/38** · `uji_tiruan_job.py` **81/81** · `uji_batas_komentar.py` **9/9** |
| Aturan batas komentar IG (BARU 22 Sep) | ✅ 100% | Total komentar **< 100 → ambil SEMUA** komentar tiap post; ≥ 100 → batas per post (plafon 500) |
| **Revisi bot 23 Sep (ramah ASN + LLM dimatikan)** | ✅ 100% | (1) Pesan Telegram ditulis ulang jadi bahasa awam; (2) estimasi biaya & waktu DIHAPUS; (3) LLM-Kita dimatikan sementara — hanya IndoBERTweet; CSV komentar dipotong 13 kolom |
| **Revisi OPD: Multi-Select Post & Usulan A (14 Okt 2026)** | ✅ 100% | Klasemen 32 akun selesai → kirim CSV ranking → bot tampilkan papan multi-select 3 halaman → user bebas pilih dinas/kecamatan (misal: dkis & disbudpar) → bot langsung kirim CSV post masing-masing akun dengan format 11 kolom & diurutkan berdasarkan skor minat masyarakat (`like + 2*comment`). |
| Komentar + sentimen **TikTok & Facebook** | ⏸️ Ditunda | Sesuai keputusan: tahap 1 TikTok/FB hanya POST (agar tidak butuh `torch`). **Instagram justru sudah rantai penuh** (post → komentar → IndoBERTweet; penilaian LLM dimatikan 23 Sep) |
| `git init` + commit | ✅ 100% | Repositori diinisialisasi, `.gitignore` ketat & aman tanpa bocor rahasia, dokumentasi README berstandar profesional. |

## Tahap Aktif

- **14 Okt 2026 — Revisi 3: Multi-Select Post Download OPD, Struktur Usulan A & Penilaian Skor Postingan.**
  - **Alur Peringkat + Multi-Select Telegram**: Pemantauan keaktifan 32 akun OPD menghasilkan klasemen peringkat terlebih dahulu. Bot otomatis mengirimkan berkas CSV klasemen (`ranking_keaktifan_opd_*.csv`) ke chat, dan secara otomatis memunculkan antarmuka interaktif 3 halaman (Dinas Bagian 1, Dinas Bagian 2, Kecamatan). Pengguna dapat memilih satu atau lebih akun secara bersamaan (misal DKIS dan Disbudpar), lalu menekan tombol "Kirim CSV Post" untuk mengunduh dataset postingan instan tanpa scraping ulang.
  - **Format Dataset Postingan (11 Kolom)**: Setiap berkas akun yang diunduh berformat:
    `scrape_id | post_id | post_url | created_at | platform | post_type | username | caption | like_count | comment_count | skor`
  - **Penilaian Konten (Skor Minat Masyarakat)**: Tiap postingan diberi bobot nilai interaksi masyarakat dengan formula:
    `skor = like_count + (comment_count * 2)`
    Seluruh postingan diurutkan dari skor tertinggi ke terendah, mempermudah identifikasi konten yang paling disukai masyarakat.
  - **Struktur Folder Usulan A (Berbasis Tanggal Run)**:
    - `instagram/cirebon_opd/data/<tanggal_run>/`
      - `ranking_keaktifan_opd_<hari>hari_<timestamp>.csv`
      - Subfolder `post/`: `<folder_akun>_<tanggal_run>.csv` dan `.json` (misal `dkis_2026-10-14.csv`, `disbudpar_2026-10-14.csv`)
    - `instagram/cirebon_opd/history/history_opd.csv` & `.json` (log audit global)
  - **Standardisasi Skema Riwayat (History OPD)**: Format kolom diseragamkan dengan standar internasional (13 kolom):
    `scrape_id, platform, target, day_range, date_from, date_to, total_post, total_likes, total_comments, started_at, finished_at, status, error_message`
    Data usang mode single (disbudpar) dan sisa kolom komentar/sentimen yang sudah tidak digunakan telah dibersihkan secara tuntas.
- **14 Okt 2026 — Revisi 2: Hapus Fitur Comment untuk OPD.**
  - **Hapus Scraping Komentar OPD**: Fungsi `scrape_comments_apify`, actor comment, parameter komentar (`MAKS_KOMENTAR_DEFAULT`, dll.), serta folder `instagram/cirebon_opd/comment` dihapus secara menyeluruh.
  - **Hapus Analisis Sentimen OPD**: Dependensi `sentiment_analyzer` (PyTorch / IndoBERTweet) pada modul OPD dihilangkan sepenuhnya, sehingga proses scraping OPD menjadi jauh lebih ringan dan cepat.
  - **Penyimpanan & Riwayat Ringkas**: `simpan_dataset_komentar_opd` dihapus, dan log `history_opd` disederhanakan hanya mencatat metrik postingan dan total engagement.
  - **Fokus Murni Klasemen 32 OPD**: Modul OPD murni bertugas memantau postingan dan menyusun klasemen keaktifan 32 akun resmi Pemkot Cirebon berdasarkan post, likes, dan comments count bawaan postingan.
- **23 Sep 2026 — bot Telegram dirapikan untuk pemakai awam & LLM dimatikan.** Tiga permintaan user (pesan
  ramah ASN · jangan beri estimasi biaya/waktu kalau tak pasti · LLM drop dulu, andalkan IndoBERTweet)
  dikerjakan tuntas 09:33–12:31, lalu **diuji nyata 12:33–12:35** (`radarcirebon` 14 hari · top 1): 18 post
  lolos filter, 108 komentar tersimpan, IndoBERT POSITIF 2 / NEGATIF 58 / NETRAL 48, biaya Apify $0,3128.
  Rincian: bagian **"Revisi 23 Sep 2026"** di bawah.
- **22 Sep 2026 — sesi terbesar sejak proyek lahir: modul `instagram/` dipindah ke proyek ini lalu
  dihubungkan ke bot Telegram tanpa LLM.** Pemicu: user memindahkan folder `instagram/` dari
  `DKIS_MONITORING(AMS_V2)` ke sini ("baru saja kupindahkan, mungkin harus dikonfigurasi ulang") dan
  ingin scraper itu "dipakai langsung user" lewat Telegram. Sesi 08:56–13:39 = brainstorming keputusan
  → bangun bot → uji nyata di Telegram; sesi 13:41–15:31 = tiga perbaikan UX (satu pesan progres yang
  diperbarui, kejelasan biaya/limit di layar konfirmasi, aturan "komentar sedikit → ambil semua").
  Rincian: bagian **"Bot Telegram `instagram/bot/` (BARU 22 Sep 2026)"**.
- **Desain diganti total pada 18 Sep** (pemicu: user scroll TikTok sendiri dan menemukan 40+ video
  relevan, padahal hasil run 17 Sep hanya 12).
  - Penyebab terbukti: prompt lama menyuruh LLM menulis `ambang_skor 0.75`, sementara kata inti
    topik ("becak listrik") hanya berbobot 0,30 → caption yang menyebut topiknya sendiri GUGUR.
    Uji mandiri tetap "lulus 3/3" karena ketiga contoh videonya caption berita panjang dari akun media.
  - Cara ukur (biaya Rp0): 5 dataset Apify run 17 Sep **dibaca ulang** (baca dataset tidak berbiaya)
    → 103 video unik → dijalankan ulang ke evaluator lama: 91 gugur (skor 29, wilayah 36, tanggal 22,
    caption kosong 4) → **recall 12/42 = 29%**.
  - Setelah gerbang disederhanakan + penilaian ke AI: **40 relevan + 4 perlu diperiksa** dari data
    yang sama, **0 salah-terima dari 61 penilaian**, konsistensi 44/45 (98%).
  - Bukti tambahan: daftar 40 kecamatan Kabupaten **tidak diperlukan** (12 caption sintetis diuji
    dengan & tanpa daftar → hasil identik 12/12), dan AI tetap bisa menolak Kabupaten yang captionnya
    MEMUAT kata "cirebon" (2/2).
- **Jejak audit sekarang wajib** (ini yang paling mencegah masalah terulang): data mentah per kata
  kunci disimpan, `run_id`/`dataset_id` Apify dicatat di history, semua kandidat disimpan,
  yang ditolak/disangsikan **tidak dibuang** tapi masuk `tiktok_ditolak_ai_*`, dan setiap run
  menulis `laporan_funnel_*.txt`.
- **Kata kunci varian sekarang lebih beragam** (hasil AI): run uji 18 Sep menghasilkan
  "becak listrik cirebon bantuan prabowo", "tukang becak cirebon dapat becak listrik gratis",
  "sulaeman becak listrik cirebon penghasilan", "becak listrik cirebon panjunan",
  "becak listrik cirebon tidak boleh dijual" — jauh lebih berbeda daripada 5 varian lama
  yang hampir kembar (efisiensi penarikan lama hanya 41%).

## Berkas hasil run uji ulang 18 Sep (di `tiktok/post/becak_listrik_kota_cirebon/`)

- `gabungan_terfilter/tiktok_master_becak_listrik_kota_cirebon_20260918_040131.csv|json` → **40 relevan**
- `gabungan_terfilter/tiktok_ditolak_ai_20260918_040131.csv|json` → 1 TIDAK + 4 RAGU (dengan alasan)
- `gabungan_terfilter/tiktok_kandidat_semua_20260918_040131.csv|json` → 45 kandidat sebelum AI
- `gabungan_terfilter/laporan_funnel_20260918_040131.txt` → ringkasan corong
- `mentah/*.json` → 250 item mentah (5 kata kunci) — bisa dipakai ulang untuk uji berikutnya, gratis
- `kandidat/*.csv|json` → hasil gerbang per kata kunci

⚠️ Berkas run **17 Sep** (`post/becak_listrik_kota_cirebon/*.csv` di level atas, tanpa subfolder)
dan master 12 video di `gabungan_terfilter/tiktok_master_becak_listrik_kota_cirebon_20260917_034041.csv`
**dibiarkan apa adanya** sebagai catatan desain lama — jangan dibingungkan dengan hasil baru
(hasil baru punya stempel `20260918`).

## Hasil uji 4 topik pada 18 Sep 2026 (3 topik BARU — Next Action #1 tuntas)

Semua run `success`, semua menulis `laporan_funnel_*.txt`. Waktu WIB, biaya Apify nyata.

| Topik | Contoh | Query | Mentah | Kandidat | YA | TIDAK | RAGU | Biaya |
|---|---|---|---|---|---|---|---|---|
| Becak Listrik (run baru 11:18–11:22) | 5 | 5 | 250 | 40 | 35 | 0 | 5 | $0,581 |
| **Banjir Kota Cirebon** (14:21–14:43) | 6 | 5 | 500 | 304 | 120 | 158 | 26 | $1,370 |
| **Tower Rubuh Kota Cirebon** (14:59–15:03) | 3 | 5 | 250 | 48 | 3 | 45 | 0 | $0,593 |
| **Maxim Demo Kota Cirebon** (15:14–15:18) | 6 | 5 | 250 | 29 | 15 | 11 | 3 | $0,545 |
| **TOTAL** | | **20** | **1.250** | **421** | **173** | **214** | **34** | **$3,089** |

- Diterima AI (contoh benar): `@infoviralcirebon` (banjir Kedawung), `@lingkupciremai` (banjir Kalijaga/Harjamukti), `@inewscirebon.id` (tower Kesambi), `@cirebonesiamedia` & `@wewararctv` (demo Maxim Pemuda).
- Ditolak AI (bukti gate tidak asal meloloskan): banjir **Kabupaten** (Desa Mekarsari/Waled, Sumber), kebakaran Pabrik Gula Gempol Palimanan, iklan jual rumah & jasa wedding, acara Indosiar, kegiatan Rutan Cirebon.
- Gerbang jalan sebelum AI: gugur `TANPA KATA WILAYAH`, `LUAR TANGGAL`, `KATA TERLARANG` (rincian per kata kunci ada di tiap `laporan_funnel_*.txt`).
- **Pelajaran penting**: mutu & jumlah contoh menentukan. Tower Rubuh hanya diberi 3 contoh dan kejadiannya sudah lewat 5 hari → 3 YA dari 48 kandidat. Banjir & Maxim (6 contoh, isu masih hangat) jauh lebih produktif.
- **Umpan balik otomatis jalan**: `contoh_negatif.json` terisi — Banjir **100**, Tower Rubuh **45**, Maxim Demo **11**, Becak Listrik **0** (karena tidak ada yang ditolak).
- Biaya nyata ±**$0,15/query** (100 item) → label tarif di `config.py` ($0,10–0,30) sudah wajar.

## Bot Telegram `instagram/bot/` (BARU 22 Sep 2026)

Tujuan: scraper Instagram dipakai **pegawai Diskominfo sendiri lewat Telegram** — on-demand, bebas waktu,
**tanpa LLM** (keputusan user), akun bisa dipilih dari daftar media atau diketik sendiri.

| Berkas | Isi |
|---|---|
| `main_bot.py` | pintu masuk: cek kesiapan setelan → **long polling** → simpan `offset` (pesan yang masuk saat bot mati tidak hilang & tidak diproses dua kali) |
| `telegram_api.py` | pembungkus Bot API: kirim pesan, **edit pesan**, kirim berkas, long polling |
| `bot_config.py` | setelan `.env` + **tabel bahasa ramah** + statistik riwayat (estimasi waktu/biaya) |
| `menu_bot.py` | alur menu: akun (daftar media / input sendiri) → rentang hari (sampai 365) → batas post/akun → jumlah post teratas untuk komentar → komentar YA/TIDAK → aliran log → **layar konfirmasi** |
| `job_runner.py` | antrean **1 job**: menjalankan `cirebon_media/code/main.py` sebagai proses terpisah, mengalirkan keluaran ke **satu pesan progres**, mengirim CSV+JSON + log mentah, batas waktu 90 menit |
| `jalankan_bot.bat` | klik dua kali di Windows (memakai `C:\Python314\python.exe` karena butuh `transformers` + `torch`) |

Operasional: allowlist user di `.env` (`BOT_ALLOWED_USER_IDS`, admin `BOT_ADMIN_USER_IDS`) · sesi per user
`data/sesi.json` · riwayat `data/riwayat_job.json` · log mentah tiap job di `log/`. **Token Telegram wajib
bot BARU** — token yang dipakai Hermes → error `409`.

Keputusan user yang dikunci 22 Sep:
- Penilaian komentar diganti ke **`gpt-5.6-terra`**, tetapi **IndoBERTweet tetap dijalankan** supaya ada dua
  gate yang bisa dibandingkan (job 14:57: keduanya sama — 5 POSITIF · 4 NETRAL · 0 NEGATIF, 0 berbeda).
- Keluaran scraper tidak lagi jadi puluhan pesan: semuanya masuk **satu pesan progres yang diperbarui**
  (±4 detik; segera bila ada ⚠️/💰/❌), dengan kendali `/logmati` & `/loghidup`.
- **Total komentar < 100 → ambil SEMUA komentar tiap post** (batas per post dilewati).
- Ringkasan memakai **nilai tengah (median)**, bukan rata-rata — satu akun ramai (472 komentar) bikin rata-rata menyesatkan.
- Batch AI dikerjakan beberapa pekerja **memakai satu penyedia API yang sama** (tidak boleh beda-beda provider).

Job nyata via Telegram (22 Sep, 8 entri `data/riwayat_job.json`, biaya Apify tercatat **$4,4252**):

| Jam WIB | Permintaan | Status | Biaya |
|---|---|---|---|
| 10:10 | radarcirebon · 3 hari · top 1 | sukses | $0,1932 |
| 11:09 | cirebonnews · 7 hari · top 3 | sukses (0 post lolos filter) | $0 |
| 11:11 | 3 akun · 7 hari · top 3 | dibatalkan user | $0,4531 |
| 11:26 | 4 akun · 7 hari · top 3 | dibatalkan user | $0,0989 |
| 11:44 | 4 akun · 7 hari · top 3 · 500 komentar/post | **sukses** | $1,4973 |
| 14:15 | 3 akun · 7 hari · top 3 | dibatalkan user (tahap AI macet) | $0,0989 |
| 14:57 | 4 akun · 3 hari · top 1 · 500 komentar/post | **sukses** | $0,1242 |
| 15:36 | 2 akun · 14 hari · top 3 · 500 komentar/post | dibatalkan user 16:01 — **791 komentar** ditarik, IndoBERT selesai, tahap AI (batch 24 dari 32) belum tuntas | $1,9596 |

Job nyata via Telegram (**23 Sep, 1 entri baru** — setelah revisi; LLM sudah mati):

| Jam WIB | Permintaan | Status | Hasil | Biaya |
|---|---|---|---|---|
| 12:33–12:35 | radarcirebon · 14 hari · top 1 · 500 komentar/post | **sukses** | 18 post lolos filter · 108 komentar tersimpan · sentimen IndoBERT **POSITIF 2 · NEGATIF 58 · NETRAL 48** | $0,3128 (post $0,0644 + komentar $0,2484) |

⚠️ **Koreksi angka "±5 detik/komentar" di bagian Blocker**: log mentah run 15:36 menunjukkan yang terjadi
bukan model menghitung lambat, melainkan **menunggu jawaban yang tak datang** — `Read timed out` di key #1,
#2, #3 berurutan (4 key × 120 detik terbuang untuk satu batch) dan `HTTP 524` berulang. Setelah perbaikan
22 Sep sore, baris `⏱ ... permintaan dipecah` muncul di log (permintaan 25 komentar otomatis dipecah jadi
12 + 13). Jadi hitungan "sekian detik/komentar" **belum bisa dipakai** sebagai patokan sebelum `llm_reviewer.py`
ikut diperbaiki (lihat Next Action #0/#1).

## Revisi 23 Sep 2026 — pesan ramah ASN, estimasi dibuang, LLM dimatikan

Sesi 23 Sep **09:33–12:31** (satu sesi CLI; setelah itu user menjalankan bot sendiri). Tiga permintaan user,
semuanya dikerjakan tuntas lalu **diuji dengan job nyata**:

1. **Pesan Telegram masih terasa "log mesin", tidak ramah untuk pegawai ASN/awam.**
   → bahasa `job_runner.py` ditulis ulang: kalimat seperti *"Penilaian AI batch 3 (komentar 50-75 dari 263)"*
   dan *"server AI lambat (HTTP 524)"* diganti bahasa awam; `_RAPIKAN`, `_susun_teks_progres`,
   `_perkiraan_langkah` dibersihkan dari istilah teknis.
2. **Jangan memberi estimasi biaya/waktu kalau tidak pasti.**
   → blok **PERKIRAAN WAKTU** & **BIAYA APIFY** dihapus dari pesan konfirmasi (`menu_bot.py`), pesan
   progres, dan ringkasan (`job_runner.py`); baris `Biaya run ini (Apify): $…` ditambahkan ke `_LEWATI_LOG`
   supaya tidak lolos ke chat. Fungsi `hitung_estimasi_biaya` / `hitung_perkiraan_durasi` / `blok_biaya`
   **dibiarkan ada tapi tidak lagi dipanggil** (mudah dihidupkan lagi nanti). Biaya tetap dicatat internal di
   `data/riwayat_job.json`.
3. **Integrasi LLM-Kita di-drop sementara, andalkan IndoBERTweet.**
   → `storage.py`: impor `llm_reviewer` dihapus, tahap 2 (`review_komentar_dengan_llm`) **dimatikan**; kolom CSV
   komentar dipotong jadi **13 kolom** (berhenti di `sentimen` + `skor_yakin`) — `sentimen_ai`, `alasan_ai`,
   `butuh_review`, `alasan_review` tidak lagi ditulis; return `simpan_dataset_comment` 7 → **4 nilai**.
   `main.py` disesuaikan (impor `ambil_model_llm` dihapus, keluaran terminal hanya sentimen IndoBERT).

**Efek samping yang bagus:** tahap terlama & paling rapuh (penilaian LLM + `HTTP 524`) hilang, jadi risiko
**"data hilang saat job dibatalkan"** turun banyak — komentar tersimpan tepat setelah IndoBERT selesai,
bukan setelah puluhan batch AI.

**Verifikasi:** job nyata 12:33–12:35 sukses (18 post · 108 komentar · IndoBERT), dan CSV komentar di disk
memang berhenti di kolom `skor_yakin` (13 kolom). Pelajaran bot sudah masuk skill `telegram-bot-wrapper`
(diperbarui 23 Sep 09:57).

## Blocker / Perlu Dibereskan

- **🔴 4 dari 10 akun media IG DIAM-DIAM KOSONG (temuan 23 Sep, bukti gratis dari dataset Apify lama)**: `suaracirebon`, `cirebontrending`, `fajar.cirebon`, `cirebonnews` → actor `shu8hvrXbJbY3Eb9W` balas 1 item `{"error": "no_items", "errorDescription": "Empty or private data for provided input"}` + biaya $0,0000, TAPI kode menghitungnya sebagai "1 postingan / 0 lolos filter" sehingga **tidak ada peringatan sama sekali**. Sama juga di proyek lama (CSV Aug–Sep 2026 isinya kosong) → cakupan "10 media" sebenarnya hanya **6**. Perlu: (a) deteksi field `error` di `apify_client.py` → laporkan GAGAL, (b) cari username IG yang benar untuk 4 akun itu.
- **🔴 Uang & data hilang kalau job dibatalkan**: run 22 Sep 15:36–16:01 (`radarcirebon,aboutcirebonid --hari 14`) sudah bayar **$1,9596** (post $0,1748 + komentar **$1,7848**, 791 komentar ter-*download*) tapi dibatalkan saat tahap penilaian AI (batch 24 dari 32) → **0 berkas komentar tersimpan** (tidak ada file di `comment/…/2026-09-22/` setelah 15:00). Data mentah komentar harus ditulis ke disk SEBELUM penilaian AI. **Status 23 Sep — risiko turun besar tapi belum nol**: penilaian LLM dimatikan, jadi tahap panjang setelah komentar ditarik kini cuma IndoBERT (cepat, di komputer sendiri); sisa jendela risiko = pembatalan tepat saat IndoBERT berjalan. **Yang BELUM dikerjakan: penulisan data mentah komentar ke disk segera setelah unduhan selesai** (sekarang tetap baru ditulis setelah IndoBERT). Catatan: tombol "Batalkan job" sudah menghentikan **run Apify di server** (`job_runner.py` → `hentikan_run_apify()`, jejak run di `history/apify_run_aktif.json` — ditambahkan 22 Sep), jadi tagihan ikut berhenti; yang masih bisa hilang tetap **data yang sudah diunduh**.
- **Tahap penilaian AI lambat & rapuh**: ±5 detik/komentar (9 post × 100 komentar ≈ 75 menit), dan di run 22 Sep jalan penuh `HTTP 524` (Cloudflare) + timeout 180 detik sehingga banyak batch harus dipecah lalu dirotasi antar 4 API key LLM-Kita (`gpt-5.6-terra`). **⏸️ TIDAK berlaku untuk modul `instagram/` sejak 23 Sep** karena LLM dimatikan (hanya IndoBERT) — masalah ini masih hidup untuk **gate AI modul `tiktok/`** dan untuk `llm_reviewer.py` IG yang kini tidak dipanggil (jawaban `6a/6b/6c` jadi tidak mendesak).
- **Modul `facebook/` belum ada** → masih satu platform, padahal desain: 1 kaidah dipakai 2 platform.
- **Jangkauan pencarian belum disentuh**: 50 hasil/query × 5 kata kunci → hanya 103 video unik
  (efisiensi 41%; 20 video muncul di kelima query). Ini urusan `--max` + varian kata kunci,
  bukan gerbang/AI. Catatan: skema actor punya `videoSearchSorting` / `videoSearchDateFilter` /
  `proxyCountryCode` / `scrapeRelatedSearchWords` — deskripsi actor menyebutnya "optional charged
  filter", biayanya belum diukur. Catatan lama "TikTok tidak punya filter tanggal" **kurang tepat**.
- ~~**Belum diuji dengan topik yang benar-benar baru**~~ → **SELESAI 18 Sep sore** (Banjir, Tower Rubuh, Maxim Demo). Temuan: jumlah & mutu contoh sangat menentukan; topik yang kejadiannya sudah lewat (Tower) hasilnya tipis.
- **Item RAGU menunggu periksa mata manusia**: 34 item dari uji 18 Sep (Banjir 26 · Becak 5 · Maxim 3) — ±10–15 menit, tidak perlu Apify.
- `contoh_negatif.json` topik **Becak Listrik masih kosong (0)** karena tiap run-nya nol penolakan → umpan balik topik itu belum terisi.
- 4 item "RAGU" tiap run = perlu periksa mata manusia (kira-kira 1 menit). Sengaja: lebih baik
  AI mengaku ragu daripada memaksa menebak.
- Belum `git init` + belum ada commit; label tarif di `config.py` masih tebakan
  (angka nyata ±$0,003/hasil).
- Daftar 64 nama jalan dari user (Kepmen PUPR/Kepgub Jabar/DPUTR) **belum dipakai** — disimpan
  sebagai amunisi topik infrastruktur (jalan rusak/banjir/drainase), bukan untuk sekarang.

## Next Action (satu hal terpenting)

0. **🔴 AMANKAN HASIL YANG SUDAH DIBAYAR (prioritas 23 Sep — separuh jalan)**: yang sudah beres 23 Sep: **penilaian LLM dimatikan**, jadi tahap panjang/rapuh setelah komentar ditarik hilang (jendela "data hilang saat dibatalkan" mengecil drastis). **Sisa yang masih harus dikerjakan:** (a) tulis data mentah komentar ke disk **segera setelah unduhan Apify selesai** (bukan menunggu IndoBERT kelar) — supaya pembatalan kapan pun tidak menghapus data yang sudah dibayar; (b) `apify_client.py` memperlakukan item ber-`error: no_items` sebagai **GAGAL** (per 24 Sep ini **belum dikerjakan** — sudah dicek, tidak ada penanganan `no_items` di kode) agar 4 akun mati langsung terlihat di chat bot; (c) cari username IG yang benar untuk `suaracirebon`, `cirebontrending`, `fajar.cirebon`, `cirebonnews`.
0b. **Cek dengan job nyata berakun banyak** (mis. 3 akun × 7 hari · top 3) bahwa pesan Telegram hasil revisi 23 Sep memang sudah ramah & tanpa angka biaya/waktu — baru ada 1 job uji (radarcirebon, 1 akun) setelah revisi.
1. **Periksa 34 item RAGU** dari uji 18 Sep (mulai dari Banjir 26) → tandai mana yang seharusnya masuk,
   lalu rapikan `contoh_negatif.json`. Murah, tanpa Apify, hasilnya langsung memperbaiki gate.
2. Bangun modul `facebook/` mengikuti pola modul tiktok yang baru (kaidah yang sama!).
3. `git init` + commit pertama (desain baru sudah stabil).
4. Kalau perlu menambah jangkauan: naikkan `--max`, lalu **ukur** tambahan video uniknya sebelum
   menaikkan lagi (jangan asal naikkan biaya).

## Log Perubahan

- 2026-09-23 (kerja sesi CLI **09:33–12:31**, direkap cron wrap-up catch-up 24 Sep 09:20): **Revisi bot Telegram
  atas 3 permintaan user — pesan dibuat ramah ASN, estimasi biaya/waktu dibuang, LLM-Kita dimatikan.** (1)
  `job_runner.py`: bahasa pesan/progres/ringkasan ditulis ulang (tanpa istilah batch/HTTP/API); (2) blok
  PERKIRAAN WAKTU & BIAYA APIFY dihapus dari `menu_bot.py` + `job_runner.py`, baris biaya Apify masuk
  `_LEWATI_LOG` (fungsi estimasi dibiarkan ada, tidak dipanggil; biaya tetap dicatat di `riwayat_job.json`);
  (3) `storage.py` + `main.py`: tahap penilaian LLM dimatikan, **kolom CSV komentar dipotong jadi 13 kolom**
  (`… sentimen, skor_yakin`), return 7 → 4 nilai. **Uji nyata 12:33–12:35**: job `radarcirebon` 14 hari · top 1
  → **sukses** (18 post lolos filter · 108 komentar · sentimen IndoBERT POSITIF 2 / NEGATIF 58 / NETRAL 48 ·
  biaya Apify $0,3128). Progress ~85% → **~88%**. Efek samping: risiko "data hilang saat job dibatalkan"
  turun besar karena tahap LLM (pemicu `HTTP 524`) hilang. Sisa: `no_items` belum ditangani, data mentah belum
  ditulis sebelum IndoBERT. Skill `telegram-bot-wrapper` diperbarui 09:57.
- 2026-09-23 (cron `daily-wrapup`, **catch-up 08:57** — job 22 Sep 21:00 tidak jalan karena PC/Hermes mati):
  cron `morning-priority` sudah merekap sesi bot 22 Sep lebih dulu (log di bawah); wrap-up ini **melengkapi**:
  progress ~75% → **~85%**, tabel modul ditambah (uji bot & aturan batas komentar), dan bagian
  **"Bot Telegram `instagram/bot/` (BARU 22 Sep 2026)"** ditambahkan berisi arsitektur 6 berkas, keputusan
  user yang dikunci, tabel 8 job nyata, serta koreksi angka "±5 detik/komentar" (log membuktikan penyebabnya
  **timeout + HTTP 524**, bukan kecepatan model) dan catatan `llm_reviewer.py` masih menunggu jawaban `6a/6b/6c`.
- 2026-09-23 (cron `morning-priority`): **Sesi bot Telegram 22 Sep (belum pernah tercatat) direkap + 3 temuan baru.** Yang terjadi 22 Sep: modul `instagram/` (10 media) dipindah ke sini dari AMS_V2, lalu bot Telegram diuji **live 8 job nyata** (4 selesai, 4 dibatalkan user) dengan biaya Apify **$4,43**; batas dibuka (`HARI_MAKS` 30→365, `MAKS_POST_DEFAULT` 300, plafon komentar 500, ambang ambil-semua 100). Temuan: (1) 4 dari 10 akun media balik `error: no_items` (bukan "1 postingan") dan selama ini tidak ada peringatan → cakupan efektif 6 akun; (2) job yang dibatalkan saat tahap AI kehilangan seluruh komentar yang sudah dibayar ($1,96 / 791 komentar, 22 Sep 15:36–16:01); (3) penilaian AI ±5 detik/komentar + `HTTP 524` dari LLM-Kita. Ketiganya masuk **Blocker** dan jadi **Next Action #0**.
- 2026-09-22 (cron wrap-up, catch-up 08:53): **Tidak ada aktivitas 19–21 Sep maupun 22 Sep pagi** —
  Hermes/gateway tidak jalan, jadi job `daily-wrapup` (21:00) & `morning-priority` (08:00) terlewat dan
  jalan bersama sebagai catch-up 08:53. Yang dicatat di sini: **uji 3 topik baru 18 Sep sore**
  (Banjir, Tower Rubuh, Maxim Demo) yang belum pernah masuk STATUS — sekarang ada bagian
  "Hasil uji 4 topik 18 Sep" + tabel. Progress ~60% → **~75%**, Next Action diarahkan ke periksa RAGU,
  modul `facebook/`, dan `git init`.
- 2026-09-18 (siang): **Revisi besar desain + kode ditulis ulang.** Kaidah kompleks (4 lapis +
  skor bobot + ambang 0,75 + 64 nama jalan + 40 kecamatan Kabupaten) DIBUANG, diganti 1 kata gerbang
  + gate AI yang belajar dari 3-5 contoh video. Terukur pada 103 video nyata: 12 → 40 relevan,
  0 salah-terima dari 61 penilaian, konsistensi 98%, daftar wilayah tidak diperlukan.
  Berkas baru: `README.md`, `kaidah/_arsip/`, `kaidah/kota_cirebon.json` v3, 6 modul ditulis ulang,
  `topik/becak_listrik_kota_cirebon/varian_query.json` + `contoh_negatif.json`.
  Bug diperbaiki: (a) `contoh.txt` multi-baris (caption ber-newline bikin contoh berikutnya terbaca
  tanpa URL), (b) gate harus menerima daftar contoh eksplisit (dulu bisa jalan tanpa contoh).
- 2026-09-18 (cron wrap-up, catch-up 09:15): STATUS.md ini **dibuat** — sebelumnya proyek ini belum
  punya STATUS (hanya `DESAIN.md`).
- 2026-09-17: **Proyek lahir & TikTok jalan dengan desain lama** (rule_set per topik, filter 4 lapis,
  run nyata "Becak Listrik Kota Cirebon": 5 query, 250 video, master 12 post, gate AI 12/12 YA, $0,629).
