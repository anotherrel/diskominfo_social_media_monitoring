# -*- coding: utf-8 -*-
"""
config.py (modul TikTok) — VERSI SEDERHANA (18 Sep 2026)
=======================================================
Pusat pengaturan Scrapper Monitoring Isu Kota Cirebon.

PRINSIP PENTING (hasil uji 18 Sep 2026 — lihat DESAIN.md bagian "Revisi 18 Sep")
------------------------------------------------------------------------------
ATURAN TIDAK ADA DI FILE INI DAN TIDAK ADA BOBOT/AMBANG.
- Penyaring wilayah  ->  kaidah/kota_cirebon.json  (1 kata gerbang + petunjuk untuk AI)
- Penentu relevansi  ->  AI (gate), belajar dari 3-5 contoh video yang diisi user
- File ini hanya berisi: lokasi folder, nama actor Apify, batas biaya, pembacaan .env.

Kenapa begitu? Versi lama memakai skor bobot kata + ambang 0,75. Terukur pada 103 video nyata:
hanya 12 lolos, padahal 42 relevan (recall 29%). Setelah gerbang wilayah disederhanakan dan
penilaian diserahkan ke AI, hasilnya 42-44 relevan dari 103, dan kemampuan AI menolak konten
Kabupaten / kota lain / jualan terbukti tepat (uji 16 kasus, 15 benar).

Cara pakai singkat: dari folder tiktok/code jalankan
    python main.py --topik "jalan rusak" --day 30
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

# python-dotenv opsional: kalau belum dipasang, program tetap jalan (asalkan .env sudah di-export)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ============================================================
# 1. LOKASI FOLDER
# ============================================================
# Pola anti-patah: folder dihitung dari posisi file ini, bukan dari "sedang ada di mana"
FOLDER_CODE = Path(__file__).resolve().parent      # .../tiktok/code
FOLDER_BASE = FOLDER_CODE.parent                   # .../tiktok
FOLDER_ROOT = FOLDER_BASE.parent                   # D:\DKIS_MONITORING_FACEBOOK_TIKTOK

FOLDER_KAIDAH = FOLDER_ROOT / "kaidah"             # kata gerbang + petunjuk AI (permanen)
FOLDER_TOPIK = FOLDER_ROOT / "topik"               # 1 folder per topik
FOLDER_POST = FOLDER_BASE / "post"                 # hasil scrape postingan
FOLDER_COMMENT = FOLDER_BASE / "comment"           # DISIAPKAN KOSONG (komentar ditunda)
FOLDER_HISTORY = FOLDER_BASE / "history"           # log tiap run

for _folder in (FOLDER_KAIDAH, FOLDER_TOPIK, FOLDER_POST, FOLDER_COMMENT, FOLDER_HISTORY):
    _folder.mkdir(parents=True, exist_ok=True)

PATH_KAIDAH_KOTA = FOLDER_KAIDAH / "kota_cirebon.json"


# ============================================================
# 2. PLATFORM & ACTOR APIFY
# ============================================================
NAMA_PLATFORM = "facebook"
LABEL_PLATFORM = "Facebook"

# Actor pencarian Facebook & komentar
ACTOR_SEARCH = "apify~facebook-search-scraper"
ACTOR_POSTS = "apify~facebook-posts-scraper"
ACTOR_COMMENTS = "apify~facebook-comments-scraper"


# ============================================================
# 3. BATAS & ESTIMASI BIAYA
# ============================================================
# Batas hasil yang diminta ke actor per kata kunci.
MAKS_HASIL_PER_QUERY = 50

# Dipakai HANYA untuk estimasi sebelum jalan. Angka pasti diambil dari usageTotalUsd tiap run.
TARIF_ESTIMASI_PER_HASIL = 0.004   # USD per hasil pencarian (~$0,003 terukur 17 Sep)

# Pengambilan CAPTION contoh video:
#   True  = user cukup menempel URL, caption diambil otomatis lewat mode 'postURLs' actor
#   False = user wajib menempel sendiri dengan format "URL | caption"
AMBIL_CAPTION_CONTOH_OTOMATIS = True
TARIF_ESTIMASI_PER_VIDEO_URL = 0.005   # USD per video saat mengambil caption dari URL


# ============================================================
# 4. ATURAN VALIDASI INPUT (dipakai rule_builder & main)
# ============================================================
MIN_KATA_CAPTION = 2        # caption contoh wajib >= 2 kata bermakna (fleksibel untuk gaya netizen)
MIN_CONTOH = 1              # minimal 1 contoh video; disarankan 3-5
SARAN_JUMLAH_CONTOH = "3-5"
JUMLAH_VARIAN_QUERY = (3, 5)  # AI disuruh membuat 3-5 varian kata kunci
MAKS_CONTOH_NEGATIF_DI_PROMPT = 10  # post yang dulu ditolak AI, dikirim lagi sebagai pengingat


# ============================================================
# 5. PENGATURAN LLM (LLM-Kita)
# ============================================================
LLM_BASE_URL_DEFAULT = "https://api.llm-kita.com/api/v1"
LLM_MODEL_DEFAULT = "deepseek-v4-flash"
LLM_TIMEOUT = 120           # detik; model reasoning butuh 20-90 detik untuk batch besar
LLM_TEMPERATURE = 0.2
LLM_MAKS_POST_PER_BATCH = 25  # jangan kirim 100+ post dalam 1 request
LLM_PANJANG_CAPTION = 2000  # caption dikirim UTUH sampai batas ini.
#   JANGAN dipotong pendek: terukur 18 dari 45 caption > 300 karakter dan pemotongan
#   300 karakter menyembunyikan kata wilayah (contoh: "Cirebon" ada di karakter 563).


# ============================================================
# 6. KAIDAH WILAYAH (dibaca dari kaidah/kota_cirebon.json)
# ============================================================
def muat_kaidah(path: Path = None) -> dict:
    """Baca kaidah wilayah. Sengaja ditaruh di config supaya modul lain tidak perlu tahu bentuk filenya."""
    path = Path(path or PATH_KAIDAH_KOTA)
    if not path.exists():
        raise FileNotFoundError(
            f"File kaidah wilayah tidak ditemukan: {path}\n"
            f"Pastikan kaidah/kota_cirebon.json ada di folder proyek."
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def kata_gerbang(kaidah: dict = None) -> list:
    """Daftar kata wilayah (biasanya cuma 1 kata, mis. 'cirebon')."""
    kaidah = kaidah or muat_kaidah()
    return [str(k).lower().strip() for k in (kaidah.get("1_kata_gerbang") or []) if str(k).strip()]


def kata_gerbang_pertama(kaidah: dict = None) -> str:
    daftar = kata_gerbang(kaidah)
    return daftar[0] if daftar else ""


def keterangan_wilayah(kaidah: dict = None) -> dict:
    kaidah = kaidah or muat_kaidah()
    bagian = kaidah.get("4_keterangan_wilayah") or {}
    return {
        "wilayah_nama": bagian.get("wilayah_nama") or "wilayah sasaran",
        "wilayah_bukan": bagian.get("wilayah_bukan") or "wilayah lain di luar sasaran",
    }


def tanda_lokal(kaidah: dict = None) -> dict:
    kaidah = kaidah or muat_kaidah()
    bagian = kaidah.get("2_tanda_lokal") or {}
    return {
        "dialek": [str(x).lower() for x in (bagian.get("dialek") or [])],
        "nama_kawasan_kota": [str(x).lower() for x in (bagian.get("nama_kawasan_kota") or [])],
    }


def daftar_kata_terlarang(kaidah: dict = None) -> list:
    kaidah = kaidah or muat_kaidah()
    bagian = kaidah.get("3_kata_terlarang") or {}
    return [str(x).lower().strip() for x in (bagian.get("daftar") or []) if str(x).strip()]


# ============================================================
# 7. PEMBACA RAHASIA DARI .env
# ============================================================
def _baca_nilai_env(nama_kunci: str, default: str = "") -> str:
    """Ambil nilai dari variabel OS; kalau kosong, baca langsung dari file .env."""
    nilai = (os.environ.get(nama_kunci) or "").strip()
    if nilai:
        return nilai

    for path_env in (FOLDER_ROOT / ".env", FOLDER_BASE / ".env", FOLDER_CODE / ".env"):
        if not path_env.exists():
            continue
        try:
            for baris in path_env.read_text(encoding="utf-8").splitlines():
                baris = baris.strip()
                if not baris or baris.startswith("#") or "=" not in baris:
                    continue
                kunci, _, isi = baris.partition("=")
                if kunci.strip() == nama_kunci:
                    isi = isi.strip().strip('"').strip("'")
                    if isi:
                        return isi
        except Exception:
            continue
    return default


def ambil_apify_token() -> str:
    """Token Apify (untuk actor pencarian)."""
    return _baca_nilai_env("APIFY_TOKEN", "")


def ambil_daftar_api_keys() -> list:
    """
    Daftar API key LLM-Kita. Mendukung beberapa bentuk penulisan di .env:
      LLMKITA_API_KEYS=key1,key2,key3
      LLMKITA_API_KEY_1=key1  (sampai _9)
      LLMKITA_API_KEY=key
    """
    keys = []

    mentah = _baca_nilai_env("LLMKITA_API_KEYS", "") or _baca_nilai_env("LLM_API_KEYS", "")
    if mentah:
        for k in mentah.split(","):
            k = k.strip()
            if k and k not in keys:
                keys.append(k)

    for i in range(1, 10):
        k = _baca_nilai_env(f"LLMKITA_API_KEY_{i}", "") or _baca_nilai_env(f"LLM_API_KEY_{i}", "")
        if k and k not in keys:
            keys.append(k)

    tunggal = _baca_nilai_env("LLMKITA_API_KEY", "") or _baca_nilai_env("LLM_API_KEY", "")
    if tunggal and tunggal not in keys:
        keys.append(tunggal)

    return keys


def normalisasi_base_url(url: str) -> str:
    """Pastikan base URL bersih. Untuk api.llm-kita.com dipastikan /api/v1, selain itu pertahankan."""
    url = (url or LLM_BASE_URL_DEFAULT).rstrip("/")
    if "api.llm-kita.com" in url and not url.endswith("/api/v1"):
        if url.endswith("/v1"):
            url = url[:-3] + "/api/v1"
        else:
            url = url + "/api/v1"
    return url


def ambil_base_url_llm() -> str:
    return normalisasi_base_url(_baca_nilai_env("LLMKITA_BASE_URL", LLM_BASE_URL_DEFAULT))


def ambil_model_llm() -> str:
    """
    Model LLM dari .env (LLMKITA_MODEL). Kalau tidak diisi, pakai default.
    Catatan: alias 'deepseek-v4-pro' RUSAK di gateway (balas kuota acak) - jangan dipakai.
    """
    return _baca_nilai_env("LLMKITA_MODEL", LLM_MODEL_DEFAULT) or LLM_MODEL_DEFAULT


# ============================================================
# 8. ALAT BANTU UMUM
# ============================================================
ZONA_WAKTU_WIB = timezone(timedelta(hours=7))


def slugkan(teks: str) -> str:
    """
    Ubah nama topik jadi nama folder yang aman.
    Contoh: "Jalan Rusak!" -> "jalan_rusak"
    """
    slug = (teks or "").lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_") or "topik_tanpa_nama"


def folder_topik(nama_topik: str) -> Path:
    """Folder kerja untuk 1 topik: topik/<slug>/ (dibuat kalau belum ada)."""
    folder = FOLDER_TOPIK / slugkan(nama_topik)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def tentukan_rentang_tanggal(preset: str = "", jumlah: int = 1, dari: str = "", sampai: str = "") -> tuple:
    """
    Hitung rentang tanggal (YYYY-MM-DD) untuk penyaringan.

    - preset : "day" / "month" / "year" — dihitung dari HARI INI (WIB)
    - jumlah : banyaknya satuan, mis. jumlah=30 preset="day" -> 30 hari ke belakang
    - dari   : tanggal awal manual (YYYY-MM-DD), menang atas preset
    - sampai : tanggal akhir manual; kosong = hari ini

    Returns: (tanggal_min, tanggal_maks)
    """
    hari_ini = datetime.now(ZONA_WAKTU_WIB).date()
    jumlah = max(1, int(jumlah or 1))

    if dari:
        tanggal_min = dari
    elif preset == "day":
        tanggal_min = (hari_ini - timedelta(days=jumlah)).isoformat()
    elif preset == "month":
        tanggal_min = (hari_ini - timedelta(days=30 * jumlah)).isoformat()
    elif preset == "year":
        tanggal_min = (hari_ini - timedelta(days=365 * jumlah)).isoformat()
    else:
        tanggal_min = ""

    tanggal_maks = sampai or hari_ini.isoformat()
    return tanggal_min, tanggal_maks


def sekarang_iso() -> str:
    """Waktu sekarang format ISO UTC (dipakai untuk kolom scraped_at & log)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
