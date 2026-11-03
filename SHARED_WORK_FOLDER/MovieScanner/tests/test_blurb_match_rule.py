"""
test_blurb_match_rule.py — V3.30: a title is a match only if its hover blurb
(OMDb plot) was successfully fetched.

Network is always mocked (urllib.request.urlopen patched); DBs are temp paths.
Every marker/reason/label is imported from production code, never re-typed.
"""

import os
import sqlite3
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from movie_scanner.omdb import OMDbClient, KEY_TRANSIENT, ERROR_NETWORK_PREFIX  # noqa: E402
from movie_scanner.scanner import (  # noqa: E402
    Scanner, REASON_PLOT_MISSING, REASON_PLOT_FETCH_FAILED, REASON_PLOT_NO_API_KEY,
)
from movie_scanner.schema import apply_schema  # noqa: E402
from .test_plot_filter import _make_app, _make_omdb_response  # noqa: E402

TEST_KEY = "test-key"
PLOT_TEXT = "A real blurb."
TCONST = "tt9000001"
MATCH_ROW = (TCONST, "Otherwise Matching Movie", 2026, "movie", 8.0, 1000, "Drama", "drama", 1)
TIMEOUT_ERR = urllib.error.URLError("timed out")


def _db(tmp_path: Path, with_key: bool = True) -> str:
    db_path = str(tmp_path / "scanner.db")
    conn = sqlite3.connect(db_path)
    apply_schema(conn)
    if with_key:
        conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('omdb_api_key', ?)", (TEST_KEY,))
    conn.commit()
    conn.close()
    return db_path


def _run_filter(db_path: str, urlopen_kwargs: dict):
    with patch("urllib.request.urlopen", **urlopen_kwargs) as m:
        kept, dropped = Scanner(db_path=db_path)._apply_plot_filter(
            db_path=db_path, match_rows=[MATCH_ROW], on_progress=lambda _: None)
    return kept, dropped, m


def _reasons(db_path: str) -> list[str]:
    conn = sqlite3.connect(db_path)
    rows = [r[0] for r in conn.execute("SELECT reason FROM scan_eliminations")]
    conn.close()
    return rows


def _cache_rows(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM title_metadata").fetchone()[0]
    conn.close()
    return n


def test_blurb_ok_is_match(tmp_path):
    db = _db(tmp_path)
    kept, dropped, _ = _run_filter(db, {"return_value": _make_omdb_response(PLOT_TEXT)})
    assert kept == [MATCH_ROW] and dropped == 0


def test_blurb_fetch_error_is_not_match_and_not_cached(tmp_path):
    db = _db(tmp_path)
    kept, dropped, _ = _run_filter(db, {"side_effect": TIMEOUT_ERR})
    assert kept == [] and dropped == 1
    assert _reasons(db) == [REASON_PLOT_FETCH_FAILED]
    assert _cache_rows(db) == 0  # transient: nothing cached


def test_transient_failure_succeeds_on_later_scan(tmp_path):
    db = _db(tmp_path)
    _run_filter(db, {"side_effect": TIMEOUT_ERR})
    kept, _, _ = _run_filter(db, {"return_value": _make_omdb_response(PLOT_TEXT)})
    assert kept == [MATCH_ROW]


def test_definite_not_found_is_not_match_and_cached(tmp_path):
    db = _db(tmp_path)
    kept, _, _ = _run_filter(db, {"return_value": _make_omdb_response(None, response_ok=False)})
    assert kept == []
    assert _reasons(db) == [REASON_PLOT_MISSING]
    assert _cache_rows(db) == 1
    _, _, m = _run_filter(db, {"side_effect": AssertionError("must not hit network")})
    m.assert_not_called()


def test_legacy_cached_transient_error_is_refetched(tmp_path):
    db = _db(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO title_metadata (tconst, plot, error) VALUES (?, NULL, ?)",
                 (TCONST, f"{ERROR_NETWORK_PREFIX}timed out"))
    conn.commit()
    conn.close()
    kept, _, _ = _run_filter(db, {"return_value": _make_omdb_response(PLOT_TEXT)})
    assert kept == [MATCH_ROW]


def test_fetch_result_flags_transient(tmp_path):
    db = _db(tmp_path)
    with patch("urllib.request.urlopen", side_effect=TIMEOUT_ERR):
        assert OMDbClient(TEST_KEY, db).fetch(TCONST)[KEY_TRANSIENT] is True


def test_no_api_key_is_not_match(tmp_path):
    db = _db(tmp_path, with_key=False)
    kept, dropped, m = _run_filter(db, {"side_effect": AssertionError("no network")})
    assert kept == [] and dropped == 1
    assert _reasons(db) == [REASON_PLOT_NO_API_KEY]
    m.assert_not_called()


def test_index_shows_blurb_exclusion_note(tmp_path):
    ms_app, client, db_path = _make_app(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO scan_eliminations (tconst, primary_title, reason) VALUES (?, 'X', ?)",
                 (TCONST, REASON_PLOT_FETCH_FAILED))
    conn.commit()
    conn.close()
    html = client.get("/").get_data(as_text=True)
    assert ms_app.BLURB_NOTE_ID in html
    assert ms_app.BLURB_NOTE_LABEL in html


MIN_VERSION = (3, 30)  # blurb rule shipped in V3.30; later versions are fine


def test_version_bumped():
    import app as ms_app  # noqa
    major, minor = ms_app.APP_VERSION.lstrip("V").split(".")
    assert (int(major), int(minor)) >= MIN_VERSION
