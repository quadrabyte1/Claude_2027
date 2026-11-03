"""
generation_id.py — per-Generate-run identifier: a standard UUID4.

Every Generate run builds one ID and uses it in the output 3MF filename
(``[<uuid>]``), so two Macs never collide and no shared state file is needed.

Example: ``3f2b8c1e-9a47-4d6e-8b0c-5e7a1d2c4f90``

Older output files on disk carry the v6.18 ``year.month.date.hour24.minute.second.username``
tag or the original numeric ``[NNNN]`` serial; ``strip_generation_id_tag`` still strips
all three forms.
"""

from __future__ import annotations

import re
import uuid

# ── Current format: canonical lowercase hyphenated UUID4 (tests import these) ─
UUID_GROUP_LENGTHS: tuple = (8, 4, 4, 4, 12)
UUID_HEX_GROUP_FMT: str = "[0-9a-f]{{{n}}}"
GENERATION_ID_SEPARATOR: str = "-"
GENERATION_ID_PATTERN: str = GENERATION_ID_SEPARATOR.join(
    UUID_HEX_GROUP_FMT.format(n=n) for n in UUID_GROUP_LENGTHS
)
GENERATION_ID_LENGTH: int = sum(UUID_GROUP_LENGTHS) + len(UUID_GROUP_LENGTHS) - 1   # 36
UUID_VERSION: int = 4

# ── Legacy formats, kept only so old filenames can still be stripped ─────────
# v6.18 "year.month.date.hour24.minute.second.username", e.g. "2026.11.01.14.05.09.jgreen".
LEGACY_TIMESTAMP_SEPARATOR: str = "."
LEGACY_TIMESTAMP_YEAR_DIGITS: int = 4
LEGACY_TIMESTAMP_FIELD_DIGITS: int = 2
LEGACY_TIMESTAMP_FIELD_COUNT: int = 6   # year, month, date, hour24, minute, second
_LEGACY_SEP_RE = re.escape(LEGACY_TIMESTAMP_SEPARATOR)
LEGACY_TIMESTAMP_PATTERN: str = (
    rf"\d{{{LEGACY_TIMESTAMP_YEAR_DIGITS}}}"
    + rf"(?:{_LEGACY_SEP_RE}\d{{{LEGACY_TIMESTAMP_FIELD_DIGITS}}}){{{LEGACY_TIMESTAMP_FIELD_COUNT - 1}}}"
    + rf"{_LEGACY_SEP_RE}[^\s\[\]]+"
)
# Original numeric serial from the oldest output files, e.g. "[1552]".
LEGACY_SERIAL_PATTERN: str = r"\d+"

# Trailing bracketed tag of an output file stem: "[<uuid>]", "[<timestamp.user>]" or "[NNNN]".
FILENAME_ID_TAG_RE = re.compile(
    rf"\s*\[(?:{GENERATION_ID_PATTERN}|{LEGACY_TIMESTAMP_PATTERN}|{LEGACY_SERIAL_PATTERN})\]\s*$"
)
FILENAME_ID_BRACKET_FMT: str = "[{generation_id}]"

# Short ID for the printed underside text: the UUID up to the first dash (8 hex chars).
SHORT_ID_SEPARATOR: str = GENERATION_ID_SEPARATOR
SHORT_ID_SEGMENT_INDEX: int = 0


def make_generation_id() -> str:
    """Return a fresh standard UUID4 as a canonical lowercase hyphenated string."""
    return str(uuid.uuid4())


def strip_generation_id_tag(stem: str) -> str:
    """Remove a trailing ``[<id>]`` tag (UUID, v6.18 timestamp.username, or legacy ``[NNNN]``) from a file stem."""
    return FILENAME_ID_TAG_RE.sub("", stem).strip()


def short_generation_id(generation_id: str) -> str:
    """First hyphen-separated segment of a UUID generation ID (8 hex chars).

    Not guaranteed unique, but collisions are rare enough for a printed identifier.
    """
    return str(generation_id).split(SHORT_ID_SEPARATOR)[SHORT_ID_SEGMENT_INDEX]
