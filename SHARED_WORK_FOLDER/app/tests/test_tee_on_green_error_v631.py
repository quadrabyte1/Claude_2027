"""v6.31: a tee hole on the green is a hard Generate error (pop-up), never a silent skip."""
from __future__ import annotations

import os
import sys

import pytest
from shapely.geometry import Polygon

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import app as app_module  # noqa: E402
import gradient_surface_diagnostic as gsd  # noqa: E402

GREEN_HALF_MM = 50.0
TEE_CLEAR_OFFSET_MM = 20.0
ROUTE = "/api/generate_models"
COURSE = "TempCourse"
HOLE = "01"
EGM_BODY = "{}"
THREE_MF_SUFFIX = ".3mf"
OUT_DIR_NAME = "out"
STUB_3MF_BYTES = b"3mf"
STATUS_KEY = "status"
MSG_KEY = "msg"
STATUS_ERROR_VALUE = "error"
GREEN = Polygon([(-GREEN_HALF_MM, -GREEN_HALF_MM), (GREEN_HALF_MM, -GREEN_HALF_MM),
                 (GREEN_HALF_MM, GREEN_HALF_MM), (-GREEN_HALF_MM, GREEN_HALF_MM)])
OFF_GREEN_X = GREEN_HALF_MM + gsd.TEE_HOLE_COLLAR_OD_MM + TEE_CLEAR_OFFSET_MM


def test_check_raises_when_tee_on_green():
    with pytest.raises(gsd.TeeOnGreenError, match=gsd.TEE_ON_GREEN_ERROR_MSG):
        gsd.ensure_tee_off_green(0.0, 0.0, GREEN)


def test_check_passes_when_tee_off_green():
    assert gsd.ensure_tee_off_green(OFF_GREEN_X, 0.0, GREEN) is None


def _setup(tmp_path, monkeypatch, tee_x):
    """Temp course folder + temp output dir; run_pipeline stubbed to the real tee check then a fake 3MF."""
    egm_dir = tmp_path / "courses" / COURSE / app_module.COURSE_SUBDIR_EGMS
    egm_dir.mkdir(parents=True)
    hole_label = HOLE.zfill(app_module.HOLE_LABEL_WIDTH) if HOLE.isdigit() else HOLE
    (egm_dir / app_module.EGM_FILENAME_FMT.format(course=COURSE, hole_label=hole_label)).write_text(EGM_BODY)
    out_dir = tmp_path / OUT_DIR_NAME
    out_dir.mkdir()
    monkeypatch.setattr(app_module, "_EGM_BASE", str(tmp_path / "courses"))
    monkeypatch.setattr(app_module.dependency_preflight, "check_dependencies", lambda: None)

    def _stub_pipeline(egm_path, **_kw):
        gsd.ensure_tee_off_green(tee_x, 0.0, GREEN)
        p = out_dir / ("hole" + THREE_MF_SUFFIX)
        p.write_bytes(STUB_3MF_BYTES)
        return str(p)
    monkeypatch.setattr(gsd, "run_pipeline", _stub_pipeline)
    return out_dir


def test_route_returns_error_payload_and_writes_no_3mf(tmp_path, monkeypatch):
    out_dir = _setup(tmp_path, monkeypatch, 0.0)
    resp = app_module.app.test_client().post(ROUTE, json={"course": COURSE, "hole": HOLE})
    body = resp.get_json()
    assert body[STATUS_KEY] == STATUS_ERROR_VALUE
    assert body[MSG_KEY] == gsd.TEE_ON_GREEN_ERROR_MSG
    assert not list(out_dir.glob("*" + THREE_MF_SUFFIX))


def test_route_tee_off_green_still_generates(tmp_path, monkeypatch):
    out_dir = _setup(tmp_path, monkeypatch, OFF_GREEN_X)
    resp = app_module.app.test_client().post(ROUTE, json={"course": COURSE, "hole": HOLE})
    assert resp.get_json()[STATUS_KEY] != STATUS_ERROR_VALUE
    assert len(list(out_dir.glob("*" + THREE_MF_SUFFIX))) == 1
