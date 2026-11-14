from pathlib import Path

import pytest

from oculus_pdf.output import demote_headings, write_document


def test_all_ok_document(tmp_path: Path) -> None:
    out_file = tmp_path / "document.md"

    write_document(out_file, "invoice", [1, 2], {1: "first page", 2: "second page"}, {})

    assert out_file.read_text(encoding="utf-8") == (
        "# invoice\n"
        "\n"
        "## Page 1\n"
        "\n"
        "first page\n"
        "\n"
        "## Page 2\n"
        "\n"
        "second page\n"
    )


def test_failed_page_collapses_error_newlines(tmp_path: Path) -> None:
    out_file = tmp_path / "document.md"

    write_document(out_file, "invoice", [1, 2], {1: "ok"}, {2: "boom\nnow"})

    assert out_file.read_text(encoding="utf-8") == (
        "# invoice\n"
        "\n"
        "## Page 1\n"
        "\n"
        "ok\n"
        "\n"
        "## Page 2 (failed)\n"
        "\n"
        "*Transcription failed: boom now*\n"
    )


def test_mixed_page_order_is_honored(tmp_path: Path) -> None:
    out_file = tmp_path / "document.md"

    write_document(
        out_file,
        "invoice",
        [2, 1, 3],
        {1: "one", 2: "two", 3: "three"},
        {},
    )

    assert out_file.read_text(encoding="utf-8") == (
        "# invoice\n"
        "\n"
        "## Page 2\n"
        "\n"
        "two\n"
        "\n"
        "## Page 1\n"
        "\n"
        "one\n"
        "\n"
        "## Page 3\n"
        "\n"
        "three\n"
    )


def test_page_missing_from_both_dicts_uses_unknown_error(tmp_path: Path) -> None:
    out_file = tmp_path / "document.md"

    write_document(out_file, "invoice", [1, 2], {1: "one"}, {})

    assert out_file.read_text(encoding="utf-8") == (
        "# invoice\n"
        "\n"
        "## Page 1\n"
        "\n"
        "one\n"
        "\n"
        "## Page 2 (failed)\n"
        "\n"
        "*Transcription failed: unknown error*\n"
    )


def test_empty_pages_writes_title_only(tmp_path: Path) -> None:
    out_file = tmp_path / "document.md"

    write_document(out_file, "title", [], {}, {})

    assert out_file.read_text(encoding="utf-8") == "# title\n"


def test_markdown_whitespace_is_stripped(tmp_path: Path) -> None:
    out_file = tmp_path / "document.md"

    write_document(out_file, "title", [1], {1: "\n\n  padded text  \n\n"}, {})

    assert out_file.read_text(encoding="utf-8") == (
        "# title\n\n## Page 1\n\npadded text\n"
    )


def test_nested_parent_dirs_are_created(tmp_path: Path) -> None:
    out_file = tmp_path / "output" / "invoices" / "Invoice_189339.md"

    write_document(out_file, "Invoice_189339", [1], {1: "content"}, {})

    assert out_file.read_text(encoding="utf-8") == (
        "# Invoice_189339\n\n## Page 1\n\ncontent\n"
    )


def test_no_page_comments_and_no_pages_directory(tmp_path: Path) -> None:
    out_file = tmp_path / "output" / "document.md"

    write_document(out_file, "title", [1, 2], {1: "one"}, {2: "failed"})

    text = out_file.read_text(encoding="utf-8")
    assert "<!--" not in text
    assert not (out_file.parent / "pages").exists()


@pytest.mark.parametrize(
    ("markdown", "levels", "expected"),
    [
        ("# A\n## B\n", 2, "### A\n#### B\n"),
        ("##### X", 2, "###### X"),
        ("###### X", 2, "###### X"),
        ("   # three spaces", 2, "   ### three spaces"),
        ("    # four spaces", 2, "    # four spaces"),
        ("#hashtag", 2, "#hashtag"),
        ("####### seven", 2, "####### seven"),
        ("#", 2, "#"),
        ("Setext\n======", 2, "Setext\n======"),
        ("```\n# not heading\n```\n# real", 2, "```\n# not heading\n```\n### real"),
        ("~~~\n# not heading\n~~~\n# real", 2, "~~~\n# not heading\n~~~\n### real"),
        (
            "````\n# not heading\n```\n# still not heading\n````\n# real",
            2,
            "````\n# not heading\n```\n# still not heading\n````\n### real",
        ),
        ("```\n# not heading", 2, "```\n# not heading"),
        ("", 2, ""),
        ("# no trailing newline", 2, "### no trailing newline"),
        ("# A\n## B", 0, "# A\n## B"),
        ("# A", 1, "## A"),
        (
            "## INVOICE: 189339 | **bold** _text_",
            2,
            "#### INVOICE: 189339 | **bold** _text_",
        ),
        ("item #3", 2, "item #3"),
        (
            "| # | value |\n| - | ----- |\n- # item\n1. # item",
            2,
            "| # | value |\n| - | ----- |\n- # item\n1. # item",
        ),
    ],
)
def test_demote_headings(markdown: str, levels: int, expected: str) -> None:
    assert demote_headings(markdown, levels) == expected


def test_write_document_demotes_page_headings(tmp_path: Path) -> None:
    out_file = tmp_path / "document.md"

    write_document(
        out_file,
        "Invoice_189339",
        [1],
        {1: "# CERTIFIED EQUIPMENT\n## INVOICE: 189339"},
        {},
    )

    assert out_file.read_text(encoding="utf-8") == (
        "# Invoice_189339\n"
        "\n"
        "## Page 1\n"
        "\n"
        "### CERTIFIED EQUIPMENT\n"
        "#### INVOICE: 189339\n"
    )


def test_write_document_title_and_page_headings_are_not_demoted(
    tmp_path: Path,
) -> None:
    out_file = tmp_path / "document.md"

    write_document(out_file, "invoice", [1], {1: "content"}, {})

    assert out_file.read_text(encoding="utf-8") == (
        "# invoice\n"
        "\n"
        "## Page 1\n"
        "\n"
        "content\n"
    )


def test_write_document_failed_error_starting_with_hash_is_not_demoted(
    tmp_path: Path,
) -> None:
    out_file = tmp_path / "document.md"

    write_document(out_file, "invoice", [1], {}, {1: "# boom"})

    assert out_file.read_text(encoding="utf-8") == (
        "# invoice\n"
        "\n"
        "## Page 1 (failed)\n"
        "\n"
        "*Transcription failed: # boom*\n"
    )

