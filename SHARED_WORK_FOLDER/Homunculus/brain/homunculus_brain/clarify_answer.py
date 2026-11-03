"""Answer path for clarifying questions (Herman dashboard v0.9).

A clarify is created by ``capture_parsed`` when a parsed capture is ambiguous.
The pending record now carries an ``answer_context`` (everything needed to
finish the capture).  ``POST /clarify/answer`` re-runs the normal capture
dispatch with the answer applied, then resolves the clarify and cancels its
``clarify_immediate`` reminder sidecar.

This module keeps its top-level imports light (stdlib + schemas) so that both
``capture_parsed`` and ``dashboard`` can import its constants without cycles.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import create_model

# --- endpoint / wire names ----------------------------------------------------
CLARIFY_ANSWER_ENDPOINT = "/clarify/answer"
FIELD_RECORD_ID = "record_id"
FIELD_ANSWER = "answer"
RESP_STATUS = "status"
RESP_QUESTION = "question"
RESP_OPTIONS = "options"
RESP_SUMMARY = "summary"
RESP_RECORD_ID = "record_id"

# --- response statuses ----------------------------------------------------------
STATUS_ANSWERED = "answered"
STATUS_DISMISSED = "dismissed"
STATUS_NEEDS_CLARIFICATION = "needs_clarification"

# --- HTTP codes -----------------------------------------------------------------
HTTP_NOT_FOUND = 404
HTTP_CONFLICT = 409
DETAIL_NOT_FOUND = "unknown clarify record_id"
DETAIL_NOT_ANSWERABLE = "clarify has no stored answer context or is already resolved"

# --- UI labels ------------------------------------------------------------------
DISMISS_BUTTON_LABEL = "Dismiss"
SUBMIT_BUTTON_LABEL = "Submit"
DISMISS_ANSWER = "__dismiss__"  # sentinel sent by the Dismiss button
MERIDIEM_AM = "AM"
MERIDIEM_PM = "PM"
DAY_OPTIONS = ("Today", "Tomorrow")
PLACEHOLDER_TIME = "type the time"
PLACEHOLDER_DAY = "type the day"
ANSWERED_PREFIX = "Answered: "
DISMISSED_SUMMARY = "Dismissed"
SUMMARY_ARROW = " → "
OUTCOME_DEFAULT = "stored"
OUTCOME_BY_VERB = {
    "schedule": "calendar event stored",
    "handle": "reminder stored",
    "remind": "reminder stored",
    "note": "note stored",
}

# --- pending-record layout --------------------------------------------------------
PENDING_FILENAME = "_clarifying_pending.jsonl"
REMINDERS_DIRNAME = "_reminders"
SIDECAR_NAME_TEMPLATE = "clarify.{record_id}.json"
SIDECAR_SCHEDULE_KEY = "schedule"
SIDECAR_STATUS_KEY = "status"
SIDECAR_STATUS_PENDING = "pending"
SIDECAR_STATUS_CANCELLED = "cancelled"  # status reminders.py already skips
PENDING_RECORD_ID_KEY = "record_id"
PENDING_QUESTION_KEY = "question"
PENDING_RESOLVED_KEY = "resolved_at"
PENDING_RESOLUTION_KEY = "resolution"
PENDING_SUMMARY_KEY = "answer_summary"
CONTEXT_KEY = "answer_context"

# --- answer_context fields ---------------------------------------------------------
CTX_VERB = "verb"
CTX_SUBJECT = "subject"
CTX_BODY = "body"
CTX_DAY_HINT = "day_hint"
CTX_TIME_HINT = "time_hint"
CTX_CAPTURED_AT = "captured_at"
CTX_TIMEZONE = "timezone"
CTX_CRITICALITY = "criticality"
CTX_RECORD_ID = "record_id"
CTX_AMBIGUOUS_FIELDS = "ambiguous_fields"
CTX_AUDIO_PATH = "audio_path"
CTX_CONFIDENCE = "confidence"
CTX_PROJECT = "project"
CONTEXT_REQUIRED_KEYS = (
    CTX_VERB, CTX_SUBJECT, CTX_BODY, CTX_DAY_HINT, CTX_TIME_HINT, CTX_CAPTURED_AT,
    CTX_TIMEZONE, CTX_CRITICALITY, CTX_RECORD_ID, CTX_AMBIGUOUS_FIELDS,
)

# --- ambiguity fields (as produced by date_resolver) ---------------------------------
AMBIG_TIME = "time"
AMBIG_DAY = "day"

# --- dashboard row payload ------------------------------------------------------------
ROW_ANSWER_KEY = "answer"
OPT_OPTIONS = "options"
OPT_FREE_TEXT = "free_text"
OPT_FIELD = "field"
OPT_PLACEHOLDER = "placeholder"
OPT_RESOLVED_SUMMARY = "resolved_summary"

_HOUR_DIGITS_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?")
_HOUR_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
_MAX_CLOCK_HOUR = 12
_MINUTE_FMT = "{hour}:{minute} {meridiem}"
_HOUR_FMT = "{hour} {meridiem}"


# Request body built from the field-name constants (single source of truth).
ClarifyAnswerRequest = create_model(
    "ClarifyAnswerRequest",
    **{FIELD_RECORD_ID: (str, ...), FIELD_ANSWER: (str, ...)},
)


class ClarifyAnswerError(Exception):
    """Raised for unknown / unanswerable clarify records (carries HTTP status)."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ---------------------------------------------------------------------------
# Context + options
# ---------------------------------------------------------------------------


def build_context(req: Any, *, record_id: str, tz_name: Optional[str],
                  ambiguous_fields: list[str]) -> dict[str, Any]:
    """Everything needed to finish a capture later (stored on the pending record)."""
    return {
        CTX_VERB: req.verb.value,
        CTX_SUBJECT: req.subject,
        CTX_BODY: req.raw_transcript,
        CTX_DAY_HINT: req.day_hint,
        CTX_TIME_HINT: req.time_hint,
        CTX_CAPTURED_AT: req.captured_at.isoformat(),
        CTX_TIMEZONE: tz_name or req.speaker_tz,
        CTX_CRITICALITY: req.criticality.value,
        CTX_RECORD_ID: record_id,
        CTX_AMBIGUOUS_FIELDS: list(ambiguous_fields),
        CTX_AUDIO_PATH: req.audio_path,
        CTX_CONFIDENCE: req.confidence,
        CTX_PROJECT: req.project,
    }


def _field_to_answer(ctx: dict[str, Any]) -> Optional[str]:
    fields = ctx.get(CTX_AMBIGUOUS_FIELDS) or []
    if AMBIG_TIME in fields:
        return AMBIG_TIME
    if AMBIG_DAY in fields:
        return AMBIG_DAY
    return None


def _parse_hour_minute(hint: Optional[str]) -> Optional[tuple[int, Optional[str]]]:
    text = (hint or "").lower()
    m = _HOUR_DIGITS_RE.search(text)
    if m:
        hour, minute = int(m.group(1)), m.group(2)
    else:
        hour, minute = None, None
        for token in re.findall(r"[a-z]+", text):
            if token in _HOUR_WORDS:
                hour = _HOUR_WORDS[token]
                break
        if hour is None:
            return None
    if not 1 <= hour <= _MAX_CLOCK_HOUR:
        return None
    return hour, minute


def time_options(time_hint: Optional[str]) -> list[str]:
    """Two buttons (AM / PM) worked out from the hint; [] when unparseable."""
    parsed = _parse_hour_minute(time_hint)
    if parsed is None:
        return []
    hour, minute = parsed
    out = []
    for meridiem in (MERIDIEM_AM, MERIDIEM_PM):
        if minute:
            out.append(_MINUTE_FMT.format(hour=hour, minute=minute, meridiem=meridiem))
        else:
            out.append(_HOUR_FMT.format(hour=hour, meridiem=meridiem))
    return out


def options_for(ctx: dict[str, Any]) -> dict[str, Any]:
    field = _field_to_answer(ctx)
    if field == AMBIG_TIME:
        options, placeholder = time_options(ctx.get(CTX_TIME_HINT)), PLACEHOLDER_TIME
    elif field == AMBIG_DAY:
        options, placeholder = list(DAY_OPTIONS), PLACEHOLDER_DAY
    else:
        options, placeholder = [], PLACEHOLDER_TIME
    return {OPT_FIELD: field, OPT_OPTIONS: options, OPT_FREE_TEXT: True,
            OPT_PLACEHOLDER: placeholder}


def answer_view(pending_row: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Dashboard payload for one clarify card, or None when it gets no controls."""
    if not pending_row:
        return None
    summary = pending_row.get(PENDING_SUMMARY_KEY)
    if pending_row.get(PENDING_RESOLVED_KEY) is not None:
        return {OPT_RESOLVED_SUMMARY: summary} if summary else None
    ctx = pending_row.get(CONTEXT_KEY)
    if not isinstance(ctx, dict) or not all(k in ctx for k in CONTEXT_REQUIRED_KEYS):
        return None
    return options_for(ctx)


# ---------------------------------------------------------------------------
# Pending-file IO
# ---------------------------------------------------------------------------


def _pending_path(vault_path: Path) -> Path:
    return vault_path / REMINDERS_DIRNAME / PENDING_FILENAME


def load_pending(vault_path: Path) -> dict[str, dict[str, Any]]:
    """record_id -> pending row (last write wins)."""
    path = _pending_path(vault_path)
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get(PENDING_RECORD_ID_KEY):
            out[row[PENDING_RECORD_ID_KEY]] = row
    return out


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _update_pending(vault_path: Path, record_id: str, mutate) -> None:
    path = _pending_path(vault_path)
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            out.append(line)
            continue
        if isinstance(row, dict) and row.get(PENDING_RECORD_ID_KEY) == record_id:
            mutate(row)
        out.append(json.dumps(row, ensure_ascii=False))
    _atomic_write(path, "\n".join(out) + "\n")


def _cancel_sidecar(vault_path: Path, record_id: str) -> None:
    path = vault_path / REMINDERS_DIRNAME / SIDECAR_NAME_TEMPLATE.format(record_id=record_id)
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    changed = False
    for sched in data.get(SIDECAR_SCHEDULE_KEY, []):
        if sched.get(SIDECAR_STATUS_KEY, SIDECAR_STATUS_PENDING) == SIDECAR_STATUS_PENDING:
            sched[SIDECAR_STATUS_KEY] = SIDECAR_STATUS_CANCELLED
            changed = True
    if changed:
        _atomic_write(path, json.dumps(data, ensure_ascii=False))


def _resolve(vault_path: Path, record_id: str, *, status: str, summary: str) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()

    def mutate(row: dict[str, Any]) -> None:
        if row.get(PENDING_RESOLVED_KEY) is None:
            row[PENDING_RESOLVED_KEY] = now_iso
        row[PENDING_RESOLUTION_KEY] = status
        row[PENDING_SUMMARY_KEY] = summary

    _update_pending(vault_path, record_id, mutate)
    _cancel_sidecar(vault_path, record_id)


# ---------------------------------------------------------------------------
# The answer itself
# ---------------------------------------------------------------------------


def answer(vault_path: Path, *, config: Any, record_id: str, answer_text: str) -> dict[str, Any]:
    """Apply ``answer_text`` to a pending clarify; see module docstring."""
    from zoneinfo import ZoneInfo

    from . import capture_parsed
    from .schemas import ParsedCaptureRequest

    row = load_pending(vault_path).get(record_id)
    if row is None:
        raise ClarifyAnswerError(HTTP_NOT_FOUND, DETAIL_NOT_FOUND)
    ctx = row.get(CONTEXT_KEY)
    if (row.get(PENDING_RESOLVED_KEY) is not None or not isinstance(ctx, dict)
            or not all(k in ctx for k in CONTEXT_REQUIRED_KEYS)):
        raise ClarifyAnswerError(HTTP_CONFLICT, DETAIL_NOT_ANSWERABLE)

    if answer_text == DISMISS_ANSWER:
        _resolve(vault_path, record_id, status=STATUS_DISMISSED, summary=DISMISSED_SUMMARY)
        return {RESP_STATUS: STATUS_DISMISSED, RESP_RECORD_ID: record_id,
                RESP_SUMMARY: DISMISSED_SUMMARY}

    answer_text = answer_text.strip()
    field = _field_to_answer(ctx)
    hint_key = CTX_DAY_HINT if field == AMBIG_DAY else CTX_TIME_HINT
    new_ctx = dict(ctx)
    new_ctx[hint_key] = answer_text

    tz = ZoneInfo(new_ctx.get(CTX_TIMEZONE) or config.default_tz_name)
    req = ParsedCaptureRequest(
        verb=new_ctx[CTX_VERB], subject=new_ctx[CTX_SUBJECT],
        day_hint=new_ctx[CTX_DAY_HINT], time_hint=new_ctx[CTX_TIME_HINT],
        criticality=new_ctx[CTX_CRITICALITY],
        confidence=new_ctx.get(CTX_CONFIDENCE) if new_ctx.get(CTX_CONFIDENCE) is not None else 1.0,
        raw_transcript=new_ctx[CTX_BODY], audio_path=new_ctx.get(CTX_AUDIO_PATH) or "",
        captured_at=datetime.fromisoformat(new_ctx[CTX_CAPTURED_AT]),
        project=new_ctx.get(CTX_PROJECT),
    )

    # Still ambiguous? Update the open card instead of dispatching (dispatch
    # would open a second clarify for the new hint hash).
    clarify = capture_parsed._resolve_from_hints(
        req, config=config, tz=tz, record_id=capture_parsed.compute_record_id(req))
    if clarify is not None:
        new_ctx[CTX_AMBIGUOUS_FIELDS] = list(clarify.ambiguous_fields)

        def mutate(r: dict[str, Any]) -> None:
            r[CONTEXT_KEY] = new_ctx
            r[PENDING_QUESTION_KEY] = clarify.clarifying_question

        _update_pending(vault_path, record_id, mutate)
        return {RESP_STATUS: STATUS_NEEDS_CLARIFICATION, RESP_RECORD_ID: record_id,
                RESP_QUESTION: clarify.clarifying_question,
                RESP_OPTIONS: options_for(new_ctx)}

    # Same code path as a normal capture: storage, scheduling, notifications.
    resp = capture_parsed.dispatch(req, config=config, tz=tz)
    outcome = OUTCOME_BY_VERB.get(new_ctx[CTX_VERB], OUTCOME_DEFAULT)
    summary = f"{ANSWERED_PREFIX}{answer_text}{SUMMARY_ARROW}{outcome}"
    _resolve(vault_path, record_id, status=STATUS_ANSWERED, summary=summary)
    return {RESP_STATUS: STATUS_ANSWERED, RESP_RECORD_ID: record_id, RESP_SUMMARY: summary,
            "stored_record_id": resp.record_id}
