"""
test_trap_grid_mode_absolute_off.py — Bug->TDD: trap heights must honour gridMode.

Delaveaga 5f [1484] (2026-10-15): all four traps had a 13 mm grid cell, gridMode
"absolute".  Traps 1/2 came out ~13+1 (delta semantics) but traps 3/4 came out
7.27/6.0 because export_trap_stls (a) ignored gridMode and (b) averaged ALL set
cells inside the trap, so incidental terrain-shaping cells (2.5, 2.8, 1 ...)
diluted the explicit 13.

Rules under test (helper _resolve_trap_height_from_grid):
  T1 absolute: highest in-trap cell wins, value is the Z (not an offset).
  T2 absolute: low incidental cells don't dilute the 13.
  T3 off: no override (None).
  T4 delta: default + MAX in-trap delta (changed from mean in v5.12).
  T5 export_trap_stls is wired to the helper and passes egm gridMode.
"""
import importlib.util, inspect, math, sys
from pathlib import Path
import pytest

APP_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(APP_DIR))


def _gsd():
    spec = importlib.util.spec_from_file_location("gsd_mode_test", APP_DIR / "gradient_surface_diagnostic.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def _geom(g):
    half = g.PRINT_SIZE_MM / 2.0 + g.FRINGE_XY_EXPANSION_MM / 2.0
    return half, 2 * half / 20


def _big_trap(g, rows, cols):
    """Rectangle covering cell centres rows x cols (inclusive)."""
    from shapely.geometry import box
    half, side = _geom(g)
    x0 = -half + (cols[0] - 0.05) * side; x1 = -half + (cols[1] + 1.05) * side
    y0 = -half + (rows[0] - 0.05) * side; y1 = -half + (rows[1] + 1.05) * side
    return box(x0, y0, x1, y1)


CELLS = {str(10 * 20 + 10): 13.0, str(10 * 20 + 11): 2.8, str(11 * 20 + 10): 2.5, str(11 * 20 + 11): 1.0}


def _resolve(g, mode, cells=CELLS, default=1.0):
    half, side = _geom(g)
    return g._resolve_trap_height_from_grid(_big_trap(g, (10, 11), (10, 11)), cells, mode, default, side, half)


def test_t1_absolute_uses_value_as_z():
    g = _gsd()
    assert _resolve(g, "absolute", {str(210): 13.0}) == pytest.approx(13.0)


def test_t2_absolute_not_diluted_by_other_cells():
    g = _gsd()
    assert _resolve(g, "absolute") == pytest.approx(13.0)


def test_t3_off_disables_override():
    g = _gsd()
    assert _resolve(g, "off") is None


def test_t4_delta_uses_highest_cell():
    """v5.12: delta = default + the HIGHEST in-trap delta (was mean)."""
    g = _gsd()
    expect = 1.0 + 13
    assert _resolve(g, "delta") == pytest.approx(expect)
    assert _resolve(g, None) == pytest.approx(expect)  # missing mode -> delta


def test_t5_export_trap_stls_uses_helper_and_gridmode():
    g = _gsd()
    src = inspect.getsource(g.export_trap_stls)
    assert "_resolve_trap_height_from_grid" in src
    assert "gridMode" in src
