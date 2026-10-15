# -*- coding: utf-8 -*-
"""
apify_client.py (cirebon_opd)
=============================
Komunikasi dengan Apify API untuk scraping postingan Instagram akun OPD.
"""

import json
import time
import requests

from config import ACTOR_ID, FOLDER_HISTORY

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
    detik_int = int(detik)
    menit, sisa_detik = divmod(detik_int, 60)
    if menit > 0:
        return f"{menit} menit {sisa_detik} detik"
    return f"{sisa_detik} detik"

def scrape_posts_apify(username: str, sejak_iso: str, hingga_iso: str, max_posts: int, token: str):
    """Menjalankan Actor Apify Instagram Scraper untuk 1 username OPD."""
    endpoint_start = f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    url_profil = f"https://www.instagram.com/{username}/"
    actor_input = {
        "resultsType": "posts",
        "directUrls": [url_profil],
        "resultsLimit": max_posts,
        "onlyPostsNewerThan": sejak_iso,
        "skipPinnedPosts": False,
    }

    print(f"\n  Memulai scraping Apify untuk @{username}...")
    print(f"  Rentang tanggal : {sejak_iso[:10]} s/d {hingga_iso[:10]}")
    print(f"  Batas maksimal  : {max_posts} post")

    try:
        resp = requests.post(endpoint_start, json=actor_input, headers=headers, timeout=30)
        if resp.status_code not in (200, 201):
            msg = f"Gagal memulai Actor Apify (HTTP {resp.status_code}): {resp.text[:300]}"
            print(f"  ❌ {msg}")
            return [], "FAILED", msg

        run_data = resp.json().get("data", {})
        run_id = run_data.get("id")
        dataset_id = run_data.get("defaultDatasetId")
        print(f"  ℹ️ Task Apify berjalan (Run ID: {run_id})")
        catat_run_aktif(run_id, ACTOR_ID, f"post @{username}")

    except Exception as e:
        msg = f"Koneksi gagal saat memanggil Apify: {e}"
        print(f"  ❌ {msg}")
        return [], "FAILED", msg

    endpoint_status = f"https://api.apify.com/v2/actor-runs/{run_id}"
    waktu_mulai = time.time()
    waktu_polling_terakhir = 0
    INTERVAL_LOG = 5

    try:
        while True:
            time.sleep(3)
            try:
                r_status = requests.get(endpoint_status, headers=headers, timeout=15)
                status_data = r_status.json().get("data", {})
                current_status = status_data.get("status", "UNKNOWN")
            except Exception as e:
                print(f"  ⚠️ Gagal memeriksa status: {e}, mencoba lagi...")
                continue

            durasi_berjalan = time.time() - waktu_mulai
            if time.time() - waktu_polling_terakhir >= INTERVAL_LOG:
                print(f"  ⏳ @{username} | Status: {current_status} ({format_durasi(durasi_berjalan)})...")
                waktu_polling_terakhir = time.time()

            if current_status == "SUCCEEDED":
                biaya_run = float(status_data.get("usageTotalUsd", 0.0) or 0.0)
                print(f"  ✅ Task @{username} selesai dalam {format_durasi(durasi_berjalan)}.")
                if biaya_run > 0:
                    print(f"  💰 Biaya run ini (Apify): ${biaya_run:.4f}")
                break
            elif current_status in ("FAILED", "ABORTED", "TIMING-OUT"):
                msg = f"Task Apify @{username} berakhir dengan status: {current_status}"
                print(f"  ❌ {msg}")
                return [], current_status, msg

            if durasi_berjalan > 900:
                print(f"  ⚠️ Timeout: Task @{username} berjalan lebih dari 15 menit. Membatalkan...")
                requests.post(f"https://api.apify.com/v2/actor-runs/{run_id}/abort", headers=headers)
                return [], "TIMEOUT", "Scraping timeout setelah 15 menit."

    finally:
        hapus_run_aktif(run_id)

    # Ambil dataset hasil
    endpoint_dataset = f"https://api.apify.com/v2/datasets/{dataset_id}/items?clean=true&format=json"
    print(f"  Mengunduh data mentah dari dataset {dataset_id}...")

    try:
        r_dataset = requests.get(endpoint_dataset, headers=headers, timeout=60)
        if r_dataset.status_code == 200:
            items = r_dataset.json()
            print(f"  ✅ Data mentah berhasil diambil: {len(items)} postingan.")
            return items, "SUCCEEDED", None
        else:
            msg = f"Gagal mengunduh dataset (HTTP {r_dataset.status_code})"
            print(f"  ❌ {msg}")
            return [], "FAILED", msg
    except Exception as e:
        msg = f"Error saat mengunduh dataset: {e}"
        print(f"  ❌ {msg}")
        return [], "FAILED", msg

