"""
v5.98 -- cell-following bunker body (BUNKER_BODY_MODE_CELLS, the default).

Rules under test
  C0  BUNKER_BODY_MODE_CELLS exists, is distinct from RULED / LEGACY and is the default mode.
  C1  Rim: at the bunker boundary the (unclamped) body = fringe - BUNKER_RIM_DROP_MM, exactly as RULED.
  C2  Interior follows the cells: at a cell centre (clear of the blend band) the body equals the cell's
      target Z -- delta: fringe(cell) - BUNKER_RIM_DROP_MM + value; absolute: the literal value.
  C3  No bowl: the interior is NOT pulled under a sagging fringe continuation (v5.98 root-cause regression:
      the v5.84 crest clamp dragged the body onto the dished virtual fringe); cells that are a plane give a plane.
  C4  Smooth rim band: no cliff -- the surface changes by at most the quintic-falloff slope bound.
  C5  Pipeline: cells reshape the body (unlike RULED), watertight, rake kept; a bunker with no owned cell
      is identical to RULED.
Synthetic inputs only; temp state only; no live EGMs / DB.
"""
import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Point, Polygon

APP_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(Path(__file__).parent))
import test_bunker_grid_topology as T   # synthetic EGM / build helpers and their constants
import test_bunker_ruled_surface as R   # plane_fn / wavy_fn / ellipse and their constants

CELL_SIDE_MM = 2.0
GRID_HALF_MM = 20.0
GRID_N = 20
PLANE_STEP_MM = 0.3            # per-column ramp of the synthetic cell values
ABS_BASE_MM = 24.0             # absolute-mode cell heights ride on this plane (above the synthetic fringe)
DEEP_VS_FLAT_MIN_MM = 1.0       # the deep cells must sit at least this far below the shallow ones
LIFT_MM = 2.0                  # added to T.SLOPED_CELLS so the deepest cell stays above the plate-base clamp
DISH_DEPTH_MM = 4.0            # sag of the virtual fringe continuation under the bunker
STEP_MM = 0.05                 # sampling step across the rim band
RIM_NUDGE_MM = 1e-3
RIM_TOL_MM = 0.02              # rim reference is sampled every BUNKER_CELLS_RIM_SAMPLE_MM along the boundary
EXACT_TOL_MM = 1e-6
QUINTIC_MAX_SLOPE = 1.875      # max derivative of 6t^5 - 15t^4 + 10t^3
CLIFF_DELTA_MM = 10.0
N_RIM_PROBE = 40
LINE_HALF_LEN_MM = 12.0


@pytest.fixture(scope="module")
def g():
    spec = importlib.util.spec_from_file_location("gsd_bunker_cells", APP_DIR / "gradient_surface_diagnostic.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def poly():
    return R.ellipse()


def cells_for(g, values_fn):
    """Owned cells (index, value) of the synthetic ellipse; value = values_fn(row, col)."""
    gch = {str(r * GRID_N + c): values_fn(r, c) for r in range(GRID_N) for c in range(GRID_N)}
    return g._trap_inside_cells(poly(), gch, CELL_SIDE_MM, GRID_HALF_MM, GRID_N)


def centre_of(ci):
    r, c = divmod(ci, GRID_N)
    return np.array([-GRID_HALF_MM + (c + 0.5) * CELL_SIDE_MM, -GRID_HALF_MM + (r + 0.5) * CELL_SIDE_MM])


def band_mm(g):
    return g.BUNKER_CELLS_BLEND_BAND_CELLS * CELL_SIDE_MM


def build(g, cells, mode, fz):
    return g._build_bunker_cells_floor_fn(poly(), cells, mode, fz, CELL_SIDE_MM, GRID_HALF_MM, GRID_N)


def dished_fn(xy):
    xy = np.asarray(xy, dtype=float).reshape(-1, 2)
    q = (xy[:, 0] / R.ELLIPSE_A_MM) ** 2 + (xy[:, 1] / R.ELLIPSE_B_MM) ** 2
    return R.plane_fn(xy) - DISH_DEPTH_MM * np.clip(1.0 - q, 0.0, None)


def test_c0_mode_constant_and_default(g):
    assert g.BUNKER_BODY_MODE_CELLS not in (g.BUNKER_BODY_MODE_RULED, g.BUNKER_BODY_MODE_LEGACY)
    assert g.BUNKER_BODY_MODE == g.BUNKER_BODY_MODE_CELLS
    assert g.BUNKER_CELLS_BLEND_BAND_CELLS > 0


def test_c1_rim_is_fringe_minus_drop(g):
    cells = cells_for(g, lambda r, c: PLANE_STEP_MM * c)
    _f, info = build(g, cells, g.GRID_MODE_DELTA, R.wavy_fn)
    p_ = poly()
    centre = np.array(p_.centroid.coords[0])
    for t in np.linspace(0, 1, N_RIM_PROBE, endpoint=False):
        b = np.array(p_.exterior.interpolate(t, normalized=True).coords[0])
        p = b + (centre - b) * RIM_NUDGE_MM / np.linalg.norm(centre - b)
        assert abs(info["unclamped"](p.reshape(1, 2))[0] - (R.wavy_fn(b)[0] - g.BUNKER_RIM_DROP_MM)) < RIM_TOL_MM


def test_c2_delta_cell_centres_follow_values(g):
    cells = cells_for(g, lambda r, c: PLANE_STEP_MM * c - 1.0)
    _f, info = build(g, cells, g.GRID_MODE_DELTA, R.wavy_fn)
    checked = 0
    for ci, v in cells:
        c = centre_of(ci)
        if poly().exterior.distance(Point(c)) < band_mm(g):
            continue
        z = info["unclamped"](c.reshape(1, 2))[0]
        assert abs(z - (R.wavy_fn(c)[0] - g.BUNKER_RIM_DROP_MM + v)) < EXACT_TOL_MM
        checked += 1
    assert checked >= 3


def test_c2_absolute_cell_centres_are_literal(g):
    cells = cells_for(g, lambda r, c: ABS_BASE_MM + PLANE_STEP_MM * c)
    _f, info = build(g, cells, g.GRID_MODE_ABSOLUTE, R.wavy_fn)
    checked = 0
    for ci, v in cells:
        c = centre_of(ci)
        if poly().exterior.distance(Point(c)) < band_mm(g):
            continue
        assert abs(info["unclamped"](c.reshape(1, 2))[0] - v) < EXACT_TOL_MM
        checked += 1
    assert checked >= 3


def test_c3_no_bowl_under_a_dished_fringe(g):
    cells = cells_for(g, lambda r, c: ABS_BASE_MM + PLANE_STEP_MM * c)
    floor, _info = build(g, cells, g.GRID_MODE_ABSOLUTE, dished_fn)
    for ci, v in cells:
        c = centre_of(ci)
        if poly().exterior.distance(Point(c)) < band_mm(g):
            continue
        # the v5.84 crest clamp would force this to dished_fn - 0.8 (far below v)
        assert abs(floor(c.reshape(1, 2))[0] - v) < EXACT_TOL_MM
        assert floor(c.reshape(1, 2))[0] > dished_fn(c)[0]            # a mound above the fringe is allowed when the cells say so


def test_c3_zero_delta_on_a_plane_is_the_offset_plane(g):
    cells = cells_for(g, lambda r, c: 0.0)
    floor, _info = build(g, cells, g.GRID_MODE_DELTA, R.plane_fn)
    rng = np.random.default_rng(R.PROBE_SEED)
    pts = R._interior_points(poly(), R.N_PROBE)
    slope = math.hypot(R.PLANE_SLOPE_X, R.PLANE_SLOPE_Y)
    assert np.all(np.abs(floor(pts) - (R.plane_fn(pts) - g.BUNKER_RIM_DROP_MM)) <= slope * band_mm(g) + RIM_TOL_MM)


@pytest.mark.parametrize("delta", [0.0, CLIFF_DELTA_MM, -CLIFF_DELTA_MM])
def test_c4_rim_band_has_no_cliff(g, delta):
    cells = cells_for(g, lambda r, c: delta)
    _f, info = build(g, cells, g.GRID_MODE_DELTA, R.plane_fn)
    xs = np.arange(-LINE_HALF_LEN_MM, R.ELLIPSE_A_MM, STEP_MM)          # y = 0 line crossing the +x rim
    line = np.column_stack([xs, np.zeros_like(xs)])
    line = line[[poly().contains(Point(p)) for p in line]]
    z = info["unclamped"](line)
    bound = QUINTIC_MAX_SLOPE * (abs(delta) + g.BUNKER_RIM_DROP_MM) / band_mm(g) + math.hypot(R.PLANE_SLOPE_X, R.PLANE_SLOPE_Y)
    assert np.max(np.abs(np.diff(z))) <= bound * STEP_MM * 1.05 + EXACT_TOL_MM


def test_c5_pipeline_cells_reshape_the_body_and_stay_printable(g):
    def mesh(cells, mode):
        prev = g.BUNKER_BODY_MODE
        g.BUNKER_BODY_MODE = mode
        try:
            _gb, fm, trap = T._build(g, T._egm({k: x + LIFT_MM for k, x in cells.items()}))
            return fm, trap[0][1]
        finally:
            g.BUNKER_BODY_MODE = prev
    fm, cm = mesh(T.SLOPED_CELLS, g.BUNKER_BODY_MODE_CELLS)
    _fm, rm = mesh(T.SLOPED_CELLS, g.BUNKER_BODY_MODE_RULED)
    assert cm.is_watertight and cm.is_volume
    assert cm.vertices.shape != rm.vertices.shape or not np.allclose(cm.vertices, rm.vertices)
    fz = g._make_fringe_field_sampler(fm.bunker_fringe_field)
    top = cm.vertices[cm.vertices[:, 2] > 0.5]
    deep = top[(top[:, 0] > 28) & (top[:, 0] < 35) & (abs(top[:, 1]) < 5)]
    flat = top[(top[:, 0] > 55) & (top[:, 0] < 60) & (abs(top[:, 1]) < 5)]
    assert deep[:, 2].mean() < flat[:, 2].mean() - DEEP_VS_FLAT_MIN_MM       # the -3 cells sit lower than the 0 cells (those sit near the rim)
    expected = fz(deep[:, :2]) - g.BUNKER_RIM_DROP_MM + T.DEEP_DELTA_MM + LIFT_MM
    assert abs(deep[:, 2].mean() - expected.mean()) < 1.5
    band = top[(top[:, 0] > 40.0) & (top[:, 0] < 40.0 + 1.125) & (abs(top[:, 1]) < 1.0)]
    assert np.ptp(band[:, 2]) > 0.5 * g.SAND_RAKE_AMPLITUDE_MM               # rake kept
    assert top[:, 2].min() >= g.BUNKER_FLOOR_MIN_MM - 1e-3                   # valleys above the plate


def test_c5_bunker_without_owned_cells_equals_ruled(g):
    def mesh(mode):
        prev = g.BUNKER_BODY_MODE
        g.BUNKER_BODY_MODE = mode
        try:
            return T._build(g, T._egm(None))[2][0][1]
        finally:
            g.BUNKER_BODY_MODE = prev
    assert np.array_equal(mesh(g.BUNKER_BODY_MODE_CELLS).vertices, mesh(g.BUNKER_BODY_MODE_RULED).vertices)
