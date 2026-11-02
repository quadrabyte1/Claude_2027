"""v6.25: the fringe's hidden default height is a smooth whole-rim blend, not the Z of the
nearest rim point.

Scenario: a green with a notch cut into its west side, with rim Z rising linearly with y.  Inside
the notch mouth the two arms are equidistant along y = 0, so the old nearest-rim rule jumped
between the arms' heights (a cliff).  Real case: Delaveaga 11 trb-m, 24.5 -> 30.3 mm in 4 mm.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_APP_DIR = Path(__file__).parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import gradient_surface_diagnostic as gsd  # noqa: E402

# ---- scenario constants (single definition each) ----
TEST_GREEN_HALF_MM = 40.0
TEST_NOTCH_X_MM = (-TEST_GREEN_HALF_MM, -10.0)   # notch opens to the west
TEST_NOTCH_HALF_Y_MM = 10.0
TEST_RIM_STEP_MM = 0.5
TEST_RIM_Z_BASE_MM = 20.0
TEST_RIM_Z_PER_Y = 0.5                            # rim Z = base + slope * y
TEST_FRAME_HALF_MM = 85.0
TEST_GRID_STEP_MM = 1.0
TEST_CLEARANCE_MM = 2.0                           # ignore points this close to the rim
TEST_MAX_GRADIENT = 3.0                           # mm of default height per mm of XY travel
TEST_RIM_EQUALITY_TOL_MM = 0.3
TEST_BOUND_TOL_MM = 1e-9


def _notched_rim():
    h, nx, ny = TEST_GREEN_HALF_MM, TEST_NOTCH_X_MM[1], TEST_NOTCH_HALF_Y_MM
    corners = [(-h, -h), (h, -h), (h, h), (-h, h), (-h, ny), (nx, ny), (nx, -ny), (-h, -ny)]
    pts = []
    for (x0, y0), (x1, y1) in zip(corners, corners[1:] + corners[:1]):
        n = max(2, int(np.hypot(x1 - x0, y1 - y0) / TEST_RIM_STEP_MM))
        t = np.linspace(0.0, 1.0, n, endpoint=False)
        pts.append(np.column_stack([x0 + t * (x1 - x0), y0 + t * (y1 - y0)]))
    rim = np.vstack(pts)
    return rim, TEST_RIM_Z_BASE_MM + TEST_RIM_Z_PER_Y * rim[:, 1]


def _outside_grid(rim):
    from scipy.spatial import cKDTree
    xs = np.arange(-TEST_FRAME_HALF_MM, TEST_FRAME_HALF_MM + 1e-9, TEST_GRID_STEP_MM)
    gx, gy = np.meshgrid(xs, xs)
    pts = np.column_stack([gx.ravel(), gy.ravel()])
    keep = cKDTree(rim).query(pts)[0] >= TEST_CLEARANCE_MM
    return gx.shape, pts, keep


def _max_gradient(values, shape, keep):
    z = np.where(keep, values, np.nan).reshape(shape)
    gx = np.abs(np.diff(z, axis=1)) / TEST_GRID_STEP_MM
    gy = np.abs(np.diff(z, axis=0)) / TEST_GRID_STEP_MM
    return float(np.nanmax([np.nanmax(gx), np.nanmax(gy)]))


def _nearest_rim_default(pts, rim, rz):
    from scipy.spatial import cKDTree
    return rz[cKDTree(rim).query(pts)[1]]


def test_nearest_rim_default_makes_a_cliff_in_this_scenario():
    """Baseline (the pre-v6.25 rule): proves the scenario really contains a cliff."""
    rim, rz = _notched_rim()
    shape, pts, keep = _outside_grid(rim)
    assert _max_gradient(_nearest_rim_default(pts, rim, rz), shape, keep) > TEST_MAX_GRADIENT


def test_smooth_default_has_no_cliff():
    rim, rz = _notched_rim()
    shape, pts, keep = _outside_grid(rim)
    z = gsd._fringe_default_z(pts, rim, rz)
    g = _max_gradient(z, shape, keep)
    assert g < TEST_MAX_GRADIENT, g


def test_default_equals_rim_height_at_the_rim():
    rim, rz = _notched_rim()
    z = gsd._fringe_default_z(rim, rim, rz)
    assert np.abs(z - rz).max() <= TEST_RIM_EQUALITY_TOL_MM


def test_default_is_bounded_by_rim_min_max():
    rim, rz = _notched_rim()
    _, pts, _ = _outside_grid(rim)
    z = gsd._fringe_default_z(pts, rim, rz)
    assert z.min() >= rz.min() - TEST_BOUND_TOL_MM
    assert z.max() <= rz.max() + TEST_BOUND_TOL_MM


def test_cell_defaults_use_the_smooth_blend(monkeypatch):
    """_build_tps_grid_height_field must take its per-cell defaults from _fringe_default_z."""
    rim, rz = _notched_rim()
    calls = []
    real = gsd._fringe_default_z

    def spy(*a, **k):
        calls.append(len(a[0]))
        return real(*a, **k)

    monkeypatch.setattr(gsd, "_fringe_default_z", spy)
    gx, gy = np.meshgrid(np.linspace(-20, 20, 5), np.linspace(-20, 20, 5))
    gsd._build_tps_grid_height_field({gsd.EGM_KEY_GRID_RESOLUTION: 20}, rim, rz, gx, gy)
    assert calls and calls[0] == 20 * 20
