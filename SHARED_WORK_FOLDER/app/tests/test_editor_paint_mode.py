"""Editor v5.77: paint mode (left palette + brush cursor + drag painting) and the unified undo history.

Same technique as the other editor tests: the real constants block (editor_constants.prelude()) and the real
methods are cut out of templates/editor.html and run in node against a mock editor object.  No server, no DB,
no EGM files.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest

APP_DIR = Path(__file__).parent.parent
EDITOR = (APP_DIR / "templates" / "editor.html").read_text()
sys.path.insert(0, str(Path(__file__).parent))
import editor_constants as C

node = shutil.which("node")
pytestmark = pytest.mark.skipif(not node, reason="node not installed")

PAINT_METHODS = ["updatePaletteSize", "paletteColor", "paintBrushValueNow", "enterPaintMode", "exitPaintMode",
                 "togglePaintMode", "selectBrush", "paintCursorCss", "applyPaintCursor", "_imgToCellUV",
                 "_paintCells", "paintBegin", "paintMove", "paintEnd", "cellColorAt", "cancelGridRamp",
                 "cancelGridCell", "pushGridUndo", "_trimUndo", "undo", "_undoGridEntry", "_m2ClearSelection"]
UNDO_METHODS = ["pushUndo", "_trimUndo", "pushGridUndo", "undo", "_undoGridEntry",
                "redo", "gridUndoSnapshot", "commitGridCell", "setGridResolution", "snapshotPolygons",
                "restoreSnapshot"]


def _method(name):
    m = re.search(r"\n    (%s\(.*?\n    \}),\n" % re.escape(name), EDITOR, re.S)
    assert m, name + " missing"
    return m.group(1)


def _handle_key():
    i = EDITOR.index("    handleKey(e) {")
    j = EDITOR.index("\n    },\n  };\n}", i)
    return EDITOR[i:j + len("\n    }")]


def _run(script, methods=None, extra_state=""):
    """Run `script` against a mock editor `o` carrying the real methods named in `methods`."""
    methods = methods or []
    body = ",\n".join(_handle_key() if n == "handleKey" else _method(n) for n in methods)
    js = C.prelude() + """
const o = {
  gridMode:'delta', gridN:20, gridCellHeights:{}, imgLoaded:true, printSizeMm:20,
  paintMode:false, paintBrush: PAINT_DEFAULT_STEP, _paintStroke:null, paletteSwatchPx:20,
  undoHistory:[], redoStack:[], maxUndo:100, polygons:[], contours:[], selectedVerts:[], selectedPoly:0,
  _gridActiveCell:null, _gridMultiSelect:null, _gridHoveredCell:null, _gridInputValue:'',
  showNewDialog:false, showOpenDialog:false, contourMode:false,
  $refs:{canvas:{style:{cursor:'default'}}},
  saves:0, draws:0, flashes:[],
  draw(){this.draws++}, autoSave(){this.saves++}, flash(m){this.flashes.push(m)},
  canvasToImg(e){return {x:e.x, y:e.y}},
  _printTopLeftPx(){return {x:0,y:0}}, _pxPerMm(){return 1},
};
%s
const M = {%s};
for (const k in M) Object.defineProperty(o, k, Object.getOwnPropertyDescriptor(M, k));
""" % (extra_state, body) + script
    out = subprocess.run([node, "-e", js], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _ev(key, tag="DIV", **kw):
    d = {"key": key, "target": {"tagName": tag}, "metaKey": False, "ctrlKey": False, "altKey": False,
         "shiftKey": False}
    d.update(kw)
    return "Object.assign(%s, {preventDefault(){}})" % json.dumps(d)


# ───────────────────────────── palette ─────────────────────────────
def _delta_step(mm):
    """Palette index of the delta value `mm` (v6.13: half-step palette)."""
    return round((mm - C.value("CELL_COLOR_DELTA_MIN_MM")) / C.value("PALETTE_VALUE_STEP"))


def _abs_step(mm):
    return round((mm - C.value("CELL_COLOR_ABSOLUTE_MIN_MM")) / C.value("PALETTE_VALUE_STEP"))


def _fmt(v, signed):
    t = ("%g" % v)
    return t  # v6.16: palette labels carry no "+" prefix (signed kept for call-site compatibility)


def test_palette_has_half_steps_plus_eraser_with_labels_per_mode():
    r = _run("""console.log(JSON.stringify({
        steps: paletteSteps(), n: PALETTE_STEP_COUNT,
        delta: paletteSteps().map(s => paletteLabel(s, 'delta')),
        side: paletteSteps().map(s => paletteSideLabel(s, 'delta')),
        abs: paletteSteps().map(s => paletteLabel(s, 'absolute')),
        vals: [paintBrushValue(PALETTE_STEP_COUNT - 1,'delta'), paintBrushValue(1,'delta'), paintBrushValue(0,'delta'),
               paintBrushValue(PALETTE_STEP_COUNT - 1,'absolute'), paintBrushValue(0,'absolute')]}));""")
    step = C.value("PALETTE_VALUE_STEP")
    dlo, dhi = C.value("CELL_COLOR_DELTA_MIN_MM"), C.value("CELL_COLOR_DELTA_MAX_MM")
    alo, ahi = C.value("CELL_COLOR_ABSOLUTE_MIN_MM"), C.value("CELL_COLOR_ABSOLUTE_MAX_MM")
    n = round((dhi - dlo) / step) + 1
    assert r["n"] == n == C.value("PALETTE_STEP_COUNT") and len(r["steps"]) == n and r["steps"][0] == n - 1 and r["steps"][-1] == 0
    dvals = [dhi - k * step for k in range(n)]
    assert r["delta"] == [_fmt(v, True) for v in dvals]                       # +15 (top) .. -15 (bottom), half steps as +1.5
    assert any(x.endswith(".5") for x in r["delta"]) and "1.5" in r["delta"] and "-1.5" in r["delta"] and "0.5" not in "".join(x for x in r["delta"] if x == "0")
    assert r["side"] == [x if float(x) == int(float(x)) else "" for x in r["delta"]]   # side strip: whole steps only
    assert r["abs"] == [_fmt(ahi - k * step, False) for k in range(n)]
    assert r["vals"] == [dhi, dlo + step, dlo, ahi, alo]


def test_palette_half_step_values_are_stored_and_round_trip_through_the_brush():
    r = _run("""console.log(JSON.stringify([2, 3].map(s => paintBrushValue(s, 'delta'))));""")
    step, dlo = C.value("PALETTE_VALUE_STEP"), C.value("CELL_COLOR_DELTA_MIN_MM")
    assert r == [dlo + 2 * step, dlo + 3 * step]
    # no integer-only assumption left: the palette index math goes through PALETTE_VALUE_STEP, never a bare 1 mm
    assert "step * PALETTE_VALUE_STEP" in EDITOR and "CELL_COLOR_STOPS.length - 1)" not in _method("paletteColor")


def test_adjacent_swatches_are_visually_distinguishable():
    stops = C.value("CELL_COLOR_STOPS")
    r = _run("""console.log(JSON.stringify(paletteSteps().map(s => o.cellColorAt(s / (PALETTE_STEP_COUNT - 1)))));""", ["cellColorAt"])
    d = [max(abs(a - b) for a, b in zip(r[i], r[i + 1])) for i in range(len(r) - 1)]
    assert all(x >= 1 for x in d)   # every neighbouring pair differs (labels + tooltip carry the exact value)


def test_palette_colors_come_from_the_fixed_scale_not_a_second_list():
    stops = C.value("CELL_COLOR_STOPS")
    r = _run("""console.log(JSON.stringify(paletteSteps().map(s => [o.paletteColor(s), o.cellColorAt(s/(PALETTE_STEP_COUNT-1))])));""",
             ["paletteColor", "cellColorAt"])
    per = C.value("PALETTE_STEP_COUNT") // (len(stops) - 1)   # swatches per colour stop (whole-mm swatches land exactly on a stop)
    for (css, rgb), step in zip(r, range(C.value("PALETTE_STEP_COUNT") - 1, -1, -1)):
        if step % per:
            assert css == "rgb(%d,%d,%d)" % tuple(rgb)   # half step: interpolated between the neighbouring stops
            continue
        hexs = stops[step // per]
        want = [int(hexs[k:k + 2], 16) for k in (1, 3, 5)]
        assert rgb == want and css == "rgb(%d,%d,%d)" % tuple(want)
    # no second hard-coded colour list: the first stop colour literal exists exactly once (the stop table)
    assert EDITOR.lower().count(stops[0].lower()) == 1


def test_palette_markup_and_swatch_height_fits_viewport():
    assert 'data-testid="paint-palette"' in EDITOR and 'data-testid="palette-eraser"' in EDITOR
    assert 'x-for="step in paletteSteps()"' in EDITOR and 'x-show="paletteVisible"' in EDITOR
    assert re.search(r"get paletteVisible\(\)\s*\{\s*return this\.imgLoaded && this\.gridMode !== GRID_MODE_OFF", EDITOR)
    r = _run("""console.log(JSON.stringify([400, 600, 800, 1200, 2000].map(h => [h, paletteSwatchHeight(h)])));""")
    for h, sw in r:
        assert C.value("PALETTE_LABEL_MIN_EDGE_PX") <= sw <= C.value("PALETTE_SWATCH_MAX_PX")
        if h >= 700:   # tall enough that the floor does not apply: PALETTE_STEP_COUNT swatches + eraser row must fit
            assert C.value("PALETTE_STEP_COUNT") * sw + sw + C.value("PALETTE_ERASER_ROW_EXTRA_PX") <= h
    assert r[-1][1] == C.value("PALETTE_SWATCH_MAX_PX")
    # v6.14: side colour boxes are landscape at every viewport height (width > the tallest possible height)
    assert C.value("PALETTE_SWATCH_WIDTH_PX") > C.value("PALETTE_SWATCH_MAX_PX")
    assert C.value("PALETTE_POPUP_SWATCH_PX") > C.value("PALETTE_POPUP_SWATCH_H_PX")


# ───────────────────────────── enter / exit ─────────────────────────────
def test_enter_exit_paths_and_brush_memory():
    r = _run("""
      const log = [];
      o.selectBrush(7);                                         // swatch click enters with that brush
      log.push([o.paintMode, o.paintBrush]);
      o.handleKey(%(esc)s); log.push(o.paintMode);              // Esc exits
      o.handleKey(%(b)s);   log.push([o.paintMode, o.paintBrush]);   // B enters, brush remembered
      o.handleKey(%(B)s);   log.push(o.paintMode);              // B again exits (capital B too)
      o.togglePaintMode();  log.push(o.paintMode);              // Paint button
      o.togglePaintMode();  log.push(o.paintMode);
      o.enterPaintMode(); o.gridMode = 'off'; o.exitPaintMode(); log.push([o.paintMode, o.$refs.canvas.style.cursor]);
      o.gridMode = 'off'; log.push([o.enterPaintMode(), o.paintMode, o.flashes.length]);   // cannot enter while Off
      console.log(JSON.stringify(log));""" % {"esc": _ev("Escape"), "b": _ev("b"), "B": _ev("B")},
             PAINT_METHODS + ["handleGenerateKey", "handleKey"])
    assert r == [[True, 7], False, [True, 7], False, True, False, [False, "default"], [False, False, 1]]


def test_b_and_esc_ignored_while_typing_or_with_modifier():
    r = _run("""
      o.handleKey(%(b_in)s); const a = o.paintMode;
      o.handleKey(%(b_ta)s); const b = o.paintMode;
      o.handleKey(%(b_cmd)s); const c = o.paintMode;
      o.enterPaintMode(); o.handleKey(%(esc_in)s); const d = o.paintMode;   // Esc inside an input leaves paint mode on
      o.showNewDialog = true; o.handleKey(%(esc)s); const e = o.paintMode;   // dialog open: ignored
      console.log(JSON.stringify([a, b, c, d, e]));""" % {
        "b_in": _ev("b", "INPUT"), "b_ta": _ev("b", "TEXTAREA"), "b_cmd": _ev("b", metaKey=True),
        "esc_in": _ev("Escape", "INPUT"), "esc": _ev("Escape")},
             PAINT_METHODS + ["handleGenerateKey", "handleKey"])
    assert r == [False, False, False, True, True]


def test_entering_paint_closes_open_value_box():
    r = _run("""o._gridActiveCell = {idx:1}; o._gridMultiSelect = new Set([1]); o.enterPaintMode();
      console.log(JSON.stringify([o._gridActiveCell, o._gridMultiSelect, o.paintMode]));""", PAINT_METHODS)
    assert r == [None, None, True]


def test_paint_branches_in_pointer_handlers():
    md = EDITOR[EDITOR.index("    onMouseDown(e) {"):][:800]
    assert md.index("this.paintMode") < md.index("this.contourMode")       # paint wins over contour / select / drag
    assert "this.paintBegin(e)" in md
    assert "if (this.paintMode) { this.paintMove(e); return; }" in EDITOR
    assert "if (this._paintStroke) { this.paintEnd(); return; }" in EDITOR
    assert re.search(r"onDblClick\(e\) \{\s*if \(this\.paintMode\) return;", EDITOR)
    assert re.search(r"onRightClick\(e\) \{\s*if \(this\.paintMode\) return;", EDITOR)
    assert "exitPaintMode()" in EDITOR[EDITOR.index("@click=\"gridMode = GRID_MODE_OFF"):][:120]
    assert "$watch('gridMode'" in EDITOR


# ───────────────────────────── painting ─────────────────────────────
def test_segment_traversal_visits_every_cell_in_order():
    r = _run("""console.log(JSON.stringify([
        cellsAlongSegment(0.5, 0.5, 4.5, 0.5),
        cellsAlongSegment(4.5, 2.5, 1.5, 2.5),
        cellsAlongSegment(0.5, 0.5, 2.5, 2.5),
        cellsAlongSegment(1.2, 1.2, 1.4, 1.4)]));""")
    assert r[0] == [[i, 0] for i in range(5)]
    assert r[1] == [[i, 2] for i in (4, 3, 2, 1)]
    diag = r[2]
    assert diag[0] == [0, 0] and diag[-1] == [2, 2] and len(diag) == 5          # 4-connected staircase
    assert all(abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1 for a, b in zip(diag, diag[1:]))
    assert r[3] == [[1, 1]]


@pytest.mark.parametrize("n", [20, 40])
def test_stroke_paints_interpolated_cells_at_both_resolutions(n):
    # cell edge = 20 mm / n  (printSizeMm 20, 1 px per mm): centre of cell (c, r-from-top) is ((c+.5)w, (r+.5)w)
    r = _run("""
      const w = o.printSizeMm / o.gridN, at = (c, rt) => ({x:(c+.5)*w, y:(rt+.5)*w, buttons:1});
      o.paintBrush = %(b5)d;                                           // delta +5
      o.paintBegin(at(0, 0));
      o.paintMove(at(%(far)d, 0));                                     // one huge jump: must not skip cells
      o.paintMove(at(%(far)d, 3));
      o.paintEnd();
      console.log(JSON.stringify({h:o.gridCellHeights, hist:o.undoHistory.length, saves:o.saves, N:o.gridN}));""" % {"far": n // 2, "b5": _delta_step(5)},
             PAINT_METHODS, extra_state="o.gridN = %d;" % n)
    N = r["N"]
    want = {}
    for c in range(0, n // 2 + 1):
        want[str((N - 1) * N + c)] = 5            # row 0 from the top = highest row index
    for rt in range(0, 4):
        want[str((N - 1 - rt) * N + n // 2)] = 5
    assert r["h"] == want
    assert r["hist"] == 1 and r["saves"] == 1       # one stroke = one undo entry, one autosave


def test_brush_value_follows_mode_and_eraser_deletes_and_zero_is_explicit():
    r = _run("""
      o.gridCellHeights = {5: 9, 6: 4};
      const at = (c) => ({x:c+.5, y:.5, buttons:1});
      o.gridMode = 'absolute'; o.paintBrush = %(a12)d;                  // 12 mm absolute
      o.paintBegin({x:5.5,y:19.5,buttons:1}); o.paintEnd();            // cell idx = (19-19)*20+5
      const abs = o.gridCellHeights[5];
      o.gridMode = 'delta'; o.paintBrush = %(d0)d;                     // delta 0 = REAL value (v5.80) -> stored
      o.paintBegin({x:5.5,y:19.5,buttons:1}); o.paintEnd();
      const zero = o.gridCellHeights[5];
      o.paintBrush = PAINT_BRUSH_ERASER;
      o.paintBegin({x:6.5,y:19.5,buttons:1}); o.paintEnd();
      console.log(JSON.stringify({abs, zero, erased: 6 in o.gridCellHeights}));""" % {"a12": _abs_step(12), "d0": _delta_step(0)}, PAINT_METHODS)
    assert r == {"abs": 12, "zero": 0, "erased": False}


COMMIT_METHODS = UNDO_METHODS + ["_untouchedExplicitZero", "cancelGridCell"]


def test_brush_zero_is_stored_then_eraser_empties_and_undo_restores_exactly():
    r = _run("""
      const at = {x:5.5, y:19.5, buttons:1};
      o.paintBrush = %d;                                               // delta 0 mm
      o.paintBegin(at); o.paintEnd();
      const painted = JSON.parse(JSON.stringify(o.gridCellHeights));   // survives a save/load JSON round trip
      o.paintBrush = PAINT_BRUSH_ERASER; o.paintBegin(at); o.paintEnd();
      const erased = JSON.stringify(o.gridCellHeights);
      o.undo(); const undoErase = JSON.stringify(o.gridCellHeights);   // explicit 0 stays explicit 0
      o.undo(); const undoPaint = JSON.stringify(o.gridCellHeights);   // empty stays empty
      console.log(JSON.stringify({painted, erased, undoErase, undoPaint}));""" % _delta_step(0), PAINT_METHODS)
    assert r == {"painted": {"5": 0}, "erased": "{}", "undoErase": '{"5":0}', "undoPaint": "{}"}


def test_typed_zero_empties_but_untouched_explicit_zero_survives_open_and_blur():
    r = _run("""
      o.gridCellHeights = {3: 0, 4: 2.5};
      o._gridActiveCell = {idx:3}; o._gridInputValue = gridValueText(0); o.commitGridCell();      // open + blur untouched (box reads 0.0 since v6.10)
      const kept = JSON.stringify(o.gridCellHeights);
      o._gridActiveCell = {idx:4}; o._gridInputValue = '0'; o.commitGridCell();      // typed 0 over a value
      const typed = JSON.stringify(o.gridCellHeights);
      o.undo(); const undone = JSON.stringify(o.gridCellHeights);
      o._gridActiveCell = {idx:9}; o._gridInputValue = '0'; o.commitGridCell();      // typed 0 on an empty cell
      console.log(JSON.stringify({kept, typed, undone, empty: JSON.stringify(o.gridCellHeights), saves:o.saves}));""", COMMIT_METHODS)
    assert r["kept"] == '{"3":0,"4":2.5}' and r["typed"] == '{"3":0}' and r["undone"] == '{"3":0,"4":2.5}'
    assert r["empty"] == '{"3":0,"4":2.5}' and r["saves"] == 3


def test_load_keeps_explicit_zero_and_no_zero_filter_remains():
    assert "Number(v) !== 0" not in EDITOR
    assert "roundGridHeights(data.gridCellHeights || {})" in EDITOR   # v6.10: rounded to 0.1 on load
    assert "if (mm === 0) continue" not in EDITOR


def test_painting_outside_the_grid_is_ignored():
    r = _run("""o.paintBegin({x:-3,y:-3,buttons:1}); o.paintMove({x:25,y:-1,buttons:1}); o.paintEnd();
      console.log(JSON.stringify({n:Object.keys(o.gridCellHeights).length, hist:o.undoHistory.length}));""",
             PAINT_METHODS)
    assert r == {"n": 0, "hist": 0}


# ───────────────────────────── undo ─────────────────────────────
def test_one_undo_reverts_whole_stroke_including_empty_cells():
    r = _run("""
      o.gridCellHeights = {380: 9, 382: 2};                    // two pre-existing cells under the stroke path (row 0 from top = idx 380..385)
      o.paintBrush = %d;                                        // +5
      o.paintBegin({x:.5,y:.5,buttons:1}); o.paintMove({x:5.5,y:.5,buttons:1}); o.paintEnd();
      const painted = {...o.gridCellHeights};
      o.undo();
      console.log(JSON.stringify({painted, back:o.gridCellHeights, hist:o.undoHistory.length, label:o.flashes.at(-1)}));""" % _delta_step(5),
             PAINT_METHODS)
    assert r["painted"] == {str(380 + c): 5 for c in range(6)}
    assert r["back"] == {"380": 9, "382": 2}                  # empty cells empty again, old values restored
    assert r["hist"] == 0 and r["label"].startswith("Undo paint stroke")


def test_eraser_stroke_undo_restores_deleted_values_and_noop_stroke_pushes_nothing():
    r = _run("""
      o.gridCellHeights = {380: 4, 381: 6};
      o.paintBrush = PAINT_BRUSH_ERASER;
      o.paintBegin({x:.5,y:.5,buttons:1}); o.paintMove({x:3.5,y:.5,buttons:1}); o.paintEnd();
      const erased = {...o.gridCellHeights}; const h1 = o.undoHistory.length;
      o.paintBegin({x:10.5,y:.5,buttons:1}); o.paintEnd();      // erasing empty cells changes nothing
      const h2 = o.undoHistory.length;
      o.undo();
      console.log(JSON.stringify({erased, h1, h2, back:o.gridCellHeights}));""",
             PAINT_METHODS)
    assert r["erased"] == {} and r["h1"] == 1 and r["h2"] == 1
    assert r["back"] == {"380": 4, "381": 6}


def test_unified_history_pops_in_chronological_order_across_grid_and_polygon_edits():
    r = _run("""
      o.polygons = [{name:'P', points:[{x:0,y:0}]}];
      const snap = () => JSON.stringify([o.polygons[0].points[0].x, JSON.stringify(o.gridCellHeights)]);
      const states = [snap()];
      o.pushUndo('move A');         o.polygons[0].points[0].x = 1;  states.push(snap());   // 1 poly
      o.gridUndoSnapshot([5], 'cell edit'); o.gridCellHeights[5] = 7; states.push(snap()); // 2 grid
      o.pushUndo('move B');         o.polygons[0].points[0].x = 2;  states.push(snap());   // 3 poly (does NOT wipe grid entry)
      o.gridUndoSnapshot([5, 6], 'set 2 cells'); o.gridCellHeights[5] = 9; o.gridCellHeights[6] = 3; states.push(snap()); // 4 grid
      const kinds = o.undoHistory.map(e => e.kind);
      const seen = [];
      for (let i = 0; i < 4; i++) { o.undo(); seen.push(snap()); }
      const extra = o.undo();
      console.log(JSON.stringify({states, kinds, seen, extra}));""",
             UNDO_METHODS)
    st = r["states"]
    assert r["kinds"] == ["poly", "grid", "poly", "grid"]
    assert r["seen"] == [st[3], st[2], st[1], st[0]]          # exactly the reverse chronological states
    assert r["extra"] is False


def test_polygon_redo_still_works_and_new_edit_clears_redo():
    r = _run("""
      o.polygons = [{name:'P', points:[{x:0,y:0}]}];
      o.pushUndo(); o.polygons[0].points[0].x = 5;
      o.undo(); const afterUndo = o.polygons[0].points[0].x; const canRedo = o.redoStack.length;
      o.redo(); const afterRedo = o.polygons[0].points[0].x; const histAfterRedo = o.undoHistory.length;
      o.undo();
      o.gridUndoSnapshot([1], 'cell edit');                    // a new edit invalidates redo
      console.log(JSON.stringify({afterUndo, canRedo, afterRedo, histAfterRedo, redoCleared:o.redoStack.length}));""",
             UNDO_METHODS)
    assert r == {"afterUndo": 0, "canRedo": 1, "afterRedo": 5, "histAfterRedo": 1, "redoCleared": 0}


def test_grid_cap_is_50_and_trims_only_grid_entries():
    assert C.value("GRID_UNDO_MAX_STEPS") == 50
    r = _run("""
      o.pushUndo('first poly');
      for (let i = 0; i < 55; i++) o.gridUndoSnapshot([i], 'g' + i);
      o.pushUndo('last poly');
      const labels = o.undoHistory.map(e => e.label);
      console.log(JSON.stringify({n:o.undoHistory.length, grid:o.undoHistory.filter(e=>e.kind==='grid').length,
        firstGrid:labels[1], lastGrid:labels[labels.length-2], polyKept:[labels[0], labels[labels.length-1]]}));""",
             UNDO_METHODS)
    assert r["grid"] == 50 and r["n"] == 52
    assert r["firstGrid"] == "g5" and r["lastGrid"] == "g54"        # oldest five dropped
    assert r["polyKept"] == ["first poly", "last poly"]


def test_polygon_cap_unchanged():
    r = _run("""for (let i = 0; i < 105; i++) o.pushUndo('p' + i);
      console.log(JSON.stringify({n:o.undoHistory.length, first:o.undoHistory[0].label}));""", UNDO_METHODS)
    assert r == {"n": 100, "first": "p5"}


def test_resolution_switch_drops_grid_entries_keeps_polygon_entries_in_order():
    r = _run("""
      o.window = {confirm: () => true}; globalThis.window = o.window;
      o.cancelGridRamp = () => {}; o.polygons = [{points:[{x:0,y:0}]}];
      o.pushUndo('A'); o.gridUndoSnapshot([1], 'g1'); o.pushUndo('B'); o.gridUndoSnapshot([2], 'g2');
      o.gridCellHeights = {1: 3};
      o.setGridResolution(40);
      console.log(JSON.stringify({labels:o.undoHistory.map(e => e.label), N:o.gridN, cells:o.gridCellHeights}));""", UNDO_METHODS)
    assert r["labels"] == ["A", "B"] and r["N"] == 40 and r["cells"] == {}


def test_undo_mode_change_consumes_entry_without_touching_cells():
    r = _run("""o.gridCellHeights = {1: 2}; o.gridUndoSnapshot([1], 'cell edit'); o.gridCellHeights[1] = 8;
      o.gridMode = 'absolute'; o.undo();
      console.log(JSON.stringify({h:o.gridCellHeights, n:o.undoHistory.length, f:o.flashes.at(-1)}));""", UNDO_METHODS)
    assert r["h"] == {"1": 8} and r["n"] == 0 and "mode changed" in r["f"]


def test_undo_key_uses_the_unified_undo():
    h = EDITOR[EDITOR.index("// Undo: Cmd+Z / Ctrl+Z"):][:800]
    assert "this.undo();" in h and "gridUndo" not in h
    assert "pushUndo()" not in _method("pushGridUndo")
    assert "_gridUndo" not in EDITOR and "this.undoStack" not in EDITOR


# ───────────────────────────── cursor ─────────────────────────────
def test_brush_cursor_hotspot_is_the_bristle_tip_and_fill_is_the_brush_color():
    r = _run("""
      const out = [];
      for (const step of [PALETTE_STEP_COUNT - 1, PALETTE_STEP_COUNT >> 1, 0]) {
        o.paintBrush = step; o.paintMode = true;
        out.push({step, css: o.paintCursorCss(), color: o.paletteColor(step)});
      }
      o.paintBrush = 4; o.applyPaintCursor(); const applied = o.$refs.canvas.style.cursor;
      o.exitPaintMode(); const restored = o.$refs.canvas.style.cursor;
      console.log(JSON.stringify({out, applied, restored, appliedColor:o.paletteColor(4)}));""", PAINT_METHODS)
    tipx, tipy = C.value("PAINT_CURSOR_TIP_X"), C.value("PAINT_CURSOR_TIP_Y")
    seen = set()
    for item in r["out"]:
        m = re.fullmatch(r'url\("data:image/svg\+xml;utf8,([^"]+)"\) (\d+) (\d+), (\w+)', item["css"])
        assert m, item["css"]
        svg = unquote(m.group(1))
        assert (int(m.group(2)), int(m.group(3))) == (tipx, tipy)               # hotspot = tip
        bristle = re.search(r'<path data-part="bristles" d="([^"]+)" fill="([^"]+)"', svg)
        assert bristle.group(2) == item["color"]                                 # bristle tip filled with the brush colour
        first = re.match(r"M(\d+) (\d+)", bristle.group(1))
        assert (int(first.group(1)), int(first.group(2))) == (tipx, tipy)       # path begins at the hotspot pixel
        size = C.value("PAINT_CURSOR_SIZE_PX")
        assert 0 <= tipx < size and 0 <= tipy < size
        seen.add(svg)
    assert len(seen) == 3                                                        # regenerated per brush
    assert unquote(re.search(r"utf8,([^\"]+)", r["applied"]).group(1)).count(r["appliedColor"]) == 1
    assert r["restored"] == "default"


def test_eraser_has_distinct_cursor_with_hotspot_on_its_working_edge():
    r = _run("""o.paintMode = true; o.paintBrush = PAINT_BRUSH_ERASER; const e = o.paintCursorCss();
      o.paintBrush = 3; console.log(JSON.stringify({e, b:o.paintCursorCss()}));""", PAINT_METHODS)
    m = re.fullmatch(r'url\("data:image/svg\+xml;utf8,([^"]+)"\) (\d+) (\d+), (\w+)', r["e"])
    hx, hy = int(m.group(2)), int(m.group(3))
    assert (hx, hy) == (C.value("ERASER_CURSOR_HOTSPOT_X"), C.value("ERASER_CURSOR_HOTSPOT_Y"))
    svg = unquote(m.group(1))
    assert 'data-part="eraser"' in svg and 'data-part="bristles"' not in svg and r["e"] != r["b"]
    d = re.search(r'data-part="eraser" d="M(\d+) (\d+) L(\d+) (\d+)', svg)
    x0, y0, x1, y1 = map(int, d.groups())
    assert ((x0 + x1) / 2, (y0 + y1) / 2) == (hx, hy)                            # midpoint of the eraser's working edge


def test_tee_hole_marker_not_draggable_in_paint_mode():
    assert "${paintMode ? 'pointer-events:none;' : ''}" in EDITOR


def test_edit_group_removed_but_keyboard_paths_remain():
    # v5.90: the Grid-row "Edit" group (Paint + Undo buttons) is gone; keyboard paths stay
    for gone in ('data-testid="paint-btn"', 'data-testid="undo-btn"', "TIP_PAINT_BTN",
                 ":disabled=\"!canUndo()\"", "undoTooltip", "canUndo"):
        assert gone not in EDITOR, gone
    assert not re.search(r'<span class="eb-cap">Edit</span>', EDITOR)
    for kept in ("togglePaintMode()", "exitPaintMode()", "undo()", "redo()", "setUiSubMode("):
        assert kept in EDITOR, kept
    assert "this.undo();" in EDITOR[EDITOR.index("// Undo: Cmd+Z / Ctrl+Z"):][:800]
    assert "this.togglePaintMode()" in _handle_key()


def test_two_brush_ramp_steps_by_the_palette_step_and_stores_half_values():
    lo, hi = _delta_step(1), _delta_step(3)     # +1 .. +3 mm over five cells -> 1, 1.5, 2, 2.5, 3
    r = _run("""console.log(JSON.stringify([0, 1, 2, 3, 4].map(k => paintBrushValue(rampStepAt(k, 5, %d, %d), 'delta'))));""" % (lo, hi))
    step = C.value("PALETTE_VALUE_STEP")
    assert r == [1 + k * step for k in range(5)] and any(v != int(v) for v in r)
