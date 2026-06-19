#!/usr/bin/env python3
"""crawl.py - data crawler for the "guess MV by frame" Vpop Discord bot.

Core philosophy (invariant): STORE RAW TRUTH, INTERPRET AT PLAY TIME.
The crawler never computes difficulty tiers, never filters by year, never
matches answers. It only collects raw facts (view_count, duration, year,
frames) and persists them. Any interpretation (easy/hard tier, year filter)
belongs to the bot at runtime; the `verify` command here only *previews*
such derivations for acceptance testing.

Commands:
    extract   read seed/songs.json -> yt-dlp metadata -> manifest.json,
              then range-seek candidate frames with ffmpeg (no video saved).
    ingest    seed U manifest -> SQLite (songs/aliases/frames). Idempotent.
    verify    read-only dump + tier preview + year-filter demo.
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

# --- Default paths (overridable so tests can inject fixtures) ---
ROOT = Path(__file__).resolve().parent
SEED_PATH = ROOT / "seed" / "songs.json"
BUILD_DIR = ROOT / "build"
MANIFEST_PATH = BUILD_DIR / "manifest.json"
CANDIDATES_DIR = BUILD_DIR / "candidates"
DB_DIR = ROOT / "db"
DB_PATH = DB_DIR / "bot.db"
FRAMES_DIR = DB_DIR / "frames"

# --- extract config ---
FRAME_COUNT = 24          # number of candidate timestamps per song
HEAD_TAIL_FRAC = 0.9       # skip ...% at head and tail
MIN_EDGE_SECONDS = 15     # ...but at least 15s each side
YTDLP_DELAY = 2.0         # polite delay between yt-dlp calls (anti-throttle)
# Format fallback chain. Prefer high-res video-only DASH streams (up to 1080p):
# YouTube's progressive mp4 is capped at 360p, so picking it makes frames blurry.
# Fall back to progressive only if no DASH stream is available.
MAX_HEIGHT = 1080
FORMAT_CHAIN = (
    f"bestvideo[ext=mp4][height<={MAX_HEIGHT}]/"
    f"bestvideo[height<={MAX_HEIGHT}]/"
    f"best[ext=mp4][height<={MAX_HEIGHT}]/best"
)
IMG_EXT = {".jpg", ".jpeg", ".png"}


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# normalize() -- the most error-prone piece. Every alias depends on it.
# Order is mandatory; see tests/test_normalize.py.
# ---------------------------------------------------------------------------
def normalize(s: str) -> str:
    """Normalize an alias string for matching.

    "Chạy Ngay Đi" and "chay ngay di" must both map to "chay ngay di".
    """
    s = s.lower()                                       # 1. lowercase (Đ -> đ)
    s = s.replace("đ", "d")                             # 2. đ -> d
    s = unicodedata.normalize("NFD", s)                 # 3. split diacritics
    s = "".join(c for c in s
                if unicodedata.category(c) != "Mn")     # 4. drop combining marks
    s = re.sub(r"[^a-z0-9 ]", " ", s)                   # 5. keep only [a-z0-9 ]
    s = re.sub(r"\s+", " ", s).strip()                  # 6. collapse whitespace
    return s


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def folder_name(song: dict) -> str:
    """Stable per-song folder: {id:03d}-slug."""
    return f"{int(song['id']):03d}-{song['slug']}"


def parse_openness(stem: str) -> str:
    """Read openness from a frame filename suffix: _hard / _easy / (none)."""
    low = stem.lower()
    if low.endswith("_hard"):
        return "hard"
    if low.endswith("_easy"):
        return "easy"
    return "normal"


def load_seed(seed_path: Path) -> list:
    with open(seed_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Seed may carry _comment / extra keys; the reader simply ignores them.
    return data


def load_manifest(manifest_path: Path) -> dict:
    if Path(manifest_path).is_file():
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_manifest(manifest_path: Path, manifest: dict) -> None:
    Path(manifest_path).parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------
def pick_stream_url(info: dict):
    """Reuse the metadata call's resolved format; do NOT call yt-dlp twice."""
    if info.get("url"):
        return info["url"]
    # Merged selection (separate video/audio): grab the video stream URL.
    for f in info.get("requested_formats") or []:
        if f.get("vcodec") and f.get("vcodec") != "none":
            return f.get("url")
    reqs = info.get("requested_formats")
    if reqs:
        return reqs[0].get("url")
    return None


def grab_frames(stream_url: str, duration: float, folder: Path) -> int:
    """Range-seek candidate frames with ffmpeg. Never downloads the video.

    `-ss` is placed BEFORE `-i` for fast input seeking.
    """
    folder.mkdir(parents=True, exist_ok=True)
    edge = max(MIN_EDGE_SECONDS, duration * HEAD_TAIL_FRAC)
    start, end = edge, duration - edge
    if end <= start:  # very short clip: fall back to inner 80%
        start, end = duration * 0.1, duration * 0.9
    step = (end - start) / (FRAME_COUNT - 1) if FRAME_COUNT > 1 else 0
    grabbed = 0
    for i in range(FRAME_COUNT):
        t = start + i * step
        out = folder / f"{int(t):05d}.jpg"
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{t:.3f}",      # seek BEFORE input = fast range-seek
            "-i", stream_url,
            "-frames:v", "1",
            "-q:v", "1",            # best mjpeg quality (lower = sharper)
            "-loglevel", "error",
            str(out),
        ]
        try:
            subprocess.run(cmd, check=True)
            grabbed += 1
        except subprocess.CalledProcessError as e:
            log(f"  [ffmpeg] frame at {t:.1f}s failed: {e}")
    return grabbed


def expand_selectors(tokens) -> set:
    """Expand --only tokens into a set of id-strings and slugs.

    Accepts ranges ("1-5" -> 1,2,3,4,5), single ids ("6"), and slugs ("la-lung").
    """
    sel = set()
    for t in tokens:
        t = str(t).strip()
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", t)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b:
                a, b = b, a
            sel.update(str(i) for i in range(a, b + 1))
        else:
            sel.add(t)
    return sel


def _already_extracted(sid: int, song: dict, manifest: dict) -> bool:
    """A song is 'done' if it has a manifest entry AND >=1 candidate frame."""
    if str(sid) not in manifest:
        return False
    folder = CANDIDATES_DIR / folder_name(song)
    if not folder.is_dir():
        return False
    return any(p.suffix.lower() in IMG_EXT for p in folder.iterdir())


def cmd_extract(args) -> int:
    try:
        import yt_dlp
    except ImportError:
        log("yt-dlp chưa cài. Chạy: pip install -r requirements.txt")
        return 2

    songs = load_seed(SEED_PATH)
    manifest = load_manifest(MANIFEST_PATH)  # keep prior entries for failed songs
    only = expand_selectors(args.only or [])  # ids/ranges/slugs; empty = all
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "format": FORMAT_CHAIN,
    }

    for song in songs:
        sid = song["id"]
        # --only filters by id (as string) or slug
        if only and str(sid) not in only and song["slug"] not in only:
            continue
        # Incremental by default: skip songs already extracted unless --force.
        if not args.force and _already_extracted(sid, song, manifest):
            log(f"[extract] song {sid}: {song.get('title')} -> đã có, bỏ qua "
                f"(dùng --force để làm lại)")
            continue
        try:
            log(f"[extract] song {sid}: {song.get('title')} ...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(song["url"], download=False)

            upload_date = info.get("upload_date")  # may be None (hidden date)
            year = int(upload_date[:4]) if upload_date else None
            view_count = info.get("view_count")    # may be None (hidden count)
            duration = info.get("duration")

            manifest[str(sid)] = {
                "id": sid,
                "view_count": view_count,
                "duration": duration,
                "upload_date": upload_date,
                "year": year,
                "extracted_at": datetime.now(timezone.utc).isoformat(),
            }
            save_manifest(MANIFEST_PATH, manifest)  # persist incrementally

            stream_url = pick_stream_url(info)
            if not duration or not stream_url:
                log(f"  thiếu duration/stream_url -> bỏ qua frame (metadata vẫn lưu)")
            else:
                folder = CANDIDATES_DIR / folder_name(song)
                n = grab_frames(stream_url, duration, folder)
                log(f"  -> {n} frame ứng viên vào {folder}")

            time.sleep(YTDLP_DELAY)  # be polite
        except Exception as e:  # one bad song must not sink the whole run
            log(f"[extract] song {sid} FAILED, bỏ qua: {e}")
            continue

    log(f"[extract] xong. manifest: {MANIFEST_PATH}")
    return 0


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------
SCHEMA = """
DROP TABLE IF EXISTS frames;
DROP TABLE IF EXISTS aliases;
DROP TABLE IF EXISTS songs;

CREATE TABLE songs (
  id                  INTEGER PRIMARY KEY,
  title               TEXT NOT NULL,
  artist              TEXT,
  url                 TEXT NOT NULL,
  view_count          INTEGER,        -- raw from manifest (may be NULL)
  duration            INTEGER,        -- seconds, raw from manifest
  year                INTEGER,        -- resolved: year_override else year_raw
  year_raw            INTEGER,        -- manifest year (raw truth kept)
  year_override       INTEGER,        -- from seed, nullable
  difficulty_override TEXT            -- from seed, nullable: easy|medium|hard
);

CREATE TABLE aliases (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  song_id   INTEGER NOT NULL REFERENCES songs(id),
  alias_norm TEXT NOT NULL,           -- normalized
  alias_raw  TEXT,                    -- original, for debugging
  UNIQUE(song_id, alias_norm)
);

CREATE TABLE frames (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  song_id   INTEGER NOT NULL REFERENCES songs(id),
  file_path TEXT NOT NULL,            -- relative to db/
  openness  TEXT,                     -- easy|hard|normal from filename suffix
  UNIQUE(song_id, file_path)
);
"""


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)  # DROP + CREATE -> idempotent


def ingest(seed_path: Path, manifest_path: Path, db_path: Path,
           frames_dir: Path) -> None:
    """Merge seed U manifest by id into a fresh SQLite db.

    Paths are parameters so tests can inject fixtures. `frames_dir` is expected
    to live under `db_path.parent` (the db/ dir) so frame paths come out
    relative to db/.
    """
    seed_path, manifest_path = Path(seed_path), Path(manifest_path)
    db_path, frames_dir = Path(db_path), Path(frames_dir)
    db_base = db_path.parent  # everything in frames.file_path is relative to this

    songs = load_seed(seed_path)
    manifest = load_manifest(manifest_path)

    db_base.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        create_schema(conn)
        for song in songs:
            sid = song["id"]
            m = manifest.get(str(sid), {})
            year_raw = m.get("year")
            year_override = song.get("year_override")
            # seed wins over manifest
            year = year_override if year_override is not None else year_raw

            conn.execute(
                """INSERT INTO songs
                   (id, title, artist, url, view_count, duration,
                    year, year_raw, year_override, difficulty_override)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (sid, song["title"], song.get("artist"), song["url"],
                 m.get("view_count"), m.get("duration"),
                 year, year_raw, year_override,
                 song.get("difficulty_override")),
            )

            # aliases: title is always an alias, plus seed extras; dedupe.
            alias_raws = [song["title"]] + list(song.get("aliases") or [])
            for raw in alias_raws:
                norm = normalize(raw)
                if not norm:
                    continue
                conn.execute(
                    """INSERT OR IGNORE INTO aliases (song_id, alias_norm, alias_raw)
                       VALUES (?,?,?)""",
                    (sid, norm, raw),
                )

            # frames: scan curated dir; missing dir = 0 frames + warning, no crash.
            folder = frames_dir / folder_name(song)
            if not folder.is_dir():
                log(f"[ingest] WARNING song {sid} ({song['slug']}): "
                    f"thiếu thư mục frames -> 0 frame")
            else:
                imgs = sorted(p for p in folder.iterdir()
                              if p.suffix.lower() in IMG_EXT)
                if not imgs:
                    log(f"[ingest] WARNING song {sid} ({song['slug']}): "
                        f"thư mục frames rỗng -> 0 frame")
                for p in imgs:
                    rel = os.path.relpath(p, db_base).replace(os.sep, "/")
                    conn.execute(
                        """INSERT OR IGNORE INTO frames (song_id, file_path, openness)
                           VALUES (?,?,?)""",
                        (sid, rel, parse_openness(p.stem)),
                    )
        conn.commit()
    finally:
        conn.close()


def cmd_ingest(args) -> int:
    ingest(SEED_PATH, MANIFEST_PATH, DB_PATH, FRAMES_DIR)
    log(f"[ingest] xong -> {DB_PATH}")
    return 0


# ---------------------------------------------------------------------------
# verify (read-only; acceptance preview, NOT real bot logic)
# ---------------------------------------------------------------------------
def _tercile_labels(view_counts: list) -> dict:
    """Map view_count -> easy/medium/hard by tercile. PREVIEW ONLY.

    With only a handful of songs this is meaningless statistically; it just
    demonstrates that tier is *derived at read time*, never stored.
    """
    vals = sorted(v for v in view_counts if v is not None)
    if not vals:
        return {}
    lo = vals[len(vals) // 3]
    hi = vals[2 * len(vals) // 3]
    labels = {}
    for v in view_counts:
        if v is None:
            labels[v] = "unknown"
        elif v >= hi:
            labels[v] = "easy"      # very popular -> easy to guess
        elif v >= lo:
            labels[v] = "medium"
        else:
            labels[v] = "hard"
    return labels


def verify(db_path: Path) -> dict:
    """Read-only dump. Returns a small summary dict (handy for tests)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        songs = conn.execute("SELECT * FROM songs ORDER BY id").fetchall()
        view_counts = [s["view_count"] for s in songs]
        tier = _tercile_labels(view_counts)

        print("=" * 64)
        print(f"DB: {db_path}   |   {len(songs)} songs")
        print("=" * 64)
        summary = {"songs": len(songs), "warnings": []}
        for s in songs:
            n_alias = conn.execute(
                "SELECT COUNT(*) FROM aliases WHERE song_id=?", (s["id"],)
            ).fetchone()[0]
            n_frame = conn.execute(
                "SELECT COUNT(*) FROM frames WHERE song_id=?", (s["id"],)
            ).fetchone()[0]
            preview = (s["difficulty_override"]
                       or tier.get(s["view_count"], "unknown"))
            forced = " (override)" if s["difficulty_override"] else ""
            print(f"[{s['id']:03d}] {s['title']} — {s['artist']}")
            print(f"      year={s['year']} (raw={s['year_raw']}, "
                  f"override={s['year_override']})  views={s['view_count']}  "
                  f"dur={s['duration']}s")
            print(f"      aliases={n_alias}  frames={n_frame}  "
                  f"tier~{preview}{forced}  [tier=preview only]")
            # sanity gate
            if n_frame == 0:
                msg = f"song {s['id']} có 0 FRAME"
                summary["warnings"].append(msg)
                print(f"      !! CẢNH BÁO: {msg}")
            if n_alias == 0:
                msg = f"song {s['id']} có 0 ALIAS"
                summary["warnings"].append(msg)
                print(f"      !! CẢNH BÁO: {msg}")

        # year-filter demo (this is bot-side interpretation, shown for sanity)
        years = [s["year"] for s in songs if s["year"] is not None]
        if years:
            lo, hi = min(years), max(years)
            mid_lo = lo + (hi - lo) // 2
            subset = conn.execute(
                "SELECT id, title, year FROM songs WHERE year BETWEEN ? AND ? "
                "ORDER BY year", (mid_lo, hi),
            ).fetchall()
            print("-" * 64)
            print(f"Demo lọc year [{mid_lo}..{hi}] -> {len(subset)} bài:")
            for r in subset:
                print(f"   ({r['year']}) [{r['id']:03d}] {r['title']}")

        if summary["warnings"]:
            print("-" * 64)
            print(f"Tổng cộng {len(summary['warnings'])} cảnh báo sanity.")
        return summary
    finally:
        conn.close()


def cmd_verify(args) -> int:
    verify(DB_PATH)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_extract = sub.add_parser(
        "extract", help="yt-dlp metadata + ffmpeg candidate frames")
    p_extract.add_argument(
        "--force", action="store_true",
        help="làm lại cả bài đã extract (mặc định: bỏ qua bài đã có frame)")
    p_extract.add_argument(
        "--only", nargs="+", metavar="ID|RANGE|SLUG",
        help="chỉ extract bài theo id, range hoặc slug "
             "(vd: --only 1-5  |  --only 6 7  |  --only la-lung)")
    sub.add_parser("ingest", help="seed U manifest -> SQLite (idempotent)")
    sub.add_parser("verify", help="read-only dump + tier/year preview")
    args = parser.parse_args(argv)

    return {
        "extract": cmd_extract,
        "ingest": cmd_ingest,
        "verify": cmd_verify,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
