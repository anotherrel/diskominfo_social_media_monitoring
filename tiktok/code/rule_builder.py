# -*- coding: utf-8 -*-
"""
rule_builder.py (modul TikTok) — VERSI SEDERHANA (18 Sep 2026)
=============================================================
Tugas file ini SEKARANG cuma 3:

  1. Mengelola CONTOH VIDEO (seed) yang diisi user: baca, validasi, simpan.
     Contoh inilah yang "mengajari" AI — captionnya dikirim apa adanya ke prompt gate.
  2. Mengisi caption contoh otomatis dari URL (mode 'postURLs' actor, biaya kecil).
  3. Membuat VARIAN KATA KUNCI pencarian (3-5 buah, wajib memuat kata wilayah).

Yang SUDAH DIHAPUS (jangan dihidupkan lagi tanpa alasan kuat):
  - induksi "rule set" berbobot kata + ambang skor
  - uji mandiri (recall test) terhadap ambang
  - pengecualian ber-konteks

Alasannya: versi lama mencetak aturan 0,75 secara default, sementara kata inti topik hanya
berbobot 0,30 -> caption yang menyebut topiknya sendiri pun GUGUR. Terukur: dari 103 video
nyata hanya 12 lolos, padahal 42 relevan. Contoh videonya juga semua bergaya berita panjang
dari akun media, jadi "uji mandiri 3/3 lulus" tidak membuktikan apa pun untuk gaya netizen.
"""

import json
from pathlib import Path

from config import (
    MIN_KATA_CAPTION,
    MIN_CONTOH,
    SARAN_JUMLAH_CONTOH,
    JUMLAH_VARIAN_QUERY,
    MAKS_CONTOH_NEGATIF_DI_PROMPT,
    folder_topik,
    kata_gerbang,
    kata_gerbang_pertama,
)
from evaluator import jumlah_kata_bermakna, muat_kaidah


# ============================================================
# 1. CONTOH VIDEO (SEED) — dibaca/ditulis di file teks biasa
# ============================================================
def parse_baris_contoh(baris: str) -> dict:
    """
    Ubah 1 baris file contoh jadi dict.
    Format: URL | caption apa adanya
    Baris tanpa tanda '|' dianggap URL saja (captionnya kosong -> nanti ditolak dengan pesan jelas).
    """
    baris = (baris or "").strip()
    if "|" in baris:
        url, _, caption = baris.partition("|")
    else:
        url, caption = baris, ""
    return {"url": url.strip(), "caption": caption.strip(), "baris_asli": baris}


def baca_file_contoh(path) -> list:
    """
    Baca file contoh.txt -> daftar contoh (baris kosong & baris berawalan # dilewati).

    CATATAN PENTING: satu contoh = SATU baris. Baris yang tidak memuat "http" dianggap
    lanjutan/sampah dan dilewati. (Dulu caption multi-baris ikut terbaca sebagai contoh baru
    tanpa URL -> muncul pesan "URL kosong" yang membingungkan.)
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File contoh tidak ditemukan: {path}")
    hasil = []
    for nomor, baris in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not baris.strip() or baris.strip().startswith("#"):
            continue
        if "http" not in baris.lower():
            continue  # bukan baris contoh
        item = parse_baris_contoh(baris)
        item["nomor_baris"] = nomor
        hasil.append(item)
    return hasil


def validasi_contoh(daftar_contoh: list) -> tuple:
    """
    Periksa kelayakan contoh SEBELUM dipakai AI.

    - URL wajib ada & diawali http.
    - Caption WAJIB ada dan minimal MIN_KATA_CAPTION kata bermakna (hashtag & URL tidak dihitung).
      Video yang captionnya cuma "#fyp #cirebon" DITOLAK -> pilih video lain.
      Ini penting: contoh yang miskin kata membuat AI menebak-nebak.
    - URL ganda dibuang otomatis.

    Returns: (contoh_sah, daftar_tolak)
    """
    contoh_sah = []
    ditolak = []
    url_sudah_ada = set()

    for item in daftar_contoh or []:
        url = (item.get("url") or "").strip()
        caption = (item.get("caption") or "").strip()
        label = url or f"baris {item.get('nomor_baris', '?')}"

        if not url:
            ditolak.append({**item, "alasan": "URL kosong"})
            continue
        if not url.lower().startswith("http"):
            ditolak.append({**item, "alasan": f"URL tidak diawali http: {url}"})
            continue
        if url in url_sudah_ada:
            ditolak.append({**item, "alasan": "URL ganda (sudah ada di daftar)"})
            continue
        if not caption:
            ditolak.append({**item, "alasan": f"{label}: caption kosong (kirim dengan format 'URL | caption')"})
            continue

        jml_kata = jumlah_kata_bermakna(caption)
        if jml_kata < MIN_KATA_CAPTION:
            if len(caption.strip()) >= 3:
                jml_kata = max(jml_kata, 1)
            else:
                ditolak.append({
                    **item,
                    "alasan": (f"{label}: caption terlalu pendek ({jml_kata} kata)."),
                })
                continue

        url_sudah_ada.add(url)
        contoh_sah.append({**item, "jumlah_kata": jml_kata})

    return contoh_sah, ditolak


def simpan_contoh(nama_topik: str, contoh_sah: list) -> Path:
    """
    Simpan contoh yang sudah lolos validasi ke topik/<slug>/contoh.txt.

    Caption DIRAPATKAN jadi 1 baris (newline -> spasi). Wajib, karena format file ini
    "1 contoh = 1 baris": caption multi-baris bikin contoh berikutnya terbaca tanpa URL.
    """
    folder = folder_topik(nama_topik)
    path = folder / "contoh.txt"
    baris_keluar = ["# Format: URL | caption apa adanya (satu contoh = satu baris)", f"# Topik: {nama_topik}", ""]
    for item in contoh_sah:
        caption = " ".join((item.get("caption") or "").split())
        baris_keluar.append(f"{item['url']} | {caption}")
    path.write_text("\n".join(baris_keluar) + "\n", encoding="utf-8")
    return path


def muat_contoh_tersimpan(nama_topik: str) -> list:
    """Baca contoh yang pernah disimpan; kosong kalau belum ada."""
    path = folder_topik(nama_topik) / "contoh.txt"
    if not path.exists():
        return []
    return baca_file_contoh(path)


def caption_contoh_untuk_ai(nama_topik: str, batas: int = 5) -> list:
    """
    Ambil caption contoh yang akan dikirim ke prompt gate (ini 'bahan belajar' AI).
    Returns: list of str
    """
    contoh = muat_contoh_tersimpan(nama_topik)
    keluaran = []
    for item in contoh[:batas]:
        cap = " ".join((item.get("caption") or "").split())
        if cap:
            keluaran.append(cap)
    return keluaran


# ============================================================
# 2. CONTOH NEGATIF (umpan balik dari run sebelumnya)
# ============================================================
def muat_contoh_negatif(nama_topik: str) -> list:
    """Baca post yang dulu dinilai TIDAK relevan AI. Dikirim lagi ke prompt sebagai pengingat."""
    path = folder_topik(nama_topik) / "contoh_negatif.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def simpan_contoh_negatif(nama_topik: str, negatif_baru: list) -> Path:
    """
    Tambahkan temuan 'tidak relevan' ke topik/<slug>/contoh_negatif.json.
    Digabung dengan temuan lama, dibatasi 100 entri terakhir supaya tetap ringan.
    """
    folder = folder_topik(nama_topik)
    path = folder / "contoh_negatif.json"

    lama = muat_contoh_negatif(nama_topik)
    url_sudah_ada = {c.get("url", "") for c in lama}

    gabungan = list(lama)
    for item in negatif_baru:
        if item.get("url") and item["url"] not in url_sudah_ada:
            url_sudah_ada.add(item["url"])
            gabungan.append(item)

    gabungan = gabungan[-100:]
    path.write_text(json.dumps(gabungan, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def contoh_negatif_untuk_prompt(nama_topik: str) -> list:
    """Ambil contoh negatif (dibatasi) untuk dikirim ke prompt."""
    return muat_contoh_negatif(nama_topik)[-MAKS_CONTOH_NEGATIF_DI_PROMPT:]


# ============================================================
# 3. VARIAN KATA KUNCI PENCARIAN
# ============================================================
def _varian_cadangan(nama_topik: str, kata: str) -> list:
    """Kalau AI tidak bisa dipakai: varian sederhana tapi tetap berisi kata wilayah."""
    dasar = (nama_topik or "").strip()
    return [f"{dasar} {kata}", f"{dasar} {kata} terbaru", f"berita {dasar} {kata}"]


def normalisasi_varian(daftar: list, kata: str) -> list:
    """
    Rapikan varian kata kunci:
    - dibuang yang kosong / ganda
    - WAJIB memuat kata wilayah (TikTok tidak punya filter lokasi, jadi kata wilayah
      adalah satu-satunya cara agar hasil pencarian relevan wilayah)
    - dibatasi JUMLAH_VARIAN_QUERY
    """
    min_v, maks_v = JUMLAH_VARIAN_QUERY
    keluaran = []
    for q in daftar or []:
        q = " ".join(str(q).split())
        if not q or q.lower() in [x.lower() for x in keluaran]:
            continue
        if kata and kata.lower() not in q.lower():
            q = f"{q} {kata}"
        keluaran.append(q)

    if len(keluaran) < min_v:
        for q in _varian_cadangan("topik", kata):
            if len(keluaran) >= min_v:
                break
            if q.lower() not in [x.lower() for x in keluaran]:
                keluaran.append(q)

    return keluaran[:maks_v]


def susun_prompt_varian(nama_topik: str, contoh_sah: list, kata: str) -> tuple:
    """Prompt singkat: minta AI membuat 3-5 kata kunci pencarian TikTok."""
    min_v, maks_v = JUMLAH_VARIAN_QUERY
    blok = "\n".join(f'{i}. "{item["caption"]}"' for i, item in enumerate(contoh_sah, 1))

    prompt_system = (
        "Kamu analis media sosial Pemerintah Kota Cirebon. Tugasmu menyusun kata kunci "
        "pencarian TikTok (bukan aturan penyaringan)."
    )
    prompt_user = f"""TOPIK: "{nama_topik}"
WILAYAH: Kota Cirebon.

CONTOH VIDEO YANG SUDAH PASTI RELEVAN:
{blok}

Buat {min_v}-{maks_v} kata kunci pencarian TikTok untuk menemukan video lain seperti contoh di atas.
Ketentuan:
- Setiap kata kunci WAJIB memuat kata "{kata}" (TikTok tidak punya filter lokasi).
- Buat variasinya BENAR-BENAR BEDA, jangan hanya menambah kata sambung. Contoh cara membedakan:
  pakai nama tokoh/instansi, nama kawasan kota, istilah yang dipakai netizen, atau sudut masalah
  yang berbeda (mis. kasus penjualan, keluhan penghasilan, penyaluran unit).
- Bahasa natural seperti yang orang ketik di kolom pencarian TikTok.

KEMBALIKAN HANYA JSON ARRAY, contoh bentuk: ["...", "...", "..."]"""

    return prompt_system, prompt_user


def simpan_varian(nama_topik: str, varian: list, sumber: str) -> Path:
    """Simpan varian kata kunci ke topik/<slug>/varian_query.json."""
    path = folder_topik(nama_topik) / "varian_query.json"
    path.write_text(json.dumps({"sumber": sumber, "varian_query": varian}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def muat_varian(nama_topik: str) -> list:
    """Baca varian kata kunci yang pernah disimpan; kosong kalau belum ada."""
    path = folder_topik(nama_topik) / "varian_query.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [str(x) for x in (data.get("varian_query") or [])]
    except Exception:
        return []


def buat_varian_query(nama_topik: str, contoh_sah: list, kaidah: dict = None,
                      paksa_ulang: bool = False) -> list:
    """
    Hasilkan varian kata kunci pencarian untuk 1 topik.

    - Kalau file varian sudah ada dan tidak dipaksa ulang -> pakai yang tersimpan (hemat & konsisten).
    - Kalau AI gagal -> pakai varian cadangan yang tetap memuat kata wilayah (tidak bikin run gagal).
    """
    kaidah = kaidah or muat_kaidah()
    kata = kata_gerbang_pertama(kaidah)

    if not paksa_ulang:
        lama = muat_varian(nama_topik)
        if lama:
            print(f"  ℹ️ Varian kata kunci sudah ada -> dipakai ulang: {lama}")
            return lama

    try:
        from llm_reviewer import panggil_llm_json
        print(f"  🤖 Meminta AI membuat varian kata kunci pencarian (wajib memuat '{kata}')...")
        ps, pu = susun_prompt_varian(nama_topik, contoh_sah, kata)
        hasil = panggil_llm_json(ps, pu)
        if isinstance(hasil, dict):
            hasil = hasil.get("varian_query") or hasil.get("hasil") or []
        varian = normalisasi_varian(hasil, kata)
        sumber = "ai"
    except Exception as e:
        print(f"  ⚠️ AI gagal membuat varian kata kunci ({str(e)[:150]}). Pakai varian cadangan.")
        varian = normalisasi_varian(_varian_cadangan(nama_topik, kata), kata)
        sumber = "cadangan"

    print(f"  ✅ Varian kata kunci ({sumber}): {varian}")
    simpan_varian(nama_topik, varian, sumber)
    return varian


# ============================================================
# 4. CAPTION CONTOH OTOMATIS DARI URL
# ============================================================
def lengkapi_caption_dari_url(daftar_contoh: list, token: str = "") -> list:
    """
    Isi caption yang masih KOSONG dengan mengambil data video langsung dari URL-nya
    (mode 'postURLs' actor Apify). Jadi user cukup menempel URL, tanpa copy-paste caption.

    - Caption yang sudah ditempel user TIDAK ditimpa.
    - Video yang gagal diambil (privat/dihapus) dilaporkan, captionnya tetap kosong
      dan nanti akan ditolak oleh validasi_contoh.
    - Biaya: pay-per-result (~$0.005 per video), dilaporkan setelah selesai.
    """
    from config import ambil_apify_token
    from apify_client import ambil_video_dari_url, id_dari_url

    perlu = [c for c in (daftar_contoh or []) if not (c.get("caption") or "").strip()]
    if not perlu:
        return daftar_contoh

    print(f"\n  🌐 {len(perlu)} contoh belum ada captionnya -> diambil otomatis dari URL TikTok.")
    token = token or ambil_apify_token()
    if not token:
        raise ValueError(
            "Butuh token Apify untuk mengambil caption otomatis. Isi APIFY_TOKEN di .env, "
            "atau tempel caption manual dengan format: URL | caption"
        )

    peta, status, pesan, info = ambil_video_dari_url([c["url"] for c in perlu], token)
    if status != "success":
        print(f"  ⚠️ Gagal mengambil caption otomatis ({pesan}). "
              f"Silakan tempel caption manual dengan format: URL | caption")
        return daftar_contoh

    hasil = []
    for baris in daftar_contoh:
        if (baris.get("caption") or "").strip():
            hasil.append(baris)
            continue

        url_target = baris["url"]
        vid = id_dari_url(url_target)
        item = peta.get(vid) or peta.get(url_target)

        # Fallback pencarian fuzzy dalam peta jika tidak langsung ketemu
        if not item:
            for k, it in peta.items():
                if vid and (vid in k or vid in (it.get("webVideoUrl") or "")):
                    item = it
                    break

        if item:
            caption = (item.get("text") or item.get("caption") or "").strip()
            akun = ((item.get("authorMeta") or {}).get("name") or "").strip()
            # Jika caption kosong di video aslinya, buatkan penjelas dari hashtag
            if not caption:
                tags = " ".join([f"#{h.get('name') if isinstance(h, dict) else h}" for h in (item.get("hashtags") or [])])
                caption = f"Video @{akun} {tags}".strip() or f"Video @{akun} isu Cirebon"

            web_url = (item.get("webVideoUrl") or "").split("?")[0].rstrip("/")
            url_final = web_url if web_url else baris["url"]
            baris = {**baris, "url": url_final, "caption": caption, "caption_dari": "otomatis", "akun": akun}
            print(f"    ✔ {vid or url_final} (@{akun or '?'}): caption {len(caption)} karakter diambil")
        else:
            print(f"    ✘ {vid or baris['url']}: gagal diambil (video privat/dihapus/wilayah terkunci?)")
        hasil.append(baris)

    if (info or {}).get("biaya_usd"):
        print(f"    💵 Biaya ambil caption: ${info['biaya_usd']:.4f}")

    return hasil
