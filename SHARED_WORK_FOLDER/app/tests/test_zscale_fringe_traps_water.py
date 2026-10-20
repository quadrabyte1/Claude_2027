"""
test_zscale_fringe_traps_water.py -- zScale must reach fringe, traps and water.

Root cause (2026-10-20): zScale was applied only to the green (save_stl_meshes).
run_pipeline built Z_mm_for_fringe from raw Z, so the fringe ignored it; traps
and water sample the flat fringe (min boundary Z - 2 mm), so they ignored it too.

Fix: shared apply_z_scale() used by the green and by Z_mm_for_fringe (after its
slope limiter).  Floors stay flat; only their height moves.

Z1  apply_z_scale: BASE + (Z-BASE)*zs inside mask, outside untouched.
Z2  apply_z_scale: clamp [0.5, 5.0], default/invalid -> 1.0 no-op.
Z3  Pipeline wiring: fringe gets apply_z_scale after limit_max_slope and before
    build_fringe_mesh; green path uses the same helper.
Z4  Trap surface from a fringe built on scaled Z is FLAT and sits higher
    (relief above BASE ratio == zScale).
Z5  Water + trap exporters are fed fringe_mesh_flat (so they inherit the scale).
Z6  No double scaling: fringe ceiling uses BASE + range*zs (matches scaled Z).

Run: python -m pytest app/tests/test_zscale_fringe_traps_water.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import Polygon

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
import gradient_surface_diagnostic as gsd  # noqa: E402

SRC = (APP_DIR / "gradient_surface_diagnostic.py").read_text()
BASE = gsd.BASE_THICKNESS_MM


def test_z1_transform_math():
    Z = np.array([[BASE, BASE + 4.0], [BASE + 2.0, 99.0]])
    mask = np.array([[True, True], [True, False]])
    out, zs = gsd.apply_z_scale(Z, mask, {"zScale": 2.0})
    assert zs == 2.0
    assert np.allclose(out[mask], [BASE, BASE + 8.0, BASE + 4.0])
    assert out[1, 1] == 99.0


def test_z2_clamp_and_default():
    Z = np.full((2, 2), BASE + 1.0); m = np.ones((2, 2), bool)
    assert gsd.apply_z_scale(Z, m, {})[1] == 1.0
    assert gsd.apply_z_scale(Z, m, {"zScale": "junk"})[1] == 1.0
    assert gsd.apply_z_scale(Z, m, {"zScale": 99})[1] == 5.0
    assert gsd.apply_z_scale(Z, m, {"zScale": 0.1})[1] == 0.5
    assert np.array_equal(gsd.apply_z_scale(Z, m, {"zScale": 1.0})[0], Z)


def test_z3_pipeline_wiring():
    assert hasattr(gsd, "apply_z_scale")
    i_lim = SRC.index("Z_mm_for_fringe, _fringe_slope_stats = limit_max_slope(")
    i_z = SRC.index("apply_z_scale(Z_mm_for_fringe")
    i_b = SRC.index("fringe_mesh = build_fringe_mesh(")
    assert i_lim < i_z < i_b
    assert "Z_mm, _z_scale = apply_z_scale(Z_mm, inside_mask, egm_data)" in SRC


def _fringe(z_top):
    xs = np.linspace(-30, 30, 25)
    verts = [[x, y, z_top] for x in xs for y in xs]
    f = []
    n = len(xs)
    for i in range(n - 1):
        for j in range(n - 1):
            a = i * n + j
            f += [[a, a + 1, a + n + 1], [a, a + n + 1, a + n]]
    return trimesh.Trimesh(np.array(verts), np.array(f), process=False)


def test_z4_trap_height_follows_scale_and_stays_flat():
    trap = Polygon([(-5, -5), (5, -5), (5, 5), (-5, 5)])
    q = np.array([[0, 0], [2, 2], [-3, 1]], float)
    relief = 4.0
    heights = {}
    for zs in (1.0, 2.0):
        Z, _ = gsd.apply_z_scale(np.array([[BASE + relief]]), np.array([[True]]), {"zScale": zs})
        heights[zs] = gsd._compute_trap_surface_from_fringe(trap, _fringe(float(Z[0, 0])), q)
        assert np.ptp(heights[zs]) < 1e-9          # flat floor
    r1 = heights[1.0][0] - gsd.TRAP_FRINGE_OFFSET_MM - BASE
    r2 = heights[2.0][0] - gsd.TRAP_FRINGE_OFFSET_MM - BASE
    assert abs(r2 / r1 - 2.0) < 1e-6


def test_z5_trap_and_water_fed_scaled_fringe():
    assert "export_trap_stls(_egm_data, green_boundary_px, slug,\n                                   fringe_mesh=fringe_mesh_flat" in SRC
    assert "export_water_meshes(_egm_data, green_boundary_px, slug,\n                                       fringe_mesh=fringe_mesh_flat" in SRC


def test_z6_ceiling_not_double_scaled():
    seg = SRC[SRC.index("_effective_z_ceiling_mm = max("):][:200]
    assert "_elevation_range_mm * _z_scale_fringe" in seg
    assert "_z_scale_fringe ** 2" not in seg and "* _z_scale_fringe * _z_scale_fringe" not in seg
