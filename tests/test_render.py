from __future__ import annotations

import pymupdf
import pytest

from oculus_pdf.render import page_count, page_text, parse_page_range, render_pages

WIDTH = 300
HEIGHT = 400


@pytest.fixture
def pdf_path(tmp_path):
    path = tmp_path / "fixture.pdf"
    doc = pymupdf.open()
    for number in range(1, 4):
        page = doc.new_page(width=WIDTH, height=HEIGHT)
        page.insert_text((50, 50), f"Page {number}")
    doc.save(path)
    doc.close()
    return path


def test_page_count(pdf_path):
    assert page_count(pdf_path) == 3


def test_page_count_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        page_count(tmp_path / "missing.pdf")


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        (None, [1, 2, 3]),
        ("2", [2]),
        ("1-2", [1, 2]),
        ("1,3", [1, 3]),
    ],
)
def test_parse_page_range(spec, expected):
    assert parse_page_range(spec, 3) == expected


@pytest.mark.parametrize("spec", ["0", "4", "a", "3-1"])
def test_parse_page_range_invalid(spec):
    with pytest.raises(ValueError):
        parse_page_range(spec, 3)


def test_render_pages_png_and_pixel_size(pdf_path):
    for page_number, png in render_pages(pdf_path, [1, 2, 3], dpi=72):
        assert png.startswith(b"\x89PNG")
        pixmap = pymupdf.Pixmap(png)
        assert (pixmap.width, pixmap.height) == (WIDTH, HEIGHT)


def test_render_pages_double_dpi(pdf_path):
    (_, at_72), = render_pages(pdf_path, [1], dpi=72)
    (_, at_144), = render_pages(pdf_path, [1], dpi=144)
    assert pymupdf.Pixmap(at_144).width == 2 * pymupdf.Pixmap(at_72).width
    assert pymupdf.Pixmap(at_144).height == 2 * pymupdf.Pixmap(at_72).height


def test_page_text_all_pages(pdf_path):
    texts = page_text(pdf_path, [1, 2, 3])
    assert list(texts) == [1, 2, 3]
    with pymupdf.open(pdf_path) as doc:
        for number, text in texts.items():
            assert text
            assert f"Page {number}" in text
            assert text == doc.load_page(number - 1).get_text()


def test_page_text_subset_in_requested_order(pdf_path):
    texts = page_text(pdf_path, [3, 1])
    assert list(texts) == [3, 1]
    assert "Page 3" in texts[3]
    assert "Page 1" in texts[1]


def test_page_text_empty_list(pdf_path):
    assert page_text(pdf_path, []) == {}


def test_page_text_without_text(tmp_path):
    path = tmp_path / "blank.pdf"
    doc = pymupdf.open()
    doc.new_page(width=WIDTH, height=HEIGHT)
    doc.save(path)
    doc.close()
    assert page_text(path, [1]) == {1: ""}


def test_page_text_missing_file(tmp_path):
    with pytest.raises(Exception):
        page_text(tmp_path / "missing.pdf", [1])


def test_page_text_garbage_file(tmp_path):
    path = tmp_path / "garbage.pdf"
    path.write_bytes(b"not a pdf")
    with pytest.raises(Exception):
        page_text(path, [1])
