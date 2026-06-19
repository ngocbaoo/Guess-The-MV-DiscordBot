"""Make crawl.py importable from the repo root for all tests, and provide a
fake-DB builder so bot tests run real logic over a small SQLite db with no
network (mirrors tests/test_ingest.py's philosophy)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from crawl import ingest


def build_db(tmp_path, specs):
    """Build a real db/bot.db from `specs` via the crawler's ingest().

    Each spec: {id, title, slug, artist?, aliases?, year?, view_count?,
    year_override?, difficulty_override?, frames?} where `frames` is a list of
    openness tags ('hard'|'easy'|'normal') -> one curated frame file each.
    Returns the db path.
    """
    seed_path = tmp_path / "seed" / "songs.json"
    manifest_path = tmp_path / "build" / "manifest.json"
    db_path = tmp_path / "db" / "bot.db"
    frames_dir = tmp_path / "db" / "frames"
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    seed, manifest = [], {}
    for s in specs:
        seed.append({
            "id": s["id"], "title": s["title"], "artist": s.get("artist", ""),
            "url": s.get("url", f"u{s['id']}"), "slug": s["slug"],
            "aliases": s.get("aliases", []),
            "year_override": s.get("year_override"),
            "difficulty_override": s.get("difficulty_override"),
        })
        manifest[str(s["id"])] = {
            "id": s["id"], "view_count": s.get("view_count"),
            "duration": s.get("duration", 200), "upload_date": None,
            "year": s.get("year"), "extracted_at": "x",
        }
        opennesses = s.get("frames", [])
        if opennesses:
            folder = frames_dir / f"{s['id']:03d}-{s['slug']}"
            folder.mkdir(parents=True, exist_ok=True)
            for i, op in enumerate(opennesses):
                suffix = "" if op == "normal" else f"_{op}"
                (folder / f"{i * 10:05d}{suffix}.jpg").write_bytes(b"")

    seed_path.write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    ingest(seed_path, manifest_path, db_path, frames_dir)
    return db_path


@pytest.fixture
def db_factory(tmp_path):
    """Fixture returning a function: specs -> open sqlite Connection (via bot.db)."""
    from bot.db import connect

    def make(specs):
        return connect(build_db(tmp_path, specs))

    return make
