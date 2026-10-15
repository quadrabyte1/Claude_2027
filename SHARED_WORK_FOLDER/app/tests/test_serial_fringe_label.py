"""Fringe-only file-name label next to the serial (task 544)."""
import os
import sys

import numpy as np
import pytest
import trimesh
from shapely.geometry import Polygon

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import serial_engraver as se


def _frame(size=100.0, hole=30.0, h=10.0):
    outer = [(-size / 2, -size / 2), (size / 2, -size / 2), (size / 2, size / 2), (-size / 2, size / 2)]
    inner = [(-hole / 2, -hole / 2), (hole / 2, -hole / 2), (hole / 2, hole / 2), (-hole / 2, hole / 2)]
    return trimesh.creation.extrude_polygon(Polygon(outer, [inner]), h)


def _slab():
    return trimesh.creation.box(extents=(80.0, 80.0, 10.0), transform=trimesh.transformations.translation_matrix((0, 0, 5)))


def _scene():
    s = trimesh.Scene()
    s.add_geometry(_frame(), node_name="fringe", geom_name="g_fringe")
    s.add_geometry(_slab(), node_name="green_surface", geom_name="g_green")
    s.add_geometry(_slab(), node_name="trap_1", geom_name="g_trap")
    return s


def _vols(scene):
    return {k: float(abs(m.volume)) for k, m in scene.geometry.items()}


@pytest.mark.parametrize("name,expected", [
    ("/x/Delaveaga (Hole 5f) [1500].3mf", "Delaveaga H5f"),
    ("Stanford (Hole 03).3mf", "Stanford H03"),
    ("Stanford (Hole 8, 5396) [1458].3mf", "Stanford H8"),   # ", 5396" discarded
    ("Firefly (Hole 14) [1400].3mf", "Firefly H14"),
    ("Fantasy Golf Course (Hole 77) [1].3mf", "Fantasy Golf Course H77"),
    ("Odd Name [1500].3mf", None),   # no (Hole N) -> serial-only fallback
    ("Plain.3mf", None),
    (None, None),
    ("", None),
])
def test_label_from_filename(name, expected):
    assert se.label_from_filename(name) == expected


def test_fringe_text_single_line_uses_engraving_serial():
    assert se.fringe_text(1500, "Delaveaga H5f") == "Delaveaga H5f, 1500"
    assert se.fringe_text(1458, "Stanford H8") == "Stanford H8, 1458"
    assert se.fringe_text(1500, None) == "s/n: 1500"
    assert se.fringe_text(1500, "") == "s/n: 1500"


def test_fringe_text_mesh_is_one_line_at_8pt():
    plain = se._build_serial_text_mesh(1500)
    one = se._build_serial_text_mesh(1500, label="Delaveaga H5f")
    # single line: height comparable to the serial-only line (not stacked)
    assert one.extents[1] < plain.extents[1] + 1.5
    assert one.extents[0] > plain.extents[0] + 10     # wider: carries the name
    assert one.extents[0] <= se.LABEL_MAX_WIDTH_MM + 0.5
    again = se._build_serial_text_mesh(1500, label=None)
    assert np.allclose(plain.extents, again.extents)


def test_fringe_gets_label_other_pieces_do_not():
    base = _scene()
    se.engrave_scene_geometries(base, 1500)
    lab = _scene()
    se.engrave_scene_geometries(lab, 1500, fringe_label="Test (Hole 01)")
    vb, vl = _vols(base), _vols(lab)
    assert vl["g_fringe"] < vb["g_fringe"] - 1.0      # extra material removed
    assert vl["g_green"] == pytest.approx(vb["g_green"])
    assert vl["g_trap"] == pytest.approx(vb["g_trap"])


def test_no_label_falls_back_to_serial_only():
    a = _scene(); se.engrave_scene_geometries(a, 1500)
    b = _scene(); se.engrave_scene_geometries(b, 1500, fringe_label=None)
    c = _scene(); se.engrave_scene_geometries(c, 1500, fringe_label="")
    assert _vols(a) == pytest.approx(_vols(b))
    assert _vols(a) == pytest.approx(_vols(c))
