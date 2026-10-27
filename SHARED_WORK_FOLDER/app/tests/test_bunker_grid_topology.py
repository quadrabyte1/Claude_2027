"""
v5.82 -- cell-owned, fringe-carved bunker floors.

Rules under test
  B1  Ownership: a SET cell fully inside a bunker belongs to that bunker only; a partly-inside
      cell stays with the fringe; gridMode off / no cells -> nobody owns anything.
  B2  Fringe exclusion: the fringe is built from every set cell EXCEPT bunker-owned ones, so
      painting a bunker-owned cell leaves the fringe mesh byte-identical; a partly-inside cell
      still shapes it.
  B3  Carved base: floor = fringe(x, y) - BUNKER_DROP_BELOW_FRINGE_MM (delta cell value 0 -> exactly that).
  B4  Delta mode: cell values are offsets added to the carved base; offset field returns to 0 at the rim.
  B5  Absolute mode: the floor passes through the literal cell value; the rim is still fringe - drop.
  B6  No owned cell -> flat bunker, exactly the pre-v5.82 behaviour (no fringe field is produced).
  B7  The sloped bunker mesh is watertight and a volume; the rake follows the slope.
  B8  Floor safety: rake crests stay below the fringe, valleys above the plate base, for extreme values.
  B9  The red controlling-cell ring is gone (server route, generator helpers, editor drawing).
Synthetic inputs only; temp state only; no live EGMs / DB.
"""
import contextlib
import importlib.util
import io
import math
import sys
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import box

APP_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(APP_DIR))

FRINGE_GRID_RES_TEST = 80          # coarse fringe grid keeps these tests quick
GREEN_Z_MM = 6.0                   # flat synthetic green height
TRAP_OFFSET_PX = 150.0             # trap centre, px right of the green centre
TRAP_RADIUS_PX = 70.0
SLOPED_CELLS = {"193": -3.0, "213": -3.0, "194": -2.0, "214": -2.0, "195": -1.0, "215": -1.0, "196": 0.0, "216": 0.0}
DEEP_DELTA_MM = -3.0               # value of the deepest sloped cells (keeps the floor clear of the plate-base clamp)
SOLE_OWNED_CELL = "174"            # fully inside the synthetic bunker
RIM_TOL_MM = 1e-6
RIM_ATOL_MM = 0.05                 # TPS ripple between zero-anchors spaced BUNKER_EDGE_ANCHOR_SPACING_MM


@pytest.fixture(scope="module")
def g():
    spec = importlib.util.spec_from_file_location("gsd_bunker_topology", APP_DIR / "gradient_surface_diagnostic.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.BUNKER_BODY_MODE = m.BUNKER_BODY_MODE_LEGACY   # v5.84: these B1-B9 rules describe the legacy (v5.82) body
    return m


def _circle(cx, cy, r, n=64):
    return [{"x": cx + r * math.cos(2 * math.pi * i / n), "y": cy + r * math.sin(2 * math.pi * i / n)} for i in range(n)]


def _egm(cells=None, mode="delta"):
    e = {"course": "T", "hole": "99", "image": "d.png", "imageSize": {"width": 600, "height": 600},
         "elevationRange": 14.5, "greenScale": 1.0,
         "polygons": [{"name": "Green", "type": "green", "points": _circle(300, 300, 105)},
                      {"name": "Trap1", "type": "trap", "points": _circle(300 + TRAP_OFFSET_PX, 300, TRAP_RADIUS_PX, 24)}],
         "fringeBoundaryHeights": [], "elevationSpikes": []}
    if cells is not None:
        e["gridCellHeights"] = dict(cells)
        e["gridMode"] = mode
    return e


def _build(g, egm):
    gb = g.interpolate_catmull_rom(egm["polygons"][0]["points"])
    res = FRINGE_GRID_RES_TEST
    xs = np.linspace(0, 599, res); ys = np.linspace(0, 599, res)
    inside = np.zeros((res, res), dtype=bool)
    for ri, py in enumerate(ys):
        for ci, px in enumerate(xs):
            inside[ri, ci] = math.hypot(px - 300, py - 300) < 105
    Z = np.full((res, res), GREEN_Z_MM)
    with contextlib.redirect_stdout(io.StringIO()):
        fm = g.build_fringe_mesh(Z, xs, ys, inside, gb, egm, fringe_grid_res=res)
        trap = g.export_trap_stls(egm, gb, slug="t", fringe_mesh=fm, write_stls=False)
    return gb, fm, trap


@pytest.fixture(scope="module")
def sloped(g):
    egm = _egm(SLOPED_CELLS)
    gb, fm, trap = _build(g, egm)
    return egm, gb, fm, trap[0][1]


def _grid(g):
    half = g.FRINGE_HALF_MM
    return half, 2 * half / 20


def _footprint(g, egm, gb):
    scale, cen = g._compute_px_to_mm(gb, egm)
    return g._build_trap_footprint(egm["polygons"][1], scale, cen, None)


def _cell_box(g, idx):
    half, side = _grid(g)
    r, c = divmod(idx, 20)
    return box(-half + c * side, -half + r * side, -half + (c + 1) * side, -half + (r + 1) * side)


# --------------------------------------------------------------------------- B1
def test_b1_fully_inside_cells_are_owned_partial_cells_are_not(g):
    egm = _egm(SLOPED_CELLS)
    gb = g.interpolate_catmull_rom(egm["polygons"][0]["points"])
    fp = _footprint(g, egm, gb)
    partial = [i for i in range(400) if fp.intersects(_cell_box(g, i)) and not fp.covers(_cell_box(g, i))]
    assert partial, "synthetic bunker must have boundary (partial) cells"
    egm2 = _egm({str(partial[0]): 2.0, SOLE_OWNED_CELL: 1.0})
    owned = g.bunker_owned_cells(egm2, gb)
    assert list(owned) == [1]
    assert [ci for ci, _ in owned[1][1]] == [int(SOLE_OWNED_CELL)]      # partial cell NOT owned


def test_b1_off_mode_and_no_cells_own_nothing(g):
    gb = g.interpolate_catmull_rom(_egm()["polygons"][0]["points"])
    assert g.bunker_owned_cells(_egm(SLOPED_CELLS, "off"), gb) == {}
    assert g.bunker_owned_cells(_egm(), gb) == {}
    assert g.bunker_owned_cells(_egm({}), gb) == {}


def test_b1_explicit_zero_cell_is_owned(g):
    gb = g.interpolate_catmull_rom(_egm()["polygons"][0]["points"])
    owned = g.bunker_owned_cells(_egm({SOLE_OWNED_CELL: 0}), gb)
    assert owned[1][1] == [(int(SOLE_OWNED_CELL), 0.0)]


# --------------------------------------------------------------------------- B2
def test_b2_fringe_ignores_bunker_owned_cells(g, sloped):
    _egm_s, _gb, fm_sloped, _m = sloped
    _, fm_plain, _ = _build(g, _egm())
    assert np.array_equal(fm_sloped.vertices, fm_plain.vertices)
    assert np.array_equal(fm_sloped.faces, fm_plain.faces)


def test_b2_partial_cell_still_shapes_the_fringe(g):
    egm = _egm()
    gb = g.interpolate_catmull_rom(egm["polygons"][0]["points"])
    fp = _footprint(g, egm, gb)
    partial = next(i for i in range(400) if fp.intersects(_cell_box(g, i)) and not fp.covers(_cell_box(g, i)))
    _, fm_plain, _ = _build(g, _egm())
    _, fm_partial, _ = _build(g, _egm({str(partial): 6.0}))
    assert not np.array_equal(fm_plain.vertices, fm_partial.vertices)


def test_b2_fringe_cell_heights_helper_drops_only_owned_keys(g):
    egm = _egm({SOLE_OWNED_CELL: 1.0, "5": 2.0})
    gb = g.interpolate_catmull_rom(egm["polygons"][0]["points"])
    assert g.fringe_grid_cell_heights(egm, gb) == {"5": 2.0}
    assert g.fringe_grid_cell_heights(_egm({"5": 2.0}), gb) == {"5": 2.0}


# --------------------------------------------------------------------------- floor-function unit tests
def _floor_fixture(g, cells, mode):
    half, side = _grid(g)
    fp = box(-half + 7.5 * side, -half + 7.5 * side, -half + 12.5 * side, -half + 12.5 * side)   # covers cells 8..11
    owned = g._trap_inside_cells(fp, cells, side, half, 20)
    fringe = lambda xy: GREEN_Z_MM + 0.01 * np.asarray(xy)[:, 0]
    floor_fn, info = g._build_bunker_floor_fn(fp, owned, mode, fringe, side, half, 20)
    return fp, floor_fn, fringe, owned, side, half


def _centre(idx, side, half):
    r, c = divmod(idx, 20)
    return np.array([[-half + (c + 0.5) * side, -half + (r + 0.5) * side]])


def test_b3_carved_base_is_fringe_minus_drop(g):
    cells = {str(9 * 20 + 9): 0.0}
    fp, floor_fn, fringe, _o, side, half = _floor_fixture(g, cells, "delta")
    pts = np.array([[fp.centroid.x, fp.centroid.y], [fp.centroid.x + 6, fp.centroid.y - 5]])
    assert np.allclose(floor_fn(pts), fringe(pts) - g.BUNKER_DROP_BELOW_FRINGE_MM, atol=1e-6)


def test_b4_delta_offsets_add_to_base_and_vanish_at_rim(g):
    value = -1.5
    cells = {str(9 * 20 + 9): value}
    fp, floor_fn, fringe, _o, side, half = _floor_fixture(g, cells, "delta")
    c = _centre(9 * 20 + 9, side, half)
    assert floor_fn(c)[0] == pytest.approx(fringe(c)[0] - g.BUNKER_DROP_BELOW_FRINGE_MM + value, abs=1e-6)
    rim = np.array([fp.exterior.interpolate(t, normalized=True).coords[0] for t in np.linspace(0, 1, 40, endpoint=False)])
    assert np.allclose(floor_fn(rim), fringe(rim) - g.BUNKER_DROP_BELOW_FRINGE_MM, atol=RIM_ATOL_MM)


def test_b4_smooth_across_bunker(g):
    cells = {str(9 * 20 + 9): -2.0, str(10 * 20 + 10): -1.0}
    fp, floor_fn, fringe, _o, side, half = _floor_fixture(g, cells, "delta")
    xs = np.linspace(fp.bounds[0] + 0.5, fp.bounds[2] - 0.5, 400)
    line = np.column_stack([xs, np.full_like(xs, fp.centroid.y)])
    z = floor_fn(line)
    assert np.abs(np.diff(z)).max() < 0.5          # no steps between sample points 0.2 mm apart


def test_b5_absolute_value_is_literal_floor_and_rim_returns_to_fringe_minus_drop(g):
    literal = 3.0
    cells = {str(9 * 20 + 9): literal}
    fp, floor_fn, fringe, _o, side, half = _floor_fixture(g, cells, "absolute")
    c = _centre(9 * 20 + 9, side, half)
    assert floor_fn(c)[0] == pytest.approx(literal, abs=1e-6)
    rim = np.array([fp.exterior.interpolate(t, normalized=True).coords[0] for t in np.linspace(0, 1, 40, endpoint=False)])
    assert np.allclose(floor_fn(rim), fringe(rim) - g.BUNKER_DROP_BELOW_FRINGE_MM, atol=RIM_ATOL_MM)


def test_b8_floor_clamped_below_fringe_and_above_base(g):
    half_rake = g.SAND_RAKE_AMPLITUDE_MM / 2
    for mode, val in (("delta", 20.0), ("delta", -20.0), ("absolute", 30.0), ("absolute", 0.0)):
        fp, floor_fn, fringe, _o, side, half = _floor_fixture(g, {str(9 * 20 + 9): val, str(10 * 20 + 10): val}, mode)
        rng = np.random.default_rng(0)
        minx, miny, maxx, maxy = fp.bounds
        pts = np.column_stack([rng.uniform(minx, maxx, 500), rng.uniform(miny, maxy, 500)])
        z = floor_fn(pts)
        assert (z + half_rake <= fringe(pts) - g.BUNKER_MIN_CLEARANCE_BELOW_FRINGE_MM + RIM_TOL_MM).all(), (mode, val)
        assert (z - half_rake >= g.BUNKER_FLOOR_MIN_MM - RIM_TOL_MM).all(), (mode, val)


# --------------------------------------------------------------------------- B6
def test_b6_no_owned_cell_stays_flat_and_matches_legacy_flat(g):
    _, fm_none, trap_none = _build(g, _egm())
    _, fm_off, trap_off = _build(g, _egm(SLOPED_CELLS, "off"))
    assert getattr(fm_none, "bunker_fringe_field", None) is None
    assert getattr(fm_off, "bunker_fringe_field", None) is None
    assert np.array_equal(trap_none[0][1].vertices, trap_off[0][1].vertices)
    top = trap_none[0][1].vertices[:, 2]
    top = top[top > 0.5]
    assert np.ptp(top) <= g.SAND_RAKE_AMPLITUDE_MM + 1e-6      # one flat height + rake only


# --------------------------------------------------------------------------- B7 / B8 (pipeline level)
def test_b7_sloped_bunker_is_watertight_and_a_volume(sloped):
    mesh = sloped[3]
    assert mesh.is_watertight and mesh.is_volume


def test_b7_floor_follows_values_and_rake_rides_on_it(g, sloped):
    egm, gb, fm, mesh = sloped
    fz = g._make_fringe_field_sampler(fm.bunker_fringe_field)
    v = mesh.vertices
    top = v[v[:, 2] > 0.5]
    deep = top[(top[:, 0] > 28) & (top[:, 0] < 35) & (abs(top[:, 1]) < 5)]      # deepest (-3) cells
    flat = top[(top[:, 0] > 55) & (top[:, 0] < 60) & (abs(top[:, 1]) < 5)]      # 0 cells
    assert deep[:, 2].mean() < flat[:, 2].mean() - 2.0
    expected_deep = fz(deep[:, :2]) - g.BUNKER_DROP_BELOW_FRINGE_MM + DEEP_DELTA_MM
    assert abs(deep[:, 2].mean() - expected_deep.mean()) < 1.5               # TPS between constraints, within a mm or so
    # rake still present on the slope: local z spread within a one-period x band
    band = top[(top[:, 0] > 40.0) & (top[:, 0] < 40.0 + 1.125) & (abs(top[:, 1]) < 1.0)]
    assert np.ptp(band[:, 2]) > 0.5 * g.SAND_RAKE_AMPLITUDE_MM


def test_b8_rim_mean_is_drop_below_fringe_and_crests_below_fringe(g, sloped):
    egm, gb, fm, mesh = sloped
    fz = g._make_fringe_field_sampler(fm.bunker_fringe_field)
    top = mesh.vertices[mesh.vertices[:, 2] > 0.5]
    depth = fz(top[:, :2]) - top[:, 2]
    assert depth.min() >= g.BUNKER_MIN_CLEARANCE_BELOW_FRINGE_MM - 1e-3        # nothing rises above the fringe
    import shapely
    ins = _footprint(g, egm, gb).buffer(-g.PRINT_TOLERANCE_MM)
    rim = shapely.get_coordinates(ins)
    from scipy.spatial import cKDTree
    d, _ = cKDTree(rim).query(top[:, :2])
    rim_depth = depth[d < 0.4]
    assert abs(rim_depth.mean() - g.BUNKER_DROP_BELOW_FRINGE_MM) < 0.35        # rake centred on fringe - drop


def test_b8_extreme_values_stay_printable(g):
    egm = _egm({"193": 20.0, "194": 20.0, "213": -20.0, "214": -20.0}, "delta")
    _, fm, trap = _build(g, egm)
    mesh = trap[0][1]
    assert mesh.is_watertight
    fz = g._make_fringe_field_sampler(fm.bunker_fringe_field)
    top = mesh.vertices[mesh.vertices[:, 2] > 0.5]
    assert (fz(top[:, :2]) - top[:, 2]).min() >= g.BUNKER_MIN_CLEARANCE_BELOW_FRINGE_MM - 1e-3
    assert top[:, 2].min() >= g.BUNKER_FLOOR_MIN_MM - 1e-3


def test_b5_absolute_mode_pipeline_runs_and_is_watertight(g):
    _, fm, trap = _build(g, _egm({"194": 3.0, "195": 4.0, "214": 3.0, "215": 4.0}, "absolute"))
    assert trap[0][1].is_watertight


# --------------------------------------------------------------------------- B9
def test_b9_controlling_cell_ring_removed(g):
    for name in ("compute_trap_controlling_cells", "controlling_cells_for_trap",
                 "_resolve_trap_height_from_grid", "_trap_grid_override"):
        assert not hasattr(g, name), name
    assert hasattr(g, "_trap_inside_cells")                # the 'fully inside' test is kept
    app_src = (APP_DIR / "app.py").read_text()
    assert "trap_controlling_cells" not in app_src and "TRAP_CONTROLLING" not in app_src
    editor = (APP_DIR / "templates" / "editor.html").read_text()
    for token in ("TRAP_CTL", "_trapCtl", "API_TRAP_CONTROLLING_CELLS", "trap_controlling_cells"):
        assert token not in editor, token


def test_named_constants_exist(g):
    assert g.BUNKER_DROP_BELOW_FRINGE_MM == 1.0
    assert g.SAND_RAKE_AMPLITUDE_MM == 1.0
    assert g.BUNKER_FLOOR_MIN_MM == g.BASE_THICKNESS_MM
