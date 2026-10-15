# -*- coding: utf-8 -*-
"""
evaluator.py (modul TikTok) — VERSI SEDERHANA (18 Sep 2026)
==========================================================
GERBANG KANDIDAT. Cuma 3 pekerjaan, semuanya murah dan pasti:

  1. Rentang tanggal (WIB)  — buang post di luar rentang.
  2. Kata terlarang sampah  — buang judi/olshop/dsb (hemat token AI).
  3. Kata gerbang wilayah   — WAJIB ada kata wilayah (biasanya "cirebon") di caption,
                              hashtag, ATAU nama akun. Dicocokkan sebagai POTONGAN KATA,
                              supaya #kotacirebon / #cirebonpride tetap kena.

File ini TIDAK menilai relevansi topik, TIDAK menghitung skor, TIDAK punya ambang.
Itu tugas gate AI (llm_reviewer.py). Alasannya ada di DESAIN.md "Revisi 18 Sep 2026":
versi lama memakai skor bobot + ambang 0,75 -> dari 103 video nyata hanya 12 lolos,
padahal 42 relevan (recall 29%).

Semua daftar kata ada di kaidah/kota_cirebon.json.
"""

import re
from datetime import datetime, timezone

from config import muat_kaidah, kata_gerbang, daftar_kata_terlarang, ZONA_WAKTU_WIB


# ============================================================
# 1. PEMBERSIHAN TEKS
# ============================================================
def pisahkan_hashtag(caption: str) -> tuple:
    """
    Pisahkan caption jadi (teks tanpa hashtag, daftar hashtag tanpa tanda #).
    Dipakai untuk validasi caption contoh + pencocokan kata.
    """
    caption = caption or ""
    hashtags = [h.lower() for h in re.findall(r"#(\w+)", caption)]
    tanpa_hashtag = re.sub(r"#\w+", " ", caption)
    tanpa_hashtag = re.sub(r"https?://\S+", " ", tanpa_hashtag)
    tanpa_hashtag = re.sub(r"\s+", " ", tanpa_hashtag).strip()
    return tanpa_hashtag, hashtags


def ambil_hashtags_item(item: dict) -> list:
    """Ambil hashtag dari item hasil scrape (TikTok memberi list of dict/str)."""
    mentah = item.get("hashtags") or []
    hasil = []
    if isinstance(mentah, list):
        for h in mentah:
            nama = h.get("name") if isinstance(h, dict) else h
            if nama:
                hasil.append(str(nama).lower().lstrip("#"))
    return hasil


def teks_untuk_cocok(caption: str, hashtags_tambahan: list = None) -> tuple:
    """
    Bentuk teks gabungan untuk pencocokan kata: caption + semua hashtag.
    Returns: (teks_gabungan_lowercase, caption_bersih, daftar_hashtag)
    """
    caption_bersih, hashtags_dari_caption = pisahkan_hashtag(caption)
    semua_hashtag = list(dict.fromkeys(
        hashtags_dari_caption + [str(h).lower().lstrip("#") for h in (hashtags_tambahan or [])]
    ))
    teks = (caption_bersih + " " + " ".join(semua_hashtag)).lower().strip()
    return teks, caption_bersih, semua_hashtag


def jumlah_kata_bermakna(caption: str) -> int:
    """
    Hitung kata bermakna pada caption (hashtag & URL dibuang).
    Dipakai rule_builder untuk memaksa contoh video bercaption jelas.
    """
    bersih, _ = pisahkan_hashtag(caption)
    kata = [k for k in bersih.split() if len(k) >= 3 and any(c.isalpha() for c in k)]
    return len(kata)


def nama_akun(item: dict) -> str:
    """Ambil username dari item hasil scrape (bentuk field-nya bisa macam-macam)."""
    return (
        (item.get("authorMeta") or {}).get("name")
        or (item.get("author") or {}).get("uniqueId")
        or item.get("author_username")
        or ""
    )


# ============================================================
# 2. TANGGAL
# ============================================================
def ekstrak_tanggal_upload(item: dict) -> str:
    """
    Ambil tanggal unggah video dan konversi ke WIB (YYYY-MM-DD). Kosong kalau tidak ada.

    TikTok memberi 'createTimeISO' (mis. 2026-09-13T13:45:00.000Z) atau createTime (unix detik).
    """
    for kunci in ("createTimeISO", "createdAt", "createTime", "uploadedAt", "timestamp"):
        nilai = item.get(kunci)
        if not nilai:
            continue

        if isinstance(nilai, (int, float)):
            try:
                detik = nilai / 1000 if nilai > 1e11 else nilai
                dt = datetime.fromtimestamp(detik, tz=timezone.utc).astimezone(ZONA_WAKTU_WIB)
                return dt.strftime("%Y-%m-%d")
            except Exception:
                continue

        if isinstance(nilai, str) and len(nilai) >= 10:
            potong = nilai[:10]
            if re.match(r"^\d{4}-\d{2}-\d{2}$", potong):
                return potong

    return ""


# ============================================================
# 3. PENCARIAN KATA
# ============================================================
def ada_kata_gerbang(teks: str, daftar: list) -> list:
    """
    Cari kata wilayah sebagai POTONGAN KATA (bukan kata utuh).

    Sengaja potongan kata: netizen menulis #kotacirebon, #cirebonpride, #cirebontiktok,
    dan versi lama (kata utuh) membuang 3-4 video asli Cirebon karena itu.
    """
    teks = (teks or "").lower()
    return [k for k in (daftar or []) if k and k.lower() in teks]


def ada_kata_utuh(teks: str, daftar: list) -> list:
    """
    Cari kata sebagai KATA UTUH (dengan pembatas).
    Dipakai untuk kata terlarang: 'pers' tidak boleh cocok dengan 'persistenteats'.
    """
    teks = (teks or "").lower()
    hasil = []
    for kata in (daftar or []):
        kata = (kata or "").lower().strip()
        if not kata:
            continue
        pola = r"(?<![a-z0-9])" + re.escape(kata) + r"(?![a-z0-9])"
        if re.search(pola, teks):
            hasil.append(kata)
    return hasil


# ============================================================
# 4. FUNGSI UTAMA: GERBANG KANDIDAT
# ============================================================
def evaluasi_gerbang(item: dict, kaidah: dict = None,
                     tanggal_min: str = "", tanggal_maks: str = "") -> dict:
    """
    Nilai 1 postingan TikTok di GERBANG (murah, tanpa AI).

    Returns dict:
      lolos          : bool  -> True berarti lanjut ke penilaian AI
      alasan_gerbang : penjelasan singkat (bisa diaudit manusia)
      meta           : kolom pendukung untuk disimpan (tanggal, kata gerbang yang kena, dll)
    """
    kaidah = kaidah or muat_kaidah()
    daftar_gerbang = kata_gerbang(kaidah)
    daftar_terlarang = daftar_kata_terlarang(kaidah)

    caption = (item.get("text") or item.get("caption") or "").strip()
    hashtags_item = ambil_hashtags_item(item)
    teks, caption_bersih, semua_hashtag = teks_untuk_cocok(caption, hashtags_item)
    tgl_upload = ekstrak_tanggal_upload(item)
    akun = nama_akun(item)

    # teks gabungan + nama akun: akun seperti 'udaridercrb' / 'infokotacirebon' ikut dihitung
    teks_dengan_akun = (teks + " " + akun.lower()).strip()

    meta = {
        "username": akun,
        "tgl_upload": tgl_upload,
        "caption_bersih": caption_bersih,
        "hashtags": semua_hashtag,
    }

    def _gugur(alasan):
        meta["kata_gerbang_kena"] = []
        return {"lolos": False, "alasan_gerbang": alasan, "meta": meta}

    # ---- (1) rentang tanggal ----
    if tgl_upload:
        if tanggal_min and tgl_upload < tanggal_min:
            return _gugur(f"LUAR TANGGAL: diunggah {tgl_upload}, sebelum batas {tanggal_min}")
        if tanggal_maks and tgl_upload > tanggal_maks:
            return _gugur(f"LUAR TANGGAL: diunggah {tgl_upload}, setelah batas {tanggal_maks}")

    # ---- (2) bahan ----
    if not caption_bersih and not semua_hashtag:
        return _gugur("TANPA BAHAN: caption & hashtag kosong")

    # ---- (3) kata terlarang sampah ----
    kena_terlarang = ada_kata_utuh(teks_dengan_akun, daftar_terlarang)
    if kena_terlarang:
        return _gugur(f"KATA TERLARANG: {', '.join(kena_terlarang)}")

    # ---- (4) kata gerbang wilayah ----
    kena_gerbang = ada_kata_gerbang(teks_dengan_akun, daftar_gerbang)
    meta["kata_gerbang_kena"] = kena_gerbang
    if not kena_gerbang:
        return _gugur(f"TANPA KATA WILAYAH: tidak ada {daftar_gerbang} di caption/hashtag/akun")

    return {
        "lolos": True,
        "alasan_gerbang": f"LOLOS gerbang: ada kata wilayah {kena_gerbang} (tanggal {tgl_upload or 'tidak diketahui'})",
        "meta": meta,
    }
