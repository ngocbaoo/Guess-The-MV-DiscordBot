"""Name masking for typing mode (display only; matching always uses normalize()).

Operates on the DISPLAY title (diacritics and case preserved). We walk grapheme
clusters (regex \\X) so a base letter plus its combining marks counts as one
"letter"; spaces and punctuation are non-letters and are ALWAYS shown. Hidden
letters render as a single '_'.

Reveal is stable per question (seeded) and MONOTONE: the 50% set is a superset
of the 25% set, because both are prefixes of the same seeded permutation.
"""
import math
import random
import unicodedata

from bot.config import REVEAL_RATIOS

try:
    import regex as _regex  # grapheme support via \X
except ImportError:  # pragma: no cover - fallback when `regex` isn't installed
    _regex = None


def _graphemes(s):
    if _regex is not None:
        return _regex.findall(r"\X", s)
    return list(s)  # fallback: per-codepoint (good enough for most Vpop titles)


def _is_letter(cluster: str) -> bool:
    return any(ch.isalpha() for ch in cluster)


def mask_name(name: str, ratio: float, seed) -> str:
    """Mask the title, revealing ~`ratio` of letter positions (seeded, stable).

    ratio=0 hides every letter; non-letters are always shown.
    """
    name = unicodedata.normalize("NFC", name)
    clusters = _graphemes(name)
    letter_idx = [i for i, c in enumerate(clusters) if _is_letter(c)]

    rng = random.Random(seed)
    order = list(letter_idx)
    rng.shuffle(order)
    k = math.ceil(ratio * len(letter_idx)) if letter_idx else 0
    revealed = set(order[:k])

    out = []
    for i, c in enumerate(clusters):
        if _is_letter(c) and i not in revealed:
            out.append("_")
        else:
            out.append(c)
    return "".join(out)


def letters_ratio_at(elapsed: int) -> float:
    """The cumulative letter-reveal ratio at a given elapsed second.

    Takes the largest configured ratio whose checkpoint has already passed, so
    reveal only ever grows (monotone) across the question's timeline.
    """
    passed = [v for sec, v in REVEAL_RATIOS.items() if sec <= elapsed]
    return max(passed) if passed else 0.0
