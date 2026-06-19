"""Matching: normalize parity with the crawler + fuzzy (>=80%) typing match."""
import crawl
from bot import matching
from bot.matching import is_correct_mc, is_correct_typing


def test_normalize_is_the_crawler_function():
    # Parity by identity: the bot must use the crawler's exact normalize().
    assert matching.normalize is crawl.normalize


def test_normalize_golden_cases_parity():
    cases = [
        "Chạy Ngay Đi", "Sơn Tùng (M-TP)", "Top 40 Hits!!!", "ĐÔNG",
        "AMEE & friends 🎵", "There's No One At All", "Y.Ê.U",
    ]
    for c in cases:
        assert matching.normalize(c) == crawl.normalize(c)


def test_typing_exact_and_diacritic_insensitive():
    aliases = [crawl.normalize("Chạy Ngay Đi"), "cnd"]
    assert is_correct_typing("chay ngay di", aliases)[0] is True
    assert is_correct_typing("Chạy Ngay Đi", aliases)[0] is True   # diacritics ok
    assert is_correct_typing("CND", aliases)[0] is True


def test_typing_fuzzy_accepts_near_miss_rejects_far():
    aliases = ["chay ngay di"]
    assert is_correct_typing("chay ngay d", aliases)[0] is True     # 1 char off
    assert is_correct_typing("chay ngay dii", aliases)[0] is True   # 1 extra char
    assert is_correct_typing("hello world", aliases)[0] is False    # unrelated
    assert is_correct_typing("", aliases)[0] is False               # empty


def test_mc_matches_by_id():
    assert is_correct_mc(7, 7) is True
    assert is_correct_mc("7", 7) is True
    assert is_correct_mc(8, 7) is False
