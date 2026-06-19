"""Build the 4 distinct MC options (1 answer + 3 distractors).

Fallback chain when the filtered pool is too thin:
  (1) distractors from the already-filtered pool (same difficulty + year),
      excluding the answer and songs already shown this game;
  (2) widen to the whole catalog (any titled song) minus the answer;
  (3) if the catalog still can't yield 4 distinct titles -> return None so the
      caller reports "MC unavailable" instead of fabricating options.

Options are distinct by title (the seed has some duplicate titles) and their
order is fixed once, by the caller's seeded rng, in the question snapshot.
"""
from bot.config import MC_CHOICES


def _as_option(row):
    return {"id": row["id"], "title": row["title"]}


def _distinct_distractors(rows, answer_id, answer_title, exclude_ids, need, rng):
    seen_titles = {answer_title}
    rows = list(rows)
    rng.shuffle(rows)
    picked = []
    for r in rows:
        if r["id"] == answer_id or r["id"] in exclude_ids:
            continue
        if r["title"] in seen_titles or not r["title"]:
            continue
        seen_titles.add(r["title"])
        picked.append(_as_option(r))
        if len(picked) == need:
            break
    return picked


def build_choices(conn, answer, pool, exclude_ids, rng, n_choices=MC_CHOICES):
    """Return a shuffled list of `n_choices` option dicts, or None if MC can't
    be built. The answer is always included.
    """
    need = n_choices - 1
    aid, atitle = answer["id"], answer["title"]

    distractors = _distinct_distractors(pool, aid, atitle, exclude_ids, need, rng)

    if len(distractors) < need:  # fallback (2): widen to whole catalog
        catalog = conn.execute(
            "SELECT id, title FROM songs WHERE title <> ''").fetchall()
        distractors = _distinct_distractors(catalog, aid, atitle, set(), need, rng)

    if len(distractors) < need:  # fallback (3): genuinely not enough songs
        return None

    options = distractors + [_as_option(answer)]
    rng.shuffle(options)
    return options
