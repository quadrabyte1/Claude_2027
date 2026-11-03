"""Regression: a day-part word (morning/afternoon/evening/tonight/night/noon/midnight)
anywhere in the day/time hints or the memo must resolve AM/PM -- never ask.

Bug (2026-11-02): "Reminder at four o'clock tomorrow morning" produced an
"AM or PM?" clarify because the LLM put the day-part into time_hint
("four o'clock tomorrow morning") and the time regex rejected it.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from homunculus_brain import date_resolver
from homunculus_brain.date_resolver import DAY_PART_MERIDIEM, resolve

TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 2, 18, 1, tzinfo=TZ)  # Monday evening
TOMORROW = (2026, 11, 3)
TODAY = (2026, 11, 2)
VERB = "remind"
HOUR_4_AM = 4
HOUR_9_PM = 21
HOUR_3_PM = 15
HOUR_NOON = 12
HOUR_MIDNIGHT = 0
BUG_MEMO = "Watch, watch, watch, watch four times. Reminder at four o'clock tomorrow morning."
BARE_MEMO = "Remind me to call Bob at 4 tomorrow"
DAY_PART_WORDS = ("morning", "afternoon", "evening", "tonight", "night", "noon", "midnight")


def _r(day, time_hint, memo):
    return resolve(day, time_hint, NOW, TZ, verb=VERB, context_text=memo)


CASES = [
    # (day_hint, time_hint, memo, (y, m, d), hour)
    ("tomorrow", "four o'clock", BUG_MEMO, TOMORROW, HOUR_4_AM),
    ("tomorrow", "four o'clock tomorrow morning", BUG_MEMO, TOMORROW, HOUR_4_AM),
    ("tomorrow morning", "four o'clock", BUG_MEMO, TOMORROW, HOUR_4_AM),
    ("tomorrow morning", "four", BUG_MEMO, TOMORROW, HOUR_4_AM),
    (None, "four o'clock tomorrow morning", BUG_MEMO, TOMORROW, HOUR_4_AM),
    ("tomorrow", "4 tomorrow morning", "remind me 4 tomorrow morning", TOMORROW, HOUR_4_AM),
    ("tomorrow", "4 in the morning", "remind me at 4 in the morning", TOMORROW, HOUR_4_AM),
    ("tomorrow", "at 4 in the morning", "remind me at 4 in the morning", TOMORROW, HOUR_4_AM),
    ("tomorrow", "four", "tomorrow morning at four", TOMORROW, HOUR_4_AM),
    ("tomorrow morning", "at four", "tomorrow morning at four", TOMORROW, HOUR_4_AM),
    ("tonight", "at 9", "remind me tonight at 9", TODAY, HOUR_9_PM),
    ("today", "tonight at 9", "remind me tonight at 9", TODAY, HOUR_9_PM),
    ("today", "9 this evening", "remind me 9 this evening", TODAY, HOUR_9_PM),
    ("this evening", "9", "remind me 9 this evening", TODAY, HOUR_9_PM),
    ("today", "3 in the afternoon", "3 in the afternoon", TODAY, HOUR_3_PM),
    ("tomorrow", "3 in the afternoon", "tomorrow 3 in the afternoon", TOMORROW, HOUR_3_PM),
    ("tomorrow", "noon", "tomorrow at noon", TOMORROW, HOUR_NOON),
    ("tomorrow", "midnight", "tomorrow at midnight", TOMORROW, HOUR_MIDNIGHT),
]


@pytest.mark.parametrize("day,time_hint,memo,ymd,hour", CASES)
def test_daypart_resolves_without_clarify(day, time_hint, memo, ymd, hour):
    r = _r(day, time_hint, memo)
    assert r.ambiguous == [], f"{day!r}/{time_hint!r} still ambiguous: {r.ambiguous}"
    assert r.resolved_at is not None
    assert (r.resolved_at.year, r.resolved_at.month, r.resolved_at.day) == ymd
    assert r.resolved_at.hour == hour


def test_bare_hour_without_daypart_still_asks_or_rolls_forward_unchanged():
    """No day-part anywhere: behaviour must not change (no AM/PM invented from the table)."""
    r = _r("tomorrow", "4", BARE_MEMO)
    baseline = resolve("tomorrow", "4", NOW, TZ, verb=VERB, context_text=BARE_MEMO)
    assert (r.resolved_at, r.ambiguous) == (baseline.resolved_at, baseline.ambiguous)


def test_bare_hour_with_minutes_no_daypart_still_clarifies():
    r = _r("tomorrow", "5:35", "remind me 5:35 tomorrow")
    assert r.ambiguous == ["time"]


def test_daypart_table_is_single_source_and_complete():
    assert set(DAY_PART_WORDS) <= set(DAY_PART_MERIDIEM)
    assert DAY_PART_MERIDIEM["morning"] == "am"
    assert DAY_PART_MERIDIEM["tonight"] == "pm"
    assert DAY_PART_MERIDIEM["evening"] == "pm"
    assert DAY_PART_MERIDIEM["afternoon"] == "pm"
