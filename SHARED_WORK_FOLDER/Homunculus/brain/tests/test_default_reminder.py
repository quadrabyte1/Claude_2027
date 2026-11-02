"""Default-to-reminder rule (v-next): no explicit calendar signal => remind.

Tests the deterministic layer only (no Ollama, no HTTP). Constants are imported
from the production module so a change in one place cannot leave a stale copy.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from fastapi.testclient import TestClient

from homunculus_brain.schemas import CaptureVerb
from homunculus_brain.server import create_app
from homunculus_brain.verb_default import (
    CALENDAR_SIGNAL_WORDS,
    apply_default_reminder,
    has_calendar_signal,
    signal_words_for_prompt,
)

TZ_NAME = "America/New_York"
CAPTURED_AT = datetime(2026, 9, 15, 9, 0, tzinfo=ZoneInfo(TZ_NAME))
AUDIO_PATH = "/tmp/x.m4a"
OLLAMA_DEAD_URL = "http://127.0.0.1:1"
CONFIDENCE = 0.9
LLM_CALENDAR_VERB = CaptureVerb.SCHEDULE

# (transcript, expected verb after the deterministic layer)
CASES = [
    ("dentist tomorrow at 3", CaptureVerb.REMIND),
    ("call Jim at 3pm", CaptureVerb.REMIND),
    ("lunch with Bob Friday at noon", CaptureVerb.REMIND),
    ("put the dentist on my calendar tomorrow at 3", CaptureVerb.SCHEDULE),
    ("meeting with Jim 2 to 3 tomorrow", CaptureVerb.SCHEDULE),
    ("schedule a call with Jim Friday", CaptureVerb.SCHEDULE),
    ("block off Saturday for an hour", CaptureVerb.SCHEDULE),
    ("dentist appointment Tuesday at 9am", CaptureVerb.SCHEDULE),
]


@pytest.mark.parametrize("transcript,expected", CASES)
def test_apply_default_reminder_flips_llm_calendar_without_signal(transcript, expected):
    assert apply_default_reminder(LLM_CALENDAR_VERB, transcript) == expected


@pytest.mark.parametrize("transcript,expected", CASES)
def test_has_calendar_signal_matches_expectation(transcript, expected):
    assert has_calendar_signal(transcript) == (expected is CaptureVerb.SCHEDULE)


@pytest.mark.parametrize(
    "verb",
    [CaptureVerb.NOTE, CaptureVerb.AVOID, CaptureVerb.START_TIMER, CaptureVerb.HANDLE, CaptureVerb.REMIND],
)
def test_non_calendar_verbs_untouched(verb):
    assert apply_default_reminder(verb, "dentist tomorrow at 3") == verb


@pytest.mark.parametrize("word", CALENDAR_SIGNAL_WORDS)
def test_every_signal_word_counts(word):
    assert has_calendar_signal(f"the {word} tomorrow at 3")


def test_signal_word_is_whole_word_only():
    assert not has_calendar_signal("the eventual outcome tomorrow")


def test_prompt_text_lists_every_signal_word():
    text = signal_words_for_prompt()
    for word in CALENDAR_SIGNAL_WORDS:
        assert word in text


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("HOMUNCULUS_VAULT", str(tmp_path))
    monkeypatch.setenv("HOMUNCULUS_TZ", TZ_NAME)
    monkeypatch.setenv("OLLAMA_BASE_URL", OLLAMA_DEAD_URL)
    monkeypatch.setenv("SPRITE_WARNINGS_PATH", str(tmp_path / "sprite" / "warnings.md"))
    monkeypatch.setenv("HOMUNCULUS_MIN_CONFIDENCE", "0.6")
    return TestClient(create_app())


def _post(client, transcript: str) -> dict:
    payload = {
        "verb": LLM_CALENDAR_VERB.value, "subject": "dentist", "day_hint": "tomorrow",
        "time_hint": "3pm", "criticality": "normal", "confidence": CONFIDENCE,
        "raw_transcript": transcript, "audio_path": AUDIO_PATH,
        "captured_at": CAPTURED_AT.isoformat(), "speaker_tz": TZ_NAME,
    }
    r = client.post("/capture/parsed", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_endpoint_routes_signalless_schedule_to_reminders(tmp_path, monkeypatch):
    body = _post(_client(tmp_path, monkeypatch), "dentist tomorrow at 3pm")
    assert body["verb"] == CaptureVerb.REMIND.value
    assert not list((tmp_path / "calendar").rglob("*.md"))


def test_endpoint_keeps_explicit_calendar(tmp_path, monkeypatch):
    body = _post(_client(tmp_path, monkeypatch), "put the dentist on my calendar tomorrow at 3pm")
    assert body["verb"] == CaptureVerb.SCHEDULE.value
