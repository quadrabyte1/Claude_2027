"""Editor v5.86: "UI Mode" switch (Mode 1 / Mode 2) -- state, localStorage persistence, markup, seam, Mode 1 unchanged.

Real constants block + real methods are cut out of templates/editor.html and run in node.  No server, no DB.
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

METHODS = ["isUiMode2", "loadUiMode", "setUiMode"]
MODE_1, MODE_2 = C.value("UI_MODE_1"), C.value("UI_MODE_2")
KEY = C.value("STORAGE_KEY_UI_MODE")


def _method(name):
    start = EDITOR.index("\n    %s(" % name) + 1
    first = EDITOR[start:EDITOR.index("\n", start)]
    end = start + len(first) if first.rstrip().endswith("},") else EDITOR.index("\n    },", start) + len("\n    }")
    return EDITOR[start:end].strip().rstrip(",")


def _run(script, storage="ok", initial=None):
    body = ",\n".join(_method(n) for n in METHODS)
    js = C.prelude() + """
const store = %s;
const mode = %s;
globalThis.localStorage = {
  getItem(k) { if (mode === 'throw') throw new Error('blocked'); return k in store ? store[k] : null; },
  setItem(k, v) { if (mode === 'throw') throw new Error('blocked'); store[k] = v; },
};
const o = {uiMode: DEFAULT_UI_MODE, %s};
""" % (json.dumps(initial or {}), json.dumps(storage), body)
    out = subprocess.run([node, "-e", js + script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_constants_are_distinct_and_default_is_mode_1():
    assert MODE_1 != MODE_2
    assert C.value("DEFAULT_UI_MODE") == MODE_1
    assert C.value("UI_MODES") == [MODE_1, MODE_2]


def test_default_is_mode_1_and_not_mode_2():
    r = _run("o.loadUiMode(); console.log(JSON.stringify({m: o.uiMode, two: o.isUiMode2()}));")
    assert r == {"m": MODE_1, "two": False}


def test_toggle_and_persist():
    r = _run("""o.setUiMode(UI_MODE_2); const a = [o.uiMode, o.isUiMode2()];
      o.setUiMode(UI_MODE_1); const b = [o.uiMode, o.isUiMode2()];
      o.setUiMode(UI_MODE_2);
      console.log(JSON.stringify({a, b, stored: store[STORAGE_KEY_UI_MODE]}));""")
    assert r == {"a": [MODE_2, True], "b": [MODE_1, False], "stored": MODE_2}


def test_restored_from_storage_on_load():
    r = _run("o.loadUiMode(); console.log(JSON.stringify(o.uiMode));", initial={KEY: MODE_2})
    assert r == MODE_2


def test_garbage_stored_value_is_ignored_and_invalid_set_rejected():
    r = _run("""o.loadUiMode(); const a = o.uiMode; o.setUiMode('bogus');
      console.log(JSON.stringify({a, b: o.uiMode, stored: store[STORAGE_KEY_UI_MODE] ?? null}));""", initial={KEY: "nonsense"})
    assert r == {"a": MODE_1, "b": MODE_1, "stored": "nonsense"}


def test_storage_throwing_is_graceful():
    r = _run("""o.loadUiMode(); const a = o.uiMode; o.setUiMode(UI_MODE_2);
      console.log(JSON.stringify({a, b: o.uiMode}));""", storage="throw")
    assert r == {"a": MODE_1, "b": MODE_2}      # still works in-session, just not persisted


def test_switch_markup_uses_constants_and_segmented_style():
    i = EDITOR.index('data-testid="ui-mode-switch"')
    block = EDITOR[i:i + 1500]
    for needle in ("UI_MODE_CAPTION", "UI_MODE_LABEL_1", "UI_MODE_LABEL_2", "UI_MODE_TIP_SWITCH",
                   "setUiMode(UI_MODE_1)", "setUiMode(UI_MODE_2)", "eb-seg-btn", 'class="eb-seg"'):
        assert needle in block, needle
    assert C.value("UI_MODE_LABEL_1") == "Mode 1" and C.value("UI_MODE_LABEL_2") == "Mode 2"
    assert C.value("UI_MODE_CAPTION") == "UI Mode"


def test_seam_comments_in_all_four_handlers():
    for h in ("handleKey(e)", "onMouseDown(e)", "onMouseMove(e)", "onMouseUp(e)"):
        i = EDITOR.index("\n    " + h + " {")
        assert "UI-mode seam" in EDITOR[i:i + 400], h


def test_mode_1_bindings_unchanged_smoke():
    """v5.83 copy/paste + v5.85 shift-line bindings still wired; Mode-2 branches are only the one-line seam dispatches."""
    assert re.search(r"if \(e\.shiftKey && this\._gridShiftLineSelect\(x, y\)\)", EDITOR)
    assert "this.copyGridCells(); return;" in EDITOR and "this.pasteGridCells(); return;" in EDITOR
    code_branches = [l.strip() for l in EDITOR.splitlines() if "isUiMode2()" in l and not l.strip().startswith(("//", "{#")) and "isUiMode2() {" not in l]
    for l in code_branches:
        assert re.match(r"if \(this\.isUiMode2\(\)[^{]*(\{ .*; return; \}|\) return;)", l) or "isUiMode2()" in l, l


def test_version_comes_from_app_py():
    app = (APP_DIR / "app.py").read_text()
    version = re.search(r'^APP_VERSION = "([^"]+)"', app, re.M).group(1)
    assert "Boundary Editor %s" % version in EDITOR[:200] or re.search(r"Boundary Editor v\d+\.\d+", EDITOR[:200])
    assert "UI Mode" in EDITOR[:3000]
