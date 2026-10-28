"""
v6.01 -- a bunker body must never silently go missing from the 3MF.

Bug (Delaveaga "Hole thomas test 4" [1551]): bunker 2's cavity was cut into the fringe but its body
object was absent.  Root cause: apply_sand_texture raised "non-watertight trap mesh" for that
footprint (Delaunay rake retriangulation left 5 boundary edges), export_trap_stls caught the
exception and DROPPED the trap (warning only).  The fringe cut-out does not depend on the body
build, so the hole stayed.

Rules under test
  N1  Every trap polygon in the real EGM geometry yields a body object (trap_1, trap_2).
  N2  If every texture retry fails, the trap still ships as a plain watertight slab (never dropped)
      and a warning naming the trap is recorded.
  N3  A texture failure on the first attempt is retried (different sample pitch) before degrading.
Temp output only; the live course folders / DB / serial file are never touched.
"""
import importlib.util
import re
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

APP_DIR = Path(__file__).parent.parent
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "delaveaga_thomas_test4"
FIXTURE_EGM_NAME = "thomas_test4.egm"
PIPELINE_SERIAL = 1
MODEL_PART = "3D/3dmodel.model"
OBJECT_TAG_RE = re.compile(r"<object [^>]*>")
COURSE_KEYS = ("images", "egms", "stls", "3mfs")
TRAP_COUNT = 2
TRAP_NODE_PREFIX = "trap_"
WARNING_MISSING_WORD = "MISSING"
WARNING_FALLBACK_WORD = "plain slab"
INJECTED_FAILURE = "injected sand texture failure"


@pytest.fixture()
def g():
    spec = importlib.util.spec_from_file_location("gsd_body_never_missing", APP_DIR / "gradient_surface_diagnostic.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture()
def run(g, tmp_path, monkeypatch):
    out = tmp_path / "out"
    paths = {k: str(out / k) for k in COURSE_KEYS}
    paths[g.PATH_KEY_IMAGES] = str(FIXTURE_DIR)
    for p in paths.values():
        Path(p).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(g, "course_paths", lambda _c: paths)
    monkeypatch.setattr(g, "DIAGNOSTICS_DIR", str(out / "diag"))
    egm = tmp_path / FIXTURE_EGM_NAME
    shutil.copy(FIXTURE_DIR / FIXTURE_EGM_NAME, egm)

    def _go():
        path = g.run_pipeline(str(egm), serial=PIPELINE_SERIAL)
        with zipfile.ZipFile(path) as z:
            n_objects = len(OBJECT_TAG_RE.findall(z.read(MODEL_PART).decode()))
        return path, n_objects
    return _go


def test_n1_both_bunker_bodies_are_in_the_3mf(g, run):
    _, n_objects = run()
    assert not [w for w in g.PIPELINE_WARNINGS if WARNING_MISSING_WORD in w], g.PIPELINE_WARNINGS
    # green + fringe + TRAP_COUNT bunkers
    assert n_objects >= 2 + TRAP_COUNT


def test_n2_total_texture_failure_still_ships_plain_slab(g, run, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError(INJECTED_FAILURE)
    monkeypatch.setattr(g, "apply_sand_texture", boom)
    _, n_objects = run()
    assert n_objects >= 2 + TRAP_COUNT
    assert any(WARNING_FALLBACK_WORD in w for w in g.PIPELINE_WARNINGS), g.PIPELINE_WARNINGS
    assert not [w for w in g.PIPELINE_WARNINGS if WARNING_MISSING_WORD in w]


def test_n3_first_failure_is_retried(g, run, monkeypatch):
    real = g.apply_sand_texture
    calls = {"n": 0}

    def flaky(mesh, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError(INJECTED_FAILURE)
        return real(mesh, *a, **k)
    monkeypatch.setattr(g, "apply_sand_texture", flaky)
    _, n_objects = run()
    assert n_objects >= 2 + TRAP_COUNT
    assert calls["n"] > TRAP_COUNT          # at least one retry happened
