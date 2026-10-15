# -*- coding: utf-8 -*-
"""
storage.py (cirebon_opd)
=========================
Menyimpan dataset postingan OPD, menghitung engagement & skor keaktifan,
menyusun klasemen ranking, serta mencatat log riwayat pemantauan (history).
Mengikuti Usulan A:
- Berkas ranking di: data/<tanggal_run>/ranking_keaktifan_opd_<hari>hari_<timestamp>.csv
- Berkas post di: data/<tanggal_run>/post/<folder_akun>_<tanggal_run>.csv
"""

import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from config import FOLDER_DATA, FOLDER_HISTORY


def parse_timestamp_iso(ts):
    if not ts:
        return ""
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_str = str(ts).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", ts_str):
        return ts_str[:19] + "Z"
    return ts_str


def bersihkan_dan_format_post(item: dict, scrape_id: str, waktu_scrape: str) -> dict:
    def ambil_nilai(*keys, default=None):
        for k in keys:
            if k in item and item[k] is not None:
                return item[k]
        return default

    ext_id = ambil_nilai("id", "shortCode", "code", "pk")
    username = ambil_nilai("ownerUsername", "username", "owner", default="")
    if isinstance(username, dict):
        username = username.get("username", "")

    post_type = ambil_nilai("type", "productType", default="Image")
    post_type_str = str(post_type).lower()
    if post_type_str in ("video", "clip", "clips", "reel", "reels"):
        post_type = "Video"
    elif post_type_str in ("sidecar", "carousel"):
        post_type = "Sidecar"
    elif post_type_str in ("image", "photo"):
        post_type = "Image"

    caption = ambil_nilai("caption", "text")
    raw_ts = ambil_nilai("timestamp", "taken_at_timestamp", "created_at")
    published_at = parse_timestamp_iso(raw_ts)

    like_count = int(ambil_nilai("likesCount", "likes_count", default=0) or 0)
    comment_count = int(ambil_nilai("commentsCount", "comments_count", default=0) or 0)
    # Skor minat masyarakat: like_count + (comment_count * 2)
    skor = like_count + (comment_count * 2)

    url_post = ambil_nilai("url", "postUrl")
    if not url_post and ext_id:
        url_post = f"https://www.instagram.com/p/{ext_id}/"

    return {
        "scrape_id": scrape_id,
        "post_id": str(ext_id or ""),
        "post_url": str(url_post or ""),
        "created_at": published_at,
        "platform": "instagram",
        "post_type": str(post_type),
        "username": username,
        "caption": caption or "",
        "like_count": like_count,
        "comment_count": comment_count,
        "skor": skor,
    }


def simpan_dataset_opd(raw_items: list, username: str, folder_akun: str, jumlah_hari: int,
                       scrape_id: str, waktu_scrape: str, folder_run: Path = None):
    """
    Menyimpan SEMUA postingan OPD dalam rentang waktu ke CSV & JSON
    di folder data/<tanggal_run>/post/<folder_akun>_<tanggal_run>.csv.
    Format kolom:
    scrape_id | post_id | post_url | created_at | platform | post_type | username | caption | like_count | comment_count | skor
    Diurutkan dari skor tertinggi ke terendah.
    """
    tgl_scrape = waktu_scrape[:10]
    folder_induk = folder_run or (FOLDER_DATA / tgl_scrape)
    folder_post = folder_induk / "post"
    folder_post.mkdir(parents=True, exist_ok=True)

    filename_base = f"{folder_akun}_{tgl_scrape}"
    path_csv = folder_post / f"{filename_base}.csv"
    path_json = folder_post / f"{filename_base}.json"

    formatted_posts = []
    total_likes = 0
    total_comments = 0

    for item in raw_items:
        if not isinstance(item, dict) or item.get("error"):
            continue
        formatted_post = bersihkan_dan_format_post(item, scrape_id, waktu_scrape)
        if not formatted_post.get("post_id"):
            continue
        if not formatted_post["username"]:
            formatted_post["username"] = username
        formatted_posts.append(formatted_post)
        total_likes += formatted_post["like_count"]
        total_comments += formatted_post["comment_count"]

    records_inserted = len(formatted_posts)
    total_engagement = total_likes + total_comments
    skor_keaktifan = records_inserted + total_likes + total_comments

    # Urutkan berdasarkan skor tertinggi ke terendah
    formatted_posts.sort(key=lambda x: int(x.get("skor", 0)), reverse=True)

    kolom = [
        "scrape_id", "post_id", "post_url", "created_at", "platform",
        "post_type", "username", "caption", "like_count", "comment_count", "skor"
    ]

    posts_to_save = [{k: p.get(k, "") for k in kolom} for p in formatted_posts]

    with open(path_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=kolom)
        writer.writeheader()
        writer.writerows(posts_to_save)

    with open(path_json, "w", encoding="utf-8") as f:
        json.dump(posts_to_save, f, ensure_ascii=False, indent=2)

    stat_akun = {
        "username": username,
        "folder_akun": folder_akun,
        "total_post": records_inserted,
        "total_likes": total_likes,
        "total_comments": total_comments,
        "total_engagement": total_engagement,
        "skor_keaktifan": skor_keaktifan,
        "path_csv": str(path_csv),
        "path_json": str(path_json),
    }

    return records_inserted, path_csv, path_json, formatted_posts, stat_akun


def simpan_ranking_opd(daftar_stat_akun: list, jumlah_hari: int, waktu_scrape: str, folder_run: Path = None):
    """
    Menyusun klasemen peringkat keaktifan dari seluruh akun OPD,
    diurutkan berdasarkan Skor Keaktifan (Post + Likes + Comments) tertinggi.
    Disimpan di data/<tanggal_run>/ranking_keaktifan_opd_<hari>hari_<timestamp>.csv
    """
    sorted_ranking = sorted(
        daftar_stat_akun,
        key=lambda x: (x.get("skor_keaktifan", 0), x.get("total_post", 0), x.get("total_engagement", 0)),
        reverse=True
    )

    tgl_scrape = waktu_scrape[:10]
    folder_induk = folder_run or (FOLDER_DATA / tgl_scrape)
    folder_induk.mkdir(parents=True, exist_ok=True)

    scraped_at_clean = waktu_scrape.replace(":", "").replace("-", "").replace("T", "_").replace("Z", "")
    filename = f"ranking_keaktifan_opd_{jumlah_hari}hari_{scraped_at_clean}.csv"
    path_csv = folder_induk / filename

    kolom = [
        "Peringkat", "Username", "Instansi", "Kategori",
        "Total Postingan", "Total Likes", "Total Komentar", "Total Engagement", "Skor Keaktifan"
    ]

    rows = []
    for idx, stat in enumerate(sorted_ranking, 1):
        rows.append({
            "Peringkat": idx,
            "Username": "@" + stat.get("username", ""),
            "Instansi": stat.get("nama_instansi", stat.get("username", "")),
            "Kategori": stat.get("kategori", "OPD"),
            "Total Postingan": stat.get("total_post", 0),
            "Total Likes": stat.get("total_likes", 0),
            "Total Komentar": stat.get("total_comments", 0),
            "Total Engagement": stat.get("total_engagement", 0),
            "Skor Keaktifan": stat.get("skor_keaktifan", 0),
        })

    with open(path_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=kolom)
        writer.writeheader()
        writer.writerows(rows)

    return sorted_ranking, path_csv


def catat_riwayat_opd(scrape_id: str, target: str, day_range: int,
                      date_from: str, date_to: str, total_post: int,
                      total_likes: int, total_comments: int,
                      started_at: str, finished_at: str,
                      status: str = "SUCCEEDED", error_message: str = ""):
    """
    Mencatat log riwayat pemantauan OPD ke history_opd.csv & history_opd.json.
    Format kolom standar:
    scrape_id, platform, target, day_range, date_from, date_to, total_post, total_likes, total_comments, started_at, finished_at, status, error_message
    """
    FOLDER_HISTORY.mkdir(parents=True, exist_ok=True)
    path_history_csv = FOLDER_HISTORY / "history_opd.csv"
    path_history_json = FOLDER_HISTORY / "history_opd.json"

    log_entry_json = {
        "scrape_id": scrape_id,
        "platform": "instagram",
        "target": target,
        "day_range": day_range,
        "date_from": date_from[:10],
        "date_to": date_to[:10],
        "total_post": total_post,
        "total_likes": total_likes,
        "total_comments": total_comments,
        "started_at": started_at,
        "finished_at": finished_at,
        "status": status,
        "error_message": error_message or "",
    }

    kolom_history = list(log_entry_json.keys())

    file_exists = path_history_csv.exists() and path_history_csv.stat().st_size > 0
    with open(path_history_csv, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=kolom_history)
        if not file_exists:
            writer.writeheader()
        writer.writerow(log_entry_json)

    history_list = []
    if path_history_json.exists() and path_history_json.stat().st_size > 0:
        try:
            with open(path_history_json, "r", encoding="utf-8") as f:
                history_list = json.load(f)
                if not isinstance(history_list, list):
                    history_list = []
        except Exception:
            history_list = []

    history_list.append(log_entry_json)

    with open(path_history_json, "w", encoding="utf-8") as f:
        json.dump(history_list, f, ensure_ascii=False, indent=2)
