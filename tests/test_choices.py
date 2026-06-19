"""MC choices: 4 distinct options incl. answer, with the fallback chain."""
import random

from bot.choices import build_choices
from bot.selection import build_pool


def _frames():
    return ["hard", "normal", "easy"]


def test_four_distinct_options_including_answer(db_factory):
    specs = [{"id": i, "title": f"T{i}", "slug": f"t{i}", "view_count": 100 - i,
              "frames": _frames()} for i in range(1, 6)]
    conn = db_factory(specs)
    pool = build_pool(conn)
    answer = next(r for r in pool if r["id"] == 1)
    opts = build_choices(conn, answer, pool, exclude_ids=set(),
                         rng=random.Random(0))
    assert len(opts) == 4
    ids = [o["id"] for o in opts]
    assert len(set(ids)) == 4               # distinct
    assert 1 in ids                         # answer present
    assert len({o["title"] for o in opts}) == 4


def test_fallback_to_catalog_when_pool_thin(db_factory):
    # Only one EASY song (the answer); distractors must come from the catalog.
    specs = [{"id": 1, "title": "A", "slug": "a", "view_count": 100,
              "difficulty_override": "easy", "frames": _frames()}]
    specs += [{"id": i, "title": f"H{i}", "slug": f"h{i}", "view_count": 90,
               "difficulty_override": "hard", "frames": _frames()}
              for i in range(2, 6)]
    conn = db_factory(specs)
    easy_pool = build_pool(conn, difficulty="easy")
    assert {r["id"] for r in easy_pool} == {1}
    answer = easy_pool[0]
    opts = build_choices(conn, answer, easy_pool, exclude_ids=set(),
                         rng=random.Random(1))
    assert opts is not None and len(opts) == 4
    assert 1 in [o["id"] for o in opts]


def test_mc_unavailable_when_catalog_too_small(db_factory):
    specs = [{"id": i, "title": f"T{i}", "slug": f"t{i}", "view_count": 10,
              "frames": _frames()} for i in range(1, 4)]   # only 3 songs total
    conn = db_factory(specs)
    pool = build_pool(conn)
    answer = pool[0]
    assert build_choices(conn, answer, pool, exclude_ids=set(),
                         rng=random.Random(2)) is None
