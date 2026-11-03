"""
test_generate_perf_v630.py -- v6.30 Generate speed-ups must be exact.

Q1  _PolylineIndex.query == brute-force _min_dist_to_polyline (distance and foot point,
    within QUERY_TOL_MM) on random closed polylines, incl. long segments and query points
    inside / outside / on the curve.
Q2  Degenerate polylines (1 point, a few points, closed ring with repeated end point).
P1  _earcut_interior_pinholes == the frozen v6.29 algorithm (below) on random meshes with
    random pinholes: identical face arrays.

The reference implementation of P1 is the v6.29 function, frozen verbatim.
Run: python -m pytest app/tests/test_generate_perf_v630.py -x -q --durations=5
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
import gradient_surface_diagnostic as gsd  # noqa: E402

RNG_SEED = 630
QUERY_TOL_MM = 1e-6
POLYLINE_SIZES = (3, 5, 9, 40, 400, 3000)
POLYLINE_RADIUS_MM = 80.0
POLYLINE_RADIUS_JITTER_MM = 15.0
QUERIES_PER_POLYLINE = 300
QUERY_SPREAD_MM = 120.0
LONG_SEGMENT_POLYLINE = ((0.0, 0.0), (100.0, 0.0), (100.0, 1.0), (0.0, 1.0), (-50.0, 0.5),
                         (-50.0, 0.4), (-50.0, 0.3), (-50.0, 0.2), (-50.0, 0.1))
GRID_SIZE = 20                      # mesh vertices per side
GRID_SPACING_MM = 1.0
GRID_JITTER_MM = 0.2
HOLE_COUNTS = (1, 5, 20)
HOLE_MERGE_PROB = 0.35              # chance a removed triangle also removes a neighbour (bigger pinhole)
MESH_TRIALS = 4


def _random_polyline(rng, n):
    ang = np.sort(rng.uniform(0, 2 * np.pi, n))
    r = POLYLINE_RADIUS_MM + rng.uniform(-POLYLINE_RADIUS_JITTER_MM, POLYLINE_RADIUS_JITTER_MM, n)
    return np.column_stack([r * np.cos(ang), r * np.sin(ang)])


def _check_queries(pts, queries):
    idx = gsd._PolylineIndex(pts)
    for x, y in queries:
        d0, x0, y0 = gsd._min_dist_to_polyline(float(x), float(y), pts)
        d1, x1, y1 = idx.query(float(x), float(y))
        assert abs(d0 - d1) <= QUERY_TOL_MM
        assert abs(x0 - x1) <= QUERY_TOL_MM and abs(y0 - y1) <= QUERY_TOL_MM


@pytest.mark.parametrize("n", POLYLINE_SIZES)
def test_Q1_index_matches_bruteforce(n):
    rng = np.random.default_rng(RNG_SEED + n)
    pts = _random_polyline(rng, n)
    queries = rng.uniform(-QUERY_SPREAD_MM, QUERY_SPREAD_MM, (QUERIES_PER_POLYLINE, 2))
    queries = np.vstack([queries, pts[: min(n, 50)]])   # points exactly on the curve
    _check_queries(pts, queries)


def test_Q1_long_segments():
    rng = np.random.default_rng(RNG_SEED)
    pts = np.asarray(LONG_SEGMENT_POLYLINE, dtype=np.float64)
    _check_queries(pts, rng.uniform(-QUERY_SPREAD_MM, QUERY_SPREAD_MM, (QUERIES_PER_POLYLINE, 2)))


def test_Q2_degenerate():
    one = np.array([[3.0, 4.0]])
    d, x, y = gsd._PolylineIndex(one).query(0.0, 0.0)
    assert d == float("inf") and (x, y) == (3.0, 4.0)
    rng = np.random.default_rng(RNG_SEED)
    ring = _random_polyline(rng, gsd.POLYLINE_INDEX_MIN_SEGMENTS + 4)
    ring = np.vstack([ring, ring[:1]])                  # closed with repeated end point (zero-length segment)
    _check_queries(ring, rng.uniform(-QUERY_SPREAD_MM, QUERY_SPREAD_MM, (QUERIES_PER_POLYLINE, 2)))


def _grid_mesh_with_holes(rng, holes):
    g = GRID_SIZE
    xy = np.array([(i * GRID_SPACING_MM, j * GRID_SPACING_MM) for j in range(g) for i in range(g)], dtype=np.float64)
    xy += rng.uniform(-GRID_JITTER_MM, GRID_JITTER_MM, xy.shape)
    vid = lambda i, j: j * g + i
    tris = []
    for j in range(g - 1):
        for i in range(g - 1):
            a, b, c, d = vid(i, j), vid(i + 1, j), vid(i + 1, j + 1), vid(i, j + 1)
            tris += [[a, b, c], [a, c, d]]
    tris = np.asarray(tris, dtype=np.int64)
    keep = np.ones(len(tris), bool)
    for _ in range(holes):
        # interior triangles only (keep a 2-cell margin so holes never touch the outer ring)
        for _try in range(100):
            k = int(rng.integers(len(tris)))
            if np.all(xy[tris[k], 0] > 2 * GRID_SPACING_MM) and np.all(xy[tris[k], 0] < (g - 3) * GRID_SPACING_MM) \
               and np.all(xy[tris[k], 1] > 2 * GRID_SPACING_MM) and np.all(xy[tris[k], 1] < (g - 3) * GRID_SPACING_MM):
                break
        keep[k] = False
        if rng.random() < HOLE_MERGE_PROB:
            keep[k ^ 1] = False
    faces = tris[keep]
    ring = set()
    for i in range(g - 1):
        for e in ((vid(i, 0), vid(i + 1, 0)), (vid(i, g - 1), vid(i + 1, g - 1)),
                  (vid(0, i), vid(0, i + 1)), (vid(g - 1, i), vid(g - 1, i + 1))):
            ring.add((min(e), max(e)))
    return faces, ring, xy


@pytest.mark.parametrize("holes", HOLE_COUNTS)
def test_P1_pinholes_identical_to_v629(holes):
    rng = np.random.default_rng(RNG_SEED + holes)
    for _ in range(MESH_TRIALS):
        faces, ring, xy = _grid_mesh_with_holes(rng, holes)
        new = gsd._earcut_interior_pinholes(faces.copy(), set(ring), xy)
        ref = _reference_earcut_interior_pinholes(faces.copy(), set(ring), xy)
        assert new.shape == ref.shape
        assert np.array_equal(new, ref)
        assert len(new) > len(faces)       # the holes really were closed


# ---------------------------------------------------------------------------
# Frozen v6.29 reference (verbatim, only renamed)
# ---------------------------------------------------------------------------

def _reference_earcut_interior_pinholes(
    top_faces: "np.ndarray",
    ring_edges_set: "set[tuple[int, int]]",
    all_xy: "np.ndarray",
    dtype=None,
) -> "np.ndarray":
    """Find interior boundary-edge chains and earcut-triangulate them.

    A boundary edge is count=1 in `top_faces`. We split them into ring edges
    (left for the wall to close) and interior edges. Interior edges form one
    or more closed chains (each surrounding a pinhole) — walk each chain and
    earcut-triangulate it in 2D using the vertex XY positions.

    Returns the augmented face array (possibly unchanged).
    """
    import numpy as np

    if top_faces.size == 0:
        return top_faces
    if dtype is None:
        dtype = top_faces.dtype

    # 1. Collect interior boundary edges.
    es = np.sort(
        np.vstack([top_faces[:, [0, 1]], top_faces[:, [1, 2]], top_faces[:, [2, 0]]]),
        axis=1,
    )
    uniq, cnt = np.unique(es, axis=0, return_counts=True)
    bedges = uniq[cnt == 1]
    interior_bedges = [
        (int(a), int(b)) for a, b in bedges
        if (int(a), int(b)) not in ring_edges_set
    ]
    if not interior_bedges:
        return top_faces

    # 2. Group into chains by vertex adjacency.
    nbr: dict[int, list[int]] = {}
    for a, b in interior_bedges:
        nbr.setdefault(a, []).append(b)
        nbr.setdefault(b, []).append(a)

    visited_edges: set[tuple[int, int]] = set()
    chains: list[list[int]] = []
    for start in list(nbr.keys()):
        # Walk connected edges from `start`.
        if all(((min(start, v), max(start, v)) in visited_edges) for v in nbr.get(start, [])):
            continue
        comp_verts: set[int] = {start}
        stack = [start]
        while stack:
            u = stack.pop()
            for v in nbr.get(u, []):
                key = (min(u, v), max(u, v))
                if key in visited_edges:
                    continue
                visited_edges.add(key)
                if v not in comp_verts:
                    comp_verts.add(v)
                    stack.append(v)
        # Try to walk a closed loop over this component.
        comp_edges = [
            (a, b) for a, b in interior_bedges
            if a in comp_verts and b in comp_verts
        ]
        if len(comp_edges) < 3:
            continue
        # Order the vertices into a cycle (greedy walker).
        local_nbr: dict[int, list[int]] = {}
        for a, b in comp_edges:
            local_nbr.setdefault(a, []).append(b)
            local_nbr.setdefault(b, []).append(a)
        start_v = comp_edges[0][0]
        chain = [start_v]
        used_edges: set[tuple[int, int]] = set()
        cur = start_v
        prev = None
        while True:
            nxts = [n for n in local_nbr.get(cur, []) if (min(cur, n), max(cur, n)) not in used_edges]
            if not nxts:
                break
            nxt = nxts[0]
            used_edges.add((min(cur, nxt), max(cur, nxt)))
            if nxt == start_v:
                break
            chain.append(nxt)
            prev = cur
            cur = nxt
            if len(chain) > len(comp_edges) + 2:
                break  # safety
        # Only accept if we closed the loop (last-to-first edge exists).
        if (min(chain[-1], chain[0]), max(chain[-1], chain[0])) not in {
            (min(a, b), max(a, b)) for a, b in comp_edges
        }:
            continue
        chains.append(chain)

    if not chains:
        return top_faces

    # Build edge-count index for diagonal selection in quad cases.
    _ec_init: dict[tuple[int, int], int] = {
        (int(a), int(b)): int(c) for (a, b), c in zip(uniq, cnt)
    }

    # 3. Earcut each chain in 2D.
    added_tris: list[list[int]] = []
    for chain in chains:
        pts = all_xy[chain]  # (K, 2)
        area2 = 0.0
        for i in range(len(chain)):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % len(chain)]
            area2 += (x1 * y2 - x2 * y1)
        if area2 < 0:
            chain = list(reversed(chain))
            pts = all_xy[chain]
        # Special case: quadrilateral — pick the diagonal with count 0 in top_faces
        # so neither resulting triangle creates a non-manifold edge.
        if len(chain) == 4:
            a, b, c, d = chain
            diag1 = (min(int(a), int(c)), max(int(a), int(c)))
            diag2 = (min(int(b), int(d)), max(int(b), int(d)))
            d1_c = _ec_init.get(diag1, 0)
            d2_c = _ec_init.get(diag2, 0)
            if d1_c < d2_c:
                added_tris.extend([[a, b, c], [a, c, d]])
                continue
            if d2_c < d1_c or d1_c == 0:
                added_tris.extend([[b, c, d], [b, d, a]])
                continue
        tris = gsd._earcut_simple_polygon(pts, chain)
        if tris:
            added_tris.extend(tris)

    if not added_tris:
        return top_faces

    # Dedup: skip earcut triangles whose edges are already count=2 in top_faces
    # (adding them would create non-manifold edges). Also skip if the exact
    # triangle (same 3 verts) already exists.
    present_count: dict[tuple[int, int], int] = {}
    for a, b in uniq:
        present_count[(int(a), int(b))] = int(cnt[np.where((uniq == (a, b)).all(axis=1))[0][0]])
    existing_tris = {tuple(sorted(int(x) for x in f)) for f in top_faces}

    kept: list[list[int]] = []
    for tri in added_tris:
        t = tuple(sorted(int(x) for x in tri))
        if t in existing_tris:
            continue
        tri_es = [
            (min(int(tri[0]), int(tri[1])), max(int(tri[0]), int(tri[1]))),
            (min(int(tri[1]), int(tri[2])), max(int(tri[1]), int(tri[2]))),
            (min(int(tri[0]), int(tri[2])), max(int(tri[0]), int(tri[2]))),
        ]
        # Reject if any of this triangle's edges is already count=2 in top_faces
        # (adding would make it count=3, i.e. non-manifold).
        # Ring edges are closed by the wall faces later, so the top surface may
        # carry at most ONE face per ring edge (limit 1, not 2).
        if any(present_count.get(e, 0) >= (1 if e in ring_edges_set else 2)
               for e in tri_es):
            continue
        kept.append(tri)
        existing_tris.add(t)
        for e in tri_es:
            present_count[e] = present_count.get(e, 0) + 1

    rejected = len(added_tris) - len(kept)
    if not kept:
        if rejected:
            print(f"    Sand earcut-interior: rejected all {rejected} candidate triangle(s) (dup/non-manifold)")
        return top_faces
    print(f"    Sand earcut-interior: closed {len(chains)} pinhole(s) with "
          f"{len(kept)} triangle(s) ({rejected} rejected)")
    return np.vstack([top_faces, np.asarray(kept, dtype=dtype)])
