"""Editor v6.22: every error goes through ONE shared modal error dialog, not the status line.
Real constants + real functions run in node with the fake DOM (same harness as the v6.12 notice tests)."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import editor_constants as C
import test_editor_ui_mode2 as T
from test_editor_ui_mode2 import EDITOR, _run

import pytest
pytestmark = pytest.mark.skipif(not T.node, reason="node not installed")

MANUAL = "globalThis.__autoOk = false;\nconst dlg = () => document.getElementById(NOTICE_BACKDROP_ID);\nconst tick = () => new Promise(r => setTimeout(r, 0));\n"
TITLE = C.value("ERROR_DIALOG_TITLE")
OK_ID = C.value("NOTICE_OK_ID")


def _async(body):
    return _run(MANUAL + "(async () => {\n" + body + "\n})();")


def test_dialog_shape_focus_title_and_dismiss_keys():
    out = _async("""
showErrorDialog('boom'); await tick();
const d = dlg();
const shape = {title: d.find(NOTICE_TITLE_ID).textContent, msg: d.find(NOTICE_MESSAGE_ID).textContent,
  focusOk: document.activeElement === d.find(NOTICE_OK_ID), err: d.find(NOTICE_BOX_ID).className.includes(NOTICE_CLASS_BOX_ERROR), open: isNoticeDialogOpen()};
const e = document.key('Escape'); await tick();
console.log(JSON.stringify({shape, stopped: e.stopped, gone: dlg() === null, open: isNoticeDialogOpen()}));""")
    assert out["shape"]["title"] == TITLE and out["shape"]["msg"] == "boom"
    assert out["shape"]["focusOk"] and out["shape"]["err"] and out["shape"]["open"]
    assert out["gone"] and not out["open"] and out["stopped"]


def test_enter_and_ok_button_dismiss():
    out = _async("""
showErrorDialog('a'); await tick(); document.key('Enter'); await tick();
const afterEnter = dlg() === null;
showErrorDialog('b'); await tick(); dlg().find(NOTICE_OK_ID).click(); await tick();
console.log(JSON.stringify({afterEnter, afterOk: dlg() === null}));""")
    assert out == {"afterEnter": True, "afterOk": True}


def test_several_errors_queue_in_order_none_lost_duplicates_not_stacked():
    out = _async("""
showErrorDialog('one'); showErrorDialog('two'); showErrorDialog('two'); showErrorDialog('three'); await tick();
const seen = [];
for (let i = 0; i < 6 && dlg(); i++) { seen.push(dlg().find(NOTICE_MESSAGE_ID).textContent); document.key('Enter'); await tick(); await tick(); }
console.log(JSON.stringify({seen, left: dlg() === null}));""")
    assert out["seen"] == ["one", "two", "three"] and out["left"]


def test_empty_message_shows_nothing():
    out = _async("showErrorDialog(''); showErrorDialog(null); await tick(); console.log(JSON.stringify({none: dlg() === null}));")
    assert out["none"]


def test_error_waits_for_open_notice_dialog():
    out = _async("""
showNoticeDialog('slope hint', null); await tick();
showErrorDialog('late'); await tick();
const first = dlg().find(NOTICE_MESSAGE_ID).textContent;
document.key('Enter'); await new Promise(r => setTimeout(r, ERROR_DIALOG_RETRY_MS * 3));
console.log(JSON.stringify({first, then: dlg() && dlg().find(NOTICE_MESSAGE_ID).textContent}));""")
    assert out == {"first": "slope hint", "then": "late"}


def test_flash_false_opens_dialog_not_status_line_and_hint_stays():
    body = EDITOR[EDITOR.index("    flash(msg, ok, filename"):EDITOR.index("    flashDismiss()")]
    out = _async("""
const o = {statusMsg: '', statusOk: true, statusFilename: '', statusSticky: false, _flashTimer: null};
o.flash = function(msg, ok, filename = '', durationMs = null) {""" + body[body.index("{") + 1:body.rindex("}")] + """};
o.flash('server said no', false); await tick();
const err = {status: o.statusMsg, dlg: dlg() && dlg().find(NOTICE_MESSAGE_ID).textContent}; document.key('Enter'); await tick();
o.flash('Nothing to undo', FLASH_KIND_HINT);
const hint = {status: o.statusMsg, ok: o.statusOk, dlg: dlg() === null};
o.flash('Saved', true);
console.log(JSON.stringify({err, hint, info: o.statusMsg}));""")
    assert out["err"] == {"status": "", "dlg": "server said no"}
    assert out["hint"] == {"status": "Nothing to undo", "ok": False, "dlg": True}
    assert out["info"] == "Saved"


def test_error_messages_with_dollar_patterns_are_literal():
    out = _async("showErrorDialog(fillDetail(MSG_UNEXPECTED_ERROR_FMT, 'cost $& $1')); await tick(); console.log(JSON.stringify(dlg().find(NOTICE_MESSAGE_ID).textContent));")
    assert out == C.value("MSG_UNEXPECTED_ERROR_FMT").replace("{detail}", "cost $& $1")


# ---- source wiring: every error path reaches the dialog -----------------------------------------
def test_no_error_flash_left_on_status_line_and_flash_reroutes():
    assert "if (ok === false) { showErrorDialog(" in EDITOR
    assert "installGlobalErrorHandlers();" in EDITOR
    assert C.value("WINDOW_EVENT_REJECTION") == "unhandledrejection" and C.value("WINDOW_EVENT_ERROR") == "error"


def test_error_paths_are_routed():
    for needle in ("showErrorDialog(fillDetail(MSG_AUTOSAVE_FAILED_FMT", "showErrorDialog(MSG_COURSE_LIST_FAILED",
                   "showErrorDialog(fillDetail(MSG_DEGRID_FAILED_FMT"):
        assert needle in EDITOR
    # load / generate / detection failures all still call flash(..., false) which now opens the dialog
    for needle in ("'Generation failed after '", "'Generation error after '", "'Error loading project: '",
                   "'Detection failed: '", "'Contour detection error: '", "' loading project: '"):
        m = re.search(re.escape(needle) + r"[^\n]*?, false", EDITOR)
        assert m, needle


def test_css_uses_custom_properties_for_error_colors():
    assert "--notice-error-accent:" in EDITOR
    assert re.search(r"\.eb-notice-title--error\s*\{\s*color:var\(--notice-error-accent\)", EDITOR)


MIN_VERSION = (6, 22)   # the release that introduced the error dialog (the version only moves up)


def test_version_bumped_separately():
    import app as app_module
    major, minor = (int(x) for x in app_module.APP_VERSION.lstrip("v").split("."))
    assert (major, minor) >= MIN_VERSION
    assert app_module.APP_VERSION in EDITOR.split("\n", 2)[1]
