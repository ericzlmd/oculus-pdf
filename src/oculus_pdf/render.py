from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pymupdf


def page_count(pdf_path: Path) -> int:
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    with pymupdf.open(pdf_path) as doc:
        return doc.page_count


def parse_page_range(spec: str | None, total: int) -> list[int]:
    if spec is None:
        return list(range(1, total + 1))

    pages: set[int] = set()
    for token in spec.split(","):
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start, end = int(start_text), int(end_text)
            if start > end:
                raise ValueError(f"invalid page range: {token!r}")
            pages.update(range(start, end + 1))
        else:
            pages.add(int(token))

    for page in pages:
        if not 1 <= page <= total:
            raise ValueError(f"page {page} out of range 1..{total}")
    return sorted(pages)


def render_pages(
    pdf_path: Path, pages: list[int], dpi: int
) -> Iterator[tuple[int, bytes]]:
    matrix = pymupdf.Matrix(dpi / 72, dpi / 72)
    with pymupdf.open(pdf_path) as doc:
        for page_number in pages:
            page = doc.load_page(page_number - 1)
            pixmap = page.get_pixmap(matrix=matrix)
            yield page_number, pixmap.tobytes("png")


def page_text(pdf_path: Path, pages: list[int]) -> dict[int, str]:
    with pymupdf.open(pdf_path) as doc:
        return {
            page_number: doc.load_page(page_number - 1).get_text()
            for page_number in pages
        }
