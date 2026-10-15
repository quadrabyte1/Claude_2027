"""
test_rake_long_axis.py — rake ridges run along the long axis of a bunker (v0.25).

Thomas 2026-10-15: "Bunker rake lines should run parallel to the long axis of a bunker."
Reverses task #610 (fixed Y).  Axis = principal axis of polygon area moments,
not vertex SVD (vertex-spacing bias).

Run: python -m pytest app/tests/test_rake_long_axis.py -v
"""
from __future__ import annotations
import importlib.util, math, sys
from pathlib import Path
import numpy as np
import pytest

APP_DIR = Path(__file__).parent.parent
GSD_PATH = APP_DIR / "gradient_surface_diagnostic.py"


@pytest.fixture(scope="module")
def gsd():
    spec = importlib.util.spec_from_file_location("gsd_rake_axis_test", GSD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ellipse(a, b, deg, n=96, dense_side=False):
    t = np.linspace(0, 2 * math.pi, n, endpoint=False)
    if dense_side:  # crowd vertices onto one end (t near 0) -> biases vertex-PCA
        t = (t / (2 * math.pi)) ** 3 * 2 * math.pi
    pts = np.column_stack([a * np.cos(t), b * np.sin(t)])
    r = math.radians(deg)
    R = np.array([[math.cos(r), -math.sin(r)], [math.sin(r), math.cos(r)]])
    return pts @ R.T + np.array([50.0, 40.0])


def _slab(poly_xy, h=4.0):
    import trimesh
    from shapely.geometry import Polygon
    m = trimesh.creation.extrude_polygon(Polygon(poly_xy), h)
    assert m.is_watertight
    return m


def _ridge_angle_deg(mesh):
    """Direction (deg, 0-180) along which top-surface Z is most constant."""
    v = np.asarray(mesh.vertices)
    top = v[v[:, 2] > v[:, 2].min() + 0.5 * (np.ptp(v[:, 2]))]
    xy, z = top[:, :2], top[:, 2]
    best, best_ang = None, None
    for ang in np.arange(0, 180, 0.5):
        r = math.radians(ang)
        perp = xy @ np.array([-math.sin(r), math.cos(r)])
        bins = np.floor(perp / 0.15).astype(int)
        res = 0.0
        for b in np.unique(bins):
            zz = z[bins == b]
            if len(zz) > 1:
                res += ((zz - zz.mean()) ** 2).sum()
        if best is None or res < best:
            best, best_ang = res, ang
    return best_ang


def _angdiff(a, b):
    d = abs(a - b) % 180
    return min(d, 180 - d)


def test_default_flag_is_on(gsd):
    assert gsd.SAND_RAKE_ALIGN_TO_MAJOR_AXIS is True


@pytest.mark.parametrize("deg", [0, 30, 75, 135])
def test_rotated_ellipse_ridges_along_long_axis(gsd, deg):
    mesh = gsd.apply_sand_texture(_slab(_ellipse(30, 10, deg)))
    assert mesh.is_watertight
    assert _angdiff(_ridge_angle_deg(mesh), deg) < 3.0


def test_dense_vertices_one_side_still_true_axis(gsd):
    poly = _ellipse(30, 10, 30, n=120, dense_side=True)
    # vertex-SVD would be skewed here; area-moment axis must not be
    ax, ratio = gsd._polygon_long_axis(__import__("shapely.geometry", fromlist=["Polygon"]).Polygon(poly))
    ang = math.degrees(math.atan2(ax[1], ax[0])) % 180
    assert _angdiff(ang, 30) < 3.0   # sampled polygon of true ellipse
    mesh = gsd.apply_sand_texture(_slab(poly))
    assert _angdiff(_ridge_angle_deg(mesh), 30) < 4.0


def test_vertex_svd_would_be_biased_on_dense_polygon(gsd):
    """Documents why the old method was replaced."""
    poly = _ellipse(30, 10, 30, n=120, dense_side=True)
    c = poly - poly.mean(axis=0)
    vt = np.linalg.svd(c, full_matrices=False)[2][0]
    svd_ang = math.degrees(math.atan2(vt[1], vt[0])) % 180
    from shapely.geometry import Polygon
    ax, _ = gsd._polygon_long_axis(Polygon(poly))
    area_ang = math.degrees(math.atan2(ax[1], ax[0])) % 180
    assert _angdiff(area_ang, 30) < _angdiff(svd_ang, 30)


def test_flag_false_restores_fixed_y(gsd, monkeypatch):
    monkeypatch.setattr(gsd, "SAND_RAKE_ALIGN_TO_MAJOR_AXIS", False)
    mesh = gsd.apply_sand_texture(_slab(_ellipse(30, 10, 30)))
    assert _angdiff(_ridge_angle_deg(mesh), 90) < 3.0


def test_hole_subtracted_from_moments(gsd):
    from shapely.geometry import Polygon, box
    p = box(0, 0, 40, 10).difference(box(15, 2, 25, 8))
    ax, ratio = gsd._polygon_long_axis(p)
    assert abs(ax[0]) > 0.99 and ratio > 3
