# -*- coding: utf-8 -*-
"""
ukur_kecepatan_sentimen.py
==========================
MENGUKUR KECEPATAN NYATA pembacaan komentar (model IndoBERTweet) memakai komentar
ASLI yang sudah ada di folder comment/ — TANPA Apify, jadi TANPA biaya.

Untuk apa?
-----------
Angka di bot_config.py (DETIK_PER_KOMENTAR_SENTIMEN dan DETIK_MUAT_MODEL) dipakai
untuk menghitung PERKIRAAN WAKTU yang ditampilkan ke pegawai. Kalau angkanya salah,
perkiraan di layar konfirmasi jadi menyesatkan. Skrip ini mengukurnya langsung di
komputer yang benar-benar dipakai bekerja (Python Windows), lalu memberi angka yang
bisa disalin ke bot_config.py.

CARA JALANKAN (PowerShell; WAJIB Python Windows karena butuh torch):

    C:\\Python314\\python.exe D:\\DKIS_MONITORING_FACEBOOK_TIKTOK\\instagram\\cirebon_media\\code\\ukur_kecepatan_sentimen.py

Bisa juga dibatasi jumlah komentarnya, misalnya 150 komentar:

    C:\\Python314\\python.exe D:\\DKIS_MONITORING_FACEBOOK_TIKTOK\\instagram\\cirebon_media\\code\\ukur_kecepatan_sentimen.py --jumlah 150

Catatan: pengukuran ini TIDAK menulis apa pun ke folder hasil. Data yang sudah ada
hanya dibaca sebagai bahan uji.
"""

import argparse
import csv
import glob
import os
import sys
import time

# Folder hasil komentar (relatif terhadap letak skrip ini).
# realpath dipakai untuk MERINGKAS tanda ".." — glob TIDAK bisa menelusuri "..",
# jadi tanpa realpath pola pencariannya tidak cocok dengan berkas apa pun.
AKAR_KOMENTAR = os.path.realpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "comment"))


def kumpulkan_teks(batas: int, dari_folder: str = None) -> list:
    """
    Ambil teks komentar dari berkas CSV yang sudah ada.

    Baris yang sebenarnya catatan bot (bukan komentar warga) disaring memakai
    fungsi resmi dari storage.py supaya pengukuran mencerminkan bahan yang benar.
    Kalau storage.py tidak bisa diimpor, penyaringan dilewati — ukuran kecepatan
    tidak berubah banyak karena panjang teksnya serupa.

    dari_folder: kalau diisi, berkas dicari di folder itu (ditelusuri sampai ke
    sub-folder paling dalam). Dipakai bila folder comment/ asli sedang kosong.
    """
    saring = None
    try:
        import storage                      # noqa: F401
        saring = storage.apakah_komentar_bot
    except Exception as galat:
        print(f"[catatan] storage.py tidak bisa dimuat ({galat}); penyaringan dilewati.")

    akar = os.path.realpath(dari_folder) if dari_folder else AKAR_KOMENTAR

    # Ditelusuri rekursif supaya struktur folder apa pun tetap terbaca.
    berkas = []
    for folder, _sub, daftar in os.walk(akar):
        for nama in daftar:
            if nama.lower().endswith(".csv") and "comment" in nama.lower():
                berkas.append(os.path.join(folder, nama))
    berkas.sort()

    if not berkas:
        print(f"[catatan] Tidak ada berkas comment_*.csv di : {akar}")
        return []
    print(f"[catatan] Berkas dipakai: {len(berkas)} buah dari {akar}")

    teks = []
    for jalur in berkas:
        try:
            with open(jalur, "r", encoding="utf-8-sig", newline="") as f:
                for baris in csv.DictReader(f):
                    isi = (baris.get("text") or "").strip()
                    if not isi:
                        continue
                    if saring and saring(isi):
                        continue
                    teks.append(isi)
                    if len(teks) >= batas:
                        return teks
        except Exception:
            continue
    return teks


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--jumlah", type=int, default=300,
                   help="jumlah komentar yang diukur (bawaan 300)")
    p.add_argument("--dari", default=None,
                   help="folder alternatif tempat mencari berkas comment_*.csv "
                        "(dipakai bila folder comment/ sedang kosong)")
    a = p.parse_args()

    print("=" * 68)
    print("  PENGUKURAN KECEPATAN PEMBACAAN KOMENTAR (tanpa Apify, tanpa biaya)")
    print("=" * 68)

    teks = kumpulkan_teks(a.jumlah, a.dari)
    if not teks:
        print("Tidak ada komentar yang bisa dipakai. Jalankan scraper dulu supaya")
        print("folder comment/ terisi.")
        return 1

    rata_panjang = sum(len(t) for t in teks) / len(teks)
    print(f"  Komentar diuji     : {len(teks)} buah (dari berkas hasil yang sudah ada)")
    print(f"  Panjang rata-rata  : {rata_panjang:.0f} karakter")
    print()

    try:
        import sentiment_analyzer as sa
    except Exception as galat:
        print(f"GAGAL memuat sentiment_analyzer: {galat}")
        print("Pastikan dijalankan dengan Python Windows yang punya torch + transformers.")
        return 1

    # ---- 1. Lama menyiapkan model (sekali per pekerjaan) ----
    print("  Menyiapkan model (ini yang biasanya memakan waktu paling lama)...")
    awal = time.time()
    sa.get_sentiment_pipeline()
    detik_muat = time.time() - awal
    print(f"  -> selesai dalam {detik_muat:.1f} detik")
    print()

    # ---- 2. Lama membaca & menggolongkan komentar (model sudah siap) ----
    print(f"  Membaca & menggolongkan {len(teks)} komentar...")
    daftar = [{"text": t} for t in teks]
    awal = time.time()
    sa.analisa_sentimen_batch(daftar)
    detik_baca = time.time() - awal

    per_komentar = detik_baca / len(daftar)
    print(f"  -> selesai dalam {detik_baca:.1f} detik")
    print()

    # ---- 3. Hasil + saran angka untuk bot_config.py ----
    print("=" * 68)
    print("  HASIL PENGUKURAN")
    print("=" * 68)
    print(f"  Lama menyiapkan model      : {detik_muat:.1f} detik "
          f"(dipakai sebagai DETIK_MUAT_MODEL)")
    print(f"  Membaca {len(daftar)} komentar      : {detik_baca:.1f} detik")
    print(f"  Per komentar (terukur)     : {per_komentar:.3f} detik")
    print()
    print("  Angka yang disarankan untuk bot_config.py:")
    print(f"      DETIK_MUAT_MODEL = {int(round(detik_muat))}")
    # Dibulatkan KE ATAS ke kelipatan 0,05 supaya perkiraan tidak terlalu optimistis.
    saran = max(0.05, round(per_komentar + 0.01, 2))
    print(f"      DETIK_PER_KOMENTAR_SENTIMEN = {saran}")
    print()
    print("  Sekarang di bot_config.py tertulis:")
    try:
        import bot_config as bc
        print(f"      DETIK_MUAT_MODEL = {bc.DETIK_MUAT_MODEL}")
        print(f"      DETIK_PER_KOMENTAR_SENTIMEN = {bc.DETIK_PER_KOMENTAR_SENTIMEN}")
        print()
        print("  Perkiraan salah/betul saat ini (1 akun, top 1, 500 komentar):")
        sekarang = bc.DETIK_MUAT_MODEL + 500 * bc.DETIK_PER_KOMENTAR_SENTIMEN
        terukur = detik_muat + 500 * per_komentar
        print(f"      menurut setelan sekarang : {sekarang:.0f} detik")
        print(f"      menurut pengukuran       : {terukur:.0f} detik")
    except Exception as galat:
        print(f"      (bot_config tidak bisa dibaca dari sini: {galat})")
    print()
    print("  Catatan: angka bisa berbeda saat job nyata, karena komputer juga sedang")
    print("  bekerja untuk hal lain. Karena itu perkiraan di bot sengaja dibuat")
    print("  'kira-kira saja, bukan janji'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
