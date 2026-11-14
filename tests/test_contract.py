from __future__ import annotations

from oculus_pdf.contract import (
    MARKER_THRESHOLD,
    WORD_THRESHOLD,
    is_contract_page,
)


def make_text(word_count: int, markers: tuple[str, ...] = ()) -> str:
    """Text with an exact word count, made of the given markers plus filler."""
    marker_words = sum(len(marker.split()) for marker in markers)
    assert marker_words <= word_count
    text = " ".join([*markers, *["filler"] * (word_count - marker_words)])
    assert len(text.split()) == word_count
    return text


def invoice_text(word_count: int = 500) -> str:
    """Ordinary invoice-like lines of items and prices, with no markers."""
    words = ["Invoice", "number", "12345"]
    index = 0
    while len(words) < word_count:
        words.extend(["Item", str(index), f"{index}.99"])
        index += 1
    text = " ".join(words[:word_count])
    assert len(text.split()) == word_count
    return text


def test_thresholds():
    assert WORD_THRESHOLD == 400
    assert MARKER_THRESHOLD == 3


def test_empty_string_is_not_contract():
    assert is_contract_page("") is False


def test_399_words_with_eight_markers_is_not_contract():
    text = make_text(
        399,
        (
            "lessee",
            "lessor",
            "indemnify",
            "hereby",
            "this agreement",
            "terms and conditions",
            "sublease",
            "warranty",
        ),
    )
    assert is_contract_page(text) is False


def test_400_words_with_two_distinct_markers_is_not_contract():
    text = make_text(400, ("lessee", "lessor"))
    assert is_contract_page(text) is False


def test_400_words_with_three_distinct_markers_is_contract():
    text = make_text(400, ("lessee", "lessor", "hereby"))
    assert is_contract_page(text) is True


def test_repeated_same_marker_counts_once():
    text = make_text(400, ("lessee",) * 20)
    assert is_contract_page(text) is False


def test_markers_are_case_insensitive():
    text = make_text(400, ("LESSEE", "Lessor", "HEREBY"))
    assert is_contract_page(text) is True


def test_whole_word_matching():
    assert is_contract_page(make_text(400, ("lessees",) * 400)) is False
    text = make_text(400, (*("lessees",) * 397, "lessor", "hereby", "lessee,"))
    assert is_contract_page(text) is True


def test_unrelated_words_do_not_match():
    assert is_contract_page(make_text(400, ("guarantee",) * 400)) is False


def test_sublease_variants_are_one_marker():
    text = make_text(400, ("sub-lease", "sublease", "subleasing") * 20)
    assert is_contract_page(text) is False
    text = make_text(
        400, ("lessor", "hereby", "sub-lease", "sublease", "subleasing")
    )
    assert is_contract_page(text) is True


def test_long_invoice_text_is_not_contract():
    text = invoice_text(500)
    assert is_contract_page(text) is False


def test_two_liability_style_markers_need_a_third_distinct_one():
    two = make_text(400, ("liability", "warranty", "liability"))
    assert is_contract_page(two) is False
    three = make_text(400, ("liability", "warranty", "governing law"))
    assert is_contract_page(three) is True
