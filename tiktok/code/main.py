# -*- coding: utf-8 -*-
"""
main.py (modul TikTok) — VERSI SEDERHANA (18 Sep 2026)
=====================================================
Pintu masuk & orkestrasi alur 5 langkah pencarian isu Kota Cirebon.

TAHAPAN
1. Input        : topik (1 kata kunci) + 1-5 contoh video relevan (TEMPEL URL SAJA,
                  caption diambil otomatis) + rentang tanggal
2. Validasi     : caption contoh wajib >= 5 kata bermakna (caption hashtag-saja ditolak)
3. Kata kunci   : AI membuat 3-5 varian kata kunci pencarian (wajib memuat kata wilayah)
4. Scrape+gerbang: tarik video per kata kunci -> GERBANG (tanggal + kata terlarang + kata wilayah)
                  -> kandidat. SEMUA item mentah disimpan untuk audit.
5. Gate AI      : AI menilai tiap kandidat (belajar dari contoh video) ->
                  YA / TIDAK / RAGU + label wilayah + alasan.
                  TIDAK & RAGU tetap disimpan (tidak dibuang diam-diam) + laporan corong.

Yang TIDAK ada lagi di versi ini: bobot kata, ambang skor, induksi "rule set",
uji mandiri ambang. Alasan & angkanya ada di DESAIN.md "Revisi 18 Sep 2026".

CARA JALANKAN (dari folder tiktok/code, atau dari root lewat launcher main.py):
    python main.py                                        # menu interaktif
    python main.py --topik "jalan rusak" --day 30
    python main.py --topik "banjir" --from 2026-08-01 --to 2026-09-17
    python main.py --topik "jalan rusak" --day 7 --dry-run  # susun kata kunci + estimasi saja
    python main.py --topik "jalan rusak" --day 30 --no-llm  # tanpa gate AI

CATATAN CAPTION CONTOH
Cukup tempel URL-nya; caption diambil otomatis lewat mode 'postURLs' actor Apify
(biaya kecil ~$0.005/video, bisa dimatikan lewat AMBIL_CAPTION_CONTOH_OTOMATIS di config.py).
Kalau mau menempel caption sendiri (gratis, tanpa panggil Apify), tulis: URL | caption apa adanya
"""

import argparse
import sys

from config import (
    LABEL_PLATFORM,
    MAKS_HASIL_PER_QUERY,
    SARAN_JUMLAH_CONTOH,
    AMBIL_CAPTION_CONTOH_OTOMATIS,
    TARIF_ESTIMASI_PER_VIDEO_URL,
    ambil_apify_token,
    ambil_model_llm,
    tentukan_rentang_tanggal,
    sekarang_iso,
    folder_topik,
    muat_kaidah,
    kata_gerbang,
    keterangan_wilayah,
)
from apify_client import validasi_token, cari_video, estimasi_biaya, ambil_komentar_tiktok
from rule_builder import (
    baca_file_contoh, validasi_contoh, simpan_contoh, buat_varian_query,
    lengkapi_caption_dari_url, caption_contoh_untuk_ai,
)
from storage import (
    saring_dan_simpan_per_query, gabungkan_dan_simpan_master, catat_riwayat, simpan_mentah,
    simpan_komentar_tiktok,
)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def tampilkan_header():
    print("=" * 78)
    print(f"   SCRAPPER MONITORING ISU KOTA CIREBON — {LABEL_PLATFORM.upper()} (DKIS)")
    print("   Topik bebas · gerbang kata wilayah · AI menilai dari contoh video")
    print("=" * 78)


# ============================================================
# 1. MENU INTERAKTIF
# ============================================================
def tanya_contoh_interaktif() -> list:
    """
    Minta contoh video. Dua cara:
      - TEMPEL URL SAJA      -> caption diambil otomatis (kena biaya kecil Apify)
      - URL | caption        -> caption menempel sendiri (gratis, tanpa panggil Apify)
      Ketik 'selesai' untuk berhenti.
    """
    print(f"\n--- CONTOH VIDEO RELEVAN (butuh 1, disarankan {SARAN_JUMLAH_CONTOH}) ---")
    print("Tempel URL TikTok saja, satu per baris. Caption akan diambil otomatis.")
    print("(Kalau mau hemat: tulis 'URL | caption apa adanya' — caption tidak diambil dari Apify.)")
    print("PENTING: contoh ini yang 'mengajari' AI. Usahakan campur: ada berita panjang")
    print("dan ada video netizen pendek, supaya AI tahu keduanya relevan.")
    print("Ketik 'selesai' kalau sudah cukup.\n")

    daftar = []
    while True:
        baris = input(f"Contoh #{len(daftar) + 1} (atau 'selesai'): ").strip()
        if not baris or baris.lower() in ("selesai", "cukup", "stop"):
            break
        if baris.lower().startswith(("file:", "path:")):
            path = baris.split(":", 1)[1].strip()
            daftar.extend(baca_file_contoh(path))
            print(f"  ℹ️ {len(daftar)} contoh dimuat dari file {path}")
            continue
        if "|" in baris:
            url, _, caption = baris.partition("|")
            daftar.append({"url": url.strip(), "caption": caption.strip()})
            continue
        if not baris.lower().startswith("http"):
            print("  ❌ Yang ditempel bukan URL. Contoh: https://www.tiktok.com/@akun/video/123456")
            continue
        daftar.append({"url": baris, "caption": ""})

    return daftar


def menu_interaktif() -> dict:
    """Tanya semua input yang dibutuhkan kalau user menjalankan tanpa argumen."""
    print("\nPILIHAN RENTANG TANGGAL:")
    print("1. 30 hari terakhir (default)")
    print("2. 7 hari terakhir")
    print("3. 1 bulan terakhir")
    print("4. 1 tahun terakhir")
    print("5. Tanggal manual (YYYY-MM-DD sampai YYYY-MM-DD)")

    pilihan = input("\nMasukkan pilihan (1-5) [Default: 1]: ").strip()
    preset, jumlah, dari, sampai = "day", 30, "", ""
    if pilihan == "2":
        jumlah = 7
    elif pilihan == "3":
        preset, jumlah = "month", 1
    elif pilihan == "4":
        preset, jumlah = "year", 1
    elif pilihan == "5":
        preset = ""
        dari = input("Tanggal awal (YYYY-MM-DD): ").strip()
        sampai = input("Tanggal akhir (YYYY-MM-DD, kosong = hari ini): ").strip()

    nama_topik = input("\nKetik topik yang dicari (contoh: jalan rusak, banjir, sampah menumpuk): ").strip()
    daftar_contoh = tanya_contoh_interaktif()

    maks = input(f"\nMaksimal hasil per kata kunci [Default: {MAKS_HASIL_PER_QUERY}]: ").strip()
    gunakan_gate = input("Pakai gate AI untuk menilai hasil? (Y/N) [Default: Y]: ").strip().lower() != "n"

    return {
        "nama_topik": nama_topik,
        "daftar_contoh": daftar_contoh,
        "preset": preset,
        "jumlah": jumlah,
        "dari": dari,
        "sampai": sampai,
        "maks_hasil": int(maks) if maks.isdigit() else MAKS_HASIL_PER_QUERY,
        "gunakan_gate_ai": gunakan_gate,
        "dry_run": False,
    }


# ============================================================
# 2. WORKFLOW 5 TAHAP
# ============================================================
def jalankan_workflow(nama_topik: str, daftar_contoh: list, tanggal_min: str, tanggal_maks: str,
                      maks_hasil: int = MAKS_HASIL_PER_QUERY, gunakan_gate_ai: bool = True,
                      dry_run: bool = False, token: str = "", paksa_ulang_query: bool = False,
                      scrape_comments: bool = False, top_video: int = 3, maks_komentar: int = 100,
                      non_interactive: bool = False) -> dict:
    """Jalankan seluruh alur untuk 1 topik. Returns ringkasan hasil."""

    kaidah = muat_kaidah()
    gerbang = kata_gerbang(kaidah)
    wil = keterangan_wilayah(kaidah)

    # caption contoh (bahan acuan AI) — dikirim EKSPLISIT sampai ke gate,
    # jadi gate tidak bergantung pada file yang mungkin belum tersimpan.
    daftar_acuan = [" ".join((c.get("caption") or "").split())
                    for c in (daftar_contoh or []) if (c.get("caption") or "").strip()]

    print("\n" + "=" * 78)
    print(f"TOPIK            : {nama_topik}")
    print(f"WILAYAH SASARAN  : {wil['wilayah_nama']}")
    print(f"KATA GERBANG     : {gerbang}")
    print(f"RENTANG TANGGAL  : {tanggal_min or '(tanpa batas awal)'} s/d {tanggal_maks or 'hari ini'} (WIB)")
    print(f"CONTOH VIDEO     : {len(daftar_acuan)} caption jadi acuan AI")
    print(f"MAKS/QUERY       : {maks_hasil}")
    print(f"GATE AI (tahap 5): {'AKTIF' if gunakan_gate_ai else 'NON-AKTIF'}")
    print(f"MODEL LLM        : {ambil_model_llm()}")
    print(f"KOMENTAR         : {'YA (top ' + str(top_video) + ', maks ' + str(maks_komentar) + '/post)' if scrape_comments else 'TIDAK'}")
    print("=" * 78)

    # ---------- TAHAP 3: varian kata kunci ----------
    daftar_query = buat_varian_query(nama_topik, daftar_contoh, kaidah, paksa_ulang=paksa_ulang_query)

    if dry_run:
        print("\n  ℹ️ MODE DRY-RUN: berhenti di sini (tidak scrape, tidak ada biaya pencarian).")
        print(f"  Estimasi biaya pencarian kalau dilanjutkan: "
              f"${estimasi_biaya(len(daftar_query), maks_hasil):.3f}")
        print(f"  Folder topik: {folder_topik(nama_topik)}")
        return {"stop": "dry-run", "varian_query": daftar_query}

    # ---------- konfirmasi biaya ----------
    estimasi = estimasi_biaya(len(daftar_query), maks_hasil)
    print(f"\n  💰 Estimasi biaya pencarian: ~${estimasi:.3f} "
          f"({len(daftar_query)} kata kunci x {maks_hasil} hasil). Angka pasti dibaca setelah run.")
    if not non_interactive and sys.stdin.isatty():
        jawab = input("  Lanjutkan pencarian? (Y/N) [Default: Y]: ").strip().lower()
        if jawab == "n":
            print("  Dibatalkan oleh user.")
            return {"stop": "dibatalkan"}
    else:
        print("  ▶ Mode otomatis/non-interaktif: pencarian dilanjutkan.")

    # ---------- TAHAP 4: pencarian + gerbang ----------
    semua_baris = []
    total_biaya = 0.0
    total_mentah = 0
    ringkasan_query = []

    for urutan, query in enumerate(daftar_query, 1):
        print("\n" + "-" * 78)
        print(f"[{urutan}/{len(daftar_query)}] Kata kunci: \"{query}\"")
        print("-" * 78)

        waktu_mulai = sekarang_iso()
        items, status, pesan, info = cari_video(query, token, maks_hasil)
        waktu_selesai = sekarang_iso()
        biaya = float((info or {}).get("biaya_usd") or 0.0)
        total_biaya += biaya
        total_mentah += len(items or [])

        jumlah_lolos = 0
        gugur = {}
        if status == "success":
            path_mentah = simpan_mentah(items, nama_topik, query)
            print(f"  🗄️ Data mentah disimpan ({len(items)} item): {path_mentah}")
            try:
                id_scrape = "tt_" + sekarang_iso().replace(":", "").replace("-", "").replace("T", "_")[:15]
                jumlah_lolos, path_csv, _, baris, ring = saring_dan_simpan_per_query(
                    items, nama_topik, query, kaidah,
                    scrape_id=id_scrape, waktu_scrape=waktu_selesai,
                    tanggal_min=tanggal_min, tanggal_maks=tanggal_maks,
                )
                semua_baris.extend(baris)
                gugur = ring["gugur"]
                print(f"  ✨ Lolos gerbang: {jumlah_lolos} video (ditarik {ring['ditarik']})")
                if gugur:
                    print(f"     Alasan terbanyak gugur: {gugur}")
                print(f"     File kandidat: {path_csv}")
            except Exception as e:
                status, pesan = "failed", f"Gagal menyimpan hasil query: {e}"
                print(f"  ❌ {pesan}")

        catat_riwayat(nama_topik, query, status, len(items), jumlah_lolos,
                      waktu_mulai, waktu_selesai, biaya,
                      run_id=(info or {}).get("run_id", ""),
                      dataset_id=(info or {}).get("dataset_id", ""),
                      pesan_error=pesan)
        ringkasan_query.append({"query": query, "status": status, "ditarik": len(items),
                                "lolos": jumlah_lolos, "gugur": gugur})

    if not semua_baris:
        print("\n  ℹ️ Tidak ada video yang lolos gerbang. Proses selesai tanpa master dataset.")
        print(f"     Periksa: (a) kata kunci pencarian, (b) kata gerbang {gerbang}, "
              f"(c) rentang tanggal {tanggal_min} s/d {tanggal_maks}.")
        return {"jumlah": 0, "ringkasan_query": ringkasan_query}

    # ---------- TAHAP 5: master + gate AI ----------
    print("\n" + "=" * 78)
    print("  MASTER DATASET & GATE AI")
    print("=" * 78)

    master = gabungkan_dan_simpan_master(semua_baris, nama_topik, kaidah,
                                         gunakan_gate_ai=gunakan_gate_ai,
                                         jumlah_mentah=total_mentah,
                                         ringkasan_query=ringkasan_query,
                                         contoh_acuan=daftar_acuan)

    # ---------- TAHAP 6: komentar + analisis sentimen ----------
    hasil_komentar = []
    stat_sentimen = {}
    path_kom_csv = None
    if scrape_comments and master.get("dataset"):
        print("\n" + "=" * 78)
        print("  TAHAP 6: PENARIKAN KOMENTAR & ANALISIS SENTIMEN")
        print("=" * 78)
        daftar_komentar, status_k, pesan_k, info_k = ambil_komentar_tiktok(
            master["dataset"], token, maks_komentar=maks_komentar, top_video=top_video
        )
        if daftar_komentar:
            try:
                from sentiment_analyzer import analisa_sentimen_batch, hitung_statistik_sentimen
                print(f"\n  🤖 Menjalankan Analisis Sentimen IndoBERTweet ({len(daftar_komentar)} komentar)...")
                daftar_komentar = analisa_sentimen_batch(daftar_komentar)
                stat_sentimen = hitung_statistik_sentimen(daftar_komentar)
                path_kom_csv, path_kom_json = simpan_komentar_tiktok(daftar_komentar, nama_topik)
                print(f"\n  📊 Ringkasan Sentimen ({stat_sentimen['total']} komentar):")
                print(f"  * POSITIF : {stat_sentimen['POSITIF']} ({stat_sentimen['POSITIF_pct']})")
                print(f"  * NEGATIF : {stat_sentimen['NEGATIF']} ({stat_sentimen['NEGATIF_pct']})")
                print(f"  * NETRAL  : {stat_sentimen['NETRAL']} ({stat_sentimen['NETRAL_pct']})")
                hasil_komentar = daftar_komentar
            except Exception as e:
                print(f"  ⚠️ Gagal analisis sentimen / simpan komentar: {e}")

    # ---------- ringkasan akhir ----------
    print("\n" + "=" * 78)
    print("  TOTAL SELESAI")
    print("=" * 78)
    for r in ringkasan_query:
        print(f"  - \"{r['query']}\": {r['status']} | ditarik {r['ditarik']} | lolos gerbang {r['lolos']}")
    print(f"\n  Item mentah ditarik  : {total_mentah}")
    kandidat_count = len(semua_baris)
    print(f"  Kandidat lolos gerbang: {kandidat_count}")
    print(f"  Relevan (YA)         : {master['jumlah_ya']}")
    print(f"    - Kota Cirebon     : {master.get('jumlah_kota', 0)}")
    print(f"    - Kabupaten Cirebon: {master.get('jumlah_kab', 0)}")
    print(f"    - Umum/Lainnya     : {master.get('jumlah_none', 0)}")
    print(f"  Tidak relevan (TIDAK): {master['jumlah_ditolak'] - master['jumlah_ragu']}")
    print(f"  Perlu diperiksa (RAGU): {master['jumlah_ragu']}")
    if hasil_komentar:
        print(f"  Komentar Saved       : {len(hasil_komentar)}")
    print(f"  Biaya pencarian run ini: ${total_biaya:.4f}")
    print(f"\n  MASTER (relevan)  : {master['path_csv']}")
    print(f"  - CSV  : {master['path_csv']}")
    if path_kom_csv:
        print(f"  - CSV  : {path_kom_csv}")
    if master.get("path_ditolak"):
        print(f"  DITOLAK/RAGU      : {master['path_ditolak']}   <- periksa, jangan langsung dipercaya")
    print(f"  LAPORAN CORONG    : {master['path_laporan']}")
    if master.get("path_negatif"):
        print(f"  Contoh negatif    : {master['path_negatif']}")

    return {
        "jumlah": master["jumlah"],
        "ringkasan_query": ringkasan_query,
        "master": master,
        "komentar": hasil_komentar,
        "sentimen": stat_sentimen,
    }


# ============================================================
# 3. CLI
# ============================================================
def ambil_argumen():
    parser = argparse.ArgumentParser(description=f"Scrapper monitoring isu Kota Cirebon ({LABEL_PLATFORM})")
    parser.add_argument("--topik", type=str, help='Topik yang dicari, mis. "jalan rusak"')
    parser.add_argument("--contoh", type=str, help="File contoh (URL saja, atau 'URL | caption')")
    parser.add_argument("--contoh-urls", type=str, help="Daftar URL video contoh dipisah koma")
    parser.add_argument("--day", type=int, help="Ambil N hari terakhir")
    parser.add_argument("--month", type=int, help="Ambil N bulan terakhir")
    parser.add_argument("--year", type=int, help="Ambil N tahun terakhir")
    parser.add_argument("--from", dest="dari", type=str, help="Tanggal awal manual YYYY-MM-DD")
    parser.add_argument("--to", dest="sampai", type=str, help="Tanggal akhir manual YYYY-MM-DD")
    parser.add_argument("--max", type=int, default=MAKS_HASIL_PER_QUERY, help="Maks hasil per kata kunci")
    parser.add_argument("--scrape-comments", action="store_true", help="Tarik komentar video terpilih")
    parser.add_argument("--skip-comments", action="store_true", help="Jangan tarik komentar")
    parser.add_argument("--top-video", type=int, default=3, help="Berapa video teratas yang ditarik komentarnya")
    parser.add_argument("--maks-komentar", type=int, default=100, help="Maksimal komentar per video")
    parser.add_argument("--yes", "-y", dest="auto_yes", action="store_true", help="Mode non-interaktif, otomatis konfirmasi")
    parser.add_argument("--dry-run", action="store_true", help="Susun kata kunci + estimasi saja, tanpa scrape")
    parser.add_argument("--no-llm", action="store_true", help="Tanpa gate AI (hanya gerbang wilayah)")
    parser.add_argument("--refresh-query", action="store_true", help="Paksa AI membuat varian kata kunci baru")
    parser.add_argument("--token", type=str, default=None, help="Token Apify (menimpa .env)")
    return parser.parse_args()


def main():
    tampilkan_header()
    args = ambil_argumen()
    token = args.token or ambil_apify_token()

    # ---- input: menu interaktif kalau topik tidak diberikan ----
    if not args.topik:
        masukan = menu_interaktif()
    else:
        preset, jumlah = "day", 30
        if args.day:
            preset, jumlah = "day", args.day
        elif args.month:
            preset, jumlah = "month", args.month
        elif args.year:
            preset, jumlah = "year", args.year

        daftar_contoh = []
        if args.contoh_urls:
            from apify_client import normalisasi_url_tiktok
            urls = [normalisasi_url_tiktok(u.strip()) for u in args.contoh_urls.split(",") if u.strip()]
            daftar_contoh = [{"url": u, "caption": ""} for u in urls if u]
            print(f"  ℹ️ Memakai {len(daftar_contoh)} URL contoh dari argumen")
        elif args.contoh:
            daftar_contoh = baca_file_contoh(args.contoh)
        else:
            path_bawaan = folder_topik(args.topik) / "contoh.txt"
            if path_bawaan.exists():
                daftar_contoh = baca_file_contoh(path_bawaan)
                print(f"  ℹ️ Memakai contoh tersimpan: {path_bawaan}")

        masukan = {
            "nama_topik": args.topik,
            "daftar_contoh": daftar_contoh,
            "preset": preset,
            "jumlah": jumlah,
            "dari": args.dari or "",
            "sampai": args.sampai or "",
            "maks_hasil": args.max,
            "gunakan_gate_ai": not args.no_llm,
            "dry_run": args.dry_run,
        }

    nama_topik = (masukan["nama_topik"] or "").strip()
    if not nama_topik:
        print("❌ Topik kosong. Jalankan lagi dengan --topik \"...\" atau lewat menu interaktif.")
        sys.exit(1)

    daftar_contoh = masukan["daftar_contoh"] or []
    if not daftar_contoh:
        print("\n❌ Belum ada contoh video. Sistem MENOLAK jalan tanpa contoh.")
        print(f"   Isi minimal 1 (disarankan {SARAN_JUMLAH_CONTOH}). Cukup tempel URL TikTok-nya saja.")
        sys.exit(1)

    # ---- caption contoh: ambil otomatis dari URL kalau belum ada ----
    token_sudah_divalidasi = False
    ada_yang_kosong = [c for c in daftar_contoh if not (c.get("caption") or "").strip()]

    if ada_yang_kosong:
        if not AMBIL_CAPTION_CONTOH_OTOMATIS:
            print("\n❌ Caption contoh kosong dan pengambilan otomatis dimatikan di config.py.")
            print("   Tempel caption manual: URL | caption apa adanya")
            sys.exit(1)
        if not token:
            print("\n❌ Butuh token Apify untuk mengambil caption otomatis.")
            print("   Isi APIFY_TOKEN di .env, atau tempel caption manual: URL | caption")
            sys.exit(1)
        if not validasi_token(token):
            print("\n❌ Token Apify tidak bisa dipakai.")
            sys.exit(1)
        token_sudah_divalidasi = True
        print(f"\n  💰 Ambil caption otomatis untuk {len(ada_yang_kosong)} video "
              f"(estimasi ~${len(ada_yang_kosong) * TARIF_ESTIMASI_PER_VIDEO_URL:.3f})")
        try:
            daftar_contoh = lengkapi_caption_dari_url(daftar_contoh, token=token)
        except Exception as e:
            print(f"\n❌ Gagal mengambil caption otomatis: {e}")
            print("   Tempel caption manual: URL | caption apa adanya")
            sys.exit(1)

    # ---- validasi contoh (caption wajib bermakna) ----
    contoh_sah, ditolak = validasi_contoh(daftar_contoh)
    if ditolak:
        print(f"\n⚠️ {len(ditolak)} contoh ditolak:")
        for d in ditolak:
            print(f"   - {d['alasan']}")
    if not contoh_sah:
        print("\n❌ Tidak ada contoh yang sah. Perbaiki URL/caption lalu jalankan lagi.")
        sys.exit(1)
    simpan_contoh(nama_topik, contoh_sah)
    print(f"\n  📚 Contoh acuan yang dipakai AI ({len(contoh_sah)}):")
    for c in caption_contoh_untuk_ai(nama_topik):
        print(f"     - {c[:110]}")

    tanggal_min, tanggal_maks = tentukan_rentang_tanggal(
        preset=masukan["preset"], jumlah=masukan["jumlah"],
        dari=masukan["dari"], sampai=masukan["sampai"],
    )

    # ---- token Apify untuk pencarian (tidak diperlukan saat dry-run) ----
    if not masukan["dry_run"] and not token_sudah_divalidasi:
        if not token:
            print("\n❌ Token Apify tidak ditemukan. Isi APIFY_TOKEN di file .env atau pakai --token.")
            sys.exit(1)
        if not validasi_token(token):
            print("\n❌ Token Apify tidak bisa dipakai.")
            sys.exit(1)
        print("✅ Token Apify sah.")

    pakai_komentar = args.scrape_comments or (not args.skip_comments)
    non_interactive = args.auto_yes or not sys.stdin.isatty()

    jalankan_workflow(
        nama_topik=nama_topik,
        daftar_contoh=contoh_sah,
        tanggal_min=tanggal_min,
        tanggal_maks=tanggal_maks,
        maks_hasil=masukan["maks_hasil"],
        gunakan_gate_ai=masukan["gunakan_gate_ai"],
        dry_run=masukan["dry_run"],
        token=token,
        paksa_ulang_query=args.refresh_query,
        scrape_comments=pakai_komentar,
        top_video=args.top_video,
        maks_komentar=args.maks_komentar,
        non_interactive=non_interactive,
    )


if __name__ == "__main__":
    main()
