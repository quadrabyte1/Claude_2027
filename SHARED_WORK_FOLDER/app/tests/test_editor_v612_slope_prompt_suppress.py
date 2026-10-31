"""Editor v6.12: Slope pop-ups are an in-page native-alert look-alike with a "Don't prompt anymore" checkbox.
Reuses the node harness of test_editor_ui_mode2 (real constants + real methods + fake DOM/localStorage)."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import editor_constants as C
import test_editor_ui_mode2 as T
from test_editor_ui_mode2 import EDITOR, _run, _go_paint, STROKE, SLOPE_KEY, SLOPE_LO, SLOPE_HI, MSG_FIRST, MSG_SECOND

import pytest
pytestmark = pytest.mark.skipif(not T.node, reason="node not installed")

LABEL = C.value("NOTICE_DONT_PROMPT_LABEL")
KEY = C.value("NOTICE_SUPPRESS_KEY_SLOPE")
ON = C.value("STORAGE_VALUE_ON")
OPT_LABEL = C.value("SLOPE_PROMPTS_OPTION_LABEL")
IDS = {n: C.value(n) for n in ("NOTICE_BACKDROP_ID", "NOTICE_CHECK_ID", "NOTICE_OK_ID", "NOTICE_MESSAGE_ID", "NOTICE_TITLE_ID")}

# open dialogs stay open (no auto-OK) so the tests can drive them
MANUAL = "globalThis.__autoOk = false;\nconst dlg = () => document.getElementById(NOTICE_BACKDROP_ID);\n"
FULL_SLOPE = """
o.m2HandleKey(key(SLOPE_KEY)); pick(%d); stroke(2, 2, 14); pick(%d); stroke(8, 2, 14);
""" % (SLOPE_LO, SLOPE_HI)


def test_constants_and_label_exact():
    assert LABEL == "Don't prompt anymore"
    assert OPT_LABEL == "Show Slope prompts"
    assert "window.alert(" not in EDITOR
    assert "showConfirmDialog(MSG_GRID_RESOLUTION_ERASE)" in EDITOR and "window.confirm(message)" in EDITOR


def test_dialog_shape_checkbox_label_and_ok_focus():
    out = _run(MANUAL + """
showNoticeDialog('hello', NOTICE_SUPPRESS_KEY_SLOPE);
const d = dlg(), box = d.find(NOTICE_BOX_ID);
console.log(JSON.stringify({open: isNoticeDialogOpen(), msg: d.find(NOTICE_MESSAGE_ID).textContent, title: d.find(NOTICE_TITLE_ID).textContent,
  label: d.find(NOTICE_CHECK_ID).parentNode.text(), ok: d.find(NOTICE_OK_ID).textContent,
  focusOk: document.activeElement === d.find(NOTICE_OK_ID), role: box.attrs.role}));""")
    assert out["open"] and out["msg"] == "hello" and out["label"] == LABEL
    assert out["ok"] == C.value("NOTICE_OK_LABEL") and out["focusOk"] and out["role"] == C.value("NOTICE_ROLE")
    assert out["title"].endswith(C.value("NOTICE_TITLE_SUFFIX"))


def test_checked_then_ok_suppresses_next_s_and_both_prompts():
    out = _run(_go_paint() + STROKE + MANUAL + """
o.m2HandleKey(key(SLOPE_KEY));
const shown1 = window.dialogs.length;
dlg().find(NOTICE_CHECK_ID).checked = true; dlg().find(NOTICE_OK_ID).click();
await_ = null;
""".replace("await_ = null;", "") + """
const stored = localStorage.getItem(NOTICE_SUPPRESS_KEY_SLOPE);
o.m2HandleKey(key(SLOPE_KEY)); pick(%d); stroke(2, 2, 14); pick(%d); stroke(8, 2, 14);   // whole workflow again
console.log(JSON.stringify({shown1, stored, after: window.dialogs.length, open: isNoticeDialogOpen(), slope: o._slope, undo: o.undoHistory.length}));
""" % (SLOPE_LO, SLOPE_HI))
    assert out["shown1"] == 1 and out["stored"] == ON
    assert out["after"] == 1 and not out["open"]          # neither the first nor the second prompt appeared again
    assert out["slope"] is None and out["undo"] == 1      # the Slope still completed exactly as if OK had been pressed


def test_unchecked_ok_still_shows_next_time():
    out = _run(_go_paint() + STROKE + MANUAL + """
o.m2HandleKey(key(SLOPE_KEY)); dlg().find(NOTICE_OK_ID).click();
o.m2HandleKey(key(SLOPE_KEY));
console.log(JSON.stringify({n: window.dialogs.length, stored: localStorage.getItem(NOTICE_SUPPRESS_KEY_SLOPE), open: isNoticeDialogOpen()}));""")
    assert out == {"n": 2, "stored": None, "open": True}


def test_enter_and_escape_dismiss_and_persist_checkbox():
    for k in ("Enter", "Escape"):
        out = _run(MANUAL + """
const p = showNoticeDialog('m', NOTICE_SUPPRESS_KEY_SLOPE); dlg().find(NOTICE_CHECK_ID).checked = true;
const e = document.key(%s);
console.log(JSON.stringify({open: isNoticeDialogOpen(), stored: localStorage.getItem(NOTICE_SUPPRESS_KEY_SLOPE), l: document.listeners(), gone: dlg() === null, prevented: e.prevented}));""" % json.dumps(k))
        assert out == {"open": False, "stored": ON, "l": 0, "gone": True, "prevented": True}


def test_reenable_restores_prompts():
    out = _run(_go_paint() + STROKE + MANUAL + """
localStorage.setItem(NOTICE_SUPPRESS_KEY_SLOPE, '1'); o.slopePromptsSuppressed = true;
o.m2HandleKey(key(SLOPE_KEY)); const n0 = window.dialogs.length;
o.setSlopePromptsSuppressed(false);
const stored = localStorage.getItem(NOTICE_SUPPRESS_KEY_SLOPE), flag = o.slopePromptsSuppressed;
o.slopeCancel(true); o.m2HandleKey(key(SLOPE_KEY));
console.log(JSON.stringify({n0, n1: window.dialogs.length, stored, flag}));""")
    assert out == {"n0": 0, "n1": 1, "stored": None, "flag": False}
    i = EDITOR.index('id="slope-prompts-checkbox"')
    assert "setSlopePromptsSuppressed(!$event.target.checked)" in EDITOR[i:i + 200]
    assert EDITOR.index('id="slope-prompts-option"') > EDITOR.index('id="options-body"')   # lives inside Options


def test_options_checkbox_stays_in_step_after_dialog_suppress():
    out = _run(_go_paint() + MANUAL + """
o.m2HandleKey(key(SLOPE_KEY)); dlg().find(NOTICE_CHECK_ID).checked = true; dlg().find(NOTICE_OK_ID).click();
await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
console.log(JSON.stringify(o.slopePromptsSuppressed));""".replace("console.log", "console.log").replace(MANUAL, MANUAL))
    assert out is True


def test_keyboard_and_canvas_blocked_while_open_and_tab_trapped():
    out = _run(_go_paint() + STROKE + MANUAL + """
o.m2HandleKey(key(SLOPE_KEY));
const ck = dlg().find(NOTICE_CHECK_ID), ok = dlg().find(NOTICE_OK_ID);
const eg = document.key('g'), es = document.key('s'), eb = document.key('b');
const t1 = document.key('Tab'); const f1 = document.activeElement === ck;
const t2 = document.key('Tab'); const f2 = document.activeElement === ok;
const t3 = document.key('Tab', {shiftKey: true}); const f3 = document.activeElement === ck;
const before = o.draws; const mode = o._m2;
o.handleKey(key('s')); o.handleKey(key('g')); down(5.5, 5.5); move(6.5, 5.5); up(6.5, 5.5);
const bd = dlg(); let bubbled = true; bd.handlers.mousedown[0]({stopPropagation() { bubbled = false; }});
console.log(JSON.stringify({stopped: [eg, es, eb].map(e => e.stopped && e.prevented), f1, f2, f3, mode: o._m2 === mode, m2: o._m2,
  draws: o.draws === before, open: isNoticeDialogOpen(), bubbled, fixed: EDITOR_CSS_OK}));""".replace("EDITOR_CSS_OK", "true"))
    assert out["stopped"] == [True, True, True] and out["f1"] and out["f2"] and out["f3"]
    assert out["mode"] and out["m2"] is None and out["draws"] and out["open"] and not out["bubbled"]
    css = EDITOR[EDITOR.index(".eb-notice-backdrop {"):]
    assert "position:fixed" in css[:200] and "inset:0" in css[:200]    # full-page backdrop swallows canvas clicks
    assert "z-index:calc(var(--editor-z-modal) + 1)" in css[:200]


def test_focus_returns_after_close_and_space_toggles_checkbox_natively():
    out = _run(MANUAL + """
const prev = document.createElement('button'); prev.focus();
showNoticeDialog('m', NOTICE_SUPPRESS_KEY_SLOPE);
const ck = dlg().find(NOTICE_CHECK_ID); ck.focus();
const sp = document.key(' ');                                        // Space on checkbox: swallowed from the page, not preventDefault-ed
document.key('Enter');
console.log(JSON.stringify({stopped: sp.stopped, prevented: sp.prevented, back: document.activeElement === prev}));""")
    assert out == {"stopped": True, "prevented": False, "back": True}


def test_storage_failures_never_throw():
    out = _run(MANUAL + """
globalThis.__storeBroken = true;
showNoticeDialog('m', NOTICE_SUPPRESS_KEY_SLOPE); dlg().find(NOTICE_CHECK_ID).checked = true; dlg().find(NOTICE_OK_ID).click();
console.log(JSON.stringify({open: isNoticeDialogOpen(), sup: isNoticeSuppressed(NOTICE_SUPPRESS_KEY_SLOPE)}));""")
    assert out == {"open": False, "sup": False}


def test_dialog_without_suppress_key_has_no_checkbox():
    out = _run(MANUAL + "showNoticeDialog('m'); console.log(JSON.stringify(dlg().find(NOTICE_CHECK_ID)));")
    assert out is None


def test_grid_resolution_warning_still_native_confirm():
    out = _run("""window.dialogs.length = 0; window.confirm = (m) => { window.dialogs.push(['confirm', m]); return true; };
console.log(JSON.stringify([showConfirmDialog('x'), window.dialogs, isNoticeDialogOpen()]));""")
    assert out == [True, [["confirm", "x"]], False]


def test_brush_cursor_has_no_strike_and_obsolete_constants_gone():
    assert "STRIKE" not in EDITOR and "no-color-strike" not in EDITOR
    svg = _run("""console.log(JSON.stringify(paintCursorSvg(CURSOR_NO_COLOR_FILL)));""")
    assert 'data-part="bristles"' in svg and 'fill="%s"' % C.value("CURSOR_NO_COLOR_FILL") in svg


def test_version_bumped():
    app = (Path(__file__).parent.parent / "app.py").read_text()
    ver = re.search(r'APP_VERSION = "(v[\d.]+)"', app).group(1)   # v6.13+ bumps keep the v6.12 entry in the changelog line
    assert "Boundary Editor " + ver in EDITOR.splitlines()[1] and "v6.12" in EDITOR.splitlines()[1]
