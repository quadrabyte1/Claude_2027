"""Editor v5.14: grid cells tinted by value with matplotlib 'terrain' (auto-scaled)."""
import ast, re, sys
from pathlib import Path
import pytest

APP_DIR = Path(__file__).parent.parent
EDITOR = (APP_DIR / "templates" / "editor.html").read_text()


def _stops():
    m = re.search(r"TERRAIN_STOPS:\s*(\[[^\]]*\])", EDITOR)
    assert m, "TERRAIN_STOPS table missing"
    return ast.literal_eval(m.group(1))


def _interp(S, t):
    n = len(S) - 1; t = max(0, min(1, t)); f = t * n; i = min(n - 1, int(f)); u = f - i
    a = [int(S[i][k:k + 2], 16) for k in (1, 3, 5)]; b = [int(S[i + 1][k:k + 2], 16) for k in (1, 3, 5)]
    return [round(a[j] + (b[j] - a[j]) * u) for j in range(3)]


def test_stop_table_matches_matplotlib_terrain():
    cm = pytest.importorskip("matplotlib.cm") and __import__("matplotlib").colormaps["terrain"]
    S = _stops()
    assert len(S) >= 33
    for t in [0, 0.05, 0.2, 0.25, 0.33, 0.5, 0.61, 0.75, 0.9, 1.0]:
        exp = [round(v * 255) for v in cm(t)[:3]]
        got = _interp(S, t)
        assert all(abs(e - g) <= 3 for e, g in zip(exp, got)), (t, exp, got)


def test_toggle_is_view_only_and_persisted_locally():
    assert 'data-testid="color-cells-toggle"' in EDITOR and "Color cells by height" in EDITOR
    m = re.search(r"setColorCells\(\) \{(.*?)\n    \},", EDITOR, re.S)
    body = m.group(1)
    assert "localStorage" in body and "try" in body and "this.draw()" in body
    assert "autoSave" not in body
    assert "colorCellsByHeight: true" in EDITOR           # default on
    assert "colorCellsByHeight" not in EDITOR[EDITOR.index("const data = {"):EDITOR.index("await fetch('/api/boundaries'")]  # never saved in EGM


def test_fill_under_numbers_and_rings_and_semi_transparent():
    fill = EDITOR.index("Cell fill by value (v5.14)")
    helper = EDITOR[EDITOR.index("_drawCellColors(ctx, tl, cellWpx, cellHpx) {"):][:1400]
    assert ",0.5)" in helper and "idx < GRID_COLS * GRID_ROWS" in helper and "|| 0" in helper and "gridRange()" in helper
    nums = EDITOR.index("Numeric value text for set cells")
    ring = EDITOR.index("Trap-controlling cell ring")
    assert fill < nums < ring
    seg = EDITOR[fill:nums]
    assert "gridMode !== 'off'" in seg and "_drawCellColors" in seg
    assert "strokeText" not in EDITOR[nums:ring]           # v5.20: no white outline on value labels


def test_degenerate_range_uses_mid_colour():
    assert "range.max === range.min ? 0.5" in EDITOR


def _range_js_semantics(values):
    """Python mirror of gridRange() -- also asserted textually against the JS below."""
    vs = [v for v in values if v]
    if not vs:
        return None
    lo, hi = min(vs), max(vs)
    if len(vs) < 400:
        lo, hi = min(lo, 0), max(hi, 0)
    return lo, hi


def test_range_counts_empty_cells_as_zero():
    src = EDITOR[EDITOR.index("gridRange() {"):][:600]
    assert "if (nSet < 400)" in src and "if (0 < lo) lo = 0" in src and "if (0 > hi) hi = 0" in src
    assert _range_js_semantics([-3, -1]) == (-3, 0)      # all negative -> 0 is the high end
    assert _range_js_semantics([2, 5]) == (0, 5)
    assert _range_js_semantics([]) is None
