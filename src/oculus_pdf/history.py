from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

HEADER = (
    "| File | SHA256 | Pages OK/Total | Pages Skipped | Status | Input Tokens "
    "| Output Tokens | Timestamp (UTC) |"
)
SEPARATOR = "| --- | --- | --- | --- | --- | --- | --- | --- |"
CELL_SEPARATOR = re.compile(r"(?<!\\)\|")
PAGES_PATTERN = re.compile(r"\d+/\d+")
SKIPPED_PATTERN = re.compile(r"\d+")


@dataclass(frozen=True)
class HistoryEntry:
    name: str
    sha256: str
    pages_ok: int
    pages_total: int
    status: str
    input_tokens: int
    output_tokens: int
    timestamp: str
    pages_skipped: int = 0


def _cells(line: str) -> list[str]:
    parts = CELL_SEPARATOR.split(line)
    if parts and not parts[0].strip():
        parts = parts[1:]
    if parts and not parts[-1].strip():
        parts = parts[:-1]
    return [part.strip() for part in parts]


def read_history(history_path: Path) -> dict[str, HistoryEntry]:
    if not history_path.exists():
        return {}

    entries: dict[str, HistoryEntry] = {}
    for line in history_path.read_text(encoding="utf-8").splitlines():
        cells = _cells(line)
        if len(cells) not in (7, 8) or not all(cells):
            continue
        if len(cells) == 8:
            name, sha256, pages, skipped, status, in_tokens, out_tokens, timestamp = cells
        else:
            name, sha256, pages, status, in_tokens, out_tokens, timestamp = cells
            skipped = "0"
        if PAGES_PATTERN.fullmatch(pages) is None:
            continue
        if SKIPPED_PATTERN.fullmatch(skipped) is None:
            continue
        if status not in ("ok", "failed"):
            continue
        try:
            pages_ok, pages_total = (int(part) for part in pages.split("/"))
            pages_skipped = int(skipped)
            input_tokens = int(in_tokens)
            output_tokens = int(out_tokens)
        except ValueError:
            continue
        name = name.replace("\\|", "|")
        entries[name] = HistoryEntry(
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
    return entries


def should_process(entry: HistoryEntry | None, sha256: str) -> bool:
    return entry is None or entry.sha256 != sha256 or entry.status != "ok"


def write_history(history_path: Path, entries: dict[str, HistoryEntry]) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [HEADER, SEPARATOR]
    for entry in sorted(entries.values(), key=lambda item: item.name.casefold()):
        name = entry.name.replace("|", "\\|")
        lines.append(
            f"| {name} | {entry.sha256} | {entry.pages_ok}/{entry.pages_total} "
            f"| {entry.pages_skipped} | {entry.status} | {entry.input_tokens} "
            f"| {entry.output_tokens} | {entry.timestamp} |"
        )

    tmp_path = Path(f"{history_path}.tmp")
    tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp_path, history_path)
