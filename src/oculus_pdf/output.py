import re
from pathlib import Path

_HEADING_RE = re.compile(r"^( {0,3})(#{1,6})( .*)$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def demote_headings(markdown: str, levels: int = 2) -> str:
    lines: list[str] = []
    fence_char = ""
    fence_length = 0

    for line in markdown.split("\n"):
        fence = _FENCE_RE.match(line)

        if fence_char:
            lines.append(line)
            if (
                fence
                and fence.group(1)[0] == fence_char
                and len(fence.group(1)) >= fence_length
                and line[fence.end() :].strip() == ""
            ):
                fence_char = ""
                fence_length = 0
            continue

        if fence:
            fence_char = fence.group(1)[0]
            fence_length = len(fence.group(1))
            lines.append(line)
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            hashes = "#" * min(6, len(heading.group(2)) + levels)
            line = f"{heading.group(1)}{hashes}{heading.group(3)}"

        lines.append(line)

    return "\n".join(lines)


def write_document(
    out_file: Path,
    title: str,
    pages: list[int],
    markdown_by_page: dict[int, str],
    errors: dict[int, str],
) -> None:
    out_file.parent.mkdir(parents=True, exist_ok=True)

    parts = [f"# {title}\n"]
    for page in pages:
        if page in markdown_by_page:
            markdown = demote_headings(markdown_by_page[page].strip(), levels=2)
            parts.append(f"\n## Page {page}\n\n{markdown}\n")
        else:
            message = errors.get(page, "unknown error").replace("\n", " ").strip()
            parts.append(
                f"\n## Page {page} (failed)\n\n*Transcription failed: {message}*\n"
            )

    text = "".join(parts)
    out_file.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
