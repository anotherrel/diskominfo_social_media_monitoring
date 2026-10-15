# -*- coding: utf-8 -*-
"""
menu_bot.py
===========
OTAK PERCAKAPAN bot: mengubah tekanan tombol / ketikan user menjadi rencana
scraping, lalu menyusun perintah untuk mesin scraper.

REDESIGN 25 Sep 2026:
- Menu dari 5 langkah menjadi 3 langkah + mode cepat
- Teks memakai HTML parse_mode (tebal, miring)
- Bahasa semi-formal ramah untuk pegawai ASN
- Emoji sebagai penanda visual
- Istilah teknis dihilangkan
"""

import json
import re
from datetime import datetime
import requests

import bot_config as cfg
import telegram_api as tg

PATH_SESI = cfg.FOLDER_BOT / "data" / "sesi.json"


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


def normalisasi_url_facebook(url: str, resolve_redirect: bool = True, timeout: int = 8) -> str:
    """
    Normalisasi semua jenis tautan Facebook menjadi canonical URL:
    - Menambahkan skema https:// jika belum ada
    - Mengurai tautan singkat / share link (fb.watch, facebook.com/share/..., l.facebook.com)
    - Menghapus parameter tracking (?ref=..., &__cft__=..., dll)
    """
    u = (url or "").strip().strip("\"'<> ")
    if not u:
        return ""
    if not u.lower().startswith("http://") and not u.lower().startswith("https://"):
        u = "https://" + u

    is_shortlink = any(domain in u.lower() for domain in ["fb.watch", "/share/", "l.facebook.com"])
    if resolve_redirect and is_shortlink:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            resp = requests.get(u, headers=headers, allow_redirects=True, timeout=timeout, stream=True)
            if resp.url and "facebook.com" in resp.url and resp.url != u:
                u = resp.url
        except Exception:
            pass

    u_bersih = u.split("?")[0].rstrip("/")
    return u_bersih

# ============================================================
# 0. SESI PER USER
# ============================================================
_SESI = {}          # {user_id (str): dict sesi}


def _sesi_baru() -> dict:
    return {
        "langkah": "idle",
        "target_jenis": "media",   # "media", "opd", "tiktok", atau "facebook"
        "opd_mode": "ranking",     # "ranking" atau "single"
        "tiktok_topik": "",
        "tiktok_urls": [],
        "facebook_topik": "",
        "facebook_urls": [],
        "akun": [],
        "hari": 7,
        "maks_post": cfg.MAKS_POST_BAWAAN,
        "top": 3,
        "komentar": True,
        "maks_komentar": cfg.MAKS_KOMENTAR_PER_POST,
        "semua_komentar": False,
        "kirim_log": True,
        "pesan_menu": None,
        "diubah": "",
    }


def muat_sesi():
    """Baca sesi dari file (kalau ada). Dipanggil sekali saat bot start."""
    global _SESI
    if not PATH_SESI.exists():
        _SESI = {}
        return
    try:
        isi = json.loads(PATH_SESI.read_text(encoding="utf-8"))
        _SESI = isi if isinstance(isi, dict) else {}
    except Exception:
        _SESI = {}


def simpan_sesi():
    try:
        PATH_SESI.parent.mkdir(parents=True, exist_ok=True)
        PATH_SESI.write_text(json.dumps(_SESI, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as galat:
        print(f"[BOT] Gagal menyimpan sesi: {galat}")


def sesi_user(user_id) -> dict:
    kunci = str(user_id)
    if kunci not in _SESI:
        _SESI[kunci] = _sesi_baru()
    return _SESI[kunci]


def reset_pilihan(sesi: dict):
    """Kosongkan pilihan, tapi pertahankan pengaturan terakhir user sebagai nilai awal."""
    hari = sesi.get("hari", 7)
    maks_post = sesi.get("maks_post", cfg.MAKS_POST_BAWAAN)
    top = sesi.get("top", 3)
    maks_komentar = sesi.get("maks_komentar", cfg.MAKS_KOMENTAR_PER_POST)
    kirim_log = sesi.get("kirim_log", True)
    target_jenis = sesi.get("target_jenis", "media")
    opd_mode = sesi.get("opd_mode", "ranking")
    tiktok_topik = sesi.get("tiktok_topik", "")
    tiktok_urls = list(sesi.get("tiktok_urls") or [])
    facebook_topik = sesi.get("facebook_topik", "")
    facebook_urls = list(sesi.get("facebook_urls") or [])
    baru = _sesi_baru()
    baru.update({"hari": hari, "maks_post": maks_post, "top": top,
                 "maks_komentar": maks_komentar, "kirim_log": kirim_log,
                 "target_jenis": target_jenis, "opd_mode": opd_mode,
                 "tiktok_topik": tiktok_topik, "tiktok_urls": tiktok_urls,
                 "facebook_topik": facebook_topik, "facebook_urls": facebook_urls})
    sesi.clear()
    sesi.update(baru)


# ============================================================
# 1. TEKS & PAPAN TOMBOL (redesign: ringkas, HTML, ramah)
# ============================================================
def t_utama(user_id, nama="") -> str:
    n = tg.esc(nama or 'Bapak/Ibu')
    return (
        f"\U0001f44b <b>Halo, {n}!</b>\n\n"
        "Selamat datang di Sistem Monitoring Media Sosial <b>Kota Cirebon</b>.\n\n"
        "Silakan pilih jenis pemantauan yang ingin dijalankan:"
    )


def kb_utama(user_id) -> dict:
    baris = [
        [tg.tombol("\U0001f4f0 Pantau Media Massa (10 Akun)", "m:mode:media")],
        [tg.tombol("\U0001f3db\ufe0f Keaktifan Akun OPD Pemkot (32 Akun)", "m:mode:opd")],
        [tg.tombol("\U0001f3b5 Pantau Isu TikTok (AI Gate)", "m:mode:tiktok")],
        [tg.tombol("🌐 Pantau Isu Facebook (AI Gate)", "m:mode:facebook")],
        [tg.tombol("\u26a1 Mulai Cepat (Media)", "m:cepat")],
        [tg.tombol("\u2753 Bantuan", "h:bantuan"), tg.tombol("\U0001f4b0 Info Biaya", "h:biaya")],
    ]
    if cfg.user_adalah_admin(user_id):
        baris.append([tg.tombol("\U0001f465 Kelola Pengguna", "a:user")])
    return tg.keyboard(baris)


def t_akun(sesi: dict) -> str:
    terpilih = sesi.get("akun") or []
    baris = [
        "\U0001f4cc <b>Langkah 1 \u2014 Pilih Akun</b>",
        "",
        "Tekan nama akun untuk memilih (boleh lebih dari satu).",
        "Tanda \u2705 berarti sudah terpilih.",
    ]
    if terpilih:
        daftar = ", ".join("@" + tg.esc(a) for a in terpilih)
        baris.append(f"\n\u2705 <b>Terpilih:</b> {daftar}")
    else:
        baris.append("\n<i>Belum ada yang dipilih \u2014 pilih minimal satu akun.</i>")
    return "\n".join(baris)


def kb_akun(sesi: dict) -> dict:
    terpilih = sesi.get("akun") or []
    papan = []
    baris = []
    for i, (username, _folder, nama) in enumerate(cfg.DAFTAR_MEDIA):
        tanda = "\u2705 " if username in terpilih else ""
        baris.append(tg.tombol(f"{tanda}{nama[:26]}", f"m:akun:{i}"))
        if len(baris) == 2:
            papan.append(baris)
            baris = []
    if baris:
        papan.append(baris)

    papan.append([tg.tombol("\u270d Ketik sendiri", "m:akun:ketik"),
                  tg.tombol(f"\u2705 Semua ({len(cfg.DAFTAR_MEDIA)})", "m:akun:semua")])
    if terpilih:
        papan.append([tg.tombol(f"\u25b6\ufe0f Lanjut ({len(terpilih)} akun)", "m:akun:lanjut")])
    papan.append([tg.tombol("\u274c Batal", "m:batal")])
    return tg.keyboard(papan)


def t_setelan(sesi: dict) -> str:
    """Langkah 2: tampilkan semua setelan sekaligus."""
    pakai_kom = sesi.get("komentar", True)
    if pakai_kom:
        teks_kom = f"Ya, {sesi.get('top', 3)} post teratas, maks {sesi.get('maks_komentar', 100)}/post"
        ket_kom = "\n   <i>(Aturan: &lt;100 komentar ditarik semua, &ge;100 ditarik teratas)</i>"
    else:
        teks_kom = "Tidak"
        ket_kom = ""
    return (
        "\u2699\ufe0f <b>Langkah 2 \u2014 Atur Pengambilan</b>\n\n"
        f"\U0001f4c5 Rentang waktu    : <b>{sesi.get('hari', 7)} hari</b>\n"
        f"\U0001f4c4 Batas postingan  : <b>{sesi.get('maks_post', 300)} per akun</b>\n"
        f"\U0001f4ac Ambil komentar   : <b>{tg.esc(teks_kom)}</b>{ket_kom}\n\n"
        "Tekan tombol untuk mengubah, atau langsung <b>Lanjut</b>."
    )


def kb_setelan() -> dict:
    return tg.keyboard([
        [tg.tombol("\U0001f4c5 Ubah Rentang Hari", "m:hari:menu"),
         tg.tombol("\U0001f4c4 Ubah Batas Post", "m:post:menu")],
        [tg.tombol("\U0001f4ac Ubah Komentar", "m:kom:menu"),
         tg.tombol("\U0001f522 Ubah Post Teratas", "m:top:menu")],
        [tg.tombol("\u25b6\ufe0f Lanjut ke Konfirmasi", "m:setelan:lanjut")],
        [tg.tombol("\u2b05\ufe0f Kembali", "m:kembali:akun"),
         tg.tombol("\u274c Batal", "m:batal")],
    ])


def t_hari(sesi: dict) -> str:
    return (
        f"\U0001f4c5 <b>Ubah Rentang Hari</b>\n\n"
        f"Berapa hari ke belakang yang mau diambil?\n\n"
        f"Sekarang: <b>{sesi.get('hari')} hari</b>"
    )


def kb_hari() -> dict:
    return tg.keyboard([
        [tg.tombol("1 hari", "m:hari:1"), tg.tombol("3 hari", "m:hari:3"), tg.tombol("7 hari", "m:hari:7")],
        [tg.tombol("14 hari", "m:hari:14"), tg.tombol("30 hari", "m:hari:30")],
        [tg.tombol("90 hari", "m:hari:90"), tg.tombol("365 hari", "m:hari:365")],
        [tg.tombol("\u270d Ketik sendiri", "m:hari:ketik")],
        [tg.tombol("\u2b05\ufe0f Kembali", "m:kembali:setelan"), tg.tombol("\u274c Batal", "m:batal")],
    ])


def t_post(sesi: dict) -> str:
    return (
        f"\U0001f4c4 <b>Ubah Batas Postingan</b>\n\n"
        f"Berapa postingan terbaru yang diambil dari tiap akun?\n"
        f"Maks {cfg.MAKS_POST_PLAFON} per akun.\n\n"
        f"Sekarang: <b>{sesi.get('maks_post')} post/akun</b>"
    )


def kb_post() -> dict:
    return tg.keyboard([
        [tg.tombol("50", "m:post:50"), tg.tombol("100", "m:post:100")],
        [tg.tombol("300 (bawaan)", "m:post:300"), tg.tombol("500", "m:post:500")],
        [tg.tombol("1000 (maks)", "m:post:1000")],
        [tg.tombol("\u270d Ketik sendiri", "m:post:ketik")],
        [tg.tombol("\u2b05\ufe0f Kembali", "m:kembali:setelan"), tg.tombol("\u274c Batal", "m:batal")],
    ])


def t_top(sesi: dict) -> str:
    return (
        f"\U0001f522 <b>Ubah Jumlah Post untuk Komentar</b>\n\n"
        "Dari postingan yang didapat, berapa yang mau dibaca komentarnya?\n"
        "Yang diambil adalah yang paling banyak komentarnya.\n\n"
        f"Sekarang: <b>{sesi.get('top')} post/akun</b>"
    )


def kb_top() -> dict:
    return tg.keyboard([
        [tg.tombol("1", "m:top:1"), tg.tombol("3", "m:top:3"), tg.tombol("5", "m:top:5")],
        [tg.tombol("\u270d Ketik sendiri", "m:top:ketik")],
        [tg.tombol("\u2b05\ufe0f Kembali", "m:kembali:setelan"), tg.tombol("\u274c Batal", "m:batal")],
    ])


def t_komentar(sesi: dict) -> str:
    if sesi.get("komentar"):
        sekarang = f"Ya, maks {sesi.get('maks_komentar')} komentar/post"
    else:
        sekarang = "Tidak"
    return (
        f"\U0001f4ac <b>Ubah Pengaturan Komentar</b>\n\n"
        "Mau sekalian dibaca isi komentarnya?\n\n"
        "\u2022 <b>Tanpa komentar</b> \u2014 lebih cepat dan murah\n"
        "\u2022 <b>Dengan komentar</b> \u2014 komentar warga dibaca dan digolongkan:\n"
        "   \U0001f7e2 Positif | \U0001f534 Negatif | \u26aa Netral\n\n"
        "ℹ️ <b>Ketentuan per akun:</b>\n"
        "Jika total komentar suatu akun &lt; 100, semua ditarik lengkap. Jika &ge; 100, hanya komentar teratas sesuai batas yang ditarik.\n\n"
        f"Sekarang: <b>{tg.esc(sekarang)}</b>"
    )


def kb_komentar() -> dict:
    baris = [
        [tg.tombol("\u274c Tanpa komentar (lebih cepat)", "m:kom:tidak")],
    ]
    for jumlah in cfg.PILIHAN_KOMENTAR_PER_POST:
        if jumlah <= cfg.MAKS_KOMENTAR_PLAFON:
            total_komentar = 3 * jumlah
            detik = cfg.DETIK_MUAT_MODEL + total_komentar * cfg.DETIK_PER_KOMENTAR_SENTIMEN
            menit = max(1, int(round(detik / 60)))
            baris.append([tg.tombol(f"\u2705 Maks {jumlah}/post (~{menit} menit)",
                                    f"m:kom:{jumlah}")])
    baris.append([tg.tombol("\u270d Ketik sendiri", "m:kom:ketik")])
    baris.append([tg.tombol("\u2b05\ufe0f Kembali", "m:kembali:setelan"), tg.tombol("\u274c Batal", "m:batal")])
    return tg.keyboard(baris)


def t_konfirmasi(sesi: dict) -> str:
    akun = sesi.get("akun") or []
    daftar = ", ".join("@" + tg.esc(a) for a in akun[:5])
    if len(akun) > 5:
        daftar += f" +{len(akun)-5} lagi"
    pakai_komentar = bool(sesi.get("komentar", True))

    perkiraan = cfg.hitung_perkiraan_durasi(
        len(akun), sesi.get("top", 1), pakai_komentar, sesi.get("maks_komentar"))
    estimasi = cfg.hitung_estimasi_biaya(
        len(akun), sesi.get("hari", 7), sesi.get("top", 1), pakai_komentar,
        sesi.get("maks_post"), sesi.get("maks_komentar"))

    if pakai_komentar:
        maks_k = sesi.get('maks_komentar', 100)
        teks_kom = f"Ya, {sesi.get('top')} post teratas, maks {maks_k}/post"
        info_aturan_kom = (
            "\nℹ️ <b>Ketentuan komentar per akun:</b>\n"
            "• Jika komentar suatu akun &lt; 100 \u2192 semua ditarik lengkap.\n"
            f"• Jika komentar suatu akun &ge; 100 \u2192 ditarik teratas (maks {maks_k}/post).\n"
        )
    else:
        teks_kom = "Tidak"
        info_aturan_kom = ""

    biaya_idr = estimasi.get('total_nyata_idr') or estimasi.get('total_idr', 0)

    return (
        "\U0001f4cb <b>Ringkasan Pemantauan</b>\n\n"
        f"\U0001f464 Akun        : <b>{len(akun)} akun</b> ({daftar})\n"
        f"\U0001f4c5 Rentang     : <b>{sesi.get('hari')} hari</b> terakhir\n"
        f"\U0001f4c4 Postingan   : maks <b>{sesi.get('maks_post')}</b>/akun\n"
        f"\U0001f4ac Komentar    : <b>{tg.esc(teks_kom)}</b>\n"
        f"{info_aturan_kom}\n"
        f"\u23f1 Perkiraan waktu : <b>~{tg.esc(perkiraan.get('total_teks', '-'))}</b>\n"
        f"\U0001f4b0 Perkiraan biaya : <b>~Rp{biaya_idr:,}</b>\n\n"
        "Tekan <b>\u2705 MULAI</b> jika sudah sesuai."
    )


def kb_konfirmasi() -> dict:
    return tg.keyboard([
        [tg.tombol("\u2705 MULAI", "m:jalankan")],
        [tg.tombol("\u270f\ufe0f Ubah Setelan", "m:ubah:setelan"), tg.tombol("\u274c Batal", "m:batal")],
        [tg.tombol("\U0001f4b0 Detail Biaya & Waktu", "h:biaya")],
    ])


def t_bantuan() -> str:
    return (
        "\u2753 <b>Bantuan</b>\n\n"
        "Bot ini memantau akun Instagram yang membahas "
        "<b>Kota Cirebon</b>, lalu mengirimkan laporan ke chat ini.\n\n"
        "<b>Cara pakai:</b>\n"
        "1\ufe0f\u20e3 Tekan <b>Mulai Pantau</b>\n"
        "2\ufe0f\u20e3 Pilih akun yang mau dipantau\n"
        "3\ufe0f\u20e3 Atur rentang hari &amp; opsi lainnya\n"
        "4\ufe0f\u20e3 Periksa ringkasan, lalu tekan <b>MULAI</b>\n\n"
        "<b>Perintah:</b>\n"
        "/start \u2014 Menu utama\n"
        "/bantuan \u2014 Pesan ini\n"
        "/status \u2014 Status pekerjaan\n"
        "/batal \u2014 Batalkan pengisian\n"
    )


def t_biaya() -> str:
    return (
        "\U0001f4b0 <b>Info Biaya &amp; Waktu</b>\n\n"
        "Pengambilan data memakai layanan pihak ketiga yang ditagih "
        "sesuai jumlah data yang terkumpul.\n\n"
        f"<b>Tarif saat ini:</b>\n"
        f"\u2022 Postingan : ${cfg.TARIF_POST_PER_HASIL}/data\n"
        f"\u2022 Komentar : ${cfg.TARIF_KOMENTAR_PER_HASIL}/data\n"
        f"\u2022 Kurs : Rp{cfg.KURS_USD_IDR:,}/dolar\n\n"
        "\U0001f4a1 <b>Tips hemat:</b> Batasi jumlah komentar per postingan \u2014 "
        "makin sedikit, makin cepat dan murah."
    )


def t_status(user_id) -> str:
    sesi = sesi_user(user_id)
    try:
        import job_runner
        info_antrean = job_runner.status_ringkas()
    except Exception:
        info_antrean = "mesin belum aktif"

    akun_teks = ', '.join('@' + a for a in (sesi.get('akun') or [])) or '(belum ada)'
    return (
        "\U0001f4ca <b>Status</b>\n\n"
        f"Akun dipilih   : {tg.esc(akun_teks)}\n"
        f"Rentang hari   : {sesi.get('hari')} hari\n"
        f"Batas post     : {sesi.get('maks_post')}/akun\n"
        f"Komentar       : {'Ya' if sesi.get('komentar') else 'Tidak'}\n\n"
        f"\U0001f4e6 {tg.esc(info_antrean)}"
    )


def t_admin_user() -> str:
    daftar = cfg.daftar_user_efektif()
    baris = ["\U0001f465 <b>Kelola Pengguna</b>", "",
             f"Pengguna yang boleh memakai bot: <b>{len(daftar)}</b>"]
    for uid in daftar:
        tanda = " (admin)" if uid in cfg.ADMIN_USER_IDS else ""
        baris.append(f"  \u2022 {uid}{tanda}")
    baris.append("")
    baris.append("<i>Admin dari file .env tidak bisa dicabut dari sini \u2014 pengaman supaya bot tidak terkunci.</i>")
    return "\n".join(baris)


def kb_admin_user() -> dict:
    return tg.keyboard([
        [tg.tombol("\u2795 Tambah pengguna", "a:user:tambah"), tg.tombol("\u2796 Cabut akses", "a:user:hapus")],
        [tg.tombol("\U0001f3e0 Menu utama", "h:menu")],
    ])


# ============================================================
# 1b. MENU KHUSUS AKUN OPD PEMERINTAH KOTA CIREBON (32 AKUN)
# ============================================================
def t_opd_hari(sesi: dict) -> str:
    return (
        f"\U0001f4c5 <b>Pilih Rentang Waktu Pemantauan OPD</b>\n\n"
        f"Sasaran: <b>Semua 32 Akun OPD &amp; Kecamatan Kota Cirebon</b>\n\n"
        "Berapa hari ke belakang postingan yang ingin ditarik?\n\n"
        f"Sekarang: <b>{sesi.get('hari', 30)} hari</b>"
    )


def kb_opd_hari() -> dict:
    return tg.keyboard([
        [tg.tombol("7 hari (1 pekan)", "m:opd_hari:7"), tg.tombol("14 hari (2 pekan)", "m:opd_hari:14")],
        [tg.tombol("30 hari (1 bulan)", "m:opd_hari:30"), tg.tombol("90 hari (3 bulan)", "m:opd_hari:90")],
        [tg.tombol("\u270d Ketik sendiri", "m:hari:ketik")],
        [tg.tombol("\u2b05\ufe0f Kembali", "m:mode:opd"), tg.tombol("\u274c Batal", "m:batal")],
    ])


def t_konfirmasi_opd_ranking(sesi: dict) -> str:
    total_akun = len(getattr(cfg, "DAFTAR_OPD", []))
    hari = sesi.get("hari", 30)
    perkiraan_detik = max(60, total_akun * 6)  # ~3-4 menit untuk post 32 akun
    menit = perkiraan_detik // 60
    biaya_est = int(total_akun * 15 * 0.0023 * cfg.KURS_USD_IDR)  # asumsi ~15 post/akun

    return (
        "\U0001f3c6 <b>Konfirmasi Klasemen Keaktifan OPD</b>\n\n"
        f"\U0001f465 Jumlah akun   : <b>{total_akun} Akun OPD &amp; Kecamatan</b>\n"
        f"\U0001f4c5 Rentang waktu : <b>{hari} hari</b> terakhir\n"
        f"\U0001f4ca Penilaian     : <b>Total Postingan + Total Likes + Total Komentar</b>\n\n"
        f"\u23f1 Perkiraan waktu: <b>~{menit} menit</b>\n"
        f"\U0001f4b0 Perkiraan biaya: <b>~Rp{biaya_est:,}</b>\n\n"
        "Tekan <b>\u2705 MULAI PERINGKAT</b> untuk menjalankan."
    )


def kb_konfirmasi_opd_ranking() -> dict:
    return tg.keyboard([
        [tg.tombol("\u2705 MULAI PERINGKAT", "m:jalankan")],
        [tg.tombol("\U0001f4c5 Ubah Rentang Hari", "m:opd_hari:menu"), tg.tombol("\u274c Batal", "m:batal")],
    ])


def t_opd_multi_pilih(sesi: dict, hal: int = 0) -> str:
    terpilih = sesi.get("opd_pilih") or []
    total_hal = 3
    judul_hal = ["Dinas & Badan (Bagian 1)", "Dinas & Badan (Bagian 2)", "Kecamatan (5 Akun)"][min(hal, 2)]

    baris = [
        "📥 <b>Pilih Akun OPD untuk Mengunduh Dataset Postingan</b>",
        "",
        f"Kategori: <b>{judul_hal}</b> (Hal {hal+1}/{total_hal})",
        "",
        "Tekan nama dinas/kecamatan di bawah untuk memilih (bisa lebih dari satu).",
        "Tanda ✅ berarti sudah terpilih.",
    ]
    if terpilih:
        daftar = ", ".join("@" + tg.esc(u) for u in terpilih[:6])
        if len(terpilih) > 6:
            daftar += f" +{len(terpilih)-6} lagi"
        baris.append(f"\n✅ <b>Terpilih ({len(terpilih)} akun):</b> {daftar}")
    else:
        baris.append("\n<i>Belum ada akun yang dipilih.</i>")
    return "\n".join(baris)


def kb_opd_multi_pilih(sesi: dict, hal: int = 0) -> dict:
    terpilih = sesi.get("opd_pilih") or []
    daftar_opd = getattr(cfg, "DAFTAR_OPD", [])
    if hal == 0:
        sub = daftar_opd[:14]
    elif hal == 1:
        sub = daftar_opd[14:27]
    else:
        sub = daftar_opd[27:]

    papan = []
    baris = []
    for u, f, n, k in sub:
        tanda = "✅ " if u in terpilih else ""
        idx_global = daftar_opd.index((u, f, n, k)) if (u, f, n, k) in daftar_opd else 0
        baris.append(tg.tombol(f"{tanda}{n[:22]}", f"opd_sel:tog:{idx_global}"))
        if len(baris) == 2:
            papan.append(baris)
            baris = []
    if baris:
        papan.append(baris)

    # Navigasi halaman
    nav = []
    if hal > 0:
        nav.append(tg.tombol("⬅️ Sebelumnya", f"opd_sel:page:{hal-1}"))
    if hal < 2:
        nav.append(tg.tombol("Selanjutnya ➡️", f"opd_sel:page:{hal+1}"))
    if nav:
        papan.append(nav)

    # Tombol kirim berkas terpilih
    if terpilih:
        papan.append([tg.tombol(f"📥 Kirim CSV Post ({len(terpilih)} Akun)", "opd_sel:kirim")])
    else:
        papan.append([tg.tombol("📥 Kirim CSV Post (Pilih Akun)", "opd_sel:kirim")])

    papan.append([tg.tombol("✅ Pilih Semua (32)", "opd_sel:semua"), tg.tombol("🔄 Reset Pilihan", "opd_sel:reset")])
    papan.append([tg.tombol("🏠 Selesai / Menu Utama", "h:menu")])
    return tg.keyboard(papan)


# ============================================================
# 1d. MENU PEMANTAUAN ISU TIKTOK (AI GATE)
# ============================================================
def t_tiktok_topik(sesi: dict) -> str:
    topik = sesi.get("tiktok_topik", "")
    baris = [
        "🎵 <b>Pantau Isu TikTok — Langkah 1: Masukkan Topik / Isu</b>",
        "",
        "Ketik isu atau kata kunci permasalahan di <b>Kota Cirebon</b> yang ingin Anda pantau.",
        "",
        "<i>Contoh: jalan rusak cipto, lampu merah perumnas, banjir kalijaga, becak listrik</i>",
    ]
    if topik:
        baris.append(f"\n✅ <b>Topik saat ini:</b> <code>{tg.esc(topik)}</code>")
    return "\n".join(baris)


def kb_tiktok_topik(sesi: dict) -> dict:
    baris = []
    if sesi.get("tiktok_topik"):
        baris.append([tg.tombol("▶️ Lanjut ke Video Contoh", "m:tiktok:topik_lanjut")])
    baris.append([tg.tombol("❌ Batal", "m:batal")])
    return tg.keyboard(baris)


def t_tiktok_urls(sesi: dict) -> str:
    urls = sesi.get("tiktok_urls") or []
    topik = sesi.get("tiktok_topik", "Isu")
    baris = [
        "🎵 <b>Langkah 2: Masukkan Contoh Video Acuan</b>",
        "",
        f"Topik: <b>{tg.esc(topik)}</b>",
        "",
        "AI membutuhkan minimal <b>1 video acuan</b> (disarankan <b>3-5 video</b>) untuk mempelajari konteks isu sebelum menarik video massal.",
        "",
        "🌐 <b>Semua jenis link TikTok didukung:</b>",
        "• Link aplikasi hp: <code>vm.tiktok.com/...</code> atau <code>vt.tiktok.com/...</code>",
        "• Link web desktop: <code>tiktok.com/@user/video/...</code>",
        "• Postingan foto/slideshow: <code>tiktok.com/@user/photo/...</code>",
        "• Link pendek: <code>tiktok.com/t/...</code>",
        "",
        "<b>Cara isi:</b> Salin link video TikTok dan kirimkan ke chat ini (boleh 1 per 1 atau sekaligus dipisah baris/koma).",
        "",
        f"📊 <b>Status:</b> {len(urls)} video terkumpul (min 1, saran 3-5)",
    ]
    if urls:
        baris.append("\n<b>Daftar Video Acuan:</b>")
        for idx, u in enumerate(urls, 1):
            pendek = u.split("?")[0]
            if len(pendek) > 48:
                pendek = pendek[:26] + "..." + pendek[-16:]
            baris.append(f"  {idx}. <code>{tg.esc(pendek)}</code>")
    else:
        baris.append("\n<i>Belum ada video acuan. Silakan tempel link video TikTok sekarang.</i>")
    return "\n".join(baris)


def kb_tiktok_urls(sesi: dict) -> dict:
    urls = sesi.get("tiktok_urls") or []
    baris = []
    if len(urls) >= 1:
        saran = " (Saran: 3-5)" if len(urls) < 3 else ""
        baris.append([tg.tombol(f"▶️ Lanjut ({len(urls)} Video Acuan){saran}", "m:tiktok:urls_lanjut")])
    else:
        baris.append([tg.tombol("⏳ Tempel minimal 1 link TikTok...", "noop")])

    baris.append([tg.tombol("🔄 Reset Link", "m:tiktok:urls_reset"), tg.tombol("✏️ Ubah Topik", "m:tiktok:ubah_topik")])
    baris.append([tg.tombol("❌ Batal", "m:batal")])
    return tg.keyboard(baris)


def t_tiktok_setelan(sesi: dict) -> str:
    pakai_kom = sesi.get("komentar", True)
    if pakai_kom:
        teks_kom = f"Ya ({sesi.get('top', 3)} video teratas, maks {sesi.get('maks_komentar', 100)}/video + IndoBERTweet)"
    else:
        teks_kom = "Tidak (hanya postingan video)"

    return (
        "⚙️ <b>Langkah 3 — Atur Pemantauan TikTok</b>\n\n"
        f"📌 Topik Isu      : <b>{tg.esc(sesi.get('tiktok_topik', '-'))}</b>\n"
        f"🎬 Video Acuan    : <b>{len(sesi.get('tiktok_urls') or [])} video</b>\n"
        f"📅 Rentang Waktu  : <b>{sesi.get('hari', 30)} hari terakhir</b>\n"
        f"💬 Analisis Komen : <b>{tg.esc(teks_kom)}</b>\n\n"
        "Tekan tombol di bawah untuk mengubah setelan, atau tekan <b>Lanjut</b>."
    )


def kb_tiktok_setelan() -> dict:
    return tg.keyboard([
        [tg.tombol("📅 Ubah Rentang Hari", "m:tiktok:hari_menu"),
         tg.tombol("💬 Ubah Opsi Komentar", "m:tiktok:kom_menu")],
        [tg.tombol("▶️ Lanjut ke Konfirmasi", "m:tiktok:setelan_lanjut")],
        [tg.tombol("⬅️ Kembali ke Link", "m:tiktok:kembali_urls"),
         tg.tombol("❌ Batal", "m:batal")],
    ])


def t_tiktok_hari(sesi: dict) -> str:
    return (
        "📅 <b>Pilih Rentang Hari Pemantauan TikTok</b>\n\n"
        f"Berapa hari ke belakang video TikTok yang ingin ditarik?\n"
        f"Sekarang: <b>{sesi.get('hari', 30)} hari</b>"
    )


def kb_tiktok_hari() -> dict:
    return tg.keyboard([
        [tg.tombol("7 Hari", "m:tiktok:hari:7"), tg.tombol("14 Hari", "m:tiktok:hari:14")],
        [tg.tombol("30 Hari (Standar)", "m:tiktok:hari:30"), tg.tombol("90 Hari", "m:tiktok:hari:90")],
        [tg.tombol("365 Hari (1 Tahun)", "m:tiktok:hari:365"), tg.tombol("730 Hari (2 Tahun)", "m:tiktok:hari:730")],
        [tg.tombol("✍️ Ketik Hari Sendiri", "m:tiktok:hari:ketik")],
        [tg.tombol("⬅️ Kembali", "m:tiktok:setelan"), tg.tombol("❌ Batal", "m:batal")],
    ])


def t_tiktok_komentar(sesi: dict) -> str:
    return (
        "💬 <b>Pengaturan Penarikan Komentar TikTok</b>\n\n"
        "Apakah Anda ingin menarik komentar dari video terpopuler dan menjalankan analisis sentimen warga (IndoBERTweet)?\n\n"
        "• <b>Ya</b>: Mengambil komentar dari 3 video dengan komentar terbanyak (maks 100/video), lalu mendeteksi tanggapan Positif / Negatif / Netral.\n"
        "• <b>Tidak</b>: Hanya mengambil data postingan video saja (lebih cepat).\n\n"
        f"Sekarang: <b>{'Ya' if sesi.get('komentar', True) else 'Tidak'}</b>"
    )


def kb_tiktok_komentar() -> dict:
    return tg.keyboard([
        [tg.tombol("✅ Ya, Analisis Komentar", "m:tiktok:kom:ya")],
        [tg.tombol("❌ Tidak, Postingan Saja", "m:tiktok:kom:tidak")],
        [tg.tombol("⬅️ Kembali", "m:tiktok:setelan")],
    ])


def t_tiktok_konfirmasi(sesi: dict) -> str:
    urls = sesi.get("tiktok_urls") or []
    topik = sesi.get("tiktok_topik", "-")
    pakai_komentar = bool(sesi.get("komentar", True))
    hari = sesi.get("hari", 30)

    durasi_menit = 3 if pakai_komentar else 2

    return (
        "📋 <b>Ringkasan Pemantauan Isu TikTok</b>\n\n"
        f"📌 Topik Isu      : <b>{tg.esc(topik)}</b>\n"
        f"🎬 Video Acuan    : <b>{len(urls)} video contoh</b>\n"
        f"📅 Rentang Waktu  : <b>{hari} hari terakhir</b>\n"
        "🤖 AI Reasoning   : <b>gpt-5.6-luna (AI Gate & Query Builder)</b>\n"
        f"💬 Analisis Komen : <b>{'Ya (IndoBERTweet Sentimen)' if pakai_komentar else 'Tidak'}</b>\n\n"
        f"⏱️ Perkiraan Waktu: <b>~{durasi_menit} - {durasi_menit + 2} menit</b>\n"
        "📍 Sasaran Wilayah: <b>Kota Cirebon</b> (Kaidah Wilayah Aktif)\n\n"
        "Tekan <b>✅ MULAI PANTAU</b> untuk menjalankan proses."
    )


def kb_tiktok_konfirmasi() -> dict:
    return tg.keyboard([
        [tg.tombol("✅ MULAI PANTAU", "m:jalankan")],
        [tg.tombol("✏️ Ubah Setelan", "m:tiktok:setelan"), tg.tombol("❌ Batal", "m:batal")],
    ])


# ============================================================
# 1e. MENU PEMANTAUAN ISU FACEBOOK (AI GATE)
# ============================================================
def t_facebook_topik(sesi: dict) -> str:
    topik = sesi.get("facebook_topik", "")
    baris = [
        "🌐 <b>Pantau Isu Facebook — Langkah 1: Masukkan Topik / Isu</b>",
        "",
        "Ketik isu atau kata kunci permasalahan di <b>Kota Cirebon</b> yang ingin Anda pantau di Facebook.",
        "",
        "<i>Contoh: banjir cirebon, jalan rusak plumbon, bansos kota cirebon, pdam mati</i>",
    ]
    if topik:
        baris.append(f"\n✅ <b>Topik saat ini:</b> <code>{tg.esc(topik)}</code>")
    return "\n".join(baris)


def kb_facebook_topik(sesi: dict) -> dict:
    baris = []
    if sesi.get("facebook_topik"):
        baris.append([tg.tombol("▶️ Lanjut ke Postingan Contoh", "m:facebook:topik_lanjut")])
    baris.append([tg.tombol("❌ Batal", "m:batal")])
    return tg.keyboard(baris)


def t_facebook_urls(sesi: dict) -> str:
    urls = sesi.get("facebook_urls") or []
    topik = sesi.get("facebook_topik", "Isu")
    baris = [
        "🌐 <b>Langkah 2: Masukkan Contoh Postingan Acuan</b>",
        "",
        f"Topik: <b>{tg.esc(topik)}</b>",
        "",
        "AI membutuhkan minimal <b>1 postingan acuan</b> (disarankan <b>3-5 postingan</b>) untuk mempelajari konteks isu sebelum menarik data massal.",
        "",
        "🌐 <b>Semua jenis link Facebook didukung:</b>",
        "• Link postingan: <code>facebook.com/.../posts/...</code>",
        "• Link video/reels: <code>facebook.com/watch/...</code> atau <code>fb.watch/...</code>",
        "• Link share: <code>facebook.com/share/p/...</code>",
        "",
        "<b>Cara isi:</b> Salin link postingan Facebook dan kirimkan ke chat ini (boleh 1 per 1 atau dipisah baris/koma).",
        "",
        f"📊 <b>Status:</b> {len(urls)} postingan terkumpul (min 1, saran 3-5)",
    ]
    if urls:
        baris.append("\n<b>Daftar Postingan Acuan:</b>")
        for idx, u in enumerate(urls, 1):
            pendek = u.split("?")[0]
            if len(pendek) > 48:
                pendek = pendek[:26] + "..." + pendek[-16:]
            baris.append(f"  {idx}. <code>{tg.esc(pendek)}</code>")
    else:
        baris.append("\n<i>Belum ada postingan acuan. Silakan tempel link Facebook sekarang.</i>")
    return "\n".join(baris)


def kb_facebook_urls(sesi: dict) -> dict:
    urls = sesi.get("facebook_urls") or []
    baris = []
    if len(urls) >= 1:
        saran = " (Saran: 3-5)" if len(urls) < 3 else ""
        baris.append([tg.tombol(f"▶️ Lanjut ({len(urls)} Postingan Acuan){saran}", "m:facebook:urls_lanjut")])
    else:
        baris.append([tg.tombol("⏳ Tempel minimal 1 link Facebook...", "noop")])

    baris.append([tg.tombol("🔄 Reset Link", "m:facebook:urls_reset"), tg.tombol("✏️ Ubah Topik", "m:facebook:ubah_topik")])
    baris.append([tg.tombol("❌ Batal", "m:batal")])
    return tg.keyboard(baris)


def t_facebook_setelan(sesi: dict) -> str:
    pakai_kom = sesi.get("komentar", True)
    if pakai_kom:
        teks_kom = f"Ya ({sesi.get('top', 3)} post teratas, maks {sesi.get('maks_komentar', 100)}/post + IndoBERTweet)"
    else:
        teks_kom = "Tidak (hanya postingan)"

    return (
        "⚙️ <b>Langkah 3 — Atur Pemantauan Facebook</b>\n\n"
        f"📌 Topik Isu      : <b>{tg.esc(sesi.get('facebook_topik', '-'))}</b>\n"
        f"📄 Postingan Acuan: <b>{len(sesi.get('facebook_urls') or [])} post</b>\n"
        f"📅 Rentang Waktu  : <b>{sesi.get('hari', 30)} hari terakhir</b>\n"
        f"💬 Analisis Komen : <b>{tg.esc(teks_kom)}</b>\n\n"
        "Tekan tombol di bawah untuk mengubah setelan, atau tekan <b>Lanjut</b>."
    )


def kb_facebook_setelan() -> dict:
    return tg.keyboard([
        [tg.tombol("📅 Ubah Rentang Hari", "m:facebook:hari_menu"),
         tg.tombol("💬 Ubah Opsi Komentar", "m:facebook:kom_menu")],
        [tg.tombol("▶️ Lanjut ke Konfirmasi", "m:facebook:setelan_lanjut")],
        [tg.tombol("⬅️ Kembali ke Link", "m:facebook:kembali_urls"),
         tg.tombol("❌ Batal", "m:batal")],
    ])


def t_facebook_hari(sesi: dict) -> str:
    return (
        "📅 <b>Pilih Rentang Hari Pemantauan Facebook</b>\n\n"
        f"Berapa hari ke belakang postingan Facebook yang ingin ditarik?\n"
        f"Sekarang: <b>{sesi.get('hari', 30)} hari</b>"
    )


def kb_facebook_hari() -> dict:
    return tg.keyboard([
        [tg.tombol("7 Hari", "m:facebook:hari:7"), tg.tombol("14 Hari", "m:facebook:hari:14")],
        [tg.tombol("30 Hari (Standar)", "m:facebook:hari:30"), tg.tombol("90 Hari", "m:facebook:hari:90")],
        [tg.tombol("365 Hari (1 Tahun)", "m:facebook:hari:365"), tg.tombol("730 Hari (2 Tahun)", "m:facebook:hari:730")],
        [tg.tombol("✍️ Ketik Hari Sendiri", "m:facebook:hari:ketik")],
        [tg.tombol("⬅️ Kembali", "m:facebook:setelan"), tg.tombol("❌ Batal", "m:batal")],
    ])


def t_facebook_komentar(sesi: dict) -> str:
    return (
        "💬 <b>Pengaturan Penarikan Komentar Facebook</b>\n\n"
        "Apakah Anda ingin menarik komentar dari postingan terpopuler dan menjalankan analisis sentimen warga (IndoBERTweet)?\n\n"
        "• <b>Ya</b>: Mengambil komentar dari 3 postingan dengan komentar terbanyak (maks 100/post), lalu mendeteksi tanggapan Positif / Negatif / Netral.\n"
        "• <b>Tidak</b>: Hanya mengambil data postingan saja (lebih cepat).\n\n"
        f"Sekarang: <b>{'Ya' if sesi.get('komentar', True) else 'Tidak'}</b>"
    )


def kb_facebook_komentar() -> dict:
    return tg.keyboard([
        [tg.tombol("✅ Ya, Analisis Komentar", "m:facebook:kom:ya")],
        [tg.tombol("❌ Tidak, Postingan Saja", "m:facebook:kom:tidak")],
        [tg.tombol("⬅️ Kembali", "m:facebook:setelan")],
    ])


def t_facebook_konfirmasi(sesi: dict) -> str:
    urls = sesi.get("facebook_urls") or []
    topik = sesi.get("facebook_topik", "-")
    pakai_komentar = bool(sesi.get("komentar", True))
    hari = sesi.get("hari", 30)

    durasi_menit = 3 if pakai_komentar else 2

    return (
        "📋 <b>Ringkasan Pemantauan Isu Facebook</b>\n\n"
        f"📌 Topik Isu      : <b>{tg.esc(topik)}</b>\n"
        f"📄 Post Acuan     : <b>{len(urls)} postingan contoh</b>\n"
        f"📅 Rentang Waktu  : <b>{hari} hari terakhir</b>\n"
        "🤖 AI Reasoning   : <b>gpt-5.6-luna (AI Gate & Query Builder)</b>\n"
        f"💬 Analisis Komen : <b>{'Ya (IndoBERTweet Sentimen)' if pakai_komentar else 'Tidak'}</b>\n\n"
        f"⏱️ Perkiraan Waktu: <b>~{durasi_menit} - {durasi_menit + 2} menit</b>\n"
        "📍 Sasaran Wilayah: <b>Kota Cirebon</b> (Kaidah Wilayah Aktif)\n\n"
        "Tekan <b>✅ MULAI PANTAU</b> untuk menjalankan proses."
    )


def kb_facebook_konfirmasi() -> dict:
    return tg.keyboard([
        [tg.tombol("✅ MULAI PANTAU", "m:jalankan")],
        [tg.tombol("✏️ Ubah Setelan", "m:facebook:setelan"), tg.tombol("❌ Batal", "m:batal")],
    ])


# ============================================================
# 2. PENYUSUN PERINTAH UNTUK MESIN SCRAPER
# ============================================================
def susun_perintah(sesi: dict) -> list:
    """
    Ubah sesi menjadi daftar argumen untuk cirebon_media, cirebon_opd, atau tiktok.
    """
    if sesi.get("target_jenis") == "tiktok":
        perintah = [
            str(cfg.SKRIP_SCRAPER_TIKTOK),
            "--topik", str(sesi.get("tiktok_topik", "")),
            "--day", str(sesi.get("hari", 30)),
            "--yes",
        ]
        if sesi.get("tiktok_urls"):
            perintah += ["--contoh-urls", ",".join(sesi["tiktok_urls"])]
        if sesi.get("komentar", True):
            perintah += [
                "--scrape-comments",
                "--top-video", str(sesi.get("top", 3)),
                "--maks-komentar", str(sesi.get("maks_komentar", 100)),
            ]
        else:
            perintah += ["--skip-comments"]
        return perintah

    if sesi.get("target_jenis") == "facebook":
        perintah = [
            str(cfg.SKRIP_SCRAPER_FACEBOOK),
            "--topik", str(sesi.get("facebook_topik", "")),
            "--day", str(sesi.get("hari", 30)),
            "--yes",
        ]
        if sesi.get("facebook_urls"):
            perintah += ["--contoh-urls", ",".join(sesi["facebook_urls"])]
        if sesi.get("komentar", True):
            perintah += [
                "--scrape-comments",
                "--top-video", str(sesi.get("top", 3)),
                "--maks-komentar", str(sesi.get("maks_komentar", 100)),
            ]
        else:
            perintah += ["--skip-comments"]
        return perintah

    if sesi.get("target_jenis") == "opd":
        return [
            str(cfg.SKRIP_SCRAPER_OPD),
            "--hari", str(sesi.get("hari", 30)),
            "--maks-post", str(sesi.get("maks_post", 50)),
        ]

    perintah = [str(cfg.SKRIP_SCRAPER)]
    if sesi.get("akun"):
        perintah += ["--akun", ",".join(sesi["akun"])]
    perintah += ["--hari", str(sesi.get("hari", 7))]
    perintah += ["--maks-post", str(sesi.get("maks_post", cfg.MAKS_POST_BAWAAN))]
    perintah += ["--top-video", str(sesi.get("top", 3))]
    perintah += ["--maks-komentar", str(sesi.get("maks_komentar", cfg.MAKS_KOMENTAR_PER_POST))]
    perintah.append("--scrape-comments" if sesi.get("komentar", True) else "--skip-comments")
    return perintah


# ============================================================
# 3. ROUTER: SATU PINTU MASUK
# ============================================================
def _tampilkan(pengirim, chat_id, sesi: dict, teks: str, papan: dict, message_id: int = None):
    if message_id:
        hasil = pengirim.edit_pesan(chat_id, message_id, teks, papan)
        if hasil is not None:
            sesi["pesan_menu"] = message_id
            return
    dikirim = pengirim.kirim_pesan(chat_id, teks, papan_tombol=papan)
    if isinstance(dikirim, dict):
        sesi["pesan_menu"] = dikirim.get("message_id")


def kirim_langkah(pengirim, chat_id, user_id, sesi: dict, message_id: int = None):
    """Tampilkan layar sesuai langkah sesi saat ini."""
    langkah = sesi.get("langkah", "idle")
    if langkah == "akun":
        _tampilkan(pengirim, chat_id, sesi, t_akun(sesi), kb_akun(sesi), message_id)
    elif langkah == "setelan":
        _tampilkan(pengirim, chat_id, sesi, t_setelan(sesi), kb_setelan(), message_id)
    elif langkah == "hari":
        _tampilkan(pengirim, chat_id, sesi, t_hari(sesi), kb_hari(), message_id)
    elif langkah == "post":
        _tampilkan(pengirim, chat_id, sesi, t_post(sesi), kb_post(), message_id)
    elif langkah == "top":
        _tampilkan(pengirim, chat_id, sesi, t_top(sesi), kb_top(), message_id)
    elif langkah == "komentar":
        _tampilkan(pengirim, chat_id, sesi, t_komentar(sesi), kb_komentar(), message_id)
    elif langkah == "konfirmasi":
        _tampilkan(pengirim, chat_id, sesi, t_konfirmasi(sesi), kb_konfirmasi(), message_id)
    elif langkah == "opd_hari":
        _tampilkan(pengirim, chat_id, sesi, t_opd_hari(sesi), kb_opd_hari(), message_id)
    elif langkah in ("opd_menu", "konfirmasi_opd_ranking"):
        _tampilkan(pengirim, chat_id, sesi, t_konfirmasi_opd_ranking(sesi), kb_konfirmasi_opd_ranking(), message_id)
    elif langkah == "opd_multi_pilih":
        hal = int(sesi.get("opd_hal", 0))
        _tampilkan(pengirim, chat_id, sesi, t_opd_multi_pilih(sesi, hal), kb_opd_multi_pilih(sesi, hal), message_id)
    elif langkah == "tiktok_topik":
        _tampilkan(pengirim, chat_id, sesi, t_tiktok_topik(sesi), kb_tiktok_topik(sesi), message_id)
    elif langkah == "tiktok_urls":
        _tampilkan(pengirim, chat_id, sesi, t_tiktok_urls(sesi), kb_tiktok_urls(sesi), message_id)
    elif langkah == "tiktok_setelan":
        _tampilkan(pengirim, chat_id, sesi, t_tiktok_setelan(sesi), kb_tiktok_setelan(), message_id)
    elif langkah == "tiktok_hari":
        _tampilkan(pengirim, chat_id, sesi, t_tiktok_hari(sesi), kb_tiktok_hari(), message_id)
    elif langkah == "tiktok_kom":
        _tampilkan(pengirim, chat_id, sesi, t_tiktok_komentar(sesi), kb_tiktok_komentar(), message_id)
    elif langkah == "tiktok_konfirmasi":
        _tampilkan(pengirim, chat_id, sesi, t_tiktok_konfirmasi(sesi), kb_tiktok_konfirmasi(), message_id)
    elif langkah == "ketik_tiktok_hari":
        _tampilkan(pengirim, chat_id, sesi,
                   "✍️ <b>Ketik Rentang Hari TikTok</b>\n\n"
                   "Kirim jumlah hari yang ingin dipantau (misal: 180, 365, 730 hari untuk 2 tahun, dst).\n\n"
                   "<i>Contoh: 730</i>",
                   tg.keyboard([[tg.tombol("⬅️ Kembali ke Pilihan Hari", "m:tiktok:hari_menu"),
                                tg.tombol("❌ Batal", "m:batal")]]), message_id)
    elif langkah == "facebook_topik":
        _tampilkan(pengirim, chat_id, sesi, t_facebook_topik(sesi), kb_facebook_topik(sesi), message_id)
    elif langkah == "facebook_urls":
        _tampilkan(pengirim, chat_id, sesi, t_facebook_urls(sesi), kb_facebook_urls(sesi), message_id)
    elif langkah == "facebook_setelan":
        _tampilkan(pengirim, chat_id, sesi, t_facebook_setelan(sesi), kb_facebook_setelan(), message_id)
    elif langkah == "facebook_hari":
        _tampilkan(pengirim, chat_id, sesi, t_facebook_hari(sesi), kb_facebook_hari(), message_id)
    elif langkah == "facebook_kom":
        _tampilkan(pengirim, chat_id, sesi, t_facebook_komentar(sesi), kb_facebook_komentar(), message_id)
    elif langkah == "facebook_konfirmasi":
        _tampilkan(pengirim, chat_id, sesi, t_facebook_konfirmasi(sesi), kb_facebook_konfirmasi(), message_id)
    elif langkah == "ketik_facebook_hari":
        _tampilkan(pengirim, chat_id, sesi,
                   "✍️ <b>Ketik Rentang Hari Facebook</b>\n\n"
                   "Kirim jumlah hari yang ingin dipantau (misal: 180, 365, 730 hari untuk 2 tahun, dst).\n\n"
                   "<i>Contoh: 730</i>",
                   tg.keyboard([[tg.tombol("⬅️ Kembali ke Pilihan Hari", "m:facebook:hari_menu"),
                                tg.tombol("❌ Batal", "m:batal")]]), message_id)
    elif langkah == "ketik_akun":
        _tampilkan(pengirim, chat_id, sesi,
                   "\u270d <b>Ketik Username Akun</b>\n\n"
                   "Kirim username yang mau dipantau, boleh beberapa "
                   "dipisah koma.\n\n"
                   "<i>Contoh: radarcirebon, aboutcirebonid</i>\n\n"
                   "Atau ketik /batal untuk keluar.",
                   tg.keyboard([[tg.tombol("\u274c Batal", "m:batal")]]), message_id)
    elif langkah == "ketik_hari":
        _tampilkan(pengirim, chat_id, sesi,
                   f"\u270d <b>Ketik Rentang Hari</b>\n\nKirim angka {cfg.HARI_MIN}-{cfg.HARI_MAKS}.\n"
                   "<i>Contoh: 45</i>",
                   tg.keyboard([[tg.tombol("\u274c Batal", "m:batal")]]), message_id)
    elif langkah == "ketik_post":
        _tampilkan(pengirim, chat_id, sesi,
                   f"\u270d <b>Ketik Batas Postingan</b>\n\nKirim angka 1-{cfg.MAKS_POST_PLAFON}.\n"
                   "<i>Contoh: 250</i>",
                   tg.keyboard([[tg.tombol("\u274c Batal", "m:batal")]]), message_id)
    elif langkah == "ketik_top":
        _tampilkan(pengirim, chat_id, sesi,
                   f"\u270d <b>Ketik Jumlah Post untuk Komentar</b>\n\nKirim angka {cfg.TOP_MIN}-{cfg.TOP_MAKS}.\n"
                   "<i>Contoh: 2</i>",
                   tg.keyboard([[tg.tombol("\u274c Batal", "m:batal")]]), message_id)
    elif langkah == "ketik_komentar":
        _tampilkan(pengirim, chat_id, sesi,
                   f"\u270d <b>Ketik Batas Komentar/Post</b>\n\nKirim angka 1-{cfg.MAKS_KOMENTAR_PLAFON}.\n"
                   "<i>Makin banyak = makin lama. Contoh: 75</i>",
                   tg.keyboard([[tg.tombol("\u274c Batal", "m:batal")]]), message_id)
    elif langkah == "user_tambah":
        _tampilkan(pengirim, chat_id, sesi,
                   "\u2795 <b>Tambah Pengguna</b>\n\n"
                   "Kirim Telegram user ID (angka, boleh beberapa dipisah koma).\n\n"
                   "<i>Cara tahu ID: minta pegawai tekan /start di bot ini.</i>",
                   tg.keyboard([[tg.tombol("\u274c Batal", "m:batal")]]), message_id)
    elif langkah == "user_hapus":
        _tampilkan(pengirim, chat_id, sesi,
                   "\u2796 <b>Cabut Akses Pengguna</b>\n\n"
                   "Kirim Telegram user ID yang mau dicabut.",
                   tg.keyboard([[tg.tombol("\u274c Batal", "m:batal")]]), message_id)
    else:
        _tampilkan(pengirim, chat_id, sesi, t_utama(user_id), kb_utama(user_id), message_id)
    simpan_sesi()


def proses_update(update: dict, pengirim=None, penjalan_job=None, nama_pengguna: str = ""):
    pengirim = pengirim or tg
    if "message" in update:
        _tangani_pesan(update["message"], pengirim, penjalan_job, nama_pengguna)
    elif "callback_query" in update:
        _tangani_tombol(update["callback_query"], pengirim, penjalan_job)


# ---------- 3a. pesan teks & perintah ----------
def _tangani_pesan(pesan: dict, pengirim, penjalan_job, nama_pengguna: str = ""):
    chat_id = (pesan.get("chat") or {}).get("id")
    user_id = (pesan.get("from") or {}).get("id")
    teks = (pesan.get("text") or "").strip()
    if not chat_id or not user_id:
        return

    if not cfg.user_diizinkan(user_id):
        pengirim.kirim_pesan(
            chat_id,
            "Maaf, ID Telegram Anda belum terdaftar.\n\n"
            f"ID Anda: <b>{user_id}</b>\n"
            "Kirim ID ini ke admin yang mengelola bot untuk didaftarkan.",
        )
        return

    nama = (pesan.get("from") or {}).get("first_name") or nama_pengguna
    sesi = sesi_user(user_id)
    perintah = teks.split()[0].lower() if teks else ""

    if perintah in ("/start", "/menu", "/ulang"):
        reset_pilihan(sesi)
        sesi["langkah"] = "idle"
        kirim_langkah(pengirim, chat_id, user_id, sesi)
        return

    if perintah in ("/batal", "/cancel"):
        reset_pilihan(sesi)
        sesi["langkah"] = "idle"
        pengirim.kirim_pesan(chat_id, "\u2705 Dibatalkan.\n\n" + t_utama(user_id, nama),
                             papan_tombol=kb_utama(user_id))
        simpan_sesi()
        return

    if perintah == "/bantuan":
        pengirim.kirim_pesan(chat_id, t_bantuan(),
                             papan_tombol=tg.keyboard([[tg.tombol("\U0001f3e0 Menu", "h:menu")]]))
        return

    if perintah == "/biaya":
        pengirim.kirim_pesan(chat_id, t_biaya(),
                             papan_tombol=tg.keyboard([[tg.tombol("\U0001f3e0 Menu", "h:menu")]]))
        return

    if perintah == "/status":
        pengirim.kirim_pesan(chat_id, t_status(user_id),
                             papan_tombol=tg.keyboard([[tg.tombol("\U0001f3e0 Menu", "h:menu")]]))
        return

    if perintah in ("/logmati", "/logoff"):
        sesi["kirim_log"] = False
        simpan_sesi()
        pengirim.kirim_pesan(chat_id, "\U0001f6d1 Catatan proses <b>disembunyikan</b>. "
                             "Ketik /loghidup untuk menampilkan kembali.")
        return

    if perintah in ("/loghidup", "/logon"):
        sesi["kirim_log"] = True
        simpan_sesi()
        pengirim.kirim_pesan(chat_id, "\u2705 Catatan proses <b>ditampilkan kembali</b>.")
        return

    langkah = sesi.get("langkah", "idle")

    if langkah == "tiktok_topik":
        if not teks:
            pengirim.kirim_pesan(chat_id, "Silakan ketik nama isu / kata kunci topik yang ingin dicari.")
            return
        sesi["tiktok_topik"] = teks
        sesi["langkah"] = "tiktok_urls"
        kirim_langkah(pengirim, chat_id, user_id, sesi)
        return

    if langkah == "tiktok_urls":
        baris_pecah = teks.replace(",", "\n").splitlines()
        urls_baru = []
        for b in baris_pecah:
            b = b.strip()
            if not b:
                continue
            if b.lower().startswith("http") or "tiktok.com" in b.lower():
                canonical = normalisasi_url_tiktok(b)
                if canonical and canonical not in sesi.setdefault("tiktok_urls", []):
                    sesi["tiktok_urls"].append(canonical)
                    urls_baru.append(canonical)
        if urls_baru:
            pengirim.kirim_pesan(chat_id, f"✅ Berhasil menambahkan <b>{len(urls_baru)} video acuan</b> (total: {len(sesi['tiktok_urls'])} video).")
        else:
            pengirim.kirim_pesan(chat_id, "⚠️ Link tidak terbaca. Harap kirimkan URL video TikTok yang valid.")
        kirim_langkah(pengirim, chat_id, user_id, sesi)
        return

    if langkah == "ketik_tiktok_hari":
        teks_bersih = teks.strip()
        if teks_bersih.isdigit() and int(teks_bersih) >= 1:
            angka = int(teks_bersih)
            sesi["hari"] = angka
            sesi["langkah"] = "tiktok_setelan"
            pengirim.kirim_pesan(chat_id, f"✅ Rentang waktu TikTok diatur ke <b>{angka} hari</b>.")
            kirim_langkah(pengirim, chat_id, user_id, sesi)
        else:
            pengirim.kirim_pesan(
                chat_id,
                "⚠️ Mohon kirimkan angka hari yang valid (angka bulat minimal 1 hari, misal: 365, 730).\n\n"
                "Silakan ketik ulang atau tekan tombol Kembali di bawah."
            )
        return

    if langkah == "facebook_topik":
        if not teks:
            pengirim.kirim_pesan(chat_id, "Silakan ketik nama isu / kata kunci topik yang ingin dicari di Facebook.")
            return
        sesi["facebook_topik"] = teks
        sesi["langkah"] = "facebook_urls"
        kirim_langkah(pengirim, chat_id, user_id, sesi)
        return

    if langkah == "facebook_urls":
        baris_pecah = teks.replace(",", "\n").splitlines()
        urls_baru = []
        for b in baris_pecah:
            b = b.strip()
            if not b:
                continue
            if b.lower().startswith("http") or "facebook.com" in b.lower() or "fb.watch" in b.lower():
                canonical = normalisasi_url_facebook(b)
                if canonical and canonical not in sesi.setdefault("facebook_urls", []):
                    sesi["facebook_urls"].append(canonical)
                    urls_baru.append(canonical)
        if urls_baru:
            pengirim.kirim_pesan(chat_id, f"✅ Berhasil menambahkan <b>{len(urls_baru)} postingan acuan</b> (total: {len(sesi['facebook_urls'])} post).")
        else:
            pengirim.kirim_pesan(chat_id, "⚠️ Link tidak terbaca. Harap kirimkan URL postingan Facebook yang valid.")
        kirim_langkah(pengirim, chat_id, user_id, sesi)
        return

    if langkah == "ketik_facebook_hari":
        teks_bersih = teks.strip()
        if teks_bersih.isdigit() and int(teks_bersih) >= 1:
            angka = int(teks_bersih)
            sesi["hari"] = angka
            sesi["langkah"] = "facebook_setelan"
            pengirim.kirim_pesan(chat_id, f"✅ Rentang waktu Facebook diatur ke <b>{angka} hari</b>.")
            kirim_langkah(pengirim, chat_id, user_id, sesi)
        else:
            pengirim.kirim_pesan(
                chat_id,
                "⚠️ Mohon kirimkan angka hari yang valid (angka bulat minimal 1 hari, misal: 365, 730).\n\n"
                "Silakan ketik ulang atau tekan tombol Kembali di bawah."
            )
        return

    if langkah == "ketik_akun":
        _terima_ketikan_akun(pengirim, chat_id, sesi, teks)
        return
    if langkah in ("ketik_hari", "ketik_post", "ketik_top", "ketik_komentar"):
        _terima_ketikan_angka(pengirim, chat_id, sesi, langkah, teks)
        return
    if langkah in ("user_tambah", "user_hapus") and cfg.user_adalah_admin(user_id):
        _terima_ketikan_user(pengirim, chat_id, sesi, langkah, teks)
        return

    pengirim.kirim_pesan(
        chat_id,
        "Maaf, saya belum mengerti. \U0001f60a\n\n"
        "Silakan pilih dari tombol di bawah, atau ketik /bantuan.",
        papan_tombol=kb_utama(user_id),
    )


def _kirim_post_opd_terpilih(pengirim, chat_id, sesi: dict, terpilih: list):
    folder_data = getattr(cfg, "FOLDER_OPD_DATA", None)
    if not folder_data or not folder_data.exists():
        pengirim.kirim_pesan(chat_id, "⚠️ Direktori dataset OPD belum ditemukan. Jalankan pemantauan klasemen terlebih dahulu.")
        return

    # Cari folder tanggal terbaru
    subdirs = sorted([d for d in folder_data.iterdir() if d.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
    if not subdirs:
        pengirim.kirim_pesan(chat_id, "⚠️ Belum ada dataset postingan OPD yang tersimpan.")
        return

    folder_terbaru = subdirs[0]
    folder_post = folder_terbaru / "post"

    terkirim = 0
    gagal = []

    peta_opd = getattr(cfg, "PETA_AKUN_OPD", {})
    for username in terpilih:
        meta = peta_opd.get(username, {})
        folder_akun = meta.get("folder", username)
        nama_instansi = meta.get("nama", username)

        # Cari file CSV postingan
        file_target = None
        if folder_post.exists():
            kandidat = sorted(folder_post.glob(f"{folder_akun}*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
            if kandidat:
                file_target = kandidat[0]

        # Fallback jika tidak di folder_post
        if not file_target:
            kandidat = sorted(folder_data.glob(f"**/{folder_akun}*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
            if kandidat:
                file_target = kandidat[0]

        if file_target and file_target.exists():
            try:
                pengirim.kirim_file(
                    chat_id,
                    file_target,
                    keterangan=f"📊 Dataset Postingan @{username} ({nama_instansi})"
                )
                terkirim += 1
            except Exception as e:
                gagal.append(f"@{username}: {e}")
        else:
            gagal.append(f"@{username}: berkas belum ada")

    pesan_akhir = [f"✅ <b>Pengiriman Selesai!</b>\n\nBerhasil mengirim <b>{terkirim} berkas CSV</b> postingan OPD."]
    if gagal:
        pesan_akhir.append("\n⚠️ Catatan kendala:\n• " + "\n• ".join(gagal))

    papan = tg.keyboard([
        [tg.tombol("📥 Pilih Akun Lain", "opd_sel:page:0"), tg.tombol("🏠 Menu Utama", "h:menu")]
    ])
    pengirim.kirim_pesan(chat_id, "\n".join(pesan_akhir), papan_tombol=papan)


# ---------- 3b. tekanan tombol ----------
def _tangani_tombol(cb: dict, pengirim, penjalan_job):
    chat_id = (cb.get("message") or {}).get("chat", {}).get("id")
    message_id = (cb.get("message") or {}).get("message_id")
    user_id = (cb.get("from") or {}).get("id")
    data = cb.get("data") or ""

    if not chat_id or not user_id:
        return

    pengirim.jawab_tombol(cb.get("id"))

    if not cfg.user_diizinkan(user_id):
        pengirim.kirim_pesan(chat_id, f"ID Anda ({user_id}) belum terdaftar.")
        return

    sesi = sesi_user(user_id)
    bagian = data.split(":")
    jenis = bagian[0] if bagian else ""

    # j:batalkan:<id_job>
    if jenis == "j":
        aksi_j = bagian[1] if len(bagian) > 1 else ""
        if aksi_j == "batalkan":
            id_job = bagian[2] if len(bagian) > 2 else ""
            try:
                import job_runner
                berhasil, pesan = job_runner.batalkan_job(id_job, user_id)
            except Exception as galat:
                berhasil, pesan = False, f"Gagal membatalkan: {tg.esc(str(galat))}"
            pengirim.kirim_pesan(chat_id, pesan)
        return

    # report:detail / report:negatif
    if jenis == "report":
        apa = bagian[1] if len(bagian) > 1 else ""
        try:
            import job_runner
            if apa == "detail":
                teks = job_runner.teks_detail_per_akun(chat_id)
            elif apa == "negatif":
                teks = job_runner.teks_contoh_negatif(chat_id)
            else:
                teks = "Pilihan tidak dikenal."
        except Exception as galat:
            teks = f"Maaf, belum bisa ditampilkan ({tg.esc(str(galat))})."
        pengirim.kirim_pesan(chat_id, teks)
        return



    # opd_sel:... = interaksi multi-pilih akun OPD untuk unduh post
    if jenis == "opd_sel":
        aksi_sel = bagian[1] if len(bagian) > 1 else ""
        hal = int(sesi.get("opd_hal", 0))

        if aksi_sel == "tog":
            idx = int(bagian[2]) if len(bagian) > 2 and bagian[2].isdigit() else 0
            daftar_opd = getattr(cfg, "DAFTAR_OPD", [])
            if 0 <= idx < len(daftar_opd):
                u = daftar_opd[idx][0]
                terpilih = list(sesi.get("opd_pilih") or [])
                if u in terpilih:
                    terpilih.remove(u)
                else:
                    terpilih.append(u)
                sesi["opd_pilih"] = terpilih
            _tampilkan(pengirim, chat_id, sesi, t_opd_multi_pilih(sesi, hal), kb_opd_multi_pilih(sesi, hal), message_id)
            return

        elif aksi_sel == "buka":
            hal = int(bagian[2]) if len(bagian) > 2 and bagian[2].isdigit() else 0
            sesi["opd_hal"] = hal
            dikirim = pengirim.kirim_pesan(chat_id, t_opd_multi_pilih(sesi, hal), papan_tombol=kb_opd_multi_pilih(sesi, hal))
            if isinstance(dikirim, dict):
                sesi["pesan_menu"] = dikirim.get("message_id")
            return

        elif aksi_sel == "page":
            hal = int(bagian[2]) if len(bagian) > 2 and bagian[2].isdigit() else 0
            sesi["opd_hal"] = hal
            _tampilkan(pengirim, chat_id, sesi, t_opd_multi_pilih(sesi, hal), kb_opd_multi_pilih(sesi, hal), message_id)
            return

        elif aksi_sel == "semua":
            daftar_opd = getattr(cfg, "DAFTAR_OPD", [])
            sesi["opd_pilih"] = [u for u, f, n, k in daftar_opd]
            _tampilkan(pengirim, chat_id, sesi, t_opd_multi_pilih(sesi, hal), kb_opd_multi_pilih(sesi, hal), message_id)
            return

        elif aksi_sel == "reset":
            sesi["opd_pilih"] = []
            _tampilkan(pengirim, chat_id, sesi, t_opd_multi_pilih(sesi, hal), kb_opd_multi_pilih(sesi, hal), message_id)
            return

        elif aksi_sel == "kirim":
            terpilih = list(sesi.get("opd_pilih") or [])
            if not terpilih:
                pengirim.kirim_pesan(
                    chat_id,
                    "⚠️ <b>Belum ada akun terpilih!</b>\n\nSilakan tekan tombol nama dinas/kecamatan di atas untuk memilih sebelum mengunduh."
                )
                return
            _kirim_post_opd_terpilih(pengirim, chat_id, sesi, terpilih)
            return

    # h:... = halaman statis
    if jenis == "h":
        apa = bagian[1] if len(bagian) > 1 else "menu"
        if apa == "bantuan":
            _tampilkan(pengirim, chat_id, sesi, t_bantuan(),
                       tg.keyboard([[tg.tombol("\U0001f3e0 Menu", "h:menu")]]), message_id)
        elif apa == "biaya":
            _tampilkan(pengirim, chat_id, sesi, t_biaya(),
                       tg.keyboard([[tg.tombol("\U0001f3e0 Menu", "h:menu")]]), message_id)
        elif apa == "status":
            _tampilkan(pengirim, chat_id, sesi, t_status(user_id),
                       tg.keyboard([[tg.tombol("\U0001f3e0 Menu", "h:menu")]]), message_id)
        else:
            reset_pilihan(sesi)
            sesi["langkah"] = "idle"
            kirim_langkah(pengirim, chat_id, user_id, sesi, message_id)
        return

    # a:user... = admin
    if jenis == "a":
        if not cfg.user_adalah_admin(user_id):
            pengirim.kirim_pesan(chat_id, "Hanya admin yang bisa membuka menu ini.")
            return
        _tangani_admin(pengirim, chat_id, sesi, bagian, message_id)
        return

    # m:... = menu utama
    aksi = bagian[1] if len(bagian) > 1 else ""
    nilai = bagian[2] if len(bagian) > 2 else ""

    if aksi == "mode":
        if nilai == "media":
            reset_pilihan(sesi)
            sesi["target_jenis"] = "media"
            sesi["langkah"] = "akun"
        elif nilai == "opd":
            reset_pilihan(sesi)
            sesi["target_jenis"] = "opd"
            sesi["opd_mode"] = "ranking"
            sesi["hari"] = 30
            sesi["komentar"] = False
            sesi["akun"] = [a[0] for a in getattr(cfg, "DAFTAR_OPD", [])]
            sesi["langkah"] = "konfirmasi_opd_ranking"
        elif nilai == "tiktok":
            reset_pilihan(sesi)
            sesi["target_jenis"] = "tiktok"
            sesi["hari"] = 30
            sesi["komentar"] = True
            sesi["langkah"] = "tiktok_topik"
        elif nilai == "facebook":
            reset_pilihan(sesi)
            sesi["target_jenis"] = "facebook"
            sesi["hari"] = 30
            sesi["komentar"] = True
            sesi["langkah"] = "facebook_topik"
        kirim_langkah(pengirim, chat_id, user_id, sesi, message_id)

    elif aksi == "tiktok":
        sub = nilai
        if sub == "topik_lanjut":
            sesi["langkah"] = "tiktok_urls"
        elif sub == "ubah_topik":
            sesi["langkah"] = "tiktok_topik"
        elif sub == "urls_lanjut":
            if len(sesi.get("tiktok_urls") or []) < 1:
                pengirim.kirim_pesan(chat_id, "⚠️ Harap masukkan minimal 1 link video acuan sebelum melanjutkan.")
                sesi["langkah"] = "tiktok_urls"
            else:
                sesi["langkah"] = "tiktok_setelan"
        elif sub == "urls_reset":
            sesi["tiktok_urls"] = []
            sesi["langkah"] = "tiktok_urls"
        elif sub == "kembali_urls":
            sesi["langkah"] = "tiktok_urls"
        elif sub == "setelan":
            sesi["langkah"] = "tiktok_setelan"
        elif sub == "hari_menu":
            sesi["langkah"] = "tiktok_hari"
        elif sub == "kom_menu":
            sesi["langkah"] = "tiktok_kom"
        elif sub == "hari":
            if len(bagian) > 3 and bagian[3] == "ketik":
                sesi["langkah"] = "ketik_tiktok_hari"
            else:
                h = int(bagian[3]) if len(bagian) > 3 and bagian[3].isdigit() else 30
                sesi["hari"] = h
                sesi["langkah"] = "tiktok_setelan"
        elif sub == "kom":
            pilihan_k = bagian[3] if len(bagian) > 3 else "ya"
            sesi["komentar"] = (pilihan_k == "ya")
            sesi["langkah"] = "tiktok_setelan"
        elif sub == "setelan_lanjut":
            sesi["langkah"] = "tiktok_konfirmasi"
        kirim_langkah(pengirim, chat_id, user_id, sesi, message_id)

    elif aksi == "facebook":
        sub = nilai
        if sub == "topik_lanjut":
            sesi["langkah"] = "facebook_urls"
        elif sub == "ubah_topik":
            sesi["langkah"] = "facebook_topik"
        elif sub == "urls_lanjut":
            if len(sesi.get("facebook_urls") or []) < 1:
                pengirim.kirim_pesan(chat_id, "⚠️ Harap masukkan minimal 1 link postingan acuan sebelum melanjutkan.")
                sesi["langkah"] = "facebook_urls"
            else:
                sesi["langkah"] = "facebook_setelan"
        elif sub == "urls_reset":
            sesi["facebook_urls"] = []
            sesi["langkah"] = "facebook_urls"
        elif sub == "kembali_urls":
            sesi["langkah"] = "facebook_urls"
        elif sub == "setelan":
            sesi["langkah"] = "facebook_setelan"
        elif sub == "hari_menu":
            sesi["langkah"] = "facebook_hari"
        elif sub == "kom_menu":
            sesi["langkah"] = "facebook_kom"
        elif sub == "hari":
            if len(bagian) > 3 and bagian[3] == "ketik":
                sesi["langkah"] = "ketik_facebook_hari"
            else:
                h = int(bagian[3]) if len(bagian) > 3 and bagian[3].isdigit() else 30
                sesi["hari"] = h
                sesi["langkah"] = "facebook_setelan"
        elif sub == "kom":
            pilihan_k = bagian[3] if len(bagian) > 3 else "ya"
            sesi["komentar"] = (pilihan_k == "ya")
            sesi["langkah"] = "facebook_setelan"
        elif sub == "setelan_lanjut":
            sesi["langkah"] = "facebook_konfirmasi"
        kirim_langkah(pengirim, chat_id, user_id, sesi, message_id)

    elif aksi == "opd":
        reset_pilihan(sesi)
        sesi["target_jenis"] = "opd"
        sesi["opd_mode"] = "ranking"
        sesi["hari"] = 30
        sesi["komentar"] = False
        sesi["akun"] = [a[0] for a in getattr(cfg, "DAFTAR_OPD", [])]
        sesi["langkah"] = "konfirmasi_opd_ranking"
        kirim_langkah(pengirim, chat_id, user_id, sesi, message_id)

    elif aksi == "opd_hari":
        if nilai == "menu":
            sesi["langkah"] = "opd_hari"
        else:
            ok, angka, _ = cfg.validasi_hari(nilai)
            if ok:
                sesi["hari"] = angka
            sesi["langkah"] = "konfirmasi_opd_ranking"
        kirim_langkah(pengirim, chat_id, user_id, sesi, message_id)

    elif aksi == "mulai_akun":
        reset_pilihan(sesi)
        sesi["target_jenis"] = "media"
        sesi["langkah"] = "akun"
        kirim_langkah(pengirim, chat_id, user_id, sesi, message_id)

    elif aksi == "cepat":
        # Mode cepat: pakai setelan terakhir, langsung ke konfirmasi
        if sesi.get("akun"):
            sesi["langkah"] = "konfirmasi"
        else:
            reset_pilihan(sesi)
            sesi["langkah"] = "akun"
        kirim_langkah(pengirim, chat_id, user_id, sesi, message_id)

    elif aksi == "akun":
        if nilai == "ketik":
            sesi["langkah"] = "ketik_akun"
        elif nilai == "semua":
            sesi["akun"] = [a[0] for a in cfg.DAFTAR_MEDIA]
            sesi["langkah"] = "akun"
        elif nilai == "lanjut":
            if not sesi.get("akun"):
                pengirim.kirim_pesan(chat_id, "Pilih minimal satu akun dulu. \U0001f60a")
                sesi["langkah"] = "akun"
            else:
                sesi["langkah"] = "setelan"
        elif nilai.isdigit():
            idx = int(nilai)
            if 0 <= idx < len(cfg.DAFTAR_MEDIA):
                username = cfg.DAFTAR_MEDIA[idx][0]
                terpilih = list(sesi.get("akun") or [])
                if username in terpilih:
                    terpilih.remove(username)
                else:
                    terpilih.append(username)
                sesi["akun"] = terpilih
            sesi["langkah"] = "akun"
        kirim_langkah(pengirim, chat_id, user_id, sesi, message_id)

    elif aksi == "setelan":
        if nilai == "lanjut":
            sesi["langkah"] = "konfirmasi"
        else:
            sesi["langkah"] = "setelan"
        kirim_langkah(pengirim, chat_id, user_id, sesi, message_id)

    elif aksi == "hari":
        if nilai == "ketik":
            sesi["langkah"] = "ketik_hari"
        elif nilai == "menu":
            sesi["langkah"] = "hari"
        else:
            ok, angka, _ = cfg.validasi_hari(nilai)
            if ok:
                sesi["hari"] = angka
                sesi["langkah"] = "setelan"
        kirim_langkah(pengirim, chat_id, user_id, sesi, message_id)

    elif aksi == "post":
        if nilai == "ketik":
            sesi["langkah"] = "ketik_post"
        elif nilai == "menu":
            sesi["langkah"] = "post"
        else:
            ok, angka, _ = cfg.validasi_maks_post(nilai)
            if ok:
                sesi["maks_post"] = angka
                sesi["langkah"] = "setelan"
        kirim_langkah(pengirim, chat_id, user_id, sesi, message_id)

    elif aksi == "top":
        if nilai == "ketik":
            sesi["langkah"] = "ketik_top"
        elif nilai == "menu":
            sesi["langkah"] = "top"
        else:
            ok, angka, _ = cfg.validasi_top_video(nilai)
            if ok:
                sesi["top"] = angka
                sesi["langkah"] = "setelan"
        kirim_langkah(pengirim, chat_id, user_id, sesi, message_id)

    elif aksi == "kom":
        if nilai == "ketik":
            sesi["langkah"] = "ketik_komentar"
        elif nilai == "menu":
            sesi["langkah"] = "komentar"
        elif nilai == "tidak":
            sesi["komentar"] = False
            sesi["langkah"] = "setelan"
        else:
            ok, angka, _ = cfg.validasi_maks_komentar(nilai)
            if ok:
                sesi["maks_komentar"] = angka
                sesi["komentar"] = True
                sesi["langkah"] = "setelan"
        kirim_langkah(pengirim, chat_id, user_id, sesi, message_id)

    elif aksi == "ubah":
        peta = {"akun": "akun", "hari": "hari", "post": "post", "top": "top",
                "komentar": "komentar", "setelan": "setelan"}
        sesi["langkah"] = peta.get(nilai, "setelan")
        kirim_langkah(pengirim, chat_id, user_id, sesi, message_id)

    elif aksi == "kembali":
        peta = {"akun": "akun", "setelan": "setelan"}
        sesi["langkah"] = peta.get(nilai, "setelan")
        kirim_langkah(pengirim, chat_id, user_id, sesi, message_id)

    elif aksi == "jalankan":
        _jalankan(pengirim, chat_id, user_id, sesi, penjalan_job, message_id)

    elif aksi == "batal":
        reset_pilihan(sesi)
        sesi["langkah"] = "idle"
        _tampilkan(pengirim, chat_id, sesi, "\u2705 Dibatalkan.\n\n" + t_utama(user_id),
                   kb_utama(user_id), message_id)


# ---------- 3c. penerimaan ketikan ----------
def _terima_ketikan_akun(pengirim, chat_id, sesi: dict, teks: str):
    usulan = [p.strip() for p in teks.split(",") if p.strip()]
    diterima, ditolak = [], []
    for mentah in usulan:
        ok, bersih, galat = cfg.validasi_username(mentah)
        if ok:
            diterima.append(bersih)
        else:
            ditolak.append(f"{tg.esc(mentah)} ({tg.esc(galat)})")

    terpilih = list(sesi.get("akun") or [])
    for u in diterima:
        if u not in terpilih:
            terpilih.append(u)
    sesi["akun"] = terpilih
    sesi["langkah"] = "akun"

    if ditolak:
        pengirim.kirim_pesan(chat_id, "Sebagian tidak diterima:\n  \u2022 " + "\n  \u2022 ".join(ditolak))
    kirim_langkah(pengirim, chat_id, None, sesi)


def _terima_ketikan_angka(pengirim, chat_id, sesi: dict, langkah: str, teks: str):
    if langkah == "ketik_hari":
        ok, angka, galat = cfg.validasi_hari(teks)
        if ok:
            sesi["hari"] = angka
            if sesi.get("target_jenis") == "opd":
                sesi["langkah"] = "konfirmasi_opd_ranking"
            else:
                sesi["langkah"] = "setelan"
        else:
            pengirim.kirim_pesan(chat_id, tg.esc(galat))
            sesi["langkah"] = "ketik_hari"
    elif langkah == "ketik_post":
        ok, angka, galat = cfg.validasi_maks_post(teks)
        if ok:
            sesi["maks_post"] = angka
            sesi["langkah"] = "setelan"
        else:
            pengirim.kirim_pesan(chat_id, tg.esc(galat))
            sesi["langkah"] = "ketik_post"
    elif langkah == "ketik_komentar":
        ok, angka, galat = cfg.validasi_maks_komentar(teks)
        if ok:
            sesi["maks_komentar"] = angka
            sesi["komentar"] = True
            sesi["langkah"] = "setelan"
        else:
            pengirim.kirim_pesan(chat_id, tg.esc(galat))
            sesi["langkah"] = "ketik_komentar"
    else:
        ok, angka, galat = cfg.validasi_top_video(teks)
        if ok:
            sesi["top"] = angka
            sesi["langkah"] = "setelan"
        else:
            pengirim.kirim_pesan(chat_id, tg.esc(galat))
            sesi["langkah"] = "ketik_top"
    kirim_langkah(pengirim, chat_id, None, sesi)


def _terima_ketikan_user(pengirim, chat_id, sesi: dict, langkah: str, teks: str):
    usulan = [p.strip() for p in teks.replace(",", " ").split() if p.strip()]
    laporan = []
    for potong in usulan:
        try:
            angka = int(potong)
        except ValueError:
            laporan.append(f"{tg.esc(potong)}: bukan angka")
            continue
        if langkah == "user_tambah":
            berhasil, pesan = cfg.tambah_user(angka)
        else:
            berhasil, pesan = cfg.hapus_user(angka)
        laporan.append(tg.esc(pesan))
    sesi["langkah"] = "user_list"
    pengirim.kirim_pesan(chat_id, "\n".join(laporan) or "Tidak ada ID yang diproses.")
    _tampilkan(pengirim, chat_id, sesi, t_admin_user(), kb_admin_user(), sesi.get("pesan_menu"))


def _tangani_admin(pengirim, chat_id, sesi: dict, bagian: list, message_id: int):
    aksi = bagian[2] if len(bagian) > 2 else ""
    if aksi == "tambah":
        sesi["langkah"] = "user_tambah"
        kirim_langkah(pengirim, chat_id, None, sesi, message_id)
    elif aksi == "hapus":
        sesi["langkah"] = "user_hapus"
        kirim_langkah(pengirim, chat_id, None, sesi, message_id)
    else:
        _tampilkan(pengirim, chat_id, sesi, t_admin_user(), kb_admin_user(), message_id)


# ---------- 3d. tombol MULAI ----------
def _jalankan(pengirim, chat_id, user_id, sesi: dict, penjalan_job, message_id: int = None):
    if sesi.get("target_jenis") == "tiktok":
        if not sesi.get("tiktok_topik"):
            pengirim.kirim_pesan(chat_id, "Nama isu/topik belum diisi. Kembali ke langkah 1.")
            sesi["langkah"] = "tiktok_topik"
            kirim_langkah(pengirim, chat_id, user_id, sesi, message_id)
            return
        if len(sesi.get("tiktok_urls") or []) < 1:
            pengirim.kirim_pesan(chat_id, "Minimal 1 link video acuan diperlukan.")
            sesi["langkah"] = "tiktok_urls"
            kirim_langkah(pengirim, chat_id, user_id, sesi, message_id)
            return
    elif sesi.get("target_jenis") == "facebook":
        if not sesi.get("facebook_topik"):
            pengirim.kirim_pesan(chat_id, "Nama isu/topik Facebook belum diisi. Kembali ke langkah 1.")
            sesi["langkah"] = "facebook_topik"
            kirim_langkah(pengirim, chat_id, user_id, sesi, message_id)
            return
        if len(sesi.get("facebook_urls") or []) < 1:
            pengirim.kirim_pesan(chat_id, "Minimal 1 link postingan acuan diperlukan.")
            sesi["langkah"] = "facebook_urls"
            kirim_langkah(pengirim, chat_id, user_id, sesi, message_id)
            return
    elif not sesi.get("akun"):
        pengirim.kirim_pesan(chat_id, "Belum ada akun terpilih. Kembali ke langkah 1.")
        sesi["langkah"] = "akun"
        kirim_langkah(pengirim, chat_id, user_id, sesi, message_id)
        return

    perintah = susun_perintah(sesi)

    if penjalan_job is None:
        teks = (
            "\u26a0\ufe0f <b>Mesin belum aktif</b>\n\n"
            "Alur menu sudah benar, tetapi pengeksekusi belum dipasang.\n"
            "Tidak ada biaya yang keluar."
        )
        _tampilkan(pengirim, chat_id, sesi, teks,
                   tg.keyboard([[tg.tombol("\u274c Batal", "m:batal")]]), message_id)
        return

    penjalan_job(sesi, perintah, chat_id, user_id)
    sesi["langkah"] = "idle"
