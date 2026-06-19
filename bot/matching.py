"""Answer matching.

The single most important invariant: the bot must normalize guesses with the
EXACT same function the crawler used to build alias_norm. So we import it
directly from the crawler — one source of truth, no drift. A parity test guards
against anyone breaking that import.

Typing mode: normalized exact alias hit OR rapidfuzz ratio >= FUZZY_RATIO_MIN.
MC mode: match by song_id of the pressed button (no normalize, no diacritics).
"""
from rapidfuzz import fuzz

from crawl import normalize  # single source of truth (shared with crawler)

from bot.config import FUZZY_RATIO_MIN


def is_correct_typing(guess: str, aliases_norm, threshold: int = FUZZY_RATIO_MIN):
    """Return (matched: bool, score: int) for a typed guess against one song.

    `aliases_norm` is the set/list of that song's normalized aliases. We accept
    an exact normalized hit, or a best fuzzy ratio at/above the threshold.
    """
    norm_guess = normalize(guess)
    if not norm_guess:
        return False, 0
    aliases = list(aliases_norm)
    if norm_guess in aliases:
        return True, 100
    best = max((fuzz.ratio(norm_guess, a) for a in aliases), default=0.0)
    return best >= threshold, int(round(best))


def is_correct_mc(picked_song_id: int, answer_song_id: int) -> bool:
    """MC is matched purely by id — no text normalization needed."""
    return int(picked_song_id) == int(answer_song_id)
