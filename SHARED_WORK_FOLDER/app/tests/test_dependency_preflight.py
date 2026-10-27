"""v5.75: generation must STOP with a clear error when a dependency is missing."""
import sys
from pathlib import Path

import pytest
from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dependency_preflight as dp
import gradient_surface_diagnostic as gsd
import trimesh

EXPECTED_MODULES = {"triangle", "manifold3d", "lxml", "mapbox_earcut", "networkx"}
KEY_STATUS, KEY_MSG, STATUS_ERROR = "status", "msg", "error"


def _block(monkeypatch, name):
    """Make `import <name>` fail, as on a venv without the package."""
    monkeypatch.setitem(sys.modules, name, None)


def test_preflight_passes_when_everything_importable():
    dp.check_dependencies()
    assert dp.status_report()["ok"] is True
    assert EXPECTED_MODULES <= {m.import_name for m in dp.REQUIRED_MODULES}


def test_missing_triangle_raises_naming_package_and_fix(monkeypatch):
    _block(monkeypatch, "triangle")
    with pytest.raises(dp.MissingDependencyError) as ei:
        dp.check_dependencies()
    msg = str(ei.value)
    assert "triangle" in msg and dp.INSTALL_COMMAND in msg
    assert [m.import_name for m in ei.value.missing] == ["triangle"]


def test_all_missing_modules_are_named(monkeypatch):
    _block(monkeypatch, "triangle")
    _block(monkeypatch, "lxml")
    msg = str(pytest.raises(dp.MissingDependencyError, dp.check_dependencies).value)
    assert "triangle" in msg and "lxml" in msg


def test_run_pipeline_preflights_before_heavy_work(monkeypatch):
    _block(monkeypatch, "triangle")

    def boom(*a, **k):
        raise AssertionError("heavy work started before preflight")

    monkeypatch.setattr(gsd, "load_egm", boom)
    with pytest.raises(dp.MissingDependencyError):
        gsd.run_pipeline("/nonexistent/tmp.egm")


def test_route_returns_error_envelope(monkeypatch):
    import app as app_module
    _block(monkeypatch, "triangle")
    resp = app_module.app.test_client().post(
        app_module.ROUTE_API_GENERATE_MODELS, json={"course": "X", "hole": "1"})
    body = resp.get_json()
    assert resp.status_code == app_module.HTTP_SERVER_ERROR
    assert body[app_module.KEY_STATUS] == app_module.STATUS_ERROR
    assert "triangle" in body[app_module.KEY_MSG]
    assert dp.INSTALL_COMMAND in body[app_module.KEY_MSG]


def test_dependencies_endpoint_reports_status(monkeypatch):
    import app as app_module
    client = app_module.app.test_client()
    assert client.get(app_module.ROUTE_API_DEPENDENCIES).get_json()["ok"] is True
    _block(monkeypatch, "triangle")
    body = client.get(app_module.ROUTE_API_DEPENDENCIES).get_json()
    assert body["ok"] is False and body["missing"] == ["triangle"]


def _spy_extrude(monkeypatch, exc):
    engines = []

    def fake(poly, height, engine=None, **kw):
        engines.append(engine)
        raise exc

    monkeypatch.setattr(trimesh.creation, "extrude_polygon", fake)
    return engines


def test_triangle_import_failure_raises_not_earcut(monkeypatch):
    engines = _spy_extrude(monkeypatch, ModuleNotFoundError("triangle"))
    old = trimesh.creation.box()
    with pytest.raises(dp.MissingDependencyError):
        gsd._replace_fringe_with_watertight_extrusion(old, box(0, 0, 10, 10), 3.0, "t")
    assert engines == [gsd.TRIANGULATE_ENGINE_TRIANGLE]


def test_triangle_runtime_failure_raises_not_earcut(monkeypatch):
    engines = _spy_extrude(monkeypatch, ValueError("bad polygon"))
    old = trimesh.creation.box()
    with pytest.raises(gsd.FringeTriangulationError):
        gsd._replace_fringe_with_watertight_extrusion(old, box(0, 0, 10, 10), 3.0, "t")
    assert gsd.TRIANGULATE_ENGINE_EARCUT not in engines


def test_boolean_engine_missing_raises(monkeypatch):
    def nope(meshes, engine=None, **k):
        raise ModuleNotFoundError("manifold3d")

    monkeypatch.setattr(trimesh.boolean, "difference", nope)
    _block(monkeypatch, "manifold3d")
    with pytest.raises(dp.MissingDependencyError):
        gsd._boolean_difference([trimesh.creation.box()], "t")


def test_boolean_genuine_failure_returns_none(monkeypatch, capsys):
    def bad(meshes, engine=None, **k):
        raise ValueError("Not all meshes are volumes")

    monkeypatch.setattr(trimesh.boolean, "difference", bad)
    assert gsd._boolean_difference([trimesh.creation.box()], "t") is None
    assert gsd.LOG_TAG_NO_FALLBACK in capsys.readouterr().out


def test_boolean_happy_path_unchanged():
    a = trimesh.creation.box(extents=(10, 10, 10))
    b = trimesh.creation.cylinder(radius=1, height=20)
    r = gsd._boolean_difference([a, b], "t")
    assert r is not None and len(r.faces) > 0
