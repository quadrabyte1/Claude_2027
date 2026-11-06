"""
test_preview_geometry_v634.py -- Boundary Editor live 3D preview, server side (APP_VERSION v6.34).

F*  wire format: header, part table, marker table, per-part byte sizes, HTTP headers
E*  error codes and statuses
S1  statelessness: no file written, no EGM touched, no database connection
G*  green cache: miss -> slow path, hit -> no solve, outline move -> miss, cachedOnly refuses the slow path
T*  the tail (soften -> rescale -> slope limit -> Z scale) re-runs when Elevation range / Z scale change
N1  no-arrows green is flat (dry 1.5 mm; water hole 5 mm + 2 mm lift)
A*  (slow) accuracy against a REAL Generate run on a temp copy of the fixture EGM
L1  measured latency at 20x20 and 40x40 (printed; hard-fails only above LATENCY_HARD_CEILING_MS)
R1  Generate output is unchanged by the shared-function extraction (helpers behave as before)

Run: python -m pytest app/tests/test_preview_geometry_v634.py -v -s
"""
from __future__ import annotations

import builtins
import copy
import hashlib
import json
import sqlite3
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import pytest

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
import app as app_module  # noqa: E402
import gradient_surface_diagnostic as gsd  # noqa: E402
import preview_geometry as pg  # noqa: E402

FIXTURE_EGM = Path(__file__).parent / "fixtures" / "delaveaga_thomas_test4" / "thomas_test4.egm"
ROUTE = app_module.ROUTE_API_PREVIEW
FIXTURE_GRID_FINE = 40
FIXTURE_GRID_COARSE = 20
WRITE_MODE_CHARS = ("w", "a", "x", "+")
MOVED_GREEN_POINT_PX = 8.0                 # shift applied to one green control point ("outline moved")
ELEVATION_RANGE_ALT_MM = 9.0               # differs from the fixture's 14.5
Z_SCALE_ALT = 2.0
BASE_THICKNESS_ALT_MM = 2.5
FRINGE_RES_ALT = 64
GREEN_ABS_TOL_MM = 0.10                    # accuracy tolerances (see A1 docstring for the reasons)
FRINGE_MEDIAN_TOL_MM = 0.05
FRINGE_P99_TOL_MM = 0.60
FRINGE_MAX_INTERIOR_TOL_MM = 1.5
FRINGE_SEAM_BAND_MM = 2.0                  # within this of the green outline Generate snaps the seam; the preview omits that
FRINGE_MAX_SEAM_TOL_MM = 3.5
BUNKER_MEAN_RADIUS_MM = 1.5                # rake texture is averaged over this radius before comparing
BUNKER_MAX_TOL_MM = 0.80                   # rake is +/- SAND_RAKE_AMPLITUDE_MM/2 about the mean, plus slack
WATER_ABS_TOL_MM = 0.60
WATER_LIFT_PROBE_XY_MM = (-70.0, -62.0)    # injected pond centre (free area of the fixture plate)
WATER_LIFT_PROBE_HALF_MM = (11.0, 8.0)
LATENCY_RUNS = 6
LATENCY_TARGET_MS = (60.0, 150.0)          # the design's target band
LATENCY_HARD_CEILING_MS = 1500.0           # test only fails above this; misses of the target are reported, not hidden
TOP_VERTEX_MIN_Z_MM = 0.05                 # vertices above this z are top-surface (walls/bottom sit at z=0)
GEN_ID = "2026.11.05.00.00.00.preview"
BLANK_IMAGE_SIZE_PX = 64


# --------------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------------
def load_snapshot(grid: int = FIXTURE_GRID_FINE) -> dict:
    snap = json.loads(FIXTURE_EGM.read_text())
    snap["greenStyle"] = "smooth"
    if grid == FIXTURE_GRID_COARSE:
        coarse: dict = {}
        for key, val in snap["gridCellHeights"].items():
            r, c = divmod(int(key), FIXTURE_GRID_FINE)
            coarse[str((r // 2) * FIXTURE_GRID_COARSE + c // 2)] = val
        snap["gridCellHeights"] = coarse
        snap["gridResolution"] = FIXTURE_GRID_COARSE
    return snap


def image_path_of(snap: dict) -> str:
    path = app_module._find_image_path(snap["image"], preferred_course=snap.get("imageCourse", ""))
    assert path, "fixture heat-map image missing from the course Images folder"
    return path


@pytest.fixture()
def client():
    pg.GREEN_CACHE.clear(); pg.TAIL_CACHE.clear(); pg.POLY_CACHE.clear(); pg.RIM_CACHE.clear()
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def post(client, snap, **extra):
    body = {pg.REQ_SNAPSHOT: snap, pg.REQ_SEQ: extra.pop(pg.REQ_SEQ, 7)}
    body.update(extra)
    return client.post(ROUTE, json=body)


def part_of(decoded, kind, index=1):
    return next(p for p in decoded["parts"] if p["kind"] == kind and p["index"] == index)


def aligned(n: int) -> int:
    return n + (-n) % pg.DATA_ALIGN_BYTES


# --------------------------------------------------------------------------------------------------
# F: wire format
# --------------------------------------------------------------------------------------------------
def test_f1_response_headers_and_layout(client):
    snap = load_snapshot()
    resp = post(client, snap, **{pg.REQ_SEQ: 41})
    assert resp.status_code == 200
    assert resp.mimetype == app_module.CONTENT_TYPE_OCTET
    assert resp.headers[app_module.HEADER_CACHE_CONTROL] == app_module.CACHE_NO_STORE
    assert resp.headers[app_module.HEADER_PREVIEW_SEQ] == "41"
    buf = resp.data
    d = pg.decode_preview(buf)
    h = d["header"]
    assert h["magic"] == pg.WIRE_MAGIC and h["version"] == pg.WIRE_VERSION and h["seq"] == 41
    assert h["plate_half_mm"] == pytest.approx(gsd.FRINGE_HALF_MM, abs=1e-3)
    assert h["lift_mm"] == 0.0 and not h["flags"] & pg.FLAG_WATER_LIFT      # fixture has no water
    assert h["base_mm"] == pytest.approx(snap["baseThicknessMm"])
    assert h["total_ms"] > 0
    # part table: green + fringe + 2 bunkers; tee + flag markers
    assert [(p["kind"], p["index"]) for p in d["parts"]] == [
        (pg.KIND_GREEN, 1), (pg.KIND_FRINGE, 1), (pg.KIND_BUNKER, 1), (pg.KIND_BUNKER, 2)]
    assert [m["kind"] for m in d["markers"]] == [pg.MARKER_TEE, pg.MARKER_FLAG]
    green, fringe = part_of(d, pg.KIND_GREEN), part_of(d, pg.KIND_FRINGE)
    assert (green["nx"], green["ny"]) == (pg.GREEN_GRID_RES, pg.GREEN_GRID_RES)
    assert (fringe["nx"], fringe["ny"]) == (pg.FRINGE_RES_DEFAULT, pg.FRINGE_RES_DEFAULT)
    # exact byte accounting
    expected = pg.HEADER_STRUCT.size + len(d["parts"]) * pg.PART_STRUCT.size + len(d["markers"]) * pg.MARKER_STRUCT.size
    offset = 0
    for p in d["parts"]:
        assert p["data_offset"] == offset
        n = p["nx"] * p["ny"]
        offset += aligned(n * pg.HEIGHT_DTYPE.itemsize + n * pg.MASK_DTYPE.itemsize)
    assert len(buf) == expected + offset
    assert d["blob_start"] == expected
    for p in d["parts"]:
        assert np.isfinite(p["heights"]).all() and p["mask"].any()
        assert p["zmin"] <= p["zmax"] and p["xmin"] < p["xmax"] and p["ymin"] < p["ymax"]
        inside = p["heights"][p["mask"]]
        assert p["zmin"] == pytest.approx(float(inside.min()), abs=1e-3)
        assert p["zmax"] == pytest.approx(float(inside.max()), abs=1e-3)
    assert fringe["xmin"] == pytest.approx(-gsd.FRINGE_HALF_MM, abs=1e-3)
    assert fringe["ymax"] == pytest.approx(gsd.FRINGE_HALF_MM, abs=1e-3)


def test_f2_fringe_res_option_changes_grid_size(client):
    d = pg.decode_preview(post(client, load_snapshot(), **{pg.REQ_FRINGE_RES: FRINGE_RES_ALT}).data)
    f = part_of(d, pg.KIND_FRINGE)
    assert (f["nx"], f["ny"]) == (FRINGE_RES_ALT, FRINGE_RES_ALT)


def test_f3_markers_follow_the_snapshot(client):
    snap = load_snapshot()
    d = pg.decode_preview(post(client, snap).data)
    tee = next(m for m in d["markers"] if m["kind"] == pg.MARKER_TEE)
    assert tee["x"] == pytest.approx(-gsd.FRINGE_HALF_MM + snap["tee_hole"]["x_mm"], abs=1e-3)
    assert tee["y"] == pytest.approx(gsd.FRINGE_HALF_MM - snap["tee_hole"]["y_mm"], abs=1e-3)
    assert tee["radius"] == pytest.approx(pg.TEE_RADIUS_MM, abs=1e-4)
    snap2 = copy.deepcopy(snap); snap2.pop("tee_hole")
    d2 = pg.decode_preview(post(client, snap2).data)
    assert [m["kind"] for m in d2["markers"]] == [pg.MARKER_FLAG]


# --------------------------------------------------------------------------------------------------
# E: errors
# --------------------------------------------------------------------------------------------------
def test_e1_bad_requests(client):
    r = client.post(ROUTE, data="not json", content_type="text/plain")
    assert r.status_code == pg.HTTP_STATUS_BY_CODE[pg.CODE_BAD_REQUEST] and r.get_json()["code"] == pg.CODE_BAD_REQUEST
    snap = load_snapshot()
    for body in ({pg.REQ_SNAPSHOT: snap, pg.REQ_SEQ: -1},
                 {pg.REQ_SNAPSHOT: snap, pg.REQ_SEQ: "x"},
                 {pg.REQ_SNAPSHOT: snap, pg.REQ_FRINGE_RES: pg.FRINGE_RES_MIN - 1},
                 {pg.REQ_SNAPSHOT: snap, pg.REQ_FRINGE_RES: pg.FRINGE_RES_MAX + 1},
                 {pg.REQ_SNAPSHOT: snap, pg.REQ_GREEN_MODE: "bogus"},
                 {pg.REQ_SNAPSHOT: "nope"}):
        r = client.post(ROUTE, json=body)
        assert r.status_code == pg.HTTP_STATUS_BY_CODE[pg.CODE_BAD_REQUEST], body
        assert r.get_json()[app_module.KEY_STATUS] == app_module.STATUS_ERROR


def test_e2_no_green_and_missing_image(client):
    snap = load_snapshot()
    no_green = copy.deepcopy(snap)
    no_green[gsd.EGM_KEY_POLYGONS] = [p for p in no_green[gsd.EGM_KEY_POLYGONS] if p[gsd.EGM_KEY_TYPE] != gsd.POLY_TYPE_GREEN]
    r = post(client, no_green)
    assert (r.status_code, r.get_json()["code"]) == (pg.HTTP_STATUS_BY_CODE[pg.CODE_NO_GREEN], pg.CODE_NO_GREEN)
    gone = copy.deepcopy(snap); gone[pg.SNAPSHOT_KEY_IMAGE] = "no such image.png"
    r = post(client, gone)
    assert (r.status_code, r.get_json()["code"]) == (pg.HTTP_STATUS_BY_CODE[pg.CODE_IMAGE_NOT_FOUND], pg.CODE_IMAGE_NOT_FOUND)


def test_e3_busy_while_generate_runs(client):
    with app_module.degrid_cleanup.TRACKER.generate_guard():
        r = post(client, load_snapshot())
    assert (r.status_code, r.get_json()["code"]) == (pg.HTTP_STATUS_BY_CODE[pg.CODE_BUSY], pg.CODE_BUSY)


# --------------------------------------------------------------------------------------------------
# S: statelessness
# --------------------------------------------------------------------------------------------------
def test_s1_no_file_write_no_egm_no_database(client, monkeypatch, tmp_path):
    snap = load_snapshot()
    image = image_path_of(snap)
    watched = [FIXTURE_EGM, Path(image), Path(app_module.DB_PATH)]
    before = {str(p): (p.stat().st_mtime_ns, p.stat().st_size) for p in watched if p.exists()}
    writes: list = []
    real_open = builtins.open

    def spy_open(file, mode="r", *a, **k):
        if any(ch in str(mode) for ch in WRITE_MODE_CHARS):
            writes.append((str(file), mode))
        return real_open(file, mode, *a, **k)

    def no_db(*a, **k):
        raise AssertionError("the preview must not open a database")

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(sqlite3, "connect", no_db)
    monkeypatch.setattr(app_module, "get_db", no_db, raising=False)
    for _ in range(2):                                   # cold (slow path) then warm
        assert post(client, snap).status_code == 200
    assert writes == []
    after = {str(p): (p.stat().st_mtime_ns, p.stat().st_size) for p in watched if p.exists()}
    assert before == after


def test_s2_snapshot_is_not_mutated(client):
    snap = load_snapshot()
    frozen = copy.deepcopy(snap)
    assert post(client, snap).status_code == 200
    assert snap == frozen
    body = {pg.REQ_SNAPSHOT: snap}
    assert json.dumps(body, sort_keys=True) == json.dumps({pg.REQ_SNAPSHOT: frozen}, sort_keys=True)


def test_s3_generator_globals_restored(client):
    saved = (gsd.BASE_THICKNESS_MM, gsd.BUNKER_FLOOR_MIN_MM)
    snap = load_snapshot(); snap["baseThicknessMm"] = BASE_THICKNESS_ALT_MM
    d = pg.decode_preview(post(client, snap).data)
    assert d["header"]["base_mm"] == pytest.approx(BASE_THICKNESS_ALT_MM)
    assert (gsd.BASE_THICKNESS_MM, gsd.BUNKER_FLOOR_MIN_MM) == saved


# --------------------------------------------------------------------------------------------------
# G: green cache
# --------------------------------------------------------------------------------------------------
def test_g1_miss_then_hit(client):
    snap = load_snapshot()
    runs0, hits0 = pg.STATS["green_slow_runs"], pg.STATS["green_cache_hits"]
    d1 = pg.decode_preview(post(client, snap).data)
    assert not d1["header"]["flags"] & pg.FLAG_GREEN_CACHE_HIT
    assert pg.STATS["green_slow_runs"] == runs0 + 1 and len(pg.GREEN_CACHE) == 1
    edited = copy.deepcopy(snap); edited["gridCellHeights"]["0"] = 3.0         # a cell edit must not re-solve
    d2 = pg.decode_preview(post(client, edited).data)
    assert d2["header"]["flags"] & pg.FLAG_GREEN_CACHE_HIT
    assert pg.STATS["green_slow_runs"] == runs0 + 1 and pg.STATS["green_cache_hits"] == hits0 + 1
    np.testing.assert_array_equal(part_of(d1, pg.KIND_GREEN)["heights"], part_of(d2, pg.KIND_GREEN)["heights"])
    assert d2["header"]["green_ms"] < d1["header"]["green_ms"]


def test_g2_moving_the_green_outline_is_a_miss(client):
    snap = load_snapshot()
    post(client, snap)
    moved = copy.deepcopy(snap)
    green = next(p for p in moved[gsd.EGM_KEY_POLYGONS] if p[gsd.EGM_KEY_TYPE] == gsd.POLY_TYPE_GREEN)
    green[gsd.EGM_KEY_POINTS][0]["x"] += MOVED_GREEN_POINT_PX
    runs0 = pg.STATS["green_slow_runs"]
    d = pg.decode_preview(post(client, moved).data)
    assert not d["header"]["flags"] & pg.FLAG_GREEN_CACHE_HIT and pg.STATS["green_slow_runs"] == runs0 + 1
    # moving a BUNKER must not invalidate the green
    bunk = copy.deepcopy(snap)
    trap = next(p for p in bunk[gsd.EGM_KEY_POLYGONS] if p[gsd.EGM_KEY_TYPE] == gsd.POLY_TYPE_TRAP)
    trap[gsd.EGM_KEY_POINTS][0]["x"] += MOVED_GREEN_POINT_PX
    d2 = pg.decode_preview(post(client, bunk).data)
    assert d2["header"]["flags"] & pg.FLAG_GREEN_CACHE_HIT


def test_g3_cached_only_refuses_the_slow_path(client):
    snap = load_snapshot()
    runs0 = pg.STATS["green_slow_runs"]
    r = post(client, snap, **{pg.REQ_GREEN_MODE: pg.GREEN_MODE_CACHED_ONLY})
    assert (r.status_code, r.get_json()["code"]) == (pg.HTTP_STATUS_BY_CODE[pg.CODE_GREEN_CACHE_MISS], pg.CODE_GREEN_CACHE_MISS)
    assert pg.STATS["green_slow_runs"] == runs0
    assert post(client, snap).status_code == 200
    assert post(client, snap, **{pg.REQ_GREEN_MODE: pg.GREEN_MODE_CACHED_ONLY}).status_code == 200


def test_g4_cache_is_bounded(client):
    snap = load_snapshot()
    green = next(p for p in snap[gsd.EGM_KEY_POLYGONS] if p[gsd.EGM_KEY_TYPE] == gsd.POLY_TYPE_GREEN)
    for i in range(pg.GREEN_CACHE_MAX_ENTRIES + 2):
        green[gsd.EGM_KEY_POINTS][0]["x"] += 1.0
        assert post(client, snap, **{pg.REQ_FRINGE_RES: pg.FRINGE_RES_MIN}).status_code == 200
    assert len(pg.GREEN_CACHE) == pg.GREEN_CACHE_MAX_ENTRIES


# --------------------------------------------------------------------------------------------------
# T: tail re-run
# --------------------------------------------------------------------------------------------------
def reference_tail(snap: dict) -> np.ndarray:
    """Generate's own tail applied to the cached raw field (what the green must equal, before the lift)."""
    egm, boundary = pg._prepare_geometry(snap)
    gsd._apply_run_base_thickness(egm)
    raw = pg.GREEN_CACHE.get(pg.green_cache_key(image_path_of(snap), boundary))
    elevation = float(egm.get(gsd.EGM_KEY_ELEVATION_RANGE) or gsd.ELEVATION_RANGE_MM)
    z, _ = gsd.soften_extremes(raw.z_raw, raw.inside_mask, elevation_range_mm=elevation)
    z_mm, _ = gsd.finish_green_heights_mm(z, raw.inside_mask, egm)
    return np.flipud(z_mm), np.flipud(raw.inside_mask)


@pytest.mark.parametrize("change", [
    {gsd.EGM_KEY_ELEVATION_RANGE: ELEVATION_RANGE_ALT_MM},
    {gsd.EGM_KEY_Z_SCALE: Z_SCALE_ALT},
    {gsd.EGM_KEY_ELEVATION_RANGE: ELEVATION_RANGE_ALT_MM, gsd.EGM_KEY_Z_SCALE: Z_SCALE_ALT},
])
def test_t1_tail_reruns_without_a_new_solve(client, change):
    snap = load_snapshot()
    base = pg.decode_preview(post(client, snap).data)
    runs0, tails0 = pg.STATS["green_slow_runs"], pg.STATS["tail_runs"]
    changed = copy.deepcopy(snap); changed.update(change)
    d = pg.decode_preview(post(client, changed).data)
    assert pg.STATS["green_slow_runs"] == runs0                  # no re-solve
    assert pg.STATS["tail_runs"] == tails0 + 1                   # tail re-ran
    got = part_of(d, pg.KIND_GREEN)
    want, mask = reference_tail(changed)
    np.testing.assert_allclose(got["heights"][mask], want[mask], atol=1e-3)
    assert not np.allclose(got["heights"][mask], part_of(base, pg.KIND_GREEN)["heights"][mask])
    if gsd.EGM_KEY_ELEVATION_RANGE in change:
        assert got["zmax"] - got["zmin"] <= change[gsd.EGM_KEY_ELEVATION_RANGE] * change.get(gsd.EGM_KEY_Z_SCALE, 1.0) + 0.5
    # the fringe seam follows the changed green (it is built from the same tail)
    assert not np.allclose(part_of(d, pg.KIND_FRINGE)["heights"], part_of(base, pg.KIND_FRINGE)["heights"])


def test_t2_identical_tail_inputs_are_served_from_the_tail_cache(client):
    snap = load_snapshot()
    post(client, snap)
    tails0, hits0 = pg.STATS["tail_runs"], pg.STATS["tail_cache_hits"]
    edited = copy.deepcopy(snap); edited["gridCellHeights"]["1"] = 4.0
    d = pg.decode_preview(post(client, edited).data)
    assert pg.STATS["tail_runs"] == tails0 and pg.STATS["tail_cache_hits"] == hits0 + 1
    assert d["header"]["flags"] & pg.FLAG_TAIL_CACHE_HIT


def test_t3_limiter_is_not_scale_proportional(monkeypatch):
    """Why the raw field (not the finished green) is cached: scaling AFTER the limiter != limiter after scaling."""
    n = 41
    yy, xx = np.mgrid[0:n, 0:n]
    cone = np.maximum(0.0, 1.0 - np.hypot(xx - n // 2, yy - n // 2) / (n / 2))
    mask = np.ones_like(cone, dtype=bool)
    egm = {gsd.EGM_KEY_ELEVATION_RANGE: ELEVATION_RANGE_ALT_MM}
    monkeypatch.setattr(gsd, "BASE_THICKNESS_MM", gsd.DEFAULT_BASE_THICKNESS_MM)
    low, _ = gsd.finish_green_heights_mm(cone, mask, egm)
    high, _ = gsd.finish_green_heights_mm(cone, mask, {gsd.EGM_KEY_ELEVATION_RANGE: ELEVATION_RANGE_ALT_MM * 3})
    naive = gsd.BASE_THICKNESS_MM + (low - gsd.BASE_THICKNESS_MM) * 3
    assert np.abs(high - naive).max() > 0.5


# --------------------------------------------------------------------------------------------------
# N: no arrows
# --------------------------------------------------------------------------------------------------
def blank_copy(tmp_path: Path) -> str:
    import cv2
    path = tmp_path / "blank.png"
    cv2.imwrite(str(path), np.full((1057, 809, 3), 255, dtype=np.uint8))      # fixture imageSize, no arrows
    return str(path)


def test_n1_no_arrows_gives_a_flat_green(tmp_path):
    snap = load_snapshot()
    image = blank_copy(tmp_path)
    d = pg.decode_preview(pg.encode_preview(pg.compute_preview(snap, image)))
    assert d["header"]["flags"] & pg.FLAG_GREEN_FLAT
    g = part_of(d, pg.KIND_GREEN)
    inside = g["heights"][g["mask"]]
    assert inside.min() == pytest.approx(inside.max()) == pytest.approx(gsd.DEFAULT_BASE_THICKNESS_MM)
    # water hole: flat at FLAT_FALLBACK_Z_WATER_MM, plus the 2 mm lift everywhere
    wet = add_pond(snap)
    d2 = pg.decode_preview(pg.encode_preview(pg.compute_preview(wet, image)))
    g2 = part_of(d2, pg.KIND_GREEN)
    inside2 = g2["heights"][g2["mask"]]
    assert d2["header"]["flags"] & pg.FLAG_WATER_LIFT and d2["header"]["lift_mm"] == gsd.WATER_HOLE_LIFT_MM
    assert inside2.min() == pytest.approx(inside2.max())
    assert inside2.max() == pytest.approx(gsd.FLAT_FALLBACK_Z_WATER_MM + gsd.WATER_HOLE_LIFT_MM)


# --------------------------------------------------------------------------------------------------
# A: accuracy against a real Generate run (slow: ~1 min)
# --------------------------------------------------------------------------------------------------
def add_pond(snap: dict) -> dict:
    """Copy of the snapshot with one water polygon in a free corner of the plate (mm -> px via the generator's transform)."""
    wet = copy.deepcopy(snap)
    egm, boundary = pg._prepare_geometry(wet)
    scale, centroid = gsd._compute_px_to_mm(boundary, egm)
    cx, cy = WATER_LIFT_PROBE_XY_MM
    hx, hy = WATER_LIFT_PROBE_HALF_MM
    pts_mm = [(cx - hx, cy - hy), (cx, cy - hy * 1.2), (cx + hx, cy - hy), (cx + hx * 1.1, cy),
              (cx + hx, cy + hy), (cx, cy + hy * 1.2), (cx - hx, cy + hy), (cx - hx * 1.1, cy)]
    pts_px = [{"x": x / scale + centroid[0], "y": centroid[1] - y / scale} for x, y in pts_mm]
    wet[gsd.EGM_KEY_POLYGONS].append({"name": "Water", gsd.EGM_KEY_TYPE: gsd.POLY_TYPE_WATER, "closed": True,
                                      gsd.EGM_KEY_POINTS: pts_px})
    wet["includeBoundaryRegion"] = True            # derives the 5 mm boulders ring and shrinks the water
    return wet


def run_generate(snap: dict, tmp_path: Path) -> "trimesh.Scene":
    """Real Generate on a temp copy; every output goes to tmp_path (course dirs and diagnostics redirected)."""
    import generate_stl_3mf as gen
    import trimesh
    out = tmp_path / "gen_out"; out.mkdir()
    original = gen.course_paths
    mp = pytest.MonkeyPatch()
    try:
        def sandboxed(course):
            paths = dict(original(course))
            paths[gen.PATH_KEY_3MFS] = paths[gen.PATH_KEY_STLS] = str(out)
            return paths
        mp.setattr(gsd, "course_paths", sandboxed)
        mp.setattr(gsd, "SAVE_DIAGNOSTIC_IMAGES", False)
        egm_copy = out / "copy.egm"
        egm_copy.write_text(json.dumps(snap))
        path_3mf = gsd.run_pipeline(str(egm_copy), generation_id=GEN_ID)
        return trimesh.load(path_3mf)
    finally:
        mp.undo()


def top_vertices(mesh) -> np.ndarray:
    v = np.asarray(mesh.vertices)
    return v[v[:, 2] > TOP_VERTEX_MIN_Z_MM]


def stats(diff: np.ndarray) -> dict:
    a = np.abs(diff)
    return {"n": int(a.size), "median": float(np.median(a)), "p95": float(np.percentile(a, 95)),
            "p99": float(np.percentile(a, 99)), "max": float(a.max()), "mean": float(diff.mean())}


@pytest.mark.slow
def test_a1_preview_matches_real_generate(client, tmp_path):
    """Preview heights vs the 3MF Generate writes for the SAME state (temp copy; real EGMs and DB untouched).

    Stated tolerances (mm), and why they are what they are:
      green     max |d| <= GREEN_ABS_TOL_MM        same code path -> essentially exact (float32 + flag hole)
      fringe    median <= FRINGE_MEDIAN_TOL_MM; p99 <= FRINGE_P99_TOL_MM; interior max <= FRINGE_MAX_INTERIOR_TOL_MM
                (Generate re-samples its 200x200 field onto a finer mesh by 4-point inverse-distance weighting,
                 which adds up to ~1-2 mm on steep banks; the preview samples the field itself.)
                within FRINGE_SEAM_BAND_MM of the green outline: max <= FRINGE_MAX_SEAM_TOL_MM
                (Generate snaps the seam ring to the green rim; the preview deliberately omits the seam snap.)
      bunkers   |preview - local mean of Generate's raked surface| <= BUNKER_MAX_TOL_MM (rake is +/-0.5 mm about the mean)
    """
    import shapely
    from scipy.interpolate import LinearNDInterpolator
    from scipy.spatial import cKDTree
    from shapely.geometry import Polygon

    snap = load_snapshot()
    snap[gsd.EGM_KEY_GRID_RESOLUTION] = FIXTURE_GRID_FINE
    snap["includeFringeWithoutGrass"] = True            # smooth fringe reference node "fringe_no_grass_sample"
    scene = run_generate(snap, tmp_path)
    d = pg.decode_preview(post(client, snap).data)

    egm, boundary = pg._prepare_geometry(snap)
    scale, centroid = gsd._compute_px_to_mm(boundary, egm)
    green_outline = Polygon(gsd._px_to_mm_2d(boundary.copy(), scale, centroid)).exterior
    report = {}

    def grid(p):
        xs = np.linspace(p["xmin"], p["xmax"], p["nx"]); ys = np.linspace(p["ymin"], p["ymax"], p["ny"])
        return np.meshgrid(xs, ys)

    # green
    gp = part_of(d, pg.KIND_GREEN)
    X, Y = grid(gp); m = gp["mask"]
    t = top_vertices(scene.geometry[gsd.BAMBU_NAME_GREEN])
    dist, idx = cKDTree(t[:, :2]).query(np.column_stack([X[m], Y[m]]))
    near = dist < 1e-2
    assert near.sum() > 0.9 * m.sum()
    report["green"] = stats((gp["heights"][m] - t[idx, 2])[near])
    assert report["green"]["max"] <= GREEN_ABS_TOL_MM

    # fringe
    fp = part_of(d, pg.KIND_FRINGE)
    X, Y = grid(fp); m = fp["mask"]
    t = top_vertices(scene.geometry[gsd.SCENE_NAME_FRINGE_NO_GRASS_SAMPLE])
    z = LinearNDInterpolator(t[:, :2], t[:, 2])(X[m], Y[m]); ok = np.isfinite(z)
    diff = (fp["heights"][m] - z)[ok]
    to_green = np.array([green_outline.distance(shapely.Point(x, y)) for x, y in zip(X[m][ok], Y[m][ok])])
    interior = to_green >= FRINGE_SEAM_BAND_MM
    report["fringe_interior"] = stats(diff[interior]); report["fringe_seam_band"] = stats(diff[~interior])
    assert report["fringe_interior"]["median"] <= FRINGE_MEDIAN_TOL_MM
    assert report["fringe_interior"]["p99"] <= FRINGE_P99_TOL_MM
    assert report["fringe_interior"]["max"] <= FRINGE_MAX_INTERIOR_TOL_MM
    assert report["fringe_seam_band"]["max"] <= FRINGE_MAX_SEAM_TOL_MM

    # bunkers
    for i in (1, 2):
        bp = part_of(d, pg.KIND_BUNKER, i)
        X, Y = grid(bp); m = bp["mask"]
        t = top_vertices(scene.geometry[f"{gsd.BAMBU_NAME_BUNKER_PREFIX}{gsd.BAMBU_NAME_SEPARATOR}{i}"])
        near = cKDTree(t[:, :2]).query_ball_point(np.column_stack([X[m], Y[m]]), r=BUNKER_MEAN_RADIUS_MM)
        mean = np.array([t[j, 2].mean() if len(j) else np.nan for j in near]); ok = np.isfinite(mean)
        report[f"bunker_{i}"] = stats((bp["heights"][m] - mean)[ok])
        assert report[f"bunker_{i}"]["max"] <= BUNKER_MAX_TOL_MM
    print("\nACCURACY (mm, preview - Generate):", json.dumps(report, indent=1))


@pytest.mark.slow
def test_a2_water_lift_water_and_boulders_match_generate(client, tmp_path):
    """A pond + auto boulders ring: green lifted 2 mm (water hole), water/boulders flat and NOT lifted."""
    from scipy.spatial import cKDTree
    snap = add_pond(load_snapshot())
    snap["includeFringeWithoutGrass"] = True
    scene = run_generate(snap, tmp_path)
    d = pg.decode_preview(post(client, snap).data)
    assert d["header"]["flags"] & pg.FLAG_WATER_LIFT and d["header"]["lift_mm"] == gsd.WATER_HOLE_LIFT_MM
    names = set(scene.geometry)
    checked = 0
    for kind, prefix in ((pg.KIND_WATER, "water"), (pg.KIND_BOULDERS, "boulders")):
        for p in [q for q in d["parts"] if q["kind"] == kind]:
            name = f"{prefix}_{p['index']}"
            assert name in names, (name, names)
            t = top_vertices(scene.geometry[name])
            gen_top = float(np.median(t[:, 2]))                  # flat slab: every top vertex has the same Z
            prev = p["heights"][p["mask"]]
            assert prev.min() == pytest.approx(prev.max())       # flat in the preview too
            assert abs(float(prev.mean()) - gen_top) <= WATER_ABS_TOL_MM, (name, float(prev.mean()), gen_top)
            checked += 1
    assert checked >= 2                                          # water + boulders ring
    # lift on the green: preview == Generate's green mesh top
    gp = part_of(d, pg.KIND_GREEN)
    t = top_vertices(scene.geometry[gsd.BAMBU_NAME_GREEN])
    assert abs(float(gp["zmax"]) - float(t[:, 2].max())) <= GREEN_ABS_TOL_MM


# --------------------------------------------------------------------------------------------------
# R: Generate unchanged by the extraction
# --------------------------------------------------------------------------------------------------
def test_r1_extracted_helpers_match_the_old_inline_maths():
    # _fringe_clamp_z: scalar and array agree with the formula it replaced
    res, ceiling = 50, 20.0
    r, c = np.meshgrid(np.arange(res), np.arange(res), indexing="ij")
    z = np.linspace(-5, 40, res * res).reshape(res, res)
    tilt = gsd.FRINGE_PLATEAU_TILT_MM * (r + c) / (2 * (res - 1))
    want = np.maximum(gsd.FRINGE_MIN_THICKNESS_MM + tilt, np.minimum(z, ceiling))
    np.testing.assert_array_equal(gsd._fringe_clamp_z(z, r, c, res, ceiling), want)
    assert gsd._fringe_clamp_z(7.0, 3, 4, res, ceiling) == pytest.approx(float(want[3, 4]) if z[3, 4] == 7.0 else
                                                                        max(gsd.FRINGE_MIN_THICKNESS_MM + gsd.FRINGE_PLATEAU_TILT_MM * (3 + 4) / (2 * (res - 1)), 7.0))
    # the vectorised ownership test returns what the per-cell loop did
    from shapely.geometry import Polygon, box
    poly = Polygon([(-20, -20), (30, -15), (25, 35), (-15, 30)])
    half, n = gsd.FRINGE_HALF_MM, FIXTURE_GRID_FINE
    side = 2 * half / n
    cells = {str(i): float(i % 7) for i in range(0, n * n, 3)}
    cells["abc"] = 1.0; cells["99999"] = 1.0
    loop = []
    for k, mm in cells.items():
        try:
            ci = int(k); v = float(mm)
        except ValueError:
            continue
        if ci < 0 or ci >= n * n:
            continue
        rr, cc = divmod(ci, n)
        x0, y0 = -half + cc * side, -half + rr * side
        if poly.covers(box(x0, y0, x0 + side, y0 + side)):
            loop.append((ci, v))
    assert gsd._trap_inside_cells(poly, cells, side, half, n) == loop and loop


# --------------------------------------------------------------------------------------------------
# L: latency
# --------------------------------------------------------------------------------------------------
def timed(client, snap, runs=LATENCY_RUNS, **extra):
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        r = post(client, snap, **extra)
        times.append((time.perf_counter() - t0) * 1000.0)
        assert r.status_code == 200
    return times


@pytest.mark.parametrize("grid", [FIXTURE_GRID_COARSE, FIXTURE_GRID_FINE])
def test_l1_latency(client, grid):
    snap = load_snapshot(grid)
    t0 = time.perf_counter(); assert post(client, snap).status_code == 200
    cold = (time.perf_counter() - t0) * 1000.0                                     # slow path: image + solve
    paint = []                                                                      # cell edit: raw + tail cached
    for i in range(LATENCY_RUNS):
        edited = copy.deepcopy(snap); edited["gridCellHeights"]["0"] = float(i)
        t0 = time.perf_counter(); assert post(client, edited).status_code == 200
        paint.append((time.perf_counter() - t0) * 1000.0)
    tail = []                                                                       # Elevation range change: tail re-runs
    for i in range(LATENCY_RUNS):
        changed = copy.deepcopy(snap); changed[gsd.EGM_KEY_ELEVATION_RANGE] = 8.0 + i * 0.5
        t0 = time.perf_counter(); assert post(client, changed).status_code == 200
        tail.append((time.perf_counter() - t0) * 1000.0)
    lo, hi = LATENCY_TARGET_MS
    row = {"grid": f"{grid}x{grid}", "cold_slow_path_ms": round(cold),
           "cell_edit_median_ms": round(statistics.median(paint)), "cell_edit_max_ms": round(max(paint)),
           "range_change_median_ms": round(statistics.median(tail)), "range_change_max_ms": round(max(tail)),
           "target_ms": f"{lo:.0f}-{hi:.0f}",
           "cell_edit_within_target": statistics.median(paint) <= hi,
           "range_change_within_target": statistics.median(tail) <= hi}
    print("\nLATENCY", json.dumps(row))
    assert max(paint) < LATENCY_HARD_CEILING_MS and max(tail) < LATENCY_HARD_CEILING_MS
