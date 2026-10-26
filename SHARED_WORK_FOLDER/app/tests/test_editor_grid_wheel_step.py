"""Editor v5.15: mouse wheel steps the grid value box (0.1 mm; Shift = 1.0 mm), no clamp,
no autosave until commit.  JS logic is extracted from editor.html and run in node."""
import json, re, shutil, subprocess, sys
from pathlib import Path
import pytest

APP_DIR = Path(__file__).parent.parent
EDITOR = (APP_DIR / "templates" / "editor.html").read_text()
sys.path.insert(0, str(Path(__file__).parent))
import editor_constants as C


def _method():
    m = re.search(r"\n    (gridWheel\(e\) \{.*?\n    \}),\n", EDITOR, re.S)
    assert m, "gridWheel(e) missing"
    return m.group(1)


def test_wired_to_input_non_passive_prevent():
    seg = EDITOR[EDITOR.index('x-ref="gridCellInput"'):][:1600]
    assert "@wheel.prevent=" in seg and "gridWheel($event)" in seg
    assert "Wheel" in seg or "wheel" in seg          # tooltip mentions it
    assert "GRID_TIP_INPUT_ABSOLUTE" in seg and "GRID_TIP_INPUT_DELTA" in seg   # tooltip comes from the constants
    tip = C.value("GRID_TIP_INPUT_DELTA")
    assert "wheel" in tip.lower() and "Shift" in tip


def test_handler_has_no_autosave_or_clamp_or_draw_commit():
    body = _method()
    assert "autoSave" not in body and "commitGridCell" not in body
    assert not re.search(r"Math\.(min|max)\(", body)   # no clamp


node = shutil.which("node")


def _run(events, start="", cells=None, active=5, multi=None):
    js = C.prelude() + """
const m = %s;
const o = {_gridInputValue: %s, _wheelAcc: 0, _gridActiveCell: {idx: %d}, _gridMultiSelect: %s, gridCellHeights: %s};
o.gridWheel = %s;
const out = [];
for (const ev of %s) { ev.preventDefault = () => { out.push('P'); }; o.gridWheel(ev); out.push(o._gridInputValue); }
console.log(JSON.stringify(out));
""" % ("null", json.dumps(start), active,
       "new Set(%s)" % json.dumps(multi) if multi else "null", json.dumps(cells or {}),
       "function" + _method()[len("gridWheel"):], json.dumps(events))
    r = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(not node, reason="node not installed")
def test_steps_up_down_and_precision():
    out = _run([{"deltaY": -100, "deltaMode": 0}] * 3, start="2.2")
    assert out[-1] == "2.5"                         # no float noise, wheel forward = up
    out = _run([{"deltaY": 100, "deltaMode": 0}], start="2.5")
    assert out[-1] == "2.4"
    assert out.count("P") == 1                      # preventDefault called


@pytest.mark.skipif(not node, reason="node not installed")
def test_shift_step_and_no_clamp():
    assert _run([{"deltaY": -100, "deltaMode": 0, "shiftKey": True}], start="29.5")[-1] == "30.5"   # past 30
    assert _run([{"deltaY": 100, "deltaMode": 0}] * 5, start="0")[-1] == "-0.5"                       # below 0
    # macOS swaps shift+wheel into deltaX
    assert _run([{"deltaY": 0, "deltaX": -100, "deltaMode": 0, "shiftKey": True}], start="1")[-1] == "2"


@pytest.mark.skipif(not node, reason="node not installed")
def test_trackpad_and_line_mode_normalised():
    swipe = [{"deltaY": -4, "deltaMode": 0}] * 50                  # 200 px total ~ 2 notches
    assert _run(swipe, start="1")[-1] == "1.2"
    assert _run([{"deltaY": -3, "deltaMode": 1}], start="1")[-1] == "1.1"   # Firefox line mode: one notch


@pytest.mark.skipif(not node, reason="node not installed")
def test_blank_start_uses_shared_cell_value_else_zero():
    assert _run([{"deltaY": -100, "deltaMode": 0}], start="", cells={"5": 2.0})[-1] == "2.1"
    assert _run([{"deltaY": -100, "deltaMode": 0}], start="", cells={"5": 2.0, "6": 3.0}, multi=[5, 6])[-1] == "0.1"
    assert _run([{"deltaY": -100, "deltaMode": 0}], start="", cells={}, multi=[5, 6])[-1] == "0.1"
