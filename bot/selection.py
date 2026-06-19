"""Pool building and per-game song/frame selection.

Tier is derived at READ time from view_count (never stored): NTILE(3) terciles,
group 1 = easy (highest views), 2 = medium, 3 = hard. `difficulty_override`
wins FULLY — overridden songs take their forced value and are excluded from the
NTILE computation so they don't skew the tercile boundaries. Tie-break is
stable: ORDER BY view_count DESC, id ASC.

Year filter and the >=3-frame playability gate are applied here too. Rejections
are logged so missing-data in the crawler output is easy to spot.
"""
import logging
import random

from bot.config import MIN_FRAMES

log = logging.getLogger(__name__)

# Tier is computed in SQL. NTILE runs only over non-overridden songs; overridden
# songs LEFT JOIN to NULL and fall through to their forced difficulty.
_POOL_SQL = """
WITH playable AS (
  SELECT s.id, s.title, s.artist, s.url, s.view_count, s.year,
         s.difficulty_override,
         (SELECT COUNT(*) FROM frames f WHERE f.song_id = s.id) AS n_frames
  FROM songs s
),
ranked AS (
  SELECT id, NTILE(3) OVER (ORDER BY view_count DESC, id ASC) AS nt
  FROM playable
  WHERE difficulty_override IS NULL
)
SELECT p.id, p.title, p.artist, p.url, p.view_count, p.year, p.n_frames,
       CASE
         WHEN p.difficulty_override IS NOT NULL THEN p.difficulty_override
         WHEN r.nt = 1 THEN 'easy'
         WHEN r.nt = 2 THEN 'medium'
         ELSE 'hard'
       END AS tier
FROM playable p
LEFT JOIN ranked r ON r.id = p.id
ORDER BY p.id ASC
"""


def build_pool(conn, difficulty="all", year_start=None, year_end=None,
               min_frames=MIN_FRAMES):
    """Return the list of playable song rows after difficulty/year/frame filters.

    `difficulty` is one of {'all','easy','medium','hard'}. Year bounds are
    inclusive; either may be None to drop that side of the range. Songs without
    a year are excluded when any year bound is set.
    """
    rows = conn.execute(_POOL_SQL).fetchall()
    pool = []
    for r in rows:
        if r["n_frames"] < min_frames:
            log.info("drop song %s (%r): %d frame < %d",
                     r["id"], r["title"], r["n_frames"], min_frames)
            continue
        if difficulty != "all" and r["tier"] != difficulty:
            log.debug("drop song %s: tier %s != %s", r["id"], r["tier"], difficulty)
            continue
        if year_start is not None and (r["year"] is None or r["year"] < year_start):
            log.debug("drop song %s: year %s < %s", r["id"], r["year"], year_start)
            continue
        if year_end is not None and (r["year"] is None or r["year"] > year_end):
            log.debug("drop song %s: year %s > %s", r["id"], r["year"], year_end)
            continue
        pool.append(r)
    return pool


def pick_questions(pool, n, rng=random):
    """Sample up to n DISTINCT songs without replacement (anti-repeat).

    Returns (chosen, truncated): `truncated` is True when the pool had fewer
    than n playable songs, so the caller can tell players n was reduced.
    """
    k = min(n, len(pool))
    chosen = rng.sample(list(pool), k)
    return chosen, k < n


def load_aliases_norm(conn, song_id):
    """Normalized aliases for one song (used by typing-mode matching)."""
    return [r["alias_norm"] for r in conn.execute(
        "SELECT alias_norm FROM aliases WHERE song_id = ?", (song_id,))]


def load_frames(conn, song_id):
    """All frames for one song as a list of {file_path, openness} dicts."""
    return [{"file_path": r["file_path"], "openness": r["openness"]}
            for r in conn.execute(
                "SELECT file_path, openness FROM frames WHERE song_id = ? "
                "ORDER BY file_path", (song_id,))]


def order_frames(frames, rng):
    """Pick 3 DISTINCT frames for stages hard/medium/easy.

    stage1 prefers openness 'hard', stage2 'normal', stage3 'easy'; when the
    preferred openness is exhausted, fall back to a random remaining frame.
    Requires len(frames) >= 3 (guaranteed by the pool's MIN_FRAMES gate).
    """
    if len(frames) < 3:
        raise ValueError("order_frames needs at least 3 frames")
    used = set()
    chosen = []
    for pref in ("hard", "normal", "easy"):
        candidates = [f for f in frames
                      if f["openness"] == pref and f["file_path"] not in used]
        if not candidates:
            candidates = [f for f in frames if f["file_path"] not in used]
        pick = rng.choice(candidates)
        used.add(pick["file_path"])
        chosen.append(pick)
    return chosen
