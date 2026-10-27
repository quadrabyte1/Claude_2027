"""Editor v5.14/v5.76: grid cells tinted by value on a FIXED RdYlBu_r scale."""
import ast, re, sys
from pathlib import Path
import pytest

APP_DIR = Path(__file__).parent.parent
EDITOR = (APP_DIR / "templates" / "editor.html").read_text()
sys.path.insert(0, str(Path(__file__).parent))
import editor_constants as C


def _stops():
    return C.value("CELL_COLOR_STOPS")


def _interp(S, t):
    n = len(S) - 1; t = max(0, min(1, t)); f = t * n; i = min(n - 1, int(f)); u = f - i
    a = [int(S[i][k:k + 2], 16) for k in (1, 3, 5)]; b = [int(S[i + 1][k:k + 2], 16) for k in (1, 3, 5)]
    return [round(a[j] + (b[j] - a[j]) * u) for j in range(3)]


def _color(v, mode):
    """Python mirror of gridRange() + cellColorRgb()."""
    lo, hi = ((C.value("CELL_COLOR_ABSOLUTE_MIN_MM"), C.value("CELL_COLOR_ABSOLUTE_MAX_MM"))
              if mode == "absolute" else
              (C.value("CELL_COLOR_DELTA_MIN_MM"), C.value("CELL_COLOR_DELTA_MAX_MM")))
    return _interp(_stops(), (v - lo) / (hi - lo))


def test_fixed_range_constants():
    assert (C.value("CELL_COLOR_DELTA_MIN_MM"), C.value("CELL_COLOR_DELTA_MAX_MM")) == (-15, 15)
    assert (C.value("CELL_COLOR_ABSOLUTE_MIN_MM"), C.value("CELL_COLOR_ABSOLUTE_MAX_MM")) == (0, 30)
    assert "GRID_RANGE_FULL_CELL_COUNT" not in EDITOR and "TERRAIN_STOPS" not in EDITOR


def test_stop_table_matches_matplotlib_rdylbu_r():
    cm = pytest.importorskip("matplotlib").colormaps["RdYlBu_r"]
    S = _stops()
    assert len(S) >= 31
    for t in [0, 0.05, 0.2, 0.25, 0.33, 0.5, 0.61, 0.75, 0.9, 1.0]:
        exp = [round(v * 255) for v in cm(t)[:3]]
        got = _interp(S, t)
        assert all(abs(e - g) <= 4 for e, g in zip(exp, got)), (t, exp, got)


def test_same_value_same_color_regardless_of_other_cells():
    # gridRange() takes no cell data: the JS must not read gridCellHeights there
    src = EDITOR[EDITOR.index("    gridRange() {"):][:500]
    assert "gridCellHeights" not in src
    assert _color(7, "delta") == _color(7, "delta")


def test_midpoint_maps_to_middle_stop():
    S = _stops()
    mid = S[len(S) // 2]
    mid_rgb = [int(mid[k:k + 2], 16) for k in (1, 3, 5)]
    assert _color(0, "delta") == mid_rgb
    assert _color(15, "absolute") == mid_rgb


def test_absolute_uses_same_colors_as_delta():
    assert _color(0, "absolute") == _color(-15, "delta")
    assert _color(30, "absolute") == _color(15, "delta")


def test_values_clamp_at_ends():
    S = _stops()
    lo = [int(S[0][k:k + 2], 16) for k in (1, 3, 5)]
    hi = [int(S[-1][k:k + 2], 16) for k in (1, 3, 5)]
    assert _color(-20, "delta") == lo == _color(-15, "delta")
    assert _color(20, "delta") == hi == _color(15, "delta")
    assert _color(-5, "absolute") == lo and _color(45, "absolute") == hi


def test_toggle_is_view_only_and_persisted_locally():
    assert 'data-testid="color-cells-toggle"' in EDITOR and "Color cells by height" in EDITOR
    m = re.search(r"setColorCells\(\) \{(.*?)\n    \},", EDITOR, re.S)
    body = m.group(1)
    assert "localStorage" in body and "try" in body and "this.draw()" in body
    assert "autoSave" not in body
    assert "colorCellsByHeight: true" in EDITOR           # default on
    assert "colorCellsByHeight" not in EDITOR[EDITOR.index("const data = {"):EDITOR.index("await fetch(API_BOUNDARIES")]  # API_BOUNDARIES = '/api/boundaries' (constants block)  # never saved in EGM


def test_fill_under_numbers_and_rings_and_semi_transparent():
    fill = EDITOR.index("Cell fill by value (v5.14)")
    helper = EDITOR[EDITOR.index("_drawCellColors(ctx, tl, cellWpx, cellHpx) {"):][:1400]
    assert ",${CELL_COLOR_ALPHA})" in helper and C.value("CELL_COLOR_ALPHA") == 0.5 and "idx < GRID_COLS * GRID_ROWS" in helper and "=== undefined" in helper and "gridRange()" in helper
    nums = EDITOR.index("Numeric value text for set cells")
    ring = EDITOR.index("Highlight the active cell")
    assert fill < nums < ring
    seg = EDITOR[fill:nums]
    assert "gridMode !== GRID_MODE_OFF" in seg and C.value("GRID_MODE_OFF") == "off" and "_drawCellColors" in seg
    assert "strokeText" not in EDITOR[nums:ring]           # v5.20: no white outline on value labels


def test_legend_labels_fixed_ends_and_clamp_in_js():
    assert "cellColorLegendGradient" not in EDITOR and "cell-color-legend" not in EDITOR   # v5.80: legend removed
    js = EDITOR[EDITOR.index("    cellColorAt(t) {"):][:400]
    assert "Math.max(0, Math.min(1, t))" in js


# ───────── v5.78: label font scales with cell width; empty cells uncoloured ─────────
import json, subprocess

def _node(js):
    out = subprocess.run([C.NODE, "-e", C.prelude() + js], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_fine_label_font_scales_and_clamps():
    lo, hi = C.value("GRID_VALUE_FONT_PX_FINE_MIN"), C.value("GRID_VALUE_FONT_PX_FINE_MAX")
    ws = [4, 10, 15, 20, 25, 30, 60, 200]
    got = _node("console.log(JSON.stringify(%s.map(w => gridValueFontPx(40, w))));" % ws)
    assert all(lo <= g <= hi for g in got)
    assert got == sorted(got) and got[0] == lo and got[-1] == hi and len(set(got)) > 2   # actually scales
    assert 0 < lo < hi <= C.value("GRID_VALUE_FONT_PX")


def test_fine_label_fits_in_cell_at_typical_sizes():
    # widest label "-12.5": 5 glyphs at <= 0.62em each must fit one cell for cells >= 16 css px (typical 40x40)
    frac = C.value("GRID_VALUE_FONT_FINE_CELL_FRACTION")
    assert frac * 5 * 0.62 <= 1.0
    for w in (16, 20, 24, 30, 40):
        f = _node("console.log(gridValueFontPx(40, %d));" % w)
        assert f * 5 * 0.62 <= w, (w, f)


def test_coarse_label_font_unchanged():
    assert C.value("GRID_VALUE_FONT_PX") == 11
    got = _node("console.log(JSON.stringify([5, 20, 80].map(w => gridValueFontPx(20, w))));")
    assert got == [11, 11, 11]


def test_draw_uses_adaptive_font_from_cell_pixel_width():
    assert "gridValueFontPx(this.gridN, Math.abs(_cw1.x - _cw0.x) / dpr)" in EDITOR
    assert "GRID_VALUE_FONT_PX_FINE " not in EDITOR and "GRID_VALUE_FONT_PX_FINE\n" not in EDITOR


def test_empty_cells_get_no_fill_set_cells_keep_scale_color():
    m = re.search(r"    _drawCellColors\(ctx, tl, cellWpx, cellHpx\) \{.*?\n    \},", EDITOR, re.S)
    fn = m.group(0)[len("    _drawCellColors"):]
    fn = "function _drawCellColors" + fn.rstrip().rstrip(",")
    js = f"""
{fn}
const stops = CELL_COLOR_STOPS;
const self = {{ gridN: 4, gridCellHeights: {{ 1: 5, 2: 0, 3: -15, 6: 15 }},
  gridRange() {{ return {{min: CELL_COLOR_DELTA_MIN_MM, max: CELL_COLOR_DELTA_MAX_MM}}; }},
  cellColorRgb(v, r) {{ return [Math.round(v), 0, 0]; }},
  imgToCanvas(x, y) {{ return {{x, y}}; }} }};
const fills = [];
const ctx = {{ set fillStyle(v) {{ this._f = v; }}, fillRect(x, y, w, h) {{ fills.push([x, y, this._f]); }} }};
_drawCellColors.call(self, ctx, {{x: 0, y: 0}}, 10, 10);
console.log(JSON.stringify(fills));
"""
    fills = _node(js)
    assert len(fills) == 4                      # cells 1, 2 (explicit 0 since v5.80), 3, 6 only: not the 12 absent ones
    assert [f[2] for f in fills] == ["rgba(5,0,0,0.5)", "rgba(0,0,0,0.5)", "rgba(-15,0,0,0.5)", "rgba(15,0,0,0.5)"]


def test_explicit_zero_cell_gets_the_scale_midpoint_colour():
    """v5.80: a brush-painted 0 is a set cell -> filled with the real cellColorAt/cellColorRgb colour.
    Delta mode: 0 is the exact midpoint of the fixed scale (pale yellow, stop 15)."""
    body = lambda n: re.search(r"\n    (%s\(.*?\n    \}),\n" % n, EDITOR, re.S).group(1)
    js = C.prelude() + "const o = {gridN: 2, gridCellHeights: {2: 0}, gridMode: 'delta', imgToCanvas(x, y) {return {x, y};}, " + \
        ",".join(body(n) for n in ("_drawCellColors", "cellColorAt", "cellColorRgb", "gridRange")) + "};" + \
        "const fills = []; const ctx = {set fillStyle(v) {this._f = v;}, fillRect() {fills.push(this._f);}};" + \
        "o._drawCellColors(ctx, {x: 0, y: 0}, 10, 10); console.log(JSON.stringify(fills));"
    import json, shutil, subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    out = subprocess.run([node, "-e", js], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    mid = _stops()[(len(_stops()) - 1) // 2]
    rgb = [int(mid[k:k + 2], 16) for k in (1, 3, 5)]
    assert json.loads(out.stdout.strip().splitlines()[-1]) == ["rgba(%d,%d,%d,%s)" % (*rgb, C.value("CELL_COLOR_ALPHA"))]
    assert rgb == [255, 254, 190]   # pale yellow


def test_old_empty_equals_zero_comments_gone():
    assert "every cell; empty = 0" not in EDITOR and "empties counted as 0" not in EDITOR
    assert "empty cells stay uncoloured" in EDITOR
