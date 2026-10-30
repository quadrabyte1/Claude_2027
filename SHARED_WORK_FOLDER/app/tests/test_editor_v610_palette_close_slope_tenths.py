"""Editor v6.10 regression tests.

1. Popup palette: each swatch prints its value inside the colour box, with light or dark text chosen from luminance.
2. Close Project button: flush autosave (await), warn + stay open on failure, then reset to the fresh-page state.
3. Slope (S) grades in SLOPE_VALUE_STEP (0.1) and fractional cell values work end to end (store, EGM round trip,
   colouring, value box, copy/paste, undo/redo, server 3MF pipeline).

Same technique as the other editor tests: the real constants block + the real methods are cut out of
templates/editor.html and run in node.  Every value comes from the editor's named constants.  No live DB.
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
sys.path.insert(0, str(APP_DIR))
import editor_constants as C
import test_editor_ui_mode2 as M2          # reuse its mock-editor harness (_run, STROKE, _go_paint ...)

node = shutil.which("node")
pytestmark = pytest.mark.skipif(not node, reason="node not installed")

STEP = C.value("SLOPE_VALUE_STEP")
DECIMALS = C.value("SLOPE_VALUE_DECIMALS")
LABEL_DECIMALS = C.value("GRID_LABEL_DECIMALS")
N = M2.N


def _js(script):
    out = subprocess.run([node, "-e", C.prelude() + "\n" + script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _method(name):
    m = re.search(r"\n    ((?:async )?%s\(.*?\n    \}),\n" % re.escape(name), EDITOR, re.S)
    assert m, name + " missing"
    return m.group(1)


def _is_tenth(v):
    return abs(v / STEP - round(v / STEP)) < 1e-9 and v == round(v, DECIMALS)


# ═════════════════════════ 1. popup palette: value inside each colour box ═════════════════════════
def _contrast(l1, l2):
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def test_popup_swatch_markup_prints_value_with_luminance_text_colour():
    i = EDITOR.index('data-testid="popup-swatch"')
    tag = EDITOR[i:EDITOR.index("</button>", i)]
    assert 'x-text="paletteLabel(step, gridMode)"' in tag        # same label format as the side palette
    assert "paletteTextColor(step)" in tag and "PALETTE_POPUP_LABEL_FONT_PX" in tag
    # colours are CSS custom properties, not literals
    assert C.value("PALETTE_TEXT_DARK_VAR") == "var(--editor-palette-text-dark)"
    assert C.value("PALETTE_TEXT_LIGHT_VAR") == "var(--editor-palette-text-light)"
    assert "--editor-palette-text-dark:" in EDITOR and "--editor-palette-text-light:" in EDITOR


def test_every_swatch_text_is_legible_and_the_better_of_dark_and_light():
    r = _js("""
const stops = CELL_COLOR_STOPS.map(h => [1, 3, 5].map(o => parseInt(h.substr(o, 2), 16)));
console.log(JSON.stringify(stops.map(rgb => ({lum: relativeLuminance(rgb), pick: paletteTextVar(rgb)}))));
""")
    dark_lum = relativeLuminance_hex("#000000")
    light_lum = relativeLuminance_hex("#ffffff")
    assert len(r) == len(C.value("CELL_COLOR_STOPS"))
    assert {x["pick"] for x in r} == {C.value("PALETTE_TEXT_DARK_VAR"), C.value("PALETTE_TEXT_LIGHT_VAR")}   # both tones are used
    for x in r:
        text = dark_lum if x["pick"] == C.value("PALETTE_TEXT_DARK_VAR") else light_lum
        assert _contrast(x["lum"], text) >= 4.5                 # WCAG AA on every swatch


def relativeLuminance_hex(h):
    ch = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def test_threshold_flips_text_tone():
    r = _js("console.log(JSON.stringify([paletteTextVar([255,255,255]), paletteTextVar([0,0,0])]));")
    assert r == [C.value("PALETTE_TEXT_DARK_VAR"), C.value("PALETTE_TEXT_LIGHT_VAR")]


def test_popup_swatch_is_wide_enough_for_the_longest_label():
    # longest label: "+15" / "-15" at the label font; ~0.62 em per glyph (tabular digits) + borders
    longest = max(len(x) for x in _js("""console.log(JSON.stringify(paletteSteps().map(s => paletteLabel(s, 'delta'))));"""))
    need = longest * C.value("PALETTE_POPUP_LABEL_FONT_PX") * 0.62 + 2
    assert C.value("PALETTE_POPUP_SWATCH_PX") >= need


# ═════════════════════════ 2. Close Project ═════════════════════════
CLOSE_METHODS = ["hasOpenProject", "closeProject", "clearEditorState", "exitPaintMode", "m2Cancel", "closePaintPopup",
                 "slopeCancel"]


def _close_run(script, outcome=C.value("AUTOSAVE_SAVED"), confirm=True, extra=""):
    body = ",\n".join(_method(n) for n in CLOSE_METHODS)
    js = C.prelude() + """
const calls = [];
const loc = {href: 'http://localhost:5051/editor?egm=%%2Ftmp%%2Fa.egm&image=x.png#h'};
globalThis.window = {location: loc, history: {state: null, replaceState(st, t, u) { calls.push(['replace', u]); }},
  confirm(m) { calls.push(['confirm', m]); return %s; }, addEventListener() {}, removeEventListener() {}};
const o = {
  selectedImage: 'x.png', selectedImageUrl: 'u', selectedImageCourse: 'c', egmPath: '/tmp/a.egm', img: {}, imgLoaded: true,
  imgW: 10, imgH: 10, courseName: 'Course', holeName: '7', polygons: [{type: 'green', points: []}], contours: [{}],
  selectedPoly: 1, selectedVerts: [{poly: 0, idx: 1}], _pendingRestore: {}, undoHistory: [{}], redoStack: [{}],
  contourStep: 99, grassAmplitude: 99, grassSpacing: 99, greenStyle: 'x', elevationRange: 99, zScale: 99, greenScale: 99,
  fringeEdgeHeight: 99, baseThicknessMm: 99, includeBoundaryRegion: true, applyFringeFrameCap: false,
  includeFringeWithoutGrass: true, flagOffsetXMm: 99, flagOffsetYMm: 99, teeHole: {x_mm: 1, y_mm: 2},
  gpsEnabled: true, gpsFile: 'f', gpsBbox: {}, gpsVertExag: 9, gpsApproachM: 9, gpsGridSize: 9, courseGeoRef: {},
  gpsPreviewDataUrl: 'd', gpsPreviewError: 'e', gpsPreviewNotes: ['n'],
  gridCellHeights: {3: 1.2}, gridMode: 'absolute', gridN: 40, _gridMultiSelect: new Set([1]), _gridRampMode: true,
  _gridMultiSelectAnchor: 1, _gridActiveCell: {idx: 3}, _gridInputValue: '1', _gridHoveredCell: {}, _gridMouseDownAt: {},
  _pendingAutoSave: true, paintMode: true, paintBrush: 3, paintBrush2: 4, uiSubMode: UI_SUB_PAINT, paintPopup: {open: true, x: 1, y: 2},
  _slope: {phase: 'second'}, _m2: {kind: 'slope'}, _paintStroke: null, selectedContour: 2, contourMode: true, contourDraft: [1],
  degridUrls: {}, _imgSrcKey: 'k', imageView: DEGRID_VIEW_HIDE, _pendingDetect: true, _pendingDegrid: true,
  showNewDialog: true, showOpenDialog: true, selectedOpenProject: {}, initialEgmPath: '/tmp/a.egm', lassoPts: null, rubberBand: false,
  $refs: {canvas: {style: {cursor: 'x'}, width: 5, height: 5, getContext() { return {clearRect() { calls.push(['clear']); }}; }}},
  flashes: [], flash(m, ok) { this.flashes.push([m, ok]); }, flashDismiss() {}, applyPaintCursor() {}, saves: 0,
  async autoSave() { calls.push(['autoSave']); return %s; }, draw() {},
};
const M = {%s};
for (const k in M) Object.defineProperty(o, k, Object.getOwnPropertyDescriptor(M, k));
%s
""" % (json.dumps(confirm).lower(), json.dumps(outcome), body, extra)
    out = subprocess.run([node, "-e", js + "\n(async () => {" + script + "})();"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


STATE_DUMP = """console.log(JSON.stringify({res, calls, flashes: o.flashes,
  s: {img: o.selectedImage, loaded: o.imgLoaded, course: o.courseName, hole: o.holeName, polys: o.polygons.length,
      contours: o.contours.length, undo: o.undoHistory.length, redo: o.redoStack.length, verts: o.selectedVerts.length,
      grid: o.gridCellHeights, mode: o.gridMode, n: o.gridN, multi: o._gridMultiSelect, active: o._gridActiveCell,
      contourStep: o.contourStep, zScale: o.zScale, tee: o.teeHole, egm: o.egmPath, init: o.initialEgmPath,
      paint: o.paintMode, slope: o._slope, popup: o.paintPopup.open, brush2: o.paintBrush2, sub: o.uiSubMode,
      view: o.imageView, dlg: [o.showNewDialog, o.showOpenDialog], open: o.hasOpenProject()}}));"""


def test_close_button_markup_is_a_sibling_of_new_and_open_with_the_named_label():
    assert C.value("LABEL_CLOSE_PROJECT") == "Close Project"
    i = EDITOR.index('data-testid="close-project"')
    tag = EDITOR[EDITOR.rindex("<button", 0, i):EDITOR.index("</button>", i)]
    assert 'closeProject()' in tag and ':disabled="!hasOpenProject()"' in tag and 'x-text="LABEL_CLOSE_PROJECT"' in tag
    bar = EDITOR[EDITOR.index('@click="openNewProjectDialog()"'):i]
    assert '@click="openProjectDialog()"' in bar and "</div>" not in bar          # same action bar, after New + Open
    k = EDITOR.index('@click="openProjectDialog()"')
    open_btn = EDITOR[EDITOR.rindex("<button", 0, k):EDITOR.index("</button>", k)]
    cls = lambda t: re.search(r'class="([^"]*)"', t).group(1)
    assert set(cls(open_btn).split()) <= set(cls(tag).split())            # matching style (plus the disabled look)


def test_close_flushes_autosave_then_resets_to_fresh_state_and_strips_url():
    r = _close_run("const res = await o.closeProject();" + STATE_DUMP)
    assert r["res"] is True
    assert [c[0] for c in r["calls"]][0] == "autoSave"                  # flushed FIRST
    s = r["s"]
    assert (s["img"], s["loaded"], s["course"], s["hole"], s["polys"], s["contours"]) == ("", False, "", "", 0, 0)
    assert (s["undo"], s["redo"], s["verts"], s["grid"], s["multi"], s["active"], s["egm"], s["init"]) == (0, 0, 0, {}, None, None, "", "")
    assert s["contourStep"] == C.value("DEFAULT_CONTOUR_STEP_MM") and s["zScale"] == C.value("DEFAULT_Z_SCALE")   # Options reset
    assert s["tee"] is None and s["n"] == C.value("GRID_N_DEFAULT") and s["mode"] == C.value("DEFAULT_GRID_MODE")
    assert (s["paint"], s["slope"], s["popup"], s["brush2"], s["sub"]) == (False, None, False, None, C.value("DEFAULT_UI_SUB_MODE"))
    assert s["view"] == C.value("DEGRID_VIEW_CLEAN") and s["dlg"] == [False, False] and s["open"] is False
    assert ["clear"] in r["calls"]                                       # canvas cleared
    url = [c[1] for c in r["calls"] if c[0] == "replace"][0]
    assert C.value("QUERY_PARAM_EGM") not in url and "image=" not in url and url.startswith("/editor") and url.endswith("#h")
    assert not [c for c in r["calls"] if c[0] == "confirm"]              # autosave covers it: no dialog
    assert r["flashes"][-1][0] == C.value("MSG_CLOSED_PROJECT")


def test_close_does_nothing_when_no_project_is_open():
    r = _close_run("""o.selectedImage = ''; o.imgLoaded = false; o.courseName = ''; o.holeName = ''; o.polygons = [];
      const res = await o.closeProject();""" + STATE_DUMP)
    assert r["res"] is False and r["calls"] == [] and r["s"]["open"] is False   # button is disabled by hasOpenProject()


def test_close_with_failed_save_warns_and_keeps_project_open():
    r = _close_run("const res = await o.closeProject();" + STATE_DUMP, outcome=C.value("AUTOSAVE_FAILED"))
    assert r["res"] is False and r["s"]["polys"] == 1 and r["s"]["grid"] == {"3": 1.2} and r["s"]["course"] == "Course"
    assert r["flashes"][-1] == [C.value("MSG_CLOSE_SAVE_FAILED"), False]
    assert not [c for c in r["calls"] if c[0] == "replace"]


def test_close_with_deferred_save_asks_first():
    skipped = C.value("AUTOSAVE_SKIPPED")
    no = _close_run("const res = await o.closeProject();" + STATE_DUMP, outcome=skipped, confirm=False)
    assert no["res"] is False and no["s"]["polys"] == 1
    assert ["confirm", C.value("MSG_CLOSE_UNSAVED_CONFIRM")] in no["calls"]
    yes = _close_run("const res = await o.closeProject();" + STATE_DUMP, outcome=skipped, confirm=True)
    assert yes["res"] is True and yes["s"]["polys"] == 0


def test_autosave_reports_saved_failed_skipped():
    src = _method("autoSave")
    assert "return AUTOSAVE_SKIPPED" in src and "return AUTOSAVE_SAVED" in src and "return AUTOSAVE_FAILED" in src
    assert "resp.ok === false" in src            # HTTP error status is a failure, not a silent success


# ═════════════════════════ 3. Slope in tenths + fractional values end to end ═════════════════════════
def test_slope_constants():
    assert STEP == 0.1 and DECIMALS == 1 and STEP * 10 ** DECIMALS == 1


def test_ramp_value_is_in_tenths_without_float_noise():
    r = _js("""const n = 41; console.log(JSON.stringify(Array.from({length: n}, (_, k) => rampValueAt(k, n, 1, 5))));""")
    assert r[0] == 1.0 and r[-1] == 5.0 and r == sorted(r)
    assert all(_is_tenth(v) for v in r)
    assert r[1] == 1.1 and r[2] == 1.2 and r[3] == 1.3            # 1.0, 1.1, 1.2, 1.3 ...
    assert not any(len(repr(v)) > 5 for v in r)                    # never 1.2000000000000002
    assert _js("console.log(JSON.stringify([rampValueAt(0, 1, 6.2, 9)]));") == [6.2]


def test_slope_fill_values_pure_function_gives_fractions():
    out = _js("""
const A = [{u: 1, v: 3.5}, {u: 12, v: 3.5}], B = [{u: 1, v: 9.5}, {u: 12, v: 9.5}];
const r = slopeFillValues(A, B, 0, 1, %d).map(e => e[1]);
console.log(JSON.stringify(r));""" % N)
    assert min(r for r in out) == 0 and max(out) == 1
    assert any(0 < v < 1 for v in out) and all(_is_tenth(v) for v in out)
    assert len(set(out)) <= 11                                     # at most 0.0 .. 1.0 in tenths


def test_slope_command_stores_tenths_and_undo_redo_roundtrips():
    out = M2._run(M2._go_paint() + M2.STROKE + """
o.m2HandleKey(key(SLOPE_KEY));
pick(15); stroke(2, 2, 14); pick(16); stroke(8, 2, 14);                   // brush values 0 -> +1 over 7 rows
const col = [2, 3, 4, 5, 6, 7, 8].map(j => val(6, j));
const snap = JSON.stringify(o.gridCellHeights);
o.handleKey(key('z', {metaKey: true})); const afterUndo = Object.keys(o.gridCellHeights).length;
o.handleKey(key('z', {metaKey: true, shiftKey: true})); const afterRedo = JSON.stringify(o.gridCellHeights);
console.log(JSON.stringify({col, undoN: o.undoHistory.length, afterUndo, same: afterRedo === snap || afterRedo === '{}'}));
""")
    col = out["col"]
    assert col[0] == 0 and col[-1] == 1 and col == sorted(col)
    assert any(0 < v < 1 for v in col) and all(_is_tenth(v) for v in col)   # fractional values were stored
    assert out["afterUndo"] == 0


def test_cell_edit_store_rounds_and_value_text_has_one_decimal():
    r = _js("""
const o = {gridMode: 'delta', gridCellHeights: {}, undoHistory: [], redoStack: [], saves: 0, maxUndo: 100,
  pushGridUndo() {}, draw() {}, autoSave() { this.saves++; }};
o._m2ApplyCells = %s;
o._m2ApplyCells([[1, 1.2000000000000002], [2, 0.30000000000000004], [3, 2]], 'x');
console.log(JSON.stringify({cells: o.gridCellHeights, txt: [gridValueText(1.2), gridValueText(2), gridValueText(-0.05), gridValueText('1.25')]}));
""" % ("function" + _method("_m2ApplyCells")[len("_m2ApplyCells"):]))
    assert r["cells"] == {"1": 1.2, "2": 0.3, "3": 2}
    assert r["txt"][0] == "%.*f" % (LABEL_DECIMALS, 1.2) and r["txt"][1] == "%.*f" % (LABEL_DECIMALS, 2)


def test_value_box_and_commit_use_one_decimal_and_round_on_store():
    body = ",\n".join(_method(n) for n in ["openGridCell", "commitGridCell", "_untouchedExplicitZero", "gridUndoSnapshot", "pushGridUndo", "_trimUndo"])
    r = _js("""
const o = {gridMode: 'delta', gridCellHeights: {5: 1.2, 6: 3}, undoHistory: [], redoStack: [], maxUndo: 100, saves: 0, _wheelAcc: 0,
  _gridActiveCell: null, _gridInputValue: '', _gridMultiSelect: null, _gridMultiSelectAnchor: null, _gridHoveredCell: null,
  $refs: {}, $nextTick() {}, draw() {}, autoSave() { this.saves++; }, _gridCellCanvasPx() { return {}; }, flash() {},
  %s };
o.openGridCell(1, 1, 5); const box5 = o._gridInputValue;
o.cancelGridCell = function () {};
o.openGridCell(1, 1, 6); const box6 = o._gridInputValue;
o._gridActiveCell = {idx: 7}; o._gridInputValue = '1.2000000000000002'; o.commitGridCell();
console.log(JSON.stringify({box5, box6, stored: o.gridCellHeights[7]}));
""" % body)
    assert r["box5"] == "%.*f" % (LABEL_DECIMALS, 1.2) and r["box6"] == "%.*f" % (LABEL_DECIMALS, 3)
    assert r["stored"] == 1.2


def test_egm_save_and_load_round_trip_without_truncation_or_noise():
    r = _js("""
const stored = {3: 1.2, 4: 1.2000000000000002, 5: 0, 6: -3.3, 7: 2};
const saved = JSON.stringify(roundGridHeights(stored));
const loaded = roundGridHeights(JSON.parse(saved));
console.log(JSON.stringify({saved, loaded, legacy: roundGridHeights({1: 4, 2: '2.5'}), none: roundGridHeights(undefined)}));
""")
    assert r["loaded"] == {"3": 1.2, "4": 1.2, "5": 0, "6": -3.3, "7": 2}      # explicit 0 kept, no truncation to int
    assert "00000" not in r["saved"]
    assert r["legacy"] == {"1": 4, "2": 2.5} and r["none"] == {}
    assert "roundGridHeights(this.gridCellHeights)" in EDITOR                     # used by autoSave
    assert "roundGridHeights(data.gridCellHeights || {})" in EDITOR               # used by loadProject


def test_cell_colour_interpolates_continuously_for_fractional_values():
    body = _method("cellColorAt") + ",\n" + _method("cellColorRgb")
    r = _js("""
const o = {%s};
const rng = {min: CELL_COLOR_DELTA_MIN_MM, max: CELL_COLOR_DELTA_MAX_MM};
console.log(JSON.stringify([o.cellColorRgb(1, rng), o.cellColorRgb(1.1, rng), o.cellColorRgb(1.5, rng), o.cellColorRgb(2, rng)]));
""" % body)
    a, b, mid, c = r
    assert a != b != c and mid != a and mid != c                    # a tenth of a mm moves the colour; halfway sits between
    for ch in range(3):
        assert min(a[ch], c[ch]) <= mid[ch] <= max(a[ch], c[ch])


def test_copy_paste_keeps_fractional_values_and_rounds_pasted_noise():
    r = _js("""
const heights = {10: 1.2, 11: 0, 12: 2.5};
const pat = gridClipBuild([10, 11, 12, 13], 12, heights, 20);
const parsed = gridClipParse(JSON.stringify(pat));
console.log(JSON.stringify(gridClipTargets(parsed, 105, 20).map(t => t[1])));
""")
    assert r == [1.2, 0, 2.5, None]
    paste = _method("applyGridPattern")
    assert "roundMm(" in paste                                       # clipboard text from outside is rounded on store


def test_label_hover_and_canvas_use_the_same_one_decimal_formatter():
    assert "gridValueText(gridCellHeights[_gridHoveredCell.idx])" in EDITOR       # hover tooltip
    assert "mmVal.toFixed(GRID_LABEL_DECIMALS)" in EDITOR                          # canvas label (same constant)


# ----- server: the 3MF pipeline takes fractional Z (no int() / integer indexing on cell values) -----
def _server():
    import test_tps_global_height_field_task704 as T
    return T


def test_server_tps_grid_field_honours_a_tenth_of_a_mm():
    import numpy as np
    T = _server()
    gsd = T._load_gsd()
    cx, cy, r = 300.0, 300.0, 105.0
    half = gsd.FRINGE_HALF_MM
    GX, GY = np.meshgrid(np.linspace(-half, half, 50), np.linspace(-half, half, 50))

    def field(v):
        egm = T._base_egm(cx, cy, r, grid_cell_heights={"210": v})
        pts = gsd.interpolate_catmull_rom(egm["polygons"][0]["points"])
        bnd = gsd._px_to_mm_2d(pts.copy(), *gsd._compute_px_to_mm(
            np.array([(p["x"], p["y"]) for p in egm["polygons"][0]["points"]], dtype=np.float64), egm))
        return gsd._build_tps_grid_height_field(egm_data=egm, green_bnd_mm=bnd, bnd_z=np.full(len(bnd), 3.0), grid_x=GX, grid_y=GY)

    d = float(np.max(field(1.3) - field(1.0)))
    assert 0.2 < d <= 1.3 - 1.0 + 1e-6          # an int() cast would give 0 (1.3 -> 1)


def test_server_bunker_cell_helpers_keep_fractional_values():
    gsd = _server()._load_gsd()
    from shapely.geometry import box
    half, n = gsd.FRINGE_HALF_MM, 20
    side = 2.0 * half / n
    trap = box(-half, -half, -half + 3 * side, -half + 3 * side)          # covers cells 0..2 of rows 0..2
    got = dict(gsd._trap_inside_cells(trap, {"0": 1.3, "21": 0.7, "399": 5.5}, side, half, n))
    assert got == {0: 1.3, 21: 0.7}
