from __future__ import annotations

from pathlib import Path

import pytest

from oculus_pdf.history import HistoryEntry, read_history, should_process, write_history

HEADER = (
    "| File | SHA256 | Pages OK/Total | Pages Skipped | Status | Input Tokens "
    "| Output Tokens | Timestamp (UTC) |"
)
SEPARATOR = "| --- | --- | --- | --- | --- | --- | --- | --- |"
LEGACY_HEADER = (
    "| File | SHA256 | Pages OK/Total | Status | Input Tokens "
    "| Output Tokens | Timestamp (UTC) |"
)
LEGACY_SEPARATOR = "| --- | --- | --- | --- | --- | --- | --- |"


def make_entry(
    name: str,
    sha256: str = "abc123",
    pages_ok: int = 1,
    pages_total: int = 1,
    status: str = "ok",
    input_tokens: int = 10,
    output_tokens: int = 5,
    timestamp: str = "2026-11-13T18:22:05+00:00",
    pages_skipped: int = 0,
) -> HistoryEntry:
    return HistoryEntry(
        name=name,
        sha256=sha256,
        pages_ok=pages_ok,
        pages_total=pages_total,
        status=status,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        timestamp=timestamp,
        pages_skipped=pages_skipped,
    )


def test_write_history_exact_content(tmp_path):
    path = tmp_path / "history.md"
    entries = {
        "Invoice_189339.pdf": HistoryEntry(
            name="Invoice_189339.pdf",
            sha256="3b4f...e2",
            pages_ok=4,
            pages_total=4,
            status="ok",
            input_tokens=12345,
            output_tokens=2345,
            timestamp="2026-11-13T18:22:05+00:00",
            pages_skipped=2,
        ),
        "Receipt.pdf": HistoryEntry(
            name="Receipt.pdf",
            sha256="9a1c...d7",
            pages_ok=1,
            pages_total=2,
            status="failed",
            input_tokens=100,
            output_tokens=20,
            timestamp="2026-11-13T19:00:00+00:00",
            pages_skipped=1,
        ),
    }

    write_history(path, entries)

    assert path.read_text(encoding="utf-8") == (
        "\n".join(
            [
                HEADER,
                SEPARATOR,
                "| Invoice_189339.pdf | 3b4f...e2 | 4/4 | 2 | ok | 12345 | 2345 "
                "| 2026-11-13T18:22:05+00:00 |",
                "| Receipt.pdf | 9a1c...d7 | 1/2 | 1 | failed | 100 | 20 "
                "| 2026-11-13T19:00:00+00:00 |",
            ]
        )
        + "\n"
    )


def test_write_history_sorts_case_insensitive(tmp_path):
    path = tmp_path / "history.md"
    write_history(path, {"b.pdf": make_entry("b.pdf"), "A.pdf": make_entry("A.pdf")})

    text = path.read_text(encoding="utf-8")
    assert text.index("| A.pdf |") < text.index("| b.pdf |")


def test_round_trip(tmp_path):
    path = tmp_path / "history.md"
    entries = {
        "A.pdf": make_entry("A.pdf"),
        "b.pdf": make_entry("b.pdf", status="failed"),
    }

    write_history(path, entries)

    assert read_history(path) == entries


def test_round_trip_preserves_pages_skipped(tmp_path):
    path = tmp_path / "history.md"
    entries = {
        "A.pdf": make_entry("A.pdf", pages_ok=2, pages_total=4, pages_skipped=2),
    }

    write_history(path, entries)

    assert read_history(path) == entries
    assert read_history(path)["A.pdf"].pages_skipped == 2


def test_round_trip_name_with_pipe(tmp_path):
    path = tmp_path / "history.md"
    entries = {"weird|name.pdf": make_entry("weird|name.pdf")}

    write_history(path, entries)

    assert "weird\\|name.pdf" in path.read_text(encoding="utf-8")
    assert read_history(path) == entries


def test_read_history_missing_file(tmp_path):
    assert read_history(tmp_path / "missing.md") == {}


def test_read_history_skips_invalid_rows(tmp_path):
    path = tmp_path / "history.md"
    path.write_text(
        "\n".join(
            [
                HEADER,
                SEPARATOR,
                "| good1.pdf | aa | 1/2 | 0 | ok | 3 | 4 "
                "| 2026-11-13T00:00:00+00:00 |",
                "| short.pdf | aa | 1/2 | 0 | ok | 3 |",
                "| tokens.pdf | aa | 1/1 | 0 | ok | x | 4 "
                "| 2026-11-13T00:00:00+00:00 |",
                "| pages.pdf | aa | 4-4 | 0 | ok | 3 | 4 "
                "| 2026-11-13T00:00:00+00:00 |",
                "| status.pdf | aa | 1/1 | 0 | done | 3 | 4 "
                "| 2026-11-13T00:00:00+00:00 |",
                "| good2.pdf | bb | 2/3 | 1 | failed | 5 | 6 "
                "| 2026-11-13T00:00:00+00:00 |",
                "",
                "junk text",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    entries = read_history(path)

    assert set(entries) == {"good1.pdf", "good2.pdf"}
    assert entries["good1.pdf"] == make_entry(
        "good1.pdf",
        sha256="aa",
        pages_ok=1,
        pages_total=2,
        input_tokens=3,
        output_tokens=4,
        timestamp="2026-11-13T00:00:00+00:00",
    )
    assert entries["good2.pdf"].status == "failed"


def test_read_history_skips_invalid_pages_skipped(tmp_path):
    path = tmp_path / "history.md"
    path.write_text(
        "\n".join(
            [
                HEADER,
                SEPARATOR,
                "| good.pdf | aa | 1/1 | 0 | ok | 3 | 4 "
                "| 2026-11-13T00:00:00+00:00 |",
                "| text.pdf | aa | 1/1 | x | ok | 3 | 4 "
                "| 2026-11-13T00:00:00+00:00 |",
                "| negative.pdf | aa | 1/1 | -1 | ok | 3 | 4 "
                "| 2026-11-13T00:00:00+00:00 |",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    entries = read_history(path)

    assert set(entries) == {"good.pdf"}


def test_read_history_legacy_format(tmp_path):
    path = tmp_path / "history.md"
    path.write_text(
        "\n".join(
            [
                LEGACY_HEADER,
                LEGACY_SEPARATOR,
                "| old1.pdf | aa | 1/2 | ok | 3 | 4 "
                "| 2026-11-13T00:00:00+00:00 |",
                "| old2.pdf | bb | 2/2 | failed | 5 | 6 "
                "| 2026-11-13T01:00:00+00:00 |",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    entries = read_history(path)

    assert set(entries) == {"old1.pdf", "old2.pdf"}
    assert entries["old1.pdf"] == make_entry(
        "old1.pdf",
        sha256="aa",
        pages_ok=1,
        pages_total=2,
        input_tokens=3,
        output_tokens=4,
        timestamp="2026-11-13T00:00:00+00:00",
    )
    assert entries["old1.pdf"].pages_skipped == 0
    assert entries["old2.pdf"] == make_entry(
        "old2.pdf",
        sha256="bb",
        pages_ok=2,
        pages_total=2,
        status="failed",
        input_tokens=5,
        output_tokens=6,
        timestamp="2026-11-13T01:00:00+00:00",
    )


def test_read_history_mixed_legacy_and_new_rows(tmp_path):
    path = tmp_path / "history.md"
    path.write_text(
        "\n".join(
            [
                HEADER,
                SEPARATOR,
                "| old.pdf | aa | 1/2 | ok | 3 | 4 "
                "| 2026-11-13T00:00:00+00:00 |",
                "| new.pdf | bb | 2/2 | 2 | ok | 5 | 6 "
                "| 2026-11-13T01:00:00+00:00 |",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    entries = read_history(path)

    assert set(entries) == {"old.pdf", "new.pdf"}
    assert entries["old.pdf"].pages_skipped == 0
    assert entries["new.pdf"].pages_skipped == 2
    assert entries["new.pdf"].input_tokens == 5


def test_write_history_upgrades_legacy_rows(tmp_path):
    path = tmp_path / "history.md"
    path.write_text(
        "\n".join(
            [
                LEGACY_HEADER,
                LEGACY_SEPARATOR,
                "| old.pdf | aa | 1/2 | ok | 3 | 4 "
                "| 2026-11-13T00:00:00+00:00 |",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    write_history(path, read_history(path))

    assert path.read_text(encoding="utf-8") == (
        "\n".join(
            [
                HEADER,
                SEPARATOR,
                "| old.pdf | aa | 1/2 | 0 | ok | 3 | 4 "
                "| 2026-11-13T00:00:00+00:00 |",
            ]
        )
        + "\n"
    )


def test_write_history_creates_parents_and_leaves_no_tmp(tmp_path):
    path = tmp_path / "nested" / "deeper" / "history.md"

    write_history(path, {"a.pdf": make_entry("a.pdf")})

    assert path.exists()
    assert not Path(f"{path}.tmp").exists()


def test_write_history_empty(tmp_path):
    path = tmp_path / "history.md"

    write_history(path, {})

    assert path.read_text(encoding="utf-8") == HEADER + "\n" + SEPARATOR + "\n"


def test_history_entry_default_pages_skipped():
    entry = HistoryEntry(
        name="a.pdf",
        sha256="abc123",
        pages_ok=1,
        pages_total=1,
        status="ok",
        input_tokens=10,
        output_tokens=5,
        timestamp="2026-11-13T18:22:05+00:00",
    )

    assert entry.pages_skipped == 0


@pytest.mark.parametrize(
    ("existing", "sha256", "expected"),
    [
        (None, "x", True),
        (make_entry("a.pdf", sha256="x", status="ok"), "x", False),
        (make_entry("a.pdf", sha256="x", status="failed"), "x", True),
        (make_entry("a.pdf", sha256="y", status="ok"), "x", True),
        (make_entry("a.pdf", sha256="y", status="failed"), "x", True),
    ],
)
def test_should_process(existing, sha256, expected):
    assert should_process(existing, sha256) is expected
