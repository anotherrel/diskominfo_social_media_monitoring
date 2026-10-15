# -*- coding: utf-8 -*-
"""
apify_client.py (modul TikTok)
==============================
Komunikasi dengan Apify untuk MENCARI VIDEO TikTok.

Satu-satunya actor yang dipakai: clockworks~tiktok-scraper (pencarian kata kunci).
Actor komentar TIDAK dipakai di tahap ini (komentar ditunda - lihat DESAIN bagian 10).

Pelajaran dari proyek AMS_V2 yang dibawa ke sini:
- TIDAK ADA fallback ke actor berjenis lain. Kalau actor tidak ada (404) -> GAGALKAN.
  (Dulu fallback ke actor pencarian membuat data video tertulis sebagai komentar.)
- Bentuk data selalu divalidasi sebelum dipakai. Hasil pencarian TikTok wajib punya
  field 'id' atau 'webVideoUrl'; kalau tidak ada satu pun, data dianggap tidak sah.
- Biaya nyata run dibaca dari field usageTotalUsd lalu dilaporkan (Apify menyediakannya).

Catatan penting soal TikTok: actor ini TIDAK menyediakan filter tanggal maupun lokasi.
Karena itu:
  - penyaringan tanggal dikerjakan lokal oleh evaluator.py (lapis 1), dan
  - varian kata kunci WAJIB memuat kata "Cirebon" (lihat config.KATA_LOKASI_PADA_QUERY).
"""

import re
import time
import requests

from config import (
    ACTOR_SEARCH,
    ACTOR_COMMENTS,
    MAKS_HASIL_PER_QUERY,
    TARIF_ESTIMASI_PER_HASIL,
    sekarang_iso,
)

API_BASE = "https://api.apify.com/v2"
TIMEOUT_RUN_DETIK = 1800     # maksimal 30 menit menunggu 1 run
JEDA_CEK_STATUS = 5          # detik


def _header(token: str) -> dict:
    return {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}


def validasi_token(token: str) -> bool:
    """Cek token Apify masih sah (GET /users/me)."""
    if not token:
        print("❌ Token Apify kosong.")
        return False
    try:
        resp = requests.get(f"{API_BASE}/users/me", headers={"Authorization": f"Bearer {token}"}, timeout=15)
    except Exception as e:
        print(f"❌ Tidak bisa menghubungi Apify: {e}")
        return False

    if resp.status_code == 200:
        return True
    if resp.status_code == 401:
        print("❌ Token Apify tidak sah (401 Unauthorized).")
        return False
    print(f"❌ Gagal validasi token. Status HTTP: {resp.status_code}")
    return False


def format_durasi(detik: float) -> str:
    menit, sisa = divmod(int(detik), 60)
    return f"{menit} menit {sisa} detik" if menit else f"{sisa} detik"


def estimasi_biaya(jumlah_query: int, maks_hasil: int = MAKS_HASIL_PER_QUERY) -> float:
    """
    Estimasi kasar biaya pencarian (USD). Angka pasti selalu dibaca dari usageTotalUsd tiap run.
    """
    return jumlah_query * maks_hasil * TARIF_ESTIMASI_PER_HASIL


def _jalankan_actor(run_input: dict, token: str, label: str, actor_id: str = None) -> tuple:
    """
    Jalankan actor Apify lalu unduh datasetnya.

    Returns: (items, status, pesan_error, info) dengan info = {"run_id", "dataset_id", "biaya_usd", "durasi_detik"}
    """
    actor = actor_id or ACTOR_SEARCH
    info = {"run_id": "", "dataset_id": "", "biaya_usd": 0.0, "durasi_detik": 0.0}
    print(f"\n  ▶ Menjalankan actor ({actor}): \"{label}\"...")

    try:
        resp = requests.post(f"{API_BASE}/acts/{actor}/runs",
                             headers=_header(token), json=run_input, timeout=60)
    except Exception as e:
        pesan = f"Gagal memulai actor: {e}"
        print(f"  ❌ {pesan}")
        return [], "failed", pesan, info

    if resp.status_code == 404:
        pesan = (f"Actor '{actor}' tidak ditemukan (404). "
                 f"Periksa nama actor di config.py.")
        print(f"  ❌ {pesan}")
        return [], "failed", pesan, info

    if resp.status_code not in (200, 201):
        detail = ""
        try:
            err = resp.json().get("error", {})
            detail = err.get("message") or err.get("type") or ""
        except Exception:
            detail = resp.text[:150]
        pesan = f"Actor menolak permintaan (HTTP {resp.status_code}: {detail})"
        print(f"  ❌ {pesan}")
        return [], "failed", pesan, info

    data_run = resp.json().get("data", {})
    run_id = data_run.get("id")
    dataset_id = data_run.get("defaultDatasetId")
    if not run_id:
        pesan = "Apify tidak mengembalikan Run ID."
        print(f"  ❌ {pesan}")
        return [], "failed", pesan, info

    info["run_id"] = run_id
    print(f"  ℹ️ Run berjalan (Run ID: {run_id})")
    waktu_mulai = time.time()

    status = "RUNNING"
    while status in ("READY", "RUNNING"):
        time.sleep(JEDA_CEK_STATUS)
        try:
            cek = requests.get(f"{API_BASE}/actor-runs/{run_id}", headers=_header(token), timeout=30)
            cek.raise_for_status()
            info_run = cek.json().get("data", {})
            status = info_run.get("status", "UNKNOWN")
            if info_run.get("defaultDatasetId"):
                dataset_id = info_run["defaultDatasetId"]
            print(f"  ⏳ Status: {status} ({format_durasi(time.time() - waktu_mulai)})...")
        except Exception as e:
            print(f"  ⚠️ Gagal cek status (dicoba lagi): {e}")

        if time.time() - waktu_mulai > TIMEOUT_RUN_DETIK:
            pesan = f"Timeout: run melebihi {TIMEOUT_RUN_DETIK // 60} menit."
            print(f"  ❌ {pesan}")
            return [], "failed", pesan, info

    info["durasi_detik"] = round(time.time() - waktu_mulai, 1)

    # baca biaya nyata run (kalau tersedia)
    try:
        info_run = requests.get(f"{API_BASE}/actor-runs/{run_id}", headers=_header(token), timeout=30).json().get("data", {})
        info["biaya_usd"] = float(info_run.get("usageTotalUsd") or 0.0)
        if info["biaya_usd"]:
            print(f"  💵 Biaya run ini: ${info['biaya_usd']:.4f}")
    except Exception:
        pass

    if status != "SUCCEEDED":
        pesan = f"Run gagal dengan status: {status}"
        print(f"  ❌ {pesan}")
        return [], "failed", pesan, info

    if not dataset_id:
        pesan = "Dataset ID tidak ditemukan pada run."
        print(f"  ❌ {pesan}")
        return [], "failed", pesan, info

    info["dataset_id"] = dataset_id

    print("  📥 Mengunduh hasil pencarian...")
    try:
        unduh = requests.get(f"{API_BASE}/datasets/{dataset_id}/items",
                             headers=_header(token), params={"limit": 5000}, timeout=120)
        unduh.raise_for_status()
        items = unduh.json()
    except Exception as e:
        pesan = f"Gagal mengunduh dataset: {e}"
        print(f"  ❌ {pesan}")
        return [], "failed", pesan, info

    if not isinstance(items, list):
        items = []

    return items, "success", "", info


def cari_video(query: str, token: str, maks_hasil: int = MAKS_HASIL_PER_QUERY) -> tuple:
    """
    Cari video TikTok untuk SATU kata kunci.

    Returns: (items_mentah, status, pesan_error, info_run)
    """
    if not query or not query.strip():
        return [], "failed", "Kata kunci kosong.", {}

    batas = maks_hasil if maks_hasil and maks_hasil > 0 else MAKS_HASIL_PER_QUERY
    run_input = {
        "searchQueries": [query.strip()],
        "resultsPerPage": batas,
        "searchSection": "/video",
        "maxItems": batas,
    }

    items, status, pesan, info = _jalankan_actor(run_input, token, label=query)
    if status != "success":
        return [], status, pesan, info

    # VALIDASI BENTUK DATA: hasil pencarian video harus punya id atau webVideoUrl
    video_sah = [it for it in items if isinstance(it, dict) and (it.get("id") or it.get("webVideoUrl"))]
    if items and not video_sah:
        pesan = (f"Actor mengembalikan {len(items)} item tetapi tidak ada yang berbentuk video "
                 f"(field 'id'/'webVideoUrl' tidak ada). Data tidak dipakai.")
        print(f"  ❌ {pesan}")
        return [], "failed", pesan, info

    print(f"  ✅ \"{query}\": {len(video_sah)} video diambil (dari {len(items)} item mentah).")
    return video_sah, "success", "", info


def normalisasi_url_tiktok(url: str, resolve_redirect: bool = True, timeout: int = 8) -> str:
    """
    Normalisasi semua jenis tautan TikTok menjadi canonical URL:
    - Menambahkan skema https:// jika belum ada
    - Mengurai shortlink (vm.tiktok.com, vt.tiktok.com, /t/) via redirect HTTP ke canonical URL
    - Menghapus parameter tracking (?_r=..., &is_from_webapp=..., dll)
    - Mendukung video, photo/slideshow, mobile (m.tiktok.com), dan desktop
    """
    u = (url or "").strip().strip("\"'<> ")
    if not u:
        return ""
    if not u.lower().startswith("http://") and not u.lower().startswith("https://"):
        u = "https://" + u

    is_shortlink = any(domain in u.lower() for domain in ["vm.tiktok.com", "vt.tiktok.com", "/t/"])
    if resolve_redirect and is_shortlink:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            resp = requests.get(u, headers=headers, allow_redirects=True, timeout=timeout, stream=True)
            if resp.url and "tiktok.com" in resp.url and resp.url != u:
                u = resp.url
        except Exception:
            pass

    u_bersih = u.split("?")[0].rstrip("/")
    return u_bersih


def id_dari_url(url: str) -> str:
    """
    Ambil ID video/foto dari URL TikTok (semua format).
    """
    if not url:
        return ""
    m = re.search(r'/(?:video|photo|v)/(\d+)', str(url))
    if m:
        return m.group(1)
    bersih = (str(url) or "").split("?")[0].rstrip("/").replace(".html", "")
    for segmen in reversed(bersih.split("/")):
        if segmen.isdigit() and len(segmen) >= 15:
            return segmen
    for segmen in reversed(bersih.split("/")):
        if segmen.isdigit():
            return segmen
    return ""


def ambil_video_dari_url(daftar_url: list, token: str) -> tuple:
    """
    Ambil data video LANGSUNG dari daftar URL (mode 'postURLs' actor clockworks~tiktok-scraper).
    Mendukung semua format link (shortlink vm/vt, photo, video desktop).
    """
    if not daftar_url:
        return {}, "failed", "Daftar URL kosong.", {}

    # 1. Normalisasi semua URL (resolve shortlink jika perlu)
    urls_kanonikal = []
    peta_alias = {}
    for u in daftar_url:
        u_norm = normalisasi_url_tiktok(u)
        urls_kanonikal.append(u_norm)
        peta_alias[u] = u_norm
        peta_alias[u_norm] = u_norm

    print(f"  🌐 Mengambil data dari {len(urls_kanonikal)} URL via Apify...")
    run_input = {"postURLs": list(urls_kanonikal)}
    items, status, pesan, info = _jalankan_actor(run_input, token, label=f"{len(urls_kanonikal)} URL contoh")
    if status != "success":
        return {}, status, pesan, info

    peta = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        vid = str(it.get("id") or id_dari_url(it.get("webVideoUrl", ""))).strip()
        web_url = (it.get("webVideoUrl") or "").split("?")[0].rstrip("/")
        if vid:
            peta[vid] = it
        if web_url:
            peta[web_url] = it

    # Hubungkan kembali dengan URL asli user
    for u_asli, u_norm in peta_alias.items():
        vid_norm = id_dari_url(u_norm)
        item_dapat = peta.get(vid_norm) or peta.get(u_norm)
        if item_dapat:
            peta[u_asli] = item_dapat
            if vid_norm:
                peta[vid_norm] = item_dapat

    if items and not peta:
        pesan = (f"Actor mengembalikan {len(items)} item tetapi tidak ada yang berbentuk video. "
                 f"Data tidak dipakai.")
        print(f"  ❌ {pesan}")
        return {}, "failed", pesan, info

    print(f"  ✅ Data video berhasil diambil: {len(items)} item dari Apify.")
    return peta, "success", "", info


def cari_semua_varian(daftar_query: list, token: str, maks_hasil: int = MAKS_HASIL_PER_QUERY) -> dict:
    """
    Jalankan pencarian untuk SEMUA kata kunci (varian topik) satu per satu.

    Dijalankan satu-satu (bukan digabung) supaya:
    - terlihat query mana yang berhasil/gagal,
    - tercatat di history per query,
    - biaya per query bisa dilaporkan.

    Returns: {"waktu_mulai","waktu_selesai","hasil":[{query,status,pesan,jumlah,info,items}]}
    """
    waktu_mulai = sekarang_iso()
    hasil = []
    total_biaya = 0.0

    for urutan, query in enumerate(daftar_query, 1):
        print(f"\n  [{urutan}/{len(daftar_query)}] Kata kunci: \"{query}\"")
        items, status, pesan, info = cari_video(query, token, maks_hasil)
        total_biaya += float((info or {}).get("biaya_usd") or 0.0)
        hasil.append({
            "query": query,
            "status": status,
            "pesan_error": pesan,
            "jumlah": len(items),
            "info": info or {},
            "items": items,
        })

    print(f"\n  💰 Total biaya pencarian run ini: ${total_biaya:.4f}")
    return {"waktu_mulai": waktu_mulai, "waktu_selesai": sekarang_iso(), "hasil": hasil, "total_biaya_usd": round(total_biaya, 4)}


def ambil_komentar_tiktok(daftar_post: list, token: str, maks_komentar: int = 100, top_video: int = 3) -> tuple:
    """
    Ambil komentar untuk postingan terpilih (berdasarkan comment_count terbanyak).
    Menggunakan actor clockworks~tiktok-comments-scraper.

    Returns: (daftar_komentar, status, pesan_error, info)
    """
    if not daftar_post:
        return [], "failed", "Daftar postingan kosong.", {}

    def _hitung_komen(p):
        try:
            return int(p.get("comment_count") or 0)
        except Exception:
            return 0

    post_dengan_komen = [p for p in daftar_post if _hitung_komen(p) > 0]
    if not post_dengan_komen:
        print("  ℹ️ Tidak ada video yang memiliki komentar (comment_count = 0).")
        return [], "success", "", {}

    post_dengan_komen.sort(key=_hitung_komen, reverse=True)
    terpilih = post_dengan_komen[:top_video]

    print(f"\n  🎯 Memilih {len(terpilih)} postingan dengan komentar terbanyak:")
    daftar_url = []
    peta_post = {}
    for idx, p in enumerate(terpilih, 1):
        url = p.get("web_url") or p.get("url") or ""
        post_id = str(p.get("post_id") or p.get("id") or "").strip()
        cnt = _hitung_komen(p)
        print(f"     {idx}. Post ID {post_id} | Komentar: {cnt} | URL: {url}")
        if url:
            daftar_url.append(url)
            peta_post[url] = p
            if post_id:
                peta_post[post_id] = p

    if not daftar_url:
        return [], "failed", "URL video tidak ditemukan pada postingan terpilih.", {}

    run_input = {
        "postURLs": daftar_url,
        "commentsPerPost": max(1, maks_komentar),
        "maxComments": max(1, maks_komentar) * len(daftar_url),
    }

    print(f"  📥 Mengambil komentar lewat actor {ACTOR_COMMENTS} (maks {maks_komentar}/post)...")
    items, status, pesan, info = _jalankan_actor(run_input, token,
                                                 label=f"Komentar {len(daftar_url)} video",
                                                 actor_id=ACTOR_COMMENTS)
    if status != "success":
        return [], status, pesan, info

    daftar_komentar = []
    for it in items:
        if not isinstance(it, dict):
            continue
        teks = (it.get("text") or it.get("comment") or "").strip()
        if not teks:
            continue

        post_url = it.get("postURL") or it.get("webVideoUrl") or it.get("videoWebUrl") or ""
        video_id = id_dari_url(post_url) or str(it.get("videoId") or "")
        parent_post = peta_post.get(post_url) or peta_post.get(video_id) or (terpilih[0] if len(terpilih) == 1 else {})

        user_info = it.get("user") or it.get("author") or {}
        if isinstance(user_info, dict):
            username = user_info.get("uniqueId") or user_info.get("nickname") or user_info.get("name") or "netizen"
        else:
            username = str(user_info or "netizen")

        comment_id = str(it.get("id") or it.get("cid") or len(daftar_komentar) + 1)
        created_at = str(it.get("createTimeISO") or it.get("createdAt") or it.get("createTime") or "")

        daftar_komentar.append({
            "topik": parent_post.get("topik", ""),
            "post_id": parent_post.get("post_id") or video_id,
            "post_url": post_url or parent_post.get("web_url", ""),
            "comment_id": comment_id,
            "username": username,
            "text": teks,
            "created_at": created_at,
            "likes": int(it.get("diggCount") or it.get("likes") or 0),
            "reply_count": int(it.get("replyCommentTotal") or it.get("replyCount") or 0),
            "sentimen": "NETRAL",
            "skor_yakin": "0.00%",
        })

    print(f"  ✅ {len(daftar_komentar)} komentar berhasil diambil dari {len(daftar_url)} video.")
    return daftar_komentar, "success", "", info
