"""v7.0 Boundary Editor cleanup.

1. "Open in default slicer" is gone from the Editor and /api/generate_models never opens anything
   (the Plaque page keeps its own slicer option).
2. Parameters the audit found inert are gone from the page, the save/Generate payloads and the route:
   applyFringeFrameCap, the dead fringeEdgeHeight, and contour polygons in the Generate payload.
3. A legacy EGM that still carries every removed field loads, and generates identical geometry.
Temp copies and temp output only: never the live DB, live EGMs or course folders.
"""
import hashlib
import importlib.util
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

import pytest

APP_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(APP_DIR))
import app as app_module  # noqa: E402

EDITOR_SRC = (APP_DIR / "templates" / "editor.html").read_text()
PLAQUE_SRC = (APP_DIR / "templates" / "plaque.html").read_text()
APP_SRC = (APP_DIR / "app.py").read_text()
EDITOR_BODY = EDITOR_SRC.split("\n", 2)[2]          # everything after the changelog comment (line 2)
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "delaveaga_thomas_test4"
FIXTURE_EGM_NAME = "thomas_test4.egm"
GENERATE_ROUTE = "/api/generate_models"
PIPELINE_GENERATION_ID = "3f2b8c1e-9a47-4d6e-8b0c-5e7a1d2c4f90"
ROUTE_COURSE, ROUTE_HOLE = "FakeCourse", "01"
MODEL_PART = "3D/3dmodel.model"
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")   # 3MF writes random object UUIDs
UUID_PLACEHOLDER = "UUID"
COURSE_KEYS = ("images", "egms", "stls", "3mfs")

SLICER_EDITOR_MARKERS = ("openInSlicer", "open_in_slicer", "Open in default slicer", "slicer_opened", "slicer_error")
REMOVED_EDITOR_MARKERS = ("applyFringeFrameCap", "FRAME_CAP_ENABLED", "Cap fringe at frame height", "Fringe cap")
REMOVED_APP_CONSTANTS = ("KEY_OPEN_IN_SLICER", "KEY_SLICER_OPENED", "KEY_SLICER_ERROR", "MSG_SLICER_TIMEOUT",
                         "MSG_SLICER_EXIT_FMT", "SLICER_OPEN_COMMAND", "SLICER_OPEN_TIMEOUT_S", "KEY_APPLY_FRINGE_FRAME_CAP")
GENERATE_FN_START, GENERATE_FN_END = "async generateSTL()", "// flash(msg, ok, filename, durationMs)"
LEGACY_CAP_KEY = "applyFringeFrameCap"
REMOVED_CAP_KWARG = "apply_fringe_frame_cap"
LEGACY_REMOVED_FIELDS = {
    LEGACY_CAP_KEY: False,
    "fringeEdgeHeight": 9.0,
    "elevationSpikes": [{"x": 10, "y": 20, "mm": 5.0}],
    "gpsBackend": {"enabled": False, "gpsFile": "", "bbox": None, "approachM": 8.0, "vertExag": 3.0, "gridSize": [200, 200]},
    "courseGeoRef": {"imageWidth": 10, "imageHeight": 10, "swCornerLatLng": [36.0, -122.0], "neCornerLatLng": [36.1, -121.9]},
}


# ── 1. slicer control ───────────────────────────────────────────────────────
@pytest.mark.parametrize("marker", SLICER_EDITOR_MARKERS)
def test_editor_has_no_slicer_control(marker):
    assert marker not in EDITOR_BODY


def test_plaque_page_keeps_its_slicer_option():
    assert 'x-model="openInSlicer"' in PLAQUE_SRC
    assert "open_in_slicer: this.openInSlicer" in PLAQUE_SRC


def _generate_fn_src():
    return EDITOR_SRC[EDITOR_SRC.index(GENERATE_FN_START):EDITOR_SRC.index(GENERATE_FN_END)]


def test_generate_flash_logic_is_warnings_only():
    fn = _generate_fn_src()
    assert "const warns = result.warnings || [];" in fn
    assert "this.flash(msg, !warns.length," in fn


@pytest.fixture()
def route_env(tmp_path, monkeypatch):
    egm_dir = tmp_path / ROUTE_COURSE / app_module.COURSE_SUBDIR_EGMS
    egm_dir.mkdir(parents=True)
    out_3mf = tmp_path / "out.3mf"
    out_3mf.write_bytes(b"x")
    (egm_dir / f"{ROUTE_COURSE} (Hole {ROUTE_HOLE}).egm").write_text(json.dumps(
        {"course": ROUTE_COURSE, "hole": ROUTE_HOLE, "imageSize": {"width": 600, "height": 600}, "polygons": []}))
    monkeypatch.setattr(app_module, "_EGM_BASE", str(tmp_path))
    monkeypatch.setattr(app_module, "_validate_gps_prereqs", lambda _e: (True, ""))
    return out_3mf


def test_generate_route_opens_nothing_and_reports_no_slicer_keys(route_env):
    seen = {}

    def _fake_pipeline(egm_path, **kwargs):
        seen.update(kwargs)
        return str(route_env)

    import subprocess
    with patch("gradient_surface_diagnostic.run_pipeline", _fake_pipeline), \
            patch.object(subprocess, "run", side_effect=AssertionError("generate must not launch anything")) as spawned:
        resp = app_module.app.test_client().post(GENERATE_ROUTE, json={
            "course": ROUTE_COURSE, "hole": ROUTE_HOLE, "open_in_slicer": True, LEGACY_CAP_KEY: False})
    body = resp.get_json()
    assert body[app_module.KEY_STATUS] == app_module.STATUS_OK
    assert not spawned.called
    assert not [k for k in body if "slicer" in k]
    assert REMOVED_CAP_KWARG not in seen        # the route no longer forwards the inert flag


@pytest.mark.parametrize("name", REMOVED_APP_CONSTANTS)
def test_unreferenced_app_constants_deleted(name):
    assert not re.search(r"^%s\b" % name, APP_SRC, re.M)


# ── 2. removed fields: page + payloads ──────────────────────────────────────
@pytest.mark.parametrize("marker", REMOVED_EDITOR_MARKERS)
def test_removed_markers_absent_from_editor(marker):
    assert marker not in EDITOR_BODY


def test_fringe_edge_height_not_in_editor_or_route():
    assert "fringeEdgeHeight" not in EDITOR_BODY
    assert "fringeEdgeHeight" not in APP_SRC


def test_generate_payload_has_no_contour_polygons():
    fn = _generate_fn_src()
    assert "'contour'" not in fn and "this.contours" not in fn
    assert "polygons: allPolygons" in fn      # closed boundary polygons are still sent


def test_editor_version_line_tracks_app_version():
    assert app_module.APP_VERSION in EDITOR_SRC.split("\n", 2)[1]
    major, minor = (int(x) for x in app_module.APP_VERSION.lstrip("v").split("."))
    assert (major, minor) >= (7, 0)


# ── 3. legacy EGM still opens ───────────────────────────────────────────────
def test_legacy_egm_with_all_removed_fields_still_loads(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DB_PATH", str(tmp_path / "workspace.db"))
    monkeypatch.setattr(app_module, "_EGM_BASE", str(tmp_path / "GolfCourses"))
    egm = json.loads((FIXTURE_DIR / FIXTURE_EGM_NAME).read_text())
    egm.update(LEGACY_REMOVED_FIELDS)
    p = tmp_path / "legacy.egm"
    p.write_text(json.dumps(egm))
    app_module.app.config["TESTING"] = True
    r = app_module.app.test_client().get(
        app_module.ROUTE_API_BOUNDARIES_LOAD_PATH + "?" + app_module.QUERY_PATH + "=" + quote(str(p), safe=""))
    assert r.status_code == 200
    assert r.get_json()[app_module.KEY_STATUS] == app_module.STATUS_OK


# ── 4. geometry identical before/after (temp COPY of the fixture) ───────────
@pytest.fixture()
def pipeline(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("gsd_cleanup_v70", APP_DIR / "gradient_surface_diagnostic.py")
    g = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = g
    spec.loader.exec_module(g)
    out = tmp_path / "out"
    paths = {k: str(out / k) for k in COURSE_KEYS}
    paths[g.PATH_KEY_IMAGES] = str(FIXTURE_DIR)
    for p in paths.values():
        Path(p).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(g, "course_paths", lambda _c: paths)
    monkeypatch.setattr(g, "DIAGNOSTICS_DIR", str(out / "diag"))

    def _geometry_digest(egm_overrides, **kwargs):
        egm = json.loads((FIXTURE_DIR / FIXTURE_EGM_NAME).read_text())
        egm.update(egm_overrides)
        copy = tmp_path / f"copy_{len(list(tmp_path.glob('copy_*')))}.egm"
        copy.write_text(json.dumps(egm))
        path = g.run_pipeline(str(copy), generation_id=PIPELINE_GENERATION_ID, **kwargs)
        with zipfile.ZipFile(path) as z:
            model = UUID_RE.sub(UUID_PLACEHOLDER, z.read(MODEL_PART).decode())
        return hashlib.sha256(model.encode()).hexdigest()
    return _geometry_digest


def test_geometry_identical_with_and_without_the_legacy_cap_key(pipeline):
    plain = pipeline({})
    legacy_off = pipeline(LEGACY_REMOVED_FIELDS)                       # EGM carrying every removed field, cap key False
    legacy_on = pipeline({LEGACY_CAP_KEY: True})
    stripped = pipeline({LEGACY_CAP_KEY: None})                        # key present but unusable
    assert plain == legacy_off == legacy_on == stripped


def test_pipeline_no_longer_accepts_the_cap_kwarg():
    import inspect
    spec = importlib.util.spec_from_file_location("gsd_sig_v70", APP_DIR / "gradient_surface_diagnostic.py")
    g = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = g
    spec.loader.exec_module(g)
    assert REMOVED_CAP_KWARG not in inspect.signature(g.run_pipeline).parameters
