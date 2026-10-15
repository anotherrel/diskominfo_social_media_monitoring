# -*- coding: utf-8 -*-
"""
sentiment_analyzer.py
=====================
Modul Analisis Sentimen Komentar Instagram menggunakan model AI IndoBERTweet
(Aardiiiiy/indobertweet-base-Indonesian-sentiment-analysis).

Berdasarkan kesimpulan & progres belajar NLP Sentiment Analysis (kesimpulan.md).
"""

import sys
import warnings
warnings.filterwarnings("ignore")

# Memastikan output terminal Windows mendukung UTF-8
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from transformers import pipeline

MODEL_NAME = "Aardiiiiy/indobertweet-base-Indonesian-sentiment-analysis"
_sentiment_pipeline = None


def get_sentiment_pipeline():
    """
    Fungsi singleton / lazy load untuk memuat model IndoBERTweet hanya saat dibutuhkan.
    """
    global _sentiment_pipeline
    if _sentiment_pipeline is None:
        print(f"\n[INFO] Memuat model AI IndoBERTweet ('{MODEL_NAME}')...")
        _sentiment_pipeline = pipeline(
            "sentiment-analysis",
            model=MODEL_NAME,
            tokenizer=MODEL_NAME,
            truncation=True,
            max_length=512,
        )
        print("[SUCCESS] Model AI IndoBERTweet Berhasil Dimuat!\n")
    return _sentiment_pipeline


def analisa_sentimen_teks(teks: str) -> tuple[str, str]:
    """
    Menganalisis 1 string komentar.
    Returns: (sentimen, skor_yakin) -> contoh: ('POSITIF', '99.82%')
    """
    if not teks or not isinstance(teks, str) or not teks.strip():
        return "NETRAL", "0.00%"

    try:
        pipe = get_sentiment_pipeline()
        hasil = pipe(teks, truncation=True, max_length=512)[0]

        mapping = {
            "Positive": "POSITIF",
            "Neutral": "NETRAL",
            "Negative": "NEGATIF",
            "positive": "POSITIF",
            "neutral": "NETRAL",
            "negative": "NEGATIF",
            "LABEL_0": "NEGATIF",
            "LABEL_1": "NETRAL",
            "LABEL_2": "POSITIF",
        }

        label_indo = mapping.get(hasil["label"], str(hasil["label"]).upper())
        skor_persen = f"{hasil['score'] * 100:.2f}%"

        return label_indo, skor_persen
    except Exception as e:
        print(f"[WARN] Error sentimen untuk teks: {e}")
        return "NETRAL", "0.00%"


def analisa_sentimen_batch(daftar_komentar: list[dict], batch_size: int = 32) -> list[dict]:
    """
    Menerima daftar dict komentar (yang memiliki key 'text').
    Menambahkan key 'sentimen' dan 'skor_yakin' ke masing-masing item komentar.
    """
    if not daftar_komentar:
        return daftar_komentar

    print(f"[AI] Menjalankan Analisis Sentimen IndoBERTweet ({len(daftar_komentar)} komentar)...")
    pipe = get_sentiment_pipeline()

    teks_list = [k.get("text") or "" for k in daftar_komentar]
    teks_clean = [t if isinstance(t, str) and t.strip() else "netral" for t in teks_list]

    try:
        hasil_batch = pipe(teks_clean, batch_size=batch_size, truncation=True, max_length=512)

        mapping = {
            "Positive": "POSITIF",
            "Neutral": "NETRAL",
            "Negative": "NEGATIF",
            "positive": "POSITIF",
            "neutral": "NETRAL",
            "negative": "NEGATIF",
            "LABEL_0": "NEGATIF",
            "LABEL_1": "NETRAL",
            "LABEL_2": "POSITIF",
        }

        for i, item in enumerate(daftar_komentar):
            raw_text = teks_list[i]
            if not raw_text or not isinstance(raw_text, str) or not raw_text.strip():
                item["sentimen"] = "NETRAL"
                item["skor_yakin"] = "0.00%"
            else:
                res = hasil_batch[i]
                label_indo = mapping.get(res["label"], str(res["label"]).upper())
                skor_persen = f"{res['score'] * 100:.2f}%"
                item["sentimen"] = label_indo
                item["skor_yakin"] = skor_persen

    except Exception as e:
        print(f"[WARN] Gagal batch inference ({e}), beralih ke analisis per-item...")
        for item in daftar_komentar:
            s, sk = analisa_sentimen_teks(item.get("text", ""))
            item["sentimen"] = s
            item["skor_yakin"] = sk

    return daftar_komentar


def hitung_statistik_sentimen(daftar_komentar: list[dict], kunci: str = "sentimen") -> dict:
    """
    Menghitung statistik ringkasan sentimen (% Positif, % Negatif, % Netral).

    Parameter `kunci` dipakai supaya fungsi yang sama bisa menghitung dua sumber:
    - kunci="sentimen"    -> hasil IndoBERTweet
    - kunci="sentimen_ai" -> hasil penilaian LLM
    """
    total = len(daftar_komentar)
    if total == 0:
        return {
            "total": 0,
            "POSITIF": 0, "POSITIF_pct": "0.00%",
            "NEGATIF": 0, "NEGATIF_pct": "0.00%",
            "NETRAL": 0,  "NETRAL_pct": "0.00%",
        }

    counts = {"POSITIF": 0, "NEGATIF": 0, "NETRAL": 0}
    for item in daftar_komentar:
        st = item.get(kunci, "NETRAL")
        counts[st] = counts.get(st, 0) + 1

    pos = counts.get("POSITIF", 0)
    neg = counts.get("NEGATIF", 0)
    net = counts.get("NETRAL", 0)

    return {
        "total": total,
        "POSITIF": pos, "POSITIF_pct": f"{(pos / total) * 100:.2f}%",
        "NEGATIF": neg, "NEGATIF_pct": f"{(neg / total) * 100:.2f}%",
        "NETRAL": net,  "NETRAL_pct": f"{(net / total) * 100:.2f}%",
    }

