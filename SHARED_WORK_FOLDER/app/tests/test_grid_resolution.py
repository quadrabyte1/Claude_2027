"""
test_grid_resolution_v522.py -- editor v5.22: 20x20 / 40x40 grid resolution switch.

Run: python -m pytest app/tests/test_grid_resolution_v522.py -v
"""
import importlib.util, re, sys
from pathlib import Path
import numpy as np

APP_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(APP_DIR))
HTML = (APP_DIR / "templates" / "editor.html").read_text()


def _gsd():
    spec = importlib.util.spec_from_file_location("gsd_res_test", APP_DIR / "gradient_surface_diagnostic.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def test_normalize_resolution():
    g = _gsd()
    assert g._normalize_grid_resolution(None) == 20
    assert g._normalize_grid_resolution(40) == 40
    assert g._normalize_grid_resolution("40") == 40
    assert g._normalize_grid_resolution(33) == 20
    assert g._normalize_grid_resolution("x") == 20


def test_controlling_cells_use_resolution():
    from shapely.geometry import box
    g = _gsd()
    half = g.PRINT_SIZE_MM / 2.0 + g.FRINGE_XY_EXPANSION_MM / 2.0
    side = 2 * half / 40
    # cell row 30, col 5 at 40x40
    poly = box(-half + 4.9 * side, -half + 29.9 * side, -half + 6.1 * side, -half + 31.1 * side)
    cells = g.controlling_cells_for_trap(poly, {30 * 40 + 5: 7.0}, side, half, 40)
    assert cells == [30 * 40 + 5]


def test_tps_field_40_grid():
    g = _gsd()
    half = g.PRINT_SIZE_MM / 2.0 + g.FRINGE_XY_EXPANSION_MM / 2.0
    t = np.linspace(0, 2 * np.pi, 60, endpoint=False)
    bnd = np.column_stack([30 * np.cos(t), 30 * np.sin(t)])
    bz = np.full(60, 5.0)
    gx, gy = np.meshgrid(np.linspace(-half, half, 41), np.linspace(-half, half, 41))
    base = {"gridMode": "absolute", "gridResolution": 40}
    z_none = g._build_tps_grid_height_field(base, bnd, bz, gx, gy)
    cell = 1000 // 1  # row 25, col 25 at 40x40 -> near centre-right of frame
    ci = 25 * 40 + 25
    z_set = g._build_tps_grid_height_field({**base, "gridCellHeights": {str(ci): 12.0}}, bnd, bz, gx, gy)
    assert z_set.max() > z_none.max() + 1.0
    # an index valid only at 40x40 is ignored at 20x20 (>= 400)
    z_20 = g._build_tps_grid_height_field({"gridMode": "absolute", "gridCellHeights": {"900": 12.0}}, bnd, bz, gx, gy)
    z_20n = g._build_tps_grid_height_field({"gridMode": "absolute"}, bnd, bz, gx, gy)
    assert np.allclose(z_20, z_20n)


def test_editor_source_wiring():
    assert "v5.68 — Grid resolution switch" in HTML
    assert "gridN: 20," in HTML
    assert "setGridResolution(40)" in HTML and "setGridResolution(20)" in HTML
    assert "Switching resolutions will cause all grid settings to be erased." in HTML
    assert "data.gridResolution = this.gridN" in HTML
    assert "this.gridN = (Number(data.gridResolution) === 40) ? 40 : 20;" in HTML
    assert not re.search(r"GRID_(COLS|ROWS)\s*=\s*20", HTML)
