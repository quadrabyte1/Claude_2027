"""Regression (v6.23): two more things that behaved like a floor in the fringe.

1. _normalize_green_fringe_interface pulled the fringe toward the green-rim Z over a
   ~26 mm band, so EGM cells asking for a lower fringe near the green were lifted by
   up to ~1.3 mm (a flat 'floor' at the rim height).  The band must only cover the seam.
2. Grass was only applied to vertices with Z > BASE_THICKNESS_MM, so any fringe lower
   than the base got a smooth, grass-less floor.  Grass must follow FRINGE_MIN_THICKNESS_MM.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import trimesh

_APP_DIR = Path(__file__).parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import gradient_surface_diagnostic as gsd  # noqa: E402

TEST_BASE_THICKNESS_MM = 6.0
TEST_RIM_Z_MM = 8.0
TEST_REQUESTED_Z_MM = 5.0
TEST_RIM_RADIUS_MM = 20.0
TEST_RIM_POINTS = 240
TEST_DIST_FROM_RIM_MM = 10.0       # well away from the seam
TEST_Z_TOLERANCE_MM = 0.05
TEST_SLAB_EXTENT_MM = 40.0
TEST_SLAB_TOP_Z_MM = 4.0           # below the (patched) base thickness, above FRINGE_MIN
TEST_SUBDIVISIONS = 5
TEST_GRASS_SPACING_MM = 1.0
TEST_GRASS_AMPLITUDE_MM = 0.5
TEST_MIN_GRASS_RISE_MM = 0.05


def test_interface_blend_does_not_lift_fringe_away_from_seam():
    ang = np.linspace(0, 2 * np.pi, TEST_RIM_POINTS, endpoint=False)
    bnd = np.column_stack([TEST_RIM_RADIUS_MM * np.cos(ang), TEST_RIM_RADIUS_MM * np.sin(ang)])
    bnd_z = np.full(TEST_RIM_POINTS, TEST_RIM_Z_MM)
    x = TEST_RIM_RADIUS_MM + TEST_DIST_FROM_RIM_MM
    gx = np.array([[x]]); gy = np.array([[0.0]])
    z_tps = np.full(gx.shape, TEST_REQUESTED_Z_MM)
    out = gsd._normalize_green_fringe_interface(z_tps, gx, gy, bnd, bnd_z)
    assert abs(float(out[0, 0]) - TEST_REQUESTED_Z_MM) <= TEST_Z_TOLERANCE_MM, out


def test_grass_applies_below_base_thickness(monkeypatch):
    monkeypatch.setattr(gsd, "BASE_THICKNESS_MM", TEST_BASE_THICKNESS_MM)
    mesh = trimesh.creation.box(extents=[TEST_SLAB_EXTENT_MM, TEST_SLAB_EXTENT_MM, TEST_SLAB_TOP_Z_MM])
    mesh.apply_translation([0, 0, TEST_SLAB_TOP_Z_MM / 2.0])
    for _ in range(TEST_SUBDIVISIONS):
        mesh = mesh.subdivide()
    assert mesh.vertices[:, 2].max() == pytest.approx(TEST_SLAB_TOP_Z_MM)
    gsd.apply_grass_texture_v2(mesh, amplitude=TEST_GRASS_AMPLITUDE_MM, bump_spacing=TEST_GRASS_SPACING_MM)
    assert mesh.vertices[:, 2].max() > TEST_SLAB_TOP_Z_MM + TEST_MIN_GRASS_RISE_MM
