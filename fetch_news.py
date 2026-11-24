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
FEEDS = [
    {"source": "GOOGLE_NEWS_ID", "lang": "id", "filter": False,
     "url": "https://news.google.com/rss/search?q=harga+emas&hl=id&gl=ID&ceid=ID:id"},
    {"source": "GOOGLE_NEWS_EN", "lang": "en", "filter": False,
     "url": "https://news.google.com/rss/search?q=gold+price&hl=en-US&gl=US&ceid=US:en"},
    # Tambahkan RSS portal lokal di bawah ini (ambil URL RSS resmi dari situsnya).
    # filter True = hanya simpan berita yang mengandung kata kunci emas.
    # {"source": "LIPUTAN6_BISNIS", "lang": "id", "filter": True, "url": "ISI_URL_RSS"},
    # {"source": "KONTAN_INVESTASI", "lang": "id", "filter": True, "url": "ISI_URL_RSS"},
]
KEYWORDS = ["emas", "antam", "logam mulia", "gold", "bullion", "xauusd"]
PER_FEED = 30        # maksimal berita diambil per sumber tiap run
MAX_ITEMS = 150      # maksimal berita disimpan
MAX_AGE_DAYS = 7     # berita lebih tua dibuang
SNIPPET_LEN = 220    # panjang cuplikan (karakter)
# =======================================================

OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news.json")
UA = "Mozilla/5.0 (compatible; BrankasEmasNewsBot/1.0)"
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
    root = ET.fromstring(fetch(feed["url"]))
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

        # Deskripsi Google News hanya mengulang judul: kosongkan agar tidak dobel
        if snippet.lower().startswith(title.lower()[:30]):
            snippet = ""

        if feed.get("filter", True):
            hay = (title + " " + snippet).lower()
            if not any(k in hay for k in KEYWORDS):
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
