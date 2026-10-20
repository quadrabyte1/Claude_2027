"""
test_seam_polish.py -- final green<->fringe seam polish (Thomas, 2026-10-19).

S1  Max green-rim -> fringe-seam Z gap <= EPS after polish (was ~1.5 mm).
S2  Green mesh vertices are byte-identical (green is the reference).
S3  Fringe far from the seam (beyond band+blend) is untouched.
S4  Blend: no new step -- correction decays monotonically away from the seam.
S5  Pipeline wiring: run_pipeline calls polish after the tee-hole block and
    before the 3MF scene is assembled.

Run: python -m pytest app/tests/test_seam_polish.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import trimesh

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
import gradient_surface_diagnostic as gsd  # noqa: E402

EPS = 0.02
R_GREEN, GAP, N_ANG = 20.0, 0.125, 96
GREEN_Z, FRINGE_Z = 6.0, 7.5     # fringe sits 1.5 mm too high
RADII = [R_GREEN + GAP, 20.8, 21.6, 22.8, 24.5, 27.0, 31.0, 40.0]


def _green():
    m = trimesh.creation.cylinder(radius=R_GREEN, height=GREEN_Z, sections=N_ANG)
    m.apply_translation([0, 0, GREEN_Z / 2.0])
    return m


def _fringe():
    ang = np.linspace(0, 2 * np.pi, N_ANG, endpoint=False)
    verts, faces = [], []
    for r in RADII:
        for a in ang:
            verts.append([r * np.cos(a), r * np.sin(a), FRINGE_Z])
    for a in ang:  # inner wall bottom ring
        verts.append([RADII[0] * np.cos(a), RADII[0] * np.sin(a), 0.0])
    nb = len(RADII) * N_ANG
    for k in range(len(RADII) - 1):
        for j in range(N_ANG):
            j2 = (j + 1) % N_ANG
            a, b = k * N_ANG + j, k * N_ANG + j2
            c, d = (k + 1) * N_ANG + j, (k + 1) * N_ANG + j2
            faces += [[a, b, d], [a, d, c]]
    for j in range(N_ANG):
        j2 = (j + 1) % N_ANG
        faces += [[j, nb + j, nb + j2], [j, nb + j2, j2]]
    return trimesh.Trimesh(np.array(verts), np.array(faces), process=False)


def _seam_gap(green, fringe):
    idx, _ = gsd._green_rim_edges(green)
    rim = green.vertices[idx]
    ft = fringe.vertices[fringe.vertices[:, 2] > 0.1]
    gaps = []
    for p in rim:
        d = np.linalg.norm(ft[:, :2] - p[:2], axis=1)
        gaps.append(abs(ft[d.argmin(), 2] - p[2]))
    return max(gaps)


def test_s1_seam_gap_closed():
    g, f = _green(), _fringe()
    assert _seam_gap(g, f) > 1.0   # precondition: gap exists
    gsd.polish_green_fringe_seam(g, f)
    assert _seam_gap(g, f) <= EPS


def test_s2_green_unchanged():
    g, f = _green(), _fringe()
    before = g.vertices.copy()
    gsd.polish_green_fringe_seam(g, f)
    assert np.array_equal(before, g.vertices)


def test_s3_far_fringe_untouched():
    g, f = _green(), _fringe()
    gsd.polish_green_fringe_seam(g, f)
    r = np.linalg.norm(f.vertices[:, :2], axis=1)
    far = (r > R_GREEN + gsd.SEAM_POLISH_BAND_MM + gsd.SEAM_POLISH_BLEND_MM + 0.5) & (f.vertices[:, 2] > 0.1)
    assert far.any()
    assert np.allclose(f.vertices[far, 2], FRINGE_Z)


def test_s4_blend_is_monotonic():
    g, f = _green(), _fringe()
    gsd.polish_green_fringe_seam(g, f)
    zs = [f.vertices[k * N_ANG, 2] for k in range(len(RADII))]   # one ray
    assert all(b >= a - 1e-9 for a, b in zip(zs, zs[1:])), zs
    assert abs(zs[0] - GREEN_Z) <= EPS and abs(zs[-1] - FRINGE_Z) <= 1e-6


def test_s5_pipeline_wiring():
    src = (APP_DIR / "gradient_surface_diagnostic.py").read_text()
    i_call = src.index("polish_green_fringe_seam(_seam_green, fringe_mesh)")
    assert src.index("[7d] Tee-hole") < i_call < src.index("scene = trimesh.Scene()")
