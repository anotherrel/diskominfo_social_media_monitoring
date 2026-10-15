# -*- coding: utf-8 -*-
"""
main.py
=======
Script Utama (Entry Point) untuk Scrapper Instagram Media Kota Cirebon.

Fitur & Alur Kerja:
1. Default Mode: Scrape 10 akun media Kota Cirebon (30 hari terakhir, Top 3 video per akun).
2. Custom Mode:
   - Pilih dari 10 akun media ATAU input username akun baru.
   - Tentukan rentang hari (1 - HARI_MAKS_SCRAPE hari, sekarang 365).
   - Tentukan batas maksimal post per akun (resultsLimit ke Apify).
   - Tentukan jumlah post teratas per akun yang mau ditarik komentarnya.
3. Filter post wajib memuat "Kota Cirebon" -> Simpan ke folder post/<nama_akun>/<YYYY-MM-DD>/.
4. Catat riwayat ke history/history_post.csv & history_post.json.
5. Alert Interaktif: Menanyakan user apakah ingin melanjutkan scraping komentar untuk Top Video.
6. Scraping Komentar -> Simpan ke comment/<nama_akun>/<YYYY-MM-DD>/ & catat ke history_comment.csv & json.
   Analisis sentimen komentar: IndoBERTweet (kolom 'sentimen' + 'skor_yakin').
   CATATAN 24 Sep 2026: tahap penilaian sentimen oleh LLM SUDAH DILEPAS. Karena itu
   kolom 'sentimen_ai', 'alasan_ai', 'butuh_review', dan 'alasan_review' tidak lagi
   ditulis. Berkas lama yang masih memuat kolom itu tetap bisa dibuka seperti biasa.

Cara Jalankan:
    python main.py                     # Menjalankan menu interaktif
    python main.py --default           # Jalankan langsung 10 akun (30 hari)
    python main.py --hari 7            # Scraping semua akun selama 7 hari
    python main.py --akun radarcirebon # Scraping 1 akun tertentu
    python main.py --akun radarcirebon --hari 90 --maks-post 500 --top-video 5 --scrape-comments
"""

import argparse
import sys
import uuid
from datetime import datetime, timedelta, timezone

# ============================================================
# KELUARAN DICETAK BARIS DEMI BARIS (line buffering)
# ============================================================
# Kalau stdout bukan terminal (misalnya dijalankan bot Telegram lewat pipe),
# Python menahan cetakan di buffer 8 KB dan baru membuangnya di akhir. Akibatnya
# bot tidak bisa melaporkan progres secara langsung dan terlihat "diam".
# Ketahuan pada uji nyata 22 Sep 2026. Pengaturan ini membuat tiap print langsung
# terkirim, sehingga bot bisa melaporkan tahap yang sedang berjalan.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass

from config import (
    DAFTAR_AKUN,
    FOLDER_POST,
    FOLDER_COMMENT,
    FOLDER_HISTORY,
    HARI_MAKS_SCRAPE,
    KATA_KUNCI_FILTER,
    KOMENTAR_AMBANG_AMBIL_SEMUA,
    MAKS_KOMENTAR_DEFAULT,
    MAKS_KOMENTAR_PLAFON,
    MAKS_POST_DEFAULT,
    MAKS_POST_MAKS,
    ambil_apify_token,
)
from apify_client import validasi_apify_token, scrape_posts_apify, scrape_comments_apify
from storage import (
    saring_dan_simpan_dataset,
    catat_riwayat_post,
    simpan_dataset_comment,
    catat_riwayat_comment,
)


def tampilkan_header():
    """Tampilan header sederhana di terminal."""
    print("=" * 75)
    print("      SCRAPPER INSTAGRAM MEDIA KOTA CIREBON - DISKOMINFO")
    print("=" * 75)


def pilih_menu_interaktif():
    """
    Menampilkan menu pilihan interaktif untuk user pemula.
    Returns:
    - daftar_dipilih (list) : Akun yang akan di-scrape
    - jumlah_hari (int)     : Rentang hari (1 - HARI_MAKS_SCRAPE hari)
    - top_n_video (int)     : Jumlah video top comment per akun
    - maks_post (int)       : Batas maksimal post per akun (resultsLimit ke Apify)
    """
    print("\nPILIHAN MODE SCRAPING:")
    print("1. [DEFAULT] Scrape SEMUA 10 akun media (30 hari terakhir, Top 3 video per akun)")
    print("2. [KUSTOM ] Pilih/Input akun, tentukan rentang hari, & tentukan jumlah top video")
    
    pilihan = input("\nMasukkan pilihan (1 atau 2) [Default: 1]: ").strip()
    
    if pilihan == "2":
        # Mode Kustom
        print("\n--- DAFTAR AKUN MEDIA TERSEDIA ---")
        for idx, (username, _, nama) in enumerate(DAFTAR_AKUN, 1):
            print(f"  {idx}. @{username:<18} ({nama})")
        print("  0. Pilih SEMUA AKUN TERSEDIA")
        print("  *(Bisa juga ketik username akun lain di luar daftar, misal: infocirebon, cirebon_kuliner)")

        input_akun = input("\nMasukkan nomor/username akun (pisahkan dengan koma, misal: 1,3 atau infocirebon): ").strip()
        
        daftar_dipilih = []
        if input_akun and input_akun != "0":
            items = [item.strip() for item in input_akun.split(",") if item.strip()]
            for item in items:
                if item.isdigit():
                    idx_n = int(item) - 1
                    if 0 <= idx_n < len(DAFTAR_AKUN):
                        if DAFTAR_AKUN[idx_n] not in daftar_dipilih:
                            daftar_dipilih.append(DAFTAR_AKUN[idx_n])
                else:
                    # Raw username input dari user
                    clean_username = item.lower().replace("@", "")
                    matched = [a for a in DAFTAR_AKUN if a[0].lower() == clean_username]
                    if matched:
                        if matched[0] not in daftar_dipilih:
                            daftar_dipilih.append(matched[0])
                    else:
                        folder_name = clean_username.replace(".", "_")
                        tuple_custom = (clean_username, folder_name, clean_username)
                        if tuple_custom not in daftar_dipilih:
                            daftar_dipilih.append(tuple_custom)
        
        if not daftar_dipilih:
            print("  ℹ️ Menggunakan semua akun media default.")
            daftar_dipilih = DAFTAR_AKUN

        # Rentang hari (Min 1, Max HARI_MAKS_SCRAPE)
        while True:
            try:
                input_hari = input(f"\nMasukkan jumlah hari ke belakang (1 - {HARI_MAKS_SCRAPE} hari) [Default: 30]: ").strip()
                if not input_hari:
                    jumlah_hari = 30
                    break
                jumlah_hari = int(input_hari)
                if 1 <= jumlah_hari <= HARI_MAKS_SCRAPE:
                    break
                else:
                    print(f"  ⚠️ Harap masukkan angka antara 1 sampai {HARI_MAKS_SCRAPE}!")
            except ValueError:
                print("  ⚠️ Harap masukkan angka yang valid!")

        # Batas maksimal post yang diambil per akun (resultsLimit ke Apify)
        while True:
            try:
                input_maks = input(f"\nBatas maksimal post per akun (1 - {MAKS_POST_MAKS}) [Default: {MAKS_POST_DEFAULT}]: ").strip()
                if not input_maks:
                    maks_post = MAKS_POST_DEFAULT
                    break
                maks_post = int(input_maks)
                if 1 <= maks_post <= MAKS_POST_MAKS:
                    break
                else:
                    print(f"  ⚠️ Harap masukkan angka antara 1 sampai {MAKS_POST_MAKS}!")
            except ValueError:
                print("  ⚠️ Harap masukkan angka yang valid!")

        # Top video per akun
        while True:
            try:
                input_top = input("\nMasukkan jumlah video top comment per akun yang ingin diidentifikasi [Default: 3]: ").strip()
                if not input_top:
                    top_n_video = 3
                    break
                top_n_video = int(input_top)
                if top_n_video >= 1:
                    break
                else:
                    print("  ⚠️ Harap masukkan angka minimal 1!")
            except ValueError:
                print("  ⚠️ Harap masukkan angka yang valid!")

        return daftar_dipilih, jumlah_hari, top_n_video, maks_post

    else:
        # Mode Default
        print("  ℹ️ Menjalankan mode default: Semua 10 akun, 30 hari, Top 3 video per akun.")
        return DAFTAR_AKUN, 30, 3, MAKS_POST_DEFAULT


def tentukan_batas_komentar(vids, batas_per_post):
    """
    Tentukan batas komentar yang layak dipakai untuk sekumpulan postingan terpilih.

    KEBIJAKAN (permintaan user 22 Sep 2026):
      - Kalau JUMLAH komentar dari semua postingan terpilih KURANG dari
        KOMENTAR_AMBANG_AMBIL_SEMUA, batas per post DIABAIKAN -> semua komentar tiap
        postingan diambil. Untuk jumlah sekecil itu, batas hanya memotong data tanpa
        menghemat waktu/biaya berarti.
      - Kalau tidak, batas per post dihormati seperti biasa.

    KENAPA results_limit DIHITUNG SENDIRI:
    Actor Apify hanya mengenal batas TOTAL komentar, BUKAN batas per post. Sebelumnya
    angka ini selalu diisi "batas per post x jumlah post", sehingga actor boleh
    menghabiskan seluruh kuota pada satu postingan saja sementara postingan lain tidak
    kebagian. Dengan angka ini, jumlah yang diminta = jumlah yang benar-benar dibutuhkan.

    Returns: (batas_efektif, results_limit, total_tersedia, keterangan)
    """
    jumlah = [int(v.get("comment_count") or 0) for v in vids]
    total_tersedia = sum(jumlah)

    if total_tersedia and total_tersedia < KOMENTAR_AMBANG_AMBIL_SEMUA:
        batas_efektif = MAKS_KOMENTAR_PLAFON
        keterangan = (f"Total komentar pada postingan terpilih hanya {total_tersedia} "
                      f"(di bawah {KOMENTAR_AMBANG_AMBIL_SEMUA}) -> batas per post diabaikan, "
                      f"SEMUA komentar tiap postingan diambil.")
    else:
        batas_efektif = batas_per_post
        keterangan = ""

    results_limit = sum(min(n or batas_efektif, batas_efektif) for n in jumlah)
    if not results_limit:
        results_limit = batas_efektif * len(vids)
    return batas_efektif, results_limit, total_tersedia, keterangan


def proses_scraping(daftar_akun_scrape, jumlah_hari, top_n_video, apify_token, auto_confirm_comments=False, skip_comments=False, maks_post_per_akun=MAKS_POST_DEFAULT, maks_komentar_per_post=MAKS_KOMENTAR_DEFAULT):
    """
    Fungsi utama yang mengeksekusi siklus scraping post & comment.

    Parameters tambahan:
    - maks_post_per_akun     : resultsLimit ke actor Apify per akun (default 300, plafon 1000)
    - maks_komentar_per_post : batas komentar per post (default 100, plafon 500).
                               Angka ini penentu lama-tidaknya tahap sentimen + penilaian AI.
    """
    waktu_sekarang_dt = datetime.now(timezone.utc)
    waktu_awal_dt = waktu_sekarang_dt - timedelta(days=jumlah_hari)

    hingga_iso = waktu_sekarang_dt.strftime("%Y-%m-%dT23:59:59Z")
    sejak_iso = waktu_awal_dt.strftime("%Y-%m-%dT00:00:00Z")

    print("\n" + "=" * 75)
    print(f"Periode Scraping  : {sejak_iso[:10]} s/d {hingga_iso[:10]} ({jumlah_hari} hari)")
    print(f"Jumlah Akun       : {len(daftar_akun_scrape)} akun")
    print(f"Top Video / Akun  : {top_n_video} video")
    print(f"Batas Post/Akun   : {maks_post_per_akun} post (resultsLimit ke Apify)")
    print(f"Komentar/Post     : {maks_komentar_per_post} komentar per post")
    print(f"Filter Kata Kunci : '{KATA_KUNCI_FILTER}'")
    print(f"Folder Post Output: {FOLDER_POST}")
    print("=" * 75)

    total_post_terfilter = 0
    total_sukses = 0
    total_gagal = 0

    all_top_videos_by_account = []

    for i, (username, folder_akun, nama_tampilan) in enumerate(daftar_akun_scrape, 1):
        print(f"\n---------------------------------------------------------------------------")
        print(f"[{i}/{len(daftar_akun_scrape)}] Memproses Post: {nama_tampilan} (@{username})")
        print(f"---------------------------------------------------------------------------")

        scrape_id = f"scrape_{uuid.uuid4().hex[:10]}"
        started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 1. Jalankan scraper post via Apify
        raw_items, status, error_msg = scrape_posts_apify(
            username=username,
            sejak_iso=sejak_iso,
            hingga_iso=hingga_iso,
            max_posts=maks_post_per_akun,
            token=apify_token,
        )

        finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        records_fetched = len(raw_items)

        records_inserted = 0
        top_videos = []
        top_video_ids = []

        if status == "success":
            try:
                records_inserted, path_csv, path_json, top_videos, post_terfilter = saring_dan_simpan_dataset(
                    raw_items=raw_items,
                    username=username,
                    folder_akun=folder_akun,
                    jumlah_hari=jumlah_hari,
                    top_n_video=top_n_video,
                    scrape_id=scrape_id,
                    waktu_scrape=finished_at,
                )
                top_video_ids = [v["post_id"] for v in top_videos]

                print(f"  ✨ Sukses Filter & Simpan Post!")
                print(f"     - Data Mentah Apify : {records_fetched} post")
                print(f"     - Lolos Filter ('{KATA_KUNCI_FILTER}'): {records_inserted} post")
                print(f"     - Top Video Komentar Terbanyak : {len(top_videos)} video")
                print(f"     - CSV  : {path_csv}")
                print(f"     - JSON : {path_json}")
                
                total_sukses += 1
                total_post_terfilter += records_inserted

                if top_videos:
                    all_top_videos_by_account.append({
                        "account": (username, folder_akun, nama_tampilan),
                        "post_scrape_id": scrape_id,
                        "top_videos": top_videos,
                    })

            except Exception as e:
                status = "failed"
                error_msg = f"Gagal saat menyimpan dataset post: {str(e)}"
                print(f"  ❌ Error simpan dataset: {e}")
                total_gagal += 1
        else:
            total_gagal += 1

        # 3. Catat Riwayat Scraping Post
        catat_riwayat_post(
            scrape_id=scrape_id,
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            records_fetched=records_fetched,
            records_inserted=records_inserted,
            count_top_comment_video=len(top_video_ids),
            top_comment_video_ids=top_video_ids,
            error_message=error_msg,
        )
        print(f"  📝 Riwayat scraping post tersimpan di history/history_post.csv & .json")

    # Ringkasan Akhir Scraping Post
    print("\n" + "=" * 75)
    print("                 RINGKASAN TAHAP SCRAPING POSTINGAN")
    print("=" * 75)
    print(f" Total Akun Diproses : {len(daftar_akun_scrape)}")
    print(f" Akun Sukses         : {total_sukses}")
    print(f" Akun Gagal          : {total_gagal}")
    print(f" Total Post Saved    : {total_post_terfilter} post (memuat 'Kota Cirebon')")
    print(f" Log History Post    : {FOLDER_HISTORY / 'history_post.csv'}")
    print("=" * 75)

    # 4. STEP ALERT INTERAKTIF & SCRAPING KOMENTAR
    total_top_videos_found = sum(len(item["top_videos"]) for item in all_top_videos_by_account)

    if total_top_videos_found == 0:
        print("\nℹ️ Tidak ditemukan postingan yang memuat kata 'Kota Cirebon' untuk di-scrape komentarnya.")
        return

    print("\n" + "!" * 75)
    print("                           ALERT INTERAKTIF")
    print("!" * 75)
    print(f" Berhasil mengidentifikasi {total_top_videos_found} postingan (semua tipe post) dengan komentar terbanyak:")
    
    for item in all_top_videos_by_account:
        usr = item["account"][0]
        vids = item["top_videos"]
        print(f"\n 📸 @{usr} ({len(vids)} post terpilih):")
        for idx_v, v in enumerate(vids, 1):
            t_type = v.get("post_type", "Post")
            print(f"    {idx_v}. [{t_type}] Post ID: {v['post_id']} | Comments: {v['comment_count']} | Likes: {v['like_count']}")

    print("\n" + "!" * 75)

    if auto_confirm_comments:
        lanjut = "y"
    elif skip_comments:
        lanjut = "n"
    else:
        lanjut = input("\nApakah Anda ingin melanjutkan scraping komentar untuk postingan terpilih tersebut? (Y/N) [Default: N]: ").strip().lower()

    if lanjut != "y":
        print("\nℹ️ Scraping komentar dilewati oleh user. Proses Selesai!")
        return

    print("\n" + "=" * 75)
    print("                     MEMULAI SCRAPING KOMENTAR")
    print("=" * 75)

    for item in all_top_videos_by_account:
        username, folder_akun, nama_tampilan = item["account"]
        vids = item["top_videos"]
        if not vids:
            continue

        print(f"\n---------------------------------------------------------------------------")
        print(f"Memproses Komentar Video: {nama_tampilan} (@{username}) - {len(vids)} video")
        print(f"---------------------------------------------------------------------------")

        target_urls = [v.get("_url") or f"https://www.instagram.com/p/{v['post_id']}/" for v in vids]
        fallback_post_id = vids[0]["post_id"] if vids else ""

        # Kebijakan batas komentar untuk postingan-postingan ini.
        # Jumlah komentarnya sudah diketahui dari tahap postingan, jadi tidak ada yang ditebak.
        batas_efektif, results_limit, total_tersedia, ket_batas = tentukan_batas_komentar(
            vids, maks_komentar_per_post
        )
        if ket_batas:
            print(f"  ℹ️ {ket_batas}")
        print(f"  ℹ️ Batas komentar dipakai : {batas_efektif} komentar/post "
              f"(total tersedia {total_tersedia}; diminta ke Apify {results_limit} komentar)")

        scrape_comment_id = f"scrape_comment_{uuid.uuid4().hex[:10]}"
        started_at_c = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Scrape komentar via Apify
        raw_comments, status_c, error_msg_c = scrape_comments_apify(
            target_urls=target_urls,
            max_comments_per_post=maks_komentar_per_post,
            token=apify_token,
            results_limit=results_limit,
        )

        finished_at_c = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        records_fetched_c = len(raw_comments)
        records_inserted_c = 0

        top_video_ids = [v.get("external_post_id") or v.get("post_id") or "" for v in vids]

        if status_c == "success":
            try:
                (records_inserted_c, path_c_csv, path_c_json,
                 stats_c) = simpan_dataset_comment(
                    raw_comments=raw_comments,
                    username=username,
                    folder_akun=folder_akun,
                    jumlah_hari=jumlah_hari,
                    top_videos=vids,
                    fallback_post_id=fallback_post_id,
                    scrape_comment_id=scrape_comment_id,
                    waktu_scrape=finished_at_c,
                )
                print(f"  ✨ Sukses Simpan & Evaluasi Komentar!")
                print(f"     - Komentar Fetched : {records_fetched_c}")
                print(f"     - Komentar Saved   : {records_inserted_c}")
                print(f"     - Sentimen IndoBERTweet:")
                print(f"       * POSITIF : {stats_c['POSITIF']} ({stats_c['POSITIF_pct']})")
                print(f"       * NEGATIF : {stats_c['NEGATIF']} ({stats_c['NEGATIF_pct']})")
                print(f"       * NETRAL  : {stats_c['NETRAL']} ({stats_c['NETRAL_pct']})")
                print(f"     - CSV  : {path_c_csv}")
                print(f"     - JSON : {path_c_json}")
            except Exception as e:
                status_c = "failed"
                error_msg_c = f"Gagal simpan dataset komentar: {str(e)}"
                print(f"  ❌ Error simpan komentar: {e}")

        # Catat History Komentar
        catat_riwayat_comment(
            scrape_comment_id=scrape_comment_id,
            started_at=started_at_c,
            finished_at=finished_at_c,
            status=status_c,
            records_fetched=records_fetched_c,
            records_inserted=records_inserted_c,
            count_top_comment_video=len(top_video_ids),
            top_comment_video_ids=top_video_ids,
            error_message=error_msg_c,
        )
        print(f"  📝 Riwayat scraping komentar tersimpan di history/history_comment.csv & .json")

    print("\n" + "=" * 75)
    print("      PROSES SCRAPING & ANALISIS SENTIMEN KOMENTAR TOTAL SELESAI!")
    print("=" * 75 + "\n")


def main():
    tampilkan_header()

    # Setup Argument Parser untuk CLI
    parser = argparse.ArgumentParser(description="Scrapper Instagram Media Kota Cirebon (Diskominfo)")
    parser.add_argument("--default", action="store_true", help="Jalankan mode default (10 akun, 30 hari, top 3 video)")
    parser.add_argument("--hari", type=int, default=None, help=f"Jumlah hari ke belakang (1 - {HARI_MAKS_SCRAPE})")
    parser.add_argument("--akun", type=str, default=None, help="Username akun IG tertentu (misal: radarcirebon atau radarcirebon,infocirebon)")
    parser.add_argument("--top-video", type=int, default=3, help="Jumlah video top comment per akun (default: 3)")
    parser.add_argument("--maks-post", type=int, default=MAKS_POST_DEFAULT, help=f"Batas maksimal post per akun (1 - {MAKS_POST_MAKS}, default: {MAKS_POST_DEFAULT})")
    parser.add_argument("--maks-komentar", type=int, default=MAKS_KOMENTAR_DEFAULT, help=f"Batas komentar per post (1 - {MAKS_KOMENTAR_PLAFON}, default: {MAKS_KOMENTAR_DEFAULT})")
    parser.add_argument("--token", type=str, default=None, help="Token API Apify")
    parser.add_argument("--scrape-comments", action="store_true", help="Otomatis scrape komentar tanpa prompt alert")
    parser.add_argument("--skip-comments", action="store_true", help="Otomatis lewatkan/tanpa scrape komentar")
    args = parser.parse_args()

    # Validasi API Token
    apify_token = args.token or ambil_apify_token()
    if not apify_token:
        print("\n❌ ERROR: Token Apify tidak ditemukan!")
        print("Pastikan Anda sudah meletakkan APIFY_TOKEN di file .env atau menyertakannya lewat argumen --token.")
        print("Contoh isi file .env: APIFY_TOKEN=apify_api_xxx")
        sys.exit(1)

    if not validasi_apify_token(apify_token):
        print("\n❌ ERROR: Token Apify tidak dapat digunakan. Silakan periksa kembali token Anda.")
        sys.exit(1)

    print("✅ Token Apify Valid!")

    # Penentuan Mode Eksekusi (CLI atau Interaktif Menu)
    if (args.default or args.hari or args.akun or args.scrape_comments or args.skip_comments
            or args.maks_post != MAKS_POST_DEFAULT
            or args.maks_komentar != MAKS_KOMENTAR_DEFAULT):
        # Nilai di luar batas TIDAK dipotong diam-diam -> diberi peringatan lalu dipakai bawaan.
        jumlah_hari = args.hari or 30
        if not (1 <= jumlah_hari <= HARI_MAKS_SCRAPE):
            print(f"⚠️ --hari {jumlah_hari} di luar rentang 1-{HARI_MAKS_SCRAPE} hari. Dipakai 30 hari.")
            jumlah_hari = 30

        top_n_video = args.top_video if args.top_video and args.top_video >= 1 else 3

        maks_post_per_akun = args.maks_post or MAKS_POST_DEFAULT
        if not (1 <= maks_post_per_akun <= MAKS_POST_MAKS):
            print(f"⚠️ --maks-post {maks_post_per_akun} di luar rentang 1-{MAKS_POST_MAKS}. Dipakai {MAKS_POST_DEFAULT}.")
            maks_post_per_akun = MAKS_POST_DEFAULT

        maks_komentar_per_post = args.maks_komentar or MAKS_KOMENTAR_DEFAULT
        if not (1 <= maks_komentar_per_post <= MAKS_KOMENTAR_PLAFON):
            print(f"⚠️ --maks-komentar {maks_komentar_per_post} di luar rentang 1-{MAKS_KOMENTAR_PLAFON}. "
                  f"Dipakai {MAKS_KOMENTAR_DEFAULT}.")
            maks_komentar_per_post = MAKS_KOMENTAR_DEFAULT

        if args.akun:
            target_usernames = [u.strip().lower().replace("@", "") for u in args.akun.split(",") if u.strip()]
            daftar_dipilih = []
            for tu in target_usernames:
                matched = [a for a in DAFTAR_AKUN if a[0].lower() == tu]
                if matched:
                    daftar_dipilih.append(matched[0])
                else:
                    folder_name = tu.replace(".", "_")
                    daftar_dipilih.append((tu, folder_name, tu))
        else:
            daftar_dipilih = DAFTAR_AKUN
    else:
        daftar_dipilih, jumlah_hari, top_n_video, maks_post_per_akun = pilih_menu_interaktif()
        # Menu interaktif belum menanyakan batas komentar -> pakai bawaan.
        maks_komentar_per_post = MAKS_KOMENTAR_DEFAULT

    # Eksekusi Scraping
    proses_scraping(
        daftar_akun_scrape=daftar_dipilih,
        jumlah_hari=jumlah_hari,
        top_n_video=top_n_video,
        apify_token=apify_token,
        auto_confirm_comments=args.scrape_comments,
        skip_comments=args.skip_comments,
        maks_post_per_akun=maks_post_per_akun,
        maks_komentar_per_post=maks_komentar_per_post,
    )



if __name__ == "__main__":
    main()
