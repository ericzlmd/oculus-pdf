from __future__ import annotations

import argparse
import shutil
import sys
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ThreadPoolExecutor,
    as_completed,
    wait,
)
from datetime import datetime, timezone
from pathlib import Path

from oculus_pdf import contract, discover, history, output, render, transcribe


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oculus-pdf",
        description=(
            "Transcribe invoice and statement PDFs to Markdown using a vision "
            "model via opencode."
        ),
    )
    parser.add_argument(
        "--input",
        default="./input",
        help=(
            "input directory containing invoices/ and statements/ "
            "(default: ./input)"
        ),
    )
    parser.add_argument(
        "--out",
        default="./output",
        help="output directory (default: ./output)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=150,
        help="render resolution in DPI (default: 150)",
    )
    parser.add_argument(
        "--model",
        default="opencode/deepseek-v4.1-flash-free#high",
        help=(
            "model as provider/model[#variant], run through opencode "
            "(default: opencode/deepseek-v4.1-flash-free#high)"
        ),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="number of parallel transcription requests (default: 4)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="ignore history and reprocess every document",
    )
    return parser


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _process_document(
    doc: discover.Document,
    out_dir: Path,
    sha256: str,
    model: str,
    dpi: int,
    concurrency: int,
) -> history.HistoryEntry:
    try:
        total = render.page_count(doc.path)
    except Exception:
        return history.HistoryEntry(
            name=doc.name,
            sha256=sha256,
            pages_ok=0,
            pages_total=0,
            status="failed",
            input_tokens=0,
            output_tokens=0,
            timestamp=_now(),
        )

    pages = list(range(1, total + 1))
    try:
        texts = render.page_text(doc.path, pages)
    except Exception:
        texts = {}
    skipped_pages = [
        p for p in pages if contract.is_contract_page(texts.get(p, ""))
    ]
    send_pages = [p for p in pages if p not in skipped_pages]
    results: dict[int, transcribe.PageResult] = {}
    markdown_by_page: dict[int, str] = {}
    errors: dict[int, str] = {}

    max_pending = concurrency * 2

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures: dict[Future, int] = {}

        def consume(future: Future) -> None:
            page = futures.pop(future)
            try:
                result = future.result()
            except Exception as exc:
                errors[page] = str(exc) or type(exc).__name__
                return
            results[page] = result
            markdown_by_page[page] = result.markdown

        try:
            for page, png in render.render_pages(doc.path, send_pages, dpi):
                if len(futures) >= max_pending:
                    done, _ = wait(futures, return_when=FIRST_COMPLETED)
                    for future in done:
                        consume(future)
                futures[
                    pool.submit(transcribe.transcribe_page, model, png)
                ] = page
        except Exception as exc:
            for future in as_completed(futures):
                consume(future)
            message = f"render failed: {exc}"
            for page in send_pages:
                if page not in markdown_by_page and page not in errors:
                    errors[page] = message

        for future in as_completed(futures):
            consume(future)

    out_file = out_dir / f"{doc.path.stem}.md"
    output.write_document(
        out_file, doc.path.stem, send_pages, markdown_by_page, errors
    )

    return history.HistoryEntry(
        name=doc.name,
        sha256=sha256,
        pages_ok=len(markdown_by_page),
        pages_total=len(send_pages),
        pages_skipped=len(skipped_pages),
        status=(
            "ok" if len(markdown_by_page) == len(send_pages) else "failed"
        ),
        input_tokens=sum(
            result.input_tokens for result in results.values()
        ),
        output_tokens=sum(
            result.output_tokens for result in results.values()
        ),
        timestamp=_now(),
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if shutil.which("opencode") is None:
        print("error: opencode not found on PATH", file=sys.stderr)
        return 2

    try:
        documents = discover.discover_documents(Path(args.input))
    except FileNotFoundError:
        print(
            f"error: input directory not found: {args.input}",
            file=sys.stderr,
        )
        return 2

    processed = 0
    skipped = 0
    failed = 0

    for category, docs in documents.items():
        history_path = Path(args.out) / category / "history.md"
        entries = history.read_history(history_path)

        for doc in docs:
            sha256 = discover.sha256_file(doc.path)
            if not args.force and not history.should_process(
                entries.get(doc.name), sha256
            ):
                print(f"skip: {category}/{doc.name} (unchanged)")
                skipped += 1
                continue

            entry = _process_document(
                doc,
                Path(args.out) / category,
                sha256,
                args.model,
                args.dpi,
                args.concurrency,
            )
            entries[doc.name] = entry
            history.write_history(history_path, entries)
            print(
                f"processed: {category}/{doc.name} "
                f"({entry.pages_ok}/{entry.pages_total} pages, "
                f"{entry.status}, {entry.pages_skipped} skipped)"
            )
            processed += 1
            if entry.status == "failed":
                failed += 1

    if not any(documents.values()):
        print("nothing to process")
    else:
        print(f"processed: {processed}, skipped: {skipped}, failed: {failed}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
