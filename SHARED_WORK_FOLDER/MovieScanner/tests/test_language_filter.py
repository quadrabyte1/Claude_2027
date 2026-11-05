"""
test_language_filter.py — V3.35: "Exclude languages" filter (mirrors countries).

All DB work uses a tmp_path DB; the live scanner.db is never touched.
Constants are imported from production code, never re-typed.
"""
import json
import os
import sqlite3
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from movie_scanner.config import ScanConfig
from movie_scanner.scanner import (
    CONFIG_KEY_EXCLUDE_LANGUAGES,
    ELIMINATIONS_TABLE,
    REASON_LANGUAGE_PREFIX,
    Scanner,
    first_excluded_match,
)
from movie_scanner.schema import apply_schema

# ── Test fixtures (data only; behaviour constants come from production) ──
LANG_HINDI = "hindi"
LANG_ENGLISH = "english"
OMDB_HINDI_ONLY = "Hindi"
OMDB_MULTI = "English, Hindi, Tamil"
OMDB_FRENCH = "French"
OMDB_MIXED_CASE_EXCLUDE = "HINDI"
TCONST_SAMPLE = "tt0000001"
TITLE_SAMPLE = "Sample Title"


def _lower(items):
    return [i.strip().lower() for i in items if i.strip()]


class TestFirstExcludedMatch:
    def test_hindi_title_dropped(self):
        assert first_excluded_match([LANG_HINDI], OMDB_HINDI_ONLY) == LANG_HINDI

    def test_multi_language_title_dropped(self):
        assert first_excluded_match([LANG_HINDI], OMDB_MULTI) == LANG_HINDI

    def test_unrelated_title_kept(self):
        assert first_excluded_match([LANG_HINDI], OMDB_FRENCH) is None

    def test_empty_list_is_no_filter(self):
        assert first_excluded_match([], OMDB_HINDI_ONLY) is None

    def test_missing_omdb_value_kept(self):
        assert first_excluded_match([LANG_HINDI], None) is None
        assert first_excluded_match([LANG_HINDI], "") is None

    def test_case_insensitive(self):
        excl = _lower([OMDB_MIXED_CASE_EXCLUDE])
        assert first_excluded_match(excl, OMDB_HINDI_ONLY) == LANG_HINDI


def _db(tmp_path):
    path = str(tmp_path / "scanner.db")
    conn = sqlite3.connect(path)
    apply_schema(conn)
    conn.commit()
    conn.close()
    return path


class TestConfigAndReason:
    def test_default_config_row_exists(self, tmp_path):
        path = _db(tmp_path)
        conn = sqlite3.connect(path)
        row = conn.execute(
            "SELECT value FROM config WHERE key=?", (CONFIG_KEY_EXCLUDE_LANGUAGES,)
        ).fetchone()
        conn.close()
        assert row is not None and json.loads(row[0]) == []

    def test_scanconfig_field_defaults_empty(self):
        assert ScanConfig().exclude_languages == []

    def test_config_loaded_from_db(self, tmp_path):
        path = _db(tmp_path)
        conn = sqlite3.connect(path)
        conn.execute(
            "UPDATE config SET value=? WHERE key=?",
            (json.dumps([OMDB_HINDI_ONLY]), CONFIG_KEY_EXCLUDE_LANGUAGES),
        )
        conn.commit()
        conn.close()
        scanner = Scanner(db_path=path)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        cfg, _ = scanner._resolve_config(conn)
        conn.close()
        assert cfg.exclude_languages == [OMDB_HINDI_ONLY]

    def test_elimination_reason_recorded(self, tmp_path):
        path = _db(tmp_path)
        scanner = Scanner(db_path=path)
        scanner._record_elimination(
            tconst=TCONST_SAMPLE,
            primary_title=TITLE_SAMPLE,
            reason=f"{REASON_LANGUAGE_PREFIX}{LANG_HINDI}",
        )
        conn = sqlite3.connect(path)
        reason = conn.execute(
            f"SELECT reason FROM {ELIMINATIONS_TABLE} WHERE tconst=?", (TCONST_SAMPLE,)
        ).fetchone()[0]
        conn.close()
        assert reason == REASON_LANGUAGE_PREFIX + LANG_HINDI
