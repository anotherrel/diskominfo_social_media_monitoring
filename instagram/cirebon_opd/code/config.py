# -*- coding: utf-8 -*-
"""
config.py (cirebon_opd)
========================
Konfigurasi khusus untuk pemantauan dan pemeringkatan keaktifan
Akun Instagram Resmi Pemerintah Kota Cirebon (27 OPD + 5 Kecamatan = 32 Akun).
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============================================================
# 1. PENGATURAN LOKASI FOLDER (PATHS)
# ============================================================
FOLDER_CODE = Path(__file__).resolve().parent
FOLDER_BASE = FOLDER_CODE.parent
FOLDER_ROOT = FOLDER_BASE.parent.parent

FOLDER_DATA = FOLDER_BASE / "data"
FOLDER_HISTORY = FOLDER_BASE / "history"

FOLDER_DATA.mkdir(parents=True, exist_ok=True)
FOLDER_HISTORY.mkdir(parents=True, exist_ok=True)

# ============================================================
# 2. PENGATURAN APIFY & BATASAN
# ============================================================
ACTOR_ID = "apify~instagram-scraper"

HARI_MAKS_SCRAPE = 365
MAKS_POST_DEFAULT = 100      # Bawaan post per akun OPD
MAKS_POST_MAKS = 500

def baca_nilai_env(nama_kunci, default=""):
    nilai = (os.environ.get(nama_kunci) or "").strip()
    if nilai:
        return nilai
    for path_env in ((FOLDER_ROOT / ".env"), (FOLDER_BASE / ".env"), (FOLDER_CODE / ".env"), (FOLDER_ROOT / "instagram" / "bot" / ".env")):
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
    return baca_nilai_env("APIFY_TOKEN", "")

# ============================================================
# 3. DAFTAR 32 AKUN INSTAGRAM RESMI PEMKOT CIREBON
# Format tuple: (username_ig, nama_folder, nama_tampilan, kategori)
# Kategori: "OPD" atau "Kecamatan"
# ============================================================
DAFTAR_OPD = [
    # 27 Organisasi Perangkat Daerah (OPD) / Dinas / Badan / Sekretariat
    ("setdakotacrb",          "setda",          "Sekretariat Daerah",             "OPD"),
    ("dprdkotacirebon",       "dprd",           "Sekretariat DPRD",               "OPD"),
    ("inspektoratkotacirebon","inspektorat",    "Inspektorat",                    "OPD"),
    ("bkpsdmkotacirebon",     "bkpsdm",         "BKPSDM",                         "OPD"),
    ("bakesbangpolkotacirebon","bakesbangpol",   "Bakesbangpol",                   "OPD"),
    ("bpbdkotacirebon",       "bpbd",           "BPBD",                           "OPD"),
    ("bpkpdkotacirebon",      "bpkpd",          "BPKPD",                          "OPD"),
    ("bapperida_kotacirebon", "bapperida",      "Bapperida",                      "OPD"),
    ("disbudparkotacirebon",  "disbudpar",      "Disbudpar",                      "OPD"),
    ("disdukcapil_kotacirebon","disdukcapil",    "Disdukcapil",                    "OPD"),
    ("dinkeskotacirebon",     "dinkes",         "Dinas Kesehatan (Dinkes)",       "OPD"),
    ("dkppp_kotacirebon",     "dkp3",           "DKP3 (Ketahanan Pangan)",        "OPD"),
    ("dkiskotacirebon",       "dkis",           "DKIS (Kominfo)",                 "OPD"),
    ("dkukmppkotacirebon",    "dkukmpp",        "DKUKMPP (Koperasi/UKM)",         "OPD"),
    ("dlhkotacirebon",        "dlh",            "Dinas Lingkungan Hidup (DLH)",   "OPD"),
    ("dputr_kotacirebon",     "dputr",          "DPUTR (PUPR)",                   "OPD"),
    ("damkar_kotacirebon",    "damkar",         "Dinas Damkar",                   "OPD"),
    ("dp3appkb.kotacirebon",  "dp3appkb",       "DP3APPKB",                       "OPD"),
    ("disporakotacirebon",    "dispora",        "Dispora",                        "OPD"),
    ("dpmptspcirebonkota",    "dpmptsp",        "DPMPTSP",                        "OPD"),
    ("disdikkotacirebon",     "disdik",         "Dinas Pendidikan (Disdik)",      "OPD"),
    ("dishubcirebonkota",     "dishub",         "Dinas Perhubungan (Dishub)",     "OPD"),
    ("dispusipkotacirebon",   "dispusip",       "Dispusip",                       "OPD"),
    ("dprkpkotacirebon",      "dprkp",          "DPRKP (Perumkim)",               "OPD"),
    ("dinsoskotacirebon",     "dinsos",         "Dinas Sosial (Dinsos)",          "OPD"),
    ("disnaker_kotacirebon",  "disnaker",       "Dinas Tenaga Kerja (Disnaker)",  "OPD"),
    ("satpolppcirebonkota",   "satpolpp",       "Satpol PP",                      "OPD"),

    # 5 Kecamatan Kota Cirebon
    ("kecharjamukti",         "kec_harjamukti",  "Kecamatan Harjamukti",          "Kecamatan"),
    ("keckejaksan",           "kec_kejaksan",    "Kecamatan Kejaksan",            "Kecamatan"),
    ("keckesambi",            "kec_kesambi",     "Kecamatan Kesambi",             "Kecamatan"),
    ("keclemahwungkuk",       "kec_lemahwungkuk","Kecamatan Lemahwungkuk",        "Kecamatan"),
    ("kecamatan_pekalipan",   "kec_pekalipan",   "Kecamatan Pekalipan",           "Kecamatan"),
]

PETA_AKUN_OPD = {u: {"folder": f, "nama": n, "kategori": k} for u, f, n, k in DAFTAR_OPD}
