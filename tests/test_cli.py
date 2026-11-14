from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import pymupdf
import pytest

from oculus_pdf import cli, discover, history, render, transcribe

LONG_LEASE_TEXT = "The Lessee shall indemnify the Lessor hereby " * 100


def write_pdf(path: Path, pages: int, tag: str = "v1") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as doc:
        for number in range(1, pages + 1):
            page = doc.new_page()
            page.insert_text((72, 72), f"{tag} {path.stem} page {number}")
        doc.save(path)
    return path


def run_cli(input_dir: Path, out_dir: Path, *extra: str) -> int:
    return cli.main(
        ["--input", str(input_dir), "--out", str(out_dir), *extra]
    )


@pytest.fixture(autouse=True)
def fake_opencode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/opencode")


@pytest.fixture
def env(tmp_path: Path) -> tuple[Path, Path]:
    input_dir = tmp_path / "input"
    (input_dir / "invoices").mkdir(parents=True)
    (input_dir / "statements").mkdir(parents=True)
    return input_dir, tmp_path / "output"


class Harness:
    def __init__(self) -> None:
        self.pages_by_png: dict[bytes, tuple[str, int]] = {}
        self.render_order: list[tuple[str, int]] = []
        self.calls: list[tuple[str, int]] = []
        self.failures: dict[tuple[str, int], str] = {}


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    state = Harness()
    real_render_pages = render.render_pages

    def recording_render_pages(pdf_path: Path, pages: list[int], dpi: int):
        for page, png in real_render_pages(pdf_path, pages, dpi):
            key = (Path(pdf_path).name, page)
            state.pages_by_png[png] = key
            state.render_order.append(key)
            yield page, png

    def stub(model, png, retries=2, sleep=None, run=None):
        key = state.pages_by_png[png]
        state.calls.append(key)
        if key in state.failures:
            raise RuntimeError(state.failures[key])
        name, page = key
        return transcribe.PageResult(
            markdown=f"{name} page {page}",
            input_tokens=100 * page,
            output_tokens=10 * page,
        )

    monkeypatch.setattr(cli.render, "render_pages", recording_render_pages)
    monkeypatch.setattr(cli.transcribe, "transcribe_page", stub)
    return state


def test_fresh_run_writes_documents_and_history(
    env: tuple[Path, Path], harness: Harness
) -> None:
    input_dir, out_dir = env
    write_pdf(input_dir / "invoices" / "a.pdf", 3)
    write_pdf(input_dir / "invoices" / "b.pdf", 2)
    write_pdf(input_dir / "statements" / "c.pdf", 1)

    assert run_cli(input_dir, out_dir) == 0

    document = (out_dir / "invoices" / "a.md").read_text(encoding="utf-8")
    assert document == (
        "# a\n"
        "\n"
        "## Page 1\n"
        "\n"
        "a.pdf page 1\n"
        "\n"
        "## Page 2\n"
        "\n"
        "a.pdf page 2\n"
        "\n"
        "## Page 3\n"
        "\n"
        "a.pdf page 3\n"
    )
    assert "<!--" not in document
    assert (out_dir / "invoices" / "b.md").is_file()
    assert (out_dir / "statements" / "c.md").is_file()
    assert list(out_dir.rglob("run.json")) == []
    assert list(out_dir.rglob("pages")) == []

    invoices_path = out_dir / "invoices" / "history.md"
    invoices = history.read_history(invoices_path)
    assert set(invoices) == {"a.pdf", "b.pdf"}
    assert all(entry.status == "ok" for entry in invoices.values())
    a = invoices["a.pdf"]
    assert (a.pages_ok, a.pages_total) == (3, 3)
    assert (a.input_tokens, a.output_tokens) == (600, 60)
    assert re.fullmatch(r"[0-9a-f]{64}", a.sha256)
    assert a.sha256 == discover.sha256_file(input_dir / "invoices" / "a.pdf")
    b = invoices["b.pdf"]
    assert (b.pages_ok, b.pages_total) == (2, 2)
    assert (b.input_tokens, b.output_tokens) == (300, 30)

    rows = [
        line
        for line in invoices_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("| ") and " | ok | " in line
    ]
    assert len(rows) == 2

    statements = history.read_history(
        out_dir / "statements" / "history.md"
    )
    assert set(statements) == {"c.pdf"}
    c = statements["c.pdf"]
    assert (c.pages_ok, c.pages_total, c.status) == (1, 1, "ok")
    assert (c.input_tokens, c.output_tokens) == (100, 10)


def test_rerun_skips_unchanged_documents(
    env: tuple[Path, Path], harness: Harness, capsys: pytest.CaptureFixture
) -> None:
    input_dir, out_dir = env
    write_pdf(input_dir / "invoices" / "a.pdf", 3)
    write_pdf(input_dir / "invoices" / "b.pdf", 2)
    write_pdf(input_dir / "statements" / "c.pdf", 1)
    assert run_cli(input_dir, out_dir) == 0

    invoices_path = out_dir / "invoices" / "history.md"
    statements_path = out_dir / "statements" / "history.md"
    before = {
        invoices_path: invoices_path.read_bytes(),
        statements_path: statements_path.read_bytes(),
    }
    harness.calls.clear()
    capsys.readouterr()

    assert run_cli(input_dir, out_dir) == 0

    assert harness.calls == []
    assert invoices_path.read_bytes() == before[invoices_path]
    assert statements_path.read_bytes() == before[statements_path]
    stdout = capsys.readouterr().out
    assert "skip: invoices/a.pdf (unchanged)" in stdout
    assert "skip: invoices/b.pdf (unchanged)" in stdout
    assert "skip: statements/c.pdf (unchanged)" in stdout
    assert "processed: 0, skipped: 3, failed: 0" in stdout


def test_new_document_is_the_only_one_processed(
    env: tuple[Path, Path], harness: Harness
) -> None:
    input_dir, out_dir = env
    write_pdf(input_dir / "invoices" / "a.pdf", 3)
    write_pdf(input_dir / "invoices" / "b.pdf", 2)
    write_pdf(input_dir / "statements" / "c.pdf", 1)
    assert run_cli(input_dir, out_dir) == 0

    invoices_path = out_dir / "invoices" / "history.md"
    before_lines = invoices_path.read_text(encoding="utf-8").splitlines()

    write_pdf(input_dir / "invoices" / "d.pdf", 2)
    harness.calls.clear()

    assert run_cli(input_dir, out_dir) == 0

    assert sorted(harness.calls) == [("d.pdf", 1), ("d.pdf", 2)]
    after_lines = invoices_path.read_text(encoding="utf-8").splitlines()
    assert after_lines[: len(before_lines)] == before_lines
    assert len(after_lines) == len(before_lines) + 1
    entries = history.read_history(invoices_path)
    assert set(entries) == {"a.pdf", "b.pdf", "d.pdf"}
    d = entries["d.pdf"]
    assert (d.pages_ok, d.pages_total, d.status) == (2, 2, "ok")
    assert (d.input_tokens, d.output_tokens) == (300, 30)


def test_failed_document_is_reprocessed_in_full(
    env: tuple[Path, Path], harness: Harness
) -> None:
    input_dir, out_dir = env
    write_pdf(input_dir / "invoices" / "a.pdf", 3)
    write_pdf(input_dir / "invoices" / "b.pdf", 2)
    write_pdf(input_dir / "statements" / "c.pdf", 1)
    harness.failures[("a.pdf", 2)] = "boom on page 2"

    assert run_cli(input_dir, out_dir) == 1

    invoices_path = out_dir / "invoices" / "history.md"
    entries = history.read_history(invoices_path)
    a = entries["a.pdf"]
    assert (a.pages_ok, a.pages_total, a.status) == (2, 3, "failed")
    assert (a.input_tokens, a.output_tokens) == (400, 40)
    b = entries["b.pdf"]
    assert b.status == "ok"
    document = (out_dir / "invoices" / "a.md").read_text(encoding="utf-8")
    assert "## Page 2 (failed)" in document
    assert "boom on page 2" in document

    harness.failures.clear()
    harness.calls.clear()

    assert run_cli(input_dir, out_dir) == 0

    assert sorted(harness.calls) == [
        ("a.pdf", 1),
        ("a.pdf", 2),
        ("a.pdf", 3),
    ]
    entries = history.read_history(invoices_path)
    assert (entries["a.pdf"].pages_ok, entries["a.pdf"].pages_total) == (3, 3)
    assert entries["a.pdf"].status == "ok"
    assert (entries["a.pdf"].input_tokens, entries["a.pdf"].output_tokens) == (
        600,
        60,
    )
    assert entries["b.pdf"] == b
    document = (out_dir / "invoices" / "a.md").read_text(encoding="utf-8")
    assert "## Page 2 (failed)" not in document


def test_changed_pdf_is_reprocessed_in_place(
    env: tuple[Path, Path], harness: Harness
) -> None:
    input_dir, out_dir = env
    pdf = write_pdf(input_dir / "invoices" / "a.pdf", 3)
    write_pdf(input_dir / "invoices" / "b.pdf", 2)
    write_pdf(input_dir / "statements" / "c.pdf", 1)
    assert run_cli(input_dir, out_dir) == 0

    invoices_path = out_dir / "invoices" / "history.md"
    before = history.read_history(invoices_path)
    write_pdf(pdf, 2, tag="changed")
    harness.calls.clear()

    assert run_cli(input_dir, out_dir) == 0

    assert sorted(harness.calls) == [("a.pdf", 1), ("a.pdf", 2)]
    entries = history.read_history(invoices_path)
    assert set(entries) == {"a.pdf", "b.pdf"}
    assert entries["a.pdf"].sha256 != before["a.pdf"].sha256
    assert entries["a.pdf"].sha256 == discover.sha256_file(pdf)
    assert (entries["a.pdf"].pages_ok, entries["a.pdf"].pages_total) == (2, 2)
    assert (entries["a.pdf"].input_tokens, entries["a.pdf"].output_tokens) == (
        300,
        30,
    )
    assert entries["b.pdf"] == before["b.pdf"]
    assert len(history.read_history(invoices_path)) == 2

    document = (out_dir / "invoices" / "a.md").read_text(encoding="utf-8")
    assert "## Page 2" in document
    assert "## Page 3" not in document


def test_force_reprocesses_everything(
    env: tuple[Path, Path],
    harness: Harness,
    capsys: pytest.CaptureFixture,
) -> None:
    input_dir, out_dir = env
    write_pdf(input_dir / "invoices" / "a.pdf", 2)
    write_pdf(input_dir / "invoices" / "b.pdf", 1)
    write_pdf(input_dir / "statements" / "c.pdf", 1)
    assert run_cli(input_dir, out_dir) == 0

    harness.calls.clear()
    capsys.readouterr()

    assert run_cli(input_dir, out_dir, "--force") == 0

    assert sorted(harness.calls) == sorted(
        [("a.pdf", 1), ("a.pdf", 2), ("b.pdf", 1), ("c.pdf", 1)]
    )
    stdout = capsys.readouterr().out
    assert "skip:" not in stdout
    assert "processed: 3, skipped: 0, failed: 0" in stdout


def test_corrupt_pdf_fails_and_is_retried(
    env: tuple[Path, Path],
    harness: Harness,
    capsys: pytest.CaptureFixture,
) -> None:
    input_dir, out_dir = env
    write_pdf(input_dir / "invoices" / "a.pdf", 2)
    write_pdf(input_dir / "statements" / "c.pdf", 1)
    bad = input_dir / "invoices" / "bad.pdf"
    bad.write_bytes(b"this is not a pdf")

    assert run_cli(input_dir, out_dir) == 1

    invoices_path = out_dir / "invoices" / "history.md"
    entries = history.read_history(invoices_path)
    assert (entries["bad.pdf"].pages_ok, entries["bad.pdf"].pages_total) == (0, 0)
    assert entries["bad.pdf"].status == "failed"
    assert entries["bad.pdf"].sha256 == discover.sha256_file(bad)
    assert not (out_dir / "invoices" / "bad.md").exists()
    assert entries["a.pdf"].status == "ok"
    assert (
        history.read_history(out_dir / "statements" / "history.md")["c.pdf"]
        .status
        == "ok"
    )
    stdout = capsys.readouterr().out
    assert "processed: invoices/bad.pdf (0/0 pages, failed, 0 skipped)" in stdout

    harness.calls.clear()
    capsys.readouterr()

    assert run_cli(input_dir, out_dir) == 1

    stdout = capsys.readouterr().out
    assert "processed: invoices/bad.pdf (0/0 pages, failed, 0 skipped)" in stdout
    assert "skip: invoices/bad.pdf" not in stdout
    assert "skip: invoices/a.pdf" in stdout
    assert "skip: statements/c.pdf" in stdout
    assert len(history.read_history(invoices_path)) == 2


def test_missing_opencode_exits_2_without_output(
    env: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    input_dir, out_dir = env
    write_pdf(input_dir / "invoices" / "a.pdf", 1)
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)

    assert run_cli(input_dir, out_dir) == 2

    assert "error: opencode not found on PATH" in capsys.readouterr().err
    assert not out_dir.exists()


def test_missing_input_exits_2_without_output(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    out_dir = tmp_path / "out"
    missing = tmp_path / "missing"

    assert cli.main(["--input", str(missing), "--out", str(out_dir)]) == 2

    assert (
        f"error: input directory not found: {missing}"
        in capsys.readouterr().err
    )
    assert not out_dir.exists()


def test_missing_category_directory_is_fine(
    tmp_path: Path, harness: Harness
) -> None:
    input_dir = tmp_path / "input"
    (input_dir / "invoices").mkdir(parents=True)
    write_pdf(input_dir / "invoices" / "a.pdf", 1)
    out_dir = tmp_path / "out"

    assert run_cli(input_dir, out_dir) == 0

    assert (out_dir / "invoices" / "a.md").is_file()
    assert (out_dir / "invoices" / "history.md").is_file()
    assert not (out_dir / "statements").exists()


def test_no_documents_prints_nothing_to_process(
    tmp_path: Path, harness: Harness, capsys: pytest.CaptureFixture
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    out_dir = tmp_path / "out"

    assert run_cli(input_dir, out_dir) == 0

    assert "nothing to process" in capsys.readouterr().out
    assert not out_dir.exists()


def test_parser_defaults() -> None:
    args = cli.build_parser().parse_args([])

    assert args.input == "./input"
    assert args.out == "./output"
    assert args.dpi == 150
    assert args.model == "opencode/deepseek-v4.1-flash-free#high"
    assert args.concurrency == 4
    assert args.force is False


def test_pages_option_is_rejected() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.build_parser().parse_args(["--pages", "1-2"])

    assert excinfo.value.code == 2


def test_positional_pdf_is_rejected() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.build_parser().parse_args(["x.pdf"])

    assert excinfo.value.code == 2


def test_in_flight_work_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_dir = tmp_path / "input"
    (input_dir / "invoices").mkdir(parents=True)
    write_pdf(input_dir / "invoices" / "many.pdf", 8)

    rendered = 0
    finished = 0
    max_in_flight = 0
    lock = threading.Lock()
    real_render_pages = render.render_pages

    def tracking_render_pages(pdf_path: Path, pages: list[int], dpi: int):
        nonlocal rendered, max_in_flight
        for page, png in real_render_pages(pdf_path, pages, dpi):
            rendered += 1
            max_in_flight = max(max_in_flight, rendered - finished)
            yield page, png

    def stub(model, png, retries=2, sleep=None, run=None):
        nonlocal finished
        time.sleep(0.01)
        with lock:
            finished += 1
        return transcribe.PageResult(
            markdown="page", input_tokens=1, output_tokens=1
        )

    monkeypatch.setattr(cli.render, "render_pages", tracking_render_pages)
    monkeypatch.setattr(cli.transcribe, "transcribe_page", stub)

    assert (
        run_cli(
            input_dir,
            tmp_path / "output",
            "--concurrency",
            "1",
            "--dpi",
            "10",
        )
        == 0
    )
    assert max_in_flight <= 3


def test_documents_are_processed_in_order(
    env: tuple[Path, Path], harness: Harness
) -> None:
    input_dir, out_dir = env
    write_pdf(input_dir / "invoices" / "b.pdf", 1)
    write_pdf(input_dir / "invoices" / "A.pdf", 1)
    write_pdf(input_dir / "statements" / "c.pdf", 1)

    assert run_cli(input_dir, out_dir) == 0

    expected = [("A.pdf", 1), ("b.pdf", 1), ("c.pdf", 1)]
    assert harness.render_order == expected
    assert harness.calls == expected


def test_contract_page_is_skipped(
    env: tuple[Path, Path],
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    input_dir, out_dir = env
    write_pdf(input_dir / "invoices" / "a.pdf", 3)
    monkeypatch.setattr(
        cli.render,
        "page_text",
        lambda pdf_path, pages: {1: "short text", 2: LONG_LEASE_TEXT},
    )

    assert run_cli(input_dir, out_dir) == 0

    assert harness.render_order == [("a.pdf", 1), ("a.pdf", 3)]
    assert harness.calls == [("a.pdf", 1), ("a.pdf", 3)]
    document = (out_dir / "invoices" / "a.md").read_text(encoding="utf-8")
    assert document == (
        "# a\n"
        "\n"
        "## Page 1\n"
        "\n"
        "a.pdf page 1\n"
        "\n"
        "## Page 3\n"
        "\n"
        "a.pdf page 3\n"
    )
    entries = history.read_history(out_dir / "invoices" / "history.md")
    a = entries["a.pdf"]
    assert (a.pages_ok, a.pages_total, a.pages_skipped, a.status) == (
        2,
        2,
        1,
        "ok",
    )
    assert (a.input_tokens, a.output_tokens) == (400, 40)
    stdout = capsys.readouterr().out
    assert "processed: invoices/a.pdf (2/2 pages, ok, 1 skipped)" in stdout


def test_all_contract_pages_are_skipped(
    env: tuple[Path, Path],
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    input_dir, out_dir = env
    write_pdf(input_dir / "invoices" / "a.pdf", 2)
    monkeypatch.setattr(
        cli.render,
        "page_text",
        lambda pdf_path, pages: {1: LONG_LEASE_TEXT, 2: LONG_LEASE_TEXT},
    )

    assert run_cli(input_dir, out_dir) == 0

    assert harness.render_order == []
    assert harness.calls == []
    document = (out_dir / "invoices" / "a.md").read_text(encoding="utf-8")
    assert document == "# a\n"
    entries = history.read_history(out_dir / "invoices" / "history.md")
    a = entries["a.pdf"]
    assert (a.pages_ok, a.pages_total, a.pages_skipped, a.status) == (
        0,
        0,
        2,
        "ok",
    )
    assert (a.input_tokens, a.output_tokens) == (0, 0)
    stdout = capsys.readouterr().out
    assert "processed: invoices/a.pdf (0/0 pages, ok, 2 skipped)" in stdout


def test_page_without_text_layer_is_not_skipped(
    env: tuple[Path, Path], harness: Harness
) -> None:
    input_dir, out_dir = env
    path = input_dir / "invoices" / "blank.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as doc:
        doc.new_page()
        doc.save(path)

    assert run_cli(input_dir, out_dir) == 0

    assert harness.render_order == [("blank.pdf", 1)]
    assert harness.calls == [("blank.pdf", 1)]
    document = (out_dir / "invoices" / "blank.md").read_text(
        encoding="utf-8"
    )
    assert document == "# blank\n\n## Page 1\n\nblank.pdf page 1\n"
    entries = history.read_history(out_dir / "invoices" / "history.md")
    entry = entries["blank.pdf"]
    assert (
        entry.pages_ok,
        entry.pages_total,
        entry.pages_skipped,
        entry.status,
    ) == (1, 1, 0, "ok")


def test_page_text_failure_skips_nothing(
    env: tuple[Path, Path],
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir, out_dir = env
    write_pdf(input_dir / "invoices" / "a.pdf", 2)

    def failing_page_text(pdf_path: Path, pages: list[int]):
        raise RuntimeError("no text layer")

    monkeypatch.setattr(cli.render, "page_text", failing_page_text)

    assert run_cli(input_dir, out_dir) == 0

    assert harness.render_order == [("a.pdf", 1), ("a.pdf", 2)]
    assert harness.calls == [("a.pdf", 1), ("a.pdf", 2)]
    entries = history.read_history(out_dir / "invoices" / "history.md")
    a = entries["a.pdf"]
    assert (a.pages_ok, a.pages_total, a.pages_skipped, a.status) == (
        2,
        2,
        0,
        "ok",
    )


def test_legacy_seven_column_history(
    env: tuple[Path, Path],
    harness: Harness,
    capsys: pytest.CaptureFixture,
) -> None:
    input_dir, out_dir = env
    a = write_pdf(input_dir / "invoices" / "a.pdf", 2)
    b = write_pdf(input_dir / "invoices" / "b.pdf", 2)
    history_path = out_dir / "invoices" / "history.md"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        "| File | SHA256 | Pages OK/Total | Status | Input Tokens | "
        "Output Tokens | Timestamp (UTC) |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        f"| a.pdf | {discover.sha256_file(a)} | 2/2 | ok | 111 | 22 "
        "| 2026-01-01T00:00:00+00:00 |\n"
        f"| b.pdf | {discover.sha256_file(b)} | 1/2 | failed | 33 | 4 "
        "| 2026-01-01T00:00:00+00:00 |\n",
        encoding="utf-8",
    )

    assert run_cli(input_dir, out_dir) == 0

    assert harness.calls == [("b.pdf", 1), ("b.pdf", 2)]
    stdout = capsys.readouterr().out
    assert "skip: invoices/a.pdf (unchanged)" in stdout
    assert "processed: invoices/b.pdf (2/2 pages, ok, 0 skipped)" in stdout

    lines = history_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == history.HEADER
    assert lines[1] == history.SEPARATOR
    assert all(line.count("|") == 9 for line in lines[2:])
    entries = history.read_history(history_path)
    assert (
        entries["a.pdf"].pages_skipped,
        entries["a.pdf"].input_tokens,
        entries["a.pdf"].output_tokens,
    ) == (0, 111, 22)
    assert (
        entries["b.pdf"].pages_ok,
        entries["b.pdf"].pages_total,
        entries["b.pdf"].status,
    ) == (2, 2, "ok")


def test_headings_are_demoted_end_to_end(
    env: tuple[Path, Path],
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir, out_dir = env
    write_pdf(input_dir / "invoices" / "a.pdf", 1)

    def stub(model, png, retries=2, sleep=None, run=None):
        return transcribe.PageResult(
            markdown="# X\n## Y", input_tokens=1, output_tokens=1
        )

    monkeypatch.setattr(cli.transcribe, "transcribe_page", stub)

    assert run_cli(input_dir, out_dir) == 0

    document = (out_dir / "invoices" / "a.md").read_text(encoding="utf-8")
    assert document == "# a\n\n## Page 1\n\n### X\n#### Y\n"


def test_rerun_after_contract_page_is_skipped_is_unchanged(
    env: tuple[Path, Path],
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    input_dir, out_dir = env
    write_pdf(input_dir / "invoices" / "a.pdf", 3)
    monkeypatch.setattr(
        cli.render,
        "page_text",
        lambda pdf_path, pages: {1: "short text", 2: LONG_LEASE_TEXT},
    )
    assert run_cli(input_dir, out_dir) == 0

    history_path = out_dir / "invoices" / "history.md"
    document_path = out_dir / "invoices" / "a.md"
    before_history = history_path.read_bytes()
    before_document = document_path.read_bytes()
    harness.calls.clear()
    harness.render_order.clear()
    capsys.readouterr()

    assert run_cli(input_dir, out_dir) == 0

    assert harness.calls == []
    assert harness.render_order == []
    assert history_path.read_bytes() == before_history
    assert document_path.read_bytes() == before_document
    stdout = capsys.readouterr().out
    assert "skip: invoices/a.pdf (unchanged)" in stdout
    assert "processed: 0, skipped: 1, failed: 0" in stdout


def test_failed_page_on_document_with_skipped_contract_page(
    env: tuple[Path, Path],
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    input_dir, out_dir = env
    write_pdf(input_dir / "invoices" / "a.pdf", 3)
    monkeypatch.setattr(
        cli.render,
        "page_text",
        lambda pdf_path, pages: {1: "short text", 2: LONG_LEASE_TEXT},
    )
    harness.failures[("a.pdf", 3)] = "boom on page 3"

    assert run_cli(input_dir, out_dir) == 1

    assert harness.render_order == [("a.pdf", 1), ("a.pdf", 3)]
    assert harness.calls == [("a.pdf", 1), ("a.pdf", 3)]
    entries = history.read_history(out_dir / "invoices" / "history.md")
    a = entries["a.pdf"]
    assert (a.pages_ok, a.pages_total, a.pages_skipped, a.status) == (
        1,
        2,
        1,
        "failed",
    )
    assert (a.input_tokens, a.output_tokens) == (100, 10)
    document = (out_dir / "invoices" / "a.md").read_text(encoding="utf-8")
    assert "## Page 2" not in document
    assert "## Page 3 (failed)" in document
    assert "boom on page 3" in document
    stdout = capsys.readouterr().out
    assert "processed: invoices/a.pdf (1/2 pages, failed, 1 skipped)" in stdout


def test_real_contract_text_page_is_skipped(
    env: tuple[Path, Path],
    harness: Harness,
    capsys: pytest.CaptureFixture,
) -> None:
    input_dir, out_dir = env
    path = input_dir / "invoices" / "lease.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as doc:
        page = doc.new_page(width=1200, height=1600)
        page.insert_textbox(
            pymupdf.Rect(40, 40, 1160, 1560),
            LONG_LEASE_TEXT,
            fontsize=8,
        )
        doc.save(path)

    with pymupdf.open(path) as doc:
        text = doc.load_page(0).get_text()
    assert len(text.split()) >= 400
    assert "lessee" in text.lower()
    assert "lessor" in text.lower()
    assert "indemnify" in text.lower()

    assert run_cli(input_dir, out_dir) == 0

    assert harness.render_order == []
    assert harness.calls == []
    document = (out_dir / "invoices" / "lease.md").read_text(
        encoding="utf-8"
    )
    assert document == "# lease\n"
    entries = history.read_history(out_dir / "invoices" / "history.md")
    entry = entries["lease.pdf"]
    assert (
        entry.pages_ok,
        entry.pages_total,
        entry.pages_skipped,
        entry.status,
    ) == (0, 0, 1, "ok")
    stdout = capsys.readouterr().out
    assert "processed: invoices/lease.pdf (0/0 pages, ok, 1 skipped)" in stdout
