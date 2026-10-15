# -*- coding: utf-8 -*-
"""
main.py (launcher root)
=======================
Pintu masuk utama proyek D:\\DKIS_MONITORING_FACEBOOK_TIKTOK.

Tugasnya hanya SATU: meneruskan perintah ke modul platform (tiktok/ atau facebook/).
Setiap platform dijalankan sebagai PROSES TERPISAH (subprocess). Alasannya: tiap modul
memakai nama file yang sama (config.py, evaluator.py, storage.py, main.py), jadi kalau
dijalankan dalam satu proses, modul platform pertama akan tersangkut di memori dan platform
kedua memakai config yang SALAH.

CARA PAKAI
----------
    python main.py                                  # menu interaktif (pilih platform)
    python main.py --tiktok                         # langsung TikTok (menu internalnya)
    python main.py --tiktok --topik "jalan rusak" --day 30 --dry-run
    python main.py --facebook --topik "banjir" --day 30
    python main.py --semua --topik "jalan rusak" --day 30

Semua argumen lain (--topik, --day, --month, --year, --from, --to, --max, --dry-run,
--no-llm, --refresh-rules, --contoh, --token) OTOMATIS diteruskan ke modul platform.
"""

import argparse
import subprocess
import sys
from pathlib import Path

FOLDER_ROOT = Path(__file__).resolve().parent

# nama: (label menu, folder kode modul)
PLATFORM = {
    "tiktok": ("TIKTOK", FOLDER_ROOT / "tiktok" / "code"),
    "facebook": ("FACEBOOK", FOLDER_ROOT / "facebook" / "code"),
}


def tampilkan_menu() -> str:
    print("=" * 78)
    print("   MASTER SCRAPPER MONITORING ISU KOTA CIREBON (DKIS)")
    print("=" * 78)
    print("\nPILIH PLATFORM:")
    print("  1. TIKTOK    — cari video per topik + gerbang wilayah + penilaian AI")
    print("  2. FACEBOOK  — cari post per topik (modul menyusul)")
    print("  3. DUA-DUANYA (TikTok lalu Facebook)")
    print("  0. Keluar")
    return input("\nMasukkan pilihan (0-3) [Default: 1]: ").strip()


def jalankan_platform(nama: str, argumen_tambahan: list = None) -> int:
    """Jalankan modul 1 platform sebagai proses terpisah. Returns kode keluar."""
    label, folder_code = PLATFORM[nama]
    script = folder_code / "main.py"

    print("\n" + "=" * 78)
    print(f"▶ Menjalankan modul {label}")
    print(f"  Folder : {folder_code}")
    print("=" * 78)

    if not script.exists():
        print(f"❌ Modul {label} belum tersedia (tidak ada {script}).")
        print(f"   Modul TikTok sudah selesai; modul Facebook menyusul.")
        return 1

    perintah = [sys.executable, "main.py"] + list(argumen_tambahan or [])
    try:
        hasil = subprocess.run(perintah, cwd=str(folder_code), check=False)
        return hasil.returncode
    except KeyboardInterrupt:
        print("\n⏹ Dihentikan user (Ctrl+C).")
        return 130
    except Exception as e:
        print(f"❌ Gagal menjalankan modul {label}: {e}")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Launcher monitoring isu Kota Cirebon (TikTok/Facebook)",
        epilog='Argumen seperti --topik / --day diteruskan ke modul platform.',
    )
    parser.add_argument("--tiktok", action="store_true", help="Jalankan modul TikTok")
    parser.add_argument("--facebook", action="store_true", help="Jalankan modul Facebook")
    parser.add_argument("--semua", action="store_true", help="Jalankan TikTok lalu Facebook")
    args, argumen_sisa = parser.parse_known_args()

    # --- mode perintah langsung ---
    if args.semua:
        kode = 0
        for nama in ("tiktok", "facebook"):
            kode = jalankan_platform(nama, argumen_sisa) or kode
        sys.exit(kode)
    if args.tiktok:
        sys.exit(jalankan_platform("tiktok", argumen_sisa))
    if args.facebook:
        sys.exit(jalankan_platform("facebook", argumen_sisa))

    # --- ada argumen tanpa nama platform? anggap TikTok (platform yang sudah jadi) ---
    if argumen_sisa:
        print(f"ℹ️ Platform tidak disebut, tapi ada argumen {argumen_sisa} -> dijalankan ke TikTok.")
        print("   (pakai --facebook kalau memang mau modul Facebook)")
        sys.exit(jalankan_platform("tiktok", argumen_sisa))

    # --- menu interaktif ---
    pilihan = tampilkan_menu()
    if pilihan == "0":
        print("Selesai.")
        return
    if pilihan == "2":
        jalankan_platform("facebook")
    elif pilihan == "3":
        jalankan_platform("tiktok")
        jalankan_platform("facebook")
    else:
        jalankan_platform("tiktok")


if __name__ == "__main__":
    main()
