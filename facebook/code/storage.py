# -*- coding: utf-8 -*-
"""
storage.py (modul TikTok) — VERSI SEDERHANA (18 Sep 2026)
========================================================
Menyimpan hasil scrape + JEJAK AUDIT supaya kehilangan data tidak pernah terjadi diam-diam.

Bentuk keluaran (semua di bawah folder tiktok/):
  post/<slug_topik>/mentah/<query>_<ts>.json                     -> SEMUA item mentah dari actor
  post/<slug_topik>/kandidat/<query>_<ts>.csv|json               -> yang lolos gerbang wilayah (per query)
  post/<slug_topik>/gabungan_terfilter/tiktok_master_<slug>_<ts>.csv|json   -> hasil akhir (dinilai relevan AI)
  post/<slug_topik>/gabungan_terfilter/tiktok_ditolak_ai_<ts>.csv|json      -> dinilai TIDAK/RAGU (tetap disimpan!)
  post/<slug_topik>/gabungan_terfilter/laporan_funnel_<ts>.txt              -> ringkasan corong tiap run
  history/history_tiktok_post.csv|json                           -> log tiap run (+ run_id & dataset_id Apify)

KENAPA data mentah dan yang ditolak DISIMPAN?
Karena itu satu-satunya cara mengukur recall. Pada run 17 Sep 2026, data mentah tidak disimpan
dan run_id tidak dicatat, sehingga satu-satunya jalan memeriksa "berapa yang sebenarnya kelewat"
adalah menebak lewat daftar run Apify. Setelah disimpan, audit berikutnya GRATIS dan bisa diulang.
"""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from config import FOLDER_POST, FOLDER_COMMENT, FOLDER_HISTORY, NAMA_PLATFORM, folder_topik
from evaluator import evaluasi_gerbang
from llm_reviewer import review_posts_dengan_llm
from rule_builder import simpan_contoh_negatif, contoh_negatif_untuk_prompt, caption_contoh_untuk_ai

# Kolom master postingan (urutan ini yang muncul di CSV)
KOLOM_POST = [
    "topik", "id", "post_id", "platform", "query_search", "username",
    "published_at", "caption", "hashtags", "like_count", "comment_count", "play_count",
    "share_count", "web_url", "scraped_at",
    "gerbang_alasan",
    "is_relevan_llm", "alasan_review_llm", "kategori",
]

KOLOM_HISTORY = [
    "waktu_mulai", "waktu_selesai", "topik", "query_search", "platform",
    "status", "jumlah_ditarik", "jumlah_lolos_gerbang", "biaya_usd",
    "run_id", "dataset_id", "pesan_error",
]

KOLOM_KOMENTAR = [
    "topik", "post_id", "post_url", "comment_id", "username",
    "text", "created_at", "likes", "reply_count", "sentimen", "skor_yakin",
]


def _stempel_waktu() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _slug_query(query: str) -> str:
    slug = "".join(c if (c.isalnum() or c == "_") else "_" for c in (query or "").lower()).strip("_")
    return slug or "query"


def _tulis_csv_json(path_csv: Path, path_json: Path, baris: list, kolom: list) -> tuple:
    """Tulis daftar dict ke CSV (utf-8-sig, biar rapi di Excel) + JSON."""
    path_csv.parent.mkdir(parents=True, exist_ok=True)

    with open(path_csv, mode="w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=kolom, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(baris)

    with open(path_json, mode="w", encoding="utf-8") as f:
        json.dump(baris, f, ensure_ascii=False, indent=2)

    return path_csv, path_json


# ============================================================
# 1. SIMPAN DATA MENTAH (semua item dari actor, belum disaring)
# ============================================================
def simpan_mentah(items: list, nama_topik: str, query_search: str) -> Path:
    """
    Simpan SELURUH item mentah 1 kata kunci ke post/<slug>/mentah/.
    Ini bahan audit recall: kapan pun, kita bisa menjalankan ulang gerbang + AI ke file ini
    TANPA scrape ulang (gratis).
    """
    slug_topik = folder_topik(nama_topik).name
    folder = FOLDER_POST / slug_topik / "mentah"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_slug_query(query_search)}_{_stempel_waktu()}.json"
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ============================================================
# 2. GERBANG: saring per kata kunci, simpan kandidat
# ============================================================
def bentuk_record_gerbang(item: dict, hasil: dict, nama_topik: str, query_search: str) -> dict:
    """Ubah 1 postingan hasil scrape Facebook + hasil gerbang jadi satu baris data yang siap disimpan."""
    meta = hasil.get("meta", {}) or {}
    akun = meta.get("username") or item.get("authorName") or item.get("profileName") or item.get("author_name") or "netizen"
    post_id = str(item.get("id") or item.get("postId") or item.get("fbid")
                  or (item.get("postUrl", "").split("/")[-1] or "")).strip()
    url = item.get("url") or item.get("postUrl") or item.get("webUrl") or f"https://www.facebook.com/{post_id}"
    daftar_hashtag = list(meta.get("hashtags") or [])

    def _angka(nilai) -> int:
        try:
            return int(nilai or 0)
        except Exception:
            return 0

    return {
        "topik": nama_topik,
        "id": item.get("_scrape_id", ""),
        "post_id": post_id,
        "platform": NAMA_PLATFORM,
        "query_search": query_search,
        "username": akun,
        "published_at": meta.get("tgl_upload") or "",
        "caption": (item.get("text") or item.get("message") or item.get("content") or item.get("caption") or "").replace("\n", " ").strip(),
        "hashtags": ", ".join(daftar_hashtag),
        "hashtag_list": daftar_hashtag,          # dipakai prompt AI (list, bukan string)
        "like_count": _angka(item.get("likes") or item.get("likesCount") or item.get("reactions") or item.get("reactionCount")),
        "comment_count": _angka(item.get("comments") or item.get("commentsCount") or item.get("commentCount")),
        "play_count": _angka(item.get("views") or item.get("viewsCount") or item.get("videoViews") or 0),
        "share_count": _angka(item.get("shares") or item.get("sharesCount") or item.get("shareCount")),
        "web_url": url,
        "scraped_at": item.get("_waktu_scrape", ""),
        "gerbang_alasan": hasil.get("alasan_gerbang", ""),
        "is_relevan_llm": "BELUM_DINILAI",
        "alasan_review_llm": "-",
        "kategori": "none",
    }


def saring_dan_simpan_per_query(items: list, nama_topik: str, query_search: str, kaidah: dict,
                                scrape_id: str, waktu_scrape: str,
                                tanggal_min: str = "", tanggal_maks: str = "") -> tuple:
    """
    Jalankan GERBANG (bukan penilaian topik) untuk hasil SATU kata kunci,
    lalu simpan kandidat ke post/<slug>/kandidat/.

    Returns: (jumlah_lolos, path_csv, path_json, dataset_lolos, ringkasan)
      ringkasan = {"ditarik", "lolos", "gugur": {alasan_singkat: jumlah}}
    """
    slug_topik = folder_topik(nama_topik).name
    folder = FOLDER_POST / slug_topik / "kandidat"
    ts = _stempel_waktu()
    sq = _slug_query(query_search)
    path_csv = folder / f"{sq}_{ts}.csv"
    path_json = folder / f"{sq}_{ts}.json"

    sudah_ada_id = set()
    baris_lolos = []
    hitung_gugur = {}

    for item in items or []:
        item["_scrape_id"] = scrape_id
        item["_waktu_scrape"] = waktu_scrape

        post_id = str(item.get("id") or "").strip()
        if post_id and post_id in sudah_ada_id:
            continue

        hasil = evaluasi_gerbang(item, kaidah, tanggal_min=tanggal_min, tanggal_maks=tanggal_maks)

        if not hasil["lolos"]:
            alasan = hasil.get("alasan_gerbang", "")
            kunci = alasan.split(":")[0].strip() or "lain-lain"
            hitung_gugur[kunci] = hitung_gugur.get(kunci, 0) + 1
            continue

        if post_id:
            sudah_ada_id.add(post_id)
        baris_lolos.append(bentuk_record_gerbang(item, hasil, nama_topik, query_search))

    _tulis_csv_json(path_csv, path_json, baris_lolos, KOLOM_POST)

    ringkasan = {"ditarik": len(items or []), "lolos": len(baris_lolos), "gugur": hitung_gugur}
    return len(baris_lolos), path_csv, path_json, baris_lolos, ringkasan


# ============================================================
# 3. MASTER + GATE AI + LAPORAN FUNNEL
# ============================================================
def _tulis_laporan_funnel(path: Path, nama_topik: str, ringkasan_query: list,
                          jumlah_kandidat: int, jumlah_mentah: int,
                          daftar_ya: list, daftar_tolak: list, contoh_acuan: list) -> Path:
    """Tulis ringkasan corong: ditarik -> lolos gerbang -> dinilai AI -> YA/TIDAK/RAGU."""
    from collections import Counter
    jumlah_ya = sum(1 for p in daftar_ya)
    jumlah_kota = sum(1 for p in daftar_ya if str(p.get("kategori")).lower() == "kota")
    jumlah_kab = sum(1 for p in daftar_ya if str(p.get("kategori")).lower() == "kabupaten")
    jumlah_none = sum(1 for p in daftar_ya if str(p.get("kategori")).lower() == "none")
    jumlah_ragu = sum(1 for p in daftar_tolak if str(p.get("is_relevan_llm")).upper() == "RAGU")
    jumlah_tidak = sum(1 for p in daftar_tolak if str(p.get("is_relevan_llm")).upper() == "TIDAK")

    baris = []
    baris.append(f"LAPORAN CORONG — topik: {nama_topik}")
    baris.append(f"Waktu: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    baris.append("=" * 70)
    baris.append(f"1. Item mentah ditarik dari Apify ....... {jumlah_mentah}")
    baris.append(f"2. Lolos gerbang wilayah (kandidat) ..... {jumlah_kandidat}")
    baris.append(f"3. Dinilai AI ............................ {len(daftar_ya) + len(daftar_tolak)}")
    baris.append(f"     - Relevan (YA) ..................... {jumlah_ya}")
    baris.append(f"         > Kota Cirebon ................. {jumlah_kota}")
    baris.append(f"         > Kabupaten Cirebon ............ {jumlah_kab}")
    baris.append(f"         > Cirebon Umum ................. {jumlah_none}")
    baris.append(f"     - Tidak relevan (TIDAK) ............ {jumlah_tidak}")
    baris.append(f"     - Perlu diperiksa (RAGU) ........... {jumlah_ragu}")
    baris.append("")
    baris.append("Rincian per kata kunci:")
    for r in ringkasan_query:
        baris.append(f"  - \"{r['query']}\": {r['status']} | ditarik {r['ditarik']} | "
                     f"lolos gerbang {r['lolos']} | gugur {r.get('gugur', {})}")
    baris.append("")
    baris.append(f"Contoh video acuan yang dipakai AI ({len(contoh_acuan)}):")
    for c in contoh_acuan:
        baris.append(f"  - {c[:150]}")
    baris.append("")
    baris.append("5 contoh yang DITOLAK AI (periksa: apakah ada yang seharusnya masuk?):")
    ditolak_contoh = [p for p in daftar_tolak][:5]
    if ditolak_contoh:
        for p in ditolak_contoh:
            baris.append(f"  [{p.get('is_relevan_llm')}] @{p.get('username')} | "
                         f"{(p.get('caption') or '')[:90]} | {str(p.get('alasan_review_llm'))[:80]}")
    else:
        baris.append("  (tidak ada yang ditolak)")
    baris.append("")
    baris.append("5 contoh yang DITERIMA AI:")
    for p in daftar_ya[:5]:
        baris.append(f"  @{p.get('username')} | {(p.get('caption') or '')[:90]}")
    baris.append("")
    baris.append("Catatan: kalau angka 'lolos gerbang' kecil sementara 'item mentah' besar,")
    baris.append("masalahnya di kata kunci pencarian — bukan di gerbang/AI.")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(baris) + "\n", encoding="utf-8")
    return path


def gabungkan_dan_simpan_master(semua_baris: list, nama_topik: str, kaidah: dict,
                                gunakan_gate_ai: bool = True,
                                jumlah_mentah: int = 0, ringkasan_query: list = None,
                                contoh_acuan: list = None) -> dict:
    """
    Gabung hasil semua kata kunci -> buang duplikat post_id -> gate AI -> MASTER.

    Post yang dinilai TIDAK atau RAGU:
      - dikeluarkan dari master, TAPI
      - tetap DISIMPAN ke file terpisah supaya bisa diperiksa manusia,
      - yang TIDAK disimpan sebagai contoh negatif untuk run berikutnya.

    Returns dict: {"jumlah", "path_csv", "path_json", "dataset", "jumlah_ya", "jumlah_ditolak",
                   "jumlah_ragu", "path_ditolak", "path_negatif", "path_laporan", "path_kandidat"}
    """
    slug_topik = folder_topik(nama_topik).name
    folder_hasil = FOLDER_POST / slug_topik / "gabungan_terfilter"
    ts = _stempel_waktu()
    path_csv = folder_hasil / f"facebook_master_{slug_topik}_{ts}.csv"
    path_json = folder_hasil / f"facebook_master_{slug_topik}_{ts}.json"
    path_tolak_csv = folder_hasil / f"facebook_ditolak_ai_{ts}.csv"
    path_tolak_json = folder_hasil / f"facebook_ditolak_ai_{ts}.json"
    path_laporan = folder_hasil / f"laporan_funnel_{ts}.txt"

    # --- dedup berdasarkan post_id (yang pertama menang) ---
    terlihat = set()
    dataset = []
    for baris in semua_baris:
        pid = baris.get("post_id") or ""
        if pid and pid in terlihat:
            continue
        if pid:
            terlihat.add(pid)
        dataset.append(baris)

    # --- simpan SEMUA kandidat (sebelum AI) — ini dasar audit ---
    path_kandidat_csv, path_kandidat_json = _tulis_csv_json(
        folder_hasil / f"facebook_kandidat_semua_{ts}.csv",
        folder_hasil / f"facebook_kandidat_semua_{ts}.json",
        dataset, KOLOM_POST)

    contoh_acuan = contoh_acuan if contoh_acuan is not None else caption_contoh_untuk_ai(nama_topik)
    if not contoh_acuan:
        print("\n" + "!" * 70)
        print("🔴 PERINGATAN: TIDAK ADA CONTOH VIDEO yang dikirim ke AI.")
        print("   Gate AI memang masih jalan, tapi tanpa contoh penilaiannya jauh lebih lemah")
        print("   (inilah akar masalah versi lama). Isi topik/<slug>/contoh.txt dulu.")
        print("!" * 70)
    contoh_negatif = contoh_negatif_untuk_prompt(nama_topik)
    print(f"\n  📌 Kandidat lolos gerbang: {len(dataset)} post (disimpan: {path_kandidat_csv})")
    if contoh_negatif:
        print(f"  📌 {len(contoh_negatif)} contoh negatif dari run sebelumnya ikut dikirim ke AI.")

    # --- gate AI ---
    daftar_ya, daftar_tolak = [], []
    path_negatif = None

    if gunakan_gate_ai and dataset:
        dataset = review_posts_dengan_llm(dataset, nama_topik, kaidah,
                                           contoh_acuan=contoh_acuan, contoh_negatif=contoh_negatif)
        negatif = []
        for baris in dataset:
            nilai = str(baris.get("is_relevan_llm", "RAGU")).upper()
            if nilai == "YA":
                daftar_ya.append(baris)
            else:
                daftar_tolak.append(baris)
                if nilai == "TIDAK":
                    negatif.append({
                        "url": baris.get("web_url", ""),
                        "caption": baris.get("caption", ""),
                        "alasan_llm": baris.get("alasan_review_llm", ""),
                        "tanggal": str(baris.get("scraped_at", ""))[:10],
                    })
        if negatif:
            path_negatif = simpan_contoh_negatif(nama_topik, negatif)
            print(f"  📝 {len(negatif)} post 'tidak relevan' disimpan sebagai contoh negatif: {path_negatif}")
    else:
        # tanpa gate AI: semua kandidat dianggap perlu diperiksa manusia
        for baris in dataset:
            baris["is_relevan_llm"] = "BELUM_DINILAI"
            baris["kategori"] = "none"
            baris["alasan_review_llm"] = "Gate AI dimatikan (--no-llm)"
        daftar_ya = list(dataset)

    _tulis_csv_json(path_csv, path_json, daftar_ya, KOLOM_POST)
    if daftar_tolak:
        _tulis_csv_json(path_tolak_csv, path_tolak_json, daftar_tolak, KOLOM_POST)
    _tulis_laporan_funnel(path_laporan, nama_topik, ringkasan_query or [], len(dataset),
                          jumlah_mentah, daftar_ya, daftar_tolak, contoh_acuan)

    return {
        "jumlah": len(daftar_ya),
        "jumlah_ya": len(daftar_ya),
        "jumlah_kota": sum(1 for p in daftar_ya if str(p.get("kategori")).lower() == "kota"),
        "jumlah_kab": sum(1 for p in daftar_ya if str(p.get("kategori")).lower() == "kabupaten"),
        "jumlah_none": sum(1 for p in daftar_ya if str(p.get("kategori")).lower() == "none"),
        "jumlah_ditolak": len(daftar_tolak),
        "jumlah_ragu": sum(1 for p in daftar_tolak if str(p.get("is_relevan_llm")).upper() == "RAGU"),
        "path_csv": path_csv,
        "path_json": path_json,
        "path_ditolak": path_tolak_csv if daftar_tolak else None,
        "path_negatif": path_negatif,
        "path_laporan": path_laporan,
        "path_kandidat": path_kandidat_csv,
        "dataset": daftar_ya,
    }


# ============================================================
# 4. RIWAYAT RUN
# ============================================================
def catat_riwayat(nama_topik: str, query_search: str, status: str, jumlah_ditarik: int,
                  jumlah_lolos: int, waktu_mulai: str, waktu_selesai: str,
                  biaya_usd: float = 0.0, run_id: str = "", dataset_id: str = "",
                  pesan_error: str = "") -> None:
    """
    Tulis 1 baris riwayat run ke history/history_tiktok_post.csv + .json (append).

    run_id & dataset_id disimpan supaya dataset Apify bisa dibaca ulang GRATIS
    (untuk audit recall) walau data di disk sudah terhapus.
    """
    FOLDER_HISTORY.mkdir(parents=True, exist_ok=True)
    path_csv = FOLDER_HISTORY / "history_facebook_post.csv"
    path_json = FOLDER_HISTORY / "history_facebook_post.json"

    baris = {
        "waktu_mulai": waktu_mulai,
        "waktu_selesai": waktu_selesai,
        "topik": nama_topik,
        "query_search": query_search,
        "platform": NAMA_PLATFORM,
        "status": status,
        "jumlah_ditarik": jumlah_ditarik,
        "jumlah_lolos_gerbang": jumlah_lolos,
        "biaya_usd": biaya_usd,
        "run_id": run_id,
        "dataset_id": dataset_id,
        "pesan_error": pesan_error,
    }

    file_baru = not path_csv.exists() or path_csv.stat().st_size == 0
    with open(path_csv, mode="a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=KOLOM_HISTORY, extrasaction="ignore")
        if file_baru:
            writer.writeheader()
        writer.writerow(baris)

    data = []
    if path_json.exists() and path_json.stat().st_size > 0:
        try:
            data = json.loads(path_json.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                data = []
        except Exception:
            data = []
    data.append(baris)
    path_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================
# 5. SIMPAN KOMENTAR FACEBOOK & SENTIMEN
# ============================================================
def simpan_komentar_facebook(daftar_komentar: list, nama_topik: str, waktu_scrape: str = "") -> tuple:
    """
    Simpan dataset komentar Facebook ke comment/<slug>/facebook_comment_<slug>_<timestamp>.csv|json.
    Mencetak '- CSV :' agar otomatis dikenali runner bot Telegram.
    """
    slug_topik = folder_topik(nama_topik).name
    folder = FOLDER_COMMENT / slug_topik
    folder.mkdir(parents=True, exist_ok=True)

    ts = waktu_scrape or _stempel_waktu()
    path_csv = folder / f"facebook_comment_{slug_topik}_{ts}.csv"
    path_json = folder / f"facebook_comment_{slug_topik}_{ts}.json"

    _tulis_csv_json(path_csv, path_json, daftar_komentar, KOLOM_KOMENTAR)

    print(f"\n  💾 DATASET KOMENTAR DISIMPAN ({len(daftar_komentar)} komentar):")
    print(f"  - CSV  : {path_csv}")
    print(f"  - JSON : {path_json}")
    return path_csv, path_json


simpan_komentar_tiktok = simpan_komentar_facebook
