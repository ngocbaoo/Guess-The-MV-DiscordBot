"""Unit tests for normalize() — the alias chokepoint.

Covers Vietnamese diacritics, Đ/đ, special chars, abbreviations,
whitespace, and idempotency.
"""
import pytest

from crawl import normalize


def test_diacritics_vs_plain_collide():
    # The canonical example from the spec.
    assert normalize("Chạy Ngay Đi") == normalize("chay ngay di") == "chay ngay di"


@pytest.mark.parametrize("raw,expected", [
    ("Đi Về Nhà", "di ve nha"),
    ("đường", "duong"),
    ("ĐÔNG", "dong"),                 # uppercase Đ -> d
    ("Hãy Trao Cho Anh", "hay trao cho anh"),
    ("Để Mị Nói Cho Mà Nghe", "de mi noi cho ma nghe"),
    ("Lạ Lùng", "la lung"),
])
def test_vietnamese_known_pairs(raw, expected):
    assert normalize(raw) == expected


def test_d_with_stroke_both_cases():
    assert normalize("Đ") == "d"
    assert normalize("đ") == "d"


def test_strip_special_chars_and_case():
    assert normalize("C.N.D!") == "c n d"
    assert normalize("Sơn Tùng (M-TP)") == "son tung m tp"
    assert normalize("AMEE & friends") == "amee friends"


def test_abbreviation():
    assert normalize("CND") == "cnd"
    assert normalize("HTCA") == "htca"


def test_whitespace_collapsed_and_trimmed():
    assert normalize("   chay    ngay   di  ") == "chay ngay di"
    assert normalize("\tDi\nVe  Nha ") == "di ve nha"


def test_idempotent():
    for s in ["Chạy Ngay Đi", "Để Mị Nói Cho Mà Nghe", "  Lạ  Lùng ", "CND"]:
        once = normalize(s)
        assert normalize(once) == once


def test_digits_kept():
    assert normalize("Top 40 Hits!!!") == "top 40 hits"
