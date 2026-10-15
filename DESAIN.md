# DESAIN — DKIS_MONITORING_FACEBOOK_TIKTOK

Status: hasil brainstorming (17 Sep 2026). **Kode sudah ada & sudah diuji.**
Proyek induk (versi insiden-tunggal): `D:\DKIS_MONITORING(AMS_V2)`.

---

## ⚠️ REVISI BESAR — 18 Sep 2026 (BACA INI DULU)

**Yang berubah: FILTER JADI SEDERHANA. Kaidah kompleks + skor bobot kata DIBUANG.**

Alasan (semuanya angka terukur, bukan pendapat — diuji ke 103 video nyata hasil run 17 Sep
dengan cara membaca ulang dataset Apify yang lama, jadi biayanya nol):

| Hal | Versi lama (17 Sep) | Versi sekarang (18 Sep) |
|-----|---------------------|--------------------------|
| Penyaring wilayah | 4 lapis: tanggal + kata terlarang + lapis kota (kecamatan/kelurahan/64 jalan/Kabupaten) + skor bobot | **tanggal + kata terlarang + 1 KATA GERBANG** ("cirebon", potongan kata) |
| Penentu relevansi | skor bobot kata vs `ambang_skor` (default LLM menulis 0,75) | **AI (gate), belajar dari 3-5 contoh video user** |
| Hasil dari 103 video | **12 relevan** (recall 12/42 = 29%) | **40 relevan + 4 perlu diperiksa** (recall ≈ 100% dari kandidat) |
| Presisi | tidak pernah menolak apa pun (12/12 YA) | 1 salah terima dari 61 penilaian; Kabupaten 2/2 ditolak; kota lain 6/6 ditolak; iklan sepeda listrik 2/2 ditolak |
| Konsistensi antar-run | belum diukur | 44/45 sama (98%) |
| Daftar bantuan wilayah | 40 kecamatan Kabupaten + 64 jalan + 18 kelurahan | **tidak diperlukan** (uji 12 caption sintetis: hasil sama dengan/tanpa daftar) |

Akar masalah versi lama: prompt `rule_builder` menyuruh LLM menulis `ambang_skor: 0.75`,
sementara kata inti topik ("becak listrik") hanya berbobot 0,30 (+0,05 bonus "cirebon" = 0,35).
Jadi **caption yang menyebut topiknya sendiri pun tidak bisa lolos**. Uji mandiri tetap lulus 3/3
karena ke-3 contoh videonya caption berita panjang dari akun media — aturan itu "belajar gaya
media", bukan gaya netizen. 32 dari 42 kandidat relevan gugur di lapis skor.

**Yang berlaku sekarang:**
- Kaidah (`kaidah/kota_cirebon.json`) = 4 bagian, isinya DATA saja (tidak ada logika):
  `1_kata_gerbang` (1 kata) · `2_tanda_lokal` (petunjuk untuk AI, bukan penyaring) ·
  `3_kata_terlarang` (sampah) · `4_keterangan_wilayah` (kalimat untuk prompt AI).
- Alur = **5 tahap**: input contoh → validasi contoh → varian kata kunci (AI) →
  scrape + gerbang → gate AI (YA/TIDAK/RAGU + label wilayah + alasan) + laporan corong.
- **Jejak audit wajib**: data mentah disimpan, `run_id`/`dataset_id` Apify dicatat,
  semua kandidat disimpan, yang ditolak/disangsikan tetap disimpan (bukan dibuang diam-diam),
  dan tiap run menulis `laporan_funnel_*.txt`.
- Keputusan lama yang **DIGANTI/DIHAPUS**: #7 & #8 (rule_set per topik), #15 (lapis kota nama resmi),
  #16 (wilayah lemah), bagian §5.3 (`rule_set.json`), §5.4 (`uji_mandiri.json`), §6 (filter 4 lapis
  + rumus skor). Bagian di bawah dibiarkan apa adanya sebagai catatan sejarah — **jangan dipakai
  sebagai acuan kode**.
- Arsip versi lama: `kaidah/_arsip/` (kota_cirebon v2, rule_set becak listrik, uji mandiri, contoh.txt lama).

**Pelurusan klaim teknis:** catatan lama "TikTok tidak punya filter tanggal/lokasi di actor"
KURANG TEPAT. Skema resmi `clockworks~tiktok-scraper` punya `videoSearchSorting`
(MOST_RELEVANT/MOST_LIKED/LATEST), `videoSearchDateFilter` (ALL_TIME/PAST_WEEK/PAST_MONTH/…),
`proxyCountryCode`, dan `scrapeRelatedSearchWords` — deskripsi actor menyebutnya
"optional charged filter" (belum diukur biayanya). Saat ini masih memakai default (MOST_RELEVANT).

**Yang BELUM dibereskan (jujur):** jangkauan pencarian. 5 kata kunci × 50 hasil → hanya 103 video
unik (efisiensi 41%; 20 video muncul di kelima query). Ini urusan kata kunci/`--max`, bukan gerbang/AI.

---

## 1. TUJUAN

Memantau **isu & tren apa pun** di Kota Cirebon dari TikTok + Facebook — bukan lagi hanya insiden "Tower Roboh Kesambi".

Ruang lingkup TAHAP 1 (sekarang):
- Hanya **POSTINGAN** (post/video) yang di-scrape, difilter, dan dinilai AI.
- **Komentar + analisis sentimen DITUNDA** (folder `comment/` disiapkan kosong).
- **Kategori isu DITIADAKAN** dulu. LLM gate hanya menjawab: relevan YA/TIDAK + skor + alasan.

---

## 2. KEPUTUSAN YANG SUDAH TERKUNCI

| # | Hal | Keputusan |
|---|-----|-----------|
| 1 | Wilayah | Hanya **Kota Cirebon** (5 kecamatan + 22 kelurahan resmi + nama jalan kota). Kabupaten = bukan target |
| 2 | Bahan aturan | **Caption + hashtag** saja (LLM tidak menonton video) |
| 3 | Contoh video (seed) | **3–5 URL, boleh campur** TikTok + Facebook. **Wajib ada** — sistem menolak jalan kalau kosong |
| 4 | Cara dapat caption seed | **Tempel URL saja** → caption diambil otomatis lewat mode `postURLs` actor `clockworks~tiktok-scraper` (~$0.005/video, kemampuan ini diverifikasi 17 Sep dari skema resmi actor). Boleh juga cara lama `URL \| caption` manual (gratis, tanpa Apify) |
| 5 | Syarat seed | **Wajib bercaption** ≥5 kata bermakna. Caption hashtag-saja ditolak; kalau caption otomatis pun kosong (video privat/dihapus) → ganti video |
| 6 | Contoh negatif manual | Tidak diminta. Diganti umpan-balik otomatis (`contoh_negatif.json`) |
| 7 | rule_set | **1 topik = 1 rule_set**, dipakai DUA platform |
| 8 | rule_set sudah ada | **Dipakai langsung** (tanpa flag bikin-ulang) |
| 9 | Query | Dari user 1 topik → LLM bikin **3–5 varian**. Untuk TikTok varian WAJIB memuat kata "Cirebon" (TikTok tidak punya filter lokasi) |
| 10 | Tanggal | `--day 30 / --month 1 / --year 1` dihitung dari **hari ini**, plus `--from --to` manual |
| 11 | Kode | **Modul terpisah per platform** (`tiktok/`, `facebook/`). Berbagi hanya file DATA `kaidah/kota_cirebon.json` |
| 12 | Struktur run | Bisa **satu platform saja** atau dua-duanya (`--tiktok`, `--facebook`, `--semua`) |
| 13 | Output | **CSV/JSON per run** (seperti sekarang). Tanpa database |
| 14 | Environment | **PowerShell, tanpa venv**. `requirements.txt` cukup `requests` + `python-dotenv` |
| 15 | Bentuk lapis kota | **Nama resmi pemerintahan** (kecamatan, kelurahan, nama jalan) — bukan daftar landmark campur-aduk. Dipilih 17 Sep karena file ini akan dirawat/dibaca ASN |
| 16 | Wilayah lemah | Post yang **hanya menyebut "cirebon"** (tanpa kecamatan/kelurahan/jalan) TIDAK dibuang: ditandai `wilayah_lemah = Ya`, tetap wajib lolos ambang skor, keputusan akhir diserahkan ke AI gate (pilihan user 17 Sep, opsi b) |

---

## 3. ALUR 6 TAHAP

1. **INPUT** — user isi: keyword topik, rentang tanggal, 3–5 URL contoh + captionnya.
2. **VALIDASI SEED** — caption digodok: buang hashtag & URL → minimal **5 kata bermakna**. Gagal = ditolak + pesan jelas.
3. **INDUKSI ATURAN (LLM)** — LLM pelajari caption contoh → hasilkan `rule_set.json` (kata inti, sinonim/slang, pelaku, pemicu beserta bobot, pengecualian, ambang skor) + 3–5 varian kata kunci.
4. **UJI MANDIRI (recall test)** — semua contoh video WAJIB tertangkap aturan sendiri. Kalau ada yang gagal → LLM revisi aturan (maks 3 putaran). Masih gagal → lanjut dengan peringatan, aturan terbaik disimpan; hasil ditandai "belum teruji".
5. **SCRAPE + FILTER 4 LAPIS** — tarik post (keyword user + varian) → saring → gabung semua query → buang duplikat `post_id` → **master dataset**.
6. **EVALUASI ULANG (LLM gate)** — tiap post dinilai: `is_relevan_llm` YA/TIDAK, `skor_relevansi`, `alasan_review_llm`. Post TIDAK relevan dibuang dari master **tapi disimpan** ke `contoh_negatif.json` (umpan balik run berikutnya).

---

## 4. STRUKTUR FOLDER

```text
D:\DKIS_MONITORING_FACEBOOK_TIKTOK\
├ main.py                  launcher: menu / --tiktok / --facebook / --semua (subprocess per platform)
├ .env                     APIFY_TOKEN, LLMKITA_API_KEYS, LLMKITA_BASE_URL, LLMKITA_MODEL
├ .env.example
├ requirements.txt         requests, python-dotenv
├ DESAIN.md                dokumen ini
├ README.md                panduan pakai (ditulis nanti)
│
├ kaidah\
│   └ kota_cirebon.json    LAPIS KOTA — permanen, buatan manusia (bukan LLM)
│
├ topik\
│   └ <slug_topik>\        mis. jalan_rusak\
│       ├ topik.json          input terkunci: topik, tanggal, daftar contoh
│       ├ contoh.txt          URL + caption yang ditempel user
│       ├ rule_set.json       hasil LLM (kamus topik + bobot + ambang) ← inti sistem
│       ├ uji_mandiri.json    hasil recall test tahap 4
│       └ contoh_negatif.json temuan AI (post yang dinilai TIDAK relevan)
│
├ tiktok\
│   ├ code\   config.py · apify_client.py · evaluator.py · rule_builder.py ·
│   │         llm_reviewer.py · storage.py · main.py
│   ├ post\   <slug_query>\ + gabungan_terfilter\
│   ├ history\
│   └ comment\ (kosong — nanti)
│
└ facebook\ (struktur sama; actor & cara ambil caption berbeda)
```

---

## 5. FORMAT FILE

### 5.1 `kaidah/kota_cirebon.json` — VERSI 2 (sederhana, ramah ASN)

Prinsipnya cuma 3 daftar: **(1) wilayah kita · (2) jalan di kota kita · (3) penyaring**. Semua nama resmi.

| Bagian | Isi | Perannya |
|--------|-----|----------|
| `1_wilayah_kota` | 5 kecamatan (harjamukti, kejaksan, kesambi, lemahwungkuk, pekalipan) + 18 nama kelurahan + frasa "kota cirebon"/"pemkot cirebon"/… | **WAJIB**: minimal 1 nama di sini ATAU 1 frasa → post dianggap wilayah kita |
| `2_jalan_kota` | ±64 nama jalan khas (siliwangi, tuparev, kalitanjung, kanggraksan, pasuketan, …) + `nama_umum_perlu_kata_jalan` (merdeka, benteng, bahagia, talang, elang) | **Nama jalan KHAS ikut dihitung sebagai sinyal wilayah kuat** (nama itu hanya ada di Cirebon, mis. "Tuparev"), karena banyak post menyebut jalan tanpa nama kecamatan. Nama umum hanya dihitung kalau dekat kata "jalan"/"jl" |
| `3_penyaring` | 40 kecamatan Kabupaten Cirebon + `pengecualian` (gunungjati/sumber/babakan) · `kata_terlarang` (judi, slot, togel, olshop, …) · `akun_media_lokal` (24 akun media/pemkot) | Kabupaten tanpa sinyal kota → **gugur** · kata terlarang → **gugur** · akun media → **auto-boost** |

Aturan penting:
- Kata **"cirebon" sendirian hanya menambah sedikit nilai**, tidak meloloskan (diputuskan user: Kabupaten diabaikan).
- `gunungjati` dari daftar Kabupaten hanya dihitung kalau ada kata "kecamatan"/"kec." — karena **RSUD Gunung Jati ada di KOTA Cirebon** (Jl. Kesambi 56).
- Semua pencocokan teks: huruf kecil, **per kata (word boundary)** untuk daftar penyaring.

*(Versi 1 yang memakai daftar landmark campur (CSB, Grage, Bima, Kebon Pelok, dst.) DIBUANG 17 Sep — dinilai terlalu rumit untuk dirawat ASN.)*

### 5.2 `topik/<slug>/contoh.txt` (ditempel user)

Satu baris satu video. Format: `URL | caption + hashtag apa adanya`

```text
https://www.tiktok.com/@akun/video/123 | jalan rusak parah di depan CSB, aspal amblas #cirebon
https://www.facebook.com/permalink.php?story_fbid=456 | Jalan berlubang di Harjamukti sudah 2 bulan, warga keluhkan #KotaCirebon
```

### 5.3 `topik/<slug>/rule_set.json` (hasil LLM)

```json
{
  "topik": "jalan rusak",
  "slug": "jalan_rusak",
  "versi": 1,
  "dibuat": "2026-09-17T10:12:00Z",
  "contoh_dipakai": ["<url1>", "<url2>", "<url3>"],
  "varian_query": ["jalan rusak Cirebon", "aspal amblas Cirebon", "jalan berlubang Kota Cirebon"],
  "ambang_skor": 0.75,
  "wajib_minimal_lokasi": true,
  "kata_inti":    [{"kata": "jalan rusak", "bobot": 0.30}, {"kata": "aspal amblas", "bobot": 0.30}, {"kata": "berlubang", "bobot": 0.25}],
  "sinonim_slang": [{"kata": "amblas", "bobot": 0.15}, {"kata": "jebol", "bobot": 0.15}, {"kata": "kubangan", "bobot": 0.10}],
  "pelaku":       [{"kata": "dinas pu", "bobot": 0.10}, {"kata": "kontraktor", "bobot": 0.10}, {"kata": "pemkot", "bobot": 0.05}],
  "pemicu":       [{"kata": "parah", "bobot": 0.05}, {"kata": "bahaya", "bobot": 0.05}, {"kata": "keluhan", "bobot": 0.05}],
  "pengecualian": [{"kata": "jalan-jalan", "alasan": "arti rekreasi"},
                   {"kata": "rusak", "wajib_ada_konteks": ["jalan", "aspal"]}],
  "catatan_llm": "Caption contoh memakai kata 'amblas' dan 'berlubang'; hashtag #cirebon dipakai konsisten."
}
```

### 5.4 `uji_mandiri.json`

```json
{
  "topik": "jalan_rusak",
  "putaran": 2,
  "hasil": [{"url": "<url1>", "skor": 1.0, "lolos": true, "alasan": "kata inti + lokasi cocok"},
            {"url": "<url2>", "skor": 0.85, "lolos": true, "alasan": "sinonim + kelurahan Harjamukti"}],
  "semua_lolos": true,
  "catatan": "Semua contoh tertangkap pada putaran ke-2."
}
```

### 5.5 `contoh_negatif.json` (umpan balik otomatis)

```json
[{"url": "<url>", "caption": "...", "alasan_llm": "Bahas jalan rusak di Kabupaten Cirebon, bukan Kota.", "tanggal": "2026-09-17"}]
```
Dibaca LLM saat membuat/revisi aturan topik yang sama → filter makin presisi tiap run.

---

## 6. FILTER 4 LAPIS + CARA HITUNG SKOR

Rumus (sederhana & bisa diaudit):

```
skor_rules = min(1.0, Σ bobot setiap kata unik dari rule_set yang cocok dengan teks)
LOLOS  bila  skor_rules >= ambang_skor  DAN  minimal 1 sinyal wilayah Kota Cirebon
```

Contoh: caption memuat "aspal amblas" (0,30) + "berlubang" (0,25) + "dinas pu" (0,10) + "parah" (0,05) = **0,70** → belum lolos (ambang 0,75). Tambah "jebol" (0,15) → 0,85 → lolos.
Bobot diatur LLM dengan pedoman: kata inti 0,25–0,35 · sinonim/slang 0,10–0,20 · pelaku 0,05–0,15 · pemicu 0,05.

Urutan lapis:
1. **Time-window** — tanggal upload (WIB, UTC+7) harus ≥ batas bawah & ≤ batas atas. Post tanpa tanggal = dilewatkan (bukan digugurkan).
2. **Kata terlarang** — `3_penyaring.kata_terlarang` (cocok per kata) → gugur.
3. **Lapis kota** — tiga jalur: (a) ada sinyal **kuat** (nama `1_wilayah_kota`/frasa ATAU nama jalan **khas** `2_jalan_kota`) → lanjut; (b) hanya wilayah **Kabupaten** → gugur; (c) hanya menyebut **"cirebon"** → **tidak dibuang**, ditandai `wilayah_lemah = Ya`, tetap harus lolos ambang skor di lapis 4, dan diserahkan ke AI gate untuk keputusan akhir. Akun media lokal → auto-boost (skor 1.0).
4. **Aturan topik** — rumus skor di atas + `pengecualian`.

Catatan teknis: TikTok tidak punya filter tanggal/lokasi di actor → penyaringan tanggal **lokal** (seperti kode lama), dan varian query harus memuat "Cirebon". Facebook punya `location` + `startDate`/`endDate` di actor → dipakai langsung.

---

## 7. PROMPT LLM (2 tugas, model dari `.env`)

**A. Induksi aturan** — input: caption+hashtag 3–5 contoh, ringkasan `kota_cirebon.json` (§1 wilayah + §2 jalan), daftar `contoh_negatif.json`, dan (kalau putaran revisi) contoh yang belum tertangkap. Output: JSON `rule_set.json` persis skema 5.3. Pesan kunci: "kata harus benar-benar muncul di caption contoh; jangan mengarang kata yang tidak ada."

**B. Gate evaluasi** — input: daftar post (id, akun, tanggal, caption). Output: JSON array `{id, is_relevan, skor_relevansi, alasan}`. Prompt menyebut: topik X, wilayah Kota Cirebon, dan daftar penanda Kabupaten supaya salah-daerah bisa dibedakan.

Ketentuan teknis (pelajaran AMS_V2):
- Multi-key rotation (`LLMKITA_API_KEYS`, dipisah koma) + `timeout=120`.
- Model default `deepseek-v4-flash` (alias `deepseek-v4-pro` RUSAK di gateway).
- Kalau semua key gagal → heuristic fallback, tapi **ditandai** di `alasan_review_llm` (jangan diam-diam dianggap terverifikasi).
- Prompt besar dipecah per batch (jangan 1 request untuk 100+ post).

---

## 8. PERINTAH CLI (rencana)

```powershell
# menu interaktif (paling ramah)
python main.py

# satu platform saja
python main.py --tiktok   --topik "jalan rusak" --day 30
python main.py --facebook --topik "jalan rusak" --month 1

# dua platform sekaligus
python main.py --semua    --topik "banjir" --from 2026-08-01 --to 2026-09-17

# uji aturan saja, TANPA scrape (hemat kredit)
python main.py --tiktok   --topik "jalan rusak" --dry-run

# aturan lama dipakai lagi + filter rule-based saja (tanpa LLM gate)
python main.py --tiktok   --topik "jalan rusak" --day 30 --no-llm
```
Flag lain: `--contoh <file>` (kalau tidak mau isi interaktif), `--max 50` (hasil per query), `--token` (override Apify).

---

## 9. BIAYA & PENGAMAN

- Estimasi biaya **ditampilkan sebelum eksekusi**; setiap run mencatat `usageTotalUsd` dari Apify → tarif nyata dikalibrasi dari run uji pertama, lalu disimpan di config.
- Batas default: **50 hasil/query** × (1 + 3–5 varian) per platform.
- `--dry-run` untuk uji aturan tanpa kredit.
- Tahap 1 tidak menyentuh komentar → tidak ada biaya komentar sama sekali.

---

## 10. BELUM DIPUTUSKAN (sengaja ditunda)

1. Scraping komentar + sentimen IndoBERTweet (butuh `transformers` + `torch`, ~2 GB).
2. Kategori isu (`kategori_isu`) + kolom `perlu_tindak_lanjut` / `urgensi`.
3. Mode "temukan tren sendiri" (hashtag #cirebon, Threads) — sekarang murni keyword user.
4. Database (SQLite) untuk tren antar waktu — sekarang file per run.
5. Ringkasan naratif / grafik untuk pimpinan — sekarang CSV/JSON saja.

---

## 11. URUTAN PENGERJAAN

1. ✅ **SELESAI 17 Sep** — Kerangka folder + `kaidah/kota_cirebon.json` + `.env` + `.env.example` + `requirements.txt` + `.gitignore`.
2. ✅ **SELESAI 17 Sep** — Modul TikTok lengkap (7 file di `tiktok/code/`), urutan pengerjaan: config → evaluator → rule_builder → llm_reviewer → apify_client → storage → main.
   - `config.py` — folder, actor, batas biaya, pembacaan .env, `slugkan`, `tentukan_rentang_tanggal`
   - `evaluator.py` — filter 4 lapis + `hitung_skor_topik` (dipakai juga oleh uji mandiri) + keranjang wilayah lemah
   - `rule_builder.py` — validasi seed, prompt induksi, normalisasi aturan, uji mandiri + revisi (maks 3 putaran), tulis `rule_set.json` & `uji_mandiri.json`
   - `llm_reviewer.py` — transport `panggil_llm_json` (rotasi key, timeout 120) + gate evaluasi berbatch + fallback bertanda FALLBACK
   - `apify_client.py` — pencarian `clockworks~tiktok-scraper` per kata kunci + validasi bentuk data + biaya `usageTotalUsd`
   - `storage.py` — kolom master (22 kolom, ada `topik` & `wilayah_lemah`), dedup `post_id`, master + history + `contoh_negatif.json`
   - `main.py` — menu interaktif + CLI, orkestrasi 6 tahap, gerbang validasi contoh, `--dry-run`
   - Sudah diuji tanpa biaya: 8 kasus filter, saring+master+dedup pakai data contoh, dan 2 gerbang penolakan (caption hashtag-saja & tanpa contoh).
   - **Belum diuji**: panggilan LLM sungguhan (induksi aturan + gate) dan run Apify sungguhan — menunggu user menjalankan sendiri.
3. Uji dengan **1 topik nyata** (mis. "jalan rusak" atau "banjir") → audit manual 10 hasil.
4. Modul Facebook: adaptasi (actor berbeda, caption dari `postText`, hashtag dari regex).
5. ✅ **Launcher root `main.py` SELESAI 17 Sep** (menu + `--tiktok` / `--facebook` / `--semua`, argumen diteruskan ke modul platform); history & master output sudah ditangani `tiktok/code/storage.py`.
6. Baru lanjut ke bagian yang ditunda (poin 10).

---

## 12. RISIKO & PENANGANAN

| Risiko | Penanganan |
|--------|-----------|
| Caption contoh cuma hashtag → aturan ngawur | Seed wajib bercaption (≥5 kata bermakna), kalau tidak → ditolak |
| Post Kabupaten Cirebon ikut masuk | Daftar 40 kecamatan Kabupaten + wajib sinyal Kota Cirebon |
| Noise judi/olshop/game | `kata_terlarang` (per kata) |
| Topik sempit → hasil nol | Ambang bisa diturunkan di `rule_set.json`; varian query ditambah |
| Filter meleset (salah buang / salah ambil) | `alasan_rules` + `alasan_review_llm` per post bisa diaudit; `contoh_negatif.json` memperbaiki run berikutnya |
| Kredit Apify habis | Estimasi sebelum run, `--dry-run`, batas `--max` |
| AI tidak jalan (key/IP bermasalah) | Ditandai jelas "FALLBACK" — tidak dianggap terverifikasi |
| Nama wilayah/akun media perlu dirawat ASN | Semua di 1 file JSON, bagian bernomor + `guna` di tiap bagian, tanpa kode program |

---

## 13. RIWAYAT PERUBAHAN DOKUMEN

- **17 Sep 2026 (siang)** — Dokumen dibuat: keputusan ronde 1–5 (wilayah Kota saja, POST dulu, seed 3–5 URL caption manual, rule_set per topik, tanggal preset hari ini, CSV/JSON per run, kode per platform).
- **17 Sep 2026 (sore)** — Lapis kota diganti dari daftar landmark campur → **versi 2 berbasis nama resmi** (5 kecamatan, 22 kelurahan, ±64 nama jalan, 40 kecamatan Kabupaten). Alasan: file ini akan dibaca/dirawat ASN, jadi harus memakai nama yang dikenali umum. Sumber: Wikipedia (daftar kecamatan/kelurahan Kota Cirebon) + JDIH Kabupaten Cirebon.
- **17 Sep 2026 (sore, lanjutan)** — Ditambah **keranjang "wilayah lemah"** (keputusan #16) setelah uji filter: post relevan seperti "jalan rusak parah, aspal amblas #cirebon" sempat terbuang. Sekarang post seperti itu ditandai `wilayah_lemah = Ya` dan diserahkan ke AI gate.
- **17 Sep 2026 (sore, kode)** — 4 modul TikTok selesai: `config.py`, `evaluator.py`, `rule_builder.py`, `llm_reviewer.py` (sisa: apify_client, storage, main). Uji 8 kasus filter lulus: penjagaan "RSUD Gunung Jati ≠ Kabupaten", akun `persistenteats` tidak dianggap media, dan tabel Kabupaten + kata "cirebon" tetap gugur.
- **18 Sep 2026 (PAGI-SIANG) — REVISI BESAR: kaidah disederhanakan, skor bobot dibuang.**
  Pemicu: user melaporkan hasil run 17 Sep "Becak Listrik Kota Cirebon" hanya 12 video, padahal
  saat scroll manual di TikTok ada 40+ video relevan.
  Cara ukur (biaya Rp0): 5 dataset Apify run 17 Sep ditarik ulang (baca dataset = gratis),
  103 video unik dijalankan ulang ke `evaluator.py` versi lama → terbukti 91 gugur:
  lapis skor 29, lapis kota 36, tanggal 22, caption kosong 4. Recall = 12/42 = 29%.
  4 uji prompt berikutnya (total 15 panggilan LLM, tanpa Apify):
  (1) gerbang 1 kata + gate AI → 42 YA / 2 RAGU / 1 TIDAK;
  (2) 16 kasus sulit (Kabupaten yang menyebut "cirebon", kota lain, iklan sepeda listrik,
      dialek) → 15 benar;
  (3) 12 caption sintetis dengan nama kecamatan Kabupaten → 12/12 benar DENGAN dan TANPA daftar
      Kabupaten → daftar itu tidak diperlukan;
  (4) 2 putaran ulang → jawaban sama 44/45 (98%).
  Lalu prompt versi 2 (caption utuh tanpa potong 300 karakter, topik-hanya-hashtag → RAGU,
  tambah contoh netizen pendek, ciri dialek) → 40 YA + 4 RAGU + 1 TIDAK, 0 salah-terima,
  dan dua kasus dialek ("ampiyum", "ci Abah") berhasil dikenali.
  Kode ditulis ulang 18 Sep: `evaluator.py` (451 → 245 baris, tanpa skor/ambang/wilayah),
  `rule_builder.py` (615 → 380 baris, tanpa induksi aturan & uji mandiri ambang),
  `llm_reviewer.py` (prompt gate global + YA/TIDAK/RAGU), `storage.py` (kandidat + ditolak +
  laporan corong + data mentah + run_id), `main.py` (alur 5 tahap), `kaidah/kota_cirebon.json`
  (v3: 1 kata gerbang), launcher root (teks menu).
  Uji offline 2 tahap: tiruan (LLM+Apify palsu) dan asli (LLM asli, data tersimpan) →
  250 item → 45 kandidat → 40 YA / 1 TIDAK / 4 RAGU, semua file & laporan corong terbentuk.
  Bug baru yang ketahuan & dibereskan: (a) `contoh.txt` tidak boleh multi-baris (caption
  ber-newline bikin contoh berikutnya terbaca tanpa URL) — sekarang caption dirapatkan saat
  disimpan dan baris tanpa "http" dilewati; (b) gate harus menerima daftar contoh secara
  eksplisit (dulu hanya membaca dari file topik → bisa jalan TANPA contoh alias diam-diam lemah).
