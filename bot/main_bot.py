# -*- coding: utf-8 -*-
"""
main_bot.py
===========
PINTU MASUK bot. Tugasnya sengaja tipis:

  1. Periksa kesiapan setelan (token, allowlist, python scraper) -> berhenti kalau belum siap.
  2. Jalankan LOOP LONG POLLING: tanya Telegram "ada pesan baru?", kerjakan, ulangi.
  3. Simpan `offset` (penanda pesan terakhir yang sudah diproses) ke file,
     supaya pesan yang masuk saat bot mati tidak hilang dan tidak diproses dua kali.

CARA PAKAI (Windows PowerShell):
    cd D:\\DKIS_MONITORING_FACEBOOK_TIKTOK\\instagram\\bot
    C:\\Python314\\python.exe main_bot.py              # mode normal (jalan terus)
    C:\\Python314\\python.exe main_bot.py --sekali     # ambil sekali lalu keluar (untuk uji)
    C:\\Python314\\python.exe main_bot.py --bersihkan  # buang pesan lama, lalu keluar

Hentikan dengan Ctrl+C. Sesi (sedang di langkah berapa tiap user) TIDAK hilang,
karena disimpan di data/sesi.json.

PENTING: satu token Telegram hanya boleh ditarik SATU proses. Jangan menjalankan
main_bot.py bersamaan dengan uji_telegram.py atau proses lain yang memakai token sama.
"""

import argparse
import json
import sys
from pathlib import Path

import bot_config as cfg
import menu_bot
import telegram_api as tg

PATH_STATE = cfg.FOLDER_BOT / "data" / "state_bot.json"


def muat_state() -> dict:
    if not PATH_STATE.exists():
        return {"offset": 0}
    try:
        isi = json.loads(PATH_STATE.read_text(encoding="utf-8"))
        return isi if isinstance(isi, dict) else {"offset": 0}
    except Exception:
        return {"offset": 0}


def simpan_state(state: dict):
    try:
        PATH_STATE.parent.mkdir(parents=True, exist_ok=True)
        PATH_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as galat:
        print(f"[BOT] Gagal menyimpan state: {galat}")


def muat_penjalan_job():
    """
    Ambil mesin pengeksekusi job kalau modulnya sudah ada (Langkah 4: job_runner).
    Kalau belum ada, bot tetap berjalan dan akan jujur mengatakan bahwa eksekusi
    belum diaktifkan — jadi alur menu bisa diuji lebih dulu tanpa biaya apa pun.
    """
    try:
        import job_runner
        return job_runner.jalankan_job
    except Exception:
        return None


def tampilkan_pembuka():
    print("=" * 74)
    print("   BOT TELEGRAM - SCRAPPER INSTAGRAM MEDIA KOTA CIREBON")
    print("=" * 74)
    try:
        info = tg.info_bot()
        print(f"   Bot         : {info.get('first_name')} (@{info.get('username')})")
    except tg.TelegramError as galat:
        print(f"   GAGAL memanggil Telegram: {galat}")
        print("   Periksa BOT_TELEGRAM_TOKEN di instagram/bot/.env")
        sys.exit(1)

    print(f"   Pengguna    : {len(cfg.daftar_user_efektif())} orang diizinkan")
    print(f"   Media       : {len(cfg.DAFTAR_MEDIA)} akun terdaftar")
    print(f"   Batas       : {cfg.HARI_MIN}-{cfg.HARI_MAKS} hari, maks {cfg.MAKS_POST_PLAFON} post/akun")
    print(f"   Scraper     : {cfg.SKRIP_SCRAPER}")

    penjalan = muat_penjalan_job()
    if penjalan is None:
        print("   Mesin job   : BELUM AKTIF (modul job_runner belum ada) - menu bisa dicoba, "
              "tombol MULAI belum mengeksekusi apa pun")
    else:
        print("   Mesin job   : AKTIF")
        try:
            info_job = __import__("job_runner").status_ringkas()
            print(f"   Antrean     : {info_job}")
        except Exception:
            pass
    print("-" * 74)


def main():
    parser = argparse.ArgumentParser(description="Bot Telegram scrapper Instagram Kota Cirebon")
    parser.add_argument("--sekali", action="store_true",
                        help="Ambil update sekali lalu keluar (untuk uji coba)")
    parser.add_argument("--bersihkan", action="store_true",
                        help="Buang semua pesan lama yang belum diproses, lalu keluar")
    args = parser.parse_args()

    masalah = cfg.periksa_kesiapan()
    if masalah:
        print("Bot belum bisa dijalankan karena setelan belum lengkap:")
        for m in masalah:
            print(f"  - {m}")
        sys.exit(1)

    if args.bersihkan:
        jumlah = tg.hapus_antrean_belum_dibaca()
        print(f"Selesai. {jumlah} pesan lama dibuang.")
        return

    menu_bot.muat_sesi()
    state = muat_state()
    offset = int(state.get("offset") or 0)

    if offset == 0 and not args.sekali:
        # Belum ada catatan offset -> kemungkinan bot baru pertama jalan.
        # Pesan lama dibuang supaya bot tidak membalas percakapan berhari-hari lalu.
        dibuang = tg.hapus_antrean_belum_dibaca()
        print(f"(Bot baru start: {dibuang} pesan lama dibuang.)")

    tampilkan_pembuka()
    penjalan = muat_penjalan_job()
    if penjalan is not None:
        # Job yang tercatat "berjalan" padahal bot baru menyala = terputus. Proses
        # scraper-nya (yang kemungkinan besar masih hidup sebagai proses yatim) dimatikan
        # di sini, karena kalau dibiarkan dia terus memakai Apify & API key yang sama.
        try:
            import job_runner
            job_runner.bersihkan_job_terputus()
            sisa = job_runner.cari_proses_scraper_lain()
            if sisa:
                print(sisa)
        except Exception:
            pass
    print("Bot berjalan. Tekan Ctrl+C untuk berhenti.\n")

    while True:
        try:
            daftar = tg.ambil_pesan(offset=offset if offset else None, timeout_polling=50)
        except tg.TelegramError as galat:
            print(f"[BOT] Gagal mengambil pesan: {galat}")
            if galat.kode in (401, 404, 409):
                print("[BOT] Kesalahan token/konflik -> bot dihentikan.")
                break
            print("[BOT] Mencoba lagi dalam 5 detik...")
            _tidur(5)
            continue
        except KeyboardInterrupt:
            print("\n[BOT] Dihentikan user.")
            break

        for update in daftar:
            offset = max(offset, int(update.get("update_id", 0)) + 1)
            try:
                menu_bot.proses_update(update, penjalan_job=penjalan)
            except Exception as galat:
                # Satu update bermasalah tidak boleh mematikan seluruh bot.
                print(f"[BOT] Gagal memproses update {update.get('update_id')}: {galat}")

        if daftar:
            state["offset"] = offset
            simpan_state(state)
            menu_bot.simpan_sesi()

        if args.sekali:
            print(f"Selesai sekali jalan. Offset terakhir: {offset}. "
                  f"{len(daftar)} update diproses.")
            return

    # ==== Keluar dari loop: jangan tinggalkan proses scraper yang jadi yatim ====
    # Kalau jendela ini ditutup saat job berjalan, proses scraper TIDAK ikut mati di
    # Windows. Proses yatim itu terus memakai Apify dan API key yang sama, sehingga job
    # berikutnya terasa jauh lebih lambat. Ini yang mencegahnya.
    if penjalan is not None:
        try:
            import job_runner
            job_runner.hentikan_semua()
        except Exception:
            pass
    print("[BOT] Bot berhenti. Tidak ada proses scraper yang ditinggalkan.")


def _tidur(detik: int):
    import time
    time.sleep(detik)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[BOT] Dihentikan user.")
        # Membersihkan proses scraper yang mungkin masih berjalan.
        try:
            import job_runner
            job_runner.hentikan_semua()
        except Exception:
            pass
        print("[BOT] Pembersihan selesai.")
