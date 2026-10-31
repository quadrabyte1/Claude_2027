"""Editor v6.17 regression tests.

1. Side-palette colour boxes are 30% shorter (PALETTE_SWATCH_HEIGHT_SCALE).
2. Click a numeric label on the side palette -> type ANY brush value (3.77); validation, cancel, readout, no swatch selected.
3. Cell values are stored to GRID_VALUE_STORE_STEP (0.01): paint, EGM round trip, value text, slope still in tenths, server 3MF pipeline.

Same technique as the other editor tests (real constants block + real methods run in node; every value read from the
editor's named constants).  No server, no live DB.
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
import test_editor_ui_mode2 as M2

node = shutil.which("node")
pytestmark = pytest.mark.skipif(not node, reason="node not installed")

M2.METHODS.extend(["onPaletteLabelMouseDown", "cancelPaletteCustom", "commitPaletteCustom"])
STORE = C.value("GRID_VALUE_STORE_STEP")
SCALE = C.value("PALETTE_SWATCH_HEIGHT_SCALE")
RANGE_FMT = C.value("MSG_PALETTE_CUSTOM_RANGE_FMT")
D_MIN, D_MAX = C.value("CELL_COLOR_DELTA_MIN_MM"), C.value("CELL_COLOR_DELTA_MAX_MM")
A_MIN, A_MAX = C.value("CELL_COLOR_ABSOLUTE_MIN_MM"), C.value("CELL_COLOR_ABSOLUTE_MAX_MM")
CUSTOM = 3.77


def _js(script):
    out = subprocess.run([node, "-e", C.prelude() + "\n" + script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _err(lo, hi):
    return RANGE_FMT.replace("{min}", str(lo)).replace("{max}", str(hi))


# harness: a mock editor with the custom-box state, driven through the real methods
BOX = """
o.paletteCustom = {open: false, text: '', error: '', top: 0};
o.$refs.paintPalette = {getBoundingClientRect() { return {top: 0}; }};
o.$refs.paletteCustomInput = {focus() {}, select() {}};
o.$nextTick = (f) => f();
const labelDown = (step, kw = {}) => o.onPaletteLabelMouseDown(step, Object.assign({button: BTN_L, preventDefault() {},
  currentTarget: {getBoundingClientRect() { return {top: 5}; }}}, kw));
const typeEnter = (t, kw) => { o.paletteCustom.text = t; o.commitPaletteCustom(ev(0, 0, kw)); };
"""


def _run(script, mode="delta"):
    return M2._run(M2._go_paint() + M2.STROKE + BOX + "o.gridMode = %s;\n" % json.dumps(mode) + script)


# ═════════════════════ 1. swatch height ═════════════════════
def test_swatch_height_constants_scaled_by_named_factor():
    assert SCALE == 0.7
    base_max, base_min = C.value("PALETTE_SWATCH_BASE_MAX_PX"), C.value("PALETTE_LABEL_BASE_MIN_EDGE_PX")
    assert C.value("PALETTE_SWATCH_MAX_PX") == int(base_max * SCALE)
    assert C.value("PALETTE_LABEL_MIN_EDGE_PX") == int(base_min * SCALE)
    assert C.value("PALETTE_SWATCH_WIDTH_PX") > C.value("PALETTE_SWATCH_MAX_PX")      # still landscape
    assert C.value("PALETTE_LABEL_MIN_EDGE_PX") >= 5                                  # still clickable


def test_swatch_height_is_30_percent_shorter_at_every_viewport():
    old_h = lambda vh: max(C.value("PALETTE_LABEL_BASE_MIN_EDGE_PX"), min(C.value("PALETTE_SWATCH_BASE_MAX_PX"),
        (vh - C.value("PALETTE_VIEWPORT_RESERVE_PX") - C.value("PALETTE_ERASER_ROW_EXTRA_PX")) // (C.value("PALETTE_STEP_COUNT") + 1)))
    vhs = [400, 900, 1400, 2000]
    got = {h: v for h, v in _js("console.log(JSON.stringify(%s.map(h => [h, paletteSwatchHeight(h)])));" % vhs)}
    for vh in vhs:
        assert got[vh] <= round(old_h(vh) * SCALE + 1) and got[vh] >= C.value("PALETTE_LABEL_MIN_EDGE_PX")
    assert got[1400] == C.value("PALETTE_SWATCH_MAX_PX") and got[900] < old_h(900)


def test_label_font_fits_two_rows_so_whole_step_labels_cannot_overlap():
    # labels sit on every 2nd row (whole mm of 0.5 steps): pitch = 2 rows >= the label font
    assert 2 * C.value("PALETTE_LABEL_MIN_EDGE_PX") >= C.value("PALETTE_LABEL_FONT_PX")


# ═════════════════════ 2. label click -> custom value box ═════════════════════
def test_label_markup_opens_box_and_does_not_select_swatch():
    i = EDITOR.index('data-testid="palette-label"')
    tag = EDITOR[i:EDITOR.index("</span>", i)]
    assert '@mousedown.stop="onPaletteLabelMouseDown(step, $event)"' in tag and "@click.stop" in tag
    assert 'data-testid="palette-custom-input"' in EDITOR and "@keydown.escape" in EDITOR and "@blur=\"cancelPaletteCustom()\"" in EDITOR
    assert "isCustomBrush(paintBrush)" in EDITOR                      # readout


def test_label_click_opens_box_prefilled_and_leaves_brush_alone():
    r = _run("""
const before = o.paintBrush; const step = %d;
labelDown(step);
console.log(JSON.stringify({open: o.paletteCustom.open, text: o.paletteCustom.text, brush: o.paintBrush === before, top: o.paletteCustom.top}));
""" % (3 - D_MIN) if False else """
const before = o.paintBrush; const step = customBrushStep(3, 'delta');
labelDown(step);
console.log(JSON.stringify({open: o.paletteCustom.open, text: o.paletteCustom.text, same: o.paintBrush === before}));
""")
    assert r == {"open": True, "text": "3", "same": True}


def test_unlabelled_half_step_does_not_open_box():
    r = _run("labelDown(customBrushStep(3.5, 'delta')); console.log(JSON.stringify(o.paletteCustom.open));")
    assert r is False


@pytest.mark.parametrize("text,value", [("3.77", 3.77), ("-15", -15), ("15", 15), ("+2", 2), ("0", 0), ("  .5 ", 0.5), ("-0.01", -0.01)])
def test_valid_values_set_brush_exactly(text, value):
    r = _run("""
labelDown(customBrushStep(3, 'delta')); typeEnter(%s);
console.log(JSON.stringify({v: o.paintBrushValueNow(), open: o.paletteCustom.open, err: o.paletteCustom.error, mode: o.uiSubMode, brush2: o.paintBrush2}));
""" % json.dumps(text))
    assert r["v"] == value and r["open"] is False and r["err"] == "" and r["brush2"] is None
    assert r["mode"] == M2.SUB_P


@pytest.mark.parametrize("text", ["abc", "", "   ", "15.01", "-16", "1.2.3", "Infinity", "-Infinity", "NaN", "1e1", "--2", "3,5", "0x10", "+"])
def test_invalid_values_rejected_with_error_and_brush_unchanged(text):
    r = _run("""
const b0 = o.paintBrush; labelDown(customBrushStep(3, 'delta')); typeEnter(%s);
console.log(JSON.stringify({same: o.paintBrush === b0, open: o.paletteCustom.open, err: o.paletteCustom.error}));
""" % json.dumps(text))
    assert r == {"same": True, "open": True, "err": _err(D_MIN, D_MAX)}


def test_absolute_mode_uses_its_own_range():
    ok = _run("labelDown(customBrushStep(10, 'absolute')); typeEnter('29.99'); console.log(JSON.stringify(o.paintBrushValueNow()));", "absolute")
    assert ok == 29.99
    bad = _run("labelDown(customBrushStep(10, 'absolute')); typeEnter('-1'); console.log(JSON.stringify(o.paletteCustom.error));", "absolute")
    assert bad == _err(A_MIN, A_MAX)
    assert _run("typeEnter('30'); console.log(JSON.stringify(o.paintBrushValueNow()));", "absolute") == A_MAX


def test_esc_and_blur_cancel_without_changing_brush():
    r = _run("""
const b0 = o.paintBrush; labelDown(customBrushStep(3, 'delta')); o.paletteCustom.text = '7.7'; o.cancelPaletteCustom();
console.log(JSON.stringify({open: o.paletteCustom.open, same: o.paintBrush === b0}));
""")
    assert r == {"open": False, "same": True}
    assert "@keydown.escape.prevent.stop=\"cancelPaletteCustom()\"" in EDITOR and "@mousedown.window=\"cancelPaletteCustom()\"" in EDITOR


def test_cursor_takes_cell_colour_of_value_and_no_swatch_is_selected():
    r = _run("""
labelDown(customBrushStep(3, 'delta')); typeEnter('3.77');
const css = o.paintCursorCss(), exp = o.paletteColor(o.paintBrush);
const swatchSteps = Array.from({length: PALETTE_STEP_COUNT}, (_, s) => s);
console.log(JSON.stringify({custom: isCustomBrush(o.paintBrush), anyHit: swatchSteps.some(s => o.paintBrush === s),
  colour: exp, cursorHasColour: decodeURIComponent(css).includes(exp.replace(/ /g, '')) || decodeURIComponent(css).includes(exp)}));
""")
    assert r["custom"] and not r["anyHit"] and r["cursorHasColour"]
    # the colour is between the 3.5 and 4 swatch colours' scale position (cellColorAt of the fractional step)
    r2 = _run("labelDown(customBrushStep(3,'delta')); typeEnter('3.77'); console.log(JSON.stringify([o.paletteColor(customBrushStep(3.5,'delta')), o.paletteColor(o.paintBrush), o.paletteColor(customBrushStep(4,'delta'))]));")
    assert len(set(r2)) == 3


def test_whole_and_half_values_select_the_matching_swatch_and_show_no_readout():
    r = _run("labelDown(customBrushStep(3, 'delta')); typeEnter('4.5'); console.log(JSON.stringify([o.paintBrush, isCustomBrush(o.paintBrush)]));")
    assert r == [C.value("PALETTE_STEP_COUNT") and round((4.5 - D_MIN) / C.value("PALETTE_VALUE_STEP")), False]


def test_picking_a_swatch_returns_to_normal_brushes():
    r = _run("labelDown(customBrushStep(3,'delta')); typeEnter('3.77'); pick(10); console.log(JSON.stringify([o.paintBrush, isCustomBrush(o.paintBrush)]));")
    assert r == [10, False]


def test_shortcut_keys_do_not_fire_while_typing_in_the_box():
    r = _run("""
labelDown(customBrushStep(3, 'delta'));
const consumed = ['g', 'b', 's', 'p'].map(k => o.handleKey(key(k, {target: {tagName: 'INPUT'}})));
console.log(JSON.stringify({consumed, slope: o._slope, sub: o.uiSubMode}));
""")
    assert not any(r["consumed"]) and r["slope"] is None and r["sub"] == M2.SUB_P


# ═════════════════════ B paint / Slope / two-brush ramp ═════════════════════
def test_painting_with_custom_brush_stores_exact_value_and_undo_clears_it():
    r = _run("""
labelDown(customBrushStep(3, 'delta')); typeEnter('3.77');
drag([cellXY(4, 4), cellXY(5, 4)]);
const stored = [val(4, 4), val(5, 4)]; o.handleKey(key('z', {metaKey: true}));
console.log(JSON.stringify({stored, afterUndo: Object.keys(o.gridCellHeights).length, text: gridValueText(stored[0])}));
""")
    assert r["stored"] == [CUSTOM, CUSTOM] and r["afterUndo"] == 0 and r["text"] == "3.77"


def test_slope_accepts_custom_value_as_a_boundary_and_still_grades_in_tenths():
    r = _run("""
o.m2HandleKey(key(SLOPE_KEY));
labelDown(customBrushStep(3, 'delta')); typeEnter('3.77');           // boundary A = 3.77 (via the custom path)
stroke(2, 2, 14); pick(customBrushStep(8, 'delta')); stroke(8, 2, 14);
const col = [2, 3, 4, 5, 6, 7, 8].map(j => val(6, j));
console.log(JSON.stringify(col));
""")
    assert r[0] == CUSTOM and r[-1] == 8
    inner = r[1:-1]
    assert all(abs(v / C.value("SLOPE_VALUE_STEP") - round(v / C.value("SLOPE_VALUE_STEP"))) < 1e-9 for v in inner)   # tenths
    assert r == sorted(r)


def test_two_brush_ramp_keeps_custom_end_exact_and_interior_on_palette_steps():
    r = _run("""
pick(customBrushStep(0, 'delta'));                                         // brush 1 = 0
labelDown(customBrushStep(3, 'delta')); typeEnter('3.77', {metaKey: true});  // Cmd+Enter -> brush 2 = 3.77
const cells = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map(i => cellXY(i, 4));
drag(cells);
console.log(JSON.stringify({b2: o.paintBrush2, vals: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map(i => val(i, 4))}));
""")
    assert r["b2"] is not None
    v = r["vals"]
    assert v[0] == 0 and v[-1] == CUSTOM and v == sorted(v)
    assert all(abs(x / C.value("PALETTE_VALUE_STEP") - round(x / C.value("PALETTE_VALUE_STEP"))) < 1e-9 for x in v[:-1])


# ═════════════════════ 3. precision ═════════════════════
def test_store_step_constants():
    assert STORE == 0.01 and C.value("GRID_VALUE_STORE_DECIMALS") == 2
    assert C.value("SLOPE_VALUE_STEP") == 0.1                       # slope unchanged
    assert C.value("PALETTE_VALUE_STEP") == 0.5


@pytest.mark.parametrize("v,txt", [(3.77, "3.77"), (2.5, "2.5"), (2, "2.0"), (0, "0.0"), (-1.05, "-1.05"), (1.2000000000000002, "1.2"), (3.7, "3.7"), (-15, "-15.0")])
def test_value_text_up_to_two_decimals_without_noise(v, txt):
    assert _js("console.log(JSON.stringify(gridValueText(%r)));" % v) == txt


RAMP_FN = re.search(r"\nfunction gridRampAssign\(.*?\n\}\n", EDITOR, re.S).group(0)


def test_stores_round_to_two_decimals_everywhere():
    r = _js(RAMP_FN + """
console.log(JSON.stringify({a: roundGridValue(3.774), b: roundGridValue(3.775), c: roundGridValue(1.2000000000000002),
  egm: roundGridValue(Number('3.77')), heights: roundGridHeights({5: 3.77, 6: 2.5, 7: 0, 8: 0.30000000000000004}),
  ramp: gridRampAssign([1, 2, 3], 3.77, 5.5, 'delta').map(e => e[1])}));
""")
    assert r["a"] == 3.77 and r["c"] == 1.2
    assert r["heights"] == {"5": 3.77, "6": 2.5, "7": 0, "8": 0.3}
    assert r["ramp"][0] == 3.77 and r["ramp"][-1] == 5.5


def test_cell_value_box_commit_and_paste_keep_two_decimals():
    r = _js("""
const o = {gridMode: 'delta', gridCellHeights: {}, _gridActiveCell: {idx: 4}, _gridInputValue: '3.77', _gridMultiSelect: null,
  _gridMultiSelectAnchor: null, undoHistory: [], redoStack: [], maxUndo: 100, gridUndoSnapshot() {}, _untouchedExplicitZero() { return false; },
  cancelGridCell() {}, draw() {}, autoSave() {}};
o.commitGridCell = %s;
o.commitGridCell();
const t = gridClipTargets(gridClipParse(JSON.stringify(gridClipBuild([10], 10, {10: 3.77}, 20))), 105, 20).map(x => x[1]);
console.log(JSON.stringify({cell: o.gridCellHeights[4], pasted: t}));
""" % ("function" + M2._method("commitGridCell")[len("commitGridCell"):]))
    assert r["cell"] == CUSTOM and r["pasted"] == [CUSTOM]


def test_colour_for_two_decimal_value_is_continuous():
    r = _run("""
const col = (v) => JSON.stringify(o.cellColorAt((v - CELL_COLOR_DELTA_MIN_MM) / (CELL_COLOR_DELTA_MAX_MM - CELL_COLOR_DELTA_MIN_MM)));
console.log(JSON.stringify([col(3.7), col(3.77), col(3.8)]));""")
    assert len(set(r)) == 3                                          # a hundredth moves the colour


def test_server_tps_grid_field_honours_a_hundredth_of_a_mm():
    import numpy as np
    import test_editor_v610_palette_close_slope_tenths as V
    T = V._server()
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

    assert float(np.max(field(3.77) - field(3.7))) > 0.0            # 0.07 mm difference survives to the surface
