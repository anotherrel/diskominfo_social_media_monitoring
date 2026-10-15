# -*- coding: utf-8 -*-
"""
apify_client.py
===============
File ini khusus menangani komunikasi dengan Apify API.
Tugasnya: Memulai proses scraping di Apify, menunggu hingga selesai,
lalu mengunduh data mentah postingan Instagram.
"""

import json
import time

import requests

from config import ACTOR_ID, ACTOR_COMMENT_ID, FOLDER_HISTORY

# ============================================================
# CATATAN RUN APIFY YANG SEDANG BERJALAN
# ============================================================
# run_id ditulis ke berkas supaya bot Telegram bisa MEMBATALKAN run di sisi Apify.
# PENTING (pelajaran 22 Sep 2026): mematikan proses python lokal saja TIDAK
# menghentikan run di server Apify — run itu tetap lanjut dan tetap ditagih.
# Karena itu run_id dicatat di sini, agar bisa dibatalkan lewat API abort.
PATH_RUN_AKTIF = FOLDER_HISTORY / "apify_run_aktif.json"


def catat_run_aktif(run_id: str, aktor: str, keterangan: str = ""):
    """Catat run yang sedang berjalan (dibaca bot untuk keperluan pembatalan)."""
    try:
        isi = []
        if PATH_RUN_AKTIF.exists():
            isi = json.loads(PATH_RUN_AKTIF.read_text(encoding="utf-8"))
        if not isinstance(isi, list):
            isi = []
        isi.append({
            "run_id": run_id,
            "aktor": aktor,
            "keterangan": keterangan,
            "dicatat": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        PATH_RUN_AKTIF.write_text(json.dumps(isi, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def hapus_run_aktif(run_id: str):
    """Hapus catatan run setelah selesai/gagal (supaya tidak dibatalkan keliru)."""
    try:
        if not PATH_RUN_AKTIF.exists():
            return
        isi = json.loads(PATH_RUN_AKTIF.read_text(encoding="utf-8"))
        if not isinstance(isi, list):
            isi = []
        sisa = [x for x in isi if str(x.get("run_id")) != str(run_id)]
        PATH_RUN_AKTIF.write_text(json.dumps(sisa, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def validasi_apify_token(token: str) -> bool:
    """
    Memeriksa apakah APIFY_TOKEN valid dan bisa digunakan.
    Returns True jika valid, False jika tidak valid.
    """
    if not token:
        print("❌ Error: Token Apify kosong.")
        return False

    url = "https://api.apify.com/v2/users/me"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            return True
        elif response.status_code == 401:
            print("❌ Error: Token Apify tidak valid (401 Unauthorized).")
            return False
        else:
            print(f"❌ Error: Gagal validasi token. Status code: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error koneksi saat validasi token Apify: {e}")
        return False


def format_durasi(detik: float) -> str:
    """Mengubah detik menjadi format menit dan detik yang mudah dibaca."""
    detik_int = int(detik)
    menit, sisa_detik = divmod(detik_int, 60)
    if menit > 0:
        return f"{menit} menit {sisa_detik} detik"
    return f"{sisa_detik} detik"


def scrape_posts_apify(username: str, sejak_iso: str, hingga_iso: str, max_posts: int, token: str):
    """
    Menjalankan Actor Apify Instagram Scraper untuk 1 username.
    
    Parameters:
    - username   : Username Instagram yang akan di-scrape (misal: "radarcirebon")
    - sejak_iso  : Tanggal batas awal dalam format ISO (misal: "2026-08-12T00:00:00Z")
    - hingga_iso : Tanggal batas akhir dalam format ISO (misal: "2026-09-11T23:59:59Z")
    - max_posts  : Batas maksimal post yang diambil per akun (default: 300)
    - token      : APIFY_TOKEN untuk autentikasi

    Returns:
    - raw_posts (list) : Data mentah hasil scraping dari Apify
    - status (str)     : "success" atau "failed"
    - error_msg (str)  : Pesan kesalahan jika terjadi kegagalan (atau "" jika sukses)
    """
    url_profil = f"https://www.instagram.com/{username}/"

    # Input payload untuk Apify Instagram Scraper
    run_input = {
        "resultsType": "posts",
        "directUrls": [url_profil],
        "resultsLimit": max_posts,
        "onlyPostsNewerThan": sejak_iso,
        "skipPinnedPosts": False,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    api_base = "https://api.apify.com/v2"
    url_start_run = f"{api_base}/acts/{ACTOR_ID}/runs"

    print(f"\n  ▶ Memulai scraping Apify untuk @{username}...")

    # Step 1: Start Actor Run
    try:
        response = requests.post(url_start_run, headers=headers, json=run_input, timeout=60)
        response.raise_for_status()
    except Exception as e:
        err_msg = f"Gagal memulai task Apify untuk @{username}: {str(e)}"
        print(f"  ❌ {err_msg}")
        return [], "failed", err_msg

    data_run = response.json().get("data", {})
    run_id = data_run.get("id")
    dataset_id = data_run.get("defaultDatasetId")

    if not run_id:
        err_msg = f"Apify tidak mengembalikan Run ID untuk @{username}"
        print(f"  ❌ {err_msg}")
        return [], "failed", err_msg

    print(f"  ℹ️ Task Apify berjalan (Run ID: {run_id})")
    catat_run_aktif(run_id, ACTOR_ID, f"post @{username}")

    # Step 2: Cek status task secara berkala hingga selesai
    url_check_status = f"{api_base}/actor-runs/{run_id}"
    status_task = "RUNNING"
    waktu_mulai = time.time()
    info_run = {}

    while status_task in ("READY", "RUNNING"):
        time.sleep(5)  # Tunggu 5 detik setiap pengecekan
        try:
            res_status = requests.get(url_check_status, headers=headers, timeout=30)
            res_status.raise_for_status()
            info_run = res_status.json().get("data", {})
            status_task = info_run.get("status", "UNKNOWN")

            if info_run.get("defaultDatasetId"):
                dataset_id = info_run["defaultDatasetId"]

            durasi = format_durasi(time.time() - waktu_mulai)
            print(f"  ⏳ @{username} | Status: {status_task} ({durasi})...")
        except Exception as e:
            print(f"  ⚠️ Warning: Gagal mengecek status Apify: {e}")

        # Batas waktu maksimal (Timeout) 30 menit
        if time.time() - waktu_mulai > 1800:
            err_msg = f"Timeout: Proses scraping @{username} melebihi 30 menit."
            print(f"  ❌ {err_msg}")
            return [], "failed", err_msg

    if status_task != "SUCCEEDED":
        err_msg = f"Scraping Apify gagal dengan status: {status_task}"
        print(f"  ❌ {err_msg}")
        hapus_run_aktif(run_id)
        return [], "failed", err_msg

    if not dataset_id:
        err_msg = f"Dataset ID dari Apify tidak ditemukan untuk @{username}"
        print(f"  ❌ {err_msg}")
        hapus_run_aktif(run_id)
        return [], "failed", err_msg

    # Biaya nyata run ini (dilaporkan Apify). Dipakai bot Telegram untuk melaporkan
    # biaya asli ke user + mengkalibrasi tarif estimasi. Kalau tidak tersedia, dilewati.
    biaya = info_run.get("usageTotalUsd")
    if biaya is not None:
        print(f"  💰 Biaya run ini (Apify): ${float(biaya):.4f}")

    # Step 3: Unduh dataset hasil scraping
    print(f"  📥 Mengunduh data postingan dari Apify...")
    url_get_items = f"{api_base}/datasets/{dataset_id}/items"

    try:
        res_items = requests.get(url_get_items, headers=headers, timeout=60)
        res_items.raise_for_status()
        raw_items = res_items.json()
    except Exception as e:
        err_msg = f"Gagal mengunduh dataset dari Apify: {str(e)}"
        print(f"  ❌ {err_msg}")
        hapus_run_aktif(run_id)
        return [], "failed", err_msg

    if not isinstance(raw_items, list):
        raw_items = []

    print(f"  ✅ Data mentah berhasil diambil: {len(raw_items)} postingan.")
    hapus_run_aktif(run_id)
    return raw_items, "success", ""


def scrape_comments_apify(target_urls: list, max_comments_per_post: int, token: str,
                          results_limit: int = None):
    """
    Menjalankan Actor Apify untuk mengambil komentar dari daftar URL postingan Instagram.

    Parameters:
    - target_urls            : List URL postingan (misal: ["https://www.instagram.com/p/CODE/"])
    - max_comments_per_post  : Batas maksimal komentar per post
    - token                  : APIFY_TOKEN untuk autentikasi
    - results_limit          : Batas TOTAL komentar yang diminta ke Apify. PENTING —
      actor Apify hanya mengenal batas TOTAL, bukan batas per post. Sebelumnya angka ini
      selalu diisi (batas per post x jumlah post), yang berarti actor boleh mengambil
      seluruh kuota dari satu postingan saja dan postingan lain tidak kebagian.
      Kalau None, dipakai cara lama (batas per post x jumlah post) demi keserasian
      dengan pemanggil lama.

    Returns:
    - raw_comments (list) : Data mentah komentar hasil scraping dari Apify
    - status (str)        : "success" atau "failed"
    - error_msg (str)     : Pesan kesalahan jika terjadi kegagalan (atau "" jika sukses)
    """
    if not target_urls:
        return [], "success", ""

    if results_limit is None:
        results_limit = max_comments_per_post * len(target_urls)
    results_limit = max(1, int(results_limit))

    # Input payload untuk Apify Comment Scraper
    # Menggunakan apify~instagram-comment-scraper atau apify~instagram-scraper dengan resultsType: comments
    run_input = {
        "directUrls": target_urls,
        "resultsLimit": results_limit,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    api_base = "https://api.apify.com/v2"
    
    # Coba jalankan dengan ACTOR_COMMENT_ID, jika tidak ada fallback ke ACTOR_ID (with resultsType: comments)
    actor_target = ACTOR_COMMENT_ID
    url_start_run = f"{api_base}/acts/{actor_target}/runs"

    print(f"\n  ▶ Memulai scraping komentar Apify untuk {len(target_urls)} post...")

    try:
        response = requests.post(url_start_run, headers=headers, json=run_input, timeout=60)
        if response.status_code == 404:
            # Fallback ke actor instagram scraper standard dengan resultsType=comments
            actor_target = ACTOR_ID
            url_start_run = f"{api_base}/acts/{actor_target}/runs"
            run_input["resultsType"] = "comments"
            response = requests.post(url_start_run, headers=headers, json=run_input, timeout=60)
            
        response.raise_for_status()
    except Exception as e:
        err_msg = f"Gagal memulai task Apify Scraper Komentar: {str(e)}"
        print(f"  ❌ {err_msg}")
        return [], "failed", err_msg

    data_run = response.json().get("data", {})
    run_id = data_run.get("id")
    dataset_id = data_run.get("defaultDatasetId")

    if not run_id:
        err_msg = "Apify tidak mengembalikan Run ID untuk scraping komentar"
        print(f"  ❌ {err_msg}")
        return [], "failed", err_msg

    print(f"  ℹ️ Task Apify Komentar berjalan (Run ID: {run_id})")
    catat_run_aktif(run_id, ACTOR_COMMENT_ID, f"komentar {len(target_urls)} post")

    # Polling status task
    url_check_status = f"{api_base}/actor-runs/{run_id}"
    status_task = "RUNNING"
    waktu_mulai = time.time()
    info_run = {}

    while status_task in ("READY", "RUNNING"):
        time.sleep(5)
        try:
            res_status = requests.get(url_check_status, headers=headers, timeout=30)
            res_status.raise_for_status()
            info_run = res_status.json().get("data", {})
            status_task = info_run.get("status", "UNKNOWN")

            if info_run.get("defaultDatasetId"):
                dataset_id = info_run["defaultDatasetId"]

            durasi = format_durasi(time.time() - waktu_mulai)
            print(f"  ⏳ Status Komentar: {status_task} ({durasi})...")
        except Exception as e:
            print(f"  ⚠️ Warning: Gagal mengecek status Apify komentar: {e}")

        if time.time() - waktu_mulai > 1800:
            err_msg = "Timeout: Proses scraping komentar melebihi 30 menit."
            print(f"  ❌ {err_msg}")
            return [], "failed", err_msg

    if status_task != "SUCCEEDED":
        err_msg = f"Scraping komentar Apify gagal dengan status: {status_task}"
        print(f"  ❌ {err_msg}")
        hapus_run_aktif(run_id)
        return [], "failed", err_msg

    if not dataset_id:
        err_msg = "Dataset ID komentar dari Apify tidak ditemukan"
        print(f"  ❌ {err_msg}")
        hapus_run_aktif(run_id)
        return [], "failed", err_msg

    # Biaya nyata run ini (dilaporkan Apify) — sama seperti pada scraping post.
    biaya = info_run.get("usageTotalUsd")
    if biaya is not None:
        print(f"  💰 Biaya run ini (Apify): ${float(biaya):.4f}")

    # Unduh dataset hasil
    print(f"  📥 Mengunduh data komentar dari Apify...")
    url_get_items = f"{api_base}/datasets/{dataset_id}/items"

    try:
        res_items = requests.get(url_get_items, headers=headers, timeout=60)
        res_items.raise_for_status()
        raw_items = res_items.json()
    except Exception as e:
        err_msg = f"Gagal mengunduh dataset komentar dari Apify: {str(e)}"
        print(f"  ❌ {err_msg}")
        hapus_run_aktif(run_id)
        return [], "failed", err_msg

    if not isinstance(raw_items, list):
        raw_items = []

    print(f"  ✅ Data mentah komentar berhasil diambil: {len(raw_items)} komentar.")
    hapus_run_aktif(run_id)
    return raw_items, "success", ""

