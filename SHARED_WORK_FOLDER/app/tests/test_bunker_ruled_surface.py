"""
v5.84 -- ruled bunker body.

Rules under test
  R1  Rim: on the footprint boundary the (unclamped) body height = fringe - BUNKER_RIM_DROP_MM.
  R2  Ruled: along any chord perpendicular to g the body Z is the straight line between the chord's
      two boundary heights (independent shapely oracle, incl. a non-convex U outline).
  R3  Tilted-plane fringe -> body is that plane offset by -BUNKER_RIM_DROP_MM; g is its downhill direction.
  R4  Flat fringe -> g falls back to the polygon principal axis (label BUNKER_RULED_GRAD_SRC_PRINCIPAL).
  R5  Grid cells inside the bunker do not change the ruled mesh; legacy mode (recoverable) does change it.
Synthetic inputs only; no live EGMs / DB.
"""
import contextlib
import importlib.util
import io
import math
import sys
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon

APP_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(Path(__file__).parent))
import test_bunker_grid_topology as T   # reuse synthetic EGM / build helpers and their constants

PLANE_BASE_Z_MM = 20.0
PLANE_SLOPE_X = 0.05           # mm per mm
PLANE_SLOPE_Y = -0.03
WAVE_AMP_MM = 0.4
WAVE_K = 0.35
N_PROBE = 60
PROBE_SEED = 7
CHORD_REACH_MM = 1000.0
LINEAR_TOL_MM = 1e-6
INWARD_NUDGE_MM = 1e-4
RIM_TOL_MM = 1e-3
ELLIPSE_A_MM, ELLIPSE_B_MM, ELLIPSE_N = 14.0, 6.0, 90
U_SHAPE = [(0, 0), (30, 0), (30, 20), (20, 20), (20, 8), (10, 8), (10, 20), (0, 20)]
DOWNHILL_TOL = 1e-6
INTERIOR_MARGIN_MM = 0.01


@pytest.fixture(scope="module")
def g():
    spec = importlib.util.spec_from_file_location("gsd_bunker_ruled", APP_DIR / "gradient_surface_diagnostic.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def plane_fn(xy):
    xy = np.asarray(xy, dtype=float).reshape(-1, 2)
    return PLANE_BASE_Z_MM + PLANE_SLOPE_X * xy[:, 0] + PLANE_SLOPE_Y * xy[:, 1]


def wavy_fn(xy):
    xy = np.asarray(xy, dtype=float).reshape(-1, 2)
    return plane_fn(xy) + WAVE_AMP_MM * np.sin(WAVE_K * xy[:, 0]) * np.cos(WAVE_K * xy[:, 1])


def ellipse():
    t = np.linspace(0, 2 * math.pi, ELLIPSE_N, endpoint=False)
    return Polygon(np.column_stack([ELLIPSE_A_MM * np.cos(t), ELLIPSE_B_MM * np.sin(t)]))


def _interior_points(poly, n):
    rng = np.random.default_rng(PROBE_SEED)
    minx, miny, maxx, maxy = poly.bounds
    out = []
    while len(out) < n:
        p = (rng.uniform(minx, maxx), rng.uniform(miny, maxy))
        if poly.buffer(-INTERIOR_MARGIN_MM).contains(Point(p)):
            out.append(p)
    return np.array(out)


def _oracle(poly, fn, g_vec, p):
    """Independent chord oracle: line through p perpendicular to g, cut by the polygon."""
    nrm = np.array([-g_vec[1], g_vec[0]])
    line = LineString([p - CHORD_REACH_MM * nrm, p + CHORD_REACH_MM * nrm])
    inter = poly.intersection(line)
    segs = [inter] if inter.geom_type == "LineString" else list(inter.geoms)
    seg = next(s for s in segs if s.distance(Point(p)) < INWARD_NUDGE_MM)
    e1, e2 = np.array(seg.coords[0]), np.array(seg.coords[-1])
    return e1, e2, fn(e1)[0], fn(e2)[0]


@pytest.mark.parametrize("poly_name", ["ellipse", "u_shape"])
def test_r2_body_is_linear_between_chord_endpoints(g, poly_name):
    g_mod = g
    poly = ellipse() if poly_name == "ellipse" else Polygon(U_SHAPE)
    floor, info = g_mod._build_bunker_ruled_floor_fn(poly, wavy_fn)
    gv = info["g"]
    pts = _interior_points(poly, N_PROBE)
    got = info["unclamped"](pts)
    for p, z in zip(pts, got):
        e1, e2, z1, z2 = _oracle(poly, wavy_fn, gv, p)
        w = np.linalg.norm(p - e1) / np.linalg.norm(e2 - e1)
        expect = (z1 + w * (z2 - z1)) - g_mod.BUNKER_RIM_DROP_MM
        assert abs(z - expect) < LINEAR_TOL_MM * 10, (p, z, expect)


def test_r1_rim_is_fringe_minus_drop(g):
    poly = ellipse()
    floor, info = g._build_bunker_ruled_floor_fn(poly, wavy_fn)
    ring = poly.exterior
    ts = np.linspace(0, 1, N_PROBE, endpoint=False) + 0.5 / N_PROBE
    centre = np.array(poly.centroid.coords[0])
    for t in ts:
        b = np.array(ring.interpolate(t, normalized=True).coords[0])
        p = b + (centre - b) * INWARD_NUDGE_MM / np.linalg.norm(centre - b)
        z = info["unclamped"](p.reshape(1, 2))[0]
        assert abs(z - (wavy_fn(b)[0] - g.BUNKER_RIM_DROP_MM)) < RIM_TOL_MM


def test_r3_tilted_plane_gives_offset_plane_and_downhill_g(g):
    poly = Polygon(U_SHAPE)
    floor, info = g._build_bunker_ruled_floor_fn(poly, plane_fn)
    down = -np.array([PLANE_SLOPE_X, PLANE_SLOPE_Y]); down /= np.linalg.norm(down)
    assert np.allclose(info["g"], down, atol=DOWNHILL_TOL)
    assert info["gradient_source"] == g.BUNKER_RULED_GRAD_SRC_PLANE
    pts = _interior_points(poly, N_PROBE)
    assert np.allclose(info["unclamped"](pts), plane_fn(pts) - g.BUNKER_RIM_DROP_MM, atol=LINEAR_TOL_MM * 10)
    assert np.allclose(floor(pts), plane_fn(pts) - g.BUNKER_RIM_DROP_MM, atol=LINEAR_TOL_MM * 10)  # clamps inactive here


def test_r4_flat_fringe_uses_principal_axis(g):
    flat = lambda xy: np.full(len(np.asarray(xy).reshape(-1, 2)), PLANE_BASE_Z_MM)
    _floor, info = g._build_bunker_ruled_floor_fn(ellipse(), flat)
    assert info["gradient_source"] == g.BUNKER_RULED_GRAD_SRC_PRINCIPAL
    assert abs(abs(info["g"][0]) - 1.0) < DOWNHILL_TOL   # ellipse long axis is x


def _trap_mesh(g, cells, mode):
    prev = g.BUNKER_BODY_MODE
    g.BUNKER_BODY_MODE = mode
    try:
        egm = T._egm(cells)
        _gb, _fm, trap = T._build(g, egm)
        return trap[0][1]
    finally:
        g.BUNKER_BODY_MODE = prev


def test_r5_cells_do_not_warp_ruled_body_but_do_warp_legacy(g):
    ruled_cells = _trap_mesh(g, T.SLOPED_CELLS, g.BUNKER_BODY_MODE_RULED)
    ruled_none = _trap_mesh(g, None, g.BUNKER_BODY_MODE_RULED)
    assert np.array_equal(ruled_cells.vertices, ruled_none.vertices)
    assert ruled_cells.is_watertight
    legacy_cells = _trap_mesh(g, T.SLOPED_CELLS, g.BUNKER_BODY_MODE_LEGACY)
    assert legacy_cells.vertices.shape != ruled_cells.vertices.shape or \
        not np.allclose(legacy_cells.vertices, ruled_cells.vertices)
