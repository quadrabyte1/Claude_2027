"""Editor v5.85: Shift during a Cmd/Ctrl cell drag constrains the selection to a straight line.

Real constants block + real methods are cut out of templates/editor.html and run in node against a mock editor
whose pointer is given directly in image px (1 cell = CELL_PX px, print origin at 0,0).  No server, no DB.
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

METHODS = ["_gridUnitsFromImgPx", "_gridRayCells", "_gridShiftSnapDir", "_gridShiftLineSelect", "_gridCellFromImgPx"]
LOCK = C.value("GRID_SHIFT_LOCK_CELLS")
SNAP = C.value("GRID_SHIFT_SNAP_DEG")
N, CELL_PX = 20, 10


def _method(name):
    m = re.search(r"\n    (%s\(.*?\n    \}),\n" % re.escape(name), EDITOR, re.S)
    assert m, name + " missing"
    return m.group(1)


def _run(script):
    body = ",\n".join(_method(n) for n in METHODS)
    js = C.prelude() + """
const o = {gridN:%d, printSizeMm:%d, _gridMultiSelect:null, _gridMultiSelectAnchor:null, _gridShiftDir:null,
  _printTopLeftPx(){return {x:0,y:0}}, _pxPerMm(){return 1}};
const M = {%s};
for (const k in M) Object.defineProperty(o, k, Object.getOwnPropertyDescriptor(M, k));
// pointer helper: (u,v) in cell units (v up from bottom) -> image px
function P(u, v) { return [u * %d, (%d - v) * %d]; }
function start(col, row) { o._gridMultiSelect = new Set([row*%d+col]); o._gridMultiSelectAnchor = {col, row, idx: row*%d+col}; o._gridShiftDir = null; }
function move(u, v) { const [x,y] = P(u,v); return o._gridShiftLineSelect(x, y); }
function cells() { return [...o._gridMultiSelect].map(i => [i %% %d, Math.floor(i / %d)]); }
""" % (N, N * CELL_PX, body, CELL_PX, N, CELL_PX, N, N, N, N)
    out = subprocess.run([node, "-e", js + script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_horizontal_with_wobble_stays_on_one_row():
    r = _run("""start(3, 8);
      const handled = [move(4.5, 8.5), move(6.5, 8.9), move(8.5, 7.3), move(11.5, 9.4)];   // wobbling above/below
      console.log(JSON.stringify({handled, cells: cells()}));""")
    assert r["handled"] == [True] * 4 or r["handled"][0] is False        # first move may be inside the lock radius
    assert {row for _, row in r["cells"]} == {8}
    assert [c for c, _ in r["cells"]] == list(range(3, 12))


def test_vertical_with_wobble_stays_on_one_column():
    r = _run("""start(5, 2);
      move(5.6, 5.0); move(6.6, 7.5); move(4.2, 9.5); move(5.9, 11.5);
      console.log(JSON.stringify({cells: cells()}));""")
    assert {c for c, _ in r["cells"]} == {5}
    assert [row for _, row in r["cells"]] == list(range(2, 12))


def test_diagonal_45_is_exact_even_when_slightly_off():
    r = _run("""start(2, 2);
      move(5.5, 5.2); move(7.0, 8.2); move(9.4, 8.7);   // ~ 45deg +/- a few degrees
      console.log(JSON.stringify({cells: cells()}));""")
    assert r["cells"] == [[2 + i, 2 + i] for i in range(len(r["cells"]))] and len(r["cells"]) >= 7


def test_thirty_degree_line_is_one_cell_wide_and_monotone():
    r = _run("""start(1, 5);
      const ang = 30 * GRID_DEG_TO_RAD;
      for (let t = 2; t <= 14; t += 1) { const w = (t%2 ? 0.8 : -0.8)*(t>3); move(1.5 + t*Math.cos(ang) - w*Math.sin(ang), 5.5 + t*Math.sin(ang) + w*Math.cos(ang)); }  // wobble perpendicular to the line
      console.log(JSON.stringify({cells: cells()}));""")
    cells = r["cells"]
    assert cells[0] == [1, 5]
    for (c0, r0), (c1, r1) in zip(cells, cells[1:]):          # 8-connected, always moving right, never down
        assert c1 - c0 in (0, 1) and r1 - r0 in (0, 1) and (c1, r1) != (c0, r0)
    # each column hit by the 30deg line has at most 2 cells and rows follow tan(30) from the centre line
    for c, row in cells:
        expected = 5.5 + (c - 1) * 0.5774
        assert abs(row + 0.5 - expected) <= 1.25   # within ~one cell of the ideal line
    assert cells[-1][0] >= 12


def test_last_cell_is_far_end_and_retreat_reorders_to_current_end():
    r = _run("""start(2, 2);
      move(8.5, 2.5);
      const far = cells().slice(-1)[0];
      move(5.5, 2.5);                                      // pull back: cells stay selected, current end becomes last
      console.log(JSON.stringify({far, last: cells().slice(-1)[0], n: cells().length}));""")
    assert r["far"] == [8, 2] and r["last"] == [5, 2] and r["n"] == 7


def test_before_lock_distance_is_not_handled_and_after_it_is():
    r = _run("""start(5, 5);
      const near = move(5.5 + %f * 0.9, 5.5);
      const dirBefore = o._gridShiftDir;
      const far = move(5.5 + %f + 0.5, 5.5);
      console.log(JSON.stringify({near, dirBefore, far, dir: o._gridShiftDir}));""" % (LOCK, LOCK))
    assert r["near"] is False and r["dirBefore"] is None and r["far"] is True and r["dir"]["x"] == 1


def test_direction_is_not_snapped_beyond_tolerance():
    r = _run("""start(5, 5);
      const a = (%f + 3) * GRID_DEG_TO_RAD;      // just outside the snap window from 0deg
      move(5.5 + 6*Math.cos(a), 5.5 + 6*Math.sin(a));
      console.log(JSON.stringify(o._gridShiftDir));""" % SNAP)
    assert abs(r["y"]) > 1e-3 and abs(r["x"]) > 0.5


def test_line_stays_inside_grid_and_is_straight_at_the_edge():
    r = _run("""start(15, 15);
      move(30, 30);
      console.log(JSON.stringify({cells: cells()}));""")
    assert r["cells"] == [[15 + i, 15 + i] for i in range(5)]


def test_release_shift_returns_to_free_mode_keeping_line_cells():
    # Mirrors the onMouseMove wiring: no Shift -> lock cleared, line cells remain, normal add continues.
    src = _method("onMouseMove") if "onMouseMove(e) {" in EDITOR else ""
    r = _run("""start(2, 2); move(8.5, 2.5);
      const kept = cells().length;
      o._gridShiftDir = null;                                // what onMouseMove does when !e.shiftKey
      const [x, y] = P(8.5, 9.5);
      const c = o._gridCellFromImgPx(x, y);                  // free selection adds the cell under the pointer
      o._gridMultiSelect.add(c.idx);
      console.log(JSON.stringify({kept, n: cells().length, dir: o._gridShiftDir}));""")
    assert r["kept"] == 7 and r["n"] == 8 and r["dir"] is None
    assert re.search(r"if \(!e\.shiftKey\) this\._gridShiftDir = null;", EDITOR)
    assert re.search(r"if \(e\.shiftKey && this\._gridShiftLineSelect\(x, y\)\)", EDITOR)


def test_version_bumped_and_constants_defined_once():
    app = (APP_DIR / "app.py").read_text()
    version = re.search(r'^APP_VERSION = "([^"]+)"', app, re.M).group(1)   # single source of truth: app.py
    assert "Boundary Editor " + version in EDITOR
    for name in ("GRID_SHIFT_LOCK_CELLS", "GRID_SHIFT_SNAP_DEG", "GRID_SHIFT_SNAP_STEP_DEG", "GRID_EDGE_EPS", "GRID_CELL_CENTER"):
        assert len(re.findall(r"^const %s\b" % name, EDITOR, re.M)) == 1
