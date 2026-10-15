# -*- coding: utf-8 -*-
"""
main.py (cirebon_opd)
======================
Pintu masuk utama untuk scraping dan pemeringkatan keaktifan
32 Akun Instagram Resmi Pemerintah Kota Cirebon (27 OPD/Dinas/Badan + 5 Kecamatan).
"""

import argparse
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Pastikan UTF-8 di Windows terminal
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config import (
    DAFTAR_OPD, PETA_AKUN_OPD, ambil_apify_token,
    HARI_MAKS_SCRAPE, MAKS_POST_DEFAULT, FOLDER_DATA
)
from apify_client import scrape_posts_apify, validasi_apify_token
from storage import simpan_dataset_opd, simpan_ranking_opd, catat_riwayat_opd


def hitung_rentang_tanggal(jumlah_hari: int):
    sekarang = datetime.now(timezone.utc)
    hingga = sekarang.strftime("%Y-%m-%dT23:59:59Z")
    sejak_dt = sekarang - timedelta(days=jumlah_hari)
    sejak = sejak_dt.strftime("%Y-%m-%dT00:00:00Z")
    return sejak, hingga


def jalankan_ranking_opd(jumlah_hari: int = 30, maks_post: int = 50, token: str = None):
    """
    Eksekusi alur pemeringkatan keaktifan 32 akun OPD & Kecamatan Kota Cirebon.
    """
    token_efektif = token or ambil_apify_token()
    if not validasi_apify_token(token_efektif):
        print("❌ GAGAL: Token Apify tidak valid atau belum diisi di .env.")
        return 1

    sejak_iso, hingga_iso = hitung_rentang_tanggal(jumlah_hari)
    waktu_mulai = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_scrape_id = f"opd_ranking_{uuid.uuid4().hex[:8]}"
    tgl_run = waktu_mulai[:10]
    folder_run = FOLDER_DATA / tgl_run
    folder_run.mkdir(parents=True, exist_ok=True)

    daftar_proses = list(DAFTAR_OPD)
    total_akun = len(daftar_proses)

    print(f"\n===========================================================================")
    print(f"🚀 MEMULAI PEMERINGKATAN KEAKTIFAN AKUN OPD KOTA CIREBON")
    print(f"   Run ID: {run_scrape_id} | Target: {total_akun} akun OPD & Kecamatan | Rentang: {jumlah_hari} hari ({sejak_iso[:10]} s/d {hingga_iso[:10]})")
    print(f"   Folder Output: {folder_run}")
    print(f"===========================================================================")

    stat_semua_akun = []
    total_post_global = 0
    akun_sukses = 0
    akun_gagal = 0

    for idx, (username, folder_akun, nama_instansi, kategori) in enumerate(daftar_proses, 1):
        print(f"\n[{idx}/{total_akun}] Memproses Post: {nama_instansi} (@{username})")
        scrape_id = run_scrape_id

        raw_items, status, err = scrape_posts_apify(
            username=username,
            sejak_iso=sejak_iso,
            hingga_iso=hingga_iso,
            max_posts=maks_post,
            token=token_efektif,
        )

        if status != "SUCCEEDED" or not raw_items:
            print(f"  ⚠️ Tidak ada data postingan untuk @{username} (status: {status}).")
            akun_gagal += 1
            stat_semua_akun.append({
                "username": username,
                "folder_akun": folder_akun,
                "nama_instansi": nama_instansi,
                "kategori": kategori,
                "total_post": 0,
                "total_likes": 0,
                "total_comments": 0,
                "total_engagement": 0,
                "skor_keaktifan": 0,
            })
            continue

        rec_inserted, p_csv, p_json, all_posts, stat_akun = simpan_dataset_opd(
            raw_items=raw_items,
            username=username,
            folder_akun=folder_akun,
            jumlah_hari=jumlah_hari,
            scrape_id=scrape_id,
            waktu_scrape=waktu_mulai,
            folder_run=folder_run,
        )

        akun_sukses += 1
        stat_akun["nama_instansi"] = nama_instansi
        stat_akun["kategori"] = kategori
        stat_semua_akun.append(stat_akun)
        total_post_global += rec_inserted

        print(f"  Data Mentah Apify : {len(raw_items)} item")
        print(f"  Lolos Filter Rentang Waktu : {rec_inserted} post")
        print(f"  Engagement: {stat_akun['total_likes']} suka, {stat_akun['total_comments']} komen (Skor: {stat_akun['skor_keaktifan']})")
        print(f"  - CSV  : {p_csv}")
        print(f"  - JSON : {p_json}")

    print(f"\nTotal Post Saved : {total_post_global} post")
    print(f"Akun Sukses : {akun_sukses}")
    print(f"Akun Gagal : {akun_gagal}")

    # Simpan & cetak klasemen ranking
    ranking_csv_path = None
    if stat_semua_akun:
        sorted_ranking, ranking_csv_path = simpan_ranking_opd(
            stat_semua_akun, jumlah_hari, waktu_mulai, folder_run=folder_run
        )
        print(f"\n===========================================================================")
        print(f"🏆 KLASEMEN PERINGKAT KEAKTIFAN AKUN OPD KOTA CIREBON ({jumlah_hari} HARI)")
        print(f"===========================================================================")
        for pos, item in enumerate(sorted_ranking[:10], 1):
            u = item.get("username", "")
            nama = item.get("nama_instansi", u)
            skor = item.get("skor_keaktifan", 0)
            p = item.get("total_post", 0)
            l = item.get("total_likes", 0)
            c = item.get("total_comments", 0)
            print(f"  {pos:2d}. @{u:<24} | Skor: {skor:5d} (Post: {p:2d}, Likes: {l:4d}, Komen: {c:3d}) - {nama}")
        print(f"\n  CSV RANKING : {ranking_csv_path}")

    # Catat log riwayat pemantauan OPD (history)
    waktu_selesai = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    catat_riwayat_opd(
        scrape_id=run_scrape_id,
        target=f"{total_akun}_akun_opd",
        day_range=jumlah_hari,
        date_from=sejak_iso,
        date_to=hingga_iso,
        total_post=total_post_global,
        total_likes=sum(s.get("total_likes", 0) for s in stat_semua_akun),
        total_comments=sum(s.get("total_comments", 0) for s in stat_semua_akun),
        started_at=waktu_mulai,
        finished_at=waktu_selesai,
        status="SUCCEEDED" if akun_sukses > 0 else "FAILED",
        error_message="" if akun_sukses > 0 else "Tidak ada akun yang berhasil discrape.",
    )

    print("\nTOTAL SELESAI")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Scraper & Pemeringkatan Keaktifan 32 Akun OPD Kota Cirebon")
    parser.add_argument("--hari", type=int, default=30,
                        help="Rentang hari ke belakang (1-365, default 30)")
    parser.add_argument("--maks-post", type=int, default=50,
                        help="Batas maksimal postingan per akun (default 50)")
    parser.add_argument("--token", type=str, default=None,
                        help="Token API Apify")

    args = parser.parse_args()

    ret = jalankan_ranking_opd(
        jumlah_hari=args.hari,
        maks_post=args.maks_post,
        token=args.token,
    )
    sys.exit(ret)


if __name__ == "__main__":
    main()
