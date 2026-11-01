"""
generation_id.py — per-Generate-run identifier: ``year.month.date.hour24.minute.second.username``.

Replaces the old shared global serial counter.  Every Generate run builds one
ID (local time + OS login name) and uses it in the output 3MF filename, so two
Macs (different users and/or different seconds) never collide and no shared
state file is needed.

Example: ``2026.11.01.14.05.09.jgreen``
"""

from __future__ import annotations

import getpass
import re
from datetime import datetime
from typing import Optional

# ── Format pieces (single source of truth; tests import these) ───────────────
GENERATION_ID_SEPARATOR: str = "."
# Zero-padded year.month.date.hour24.minute.second, joined by the separator.
GENERATION_ID_TIME_FIELDS: tuple = ("%Y", "%m", "%d", "%H", "%M", "%S")
GENERATION_ID_TIME_FORMAT: str = GENERATION_ID_SEPARATOR.join(GENERATION_ID_TIME_FIELDS)

# Pattern for a generation ID inside a filename (time fields + username).
GENERATION_ID_TIME_FIELD_COUNT: int = len(GENERATION_ID_TIME_FIELDS)
GENERATION_ID_YEAR_DIGITS: int = 4
GENERATION_ID_FIELD_DIGITS: int = 2
_SEP_RE = re.escape(GENERATION_ID_SEPARATOR)
GENERATION_ID_PATTERN: str = (
    rf"\d{{{GENERATION_ID_YEAR_DIGITS}}}"
    + rf"(?:{_SEP_RE}\d{{{GENERATION_ID_FIELD_DIGITS}}}){{{GENERATION_ID_TIME_FIELD_COUNT - 1}}}"
    + rf"{_SEP_RE}[^\s\[\]]+"
)
# Legacy numeric serial from older output files, e.g. "[1552]".
LEGACY_SERIAL_PATTERN: str = r"\d+"

# Trailing bracketed tag of an output file stem: "[<new id>]" or legacy "[NNNN]".
FILENAME_ID_TAG_RE = re.compile(
    rf"\s*\[(?:{GENERATION_ID_PATTERN}|{LEGACY_SERIAL_PATTERN})\]\s*$"
)
FILENAME_ID_BRACKET_FMT: str = "[{generation_id}]"


def make_generation_id(now: Optional[datetime] = None, username: Optional[str] = None) -> str:
    """Build ``year.month.date.hour24.minute.second.username`` from local time.

    ``now`` and ``username`` default to the current local time and
    ``getpass.getuser()``; they are parameters so tests can freeze both.
    """
    if now is None:
        now = datetime.now()
    if username is None:
        username = getpass.getuser()
    return GENERATION_ID_SEPARATOR.join((now.strftime(GENERATION_ID_TIME_FORMAT), username))


def strip_generation_id_tag(stem: str) -> str:
    """Remove a trailing ``[<id>]`` tag (new format or legacy ``[NNNN]``) from a file stem."""
    return FILENAME_ID_TAG_RE.sub("", stem).strip()
