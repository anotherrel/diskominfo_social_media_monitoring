# -*- coding: utf-8 -*-
"""
config.py
=========
File ini berfungsi sebagai pusat pengaturan (konfigurasi) aplikasi.
Semua variabel seperti Token API, lokasi folder, dan daftar akun disimpan di sini.
"""

import os
from pathlib import Path

# Load python-dotenv jika tersedia untuk membaca file .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============================================================
# 1. PENGATURAN LOKASI FOLDER (PATHS)   
# ============================================================
# Folder tempat file config.py ini berada
FOLDER_CODE = Path(__file__).resolve().parent

# Folder utama cirebon_media (satu tingkat di atas folder code)
FOLDER_BASE = FOLDER_CODE.parent

# Folder root proyek (DKIS_MONITORING(AMS_V2))
FOLDER_ROOT = FOLDER_BASE.parent.parent

# Folder penyimpanan dataset hasil postingan
FOLDER_POST = FOLDER_BASE / "post"

# Folder penyimpanan dataset komentar
FOLDER_COMMENT = FOLDER_BASE / "comment"

# Folder penyimpanan riwayat scraping (history)
FOLDER_HISTORY = FOLDER_BASE / "history"

# Pastikan folder post, comment, dan history dibuat jika belum ada
FOLDER_POST.mkdir(parents=True, exist_ok=True)
FOLDER_COMMENT.mkdir(parents=True, exist_ok=True)
FOLDER_HISTORY.mkdir(parents=True, exist_ok=True)


# ============================================================
# 2. PENGATURAN APIFY & KATA KUNCI FILTER
# ============================================================
# ID Actor Apify untuk scraping Instagram Post & Comment
ACTOR_ID = "apify~instagram-scraper"
ACTOR_COMMENT_ID = "apify~instagram-comment-scraper"

# Kata kunci yang WAJIB ada di caption postingan
KATA_KUNCI_FILTER = "Kota Cirebon"

# ------------------------------------------------------------
# Batas rentang hari & jumlah post per akun
# ------------------------------------------------------------
# Dipakai bersama oleh menu interaktif, argumen CLI, DAN bot Telegram
# (instagram/bot/bot_config.py membaca nilai yang sama dari sini).
HARI_MAKS_SCRAPE = 365      # 22 Sep 2026: dibuka dari 30 -> 365 hari atas permintaan user
MAKS_POST_DEFAULT = 300     # resultsLimit bawaan ke actor Apify (per akun)
MAKS_POST_MAKS = 1000       # plafon keras: permintaan di atas ini ditolak, bukan diam-diam dipotong
MAKS_KOMENTAR_DEFAULT = 100 # komentar maksimal per post yang ditarik (bawaan)
MAKS_KOMENTAR_PLAFON = 500  # plafon keras. Angka ini penentu LAMA-TIDAKNYA job:
#   penilaian AI ±5 detik per komentar (terukur 22 Sep 2026), jadi
#   9 post x 100 komentar = 900 komentar ≈ 75 menit hanya untuk penilaian AI.
KOMENTAR_AMBANG_AMBIL_SEMUA = 100
#   22 Sep 2026 (permintaan user): kalau JUMLAH komentar dari semua postingan terpilih
#   kurang dari angka ini, batas per post DIABAIKAN dan semua komentar tiap postingan
#   diambil. Dasarnya: untuk jumlah sekecil itu, batas per post hanya memotong data
#   tanpa menghemat waktu/biaya berarti. Jumlahnya sendiri sudah diketahui dari tahap
#   postingan (kolom comment_count), jadi tidak ada angka yang ditebak.


# ============================================================
# 2b. PENGATURAN LLM (LLM-Kita) — TIDAK DIPAKAI LAGI
# ============================================================
# STATUS 24 Sep 2026: TAHAP PENILAIAN SENTIMEN OLEH LLM SUDAH DILEPAS dari alur kerja.
# Tidak ada satu pun bagian program yang memanggil layanan LLM sekarang:
#   - main.py TIDAK mengimpor llm_reviewer lagi;
#   - storage.py hanya menjalankan IndoBERTweet (model lokal);
#   - bot Telegram juga sudah tidak menghitung/menampilkan apa pun soal LLM.
# Setelan di bawah sengaja DIBIARKAN supaya tidak hilang bila nanti ingin dipakai lagi.
# Memasang ulang tahap LLM = memanggil llm_reviewer lagi dari storage.py, dan menambah
# perkiraan waktunya kembali di bot_config.py (sekarang tidak ikut dihitung).
LLM_BASE_URL_DEFAULT = "https://api.llm-kita.com/api/v1"
LLM_MODEL_DEFAULT = "gpt-5.6-terra"   # 22 Sep 2026: model gateway yang terbukti jalan
LLM_TIMEOUT = 180                     # detik. Dinaikkan dari 120 pada 22 Sep 2026 setelah
#   terbukti batch 25 komentar TIDAK selesai dalam 120 detik (Read timed out di semua key,
#   membuat 1 batch makan 8 menit karena mencoba key satu per satu tanpa guna).
LLM_TEMPERATURE = 0.2
LLM_MAKS_KOMENTAR_PER_BATCH = 25      # ukuran permintaan mula-mula. Kalau timeout, otomatis dipecah.
LLM_KOMENTAR_MIN_PER_REQUEST = 5      # batas terkecil saat permintaan dipecah. Di bawah ini
#   tidak dipecah lagi, supaya tidak lahir puluhan permintaan mini yang justru memperlambat.
LLM_MAKS_PARALEL = 3                  # berapa batch dikerjakan BERSAMAAN (paralel).
#   Dasar angkanya: pengukuran 22 Sep 2026 -> 1 batch 25 komentar ≈ 2 menit 45 detik
#   (±6,5 detik/komentar) dengan gpt-5.6-terra. Itu tahap paling lama di seluruh job.
#   PENTING: paralel di sini TIDAK memerlukan banyak API key. Semua permintaan bersamaan
#   memakai key yang SAMA (kasus nyata: satu penyedia/key saja). API key tambahan hanya
#   dipakai sebagai cadangan kalau key aktif gagal.
#   Kalau penyedia membalas 429 (rate limit) terlalu sering, turunkan angka ini
#   (3 -> 2 -> 1). Angka 1 berarti dikerjakan satu per satu seperti sebelumnya.
LLM_PANJANG_CAPTION = 2000            # caption dikirim utuh sampai batas ini (jangan dipotong pendek)


# ============================================================
# 3. FUNGSI UNTUK MEMBACA NILAI DARI .env
# ============================================================
def baca_nilai_env(nama_kunci, default=""):
    """
    Ambil nilai dari environment OS; kalau kosong, baca langsung dari file .env.

    Dibuat eksplisit begini supaya modul mana pun (termasuk llm_reviewer) tidak
    bergantung pada urutan impor atau pada library python-dotenv.
    Urutan pencarian file .env: folder root proyek -> cirebon_media -> code.
    """
    nilai = (os.environ.get(nama_kunci) or "").strip()
    if nilai:
        return nilai

    for path_env in ((FOLDER_ROOT / ".env"), (FOLDER_BASE / ".env"), (FOLDER_CODE / ".env")):
        if not path_env.exists():
            continue
        try:
            for line in path_env.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                kunci, _, isi = line.partition("=")
                if kunci.strip() == nama_kunci:
                    isi = isi.strip().strip('"').strip("'")
                    if isi:
                        return isi
        except Exception:
            continue
    return default


def ambil_apify_token():
    """Token Apify (untuk actor pencarian & komentar)."""
    return baca_nilai_env("APIFY_TOKEN", "")


def ambil_daftar_api_keys():
    """
    Daftar API key LLM-Kita. Mendukung tiga cara penulisan di .env:
      LLMKITA_API_KEYS=key1,key2,key3
      LLMKITA_API_KEY_1 .. LLMKITA_API_KEY_9
      LLMKITA_API_KEY=key
    Beberapa key dipakai untuk rotasi otomatis kalau ada yang gagal/kuota habis.
    """
    keys = []

    mentah = baca_nilai_env("LLMKITA_API_KEYS") or baca_nilai_env("LLM_API_KEYS")
    if mentah:
        for k in mentah.split(","):
            k = k.strip()
            if k and k not in keys:
                keys.append(k)

    for i in range(1, 10):
        k = baca_nilai_env(f"LLMKITA_API_KEY_{i}") or baca_nilai_env(f"LLM_API_KEY_{i}")
        if k and k not in keys:
            keys.append(k)

    tunggal = baca_nilai_env("LLMKITA_API_KEY") or baca_nilai_env("LLM_API_KEY")
    if tunggal and tunggal not in keys:
        keys.append(tunggal)

    return keys


def normalisasi_base_url(url):
    """Pastikan base URL memakai bentuk resmi LLM-Kita: https://api.llm-kita.com/api/v1"""
    url = (url or LLM_BASE_URL_DEFAULT).rstrip("/")
    if url.endswith("/v1") and not url.endswith("/api/v1"):
        url = url[:-3] + "/api/v1"
    elif "api.llm-kita.com" in url and not url.endswith("/api/v1"):
        url = LLM_BASE_URL_DEFAULT
    return url


def ambil_base_url_llm():
    return normalisasi_base_url(baca_nilai_env("LLMKITA_BASE_URL", LLM_BASE_URL_DEFAULT))


def ambil_model_llm():
    """
    Model LLM dari .env (LLMKITA_MODEL). Bawaan: gpt-5.6-terra.

    Catatan hasil pengujian: nama model TIDAK boleh mengandung spasi (gateway
    membalas HTTP 400), dan alias 'deepseek-v4-pro' RUSAK (membalas kuota acak).
    Karena itu spasi dibuang otomatis di sini dan tidak ada nama ber-spasi di bawaan.
    """
    model = baca_nilai_env("LLMKITA_MODEL", LLM_MODEL_DEFAULT) or LLM_MODEL_DEFAULT
    model = model.strip().split(" ")[0]
    return model


# ============================================================
# 4. DAFTAR AKUN MEDIA KOTA CIREBON YANG DIAWASI (10 AKUN)
# Format tuple: (username_ig, nama_folder, nama_tampilan)
# ============================================================
DAFTAR_AKUN = [
    ("radarcirebon",    "radarcirebon",    "Radar Cirebon"),
    ("aboutcirebonid",  "aboutcirebonid",  "ABOUT CIREBON Media Cirebon"),
    ("cirebonbribin",   "cirebonbribin",   "Cirebon Bribin"),
    ("rctvcirebon",     "rctvcirebon",     "RCTV Radar Cirebon TV"),
    ("cirebon.banget",  "cirebon_banget",  "Cirebon Banget!"),
    ("suaracirebon",    "suaracirebon",    "Harian Suara Cirebon"),
    ("cirebonnews",     "cirebonnews",     "Cirebonnews"),
    ("kabarcirebon",    "kabarcirebon",    "Kabar Cirebon"),
    ("cirebontrending", "cirebontrending", "Cirebon Trending"),
    ("fajar.cirebon",   "fajar_cirebon",   "Fajar Cirebon"),
]
