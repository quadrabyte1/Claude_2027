"""Default-to-reminder rule for the remind-vs-calendar choice.

A memo with a time or day but NO explicit calendar signal is a reminder.
Only an explicit signal (a word in ``CALENDAR_SIGNAL_WORDS`` or a duration /
end-time expression) produces a calendar event. This module is the single
source of the signal list: the deterministic post-check below and any prompt
text both derive from it.
"""

from __future__ import annotations

import re

from .schemas import CaptureVerb

# Explicit "put this on the calendar" words. Whole-word, case-insensitive.
# Multi-word phrases are fine; "put on my calendar" is covered by "calendar".
CALENDAR_SIGNAL_WORDS: tuple[str, ...] = (
    "calendar",
    "event",
    "meeting",
    "appointment",
    "schedule",
)

# Duration / end-time expressions that imply a block of time on the calendar.
_NUM = r"\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?"
DURATION_SIGNAL_PATTERNS: tuple[str, ...] = (
    rf"\bfrom\s+{_NUM}\s+(?:to|until|till|-)\s+{_NUM}",      # "from 2 to 3"
    rf"\b{_NUM}\s+(?:to|until|till)\s+\d{{1,2}}\b",          # "2 to 3"
    r"\bfor\s+(?:an?|one|two|three|four|\d+(?:\.\d+)?)\s+(?:hours?|hrs?|minutes?|mins?)\b",
    r"\bfor\s+(?:half\s+an\s+hour|an\s+hour\s+and\s+a\s+half)\b",
    r"\buntil\s+\d",
)

SIGNAL_WORD_JOINER = ", "

_WORD_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in CALENDAR_SIGNAL_WORDS) + r")\b",
    re.IGNORECASE,
)
_DURATION_RES = tuple(re.compile(p, re.IGNORECASE) for p in DURATION_SIGNAL_PATTERNS)

CALENDAR_VERBS = frozenset({CaptureVerb.SCHEDULE})
DEFAULT_VERB = CaptureVerb.REMIND


def has_calendar_signal(text: str) -> bool:
    """True when the transcript explicitly asks for a calendar event."""
    return bool(_WORD_RE.search(text)) or any(r.search(text) for r in _DURATION_RES)


def signal_words_for_prompt() -> str:
    """Signal words rendered for inclusion in an LLM prompt."""
    return SIGNAL_WORD_JOINER.join(f'"{w}"' for w in CALENDAR_SIGNAL_WORDS)


def apply_default_reminder(verb: CaptureVerb, transcript: str) -> CaptureVerb:
    """Flip a calendar verb to remind when the transcript has no explicit signal."""
    if verb in CALENDAR_VERBS and not has_calendar_signal(transcript):
        return DEFAULT_VERB
    return verb
