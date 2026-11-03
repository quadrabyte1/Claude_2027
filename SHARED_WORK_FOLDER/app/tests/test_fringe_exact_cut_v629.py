"""
test_fringe_exact_cut_v629.py -- v6.29 regressions (Bambu "conflicts of gcode paths", task 735).

E1  GREEN_FRINGE_GAP_MM is a hair (> 0, below the slicer-visible limit): exact cut.
E2  A tee collar that sits on the green is refused (it was the real 20.5 mm2 overlap);
    one clear of the green is still allowed.
N1  bambu_object_name maps scene names to green / fringe / bunker_N / water_N / boulders_N.
N2  A real injected 3MF carries those names in 3D/3dmodel.model AND Metadata/model_settings.config.
T1  Trap 2's outline (cluster of vertices < 3 um apart) now rake-textures watertight.
M1  The manifold gate no longer skips the fringe; strict_manifold_problems flags an open engraved body.
P1  (slow, end to end) Delaveaga 11.40 copy: names, zero green/fringe overlap volume, trap_2 raked,
    engraved green + fringe strictly closed.

Run: python -m pytest app/tests/test_fringe_exact_cut_v629.py -v
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest
import trimesh
from shapely.geometry import Polygon

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
import gradient_surface_diagnostic as gsd  # noqa: E402
from generate_stl_3mf import _build_slab_from_shapely  # noqa: E402

FIXTURE_TRAP2 = Path(__file__).parent / "fixtures" / "trap2_cluster_outline_v629.json"
REAL_EGM = APP_DIR.parent / "ItWentIn" / "GolfCourses" / "Delaveaga" / "EGMs" / "Delaveaga (Hole 11.40).egm"
SLICER_VISIBLE_GAP_MM = 0.05          # anything under this is below what a 0.4 mm nozzle resolves
RAKE_MIN_FACES = 5000                 # a raked bunker has tens of thousands of faces; a plain slab ~160
OVERLAP_VOLUME_TOL_MM3 = 0.0
TEE_CLEAR_OFFSET_MM = 20.0            # distance beyond the green edge for the "tee is clear" case
TEE_ON_GREEN_RADIUS_MM = 10.0
SYNTH_TRAP_INDEX = 2
SYNTH_FRACTION = gsd.SAND_GRID_STEP_FRACTION
SCENE_GREEN, SCENE_FRINGE = gsd.SCENE_NAME_GREEN_SURFACE, gsd.SCENE_NAME_FRINGE
EXPECTED_P1_NAMES = [gsd.BAMBU_NAME_GREEN, gsd.BAMBU_NAME_FRINGE,
                     f"{gsd.BAMBU_NAME_BUNKER_PREFIX}{gsd.BAMBU_NAME_SEPARATOR}1",
                     f"{gsd.BAMBU_NAME_BUNKER_PREFIX}{gsd.BAMBU_NAME_SEPARATOR}2"]


def test_e1_exact_cut_gap_is_tiny_but_positive():
    assert 0 < gsd.GREEN_FRINGE_GAP_MM < SLICER_VISIBLE_GAP_MM


def test_e2_tee_collar_on_green_is_refused():
    green = Polygon([(-50, -50), (50, -50), (50, 50), (-50, 50)])
    assert gsd.tee_collar_overlaps_green(0.0, 0.0, green)
    assert not gsd.tee_collar_overlaps_green(50 + TEE_CLEAR_OFFSET_MM, 0.0, green)
    # collar disk reaching the edge counts as touching
    edge_x = 50 + gsd.TEE_HOLE_COLLAR_OD_MM / 2 + gsd.TEE_HOLE_GUARD_MM - 0.01
    assert gsd.tee_collar_overlaps_green(edge_x, 0.0, green)


@pytest.mark.parametrize("scene_name,expected", [
    (gsd.SCENE_NAME_GREEN_SURFACE, gsd.BAMBU_NAME_GREEN),
    (gsd.SCENE_NAME_FRINGE, gsd.BAMBU_NAME_FRINGE),
    ("trap_1", "bunker_1"),
    ("trap_12", "bunker_12"),
    ("water_3", "water_3"),
    ("boulders_1", "boulders_1"),
    (gsd.SCENE_NAME_FRINGE_NO_GRASS_SAMPLE, gsd.SCENE_NAME_FRINGE_NO_GRASS_SAMPLE),
])
def test_n1_bambu_object_name(scene_name, expected):
    assert gsd.bambu_object_name(scene_name) == expected


def test_n2_injected_3mf_has_real_names(tmp_path):
    scene_names = [SCENE_GREEN, SCENE_FRINGE, "trap_1", "water_1"]
    scene = trimesh.Scene()
    for i, n in enumerate(scene_names):
        box = trimesh.creation.box(extents=(5, 5, 5))
        box.apply_translation((i * 10, 0, 2.5))
        scene.add_geometry(box, node_name=n)
    path = tmp_path / "t.3mf"
    scene.export(str(path))
    gsd._inject_bambu_extruder_metadata(str(path), scene_names)
    with zipfile.ZipFile(path) as z:
        model = z.read(gsd.THREE_MF_MODEL_PATH).decode()
        cfg = z.read("Metadata/model_settings.config").decode()
    want = [gsd.bambu_object_name(n) for n in scene_names]
    assert re.findall(r'<object id="\d+" name="([^"]*)"', model) == want
    assert re.findall(r'<metadata key="name" value="([^"]*)"/>', cfg)[::2] == want
    assert "geometry_" not in model.split("<build")[0] and "geometry_" not in cfg


def test_t1_trap2_outline_textures_watertight():
    data = json.loads(FIXTURE_TRAP2.read_text())
    poly = Polygon(data["outline_xy"])
    simp = gsd.simplify_trap_outline(poly)
    assert simp.is_valid and abs(simp.area - poly.area) < gsd.TRAP_OUTLINE_SIMPLIFY_TOL_MM * poly.length
    slab = _build_slab_from_shapely(simp, data["height_mm"])
    out = gsd.apply_sand_texture(slab.copy(), trap_index=SYNTH_TRAP_INDEX, grid_step_fraction=SYNTH_FRACTION)
    assert out.is_watertight
    assert len(out.faces) > RAKE_MIN_FACES


def test_t1b_unsimplified_trap2_outline_is_the_regression():
    """Guards the premise: the raw outline (without simplify) fails at the default pitch."""
    data = json.loads(FIXTURE_TRAP2.read_text())
    slab = _build_slab_from_shapely(Polygon(data["outline_xy"]), data["height_mm"])
    with pytest.raises(RuntimeError):
        gsd.apply_sand_texture(slab.copy(), trap_index=SYNTH_TRAP_INDEX, grid_step_fraction=SYNTH_FRACTION)


def test_m1_manifold_gate_covers_engraved_bodies():
    assert not gsd.MANIFOLD_SKIP_LABELS
    assert SCENE_FRINGE not in gsd.MANIFOLD_SKIP_LABELS
    assert set(gsd.ENGRAVED_SCENE_NAMES) == {SCENE_GREEN, SCENE_FRINGE}

    scene = trimesh.Scene()
    scene.add_geometry(trimesh.creation.box(), node_name=SCENE_GREEN)
    scene.add_geometry(trimesh.creation.icosphere(), node_name=SCENE_FRINGE)
    assert gsd.strict_manifold_problems(scene, gsd.ENGRAVED_SCENE_NAMES) == []

    holey = trimesh.creation.box()
    holey.update_faces(np.arange(len(holey.faces)) != 0)
    scene2 = trimesh.Scene()
    scene2.add_geometry(trimesh.creation.box(), node_name=SCENE_GREEN)
    scene2.add_geometry(holey, node_name=SCENE_FRINGE)
    probs = gsd.strict_manifold_problems(scene2, gsd.ENGRAVED_SCENE_NAMES)
    assert len(probs) == 1 and SCENE_FRINGE in probs[0]
    assert gsd.strict_manifold_problems(trimesh.Scene(), gsd.ENGRAVED_SCENE_NAMES)  # missing -> reported


@pytest.mark.slow
@pytest.mark.skipif(not REAL_EGM.is_file(), reason="Delaveaga 11.40 EGM not present")
def test_p1_end_to_end_delaveaga_h11(tmp_path, monkeypatch):
    manifold3d = pytest.importorskip("manifold3d")
    egm_copy = tmp_path / "h11.egm"
    shutil.copy(REAL_EGM, egm_copy)               # read-only use of the course folder
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    orig = gsd.course_paths
    monkeypatch.setattr(gsd, "course_paths",
                        lambda c: {**orig(c), gsd.PATH_KEY_3MFS: str(out_dir), gsd.PATH_KEY_STLS: str(out_dir / "stl")})
    monkeypatch.setattr(gsd, "SAVE_DIAGNOSTIC_IMAGES", False)
    path = gsd.run_pipeline(str(egm_copy))
    assert Path(path).parent == out_dir

    with zipfile.ZipFile(path) as z:
        model = z.read(gsd.THREE_MF_MODEL_PATH).decode()
    assert re.findall(r'<object id="\d+" name="([^"]*)"', model) == EXPECTED_P1_NAMES

    scene = trimesh.load(path, process=False)
    meshes = list(scene.geometry.values())
    green, fringe, _b1, bunker2 = meshes[0], meshes[1], meshes[2], meshes[3]
    assert bunker2.is_watertight and len(bunker2.faces) > RAKE_MIN_FACES
    for m in (green, fringe):
        assert m.is_watertight and m.is_winding_consistent and m.volume > 0

    def _m3(g):
        return manifold3d.Manifold(manifold3d.Mesh(vert_properties=g.vertices.astype("float32"),
                                                   tri_verts=g.faces.astype("uint32")))
    assert (_m3(green) ^ _m3(fringe)).volume() <= OVERLAP_VOLUME_TOL_MM3
