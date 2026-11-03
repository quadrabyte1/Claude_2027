"""
test_interrupt_safe_scan.py — V3.33: an interrupted / failed / orphaned scan must
not wipe titles, matches or the NEW-since-last-scan baseline; the reloader is off.

Temp DB paths only, no network, never the live scanner.db. Values come from
production constants (or are defined once here).
"""

import os
import runpy
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from movie_scanner import scanner as scanner_mod  # noqa: E402
from movie_scanner.scanner import Scanner, ELIMINATIONS_TABLE  # noqa: E402
from movie_scanner.schema import apply_schema  # noqa: E402
from .test_plot_filter import _make_app  # noqa: E402

OLD_TCONSTS = ("tt0000001", "tt0000002", "tt0000003")
BASELINE_TCONSTS = ("tt0000001", "tt0000002")
OLD_ELIM_TCONST = "tt0000009"
OLD_ELIM_REASON = "year:1999<2026"
NEW_TCONST = "tt7000001"
NEW_TITLE = "Brand New Movie"
NEW_YEAR = 2026
NEW_RATING = 8.5
NEW_VOTES = 5000
NEW_GENRES = "Drama"
NEW_ROW = (NEW_TCONST, "movie", NEW_TITLE, NEW_YEAR, 100, NEW_GENRES)
NEW_MATCH_ROW = (NEW_TCONST, NEW_TITLE, NEW_YEAR, "movie", NEW_RATING, NEW_VOTES,
                 NEW_GENRES, "drama", 1)
DUMMY_PATHS = ("basics.gz", "ratings.gz", "episodes.gz")
BOOM = "boom: simulated failure"
FRESH_STATUS = "done"


def _seed(tmp_path: Path) -> str:
    db_path = str(tmp_path / "scanner.db")
    conn = sqlite3.connect(db_path)
    apply_schema(conn)
    run_id = conn.execute(
        "INSERT INTO runs (status, phase) VALUES ('done', 'done')").lastrowid
    for t in OLD_TCONSTS:
        conn.execute("INSERT INTO titles (tconst, title_type, primary_title) VALUES (?, 'movie', 'Old')", (t,))
        conn.execute("INSERT INTO matches (tconst, primary_title, title_type, rating, num_votes, genres, matched_tags, run_id) VALUES (?, 'Old', 'movie', 8.0, 1000, 'Drama', 'drama', ?)", (t, run_id))
    for t in BASELINE_TCONSTS:
        conn.execute("INSERT INTO previous_match_tconsts (tconst) VALUES (?)", (t,))
    conn.execute(f"INSERT INTO {ELIMINATIONS_TABLE} (tconst, primary_title, reason) VALUES (?, 'x', ?)",
                 (OLD_ELIM_TCONST, OLD_ELIM_REASON))
    conn.commit()
    conn.close()
    return db_path


def _state(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    out = {
        "titles": sorted(r[0] for r in conn.execute("SELECT tconst FROM titles")),
        "matches": sorted(r[0] for r in conn.execute("SELECT tconst FROM matches")),
        "baseline": sorted(r[0] for r in conn.execute("SELECT tconst FROM previous_match_tconsts")),
        "elims": sorted(r[0] for r in conn.execute(f"SELECT tconst FROM {ELIMINATIONS_TABLE}")),
    }
    conn.close()
    return out


def _run_scan(db_path: str, basics, match_rows=None):
    """Run a replace-mode scan with all file/network inputs stubbed."""
    s = Scanner(db_path=db_path, data_dir=str(Path(db_path).parent / "data"))
    patches = [
        patch.object(scanner_mod, "fetch_dumps", return_value=DUMMY_PATHS),
        patch.object(scanner_mod, "_load_ratings",
                     return_value={NEW_TCONST: (NEW_RATING, NEW_VOTES)}),
        patch.object(scanner_mod, "_seasons_cache_key", return_value="k"),
        patch.object(scanner_mod, "_load_episode_years", return_value={}),
        patch.object(scanner_mod, "_iter_episodes", return_value=iter(())),
        patch.object(scanner_mod, "_iter_basics", basics),
    ]
    if match_rows is not None:
        patches.append(patch.object(Scanner, "_apply_plot_filter",
                                    return_value=(match_rows, 0)))
        patches.append(patch.object(Scanner, "_apply_theaters_filter",
                                    return_value=(match_rows, 0)))
    for p in patches:
        p.start()
    try:
        return s.scan(replace_existing=True)
    finally:
        for p in patches:
            p.stop()


def _raise_mid_diff(*_a, **_k):
    yield NEW_ROW
    raise RuntimeError(BOOM)


def test_a_scan_raising_mid_diff_leaves_data_intact(tmp_path):
    db = _seed(tmp_path)
    before = _state(db)
    try:
        _run_scan(db, _raise_mid_diff)
    except RuntimeError as e:
        assert BOOM in str(e)
    else:
        raise AssertionError("scan should have raised")
    after = _state(db)
    assert after == before
    assert before["titles"] and before["matches"] and before["baseline"]


def test_a2_scan_failing_during_persist_rolls_back_everything(tmp_path):
    db = _seed(tmp_path)
    before = _state(db)
    conn = sqlite3.connect(db)
    conn.execute(f"CREATE TRIGGER boom BEFORE INSERT ON matches "
                 f"BEGIN SELECT RAISE(ABORT, '{BOOM}'); END")
    conn.commit()
    conn.close()
    try:
        _run_scan(db, lambda *_a, **_k: iter([NEW_ROW]), match_rows=[NEW_MATCH_ROW])
    except Exception as e:
        assert BOOM in str(e)
    else:
        raise AssertionError("scan should have raised")
    assert _state(db) == before


def test_successful_scan_swaps_in_atomically_and_snapshots_baseline(tmp_path):
    db = _seed(tmp_path)
    old_matches = _state(db)["matches"]
    summary = _run_scan(db, lambda *_a, **_k: iter([NEW_ROW]), match_rows=[NEW_MATCH_ROW])
    assert summary["matches"] == 1
    after = _state(db)
    assert after["titles"] == [NEW_TCONST]
    assert after["matches"] == [NEW_TCONST]
    assert after["baseline"] == sorted(old_matches)   # outgoing matches become baseline
    assert OLD_ELIM_TCONST not in after["elims"]       # stale eliminations replaced
    conn = sqlite3.connect(db)
    status = conn.execute("SELECT status FROM runs ORDER BY id DESC LIMIT 1").fetchone()[0]
    conn.close()
    assert status == FRESH_STATUS


def test_empty_result_never_overwrites_baseline_with_empty_snapshot(tmp_path):
    db = _seed(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM matches")   # outgoing state has no matches
    conn.commit()
    conn.close()
    baseline_before = _state(db)["baseline"]
    _run_scan(db, lambda *_a, **_k: iter([NEW_ROW]), match_rows=[])
    assert _state(db)["baseline"] == baseline_before


def test_b_orphaned_run_reconciled_at_startup_leaves_data_intact(tmp_path):
    db = _seed(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO runs (status, phase) VALUES ('running', 'diffing basics')")
    conn.commit()
    conn.close()
    before = _state(db)
    ms_app, _client, db_path = _make_app(tmp_path)   # import runs _reconcile_orphaned_runs()
    assert db_path == db
    assert _state(db) == before
    conn = sqlite3.connect(db)
    statuses = [r[0] for r in conn.execute("SELECT status FROM runs WHERE phase='diffing basics'")]
    conn.close()
    assert statuses == ["error"]


def test_run_route_does_not_wipe_live_tables(tmp_path):
    db = _seed(tmp_path)
    before = _state(db)
    ms_app, client, _ = _make_app(tmp_path)
    with patch.object(ms_app, "_spawn_scan_worker"):
        client.post("/run", data={})
    assert _state(db) == before


def test_c_reloader_constant_false_and_passed_to_app_run(tmp_path):
    ms_app, _client, _ = _make_app(tmp_path)
    assert ms_app.USE_RELOADER is False
    captured = {}
    with patch("flask.Flask.run", lambda self, *a, **kw: captured.update(kw)):
        runpy.run_path(ms_app.__file__, run_name="__main__")
    assert captured["use_reloader"] is ms_app.USE_RELOADER
    assert captured["debug"] is ms_app.DEBUG_MODE


MIN_VERSION = (3, 33)  # this feature shipped in V3.33; later versions are fine


def test_version_bumped():
    import re
    src = Path(__file__).resolve().parents[1].joinpath("app.py").read_text()
    m = re.search(r'^APP_VERSION = "V(\d+)\.(\d+)"', src, re.M)
    assert m and (int(m.group(1)), int(m.group(2))) >= MIN_VERSION
