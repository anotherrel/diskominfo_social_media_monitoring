# -*- coding: utf-8 -*-
"""
uji_batas_komentar.py
=====================
UJI CEPAT untuk aturan batas komentar (permintaan user 22 Sep 2026):

    "misal kita scraping beberapa post, dari itu kalau dijumlahkan total komentarnya
     di bawah 100, maka scrap saja semua komentar tiap postingan"

Yang diuji: fungsi tentukan_batas_komentar() di main.py.

KENAPA PAKAI MODUL TIRUAN:
main.py menarik modul storage -> sentiment_analyzer -> transformers + torch, dan kedua
paket itu hanya terpasang di Windows. Supaya uji ini bisa dijalankan di mana saja
(termasuk WSL), transformers/torch/sentiment_analyzer diganti modul kosong lebih dulu.
Yang diuji di sini murni HITUNGAN, jadi tidak butuh model AI sungguhan.

Cara jalankan (dari folder ini):
    python uji_batas_komentar.py
"""

import os
import sys
import types

FOLDER_INI = os.path.dirname(os.path.abspath(__file__))
if FOLDER_INI not in sys.path:
    sys.path.insert(0, FOLDER_INI)

# --- modul tiruan: supaya main.py bisa diimpor tanpa transformers/torch ---
for _nama in ("torch", "transformers"):
    sys.modules.setdefault(_nama, types.ModuleType(_nama))
_sa = types.ModuleType("sentiment_analyzer")
_sa.analisa_sentimen_batch = lambda *a, **k: []
_sa.hitung_statistik_sentimen = lambda *a, **k: {}
sys.modules["sentiment_analyzer"] = _sa

import config as cfg          # noqa: E402
import main as scr            # noqa: E402

_laporan = []


def judul(teks: str):
    print("=" * 74)
    print(f"  {teks}")
    print("=" * 74)


def cek(nama: str, lulus: bool, keterangan: str = ""):
    _laporan.append((nama, bool(lulus), keterangan))
    tanda = "[LULUS]" if lulus else "[GAGAL]"
    print(f"  {tanda} {nama}" + (f" — {keterangan}" if keterangan else ""))


def vids(*jumlah_komentar):
    """Buat daftar postingan tiruan dengan kolom comment_count seperti aslinya."""
    return [{"post_id": str(i), "comment_count": n} for i, n in enumerate(jumlah_komentar)]


def main_uji():
    ambang = cfg.KOMENTAR_AMBANG_AMBIL_SEMUA
    plafon = cfg.MAKS_KOMENTAR_PLAFON
    print(f"Uji aturan batas komentar. Ambang ambil-semua = {ambang}, plafon = {plafon}.\n")

    # ---------- 1. komentar sedikit -> ambil SEMUA ----------
    judul("1. Total komentar di bawah ambang -> batas per post DIABAIKAN")
    for label, daftar, batas, total in (
        ("3 post: 28+2+1 = 31", vids(28, 2, 1), 50, 31),
        ("2 post: 60+30 = 90", vids(60, 30), 50, 90),
        ("1 post: 1 komentar", vids(1), 10, 1),
    ):
        b, lim, tot, ket = scr.tentukan_batas_komentar(daftar, batas)
        cek(f"{label} (batas {batas}) -> ambil semua",
            b == plafon and lim == total and bool(ket),
            f"batas={b} diminta={lim} tersedia={tot}")

    # ---------- 2. komentar banyak -> batas per post DIHORMATI ----------
    judul("2. Total komentar di atas ambang -> batas per post tetap dipakai")
    for label, daftar, batas, diharap in (
        ("3 post: 322+229+173, batas 50", vids(322, 229, 173), 50, 150),
        ("3 post: 322+229+173, batas 100", vids(322, 229, 173), 100, 300),
        ("2 post: 500+20, batas 50", vids(500, 20), 50, 70),
    ):
        b, lim, tot, ket = scr.tentukan_batas_komentar(daftar, batas)
        cek(f"{label} -> tetap dibatasi",
            b == batas and lim == diharap and not ket,
            f"batas={b} diminta={lim} (diharap {diharap})")

    # ---------- 3. tepat di ambang: TIDAK dianggap kecil ----------
    judul("3. Tepat di ambang tidak dianggap 'sedikit'")
    b, lim, tot, ket = scr.tentukan_batas_komentar(vids(60, 40), 50)
    cek(f"Total tepat {ambang} -> batas per post tetap berlaku",
        b == 50 and lim == 90 and not ket, f"batas={b} diminta={lim}")

    # ---------- 4. jumlah komentar tidak diketahui ----------
    judul("4. Jumlah komentar tidak terbaca -> pakai batas per post (aman, tidak menebak)")
    b, lim, tot, ket = scr.tentukan_batas_komentar(vids(0, 0, 0), 50)
    cek("comment_count 0 -> batas per post dipakai apa adanya",
        b == 50 and lim == 150 and not ket, f"batas={b} diminta={lim}")

    # ---------- 5. jaminan tidak kehilangan kuota postingan lain ----------
    judul("5. Kuota tidak boleh dihabiskan satu postingan saja")
    b, lim, tot, ket = scr.tentukan_batas_komentar(vids(1000, 5, 5), 50)
    cek("Postingan raksasa tidak menghabiskan kuota postingan kecil",
        lim == 50 + 5 + 5, f"diminta={lim} (diharap 60)")

    # ---------- ringkasan ----------
    judul("RINGKASAN")
    lulus = sum(1 for _, l, _ in _laporan if l)
    print(f"  {lulus}/{len(_laporan)} pemeriksaan lulus.\n")
    for nama, l, ket in _laporan:
        if not l:
            print(f"  GAGAL: {nama} {ket}")
    return 0 if lulus == len(_laporan) else 1


if __name__ == "__main__":
    sys.exit(main_uji())
