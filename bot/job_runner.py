# -*- coding: utf-8 -*-
"""
job_runner.py
=============
MESIN PENGEEKSEKUSI JOB: antrean, menjalankan scraper sebagai proses terpisah,
melaporkan perkembangan TERUS-MENERUS, lalu mengirim hasil.

PELAJARAN 22 Sep 2026 (keluhan user: "menunggu ber menit-menit tanpa kabar")
--------------------------------------------------------------------------
Versi pertama hanya memperbarui pesan progres saat ada PENANDA PERISTIWA
(misal "Lolos Filter", "Analisis sentimen"). Akibatnya, selama Apify bekerja
1-3 menit per akun, user tidak melihat apa pun — tidak tahu sedang apa, tidak
tahu masih hidup atau sudah mati.

Perbaikan di versi ini:
1. DETAK (heartbeat): pesan progres diperbarui tiap DETAK_DETIK detik walau
   tidak ada peristiwa baru, isinya "sudah berjalan X menit" + aktivitas terakhir.
2. Baris POLLING Apify ikut dibaca: "Status: RUNNING (2 menit 5 detik)" diterjemahkan
   jadi "Apify sedang mengambil data (2 menit 5 detik)".
3. Galat yang muncul di tengah jalan langsung dilaporkan saat itu juga, bukan
   disimpan sampai akhir.
4. Tombol "Batalkan job" di pesan progres -> proses scraper benar-benar dimatikan.
5. Kalau gagal, ringkasan memuat CUPLIKAN keluaran terakhir supaya penyebabnya
   bisa dipastikan tanpa menebak.

KENAPA SCRAPER DIJALANKAN SEBAGAI PROSES TERPISAH (subprocess)?
- Modul scraper butuh transformers + torch yang hanya ada di Python Windows.
- Bot tetap hidup kalau scraper crash, dan bot bisa melaporkan penyebabnya.
- Keluaran scraper dibaca baris demi baris -> bahan pesan progres & detak.
- Tidak ada tabrakan nama modul (config.py ada di dua tempat berbeda).
"""

import json
import os
import re
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import bot_config as cfg
import telegram_api as tg

PENGIRIM = tg                      # bisa diganti di uji tiruan
PATH_JOB = cfg.FOLDER_BOT / "data" / "job.json"
PATH_RIWAYAT = cfg.FOLDER_BOT / "data" / "riwayat_job.json"

DETAK_DETIK = 10                   # jeda detak progres; disetel kecil saat uji
MAKS_BARIS_CUPLIKAN = 10           # jumlah baris keluaran terakhir yang disimpan
MAKS_KEJADIAN = 6                  # jumlah kejadian yang ditampilkan di pesan progres
MAKS_BERKAS_CADANGAN = 25          # batas berkas pada pencarian cadangan (lihat
#   _kumpulkan_berkas). Dinaikkan dari 6 pada 22 Sep 2026: satu job 4 akun dengan
#   komentar menghasilkan 14 berkas (8 post + 6 komentar), jadi batas 6 membuang
#   berkas POST secara diam-diam. Angka ini hanya jaring pengaman kalau scraper
#   berhenti mendadak sehingga daftar berkas resminya tidak sempat tercetak.
MAKS_BARIS_ARSIP_LOG = 50000       # batas baris arsip log mentah per job.
#   Sejak baris log yang tidak menambah informasi tidak lagi dikirim ke chat
#   (permintaan user 22 Sep 2026), SEMUA baris tetap disimpan apa adanya di berkas
#   arsip. Angka ini hanya jaring pengaman supaya berkas tidak tumbuh tanpa batas;
#   job nyata hanya menghasilkan ratusan baris.

# ============================================================
# POLA BARIS OUTPUT SCRAPER YANG DIPANTAU
# ============================================================
POLA = {
    "mulai_akun": re.compile(r"\[(\d+)/(\d+)\] Memproses Post: (.+?) \(@(.+?)\)"),
    "apify_post": re.compile(r"Memulai scraping Apify untuk @(\S+)"),
    # Jumlah post MENTAH yang ditarik Apify sebelum difilter -> bahan rincian per akun.
    "mentah_post": re.compile(r"Data Mentah Apify\s*:\s*(\d+)\s*post"),
    "lolos": re.compile(r"Lolos Filter \([^)]*\):\s*(\d+) post"),
    "top_video": re.compile(r"Top Video Komentar Terbanyak\s*:\s*(\d+) video"),
    "apify_komentar": re.compile(r"Memulai scraping komentar Apify untuk (\d+) post"),
    # Judul blok komentar per akun -> penanda "sekarang sedang akun siapa".
    "komentar_akun": re.compile(r"Memproses Komentar Video:\s*.+?\(@(.+?)\)"),
    # Baris polling Apify: "Status: RUNNING (2 menit 5 detik)" / "Status Komentar: ..."
    "polling": re.compile(r"Status(?: Komentar)?:\s*([A-Z\-]+)\s*\(\s*([^)]+)\)"),
    "sentimen": re.compile(r"Menjalankan Analisis Sentimen IndoBERTweet \((\d+) komentar\)"),
    # CATATAN 24 Sep 2026: pola untuk tahap penilaian LLM (gate, ai_batch, llm_gagal,
    # llm_rotasi, ai_pos/ai_neg/ai_net, ai_beda, gate_ya) SUDAH DIHAPUS karena tahap
    # itu tidak lagi dijalankan oleh scraper. Menyimpan pola untuk kalimat yang tidak
    # pernah dicetak hanya membuat bot menunggu peristiwa yang tidak akan datang —
    # inilah yang dulu membuat pesan progres terlihat macet.
    "komentar_saved": re.compile(r"Komentar Saved\s*:\s*(\d+)"),
    "total_post": re.compile(r"Total Post Saved\s*:\s*(\d+) post"),
    "akun_sukses": re.compile(r"Akun Sukses\s*:\s*(\d+)"),
    "akun_gagal": re.compile(r"Akun Gagal\s*:\s*(\d+)"),
    "sentimen_pos": re.compile(r"^\s*\*\s*POSITIF\s*:\s*(\d+)\s*\(([\d.]+)%\)"),
    "sentimen_neg": re.compile(r"^\s*\*\s*NEGATIF\s*:\s*(\d+)\s*\(([\d.]+)%\)"),
    "sentimen_net": re.compile(r"^\s*\*\s*NETRAL\s*:\s*(\d+)\s*\(([\d.]+)%\)"),
    # (Pola penilaian sentimen oleh LLM sudah dihapus — lihat catatan di atas.)
    # PENTING: scraper mencetak "- CSV  : D:\\..." (ada tanda strip di depannya).
    # Pola lama "^\s*(CSV|JSON)" TIDAK PERNAH cocok, karena tanda strip bukan spasi.
    # Akibatnya tidak satu pun alamat berkas terbaca, bot lalu jatuh ke pencarian
    # cadangan yang hanya mengambil 6 berkas TERBARU — dan karena berkas komentar
    # selalu ditulis SETELAH berkas post, ke-6 kuota itu habis oleh berkas komentar.
    # Itulah sebabnya berkas POST tidak pernah ikut terkirim (kejadian nyata job001,
    # 22 Sep 2026). Tanda strip/bullet kini diterima.
    "berkas": re.compile(r"^\s*[-•*]?\s*(?:CSV\s+RANKING|CSV|JSON)\s*:\s*(.+?)\s*$", re.I),
    "ranking_item": re.compile(r"^\s*(\d+)\.\s*@(\S+)\s*\|\s*Skor:\s*(\d+)\s*\(([^)]+)\)\s*-\s*(.+)$"),
    "biaya": re.compile(r"Biaya run ini \(Apify\):\s*\$([\d.]+)"),
    "galat": re.compile(r"❌\s*(.+)$"),
    "selesai": re.compile(r"TOTAL SELESAI"),
    "spam": re.compile(r"\[INFO\]\s*(\d+)\s*komentar bot\/log terfilter sebelum sentimen"),
    "tiktok_query": re.compile(r"\[(\d+)/(\d+)\] Kata kunci:\s*\"(.+?)\""),
    "tiktok_mentah": re.compile(r"Item mentah ditarik\s*:\s*(\d+)"),
    "tiktok_lolos": re.compile(r"Kandidat lolos gerbang:\s*(\d+)"),
    "tiktok_relevan": re.compile(r"Relevan \(YA\)\s*:\s*(\d+)"),
    "tiktok_kota": re.compile(r"-\s*Kota Cirebon\s*:\s*(\d+)"),
    "tiktok_kab": re.compile(r"-\s*Kabupaten Cirebon\s*:\s*(\d+)"),
    "tiktok_none": re.compile(r"-\s*Umum/Lainnya\s*:\s*(\d+)"),
    "tiktok_ragu": re.compile(r"Perlu diperiksa \(RAGU\)\s*:\s*(\d+)"),
    "tiktok_ai_gate": re.compile(r"MASTER DATASET & GATE AI|Meminta AI membuat|Menilai relevansi", re.I),
}

# Status job
MENUNGGU = "menunggu"
BERJALAN = "berjalan"
SUKSES = "sukses"
GAGAL = "gagal"
DIBATALKAN = "dibatalkan"
TERPUTUS = "terputus"

# ============================================================
# KEADAAN INTERNAL
# ============================================================
_ANTREAN = []
_AKTIF = None
_NOMOR = 0
# Laporan terakhir per chat (untuk tombol interaktif pada pesan ringkasan).
# Disimpan di memori: cukup untuk sesi bot berjalan, tidak perlu ikut disimpan ke berkas.
_LAPORAN_TERAKHIR = {}
# PENTING: RLock (re-entrant lock), BUKAN Lock biasa.
# Alasannya: jalankan_job() mengunci antrean, lalu di dalamnya memanggil fungsi
# pemeriksaan (job_aktif_untuk) yang ikut mengunci antrean. Dengan Lock biasa,
# thread yang sama menunggu dirinya sendiri -> program membeku tanpa pesan apa pun.
# Kejadian ini nyata pada uji tiruan 22 Sep 2026 (uji berhenti di skenario 1).
_LOCK = threading.RLock()
_WORKER_JALAN = False


def _sekarang() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _durasi(detik: float) -> str:
    menit, sisa = divmod(int(detik), 60)
    if menit:
        return f"{menit} menit {sisa} detik"
    return f"{sisa} detik"


def _pct(bagian: int, total: int) -> str:
    """
    Persentase dengan 2 angka di belakang koma. Aman kalau totalnya nol.

    DIHITUNG ULANG dari jumlah kumulatif, karena persentase tiap akun TIDAK BOLEH
    dijumlahkan begitu saja (60% + 12% bukan 72%).
    """
    if not total:
        return "0.00"
    return f"{bagian * 100.0 / total:.2f}"


def _catatan_gabungan(hasil: dict) -> str:
    """
    Keterangan kecil penanda bahwa angka sentimen di baris itu GABUNGAN seluruh akun.

    Hanya muncul kalau memang ada lebih dari satu akun berkomentar — supaya tidak
    membingungkan saat jobnya cuma satu akun.
    """
    jumlah = hasil.get("akun_komentar") or 0
    return f" (gabungan {jumlah} akun)" if jumlah > 1 else ""


def _path_untuk_windows(path) -> str:
    """
    Ubah /mnt/d/foo/bar.py menjadi D:\\foo\\bar.py.

    KENAPA PERLU: kalau bot dijalankan dari WSL, python.exe milik Windows
    TIDAK paham alamat gaya Linux. Argumen harus diterjemahkan dulu.
    """
    teks = str(path)
    if teks.startswith("/mnt/") and len(teks) > 6:
        drive = teks[5].upper()
        sisa = teks[6:].replace("/", "\\")
        return f"{drive}:{sisa}"
    return teks


# ============================================================
# BACA/SIMPAN JEJAK JOB
# ============================================================
def _muat_json(path, bawaan):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return bawaan


def _simpan_json(path, isi):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(isi, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as galat:
        print(f"[JOB] Gagal menyimpan {path.name}: {galat}")


def _catat_jejak(semua_job: list):
    _simpan_json(PATH_JOB, semua_job)


def bersihkan_job_terputus():
    """
    Dipanggil sekali saat bot start. Dua tugas:

    1. MEMATIKAN PROSES SCRAPER YATIM. Kalau jendela bot ditutup saat job berjalan,
       proses scraper-nya TIDAK ikut mati di Windows — dia jadi yatim dan terus bekerja
       di latar belakang (masih menembak Apify). Akibatnya beberapa proses berebut
       sumber daya komputer yang sama dan semuanya jadi lambat.
       Kejadian nyata 22 Sep 2026: satu tahap yang biasanya ±2,5 menit menjadi >6 menit
       karena ada proses lama yang belum mati.
    2. Menandai job yang tercatat 'berjalan' sebagai 'terputus' (jujur apa adanya).
    """
    riwayat = _muat_json(PATH_JOB, [])
    if not isinstance(riwayat, list):
        return
    diubah = False
    for job in riwayat:
        if job.get("status") == BERJALAN:
            pid = job.get("pid")
            if pid:
                if _matikan_pid(pid):
                    job["catatan"] = (f"Proses scraper lama (PID {pid}) dimatikan otomatis saat bot "
                                      "start, karena bot sebelumnya berhenti tanpa menutup prosesnya.")
                else:
                    job["catatan"] = f"Proses scraper (PID {pid}) sudah tidak berjalan."
            else:
                job["catatan"] = "Bot mati/restart saat job ini berjalan."
            job["status"] = TERPUTUS
            job["selesai"] = _sekarang()
            diubah = True
    if diubah:
        _catat_jejak(riwayat)
        print("[JOB] Job lama ditandai 'terputus'. Proses scraper yang tertinggal dimatikan.")
        # Run Apify dari sesi lama juga diminta berhenti, supaya biaya tidak jalan terus.
        jumlah, info = hentikan_run_apify()
        if jumlah:
            print(f"[JOB] {info}")


def _matikan_pid(pid) -> bool:
    """
    Matikan proses berdasarkan PID. Returns True kalau prosesnya memang ada dan dimatikan.
    Dipakai HANYA untuk proses scraper yang kita sendiri jalankan (PID dicatat saat start).
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            hasil = subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                                   capture_output=True, text=True, timeout=15)
            return hasil.returncode == 0
        os.kill(pid, 9)
        return True
    except Exception:
        return False


def hentikan_semua():
    """
    Dipanggil saat bot dihentikan (Ctrl+C / jendela ditutup). Mematikan proses scraper
    yang sedang berjalan supaya tidak jadi yatim, dan meminta Apify berhenti.
    """
    with _LOCK:
        job = _AKTIF
    if not job:
        return
    proses = job.get("_proses")
    pid = job.get("pid")
    if proses is not None or pid:
        if proses is not None:
            try:
                proses.kill()
            except Exception:
                pass
        elif pid:
            _matikan_pid(pid)
        print(f"[JOB] Job {job['id_job']} dihentikan bersama bot (proses scraper dimatikan).")
    jumlah, info = hentikan_run_apify()
    if jumlah:
        print(f"[JOB] {info}")
    job["status"] = DIBATALKAN
    job["catatan"] = "Bot dihentikan saat job ini berjalan; proses scraper dimatikan."
    job["selesai"] = _sekarang()
    _simpan_riwayat(job)


def cari_proses_scraper_lain() -> str:
    """
    Cari proses scraper lain yang mungkin tertinggal dari sesi sebelumnya.

    HANYA untuk peringatan — tidak mematikan apa pun. Tujuannya: kalau bot terasa
    lambat, penyebabnya langsung terlihat, bukan ditebak-tebak. Bot ini hanya menjalankan
    SATU scraper sekaligus, jadi jumlah lebih dari satu selalu mencurigakan.
    """
    try:
        if os.name == "nt":
            hasil = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
                                   capture_output=True, text=True, timeout=15)
            jumlah = hasil.stdout.count('"python.exe"')
            rincian = "python.exe"
        else:
            hasil = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True, timeout=15)
            jumlah = len([b for b in hasil.stdout.splitlines()
                          if "cirebon_media" in b and "main.py" in b])
            rincian = "proses scraper (main.py cirebon_media)"
        if jumlah > 1:
            return (f"[JOB] PERHATIAN: terdeteksi {jumlah} {rincian}. Bot ini hanya menjalankan satu "
                    "scraper sekaligus, jadi kemungkinan ada proses tertinggal dari sesi sebelumnya.\n"
                    "[JOB] Proses tertinggal membuat pekerjaan baru terasa lebih lambat karena "
                    "berebut sumber daya komputer yang sama.\n"
                    "[JOB] Solusi: tutup proses itu lewat Task Manager (tab Details, cari python.exe), "
                    "atau jalankan: taskkill /F /IM python.exe (ingat: ini mematikan SEMUA python).")
    except Exception:
        pass
    return ""


# ============================================================
# API UNTUK menu_bot & main_bot
# ============================================================
def status_ringkas() -> str:
    with _LOCK:
        if _AKTIF:
            lewat = _durasi(time.time() - _AKTIF.get("_mulai_epoch", time.time()))
            aktif = f"sedang berjalan (sudah {lewat})"
        else:
            aktif = "tidak ada"
        antre = f"{len(_ANTREAN)} menunggu" if _ANTREAN else "kosong"
        return f"Antrean: {antre} | Pekerjaan: {aktif}"


def daftar_antrean() -> list:
    with _LOCK:
        return [dict(job) for job in _ANTREAN]


def job_aktif_untuk(user_id) -> bool:
    """Cek apakah user ini sedang punya job berjalan/menunggu (batas 1 job per orang)."""
    with _LOCK:
        if _AKTIF and _AKTIF["user_id"] == user_id:
            return True
        return any(job["user_id"] == user_id for job in _ANTREAN)


def jalankan_job(sesi: dict, argv: list, chat_id, user_id, nama: str = ""):
    """
    Titik masuk dari menu_bot (tombol MULAI).

    Fungsi ini CEPAT selesai: ia hanya memasukkan job ke antrean lalu menyuruh
    pekerja (worker) bekerja di latar belakang. Kalau ia ikut menunggu proses
    scraper 20 menit, seluruh bot akan membeku dan user lain tidak dilayani.
    """
    global _NOMOR, _WORKER_JALAN

    with _LOCK:
        if job_aktif_untuk(user_id):
            PENGIRIM.kirim_pesan(
                chat_id,
                "Anda masih punya job yang sedang berjalan/menunggu. "
                "Tunggu sampai selesai dulu, ya — atau tekan 'Batalkan job' di pesan progresnya.",
            )
            return
        if len(_ANTREAN) >= cfg.MAKS_JOB_ANTREAN:
            PENGIRIM.kirim_pesan(
                chat_id,
                f"Antrean sedang penuh ({len(_ANTREAN)} job menunggu, batas {cfg.MAKS_JOB_ANTREAN}). "
                "Coba lagi beberapa menit lagi.",
            )
            return

        _NOMOR += 1
        job = {
            "id_job": f"job{_NOMOR:03d}",
            "user_id": user_id,
            "chat_id": chat_id,
            "nama": nama,
            "argv": list(argv),
            "sesi": {
                **dict(sesi),
                "kirim_log": sesi.get("kirim_log", cfg.KIRIM_LOG_KE_TELEGRAM),
            },
            "status": MENUNGGU,
            "dibuat": _sekarang(),
            "mulai": "",
            "selesai": "",
            "biaya_usd": 0.0,
            "berkas": [],
            "_dibatalkan": False,
            "_aktivitas": "menunggu giliran",
        }
        _ANTREAN.append(job)
        posisi = len(_ANTREAN)
        perlu_mulai_worker = not _WORKER_JALAN
        _WORKER_JALAN = True

    _catat_jejak(_semua_job_snapshot())

    ringkas = _teks_permintaan(job)
    if perlu_mulai_worker:
        PENGIRIM.kirim_pesan(
            chat_id,
            f"\u2705 Permintaan <b>diterima</b>!\n\n"
            f"{tg.esc(ringkas)}\n\n"
            "Pemantauan akan segera dimulai. Kabar berkala dikirim otomatis "
            "sampai selesai \u2014 Anda tidak perlu menunggu di sini. \U0001f60a",
        )
    else:
        PENGIRIM.kirim_pesan(
            chat_id,
            f"\u2705 Permintaan <b>diterima</b> (antrean posisi {posisi}).\n\n"
            f"{tg.esc(ringkas)}\n\n"
            "<i>Ada pekerjaan lain yang sedang berjalan. Permintaan Anda akan dimulai setelahnya.</i>",
        )

    if perlu_mulai_worker:
        threading.Thread(target=_worker, name="worker-job", daemon=True).start()


def hentikan_run_apify() -> tuple:
    """
    Minta APIFY menghentikan run yang sedang berjalan (bukan cuma mematikan proses lokal).

    KENAPA PENTING: kalau proses python lokal dimatikan tanpa ini, run Apify tetap
    lanjut di server mereka dan tetap ditagih meski hasilnya tidak kita ambil.
    run_id dibaca dari catatan yang ditulis modul scraper (history/apify_run_aktif.json).

    Returns: (jumlah_dihentikan, pesan_untuk_user)
    """
    import urllib.error
    import urllib.request

    path = cfg.FOLDER_HISTORY / "apify_run_aktif.json"
    if not path.exists():
        return 0, "Tidak ada permintaan Apify tercatat yang sedang berjalan."
    try:
        isi = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0, "Catatan run Apify tidak terbaca; permintaan di server mungkin masih berjalan."

    if not isinstance(isi, list) or not isi:
        return 0, "Tidak ada permintaan Apify tercatat yang sedang berjalan."

    token = cfg.ambil_apify_token()
    if not token:
        return 0, (f"{len(isi)} permintaan Apify mungkin masih berjalan di server, "
                   "tetapi token Apify tidak ditemukan untuk menghentikannya.")

    berhasil, gagal = 0, []
    for entri in isi:
        run_id = str(entri.get("run_id") or "")
        if not run_id:
            continue
        url = f"https://api.apify.com/v2/actor-runs/{run_id}/abort"
        permintaan = urllib.request.Request(
            url, data=b"{}", method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        try:
            with urllib.request.urlopen(permintaan, timeout=20) as jawaban:
                if jawaban.status == 200:
                    berhasil += 1
        except Exception as galat:
            gagal.append(f"{run_id} ({galat})")

    # Catatan dibersihkan apa pun hasilnya supaya tidak dibatalkan berulang.
    try:
        path.write_text("[]", encoding="utf-8")
    except Exception:
        pass

    print(f"[JOB] Pembatalan Apify: {berhasil} run dihentikan, {len(gagal)} gagal.")
    if gagal:
        return berhasil, (f"{berhasil} run Apify dihentikan, {len(gagal)} gagal dihentikan "
                          "(run yang gagal itu mungkin masih lanjut di server Apify).")
    return berhasil, f"{berhasil} run Apify sudah dihentikan di sisi server."


def batalkan_job(id_job: str, user_id=None) -> tuple:
    """
    Batalkan job. Yang sedang berjalan: proses lokal dimatikan DAN run Apify-nya
    diminta berhenti di server. Yang masih menunggu: dikeluarkan dari antrean.
    Returns: (berhasil, pesan)
    """
    def _boleh(job) -> bool:
        if not user_id:
            return True
        return job["user_id"] == user_id or user_id in cfg.ADMIN_USER_IDS

    # ---- 1. Job yang sedang berjalan ----
    sedang_berjalan = False
    with _LOCK:
        if _AKTIF and _AKTIF["id_job"] == id_job:
            if not _boleh(_AKTIF):
                return False, "Job itu milik pengguna lain."
            _AKTIF["_dibatalkan"] = True
            proses = _AKTIF.get("_proses")
            if proses is not None:
                try:
                    proses.kill()
                except Exception:
                    pass
            sedang_berjalan = True

    # Panggilan jaringan ke Apify dilakukan DI LUAR kunci supaya bot tidak membeku
    # kalau jaringan lambat (bisa sampai 20 detik).
    if sedang_berjalan:
        _, info_apify = hentikan_run_apify()
        return True, f"Job {id_job} sedang dihentikan. {info_apify}"

    # ---- 2. Job yang masih menunggu di antrean ----
    with _LOCK:
        for posisi, job in enumerate(_ANTREAN):
            if job["id_job"] == id_job:
                if not _boleh(job):
                    return False, "Job itu milik pengguna lain."
                _ANTREAN.pop(posisi)
                job["status"] = DIBATALKAN
                job["catatan"] = "Dibatalkan pengguna sebelum mulai."
                job["selesai"] = _sekarang()
                _simpan_riwayat(job)
                # Beri tahu tetap dikirim supaya user tidak menunggu kabar yang tak akan datang.
                PENGIRIM.kirim_pesan(
                    job["chat_id"],
                    f"Job {id_job} DIBATALKAN sebelum mulai. Tidak ada biaya yang keluar "
                    "karena permintaan tidak pernah dikirim ke Apify.",
                )
                return True, f"Job {id_job} dibatalkan (belum sempat jalan)."

    return False, "Job itu sudah tidak ada di antrean."


def _teks_permintaan(job: dict) -> str:
    sesi = job.get("sesi") or {}
    if sesi.get("target_jenis") in ("tiktok", "facebook"):
        nama_plat = "Facebook" if sesi.get("target_jenis") == "facebook" else "TikTok"
        topik = sesi.get("facebook_topik") if sesi.get("target_jenis") == "facebook" else sesi.get("tiktok_topik")
        return (
            f"Isu {nama_plat}: {topik or '-'} • {sesi.get('hari', 30)} hari • "
            f"komentar: {'ya' if sesi.get('komentar', True) else 'tidak'}"
        )
    jumlah_akun = len(sesi.get('akun') or [])
    return (
        f"{jumlah_akun} akun \u2022 {sesi.get('hari', '?')} hari \u2022 "
        f"maks {sesi.get('maks_post', '?')} post/akun \u2022 "
        f"komentar: {'ya' if sesi.get('komentar') else 'tidak'}"
    )


def _semua_job_snapshot() -> list:
    """
    Salinan job untuk ditulis ke berkas jejak.
    Kunci internal (diawali '_') DIBUANG karena isinya bukan JSON: misalnya
    obyek proses (Popen) dan penanda henti (threading.Event). Kalau ikut disimpan,
    penulisan berkas gagal di tengah job.
    """
    with _LOCK:
        semua = _ANTREAN + ([_AKTIF] if _AKTIF else [])
        return [{k: v for k, v in job.items() if not k.startswith("_")} for job in semua]


def _pecah_teks(teks: str, maks: int = None) -> list:
    """Pecah teks panjang jadi beberapa pesan, dipotong di batas baris (tanpa library luar)."""
    maks = maks or cfg.PANJANG_TELEGRAM
    if len(teks) <= maks:
        return [teks]

    bagian, sedang = [], ""
    for baris in teks.splitlines(keepends=True):
        if len(baris) > maks:                 # satu baris kelewat panjang -> potong paksa
            if sedang:
                bagian.append(sedang)
                sedang = ""
            for i in range(0, len(baris), maks):
                bagian.append(baris[i:i + maks])
            continue
        if len(sedang) + len(baris) > maks:
            bagian.append(sedang)
            sedang = baris
        else:
            sedang += baris
    if sedang:
        bagian.append(sedang)
    return bagian or [teks[:maks]]


# ============================================================
# PENYARING BARIS LOG (permintaan user 22 Sep 2026)
# ============================================================
# Keluhan user: "semua keluaran terlihat itu bagus, tapi keluaran user tidak rapih
# dan membingungkan". Penjelasannya: dari 70 pesan LOG pada job001, mayoritas cuma
# mengulang baris "Status: RUNNING (6 detik)" yang SUDAH ditampilkan di pesan
# progres, ditambah potongan dokumen HTML galat 524 yang bikin panik tanpa sebab.
#
# Prinsip penyaringan: yang dibuang HANYA baris yang tidak menambah informasi.
#   (a) sudah diwakili pesan progres (baris polling),
#   (b) sampah mesin (potongan HTML, semboyan unduhan model),
#   (c) sekadar garis hiasan / baris kosong.
# Baris galat TIDAK disembunyikan — hanya diubah bentuknya jadi kalimat yang bisa
# dipahami (lihat _RAPIKAN).
_LEWATI_LOG = (
    re.compile(r"^[=\-!]{6,}$"),                       # garis pemisah === / --- / !!!
    re.compile(r"^$"),                                 # baris kosong
    re.compile(r"^<"),                                 # potongan dokumen HTML galat
    re.compile(r"^⏳.*Status(?: Komentar)?:\s*(RUNNING|READY|SUCCEEDED|FAILED|ABORTED|TIMING-OUT)", re.I),
    re.compile(r"^Warning: You are sending unauthenticated requests", re.I),
    re.compile(r"^Loading weights:"),
    # Catatan internal scraper: berguna bagi mesin, tidak berguna bagi pegawai.
    # Semuanya tetap UTUH di berkas arsip log mentah.
    re.compile(r"^📝 Riwayat "),
    # Alamat berkas di komputer. Berkasnya SENDIRI dikirim ke chat, jadi jalur panjang
    # ini hanya jadi gangguan. Tetap utuh di arsip.
    re.compile(r"^-\s*(CSV|JSON)\s*:"),
    re.compile(r"^Folder Post Output\s*:"),
    re.compile(r"^Log History Post\s*:"),
    # Baris biaya — tidak ditampilkan ke user (permintaan revisi).
    re.compile(r"^💰 Biaya "),
)

# Banyak baris scraper isinya BENAR tapi bahasanya teknis: nomor Run Apify, potongan
# kunci API, istilah batch/pekerja/key, nama model, dan campuran istilah Inggris.
# Semuanya DITERJEMAHKAN ke bahasa manusia, BUKAN dihapus — informasinya tetap ada,
# hanya bentuknya yang ramah dibaca pegawai. Berkas arsip log mentah tetap memuat
# teks aslinya apa adanya.
#
# >>> INI SATU-SATUNYA TEMPAT MENGUBAH GAYA BAHASA CATATAN PROSES. <<<
# Kalau ada kalimat yang kurang pas untuk keperluan pemerintahan, cukup ubah di sini.
# Aturan dijalankan BERURUTAN dari atas ke bawah; taruh aturan yang lebih khusus dulu.
_RAPIKAN = (
    # --- 1. Kegagalan jaringan umum (jaring pengaman) ---
    # Dulu di sini ada aturan khusus kegagalan "batch" dari server LLM. Tahap itu sudah
    # dilepas, jadi aturannya dihapus. Yang tinggal hanya jaring pengaman supaya galat
    # berbentuk HTTP tetap terbaca sebagai kalimat manusia, bukan potongan HTML.
    (re.compile(r"HTTP\s*(\d{3})\s*:.*$", re.S),
     r"HTTP \1 (server tidak menjawab dalam batas waktu) — dicoba ulang otomatis."),

    # --- 2. Sisa label/istilah teknis ---
    (re.compile(r"ℹ️ Task Apify( Komentar)? berjalan \(Run ID: [^)]+\)"),
     "ℹ️ Permintaan sudah diterima Apify — data sedang diambil."),
    (re.compile(r"\s*\(sk-[^)]*\)"), ""),          # potongan kunci API: jangan tampil

    # --- 3. Nama model pembaca komentar (IndoBERT, model lokal — BUKAN layanan LLM) ---
    (re.compile(r"\[INFO\] Memuat model AI IndoBERTweet \(.*?\)\.\.\."),
     "ℹ️ Menyiapkan alat pembaca komentar — perlu waktu ±40 detik..."),
    (re.compile(r"\[SUCCESS\] Model AI IndoBERTweet Berhasil Dimuat!"),
     "✅ Alat pembaca komentar siap."),
    (re.compile(r"\[AI\] Menjalankan Analisis Sentimen IndoBERTweet \((\d+) komentar\)\.\.\."),
     r"🔍 Membaca & menggolongkan \1 komentar..."),

    # --- 4. Judul blok supaya enak dibaca di ponsel ---
    (re.compile(r"^\[(\d+)/(\d+)\] Memproses Post: (.+?) \(@(.+?)\)$"),
     r"▶ Akun \1 dari \2: \3 (@\4)"),
    (re.compile(r"^Memproses Komentar Video: .+?\(@(.+?)\) - (\d+) video$"),
     r"▶ Mengambil komentar: \1 — \2 postingan teratas"),
    (re.compile(r"^RINGKASAN TAHAP SCRAPING POSTINGAN$"), "RINGKASAN POSTINGAN"),
    (re.compile(r"^MEMULAI SCRAPING KOMENTAR$"), "MEMULAI PENGAMBILAN KOMENTAR"),
    (re.compile(r"^ALERT INTERAKTIF$"), "POSTINGAN TERPILIH"),
    (re.compile(r"^Berhasil mengidentifikasi (\d+) postingan \(semua tipe post\) dengan komentar terbanyak:"),
     r"Terdapat \1 postingan dengan komentar terbanyak:"),

    # --- 5. Baris hasil: istilah Inggris/teknis diganti ---
    (re.compile(r"^✅ Token Apify Valid!$"), "✅ Koneksi ke Apify berhasil."),
    (re.compile(r"^✅ Data mentah berhasil diambil: (\d+) postingan\.$"),
     r"✅ \1 postingan berhasil diambil dari Apify."),
    (re.compile(r"^✅ Data mentah komentar berhasil diambil: (\d+) komentar\.$"),
     r"✅ \1 komentar berhasil diambil dari Apify."),
    (re.compile(r"^✨ Sukses Filter & Simpan Post!$"), "✨ Postingan berhasil disaring & disimpan."),
    (re.compile(r"^✨ Sukses Simpan & Evaluasi Komentar!$"), "✨ Komentar berhasil disimpan & dinilai."),
    (re.compile(r"^-\s*Data Mentah Apify\s*:\s*(\d+) post$"), r"• Ditarik dari Apify: \1 postingan"),
    (re.compile(r"^-\s*Lolos Filter \('([^']+)'\):\s*(\d+) post$"),
     r"• Lolos penyaringan '\1': \2 postingan"),
    (re.compile(r"^-\s*Top Video Komentar Terbanyak\s*:\s*(\d+) video$"),
     r"• Postingan terpilih untuk diambil komentarnya: \1"),
    (re.compile(r"^-\s*Komentar Fetched\s*:\s*(\d+)$"), r"• Komentar diambil: \1"),
    (re.compile(r"^-\s*Komentar Saved\s*:\s*(\d+)$"), r"• Komentar disimpan: \1"),
    (re.compile(r"^-\s*Sentimen IndoBERTweet \(label mesin\):$"), "• Hasil sentimen:"),
    (re.compile(r"^-\s*Sentimen IndoBERTweet:$"), "• Hasil sentimen:"),
    # (Aturan "Penilaian Sentimen oleh AI (...)" dan "Penanda Tindak Lanjut (LLM)"
    #  sudah DIHAPUS 24 Sep 2026 — tahap penilaian LLM tidak lagi dijalankan.)
    (re.compile(r"^\s*\* POSITIF\s*:"), "   POSITIF:"),
    (re.compile(r"^\s*\* NEGATIF\s*:"), "   NEGATIF:"),
    (re.compile(r"^\s*\* NETRAL\s*:"), "   NETRAL:"),
    # (Aturan untuk baris hasil penilaian LLM — "AI POSITIF/NEGATIF/NETRAL",
    #  "AI berbeda dari IndoBERT", "BUTUH REVIEW", "TIDAK PERLU" — sudah DIHAPUS
    #  karena tahap itu tidak lagi dijalankan.)
    (re.compile(r"^(\d+)\.\s*\[(\w+)\]\s*Post ID:\s*\S+\s*\|\s*Comments:\s*(\d+)\s*\|\s*Likes:\s*(\d+)$"),
     r"\1. [\2] Komentar: \3 | Suka: \4"),

    # --- 6. Ringkasan tahap postingan ---
    (re.compile(r"^Total Akun Diproses\s*:"), " Total akun diproses :"),
    (re.compile(r"^Akun Sukses\s*:"), " Akun berhasil       :"),
    (re.compile(r"^Akun Gagal\s*:"), " Akun gagal          :"),
    (re.compile(r"^Total Post Saved\s*:\s*(\d+) post \(memuat '([^']+)'\)$"),
     r" Total postingan tersimpan: \1 (memuat '\2')"),
)


def _rapikan_baris_log(baris: str):
    """
    Rapikan satu baris keluaran scraper sebelum dikirim ke Telegram.

    Returns: teks yang layak dikirim, atau None kalau baris itu memang tidak
    menambah informasi apa pun (lihat penjelasan _LEWATI_LOG di atas).
    """
    teks = (baris or "").strip()
    if not teks:
        return None
    for pola in _LEWATI_LOG:
        if pola.search(teks):
            return None
    for pola, ganti in _RAPIKAN:
        teks = pola.sub(ganti, teks)
    return teks.strip() or None


# ============================================================
# ARSIP LOG MENTAH (permintaan user 22 Sep 2026, pilihan "4a")
# ============================================================
# Chat hanya memuat baris log yang menambah informasi (lihat _LEWATI_LOG). Supaya
# TIDAK ADA data yang benar-benar hilang, SEMUA baris keluaran scraper tetap ditulis
# APA ADANYA ke berkas instagram/bot/log/log_<job>_<waktu>.txt, lalu berkas itu
# dikirim ke chat di akhir job. Jadi: chat rapi, pemeriksaan menyeluruh tetap mungkin.
#
# Berkas ditulis baris demi baris (bukan ditahan di memori) supaya isinya tetap ada
# walau bot dimatikan di tengah job. Kegagalan menulis arsip TIDAK PERNAH menghentikan
# job — arsip itu pelengkap, bukan syarat berjalannya proses.
def _buka_arsip_log(job: dict):
    """Buka berkas arsip log mentah untuk satu job. Returns: (path, pegangan)."""
    try:
        cfg.FOLDER_LOG.mkdir(parents=True, exist_ok=True)
        stempel = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = cfg.FOLDER_LOG / f"log_{job['id_job']}_{stempel}.txt"
        pegangan = open(path, "w", encoding="utf-8", errors="replace")
        pegangan.write("# " + "=" * 72 + "\n")
        pegangan.write(f"# LOG MENTAH {job['id_job']} — SCRAPER INSTAGRAM MEDIA KOTA CIREBON\n")
        pegangan.write("# " + "=" * 72 + "\n")
        pegangan.write(f"# {_teks_permintaan(job)}\n")
        pegangan.write(f"# Mulai       : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (waktu komputer)\n")
        pegangan.write(f"# Perintah    : {' '.join(job.get('_perintah') or [])}\n")
        pegangan.write("# Catatan     : berisi SEMUA baris keluaran scraper APA ADANYA, termasuk\n")
        pegangan.write("#               baris yang TIDAK dikirim ke chat (baris polling, garis\n")
        pegangan.write("#               hiasan, sisa dokumen HTML galat). Gunakan berkas ini bila\n")
        pegangan.write("#               perlu memeriksa proses secara menyeluruh.\n")
        pegangan.write("# " + "-" * 72 + "\n")
        pegangan.flush()
        return path, pegangan
    except Exception as galat:
        print(f"[JOB] Gagal membuat arsip log mentah: {galat}")
        return None, None


def _catat_baris_arsip(job: dict, baris: str):
    """Tulis satu baris keluaran scraper APA ADANYA ke berkas arsip (tanpa disaring)."""
    pegangan = job.get("_arsip_pegangan")
    if pegangan is None or pegangan.closed:
        return
    if (job.get("_arsip_jumlah") or 0) >= MAKS_BARIS_ARSIP_LOG:
        return
    try:
        pegangan.write(baris + "\n")
        job["_arsip_jumlah"] = (job.get("_arsip_jumlah") or 0) + 1
    except Exception:
        pass                    # arsip gagal ditulis bukan alasan menghentikan job


def _tutup_arsip_log(job: dict, kode=None):
    """Tutup berkas arsip log mentah. Aman dipanggil berkali-kali (penutupan ganda diabaikan)."""
    pegangan = job.get("_arsip_pegangan")
    if pegangan is None:
        return
    job["_arsip_pegangan"] = None
    if pegangan.closed:
        return
    try:
        jumlah = job.get("_arsip_jumlah") or 0
        pegangan.write("# " + "-" * 72 + "\n")
        pegangan.write(f"# Selesai      : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        pegangan.write(f"# Kode keluar scraper : {kode if kode is not None else 'tidak diketahui'}\n")
        pegangan.write(f"# Jumlah baris tercatat: {jumlah}\n")
        if jumlah >= MAKS_BARIS_ARSIP_LOG:
            pegangan.write(f"# CATATAN: arsip dipotong di {MAKS_BARIS_ARSIP_LOG} baris.\n")
    except Exception as galat:
        print(f"[JOB] Gagal menulis penutup arsip log: {galat}")
    try:
        pegangan.close()
    except Exception:
        pass


def _alirkan_log(job: dict, baris: str):
    """
    Tampilkan keluaran scraper ke user, dengan dua cara yang bisa dipilih:

    A. MODE SATU PESAN (bawaan, cfg.LOG_SATU_PESAN) — permintaan user 22 Sep 2026.
       Keluaran scraper TIDAK dikirim sebagai pesan terpisah (dulu bisa 70 pesan = spam).
       Beberapa baris terakhir ditampilkan DI DALAM pesan progres yang diperbarui
       terus-menerus. Jadi user tetap melihat prosesnya bergerak, tanpa chat dibanjiri.
       Seluruh isi tetap tersimpan di berkas log mentah yang dikirim di akhir job.

    B. MODE PESAN TERPISAH (cfg.LOG_SATU_PESAN = False) — cara lama: tiap kelompok baris
       menjadi pesan sendiri, dengan jeda LOG_INTERVAL_DETIK detik.
    """
    if not job.get("sesi", {}).get("kirim_log", True):
        return

    teks = _rapikan_baris_log(baris)
    if teks is None:
        return                       # baris ini tidak menambah informasi -> buang

    # ---------- A. MODE SATU PESAN ----------
    if cfg.LOG_SATU_PESAN:
        tail = job.setdefault("_log_tail", deque(maxlen=cfg.LOG_TAIL_BARIS))
        tail.append(teks[:cfg.LOG_PANJANG_BARIS])
        sekarang = time.time()
        penting = any(tanda in teks for tanda in ("❌", "⚠️", "TOTAL SELESAI"))
        if penting or sekarang - job.get("_log_terakhir", 0) >= cfg.LOG_INTERVAL_DETIK:
            job["_log_terakhir"] = sekarang
            _kirim_progres(job, paksa=True)     # EDIT pesan yang sama, bukan kirim baru
        return

    # ---------- B. MODE PESAN TERPISAH ----------
    if job.get("_log_pesan_terkirim", 0) >= cfg.LOG_MAKS_PESAN_PER_JOB:
        return

    pending = job.setdefault("_log_pending", [])
    pending.append(teks[:300])

    penting = any(tanda in teks for tanda in ("❌", "⚠️", "✨", "💰", "⏱", "TOTAL SELESAI", "ROTASI"))
    sekarang = time.time()
    cukup_jeda = sekarang - job.get("_log_terakhir", 0) >= cfg.LOG_INTERVAL_DETIK
    cukup_banyak = len(pending) >= cfg.LOG_MAKS_BARIS_PER_PESAN

    if not (penting or cukup_jeda or cukup_banyak):
        return
    if sekarang - job.get("_log_terakhir", 0) < cfg.LOG_JEDA_MINIMAL_DETIK and not cukup_banyak:
        return                       # terlalu cepat; biarkan menumpuk dulu
    _kirim_log_sekarang(job)


def _kirim_log_sekarang(job: dict):
    """Kirim isi log yang menumpuk sekarang juga (dipakai juga saat job berakhir)."""
    if cfg.LOG_SATU_PESAN:
        return          # mode satu pesan: tidak ada pesan log terpisah yang perlu dikirim
    pending = job.get("_log_pending") or []
    if not pending:
        return
    blok = "\n".join(pending)
    job["_log_pending"] = []
    job["_log_terakhir"] = time.time()
    job["_log_pesan_terkirim"] = job.get("_log_pesan_terkirim", 0) + 1
    nomor = job["_log_pesan_terkirim"]
    lewat = _durasi(time.time() - job.get("_mulai_epoch", time.time()))
    # Judul diberi TAHAP supaya user tahu catatan ini sedang bicara soal bagian mana.
    # Bahasa "LOG #7" diganti "CATATAN PROSES #7" karena ini dipakai pegawai pemerintahan.
    judul_log = f"📋 CATATAN PROSES {job['id_job']} #{nomor} — {lewat}"
    tahap = job.get("_aktivitas")
    if tahap:
        judul_log += f"\n     Tahap: {tahap}"
    judul_log += "\n"
    for potongan in _pecah_teks(judul_log + blok):
        try:
            PENGIRIM.kirim_pesan(job["chat_id"], potongan)
        except Exception as galat:
            print(f"[JOB] Gagal mengirim log: {galat}")
            return


# ============================================================
# PEKERJA (WORKER)
# ============================================================
def _worker():
    global _AKTIF, _WORKER_JALAN
    while True:
        with _LOCK:
            if not _ANTREAN:
                _WORKER_JALAN = False
                return
            _AKTIF = _ANTREAN.pop(0)
            job = _AKTIF
            job["status"] = BERJALAN
            job["mulai"] = _sekarang()

        _catat_jejak(_semua_job_snapshot())
        try:
            _kerjakan(job)
        except Exception as galat:
            job["status"] = GAGAL
            job["catatan"] = f"Kesalahan tak terduga di mesin job: {galat}"
            PENGIRIM.kirim_pesan(job["chat_id"], f"Job {job['id_job']} GAGAL: {galat}")
        finally:
            job["selesai"] = _sekarang()
            _hentikan_detak(job)
            # Jaring pengaman: kalau terjadi kesalahan tak terduga, berkas arsip log
            # tetap ditutup rapi supaya isinya tidak hilang setengah jalan.
            _tutup_arsip_log(job)
            _simpan_riwayat(job)
            with _LOCK:
                _AKTIF = None
            _catat_jejak(_semua_job_snapshot())


def _simpan_riwayat(job: dict):
    riwayat = _muat_json(PATH_RIWAYAT, [])
    if not isinstance(riwayat, list):
        riwayat = []
    bersih = {k: v for k, v in job.items() if not k.startswith("_")}
    riwayat.append(bersih)
    _simpan_json(PATH_RIWAYAT, riwayat[-200:])     # simpan 200 terakhir saja


# ============================================================
# DETAK PROGRES (bagian yang menjawab keluhan "tidak ada kabar")
# ============================================================
def _blok_catatan_proses(job: dict, panjang_terpakai: int, sisa_untuk_penutup: int = 300) -> list:
    """
    Susun blok "catatan proses terakhir" untuk pesan progres (mode satu pesan).

    Isinya: beberapa baris TERAKHIR keluaran scraper. Kalau kepanjangan (Telegram hanya
    menerima 4096 karakter per pesan), baris yang paling lama dibuang lebih dulu — jadi
    yang selalu terlihat adalah keadaan paling baru. Isi lengkapnya selalu tersedia di
    berkas log mentah yang dikirim di akhir job.

    Returns: daftar baris siap tempel; kosong kalau memang tidak ada yang ditampilkan.
    """
    if not cfg.LOG_SATU_PESAN:
        return []
    if not job.get("sesi", {}).get("kirim_log", True):
        return []
    tail = list(job.get("_log_tail") or [])
    if not tail:
        return []

    batas = cfg.PANJANG_TELEGRAM - panjang_terpakai - sisa_untuk_penutup
    if batas < 120:
        return []
    judul = (f"Catatan proses terakhir ({len(tail)} baris terakhir; lengkapnya ada di "
             f"berkas log yang dikirim setelah job selesai):")
    terpilih, panjang = [], len(judul) + 1
    for satu in reversed(tail):
        teks = "  " + satu
        if terpilih and panjang + len(teks) + 1 > batas:
            break
        terpilih.insert(0, teks)
        panjang += len(teks) + 1
    if not terpilih:
        return []
    return ["", judul] + terpilih


def _perkiraan_langkah(aktivitas: str) -> str:
    """
    Kalimat perkiraan lama satu langkah. Gunanya: memberi ukuran kepada user.
    """
    teks = (aktivitas or "").lower()
    # PENTING: jangan menulis kata "biasanya" di dalam fungsi ini. Kata itu sudah ada
    # di kalimat pemanggilnya ("langkah ini biasanya ..."). Pada 24 Sep 2026 keduanya
    # bertemu sehingga layar pegawai menampilkan "biasanya biasanya mulai dalam
    # beberapa detik" — salah satu dari sedikit kekurangan yang terlihat pengguna.
    if "analisis sentimen" in teks or "membaca" in teks or "menggolongkan" in teks:
        # Pembacaan komentar memakai model lokal: sekali muat model, lalu cepat.
        return f"selesai dalam ±{cfg.format_durasi(cfg.DETIK_MUAT_MODEL + 60)}"
    if "menarik komentar" in teks or "mengambil komentar" in teks:
        return "selesai dalam ±30 detik"
    if "apify" in teks or "internet" in teks:
        return "selesai dalam ±1 menit 30 detik"
    if "memproses akun" in teks or "mengerjakan akun" in teks:
        return "selesai dalam ±1 menit 30 detik"
    if "menyimpan hasil" in teks:
        return "selesai dalam ±10 detik"
    if "menyiapkan" in teks:
        return "mulai dalam beberapa detik"
    return ""


def _ramahkan_aktivitas(aktivitas: str) -> str:
    """Terjemahkan aktivitas teknis menjadi bahasa ramah untuk pegawai."""
    teks = (aktivitas or "").strip()
    teks = re.sub(r'\bApify\b', 'internet', teks, flags=re.I)
    teks = re.sub(r'\bscraper\b', 'pengambil data', teks, flags=re.I)
    teks = re.sub(r'\bscraping\b', 'pengambilan', teks, flags=re.I)
    teks = re.sub(r'\bsentimen\b', 'tanggapan', teks, flags=re.I)
    teks = re.sub(r'\bIndoBERTweet\b', '', teks, flags=re.I)
    teks = re.sub(r'\bIndoBERT\b', '', teks, flags=re.I)
    teks = re.sub(r'\bfilter\b', 'penyaringan', teks, flags=re.I)
    teks = re.sub(r'\bmodel AI\b', 'alat pembaca', teks, flags=re.I)
    teks = re.sub(r'PID \d+', '', teks)
    teks = re.sub(r'\(PID \d+\)', '', teks)
    teks = re.sub(r'\s+', ' ', teks).strip()
    return teks or "memproses..."

def _susun_teks_progres(job: dict) -> str:
    """
    Susun pesan progres: super ringkas, visual, ramah.
    Hanya progress bar, indikator status singkat, dan estimasi waktu selesai.
    """
    lewat_detik = time.time() - job.get("_mulai_epoch", time.time())
    persen = max(1, min(99, int(job.get("_progres_persen", 5))))

    # Progress bar visual (20 blok)
    bar_penuh = persen // 5
    bar_kosong = 20 - bar_penuh
    progress_bar = "▓" * bar_penuh + "░" * bar_kosong

    # Estimasi sisa waktu dinamis
    sesi = job.get("sesi") or {}
    pakai_komentar = sesi.get("komentar", True)
    perkiraan = cfg.hitung_perkiraan_durasi(
        len(sesi.get("akun") or [1]), sesi.get("top", 1),
        pakai_komentar, sesi.get("maks_komentar", 100))
    est_total_detik = max(60, perkiraan.get("total_detik", 180))

    if persen >= 10 and lewat_detik >= 8:
        laju_per_persen = lewat_detik / persen
        sisa_detik = max(5, int((100 - persen) * laju_per_persen))
    else:
        sisa_detik = max(10, est_total_detik - int(lewat_detik))

    if sisa_detik <= 15:
        teks_sisa = "sebentar lagi selesai"
    elif sisa_detik < 60:
        teks_sisa = f"~{sisa_detik} detik lagi"
    else:
        teks_sisa = f"~{_durasi(sisa_detik)} lagi"

    aktivitas = _ramahkan_aktivitas(job.get("_aktivitas") or "menyiapkan pemantauan")

    baris = [
        "📊 <b>Pemantauan Sedang Berjalan</b>",
        "",
        f"{progress_bar} {persen}%",
        "",
        f"📍 <b>Status:</b> {tg.esc(aktivitas)}",
        f"⏱ <b>Perkiraan selesai:</b> {teks_sisa} <i>(berjalan {_durasi(lewat_detik)})</i>",
    ]
    return "\n".join(baris)


def _kirim_progres(job: dict, kejadian: str = None, paksa: bool = False, detak: bool = False):
    """
    Perbarui pesan progres (EDIT, bukan kirim baru).

    - kejadian : kalimat peristiwa baru (mis. "Akun 2/3 selesai") -> dimasukkan ke jejak.
    - paksa    : abaikan pembatasan frekuensi (dipakai untuk peristiwa penting).
    - detak    : pembaruan berkala tanpa peristiwa baru (menjaga user tetap melihat kabar).
    """
    sekarang = time.time()

    if kejadian:
        daftar = job.setdefault("_kejadian", [])
        daftar.append(kejadian[:110])
        job["_kejadian"] = daftar[-MAKS_KEJADIAN:]
        paksa = True                      # peristiwa nyata selalu dikirim

    if detak and not paksa:
        if sekarang - job.get("_terakhir_detak", 0) < DETAK_DETIK:
            return
        job["_terakhir_detak"] = sekarang
    elif not paksa:
        if sekarang - job.get("_terakhir_kirim", 0) < 5:
            return

    teks = _susun_teks_progres(job)[:cfg.PANJANG_TELEGRAM]
    if teks == job.get("_teks_terakhir"):
        return                            # tidak ada perubahan -> tidak perlu edit
    job["_teks_terakhir"] = teks

    if job.get("_jumlah_progres", 0) >= cfg.MAKS_PESAN_PROGRES and not paksa:
        return
    job["_jumlah_progres"] = job.get("_jumlah_progres", 0) + 1
    job["_terakhir_kirim"] = sekarang

    # Jejak di konsol juga, supaya orang yang mengawasi jendela bot melihat gerakannya.
    print(f"[JOB {job['id_job']}] {_durasi(sekarang - job.get('_mulai_epoch', sekarang))} | "
          f"{job.get('_aktivitas') or '-'}" + (f" | {kejadian}" if kejadian else ""))

    papan = tg.keyboard([[tg.tombol("\u274c Batalkan", f"j:batalkan:{job['id_job']}")]])
    pesan_id = job.get("_pesan_id")
    if pesan_id:
        hasil = PENGIRIM.edit_pesan(job["chat_id"], pesan_id, teks, papan_tombol=papan)
        if hasil is not None:
            return
    dikirim = PENGIRIM.kirim_pesan(job["chat_id"], teks, papan_tombol=papan)
    if isinstance(dikirim, dict):
        job["_pesan_id"] = dikirim.get("message_id")


def _mulai_detak(job: dict):
    """Jalankan detak di thread terpisah: tiap DETAK_DETIK detik pesan progres diperbarui."""
    henti = threading.Event()
    job["_henti_detak"] = henti

    def loop():
        while not henti.wait(DETAK_DETIK):
            try:
                _kirim_progres(job, detak=True)
            except Exception as galat:
                print(f"[JOB] Gagal memperbarui progres: {galat}")

    threading.Thread(target=loop, name=f"detak-{job['id_job']}", daemon=True).start()


def _hentikan_detak(job: dict):
    henti = job.get("_henti_detak")
    if henti is not None:
        henti.set()


# ============================================================
# PELAKSANAAN SATU JOB
# ============================================================
def _kerjakan(job: dict):
    """Jalankan scraper, pantau keluarannya, kirim ringkasan + berkas."""
    job["_mulai_epoch"] = time.time()
    job["_kejadian"] = ["Permintaan Anda mulai diproses."]
    job["_aktivitas"] = "menyiapkan pengambilan data"
    _kirim_progres_awal(job)
    _mulai_detak(job)

    # argv yang disusun menu_bot berbentuk: [skrip, "--akun", "...", "--hari", "7", ...]
    # Elemen pertama diganti dengan skrip dari setelan (satu sumber kebenaran),
    # sisanya diteruskan apa adanya. Alamat diterjemahkan ke gaya Windows bila perlu.
    argumen = [str(a) for a in job["argv"][1:]]
    skrip_asal = str(job["argv"][0]) if job.get("argv") else str(cfg.SKRIP_SCRAPER)
    
    target_jenis = job.get("sesi", {}).get("target_jenis")
    if target_jenis == "facebook":
        skrip_target = cfg.SKRIP_SCRAPER_FACEBOOK
        folder_cwd = cfg.FOLDER_FACEBOOK_CODE
    elif target_jenis == "tiktok":
        skrip_target = cfg.SKRIP_SCRAPER_TIKTOK
        folder_cwd = cfg.FOLDER_TIKTOK_CODE
    elif target_jenis == "opd":
        skrip_target = cfg.SKRIP_SCRAPER_OPD
        folder_cwd = cfg.FOLDER_OPD_CODE
    elif "facebook" in Path(skrip_asal).parts or "facebook" in Path(skrip_asal).as_posix().split("/"):
        skrip_target = cfg.SKRIP_SCRAPER_FACEBOOK
        folder_cwd = cfg.FOLDER_FACEBOOK_CODE
    elif "tiktok" in Path(skrip_asal).parts or "tiktok" in Path(skrip_asal).as_posix().split("/"):
        skrip_target = cfg.SKRIP_SCRAPER_TIKTOK
        folder_cwd = cfg.FOLDER_TIKTOK_CODE
    elif "cirebon_opd" in Path(skrip_asal).as_posix():
        skrip_target = cfg.SKRIP_SCRAPER_OPD
        folder_cwd = cfg.FOLDER_OPD_CODE
    else:
        skrip_target = cfg.SKRIP_SCRAPER
        folder_cwd = cfg.FOLDER_IG_CODE

    perintah = [cfg.PYTHON_SCRAPER, "-u", _path_untuk_windows(skrip_target)] + argumen
    job["_perintah"] = list(perintah)

    if os.name == "nt":
        cwd = str(folder_cwd)
    else:
        cwd = _path_untuk_windows(folder_cwd) if str(cfg.PYTHON_SCRAPER).startswith("/mnt/") else str(folder_cwd)

    print("[JOB] Perintah:", " ".join(perintah))

    lingkungan = dict(os.environ)
    lingkungan["PYTHONUTF8"] = "1"
    lingkungan["PYTHONIOENCODING"] = "utf-8"
    # Cadangan kedua untuk masalah buffer (lihat penjelasan "-u" di atas).
    lingkungan["PYTHONUNBUFFERED"] = "1"

    try:
        proses = subprocess.Popen(
            perintah,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=lingkungan,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except Exception as galat:
        job["status"] = GAGAL
        _kirim_progres(job, f"GAGAL memulai scraper: {galat}", paksa=True)
        return

    job["_proses"] = proses
    # PID juga disimpan ke berkas jejak (bukan hanya di memori), supaya kalau bot
    # ditutup dan dijalankan ulang, proses scraper yang tertinggal bisa dimatikan.
    job["pid"] = proses.pid
    _catat_jejak(_semua_job_snapshot())
    _kirim_progres(job, "Pengambilan data dimulai...", paksa=True)

    # Arsip log mentah: SEMUA baris disimpan apa adanya, termasuk yang tidak dikirim
    # ke chat. Dibuka sebelum pembacaan dimulai supaya tidak ada baris yang terlewat.
    path_arsip, pegangan_arsip = _buka_arsip_log(job)
    job["_arsip_pegangan"] = pegangan_arsip
    job["_arsip_jumlah"] = 0
    job["_arsip_path"] = str(path_arsip) if path_arsip else ""

    # PENTING: angka-angka di bawah ini adalah AKUMULASI SELURUH AKUN, bukan nilai
    # akun terakhir. Sebelumnya tiap akun MENIMPA nilai sebelumnya, sehingga ringkasan
    # akhir job001 (22 Sep 2026) melaporkan "Komentar tersimpan: 31" padahal
    # sebenarnya 538, dan "NEGATIF 13" padahal 260. Ringkasan harus jujur.
    hasil = {
        "berkas": [],
        "biaya": 0.0,
        "galat": [],
        "selesai_bersih": False,
        "komentar_saved": 0,
        "akun_komentar": 0,
        "sentimen": {"POSITIF": 0, "NEGATIF": 0, "NETRAL": 0},
        "post_lolos_akun": 0,
        # Rincian PER AKUN (permintaan user 22 Sep 2026): {username: {"mentah":..,
        # "lolos":.., "komentar":..}}. Urutannya mengikuti urutan akun diproses.
        "per_akun": {},
    }
    cuplikan = deque(maxlen=MAKS_BARIS_CUPLIKAN)
    waktu_mulai = time.time()
    job["_waktu_mulai"] = waktu_mulai

    while True:
        if job.get("_dibatalkan"):
            try:
                proses.kill()
            except Exception:
                pass
            break

        baris = proses.stdout.readline() if proses.stdout else ""
        if not baris:
            if proses.poll() is not None:
                break
            if time.time() - waktu_mulai > cfg.TIMEOUT_JOB_DETIK:
                proses.kill()
                job["catatan"] = f"Melewati batas waktu {cfg.TIMEOUT_JOB_DETIK} detik."
                _kirim_progres(job, "DIHENTIKAN: melewati batas waktu.", paksa=True)
                break
            time.sleep(0.2)
            continue

        baris = baris.rstrip("\n")
        # Cuplikan untuk user disaring & dirapikan lebih dulu, supaya saat job gagal atau
        # dibatalkan ringkasannya tidak menampilkan potongan dokumen HTML yang bikin
        # panik. Teks aslinya tetap UTUH di berkas arsip log mentah.
        rapi_cuplikan = _rapikan_baris_log(baris)
        if rapi_cuplikan:
            cuplikan.append(rapi_cuplikan)
        _baca_baris(baris, hasil, job)
        # Setiap baris keluaran scraper juga dialirkan ke Telegram (dikelompokkan),
        # supaya tidak ada bagian proses yang tidak terlihat oleh user.
        _alirkan_log(job, baris)
        # ...dan SETIAP baris (tanpa terkecuali) masuk ke arsip log mentah.
        _catat_baris_arsip(job, baris)

    kode = proses.wait()
    _tutup_arsip_log(job, kode)
    durasi = _durasi(time.time() - waktu_mulai)
    berkas_baru = _kumpulkan_berkas(hasil, waktu_mulai)
    # Kirim sisa log yang belum terkirim sebelum ringkasan, supaya urutannya masuk akal.
    _kirim_log_sekarang(job)

    if job.get("_dibatalkan"):
        job["status"] = DIBATALKAN
        job["catatan"] = "Dibatalkan pengguna saat berjalan."
    elif job["status"] != GAGAL:
        job["status"] = SUKSES if kode == 0 else GAGAL
    if kode != 0 and not hasil["galat"] and job["status"] == GAGAL:
        hasil["galat"].append(f"Proses keluar dengan kode {kode}.")

    job["biaya_usd"] = hasil["biaya"]
    job["berkas"] = [str(b) for b in berkas_baru]

    _kirim_ringkasan(job, hasil, durasi, kode, berkas_baru, list(cuplikan))


def _teks_info_log() -> str:
    """
    Kalimat penjelasan cara kerja aliran log di pesan "job dimulai".

    Dibuat terpisah karena bergantung pada mode (satu pesan vs pesan terpisah) dan harus
    menjelaskan dengan jujur ke mana keluaran scraper pergi.
    """
    if cfg.LOG_SATU_PESAN:
        return (
            "Pesan ini diperbarui terus-menerus (tiap beberapa detik), dan di dalamnya "
            "ditampilkan pula keluaran scraper terbaru — jadi seluruh proses terlihat tanpa "
            "membanjiri chat. Berkas log LENGKAP (semua baris apa adanya) dikirim sebagai "
            "lampiran setelah job selesai. Kirim /logmati bila tidak ingin melihat catatan "
            "prosesnya, lalu /loghidup untuk menyalakan kembali.\n"
        )
    return (
        "Pesan ini akan diperbarui berkala (tiap beberapa detik) dengan aktivitas terbaru, "
        "DAN setiap keluaran scraper dikirim ke chat ini sebagai pesan LOG — jadi seluruh "
        "proses terlihat dari awal sampai akhir. Kalau terlalu ramai, kirim /logmati, dan "
        "/loghidup untuk menyalakannya lagi.\n"
    )


def _kirim_progres_awal(job: dict):
    """Pesan pertama saat job dimulai."""
    sesi = job.get("sesi") or {}
    jumlah_akun = len(sesi.get("akun") or [])
    teks = (
        f"\U0001f680 <b>Pemantauan Dimulai!</b>\n\n"
        f"\U0001f464 {jumlah_akun} akun  \u2022  \U0001f4c5 {sesi.get('hari', 7)} hari  \u2022  "
        f"\U0001f4ac Komentar: {'Ya' if sesi.get('komentar') else 'Tidak'}\n\n"
        "Pesan ini akan diperbarui otomatis. "
        "Anda boleh menutup chat \u2014 laporan dikirim sendiri setelah selesai. \U0001f60a"
    )
    papan = tg.keyboard([[tg.tombol("\u274c Batalkan", f"j:batalkan:{job['id_job']}")]])
    dikirim = PENGIRIM.kirim_pesan(job["chat_id"], teks[:cfg.PANJANG_TELEGRAM], papan_tombol=papan)
    if isinstance(dikirim, dict):
        job["_pesan_id"] = dikirim.get("message_id")
    job["_teks_terakhir"] = teks[:cfg.PANJANG_TELEGRAM]


def _slot_akun(hasil: dict, job: dict):
    """
    Ambil wadah rincian untuk akun yang SEDANG diproses.

    Akun dikenali dari job["_akun_kini"], yang diisi oleh baris "Memproses Post:"
    dan "Memproses Komentar Video:". Kalau penanda itu belum terbaca, kembalikan
    None: angkanya tetap masuk ke TOTAL, hanya rincian per akun yang tidak terisi.
    """
    akun = (job.get("_akun_kini") or "").strip()
    if not akun:
        return None
    return hasil.setdefault("per_akun", {}).setdefault(akun, {})


def _catat_akun(hasil: dict, job: dict, kunci: str, nilai):
    """Simpan satu angka ke rincian akun yang sedang diproses."""
    slot = _slot_akun(hasil, job)
    if slot is not None:
        slot[kunci] = nilai


def _baca_baris(baris: str, hasil: dict, job: dict):
    """Terjemahkan satu baris keluaran scraper menjadi data yang bisa dilaporkan."""
    sesi = job.get("sesi") or {}
    total_akun = max(1, len(sesi.get("akun") or [1]))
    pakai_komentar = bool(sesi.get("komentar", True))
    bobot_post = 50.0 if pakai_komentar else 85.0
    bobot_komen = 38.0

    for nama, pola in POLA.items():
        cocok = pola.search(baris)
        if not cocok:
            continue

        if nama == "mulai_akun":
            idx = int(cocok.group(1))
            total_dari_output = int(cocok.group(2))
            usr = cocok.group(4)
            job["_akun_kini"] = usr
            job["_idx_akun_kini"] = idx
            total = max(total_akun, total_dari_output)
            p = 5.0 + ((idx - 1) / total) * bobot_post + (0.2 * (bobot_post / total))
            job["_progres_persen"] = max(job.get("_progres_persen", 5), int(p))
            job["_aktivitas"] = f"mengambil video & postingan @{usr} ({idx}/{total})"
            _kirim_progres(job)

        elif nama == "apify_post":
            usr = cocok.group(1)
            job["_aktivitas"] = f"mengambil video & postingan @{usr}..."
            idx = job.get("_idx_akun_kini", 1)
            p = 5.0 + ((idx - 1) / total_akun) * bobot_post + (0.5 * (bobot_post / total_akun))
            job["_progres_persen"] = max(job.get("_progres_persen", 5), int(p))
            _kirim_progres(job)

        elif nama == "polling":
            durasi_apify = cocok.group(2).strip()
            usr = job.get("_akun_kini") or "akun"
            job["_aktivitas"] = f"mengambil video @{usr} ({durasi_apify})"
            _kirim_progres(job, detak=True)

        elif nama == "mentah_post":
            _catat_akun(hasil, job, "mentah", int(cocok.group(1)))

        elif nama == "lolos":
            jumlah = int(cocok.group(1))
            hasil["post_lolos_akun"] += jumlah
            _catat_akun(hasil, job, "lolos", jumlah)
            idx = job.get("_idx_akun_kini", 1)
            p = 5.0 + (idx / total_akun) * bobot_post
            job["_progres_persen"] = max(job.get("_progres_persen", 5), int(p))
            job["_aktivitas"] = f"menyaring postingan @{job.get('_akun_kini', '')} ({jumlah} lolos)..."
            _kirim_progres(job)

        elif nama == "top_video":
            hasil["top_video"] = int(cocok.group(1))
            job["_aktivitas"] = f"memilih video teratas @{job.get('_akun_kini', '')}..."
            _kirim_progres(job)

        elif nama == "apify_komentar":
            k = job.get("_idx_akun_komen", 0) + 1
            job["_idx_akun_komen"] = k
            p = 55.0 + ((k - 1) / total_akun) * bobot_komen + (0.3 * (bobot_komen / total_akun))
            job["_progres_persen"] = max(job.get("_progres_persen", 55), int(p))
            job["_aktivitas"] = f"mengambil komentar video @{job.get('_akun_kini', '')}..."
            _kirim_progres(job)

        elif nama == "komentar_akun":
            job["_akun_kini"] = cocok.group(1)
            k = max(1, job.get("_idx_akun_komen", 1))
            p = 55.0 + ((k - 1) / total_akun) * bobot_komen + (0.4 * (bobot_komen / total_akun))
            job["_progres_persen"] = max(job.get("_progres_persen", 55), int(p))
            job["_aktivitas"] = f"mengambil komentar video @{cocok.group(1)}..."
            _kirim_progres(job)

        elif nama == "sentimen":
            k = max(1, job.get("_idx_akun_komen", 1))
            p = 55.0 + ((k - 1) / total_akun) * bobot_komen + (0.8 * (bobot_komen / total_akun))
            job["_progres_persen"] = max(job.get("_progres_persen", 55), int(p))
            job["_aktivitas"] = f"membaca tanggapan komentar @{job.get('_akun_kini', '')}..."
            _kirim_progres(job)

        elif nama == "komentar_saved":
            jumlah_komentar = int(cocok.group(1))
            hasil["komentar_saved"] += jumlah_komentar
            hasil["akun_komentar"] += 1
            _catat_akun(hasil, job, "komentar", jumlah_komentar)
            job["_peringatan_terakhir"] = ""
            k = max(1, job.get("_idx_akun_komen", 1))
            p = 55.0 + (k / total_akun) * bobot_komen
            job["_progres_persen"] = max(job.get("_progres_persen", 55), int(p))
            job["_aktivitas"] = f"komentar @{job.get('_akun_kini', '')} tersimpan..."
            _kirim_progres(job)

        elif nama == "total_post":
            hasil["total_post"] = int(cocok.group(1))
        elif nama == "akun_sukses":
            hasil["akun_sukses"] = int(cocok.group(1))
        elif nama == "akun_gagal":
            hasil["akun_gagal"] = int(cocok.group(1))
        elif nama == "sentimen_pos":
            hasil["sentimen"]["POSITIF"] += int(cocok.group(1))
        elif nama == "sentimen_neg":
            hasil["sentimen"]["NEGATIF"] += int(cocok.group(1))
        elif nama == "sentimen_net":
            hasil["sentimen"]["NETRAL"] += int(cocok.group(1))

        elif nama == "tiktok_query":
            idx = int(cocok.group(1))
            total_q = int(cocok.group(2))
            query_str = cocok.group(3)
            job["_aktivitas"] = f"mencari video TikTok: \"{query_str}\" ({idx}/{total_q})"
            job["_progres_persen"] = min(75, 10 + int(idx * 40 / max(1, total_q)))
            _kirim_progres(job)

        elif nama == "tiktok_ai_gate":
            job["_aktivitas"] = "menilai relevansi video dengan AI Gate (gpt-5.6-luna)..."
            job["_progres_persen"] = 65
            _kirim_progres(job)

        elif nama == "tiktok_mentah":
            hasil["tiktok_mentah"] = int(cocok.group(1))

        elif nama == "tiktok_lolos":
            hasil["tiktok_lolos"] = int(cocok.group(1))

        elif nama == "tiktok_relevan":
            hasil["tiktok_relevan"] = int(cocok.group(1))
            hasil["total_post"] = int(cocok.group(1))
        
        elif nama == "tiktok_kota":
            hasil["tiktok_kota"] = int(cocok.group(1))
            
        elif nama == "tiktok_kab":
            hasil["tiktok_kab"] = int(cocok.group(1))
            
        elif nama == "tiktok_none":
            hasil["tiktok_none"] = int(cocok.group(1))

        elif nama == "tiktok_ragu":
            hasil["tiktok_ragu"] = int(cocok.group(1))

        elif nama == "ranking_item":
            pos = int(cocok.group(1))
            usr = cocok.group(2).strip()
            skor = int(cocok.group(3))
            detail = cocok.group(4).strip()
            nama_inst = cocok.group(5).strip()
            hasil.setdefault("ranking_opd", []).append({
                "pos": pos,
                "username": usr,
                "skor": skor,
                "detail": detail,
                "instansi": nama_inst,
            })

        elif nama == "berkas":
            jalur = cocok.group(1 if cocok.lastindex == 1 else cocok.lastindex).strip()
            if jalur and jalur not in hasil["berkas"]:
                hasil["berkas"].append(jalur)

        elif nama == "biaya":
            try:
                hasil["biaya"] += float(cocok.group(1))
            except ValueError:
                pass

        elif nama == "galat":
            mentah = cocok.group(1).strip()
            pesan = _rapikan_baris_log(mentah) or mentah
            if pesan not in hasil["galat"]:
                hasil["galat"].append(pesan)
                job["_peringatan_terakhir"] = pesan
                job["_aktivitas"] = f"gangguan: {pesan[:80]}"
                _kirim_progres(job, f"⚠️ {pesan[:110]}")

        elif nama == "spam":
            job["_spam_dihapus"] = int(cocok.group(1))

        elif nama == "selesai":
            hasil["selesai_bersih"] = True
            job["_progres_persen"] = 100
            job["_aktivitas"] = "selesai — menyusun laporan"
            _kirim_progres(job, "✅ Selesai — menyusun laporan...")
            return


def _kumpulkan_berkas(hasil: dict, waktu_mulai: float) -> list:
    """
    Kumpulkan berkas hasil. Utamanya dari baris 'CSV : ...' / 'JSON : ...' yang
    dicetak scraper. Kalau tidak ada yang terbaca (misal scraper berhenti di tengah),
    dicari cadangan: berkas baru di folder post/comment sesudah job dimulai.
    """
    dari_scraper = []
    for jalur in hasil["berkas"]:
        p = _ke_path_lokal(jalur)
        if p and p.exists():
            dari_scraper.append(p)
    if dari_scraper:
        return dari_scraper

    cadangan = []
    batas = waktu_mulai - 5
    for folder in (cfg.FOLDER_IG_POST, cfg.FOLDER_IG_COMMENT,
                   getattr(cfg, "FOLDER_OPD_POST", Path(".")),
                   getattr(cfg, "FOLDER_OPD_RANKING", Path(".")),
                   getattr(cfg, "FOLDER_TIKTOK_POST", Path(".")),
                   getattr(cfg, "FOLDER_TIKTOK_COMMENT", Path(".")),
                   getattr(cfg, "FOLDER_FACEBOOK_POST", Path(".")),
                   getattr(cfg, "FOLDER_FACEBOOK_COMMENT", Path("."))):
        if not folder.exists():
            continue
        for berkas in folder.rglob("*"):
            try:
                if berkas.is_file() and berkas.stat().st_mtime >= batas and berkas.suffix.lower() in (".csv", ".json"):
                    cadangan.append(berkas)
            except OSError:
                continue
    cadangan.sort(key=lambda p: p.stat().st_mtime)
    return cadangan[-MAKS_BERKAS_CADANGAN:]


def _ke_path_lokal(jalur: str):
    """
    Ubah jalur apa pun menjadi Path yang bisa dibaca bot INI.

    - Kalau bot dijalankan di Windows: jalur "D:\\..." sudah bisa dibaca apa adanya.
    - Kalau bot dijalankan di WSL/Linux: jalur "D:\\..." harus diubah jadi /mnt/d/...
    Perbedaan ini penting: mengubah ke /mnt/... saat bot sedang jalan di Windows
    justru membuat berkas tidak ditemukan.
    """
    teks = (jalur or "").strip().strip('"')
    if not teks:
        return None
    if re.match(r"^[A-Za-z]:[\\/]", teks) and os.name != "nt":
        drive = teks[0].lower()
        sisa = teks[2:].replace("\\", "/")
        return Path(f"/mnt/{drive}{sisa}")
    return Path(teks)


def _kirim_ringkasan(job: dict, hasil: dict, durasi: str, kode: int, berkas: list,
                     cuplikan: list = None, arsip_log: str = None):
    """Susun laporan akhir ringkas dan kirim berkas."""
    arsip_log = arsip_log or job.get("_arsip_path") or ""
    sesi = job.get("sesi") or {}
    argv_str = " ".join(str(a) for a in (job.get("argv") or []))

    status_label = {
        SUKSES: "✅ Selesai",
        GAGAL: "❌ Gagal",
        DIBATALKAN: "🚫 Dibatalkan",
        TERPUTUS: "⚠️ Terputus",
    }.get(job.get("status"), job.get("status", "Selesai"))

    s = hasil.get("sentimen") or {}
    jml = sum(s.values())
    komentar_total = hasil.get("komentar_saved") or 0
    jumlah_post = hasil.get("total_post") or hasil.get("post_lolos_akun", 0) or hasil.get("tiktok_relevan", 0)

    target_jenis = sesi.get("target_jenis")
    is_facebook = (target_jenis == "facebook")
    is_tiktok = (target_jenis == "tiktok")
    is_opd_ranking = (target_jenis == "opd" and sesi.get("opd_mode") == "ranking")
    if not is_facebook and not is_tiktok and not is_opd_ranking:
        if "facebook/code" in argv_str.lower().replace("\\", "/"):
            is_facebook = True
        elif "tiktok/code" in argv_str.lower().replace("\\", "/"):
            is_tiktok = True
        elif "cirebon_opd" in argv_str.lower() and "ranking" in argv_str.lower():
            is_opd_ranking = True

    if is_tiktok or is_facebook:
        nama_plat = "Facebook" if is_facebook else "TikTok"
        icon_plat = "🌐" if is_facebook else "🎵"
        tipe_item = "postingan" if is_facebook else "video"
        kunci_topik = "facebook_topik" if is_facebook else "tiktok_topik"
        topik = sesi.get(kunci_topik, f"Isu {nama_plat}")
        baris = [f"{icon_plat} <b>Laporan Pemantauan Isu {nama_plat}</b> {status_label}"]
        baris.append(f"⏱️ Selesai dalam {tg.esc(durasi)}")
        baris.append(f"📌 Topik/Isu: <b>{tg.esc(topik)}</b>")
        baris.append(f"📅 Rentang Waktu: <b>{sesi.get('hari', 30)} hari terakhir</b>")
        baris.append("")
        baris.append("━━━━━━━━━━━━━━━━━━━━")

        # Corong Hasil
        ditarik = hasil.get("tiktok_mentah") or 0
        lolos_kata = hasil.get("tiktok_lolos") or 0
        relevan = hasil.get("tiktok_relevan") or hasil.get("total_post", 0)
        ragu = hasil.get("tiktok_ragu", 0)

        baris.append("📊 <b>Hasil Corong Pencarian & AI Gate:</b>")
        if ditarik:
            baris.append(f"📥 {tipe_item.capitalize()} ditarik Apify : <b>{ditarik} {tipe_item}</b>")
        if lolos_kata:
            baris.append(f"✨ Lolos filter kata wilayah : <b>{lolos_kata} {tipe_item}</b>")
        baris.append(f"✅ Relevan Cirebon (AI Gate) : <b>{relevan} {tipe_item}</b>")
        if relevan:
            kota = hasil.get("tiktok_kota", 0)
            kab = hasil.get("tiktok_kab", 0)
            none = hasil.get("tiktok_none", 0)
            if kota or kab or none:
                baris.append(f"   ┣ 🏙️ Kota : <b>{kota}</b> | 🏘️ Kab : <b>{kab}</b> | ❓ Umum : <b>{none}</b>")
        if ragu:
            baris.append(f"❓ Perlu dicek (Ragu AI) : <b>{ragu} {tipe_item}</b>")

        # Ringkasan Sentimen Komentar
        if jml and komentar_total:
            baris.append("")
            baris.append("━━━━━━━━━━━━━━━━━━━━")
            pos = s.get("POSITIF", 0)
            neg = s.get("NEGATIF", 0)
            net = s.get("NETRAL", 0)
            if neg > pos and neg > net:
                suasana = "🔴 <b>Cenderung Negatif</b>"
                detail = f"{neg} dari {komentar_total} komentar berisi keluhan/kritik."
            elif pos > neg and pos > net:
                suasana = "🟢 <b>Cenderung Positif</b>"
                detail = f"{pos} dari {komentar_total} komentar berisi apresiasi/dukungan."
            else:
                suasana = "⚪ <b>Campuran / Netral</b>"
                detail = "Belum ada kecenderungan kuat."

            baris.append(f"💬 <b>Tanggapan Komentar Warga:</b> {suasana}")
            baris.append(detail)
            baris.append("")
            baris.append(f"🟢 Positif : {pos} ({_pct(pos, jml)}%)")
            baris.append(f"🔴 Negatif : {neg} ({_pct(neg, jml)}%)")
            baris.append(f"⚪ Netral  : {net} ({_pct(net, jml)}%)")

        baris.append("")
        baris.append("━━━━━━━━━━━━━━━━━━━━")

    elif is_opd_ranking:
        total_pantau = len(sesi.get("akun") or getattr(cfg, "DAFTAR_OPD", []))
        baris = [f"\U0001f3c6 <b>Klasemen Keaktifan Akun Pemkot Cirebon</b> {status_label}"]
        baris.append(f"\u23f1 Selesai dalam {tg.esc(durasi)}")
        baris.append(f"\U0001f4c5 <i>Rentang waktu: {sesi.get('hari', 30)} hari terakhir ({total_pantau} akun dipantau)</i>")
        baris.append("")
        baris.append("\u2501" * 20)

        ranking_list = hasil.get("ranking_opd") or []
        if ranking_list:
            baris.append("")
            medals = {1: "\U0001f947", 2: "\U0001f948", 3: "\U0001f949"}
            for item in ranking_list[:10]:
                pos = item["pos"]
                icon = medals.get(pos, f"<b>{pos}.</b>")
                baris.append(f"{icon} <b>@{tg.esc(item['username'])}</b> ({tg.esc(item['instansi'])})")
                baris.append(f"   \u2022 Skor: <b>{item['skor']:,}</b> | {tg.esc(item['detail'])}")
            if len(ranking_list) > 10:
                baris.append("")
                baris.append(f"<i>...dan {len(ranking_list)-10} akun lainnya (rincian lengkap di berkas CSV terlampir).</i>")
        else:
            baris.append("")
            baris.append(f"\U0001f4ca Total {hasil.get('total_post', 0)} postingan berhasil dikumpulkan.")

        baris.append("")
        baris.append("\u2501" * 20)

    else:
        baris = [f"\U0001f4dd <b>Laporan Pemantauan</b> {status_label}"]
        baris.append(f"\u23f1 Selesai dalam {tg.esc(durasi)}")
        baris.append("")
        baris.append("\u2501" * 20)

        # Kesimpulan suasana komentar (paling penting, taruh di atas)
        s = hasil.get("sentimen") or {}
        jml = sum(s.values())
        komentar_total = hasil.get("komentar_saved") or 0

        if jml and komentar_total:
            pos = s.get("POSITIF", 0)
            neg = s.get("NEGATIF", 0)
            net = s.get("NETRAL", 0)
            if neg > pos and neg > net:
                suasana = "\U0001f61f <b>Cenderung Negatif</b>"
                detail = f"{neg} dari {komentar_total} komentar berisi keluhan/kritik."
            elif pos > neg and pos > net:
                suasana = "\U0001f60a <b>Cenderung Positif</b>"
                detail = f"{pos} dari {komentar_total} komentar berisi dukungan/pujian."
            else:
                suasana = "\U0001f610 <b>Campuran / Netral</b>"
                detail = "Belum ada kecenderungan kuat."

            baris.append("")
            baris.append(f"\U0001f4ac Suasana Komentar: {suasana}")
            baris.append(detail)

        baris.append("")
        baris.append("\u2501" * 20)

        # Ringkasan data
        jumlah_post = hasil.get("total_post") or hasil.get("post_lolos_akun", 0)
        jumlah_akun = len(sesi.get("akun") or [])

        baris.append("")
        baris.append("\U0001f4ca <b>Ringkasan Data</b>")
        baris.append(f"\U0001f464 {jumlah_akun} akun dipantau ({sesi.get('hari', '?')} hari terakhir)")
        if jumlah_post:
            baris.append(f"\U0001f4c4 {jumlah_post} postingan ditemukan")
        if komentar_total:
            baris.append(f"\U0001f4ac {komentar_total} komentar dianalisis")

        if jml:
            baris.append("")
            baris.append(f"\U0001f7e2 Positif : {s.get('POSITIF', 0)} ({_pct(s.get('POSITIF', 0), jml)}%)")
            baris.append(f"\U0001f534 Negatif : {s.get('NEGATIF', 0)} ({_pct(s.get('NEGATIF', 0), jml)}%)")
            baris.append(f"\u26aa Netral  : {s.get('NETRAL', 0)} ({_pct(s.get('NETRAL', 0), jml)}%)")

        # Penjelasan mekanisme penarikan komentar (sesuai workflow per akun)
        if komentar_total:
            top_n = sesi.get("top", 3)
            maks_kom = sesi.get("maks_komentar", 100)
            baris.append("")
            baris.append("ℹ️ <b>Ketentuan Penarikan Komentar (Berlaku Per Akun):</b>")
            baris.append(f"• Tiap akun diambil {top_n} postingan teratas.")
            baris.append(f"• <b>&lt; 100 komentar:</b> Semua komentar akun tersebut ditarik lengkap.")
            baris.append(f"• <b>&ge; 100 komentar:</b> Ditarik komentar teratas/terbanyak disukai (maks {maks_kom}/post).")

            akun_komen = [(a, d.get("komentar", 0)) for a, d in (hasil.get("per_akun") or {}).items() if d.get("komentar") is not None]
            if akun_komen:
                baris.append("<i>Penerapan pada akun:</i>")
                for a, jml_k in akun_komen:
                    if jml_k < 100:
                        baris.append(f"  • @{tg.esc(a)} ({jml_k} komentar): &lt; 100 \u2192 <b>semua komentar ditarik</b>")
                    else:
                        baris.append(f"  • @{tg.esc(a)} ({jml_k} komentar): &ge; 100 \u2192 <b>komentar teratas</b> (maks {maks_kom}/post)")

    if hasil.get("galat"):
        baris.append("")
        baris.append("\u26a0\ufe0f <b>Gangguan:</b>")
        for g in hasil["galat"][:3]:
            baris.append(f"  \u2022 {tg.esc(str(g)[:100])}")

    if job["status"] != SUKSES and cuplikan:
        rapi = [t for t in (_rapikan_baris_log(x) for x in cuplikan[-4:]) if t]
        if rapi:
            baris.append("")
            baris.append("<i>Keluaran terakhir:</i>")
            for l in rapi:
                baris.append(f"  <i>{tg.esc(l[:100])}</i>")

    # Hanya kirim berkas CSV (sesuai instruksi: log dan json tidak dikirimkan)
    daftar_csv = [Path(p) for p in (berkas or []) if str(p).lower().endswith(".csv")]
    if daftar_csv:
        baris.append("")
        baris.append(f"\U0001f4ce {len(daftar_csv)} berkas CSV hasil pemantauan terlampir.")

    # Tombol interaktif
    try:
        from telegram_api import tombol, keyboard
        if is_tiktok or is_facebook:
            mode_cmd = "m:mode:facebook" if is_facebook else "m:mode:tiktok"
            baris_tombol = [
                [tombol("🔄 Pantau Isu Lain", mode_cmd),
                 tombol("🏠 Menu Utama", "h:menu")],
            ]
        elif is_opd_ranking:
            baris_tombol = [
                [tombol("📥 Unduh CSV Postingan OPD", "opd_sel:buka:0")],
                [tombol("🔄 Pantau Peringkat Lagi", "m:mode:opd"),
                 tombol("🏠 Menu Utama", "h:menu")],
            ]
        else:
            baris_tombol = [
                [tombol("\U0001f4cb Rincian Per Akun", "report:detail"),
                 tombol("\U0001f534 Lihat Keluhan", "report:negatif")],
                [tombol("\U0001f504 Mulai Pantau Lagi", "h:menu")],
            ]
        papan = keyboard(baris_tombol)
    except Exception:
        papan = None

    PENGIRIM.kirim_pesan(job["chat_id"], "\n".join(baris), papan_tombol=papan)

    # Simpan data untuk tombol interaktif
    per_akun = hasil.get("per_akun") or {}
    _LAPORAN_TERAKHIR[str(job["chat_id"])] = {
        "id_job": job["id_job"],
        "sesi": job.get("sesi") or {},
        "durasi": durasi,
        "per_akun": dict(per_akun),
        "ranking_opd": list(hasil.get("ranking_opd") or []),
        "jumlah_post": jumlah_post,
        "komentar_saved": komentar_total,
        "sentimen": dict(s),
        "spam_dihapus": job.get("_spam_dihapus", 0),
        "berkas": [str(p) for p in berkas],
    }

    # Kirim berkas CSV ke chat Telegram
    if is_opd_ranking:
        # Untuk klasemen OPD, otomatis kirim berkas CSV klasemen/ranking saja.
        # Seluruh CSV post disimpan di disk, dan user dapat memilih akun yang diinginkan
        # melalui papan tombol interaktif di bawah agar chat tidak banjir (32 akun).
        csv_ranking = [p for p in daftar_csv if "ranking" in p.name.lower()]
        for p in (csv_ranking or daftar_csv[:1]):
            try:
                PENGIRIM.kirim_file(job["chat_id"], p, keterangan=f"📊 {p.name}")
            except Exception as galat:
                PENGIRIM.kirim_pesan(job["chat_id"],
                                    f"Gagal mengirim {tg.esc(p.name)}: {tg.esc(str(galat))}")

        # Tampilkan langsung menu interaktif pilih akun untuk unduh dataset postingan
        try:
            import menu_bot
            sesi_picker = menu_bot.sesi_user(job.get("user_id")) if job.get("user_id") else (job.get("sesi") or {})
            sesi_picker["opd_pilih"] = []
            sesi_picker["opd_hal"] = 0
            sesi_picker["langkah"] = "opd_multi_pilih"
            teks_pilih = menu_bot.t_opd_multi_pilih(sesi_picker, 0)
            kb_pilih = menu_bot.kb_opd_multi_pilih(sesi_picker, 0)
            dikirim_p = PENGIRIM.kirim_pesan(job["chat_id"], teks_pilih, papan_tombol=kb_pilih)
            if isinstance(dikirim_p, dict):
                sesi_picker["pesan_menu"] = dikirim_p.get("message_id")
        except Exception as err:
            logger.warning(f"Gagal menampilkan picker OPD multi-select: {err}")
    else:
        for p in daftar_csv:
            try:
                PENGIRIM.kirim_file(job["chat_id"], p, keterangan=f"{p.name}")
            except Exception as galat:
                PENGIRIM.kirim_pesan(job["chat_id"],
                                    f"Gagal mengirim {tg.esc(p.name)}: {tg.esc(str(galat))}")


# ============================================================
# TOMBOL INTERAKTIF PADA PESAN RINGKASAN
# ============================================================
# Tujuan: pegawai tidak perlu membaca berkas CSV untuk hal-hal yang sering ditanya.
# Semua fungsi di bawah HANYA MEMBACA data yang sudah ada — tidak menjalankan ulang
# scraper, jadi tidak ada biaya tambahan dan tidak mungkin merusak data.
def teks_detail_per_akun(chat_id) -> str:
    data = _LAPORAN_TERAKHIR.get(str(chat_id))
    if not data:
        return "Belum ada laporan. Silakan jalankan pemantauan lebih dulu."

    sesi = data.get("sesi") or {}
    maks_kom = sesi.get("maks_komentar", 100)
    baris = [
        "\U0001f4cb <b>Rincian Per Akun</b>",
        f"<i>Laporan {tg.esc(str(sesi.get('hari', '?')))} hari terakhir</i>",
        "",
    ]
    for a, d in (data.get("per_akun") or {}).items():
        baris.append(f"<b>@{tg.esc(a)}</b>")
        if d.get("mentah") is not None:
            baris.append(f"  \U0001f4c4 Ditarik : {d['mentah']} postingan")
        if d.get("lolos") is not None:
            baris.append(f"  \u2705 Lolos   : {d['lolos']} postingan")
        if d.get("komentar") is not None:
            jml_k = d['komentar']
            ket = "semua ditarik (&lt;100)" if jml_k < 100 else f"disaring teratas maks {maks_kom}/post (&ge;100)"
            baris.append(f"  \U0001f4ac Komentar: {jml_k} ({ket})")
        baris.append("")

    baris.append(f"<b>Total:</b> {data.get('jumlah_post', 0)} postingan, "
                 f"{data.get('komentar_saved', 0)} komentar")

    if data.get("komentar_saved", 0) > 0:
        baris.append("")
        baris.append("ℹ️ <i>Aturan: Akun dengan &lt;100 komentar ditarik semua, sedangkan &ge;100 disaring komentar teratas.</i>")
    return "\n".join(baris)


def teks_contoh_negatif(chat_id, maks: int = 5) -> str:
    """
    Contoh komentar berlabel NEGATIF dari berkas hasil terakhir (tombol 'Contoh negatif').
    Berguna supaya pegawai tidak perlu membuka CSV untuk tahu APA keluhan warganya.
    """
    data = _LAPORAN_TERAKHIR.get(str(chat_id))
    if not data:
        return ("Belum ada laporan pada sesi bot ini. Silakan jalankan pengambilan data "
                "lebih dulu lewat menu, lalu tekan tombol ini lagi.")

    from csv import DictReader

    baris_hasil = []
    for jalur in (data.get("berkas") or []):
        p = _ke_path_lokal(jalur)
        if not p or p.suffix.lower() != ".csv" or "comment" not in p.name.lower():
            continue
        if not p.exists():
            continue
        try:
            with open(p, "r", encoding="utf-8-sig", newline="") as f:
                for row in DictReader(f):
                    label = (row.get("sentimen") or "").strip().upper()
                    if label != "NEGATIF":
                        continue
                    teks = (row.get("text") or "").replace("\n", " ").strip()
                    if not teks:
                        continue
                    penulis = (row.get("author") or "warga").strip() or "warga"
                    suka = (row.get("likes") or "0").strip() or "0"
                    baris_hasil.append(f"- @{penulis} ({suka} suka): {teks[:180]}")
                    if len(baris_hasil) >= maks:
                        break
        except Exception:
            continue
        if baris_hasil:
            break

    if not baris_hasil:
        return ("Belum ada contoh komentar negatif yang bisa ditampilkan pada laporan "
                "terakhir. Berkas lengkapnya tetap dikirim bersama laporan (CSV).")

    return "\n".join([
        f"\U0001f534 <b>{len(baris_hasil)} Contoh Keluhan Warga:</b>",
        "",
        *baris_hasil,
        "",
        "<i>Daftar lengkap ada di berkas CSV.</i>",
    ])


# ============================================================
# UJI CEPAT: python job_runner.py
# ============================================================
if __name__ == "__main__":
    print("Status:", status_ringkas())
    print("Python scraper :", cfg.PYTHON_SCRAPER)
    print("Skrip scraper  :", cfg.SKRIP_SCRAPER)
    print("Bentuk untuk Windows:", _path_untuk_windows(cfg.SKRIP_SCRAPER))
    print("Batas: antrean", cfg.MAKS_JOB_ANTREAN, "| timeout", cfg.TIMEOUT_JOB_DETIK, "detik",
          "| detak tiap", DETAK_DETIK, "detik")
    print("(Tidak ada yang dijalankan oleh uji cepat ini.)")
