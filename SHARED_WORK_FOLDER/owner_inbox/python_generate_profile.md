# Python Generate profile

(The original v6.29 profile write-up was not on disk; raw numbers live in /private/tmp/claude-501/topo_profile_snapshot/results/. Hot spots found: `_min_dist_to_polyline` 17-23 s per hole, `_earcut_interior_pinholes` 30 s on Delaveaga 15 (83 s for the sand-trap stage), fringe stage 60-80 s.)

## After v6.30

Unprofiled wall-clock of `run_pipeline`, same harness, same machine, sequential runs, scratch EGM copies only.
Before = HEAD (v6.29), After = v6.30.

| Hole | Before | After | Speed-up |
|---|---|---|---|
| Delaveaga 11.40 | 83.1 s | 40.7 s | 2.0x |
| Delaveaga 15 | 134.5 s | 41.7 s | 3.2x |
| Stanford 08 | 133.0 s | 57.2 s | 2.3x |
| Seabright 05 | > 600 s (killed at the earlier 10-min limit) | 58.7 s | > 10x |

Delaveaga 11.40 stages: fringe mesh 60.0 s -> 15.5 s (profiled before) ; sand traps 6.1 s -> 1.2 s.

### What changed (app/gradient_surface_diagnostic.py)
- `_PolylineIndex` (new): exact spatial index for repeated nearest-point-on-polyline queries. A KD-tree on vertices gives an upper bound dv; a KD-tree on segment midpoints returns every segment within dv + longest-half-segment; the original per-segment arithmetic then runs only on those candidates, in index order. Result is bit-identical to brute force (same formula, same first-index tie-break). Used at the four call sites (boundary-vertex snap, `_cell_fringe_z`, green seam reseat, trap/water seam reseat). The brute-force `_min_dist_to_polyline` is kept as the reference.
- `_earcut_interior_pinholes`: the real cost was two quadratic scans, not the earcut. (a) `present_count` was built with an `np.where` over all unique edges per edge (O(U^2)); now a dict built in O(U). (b) each connected component re-scanned all interior boundary edges; components are now labelled once and edges grouped. Chain walk order and output unchanged.
- Constants: `POLYLINE_INDEX_MIN_SEGMENTS`, `POLYLINE_INDEX_RADIUS_PAD_MM`.

### Equivalence (Delaveaga 11.40, before vs after 3MF, per body)
| Body | Verts | Faces | Volume | Max vertex diff |
|---|---|---|---|---|
| bunker_1 | 21345 | 42686 | 11854.282 | 0.0 |
| bunker_2 | 15110 | 30216 | 5252.174 | 0.0 |
| fringe | 426225 | 852458 | 195718.919 | 0.0 |
| green | 29237 | 58474 | 142055.399 | 0.0 |

Bounds identical; vertices bit-for-bit identical, so there is no float-noise difference at all.

### Tests
- New `app/tests/test_generate_perf_v630.py` (11 tests, 0.6 s): index vs brute force on random/long-segment/degenerate polylines (tolerance 1e-6 mm), and new pinhole function vs the frozen v6.29 function on random meshes with random holes (identical face arrays).
- `test_fringe_exact_cut_v629.py`: 14 passed (includes the end-to-end Delaveaga 11.40 generate).
- `test_fringe_boundary_anchors.py`: all 14 skipped in this environment, so it adds no coverage; the v6.29 end-to-end test is what exercises the new index.

### Remaining time (Delaveaga 11.40, ~41 s)
Fringe mesh ~15 s, label/short-ID engraving ~16 s (next target), green mesh ~3 s.
