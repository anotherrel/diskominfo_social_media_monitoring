# -*- coding: utf-8 -*-
"""
storage.py
==========
File ini menangani penyaringan data, pemformatan dataset post & komentar,
serta penyimpanan file CSV & JSON untuk dataset dan riwayat scraping (history_post & history_comment).
"""

import csv
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from config import FOLDER_POST, FOLDER_COMMENT, FOLDER_HISTORY, KATA_KUNCI_FILTER
from sentiment_analyzer import analisa_sentimen_batch, hitung_statistik_sentimen


def parse_timestamp_iso(ts_val) -> str:
    """
    Mengubah nilai timestamp (Unix int/float atau string) menjadi string ISO format UTC.
    """
    if not ts_val:
        return ""

    if isinstance(ts_val, (int, float)) and ts_val > 0:
        try:
            return datetime.fromtimestamp(ts_val, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            return str(ts_val)

    return str(ts_val)


def apakah_komentar_bot(teks) -> bool:
    """
    Menentukan apakah sebuah baris komentar SEBENARNYA catatan bot, bukan komentar warga.

    KENAPA PERLU (kejadian 22-23 Sep 2026):
    Pesan status bot pernah ikut tertulis di kolom komentar akun yang dipantau, lalu
    Apify menariknya kembali seolah-olah itu komentar warga. Akibatnya, teks seperti
    "[22/09/2026 11:44] DKIS_SCRAPPER: LOG job001 #1 — 22 detik" ikut dinilai sentimen,
    dan persentase POSITIF/NEGATIF jadi menyesatkan (naik-turun tanpa sebab).

    PRINSIP: hanya buang teks yang MUSTAHIL ditulis warga. Pola di bawah sengaja
    memakai penanda yang sangat khas bot (label bot, nomor job, atau kombinasi
    waktu+label). Kata umum seperti "selesai" TIDAK dipakai sebagai patokan, karena
    komentar warga seperti "semoga cepat selesai" bisa ikut terbuang — dan membuang
    keluhan warga asli jauh lebih berbahaya daripada menyisakan satu baris sampah.

    Returns True kalau baris ini harus DIBUANG.
    """
    if teks is None or not isinstance(teks, str):
        return True
    bersih = teks.strip()
    if not bersih:                      # kosong / hanya spasi: tidak ada isinya
        return True

    pola_bot = (
        # 1. Label bot itu sendiri — penanda paling kuat.
        r"DKIS[ _]?SCRAPPER",
        # 2. Baris status dengan NOMOR JOB (hanya mesin yang menulis seperti ini).
        r"\bJob\s+job\d+\b",
        r"\bJOB\s+job\d+\s*[—\-]",
        r"\bLOG\s+job\d+\s*#\d+",
        # 3. Status antrean lengkap: "Job job001 MASUK ANTREAN (posisi 1)."
        r"\bMASUK ANTREAN\s*\(posisi\s*\d+\)",
    )
    for pola in pola_bot:
        if re.search(pola, bersih, re.IGNORECASE):
            return True
    return False


def bersihkan_dan_format_post(item_mentah: dict, scrape_id: str, waktu_scrape: str) -> dict:
    """
    Mengekstrak dan memformat 1 item postingan mentah dari Apify menjadi format standar.
    
    Kolom Standard:
    1. id               : Internal scrape ID
    2. post_id          : Post ID dari Instagram
    3. platform         : instagram
    4. post_type        : Tipe post (Video, Image, Sidecar, Reels, etc.)
    5. username         : Username akun pengunggah
    6. published_at     : Waktu postingan dibuat (created time)
    7. caption          : Isi teks caption
    8. like_count       : Jumlah like
    9. comment_count    : Jumlah komentar
    10. scraped_at      : Waktu di-scrape
    """
    def ambil_nilai(*keys, default=""):
        for k in keys:
            if k in item_mentah and item_mentah[k] is not None:
                return item_mentah[k]
        return default

    # Ambil post id (id / pk / code / shortCode)
    ext_id = str(ambil_nilai("id", "pk", "code", "shortCode"))

    # Ambil username pemilik akun
    owner = item_mentah.get("owner") or {}
    username = ambil_nilai("ownerUsername", "owner_username") or (owner.get("username") if isinstance(owner, dict) else "")

    # Ambil post_type
    post_type = ambil_nilai("type", "productType", "post_type", "media_type")
    if not post_type:
        if item_mentah.get("isVideo") or item_mentah.get("is_video"):
            post_type = "Video"
        else:
            post_type = "Image"

    # Normalize type display
    post_type_str = str(post_type).lower()
    if post_type_str in ("video", "clip", "clips", "reel", "reels"):
        post_type = "Video"
    elif post_type_str in ("sidecar", "carousel"):
        post_type = "Sidecar"
    elif post_type_str in ("image", "photo"):
        post_type = "Image"

    # Ambil caption
    caption = ambil_nilai("caption", "text")

    # Ambil waktu publish
    raw_ts = ambil_nilai("timestamp", "taken_at_timestamp", "created_at")
    published_at = parse_timestamp_iso(raw_ts)

    # Ambil like dan comment count
    like_count = int(ambil_nilai("likesCount", "likes_count", default=0) or 0)
    comment_count = int(ambil_nilai("commentsCount", "comments_count", default=0) or 0)

    # Ambil URL postingan
    url_post = ambil_nilai("url", "postUrl")
    if not url_post and ext_id:
        url_post = f"https://www.instagram.com/p/{ext_id}/"

    return {
        "id": scrape_id,
        "post_id": ext_id,
        "platform": "instagram",
        "post_type": str(post_type),
        "username": username,
        "published_at": published_at,
        "caption": caption,
        "like_count": like_count,
        "comment_count": comment_count,
        "scraped_at": waktu_scrape,
        "_url": url_post,  # Helper internal untuk link scraping comment
    }


def saring_dan_simpan_dataset(raw_items: list, username: str, folder_akun: str, jumlah_hari: int, top_n_video: int, scrape_id: str, waktu_scrape: str):
    """
    Menyaring data mentah berdasarkan kata kunci "Kota Cirebon", 
    menyimpan dataset post ke CSV dan JSON di folder post/<folder_akun>/<YYYY-MM-DD>/,
    serta mengidentifikasi Top N Video dengan komentar terbanyak.

    Returns:
    - records_inserted (int): Jumlah postingan yang lolos filter
    - path_csv (Path)       : Path file CSV hasil
    - path_json (Path)      : Path file JSON hasil
    - top_videos (list)     : List dict video top comment terpilih
    - post_terfilter (list) : Semua post yang lolos filter
    """
    tgl_scrape = waktu_scrape[:10]  # YYYY-MM-DD
    folder_tujuan = FOLDER_POST / folder_akun / tgl_scrape
    folder_tujuan.mkdir(parents=True, exist_ok=True)

    # Clean timestamp for filename (misal: 20260911_152000)
    scraped_at_clean = waktu_scrape.replace(":", "").replace("-", "").replace("T", "_").replace("Z", "")
    filename_base = f"{username}_{jumlah_hari}hari_scrape_{scraped_at_clean}"
    
    path_csv = folder_tujuan / f"{filename_base}.csv"
    path_json = folder_tujuan / f"{filename_base}.json"

    # 1. Format semua item mentah
    formatted_posts = []
    for item in raw_items:
        formatted_post = bersihkan_dan_format_post(item, scrape_id, waktu_scrape)
        if not formatted_post["username"]:
            formatted_post["username"] = username
        formatted_posts.append(formatted_post)

    # 2. Filterisasi: Caption WAJIB memuat kata "Kota Cirebon"
    post_terfilter = []
    kw = KATA_KUNCI_FILTER.lower()
    for post in formatted_posts:
        caption_text = (post.get("caption") or "").lower()
        if kw in caption_text:
            post_terfilter.append(post)

    records_inserted = len(post_terfilter)

    # 3. Cari Top N Post (semua tipe post: Video, Image, Sidecar, dll) dengan Komentar Terbanyak dari post yang lolos filter
    posts_sorted = sorted(post_terfilter, key=lambda x: int(x.get("comment_count", 0) or 0), reverse=True)
    top_videos = posts_sorted[:top_n_video]

    # 4. Simpan File CSV & JSON (tanpa field _url)
    kolom = [
        "id",
        "post_id",
        "platform",
        "post_type",
        "username",
        "published_at",
        "caption",
        "like_count",
        "comment_count",
        "scraped_at",
    ]

    posts_to_save = []
    for p in post_terfilter:
        p_clean = {k: v for k, v in p.items() if k in kolom}
        posts_to_save.append(p_clean)

    # Simpan CSV
    with open(path_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=kolom)
        writer.writeheader()
        writer.writerows(posts_to_save)

    # Simpan JSON
    with open(path_json, "w", encoding="utf-8") as f:
        json.dump(posts_to_save, f, ensure_ascii=False, indent=2)

    return records_inserted, path_csv, path_json, top_videos, post_terfilter


def catat_riwayat_post(scrape_id: str, started_at: str, finished_at: str, status: str, records_fetched: int, records_inserted: int, count_top_comment_video: int, top_comment_video_ids: list, error_message: str):
    """
    Mencatat log riwayat scraping post ke history_post.csv & history_post.json.
    """
    log_entry_json = {
        "id": scrape_id,
        "platform": "instagram",
        "started_at": started_at,
        "finished_at": finished_at,
        "status": status,
        "records_fetched": records_fetched,
        "records_inserted": records_inserted,
        "count_top_comment_video": count_top_comment_video,
        "top_comment_video_id": top_comment_video_ids,
        "error_message": error_message or "",
    }

    log_entry_csv = dict(log_entry_json)
    log_entry_csv["top_comment_video_id"] = ";".join(str(v) for v in top_comment_video_ids)

    path_history_csv = FOLDER_HISTORY / "history_post.csv"
    path_history_json = FOLDER_HISTORY / "history_post.json"

    kolom_history = [
        "id",
        "platform",
        "started_at",
        "finished_at",
        "status",
        "records_fetched",
        "records_inserted",
        "count_top_comment_video",
        "top_comment_video_id",
        "error_message",
    ]

    # CSV History
    file_exists = path_history_csv.exists() and path_history_csv.stat().st_size > 0
    with open(path_history_csv, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=kolom_history)
        if not file_exists:
            writer.writeheader()
        writer.writerow(log_entry_csv)

    # JSON History
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


def bersihkan_dan_format_comment(item_mentah: dict, scrape_comment_id: str, top_videos: list, fallback_post_id: str, waktu_scrape: str) -> dict:
    """
    Mengekstrak dan memformat 1 item komentar mentah dari Apify.
    Mencocokkan post_id komentar secara akurat dengan post_id dari top_videos.
    
    Kolom Standard:
    1. id                 : Internal scrape ID komentar (scrape_comment_id)
    2. post_id            : ID Post Instagram asal komentar (post_id top video)
    3. comment_id         : ID komentar dari Instagram
    4. parent_comment_id  : ID parent comment (jika reply)
    5. is_reply           : 0 (utama) / 1 (reply)
    6. author             : Username pembuat komentar
    7. text               : Teks komentar
    8. likes              : Jumlah like pada komentar
    9. reply_count        : Jumlah balasan komentar
    10. published_at      : Waktu dipublikasikan
    11. scraped_at        : Waktu di-scrape
    """
    def ambil_nilai(*keys, default=""):
        for k in keys:
            if k in item_mentah and item_mentah[k] is not None:
                return item_mentah[k]
        return default

    # Ambil comment_id
    comment_id = str(ambil_nilai("id", "pk", "comment_id"))

    # Ambil & cocokkan post_id secara akurat dari top_videos
    raw_pid = str(ambil_nilai("postId", "post_id", "shortCode", "code") or "")
    raw_url = str(ambil_nilai("inputUrl", "postUrl", "url", "targetUrl") or "").lower()

    post_id = ""
    if top_videos:
        for v in top_videos:
            v_ext_id = str(v.get("post_id") or "")
            v_url = str(v.get("_url") or "").lower()
            if v_ext_id and (v_ext_id == raw_pid or v_ext_id in raw_url):
                post_id = v_ext_id
                break
            if v_url and v_url in raw_url:
                post_id = v_ext_id
                break

    if not post_id:
        post_id = raw_pid or fallback_post_id

    # Ambil parent comment id & is_reply
    parent_id = str(ambil_nilai("parentCommentId", "parent_comment_id", "parent_id", default=""))
    is_reply = 1 if (parent_id and parent_id != "None" and parent_id != "0") else 0
    if not is_reply:
        parent_id = ""

    # Ambil author
    owner = item_mentah.get("owner") or item_mentah.get("user") or {}
    author = ambil_nilai("ownerUsername", "username", "author") or (owner.get("username") if isinstance(owner, dict) else "")

    # Ambil text
    text = ambil_nilai("text", "caption")

    # Ambil likes & reply_count
    likes = int(ambil_nilai("likesCount", "likes_count", "likes", default=0) or 0)
    reply_count = int(ambil_nilai("repliesCount", "replies_count", "childCommentsCount", default=0) or 0)

    # Ambil timestamp publish
    raw_ts = ambil_nilai("timestamp", "created_at", "createdAt")
    published_at = parse_timestamp_iso(raw_ts)

    return {
        "id": scrape_comment_id,
        "post_id": post_id,
        "comment_id": comment_id,
        "parent_comment_id": parent_id,
        "is_reply": is_reply,
        "author": author,
        "text": text,
        "likes": likes,
        "reply_count": reply_count,
        "published_at": published_at,
        "scraped_at": waktu_scrape,
    }


def simpan_dataset_comment(raw_comments: list, username: str, folder_akun: str, jumlah_hari: int, top_videos: list, fallback_post_id: str, scrape_comment_id: str, waktu_scrape: str):
    """
    Memformat, menganalisis sentimen dengan IndoBERTweet,
    & menyimpan dataset komentar ke comment/<folder_akun>/<YYYY-MM-DD>/.

    Returns:
    - records_inserted (int): Jumlah komentar yang berhasil disimpan
    - path_csv (Path)       : Path file CSV hasil
    - path_json (Path)      : Path file JSON hasil
    - stats_sentimen (dict) : Ringkasan sentimen IndoBERTweet (% Positif, % Negatif, % Netral)
    """
    tgl_scrape = waktu_scrape[:10]  # YYYY-MM-DD
    folder_tujuan = FOLDER_COMMENT / folder_akun / tgl_scrape
    folder_tujuan.mkdir(parents=True, exist_ok=True)

    scraped_at_clean = waktu_scrape.replace(":", "").replace("-", "").replace("T", "_").replace("Z", "")
    filename_base = f"comment_{username}_{jumlah_hari}hari_scrape_{scraped_at_clean}"

    path_csv = folder_tujuan / f"{filename_base}.csv"
    path_json = folder_tujuan / f"{filename_base}.json"

    formatted_comments = []
    for item in raw_comments:
        fmt_comment = bersihkan_dan_format_comment(item, scrape_comment_id, top_videos, fallback_post_id, waktu_scrape)
        formatted_comments.append(fmt_comment)

    # Filter komentar bot/spam: hapus teks log sistem yang bocor ke data.
    # Bot DKIS_SCRAPPER pernah ikut tertulis di kolom komentar IG target, lalu Apify
    # menariknya kembali seolah-olah itu komentar warga. Kalau dibiarkan, teks log ini
    # ikut dinilai sentimen dan membuat persentase hasil jadi menyesatkan.
    bersih_sebelum_sentimen = []
    spam_dihapus = 0
    for cmt in formatted_comments:
        if apakah_komentar_bot(cmt.get("text")):
            spam_dihapus += 1
            continue
        bersih_sebelum_sentimen.append(cmt)

    if spam_dihapus > 0:
        # Sengaja memakai tanda "->" (bukan panah Unicode) supaya tetap aman walau
        # keluaran scraper dialihkan ke konsol Windows yang bukan UTF-8.
        print(f"[INFO] {spam_dihapus} komentar bot/log terfilter sebelum sentimen -> "
              f"tinggal {len(bersih_sebelum_sentimen)} komentar warga nyata")

    # 1. Stage 1: Analisis Sentimen IndoBERTweet (label mesin -> kolom 'sentimen')
    if bersih_sebelum_sentimen:
        bersih_sebelum_sentimen = analisa_sentimen_batch(bersih_sebelum_sentimen)
    formatted_comments = bersih_sebelum_sentimen

    # TAHAP PENILAIAN OLEH LLM SUDAH DILEPAS (24 Sep 2026).
    # Karena itu hanya IndoBERT (model lokal) yang dipakai: kolom 'sentimen' + 'skor_yakin'.
    # Kolom 'sentimen_ai'/'alasan_ai'/'butuh_review'/'alasan_review' TIDAK lagi ditulis.

    stats_sentimen = hitung_statistik_sentimen(formatted_comments)          # hasil IndoBERT

    records_inserted = len(formatted_comments)

    kolom = [
        "id",
        "post_id",
        "comment_id",
        "parent_comment_id",
        "is_reply",
        "author",
        "text",
        "likes",
        "reply_count",
        "published_at",
        "scraped_at",
        "sentimen",         # label IndoBERTweet
        "skor_yakin",       # keyakinan IndoBERTweet
    ]

    # Simpan CSV
    with open(path_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=kolom)
        writer.writeheader()
        writer.writerows(formatted_comments)

    # Simpan JSON
    with open(path_json, "w", encoding="utf-8") as f:
        json.dump(formatted_comments, f, ensure_ascii=False, indent=2)

    return records_inserted, path_csv, path_json, stats_sentimen


def catat_riwayat_comment(scrape_comment_id: str, started_at: str, finished_at: str, status: str, records_fetched: int, records_inserted: int, count_top_comment_video: int, top_comment_video_ids: list, error_message: str):
    """
    Mencatat log riwayat scraping komentar ke history_comment.csv & history_comment.json.
    """
    log_entry_json = {
        "id": scrape_comment_id,
        "platform": "instagram",
        "started_at": started_at,
        "finished_at": finished_at,
        "status": status,
        "records_fetched": records_fetched,
        "records_inserted": records_inserted,
        "count_top_comment_video": count_top_comment_video,
        "top_comment_video_id": top_comment_video_ids or [],
        "error_message": error_message or "",
    }

    log_entry_csv = dict(log_entry_json)
    log_entry_csv["top_comment_video_id"] = ";".join(str(v) for v in (top_comment_video_ids or []))

    path_history_csv = FOLDER_HISTORY / "history_comment.csv"
    path_history_json = FOLDER_HISTORY / "history_comment.json"

    kolom_history = [
        "id",
        "platform",
        "started_at",
        "finished_at",
        "status",
        "records_fetched",
        "records_inserted",
        "count_top_comment_video",
        "top_comment_video_id",
        "error_message",
    ]

    # CSV History
    file_exists = path_history_csv.exists() and path_history_csv.stat().st_size > 0
    with open(path_history_csv, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=kolom_history)
        if not file_exists:
            writer.writeheader()
        writer.writerow(log_entry_csv)

    # JSON History
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

