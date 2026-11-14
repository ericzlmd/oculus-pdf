from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

CATEGORIES: tuple[str, ...] = ("invoices", "statements")


@dataclass(frozen=True)
class Document:
    category: str
    path: Path
    name: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def discover_documents(
    input_dir: Path, categories: tuple[str, ...] = CATEGORIES
) -> dict[str, list[Document]]:
    """Raises FileNotFoundError if input_dir doesn't exist (or isn't a directory).
    Returns a dict with one key per category in `categories` (in that order).
    A missing category subdirectory yields [] for that key, not an error.
    Each list is sorted by name, case-insensitive (key=str.casefold).
    Only regular files whose suffix is .pdf (case-insensitive) count; dotfiles
    (names starting with '.') and subdirectories are ignored. Non-recursive:
    only one level under input_dir/<category>/."""
    if not input_dir.is_dir():
        raise FileNotFoundError(input_dir)

    documents: dict[str, list[Document]] = {}
    for category in categories:
        category_dir = input_dir / category
        found: list[Document] = []
        if category_dir.is_dir():
            for path in category_dir.iterdir():
                if path.name.startswith("."):
                    continue
                if path.suffix.lower() != ".pdf" or not path.is_file():
                    continue
                found.append(Document(category=category, path=path, name=path.name))
        found.sort(key=lambda document: document.name.casefold())
        documents[category] = found
    return documents
