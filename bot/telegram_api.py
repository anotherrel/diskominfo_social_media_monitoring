# -*- coding: utf-8 -*-
"""
telegram_api.py
===============
Pembungkus tipis Telegram Bot API untuk bot scraper Instagram.

KENAPA TIDAK PAKAI LIBRARY (python-telegram-bot / pyTelegramBotAPI)?
------------------------------------------------------------------
1. Bot ini cuma butuh 6 perintah API. Stdlib `urllib` sudah cukup, artinya:
   tidak ada `pip install`, tidak ada masalah versi, dan bot bisa dijalankan
   dari WSL maupun Windows dengan Python apa pun yang >= 3.8.
2. Nilai belajarnya lebih tinggi: kelihatan langsung bentuk HTTP-nya
   (endpoint, header, body JSON, multipart/form-data) tanpa tertutup library.
Konsekuensinya: kalau nanti butuh fitur kompleks (payment, forum topic, dll),
pindah ke library resmi itu wajar.

CARA KERJA SINGKAT (penting untuk paham, bukan dihafal)
------------------------------------------------------
- SETIAP perintah Telegram Bot API punya bentuk URL:
      https://api.telegram.org/bot<TOKEN>/<namaMetode>
  Token menempel di URL. Karena itu token = rahasia mutlak (siapa pun yang
  punya URL itu bisa menyamar jadi bot).
- Mengirim pesan = POST JSON ke /sendMessage dengan body {"chat_id":..., "text":...}
- Menerima pesan = MEMANGGIL /getUpdates berulang-ulang (istilahnya LONG POLLING:
  kita datang ke Telegram dan "menunggu" sampai 50 detik; kalau ada pesan,
  Telegram membalaskan daftar update, kalau tidak ada dia menjawab daftar kosong).
  Setiap update punya nomor naik terus (update_id). Kita kirim balik `offset`
  = update_id terakhir + 1 supaya Telegram tahu pesan mana yang belum kita akui.
- Tombol di bawah pesan (inline keyboard) MENGIRIM callback_data, bukan teks.
  Telegram memakai istilahnya "callback_query"; setiap kali user menekan tombol
  WAJIB dijawab dengan answerCallbackQuery, kalau tidak ikon loading di tombol
  tidak berhenti.

Batas yang perlu diingat:
- Teks pesan maksimum 4096 karakter  -> pakai pecah_pesan()
- caption file maksimum 1024 karakter
- callback_data maksimum 64 BYTE    -> jangan menaruh JSON panjang di situ
- Rate limit per chat sekitar 1 pesan/detik; kena limit -> Telegram balas 429
  beserta retry_after (detik) -> _panggil() menunggu lalu mencoba lagi.
"""

import json
import mimetypes
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

try:
    import bot_config
    TOKEN_BOT = bot_config.TOKEN_BOT
    PANJANG_TELEGRAM = bot_config.PANJANG_TELEGRAM
except Exception:
    TOKEN_BOT = ""
    PANJANG_TELEGRAM = 4096

URL_API = "https://api.telegram.org"
TIMEOUT_DEFAULT = 60
MAKS_PERCOBAAN_ULANG = 3


class TelegramError(Exception):
    """Kesalahan dari sisi Telegram (kode + deskripsi) atau dari jaringan."""

    def __init__(self, deskripsi: str, kode: int = 0, retry_after: int = 0):
        super().__init__(f"[{kode}] {deskripsi}")
        self.deskripsi = deskripsi
        self.kode = kode
        self.retry_after = retry_after


def esc(teks) -> str:
    """
    Escape karakter khusus HTML agar aman dipakai dalam parse_mode='HTML'.
    WAJIB dipanggil untuk SEMUA teks dinamis (username, input user, angka
    dari luar, dsb.) sebelum disisipkan ke template HTML.
    """
    return (str(teks)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def _url(metode: str, token: str = None) -> str:
    token = token or TOKEN_BOT
    if not token:
        raise TelegramError(
            "Token bot belum ada. Isi BOT_TELEGRAM_TOKEN di instagram/bot/.env "
            "(token dari @BotFather)."
        )
    return f"{URL_API}/bot{token}/{metode}"


# ============================================================
# 1. INTI: satu fungsi untuk SEMUA perintah API
# ============================================================
def _panggil(metode: str, data: dict = None, timeout: int = TIMEOUT_DEFAULT, token: str = None):
    """
    POST JSON ke Telegram Bot API.

    Returns: isi "result" dari jawaban Telegram.
    Raise TelegramError kalau Telegram menolak atau jaringan bermasalah.

    Tiga hal yang ditangani otomatis di sini (supaya kode menu tidak dipenuhi
    urusan teknis):
    - 429 rate limit  -> tunggu sesuai retry_after, lalu ulangi
    - gangguan jaringan sesaat -> tunggu sebentar, ulangi (maks 3 kali)
    - 409 Conflict    -> diterjemahkan jadi pesan yang jelas (token dipakai proses lain)
    """
    url = _url(metode, token)
    body = json.dumps(data or {}).encode("utf-8")
    galat_terakhir = None

    for percobaan in range(1, MAKS_PERCOBAAN_ULANG + 1):
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as jawaban:
                isi = json.loads(jawaban.read().decode("utf-8"))
            if isi.get("ok"):
                return isi.get("result")
            raise TelegramError(isi.get("description") or "Telegram menolak tanpa keterangan")

        except urllib.error.HTTPError as galat:
            mentah = galat.read().decode("utf-8", "replace")
            try:
                isi = json.loads(mentah)
            except Exception:
                isi = {}
            deskripsi = isi.get("description") or mentah[:200]
            retry_after = int((isi.get("parameters") or {}).get("retry_after") or 0)

            if galat.code == 409:
                raise TelegramError(
                    "409 Conflict: token ini sedang dipakai proses lain. Pastikan tidak ada "
                    "bot/proses lain yang memakai BOT_TELEGRAM_TOKEN yang sama.",
                    409,
                )
            if galat.code == 429 and percobaan < MAKS_PERCOBAAN_ULANG:
                print(f"[BOT] Kena rate limit, menunggu {retry_after or 3} detik...")
                time.sleep(min(retry_after or 3, 30))
                continue

            galat_terakhir = TelegramError(deskripsi, galat.code, retry_after)
            if percobaan >= MAKS_PERCOBAAN_ULANG:
                raise galat_terakhir

        except urllib.error.URLError as galat:
            galat_terakhir = TelegramError(f"Koneksi ke Telegram gagal: {galat.reason}")
            if percobaan < MAKS_PERCOBAAN_ULANG:
                time.sleep(2 * percobaan)          # 2s, 4s -> jeda makin panjang
                continue
            raise galat_terakhir

    raise galat_terakhir or TelegramError("Gagal memanggil Telegram tanpa keterangan")


# ============================================================
# 2. TOMBOL (inline keyboard)
# ============================================================
def tombol(teks: str, data_callback: str) -> dict:
    """
    Satu tombol. data_callback = teks yang dikirim balik ke bot saat ditekan.
    INGAT: maksimum 64 byte, jadi pakai kode pendek seperti "menu:akun:3".
    """
    return {"text": teks, "callback_data": data_callback}


def tombol_url(teks: str, url: str) -> dict:
    """Tombol yang membuka tautan (tidak mengirim callback)."""
    return {"text": teks, "url": url}


def keyboard(baris_tombol: list) -> dict:
    """
    Susun papan tombol. baris_tombol = daftar baris, tiap baris daftar tombol.
    Contoh: keyboard([[tombol("A","a"), tombol("B","b")], [tombol("Batal","x")]])
    """
    return {"inline_keyboard": baris_tombol}


# ============================================================
# 3. MENGIRIM PESAN & MENGUBAH PESAN
# ============================================================
def kirim_pesan(chat_id, teks: str, papan_tombol: dict = None, balas_ke: int = None,
                token: str = None, parse_mode: str = "HTML") -> dict:
    """
    Kirim pesan teks. Returns dict pesan (berisi message_id).
    parse_mode='HTML' secara bawaan. Kalau Telegram menolak karena HTML tidak valid,
    otomatis dicoba ulang TANPA parse_mode (fallback ke teks polos).
    """
    data = {"chat_id": chat_id, "text": teks[:PANJANG_TELEGRAM]}
    if parse_mode:
        data["parse_mode"] = parse_mode
    if papan_tombol:
        data["reply_markup"] = papan_tombol
    if balas_ke:
        data["reply_to_message_id"] = balas_ke
    try:
        return _panggil("sendMessage", data, token=token)
    except TelegramError as galat:
        if parse_mode and "parse" in galat.deskripsi.lower():
            # HTML tidak valid -> coba lagi tanpa formatting
            data.pop("parse_mode", None)
            return _panggil("sendMessage", data, token=token)
        raise


def kirim_pesan_panjang(chat_id, teks: str, papan_tombol: dict = None, token: str = None) -> dict:
    """
    Kirim teks yang mungkin lebih dari 4096 karakter: dipecah jadi beberapa pesan.
    Tombol hanya ditempel di pesan TERAKHIR (biar tidak ada tombol menggantung).
    """
    potongan = pecah_pesan(teks)
    terakhir = None
    for i, bagian in enumerate(potongan, 1):
        papan = papan_tombol if i == len(potongan) else None
        terakhir = kirim_pesan(chat_id, bagian, papan_tombol=papan, token=token)
    return terakhir


def edit_pesan(chat_id, message_id: int, teks: str, papan_tombol: dict = None,
               token: str = None, parse_mode: str = "HTML") -> dict:
    """
    Ubah isi pesan yang sudah terkirim (dipakai untuk memperbarui menu/progres).
    Kalau isi dan tombolnya persis sama, Telegram menolak dengan "message is not
    modified" -> itu bukan kesalahan, jadi dikembalikan sebagai None.
    Fallback ke teks polos kalau HTML tidak valid.
    """
    data = {"chat_id": chat_id, "message_id": message_id, "text": teks[:PANJANG_TELEGRAM]}
    if parse_mode:
        data["parse_mode"] = parse_mode
    if papan_tombol is not None:
        data["reply_markup"] = papan_tombol
    try:
        return _panggil("editMessageText", data, token=token)
    except TelegramError as galat:
        if "not modified" in galat.deskripsi.lower():
            return None
        if parse_mode and "parse" in galat.deskripsi.lower():
            data.pop("parse_mode", None)
            try:
                return _panggil("editMessageText", data, token=token)
            except TelegramError as galat2:
                if "not modified" in galat2.deskripsi.lower():
                    return None
                raise
        raise


def hapus_pesan(chat_id, message_id: int, token: str = None) -> bool:
    """Hapus pesan. Gagal dihapus (mis. sudah lama) bukan masalah besar -> return False."""
    try:
        _panggil("deleteMessage", {"chat_id": chat_id, "message_id": message_id}, token=token)
        return True
    except TelegramError:
        return False


def jawab_tombol(callback_query_id: str, teks: str = None, token: str = None) -> bool:
    """
    WAJIB dipanggil setiap kali user menekan tombol inline.
    Fungsinya: menghentikan ikon "loading" di tombol + (opsional) menampilkan
    keterangan kecil di atas layar Telegram.
    """
    data = {"callback_query_id": callback_query_id}
    if teks:
        data["text"] = teks[:200]
    try:
        _panggil("answerCallbackQuery", data, token=token)
        return True
    except TelegramError:
        return False


# ============================================================
# 4. MENGIRIM FILE (multipart/form-data)
# ============================================================
def kirim_file(chat_id, path_file, keterangan: str = "", token: str = None, timeout: int = 300) -> dict:
    """
    Kirim file dari disk sebagai "document" (CSV/JSON) ke chat.

    Kenapa ditulis manual? Karena mengirim file TIDAK memakai JSON, melainkan
    multipart/form-data: satu body berisi beberapa "bidang" yang dipisah penanda
    (boundary), dan file dikirim mentah sebagai byte. Inilah cara kerja upload
    file di web pada umumnya.
    """
    path_file = Path(path_file)
    if not path_file.exists():
        raise TelegramError(f"File tidak ditemukan: {path_file}")

    batas = "----BatasBot" + uuid.uuid4().hex
    tipe = mimetypes.guess_type(path_file.name)[0] or "application/octet-stream"
    potongan = []

    def bidang(nama: str, nilai: str):
        potongan.append(
            f"--{batas}\r\n"
            f'Content-Disposition: form-data; name="{nama}"\r\n\r\n'
            f"{nilai}\r\n".encode("utf-8")
        )

    bidang("chat_id", str(chat_id))
    if keterangan:
        bidang("caption", keterangan[:1024])

    potongan.append(
        f"--{batas}\r\n"
        f'Content-Disposition: form-data; name="document"; filename="{path_file.name}"\r\n'
        f"Content-Type: {tipe}\r\n\r\n".encode("utf-8")
    )
    potongan.append(path_file.read_bytes())
    potongan.append(b"\r\n")
    potongan.append(f"--{batas}--\r\n".encode("utf-8"))
    body = b"".join(potongan)

    request = urllib.request.Request(
        _url("sendDocument", token),
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={batas}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as jawaban:
            isi = json.loads(jawaban.read().decode("utf-8"))
    except urllib.error.HTTPError as galat:
        raise TelegramError(f"Gagal mengirim file: HTTP {galat.code} {galat.read()[:200]!r}")
    except urllib.error.URLError as galat:
        raise TelegramError(f"Gagal mengirim file (jaringan): {galat.reason}")

    if not isi.get("ok"):
        raise TelegramError(f"Gagal mengirim file: {isi.get('description')}")
    return isi.get("result")


# ============================================================
# 5. MENERIMA PESAN (LONG POLLING)
# ============================================================
def ambil_pesan(offset: int = None, timeout_polling: int = 50, jenis: list = None, token: str = None) -> list:
    """
    Ambil pesan/tekanan tombol baru dari Telegram.

    - timeout_polling = berapa detik kita menunggu di sisi Telegram (long polling).
    - offset          = update_id terakhir + 1. Telegram akan menganggap semua
                        update sebelum angka ini "sudah dibaca" dan tidak
                        mengirimkannya lagi. KARENA ITU offset wajib disimpan
                        oleh pemanggil (nanti di main_bot.py).
    Returns: daftar update (list). Kosong = tidak ada pesan baru (normal).
    """
    data = {
        "timeout": timeout_polling,
        "allowed_updates": jenis or ["message", "callback_query"],
    }
    if offset:
        data["offset"] = offset

    # timeout HTTP dibuat lebih panjang dari long polling, kalau tidak koneksi
    # diputus sendiri sebelum Telegram sempat menjawab.
    hasil = _panggil("getUpdates", data, timeout=timeout_polling + 20, token=token)
    return hasil or []


def hapus_antrean_belum_dibaca(token: str = None) -> int:
    """
    Buang semua pesan lama yang belum diproses (dipakai sekali saat bot baru start,
    supaya bot tidak membalas pesan dari berhari-hari lalu).
    Returns: jumlah update yang dibuang.
    """
    hasil = ambil_pesan(offset=-1, timeout_polling=0, token=token)
    return len(hasil)


# ============================================================
# 6. INFORMASI & ALAT BANTU
# ============================================================
def info_bot(token: str = None) -> dict:
    """Info bot sendiri (getMe). Berguna untuk memastikan token benar."""
    return _panggil("getMe", {}, token=token)


def pecah_pesan(teks: str, maks: int = None) -> list:
    """
    Pecah teks panjang jadi beberapa bagian <= 4096 karakter.
    Dipecah di batas baris supaya tidak memotong kalimat di tengah.
    """
    maks = maks or PANJANG_TELEGRAM
    teks = teks or ""
    if len(teks) <= maks:
        return [teks] if teks.strip() else [""]

    bagian = []
    sedang = ""
    for baris in teks.splitlines(keepends=True):
        while len(baris) > maks:            # satu baris kelewat panjang: potong paksa
            sisa = maks - len(sedang)
            sedang += baris[:sisa]
            bagian.append(sedang)
            sedang = ""
            baris = baris[sisa:]
        if len(sedang) + len(baris) > maks:
            bagian.append(sedang)
            sedang = baris
        else:
            sedang += baris
    if sedang.strip():
        bagian.append(sedang)
    return bagian


def format_bold(teks: str) -> str:
    """
    Bungkus teks jadi tebal ala Telegram. Bot ini sengaja TIDAK memakai parse_mode
    HTML/Markdown global: satu karakter '_' atau '*' nyasar bisa membuat Telegram
    menolak seluruh pesan. Kalau butuh tebal, pakai helper ini secara terbatas.
    """
    return f"<b>{teks}</b>"


if __name__ == "__main__":
    # Uji cepat tanpa mengirim apa pun: pastikan token bisa dipakai.
    # Jalankan dari folder instagram/bot:  python telegram_api.py
    print("Menguji token bot (memanggil getMe, tidak mengirim pesan)...")
    try:
        info = info_bot()
        print("BERHASIL. Bot bernama:", info.get("first_name"), "| username: @" + str(info.get("username")))
    except TelegramError as galat:
        print("GAGAL:", galat)
