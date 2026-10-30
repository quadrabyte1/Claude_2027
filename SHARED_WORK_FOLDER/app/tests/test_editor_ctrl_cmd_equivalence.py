"""Editor v5.91: Ctrl behaves exactly like Cmd (spec: "Cmd and Ctrl modifier keys can be used interchangeably").

macOS turns Ctrl+left-click into a context-menu click: NO `click` event, but mousedown (button 0, ctrlKey) and then
`contextmenu` (ctrlKey).  So (1) palette swatches must select on mousedown, and (2) a contextmenu event with Ctrl held
must never run the right-click actions (delete point / add point / clear grid cell / open popup palette).
Same technique as test_editor_ui_mode2.py: the REAL methods run in node against its mock editor object.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import editor_constants as C
import test_editor_ui_mode2 as T

pytestmark = pytest.mark.skipif(not T.node, reason="node not installed")

EXTRA = ["onSwatchMouseDown", "onSwatchKeyClick", "onPopupSwatchMouseDown", "onPopupSwatchKeyClick",
         "deleteGridCell", "gridUndoSnapshot"]
BTN_L, BTN_R = C.value("MOUSE_BUTTON_LEFT"), C.value("MOUSE_BUTTON_RIGHT")
KBD = C.value("CLICK_DETAIL_KEYBOARD")
# Mode 1 mock: one set grid cell (index CELL) at canvas px (CELL_X, CELL_Y); every cell is 10 css px wide.
CELL, CELL_X, CELL_Y = 5, 55, 5
MODE1 = (T.MODE1_STATE if hasattr(T, "MODE1_STATE") else "") + """
o.gridCellHeights = {%d: 1.5}; o.gridUndoSnapshot = function () {}; o.undoCount = 0;
o._gridCellCanvasPx = (c, r) => ({x: c * 10, y: r * 10, w: 10, h: 10});
""" % CELL


def _run(script, state=""):
    names = T.METHODS + [n for n in EXTRA if n not in T.METHODS]
    body = ",\n".join(T._handle_key() if n == "handleKey" else T._method(n) for n in names + ["handleGenerateKey", "handleKey"])
    js = C.prelude() + T.MOCK % (T.N, T.N, body, T.N, T.N) + state + "\n" + script
    out = subprocess.run([T.node, "-e", js], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


# ───────────────────────── swatches (side palette, popup palette, Eraser) ─────────────────────────
def test_swatch_markup_selects_on_mousedown_and_suppresses_context_menu():
    for tid, handler in (("palette-swatch", "onSwatchMouseDown"), ("palette-eraser", "onSwatchMouseDown"),
                         ("popup-swatch", "onPopupSwatchMouseDown"), ("popup-eraser", "onPopupSwatchMouseDown")):
        m = re.search(r'<button[^>]*data-testid="%s".*?>' % tid, T.EDITOR, re.S)
        assert m, tid
        tag = m.group(0)
        assert "@mousedown=\"%s(" % handler in tag, tid
        assert "@contextmenu.prevent" in tag, tid


def test_ctrl_mousedown_on_swatch_adds_second_brush_just_like_cmd():
    for mod in ("ctrlKey", "metaKey"):
        r = _run("""o.onSwatchMouseDown(7, ev(0, 0, {}));
          o.onSwatchMouseDown(20, ev(0, 0, {%s: true}));
          console.log(JSON.stringify([o.paintBrush, o.paintBrush2]));""" % mod)
        assert r == [7, 20], mod


def test_plain_mousedown_after_two_brushes_returns_to_single_brush():
    r = _run("""o.onSwatchMouseDown(7, ev(0,0)); o.onSwatchMouseDown(20, ev(0,0,{ctrlKey: true}));
      o.onSwatchMouseDown(3, ev(0,0)); console.log(JSON.stringify([o.paintBrush, o.paintBrush2]));""")
    assert r == [3, None]


def test_mouse_press_does_not_fire_twice_but_keyboard_activation_still_works():
    r = _run("""o.onSwatchMouseDown(7, ev(0, 0));
      o.onSwatchKeyClick(20, {detail: 1, ctrlKey: true});               // the click that follows a real press: ignored
      const afterPress = [o.paintBrush, o.paintBrush2];
      o.onSwatchKeyClick(9, {detail: %d});                               // Enter / Space on a focused swatch
      console.log(JSON.stringify({afterPress, kbd: [o.paintBrush, o.paintBrush2]}));""" % KBD)
    assert r == {"afterPress": [7, None], "kbd": [9, None]}


def test_right_button_mousedown_on_swatch_selects_nothing():
    r = _run("""o.onSwatchMouseDown(7, ev(0, 0, {button: BTN_R})); console.log(JSON.stringify([o.paintMode, o.paintBrush]));""")
    assert r[0] is False


def test_popup_swatch_mousedown_picks_single_brush_and_closes_popup_with_ctrl_too():
    r = _run("""o.onSwatchMouseDown(7, ev(0,0)); o.onSwatchMouseDown(20, ev(0,0,{ctrlKey: true}));
      o.openPaintPopup(50, 60);
      o.onPopupSwatchMouseDown(4, ev(0, 0, {ctrlKey: true}));
      console.log(JSON.stringify({b: [o.paintBrush, o.paintBrush2], open: o.paintPopup.open}));""")
    assert r == {"b": [4, None], "open": False}


# ───────────────────────── canvas: Ctrl-originated contextmenu is not a right-click ─────────────────────────
def test_ctrl_contextmenu_in_mode1_does_not_clear_cell_or_delete_point():
    r = _run("""o.onRightClick(ev(%d, %d, {button: BTN_L, ctrlKey: true}));        // macOS Ctrl+click contextmenu on a set cell
      const cellKept = (%d in o.gridCellHeights);
      o.onRightClick(ev(100, 100, {button: BTN_L, ctrlKey: true}));                // ... and on a polygon point
      console.log(JSON.stringify({cellKept, pts: o.polygons[0].points.length}));""" % (CELL_X, CELL_Y, CELL), MODE1)
    assert r == {"cellKept": True, "pts": 4}


def test_genuine_right_click_in_mode1_still_clears_cell_and_deletes_point():
    r = _run("""o.onRightClick(ev(%d, %d, {button: BTN_R}));
      const cellGone = !(%d in o.gridCellHeights);
      o.onRightClick(ev(100, 100, {button: BTN_R}));
      console.log(JSON.stringify({cellGone, pts: o.polygons[0].points.length}));""" % (CELL_X, CELL_Y, CELL), MODE1)
    assert r == {"cellGone": True, "pts": 3}


def test_ctrl_click_in_mode2_z_painting_does_not_open_popup_and_ctrl_drag_still_fills():
    r = _run("""o.setUiSubMode(UI_SUB_PAINT);
      o.onMouseDown(ev(5.5, 5.5, {ctrlKey: true})); o.onRightClick(ev(5.5, 5.5, {ctrlKey: true}));   // mousedown then contextmenu
      const popup = o.paintPopup.open; o.onMouseUp(ev(5.5, 5.5, {buttons: 0, ctrlKey: true}));
      console.log(JSON.stringify({popup}));""")
    assert r == {"popup": False}


def test_ctrl_contextmenu_in_mode2_boundary_editing_changes_nothing():
    r = _run("""o.onMouseDown(ev(100, 100, {ctrlKey: true})); o.onMouseUp(ev(100, 100, {buttons: 0, ctrlKey: true}));
      const before = JSON.stringify(o.polygons);
      o.onRightClick(ev(100, 100, {ctrlKey: true})); o.onRightClick(ev(150, 100, {ctrlKey: true}));
      console.log(JSON.stringify({same: before === JSON.stringify(o.polygons)}));""")
    assert r == {"same": True}


# ───────────────────────── keyboard chords + the single helper ─────────────────────────
def test_ctrl_chords_work_like_cmd():
    for mod in ("ctrlKey", "metaKey"):
        r = _run("""o.handleKey(key('p', {%s: true})); const p = o.uiSubMode;
          o.handleKey(key('b', {%s: true})); console.log(JSON.stringify([p, o.uiSubMode]));""" % (mod, mod))
        assert r == [T.SUB_P, T.SUB_B], mod


def test_cmd_like_helper_is_the_only_place_that_tests_both_modifiers():
    src = T.EDITOR
    assert len(re.findall(r"e\.metaKey\s*\|\|\s*e\.ctrlKey", src)) == 1       # inside isCmdLike() itself
    assert "isCmdLike(e)" in src and "isCtrlContextMenu(e)" in src
