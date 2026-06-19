"""Selection: runtime tier (NTILE + full override), year filter, the >=3-frame
gate, no-repeat sampling, and per-question frame ordering."""
import random

from bot.selection import (build_pool, load_frames, order_frames,
                           pick_questions)

# Six non-overridden songs (views 600..100 desc) + three overridden songs whose
# huge views would skew terciles IF they were counted -- they must not be.
_TIER_SPECS = [
    {"id": 1, "title": "S1", "slug": "s1", "view_count": 600, "year": 2020,
     "frames": ["hard", "normal", "easy"]},
    {"id": 2, "title": "S2", "slug": "s2", "view_count": 500, "year": 2020,
     "frames": ["hard", "normal", "easy"]},
    {"id": 3, "title": "S3", "slug": "s3", "view_count": 400, "year": 2019,
     "frames": ["hard", "normal", "easy"]},
    {"id": 4, "title": "S4", "slug": "s4", "view_count": 300, "year": 2019,
     "frames": ["hard", "normal", "easy"]},
    {"id": 5, "title": "S5", "slug": "s5", "view_count": 200, "year": 2018,
     "frames": ["hard", "normal", "easy"]},
    {"id": 6, "title": "S6", "slug": "s6", "view_count": 100, "year": 2018,
     "frames": ["hard", "normal", "easy"]},
    {"id": 7, "title": "O7", "slug": "o7", "view_count": 9990, "year": 2020,
     "difficulty_override": "easy", "frames": ["hard", "normal", "easy"]},
    {"id": 8, "title": "O8", "slug": "o8", "view_count": 9990, "year": 2020,
     "difficulty_override": "medium", "frames": ["hard", "normal", "easy"]},
    {"id": 9, "title": "O9", "slug": "o9", "view_count": 9990, "year": 2020,
     "difficulty_override": "hard", "frames": ["hard", "normal", "easy"]},
]


def test_tier_ntile_and_full_override(db_factory):
    conn = db_factory(_TIER_SPECS)
    tier = {r["id"]: r["tier"] for r in build_pool(conn)}
    # NTILE over the 6 non-overridden songs only: top2 easy, mid2 med, low2 hard.
    assert tier[1] == "easy" and tier[2] == "easy"
    assert tier[3] == "medium" and tier[4] == "medium"
    assert tier[5] == "hard" and tier[6] == "hard"
    # Overridden songs keep their forced value despite 9990 views.
    assert tier[7] == "easy" and tier[8] == "medium" and tier[9] == "hard"


def test_difficulty_filter(db_factory):
    conn = db_factory(_TIER_SPECS)
    easy_ids = {r["id"] for r in build_pool(conn, difficulty="easy")}
    assert easy_ids == {1, 2, 7}


def test_year_filter_inclusive_and_null_bound(db_factory):
    conn = db_factory(_TIER_SPECS)
    ids = {r["id"] for r in build_pool(conn, year_start=2019, year_end=2019)}
    assert ids == {3, 4}
    # Only an upper bound (start None): everything <= 2018.
    ids2 = {r["id"] for r in build_pool(conn, year_end=2018)}
    assert ids2 == {5, 6}


def test_min_frames_gate(db_factory):
    specs = [
        {"id": 1, "title": "ok", "slug": "ok", "view_count": 100,
         "frames": ["hard", "normal", "easy"]},
        {"id": 2, "title": "thin", "slug": "thin", "view_count": 90,
         "frames": ["hard", "easy"]},          # only 2 frames -> excluded
        {"id": 3, "title": "none", "slug": "none", "view_count": 80},  # 0 frames
    ]
    conn = db_factory(specs)
    assert {r["id"] for r in build_pool(conn)} == {1}


def test_pick_questions_no_repeat_and_truncation(db_factory):
    conn = db_factory(_TIER_SPECS)
    pool = build_pool(conn)
    rng = random.Random(0)
    chosen, truncated = pick_questions(pool, 4, rng)
    assert len(chosen) == 4
    assert len({c["id"] for c in chosen}) == 4          # all distinct
    assert truncated is False
    # Ask for more than the pool has -> truncated, still distinct.
    chosen2, truncated2 = pick_questions(pool, 100, rng)
    assert truncated2 is True
    assert len(chosen2) == len(pool)
    assert len({c["id"] for c in chosen2}) == len(pool)


def test_order_frames_prefers_openness_and_is_distinct(db_factory):
    specs = [{"id": 1, "title": "f", "slug": "f", "view_count": 100,
              "frames": ["hard", "hard", "normal", "easy", "easy"]}]
    conn = db_factory(specs)
    frames = load_frames(conn, 1)
    chosen = order_frames(frames, random.Random(1))
    assert len(chosen) == 3
    assert len({f["file_path"] for f in chosen}) == 3   # distinct
    assert chosen[0]["openness"] == "hard"
    assert chosen[1]["openness"] == "normal"
    assert chosen[2]["openness"] == "easy"


def test_order_frames_falls_back_when_openness_missing(db_factory):
    # No 'normal' tag: stage2 must still get a distinct frame (random fallback).
    specs = [{"id": 1, "title": "f", "slug": "f", "view_count": 100,
              "frames": ["hard", "easy", "easy"]}]
    conn = db_factory(specs)
    chosen = order_frames(load_frames(conn, 1), random.Random(2))
    assert len({f["file_path"] for f in chosen}) == 3
    assert chosen[0]["openness"] == "hard"
    assert chosen[2]["openness"] == "easy"
