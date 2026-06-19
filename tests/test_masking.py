"""Masking: monotone reveal (50% superset of 25%), non-letters always shown."""
from bot.masking import letters_ratio_at, mask_name

NAME = "Chay Ngay Di"   # ASCII so per-position checks are unambiguous


def _revealed_letters(name, ratio, seed):
    m = mask_name(name, ratio, seed)
    return {i for i, (a, b) in enumerate(zip(name, m)) if a.isalpha() and b != "_"}


def test_ratio_zero_hides_all_letters():
    m = mask_name(NAME, 0.0, seed=7)
    assert _revealed_letters(NAME, 0.0, 7) == set()
    # spaces are non-letters and stay visible at their positions
    assert m[4] == " " and m[9] == " "


def test_reveal_is_monotone_superset():
    s = 123
    small = _revealed_letters(NAME, 0.25, s)
    big = _revealed_letters(NAME, 0.50, s)
    assert small <= big                 # 50% set contains the 25% set
    assert len(big) > len(small)


def test_non_letters_always_shown():
    name = "C.N.D! (x)"
    m = mask_name(name, 0.0, seed=1)
    for i, ch in enumerate(name):
        if not ch.isalpha():
            assert m[i] == ch           # punctuation/space/parens preserved


def test_letters_ratio_at_checkpoints():
    assert letters_ratio_at(0) == 0.0
    assert letters_ratio_at(10) == 0.25
    assert letters_ratio_at(20) == 0.25     # no new reveal until 40s
    assert letters_ratio_at(40) == 0.50
