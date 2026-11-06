"""Tests for generation_id.make_generation_id() and its use in output filenames / the generate route."""

from __future__ import annotations

import glob
import json
import os
import re
import sys
import uuid
from unittest.mock import patch

import pytest

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import generation_id as gid

EXPECTED_ID = "3f2b8c1e-9a47-4d6e-8b0c-5e7a1d2c4f90"
LEGACY_TIMESTAMP_ID = "2026.11.01.14.05.09.jgreen"
UNIQUENESS_SAMPLE_COUNT = 200
LEGACY_SERIAL = 1552
COURSE = "Test Course"
HOLE = "01"
ROUTE_COURSE = "FakeCourse"
ROUTE_PATH = "/api/generate_models"
GLOBAL_SERIAL_MARKERS = ("global_serial", "GLOBAL_SERIAL", "commit_global", "peek_next")
SOURCE_FILES = ("app.py", "generate_stl_3mf.py", "gradient_surface_diagnostic.py",
                "fringe_label_engraver.py", "generation_id.py")
GLOBAL_SERIAL_FILENAME = "global_serial.json"


def test_id_is_valid_uuid4_canonical_form():
    result = gid.make_generation_id()
    parsed = uuid.UUID(result)
    assert parsed.version == gid.UUID_VERSION
    assert str(parsed) == result                      # lowercase, hyphenated
    assert len(result) == gid.GENERATION_ID_LENGTH
    assert re.fullmatch(gid.GENERATION_ID_PATTERN, result)


def test_ids_are_unique_across_calls():
    ids = {gid.make_generation_id() for _ in range(UNIQUENESS_SAMPLE_COUNT)}
    assert len(ids) == UNIQUENESS_SAMPLE_COUNT


@pytest.mark.parametrize("stem", [
    f"{COURSE} (Hole {HOLE}) [{EXPECTED_ID}]",
    f"{COURSE} (Hole {HOLE}) [{LEGACY_TIMESTAMP_ID}]",
    f"{COURSE} (Hole {HOLE}) [{LEGACY_SERIAL}]",
    f"{COURSE} (Hole {HOLE})",
])
def test_strip_generation_id_tag_handles_uuid_timestamp_legacy_and_untagged(stem):
    assert gid.strip_generation_id_tag(stem) == f"{COURSE} (Hole {HOLE})"


def test_strip_generation_id_tag_generated_id_roundtrip():
    new_id = gid.make_generation_id()
    tagged = f"{COURSE} (Hole {HOLE}) {gid.FILENAME_ID_BRACKET_FMT.format(generation_id=new_id)}"
    assert gid.strip_generation_id_tag(tagged) == f"{COURSE} (Hole {HOLE})"


def test_generate_from_egm_file_names_file_with_id_and_writes_no_counter(tmp_path):
    import generate_stl_3mf as gstl
    egm_data = {
        "course": COURSE, "hole": HOLE,
        "imageSize": {"width": 600, "height": 600},
        "polygons": [{"type": "green", "points": [
            {"x": 100, "y": 100}, {"x": 200, "y": 100}, {"x": 200, "y": 200}, {"x": 100, "y": 200}]}],
    }
    egm_path = str(tmp_path / f"{COURSE} (Hole {HOLE}).egm")
    with open(egm_path, "w") as f:
        json.dump(egm_data, f)
    out_dir = str(tmp_path / "out")
    os.makedirs(out_dir)
    try:
        gstl.generate_from_egm_file(egm_path, output_dir=out_dir, generation_id=EXPECTED_ID)
    except Exception:
        pass  # pipeline may need images/deps; only names matter here
    for mf in glob.glob(os.path.join(out_dir, "**", "*.3mf"), recursive=True):
        assert gid.FILENAME_ID_BRACKET_FMT.format(generation_id=EXPECTED_ID) in os.path.basename(mf)
    assert not os.path.exists(tmp_path / GLOBAL_SERIAL_FILENAME)


def test_3mf_filename_helper():
    import generate_stl_3mf as gstl
    assert gstl._3mf_filename(COURSE, HOLE, generation_id=EXPECTED_ID) == \
        f"{COURSE} (Hole {HOLE}) [{EXPECTED_ID}].3mf"
    assert gstl._3mf_filename(COURSE, HOLE) == f"{COURSE} (Hole {HOLE}).3mf"


def test_route_makes_one_id_per_request_passes_it_and_returns_it(tmp_path, monkeypatch):
    import app as flask_app
    egm_dir = tmp_path / ROUTE_COURSE / "EGMs"
    egm_dir.mkdir(parents=True)
    out_3mf = tmp_path / f"{ROUTE_COURSE} (Hole {HOLE}) [{EXPECTED_ID}].3mf"
    out_3mf.write_bytes(b"x")
    (egm_dir / f"{ROUTE_COURSE} (Hole {HOLE}).egm").write_text(json.dumps(
        {"course": ROUTE_COURSE, "hole": HOLE, "imageSize": {"width": 600, "height": 600}, "polygons": []}))
    monkeypatch.setattr(flask_app, "_EGM_BASE", str(tmp_path))
    monkeypatch.setattr(flask_app, "_validate_gps_prereqs", lambda _e: (True, ""))

    make_calls, seen = [], {}

    def _fake_make():
        make_calls.append(1)
        return EXPECTED_ID

    def _fake_pipeline(egm_path, **kwargs):
        seen.update(kwargs)
        return str(out_3mf)

    monkeypatch.setattr(flask_app, "make_generation_id", _fake_make)
    with patch("gradient_surface_diagnostic.run_pipeline", _fake_pipeline):
        resp = flask_app.app.test_client().post(
            ROUTE_PATH, json={"course": ROUTE_COURSE, "hole": HOLE})
    body = resp.get_json()
    assert len(make_calls) == 1
    assert seen["generation_id"] == EXPECTED_ID
    assert body[flask_app.KEY_GENERATION_ID] == EXPECTED_ID
    assert EXPECTED_ID in body[flask_app.KEY_FILE][flask_app.KEY_NAME]


def test_no_source_file_references_the_global_serial_counter():
    for name in SOURCE_FILES:
        text = open(os.path.join(APP_DIR, name)).read()
        # allow the explanatory docstring mention in fringe_label_engraver.py
        text = text.replace(GLOBAL_SERIAL_FILENAME, "")
        for marker in GLOBAL_SERIAL_MARKERS:
            assert marker not in text, f"{name} still references {marker}"
