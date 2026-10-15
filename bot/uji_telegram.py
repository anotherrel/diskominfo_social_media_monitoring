# -*- coding: utf-8 -*-
"""
uji_telegram.py
===============
Alat uji bertahap untuk bot Telegram scraper IG. TIDAK menyentuh Apify dan
TIDAK memanggil LLM sama sekali — biayanya nol. Yang diuji hanya "pipa" Telegram:
terima token? terima pesan? kirim pesan? tombol bekerja? file terkirim?

CARA PAKAI (dari Windows PowerShell):
    cd D:\\DKIS_MONITORING_FACEBOOK_TIKTOK\\instagram\\bot
    C:\\Python314\\python.exe uji_telegram.py

SEBELUM MENJALANKAN — PENTING:
    Pastikan TIDAK ADA proses bot lain yang memakai token yang sama
    (jangan jalankan main_bot.py bersamaan). Satu token hanya boleh ditarik
    satu proses; kalau dua, Telegram membalas 409 Conflict dan uji ini gagal
    bukan karena kodenya salah.

Yang dilakukan alat ini, satu per satu (boleh berhenti kapan saja dengan Ctrl+C):
    CEK 1  Token benar?            -> memanggil getMe
    CEK 2  Bisa menerima pesan?    -> kamu kirim apa saja ke bot, ID kamu muncul
    CEK 3  Bisa mengirim + tombol? -> kamu tekan tombolnya, bot menjawab balik
    CEK 4  Bisa mengirim file?     -> dikirim file CSV contoh
    CEK 5  Ringkasan lulus/gagal dari 4 cek di atas
"""

import sys
import time
from pathlib import Path

import telegram_api as tg
import bot_config as cfg


# ============================================================
# Alat bantu tampilan
# ============================================================
def judul(teks: str):
    print("\n" + "=" * 72)
    print(f"  {teks}")
    print("=" * 72)


def hasil(nama: str, lulus: bool, keterangan: str = ""):
    tanda = "LULUS" if lulus else "GAGAL"
    print(f"  [{tanda}] {nama}" + (f" — {keterangan}" if keterangan else ""))
    return lulus


def tanya(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nDihentikan user.")
        sys.exit(0)


def tunggu_update(offset, kata_kunci_ketik: str, batas_detik: int = 60, jenis: list = None):
    """
    Menunggu update yang mengandung `kata_kunci_ketik` ("message" atau "callback_query").
    Returns: (update_ditemukan, offset_baru)
    """
    batas = time.time() + batas_detik
    while time.time() < batas:
        sisa = max(1, int(batas - time.time()))
        daftar = tg.ambil_pesan(offset=offset, timeout_polling=min(20, sisa), jenis=jenis)
        for update in daftar:
            offset = max(offset or 0, int(update.get("update_id", 0)) + 1)
            if kata_kunci_ketik in update:
                return update, offset
        print("      ...menunggu", end="\r", flush=True)
    return None, offset


# ============================================================
# CEK 1 — token
# ============================================================
def cek_1_token() -> bool:
    judul("CEK 1 — Apakah token bot benar?")
    print("  Memanggil getMe (tidak mengirim pesan ke siapa pun)...")
    try:
        info = tg.info_bot()
    except tg.TelegramError as galat:
        pesan_bantuan = {
            401: "Token salah/tidak lengkap. Salin ulang dari @BotFather.",
            404: "Token berbentuk salah. Pastikan formatnya 123456789:AA... dan tidak ada spasi.",
            409: "Ada proses lain memakai token ini. Tutup bot/proses itu dulu.",
        }.get(galat.kode, "")
        return hasil("Token bot", False, f"{galat} {pesan_bantuan}")
    print(f"      Nama bot     : {info.get('first_name')}")
    print(f"      Username     : @{info.get('username')}")
    print(f"      ID bot       : {info.get('id')}")
    return hasil("Token bot", True, "token hidup dan bisa dipakai")


# ============================================================
# CEK 2 — menerima pesan (long polling + dapat chat_id)
# ============================================================
def cek_2_terima_pesan(offset) -> tuple:
    """Returns: (lulus, offset_baru, chat_id)"""
    judul("CEK 2 — Apakah bot bisa menerima pesan?")
    print("  Langkah: buka chat dengan bot di Telegram, lalu ketik apa saja")
    print("           (contoh: /start atau 'halo'), JANGAN tutup alat ini.")
    print("  Catatan: bot tidak bisa memulai percakapan; kamu yang harus menyapa dulu.\n")

    for percobaan in range(1, 4):
        print(f"  Menunggu pesan dari kamu... (percobaan {percobaan}/3, tunggu maks 60 detik)")
        update, offset = tunggu_update(offset, "message", batas_detik=60)
        if not update:
            print("\n      Tidak ada pesan masuk dalam 60 detik.")
            ulang = tanya("      Coba lagi? (y/n) [n]: ").lower()
            if ulang != "y":
                return hasil("Terima pesan", False, "tidak ada pesan masuk"), offset, None
            continue

        pesan = update["message"]
        pengirim = pesan.get("from") or {}
        chat = pesan.get("chat") or {}
        user_id = pengirim.get("id")
        chat_id = chat.get("id")
        print("\n      Pesan diterima:")
        print(f"        dari      : {pengirim.get('first_name')} (@{pengirim.get('username')})")
        print(f"        user id   : {user_id}")
        print(f"        chat id   : {chat_id}  (jenis: {chat.get('type')})")
        print(f"        isi pesan : {(pesan.get('text') or '(tanpa teks)')[:60]}")

        diizinkan = cfg.user_diizinkan(user_id) if user_id else False
        print(f"\n      Ada di allowlist bot? {('YA' if diizinkan else 'BELUM')}")
        if not diizinkan:
            print("      Cara memasukkan: tulis ID di atas pada baris BOT_ALLOWED_USER_IDS")
            print("      di file instagram/bot/.env (pisahkan dengan koma kalau lebih dari satu),")
            print("      lalu jalankan ulang alat uji ini.")
        return hasil("Terima pesan", True, f"user id {user_id} terbaca"), offset, chat_id

    return hasil("Terima pesan", False, "menyerah setelah 3 percobaan"), offset, None


# ============================================================
# CEK 3 — mengirim pesan + tombol
# ============================================================
def cek_3_kirim_tombol(chat_id, offset) -> tuple:
    judul("CEK 3 — Apakah bot bisa mengirim pesan dan tombol bekerja?")
    print(f"  Mengirim pesan + 2 tombol ke chat {chat_id}...")

    papan = tg.keyboard([
        [tg.tombol("Uji OK", "uji:ok"), tg.tombol("Uji Tolak", "uji:tolak")],
    ])
    try:
        pesan = tg.kirim_pesan(
            chat_id,
            "UJI BOT (bukan data asli)\n\nTekan salah satu tombol di bawah. "
            "Kalau tombol terasa 'berputar' lama, berarti jawab_tombol belum jalan.",
            papan_tombol=papan,
        )
    except tg.TelegramError as galat:
        bantuan = ""
        if galat.kode == 403:
            bantuan = "User belum pernah menekan /start di chat bot ini (Telegram melarang bot menyapa lebih dulu)."
        return hasil("Kirim pesan", False, f"{galat} {bantuan}"), offset

    print(f"      Terkirim (message_id={pesan.get('message_id')}).")
    print("  Sekarang buka Telegram dan TEKAN salah satu tombol itu.\n")

    update, offset = tunggu_update(offset, "callback_query", batas_detik=60)
    if not update:
        print("\n      Tidak ada tombol yang ditekan dalam 60 detik.")
        return hasil("Tombol (callback)", False, "tidak ada tekanan tombol terdeteksi"), offset

    cb = update["callback_query"]
    data_tekanan = cb.get("data", "")
    print(f"      Tombol ditekan: '{data_tekanan}' oleh {cb.get('from', {}).get('first_name')}")

    # Dua hal wajib setelah tombol ditekan:
    # 1) answerCallbackQuery  -> menghentikan ikon loading
    # 2) editMessageText      -> mengubah isi pesan jadi hasil akhir
    sudah_dijawab = tg.jawab_tombol(cb.get("id"), teks="Tombol diterima bot")
    try:
        tg.edit_pesan(
            chat_id,
            pesan.get("message_id"),
            f"UJI BOT SELESAI\n\nTombol yang kamu tekan: {data_tekanan}\n"
            "Kalau pesan ini berubah, berarti alur tombol bekerja penuh.",
        )
        pesan_diubah = True
    except tg.TelegramError as galat:
        print(f"      Gagal mengubah pesan: {galat}")
        pesan_diubah = False

    return hasil(
        "Tombol (callback)",
        bool(sudah_dijawab and pesan_diubah and data_tekanan),
        f"jawab_tombol={'ok' if sudah_dijawab else 'gagal'}, edit_pesan={'ok' if pesan_diubah else 'gagal'}",
    ), offset


# ============================================================
# CEK 4 — mengirim file (multipart)
# ============================================================
def cek_4_kirim_file(chat_id) -> bool:
    judul("CEK 4 — Apakah bot bisa mengirim file (CSV)?")
    contoh = cfg.FOLDER_LOG / "uji_kirim_file.csv"
    contoh.parent.mkdir(parents=True, exist_ok=True)
    contoh.write_text(
        "kolom_uji,nilai\n"
        "catatan,file ini dibuat otomatis oleh uji_telegram.py\n"
        "tujuan,membuktikan jalur kirim CSV/JSON bekerja\n",
        encoding="utf-8",
    )
    print(f"  File contoh dibuat: {contoh}")
    print(f"  Ukuran: {contoh.stat().st_size} byte. Mengirim ke chat {chat_id}...")
    try:
        tg.kirim_file(chat_id, contoh, keterangan="Uji kirim file CSV (bukan data asli)")
    except tg.TelegramError as galat:
        return hasil("Kirim file", False, str(galat))
    return hasil("Kirim file", True, "file terkirim — cek di Telegram")


# ============================================================
# ALUR UTAMA
# ============================================================
def main():
    judul("ALAT UJI BOT TELEGRAM — SCRAPPER INSTAGRAM (biaya Rp0)")

    masalah_setelan = cfg.periksa_kesiapan()
    if masalah_setelan:
        print("  Catatan kesiapan setelan:")
        for m in masalah_setelan:
            print(f"    - {m}")

    if not tg.TOKEN_BOT:
        print("\n  Token bot belum ada. Alat ini butuh BOT_TELEGRAM_TOKEN di instagram/bot/.env.")
        return

    laporan = {}
    offset = 0

    laporan["Token bot"] = cek_1_token()
    if not laporan["Token bot"]:
        print("\n  Uji dihentikan: tanpa token yang benar, cek berikutnya tidak ada artinya.")
        ringkasan(laporan)
        return

    # Buang sisa pesan lama supaya CEK 2 tidak terjawab oleh pesan dari masa lalu.
    dibuang = tg.hapus_antrean_belum_dibaca()
    print(f"\n  (Membersihkan {dibuang} pesan lama yang belum diproses.)")

    laporan["Terima pesan"], offset, chat_id = cek_2_terima_pesan(offset)

    if laporan["Terima pesan"] and chat_id:
        lanjut = tanya("\n  Tekan Enter untuk lanjut CEK 3 (kirim pesan + tombol), atau 'n' untuk berhenti: ")
        if lanjut.lower() != "n":
            laporan["Kirim pesan + tombol"], offset = cek_3_kirim_tombol(chat_id, offset)
            if laporan.get("Kirim pesan + tombol"):
                lanjut = tanya("\n  Tekan Enter untuk lanjut CEK 4 (kirim file), atau 'n' untuk berhenti: ")
                if lanjut.lower() != "n":
                    laporan["Kirim file"] = cek_4_kirim_file(chat_id)

    ringkasan(laporan)


def ringkasan(laporan: dict):
    judul("RINGKASAN HASIL UJI")
    for nama, lulus in laporan.items():
        print(f"  {'LULUS' if lulus else 'GAGAL'}  {nama}")
    jumlah_lulus = sum(1 for v in laporan.values() if v)
    print(f"\n  {jumlah_lulus}/{len(laporan)} cek lulus.")
    if laporan and jumlah_lulus == len(laporan):
        print("  Pipa Telegram sudah beres. Langkah berikut: uji alur menu (Langkah 3).")
    else:
        print("  Kirimkan keluaran ini ke saya apa adanya; jangan dibetulkan sendiri dulu.")


if __name__ == "__main__":
    main()
