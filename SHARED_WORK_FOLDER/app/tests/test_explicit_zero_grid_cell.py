"""
Editor v5.80 / generator: a 0 painted with the paint-mode brush is a REAL grid value.

Key presence in egm["gridCellHeights"] defines "set"; an explicit 0 is a TPS / trap constraint like any other.
Synthetic inputs only: no live EGMs, no DB, no pipeline run.
"""
import importlib.util, sys
from pathlib import Path
import numpy as np

APP_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(APP_DIR))


def _gsd():
    spec = importlib.util.spec_from_file_location("gsd_zero_test", APP_DIR / "gradient_surface_diagnostic.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def _field(g, egm):
    half = g.FRINGE_HALF_MM
    t = np.linspace(0, 2 * np.pi, 60, endpoint=False)
    bnd = np.column_stack([30 * np.cos(t), 30 * np.sin(t)])
    bz = np.full(60, 12.0)
    gx, gy = np.meshgrid(np.linspace(-half, half, 41), np.linspace(-half, half, 41))
    return g._build_tps_grid_height_field(egm, bnd, bz, gx, gy)


def _box_over_cell(g, row, col):
    from shapely.geometry import box
    half = g.FRINGE_HALF_MM; side = 2 * half / 20
    return box(-half + (col - 0.05) * side,
               -half + (row - 0.05) * side, -half + (col + 1.05) * side, -half + (row + 1.05) * side)


def test_absolute_explicit_zero_cell_is_a_tps_constraint():
    g = _gsd()
    base = {"gridMode": "absolute"}
    ci = 5 * 20 + 14                                   # a frame-side cell, away from the bnd ring
    without = _field(g, base)
    with_zero = _field(g, {**base, "gridCellHeights": {str(ci): 0}})
    assert not np.allclose(without, with_zero)         # the 0 pins that spot to BASE_THICKNESS_MM, not the default 12
    assert with_zero.min() < without.min() or not np.allclose(with_zero, without)


def test_delta_explicit_zero_pins_to_default_so_surface_is_unchanged():
    """Delta 0 = offset 0 = the cell's own default: every cell is already a TPS constraint, so no change."""
    g = _gsd()
    a = _field(g, {"gridMode": "delta"})
    b = _field(g, {"gridMode": "delta", "gridCellHeights": {str(5 * 20 + 14): 0}})
    assert np.array_equal(a, b)


def test_explicit_zero_counts_as_a_bunker_owned_cell():
    g = _gsd()
    half = g.FRINGE_HALF_MM; side = 2 * half / 20
    poly = _box_over_cell(g, 5, 5)
    cells = {str(5 * 20 + 5): 0}
    # explicit 0 is a set cell: it is owned by a bunker that fully covers it
    assert g._trap_inside_cells(poly, cells, side, half) == [(5 * 20 + 5, 0.0)]
    # absent key = empty
    assert g._trap_inside_cells(poly, {str(7 * 20 + 7): 0}, side, half) == []


def test_zero_mixed_with_other_cells_both_owned():
    g = _gsd()
    half = g.FRINGE_HALF_MM; side = 2 * half / 20
    from shapely.geometry import box
    poly = box(-half + 4.95 * side, -half + 4.95 * side, -half + 7.05 * side, -half + 5.05 * side + side)
    cells = {str(5 * 20 + 5): 0, str(5 * 20 + 6): 7}
    assert sorted(g._trap_inside_cells(poly, cells, side, half)) == [(5 * 20 + 5, 0.0), (5 * 20 + 6, 7.0)]
