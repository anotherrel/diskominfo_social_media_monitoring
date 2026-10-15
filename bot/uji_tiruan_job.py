# -*- coding: utf-8 -*-
"""
uji_tiruan_job.py
=================
Uji MESIN JOB (job_runner) tanpa Telegram dan tanpa Apify. Biaya: Rp0.

Cara kerjanya:
  1. Dibuat "scraper palsu" — program kecil yang meniru cetakan main.py
     (baris "Lolos Filter", "Status: RUNNING", "Komentar Saved", "Biaya run ini", dst)
     dan benar-benar menulis berkas CSV/JSON ke folder sementara.
  2. job_runner diarahkan memakai scraper palsu itu (bukan Apify).
  3. PENGIRIM diganti Telegram palsu yang cuma mencatat.

Yang diuji: pembacaan keluaran scraper, DETAK progres (kabar berkala),
laporan galat saat kejadian, tombol batalkan, cuplikan keluaran saat gagal,
antrean, batas keamanan, ringkasan akhir, dan pengiriman berkas.

CARA PAKAI:
    python uji_tiruan_job.py
"""

import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

import bot_config as cfg
import job_runner

# ============================================================
# LINGKUNGAN UJI
# ============================================================
FOLDER_UJI = Path(tempfile.mkdtemp(prefix="uji_job_"))
FOLDER_POST = FOLDER_UJI / "post"
FOLDER_COMMENT = FOLDER_UJI / "comment"
SKRIP_PALSU = FOLDER_UJI / "skrip_palsu.py"

ID_USER = 111111
CHAT_ID = 111111

_laporan = []


def cek(nama: str, lulus: bool, keterangan: str = ""):
    _laporan.append((nama, lulus, keterangan))
    print(f"  [{'LULUS' if lulus else 'GAGAL'}] {nama}" + (f" — {keterangan}" if keterangan else ""))


def judul(teks: str):
    print("\n" + "=" * 74)
    print(f"  {teks}")
    print("=" * 74)


# ============================================================
# TELEGRAM PALSU
# ============================================================
class TelegramPalsu:
    def __init__(self):
        self.catatan = []
        self.berkas_dikirim = []
        self._mid = 500

    def kirim_pesan(self, chat_id, teks, papan_tombol=None, balas_ke=None, **kwargs):
        self._mid += 1
        self.catatan.append({"aksi": "kirim", "teks": teks, "message_id": self._mid, "papan": papan_tombol})
        return {"message_id": self._mid}

    def edit_pesan(self, chat_id, message_id, teks, papan_tombol=None, **kwargs):
        self.catatan.append({"aksi": "edit", "teks": teks, "message_id": message_id, "papan": papan_tombol})
        return {"message_id": message_id}

    def jawab_tombol(self, *args, **kwargs):
        return True

    def kirim_file(self, chat_id, path_file, keterangan="", **kwargs):
        self.berkas_dikirim.append(str(path_file))
        self.catatan.append({"aksi": "file", "teks": f"{keterangan} <- {path_file}", "message_id": self._mid})
        return {"message_id": self._mid}

    def semua_teks(self) -> str:
        return "\n".join(i["teks"] or "" for i in self.catatan)

    def teks_akhir(self) -> str:
        for item in reversed(self.catatan):
            if item["aksi"] == "kirim":
                return item["teks"]
        return ""

    def bersihkan(self):
        self.catatan.clear()


# ============================================================
# SCRAPER PALSU
# ============================================================
ISI_SKRIP_PALSU = '''# -*- coding: utf-8 -*-
"""Scraper palsu untuk uji: meniru cetakan main.py, menulis berkas asli ke folder uji."""
import argparse
import sys
import time
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--akun", default="aboutcirebonid")
p.add_argument("--hari", default="7")
p.add_argument("--maks-post", dest="maks", default="300")
p.add_argument("--maks-komentar", dest="maks_k", default="100")
p.add_argument("--top-video", dest="top", default="2")
p.add_argument("--scrape-comments", action="store_true")
p.add_argument("--skip-comments", action="store_true")
p.add_argument("--outdir", default=".")
p.add_argument("--tidur", type=float, default=0.2)
p.add_argument("--gagal", action="store_true")
a = p.parse_args()

akar = Path(a.outdir)
daftar_akun = [x for x in a.akun.split(",") if x]
tidur_per_akun = max(0.05, a.tidur / max(1, len(daftar_akun)))

print("=" * 75)
print("      SCRAPPER INSTAGRAM MEDIA KOTA CIREBON - DISKOMINFO")
print("=" * 75)
print(f"Periode Scraping  : 7 hari | Batas Post/Akun : {a.maks} post")

if a.gagal:
    print("  \\u274c Akun tidak ditemukan saat diuji (ini skenario gagal yang disengaja)")
    sys.exit(1)

for i, akun in enumerate(daftar_akun, 1):
    print(f"  \\u25b6 Memulai scraping Apify untuk @{akun}...")
    print(f"[{i}/{len(daftar_akun)}] Memproses Post: {akun} (@{akun})")
    # Baris polling seperti aslinya, tiap 5 detik -> bahan DETAK progres
    sisa = tidur_per_akun
    while sisa > 0:
        print(f"  \\u23f3 @{akun} | Status: RUNNING ({max(0, int(tidur_per_akun - sisa))} detik)...")
        time.sleep(min(0.5, sisa))
        sisa -= 0.5

    folder = akar / "post" / akun / "2026-09-22"
    folder.mkdir(parents=True, exist_ok=True)
    berkas_csv = folder / f"{akun}_{a.hari}hari_scrape_20260922_120000.csv"
    berkas_json = folder / f"{akun}_{a.hari}hari_scrape_20260922_120000.json"
    berkas_csv.write_text("id,post_id,caption\\n1,2,Contoh caption Kota Cirebon\\n", encoding="utf-8")
    berkas_json.write_text('[{"post_id": "2"}]', encoding="utf-8")
    print("  \\u2728 Sukses Filter & Simpan Post!")
    print(f"     - Data Mentah Apify : {a.maks} post")
    print("     - Lolos Filter ('Kota Cirebon'): 12 post")
    print(f"     - Top Video Komentar Terbanyak : {a.top} video")
    print(f"     - CSV  : {berkas_csv}")
    print(f"     - JSON : {berkas_json}")
    print("  \\U0001F4B0 Biaya run ini (Apify): $0.0068")

print(" Total Akun Diproses : " + str(len(daftar_akun)))
print(" Akun Sukses         : " + str(len(daftar_akun)))
print(" Akun Gagal          : 0")
print(" Total Post Saved    : " + str(12 * len(daftar_akun)) + " post (memuat 'Kota Cirebon')")

if a.scrape_comments:
    print("                     MEMULAI SCRAPING KOMENTAR")
    print(f"  \\u25b6 Memulai scraping komentar Apify untuk {a.top} post...")
    print("  \\u23f3 Status Komentar: RUNNING (12 detik)...")
    print("[AI] Menjalankan Analisis Sentimen IndoBERTweet (25 komentar)...")
    print("[JOB] Menyiapkan alat pembaca komentar (model lokal, bukan layanan LLM)...")
    print("     - Sentimen IndoBERTweet (label mesin):")
    print("       * POSITIF : 15 (60.00%)")
    print("       * NEGATIF : 3 (12.00%)")
    print("       * NETRAL  : 7 (28.00%)")
    # CATATAN 24 Sep 2026: baris tiruan untuk tahap penilaian LLM (AI POSITIF/…
    # dst.) SUDAH DIHAPUS dari scraper palsu ini, karena scraper aslinya juga tidak
    # lagi mencetak baris-baris itu. Dengan begini, uji ini mencerminkan kenyataan.
    print(f"Memproses Komentar Video: {daftar_akun[0]} (@{daftar_akun[0]}) - {a.top} video")
    print("     - Komentar Saved   : 25")
    # Blok komentar akun KEDUA: dipakai menguji rincian PER AKUN di ringkasan.
    # (Berkas sengaja tidak ditulis ulang supaya jumlah berkas uji tetap 5.)
    akun_kedua = daftar_akun[1] if len(daftar_akun) > 1 else daftar_akun[0]
    print(f"Memproses Komentar Video: {akun_kedua} (@{akun_kedua}) - {a.top} video")
    print("[AI] Menjalankan Analisis Sentimen IndoBERTweet (25 komentar)...")
    print("     - Sentimen IndoBERTweet (label mesin):")
    print("       * POSITIF : 15 (60.00%)")
    print("       * NEGATIF : 3 (12.00%)")
    print("       * NETRAL  : 7 (28.00%)")
    print("     - Komentar Saved   : 25")
    folder_k = akar / "comment" / daftar_akun[0] / "2026-09-22"
    folder_k.mkdir(parents=True, exist_ok=True)
    berkas_k = folder_k / f"comment_{daftar_akun[0]}_{a.hari}hari_scrape_20260922_120000.csv"
    berkas_k.write_text("id,text,sentimen,sentimen_ai,beda_sentimen\\n1,contoh,POSITIF,POSITIF,Tidak\\n", encoding="utf-8")
    print(f"     - CSV  : {berkas_k}")
    print("  \\U0001F4B0 Biaya run ini (Apify): $0.0021")

print("      PROSES SCRAPING & ANALISIS SENTIMEN KOMENTAR TOTAL SELESAI!")
sys.exit(0)
'''


def siapkan_lingkungan():
    """Arahkan job_runner ke scraper palsu + folder uji. Tidak menyentuh data asli."""
    SKRIP_PALSU.write_text(ISI_SKRIP_PALSU, encoding="utf-8")
    FOLDER_POST.mkdir(parents=True, exist_ok=True)
    FOLDER_COMMENT.mkdir(parents=True, exist_ok=True)
    (FOLDER_UJI / "log").mkdir(parents=True, exist_ok=True)

    cfg.PYTHON_SCRAPER = sys.executable          # python yang sedang dipakai uji ini
    cfg.SKRIP_SCRAPER = SKRIP_PALSU
    cfg.FOLDER_IG_POST = FOLDER_POST
    cfg.FOLDER_IG_COMMENT = FOLDER_COMMENT
    cfg.FOLDER_LOG = FOLDER_UJI / "log"          # arsip log mentah jangan masuk folder asli
    job_runner.PATH_JOB = FOLDER_UJI / "job.json"
    job_runner.PATH_RIWAYAT = FOLDER_UJI / "riwayat_job.json"
    job_runner.DETAK_DETIK = 1                   # detak tiap 1 detik supaya uji cepat

    print(f"  Python  : {cfg.PYTHON_SCRAPER}")
    print(f"  Scraper : {cfg.SKRIP_SCRAPER} (PALSU, bukan Apify)")
    print(f"  Folder  : {FOLDER_UJI}")


def tunggu_selesai(batas_detik: int = 90) -> bool:
    batas = time.time() + batas_detik
    while time.time() < batas:
        if "0 menunggu, tidak ada" in job_runner.status_ringkas():
            return True
        time.sleep(0.3)
    return False


def tunggu_berjalan(batas_detik: int = 20) -> bool:
    """Tunggu sampai worker benar-benar mulai mengerjakan job (bukan masih di antrean)."""
    batas = time.time() + batas_detik
    while time.time() < batas:
        if "sedang jalan" in job_runner.status_ringkas():
            return True
        time.sleep(0.2)
    return False


def id_job_terakhir(tg_palsu: TelegramPalsu) -> str:
    """Ambil id job terakhir dari pesan antrean (biar tidak menebak-nebak nomornya)."""
    cocok = re.findall(r"Job (job\d+) MASUK ANTREAN", tg_palsu.semua_teks())
    return cocok[-1] if cocok else ""


def perintah_uji(akun="aboutcirebonid,radarcirebon", hari="7", top="2", komentar=True,
                 tidur="3", gagal=False):
    argv = [str(cfg.SKRIP_SCRAPER), "--akun", akun, "--hari", hari,
            "--maks-post", "300", "--top-video", top,
            "--scrape-comments" if komentar else "--skip-comments",
            "--outdir", str(FOLDER_UJI), "--tidur", tidur]
    if gagal:
        argv.append("--gagal")
    return argv


# ============================================================
# UJI
# ============================================================
def main():
    print("Uji tiruan MESIN JOB. Scraper palsu — tidak ada Apify, tidak ada Telegram.")
    siapkan_lingkungan()

    tg_palsu = TelegramPalsu()
    job_runner.PENGIRIM = tg_palsu
    sesi = {"akun": ["aboutcirebonid", "radarcirebon"], "hari": 7, "maks_post": 300,
            "top": 2, "komentar": True}

    # ---------- 1. batas antrean ----------
    judul("SKENARIO 1 — Antrean penuh ditolak (bukan dijalankan diam-diam)")
    simpan_batas = cfg.MAKS_JOB_ANTREAN
    cfg.MAKS_JOB_ANTREAN = 0
    job_runner.jalankan_job(sesi, perintah_uji(), CHAT_ID, ID_USER)
    cfg.MAKS_JOB_ANTREAN = simpan_batas
    cek("Antrean penuh -> user diberi tahu", "penuh" in tg_palsu.teks_akhir().lower())
    cek("Tidak ada job yang masuk", "0 menunggu, tidak ada" in job_runner.status_ringkas())

    # ---------- 2. job masuk antrean + batas 1 job per orang ----------
    judul("SKENARIO 2 — Job masuk antrean, dan 1 orang hanya boleh 1 job")
    tg_palsu.bersihkan()
    job_runner.jalankan_job(sesi, perintah_uji(tidur="3"), CHAT_ID, ID_USER)
    pesan_antrean = tg_palsu.teks_akhir()
    print("\n  Pesan antrean:\n    " + pesan_antrean.replace("\n", "\n    ")[:340])
    cek("User diberi tahu job masuk antrean", "MASUK ANTREAN" in pesan_antrean)
    cek("Dijanjikan kabar berkala", "kabar berkala" in pesan_antrean)

    tg_palsu.bersihkan()
    job_runner.jalankan_job(sesi, perintah_uji(tidur="3"), CHAT_ID, ID_USER)
    cek("Job kedua dari orang yang sama ditolak",
        "masih punya job" in tg_palsu.teks_akhir(), tg_palsu.teks_akhir()[:80])

    # ---------- 3. progres bergerak (DETAK) ----------
    judul("SKENARIO 3 — Progres berdetak: user selalu dapat kabar")
    tg_palsu.bersihkan()
    selesai = tunggu_selesai(90)
    cek("Job selesai dalam batas waktu", selesai, job_runner.status_ringkas())

    edits = [i for i in tg_palsu.catatan if i["aksi"] == "edit"]
    teks_edit = "\n".join(i["teks"] or "" for i in edits)
    cek("Ada pesan dimulai yang menyebut perkiraan waktu",
        any("DIMULAI" in (i["teks"] or "") for i in tg_palsu.catatan))
    cek("Pesan progres beberapa kali diperbarui (bukan sekali lalu diam)",
        len(edits) >= 2, f"{len(edits)} pembaruan")
    cek("Setiap progres memuat durasi berjalan", "SEDANG BERJALAN" in teks_edit)
    cek("Aktivitas Apify diterjemahkan jadi kalimat yang bisa dibaca",
        "sedang mengambil data" in teks_edit, teks_edit[:0])
    cek("Ada jejak langkah terakhir", "Jejak langkah terakhir" in teks_edit)
    cek("Ada tombol Batalkan job di pesan progres",
        any(t["text"] == "Batalkan job" for i in edits
            for baris in ((i.get("papan") or {}).get("inline_keyboard") or []) for t in baris))

    # ---------- 4. ringkasan & berkas ----------
    judul("SKENARIO 4 — Ringkasan akhir dan berkas")
    teks = tg_palsu.semua_teks()
    print("\n  ---- Ringkasan akhir ----")
    print("    " + tg_palsu.teks_akhir().replace("\n", "\n    ")[:600])
    cek("Ringkasan punya bagian POSTINGAN",
        f"POSTINGAN (filter '{cfg.KATA_KUNCI_SCRAPER}')" in teks)
    cek("Ringkasan menyebut TOTAL post (24 = 12+12)", "TOTAL: 24 post" in teks)
    cek("Ringkasan memuat rincian post PER AKUN (dengan jumlah mentah)",
        "@aboutcirebonid : 12 post lolos (dari 300 ditarik)" in teks
        and "@radarcirebon : 12 post lolos (dari 300 ditarik)" in teks)
    cek("Ringkasan punya bagian KOMENTAR", "\nKOMENTAR" in teks)
    cek("Ringkasan menjumlah komentar 2 akun (25+25), bukan 25",
        "TOTAL: 50 komentar (dari 2 akun)" in teks)
    cek("Ringkasan memuat rincian komentar PER AKUN",
        "@aboutcirebonid : 25 komentar" in teks and "@radarcirebon : 25 komentar" in teks)
    cek("Ringkasan menyebut sentimen gabungan (30 = 15+15)",
        "IndoBERT (mesin)" in teks and "POSITIF 30 (60.00%)" in teks)
    # (Pemeriksaan "SENTIMEN AI", "AI beda dari IndoBERT", dan "Gate AI" DIHAPUS
    #  24 Sep 2026 — tahap penilaian LLM sudah dilepas dari sistem.)
    cek("Biaya Apify digabung dari semua tahap ($0.0157)",
        "BIAYA APIFY: $0.0157" in teks)
    cek("Berkas hasil + arsip log dikirim (4 post + 1 komentar + 1 arsip = 6)",
        len(tg_palsu.berkas_dikirim) == 6,
        f"terkirim ({len(tg_palsu.berkas_dikirim)}): {[Path(p).name for p in tg_palsu.berkas_dikirim]}")

    # ---- arsip log mentah: tidak ada data yang benar-benar hilang ----
    arsip = [Path(p) for p in tg_palsu.berkas_dikirim if Path(p).name.startswith("log_")]
    cek("Arsip log mentah dibuat & ikut dikirim", len(arsip) == 1, str(arsip))
    if arsip:
        isi_arsip = arsip[0].read_text(encoding="utf-8", errors="replace")
        cek("Arsip memuat baris polling yang TIDAK dikirim ke chat",
            "Status: RUNNING" in isi_arsip, "baris yang disaring harus tetap ada di arsip")
        cek("Arsip memuat baris penting yang juga dikirim ke chat",
            "Lolos Filter" in isi_arsip and "Komentar Saved" in isi_arsip)
        cek("Arsip punya kepala + penutup (jumlah baris & kode keluar tercatat)",
            "LOG MENTAH" in isi_arsip and "Jumlah baris tercatat" in isi_arsip
            and "Kode keluar scraper" in isi_arsip)
        cek("Ringkasan menyebut nama berkas arsip log", arsip[0].name in teks)

    # ---------- 5. jejak job ----------
    judul("SKENARIO 5 — Jejak job tersimpan")
    riwayat = json.loads(job_runner.PATH_RIWAYAT.read_text(encoding="utf-8")) if job_runner.PATH_RIWAYAT.exists() else []
    cek("Riwayat job ditulis", len(riwayat) == 1, f"{len(riwayat)} entri")
    if riwayat:
        cek("Status job sukses", riwayat[-1]["status"] == "sukses", riwayat[-1]["status"])
        cek("Biaya tersimpan di jejak", abs(riwayat[-1]["biaya_usd"] - 0.0157) < 0.0005,
            str(riwayat[-1]["biaya_usd"]))

    # ---------- 6. tombol batalkan job ----------
    judul("SKENARIO 6 — Tombol Batalkan benar-benar menghentikan job")
    tg_palsu.bersihkan()
    job_runner.jalankan_job(sesi, perintah_uji(akun="aboutcirebonid", komentar=False, tidur="8"),
                            CHAT_ID, ID_USER)
    id_job = id_job_terakhir(tg_palsu)
    cek("Job benar-benar mulai dikerjakan", tunggu_berjalan(20))
    time.sleep(1.2)                       # biarkan beberapa detak progres terkirim
    berhasil, pesan = job_runner.batalkan_job(id_job, ID_USER)
    print(f"  Hasil batalkan: berhasil={berhasil} | pesan={pesan}")
    cek("Pembatalan diterima", berhasil, pesan)
    cek("Pesan pembatalan menjelaskan status permintaan Apify", "Apify" in pesan)
    tunggu_selesai(60)
    cek("Ringkasan menandai job DIBATALKAN", "DIBATALKAN" in tg_palsu.semua_teks())
    cek("Antrean kembali kosong", "0 menunggu, tidak ada" in job_runner.status_ringkas())

    # orang lain tidak boleh membatalkan job kita
    judul("SKENARIO 7 — Orang lain tidak bisa membatalkan job kita")
    tg_palsu.bersihkan()
    job_runner.jalankan_job(sesi, perintah_uji(akun="aboutcirebonid", komentar=False, tidur="6"),
                            CHAT_ID, ID_USER)
    id_job = id_job_terakhir(tg_palsu)
    tunggu_berjalan(20)
    berhasil_lain, pesan_lain = job_runner.batalkan_job(id_job, user_id=999999)
    cek("Ditolak karena bukan pemiliknya", not berhasil_lain, pesan_lain)
    berhasil_sendiri, _ = job_runner.batalkan_job(id_job, ID_USER)
    cek("Pemiliknya sendiri tetap bisa membatalkan", berhasil_sendiri)
    tunggu_selesai(60)

    # ---------- 8. kegagalan terlihat jelas ----------
    judul("SKENARIO 8 — Gagal: user tahu penyebabnya, bukan menunggu tanpa kabar")
    tg_palsu.bersihkan()
    job_runner.jalankan_job(sesi, perintah_uji(akun="aboutcirebonid", komentar=False,
                                              tidur="1", gagal=True), CHAT_ID, ID_USER)
    tunggu_selesai(60)
    teks_gagal = tg_palsu.semua_teks()
    print("\n  ---- Pesan terakhir ----")
    print("    " + tg_palsu.teks_akhir().replace("\n", "\n    ")[:600])
    cek("Gangguan dilaporkan SAAT KEJADIAN (bukan nanti)", "⚠️" in teks_gagal)
    cek("Ringkasan berlabel GAGAL", "GAGAL" in tg_palsu.teks_akhir())
    cek("Cuplikan keluaran terakhir disertakan", "Cuplikan keluaran terakhir" in teks_gagal)
    cek("Penyebab asli ikut terbaca", "Akun tidak ditemukan" in teks_gagal)

    # ---------- 9. penerjemahan alamat ----------
    judul("SKENARIO 9 — Penerjemahan alamat WSL <-> Windows")
    cek("Alamat WSL diubah ke gaya Windows",
        job_runner._path_untuk_windows("/mnt/d/DKIS/x/main.py") == "D:\\DKIS\\x\\main.py",
        job_runner._path_untuk_windows("/mnt/d/DKIS/x/main.py"))
    cek("Alamat Windows dibiarkan apa adanya",
        job_runner._path_untuk_windows("C:\\Python314\\python.exe") == "C:\\Python314\\python.exe")

    # ---------- 9b. angka DIJUMLAHKAN, bukan ditimpa (bug job001, 22 Sep 2026) ----------
    judul("SKENARIO 9b — Ringkasan menjumlahkan SELURUH akun, bukan akun terakhir")
    cek("Alamat berkas bertanda strip di depan ('- CSV  : D:\\\\...') ikut terbaca",
        bool(job_runner.POLA["berkas"].search("     - CSV  : D:\\x\\post\\a.csv")),
        "pola lama gagal di sini -> berkas POST tidak pernah terkirim")

    h_uji = {
        "berkas": [], "biaya": 0.0, "galat": [], "selesai_bersih": False,
        "komentar_saved": 0, "akun_komentar": 0,
        "sentimen": {"POSITIF": 0, "NEGATIF": 0, "NETRAL": 0},
        "ai": {"POSITIF": 0, "NEGATIF": 0, "NETRAL": 0},
        "ai_beda": 0, "gate_ya": 0, "post_lolos_akun": 0,
    }
    job_palsu = {"_aktivitas": "", "_kejadian": [], "_mulai_epoch": time.time()}
    for _ in range(2):            # meniru 2 akun yang masing-masing punya komentar
        for baris_uji in ("     - Komentar Saved   : 100",
                          "       * POSITIF : 26 (26.00%)",
                          "       * NEGATIF : 60 (60.00%)",
                          "       * NETRAL  : 14 (14.00%)"):
            job_runner._baca_baris(baris_uji, h_uji, job_palsu)
    cek("Komentar 2 akun DIJUMLAHKAN (100+100), bukan jadi 100",
        h_uji["komentar_saved"] == 200, str(h_uji["komentar_saved"]))
    cek("Sentimen 2 akun DIJUMLAHKAN, bukan ditimpa akun terakhir",
        h_uji["sentimen"] == {"POSITIF": 52, "NEGATIF": 120, "NETRAL": 28},
        str(h_uji["sentimen"]))

    # ---------- 9c. penyaring baris log (pilihan user "2b") ----------
    cek("Baris polling kembar DIBUANG dari aliran log",
        job_runner._rapikan_baris_log("⏳ @radarcirebon | Status: RUNNING (6 detik)...") is None)
    cek("Garis hiasan (=== / --- / !!!) DIBUANG",
        job_runner._rapikan_baris_log("=" * 75) is None
        and job_runner._rapikan_baris_log("-" * 75) is None)
    cek("Baris kosong DIBUANG", job_runner._rapikan_baris_log("   ") is None)
    cek("Potongan dokumen HTML DIBUANG",
        job_runner._rapikan_baris_log('<!--[if lt IE 7]> <html class="no-js ie6 oldie"> <![endif]-->') is None)
    cek("Semboyan unduhan model DIBUANG",
        job_runner._rapikan_baris_log("Loading weights: 100%|██████████| 201/201 [00:00<00:00]") is None
        and job_runner._rapikan_baris_log("Warning: You are sending unauthenticated requests to the HF Hub") is None)
    cek("Galat 524 TIDAK disembunyikan, hanya dirapikan jadi kalimat yang bisa dipahami",
        "HTTP 524" in (job_runner._rapikan_baris_log(
            "⚠️ Batch 5 gagal di key #1 (sk-kit...3e7e) [umum]: HTTP 524: <!DOCTYPE html>") or ""))
    cek("Baris yang menambah informasi tetap diteruskan",
        job_runner._rapikan_baris_log("✅ Data mentah berhasil diambil: 100 postingan.") is not None)

    # ---------- 9d. catatan proses ramah + penjelasan "kenapa lama" ----------
    # CATATAN 24 Sep 2026: pemeriksaan khusus tahap LLM (batch, pekerja, key, "server AI")
    # DIHAPUS dari uji ini karena tahap itu tidak lagi dijalankan. Yang diuji sekarang
    # hanya yang benar-benar berjalan: Apify + pembacaan komentar dengan model lokal.
    judul("SKENARIO 9d — Catatan proses ramah & penjelasan saat langkah terasa lama")
    R = job_runner._rapikan_baris_log

    garis_gagal = R("⚠️ Batch 1 gagal di key #1 (sk-kit...3e7e) [umum]: HTTP 524: <!DOCTYPE html>") or ""
    cek("Potongan kunci API TIDAK pernah tampil di percakapan", "sk-kit" not in garis_gagal)
    cek("Galat jaringan diterjemahkan + kode HTTP tetap disebut",
        "HTTP 524" in garis_gagal and "dicoba ulang" in garis_gagal)
    cek("Run ID Apify diganti kalimat manusiawi",
        "Run ID" not in (R("ℹ️ Task Apify berjalan (Run ID: 2opVVMTZINFIl5H1G)") or "")
        and "diterima Apify" in (R("ℹ️ Task Apify berjalan (Run ID: 2opVVMTZINFIl5H1G)") or ""))
    cek("Alamat berkas di komputer tidak lagi membanjiri chat",
        R(r"     - CSV  : D:\x\post\a.csv") is None and R(r"     - JSON : D:\x\post\a.json") is None)
    cek("Catatan internal scraper tidak dikirim ke chat",
        R("📝 Riwayat scraping post tersimpan di history/history_post.csv & .json") is None)
    cek("Baris Post ID/Comments/Likes jadi istilah Indonesia",
        R("1. [Video] Post ID: 3987359621072088753 | Comments: 28 | Likes: 108")
        == "1. [Video] Komentar: 28 | Suka: 108")

    # Pesan progres WAJIB menjelaskan saat sebuah langkah kelewat lama.
    job_lambat = {
        "id_job": "job902", "chat_id": CHAT_ID, "status": job_runner.BERJALAN,
        "_mulai_epoch": time.time() - 600,
        "_aktivitas": "analisis sentimen (500 komentar)",
        "_aktivitas_terakhir": "analisis sentimen (500 komentar)",
        "_aktivitas_mulai": time.time() - 420,
        "_kejadian": ["Membaca & menggolongkan komentar dimulai"],
        "sesi": {"akun": ["aboutcirebonid"], "hari": 7, "maks_post": 50, "top": 3, "komentar": True},
    }
    teks_lambat = job_runner._susun_teks_progres(job_lambat)
    cek("Progres memuat penghitung lama LANGKAH INI (bukti job masih hidup)",
        "pada langkah ini" in teks_lambat and "sudah 7 menit" in teks_lambat)
    cek("Progres memberi perkiraan lama langkah itu",
        "biasanya selesai dalam" in teks_lambat)
    cek("Progres menjelaskan SEBAB saat langkah kelewat lama",
        "Mengapa lama?" in teks_lambat and "komputer sedang" in teks_lambat)
    cek("Progres menyebut akibatnya: job jalan terus & data tidak hilang",
        "TIDAK berhenti" in teks_lambat and "tidak ada data yang hilang" in teks_lambat)
    cek("Progres memberi pilihan tindakan yang jelas", "Batalkan job" in teks_lambat)

    # (Blok uji "galat server AI harus tertangkap" DIHAPUS 24 Sep 2026: pola llm_gagal
    #  dan llm_rotasi tidak lagi ada karena tahap penilaian LLM sudah dilepas.)

    # ---------- 9e. mode satu pesan: keluaran scraper tidak lagi jadi puluhan pesan ----------
    judul("SKENARIO 9e — Keluaran scraper tampil di SATU pesan (tidak membanjiri chat)")
    job_spam = {
        "id_job": "job904", "chat_id": CHAT_ID,
        "_aktivitas": "memproses akun 1 dari 1 (@uji)", "_kejadian": [], "_mulai_epoch": time.time(),
        "sesi": {"akun": ["uji"], "hari": 7, "maks_post": 10, "top": 3,
                 "komentar": False, "kirim_log": True},
    }
    tg_palsu.bersihkan()
    for b in ("✅ Data mentah berhasil diambil: 5 postingan.",
              "⏳ @uji | Status: RUNNING (6 detik)...",
              r"     - CSV  : D:\x\post\a.csv",
              "✨ Postingan berhasil disaring & disimpan.",
              "💰 Biaya run ini (Apify): $0.0100"):
        job_runner._alirkan_log(job_spam, b)
    pesan_baru = [i for i in tg_palsu.catatan if i["aksi"] == "kirim"]
    cek("5 baris keluaran TIDAK menjadi 5 pesan (mode satu pesan)",
        job_runner.cfg.LOG_SATU_PESAN and len(pesan_baru) <= 1, f"{len(pesan_baru)} pesan baru")

    sebelum = len(tg_palsu.catatan)
    for b in ("baris susulan A", "baris susulan B"):
        job_runner._alirkan_log(job_spam, b)
    cek("Baris susulan langsung berikutnya tidak menambah pesan baru",
        len(tg_palsu.catatan) - sebelum == 0, f"{len(tg_palsu.catatan) - sebelum} pesan baru")

    isi_progres = job_runner._susun_teks_progres(job_spam)
    # Catatan: teks baris di bawah sudah melewati penerjemahan bahasa ramah, jadi yang
    # dicari adalah bentuk RAMAHNYA ("berhasil diambil dari Apify"), bukan teks aslinya.
    cek("Keluaran scraper tampil DI DALAM pesan progres",
        "Catatan proses terakhir" in isi_progres
        and "berhasil diambil dari Apify" in isi_progres
        and "Postingan berhasil disaring" in isi_progres)
    cek("Baris sampah tidak ikut tampil di pesan progres",
        "Status: RUNNING" not in isi_progres and "CSV  :" not in isi_progres)
    cek("Pesan progres tetap di bawah batas Telegram (4096 karakter)",
        len(isi_progres) <= job_runner.cfg.PANJANG_TELEGRAM, str(len(isi_progres)))

    for i in range(60):
        job_runner._alirkan_log(job_spam, f"baris panjang sekali nomor {i} " + "x" * 80)
    isi_padat = job_runner._susun_teks_progres(job_spam)
    jumlah_tampil = sum(1 for b in isi_padat.splitlines() if b.startswith("  baris panjang"))
    cek("Jumlah baris yang ditampilkan dibatasi (tidak tumbuh tanpa henti)",
        jumlah_tampil <= job_runner.cfg.LOG_TAIL_BARIS, f"{jumlah_tampil} baris")
    cek("Walau barisnya sangat banyak, pesan tetap di bawah batas Telegram",
        len(isi_padat) <= job_runner.cfg.PANJANG_TELEGRAM, str(len(isi_padat)))

    job_spam["sesi"]["kirim_log"] = False
    cek("Setelah /logmati, catatan proses hilang dari pesan progres",
        "Catatan proses terakhir" not in job_runner._susun_teks_progres(job_spam))
    job_spam["sesi"]["kirim_log"] = True

    # ---------- ringkasan ----------
    judul("RINGKASAN UJI MESIN JOB")
    lulus = sum(1 for _, l, _ in _laporan if l)
    print(f"  {lulus}/{len(_laporan)} pemeriksaan lulus.\n")
    for nama, l, ket in _laporan:
        if not l:
            print(f"  GAGAL: {nama} {ket}")

    try:
        shutil.rmtree(FOLDER_UJI, ignore_errors=True)
        print(f"\n  Folder uji dibersihkan: {FOLDER_UJI}")
    except Exception as galat:
        print(f"\n  (Folder uji {FOLDER_UJI} tidak terhapus: {galat})")

    sys.exit(0 if lulus == len(_laporan) else 1)


if __name__ == "__main__":
    main()
