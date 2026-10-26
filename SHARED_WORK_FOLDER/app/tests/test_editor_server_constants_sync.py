"""
Drift guard: values that templates/editor.html and the server must agree on.

Coding Standard (CLAUDE.md): one definition per value.  Where the editor (JS) and the server
(Python) both need a value they cannot share a source, so this test reads the editor's named
constants (tests/editor_constants.value) and asserts they equal the server-side constants
(app.py `ROUTE_*` / `QUERY_*` / `DETECT_*` / `GPS_PREVIEW_*`, and the generator modules
generate_stl_3mf.py / gradient_surface_diagnostic.py).  If either side changes alone, this fails.

Run: python -m pytest app/tests/test_editor_server_constants_sync.py -v
"""
import importlib.util
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(Path(__file__).parent))
import editor_constants as C  # noqa: E402

BASE_PATH_PLACEHOLDER_START = "<"   # Flask converter marker in a route string


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, APP_DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def server():
    """app.py's constants (import only; no request is made, no DB path is touched here)."""
    import app as _app
    return _app


@pytest.fixture(scope="module")
def gen():
    return _load("gen_sync_test", "generate_stl_3mf.py")


@pytest.fixture(scope="module")
def gsd():
    return _load("gsd_sync_test", "gradient_surface_diagnostic.py")


# ── API route strings ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("editor_name, server_name", [
    ("API_DETECT_BOUNDARIES", "ROUTE_API_DETECT_BOUNDARIES"),
    ("API_TRAP_CONTROLLING_CELLS", "ROUTE_API_TRAP_CONTROLLING_CELLS"),
    ("API_BOUNDARIES", "ROUTE_API_BOUNDARIES"),
    ("API_BOUNDARIES_LIST", "ROUTE_API_BOUNDARIES_LIST"),
    ("API_BOUNDARIES_LOAD", "ROUTE_API_BOUNDARIES_LOAD"),
    ("API_IMAGES", "ROUTE_API_IMAGES"),
    ("API_COURSES", "ROUTE_API_COURSES"),
    ("API_PRINT_CONSTANTS", "ROUTE_API_PRINT_CONSTANTS"),
    ("API_FIND_CONTOURS", "ROUTE_API_FIND_CONTOURS"),
    ("API_GPS_FILES", "ROUTE_API_GPS_FILES"),
    ("API_GPS_HEIGHTMAP_PREVIEW", "ROUTE_API_GPS_HEIGHTMAP_PREVIEW"),
    ("API_GENERATE_MODELS", "ROUTE_API_GENERATE_MODELS"),
    ("API_RUNNING_TASKS_COUNT", "ROUTE_API_TASKS_RUNNING_COUNT"),
])
def test_api_route_strings_match(server, editor_name, server_name):
    assert C.value(editor_name) == getattr(server, server_name)


@pytest.mark.parametrize("editor_name, server_name", [
    ("IMAGE_URL_TEAM_INBOX", "ROUTE_TEAM_INBOX"),
    ("IMAGE_URL_EGM_IMAGES", "ROUTE_EGM_IMAGE"),
])
def test_image_url_prefixes_match_server_routes(server, editor_name, server_name):
    route = getattr(server, server_name)
    assert route.startswith(C.value(editor_name))
    # the server's own URL builders must produce URLs under the same prefix
    assert route[:route.index(BASE_PATH_PLACEHOLDER_START)] == C.value(editor_name)


def test_server_url_formats_use_editor_prefixes(server):
    assert server.TEAM_INBOX_URL_FMT.startswith(C.value("IMAGE_URL_TEAM_INBOX"))
    assert server.EGM_IMAGE_URL_FMT.startswith(C.value("IMAGE_URL_EGM_IMAGES"))


def test_query_param_names_match(server):
    assert C.value("QUERY_FILENAME") == "?" + server.QUERY_FILENAME + "="
    assert C.value("QUERY_COURSE") == "?" + server.QUERY_COURSE + "="


# ── Print size / fringe expansion ─────────────────────────────────────────────

def test_print_constants_match_generators_and_editor(gen, gsd):
    assert C.value("DEFAULT_PRINT_SIZE_MM") == gen.PRINT_SIZE_MM == gsd.PRINT_SIZE_MM
    assert C.value("DEFAULT_FRINGE_XY_EXPANSION_MM") == gen.FRINGE_XY_EXPANSION_MM == gsd.FRINGE_XY_EXPANSION_MM


def test_shared_print_constants_defined_once(gen, gsd):
    """PRINT_SIZE_MM / FRINGE_XY_EXPANSION_MM live only in generate_stl_3mf.py; the
    diagnostic imports them (Coding Standard: one definition per value)."""
    import re
    gsd_src = (APP_DIR / "gradient_surface_diagnostic.py").read_text()
    for name in ("PRINT_SIZE_MM", "FRINGE_XY_EXPANSION_MM", "FRINGE_HALF_MM"):
        assert not re.search(rf"^{name}\s*(:[^=]+)?=", gsd_src, re.MULTILINE), \
            f"{name} must be imported from generate_stl_3mf, not redefined"
    assert gsd.FRINGE_HALF_MM == gen.FRINGE_HALF_MM == gen.PRINT_SIZE_MM / 2.0 + gen.FRINGE_XY_EXPANSION_MM / 2.0


# ── Grid resolution / mode / clamps ───────────────────────────────────────────

def test_grid_resolutions_accepted_by_generator(gsd):
    n_default, n_fine = C.value("GRID_N_DEFAULT"), C.value("GRID_N_FINE")
    assert gsd._normalize_grid_resolution(n_default) == n_default
    assert gsd._normalize_grid_resolution(n_fine) == n_fine
    # missing / unknown fall back to the editor's legacy default
    assert gsd._normalize_grid_resolution(None) == n_default
    assert gsd._normalize_grid_resolution(n_fine + 1) == n_default


def test_grid_modes_match_generator(gsd):
    for mode in C.value("GRID_MODES"):
        assert gsd._normalize_grid_mode(mode) == mode
    assert gsd._normalize_grid_mode(None) == C.value("DEFAULT_GRID_MODE")


def test_absolute_upper_clamp_matches_generator(gsd, monkeypatch):
    """Generator clamps a trap's absolute height at the editor's GRID_ABSOLUTE_MAX_MM."""
    over = C.value("GRID_ABSOLUTE_MAX_MM") * 10.0
    monkeypatch.setattr(gsd, "_trap_inside_cells", lambda *a, **k: [(0, over)])
    got = gsd._resolve_trap_height_from_grid(
        None, {"0": over}, "absolute", 1.0, 1.0, 1.0, C.value("GRID_N_DEFAULT"))
    assert got == C.value("GRID_ABSOLUTE_MAX_MM")


@pytest.mark.parametrize("gsd_name, editor_name", [
    ("GRID_DELTA_MIN_MM", "GRID_DELTA_MIN_MM"),
    ("GRID_DELTA_MAX_MM", "GRID_DELTA_MAX_MM"),
    ("GRID_ABSOLUTE_MIN_MM", "GRID_ABSOLUTE_MIN_MM"),
    ("GRID_ABSOLUTE_MAX_MM", "GRID_ABSOLUTE_MAX_MM"),
])
def test_generator_clamp_constants_match_editor(gsd, gsd_name, editor_name):
    # The generator still clamps with inline -20/20/0/30 literals (stage 3 of the
    # named-constants refactor extracts them under these names).  Skipped until then.
    if not hasattr(gsd, gsd_name):
        pytest.skip(f"gradient_surface_diagnostic.{gsd_name} not defined yet (stage 3)")
    assert getattr(gsd, gsd_name) == C.value(editor_name)


# ── Defaults the server hands to / mirrors from the editor ────────────────────

def test_detect_boundaries_default_contour_step_matches_editor(server):
    assert server.DETECT_DEFAULT_CONTOUR_STEP_MM == C.value("DEFAULT_CONTOUR_STEP_MM")


def test_gps_preview_default_approach_matches_editor(server):
    assert server.GPS_PREVIEW_DEFAULT_APPROACH_M == C.value("DEFAULT_GPS_APPROACH_M")


def test_egm_base_matches_generator(server, gen):
    assert server._EGM_BASE == gen.EGM_BASE
