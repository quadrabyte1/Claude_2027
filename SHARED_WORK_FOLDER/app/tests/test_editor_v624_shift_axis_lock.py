"""Editor v6.24: Shift held during a Mode-2 Z-Painting stroke locks it to one row or column.
Real constants + real methods run in node on the mock editor of test_editor_ui_mode2 (no server, no DB, no EGMs)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import editor_constants as C
import test_editor_ui_mode2 as T
from test_editor_ui_mode2 import EDITOR, _run, _go_paint, N

import pytest
pytestmark = pytest.mark.skipif(not T.node, reason="node not installed")

SHIFT = "{shiftKey: true}"
BRUSH_STEP = C.value("PAINT_DEFAULT_STEP")
LOCK_CELLS = C.value("PAINT_SHIFT_LOCK_CELLS")
AXIS_H, AXIS_V = C.value("PAINT_AXIS_H"), C.value("PAINT_AXIS_V")
START_COL, START_ROW = 3, 5
FAR = 8          # cells moved along the stroke direction
STRAY = 3        # cells of perpendicular wobble


def _cells(script):
    """Run a stroke; return the set of painted (col, row) cells plus the undo count."""
    return _run(_go_paint() + """
o.onSwatchClick(%d, {});
%s
const cells = Object.keys(o.gridCellHeights).map(k => { const n = Number(k); return [n %% gridN_, gridN_ - 1 - Math.floor(n / gridN_)]; });
console.log(JSON.stringify({cells, hist: o.undoHistory.length}));""".replace("gridN_", str(N)) % (BRUSH_STEP, script))


def _cellset(r):
    return {tuple(c) for c in r["cells"]}


def test_constants():
    assert LOCK_CELLS > 0 and AXIS_H != AXIS_V


def test_shift_stroke_starting_horizontal_stays_on_its_row():
    r = _cells("""down(...cellXY(%d, %d), %s);
      move(...cellXY(%d, %d), %s); move(...cellXY(%d, %d), %s); move(...cellXY(%d, %d), %s);
      up(...cellXY(%d, %d), %s);""" % (START_COL, START_ROW, SHIFT,
                                      START_COL + 2, START_ROW + 1, SHIFT,            # mostly sideways -> H
                                      START_COL + FAR - 2, START_ROW + STRAY, SHIFT,  # wobbles down
                                      START_COL + FAR, START_ROW - STRAY, SHIFT,
                                      START_COL + FAR, START_ROW - STRAY, SHIFT))
    assert {row for _, row in _cellset(r)} == {START_ROW}
    assert {col for col, _ in _cellset(r)} == set(range(START_COL, START_COL + FAR + 1))     # no cell skipped
    assert r["hist"] == 1


def test_shift_stroke_starting_vertical_stays_on_its_column():
    r = _cells("""down(...cellXY(%d, %d), %s);
      move(...cellXY(%d, %d), %s); move(...cellXY(%d, %d), %s); move(...cellXY(%d, %d), %s);
      up(...cellXY(%d, %d), %s);""" % (START_COL, START_ROW, SHIFT,
                                      START_COL + 1, START_ROW + 2, SHIFT,            # mostly vertical -> V
                                      START_COL + STRAY, START_ROW + FAR - 2, SHIFT,
                                      START_COL - STRAY, START_ROW + FAR, SHIFT,
                                      START_COL - STRAY, START_ROW + FAR, SHIFT))
    assert {col for col, _ in _cellset(r)} == {START_COL}
    assert {row for _, row in _cellset(r)} == set(range(START_ROW, START_ROW + FAR + 1))
    assert r["hist"] == 1


def test_without_shift_the_stroke_stays_free():
    r = _cells("""drag([cellXY(%d, %d), cellXY(%d, %d), cellXY(%d, %d)]);""" % (
        START_COL, START_ROW, START_COL + FAR, START_ROW, START_COL + FAR, START_ROW + STRAY))
    cells = _cellset(r)
    assert len({row for _, row in cells}) > 1 and len({col for col, _ in cells}) > 1


def test_releasing_shift_mid_stroke_returns_to_free_painting():
    r = _cells("""down(...cellXY(%d, %d), %s);
      move(...cellXY(%d, %d), %s);                       // locked horizontal
      move(...cellXY(%d, %d), %s);                       // stray row is ignored
      move(...cellXY(%d, %d));                           // Shift released: free again, at the pointer
      up(...cellXY(%d, %d));""" % (START_COL, START_ROW, SHIFT,
                                  START_COL + 3, START_ROW, SHIFT,
                                  START_COL + 5, START_ROW + STRAY, SHIFT,
                                  START_COL + 5, START_ROW + STRAY,
                                  START_COL + 5, START_ROW + STRAY))
    cells = _cellset(r)
    assert (START_COL + 5, START_ROW + STRAY) in cells                    # painted where the pointer really is
    assert (START_COL + 5, START_ROW) in cells and (START_COL + 4, START_ROW + STRAY) not in cells   # no diagonal back-fill
    assert r["hist"] == 1


def test_pressing_shift_mid_stroke_locks_from_the_current_point():
    r = _cells("""down(...cellXY(%d, %d));
      move(...cellXY(%d, %d));                           // free
      move(...cellXY(%d, %d), %s);                       // Shift pressed here: anchor row = %d
      move(...cellXY(%d, %d), %s);
      up(...cellXY(%d, %d), %s);""" % (START_COL, START_ROW,
                                      START_COL + 1, START_ROW + 1,
                                      START_COL + 3, START_ROW + 1, SHIFT, START_ROW + 1,
                                      START_COL + 6, START_ROW + STRAY, SHIFT,
                                      START_COL + 6, START_ROW + STRAY, SHIFT))
    cells = _cellset(r)
    assert {(c, START_ROW + 1) for c in range(START_COL + 1, START_COL + 7)} <= cells
    assert not any(row > START_ROW + 1 for _, row in cells)


def test_eraser_gets_the_same_lock():
    r = _run(_go_paint() + """
for (let i = 0; i < 12; i++) for (let j = 0; j < 12; j++) o.gridCellHeights[cellIdx(i, j)] = 3;
o.onSwatchClick(PAINT_BRUSH_ERASER, {});
down(...cellXY(2, 4), {shiftKey: true}); move(...cellXY(5, 4), {shiftKey: true}); move(...cellXY(8, 7), {shiftKey: true}); up(...cellXY(8, 7), {shiftKey: true});
const left = (r) => [...Array(12).keys()].filter(i => o.gridCellHeights[cellIdx(i, r)] === undefined);
console.log(JSON.stringify({row4: left(4), row7: left(7), hist: o.undoHistory.length}));""")
    assert r["row4"] == [2, 3, 4, 5, 6, 7, 8] and r["row7"] == [] and r["hist"] == 1


def test_two_brush_ramp_drag_is_locked_too_and_stays_one_undo_step():
    r = _run(_go_paint() + """
o.onSwatchClick(10, {}); o.onSwatchClick(20, {metaKey: true});
down(...cellXY(1, 2), {shiftKey: true}); move(...cellXY(4, 2), {shiftKey: true}); move(...cellXY(7, 6), {shiftKey: true});
up(...cellXY(7, 6), {shiftKey: true});
const cells = Object.keys(o.gridCellHeights).map(k => { const n = Number(k); return [n % %d, %d - 1 - Math.floor(n / %d)]; });
console.log(JSON.stringify({cells, hist: o.undoHistory.length}));""".replace("%d", str(N)))
    assert {row for _, row in map(tuple, r["cells"])} == {2} and len(r["cells"]) == 7 and r["hist"] == 1


def test_shift_in_boundary_editing_is_still_additive_selection():
    assert "additive: !!e.shiftKey" in EDITOR
    r = _run("""down(100, 100); up(100, 100); down(200, 100, {shiftKey: true}); up(200, 100, {shiftKey: true});
      console.log(JSON.stringify({sel: sel()}));""")
    assert r["sel"] == "[[0,0],[0,1]]"


def test_no_literals_and_version():
    import app as app_module
    assert "paintAxisLock(st, raw.u, raw.v, e.shiftKey)" in EDITOR and "paintAxisLock(m, raw.u, raw.v, e.shiftKey)" in EDITOR
    major, minor = (int(x) for x in app_module.APP_VERSION.lstrip("v").split("."))
    assert (major, minor) >= (6, 24) and app_module.APP_VERSION in EDITOR.split("\n", 2)[1]
