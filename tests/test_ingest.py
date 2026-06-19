"""End-to-end ingest -> verify on a FAKE fixture. No YouTube, no network.

This is the real acceptance of the crawl logic: resolve year (null-safe +
seed-wins), dedupe aliases, relative frame paths, openness from suffix,
idempotency, and the missing-frames-dir branch.
"""
import json
import sqlite3

import pytest

from crawl import ingest, verify, normalize, expand_selectors


def test_expand_selectors():
    assert expand_selectors(["1-5"]) == {"1", "2", "3", "4", "5"}
    assert expand_selectors(["6", "7"]) == {"6", "7"}
    assert expand_selectors(["la-lung"]) == {"la-lung"}
    # mixed + reversed range + slug
    assert expand_selectors(["3-1", "la-lung"]) == {"1", "2", "3", "la-lung"}
    assert expand_selectors([]) == set()


def _write_fixture(tmp_path):
    """Build a complete fake run: seed, manifest, and curated frames.

    Layout mirrors production:
        seed/songs.json
        build/manifest.json
        db/bot.db
        db/frames/{id:03d}-slug/*.jpg
    """
    seed_path = tmp_path / "seed" / "songs.json"
    manifest_path = tmp_path / "build" / "manifest.json"
    db_path = tmp_path / "db" / "bot.db"
    frames_dir = tmp_path / "db" / "frames"

    seed = [
        # id 1: title equals one alias -> must dedupe to a single row.
        {"id": 1, "title": "Chạy Ngay Đi", "artist": "Sơn Tùng M-TP",
         "url": "u1", "slug": "chay-ngay-di",
         "aliases": ["Chay Ngay Di", "chay ngay di", "CND"],
         "year_override": 2017, "difficulty_override": None},
        # id 2: hidden upload_date AND hidden view_count (null-safe).
        {"id": 2, "title": "Lạ Lùng", "artist": "Vũ", "url": "u2",
         "slug": "la-lung", "aliases": ["La Lung"],
         "year_override": None, "difficulty_override": "hard"},
        # id 3: no curated frames dir at all -> 0-frame branch, no crash.
        {"id": 3, "title": "Đi Về Nhà", "artist": "Đen", "url": "u3",
         "slug": "di-ve-nha", "aliases": [],
         "year_override": None, "difficulty_override": None},
    ]
    manifest = {
        "1": {"id": 1, "view_count": 500_000_000, "duration": 247,
              "upload_date": "20180512", "year": 2018,
              "extracted_at": "x"},
        "2": {"id": 2, "view_count": None, "duration": 300,
              "upload_date": None, "year": None, "extracted_at": "x"},
        "3": {"id": 3, "view_count": 30_000_000, "duration": 210,
              "upload_date": "20201001", "year": 2020, "extracted_at": "x"},
    }

    seed_path.parent.mkdir(parents=True)
    manifest_path.parent.mkdir(parents=True)
    seed_path.write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    # Curated frames: empty .jpg files with openness suffixes.
    (frames_dir / "001-chay-ngay-di").mkdir(parents=True)
    for name in ["00060_easy.jpg", "00120.jpg", "00180_hard.jpg"]:
        (frames_dir / "001-chay-ngay-di" / name).write_bytes(b"")
    (frames_dir / "002-la-lung").mkdir(parents=True)
    (frames_dir / "002-la-lung" / "00090.jpg").write_bytes(b"")
    # id 3: intentionally NO directory created.

    return seed_path, manifest_path, db_path, frames_dir


def test_ingest_end_to_end(tmp_path):
    seed_path, manifest_path, db_path, frames_dir = _write_fixture(tmp_path)
    ingest(seed_path, manifest_path, db_path, frames_dir)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        songs = {r["id"]: r for r in conn.execute("SELECT * FROM songs")}
        assert len(songs) == 3

        # seed-wins-manifest for year
        assert songs[1]["year"] == 2017          # override beats manifest 2018
        assert songs[1]["year_raw"] == 2018
        # null-safe: hidden date -> year None, hidden views -> view_count None
        assert songs[2]["year"] is None
        assert songs[2]["view_count"] is None
        # no override -> manifest year passes through
        assert songs[3]["year"] == 2020
        assert songs[2]["difficulty_override"] == "hard"

        # dedupe: title + 3 aliases but several normalize identically -> 2 rows
        a1 = [r["alias_norm"] for r in conn.execute(
            "SELECT alias_norm FROM aliases WHERE song_id=1 ORDER BY alias_norm")]
        assert a1 == ["chay ngay di", "cnd"]
        assert normalize("Chạy Ngay Đi") in a1

        # frames: relative to db/, openness from suffix
        frames1 = {r["file_path"]: r["openness"] for r in conn.execute(
            "SELECT file_path, openness FROM frames WHERE song_id=1")}
        assert frames1 == {
            "frames/001-chay-ngay-di/00060_easy.jpg": "easy",
            "frames/001-chay-ngay-di/00120.jpg": "normal",
            "frames/001-chay-ngay-di/00180_hard.jpg": "hard",
        }
        # every stored path is relative and points to a real file
        for path in frames1:
            assert not path.startswith("/") and ":" not in path
            assert (db_path.parent / path).is_file()

        # id 3 had no frames dir -> 0 frames, but song still ingested
        assert conn.execute(
            "SELECT COUNT(*) FROM frames WHERE song_id=3").fetchone()[0] == 0
    finally:
        conn.close()


def test_ingest_is_idempotent(tmp_path):
    seed_path, manifest_path, db_path, frames_dir = _write_fixture(tmp_path)
    ingest(seed_path, manifest_path, db_path, frames_dir)
    ingest(seed_path, manifest_path, db_path, frames_dir)  # rerun = drop & recreate

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM aliases").fetchone()[0] == 2 + 1 + 1
        assert conn.execute("SELECT COUNT(*) FROM frames").fetchone()[0] == 3 + 1
    finally:
        conn.close()


def test_verify_flags_zero_frames(tmp_path, capsys):
    seed_path, manifest_path, db_path, frames_dir = _write_fixture(tmp_path)
    ingest(seed_path, manifest_path, db_path, frames_dir)
    summary = verify(db_path)

    assert summary["songs"] == 3
    # id 3 has no curated frames dir -> 0-frame warning.
    # (Title is always an alias, so 0-alias cannot occur for these songs.)
    assert any("0 FRAME" in w for w in summary["warnings"])
    assert not any("0 ALIAS" in w for w in summary["warnings"])
