"""Fringe-only course/hole label engraving (task 544; serial text removed)."""
import os
import sys

import numpy as np
import pytest
import trimesh
from shapely.geometry import Polygon

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import fringe_label_engraver as se
import generation_id as gid


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


GEN_ID = "2026.11.01.14.05.09.jgreen"
LEGACY_SERIAL = 1500
LABEL = "Delaveaga H5f"


@pytest.mark.parametrize("name,expected", [
    (f"/x/Delaveaga (Hole 5f) [{LEGACY_SERIAL}].3mf", "Delaveaga H5f"),          # legacy numeric tag
    (f"/x/Delaveaga (Hole 5f) [{GEN_ID}].3mf", "Delaveaga H5f"),                  # new ID tag
    ("Stanford (Hole 03).3mf", "Stanford H03"),
    ("Stanford (Hole 8, 5396) [1458].3mf", "Stanford H8"),   # ", 5396" discarded
    (f"Firefly (Hole 14) [{GEN_ID}].3mf", "Firefly H14"),
    ("Fantasy Golf Course (Hole 77) [1].3mf", "Fantasy Golf Course H77"),
    ("Odd Name [1500].3mf", None),   # no (Hole N) -> no label
    ("Plain.3mf", None),
    (None, None),
    ("", None),
])
def test_label_from_filename(name, expected):
    assert se.label_from_filename(name) == expected


def test_label_mesh_is_one_line_at_8pt_and_width_capped():
    m = se.build_label_text_mesh(LABEL)
    assert m.extents[1] < se.ENGRAVE_FONT_PT * se.PT_TO_MM * 2
    assert m.extents[0] <= se.LABEL_MAX_WIDTH_MM + 0.5


def test_fringe_gets_label_other_pieces_do_not():
    base = _scene()
    lab = _scene()
    summary = se.engrave_fringe_label(lab, "Test (Hole 01)")
    vb, vl = _vols(base), _vols(lab)
    assert vl["g_fringe"] < vb["g_fringe"] - 1.0      # extra material removed
    assert vl["g_green"] == pytest.approx(vb["g_green"])
    assert vl["g_trap"] == pytest.approx(vb["g_trap"])
    assert list(summary) == ["g_fringe"]


@pytest.mark.parametrize("label", [None, ""])
def test_no_label_engraves_nothing(label):
    base = _scene()
    other = _scene()
    assert se.engrave_fringe_label(other, label) == {}
    assert _vols(base) == pytest.approx(_vols(other))
