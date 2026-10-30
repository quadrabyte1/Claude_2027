"""Editor v6.09: (1) a selected control point grows only half as much as before; (2) a plain click on empty space clears
ALL selections (points, highlighted boundary, contour, grid cells) in Boundary Editing.

Reuses the node mock harness of test_editor_ui_mode2 (real constants block + real methods cut from editor.html).
Every value comes from the editor's named constants.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import editor_constants as C
from test_editor_ui_mode2 import EDITOR, THRESH, SUB_P, _run, _method

NO_POLY = C.value("NO_POLY_SELECTED")


# ═══════════════════════════ point size ═══════════════════════════
def test_selected_point_growth_is_half_of_the_old_growth():
    normal = C.value("VERTEX_RADIUS")
    full = C.value("VERTEX_SELECTED_POLY_EXTRA_RADIUS_FULL")
    scale = C.value("VERTEX_EXPANSION_SCALE")
    assert scale == 0.5
    assert C.value("VERTEX_SELECTED_POLY_RADIUS") == normal + full * scale
    assert C.value("VERTEX_SELECTED_POLY_RADIUS") - normal == (full) / 2          # growth halved
    assert C.value("VERTEX_SELECTED_RADIUS_BONUS") == C.value("VERTEX_SELECTED_RADIUS_BONUS_FULL") * scale
    assert normal == 4                                                             # unselected size unchanged


def test_draw_uses_the_new_selected_radius_and_hit_radius_is_untouched():
    assert "isSelected ? VERTEX_SELECTED_POLY_RADIUS : VERTEX_RADIUS" in EDITOR
    assert "isSelected ? this.POINT_RADIUS : VERTEX_RADIUS" not in EDITOR
    assert "const hitR = this.POINT_RADIUS / this.scale + HIT_SLACK_PX" in EDITOR   # clicking is as easy as before


# ═══════════════════════════ click-away ═══════════════════════════
def test_click_on_empty_space_clears_points_polygon_contour_and_cells():
    r = _run("""o.selectedVerts = [{poly: 0, idx: 1}]; o.selectedPoly = 1; o.selectedContour = 0;
      o._gridMultiSelect = new Set([5, 6]); o._gridActiveCell = {idx: 5};
      down(600, 600); up(600, 600);
      console.log(JSON.stringify({sel: sel(), poly: o.selectedPoly, contour: o.selectedContour, multi: o._gridMultiSelect,
        active: o._gridActiveCell, hist: o.undoHistory.length}));""")
    assert r == {"sel": "[]", "poly": NO_POLY, "contour": -1, "multi": None, "active": None, "hist": 0}


def test_polygon_only_selection_is_cleared_by_click_away():
    r = _run("""down(600, 600); up(600, 600); console.log(JSON.stringify({poly: o.selectedPoly}));""")
    assert r == {"poly": NO_POLY}


def test_drag_is_not_a_click_away_but_subthreshold_wobble_is():
    r = _run("""o.selectedPoly = 1; o.selectedVerts = [{poly: 1, idx: 0}];
      down(600, 600); move(600 + %d + 5, 600); up(600 + %d + 5, 600);   // real drag: rubber band, selects nothing in it
      const poly = o.selectedPoly;
      o.selectedPoly = 1; o.selectedContour = 0;
      down(600, 600); move(600 + %d - 1, 600); up(600 + %d - 1, 600);   // wobble under the threshold = click
      console.log(JSON.stringify({poly, after: o.selectedPoly, contour: o.selectedContour}));""" % (THRESH, THRESH, THRESH, THRESH))
    assert r == {"poly": 1, "after": NO_POLY, "contour": -1}


def test_shift_click_and_cmd_click_on_empty_space_keep_everything():
    r = _run("""o.selectedVerts = [{poly: 0, idx: 1}]; o.selectedPoly = 1; o._gridMultiSelect = new Set([5]);
      down(600, 600, {shiftKey: true}); up(600, 600, {shiftKey: true});
      down(600, 600, {metaKey: true}); up(600, 600, {metaKey: true});
      console.log(JSON.stringify({sel: sel(), poly: o.selectedPoly, cells: o._gridMultiSelect.size}));""")
    assert r == {"sel": "[[0,1]]", "poly": 1, "cells": 1}


def test_click_on_a_control_point_selects_it_not_away():
    r = _run("""o.selectedPoly = 1; down(100, 100); up(100, 100);
      console.log(JSON.stringify({sel: sel(), poly: o.selectedPoly}));""")
    assert r == {"sel": "[[0,0]]", "poly": 0}


def test_z_painting_click_paints_and_never_deselects():
    r = _run("""o.setUiSubMode(UI_SUB_PAINT); o.selectedPoly = 1; o._gridMultiSelect = new Set([5]);
      down(300, 300); up(300, 300);
      console.log(JSON.stringify({sub: o.uiSubMode, poly: o.selectedPoly, cells: o._gridMultiSelect.size}));""")
    assert r == {"sub": SUB_P, "poly": 1, "cells": 1}


def test_popup_dismiss_click_does_not_clear_selection():
    r = _run("""o.paintPopup.open = true; o.selectedPoly = 1; down(600, 600); up(600, 600);
      console.log(JSON.stringify({poly: o.selectedPoly}));""")
    assert r == {"poly": 1}


def test_clearing_with_nothing_selected_does_not_redraw():
    r = _run("""o.selectedPoly = %d; const d = o.draws; down(600, 600); up(600, 600);
      console.log(JSON.stringify({redraws: o.draws - d}));""" % NO_POLY)
    assert r == {"redraws": 0}


def test_canvas_only_listener_so_clicks_on_other_ui_do_not_clear():
    i = EDITOR.index('<canvas x-ref="canvas"')
    assert '@mousedown="onMouseDown($event)"' in EDITOR[i:i + 200]
    assert "document.addEventListener('mousedown'" not in EDITOR and "document.addEventListener(\"mousedown\"" not in EDITOR
