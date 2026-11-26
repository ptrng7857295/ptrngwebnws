#!/usr/bin/env python3
"""Ambil berita emas dari RSS lalu simpan ke news.json (dijalankan GitHub Actions)."""
import html
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

# ===================== KONFIGURASI =====================

# ==================== KATA KUNCI (ubah di sini) ====================
# Berita hanya lolos kalau JUDULNYA memuat frasa di bawah. Kata "emas" saja TIDAK cukup.

# 1) Berita lokal (bahasa Indonesia): frasa pencarian
PHRASES_ID = [
    "harga emas", "investasi emas", "tabungan emas", "emas dunia", "emas anjlok",
    "emas perhiasan", "emas digital", "harga emas pegadaian", "beli emas",
    "jual emas", "cek harga emas", "prediksi harga emas", "buyback emas",
    "transaksi emas",
]

# 2) Berita internasional (bahasa Inggris)
PHRASES_EN = ["gold price"]
# Judul internasional yang memuat "gold" + salah satu kata pasar ini juga lolos
# (mis. "Gold falls ahead of PCE data"). Kosongkan daftar ini ([]) agar hanya frasa di atas.
GOLD_EN_CONTEXT = [
    "price", "prices", "ounce", "bullion", "futures", "spot", "fed", "inflation",
    "dollar", "etf", "rally", "record", "forecast", "target", "outlook", "rate cut",
    "falls", "slips", "drops", "slides", "tumbles", "plunges", "rises", "climbs",
    "jumps", "surges", "gains", "retreats", "extends",
]

# 3) Nama brand emas
# Nama khas: judul cukup menyebut nama ini (boleh pola regex, mis. "galeri ?24").
BRANDS = [
    "bsi gold", "semar nusantara", "king halim", "galeri ?24", "tring!? pegadaian",
    "lotus archi", "hartadinata", "waris sampoerna",
]
# Nama yang bisa berarti hal lain (UBS = bank, BYOND = aplikasi bank, Antam = juga tambang nikel):
# lolos hanya jika ada konteks emas (kata di CONTEXT) atau judulnya "harga <nama>".
BRANDS_AMBIGUOUS = ["antam", "ubs", "byond", "tring"]
CONTEXT = ["emas", "gold", "logam mulia", "batangan", "buyback", "gram"]

# Dibuang walau cocok di atas
SKIP_WORDS = ["medali", "generasi emas", "indonesia emas", "emas 2045",
              "gold medal", "golden", "gold coast", "gold cup"]


def _phrase(p):
    return r"\s+".join(re.escape(w) for w in p.split())


def _any(words, raw=False):
    parts = [w if raw else _phrase(w) for w in words]
    return re.compile(r"\b(" + "|".join(parts) + r")\b", re.I)


PHRASE_ID_RE = _any(PHRASES_ID)
PHRASE_EN_RE = _any(PHRASES_EN)
EN_CONTEXT_RE = _any(GOLD_EN_CONTEXT) if GOLD_EN_CONTEXT else None
GOLD_WORD_RE = re.compile(r"\bgold\b", re.I)
BRAND_RE = _any(BRANDS, raw=True)
AMBIG_RE = _any(BRANDS_AMBIGUOUS)
PRICE_BRAND_RE = re.compile(r"\bharga\s+(" + "|".join(re.escape(b) for b in BRANDS_AMBIGUOUS) + r")\b", re.I)
CONTEXT_RE = _any(CONTEXT)
SKIP_RE = re.compile("|".join(re.escape(w) for w in SKIP_WORDS), re.I)


def is_gold(title, snippet, lang="id"):
    """True jika berita memang soal emas (investasi, harga, atau brand emas)."""
    if SKIP_RE.search(title):
        return False

    if lang == "en":
        if PHRASE_EN_RE.search(title):
            return True
        if EN_CONTEXT_RE is not None:
            if GOLD_WORD_RE.search(title):
                return EN_CONTEXT_RE.search(title) is not None
        return False

    if PHRASE_ID_RE.search(title):
        return True
    if BRAND_RE.search(title):
        return True
    if PRICE_BRAND_RE.search(title):
        return True
    if AMBIG_RE.search(title):
        return CONTEXT_RE.search(title + " " + snippet) is not None
    return False


# ==================== DAFTAR RSS (tambah/hapus di sini) ====================
# Tiap blok = satu sumber:
#   source = kode unik tanpa spasi (muncul di log)
#   name   = nama media yang tampil di kartu berita
#   lang   = "id" (tab Indonesia) atau "en" (tab Internasional)
#   filter = True -> hanya simpan berita emas (aturan kata kunci di atas)
#   urls   = daftar URL RSS, dicoba berurutan; URL pertama yang berisi berita dipakai
FEEDS = [
    {"source": "KONTAN_INVESTASI", "name": "Kontan", "lang": "id", "filter": True,
     "urls": ["https://keuangan.kontan.co.id/rss"]},
    {"source": "LIPUTAN6_BISNIS", "name": "Liputan6 Bisnis", "lang": "id", "filter": True,
     "urls": ["https://feed.liputan6.com/rss/bisnis"]},
    {"source": "DETIK_FINANCE", "name": "detikFinance", "lang": "id", "filter": True,
     "urls": ["https://finance.detik.com/rss"]},
    {"source": "DETIK_EKBIS", "name": "detikFinance", "lang": "id", "filter": True,
     "urls": ["https://finance.detik.com/berita-ekonomi-bisnis/rss"]},
    {"source": "CNBC_MARKET", "name": "CNBC Indonesia", "lang": "id", "filter": True,
     "urls": ["https://www.cnbcindonesia.com/market/rss"]},
    {"source": "CNBC_NEWS", "name": "CNBC Indonesia", "lang": "id", "filter": True,
     "urls": ["https://www.cnbcindonesia.com/rss"]},
    {"source": "CNBC_RESEARCH", "name": "CNBC Indonesia", "lang": "id", "filter": True,
     "urls": ["https://www.cnbcindonesia.com/research/rss"]},
    {"source": "SINDONEWS_EKBIS", "name": "Sindonews", "lang": "id", "filter": True,
     "urls": ["https://ekbis.sindonews.com/rss"]},
    {"source": "MEDCOM", "name": "Medcom.id", "lang": "id", "filter": True,
     "urls": ["https://www.medcom.id/feed/flipboard"]},
    {"source": "BLOOMBERG_TECHNOZ", "name": "Bloomberg Technoz", "lang": "id", "filter": True,
     "urls": ["https://www.bloombergtechnoz.com/rss"]},
    {"source": "ANTARA_KEPRI", "name": "Antara Kepri", "lang": "id", "filter": True,
     "urls": ["https://kepri.antaranews.com/rss/ekonomi-ftz.xml"]},
    {"source": "CNN_EKONOMI", "name": "CNN Indonesia", "lang": "id", "filter": True,
     "urls": ["https://www.cnnindonesia.com/ekonomi/rss"]},
    {"source": "MINING_COM", "name": "Mining.com", "lang": "en", "filter": True,
     "urls": ["https://www.mining.com/tag/gold/feed/"]},
]
# ===========================================================================

PER_FEED = 30        # maksimal berita diambil per sumber tiap run
MAX_ITEMS = 150      # maksimal berita disimpan
MAX_AGE_DAYS = 7     # berita lebih tua dibuang
SNIPPET_LEN = 220    # panjang cuplikan (karakter)
# =======================================================

OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
MEDIA_NS = "{http://search.yahoo.com/mrss/}"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def clean_text(raw):
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def shorten(text, size):
    if size >= len(text):
        return text
    cut = text[:size].rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:-") + "..."


def find_image(item, desc_raw):
    for tag in ("content", "thumbnail"):
        el = item.find(MEDIA_NS + tag)
        if el is not None and el.get("url"):
            return el.get("url")
    enc = item.find("enclosure")
    if enc is not None and "image" in (enc.get("type") or ""):
        return enc.get("url") or ""
    m = re.search(r"<img[^>]+src=[\"']([^\"']+)[\"']", html.unescape(desc_raw or ""))
    return m.group(1) if m else ""


def parse_feed(feed):
    for url in feed["urls"]:
        try:
            items = parse_url(feed, url)
        except Exception as e:
            print("  gagal " + url + " : " + str(e), file=sys.stderr)
            continue
        if items:
            print("OK " + feed["source"] + ": " + str(len(items)) + " berita dari " + url)
            return items
        print("  kosong " + url)
    raise RuntimeError("semua URL gagal atau kosong")


def parse_url(feed, feed_url):
    root = ET.fromstring(fetch(feed_url))
    out = []
    for item in root.iter("item"):
        title = clean_text(item.findtext("title"))
        url = (item.findtext("link") or "").strip()
        if not title or not url:
            continue

        desc_raw = item.findtext("description") or ""
        snippet = clean_text(desc_raw)
        snippet = re.sub(r"\s*\|\s*", " ", snippet)   # Medcom: poin dipisah tanda |

        publisher = feed.get("name", "")

        # Jika deskripsi hanya mengulang judul, kosongkan agar tidak dobel
        if snippet.lower().startswith(title.lower()[:30]):
            snippet = ""

        if feed.get("filter", True):
            if not is_gold(title, snippet, feed["lang"]):
                continue

        try:
            ts = int(parsedate_to_datetime(item.findtext("pubDate")).timestamp())
        except Exception:
            ts = int(time.time())

        out.append({
            "title": title,
            "snippet": shorten(snippet, SNIPPET_LEN),
            "url": url,
            "source": feed["source"],
            "publisher": publisher,
            "lang": feed["lang"],
            "time": ts,
            "image": find_image(item, desc_raw),
        })
        if len(out) >= PER_FEED:
            break
    return out


def keep_old(it):
    if "news.google.com" in it.get("url", ""):
        return False
    return is_gold(it.get("title", ""), it.get("snippet", ""), it.get("lang", "id"))


def title_key(title):
    return re.sub(r"[^a-z0-9]", "", title.lower())[:60]


def main():
    old = []
    if os.path.exists(OUT_FILE):
        try:
            with open(OUT_FILE, encoding="utf-8") as f:
                old = json.load(f).get("items", [])
        except Exception:
            old = []

    # Bersihkan berita lama: buang yang berasal dari Google News dan saring ulang
    # dengan aturan kata kunci terbaru, agar perubahan langsung berlaku
    old_raw = old
    old = [it for it in old_raw if keep_old(it)]
    if len(old) != len(old_raw):
        print("Dibuang dari berita lama: " + str(len(old_raw) - len(old)))

    fresh, ok = [], 0
    for feed in FEEDS:
        try:
            fresh += parse_feed(feed)
            ok += 1
        except Exception as e:
            print("GAGAL " + feed["source"] + ": " + str(e), file=sys.stderr)
    if ok == 0:
        sys.exit(1)

    cutoff = time.time() - MAX_AGE_DAYS * 86400
    seen_url, seen_title, merged = set(), set(), []
    for it in fresh + old:
        if it["time"] > cutoff:
            tk = title_key(it["title"])
            if it["url"] not in seen_url:
                if tk not in seen_title:
                    seen_url.add(it["url"])
                    seen_title.add(tk)
                    merged.append(it)

    merged.sort(key=lambda x: x["time"], reverse=True)
    merged = merged[:MAX_ITEMS]

    if merged == old_raw:
        print("Tidak ada perubahan")
        return

    data = {"updated": int(time.time()), "count": len(merged), "items": merged}
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("Tersimpan: " + str(len(merged)) + " berita")


if __name__ == "__main__":
    main()
