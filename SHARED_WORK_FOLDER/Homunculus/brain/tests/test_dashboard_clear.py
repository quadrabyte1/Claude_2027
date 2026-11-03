"""Tests for the dashboard Clear button / POST /dashboard/clear (temp vault only)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from homunculus_brain import dashboard as dash
from homunculus_brain.server import create_app


def _app(vault: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("HOMUNCULUS_VAULT", str(vault))
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:1")
    return TestClient(create_app())


def _activity(vault: Path, rows: list[dict]) -> Path:
    p = vault / "_activity.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


def _row(at: str, text: str = "x") -> dict:
    return {"at": at, "kind": "note", "event_id": None, "raw_text": text, "details": {}}


def _seed_clarify(vault: Path) -> tuple[Path, Path]:
    rem = vault / "_reminders"
    rem.mkdir(parents=True, exist_ok=True)
    pending = rem / "_clarifying_pending.jsonl"
    pending.write_text(json.dumps({"record_id": "r1", "resolved_at": None, "question": "q"}) + "\n")
    side = rem / "clarify.r1.json"
    side.write_text(json.dumps({"event_id": "clarify.r1", "schedule": [
        {"event_id": "clarify.r1", "kind": "clarify_immediate", "fire_at": "2026-01-01T00:00:00+00:00",
         "tz": "UTC", "body": "b", "status": dash.STATUS_PENDING}]}))
    return pending, side


def test_constants_exposed():
    assert dash.CLEAR_ENDPOINT == "/dashboard/clear"
    assert dash.CLEAR_BUTTON_LABEL in dash.DASHBOARD_HTML
    assert dash.CLEAR_ENDPOINT in dash.DASHBOARD_HTML
    assert dash.CLEAR_CONFIRM_TEXT in dash.DASHBOARD_HTML


def test_clear_filters_old_rows_and_keeps_activity_file(tmp_path, monkeypatch):
    activity = _activity(tmp_path, [_row("2020-01-01T00:00:00Z", "old")])
    before = activity.read_bytes()
    c = _app(tmp_path, monkeypatch)
    assert len(c.get("/dashboard/data").json()["rows"]) == 1
    r = c.post(dash.CLEAR_ENDPOINT)
    assert r.status_code == 200
    assert r.json()["cleared_at"]
    data = c.get("/dashboard/data").json()
    assert data["rows"] == []
    assert data["cleared_at"] == r.json()["cleared_at"]
    assert (tmp_path / dash.CLEAR_STATE_FILENAME).exists()
    assert activity.read_bytes() == before


def test_new_rows_after_clear_appear(tmp_path, monkeypatch):
    _activity(tmp_path, [_row("2020-01-01T00:00:00Z", "old")])
    c = _app(tmp_path, monkeypatch)
    c.post(dash.CLEAR_ENDPOINT)
    with (tmp_path / "_activity.jsonl").open("a") as f:
        f.write(json.dumps(_row("2999-01-01T00:00:00Z", "new")) + "\n")
    rows = c.get("/dashboard/data").json()["rows"]
    assert len(rows) == 1


def test_watermark_persists_across_app_instances(tmp_path, monkeypatch):
    _activity(tmp_path, [_row("2020-01-01T00:00:00Z")])
    stamp = _app(tmp_path, monkeypatch).post(dash.CLEAR_ENDPOINT).json()["cleared_at"]
    c2 = _app(tmp_path, monkeypatch)
    d = c2.get("/dashboard/data").json()
    assert d["cleared_at"] == stamp and d["rows"] == []


def test_no_clear_means_null_watermark(tmp_path, monkeypatch):
    assert _app(tmp_path, monkeypatch).get("/dashboard/data").json()["cleared_at"] is None


def test_clear_dismisses_clarify_without_deleting(tmp_path, monkeypatch):
    pending, side = _seed_clarify(tmp_path)
    c = _app(tmp_path, monkeypatch)
    body = c.post(dash.CLEAR_ENDPOINT).json()
    assert body["dismissed_pending"] == 1 and body["dismissed_sidecars"] == 1
    assert pending.exists() and side.exists()
    assert json.loads(pending.read_text().splitlines()[0])["resolved_at"] is not None
    assert json.loads(side.read_text())["schedule"][0]["status"] == dash.STATUS_DISMISSED
    from homunculus_brain import capture_parsed
    assert capture_parsed.read_unresolved_clarifying(tmp_path) == []


def test_clear_is_idempotent_and_leaves_real_reminders_alone(tmp_path, monkeypatch):
    _seed_clarify(tmp_path)
    real = tmp_path / "_reminders" / "2026-11-03-0800-real.json"
    real.write_text(json.dumps({"event_id": "real", "schedule": [{"status": "pending", "kind": "t_minus_15"}]}))
    snapshot = real.read_bytes()
    c = _app(tmp_path, monkeypatch)
    c.post(dash.CLEAR_ENDPOINT)
    again = c.post(dash.CLEAR_ENDPOINT).json()
    assert again["dismissed_pending"] == 0 and again["dismissed_sidecars"] == 0
    assert real.read_bytes() == snapshot


def test_dismissed_sidecar_not_listed_upcoming(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from homunculus_brain import reminders
    _seed_clarify(tmp_path)
    _app(tmp_path, monkeypatch).post(dash.CLEAR_ENDPOINT)
    now = datetime.now(timezone.utc)
    rows = reminders._collect_clarify_notifications(
        tmp_path, events_from=now, window_end=now, include_fired=False)
    assert rows == []
