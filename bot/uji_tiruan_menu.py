# -*- coding: utf-8 -*-
"""
uji_tiruan_menu.py
==================
Uji alur menu TANPA Telegram dan TANPA internet. Biaya: Rp0.

Cara kerjanya: "pengirim" milik menu_bot diganti obyek palsu (TelegramPalsu) yang
cuma MENCATAT apa yang seharusnya dikirim. Lalu kita suapkan deretan update tiruan
(seperti tekanan tombol dan ketikan user), dan periksa apakah reaksi bot benar.

Jadi yang diuji di sini adalah LOGIKA: urutan langkah, validasi masukan, penolakan
user tak dikenal, penjumlahan estimasi biaya, dan perintah akhir yang disusun.

Yang TIDAK diuji di sini (memang bukan di sini tempatnya): jaringan Telegram,
kode token, dan pemanggilan Apify.

CARA PAKAI:
    python uji_tiruan_menu.py         (dari folder instagram/bot)
"""

import json
import sys
import tempfile
from pathlib import Path

import bot_config as cfg
import menu_bot

# ============================================================
# SIAPKAN LINGKUNGAN UJI (jangan sampai menyentuh data sungguhan)
# ============================================================
FOLDER_UJI = Path(tempfile.mkdtemp(prefix="uji_bot_"))
menu_bot.PATH_SESI = FOLDER_UJI / "sesi_uji.json"
cfg.PATH_USERS = FOLDER_UJI / "users_uji.json"

ID_USER = 111111          # user biasa yang diizinkan
ID_ADMIN = 999999         # admin
ID_ORANG_ASING = 222222   # tidak diizinkan

cfg.ALLOWED_USER_IDS = [ID_USER]
cfg.ADMIN_USER_IDS = [ID_ADMIN]

_laporan = []


# ============================================================
# TELEGRAM PALSU
# ============================================================
class TelegramPalsu:
    def __init__(self):
        self.catatan = []       # semua yang "dikirim"
        self.tombol_dijawab = []
        self._mid = 100

    def kirim_pesan(self, chat_id, teks, papan_tombol=None, balas_ke=None, **kwargs):
        self._mid += 1
        self.catatan.append({
            "aksi": "kirim", "chat_id": chat_id, "message_id": self._mid,
            "teks": teks, "papan": papan_tombol, "balas_ke": balas_ke,
        })
        return {"message_id": self._mid, "chat": {"id": chat_id}, "text": teks}

    def edit_pesan(self, chat_id, message_id, teks, papan_tombol=None, **kwargs):
        self.catatan.append({
            "aksi": "edit", "chat_id": chat_id, "message_id": message_id,
            "teks": teks, "papan": papan_tombol,
        })
        return {"message_id": message_id, "chat": {"id": chat_id}, "text": teks}

    def jawab_tombol(self, callback_query_id, teks=None, **kwargs):
        self.tombol_dijawab.append(callback_query_id)
        return True

    def kirim_file(self, chat_id, path_file, keterangan="", **kwargs):
        self.catatan.append({"aksi": "file", "chat_id": chat_id, "teks": str(path_file), "papan": None})
        return {"message_id": self._mid}

    # --- alat bantu untuk pemeriksaan ---
    def teks_terakhir(self) -> str:
        for item in reversed(self.catatan):
            if item["aksi"] in ("kirim", "edit"):
                return item["teks"] or ""
        return ""

    def id_pesan_terakhir(self):
        for item in reversed(self.catatan):
            if item["aksi"] in ("kirim", "edit"):
                return item["message_id"]
        return None

    def tombol_terakhir(self) -> list:
        for item in reversed(self.catatan):
            if item.get("papan"):
                isi = item["papan"].get("inline_keyboard") or []
                return [t["text"] for baris in isi for t in baris]
        return []

    def semua_teks(self) -> str:
        return "\n".join(i["teks"] or "" for i in self.catatan)


# ============================================================
# UPDATE TIRUAN
# ============================================================
_nomor_update = [0]


def update_pesan(user_id, teks, chat_id=None):
    _nomor_update[0] += 1
    return {
        "update_id": _nomor_update[0],
        "message": {
            "message_id": _nomor_update[0] * 10,
            "from": {"id": user_id, "first_name": "Pengguna Uji", "username": "uji_user"},
            "chat": {"id": chat_id or user_id, "type": "private"},
            "text": teks,
        },
    }


def update_tombol(user_id, data, message_id, chat_id=None):
    _nomor_update[0] += 1
    return {
        "update_id": _nomor_update[0],
        "callback_query": {
            "id": f"cb{_nomor_update[0]}",
            "from": {"id": user_id, "first_name": "Pengguna Uji", "username": "uji_user"},
            "data": data,
            "message": {
                "message_id": message_id,
                "chat": {"id": chat_id or user_id, "type": "private"},
            },
        },
    }


# ============================================================
# PEMERIKSAAN
# ============================================================
def cek(nama: str, lulus: bool, keterangan: str = ""):
    _laporan.append((nama, lulus, keterangan))
    tanda = "LULUS" if lulus else "GAGAL"
    print(f"  [{tanda}] {nama}" + (f" — {keterangan}" if keterangan else ""))


def judul(teks: str):
    print("\n" + "=" * 74)
    print(f"  {teks}")
    print("=" * 74)


def tampilkan_transkrip(tg_palsu: TelegramPalsu, jumlah=1):
    for item in tg_palsu.catatan[-jumlah:]:
        tanda = "KIRIM" if item["aksi"] == "kirim" else ("EDIT " if item["aksi"] == "edit" else "FILE ")
        isi = (item["teks"] or "").strip().replace("\n", "\n          ")
        print(f"\n  [{tanda}] {isi[:420]}")
        papan = item.get("papan") or {}
        tombol = [t["text"] for baris in (papan.get("inline_keyboard") or []) for t in baris]
        if tombol:
            print("          tombol: " + " | ".join(tombol))


# ============================================================
# SKENARIO
# ============================================================
def main():
    tg_palsu = TelegramPalsu()
    menu_bot.muat_sesi()

    print("Uji tiruan alur menu bot. Telegram palsu — tidak ada pesan yang benar-benar terkirim.")
    print(f"Folder data uji (dibuang setelah selesai): {FOLDER_UJI}")

    # ---------- 1. user tak dikenal ditolak ----------
    judul("SKENARIO 1 — Orang di luar daftar tidak boleh memakai bot")
    tg_palsu.catatan.clear()
    menu_bot.proses_update(update_pesan(ID_ORANG_ASING, "/start"), pengirim=tg_palsu)
    tampilkan_transkrip(tg_palsu)
    cek("Orang asing ditolak",
        "belum terdaftar" in tg_palsu.teks_terakhir() and str(ID_ORANG_ASING) in tg_palsu.teks_terakhir())

    # ---------- 2. user diizinkan membuka menu ----------
    judul("SKENARIO 2 — Menu utama")
    tg_palsu.catatan.clear()
    menu_bot.proses_update(update_pesan(ID_USER, "/start"), pengirim=tg_palsu)
    tampilkan_transkrip(tg_palsu)
    tombol = tg_palsu.tombol_terakhir()
    cek("Menu utama tampil dengan tombol", "Mulai scrape" in tombol, f"tombol: {tombol}")
    cek("User biasa TIDAK melihat menu admin", not any("admin" in t.lower() for t in tombol))

    # ---------- 3. pilih akun lewat tombol + ketik sendiri ----------
    judul("SKENARIO 3 — Pilih akun (tombol, semua, dan ketik sendiri)")
    tg_palsu.catatan.clear()
    menu_bot.proses_update(update_tombol(ID_USER, "m:mulai_akun", tg_palsu.id_pesan_terakhir()), pengirim=tg_palsu)
    tampilkan_transkrip(tg_palsu)
    cek("Masuk langkah 1 (akun)", "LANGKAH 1/5" in tg_palsu.teks_terakhir())

    menu_bot.proses_update(update_tombol(ID_USER, "m:akun:1", tg_palsu.id_pesan_terakhir()), pengirim=tg_palsu)
    menu_bot.proses_update(update_tombol(ID_USER, "m:akun:2", tg_palsu.id_pesan_terakhir()), pengirim=tg_palsu)
    tampilkan_transkrip(tg_palsu)
    cek("Dua akun terpilih", "Terpilih: @aboutcirebonid" in tg_palsu.teks_terakhir()
        and "@cirebonbribin" in tg_palsu.teks_terakhir())

    # tombol dengan indeks ngawur tidak boleh membuat bot rusak
    menu_bot.proses_update(update_tombol(ID_USER, "m:akun:99", tg_palsu.id_pesan_terakhir()), pengirim=tg_palsu)
    cek("Indeks akun ngawur diabaikan dengan aman", "Terpilih: @aboutcirebonid" in tg_palsu.teks_terakhir())

    # ketik sendiri: satu valid, satu ada spasi (ditolak), satu berupa tautan (dibersihkan)
    tg_palsu.catatan.clear()
    menu_bot.proses_update(update_tombol(ID_USER, "m:akun:ketik", tg_palsu.id_pesan_terakhir()), pengirim=tg_palsu)
    menu_bot.proses_update(update_pesan(ID_USER, "fajar.cirebon, radar cirebon, https://www.instagram.com/cirebonnews/"),
                           pengirim=tg_palsu)
    tampilkan_transkrip(tg_palsu, jumlah=3)
    teks = tg_palsu.semua_teks()
    cek("Username dari tautan dibersihkan", "@cirebonnews" in teks)
    cek("Username berspasi ditolak, bukan dipecah jadi akun palsu",
        "tidak diterima" in teks and "@radar" not in teks)

    # ---------- 4. rentang hari: validasi ----------
    judul("SKENARIO 4 — Rentang hari (batas 1-365)")
    menu_bot.proses_update(update_tombol(ID_USER, "m:akun:lanjut", tg_palsu.id_pesan_terakhir()), pengirim=tg_palsu)
    cek("Masuk langkah 2 (hari)", "LANGKAH 2/5" in tg_palsu.teks_terakhir())

    menu_bot.proses_update(update_tombol(ID_USER, "m:hari:ketik", tg_palsu.id_pesan_terakhir()), pengirim=tg_palsu)
    tg_palsu.catatan.clear()
    menu_bot.proses_update(update_pesan(ID_USER, "3650"), pengirim=tg_palsu)
    tampilkan_transkrip(tg_palsu)
    cek("3650 hari ditolak dengan pesan jelas", "harus antara 1 sampai 365" in tg_palsu.semua_teks())

    tg_palsu.catatan.clear()
    menu_bot.proses_update(update_pesan(ID_USER, "90"), pengirim=tg_palsu)
    tampilkan_transkrip(tg_palsu)
    cek("90 hari diterima", "LANGKAH 3/5" in tg_palsu.teks_terakhir())

    # ---------- 5. batas post per akun ----------
    judul("SKENARIO 5 — Batas post per akun (batas 1-1000)")
    tg_palsu.catatan.clear()
    menu_bot.proses_update(update_tombol(ID_USER, "m:post:500", tg_palsu.id_pesan_terakhir()), pengirim=tg_palsu)
    tampilkan_transkrip(tg_palsu)
    cek("Batas 500 post diterima", "LANGKAH 4/5" in tg_palsu.teks_terakhir())

    tg_palsu.catatan.clear()
    menu_bot.proses_update(update_tombol(ID_USER, "m:top:5", tg_palsu.id_pesan_terakhir()), pengirim=tg_palsu)
    tampilkan_transkrip(tg_palsu)
    cek("Masuk langkah 5 (komentar)", "LANGKAH 5/5" in tg_palsu.teks_terakhir())

    # ---------- 6. konfirmasi + estimasi biaya ----------
    judul("SKENARIO 6 — Konfirmasi, perkiraan waktu & estimasi biaya")
    tg_palsu.catatan.clear()
    menu_bot.proses_update(update_tombol(ID_USER, "m:kom:50", tg_palsu.id_pesan_terakhir()), pengirim=tg_palsu)
    tampilkan_transkrip(tg_palsu)
    teks = tg_palsu.teks_terakhir()
    cek("Ringkasan menampilkan semua pilihan",
        "@aboutcirebonid" in teks and "90 hari" in teks and "500 post" in teks)
    cek("Ringkasan menyebut batas komentar per post", "maks 50 komentar/post" in teks)
    cek("Perkiraan waktu ditampilkan", "PERKIRAAN WAKTU" in teks and "TOTAL" in teks)
    cek("Estimasi biaya tampil dalam dolar dan rupiah", "PERKIRAAN BIAYA" in teks and "Rp" in teks)
    # --- perbaikan #2 (keluhan 22 Sep 2026: "2000 komentar ... bikin rancu") ---
    cek("Angka komentar diberi label 'paling banyak' (dulu 'sekitar' sehingga rancu)",
        "paling banyak" in teks)
    cek("Rumus batas atas ditampilkan supaya tidak menimbulkan tafsir lain",
        "akun x" in teks and "komentar/post" in teks)
    cek("Ada pembanding angka 'biasanya' dari riwayat (kalau riwayatnya ada)",
        ("biasanya" in teks) == (cfg.statistik_komentar_terukur()["median"] > 0),
        f"median={cfg.statistik_komentar_terukur()['median']}")
    cek("Dijelaskan bahwa Apify menagih menurut hasil NYATA",
        "BENAR-BENAR terkumpul" in teks)
    cek("Aliran log disebut sesuai perilaku sebenarnya",
        menu_bot._sebutan_aliran_log() in teks)

    # ---------- 7. tombol MULAI menyusun perintah yang benar ----------
    judul("SKENARIO 7 — Tombol MULAI")
    sesi_sekarang = menu_bot.sesi_user(ID_USER)
    perintah = menu_bot.susun_perintah(sesi_sekarang)
    print("\n  Perintah yang disusun:")
    print("    " + " ".join(perintah))
    cek("Perintah memuat akun, hari, batas post, top, batas komentar, dan komentar",
        "--akun" in perintah and "--hari" in perintah and "--maks-post" in perintah
        and "--top-video" in perintah and "--maks-komentar" in perintah
        and "--scrape-comments" in perintah)
    cek("Nilai sesuai pilihan user",
        "90" in perintah and "500" in perintah and "5" in perintah and "50" in perintah)

    tg_palsu.catatan.clear()
    menu_bot.proses_update(update_tombol(ID_USER, "m:jalankan", tg_palsu.id_pesan_terakhir()), pengirim=tg_palsu)
    tampilkan_transkrip(tg_palsu)
    cek("Tanpa job_runner, bot jujur bilang mesin job belum aktif",
        "BELUM DIAKTIFKAN" in tg_palsu.teks_terakhir())

    # simulasi job_runner terpasang: pastikan bot memanggilnya dengan data benar
    dipanggil = {}

    def penjalan_tiruan(sesi, argv, chat_id, user_id):
        dipanggil["argv"] = argv
        dipanggil["chat_id"] = chat_id
        dipanggil["user_id"] = user_id

    menu_bot.proses_update(update_tombol(ID_USER, "m:jalankan", tg_palsu.id_pesan_terakhir()),
                           pengirim=tg_palsu, penjalan_job=penjalan_tiruan)
    cek("Dengan job_runner, bot menyerahkan perintah ke pengeksekusi",
        bool(dipanggil) and dipanggil["user_id"] == ID_USER,
        f"chat_id={dipanggil.get('chat_id')}")

    # ---------- 8. batal & kembali ----------
    judul("SKENARIO 8 — Batal dan kembali")
    tg_palsu.catatan.clear()
    menu_bot.proses_update(update_tombol(ID_USER, "m:batal", tg_palsu.id_pesan_terakhir()), pengirim=tg_palsu)
    cek("Batal mengembalikan ke menu utama", "Mulai scrape" in tg_palsu.tombol_terakhir())
    cek("Pilihan sebelumnya dikosongkan", not (menu_bot.sesi_user(ID_USER).get("akun") or []))

    # ---------- 9. tombol tidak dijawab = tombol berputar terus ----------
    judul("SKENARIO 9 — Setiap tekanan tombol wajib dijawab")
    cek("Semua callback terjawab", len(tg_palsu.tombol_dijawab) >= 10,
        f"jawab_tombol dipanggil {len(tg_palsu.tombol_dijawab)} kali")

    # ---------- 10. admin mengelola pengguna ----------
    judul("SKENARIO 10 — Admin menambah & mencabut pengguna")
    tg_palsu.catatan.clear()
    menu_bot.proses_update(update_pesan(ID_ADMIN, "/start"), pengirim=tg_palsu)
    cek("Admin melihat tombol kelola pengguna",
        any("Kelola pengguna" in t for t in tg_palsu.tombol_terakhir()))

    menu_bot.proses_update(update_tombol(ID_ADMIN, "a:user", tg_palsu.id_pesan_terakhir()), pengirim=tg_palsu)
    cek("Halaman kelola pengguna tampil", "KELOLA PENGGUNA" in tg_palsu.teks_terakhir())

    menu_bot.proses_update(update_tombol(ID_ADMIN, "a:user:tambah", tg_palsu.id_pesan_terakhir()), pengirim=tg_palsu)
    tg_palsu.catatan.clear()
    menu_bot.proses_update(update_pesan(ID_ADMIN, "333333, bukan_angka"), pengirim=tg_palsu)
    tampilkan_transkrip(tg_palsu, jumlah=2)
    teks = tg_palsu.semua_teks()
    cek("User baru ditambahkan", "333333 ditambahkan" in teks)
    cek("Masukan bukan angka ditolak dengan pesan", "bukan angka" in teks)
    cek("Daftar efektif bertambah", 333333 in cfg.daftar_user_efektif())

    tg_palsu.catatan.clear()
    menu_bot.proses_update(update_tombol(ID_ADMIN, "a:user:hapus", tg_palsu.id_pesan_terakhir()), pengirim=tg_palsu)
    menu_bot.proses_update(update_pesan(ID_ADMIN, "333333"), pengirim=tg_palsu)
    tampilkan_transkrip(tg_palsu, jumlah=2)
    cek("User dicabut", 333333 not in cfg.daftar_user_efektif())
    cek("Pesan pencabutan masuk", "dicabut" in tg_palsu.semua_teks())

    # ---------- 11. user yang dicabut benar-benar tidak bisa memakai ----------
    judul("SKENARIO 11 — Bukti pencabutan berlaku")
    tg_palsu.catatan.clear()
    menu_bot.proses_update(update_pesan(333333, "/start"), pengirim=tg_palsu)
    cek("User yang dicabut langsung ditolak", "belum terdaftar" in tg_palsu.teks_terakhir())

    # ---------- 12. teks di luar konteks tidak merusak apa pun ----------
    judul("SKENARIO 12 — Ketikan ngawur")
    tg_palsu.catatan.clear()
    menu_bot.proses_update(update_pesan(ID_USER, "halo bot apa kabar"), pengirim=tg_palsu)
    cek("Ketikan bebas dijawab ramah, bukan error", "belum saya mengerti" in tg_palsu.teks_terakhir())

    # ---------- RINGKASAN ----------
    judul("RINGKASAN UJI TIRUAN")
    lulus = sum(1 for _, l, _ in _laporan if l)
    print(f"  {lulus}/{len(_laporan)} pemeriksaan lulus.\n")
    for nama, l, ket in _laporan:
        if not l:
            print(f"  GAGAL: {nama} {ket}")

    # bersihkan folder uji
    try:
        for berkas in FOLDER_UJI.glob("*"):
            berkas.unlink()
        FOLDER_UJI.rmdir()
        print(f"\n  Folder data uji dibersihkan: {FOLDER_UJI}")
    except Exception as galat:
        print(f"\n  (Catatan: folder uji {FOLDER_UJI} tidak terhapus: {galat})")

    sys.exit(0 if lulus == len(_laporan) else 1)


if __name__ == "__main__":
    main()
