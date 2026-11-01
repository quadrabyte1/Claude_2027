"""Regression (v6.20): the fringe must follow the EGM slope out to the frame.

Thomas: a smooth downward slope in the EGM flattened into a plateau near the frame
because cell Z was floored at BASE_THICKNESS_MM.  Only FRINGE_MIN_THICKNESS_MM
(a real printability floor, far below the base) may clamp the fringe.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

_APP_DIR = Path(__file__).parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

# ---- test scenario constants (single definition each) ----
TEST_BASE_THICKNESS_MM = 6.0       # a thick user base, like Delaveaga 11.40
TEST_GREEN_RIM_Z_MM = 8.0          # flat green rim height
TEST_GREEN_RADIUS_MM = 20.0
TEST_RIM_POINTS = 120
TEST_GRID_SIZE = 20
TEST_SLOPE_MM_PER_CELL = 0.5       # delta steps down per cell toward +x frame
TEST_SLOPE_FIRST_COL = TEST_GRID_SIZE // 2
TEST_PROFILE_SAMPLES = 60
TEST_TREND_STRIDE = 6
TEST_END_TOLERANCE_MM = 0.25
TEST_MIN_STEP_MM = 1e-4            # every sample must drop by at least this (no plateau)


@pytest.fixture(scope="module")
def gsd():
    import gradient_surface_diagnostic as mod
    return mod


def test_sloping_fringe_has_no_plateau_below_base(gsd, monkeypatch):
    monkeypatch.setattr(gsd, "BASE_THICKNESS_MM", TEST_BASE_THICKNESS_MM)
    half = gsd.FRINGE_HALF_MM
    cell = 2.0 * half / TEST_GRID_SIZE
    ang = np.linspace(0, 2 * np.pi, TEST_RIM_POINTS, endpoint=False)
    bnd = np.column_stack([TEST_GREEN_RADIUS_MM * np.cos(ang), TEST_GREEN_RADIUS_MM * np.sin(ang)])
    bnd_z = np.full(TEST_RIM_POINTS, TEST_GREEN_RIM_Z_MM)
    # Slope down along the cell row nearest y=0, all the way to the +x frame.
    row = TEST_GRID_SIZE // 2
    heights = {}
    for k, col in enumerate(range(TEST_SLOPE_FIRST_COL, TEST_GRID_SIZE), start=1):
        heights[str(row * TEST_GRID_SIZE + col)] = -TEST_SLOPE_MM_PER_CELL * k
    egm = {gsd.EGM_KEY_GRID_RESOLUTION: TEST_GRID_SIZE, gsd.EGM_KEY_GRID_CELL_HEIGHTS: heights}
    x_start = TEST_GREEN_RADIUS_MM + cell
    xs = np.linspace(x_start, half - cell / 2.0, TEST_PROFILE_SAMPLES)
    y_line = -half + (row + 0.5) * cell
    gx, gy = np.meshgrid(xs, np.array([y_line]))
    z = gsd._build_tps_grid_height_field(egm, bnd, bnd_z, gx, gy)[0]
    # The staircase of per-cell deltas makes the TPS ripple by a few hundredths of a mm
    # between cell centres, so check the trend at a coarse stride: strictly falling all the
    # way out, ending at the lowest requested Z (old code: flat at the base, 6.0 here).
    coarse = z[::TEST_TREND_STRIDE]
    assert (np.diff(coarse) < -TEST_MIN_STEP_MM).all(), z.tolist()
    lowest_requested = TEST_GREEN_RIM_Z_MM - TEST_SLOPE_MM_PER_CELL * (TEST_GRID_SIZE - TEST_SLOPE_FIRST_COL)
    assert abs(z[-1] - lowest_requested) <= TEST_END_TOLERANCE_MM, z[-1]
    assert lowest_requested < TEST_BASE_THICKNESS_MM
