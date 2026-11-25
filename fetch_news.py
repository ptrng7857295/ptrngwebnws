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
def gn(query, lang="id"):
    """URL RSS Google News untuk satu pencarian (spasi ditulis +)."""
    if lang == "id":
        tail = "&hl=id&gl=ID&ceid=ID:id"
    else:
        tail = "&hl=en-US&gl=US&ceid=US:en"
    return "https://news.google.com/rss/search?q=" + query + tail


# Tiap sumber punya daftar "urls": dicoba berurutan, yang pertama berisi berita dipakai.
# Taruh RSS portal langsung di atas (ada cuplikan + gambar), Google News di paling bawah.
FEEDS = [
    {"source": "KONTAN_INVESTASI", "name": "Kontan", "lang": "id", "filter": True,
     "urls": ["https://keuangan.kontan.co.id/rss",
              gn("harga+emas+site:kontan.co.id+when:3d")]},
    {"source": "LIPUTAN6_BISNIS", "name": "Liputan6 Bisnis", "lang": "id", "filter": True,
     "urls": ["https://feed.liputan6.com/rss/bisnis",
              gn("harga+emas+site:liputan6.com+when:3d")]},
    {"source": "DETIK_FINANCE", "name": "detikFinance", "lang": "id", "filter": True,
     "urls": ["https://finance.detik.com/rss",
              gn("harga+emas+site:detik.com+when:3d")]},
    {"source": "MINING_COM", "name": "Mining.com", "lang": "en", "filter": True,
     "urls": ["https://www.mining.com/tag/gold/feed/",
              gn("gold+site:mining.com+when:3d", "en")]},
    {"source": "GOOGLE_NEWS_ID", "lang": "id", "filter": True,
     "urls": [gn("harga+emas+OR+emas+antam+OR+investasi+emas+when:3d")]},
    {"source": "GOOGLE_NEWS_EN", "lang": "en", "filter": True,
     "urls": [gn("gold+price+OR+gold+market+when:3d", "en")]},
]

# Filter berita emas: cocok per KATA (bukan potongan kata), jadi "kemasan" / "pemasaran" tidak lolos.
GOLD_RE = re.compile(r"\b(emas|antam|logam mulia|galeri ?24|gold|bullion|xau(usd)?)\b", re.I)
STRONG_RE = re.compile(r"harga emas|emas dunia|emas antam|gold price|price of gold", re.I)
SKIP_RE = re.compile(r"medali|generasi emas|indonesia emas|emas 2045|gold medal|golden", re.I)


def is_gold(title, snippet):
    if SKIP_RE.search(title):
        return False
    if GOLD_RE.search(title):
        return True
    return STRONG_RE.search(snippet) is not None


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

        # Google News menaruh nama media di <source>, dan judul berakhiran " - Media"
        publisher = ""
        src = item.find("source")
        if src is not None and src.text:
            publisher = src.text.strip()
            suffix = " - " + publisher
            if title.endswith(suffix):
                title = title[: -len(suffix)].strip()

        if not publisher:
            publisher = feed.get("name", "")

        # Deskripsi Google News hanya mengulang judul: kosongkan agar tidak dobel
        if snippet.lower().startswith(title.lower()[:30]):
            snippet = ""

        if feed.get("filter", True):
            if not is_gold(title, snippet):
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

    if merged == old:
        print("Tidak ada perubahan")
        return

    data = {"updated": int(time.time()), "count": len(merged), "items": merged}
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("Tersimpan: " + str(len(merged)) + " berita")


if __name__ == "__main__":
    main()
