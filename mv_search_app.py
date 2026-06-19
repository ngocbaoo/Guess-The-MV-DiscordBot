#!/usr/bin/env python3
"""mv_search_app.py — Web UI for searching YouTube MVs and adding to songs.json.

Usage:
    python mv_search_app.py
    → Opens at http://localhost:5555
"""

import json
import re
import sys
import os
import unicodedata
import threading
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    os.environ["PYTHONIOENCODING"] = "utf-8"

try:
    import yt_dlp
except ImportError:
    print("❌  yt-dlp chưa cài. Chạy: pip install yt-dlp", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parent
SEED_PATH = ROOT / "seed" / "songs.json"

app = Flask(__name__, static_folder=None)

# ── MV search keyword variants ──────────────────────────────────────────────
MV_KEYWORDS = [
    "MV",
    "Official MV",
    "Official Music Video",
    "M/V",
    "Official M/V",
    "Music Video",
    "MV Official",
    "MV Chính Thức",
]

RESULTS_PER_QUERY = 10


# ── Helpers ──────────────────────────────────────────────────────────────────
def slugify(text: str) -> str:
    text = text.lower()
    text = text.replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text


def strip_mv_tags(title: str) -> str:
    patterns = [
        r"\s*[\(\[【]?\s*(?:Official\s+)?(?:Music\s+Video|MV|M\s*/\s*V|Lyric(?:\s+Video)?)\s*[\)\]】]?\s*",
        r"\s*[\(\[【]\s*(?:MV\s+)?(?:Chính\s+Thức|Official)\s*[\)\]】]\s*",
        r"\s*\|\s*(?:Official\s+)?(?:Music\s+Video|MV|M\s*/\s*V)\s*",
        r"\s*-\s*(?:Official\s+)?(?:Music\s+Video|MV|M\s*/\s*V)\s*$",
    ]
    cleaned = title
    for pat in patterns:
        cleaned = re.sub(pat, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(?:MV|M\s*/\s*V)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\s*[|\-]\s*$", "", cleaned).strip()
    return cleaned


def remove_artist_from_title(title: str, artist: str) -> str:
    escaped = re.escape(artist)
    cleaned = re.sub(rf"^{escaped}\s*[-|x×]\s*", "", title, flags=re.IGNORECASE)
    cleaned = re.sub(rf"\s*[-|x×]\s*{escaped}\s*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def load_songs() -> list:
    with open(SEED_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_songs(songs: list) -> None:
    with open(SEED_PATH, "w", encoding="utf-8") as f:
        json.dump(songs, f, ensure_ascii=False, indent=2)


def get_existing_urls(songs: list) -> set:
    urls = set()
    for s in songs:
        if s.get("url"):
            m = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", s["url"])
            if m:
                urls.add(m.group(1))
    return urls


def get_next_empty_slot(songs: list):
    for i, s in enumerate(songs):
        if not s.get("title"):
            return i
    return None


def _looks_like_mv(title: str, artist: str) -> bool:
    lower = title.lower()
    mv_markers = [
        "mv", "m/v", "music video", "official video",
        "official mv", "chính thức", "lyric video",
        "official lyric", "visualizer",
    ]
    for marker in mv_markers:
        if marker in lower:
            return True
    if artist.lower() in lower:
        return True
    return False


# ── Cookie helper ────────────────────────────────────────────────────────────
COOKIES_PATH = ROOT / "cookies.txt"


def _get_ydl_opts() -> dict:
    """Base yt-dlp options, with cookie file if available."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": "in_playlist",  # metadata only, no format resolution
        "ignoreerrors": True,
    }
    if COOKIES_PATH.exists():
        opts["cookiefile"] = str(COOKIES_PATH)
    return opts


# ── YouTube Search ───────────────────────────────────────────────────────────
def search_youtube(artist: str) -> list:
    seen_ids = set()
    results = []
    ydl_opts = _get_ydl_opts()

    if COOKIES_PATH.exists():
        print(f"  🍪  Dùng cookies từ {COOKIES_PATH.name}", file=sys.stderr)
    else:
        print("  ⚠  Không có cookies.txt → video age-restricted sẽ bị skip", file=sys.stderr)

    for keyword in MV_KEYWORDS:
        query = f"{artist} {keyword}"
        search_url = f"ytsearch{RESULTS_PER_QUERY}:{query}"

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(search_url, download=False)

            for entry in info.get("entries") or []:
                if not entry:
                    continue
                # In flat mode, id may be in 'id' or parseable from 'url'
                vid = entry.get("id")
                if not vid:
                    entry_url = entry.get("url", "")
                    m = re.search(r"(?:v=|/vi/)([a-zA-Z0-9_-]{11})", entry_url)
                    vid = m.group(1) if m else None
                if not vid or vid in seen_ids:
                    continue
                seen_ids.add(vid)

                title = entry.get("title", "")
                if not title or not _looks_like_mv(title, artist):
                    continue

                # Auto-clean the title
                clean = strip_mv_tags(title)
                clean = remove_artist_from_title(clean, artist)

                results.append({
                    "video_id": vid,
                    "original_title": title,
                    "clean_title": clean,
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "channel": entry.get("channel") or entry.get("uploader") or entry.get("uploader_id") or "",
                    "view_count": entry.get("view_count"),
                    "duration": entry.get("duration"),
                    "thumbnail": entry.get("thumbnail") or entry.get("thumbnails", [{}])[0].get("url", "") or f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                })

        except Exception as e:
            print(f"  ⚠  Error searching '{query}': {e}", file=sys.stderr)

    results.sort(key=lambda r: r.get("view_count") or 0, reverse=True)
    return results


# ── Routes ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(ROOT / "web", "index.html")


@app.route("/web/<path:filename>")
def serve_static(filename):
    return send_from_directory(ROOT / "web", filename)


@app.route("/api/songs")
def api_songs():
    """Return current songs.json content."""
    songs = load_songs()
    filled = [s for s in songs if s.get("title")]
    empty_count = sum(1 for s in songs if not s.get("title"))
    return jsonify({"songs": filled, "empty_slots": empty_count, "total": len(songs)})


@app.route("/api/search", methods=["POST"])
def api_search():
    """Search YouTube for MVs by artist."""
    data = request.json
    artist = data.get("artist", "").strip()
    if not artist:
        return jsonify({"error": "Tên nghệ sĩ không được để trống"}), 400

    songs = load_songs()
    existing = get_existing_urls(songs)

    results = search_youtube(artist)

    # Mark existing
    for r in results:
        m = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", r["url"])
        r["exists"] = bool(m and m.group(1) in existing)
        # Suggest artist name
        r["artist"] = artist

    return jsonify({"results": results, "artist": artist})


@app.route("/api/add", methods=["POST"])
def api_add():
    """Add selected songs to songs.json."""
    data = request.json
    items = data.get("items", [])

    if not items:
        return jsonify({"error": "Không có bài nào để thêm"}), 400

    songs = load_songs()
    existing = get_existing_urls(songs)
    added = []

    for item in items:
        # Check duplicate
        vid_match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", item["url"])
        if vid_match and vid_match.group(1) in existing:
            continue

        title = item.get("title", "").strip()
        artist = item.get("artist", "").strip()
        url = item.get("url", "").strip()

        if not title or not url:
            continue

        slug = slugify(title)
        alias = slugify(title).replace("-", " ")

        slot_idx = get_next_empty_slot(songs)
        if slot_idx is not None:
            song_id = songs[slot_idx]["id"]
            songs[slot_idx] = {
                "id": song_id,
                "title": title,
                "artist": artist,
                "url": url,
                "slug": slug,
                "aliases": [alias],
                "year_override": None,
                "difficulty_override": None,
            }
        else:
            max_id = max(s["id"] for s in songs) if songs else 0
            songs.append({
                "id": max_id + 1,
                "title": title,
                "artist": artist,
                "url": url,
                "slug": slug,
                "aliases": [alias],
                "year_override": None,
                "difficulty_override": None,
            })

        # Add to existing set to prevent within-batch duplicates
        if vid_match:
            existing.add(vid_match.group(1))

        added.append({"title": title, "artist": artist})

    save_songs(songs)
    return jsonify({"added": added, "count": len(added)})


# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import webbrowser

    port = 5555
    url = f"http://localhost:{port}"
    print(f"\n🎵  MV Search Tool đang chạy tại: {url}\n")

    # Auto-open browser after a short delay
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    app.run(host="0.0.0.0", port=port, debug=False)
