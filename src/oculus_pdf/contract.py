from __future__ import annotations

import re

WORD_THRESHOLD: int = 400
MARKER_THRESHOLD: int = 3

# The word gate rules out short pages; markers are lease/contract vocabulary.
# Calibration: invoice pages had 224 and 42 words with 0 markers, while lease
# boilerplate pages had 2291 words and 8 markers.
MARKER_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\blessee\b",
        r"\blessor\b",
        r"indemnif|indemnit",
        r"\bhereby\b",
        r"\bthis agreement\b",
        r"\bterms and conditions\b",
        r"sub-?leas",
        r"\bwarrant(?:y|ies)\b",
        r"\bliabilit(?:y|ies)\b",
        r"\bgoverning law\b",
    )
)


def is_contract_page(text: str) -> bool:
    """True iff text has >= WORD_THRESHOLD words (len(text.split())) AND matches
    >= MARKER_THRESHOLD distinct marker patterns (case-insensitive) from
    MARKER_PATTERNS. Pure and deterministic."""
    if len(text.split()) < WORD_THRESHOLD:
        return False
    matches = sum(1 for pattern in MARKER_PATTERNS if pattern.search(text))
    return matches >= MARKER_THRESHOLD
