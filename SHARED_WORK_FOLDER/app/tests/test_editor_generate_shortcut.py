"""Editor v6.07: G / Cmd+G / Ctrl+G press the Generate button.  Real method + constants run in node on a mock editor.
Run: python -m pytest app/tests/test_editor_generate_shortcut.py -v
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

KEY = C.value("GENERATE_KEY")
HINT = C.value("GENERATE_HINT_TEXT")
METHOD = re.search(r"\n    (handleGenerateKey\(.*?\n    \}),\n", EDITOR, re.S).group(1)


def run(ev, target="BODY", disabled=False, generating=False, dialog=False):
    js = C.prelude() + """
const ed = { showNewDialog: %s, showOpenDialog: false, generating: %s,
  isTypingTarget(t) { return !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || !!t.isContentEditable); },
  $refs: { generateBtn: { disabled: %s, click() { clicks++; } } },
  %s };
let clicks = 0, prevented = 0;
const e = Object.assign({ metaKey:false, ctrlKey:false, altKey:false, shiftKey:false, preventDefault(){ prevented++; } }, %s,
  { target: { tagName: %s } });
const r = ed.handleGenerateKey(e);
console.log(JSON.stringify({ r, clicks, prevented }));
""" % (json.dumps(dialog), json.dumps(generating), json.dumps(disabled), METHOD, json.dumps(ev), json.dumps(target))
    return json.loads(subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout)


def test_plain_key_clicks():
    assert run({"key": KEY}) == {"r": True, "clicks": 1, "prevented": 1}
    assert run({"key": KEY.upper()})["clicks"] == 1


@pytest.mark.parametrize("tag", ["INPUT", "TEXTAREA", "SELECT"])
def test_plain_key_ignored_in_fields(tag):
    assert run({"key": KEY}, target=tag) == {"r": False, "clicks": 0, "prevented": 0}


@pytest.mark.parametrize("mod", ["metaKey", "ctrlKey"])
def test_cmd_ctrl_works_in_field_and_prevents_default(mod):
    assert run({"key": KEY, mod: True}, target="INPUT") == {"r": True, "clicks": 1, "prevented": 1}


def test_alt_ignored():
    assert run({"key": KEY, "altKey": True})["clicks"] == 0


def test_disabled_or_generating_is_noop():
    assert run({"key": KEY}, disabled=True)["clicks"] == 0
    assert run({"key": KEY}, generating=True)["clicks"] == 0


def test_dialog_open_ignored():
    assert run({"key": KEY}, dialog=True)["clicks"] == 0


def test_other_key_ignored():
    assert run({"key": "x"})["r"] is False


def test_hint_in_button_and_wired():
    assert "GENERATE_HINT_TEXT" in EDITOR and 'x-ref="generateBtn"' in EDITOR
    assert 'x-text="GENERATE_KEY_LABEL"' in EDITOR
    assert KEY.upper() in HINT
    assert "if (this.handleGenerateKey(e)) return;" in EDITOR
