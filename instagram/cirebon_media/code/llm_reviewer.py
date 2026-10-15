# -*- coding: utf-8 -*-
"""
llm_reviewer.py
===============
PENILAI SENTIMEN oleh LLM (LLM-Kita), model bawaan: gpt-5.6-terra.

*** STATUS 24 Sep 2026: MODUL INI TIDAK DIPAKAI LAGI. ***
Tahap penilaian sentimen oleh LLM sudah DILEPAS dari alur kerja, jadi TIDAK ADA
bagian program yang memanggil modul ini (main.py tidak mengimpornya lagi dan
storage.py hanya menjalankan IndoBERTweet). Isi berkas ini sengaja DIBIARKAN utuh
supaya bisa dipakai kembali bila nanti diperlukan — untuk memasangnya lagi, panggil
fungsi di sini dari storage.py dan tambahkan kembali perkiraan waktunya di
bot_config.py.

PERUBAHAN PERAN (22 Sep 2026) — penting dibaca
---------------------------------------------
VERSI LAMA: LLM hanya menjawab `butuh_review` (pantas ditindaklanjuti dinas atau
tidak). Sentimen sepenuhnya diserahkan ke IndoBERTweet, dan LLM cuma MENERIMA
label itu sebagai bahan pertimbangan. Akibatnya label mentah IndoBERT lolos tanpa
pemeriksaan. Bukti nyata pada data 14 Sep 2026: komentar "Subhanallah" dilabeli
NEGATIF dengan keyakinan 99,10% — jelas salah, dan tidak ada yang mengoreksi.

VERSI BARU: LLM DIMINTA MENILAI SENDIRI sentimen setiap komentar
(`sentimen_ai`: POSITIF / NEGATIF / NETRAL) dengan melihat isi + konteks caption,
termasuk sindiran, dialek, singkatan, dan emoji. Label IndoBERT tetap disimpan
sebagai PEMBANDING (kolom `sentimen`), lalu dihitung berapa banyak yang berbeda
(fungsi hitung_kesesuaian_sentimen). `butuh_review` tetap ada sebagai penanda
tindak lanjut, tetapi kini diturunkan dari penilaian LLM yang sudah kontekstual.

Kolom yang ditambahkan ke hasil scraping:
  - sentimen_ai   : penilaian sentimen oleh LLM
  - alasan_ai     : alasan singkat (termasuk bila berbeda dari IndoBERT)
  - alasan_review : alasan perlu/tidak perlu tindak lanjut

Uji cepat tanpa Apify (biaya hanya token LLM, ±beberapa ratus rupiah):
    python llm_reviewer.py

Dukungan multi-key rotation & fallback:
  - beberapa API key di .env dipakai bergiliran kalau ada yang gagal/kuota habis
  - kalau semua key gagal: bot TIDAK mengarang. sentimen_ai diisi mengikuti
    label IndoBERT dan ditandai jelas di kolom alasan_ai.
"""

import json
import queue
import sys
import threading
from typing import Dict, List

import requests

from config import (
    LLM_KOMENTAR_MIN_PER_REQUEST,
    LLM_MAKS_KOMENTAR_PER_BATCH,
    LLM_MAKS_PARALEL,
    LLM_PANJANG_CAPTION,
    LLM_TEMPERATURE,
    LLM_TIMEOUT,
    ambil_base_url_llm,
    ambil_daftar_api_keys,
    ambil_model_llm,
)
from sentiment_analyzer import hitung_statistik_sentimen

# Memastikan output terminal Windows mendukung UTF-8
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

LABEL_SAH = ("POSITIF", "NEGATIF", "NETRAL")


class LLMGagal(Exception):
    """
    Kesalahan saat memanggil LLM, LENGKAP dengan jenisnya.

    KENAPA JENISNYA PENTING (pelajaran mahal 22 Sep 2026):
    versi lama memperlakukan SEMUA kegagalan sama: coba key berikutnya. Padahal kalau
    penyebabnya TIMEOUT (penyedia lambat menjawab permintaan besar), mencoba key lain
    dengan permintaan yang sama besar itu sia-sia — hasilnya 4 key x 180 detik terbuang.
    Sekarang pemanggil bisa membedakan:
      - "timeout"    -> permintaan terlalu besar: dipecah jadi dua, bukan ganti key
      - "kunci"      -> key bermasalah: ganti key memang berguna
      - "rate_limit" -> terlalu banyak permintaan: tunggu/ganti key
      - "umum"       -> gangguan lain (server 5xx, jawaban tidak bisa dibaca)
    """

    def __init__(self, pesan: str, jenis: str = "umum", kode: int = 0):
        super().__init__(pesan)
        self.jenis = jenis
        self.kode = kode

# Terjemahan label asing -> label Indonesia
PETA_LABEL = {
    "POSITIVE": "POSITIF", "NEGATIVE": "NEGATIF", "NEUTRAL": "NETRAL",
    "POSITIF": "POSITIF", "NEGATIF": "NEGATIF", "NETRAL": "NETRAL",
    "LABEL_0": "NEGATIF", "LABEL_1": "NETRAL", "LABEL_2": "POSITIF",
}


# ============================================================
# 1. TITIK MASUK
# ============================================================
def review_komentar_dengan_llm(caption: str, daftar_komentar: List[Dict], top_videos: List = None) -> List[Dict]:
    """
    Menilai sentimen + kebutuhan tindak lanjut untuk SELURUH daftar komentar.

    Mengubah setiap item dengan menambahkan: sentimen_ai, alasan_ai,
    butuh_review, alasan_review.

    Komentar diproses per batch (LLM_MAKS_KOMENTAR_PER_BATCH, bawaan 25) supaya:
      - model tidak kewalahan dan mutu jawaban tetap terjaga;
      - kalau satu batch gagal, batch lain tetap terselamatkan.
    """
    if not daftar_komentar:
        return daftar_komentar

    caption_teks = caption or ""
    if not caption_teks and top_videos:
        caption_teks = "\n---\n".join([v.get("caption") or "" for v in top_videos if v.get("caption")])

    model = ambil_model_llm()
    base_url = ambil_base_url_llm()
    api_keys = ambil_daftar_api_keys()

    total = len(daftar_komentar)
    print(f"[AI] Penilaian sentimen oleh LLM-Kita | model: {model} | {total} komentar "
          f"(diproses per {LLM_MAKS_KOMENTAR_PER_BATCH} komentar)")

    if not api_keys:
        print("⚠️ [WARN] Tidak ada API key LLM-Kita di .env (LLMKITA_API_KEYS). "
              "sentimen_ai akan mengikuti label IndoBERT dan ditandai di kolom alasan_ai.")
        for potongan in _potongan_batch(daftar_komentar):
            _fallback_tanpa_llm(potongan)
        return daftar_komentar

    ukuran_batch = max(1, int(LLM_MAKS_KOMENTAR_PER_BATCH))
    daftar_batch = list(_potongan_batch(daftar_komentar))
    # PENTING (permintaan user 22 Sep 2026): jumlah pekerja TIDAK dibatasi jumlah API key.
    # Kasus nyata nanti hanya punya SATU key/penyedia, dan itu tetap boleh: beberapa
    # permintaan berjalan bersamaan memakai key yang sama. API key tambahan (kalau ada)
    # hanya dipakai sebagai CADANGAN kalau key yang sedang dipakai gagal.
    # Batasnya cuma dua: jumlah batch yang ada, dan LLM_MAKS_PARALEL.
    jumlah_pekerja = max(1, min(int(LLM_MAKS_PARALEL), len(daftar_batch)))

    if jumlah_pekerja > 1:
        print(f"[AI] {len(daftar_batch)} batch dikerjakan BERSAMAAN oleh {jumlah_pekerja} pekerja, "
              f"memakai API key yang sama ({len(api_keys)} key terdaftar; rotasi hanya kalau gagal).")
    else:
        print(f"[AI] {len(daftar_batch)} batch dikerjakan satu per satu.")

    antrean = queue.Queue()
    for nomor, potongan in enumerate(daftar_batch, 1):
        antrean.put((nomor, potongan))

    kunci_cetak = threading.Lock()
    keadaan = {"peringatan_ip": False, "indeks_key": 0}

    def catat(pesan: str):
        """Cetak aman dari banyak thread sekaligus (tanpa ini baris bisa saling menempel)."""
        with kunci_cetak:
            print(pesan)

    def kerjakan(potongan: List[Dict], label: str) -> bool:
        """
        Selesaikan satu potongan komentar. Menangani tiga jenis kegagalan secara berbeda:

        - TIMEOUT     -> permintaan dipecah dua lalu diulang (penyebabnya ukuran permintaan,
                         bukan key yang rusak; mencoba key lain dengan ukuran sama itu sia-sia)
        - kunci/rate  -> ganti key cadangan (di sini ganti key memang masuk akal)
        - gagal total -> fallback jujur: sentimen_ai mengikuti IndoBERT dan ditandai di alasan_ai
        """
        galat_terakhir = ""
        for geser in range(len(api_keys)):
            with kunci_cetak:
                indeks_aktif = keadaan["indeks_key"]
            idx = (indeks_aktif + geser) % len(api_keys)
            key = api_keys[idx]
            key_tampil = key[:6] + "..." + key[-4:] if len(key) > 10 else "***"
            try:
                hasil = _panggil_llm_kita(caption_teks, potongan, key, base_url, model)
                _terapkan_hasil(potongan, hasil)
                _catat_sumber(potongan, f"llm:{model}")
                with kunci_cetak:
                    keadaan["indeks_key"] = idx
                return True
            except LLMGagal as galat:
                galat_terakhir = str(galat)
                catat(f"    ⚠️ {label} gagal di key #{idx + 1} ({key_tampil}) "
                      f"[{galat.jenis}]: {galat_terakhir[:120]}")
                if galat.jenis == "timeout":
                    if len(potongan) > LLM_KOMENTAR_MIN_PER_REQUEST:
                        separuh = max(LLM_KOMENTAR_MIN_PER_REQUEST, len(potongan) // 2)
                        catat(f"    ⏱ {len(potongan)} komentar tidak selesai dalam {LLM_TIMEOUT} detik. "
                              f"Permintaan dipecah jadi {separuh} + {len(potongan) - separuh} lalu diulang "
                              f"(menunggu key lain dengan permintaan sebesar ini tidak ada gunanya).")
                        sukses_a = kerjakan(potongan[:separuh], f"{label}a")
                        sukses_b = kerjakan(potongan[separuh:], f"{label}b")
                        return sukses_a and sukses_b
                    catat(f"    ⚠️ {label} sudah sekecil mungkin "
                          f"({len(potongan)} komentar) tetapi tetap timeout.")
                    break
                # jenis lain (kunci rusak / rate limit / gangguan): coba key cadangan
                if len(api_keys) > 1 and geser < len(api_keys) - 1:
                    catat(f"    🔄 [ROTASI] {label} mencoba key cadangan berikutnya...")
                if "IP is not allowlisted" in galat_terakhir or "403" in galat_terakhir:
                    with kunci_cetak:
                        if not keadaan["peringatan_ip"]:
                            _cetak_peringatan_ip()
                            keadaan["peringatan_ip"] = True
            except Exception as galat:
                galat_terakhir = str(galat)
                catat(f"    ⚠️ {label} gagal (tak terduga): {galat_terakhir[:120]}")

        catat(f"    ⚠️ {label} gagal -> sentimen_ai mengikuti IndoBERT dan ditandai di alasan_ai. "
              f"Galat terakhir: {galat_terakhir[:120]}")
        _fallback_tanpa_llm(potongan)
        return False

    def pekerja(nomor_pekerja: int):
        while True:
            try:
                nomor, potongan = antrean.get_nowait()
            except queue.Empty:
                return

            awal = (nomor - 1) * ukuran_batch + 1
            akhir = awal + len(potongan) - 1
            catat(f"  ▶ Batch {nomor}: komentar {awal}-{akhir} dari {total} | mulai")

            sukses = kerjakan(potongan, f"Batch {nomor}")
            if sukses:
                with kunci_cetak:
                    idx_terakhir = keadaan["indeks_key"]
                keterangan_key = f", key #{idx_terakhir + 1}" if len(api_keys) > 1 else ""
                catat(f"    ✨ Batch {nomor} selesai ({len(potongan)} komentar{keterangan_key}).")

    benang = [threading.Thread(target=pekerja, args=(i,), name=f"llm-pekerja-{i}")
              for i in range(jumlah_pekerja)]
    for t in benang:
        t.start()
    for t in benang:
        t.join()

    return daftar_komentar


def _cetak_peringatan_ip():
    print("\n" + "!" * 75)
    print("🔒 PERHATIAN LLM-KITA: IP KOMPUTER INI BELUM DIDAFTARKAN (ALLOWLISTED)")
    print("!" * 75)
    print(" Buka https://www.llm-kita.com/dashboard -> Settings -> IP Access,")
    print(" daftarkan IP publik komputer ini, lalu jalankan ulang.")
    print("!" * 75 + "\n")


# ============================================================
# 2. PENYUSUN PROMPT
# ============================================================
def _susun_prompt(caption: str, potongan: List[Dict]) -> tuple:
    baris_komentar = []
    for idx, c in enumerate(potongan, 1):
        c_id = c.get("comment_id") or c.get("id") or str(idx)
        c_text = (c.get("text") or "").replace("\n", " ").strip() or "(kosong)"
        c_sentimen = c.get("sentimen") or "NETRAL"
        c_skor = c.get("skor_yakin") or ""
        baris_komentar.append(
            f'{idx}. ID: {c_id} | Teks: "{c_text[:600]}" | Label IndoBERT: {c_sentimen} ({c_skor})'
        )

    prompt_system = (
        "Kamu adalah analis sentimen komentar media sosial untuk Diskominfo Kota Cirebon. "
        "Kamu teliti, tidak asal menyalin label mesin, dan memahami bahasa gaul, singkatan, "
        "serta sindiran yang biasa muncul di kolom komentar media sosial Indonesia."
    )

    prompt_user = f"""KONTEKS CAPTION POSTINGAN (untuk memahami kemungkinan sindiran):
"{(caption or '(caption tidak tersedia)')[:LLM_PANJANG_CAPTION]}"

DAFTAR KOMENTAR YANG HARUS DINILAI:
{chr(10).join(baris_komentar)}

TUGAS
Tentukan sentimen SEBENARNYA dari setiap komentar berdasarkan isi dan konteksnya.
Label IndoBERT hanyalah PEMBANDING — jangan disalin mentah, dan jangan segan berbeda
kalau label itu menurutmu salah.

PEDOMAN PENILAIAN
1. POSITIF : memuji, mendukung, bersyukur, mengapresiasi, menyampaikan kabar baik, nada gembira.
2. NEGATIF : mengeluh, mengkritik, menyindir/sarkas, kecewa, marah, memprotes, kabar buruk.
3. NETRAL  : bertanya tanpa nada menuntut, berbagi informasi, ucapan/doa singkat tanpa arah
             (contoh: "Subhanallah", "amin", "semoga bermanfaat"), emoji saja, spam/iklan.
4. Ucapan doa atau kata religius singkat TIDAK otomatis negatif. Sebaliknya, emoji saja
   dianggap NETRAL kecuali jelas bermakna (contoh: 😡 ditujukan pada layanan).
5. Sindiran terhadap caption dianggap NEGATIF, contoh: "mantap ya, jalannya bagus begini"
   pada postingan jalan rusak.
6. Pertimbangkan dialek/typo/singkatan khas Indonesia (mis. "gimna", "udh", "bgt", "ga", "jg").
7. `butuh_review`: jawab "Ya" HANYA bila komentar pantas ditindaklanjuti dinas
   (pengaduan fasilitas/layanan, kekecewaan serius, pertanyaan resmi yang belum dijawab,
   potensi viral). Selain itu "Tidak".
8. `alasan_ai`: MAKSIMAL 12 KATA. WAJIB sebut perbandingan dengan label IndoBERT
   bila hasilmu berbeda (contoh: "Pujian; sepakat IndoBERT." atau
   "Doa singkat; IndoBERT salah, ini NETRAL.").
9. `alasan_review`: MAKSIMAL 10 KATA, dan tulis "-" saja bila butuh_review "Tidak".

PENTING: jawaban dibatasi pendek karena setiap batch berisi 25 komentar sekaligus;
alasan yang bertele-tele memperlambat seluruh proses.

KEMBALIKAN HANYA JSON ARRAY, TANPA TEKS TAMBAHAN APA PUN:
[
  {{
    "id": "ID_KOMENTAR",
    "sentimen_ai": "POSITIF",
    "alasan_ai": "Pujian tulus; sepakat IndoBERT.",
    "butuh_review": "Tidak",
    "alasan_review": "-"
  }}
]
"""
    return prompt_system, prompt_user


# ============================================================
# 3. Panggilan API & pemasangan hasil
# ============================================================
def _panggil_llm_kita(caption: str, potongan: List[Dict], api_key: str, base_url: str, model_name: str) -> list:
    """
    Kirim satu batch ke LLM-Kita. Returns: daftar dict hasil (mentah dari model).
    Raise Exception kalau HTTP gagal / jawaban tidak bisa dibaca — pemanggil yang
    memutuskan rotasi key atau fallback.
    """
    prompt_system, prompt_user = _susun_prompt(caption, potongan)
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": prompt_system},
            {"role": "user", "content": prompt_user},
        ],
        "temperature": LLM_TEMPERATURE,
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.post(f"{base_url}/chat/completions", json=payload, headers=headers,
                             timeout=(15, LLM_TIMEOUT))
    except requests.exceptions.ReadTimeout:
        raise LLMGagal(f"Timeout: penyedia tidak menjawab dalam {LLM_TIMEOUT} detik "
                       f"untuk {len(potongan)} komentar", "timeout")
    except requests.exceptions.RequestException as galat:
        raise LLMGagal(f"Gagal menghubungi penyedia: {galat}", "umum")

    if resp.status_code in (401, 403):
        raise LLMGagal(f"HTTP {resp.status_code}: {resp.text[:200]}", "kunci", resp.status_code)
    if resp.status_code == 429:
        raise LLMGagal(f"HTTP 429 (rate limit): {resp.text[:200]}", "rate_limit", 429)
    if resp.status_code != 200:
        raise LLMGagal(f"HTTP {resp.status_code}: {resp.text[:200]}", "umum", resp.status_code)

    try:
        isi = resp.json()
        content = isi["choices"][0]["message"]["content"]
    except Exception as galat:
        raise LLMGagal(f"Jawaban penyedia tidak bisa dibaca: {galat}", "umum")

    try:
        return _urai_json(content)
    except Exception as galat:
        raise LLMGagal(f"Jawaban bukan JSON yang bisa dibaca: {galat}", "umum")


def _urai_json(content: str) -> list:
    """
    Ambil JSON array dari jawaban model. Model reasoning kadang menulis penjelasan
    dulu, atau membungkus JSON dengan pagar ```json. Karena itu dibaca bertahap:
    1) buang pagar kode, 2) coba langsung, 3) kalau gagal ambil dari '[' pertama
    sampai ']' terakhir.
    """
    teks = (content or "").strip()
    if "```json" in teks:
        teks = teks.split("```json")[1].split("```")[0].strip()
    elif "```" in teks:
        teks = teks.split("```")[1].split("```")[0].strip()

    try:
        hasil = json.loads(teks)
    except Exception:
        awal = teks.find("[")
        akhir = teks.rfind("]")
        if awal == -1 or akhir == -1 or akhir <= awal:
            raise Exception(f"Jawaban model bukan JSON array: {teks[:200]!r}")
        hasil = json.loads(teks[awal:akhir + 1])

    if isinstance(hasil, dict):
        hasil = [hasil]
    if not isinstance(hasil, list):
        raise Exception("Jawaban model bukan JSON array.")
    return hasil


def _normalkan_label(nilai) -> str:
    label = str(nilai or "").strip().upper()
    return PETA_LABEL.get(label, "NETRAL")


def _terapkan_hasil(potongan: List[Dict], hasil_llm: list):
    """Pasangkan jawaban model ke tiap komentar (berdasarkan ID, cadangan: urutan)."""
    peta = {}
    for item in hasil_llm:
        if isinstance(item, dict) and item.get("id") is not None:
            peta[str(item.get("id"))] = item

    for idx, komentar in enumerate(potongan, 1):
        c_id = str(komentar.get("comment_id") or komentar.get("id") or idx)
        jawab = peta.get(c_id)
        if not jawab and idx <= len(hasil_llm) and isinstance(hasil_llm[idx - 1], dict):
            jawab = hasil_llm[idx - 1]      # cadangan: asumsikan urutan sama

        if not jawab:
            komentar["sentimen_ai"] = komentar.get("sentimen", "NETRAL")
            komentar["alasan_ai"] = "Model tidak memberi jawaban untuk komentar ini; dipakai label IndoBERT."
            komentar["beda_sentimen"] = "Tidak"
            komentar["butuh_review"] = "Tidak"
            komentar["alasan_review"] = "Tidak ada penilaian AI untuk komentar ini."
            continue

        komentar["sentimen_ai"] = _normalkan_label(jawab.get("sentimen_ai"))
        komentar["alasan_ai"] = str(jawab.get("alasan_ai") or "-").strip()
        # Kolom pembanding: penanda cepat kalau IndoBERT dan AI tidak sepakat.
        komentar["beda_sentimen"] = "Ya" if komentar["sentimen_ai"] != komentar.get("sentimen") else "Tidak"
        komentar["butuh_review"] = "Ya" if str(jawab.get("butuh_review", "Tidak")).strip().lower().startswith("y") else "Tidak"
        komentar["alasan_review"] = str(jawab.get("alasan_review") or "-").strip()


def _catat_sumber(potongan: List[Dict], sumber: str):
    """Catat dari mana penilaian berasal (audit: LLM atau fallback)."""
    for komentar in potongan:
        komentar["sumber_penilaian"] = sumber


def _fallback_tanpa_llm(potongan: List[Dict]):
    """
    Dipakai kalau LLM tidak bisa dihubungi sama sekali.
    Prinsipnya JUJUR: sentimen_ai mengikuti IndoBERT, dan itu ditulis terang-terangan
    di alasan_ai supaya pembaca laporan tahu angka ini bukan hasil penilaian AI.
    Pengecualian: butuh_review masih diisi dari aturan heuristik kata kunci + sentimen,
    supaya penanda tindak lanjut tidak hilang total.
    """
    kata_kunci_keluhan = [
        "rusak", "parah", "macet", "sampah", "air", "mati", "lampu", "ktp", "dukcapil",
        "kecewa", "lelet", "berlubang", "banjir", "tanya", "mana", "kenapa", "kok",
        "bagaimana", "tolong", "mohon", "diperbaiki", "lambat", "pemkot", "dinas",
    ]
    for c in potongan:
        sentimen_indo = c.get("sentimen", "NETRAL")
        text_lower = (c.get("text") or "").lower()
        ada_keluhan = any(kw in text_lower for kw in kata_kunci_keluhan)

        c["sumber_penilaian"] = "fallback-indobert"
        c["sentimen_ai"] = sentimen_indo
        c["beda_sentimen"] = "Tidak"          # mengikuti IndoBERT, jadi tidak ada perbedaan
        c["alasan_ai"] = (f"LLM tidak tersedia; sentimen_ai mengikuti label IndoBERT ({sentimen_indo}). "
                          "Angka ini BUKAN hasil penilaian AI.")

        if sentimen_indo == "NEGATIF" or ada_keluhan:
            c["butuh_review"] = "Ya"
            c["alasan_review"] = "Heuristik: sentimen negatif atau memuat kata kunci keluhan layanan."
        else:
            c["butuh_review"] = "Tidak"
            c["alasan_review"] = "Heuristik: komentar umum/positif, tidak perlu tindak lanjut khusus."


def _potongan_batch(daftar: List[Dict]):
    """Pecah daftar komentar menjadi batch berukuran LLM_MAKS_KOMENTAR_PER_BATCH."""
    ukuran = max(1, int(LLM_MAKS_KOMENTAR_PER_BATCH))
    for awal in range(0, len(daftar), ukuran):
        yield daftar[awal:awal + ukuran]


# ============================================================
# 4. STATISTIK
# ============================================================
def hitung_statistik_sentimen_ai(daftar_komentar: List[Dict]) -> Dict:
    """Ringkasan sentimen hasil penilaian AI (kolom sentimen_ai)."""
    return hitung_statistik_sentimen(daftar_komentar, kunci="sentimen_ai")


def hitung_kesesuaian_sentimen(daftar_komentar: List[Dict]) -> Dict:
    """
    Bandingkan penilaian AI dengan label IndoBERT.
    Angka ini yang menjawab pertanyaan: "seberapa sering IndoBERT keliru?"
    """
    dinilai = [c for c in daftar_komentar if c.get("sentimen_ai")]
    total = len(daftar_komentar)
    if not dinilai:
        return {"total": total, "dinilai_ai": 0, "sama": 0, "beda": 0, "beda_pct": "0.00%"}

    sama = sum(1 for c in dinilai if c.get("sentimen_ai") == c.get("sentimen"))
    beda = len(dinilai) - sama
    return {
        "total": total,
        "dinilai_ai": len(dinilai),
        "sama": sama,
        "beda": beda,
        "beda_pct": f"{(beda / len(dinilai)) * 100:.2f}%",
    }


def hitung_statistik_review(daftar_komentar: List[Dict]) -> Dict:
    """Ringkasan penanda tindak lanjut (kolom butuh_review: Ya vs Tidak)."""
    total = len(daftar_komentar)
    if total == 0:
        return {"total": 0, "YA": 0, "YA_pct": "0.00%", "TIDAK": 0, "TIDAK_pct": "0.00%"}

    ya = sum(1 for c in daftar_komentar if c.get("butuh_review") == "Ya")
    tidak = total - ya
    return {
        "total": total,
        "YA": ya,
        "YA_pct": f"{(ya / total) * 100:.2f}%",
        "TIDAK": tidak,
        "TIDAK_pct": f"{(tidak / total) * 100:.2f}%",
    }


# ============================================================
# 5. UJI CEPAT TANPA APIFY: python llm_reviewer.py
# ============================================================
CONTOH_KOMENTAR = [
    {"comment_id": "uji1", "text": "Subhanallah", "sentimen": "NEGATIF", "skor_yakin": "99.10%"},
    {"comment_id": "uji2", "text": "jalan rusak parah kok dibiarkan sampe sekarang",
     "sentimen": "NETRAL", "skor_yakin": "51.20%"},
    {"comment_id": "uji3", "text": "mantap ya, jalannya bagus begini 🙏",
     "sentimen": "POSITIF", "skor_yakin": "88.00%"},
    {"comment_id": "uji4", "text": "kapan diperbaiki pak? sudah 3 bulan begini",
     "sentimen": "NEGATIF", "skor_yakin": "90.10%"},
    {"comment_id": "uji5", "text": "Terima kasih Pak Wali, akhirnya lampu jalannya nyala",
     "sentimen": "POSITIF", "skor_yakin": "97.30%"},
    {"comment_id": "uji6", "text": "amin semoga bermanfaat bgt",
     "sentimen": "NETRAL", "skor_yakin": "70.00%"},
]

CAPTION_UJI = (
    "Perbaikan jalan di Kecamatan Harjamukti Kota Cirebon ditargetkan rampung bulan ini. "
    "Pemkot Cirebon meminta warga melaporkan jalan rusak melalui kanal pengaduan."
)


def uji_cepat():
    """Menjalankan LLM atas komentar contoh, lalu mencetak tabel perbandingan."""
    print("=" * 96)
    print("  UJI CEPAT PENILAIAN SENTIMEN OLEH LLM (tanpa Apify, tanpa scraping)")
    print("=" * 96)
    print(f"  Model : {ambil_model_llm()}")
    print(f"  Endpoint: {ambil_base_url_llm()}")
    print(f"  Jumlah API key: {len(ambil_daftar_api_keys())}")
    print("-" * 96)

    hasil = review_komentar_dengan_llm(CAPTION_UJI, [dict(k) for k in CONTOH_KOMENTAR])

    print("\n" + "=" * 96)
    print(f"{'TEKS':<44} {'INDOBERT':<10} {'AI':<9} {'REVIEW':<7} ALASAN")
    print("-" * 96)
    for k in hasil:
        teks = (k.get("text") or "")[:42]
        print(f"{teks:<44} {k.get('sentimen', '-'):<10} {k.get('sentimen_ai', '-'):<9} "
              f"{k.get('butuh_review', '-'):<7} {(k.get('alasan_ai') or '')[:60]}")
    print("=" * 96)

    selisih = hitung_kesesuaian_sentimen(hasil)
    print(f"  Kesesuaian dengan IndoBERT : {selisih['sama']} sama, {selisih['beda']} berbeda "
          f"({selisih['beda_pct']} berbeda)")
    print(f"  Ringkasan sentimen AI      : {hitung_statistik_sentimen_ai(hasil)}")
    print(f"  Ringkasan tindak lanjut    : {hitung_statistik_review(hasil)}")
    print("\n  Yang perlu diperiksa mata: apakah sentimen_ai di baris 'Subhanallah' dan")
    print("  'mantap ya, jalannya bagus begini' sudah benar (dua-duanya uji sindiran/doa).")


if __name__ == "__main__":
    uji_cepat()
