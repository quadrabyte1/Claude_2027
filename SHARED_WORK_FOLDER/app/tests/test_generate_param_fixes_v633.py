"""v6.33 fixes from Topo's Generate-parameter audit (owner_inbox/generate_parameters_v6.31.md).

1. dead "Fringe edge height" field removed from the editor (old EGM key still tolerated)
2. (superseded in v7.0: the inert "Cap fringe at frame height" checkbox was removed entirely; see test_editor_cleanup_v70.py)
3. grass tooltips say the FRINGE is textured, not the green
4. grass-spacing editor default/min == the pipeline's effective minimum
5. base thickness is resolved per run (no leak between runs); BUNKER_FLOOR_MIN_MM follows it
No server, no DB, no EGM files: the editor template is read as text, the generator module is imported.
"""
import importlib.util
import re
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(Path(__file__).parent))
import editor_constants as C  # noqa: E402

EDITOR = (APP_DIR / "templates" / "editor.html").read_text()
EGM_KEY_BASE_THICKNESS = "baseThicknessMm"
EGM_KEY_FRINGE_EDGE = "fringeEdgeHeight"
TEST_BASE_THICKNESS_MM = 3.25
INVALID_BASE_VALUES = (None, 0, 0.0, "", "abc", -2.0)
STALE_SURFACE_WORDING = "on the green"


@pytest.fixture(scope="module")
def g():
    spec = importlib.util.spec_from_file_location("gsd_v633", APP_DIR / "gradient_surface_diagnostic.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _block(title_marker):
    """The {# comment #} + <div> markup block that follows a template comment containing title_marker."""
    i = EDITOR.index(title_marker)
    return EDITOR[i:i + 1600]


# ── 1. dead fringe-edge-height field ─────────────────────────────────────────
def test_fringe_edge_height_field_removed_from_ui():
    assert "Fringe edge height" not in EDITOR
    assert "FIELD_LIMITS.fringeEdgeHeight" not in EDITOR
    assert 'x-model.number="fringeEdgeHeight"' not in EDITOR
    assert "DEFAULT_FRINGE_EDGE_HEIGHT_MM" not in EDITOR


def test_old_egm_with_fringe_edge_key_still_loads_in_pipeline(g):
    # the pipeline never reads the key any more; an old project carrying it must resolve as before
    assert g._resolve_base_thickness({EGM_KEY_FRINGE_EDGE: 9.0}) == g.DEFAULT_BASE_THICKNESS_MM


# ── 3. grass tooltips ────────────────────────────────────────────────────────
@pytest.mark.parametrize("marker", ["{# Grass amplitude #}", "{# Grass spacing #}"])
def test_grass_tooltips_describe_fringe_not_green(marker):
    title = re.search(r'title="([^"]*)"', _block(marker)).group(1)
    assert "fringe" in title.lower()
    assert STALE_SURFACE_WORDING not in title


# ── 4. grass spacing default == effective minimum ────────────────────────────
def test_grass_spacing_editor_constants_match_pipeline_floor(g):
    assert C.value("GRASS_SPACING_MIN_MM") == g.FRINGE_GRASS_MIN_SPACING_MM
    assert C.value("DEFAULT_GRASS_SPACING_MM") == g.FRINGE_GRASS_MIN_SPACING_MM
    assert C.value("FIELD_LIMITS")["grassSpacing"]["min"] == g.FRINGE_GRASS_MIN_SPACING_MM


# ── 5. base thickness: per-run resolution, no leak ───────────────────────────
def test_resolve_base_thickness_uses_field_else_default(g):
    assert g._resolve_base_thickness({EGM_KEY_BASE_THICKNESS: TEST_BASE_THICKNESS_MM}) == TEST_BASE_THICKNESS_MM
    for bad in INVALID_BASE_VALUES:
        assert g._resolve_base_thickness({EGM_KEY_BASE_THICKNESS: bad}) == g.DEFAULT_BASE_THICKNESS_MM, bad
    assert g._resolve_base_thickness({}) == g.DEFAULT_BASE_THICKNESS_MM


def test_base_thickness_does_not_leak_into_next_run(g, monkeypatch):
    monkeypatch.setattr(g, "BASE_THICKNESS_MM", g.DEFAULT_BASE_THICKNESS_MM)
    monkeypatch.setattr(g, "BUNKER_FLOOR_MIN_MM", g.DEFAULT_BASE_THICKNESS_MM)
    g._apply_run_base_thickness({EGM_KEY_BASE_THICKNESS: TEST_BASE_THICKNESS_MM})
    assert g.BASE_THICKNESS_MM == TEST_BASE_THICKNESS_MM
    assert g.BUNKER_FLOOR_MIN_MM == TEST_BASE_THICKNESS_MM          # follows the field
    g._apply_run_base_thickness({EGM_KEY_BASE_THICKNESS: ""})        # next run: empty field
    assert g.BASE_THICKNESS_MM == g.DEFAULT_BASE_THICKNESS_MM
    assert g.BUNKER_FLOOR_MIN_MM == g.DEFAULT_BASE_THICKNESS_MM


def test_import_time_defaults_unchanged(g):
    assert g.BASE_THICKNESS_MM == g.DEFAULT_BASE_THICKNESS_MM
    assert g.BUNKER_FLOOR_MIN_MM == g.DEFAULT_BASE_THICKNESS_MM


def test_run_pipeline_uses_the_per_run_helper():
    src = (APP_DIR / "gradient_surface_diagnostic.py").read_text()
    assert 'globals()["BASE_THICKNESS_MM"]' not in src
    assert "_apply_run_base_thickness(_egm_data)" in src
