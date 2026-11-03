"""TDD suite -- dashboard answer buttons for clarifying questions (dashboard v0.9).

All tests use a temp vault only; the live Homunculus/vault is never touched.
Every endpoint path, label, status string and field name comes from the
``clarify_answer`` constants (single source of truth).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from homunculus_brain import activity_log, capture_parsed, clarify_answer as ca
from homunculus_brain import dashboard as dash
from homunculus_brain.schemas import ParsedCaptureRequest
from homunculus_brain.server import create_app

TZ_NAME = "America/New_York"
TZ = ZoneInfo(TZ_NAME)
NOW = datetime(2026, 9, 22, 14, 0, tzinfo=TZ)  # Mon 2pm
VERB_REMIND = "remind"
SUBJECT = "ping Sam"
DAY_HINT = "friday"
HINT_FOUR_OCLOCK = "four o'clock"
HINT_AMBIGUOUS_MINUTES = "4:30"
GIBBERISH_ANSWER = "whenever"
HOUR_AM = 4
HOUR_PM = 16
MINUTE_HALF = 30
CONFIDENCE = 0.9
AUDIO = "/tmp/x.m4a"
UNKNOWN_ID = "does-not-exist"
LEGACY_ID = "legacy-record"
LEGACY_QUESTION = "Did you mean AM or PM?"
ACTIVITY_KIND = "capture_parsed"
CLARIFY_QUESTION_TIME = "Did you mean AM or PM?"
CLARIFY_QUESTION_DAY = "I couldn't understand the day"
NOTE_REMINDERS_DIR = "reminders"
STARTS_AT_KEY = "starts_at"


def _client(vault: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("HOMUNCULUS_VAULT", str(vault))
    monkeypatch.setenv("HOMUNCULUS_TZ", TZ_NAME)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("SPRITE_WARNINGS_PATH", str(vault / "sprite" / "warnings.md"))
    monkeypatch.setenv("HOMUNCULUS_MIN_CONFIDENCE", "0.6")
    return TestClient(create_app())


def _req(time_hint, day_hint=DAY_HINT, verb=VERB_REMIND) -> ParsedCaptureRequest:
    return ParsedCaptureRequest(
        verb=verb, subject=SUBJECT, day_hint=day_hint, time_hint=time_hint,
        confidence=CONFIDENCE, raw_transcript=f"{SUBJECT} {day_hint} at {time_hint}",
        audio_path=AUDIO, captured_at=NOW,
    )


def _seed(vault: Path, req: ParsedCaptureRequest, question=CLARIFY_QUESTION_TIME,
          ambiguous=("time",)) -> str:
    """Create a clarify the way dispatch does (real helpers + activity row)."""
    rid = capture_parsed.compute_record_id(req)
    capture_parsed._enqueue_clarify_notification(
        vault, record_id=rid, question=question, transcript=req.raw_transcript, req=req)
    capture_parsed._append_clarifying_pending(
        vault, record_id=rid, question=question, transcript=req.raw_transcript, req=req,
        tz=TZ, ambiguous_fields=list(ambiguous))
    activity_log.log(vault, ACTIVITY_KIND, at=req.captured_at, event_id=None,
                     raw_text=req.raw_transcript,
                     details={"verb": req.verb.value, "subject": req.subject,
                              "record_id": rid, "stored": False,
                              "ambiguous_fields": list(ambiguous),
                              "clarifying_question": question})
    return rid


def _seed_legacy(vault: Path) -> str:
    """Old-format record: no stored answer context."""
    rem = vault / "_reminders"
    rem.mkdir(parents=True, exist_ok=True)
    (rem / capture_parsed._CLARIFYING_PENDING_FILENAME).write_text(json.dumps(
        {"record_id": LEGACY_ID, "question": LEGACY_QUESTION, "verb": VERB_REMIND,
         "subject": SUBJECT, "captured_at": NOW.isoformat(), "resolved_at": None}) + "\n")
    activity_log.log(vault, ACTIVITY_KIND, at=NOW, event_id=None, raw_text="x",
                     details={"verb": VERB_REMIND, "subject": SUBJECT, "record_id": LEGACY_ID,
                              "stored": False, "clarifying_question": LEGACY_QUESTION})
    return LEGACY_ID


def _pending(vault: Path, rid: str) -> dict:
    p = vault / "_reminders" / capture_parsed._CLARIFYING_PENDING_FILENAME
    for line in p.read_text().splitlines():
        row = json.loads(line)
        if row["record_id"] == rid:
            return row
    raise AssertionError(rid)


def _reminder_starts(vault: Path) -> list[datetime]:
    d = vault / NOTE_REMINDERS_DIR
    out = []
    for f in sorted(d.glob("*.md")) if d.is_dir() else []:
        for line in f.read_text().splitlines():
            if line.startswith(f"{STARTS_AT_KEY}:"):
                out.append(datetime.fromisoformat(line.split(":", 1)[1].strip().strip("'\"")))
    return out


def _answer(c, rid, answer):
    return c.post(ca.CLARIFY_ANSWER_ENDPOINT, json={ca.FIELD_RECORD_ID: rid, ca.FIELD_ANSWER: answer})


def _row_for(c, rid):
    rows = c.get("/dashboard/data").json()["rows"]
    return next(r for r in rows if (r.get("details") or {}).get("record_id") == rid)


def _label(hour, meridiem):
    return f"{hour} {meridiem}"


# --- storage of answer context ------------------------------------------------

def test_dispatch_stores_answer_context(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    payload = json.loads(_req(HINT_AMBIGUOUS_MINUTES).model_dump_json())
    body = c.post("/capture/parsed", json=payload).json()
    assert body["stored"] is False
    ctx = _pending(tmp_path, body["record_id"])[ca.CONTEXT_KEY]
    for key in ca.CONTEXT_REQUIRED_KEYS:
        assert key in ctx, key
    assert ctx[ca.CTX_TIME_HINT] == HINT_AMBIGUOUS_MINUTES
    assert ctx[ca.CTX_DAY_HINT] == DAY_HINT
    assert ctx[ca.CTX_TIMEZONE] == TZ_NAME
    assert ctx[ca.CTX_AMBIGUOUS_FIELDS] == ["time"]


# --- card options -----------------------------------------------------------------

def test_card_offers_am_pm_buttons(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rid = _seed(tmp_path, _req(HINT_FOUR_OCLOCK))
    ans = _row_for(c, rid)[ca.ROW_ANSWER_KEY]
    assert ans[ca.OPT_OPTIONS] == [_label(HOUR_AM, ca.MERIDIEM_AM), _label(HOUR_AM, ca.MERIDIEM_PM)]
    assert ans[ca.OPT_FREE_TEXT] is True  # type-your-own box stays available
    assert ca.DISMISS_BUTTON_LABEL and ca.SUBMIT_BUTTON_LABEL


def test_card_am_pm_buttons_keep_minutes(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rid = _seed(tmp_path, _req(HINT_AMBIGUOUS_MINUTES))
    opts = _row_for(c, rid)[ca.ROW_ANSWER_KEY][ca.OPT_OPTIONS]
    assert opts == [f"{HOUR_AM}:{MINUTE_HALF} {ca.MERIDIEM_AM}", f"{HOUR_AM}:{MINUTE_HALF} {ca.MERIDIEM_PM}"]


def test_card_day_ambiguity_offers_day_buttons(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rid = _seed(tmp_path, _req("9 am", day_hint="blorp"), question=CLARIFY_QUESTION_DAY,
                ambiguous=("day",))
    assert _row_for(c, rid)[ca.ROW_ANSWER_KEY][ca.OPT_OPTIONS] == list(ca.DAY_OPTIONS)


def test_card_unparseable_time_gets_text_box_only(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rid = _seed(tmp_path, _req(GIBBERISH_ANSWER))
    ans = _row_for(c, rid)[ca.ROW_ANSWER_KEY]
    assert ans[ca.OPT_OPTIONS] == []
    assert ans[ca.OPT_FREE_TEXT] is True


def test_old_record_without_context_has_no_buttons(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rid = _seed_legacy(tmp_path)
    row = _row_for(c, rid)
    assert row.get(ca.ROW_ANSWER_KEY) is None
    assert _answer(c, rid, "4 AM").status_code == ca.HTTP_CONFLICT


def test_dashboard_html_uses_constants(tmp_path, monkeypatch):
    html = dash.DASHBOARD_HTML
    assert ca.CLARIFY_ANSWER_ENDPOINT in html
    assert ca.DISMISS_BUTTON_LABEL in html
    assert ca.SUBMIT_BUTTON_LABEL in html
    assert dash.DASHBOARD_VERSION in html


# --- answering ---------------------------------------------------------------------

def test_answer_am_stores_0400_reminder(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rid = _seed(tmp_path, _req(HINT_FOUR_OCLOCK))
    r = _answer(c, rid, _label(HOUR_AM, ca.MERIDIEM_AM))
    assert r.status_code == 200, r.text
    assert r.json()[ca.RESP_STATUS] == ca.STATUS_ANSWERED
    starts = _reminder_starts(tmp_path)
    assert len(starts) == 1
    assert (starts[0].hour, starts[0].minute) == (HOUR_AM, 0)
    # clarify resolved, sidecar cancelled, card shows the summary
    assert _pending(tmp_path, rid)["resolved_at"]
    side = json.loads((tmp_path / "_reminders" / f"clarify.{rid}.json").read_text())
    assert all(s["status"] == dash.STATUS_DISMISSED for s in side["schedule"])
    summary = _row_for(c, rid)[ca.ROW_ANSWER_KEY][ca.OPT_RESOLVED_SUMMARY]
    assert summary.startswith(ca.ANSWERED_PREFIX) and "4 AM" in summary


def test_answer_pm_stores_1600_reminder(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rid = _seed(tmp_path, _req(HINT_FOUR_OCLOCK))
    assert _answer(c, rid, _label(HOUR_AM, ca.MERIDIEM_PM)).status_code == 200
    starts = _reminder_starts(tmp_path)
    assert [(s.hour, s.minute) for s in starts] == [(HOUR_PM, 0)]


def test_answer_keeps_day_hint(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rid = _seed(tmp_path, _req(HINT_FOUR_OCLOCK))
    _answer(c, rid, _label(HOUR_AM, ca.MERIDIEM_AM))
    assert _reminder_starts(tmp_path)[0].strftime("%A").lower() == DAY_HINT


def test_dismiss_stores_nothing(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rid = _seed(tmp_path, _req(HINT_FOUR_OCLOCK))
    r = _answer(c, rid, ca.DISMISS_ANSWER)
    assert r.status_code == 200
    assert r.json()[ca.RESP_STATUS] == ca.STATUS_DISMISSED
    assert _reminder_starts(tmp_path) == []
    assert not (tmp_path / NOTE_REMINDERS_DIR).exists() or not list((tmp_path / NOTE_REMINDERS_DIR).iterdir())
    assert _pending(tmp_path, rid)["resolved_at"]
    side = json.loads((tmp_path / "_reminders" / f"clarify.{rid}.json").read_text())
    assert all(s["status"] == dash.STATUS_DISMISSED for s in side["schedule"])


def test_unknown_record_id_is_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert _answer(c, UNKNOWN_ID, "4 AM").status_code == ca.HTTP_NOT_FOUND


def test_still_ambiguous_answer_keeps_card_open(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rid = _seed(tmp_path, _req(HINT_FOUR_OCLOCK))
    r = _answer(c, rid, HINT_AMBIGUOUS_MINUTES)   # still no AM/PM
    assert r.status_code == 200
    body = r.json()
    assert body[ca.RESP_STATUS] == ca.STATUS_NEEDS_CLARIFICATION
    assert body[ca.RESP_QUESTION]
    assert _reminder_starts(tmp_path) == []
    assert _pending(tmp_path, rid)["resolved_at"] is None
    # no duplicate clarify created
    rows = (tmp_path / "_reminders" / capture_parsed._CLARIFYING_PENDING_FILENAME).read_text().splitlines()
    assert len(rows) == 1
    # follow-up answer now works against the updated hints
    assert _answer(c, rid, f"{HOUR_AM}:{MINUTE_HALF} {ca.MERIDIEM_PM}").status_code == 200
    assert _pending(tmp_path, rid)["resolved_at"]


def test_resolved_record_cannot_be_answered_again(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rid = _seed(tmp_path, _req(HINT_FOUR_OCLOCK))
    assert _answer(c, rid, ca.DISMISS_ANSWER).status_code == 200
    assert _answer(c, rid, "4 AM").status_code == ca.HTTP_CONFLICT
