# -*- coding: utf-8 -*-
"""
bot_config.py
=============
Pusat setelan BOT TELEGRAM untuk Scrapper Instagram Media Kota Cirebon.

Bedanya dengan cirebon_media/code/config.py:
- config.py        -> setelan MESIN SCRAPER (actor Apify, daftar akun, path hasil)
- bot_config.py    -> setelan PINTU MASUK TELEGRAM (token bot, siapa yang boleh
                      memakai, batas aman, cara memanggil scraper, estimasi biaya)

PRINSIP PENTING
---------------
1. Bot TIDAK memakai LLM. Bot hanya bisa satu hal: menjalankan scraper IG dan
   mengirim hasilnya. Karena itu semua batas (hari, jumlah post, panjang antrean)
   harus ditulis tegas di sini, bukan diserahkan ke kecerdasan AI.
2. Bot TIDAK mengimpor modul scraper secara langsung (tidak "import storage").
   Bot memanggil `main.py` scraper sebagai PROSES TERPISAH. Alasannya:
   a) modul scraper butuh transformers + torch yang hanya ada di Python Windows;
   b) kalau scraper crash, bot tetap hidup;
   c) dua proses tidak saling mengunci nama file (config.py ada di dua tempat).
3. Nama kunci di file .env bot sengaja diberi awalan BOT_ supaya TIDAK bertabrakan
   dengan kunci milik Hermes (TELEGRAM_BOT_TOKEN). Memakai token Hermes untuk bot
   ini akan gagal: satu token Telegram hanya boleh ditarik satu proses (error 409
   Conflict), sedangkan gateway Hermes sudah memakainya.

Cara pakai:
    Salin instagram/bot/.env.example menjadi instagram/bot/.env, isi tokennya.
    Lalu: python main_bot.py   (dari folder instagram/bot)
"""

import json
import os
import re
from pathlib import Path

# ============================================================
# 1. LOKASI FOLDER (dihitung dari posisi file ini, bukan dari "sedang di mana")
# ============================================================
FOLDER_BOT = Path(__file__).resolve().parent          # bot
FOLDER_ROOT = FOLDER_BOT.parent                        # root D:\DKIS_MONITORING_FACEBOOK_TIKTOK
FOLDER_INSTAGRAM = FOLDER_ROOT / "instagram"           # instagram
FOLDER_IG = FOLDER_INSTAGRAM / "cirebon_media"         # instagram/cirebon_media
FOLDER_IG_CODE = FOLDER_IG / "code"                    # tempat main.py scraper
FOLDER_IG_POST = FOLDER_IG / "post"                    # hasil post
FOLDER_IG_COMMENT = FOLDER_IG / "comment"              # hasil komentar
FOLDER_HISTORY = FOLDER_IG / "history"                 # log scraper
FOLDER_LOG = FOLDER_BOT / "log"                        # log bot sendiri

# Lokasi folder scraper Akun OPD / Pemerintah Kota Cirebon
FOLDER_OPD = FOLDER_INSTAGRAM / "cirebon_opd"
FOLDER_OPD_CODE = FOLDER_OPD / "code"
FOLDER_OPD_DATA = FOLDER_OPD / "data"
FOLDER_OPD_POST = FOLDER_OPD / "data"       # kompatibilitas
FOLDER_OPD_RANKING = FOLDER_OPD / "data"    # kompatibilitas

# Lokasi folder scraper Isu TikTok Kota Cirebon
FOLDER_TIKTOK = FOLDER_ROOT / "tiktok"
FOLDER_TIKTOK_CODE = FOLDER_TIKTOK / "code"
FOLDER_TIKTOK_POST = FOLDER_TIKTOK / "post"
FOLDER_TIKTOK_COMMENT = FOLDER_TIKTOK / "comment"
FOLDER_TIKTOK_HISTORY = FOLDER_TIKTOK / "history"

# Lokasi folder scraper Isu Facebook Kota Cirebon
FOLDER_FACEBOOK = FOLDER_ROOT / "facebook"
FOLDER_FACEBOOK_CODE = FOLDER_FACEBOOK / "code"
FOLDER_FACEBOOK_POST = FOLDER_FACEBOOK / "post"
FOLDER_FACEBOOK_COMMENT = FOLDER_FACEBOOK / "comment"
FOLDER_FACEBOOK_HISTORY = FOLDER_FACEBOOK / "history"

for _folder in (FOLDER_LOG, FOLDER_OPD_DATA,
                FOLDER_TIKTOK_POST, FOLDER_TIKTOK_COMMENT, FOLDER_TIKTOK_HISTORY,
                FOLDER_FACEBOOK_POST, FOLDER_FACEBOOK_COMMENT, FOLDER_FACEBOOK_HISTORY):
    _folder.mkdir(parents=True, exist_ok=True)

SKRIP_SCRAPER = FOLDER_IG_CODE / "main.py"             # scraper media massa
SKRIP_SCRAPER_OPD = FOLDER_OPD_CODE / "main.py"         # scraper akun OPD
SKRIP_SCRAPER_TIKTOK = FOLDER_TIKTOK_CODE / "main.py"   # scraper isu TikTok
SKRIP_SCRAPER_FACEBOOK = FOLDER_FACEBOOK_CODE / "main.py"  # scraper isu Facebook


# ============================================================
# 2. RAHASIA (BACA DARI .env MILIK BOT SENDIRI)
# ============================================================
PATH_ENV_BOT = FOLDER_BOT / ".env"


def _baca_env(nama_kunci: str, default: str = "") -> str:
    """
    Ambil nilai dari variabel OS; kalau kosong, baca langsung dari file .env bot.
    Dibaca manual (tanpa library) supaya bot bisa jalan walau python-dotenv
    belum dipasang di mesin yang menjalankan bot.
    """
    nilai = (os.environ.get(nama_kunci) or "").strip()
    if nilai:
        return nilai

    if PATH_ENV_BOT.exists():
        try:
            for baris in PATH_ENV_BOT.read_text(encoding="utf-8").splitlines():
                baris = baris.strip()
                if not baris or baris.startswith("#") or "=" not in baris:
                    continue
                kunci, _, isi = baris.partition("=")
                if kunci.strip() == nama_kunci:
                    isi = isi.strip().strip('"').strip("'")
                    if isi:
                        return isi
        except Exception:
            pass
    return default


def _baca_daftar_id(nama_kunci: str) -> list:
    """Baca daftar Telegram user ID yang dipisah koma. Contoh: 111111,222222"""
    mentah = _baca_env(nama_kunci, "")
    hasil = []
    for potong in mentah.split(","):
        potong = potong.strip()
        if not potong:
            continue
        try:
            angka = int(potong)
        except ValueError:
            continue          # ID yang bukan angka diabaikan, bukan bikin bot mati
        if angka not in hasil:
            hasil.append(angka)
    return hasil


TOKEN_BOT = _baca_env("BOT_TELEGRAM_TOKEN", "")
ALLOWED_USER_IDS = _baca_daftar_id("BOT_ALLOWED_USER_IDS")
ADMIN_USER_IDS = _baca_daftar_id("BOT_ADMIN_USER_IDS")


# ============================================================
# 3. MESIN PYTHON UNTUK SCRAPER
# ============================================================
# Modul scraper butuh transformers + torch (langkah IndoBERTweet), dan itu hanya
# terpasang di Python Windows. Kalau bot dijalankan dari WSL/Linux, bot tetap bisa
# memanggil Python Windows lewat path /mnt/c/...
KANDIDAT_PYTHON_SCRAPER = [
    _baca_env("BOT_PYTHON_SCRAPER", ""),   # paling utama: diisi manual di .env
    "/mnt/c/Python314/python.exe",         # WSL -> Python Windows
    r"C:\Python314\python.exe",            # kalau bot dijalankan dari Windows
]

PYTHON_SCRAPER = ""
for _kandidat in KANDIDAT_PYTHON_SCRAPER:
    if _kandidat and Path(_kandidat).exists():
        PYTHON_SCRAPER = _kandidat
        break


# ============================================================
# 4. BATAS AMAN (tempat menahan kesalahan & pemborosan)
# ============================================================
HARI_MIN = 1
HARI_MAKS = 30          # DITIMPA di bagian 5 dari config.py scraper (sekarang 365, sesuai keputusan user)
TOP_MIN = 1
TOP_MAKS = 5            # 5 post teratas per akun sudah lebih dari cukup untuk dipantau
MAKS_POST_BAWAAN = 300  # DITIMPA di bagian 5 dari config.py scraper
MAKS_POST_PLAFON = 1000 # DITIMPA di bagian 5 dari config.py scraper
MAKS_KOMENTAR_PER_POST = 100   # DITIMPA di bagian 5 dari config.py scraper
MAKS_KOMENTAR_PLAFON = 500     # DITIMPA di bagian 5 dari config.py scraper
# Pilihan tombol batas komentar per post. Makin kecil = makin cepat & murah.
# (Sejak 24 Sep 2026 tahap penilaian oleh LLM dilepas, jadi lama job ditentukan
#  oleh Apify + pembacaan komentar dengan model lokal — lihat bagian 6b.)
PILIHAN_KOMENTAR_PER_POST = (50, 100, 200)

MAKS_JOB_ANTREAN = 3            # total job menunggu di seluruh bot
MAKS_JOB_AKTIF_PER_USER = 1     # 1 orang tidak boleh menumpuk job
TIMEOUT_JOB_DETIK = 5400        # 90 menit; lebih dari ini dianggap macet
MAKS_PESAN_PROGRES = 300         # batas pembaruan pesan progres.
#   Dinaikkan dari 40 pada 22 Sep 2026: sejak ada DETAK (progres diperbarui tiap
#   10 detik walau tidak ada peristiwa), batas 40 akan tercapai di tengah job
#   panjang dan user kembali buta. 300 ≈ 50 menit job. Ini hanya jaring pengaman.
PANJANG_MAKS_KETERANGAN = 60    # keterangan yang diisi user (misal nama akun)

PANJANG_TELEGRAM = 4096         # batas keras satu pesan Telegram
PANJANG_CAPTION_FILE = 1024     # batas keterangan saat mengirim file

# ============================================================
# ALIRAN LOG KE TELEGRAM (permintaan user 22 Sep 2026)
# ============================================================
# Setiap baris keluaran scraper dikirim ke chat, dikelompokkan agar tidak membanjiri
# (Telegram membatasi ±1 pesan per detik per chat). Tujuannya: user SELALU tahu proses
# masih hidup, sedang di tahap apa, dan apa yang sedang terjadi — tanpa perlu menebak.
KIRIM_LOG_KE_TELEGRAM = (_baca_env("BOT_KIRIM_LOG", "1") or "1").strip() not in ("0", "false", "tidak")
LOG_INTERVAL_DETIK = int(_baca_env("BOT_LOG_INTERVAL_DETIK", "4") or 4)   # jeda minimal antar pesan log
#   ^ Diturunkan dari 6 ke 4 detik pada 22 Sep 2026: user ingin catatan proses tetap
#     mengalir rapat supaya tidak ada masa "diam" yang bikin bingung. Isinya sendiri
#     sudah disaring (lihat job_runner._rapikan_baris_log), jadi lebih rapat != lebih ramai.
LOG_JEDA_MINIMAL_DETIK = 2      # batas keras: jangan kirim log lebih cepat dari ini
LOG_MAKS_BARIS_PER_PESAN = int(_baca_env("BOT_LOG_MAKS_BARIS", "18") or 18)
LOG_MAKS_PESAN_PER_JOB = int(_baca_env("BOT_LOG_MAKS_PESAN", "250") or 250)
#   ^ jaring pengaman supaya job sangat panjang tidak mengirim ribuan pesan.

# --- MODE ALIRAN LOG (permintaan user 22 Sep 2026) ---
# Keluhan: "daripada kirim keluaran sampai spam, mending pesan yang diperbarui otomatis
# ini menjadi keluaran yang di-update terus menerus".
# "satu_pesan" (bawaan): keluaran scraper TIDAK dikirim sebagai pesan terpisah. Beberapa
#   baris terakhir ditampilkan DI DALAM pesan progres yang diperbarui terus-menerus,
#   sehingga chat tetap rapi. Berkas log mentah tetap dikirim lengkap di akhir job.
# "terpisah": cara lama (tiap kelompok baris jadi pesan sendiri).
# Diatur lewat .env: BOT_LOG_MODE=satu_pesan / terpisah
LOG_SATU_PESAN = (_baca_env("BOT_LOG_MODE", "satu_pesan") or "satu_pesan").strip().lower() \
    not in ("terpisah", "pesan_terpisah", "0", "false", "tidak")
LOG_TAIL_BARIS = int(_baca_env("BOT_LOG_TAIL", "20") or 20)
#   ^ jumlah baris keluaran scraper terakhir yang ditampilkan di pesan progres.
LOG_PANJANG_BARIS = int(_baca_env("BOT_LOG_PANJANG_BARIS", "110") or 110)
#   ^ panjang maksimum satu baris di pesan progres (supaya tidak ada baris raksasa).


# ============================================================
# 5. DAFTAR AKUN MEDIA (DIAMBIL DARI MODUL SCRAPER -> SATU SUMBER KEBENARAN)
# ============================================================
# Supaya daftar akun tidak pernah berbeda antara bot dan scraper, bot membaca
# daftar yang sama dari cirebon_media/code/config.py.
import sys

if str(FOLDER_IG_CODE) not in sys.path:
    sys.path.insert(0, str(FOLDER_IG_CODE))

try:
    import config as config_scraper          # noqa: E402
    DAFTAR_MEDIA = [tuple(a) for a in config_scraper.DAFTAR_AKUN]   # (username, folder, nama)
    KATA_KUNCI_SCRAPER = config_scraper.KATA_KUNCI_FILTER
    MASALAH_IMPOR = ""

    # Batas hari & post diambil dari modul scraper supaya bot dan mesin scraper
    # TIDAK PERNAH berbeda angka. Ubah batas cukup di cirebon_media/code/config.py.
    HARI_MAKS = int(getattr(config_scraper, "HARI_MAKS_SCRAPE", HARI_MAKS))
    MAKS_POST_BAWAAN = int(getattr(config_scraper, "MAKS_POST_DEFAULT", MAKS_POST_BAWAAN))
    MAKS_POST_PLAFON = int(getattr(config_scraper, "MAKS_POST_MAKS", MAKS_POST_PLAFON))
    MAKS_KOMENTAR_PER_POST = int(getattr(config_scraper, "MAKS_KOMENTAR_DEFAULT", MAKS_KOMENTAR_PER_POST))
    MAKS_KOMENTAR_PLAFON = int(getattr(config_scraper, "MAKS_KOMENTAR_PLAFON", 500))
except Exception as error_impor:
    DAFTAR_MEDIA = []
    KATA_KUNCI_SCRAPER = ""
    MASALAH_IMPOR = f"Gagal membaca daftar akun dari modul scraper: {error_impor}"


# ============================================================
# Impor konfigurasi akun OPD / Pemerintah Kota Cirebon
import importlib.util

try:
    path_cfg_opd = FOLDER_OPD_CODE / "config.py"
    spec_opd = importlib.util.spec_from_file_location("cirebon_opd_config", str(path_cfg_opd))
    config_opd = importlib.util.module_from_spec(spec_opd)
    spec_opd.loader.exec_module(config_opd)
    DAFTAR_OPD = [tuple(a) for a in config_opd.DAFTAR_OPD]  # (username, folder, nama, kategori)
    PETA_AKUN_OPD = dict(config_opd.PETA_AKUN_OPD)
except Exception as err_opd:
    DAFTAR_OPD = []
    PETA_AKUN_OPD = {}
    print(f"[BOT] Gagal membaca daftar akun OPD: {err_opd}")

def ambil_apify_token() -> str:
    """
    Token Apify. Dipakai mesin job untuk MEMBATALKAN run di sisi Apify
    (bukan sekadar mematikan proses lokal). Dibaca lewat modul scraper supaya
    hanya ada satu cara pembacaan rahasia di seluruh proyek.
    """
    try:
        return config_scraper.baca_nilai_env("APIFY_TOKEN", "")
    except Exception:
        return _baca_env("APIFY_TOKEN", "")

# Akun yang paling sering dipakai cukup lewat tombol; sisanya user ketik sendiri.
AKUN_TOMBOL = [a[0] for a in DAFTAR_MEDIA]
AKUN_OPD_TOMBOL = [a[0] for a in DAFTAR_OPD]


# ============================================================
# 6. ESTIMASI BIAYA (biar user tahu sebelum menekan "Mulai")
# ============================================================
# Tarif di bawah adalah TARIF SEMENTARA. Cara kalibrasi yang jujur: jalankan 1 kali
# skala kecil, lihat kolom usageTotalUsd dari Apify, lalu perbarui angka di .env.
TARIF_POST_PER_HASIL = float(_baca_env("BOT_TARIF_POST_PER_HASIL", "0.0023") or 0.0023)
TARIF_KOMENTAR_PER_HASIL = float(_baca_env("BOT_TARIF_KOMENTAR_PER_HASIL", "0.0025") or 0.0025)
MAKS_POST_PER_AKUN = 300        # sama dengan resultsLimit di modul scraper
MAKS_KOMENTAR_PER_POST = 100    # sama dengan max_comments_per_post di modul scraper
ESTIMASI_HASIL_POST_PER_AKUN = 120   # asumsi konservatif: ±120 post per akun dalam 30 hari
KURS_USD_IDR = int(_baca_env("BOT_KURS_USD_IDR", "16000") or 16000)


def statistik_komentar_terukur() -> dict:
    """
    Hitung rata-rata & nilai tengah komentar PER POST TERPILIH dari riwayat job sendiri.

    KENAPA ADA (permintaan user 22 Sep 2026):
    Angka "paling banyak" (jumlah akun x post teratas x batas komentar/post) adalah batas
    ATAS yang hampir tidak pernah tercapai — akun media nyatanya hanya menghasilkan
    belasan komentar per post. Menampilkannya sebagai "sekitar 2000 komentar" membuat
    permintaan terasa rancu. Angka NYATA dari riwayat inilah pembanding yang jujur.

    Sumber: history/history_comment.csv (records_inserted / count_top_comment_video).

    Returns: {"median", "rata", "jumlah_data", "sumber"} — nilai 0 kalau belum ada data.
    """
    kosong = {"median": 0.0, "rata": 0.0, "jumlah_data": 0, "sumber": "belum ada riwayat"}
    path = FOLDER_HISTORY / "history_comment.csv"
    if not path.exists():
        return kosong
    try:
        import csv
        per_post = []
        with path.open(encoding="utf-8-sig", newline="") as berkas:
            for baris in csv.DictReader(berkas):
                if (baris.get("status") or "").strip().lower() != "success":
                    continue          # hanya job yang benar-benar berhasil
                try:
                    jumlah = int(baris.get("records_inserted") or 0)
                    pembagi = int(baris.get("count_top_comment_video") or 0)
                except (TypeError, ValueError):
                    continue
                if pembagi > 0 and jumlah > 0:
                    per_post.append(jumlah / pembagi)
        if not per_post:
            return kosong
        per_post.sort()
        tengah = len(per_post) // 2
        median = per_post[tengah] if len(per_post) % 2 else (per_post[tengah - 1] + per_post[tengah]) / 2
        return {
            "median": round(median, 1),
            "rata": round(sum(per_post) / len(per_post), 1),
            "jumlah_data": len(per_post),
            "sumber": f"riwayat {len(per_post)} job yang sudah lewat",
        }
    except Exception:
        return kosong


# ============================================================
# 6b. PERKIRAAN DURASI (biar user tahu harus menunggu berapa lama)
# ============================================================
# CATATAN REVISI 24 Sep 2026 — TAHAP PENILAIAN OLEH LLM SUDAH DILEPAS.
# Perkiraan di bawah HANYA memakai dua tahap yang benar-benar berjalan:
#   1. pengambilan data dari Apify
#   2. pembacaan & penggolongan komentar memakai model lokal (IndoBERTweet)
# Sebelumnya perkiraan ikut menghitung "penilaian AI" ±6,5 detik per komentar dan
# menyebut "3 batch berjalan sekaligus". Angka itu sudah TIDAK BERLAKU lagi dan
# membuat perkiraan waktu jauh lebih lama daripada kenyataan.
#
# Angka pengukuran:
#   - 1 akun perlu ±1,5 menit di Apify untuk menarik postingan
#   - tiap post yang diambil komentarnya ±30 detik
#   - menyiapkan model IndoBERTweet ±4,5 detik (model sudah tersimpan di komputer;
#     angka di sini dibulatkan ke 10 detik supaya tetap aman saat pertama kali jalan)
#   - membaca komentar ±0,14 detik per komentar (model lokal di komputer)
#
# CARA MENGUKUR ULANG (kalau angka ini terasa tidak cocok dengan kenyataan):
#     C:\Python314\python.exe D:\DKIS_MONITORING_FACEBOOK_TIKTOK\instagram\cirebon_media\code\ukur_kecepatan_sentimen.py
#   Skrip itu memakai komentar yang sudah ada (tanpa Apify, tanpa biaya) dan
#   menyarankan angka baru untuk dua baris di bawah ini.
DETIK_PER_AKUN_APIFY = 90
DETIK_PER_POST_KOMENTAR = 30
DETIK_PER_KOMENTAR_SENTIMEN = 0.15
#   ^ terukur 24 Sep 2026: 250 komentar asli (rata-rata 51 karakter) dibaca dalam
#     33,9 detik = 0,136 detik/komentar. Dinaikkan ke 0,15 supaya perkiraan tidak
#     terlalu optimistis.
DETIK_MUAT_MODEL = 10
#   ^ terukur 4,5 detik pada keadaan model sudah tersimpan. Dinaikkan ke 10 detik
#     sebagai kelonggaran saat komputer baru dinyalakan / model belum di cache.

DETIK_LANGKAH_DIINGATKAN = 240
#   ^ Kalau satu langkah sudah berjalan lebih lama dari ini, pesan progres WAJIB
#     menjelaskan sebabnya + memberi pilihan tindakan. Bukan sekadar diam.


def format_durasi(detik: float) -> str:
    """Ubah detik jadi teks yang enak dibaca: '12 menit 5 detik' atau '1 jam 4 menit'."""
    detik = int(max(0, detik))
    menit, sisa = divmod(detik, 60)
    if menit >= 60:
        jam, sisa_menit = divmod(menit, 60)
        return f"{jam} jam {sisa_menit} menit"
    if menit:
        return f"{menit} menit {sisa} detik" if sisa else f"{menit} menit"
    return f"{sisa} detik"


def hitung_perkiraan_durasi(jumlah_akun: int, top_video: int, pakai_komentar: bool,
                            maks_komentar: int = MAKS_KOMENTAR_PER_POST) -> dict:
    """
    Perkiraan durasi job. Dipakai menu konfirmasi DAN pesan mulai job,
    supaya user tahu harus menunggu berapa lama.
    """
    jumlah_akun = max(1, int(jumlah_akun or 1))
    rincian = []

    detik_apify = jumlah_akun * DETIK_PER_AKUN_APIFY
    rincian.append(f"Mengambil daftar postingan: ±{format_durasi(detik_apify)}")
    detik_total = detik_apify

    jumlah_komentar = 0
    jumlah_komentar_nyata = 0
    if pakai_komentar:
        post_komentar = jumlah_akun * max(1, int(top_video or 1))
        batas = max(1, int(maks_komentar or MAKS_KOMENTAR_PER_POST))
        jumlah_komentar = post_komentar * batas
        detik_apify_komentar = post_komentar * DETIK_PER_POST_KOMENTAR
        # Pembacaan komentar memakai model lokal: sekali muat model, lalu per komentar
        # hanya sepersekian detik. Tidak ada layanan internet di tahap ini.
        detik_baca = DETIK_MUAT_MODEL + jumlah_komentar * DETIK_PER_KOMENTAR_SENTIMEN
        rincian.append(f"Mengambil komentar dari postingan terpilih: ±{format_durasi(detik_apify_komentar)}")
        rincian.append(f"Membaca & menggolongkan komentar (paling banyak {jumlah_komentar} komentar): "
                       f"±{format_durasi(detik_baca)}")
        detik_total += detik_apify_komentar + detik_baca

        # Pembanding REALISTIS dari riwayat job sendiri. Tanpa ini, angka "paling banyak"
        # mudah disalahpahami sebagai jumlah yang PASTI diproses.
        stat = statistik_komentar_terukur()
        if stat["median"]:
            per_post_nyata = min(float(stat["median"]), float(batas))
            jumlah_komentar_nyata = int(round(post_komentar * per_post_nyata))
            detik_nyata = jumlah_komentar_nyata * DETIK_PER_KOMENTAR_SENTIMEN
            rincian.append(f"  -> menurut catatan pekerjaan sebelumnya (±{stat['median']:g} komentar/post),")
            rincian.append(f"     biasanya hanya sekitar {jumlah_komentar_nyata} komentar: "
                           f"±{format_durasi(detik_nyata)}")

    return {
        "total_detik": detik_total,
        "total_teks": format_durasi(detik_total),
        "jumlah_komentar": jumlah_komentar,
        "jumlah_komentar_nyata": jumlah_komentar_nyata,
        "rincian": rincian,
        "berat": detik_total > 900,        # lebih dari 15 menit = berat
    }


def hitung_estimasi_biaya(jumlah_akun: int, hari: int, top_video: int, pakai_komentar: bool,
                          maks_post: int = None, maks_komentar: int = None) -> dict:
    """
    Hitung perkiraan biaya Apify SEBELUM job jalan.

    Rumusnya sengaja dibuat kasar & konservatif (lebih besar dari kenyataan),
    supaya user tidak kaget di akhir. Angka nyata selalu bisa dilihat di output
    Apify setelah run selesai.
    """
    jumlah_akun = max(1, int(jumlah_akun or 1))
    hari = max(1, int(hari or 1))
    maks_post = int(maks_post or MAKS_POST_BAWAAN)
    maks_komentar = int(maks_komentar or MAKS_KOMENTAR_PER_POST)

    # Post: 1 kali tarikan per akun, dibatasi MAKS_POST per akun
    perkiraan_post_per_akun = min(maks_post, max(10, int(round(ESTIMASI_HASIL_POST_PER_AKUN * min(hari, 365) / 30))))
    biaya_post = jumlah_akun * perkiraan_post_per_akun * TARIF_POST_PER_HASIL

    biaya_komentar = 0.0
    perkiraan_komentar = 0
    if pakai_komentar:
        perkiraan_komentar = jumlah_akun * max(1, int(top_video or 1)) * maks_komentar
        biaya_komentar = perkiraan_komentar * TARIF_KOMENTAR_PER_HASIL

    total_usd = biaya_post + biaya_komentar

    # --- Perkiraan REALISTIS dari riwayat job sendiri (permintaan user 22 Sep 2026) ---
    # Angka di atas adalah BATAS ATAS. Akun media nyatanya hanya menghasilkan belasan
    # komentar per post, jadi biaya nyata biasanya jauh di bawahnya. Angka pembanding ini
    # dihitung dari riwayat (history_comment.csv), bukan ditebak.
    statistik = statistik_komentar_terukur()
    per_post_nyata = 0.0
    if statistik["median"]:
        per_post_nyata = min(float(statistik["median"]), float(maks_komentar))
    jumlah_post_komentar = jumlah_akun * max(1, int(top_video or 1))
    perkiraan_komentar_nyata = int(round(jumlah_post_komentar * per_post_nyata)) if per_post_nyata else 0
    biaya_komentar_nyata = 0.0
    if pakai_komentar and perkiraan_komentar_nyata:
        biaya_komentar_nyata = perkiraan_komentar_nyata * TARIF_KOMENTAR_PER_HASIL
    total_nyata = biaya_post + biaya_komentar_nyata

    def _idr(usd: float) -> int:
        return int(round(usd * KURS_USD_IDR / 500.0) * 500)   # dibulatkan ke Rp500-an

    return {
        "jumlah_akun": jumlah_akun,
        "hari": hari,
        "top_video": max(1, int(top_video or 1)),
        "maks_post": maks_post,
        "maks_komentar": maks_komentar,
        "pakai_komentar": bool(pakai_komentar),
        "perkiraan_post": jumlah_akun * perkiraan_post_per_akun,
        "perkiraan_komentar": perkiraan_komentar,
        "biaya_post_usd": round(biaya_post, 4),
        "biaya_komentar_usd": round(biaya_komentar, 4),
        "total_usd": round(total_usd, 4),
        "total_idr": _idr(total_usd),
        # Pembanding realistis (kosong kalau riwayat belum ada).
        "statistik": statistik,
        "perkiraan_komentar_nyata": perkiraan_komentar_nyata,
        "biaya_komentar_nyata_usd": round(biaya_komentar_nyata, 4),
        "total_nyata_usd": round(total_nyata, 4),
        "total_nyata_idr": _idr(total_nyata),
        "catatan": "Angka ini perkiraan (konservatif). Biaya nyata muncul di output Apify tiap run.",
    }


# ============================================================
# 7. DAFTAR USER YANG BOLEH MEMAKAI (tambahan dari dalam bot)
# ============================================================
# Admin (ID-nya ada di BOT_ADMIN_USER_IDS) boleh menambah/mencabut akses lewat bot.
# Perubahan disimpan di file JSON, BUKAN ditulis ke .env. Alasannya:
#   - .env jadi "kunci induk": admin di sana tidak bisa dihapus dari dalam bot,
#     jadi tidak mungkin terjadi "semua admin terhapus" lalu bot terkunci sendiri.
#   - menulis ulang .env dari kode berisiko merusak isi file rahasia.
PATH_USERS = FOLDER_BOT / "data" / "users.json"


def _isi_users_kosong() -> dict:
    return {"tambahan": [], "ditolak": []}


def _muat_json_users() -> dict:
    if not PATH_USERS.exists():
        return _isi_users_kosong()
    try:
        isi = json.loads(PATH_USERS.read_text(encoding="utf-8"))
        if not isinstance(isi, dict):
            return _isi_users_kosong()
        return {
            "tambahan": [int(x) for x in (isi.get("tambahan") or [])],
            "ditolak": [int(x) for x in (isi.get("ditolak") or [])],
        }
    except Exception:
        return _isi_users_kosong()


def _simpan_json_users(isi: dict):
    PATH_USERS.parent.mkdir(parents=True, exist_ok=True)
    PATH_USERS.write_text(json.dumps(isi, ensure_ascii=False, indent=2), encoding="utf-8")


def daftar_user_efektif() -> list:
    """Gabungan: admin (.env) + allowlist (.env) + tambahan (JSON) - dicabut (JSON)."""
    isi = _muat_json_users()
    gabungan = set(ADMIN_USER_IDS) | set(ALLOWED_USER_IDS) | set(isi["tambahan"])
    return sorted(gabungan - set(isi["ditolak"]))


def tambah_user(user_id: int) -> tuple:
    """Returns: (berhasil, pesan untuk dibalas ke Telegram)."""
    user_id = int(user_id)
    if user_id in daftar_user_efektif():
        return False, f"User {user_id} sudah ada di daftar."
    isi = _muat_json_users()
    isi["tambahan"] = sorted(set(isi["tambahan"]) | {user_id})
    isi["ditolak"] = [x for x in isi["ditolak"] if x != user_id]
    _simpan_json_users(isi)
    return True, f"User {user_id} ditambahkan. Total {len(daftar_user_efektif())} orang."


def hapus_user(user_id: int) -> tuple:
    """Returns: (berhasil, pesan). Admin dari .env sengaja tidak bisa dihapus."""
    user_id = int(user_id)
    if user_id in ADMIN_USER_IDS:
        return False, "Admin dari .env tidak bisa dicabut lewat bot (pengaman supaya bot tidak terkunci)."
    isi = _muat_json_users()
    isi["tambahan"] = [x for x in isi["tambahan"] if x != user_id]
    if user_id in ALLOWED_USER_IDS:
        isi["ditolak"] = sorted(set(isi["ditolak"]) | {user_id})
    _simpan_json_users(isi)
    return True, f"Akses user {user_id} dicabut. Sisa {len(daftar_user_efektif())} orang."


# ============================================================
# 8. VALIDASI MASUKAN USER (biar bot tidak menuruti perintah ngawur)
# ============================================================
POLA_USERNAME = re.compile(r"^[a-z0-9._]{2,30}$")


def bersihkan_username(teks: str) -> str:
    """
    Rapikan username yang diketik user: buang @, spasi, dan tautan profil penuh.
    'https://www.instagram.com/AboutCirebonID/' -> 'aboutcirebonid'
    """
    teks = (teks or "").strip().lower()
    teks = teks.replace("https://", "").replace("http://", "")
    teks = teks.replace("www.instagram.com/", "").replace("instagram.com/", "")
    teks = teks.strip("/").lstrip("@")
    if "/" in teks:                     # kalau ada sisa path, ambil potongan pertama
        teks = teks.split("/")[0]
    return teks.strip()


def validasi_username(teks: str) -> tuple:
    """
    Returns: (ok: bool, username_bersih: str, pesan_galat: str)
    Dipakai bot untuk menolak masukan aneh SEBELUM memanggil Apify (hemat biaya).
    """
    bersih = bersihkan_username(teks)
    if not bersih:
        return False, "", "Username kosong. Contoh yang benar: aboutcirebonid"
    if not POLA_USERNAME.match(bersih):
        return False, bersih, (
            "Username tidak valid. Gunakan huruf/angka/titik/garis bawah, "
            "2-30 karakter. Contoh: aboutcirebonid, fajar.cirebon"
        )
    return True, bersih, ""


def validasi_hari(teks: str) -> tuple:
    """Returns: (ok, angka, pesan_galat). Rentang hari sesuai batas mesin scraper."""
    try:
        angka = int(str(teks).strip())
    except (TypeError, ValueError):
        return False, 0, "Rentang hari harus berupa angka. Contoh: 7"
    if not (HARI_MIN <= angka <= HARI_MAKS):
        return False, 0, f"Rentang hari harus antara {HARI_MIN} sampai {HARI_MAKS} hari."
    return True, angka, ""


def validasi_top_video(teks: str) -> tuple:
    """Returns: (ok, angka, pesan_galat). Jumlah post teratas yang ditarik komentarnya."""
    try:
        angka = int(str(teks).strip())
    except (TypeError, ValueError):
        return False, 0, "Jumlah post harus berupa angka. Contoh: 3"
    if not (TOP_MIN <= angka <= TOP_MAKS):
        return False, 0, f"Jumlah post harus antara {TOP_MIN} sampai {TOP_MAKS}."
    return True, angka, ""


def validasi_maks_post(teks: str) -> tuple:
    """Returns: (ok, angka, pesan_galat). Batas jumlah post yang diambil per akun."""
    try:
        angka = int(str(teks).strip())
    except (TypeError, ValueError):
        return False, 0, f"Batas post harus berupa angka. Contoh: {MAKS_POST_BAWAAN}"
    if not (1 <= angka <= MAKS_POST_PLAFON):
        return False, 0, f"Batas post harus antara 1 sampai {MAKS_POST_PLAFON}."
    return True, angka, ""


def validasi_maks_komentar(teks: str) -> tuple:
    """Returns: (ok, angka, pesan_galat). Batas komentar per post."""
    try:
        angka = int(str(teks).strip())
    except (TypeError, ValueError):
        return False, 0, f"Batas komentar harus berupa angka. Contoh: {MAKS_KOMENTAR_PER_POST}"
    if not (1 <= angka <= MAKS_KOMENTAR_PLAFON):
        return False, 0, f"Batas komentar harus antara 1 sampai {MAKS_KOMENTAR_PLAFON}."
    return True, angka, ""


def user_diizinkan(user_id: int) -> bool:
    """Hanya ID di daftar allowlist yang boleh memakai bot (hemat kuota Apify)."""
    return int(user_id) in daftar_user_efektif()


def user_adalah_admin(user_id: int) -> bool:
    """Admin = ID yang tertulis di BOT_ADMIN_USER_IDS (.env)."""
    return int(user_id) in ADMIN_USER_IDS


# ============================================================
# 8. PEMERIKSAAN SAAT BOT DIAKTIFKAN (biar salah setelan ketahuan di awal)
# ============================================================
def periksa_kesiapan() -> list:
    """
    Returns: daftar masalah (list of str). Kosong = bot siap jalan.
    Dipanggil sekali saat bot start, hasilnya dicetak di terminal.
    """
    masalah = []
    if not TOKEN_BOT:
        masalah.append(
            "BOT_TELEGRAM_TOKEN belum diisi. Buat bot baru di @BotFather, "
            "lalu tulis tokennya di instagram/bot/.env"
        )
    if not ALLOWED_USER_IDS and not ADMIN_USER_IDS:
        masalah.append(
            "Belum ada user yang diizinkan (BOT_ALLOWED_USER_IDS / BOT_ADMIN_USER_IDS kosong). "
            "Kalau dibiarkan, bot akan menolak semua orang."
        )
    if not PYTHON_SCRAPER:
        masalah.append(
            "Python untuk scraper tidak ditemukan. Isi BOT_PYTHON_SCRAPER di .env "
            "(contoh WSL: /mnt/c/Python314/python.exe)."
        )
    if not SKRIP_SCRAPER.exists():
        masalah.append(f"Skrip scraper tidak ditemukan: {SKRIP_SCRAPER}")
    if MASALAH_IMPOR:
        masalah.append(MASALAH_IMPOR)
    return masalah


if __name__ == "__main__":
    # Cek cepat tanpa menjalankan bot: python bot_config.py
    print("FOLDER_BOT        :", FOLDER_BOT)
    print("SKRIP_SCRAPER     :", SKRIP_SCRAPER, "(ada)" if SKRIP_SCRAPER.exists() else "(TIDAK ADA)")
    print("PYTHON_SCRAPER    :", PYTHON_SCRAPER or "(TIDAK DITEMUKAN)")
    print("Token bot terisi  :", "ya" if TOKEN_BOT else "belum")
    print("User diizinkan    :", len(set(ALLOWED_USER_IDS) | set(ADMIN_USER_IDS)), "orang")
    print("Daftar media      :", len(DAFTAR_MEDIA), "akun")
    print("Estimasi 1 akun/7 hari/top 3 + komentar :", hitung_estimasi_biaya(1, 7, 3, True))
    print("Kesiapan          :", periksa_kesiapan() or "SIAP")
