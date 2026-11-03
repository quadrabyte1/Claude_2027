"""
test_omdb_key_field.py — V3.34: OMDb API key entry on the main page.

Network is mocked (urllib.request.urlopen patched); DBs are temp paths.
Every route/field/status/message is read from the production module.
"""
import json
import re
import sqlite3
import urllib.error
from unittest.mock import MagicMock, patch

from .test_plot_filter import _make_app, _seed_omdb_key

SECRET_KEY = "SECRETKEY123456"
OTHER_KEY = "OTHERKEY98765432"
BARE_DISABLED_RE = r"\sdisabled(\s|$)"  # attribute, not a tailwind disabled: class
FIELD_MIN_RATING = "min_rating"
MIN_RATING_VALUE = "8.1"
NETWORK_REASON = "timed out"
HTTP_UNAUTHORIZED = 401


def _stored(db_path: str):
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT value FROM config WHERE key=?", ("omdb_api_key",)).fetchone()
    conn.close()
    return row[0] if row else None


def _resp(payload: dict):
    m = MagicMock()
    m.read.return_value = json.dumps(payload).encode("utf-8")
    m.__enter__.return_value = m
    return m


def _test_key(ms_app, client, **body):
    return client.post(ms_app.OMDB_TEST_KEY_ROUTE, json=body).get_json()


# ── save semantics ─────────────────────────────────────────────────────────

def test_save_stores_submitted_key(tmp_path):
    ms_app, client, db = _make_app(tmp_path)
    client.post("/config", data={ms_app.OMDB_KEY_FORM_FIELD: SECRET_KEY})
    assert _stored(db) == SECRET_KEY


def test_blank_submit_keeps_existing_key(tmp_path):
    ms_app, client, db = _make_app(tmp_path)
    _seed_omdb_key(db, SECRET_KEY)
    client.post("/config", data={FIELD_MIN_RATING: MIN_RATING_VALUE, ms_app.OMDB_KEY_FORM_FIELD: ""})
    assert _stored(db) == SECRET_KEY
    client.post("/config", data={FIELD_MIN_RATING: MIN_RATING_VALUE})  # field absent
    assert _stored(db) == SECRET_KEY


def test_new_key_replaces_old(tmp_path):
    ms_app, client, db = _make_app(tmp_path)
    _seed_omdb_key(db, SECRET_KEY)
    client.post("/config", data={ms_app.OMDB_KEY_FORM_FIELD: OTHER_KEY})
    assert _stored(db) == OTHER_KEY


def test_explicit_clear_removes_key(tmp_path):
    ms_app, client, db = _make_app(tmp_path)
    _seed_omdb_key(db, SECRET_KEY)
    client.post("/config", data={ms_app.OMDB_KEY_CLEAR_FIELD: "1"})
    assert not _stored(db)


# ── rendering ──────────────────────────────────────────────────────────────

def test_full_key_never_in_html_only_hint(tmp_path):
    ms_app, client, db = _make_app(tmp_path)
    _seed_omdb_key(db, SECRET_KEY)
    html = client.get("/").get_data(as_text=True)
    assert SECRET_KEY not in html
    assert SECRET_KEY[-ms_app.OMDB_KEY_HINT_CHARS:] in html
    assert ms_app.OMDB_KEY_SAVED_LABEL in html


def test_status_endpoint_masks_key(tmp_path):
    ms_app, client, db = _make_app(tmp_path)
    _seed_omdb_key(db, SECRET_KEY)
    body = client.get(ms_app.OMDB_KEY_STATUS_ROUTE).get_data(as_text=True)
    assert SECRET_KEY not in body
    assert json.loads(body)["saved"] is True


def test_no_key_shows_not_saved_and_disabled_run_button(tmp_path):
    ms_app, client, db = _make_app(tmp_path)
    html = client.get("/").get_data(as_text=True)
    assert ms_app.OMDB_KEY_SAVED_LABEL not in html
    assert ms_app.RUN_BUTTON_ID in html
    assert ms_app.RUN_DISABLED_TOOLTIP in html
    btn = html[html.index('id="%s"' % ms_app.RUN_BUTTON_ID):]
    btn = btn[:btn.index(">")]
    assert re.search(BARE_DISABLED_RE, btn)


def test_with_key_run_button_enabled(tmp_path):
    ms_app, client, db = _make_app(tmp_path)
    _seed_omdb_key(db, SECRET_KEY)
    html = client.get("/").get_data(as_text=True)
    btn = html[html.index('id="%s"' % ms_app.RUN_BUTTON_ID):]
    btn = btn[:btn.index(">")]
    assert not re.search(BARE_DISABLED_RE, btn)


def test_helper_text_present(tmp_path):
    ms_app, client, db = _make_app(tmp_path)
    html = client.get("/").get_data(as_text=True)
    assert ms_app.OMDB_HELPER_TEXT in html


def test_integrity_banner_stops_once_key_saved(tmp_path):
    ms_app, client, db = _make_app(tmp_path)
    client.post("/config", data={ms_app.OMDB_KEY_FORM_FIELD: SECRET_KEY, FIELD_MIN_RATING: MIN_RATING_VALUE})
    html = client.get("/").get_data(as_text=True)
    assert "Config appears reset" not in html


# ── /run guard ─────────────────────────────────────────────────────────────

def test_run_without_key_does_not_spawn_scan(tmp_path):
    ms_app, client, db = _make_app(tmp_path)
    with patch.object(ms_app, "_spawn_scan_worker") as spawn:
        client.post("/run", data={})
    spawn.assert_not_called()


def test_run_with_key_spawns_scan(tmp_path):
    ms_app, client, db = _make_app(tmp_path)
    _seed_omdb_key(db, SECRET_KEY)
    with patch.object(ms_app, "_spawn_scan_worker") as spawn:
        client.post("/run", data={})
    spawn.assert_called_once()


# ── test-key endpoint ──────────────────────────────────────────────────────

def test_key_ok(tmp_path):
    ms_app, client, db = _make_app(tmp_path)
    with patch("urllib.request.urlopen", return_value=_resp({"Response": "True", "Title": "X", "Plot": "p"})) as m:
        out = _test_key(ms_app, client, key=SECRET_KEY)
    assert out["status"] == ms_app.KEY_STATUS_OK
    assert m.call_count == 1
    assert ms_app.OMDB_TEST_TCONST in m.call_args[0][0].full_url


def test_key_invalid_or_unactivated(tmp_path):
    ms_app, client, db = _make_app(tmp_path)
    with patch("urllib.request.urlopen", return_value=_resp({"Response": "False", "Error": "Invalid API key!"})):
        out = _test_key(ms_app, client, key=SECRET_KEY)
    assert out["status"] == ms_app.KEY_STATUS_INVALID
    assert "activation" in out["message"].lower()


def test_key_invalid_via_http_401(tmp_path):
    ms_app, client, db = _make_app(tmp_path)
    err = urllib.error.HTTPError("http://x", HTTP_UNAUTHORIZED, "Unauthorized", {}, None)
    with patch("urllib.request.urlopen", side_effect=err):
        out = _test_key(ms_app, client, key=SECRET_KEY)
    assert out["status"] == ms_app.KEY_STATUS_INVALID


def test_key_network_error(tmp_path):
    ms_app, client, db = _make_app(tmp_path)
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError(NETWORK_REASON)):
        out = _test_key(ms_app, client, key=SECRET_KEY)
    assert out["status"] == ms_app.KEY_STATUS_NETWORK


def test_key_rate_limited(tmp_path):
    ms_app, client, db = _make_app(tmp_path)
    with patch("urllib.request.urlopen", return_value=_resp({"Response": "False", "Error": "Request limit reached!"})):
        out = _test_key(ms_app, client, key=SECRET_KEY)
    assert out["status"] == ms_app.KEY_STATUS_RATE_LIMITED


def test_blank_test_uses_stored_key_and_no_key_makes_no_request(tmp_path):
    ms_app, client, db = _make_app(tmp_path)
    with patch("urllib.request.urlopen") as m:
        out = _test_key(ms_app, client, key="")
    assert out["status"] == ms_app.KEY_STATUS_MISSING
    m.assert_not_called()
    _seed_omdb_key(db, SECRET_KEY)
    with patch("urllib.request.urlopen", return_value=_resp({"Response": "True"})) as m:
        out = _test_key(ms_app, client, key="")
    assert out["status"] == ms_app.KEY_STATUS_OK
    assert SECRET_KEY in m.call_args[0][0].full_url


def test_response_never_echoes_key(tmp_path):
    ms_app, client, db = _make_app(tmp_path)
    with patch("urllib.request.urlopen", return_value=_resp({"Response": "False", "Error": "Invalid API key!"})):
        raw = client.post(ms_app.OMDB_TEST_KEY_ROUTE, json={"key": SECRET_KEY}).get_data(as_text=True)
    assert SECRET_KEY not in raw


def test_export_includes_key(tmp_path):
    ms_app, client, db = _make_app(tmp_path)
    _seed_omdb_key(db, SECRET_KEY)
    data = json.loads(client.get("/config/export").get_data(as_text=True))
    assert data["config"]["omdb_api_key"] == SECRET_KEY
