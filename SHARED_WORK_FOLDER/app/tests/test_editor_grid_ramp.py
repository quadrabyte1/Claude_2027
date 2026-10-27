"""Editor v5.19: Ctrl+Option(Alt)+drag selects cells along the drag PATH (visit order) and the
popup takes a first and a last value; Tab/Enter out of the second box spreads first->last
linearly over the cells.  Pure function gridRampAssign is extracted from editor.html and run in node."""
import json, re, shutil, subprocess, sys
from pathlib import Path
import pytest

APP_DIR = Path(__file__).parent.parent
EDITOR = (APP_DIR / "templates" / "editor.html").read_text()
node = shutil.which("node")
sys.path.insert(0, str(Path(__file__).parent))
import editor_constants as C


def _fn():
    m = re.search(r"\nfunction (gridRampAssign\(.*?\n\})\n", EDITOR, re.S)
    assert m, "top-level gridRampAssign() missing"
    return C.prelude() + "function " + m.group(1)   # editor constants + the extracted function


def _run(order, first, last, mode="delta"):
    js = _fn() + "\nconsole.log(JSON.stringify(gridRampAssign(%s, %s, %s, %s)));" % (
        json.dumps(order), json.dumps(first), json.dumps(last), json.dumps(mode))
    return json.loads(subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout)


@pytest.mark.skipif(not node, reason="node not installed")
def test_six_cells_3_to_10():
    r = _run([10, 11, 12, 13, 14, 15], 3, 10)
    assert [p[0] for p in r] == [10, 11, 12, 13, 14, 15]     # visit order preserved
    assert [p[1] for p in r] == [3, 4.4, 5.8, 7.2, 8.6, 10]


@pytest.mark.skipif(not node, reason="node not installed")
def test_one_cell_gets_first_and_descending_ramp():
    assert _run([7], 3, 10) == [[7, 3]]
    assert [p[1] for p in _run([1, 2, 3], 2, -2)] == [2, 0, -2]


@pytest.mark.skipif(not node, reason="node not installed")
def test_rounded_to_tenth_and_clamped_by_mode():
    assert [p[1] for p in _run([1, 2, 3, 4], 0, 1)] == [0, 0.3, 0.7, 1]
    assert [p[1] for p in _run([1, 2], 25, 40, "absolute")] == [25, 30]
    assert [p[1] for p in _run([1, 2], -30, 30, "delta")] == [-20, 20]
    assert [p[1] for p in _run([1, 2], -5, 5, "absolute")] == [0, 5]


def test_wiring():
    assert "_gridRampMode" in EDITOR and "commitGridRamp" in EDITOR
    # Ctrl+Option branch is decided at mousedown from altKey, inside the Ctrl/Cmd branch
    i = EDITOR.index("if (gridCell && isCmdLike(e))")
    assert "e.altKey" in EDITOR[i:i + 900]
    assert "@keydown.tab.prevent" in EDITOR and "commitGridRamp()" in EDITOR
    assert "Ctrl+Option" in EDITOR   # help text
    # mouseup in ramp mode must not use the single-value path
    j = EDITOR.index("Grid multi-select finalization")
    assert "_gridRampMode" in EDITOR[j:j + 1500]


# ───────── grid-cell undo entries (single edit, Ctrl+drag set-all, ramp) -- v5.77: pushed on the unified history ─────────
def _method(name):
    m = re.search(r"\n    (%s\(.*?\n    \}),\n" % name, EDITOR, re.S)
    assert m, name + " missing"
    return m.group(1)


def _undo_run(script):
    """Run `script` against a mock editor object built from the real methods."""
    js = ("const " + _fn().replace("function ", "gridRampAssign = function ", 1) + ";\n"
          if False else _fn() + "\n") + """
const o = {gridMode:'delta', gridCellHeights:{1:2, 2:5}, _gridActiveCell:{idx:1}, _gridInputValue:'',
  _gridMultiSelect:null, _gridMultiSelectAnchor:null, _gridRampMode:false, _gridRampFirst:'', _gridRampLast:'',
  undoHistory:[], redoStack:[], maxUndo:100, gridN:20, saves:0, draws:0, flashes:[],
  draw(){this.draws++}, autoSave(){this.saves++}, flash(m){this.flashes.push(m)}};
const M = {%s};
for (const k in M) o[k] = M[k];
""" % ",\n".join(_method(n) for n in ["gridUndoSnapshot", "pushGridUndo", "_trimUndo", "undo", "_undoGridEntry",
                                       "commitGridCell", "commitGridRamp", "cancelGridRamp", "cancelGridCell", "_untouchedExplicitZero"]) + script
    out = subprocess.run([node, "-e", js], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(not node, reason="node not installed")
def test_undo_single_cell_edit():
    r = _undo_run("""o._gridInputValue='7'; o.commitGridCell();
      const after = JSON.stringify(o.gridCellHeights); const had = o.undoHistory.length === 1;
      o.undo(); console.log(JSON.stringify({after, had, back:o.gridCellHeights, saves:o.saves, undo:o.undoHistory.length}));""")
    assert json.loads(r["after"]) == {"1": 7, "2": 5} and r["had"]
    assert r["back"] == {"1": 2, "2": 5} and r["undo"] == 0
    assert r["saves"] == 2          # commit + undo both autosave


@pytest.mark.skipif(not node, reason="node not installed")
def test_undo_ctrl_drag_set_all_restores_exactly_touched_cells():
    r = _undo_run("""o._gridMultiSelect=new Set([1,3,4]); o._gridInputValue='9'; o.commitGridCell();
      const mid = JSON.stringify(o.gridCellHeights); o.undo();
      console.log(JSON.stringify({mid, back:o.gridCellHeights}));""")
    assert json.loads(r["mid"]) == {"1": 9, "2": 5, "3": 9, "4": 9}
    assert r["back"] == {"1": 2, "2": 5}            # empty cells deleted again, cell 2 untouched


@pytest.mark.skipif(not node, reason="node not installed")
def test_undo_ramp_fill_and_label_and_absolute_mode():
    r = _undo_run("""o.gridMode='absolute'; o._gridRampMode=true; o._gridMultiSelect=new Set([1,5,6,7]);
      o._gridRampFirst='3'; o._gridRampLast='10'; o.commitGridRamp();
      const mid = JSON.stringify(o.gridCellHeights); const label = o.undoHistory[0].label; o.undo();
      console.log(JSON.stringify({mid, label, back:o.gridCellHeights}));""")
    assert json.loads(r["mid"]) == {"1": 3, "2": 5, "5": 5.3, "6": 7.7, "7": 10}
    assert r["label"] == "ramp fill (4 cells)"
    assert r["back"] == {"1": 2, "2": 5}


@pytest.mark.skipif(not node, reason="node not installed")
def test_second_undo_is_noop_and_new_edit_stacks_on_history():
    r = _undo_run("""o._gridInputValue='7'; o.commitGridCell(); o.undo();
      const s1 = o.saves; const again = o.undo(); const noop = {again, same: s1===o.saves, h:{...o.gridCellHeights}};
      o._gridActiveCell={idx:2}; o._gridInputValue='1'; o.commitGridCell();   // edit A
      o._gridActiveCell={idx:1}; o._gridInputValue='8'; o.commitGridCell();   // edit B stacks on A
      o.undo(); const afterB = {...o.gridCellHeights}; const second = o.undo();
      console.log(JSON.stringify({noop, afterB, second, final:o.gridCellHeights}));""")
    assert r["noop"] == {"again": False, "same": True, "h": {"1": 2, "2": 5}}
    assert r["afterB"] == {"1": 2, "2": 1}          # only B undone first
    # v5.77: history is a stack, so the second undo steps back through edit A too
    assert r["second"] is True and r["final"] == {"1": 2, "2": 5}


@pytest.mark.skipif(not node, reason="node not installed")
def test_undo_refuses_after_mode_change():
    r = _undo_run("""o._gridInputValue='7'; o.commitGridCell(); o.gridMode='absolute'; o.undo();
      console.log(JSON.stringify({h:o.gridCellHeights, u:o.undoHistory.length}));""")
    assert r["h"] == {"1": 7, "2": 5} and r["u"] == 0     # refused, entry consumed


def test_undo_wiring():
    # v5.77: one unified history; Cmd+Z calls undo() (grid + polygon entries), no separate grid-undo path
    assert "_gridUndo" not in EDITOR and "this.undoStack" not in EDITOR
    h = EDITOR[EDITOR.index("// Undo: Cmd+Z / Ctrl+Z"):][:900]
    assert "tagName === 'INPUT'" in h and h.index("tagName === 'INPUT'") < h.index("this.undo()")
    # history cleared on project load / new project / reset
    assert len(re.findall(r"this\.undoHistory\s*=\s*\[\]", EDITOR)) >= 3
