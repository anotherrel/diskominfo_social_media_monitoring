# -*- coding: utf-8 -*-
"""
llm_reviewer.py (modul TikTok) — VERSI SEDERHANA (18 Sep 2026)
=============================================================
Dua tugas:

1. `panggil_llm_json()`        -> TRANSPORT. Kirim prompt ke LLM-Kita, kembalikan JSON
                                  (rotasi API key, timeout, pembersih jawaban).
2. `review_posts_dengan_llm()` -> GATE PENILAIAN. Ini penentu relevansi yang sebenarnya.

PRINSIP GATE (hasil uji 18 Sep 2026, lihat DESAIN.md "Revisi 18 Sep 2026")
-------------------------------------------------------------------------
- AI menilai RELEVAN/TIDAK dengan belajar dari 3-5 CONTOH VIDEO yang diisi user
  (captionnya dikirim apa adanya ke prompt) + ciri relevan umum di bawah.
- Tidak ada bobot kata, tidak ada ambang skor. Uji terukur: gerbang 1 kata wilayah + gate ini
  menerima 42-44 video dari 103 (versi lama: 12), dan menolak Kabupaten/kota lain/konten jualan
  dengan tepat (uji 16 kasus, 15 benar).
- Jawaban ada 3 nilai: YA / TIDAK / RAGU. RAGU = "perlu mata manusia", jangan menebak.
- Pelajaran penting yang sudah ditanam di prompt:
  (a) caption JANGAN dipotong pendek (LLM_PANJANG_CAPTION) — memotong 300 karakter pernah
      menyembunyikan kata wilayah di karakter ke-563 dan membuat AI salah menilai;
  (b) kalau topik hanya muncul sebagai HASHTAG tanpa kalimat pendukung -> RAGU
      (mencegah false positive seperti "Berangkat, Cirebon kami datang #becaklistrik");
  (c) video netizen pendek tanpa kata "kota" tetap dianggap wilayah sasaran;
  (d) ciri dialek lokal dianggap penguat wilayah.
- Kalau AI gagal total (semua key/API mati), hasil ditandai FALLBACK + RAGU secara terang-terangan.
  JANGAN pernah menandai "YA" diam-diam: gate yang tidak jalan tidak boleh tampak seperti jalan.
"""

import json
import sys

import requests

from config import (
    LLM_TIMEOUT,
    LLM_TEMPERATURE,
    LLM_MAKS_POST_PER_BATCH,
    LLM_PANJANG_CAPTION,
    ambil_daftar_api_keys,
    ambil_base_url_llm,
    ambil_model_llm,
    keterangan_wilayah,
    tanda_lokal,
    kata_gerbang,
)
from evaluator import muat_kaidah

# Terminal Windows: paksa UTF-8 supaya emoji/aksen tidak bikin error
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


class GagalLLM(Exception):
    """Dilempar kalau semua API key gagal dipakai."""
    pass


# ============================================================
# 1. TRANSPORT: KIRIM PROMPT -> DAPAT JSON
# ============================================================
def _bersihkan_jawaban_llm(teks: str):
    """
    Ambil JSON dari jawaban LLM. Model kadang membungkus dengan ```json ... ``` atau menambah kalimat.
    """
    teks = (teks or "").strip()

    if "```" in teks:
        bagian = teks.split("```")
        for potong in bagian:
            potong = potong.strip()
            if potong.lower().startswith("json"):
                potong = potong[4:].strip()
            if potong.startswith("{") or potong.startswith("["):
                teks = potong
                break

    if teks.startswith("{") or teks.startswith("["):
        try:
            return json.loads(teks)
        except Exception:
            pass

    # jalan terakhir: ambil dari kurung pertama sampai kurung terakhir
    for buka, tutup in (("{", "}"), ("[", "]")):
        awal, akhir = teks.find(buka), teks.rfind(tutup)
        if awal != -1 and akhir > awal:
            try:
                return json.loads(teks[awal:akhir + 1])
            except Exception:
                continue

    raise GagalLLM("Jawaban LLM tidak bisa dibaca sebagai JSON.")


def _panggil_chat(prompt_system: str, prompt_user: str, api_key: str) -> str:
    """Kirim 1 permintaan chat ke LLM-Kita, kembalikan isi teks jawabannya."""
    url = f"{ambil_base_url_llm()}/chat/completions"
    payload = {
        "model": ambil_model_llm(),
        "messages": [
            {"role": "system", "content": prompt_system},
            {"role": "user", "content": prompt_user},
        ],
        "temperature": LLM_TEMPERATURE,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=LLM_TIMEOUT)
    if resp.status_code != 200:
        raise GagalLLM(f"HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        raise GagalLLM(f"Bentuk jawaban LLM tidak dikenal: {str(data)[:300]}")


def panggil_llm_json(prompt_system: str, prompt_user: str):
    """
    Kirim prompt ke LLM-Kita dengan ROTASI API KEY.

    Returns: hasil json.loads (bisa dict atau list)
    Raises : GagalLLM kalau semua key gagal.
    """
    daftar_key = ambil_daftar_api_keys()
    if not daftar_key:
        raise GagalLLM(
            "Tidak ada API key LLM-Kita. Isi LLMKITA_API_KEYS di file .env "
            "(boleh 1 key, boleh beberapa dipisah koma)."
        )

    model = ambil_model_llm()
    peringatan_ip_sudah = False
    kesalahan_terakhir = ""

    for nomor, key in enumerate(daftar_key, 1):
        key_samar = (key[:6] + "..." + key[-4:]) if len(key) > 10 else "***"
        try:
            print(f"  [LLM] Mengirim permintaan (key #{nomor}: {key_samar} | model: {model})...")
            jawaban = _panggil_chat(prompt_system, prompt_user, key)
            hasil = _bersihkan_jawaban_llm(jawaban)
            print("  ✅ Jawaban LLM diterima & berhasil dibaca sebagai JSON.")
            return hasil
        except Exception as e:
            kesalahan_terakhir = str(e)
            print(f"  ⚠️ Key #{nomor} gagal: {kesalahan_terakhir[:200]}")

            if ("IP is not allowlisted" in kesalahan_terakhir or "403" in kesalahan_terakhir) and not peringatan_ip_sudah:
                print("\n" + "!" * 70)
                print("🔒 IP KOMPUTER INI BELUM DIDAFTARKAN DI LLM-KITA (allowlist).")
                print("   Daftarkan di: https://www.llm-kita.com/dashboard -> Settings -> IP Access")
                print("   Selama belum didaftarkan, penilaian AI tidak akan berjalan.")
                print("!" * 70 + "\n")
                peringatan_ip_sudah = True

            if nomor < len(daftar_key):
                print(f"  🔄 Beralih ke API key #{nomor + 1}...")

    raise GagalLLM(f"Semua {len(daftar_key)} API key gagal. Kesalahan terakhir: {kesalahan_terakhir}")


# ============================================================
# 2. PROMPT GATE (TEMPLATE GLOBAL — bisa dipakai topik/kota apa pun)
# ============================================================
def susun_prompt_gate(nama_topik: str, daftar_post: list, contoh_acuan: list = None,
                      contoh_negatif: list = None, kaidah: dict = None) -> tuple:
    """
    Susun (prompt_system, prompt_user) untuk menilai relevansi sekumpulan post.

    Semua nama wilayah diambil dari kaidah/kota_cirebon.json -> prompt ini TIDAK
    mengandung nama kota/topik tertentu di dalam kode.
    """
    kaidah = kaidah or muat_kaidah()
    wil = keterangan_wilayah(kaidah)
    lokal = tanda_lokal(kaidah)
    daftar_kata_lokal = ", ".join((lokal.get("dialek") or []) + (lokal.get("nama_kawasan_kota") or []) + (lokal.get("nama_kawasan_kabupaten") or []))

    baris_post = []
    for i, p in enumerate(daftar_post, 1):
        hashtag = " ".join(f"#{t}" for t in (p.get("hashtag_list") or [])) or "(tidak ada)"
        baris_post.append(
            f"{i}. ID: {p.get('post_id', '')} | Akun: {p.get('username', '-')} "
            f"| Tanggal: {p.get('published_at', '-')}\n"
            f"   Caption: \"{(p.get('caption') or '(KOSONG)')[:LLM_PANJANG_CAPTION]}\"\n"
            f"   Hashtag: {hashtag}"
        )

    blok_contoh = "\n".join(f'{i}. "{c[:LLM_PANJANG_CAPTION]}"'
                            for i, c in enumerate(contoh_acuan or [], 1)) or "(belum ada contoh)"
    blok_negatif = ""
    if contoh_negatif:
        daftar_neg = "\n".join(
            f"- \"{(c.get('caption') or '')[:200]}\" (alasan dulu: {c.get('alasan_llm', '-')})"
            for c in contoh_negatif
        )
        blok_negatif = f"\nPOST YANG PERNAH DINILAI TIDAK RELEVAN (jangan loloskan lagi):\n{daftar_neg}\n"

    prompt_system = (
        f"Kamu analis intelijen media Pemerintah Kota Cirebon. Tugasmu menilai apakah sebuah "
        f"postingan Facebook BENAR-BENAR membahas topik yang diminta DAN berlokasi di {wil['wilayah_nama']} "
        f"(bukan wilayah lain), lalu mengklasifikasikan wilayahnya. Nilai HANYA dari caption, hashtag, dan nama akun. Jangan mengarang "
        f"bukti yang tidak ada. Waspada: banyak konten dari wilayah lain memakai nama wilayah sasaran "
        f"supaya ikut ramai."
    )

    prompt_user = f"""TOPIK YANG DIPANTAU: "{nama_topik}"

WILAYAH SASARAN: {wil['wilayah_nama']}
BUKAN sasaran: {wil['wilayah_bukan']}

POSTINGAN YANG SUDAH PASTI RELEVAN (acuan dari user — pakai sebagai rasa acuan):
{blok_contoh}

CATATAN: video netizen pendek (1 kalimat + hashtag) SAMA relevannya dengan berita panjang.
Jangan menolak hanya karena captionnya pendek, singkat, atau bahasanya santai.

CIRI RELEVAN:
- membahas topik di atas dan peristiwanya terjadi di wilayah sasaran;
- sudut pandang boleh apa saja: penyaluran, dampak ke warga/pelaku, keluhan, kasus viral,
  kritik, atau tanggapan netizen;
- penanda bahasa/daerah sasaran yang menguatkan wilayah: {daftar_kata_lokal}
{blok_negatif}
CARA MENILAI (WAJIB DIIKUTI):
1. Caption hanya menyebut nama wilayah dasar (mis. "{kata_gerbang(kaidah)[0] if kata_gerbang(kaidah) else 'nama wilayah'}")
   tanpa spesifik -> ANGGAP wilayah sasaran, selama tidak ada bukti wilayah lain. Beri kategori "none" (umum).
2. Ada nama kawasan/kelurahan/kecamatan wilayah sasaran -> pasti wilayah sasaran. Jika itu wilayah Kota Cirebon, beri kategori "kota". Jika itu wilayah Kabupaten Cirebon, beri kategori "kabupaten".
3. Ada nama wilayah lain di luar sasaran (provinsi/kota/kabupaten lain) DAN tidak ada satu pun nama wilayah
   sasaran -> jawab TIDAK.
4. Topiknya sama tapi jelas terjadi di luar wilayah sasaran -> TIDAK.
5. Isu berbeda (produk sejenis tapi bukan isu ini, iklan, jualan, hiburan, acara lain) -> TIDAK.
6. Kalau kata topik HANYA muncul sebagai HASHTAG sementara kalimat captionnya TIDAK menjelaskan
   isu apa pun (mis. hanya "berangkat kami datang", atau caption kosong) -> jawab "RAGU".
   Kalau kalimat captionnya jelas membahas isu (walau singkat/dialek), baru jawab YA.
7. Kalau benar-benar tidak cukup bukti -> jawab "RAGU". Jangan menebak.

POSTINGAN YANG HARUS DINILAI ({len(daftar_post)} buah):
{chr(10).join(baris_post)}

KEMBALIKAN HANYA JSON ARRAY (satu objek per post, urut):
[
  {{"id": "ID_POST", "is_relevan": "YA", "kategori": "kota", "alasan": "alasan singkat maks 20 kata"}}
]
Nilai is_relevan hanya: "YA" / "TIDAK" / "RAGU".
Nilai kategori hanya: "kota" / "kabupaten" / "none"."""

    return prompt_system, prompt_user


# ============================================================
# 3. GATE: NILAI POST DENGAN AI
# ============================================================
_NILAI_SAH = ("YA", "TIDAK", "RAGU")


def _pasang_hasil_ke_post(daftar_post: list, hasil_llm) -> list:
    """Tempelkan hasil penilaian LLM ke masing-masing dict post."""
    peta = {}
    for butir in hasil_llm or []:
        if isinstance(butir, dict) and butir.get("id") is not None:
            peta[str(butir["id"])] = butir

    for urutan, p in enumerate(daftar_post, 1):
        kunci = str(p.get("post_id", ""))
        butir = peta.get(kunci)

        # cadangan: kalau LLM tidak menulis ID dengan benar, pakai urutan array
        if not butir and isinstance(hasil_llm, list) and urutan <= len(hasil_llm) and isinstance(hasil_llm[urutan - 1], dict):
            butir = hasil_llm[urutan - 1]

        if butir:
            nilai = str(butir.get("is_relevan", "RAGU")).strip().upper()
            p["is_relevan_llm"] = nilai if nilai in _NILAI_SAH else "RAGU"
            kat = str(butir.get("kategori", "none")).strip().lower()
            p["kategori"] = kat if kat in ("kota", "kabupaten", "none") else "none"
            p["alasan_review_llm"] = str(butir.get("alasan", "Dinilai AI."))[:500]
        else:
            # tidak ada penilaian -> jangan mengaku YA. Masukkan ke tumpukan periksa manusia.
            p["is_relevan_llm"] = "RAGU"
            p["kategori"] = "none"
            p["alasan_review_llm"] = "TIDAK DINILAI AI (jawaban tidak memuat post ini) — periksa manual."

    return daftar_post


def _fallback_heuristik(daftar_post: list, pesan_error: str = "") -> list:
    """
    Dipakai HANYA kalau AI tidak bisa jalan. Semua post ditandai FALLBACK + RAGU,
    supaya tidak ada yang lolos diam-diam seolah sudah diverifikasi AI.
    """
    for p in daftar_post:
        p["is_relevan_llm"] = "RAGU"
        p["kategori"] = "none"
        p["alasan_review_llm"] = (
            f"FALLBACK (AI tidak berjalan): perlu diperiksa manual. Cek API key/allowlist IP. "
            f"Error: {pesan_error[:150]}"
        )
    return daftar_post


def review_posts_dengan_llm(daftar_post: list, nama_topik: str, kaidah: dict = None,
                            contoh_acuan: list = None, contoh_negatif: list = None) -> list:
    """
    Gate penilaian: menilai tiap post dengan AI.

    Menambahkan ke setiap post:
      - is_relevan_llm   : "YA" / "TIDAK" / "RAGU"
      - wilayah_llm      : "sasaran" / "bukan_sasaran" / "luar" / "tidak_jelas"
      - alasan_review_llm: alasan dari AI

    Prompt dipecah per batch (LLM_MAKS_POST_PER_BATCH) supaya tidak melebihi kapasitas model.
    """
    if not daftar_post:
        return daftar_post

    kaidah = kaidah or muat_kaidah()
    total = len(daftar_post)
    print(f"\n  🤖 Gate AI: menilai {total} post (topik: {nama_topik})...")
    if contoh_acuan:
        print(f"     Acuan: {len(contoh_acuan)} contoh video dari user.")

    for mulai in range(0, total, LLM_MAKS_POST_PER_BATCH):
        batch = daftar_post[mulai:mulai + LLM_MAKS_POST_PER_BATCH]
        nomor_batch = (mulai // LLM_MAKS_POST_PER_BATCH) + 1
        jumlah_batch = (total + LLM_MAKS_POST_PER_BATCH - 1) // LLM_MAKS_POST_PER_BATCH
        print(f"     Batch {nomor_batch}/{jumlah_batch} ({len(batch)} post)...")

        prompt_system, prompt_user = susun_prompt_gate(nama_topik, batch, contoh_acuan, contoh_negatif, kaidah)
        try:
            hasil_llm = panggil_llm_json(prompt_system, prompt_user)
            if isinstance(hasil_llm, dict) and "hasil" in hasil_llm:
                hasil_llm = hasil_llm["hasil"]
            _pasang_hasil_ke_post(batch, hasil_llm)
        except Exception as e:
            print(f"     ❌ Batch {nomor_batch} gagal dinilai AI: {str(e)[:200]}")
            _fallback_heuristik(batch, str(e))

    jumlah = {"YA": 0, "TIDAK": 0, "RAGU": 0}
    for p in daftar_post:
        jumlah[str(p.get("is_relevan_llm", "RAGU")).upper()] = jumlah.get(str(p.get("is_relevan_llm", "RAGU")).upper(), 0) + 1
    jumlah_fallback = sum(1 for p in daftar_post if "FALLBACK" in str(p.get("alasan_review_llm", "")))

    print(f"  ✅ Gate selesai: YA {jumlah.get('YA', 0)} | TIDAK {jumlah.get('TIDAK', 0)} | "
          f"RAGU {jumlah.get('RAGU', 0)}")
    if jumlah_fallback:
        print("\n" + "!" * 70)
        print(f"🔴 {jumlah_fallback} post memakai FALLBACK — AI TIDAK BERJALAN. Periksa API key/allowlist,")
        print("   lalu jalankan ulang. Angka di atas belum bisa dipakai untuk laporan.")
        print("!" * 70)
    return daftar_post
