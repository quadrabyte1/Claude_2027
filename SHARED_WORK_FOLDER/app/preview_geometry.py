"""Live 3D preview geometry for the Boundary Editor (phase 1, server side).

Turns a snapshot of the editor's in-memory state (the same dict the editor POSTs to save an EGM) into
coarse HEIGHT GRIDS for every printed part, using the generator's own height maths
(``gradient_surface_diagnostic``).  No mesh is built: no triangulation, boolean cuts, textures, grass, rake,
engraving, seam polish, median/spike filters or seam snap.  Heights are true-scale millimetres of the printed
part (base plate at z = 0).  On a water hole the green, fringe and bunkers include the 2 mm water-hole lift;
water and boulders do NOT (Generate sizes those slabs from the unlifted fringe).

The module is STATELESS apart from two bounded in-memory caches (no files, no EGM, no database):
  * green cache  -- the RAW least-squares field per (image identity + green outline);
  * tail cache   -- the tail result (soften -> rescale -> slope limit -> Z scale) per (green key, tail params).

Binary wire format: see ``encode_preview`` and owner_inbox/preview_api_contract.md.
Coding standard: every value below is a named constant; the tests import the same names.
"""
from __future__ import annotations

import collections
import contextlib
import copy
import hashlib
import io
import math
import os
import struct
import sys
import threading
import time
from dataclasses import dataclass, field

import numpy as np

import gradient_surface_diagnostic as gsd

# --------------------------------------------------------------------------------------------------
# Wire format
# --------------------------------------------------------------------------------------------------
WIRE_MAGIC: bytes = b"EGMP"
WIRE_VERSION: int = 1
WIRE_BYTE_ORDER: str = "<"                       # little endian, no padding
HEADER_FIELDS: tuple = (                         # (name, struct code) in wire order
    ("magic", "4s"), ("version", "H"), ("flags", "H"), ("seq", "I"),
    ("plate_half_mm", "f"), ("lift_mm", "f"), ("base_mm", "f"),
    ("total_ms", "f"), ("green_ms", "f"), ("fringe_ms", "f"),
    ("n_parts", "H"), ("n_markers", "H"),
)
PART_FIELDS: tuple = (
    ("kind", "B"), ("index", "B"), ("nx", "H"), ("ny", "H"), ("reserved", "H"),
    ("xmin", "f"), ("ymin", "f"), ("xmax", "f"), ("ymax", "f"),
    ("zmin", "f"), ("zmax", "f"), ("data_offset", "I"),
)
MARKER_FIELDS: tuple = (
    ("kind", "B"), ("pad0", "B"), ("pad1", "B"), ("pad2", "B"),
    ("x", "f"), ("y", "f"), ("z", "f"), ("radius", "f"),
)
HEADER_STRUCT = struct.Struct(WIRE_BYTE_ORDER + "".join(code for _n, code in HEADER_FIELDS))
PART_STRUCT = struct.Struct(WIRE_BYTE_ORDER + "".join(code for _n, code in PART_FIELDS))
MARKER_STRUCT = struct.Struct(WIRE_BYTE_ORDER + "".join(code for _n, code in MARKER_FIELDS))
HEIGHT_DTYPE = np.dtype("<f4")
MASK_DTYPE = np.dtype("u1")
DATA_ALIGN_BYTES: int = 4                        # every part's data block is padded to this multiple

# part kinds
KIND_GREEN: int = 1
KIND_FRINGE: int = 2
KIND_BUNKER: int = 3
KIND_WATER: int = 4
KIND_BOULDERS: int = 5
# marker kinds
MARKER_TEE: int = 1
MARKER_FLAG: int = 2
# header flag bits
FLAG_GREEN_CACHE_HIT: int = 1
FLAG_GREEN_FLAT: int = 2          # no arrows detected: flat green
FLAG_WATER_LIFT: int = 4          # water hole: 2 mm lift included in green / fringe / bunker heights and the markers
FLAG_TAIL_CACHE_HIT: int = 8

# --------------------------------------------------------------------------------------------------
# Request vocabulary
# --------------------------------------------------------------------------------------------------
REQ_SNAPSHOT: str = "snapshot"
REQ_SEQ: str = "seq"
REQ_FRINGE_RES: str = "fringeRes"
REQ_GREEN_MODE: str = "greenMode"
GREEN_MODE_AUTO: str = "auto"                    # cache miss -> slow path
GREEN_MODE_CACHED_ONLY: str = "cachedOnly"       # cache miss -> error CODE_GREEN_CACHE_MISS (no slow path)
GREEN_MODES: tuple = (GREEN_MODE_AUTO, GREEN_MODE_CACHED_ONLY)
FRINGE_RES_DEFAULT: int = 96
FRINGE_RES_MIN: int = 32
FRINGE_RES_MAX: int = gsd.FRINGE_GRID_RES
SEQ_MAX: int = 2 ** 32 - 1
SNAPSHOT_KEY_IMAGE: str = "image"
SNAPSHOT_KEY_IMAGE_COURSE: str = "imageCourse"
SNAPSHOT_KEY_TEE: str = "tee_hole"
SNAPSHOT_KEY_TEE_X: str = "x_mm"
SNAPSHOT_KEY_TEE_Y: str = "y_mm"
SNAPSHOT_KEY_FLAG_X: str = "flagOffsetXMm"
SNAPSHOT_KEY_FLAG_Y: str = "flagOffsetYMm"
SNAPSHOT_KEY_INCLUDE_BOUNDARY: str = "includeBoundaryRegion"

# error codes (JSON body {"status": "error", "code": ..., "msg": ...})
CODE_BAD_REQUEST: str = "bad_request"
CODE_NO_GREEN: str = "no_green"
CODE_IMAGE_NOT_FOUND: str = "image_not_found"
CODE_GREEN_CACHE_MISS: str = "green_cache_miss"
CODE_BUSY: str = "busy"
CODE_INTERNAL: str = "internal_error"
HTTP_STATUS_BY_CODE: dict = {
    CODE_BAD_REQUEST: 400, CODE_NO_GREEN: 400, CODE_IMAGE_NOT_FOUND: 404,
    CODE_GREEN_CACHE_MISS: 409, CODE_BUSY: 503, CODE_INTERNAL: 500,
}

# --------------------------------------------------------------------------------------------------
# Geometry parameters
# --------------------------------------------------------------------------------------------------
GREEN_GRID_RES: int = gsd.GRADIENT_GRID_RES      # the generator's real green grid
PART_GRID_STEP_MM: float = 1.0                   # bunker / water / boulders grid spacing target
PART_GRID_MIN: int = 8
PART_GRID_MAX: int = 64
PART_MASK_PAD_STEPS: float = 1.0                 # part mask = footprint grown by this many grid steps
FLAG_HOLE_DIAMETER_MM: float = 3.0               # drill_flag_hole diameter used by save_stl_meshes
FLAG_RADIUS_MM: float = FLAG_HOLE_DIAMETER_MM / 2.0
TEE_RADIUS_MM: float = gsd.TEE_HOLE_DIAMETER_MM / 2.0
FINITE_FILL_FLOOR_MM: float = 0.0                # value written where a part has no surface and the grid has no valid cell

# caches
GREEN_CACHE_MAX_ENTRIES: int = 6
TAIL_CACHE_MAX_ENTRIES: int = 8
POLY_CACHE_MAX_ENTRIES: int = 6
CACHE_KEY_DIGEST = hashlib.sha256
IMAGE_IDENTITY_FMT: str = "{path}|{mtime_ns}|{size}"
ENCODING: str = "utf-8"


class PreviewError(Exception):
    """Raised for any condition the endpoint turns into a JSON error body."""

    def __init__(self, code: str, msg: str):
        super().__init__(msg)
        self.code = code
        self.msg = msg

    @property
    def http_status(self) -> int:
        return HTTP_STATUS_BY_CODE.get(self.code, HTTP_STATUS_BY_CODE[CODE_INTERNAL])


@dataclass
class Part:
    kind: int
    index: int
    xmin: float
    ymin: float
    xmax: float
    ymax: float
    heights: np.ndarray            # (ny, nx) float, row 0 = ymin, col 0 = xmin
    mask: np.ndarray               # (ny, nx) bool


@dataclass
class Marker:
    kind: int
    x: float
    y: float
    z: float
    radius: float


@dataclass
class PreviewResult:
    seq: int
    flags: int
    lift_mm: float
    base_mm: float
    parts: list = field(default_factory=list)
    markers: list = field(default_factory=list)
    total_ms: float = 0.0
    green_ms: float = 0.0
    fringe_ms: float = 0.0


# --------------------------------------------------------------------------------------------------
# Caches and locking (the only state in this module; bounded, in memory)
# --------------------------------------------------------------------------------------------------
class _BoundedCache:
    """Thread-safe LRU dict with a hard size bound."""

    def __init__(self, max_entries: int):
        self._max = max_entries
        self._data: "collections.OrderedDict" = collections.OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                return self._data[key]
        return None

    def put(self, key, value) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


GREEN_CACHE = _BoundedCache(GREEN_CACHE_MAX_ENTRIES)
TAIL_CACHE = _BoundedCache(TAIL_CACHE_MAX_ENTRIES)
POLY_CACHE = _BoundedCache(POLY_CACHE_MAX_ENTRIES)
# The generator keeps the run's base thickness in module globals, so one preview computes at a time.
COMPUTE_LOCK = threading.Lock()
# Counters the tests (and a curious maintainer) can read.
STATS = {"green_slow_runs": 0, "green_cache_hits": 0, "tail_runs": 0, "tail_cache_hits": 0}


class _ThreadMutedStdout:
    """sys.stdout proxy: drops writes from threads that set ``muted`` and forwards all others untouched.
    The generator functions print a lot; at preview rates that would flood the server log and (with a plain
    redirect_stdout) could swallow another thread's Generate log."""

    def __init__(self, real):
        self._real = real
        self.local = threading.local()

    def write(self, text):
        if getattr(self.local, "muted", False):
            return len(text)
        return self._real.write(text)

    def flush(self):
        if not getattr(self.local, "muted", False):
            self._real.flush()

    def __getattr__(self, name):
        return getattr(self._real, name)


_MUTE_INSTALL_LOCK = threading.Lock()


@contextlib.contextmanager
def _quiet():
    with _MUTE_INSTALL_LOCK:
        if not isinstance(sys.stdout, _ThreadMutedStdout):
            sys.stdout = _ThreadMutedStdout(sys.stdout)
        proxy = sys.stdout
    proxy.local.muted = True
    try:
        yield
    finally:
        proxy.local.muted = False


# --------------------------------------------------------------------------------------------------
# Snapshot helpers
# --------------------------------------------------------------------------------------------------
def _digest(*chunks: bytes) -> str:
    h = CACHE_KEY_DIGEST()
    for c in chunks:
        h.update(c)
    return h.hexdigest()


def image_identity(image_path: str) -> str:
    st = os.stat(image_path)
    return IMAGE_IDENTITY_FMT.format(path=os.path.realpath(image_path), mtime_ns=st.st_mtime_ns, size=st.st_size)


def _validate_snapshot(snapshot) -> None:
    if not isinstance(snapshot, dict):
        raise PreviewError(CODE_BAD_REQUEST, "snapshot must be a JSON object")
    polys = snapshot.get(gsd.EGM_KEY_POLYGONS)
    if not isinstance(polys, list):
        raise PreviewError(CODE_BAD_REQUEST, "snapshot.polygons must be a list")
    if not any(isinstance(p, dict) and p.get(gsd.EGM_KEY_TYPE) == gsd.POLY_TYPE_GREEN for p in polys):
        raise PreviewError(CODE_NO_GREEN, "snapshot has no green polygon")


def _prepare_geometry(snapshot: dict):
    """(egm_data, green_boundary_px) -- the same preparation load_egm does (green scale, spline +
    Chaikin smoothing of green / bunker / water outlines).  Memoised on the polygons + greenScale because the
    smoothing is independent of cell edits.  Returns a deep copy so callers may mutate it."""
    key = _digest(
        repr(snapshot.get(gsd.EGM_KEY_POLYGONS)).encode(ENCODING),
        repr(snapshot.get(gsd.EGM_KEY_GREEN_SCALE)).encode(ENCODING),
    )
    cached = POLY_CACHE.get(key)
    if cached is None:
        data = copy.deepcopy(snapshot)
        green_poly = next(p for p in data[gsd.EGM_KEY_POLYGONS] if p.get(gsd.EGM_KEY_TYPE) == gsd.POLY_TYPE_GREEN)
        boundary_px = gsd._prepare_egm_geometry(data, green_poly)
        cached = (data[gsd.EGM_KEY_POLYGONS], boundary_px)
        POLY_CACHE.put(key, cached)
    polys, boundary_px = cached
    data = {k: v for k, v in snapshot.items() if k != gsd.EGM_KEY_POLYGONS}
    data = copy.deepcopy(data)
    data[gsd.EGM_KEY_POLYGONS] = copy.deepcopy(polys)
    return data, boundary_px.copy()


# --------------------------------------------------------------------------------------------------
# Green: raw field (cached) + tail (re-run)
# --------------------------------------------------------------------------------------------------
@dataclass
class GreenRaw:
    xs_grid: np.ndarray
    ys_grid: np.ndarray
    inside_mask: np.ndarray
    z_raw: "np.ndarray | None"     # None = no arrows detected (flat green)
    n_arrows: int


def green_cache_key(image_path: str, green_boundary_px: np.ndarray) -> str:
    return _digest(image_identity(image_path).encode(ENCODING), np.ascontiguousarray(green_boundary_px).tobytes())


def _solve_green_raw(image_path: str, green_boundary_px: np.ndarray) -> GreenRaw:
    """The slow path: arrow detection, direction field, least-squares height -- Generate's steps 2-4."""
    import cv2
    img = cv2.imread(image_path)
    if img is None:
        raise PreviewError(CODE_IMAGE_NOT_FOUND, "cannot read image")
    arrows = gsd.detect_arrows(img, green_boundary_px, dark_threshold=gsd.ARROW_DARK_V_THRESHOLD,
                               max_arrow_area=gsd.ARROW_MAX_AREA_PX_PIPELINE)
    xs_grid, ys_grid, inside_mask, gx, gy = gsd.build_gradient_field(arrows, green_boundary_px, grid_res=GREEN_GRID_RES)
    z_raw = None if not arrows else gsd.solve_poisson_height(inside_mask, gx, gy)
    return GreenRaw(xs_grid, ys_grid, inside_mask, z_raw, len(arrows))


def _green_tail(raw: GreenRaw, egm_data: dict) -> np.ndarray:
    """Soften -> rescale -> slope limit -> Z scale, exactly as Generate (flat green when no arrows)."""
    if raw.z_raw is None:
        fallback = gsd.flat_fallback_z_mm(egm_data)
        z = np.where(raw.inside_mask, fallback, np.nan)
    else:
        elevation = float(egm_data.get(gsd.EGM_KEY_ELEVATION_RANGE) or gsd.ELEVATION_RANGE_MM)
        z, _stats = gsd.soften_extremes(raw.z_raw, raw.inside_mask, elevation_range_mm=elevation)
    z_mm, _info = gsd.finish_green_heights_mm(z, raw.inside_mask, egm_data)
    return z_mm


def tail_cache_key(green_key: str, egm_data: dict) -> str:
    return _digest(
        green_key.encode(ENCODING),
        repr((egm_data.get(gsd.EGM_KEY_ELEVATION_RANGE), egm_data.get(gsd.EGM_KEY_Z_SCALE),
              gsd.BASE_THICKNESS_MM, gsd._hole_has_water(egm_data))).encode(ENCODING),
    )


@dataclass
class RimEntry:
    """Everything that depends only on the green (outline + tail), not on cells: cached with the tail."""
    gbnd: np.ndarray
    bnd_z: np.ndarray
    bnd_kd: object
    default_memo: dict
    xs_green: np.ndarray
    ys_green: np.ndarray
    green_excl: object


RIM_CACHE = _BoundedCache(TAIL_CACHE_MAX_ENTRIES)


def _rim_for(raw: GreenRaw, z_mm, egm, boundary_px, scale, centroid_px, ceiling, tail_key: str) -> RimEntry:
    """Green-rim heights + helpers, memoised per (tail key, image size, fringeBoundaryHeights anchors).
    The anchors are clamped to the cell-dependent ceiling, so the ceiling joins the key only when anchors exist."""
    from scipy.spatial import cKDTree
    anchors = egm.get("fringeBoundaryHeights") or []
    key = _digest(tail_key.encode(ENCODING), repr(egm.get("imageSize")).encode(ENCODING),
                  repr(anchors).encode(ENCODING), (repr(ceiling) if anchors else "").encode(ENCODING))
    entry = RIM_CACHE.get(key)
    if entry is None:
        xs_green = (raw.xs_grid - centroid_px[0]) * scale
        ys_green = -(raw.ys_grid - centroid_px[1]) * scale
        gbnd = gsd._px_to_mm_2d(boundary_px.copy(), scale, centroid_px)
        bnd_z = gsd._fringe_boundary_z(z_mm, raw.inside_mask, xs_green, ys_green, gbnd, egm, scale, centroid_px, ceiling)
        _green, green_excl = gsd._green_exclusion_polygons(gbnd)
        entry = RimEntry(gbnd, bnd_z, cKDTree(gbnd), {}, xs_green, ys_green, green_excl)
        RIM_CACHE.put(key, entry)
    return entry


# --------------------------------------------------------------------------------------------------
# Grid helpers
# --------------------------------------------------------------------------------------------------
def _part_grid(bounds, pad_mm: float):
    """(xmin, ymin, xmax, ymax, nx, ny, X, Y) for a part's bbox grown by pad_mm."""
    x0, y0, x1, y1 = bounds
    x0, y0, x1, y1 = x0 - pad_mm, y0 - pad_mm, x1 + pad_mm, y1 + pad_mm
    nx = int(min(PART_GRID_MAX, max(PART_GRID_MIN, math.ceil((x1 - x0) / PART_GRID_STEP_MM) + 1)))
    ny = int(min(PART_GRID_MAX, max(PART_GRID_MIN, math.ceil((y1 - y0) / PART_GRID_STEP_MM) + 1)))
    X, Y = np.meshgrid(np.linspace(x0, x1, nx), np.linspace(y0, y1, ny))
    return x0, y0, x1, y1, nx, ny, X, Y


def _mask_of(footprint, X, Y, x0, x1, nx) -> np.ndarray:
    import shapely
    step = (x1 - x0) / max(nx - 1, 1)
    grown = footprint.buffer(PART_MASK_PAD_STEPS * step)
    return np.asarray(shapely.contains_xy(grown, X.ravel(), Y.ravel())).reshape(X.shape)


def _bilinear(xs, ys, Z, x, y) -> float:
    """Bilinear sample of a regular grid (xs, ys ascending) at one point, clamped to the grid."""
    fx = np.clip((x - xs[0]) / (xs[-1] - xs[0]), 0.0, 1.0) * (len(xs) - 1)
    fy = np.clip((y - ys[0]) / (ys[-1] - ys[0]), 0.0, 1.0) * (len(ys) - 1)
    ix, iy = min(int(fx), len(xs) - 2), min(int(fy), len(ys) - 2)
    tx, ty = fx - ix, fy - iy
    z00, z01 = Z[iy, ix], Z[iy, ix + 1]
    z10, z11 = Z[iy + 1, ix], Z[iy + 1, ix + 1]
    return float((1 - ty) * ((1 - tx) * z00 + tx * z01) + ty * ((1 - tx) * z10 + tx * z11))


# --------------------------------------------------------------------------------------------------
# The computation
# --------------------------------------------------------------------------------------------------
def compute_preview(snapshot: dict, image_path: str, *, seq: int = 0, fringe_res: int = FRINGE_RES_DEFAULT,
                    green_mode: str = GREEN_MODE_AUTO) -> PreviewResult:
    """Height grids for every part.  Pure function of (snapshot, image bytes); never touches files, EGMs or
    databases.  Serialised by COMPUTE_LOCK because the generator reads module globals for the base thickness
    (set here and restored afterwards)."""
    _validate_snapshot(snapshot)
    if green_mode not in GREEN_MODES:
        raise PreviewError(CODE_BAD_REQUEST, f"greenMode must be one of {GREEN_MODES}")
    if not isinstance(fringe_res, int) or not (FRINGE_RES_MIN <= fringe_res <= FRINGE_RES_MAX):
        raise PreviewError(CODE_BAD_REQUEST, f"fringeRes must be an integer in [{FRINGE_RES_MIN}, {FRINGE_RES_MAX}]")
    if not (os.path.isfile(image_path)):
        raise PreviewError(CODE_IMAGE_NOT_FOUND, "image file not found")
    with COMPUTE_LOCK, _quiet():
        saved = (gsd.BASE_THICKNESS_MM, gsd.BUNKER_FLOOR_MIN_MM)
        try:
            return _compute_locked(snapshot, image_path, seq, fringe_res, green_mode)
        finally:
            gsd.BASE_THICKNESS_MM, gsd.BUNKER_FLOOR_MIN_MM = saved


def _compute_locked(snapshot, image_path, seq, fringe_res, green_mode) -> PreviewResult:
    import shapely
    from shapely.geometry import Polygon as ShapelyPolygon

    t_start = time.perf_counter()
    egm, boundary_px = _prepare_geometry(snapshot)
    base_mm = gsd._apply_run_base_thickness(egm)
    if bool(egm.get(SNAPSHOT_KEY_INCLUDE_BOUNDARY, False)):
        gsd._apply_boundary_region_derivation(egm, boundary_px)
    has_water = gsd._hole_has_water(egm)
    lift = gsd.WATER_HOLE_LIFT_MM if (gsd.WATER_HOLE_LIFT_ENABLED and has_water) else 0.0
    flags = FLAG_WATER_LIFT if lift else 0

    # ---- green: raw field from cache (or the slow path), then the tail --------------------------------
    t_green = time.perf_counter()
    green_key = green_cache_key(image_path, boundary_px)
    raw = GREEN_CACHE.get(green_key)
    if raw is None:
        if green_mode == GREEN_MODE_CACHED_ONLY:
            raise PreviewError(CODE_GREEN_CACHE_MISS, "green outline/image changed; the slow solve is needed")
        raw = _solve_green_raw(image_path, boundary_px)
        GREEN_CACHE.put(green_key, raw)
        STATS["green_slow_runs"] += 1
    else:
        flags |= FLAG_GREEN_CACHE_HIT
        STATS["green_cache_hits"] += 1
    if raw.z_raw is None:
        flags |= FLAG_GREEN_FLAT
    tkey = tail_cache_key(green_key, egm)
    z_mm = TAIL_CACHE.get(tkey)
    if z_mm is None:
        z_mm = _green_tail(raw, egm)
        TAIL_CACHE.put(tkey, z_mm)
        STATS["tail_runs"] += 1
    else:
        flags |= FLAG_TAIL_CACHE_HIT
        STATS["tail_cache_hits"] += 1
    green_ms = (time.perf_counter() - t_green) * 1000.0

    # ---- fringe -----------------------------------------------------------------------------------------
    t_fringe = time.perf_counter()
    scale, centroid_px = gsd._compute_px_to_mm(boundary_px, egm)
    half = gsd.FRINGE_HALF_MM

    if gsd.ENABLE_MOUNT_BORE:
        bore_cx, bore_cy = -half + gsd.MOUNT_BORE_INSET_MM, +half - gsd.MOUNT_BORE_INSET_MM
        pipe_circle = gsd._build_pipe_circle(bore_cx, bore_cy)
        holes = [(bore_cx, bore_cy, gsd.MOUNT_BORE_OUTER_RADIUS_MM)]
    else:
        pipe_circle, holes = None, []

    egm_fringe, bunker_owned = gsd._fringe_egm_data(egm, boundary_px, holes)
    ceiling = gsd._fringe_z_ceiling_mm(egm, egm_fringe)
    rim = _rim_for(raw, z_mm, egm, boundary_px, scale, centroid_px, ceiling, tkey)
    gbnd, bnd_z = rim.gbnd, rim.bnd_z
    xs_green, ys_green = rim.xs_green, rim.ys_green

    xs = np.linspace(-half, half, fringe_res)
    ys = np.linspace(-half, half, fringe_res)
    GX, GY = np.meshgrid(xs, ys)
    z_tps = gsd._fringe_tps_surface(egm_fringe, gbnd, bnd_z, GX, GY, bnd_kd=rim.bnd_kd, default_memo=rim.default_memo)
    rr, cc = np.meshgrid(np.arange(fringe_res), np.arange(fringe_res), indexing="ij")
    z_cell = gsd._fringe_clamp_z(z_tps, rr, cc, fringe_res, ceiling)

    carve = gsd._fringe_carve_shapes(egm, scale, centroid_px, holes)
    green_excl = rim.green_excl
    px, py = GX.ravel(), GY.ravel()
    in_green = np.asarray(shapely.contains_xy(green_excl, px, py))
    if carve.traps_union is not None:
        shapely.prepare(carve.traps_union)
        hs = (xs[1] - xs[0]) / 2.0
        carved = np.asarray(shapely.intersects(shapely.box(px - hs, py - hs, px + hs, py + hs), carve.traps_union))
    else:
        carved = np.zeros_like(in_green)
    in_hole = np.zeros_like(in_green)
    for hx, hy, hr in holes:
        in_hole |= np.hypot(px - hx, py - hy) <= hr
    fringe_mask = ~in_green & ~carved & ~in_hole
    virtual_mask = ~in_green & carved
    z_flat = z_cell.ravel()

    want_virtual = bool(bunker_owned) or (
        gsd.BUNKER_BODY_MODE in (gsd.BUNKER_BODY_MODE_RULED, gsd.BUNKER_BODY_MODE_CELLS) and carve.traps_union is not None)
    bunker_field = None
    if want_virtual:
        comb = np.where(fringe_mask | virtual_mask, z_flat, np.nan).reshape(fringe_res, fringe_res)
        bunker_field = (xs.copy(), ys.copy(), comb)

    # nearest-fringe-vertex lookup for water / boulders flat heights (cells that are real fringe surface)
    from scipy.spatial import cKDTree
    fr_xy = np.column_stack([px[fringe_mask], py[fringe_mask]])
    fr_top = np.column_stack([fr_xy, z_flat[fringe_mask]])
    fr_kd = cKDTree(fr_xy) if len(fr_xy) else None

    result = PreviewResult(seq=seq, flags=flags, lift_mm=lift, base_mm=base_mm)

    # green part (row 0 = ymin; the generator's rows run top-down in the image)
    g_heights = np.flipud(z_mm)
    g_mask = np.flipud(raw.inside_mask)
    result.parts.append(Part(KIND_GREEN, 1, float(xs_green[0]), float(ys_green[-1]), float(xs_green[-1]), float(ys_green[0]),
                             _finite_fill(g_heights, g_mask) + lift, g_mask))
    result.parts.append(Part(KIND_FRINGE, 1, float(-half), float(-half), float(half), float(half),
                             z_cell + lift, fringe_mask.reshape(fringe_res, fringe_res)))

    # ---- bunkers ----------------------------------------------------------------------------------------
    traps = [p for p in egm.get(gsd.EGM_KEY_POLYGONS, []) if p.get(gsd.EGM_KEY_TYPE) == gsd.POLY_TYPE_TRAP]
    for i, trap in enumerate(traps, start=1):
        try:
            footprint = gsd._build_trap_footprint(trap, scale, centroid_px, pipe_circle, f"Trap {i}")
            if footprint is None:
                continue
            inset = footprint.buffer(-gsd.PRINT_TOLERANCE_MM)
            if inset.is_empty:
                continue
            inset = gsd.simplify_trap_outline(inset)
            floor_fn, _binfo, _ci, _ri, _gm = gsd._resolve_bunker_floor(footprint, egm, bunker_field, label=f"Trap {i}")
            x0, y0, x1, y1, nx, ny, X, Y = _part_grid(inset.bounds, 0.0)
            xy = np.column_stack([X.ravel(), Y.ravel()])
            if floor_fn is not None:
                z = np.asarray(floor_fn(xy), dtype=np.float64).reshape(ny, nx)
            else:                                   # no fringe field: flat, below the lowest adjoining fringe
                z = np.full((ny, nx), _flat_trap_height(inset, fr_kd, fr_top))
            result.parts.append(Part(KIND_BUNKER, i, x0, y0, x1, y1, z + lift, _mask_of(inset, X, Y, x0, x1, nx)))
        except Exception:
            continue                                # a failed bunker is simply absent, like Generate's warning path

    # ---- water --------------------------------------------------------------------------------------------
    water_shapely_mm = []
    for i, wp in enumerate([p for p in egm.get(gsd.EGM_KEY_POLYGONS, []) if p.get(gsd.EGM_KEY_TYPE) == gsd.POLY_TYPE_WATER], start=1):
        try:
            inset = gsd._water_inset_footprint(wp, scale, centroid_px, pipe_circle, f"Water {i}")
            if inset is None:
                continue
            h = _flat_height(inset, fr_kd, fr_top, gsd.TRAP_THICKNESS_MM)
            result.parts.append(_flat_part(KIND_WATER, i, inset, h))        # water is NOT lifted (Generate sizes it from the unlifted fringe)
        except Exception:
            continue
    for wp in egm.get(gsd.EGM_KEY_POLYGONS, []):
        if wp.get(gsd.EGM_KEY_TYPE) != gsd.POLY_TYPE_WATER:
            continue
        try:
            w_px = gsd._poly_to_dense_px(wp)
            wsp = ShapelyPolygon(gsd._px_to_mm_2d(w_px, scale, centroid_px))
            water_shapely_mm.append(wsp if wsp.is_valid else wsp.buffer(0))
        except Exception:
            pass
    # ---- boulders -----------------------------------------------------------------------------------------
    for i, bp in enumerate([p for p in egm.get(gsd.EGM_KEY_POLYGONS, []) if p.get(gsd.EGM_KEY_TYPE) == gsd.POLY_TYPE_BOULDERS], start=1):
        try:
            inset, _annulus = gsd._boulders_inset_footprint(bp, water_shapely_mm, scale, centroid_px, pipe_circle, f"Boulders {i}")
            if inset is None:
                continue
            h = _flat_height(inset, fr_kd, fr_top, gsd.TRAP_THICKNESS_MM)
            result.parts.append(_flat_part(KIND_BOULDERS, i, inset, h))     # boulders are NOT lifted either
        except Exception:
            continue

    # ---- markers --------------------------------------------------------------------------------------------
    tee = egm.get(SNAPSHOT_KEY_TEE)
    if tee:
        try:
            tx = -half + float(tee.get(SNAPSHOT_KEY_TEE_X))
            ty = +half - float(tee.get(SNAPSHOT_KEY_TEE_Y))
            tz = _bilinear(xs, ys, z_cell, tx, ty) + lift
            result.markers.append(Marker(MARKER_TEE, tx, ty, tz, TEE_RADIUS_MM))
        except (TypeError, ValueError, AttributeError):
            pass
    rows, cols = np.where(raw.inside_mask)
    if len(rows):
        fx = (xs_green[cols].min() + xs_green[cols].max()) / 2.0 + float(egm.get(SNAPSHOT_KEY_FLAG_X) or 0.0)
        fy = (ys_green[rows].min() + ys_green[rows].max()) / 2.0 + float(egm.get(SNAPSHOT_KEY_FLAG_Y) or 0.0)
        j = int(np.argmin((xs_green[cols] - fx) ** 2 + (ys_green[rows] - fy) ** 2))
        result.markers.append(Marker(MARKER_FLAG, float(fx), float(fy), float(z_mm[rows[j], cols[j]]) + lift, FLAG_RADIUS_MM))

    result.green_ms = green_ms
    result.fringe_ms = (time.perf_counter() - t_fringe) * 1000.0
    result.total_ms = (time.perf_counter() - t_start) * 1000.0
    return result


def _finite_fill(z: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Float copy of ``z`` with every cell outside ``mask`` set to the part's minimum (finite, never NaN)."""
    out = np.array(z, dtype=np.float64)
    fill = float(out[mask].min()) if mask.any() else FINITE_FILL_FLOOR_MM
    out[~mask | ~np.isfinite(out)] = fill
    return out


def _flat_height(inset, fr_kd, fr_top, fallback: float) -> float:
    if fr_kd is None:
        return float(fallback)
    h, _n = gsd._min_fringe_z_over_footprint(inset, fr_kd, fr_top)
    return h


def _flat_trap_height(inset, fr_kd, fr_top) -> float:
    """Bunker with no floor function: flat at (lowest adjoining fringe) + TRAP_FRINGE_OFFSET_MM, >= 1 mm."""
    if fr_kd is None:
        return float(gsd.TRAP_THICKNESS_MM)
    near = fr_kd.query_ball_point(np.asarray(inset.exterior.coords), r=gsd.TRAP_FRINGE_BOUNDARY_BAND_MM)
    idx = sorted({j for hit in near for j in hit})
    if not idx:
        return float(gsd.TRAP_THICKNESS_MM)
    return max(float(fr_top[idx, 2].min()) + gsd.TRAP_FRINGE_OFFSET_MM, 1.0)


def _flat_part(kind: int, index: int, inset, height: float) -> Part:
    x0, y0, x1, y1, nx, ny, X, Y = _part_grid(inset.bounds, 0.0)
    return Part(kind, index, x0, y0, x1, y1, np.full((ny, nx), height), _mask_of(inset, X, Y, x0, x1, nx))


# --------------------------------------------------------------------------------------------------
# Encoding
# --------------------------------------------------------------------------------------------------
def _pad(n: int) -> int:
    return (-n) % DATA_ALIGN_BYTES


def encode_preview(result: PreviewResult) -> bytes:
    """Serialise a PreviewResult: header | part table | marker table | data blob (see the API contract)."""
    blobs, entries, offset = [], [], 0
    for p in result.parts:
        ny, nx = p.heights.shape
        h = np.ascontiguousarray(p.heights, dtype=HEIGHT_DTYPE).tobytes()
        m = np.ascontiguousarray(p.mask, dtype=MASK_DTYPE).tobytes()
        data = h + m
        data += b"\0" * _pad(len(data))
        vals = p.heights[p.mask] if p.mask.any() else p.heights
        entries.append(PART_STRUCT.pack(p.kind, p.index, nx, ny, 0, p.xmin, p.ymin, p.xmax, p.ymax,
                                        float(vals.min()), float(vals.max()), offset))
        blobs.append(data)
        offset += len(data)
    header = HEADER_STRUCT.pack(WIRE_MAGIC, WIRE_VERSION, result.flags, result.seq & SEQ_MAX,
                                gsd.FRINGE_HALF_MM, result.lift_mm, result.base_mm,
                                result.total_ms, result.green_ms, result.fringe_ms,
                                len(result.parts), len(result.markers))
    markers = b"".join(MARKER_STRUCT.pack(m.kind, 0, 0, 0, m.x, m.y, m.z, m.radius) for m in result.markers)
    return header + b"".join(entries) + markers + b"".join(blobs)


def decode_preview(buf: bytes) -> dict:
    """Reference decoder (used by the tests; mirrors what the JS client does)."""
    hv = dict(zip((n for n, _c in HEADER_FIELDS), HEADER_STRUCT.unpack_from(buf, 0)))
    pos = HEADER_STRUCT.size
    parts = []
    for _ in range(hv["n_parts"]):
        parts.append(dict(zip((n for n, _c in PART_FIELDS), PART_STRUCT.unpack_from(buf, pos))))
        pos += PART_STRUCT.size
    markers = []
    for _ in range(hv["n_markers"]):
        markers.append(dict(zip((n for n, _c in MARKER_FIELDS), MARKER_STRUCT.unpack_from(buf, pos))))
        pos += MARKER_STRUCT.size
    blob = pos
    for p in parts:
        n = p["nx"] * p["ny"]
        base = blob + p["data_offset"]
        p["heights"] = np.frombuffer(buf, dtype=HEIGHT_DTYPE, count=n, offset=base).reshape(p["ny"], p["nx"])
        p["mask"] = np.frombuffer(buf, dtype=MASK_DTYPE, count=n, offset=base + n * HEIGHT_DTYPE.itemsize).reshape(p["ny"], p["nx"]).astype(bool)
    return {"header": hv, "parts": parts, "markers": markers, "blob_start": blob}
