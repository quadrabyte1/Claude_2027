"""v6.28: the short generation ID (first UUID segment) is engraved on the green and the fringe only."""
import os
import sys


import pytest
import trimesh

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
sys.path.insert(0, os.path.dirname(__file__))

import fringe_label_engraver as se
import generation_id as gid
import test_fringe_label_engraver as base_tests

SAMPLE_UUID = "3f2b8c1e-9a47-4d6e-8b0c-5e7a1d2c4f90"
SAMPLE_SHORT = "3f2b8c1e"
SHORT_ID_LENGTH = 8
LABEL = "Test H01"
GREEN_KEY, FRINGE_KEY, TRAP_KEY = "g_green", "g_fringe", "g_trap"
VOLUME_EPS_MM3 = 1.0
EXTRA_NODES = ("water_1", "boulders_1", se.LABEL_NODE_NAME + "_no_grass_sample")


def _scene_with_extras():
    s = base_tests._scene()
    for i, n in enumerate(EXTRA_NODES):
        s.add_geometry(base_tests._slab(), node_name=n, geom_name=f"g_extra{i}")
    return s


def test_short_generation_id_is_first_segment():
    assert gid.short_generation_id(SAMPLE_UUID) == SAMPLE_SHORT
    assert len(gid.short_generation_id(gid.make_generation_id())) == SHORT_ID_LENGTH
    assert gid.SHORT_ID_SEGMENT_INDEX == 0 and gid.SHORT_ID_SEPARATOR == gid.GENERATION_ID_SEPARATOR


def test_green_and_fringe_get_the_id_others_do_not():
    before = _scene_with_extras()
    after = _scene_with_extras()
    summary = se.engrave_fringe_label(after, LABEL, short_id=SAMPLE_SHORT)
    vb, va = base_tests._vols(before), base_tests._vols(after)
    assert set(summary) == {GREEN_KEY, FRINGE_KEY}
    assert va[GREEN_KEY] < vb[GREEN_KEY] - VOLUME_EPS_MM3
    assert va[FRINGE_KEY] < vb[FRINGE_KEY] - VOLUME_EPS_MM3
    for key in set(vb) - {GREEN_KEY, FRINGE_KEY}:        # trap, water, boulders, plate-2 sample
        assert va[key] == pytest.approx(vb[key])
    for key in (GREEN_KEY, FRINGE_KEY):
        assert after.geometry[key].is_watertight


def test_fringe_id_adds_material_removal_beyond_label_alone_and_does_not_overlap():
    label_only = base_tests._scene()
    both = base_tests._scene()
    se.engrave_fringe_label(label_only, LABEL)
    se.engrave_fringe_label(both, LABEL, short_id=SAMPLE_SHORT)
    assert base_tests._vols(both)[FRINGE_KEY] < base_tests._vols(label_only)[FRINGE_KEY] - VOLUME_EPS_MM3
    assert both.geometry[FRINGE_KEY].is_watertight


def test_green_gets_id_even_without_a_label():
    s = base_tests._scene()
    vb = base_tests._vols(s)
    se.engrave_fringe_label(s, None, short_id=SAMPLE_SHORT)
    va = base_tests._vols(s)
    assert va[GREEN_KEY] < vb[GREEN_KEY] - VOLUME_EPS_MM3
    assert va[FRINGE_KEY] < vb[FRINGE_KEY] - VOLUME_EPS_MM3      # fringe carries the ID alone too
    assert va[TRAP_KEY] == pytest.approx(vb[TRAP_KEY])


def test_no_id_no_label_engraves_nothing():
    assert se.engrave_fringe_label(base_tests._scene(), None, short_id=None) == {}
