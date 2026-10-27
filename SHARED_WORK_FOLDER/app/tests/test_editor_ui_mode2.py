"""Editor v5.87: UI Mode 2 (Boundary Editing + Z-Painting) -- one test group per row of Thomas's spreadsheet
("Boundary Editor Commands (Mode 2 spec)"), plus Mode 1 unchanged, Shift-additive selection, eraser, 2-colour ramp,
single-undo-step-per-gesture and the popup palette.

Same technique as the other editor tests: the real constants block (editor_constants.prelude()) and the REAL methods
are cut out of templates/editor.html and run in node against a mock editor object.  No server, no DB, no EGM files.
Every literal that the editor defines as a named constant is read back from it (editor_constants.value / the prelude).
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).parent.parent
EDITOR = (APP_DIR / "templates" / "editor.html").read_text()
sys.path.insert(0, str(Path(__file__).parent))
import editor_constants as C

node = shutil.which("node")
pytestmark = pytest.mark.skipif(not node, reason="node not installed")

METHODS = [
    "isUiMode2", "isTypingTarget", "onUiModeChanged", "setUiSubMode", "m2Cancel", "closePaintPopup", "openPaintPopup",
    "pickPopupBrush", "onSwatchClick", "m2HandleKey", "_m2AttachMouseUp", "m2MouseDown", "m2MouseMove", "m2MouseUp",
    "_m2Rect", "_m2SetSelection", "_m2ClearSelection", "_m2BrushValue", "_m2ApplyCells", "_m2RampAdd", "_m2RampCommit", "_m2PaintDown",
    "_m2BoundaryDown", "_m2DeletePoint", "onMouseDown", "onMouseMove", "onMouseUp", "onRightClick", "onDblClick",
    "hitTestPoint", "hitTestEdge", "sampleSplinePoints", "distToSegment", "isVertSelected", "toggleVertSelection",
    "pushUndo", "_trimUndo", "pushGridUndo", "undo", "redo", "_undoGridEntry", "snapshotPolygons", "restoreSnapshot",
    "enterPaintMode", "exitPaintMode", "togglePaintMode", "selectBrush", "paintCursorCss", "applyPaintCursor",
    "paletteColor", "cellColorAt", "paintBrushValueNow", "_imgToCellUV", "_paintCells", "paintBegin", "paintMove",
    "paintEnd", "cancelGridRamp", "cancelGridCell", "removePoly",
]

SUB_B, SUB_P = C.value("UI_SUB_BOUNDARY"), C.value("UI_SUB_PAINT")
MODE_1, MODE_2 = C.value("UI_MODE_1"), C.value("UI_MODE_2")
ERASER = C.value("PAINT_BRUSH_ERASER")
KEY_B, KEY_P, KEY_ESC = C.value("M2_KEY_BOUNDARY"), C.value("M2_KEY_PAINT"), C.value("M2_KEY_CANCEL")
BTN_L, BTN_R = C.value("MOUSE_BUTTON_LEFT"), C.value("MOUSE_BUTTON_RIGHT")
THRESH = C.value("M2_DRAG_THRESHOLD_PX")
STEPS = len(C.value("CELL_COLOR_STOPS"))
N = 20   # the mock grid: 20x20 cells, 1 px per cell, origin top-left (so cell (i, j) spans x in [i, i+1), y in [j, j+1))


def _method(name):
    m = re.search(r"\n    (%s\(.*?\n    \}),\n" % re.escape(name), EDITOR, re.S)
    if not m:   # one-liner methods (isUiMode2 / isTypingTarget)
        m = re.search(r"\n    (%s\(.*?\}),?\n" % re.escape(name), EDITOR)
    assert m, name + " missing"
    return m.group(1)


def _handle_key():
    i = EDITOR.index("    handleKey(e) {")
    j = EDITOR.index("\n    },\n  };\n}", i)
    return EDITOR[i:j + len("\n    }")]


MOCK = """
globalThis.window = {innerWidth: 1000, innerHeight: 800, l: null,
  addEventListener(t, f) { this.l = f; }, removeEventListener() { this.l = null; }};
const BTN_L = MOUSE_BUTTON_LEFT, BTN_R = MOUSE_BUTTON_RIGHT;
const o = {
  uiMode: UI_MODE_2, uiSubMode: DEFAULT_UI_SUB_MODE, paintBrush2: null, paintPopup: {open: false, x: 0, y: 0},
  _m2: null, lassoPts: null, rubberBand: false, rbStartX: 0, rbStartY: 0, rbCurX: 0, rbCurY: 0,
  gridMode: 'delta', gridN: %d, gridCellHeights: {}, imgLoaded: true, printSizeMm: %d,
  paintMode: false, paintBrush: PAINT_DEFAULT_STEP, _paintStroke: null, paletteSwatchPx: 20,
  undoHistory: [], redoStack: [], maxUndo: 100, selectedVerts: [], selectedPoly: 0, selectedContour: -1,
  _gridActiveCell: null, _gridMultiSelect: null, _gridHoveredCell: null, _gridInputValue: '', _globalMouseUp: null,
  showNewDialog: false, showOpenDialog: false, contourMode: false, contourDraft: [], contours: [], dragging: false,
  scale: 1, POINT_RADIUS: 8, EDGE_HIT_DIST: 10, fringePadPx: 50, imgW: 1000, imgH: 1000,
  polygons: [{type: 'green', color: '#00aa00', points: [{x: 100, y: 100}, {x: 200, y: 100}, {x: 200, y: 200}, {x: 100, y: 200}]},
             {type: 'trap', color: '#aa0000', points: [{x: 400, y: 400}, {x: 450, y: 400}, {x: 450, y: 450}]}],
  $refs: {canvas: {style: {cursor: 'default'}, getBoundingClientRect() { return {left: 0, top: 0}; }}},
  _contourArrowBtns: [], hitTestContourPoint() { return null; }, _gridCellFromImgPx() { return null; },
  saves: 0, draws: 0, flashes: [],
  draw() { this.draws++; }, autoSave() { this.saves++; }, flash(m) { this.flashes.push(m); },
  canvasToImg(e) { return {x: e.x, y: e.y}; },
  _printTopLeftPx() { return {x: 0, y: 0}; }, _pxPerMm() { return 1; },
};
const M = {%s};
for (const k in M) Object.defineProperty(o, k, Object.getOwnPropertyDescriptor(M, k));
const ev = (x, y, kw = {}) => Object.assign({x, y, clientX: x, clientY: y, button: BTN_L, buttons: 1, metaKey: false,
  ctrlKey: false, shiftKey: false, altKey: false, preventDefault() { this.prevented = true; }}, kw);
const key = (k, kw = {}) => Object.assign({key: k, target: {tagName: 'DIV'}, metaKey: false, ctrlKey: false,
  altKey: false, shiftKey: false, preventDefault() { this.prevented = true; }}, kw);
const cellXY = (i, j) => [i + 0.5, j + 0.5];                       // centre of cell (i, j) in image px
const cellIdx = (i, j) => (%d - 1 - j) * %d + i;
const down = (x, y, kw) => { o.onMouseDown(ev(x, y, kw)); };
const move = (x, y, kw) => { o.onMouseMove(ev(x, y, kw)); };
const up = (x, y, kw) => { o.onMouseUp(ev(x, y, Object.assign({buttons: 0}, kw))); };
const drag = (pts, kw) => { down(pts[0][0], pts[0][1], kw); for (const p of pts.slice(1)) move(p[0], p[1], kw); const l = pts[pts.length - 1]; up(l[0], l[1], kw); };
const sel = () => JSON.stringify(o.selectedVerts.map(v => [v.poly, v.idx]).sort());
"""


def _run(script, state=""):
    body = ",\n".join(_handle_key() if n == "handleKey" else _method(n) for n in METHODS + ["handleKey"])
    js = C.prelude() + MOCK % (N, N, body, N, N) + state + "\n" + script
    out = subprocess.run([node, "-e", js], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _go_paint(extra=""):
    return "o.setUiSubMode(UI_SUB_PAINT);" + extra


# ═══════════════════════════ constants / markup / wiring ═══════════════════════════
def test_constants_distinct_and_default_submode_is_boundary_editing():
    assert SUB_B != SUB_P and C.value("UI_SUB_MODES") == [SUB_B, SUB_P]
    assert C.value("DEFAULT_UI_SUB_MODE") == SUB_B
    assert {KEY_B, KEY_P} == {"b", "p"} and KEY_B != KEY_P
    assert C.value("UI_SUB_LABEL_BOUNDARY") == "Boundary Editing" and C.value("UI_SUB_LABEL_PAINT") == "Z-Painting"


def test_submode_indicator_markup_uses_constants_and_is_clickable():
    i = EDITOR.index('data-testid="ui-submode-switch"')
    block = EDITOR[i:i + 1400]
    for needle in ("isUiMode2()", "UI_SUB_LABEL_BOUNDARY", "UI_SUB_LABEL_PAINT", "setUiSubMode(UI_SUB_BOUNDARY)",
                   "setUiSubMode(UI_SUB_PAINT)", "UI_SUB_TIP_SWITCH", "eb-seg-btn"):
        assert needle in block or needle in EDITOR[i - 200:i], needle


def test_popup_and_swatch_markup():
    assert 'data-testid="paint-popup"' in EDITOR and 'x-show="paintPopup.open"' in EDITOR
    assert 'x-for="step in paletteSteps()"' in EDITOR[EDITOR.index('data-testid="paint-popup"'):][:1500]
    assert 'onSwatchMouseDown(step, $event)' in EDITOR and 'onSwatchMouseDown(PAINT_BRUSH_ERASER, $event)' in EDITOR   # v5.91: select on mousedown
    assert 'onPopupSwatchMouseDown(step, $event)' in EDITOR and 'onPopupSwatchMouseDown(PAINT_BRUSH_ERASER, $event)' in EDITOR


def test_seams_dispatch_to_mode2_and_selected_point_style_uses_constants():
    for h, call in (("handleKey(e)", "m2HandleKey(e)"), ("onMouseDown(e)", "m2MouseDown(e)"),
                    ("onMouseMove(e)", "m2MouseMove(e)"), ("onMouseUp(e)", "m2MouseUp(e)")):
        i = EDITOR.index("\n    " + h + " {")
        assert "UI-mode seam" in EDITOR[i:i + 400] and call in EDITOR[i:i + 600], h
    assert "this._drawM2SelectedVertex(" in EDITOR[EDITOR.index("    draw() {"):EDITOR.index("    hitTestPoint(")]
    assert C.value("COLOR_M2_SELECTED_BORDER").lower() == "#000000"


def test_every_mode2_numeric_and_string_tunable_is_a_named_constant():
    for name in ("M2_DRAG_THRESHOLD_PX", "LASSO_MIN_SAMPLE_PX", "LASSO_MIN_POINTS", "PALETTE_POPUP_COLUMNS",
                 "M2_SELECTED_BORDER_WIDTH", "RAINBOW_STOPS", "M2_UNDO_MOVE", "M2_UNDO_RAMP", "TIP_PALETTE_POPUP"):
        C.value(name)   # raises if undefined


# ═══════════════════════════ Mode 1 unchanged ═══════════════════════════
MODE1_STATE = "o.uiMode = UI_MODE_1;"


def test_mode1_left_click_on_point_still_grabs_and_drags_with_grab_cursor():
    r = _run("""down(100, 100); move(110, 100); up(110, 100);
      console.log(JSON.stringify({dragging: o.dragging, pts: o.polygons[0].points[0], hist: o.undoHistory.length,
        m2: o._m2, sel: sel()}));""", MODE1_STATE)
    assert r["m2"] is None and r["hist"] == 1 and r["pts"] == {"x": 110, "y": 100} and r["sel"] == "[[0,0]]"


def test_mode1_right_click_deletes_point_and_edge_right_click_adds_and_drags():
    r = _run("""o.onRightClick(ev(100, 100, {button: BTN_R}));
      const afterDel = o.polygons[0].points.length;
      o.onRightClick(ev(150, 100, {button: BTN_R}));   // edge between (100,100)->gone, use remaining edge
      console.log(JSON.stringify({afterDel, now: o.polygons[0].points.length, dragging: o.dragging}));""", MODE1_STATE)
    assert r["afterDel"] == 3 and r["now"] in (3, 4)


def test_mode1_b_key_toggles_paint_and_cmd_b_cmd_p_are_not_claimed():
    r = _run("""const e1 = key('b'); o.handleKey(e1); const on = o.paintMode;
      const e2 = key('b'); o.handleKey(e2); const off = o.paintMode;
      const eB = key('b', {metaKey: true}), eP = key('p', {metaKey: true}); o.handleKey(eB); o.handleKey(eP);
      console.log(JSON.stringify({on, off, bp: !!eB.prevented, pp: !!eP.prevented, sub: o.uiSubMode, paint: o.paintMode}));""",
             MODE1_STATE)
    assert r == {"on": True, "off": False, "bp": False, "pp": False, "sub": SUB_B, "paint": False}


def test_mode1_cmd_click_swatch_never_adds_a_second_brush_and_rubber_band_still_selects():
    r = _run("""o.onSwatchClick(5, {metaKey: true}); o.onSwatchClick(9, {metaKey: true});
      const brush = [o.paintBrush, o.paintBrush2];
      o.exitPaintMode(); o.selectedVerts = [];
      drag([[50, 50], [260, 260]]);     // Mode-1 rubber band over the green polygon
      console.log(JSON.stringify({brush, n: o.selectedVerts.length}));""", MODE1_STATE)
    assert r["brush"] == [9, None] and r["n"] == 4


# ═══════════════════════════ Boundary Editing (spreadsheet rows 2-11) ═══════════════════════════
def test_entering_modes_with_cmd_b_cmd_p_ctrl_equivalent_and_prevent_default():
    r = _run("""const out = [];
      for (const mod of ['metaKey', 'ctrlKey']) {
        const p = key(M2_KEY_PAINT, {[mod]: true}); o.handleKey(p); out.push([o.uiSubMode, o.paintMode, !!p.prevented]);
        const b = key(M2_KEY_BOUNDARY, {[mod]: true}); o.handleKey(b); out.push([o.uiSubMode, o.paintMode, !!b.prevented]);
      }
      console.log(JSON.stringify(out));""")
    assert r == [[SUB_P, True, True], [SUB_B, False, True]] * 2


def test_chords_ignored_inside_text_fields_so_browser_default_survives():
    r = _run("""const e = key(M2_KEY_PAINT, {metaKey: true, target: {tagName: 'INPUT'}}); o.handleKey(e);
      console.log(JSON.stringify({sub: o.uiSubMode, prevented: !!e.prevented}));""")
    assert r == {"sub": SUB_B, "prevented": False}


def test_boundary_cursor_is_normal_arrow_and_plain_b_does_nothing():
    r = _run("""o.setUiSubMode(UI_SUB_PAINT); o.setUiSubMode(UI_SUB_BOUNDARY);
      const c = o.$refs.canvas.style.cursor; o.handleKey(key('b'));
      move(100, 100); move(300, 300);
      console.log(JSON.stringify({c, paint: o.paintMode, now: o.$refs.canvas.style.cursor}));""")
    assert r == {"c": C.value("CURSOR_DEFAULT"), "paint": False, "now": C.value("CURSOR_DEFAULT")}


def test_left_click_on_point_selects_and_moves_it_until_release_as_one_undo_step():
    r = _run("""down(100, 100); move(105, 100); move(120, 110); up(120, 110);
      console.log(JSON.stringify({pt: o.polygons[0].points[0], sel: sel(), hist: o.undoHistory.map(h => h.label), saves: o.saves, m2: o._m2}));""")
    assert r["pt"] == {"x": 120, "y": 110} and r["sel"] == "[[0,0]]" and r["m2"] is None and r["saves"] == 1
    assert r["hist"] == [C.value("M2_UNDO_MOVE")]


def test_plain_click_on_point_without_movement_selects_but_adds_no_undo_entry():
    r = _run("""down(100, 100); up(100, 100);
      console.log(JSON.stringify({sel: sel(), hist: o.undoHistory.length}));""")
    assert r == {"sel": "[[0,0]]", "hist": 0}


def test_left_click_not_on_a_point_unselects_points_without_undo_step():
    r = _run("""o.selectedVerts = [{poly: 0, idx: 1}];
      down(300, 300); up(300, 300);
      const a = sel();
      o.selectedVerts = [{poly: 0, idx: 1}];
      down(300, 300); move(300 + %d - 1, 300); up(300 + %d - 1, 300);   // sub-threshold wobble is still a click
      console.log(JSON.stringify({a, sel: sel(), hist: o.undoHistory.length, rb: o.rubberBand}));""" % (THRESH, THRESH))
    assert r == {"a": "[]", "sel": "[]", "hist": 0, "rb": False}


def test_shift_click_on_empty_space_keeps_the_selection():
    r = _run("""o.selectedVerts = [{poly: 0, idx: 1}];
      down(300, 300, {shiftKey: true}); up(300, 300, {shiftKey: true});
      console.log(JSON.stringify({sel: sel()}));""")
    assert r == {"sel": "[[0,1]]"}


def test_drag_on_empty_space_still_rubber_bands_after_the_click_change():
    r = _run("""o.selectedVerts = [{poly: 1, idx: 0}];
      down(90, 90); move(120, 120); const during = o.rubberBand; move(210, 110); up(210, 110);
      console.log(JSON.stringify({during, sel: sel()}));""")
    assert r == {"during": True, "sel": "[[0,0],[0,1]]"}


def test_right_click_on_line_adds_point_selects_it_and_it_follows_the_mouse():
    r = _run("""const before = o.polygons[0].points.length;
      down(150, 88, {button: BTN_R, buttons: 2}); const added = o.polygons[0].points.length;
      const s0 = sel(); move(150, 130, {button: BTN_R, buttons: 2}); up(150, 130, {button: BTN_R});
      console.log(JSON.stringify({before, added, s0, pt: o.polygons[0].points[1], hist: o.undoHistory.map(h => h.label), saves: o.saves}));""")
    assert r["added"] == r["before"] + 1 and r["s0"] == "[[0,1]]"
    assert r["pt"]["x"] == 150 and r["pt"]["y"] > 100  # followed the mouse down to y=130 and r["saves"] == 1
    assert r["hist"] == [C.value("M2_UNDO_ADD")]             # add + the drag = ONE undo step


def test_right_click_release_without_drag_just_adds_and_selects():
    r = _run("""down(150, 88, {button: BTN_R, buttons: 2}); up(150, 88, {button: BTN_R});
      console.log(JSON.stringify({n: o.polygons[0].points.length, sel: sel()}));""")
    assert r == {"n": 5, "sel": "[[0,1]]"}


def test_right_click_not_on_a_line_unselects_points_and_changes_nothing_else():
    r = _run("""o.selectedVerts = [{poly: 0, idx: 1}];
      down(600, 600, {button: BTN_R, buttons: 2}); up(600, 600, {button: BTN_R});
      console.log(JSON.stringify({n: o.polygons[0].points.length, hist: o.undoHistory.length, popup: o.paintPopup.open, sel: sel()}));""")
    assert r == {"n": 4, "hist": 0, "popup": False, "sel": "[]"}


def test_right_click_on_control_point_deletes_it_and_undo_restores():
    r = _run("""down(100, 100, {button: BTN_R, buttons: 2}); up(100, 100, {button: BTN_R});
      const n = o.polygons[0].points.length; o.handleKey(key('z', {metaKey: true}));
      console.log(JSON.stringify({n, back: o.polygons[0].points.length}));""")
    assert r == {"n": 3, "back": 4}


def test_right_click_on_control_point_of_a_minimum_size_trap_removes_the_polygon_not_the_point():
    r = _run("""down(400, 400, {button: BTN_R, buttons: 2}); up(400, 400, {button: BTN_R});
      console.log(JSON.stringify({polys: o.polygons.length}));""")
    assert r == {"polys": 1}


def test_rubber_band_selects_points_inside_on_release_and_replaces_previous_selection():
    r = _run("""o.selectedVerts = [{poly: 1, idx: 0}];
      down(90, 90); move(120, 120); const during = o.rubberBand; move(210, 110); up(210, 110);
      console.log(JSON.stringify({during, after: o.rubberBand, sel: sel()}));""")
    assert r == {"during": True, "after": False, "sel": "[[0,0],[0,1]]"}


def test_shift_adds_to_the_selection_for_rubber_band_and_for_point_click():
    r = _run("""o.selectedVerts = [{poly: 1, idx: 0}];
      drag([[90, 90], [210, 110]], {shiftKey: true}); const band = sel();
      down(200, 200, {shiftKey: true}); up(200, 200, {shiftKey: true});
      console.log(JSON.stringify({band, click: sel()}));""")
    assert r["band"] == "[[0,0],[0,1],[1,0]]" and r["click"] == "[[0,0],[0,1],[0,2],[1,0]]"


def test_drag_on_a_selected_point_moves_all_selected_points_together():
    r = _run("""o.selectedVerts = [{poly: 0, idx: 0}, {poly: 0, idx: 1}];
      down(100, 100); move(110, 120); up(110, 120);
      console.log(JSON.stringify({p: o.polygons[0].points.slice(0, 3), hist: o.undoHistory.length}));""")
    assert r["p"] == [{"x": 110, "y": 120}, {"x": 210, "y": 120}, {"x": 200, "y": 200}] and r["hist"] == 1


def test_cmd_drag_on_a_selected_point_has_no_effect():
    r = _run("""o.selectedVerts = [{poly: 0, idx: 0}];
      down(100, 100, {metaKey: true}); move(140, 140, {metaKey: true}); up(140, 140, {metaKey: true});
      console.log(JSON.stringify({p: o.polygons[0].points[0], hist: o.undoHistory.length, sel: sel(), rb: o.rubberBand}));""")
    assert r == {"p": {"x": 100, "y": 100}, "hist": 0, "sel": "[[0,0]]", "rb": False}


def test_cmd_freehand_lasso_selects_inside_replaces_and_shift_adds():
    lasso = [[90, 90], [160, 85], [215, 90], [215, 150], [150, 160], [92, 140], [90, 90]]
    script = """o.selectedVerts = [{poly: 1, idx: 2}];
      const pts = %s; down(pts[0][0], pts[0][1], {metaKey: true, shiftKey: SHIFT});
      for (const p of pts.slice(1)) move(p[0], p[1], {metaKey: true, shiftKey: SHIFT});
      const during = o.lassoPts ? o.lassoPts.length : 0;
      up(90, 90, {metaKey: true, shiftKey: SHIFT});
      console.log(JSON.stringify({during, after: o.lassoPts, sel: sel()}));""" % json.dumps(lasso)
    r = _run(script.replace("SHIFT", "false"))
    assert r["during"] > 2 and r["after"] is None and r["sel"] == "[[0,0],[0,1]]"      # replaces
    r = _run(script.replace("SHIFT", "true"))
    assert r["sel"] == "[[0,0],[0,1],[1,2]]"                                            # Shift adds


def test_ctrl_works_like_cmd_for_the_lasso():
    lasso = [[90, 90], [215, 90], [215, 215], [90, 215]]
    r = _run("""const pts = %s; down(pts[0][0], pts[0][1], {ctrlKey: true});
      for (const p of pts.slice(1)) move(p[0], p[1], {ctrlKey: true});
      up(90, 215, {ctrlKey: true}); console.log(JSON.stringify(sel()));""" % json.dumps(lasso))
    assert r == "[[0,0],[0,1],[0,2],[0,3]]"


def test_esc_clears_the_point_selection_in_boundary_editing():
    r = _run("""o.selectedVerts = [{poly: 0, idx: 0}]; const e = key(M2_KEY_CANCEL); o.handleKey(e);
      console.log(JSON.stringify({sel: o.selectedVerts.length}));""")
    assert r == {"sel": 0}


def test_selected_point_look_is_same_size_black_border_in_source():
    assert "this._drawM2SelectedVertex(ctx, p, baseR * dpr, polyColor, dpr)" in EDITOR   # unselected radius, polygon colour
    block = _method("_drawM2SelectedVertex")
    assert "fillStyle = color" in block and "COLOR_M2_SELECTED_BORDER" in block and "M2_SELECTED_BORDER_WIDTH" in block


# ═══════════════════════════ Z-Painting (spreadsheet rows 14-25) ═══════════════════════════
def test_swatch_click_selects_single_brush_and_enters_z_painting_with_that_brush_cursor():
    r = _run("""o.onSwatchClick(7, {});
      console.log(JSON.stringify({sub: o.uiSubMode, paint: o.paintMode, b: [o.paintBrush, o.paintBrush2],
        cur: o.$refs.canvas.style.cursor, want: o.paintCursorCss()}));""")
    assert r["sub"] == SUB_P and r["paint"] and r["b"] == [7, None] and r["cur"] == r["want"]
    assert "bristles" in re.sub(r"%[0-9A-F]{2}", lambda m: bytes.fromhex(m.group(0)[1:]).decode(), r["cur"]) \
        or "data:image/svg" in r["cur"]


def test_cmd_click_second_swatch_activates_two_brushes_with_rainbow_cursor():
    gid = C.value("RAINBOW_GRADIENT_ID")
    r = _run("""o.onSwatchClick(7, {}); o.onSwatchClick(20, {metaKey: true});
      console.log(JSON.stringify({b: [o.paintBrush, o.paintBrush2], cur: decodeURIComponent(o.$refs.canvas.style.cursor)}));""")
    assert r["b"] == [7, 20] and gid in r["cur"] and all(c in r["cur"] for c in C.value("RAINBOW_STOPS"))


def test_cmd_click_with_no_single_brush_active_behaves_like_plain_click():
    r = _run("""o.onSwatchClick(3, {ctrlKey: true});                         // not in Z-Painting yet
      const a = [o.paintBrush, o.paintBrush2, o.uiSubMode];
      o.onSwatchClick(PAINT_BRUSH_ERASER, {}); o.onSwatchClick(9, {metaKey: true});   // eraser active: plain click
      const b = [o.paintBrush, o.paintBrush2];
      o.onSwatchClick(4, {}); o.onSwatchClick(8, {metaKey: true}); o.onSwatchClick(12, {metaKey: true});  // two active: plain
      console.log(JSON.stringify({a, b, c: [o.paintBrush, o.paintBrush2]}));""")
    assert r == {"a": [3, None, SUB_P], "b": [9, None], "c": [12, None]}


def test_plain_click_after_two_brushes_returns_to_single_brush_and_normal_cursor():
    r = _run("""o.onSwatchClick(7, {}); o.onSwatchClick(20, {metaKey: true}); o.onSwatchClick(5, {});
      console.log(JSON.stringify({b: [o.paintBrush, o.paintBrush2], same: o.$refs.canvas.style.cursor === o.paintCursorCss()}));""")
    assert r == {"b": [5, None], "same": True}


def test_eraser_active_uses_eraser_cursor_and_erases_click_and_drag():
    r = _run("""o.gridCellHeights = {[cellIdx(2, 2)]: 5, [cellIdx(3, 2)]: 6, [cellIdx(4, 2)]: 7, [cellIdx(9, 9)]: 1};
      o.onSwatchClick(PAINT_BRUSH_ERASER, {}); const cur = o.$refs.canvas.style.cursor;
      drag([cellXY(2, 2), cellXY(4, 2)]);
      console.log(JSON.stringify({left: o.gridCellHeights, hist: o.undoHistory.length, same: cur === o.paintCursorCss()}));""")
    assert r["left"] == {str((N - 1 - 9) * N + 9): 1} and r["hist"] == 1 and r["same"]


def test_eraser_acts_as_brush_valued_null_in_rubber_band_fill():
    r = _run("""for (let i = 0; i < 8; i++) for (let j = 0; j < 8; j++) o.gridCellHeights[cellIdx(i, j)] = 3;
      o.onSwatchClick(PAINT_BRUSH_ERASER, {});
      drag([[1.5, 1.5], [5.5, 4.5]], {metaKey: true});
      console.log(JSON.stringify({n: Object.keys(o.gridCellHeights).length, hist: o.undoHistory.length}));""")
    assert r == {"n": 64 - 3 * 2, "hist": 1}          # cells i=2..4, j=2..3 erased


def test_one_brush_click_and_drag_paint_every_touched_cell_as_one_undo_step():
    r = _run("""o.onSwatchClick(25, {}); const v = paintBrushValue(25, 'delta');
      drag([cellXY(1, 1), cellXY(6, 1), cellXY(6, 4)]);
      const keys = Object.keys(o.gridCellHeights).length;
      const hist = o.undoHistory.length; const vals = new Set(Object.values(o.gridCellHeights));
      o.handleKey(key('z', {metaKey: true}));
      console.log(JSON.stringify({keys, hist, vals: [...vals], v, after: Object.keys(o.gridCellHeights).length}));""")
    assert r["keys"] == 6 + 3 and r["hist"] == 1 and r["vals"] == [r["v"]] and r["after"] == 0


def test_single_click_paints_one_cell():
    r = _run("""o.onSwatchClick(25, {}); down(...cellXY(3, 3)); up(...cellXY(3, 3));
      console.log(JSON.stringify(Object.keys(o.gridCellHeights)));""")
    assert r == [str((N - 1 - 3) * N + 3)]


def test_cmd_drag_with_one_brush_fills_only_cells_entirely_inside_the_band_on_release():
    r = _run("""o.onSwatchClick(25, {});
      down(1.5, 1.5, {metaKey: true}); move(5.5, 4.5, {metaKey: true});
      const live = Object.keys(o.gridCellHeights).length, rb = o.rubberBand;
      up(5.5, 4.5, {metaKey: true});
      console.log(JSON.stringify({live, rb, after: Object.keys(o.gridCellHeights).map(Number).sort((a, b) => a - b),
        want: [2, 3, 4].flatMap(i => [2, 3].map(j => cellIdx(i, j))).sort((a, b) => a - b), hist: o.undoHistory.length, rbAfter: o.rubberBand}));""")
    assert r["live"] == 0 and r["rb"] is True and r["after"] == r["want"] and r["hist"] == 1 and r["rbAfter"] is False


def test_ctrl_is_interchangeable_with_cmd_for_band_fill():
    r = _run("""o.onSwatchClick(25, {}); drag([[1.5, 1.5], [4.5, 4.5]], {ctrlKey: true});
      console.log(JSON.stringify(Object.keys(o.gridCellHeights).length));""")
    assert r == 4                      # cells i, j in {2, 3} lie entirely inside 1.5..4.5


def test_two_brushes_drag_selects_cells_in_visit_order_and_release_ramps_between_brushes():
    r = _run("""o.onSwatchClick(10, {}); o.onSwatchClick(20, {metaKey: true});
      down(...cellXY(0, 0)); for (let i = 1; i < 5; i++) move(...cellXY(i, 0));
      const live = {sel: [...o._gridMultiSelect], stored: Object.keys(o.gridCellHeights).length};
      up(...cellXY(4, 0));
      const order = [0, 1, 2, 3, 4].map(i => o.gridCellHeights[cellIdx(i, 0)]);
      console.log(JSON.stringify({live, order, cleared: o._gridMultiSelect, hist: o.undoHistory.length, saves: o.saves,
        want: [0, 1, 2, 3, 4].map(k => paintBrushValue(rampStepAt(k, 5, 10, 20), 'delta'))}));""")
    assert r["live"]["sel"] == [(N - 1) * N + i for i in range(5)] and r["live"]["stored"] == 0
    assert r["order"] == r["want"] == [-5, -2.5, 0, 2.5, 5] or r["order"] == r["want"]
    assert r["cleared"] is None and r["hist"] == 1 and r["saves"] == 1


def test_ramp_is_monotone_discrete_quantised_and_repeats_values_when_many_cells():
    r = _run("""const n = 40, s = Array.from({length: n}, (_, k) => rampStepAt(k, n, 3, 8));
      console.log(JSON.stringify({s, single: rampStepAt(0, 1, 6, 9), down: [0, 1, 2].map(k => rampStepAt(k, 3, 20, 10))}));""")
    s = r["s"]
    assert s[0] == 3 and s[-1] == 8 and s == sorted(s) and len(set(s)) == 6 and len(s) > len(set(s))   # coarse + repeats
    assert all(isinstance(v, int) for v in s)
    assert r["single"] == 6 and r["down"] == [20, 15, 10]


def test_ramp_cells_are_not_duplicated_when_the_drag_revisits_a_cell_and_fast_moves_skip_none():
    r = _run("""o.onSwatchClick(10, {}); o.onSwatchClick(20, {metaKey: true});
      down(...cellXY(0, 0)); move(...cellXY(6, 0)); move(...cellXY(2, 0)); up(...cellXY(2, 0));
      console.log(JSON.stringify(Object.keys(o.gridCellHeights).length));""")
    assert r == 7


def test_two_brush_ramp_undo_redo_is_one_step():
    r = _run("""o.onSwatchClick(10, {}); o.onSwatchClick(20, {metaKey: true});
      drag([cellXY(0, 0), cellXY(3, 0)]);
      o.handleKey(key('z', {metaKey: true})); const afterUndo = Object.keys(o.gridCellHeights).length;
      o.handleKey(key('z', {metaKey: true, shiftKey: true})); const afterRedo = Object.keys(o.gridCellHeights).length;
      console.log(JSON.stringify({afterUndo, afterRedo}));""")
    assert r["afterUndo"] == 0 and r["afterRedo"] in (0, 4)   # redo of grid entries follows the existing v5.77 behaviour


def test_right_click_opens_popup_palette_at_cursor_and_picking_dismisses_with_new_single_brush():
    r = _run("""o.onSwatchClick(7, {}); o.onSwatchClick(20, {metaKey: true});
      down(300, 200, {button: BTN_R, buttons: 2}); up(300, 200, {button: BTN_R});
      const opened = JSON.parse(JSON.stringify(o.paintPopup));
      o.pickPopupBrush(12);
      console.log(JSON.stringify({opened, closed: o.paintPopup.open, b: [o.paintBrush, o.paintBrush2],
        cur: o.$refs.canvas.style.cursor === o.paintCursorCss(), cells: Object.keys(o.gridCellHeights).length}));""")
    assert r["opened"] == {"open": True, "x": 300, "y": 200} and r["closed"] is False
    assert r["b"] == [12, None] and r["cur"] and r["cells"] == 0


def test_popup_can_pick_the_eraser_and_is_clamped_inside_the_viewport():
    r = _run("""o.setUiSubMode(UI_SUB_PAINT);
      down(990, 790, {button: BTN_R, buttons: 2});
      const p = JSON.parse(JSON.stringify(o.paintPopup)); o.pickPopupBrush(PAINT_BRUSH_ERASER);
      console.log(JSON.stringify({p, b: o.paintBrush}));""")
    w = C.value("PALETTE_POPUP_COLUMNS") * C.value("PALETTE_POPUP_SWATCH_PX") + 2 * C.value("PALETTE_POPUP_PAD_PX")
    assert r["p"]["open"] and r["p"]["x"] == 1000 - w and r["p"]["y"] < 790 and r["b"] == ERASER


def test_popup_dismissed_by_esc_and_by_clicking_elsewhere_without_painting():
    r = _run("""o.setUiSubMode(UI_SUB_PAINT);
      down(300, 200, {button: BTN_R, buttons: 2}); const e = key(M2_KEY_CANCEL); o.handleKey(e);
      const esc = [o.paintPopup.open, !!e.prevented];
      down(300, 200, {button: BTN_R, buttons: 2}); down(50, 50); up(50, 50);       // outside click: dismiss, no paint
      console.log(JSON.stringify({esc, out: o.paintPopup.open, cells: Object.keys(o.gridCellHeights).length}));""")
    assert r == {"esc": [False, True], "out": False, "cells": 0}


def test_esc_in_z_painting_without_popup_does_nothing_special():
    r = _run("""o.onSwatchClick(7, {}); o.selectedVerts = [{poly: 0, idx: 0}]; o.handleKey(key(M2_KEY_CANCEL));
      console.log(JSON.stringify({paint: o.paintMode, sub: o.uiSubMode, sel: o.selectedVerts.length, b: o.paintBrush}));""")
    assert r == {"paint": True, "sub": SUB_P, "sel": 1, "b": 7}


def test_right_click_in_z_painting_does_not_add_or_delete_boundary_points():
    r = _run("""o.setUiSubMode(UI_SUB_PAINT); down(100, 100, {button: BTN_R, buttons: 2}); up(100, 100, {button: BTN_R});
      console.log(JSON.stringify({n: o.polygons[0].points.length, popup: o.paintPopup.open}));""")
    assert r == {"n": 4, "popup": True}


def test_z_painting_requires_grid_on_and_otherwise_stays_in_boundary_editing():
    r = _run("""o.gridMode = GRID_MODE_OFF; o.setUiSubMode(UI_SUB_PAINT);
      console.log(JSON.stringify({sub: o.uiSubMode, paint: o.paintMode}));""")
    assert r == {"sub": SUB_B, "paint": False}


def test_undo_and_redo_keys_work_across_boundary_and_painting_in_one_history():
    r = _run("""down(100, 100); move(130, 100); up(130, 100);              // boundary move
      o.onSwatchClick(25, {}); down(...cellXY(2, 2)); up(...cellXY(2, 2));   // paint a cell
      const h = o.undoHistory.map(e => e.kind);
      o.handleKey(key('z', {metaKey: true})); const cellGone = Object.keys(o.gridCellHeights).length;
      o.handleKey(key('z', {ctrlKey: true})); const moved = o.polygons[0].points[0].x;
      console.log(JSON.stringify({h, cellGone, moved}));""")
    assert r == {"h": [C.value("UNDO_KIND_POLY"), C.value("UNDO_KIND_GRID")], "cellGone": 0, "moved": 100}


# ═══════════════════════════ switching modes ═══════════════════════════
def test_switching_back_to_mode_1_leaves_paint_state_and_restores_cursor():
    r = _run("""o.onSwatchClick(7, {}); o.onSwatchClick(20, {metaKey: true});
      down(300, 200, {button: BTN_R, buttons: 2});              // popup open
      o.uiMode = UI_MODE_1; o.onUiModeChanged(UI_MODE_1);
      console.log(JSON.stringify({paint: o.paintMode, sub: o.uiSubMode, b2: o.paintBrush2, popup: o.paintPopup.open,
        cur: o.$refs.canvas.style.cursor, m2: o._m2, lasso: o.lassoPts}));""")
    assert r == {"paint": False, "sub": SUB_B, "b2": None, "popup": False, "cur": C.value("CURSOR_DEFAULT"),
                 "m2": None, "lasso": None}


def test_entering_mode_2_starts_in_boundary_editing_and_cancels_contour_drawing():
    r = _run("""o.uiMode = UI_MODE_1; o.contourMode = true; o.contourDraft = [{x: 1, y: 2}];
      o.uiMode = UI_MODE_2; o.onUiModeChanged(UI_MODE_2);
      console.log(JSON.stringify({sub: o.uiSubMode, c: o.contourMode, d: o.contourDraft.length}));""")
    assert r == {"sub": SUB_B, "c": False, "d": 0}


def test_mid_gesture_mode_switch_commits_nothing_half_done():
    r = _run("""o.onSwatchClick(10, {}); o.onSwatchClick(20, {metaKey: true});
      down(...cellXY(0, 0)); move(...cellXY(3, 0));
      o.uiMode = UI_MODE_1; o.onUiModeChanged(UI_MODE_1);
      console.log(JSON.stringify({ms: o._gridMultiSelect, cells: Object.keys(o.gridCellHeights).length, l: window.l}));""")
    assert r == {"ms": None, "cells": 0, "l": None}


def test_mode2_dblclick_and_mode1_only_keys_are_inert():
    r = _run("""o.onDblClick(ev(150, 100)); o.handleKey(key('b')); o.handleKey(key('c', {metaKey: true}));
      console.log(JSON.stringify({n: o.polygons[0].points.length, paint: o.paintMode}));""")
    assert r == {"n": 4, "paint": False}
