"""Editor v5.83: Cmd/Ctrl+C / Cmd/Ctrl+V copy and paste of grid cells.

Same technique as test_editor_paint_mode.py: the real constants block and the real methods are cut out of
templates/editor.html and run in node against a mock editor object.  No server, no DB, no EGM files.
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

METHODS = ["_gridSelectionList", "_gridClipKeyOk", "copyGridCells", "pasteGridCells", "applyGridPattern",
           "pushGridUndo", "_trimUndo", "gridUndoSnapshot", "undo", "_undoGridEntry", "cancelGridCell"]
COPY_KEY, PASTE_KEY = C.value("GRID_COPY_KEY"), C.value("GRID_PASTE_KEY")
CLIP_TYPE = C.value("GRID_CLIP_TYPE")


def _method(name):
    m = re.search(r"\n    (%s\(.*?\n    \}),\n" % re.escape(name), EDITOR, re.S)
    assert m, name + " missing"
    return m.group(1)


def _handle_key():
    i = EDITOR.index("    handleKey(e) {")
    j = EDITOR.index("\n    },\n  };\n}", i)
    return EDITOR[i:j + len("\n    }")]


def _run(script, state="", clipboard="null"):
    body = ",\n".join(_handle_key() if n == "handleKey" else _method(n) for n in METHODS + ["handleGenerateKey", "handleKey"])
    js = C.prelude() + """
const clipLog = [];
let clipText = %s;
Object.defineProperty(globalThis, 'navigator', {value: {clipboard: CLIPAPI}, configurable: true});
const o = {
  gridMode:'delta', gridN:20, gridCellHeights:{}, _gridClipPattern:null,
  undoHistory:[], redoStack:[], maxUndo:100,
  _gridActiveCell:null, _gridMultiSelect:null, _gridMultiSelectAnchor:null, _gridHoveredCell:null, _gridInputValue:'',
  showNewDialog:false, showOpenDialog:false, contourMode:false, paintMode:false,
  $refs:{gridCellInput:{tagName:'INPUT'}},
  saves:0, draws:0, flashes:[],
  draw(){this.draws++}, autoSave(){this.saves++}, flash(m){this.flashes.push(m)},
};
%s
const M = {%s};
for (const k in M) Object.defineProperty(o, k, Object.getOwnPropertyDescriptor(M, k));
""" % (clipboard, state, body)
    js = js.replace("CLIPAPI", "{writeText(t){clipText=t; clipLog.push(t); return Promise.resolve()}, "
                    "readText(){return clipText===null?Promise.reject(new Error('denied')):Promise.resolve(clipText)}}")
    out = subprocess.run([node, "-e", js + script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _ev(key, tag="DIV", **kw):
    d = {"key": key, "target": {"tagName": tag}, "metaKey": True, "ctrlKey": False, "altKey": False, "shiftKey": False}
    d.update(kw)
    return "Object.assign(%s, {preventDefault(){this.pd=true}})" % json.dumps(d)


SELECT_L = "o._gridMultiSelect = new Set([21, 22, 42]); o.gridCellHeights = {21: 3.5, 22: 0, 42: -2};"   # 22 is explicit 0, 42 last


def test_copy_stores_offsets_values_and_explicit_zero_relative_to_last_selected():
    r = _run(SELECT_L + """
      const e = %s; o.handleKey(e);
      console.log(JSON.stringify({pd: e.pd, mem: o._gridClipPattern, clip: JSON.parse(clipLog[0])}));""" % _ev(COPY_KEY))
    assert r["pd"] and r["mem"] == r["clip"] and r["clip"]["type"] == CLIP_TYPE
    cells = {(c["dc"], c["dr"]): c["val"] for c in r["clip"]["cells"]}
    # anchor = idx 42 (col 2,row 2): idx21 = (1,1) -> (-1,-1); idx22 = (2,1) -> (0,-1); anchor itself (0,0)
    assert cells == {(-1, -1): 3.5, (0, -1): 0, (0, 0): -2}


def test_ctrl_key_works_like_meta():
    r = _run(SELECT_L + "const e = %s; o.handleKey(e); console.log(JSON.stringify({pd: e.pd}));" %
             _ev(COPY_KEY, metaKey=False, ctrlKey=True))
    assert r["pd"]


def test_paste_translates_pattern_to_most_recent_cell_with_values_and_single_undo_step():
    r = _run(SELECT_L + """
      o.handleKey(%s);
      o._gridMultiSelect = null; o._gridActiveCell = {idx: 5*20+10, col:10, row:5};   // paste anchor (10,5)
      o.gridCellHeights[5*20+10] = 9;
      const before = Object.assign({}, o.gridCellHeights);
      const e = %s; o.handleKey(e);
      await_();
      function await_() {}
      Promise.resolve().then(() => Promise.resolve()).then(() => setTimeout(() => {
        const hist = o.undoHistory.length;
        o.undo();
        console.log(JSON.stringify({pd: e.pd, hist, after: null, flashes: o.flashes, saves: o.saves,
          restored: o.gridCellHeights, before}));
      }, 0));""" % (_ev(COPY_KEY), _ev(PASTE_KEY)))
    assert r["pd"] and r["hist"] == 1 and r["saves"] >= 2
    assert r["restored"] == r["before"]       # one undo step restores everything (incl. the overwritten 9)


def test_paste_values_land_at_translated_cells_and_selection_closes():
    r = _run(SELECT_L + """
      o.handleKey(%s);
      o._gridMultiSelect = null; o._gridActiveCell = {idx: 5*20+10, col:10, row:5};
      o.handleKey(%s);
      setTimeout(() => console.log(JSON.stringify({h: o.gridCellHeights, sel: o._gridActiveCell, draws: o.draws,
        hist: o.undoHistory.length})), 0);""" % (_ev(COPY_KEY), _ev(PASTE_KEY)))
    h = r["h"]
    assert h["89"] == 3.5 and h["90"] == 0 and h["110"] == -2     # (9,4) (10,4) (10,5); explicit 0 kept as key
    assert r["sel"] is None and r["draws"] >= 1 and r["hist"] == 1


def test_cells_outside_grid_are_skipped():
    r = _run("""
      o._gridClipPattern = {type: GRID_CLIP_TYPE, v: 1, gridN: 20, cells:[{dc:0,dr:0,val:1},{dc:1,dr:0,val:2},{dc:0,dr:1,val:3}]};
      o._gridActiveCell = {idx: 19, col:19, row:0};            // right edge, bottom row
      o.applyGridPattern(o._gridClipPattern, 19);
      console.log(JSON.stringify(o.gridCellHeights));""")
    assert r == {"19": 1, "39": 3}


def test_system_clipboard_denied_falls_back_to_memory_copy():
    r = _run(SELECT_L + """
      o.handleKey(%s);
      clipText = null;                                         // readText now rejects (permission denied)
      o._gridMultiSelect = null; o._gridActiveCell = {idx: 5*20+10, col:10, row:5};
      o.handleKey(%s);
      setTimeout(() => console.log(JSON.stringify(o.gridCellHeights)), 0);""" % (_ev(COPY_KEY), _ev(PASTE_KEY)))
    assert r["110"] == -2 and r["89"] == 3.5


def test_paste_reads_tagged_system_clipboard_when_memory_empty():
    payload = json.dumps({"type": CLIP_TYPE, "v": 1, "gridN": 20, "cells": [{"dc": 0, "dr": 0, "val": 7}]})
    r = _run("o._gridActiveCell = {idx: 44, col:4, row:2}; o.handleKey(%s); setTimeout(() => console.log(JSON.stringify(o.gridCellHeights)), 0);"
             % _ev(PASTE_KEY), clipboard=json.dumps(payload))
    assert r == {"44": 7}


def test_non_tagged_clipboard_text_is_ignored():
    r = _run("o._gridClipPattern = null; o._gridActiveCell = {idx: 44, col:4, row:2}; o.handleKey(%s);"
             " setTimeout(() => console.log(JSON.stringify({h:o.gridCellHeights, f:o.flashes})), 0);" % _ev(PASTE_KEY),
             clipboard='"hello"')
    assert r["h"] == {}


def test_text_fields_keep_native_copy_paste():
    for tag in ("INPUT", "TEXTAREA"):
        r = _run(SELECT_L + "const e = %s; o.handleKey(e); console.log(JSON.stringify({pd: !!e.pd, mem: o._gridClipPattern}));"
                 % _ev(COPY_KEY, tag=tag))
        assert not r["pd"] and r["mem"] is None
        r = _run("o._gridClipPattern={type:GRID_CLIP_TYPE,gridN:20,cells:[]}; o._gridActiveCell={idx:1,col:1,row:0};"
                 "const e = %s; o.handleKey(e); console.log(JSON.stringify({pd: !!e.pd}));" % _ev(PASTE_KEY, tag=tag))
        assert not r["pd"]


def test_untouched_grid_value_box_lets_copy_act_on_cells_but_typed_text_stays_native():
    r = _run(SELECT_L + """
      const box = o.$refs.gridCellInput; box.value = '3.5'; box.selectionStart = 0; box.selectionEnd = 3;
      const e1 = Object.assign(%s, {target: box}); o.handleKey(e1);
      box.selectionStart = 1; box.selectionEnd = 1;
      const e2 = Object.assign(%s, {target: box}); o.handleKey(e2);
      console.log(JSON.stringify({a: !!e1.pd, b: !!e2.pd}));""" % (_ev(COPY_KEY), _ev(COPY_KEY)))
    assert r == {"a": True, "b": False}


def test_nothing_selected_means_no_hijack():
    r = _run("const e = %s; o.handleKey(e); const f = %s; o.handleKey(f); console.log(JSON.stringify({a: !!e.pd, b: !!f.pd}));"
             % (_ev(COPY_KEY), _ev(PASTE_KEY)))
    assert r == {"a": False, "b": False}


def test_resolution_mismatch_is_refused_without_changes():
    r = _run("o.gridN = 40; const ok = o.applyGridPattern({type: GRID_CLIP_TYPE, gridN: 20, cells:[{dc:0,dr:0,val:1}]}, 5);"
             " console.log(JSON.stringify({ok, h: o.gridCellHeights, hist: o.undoHistory.length}));")
    assert r == {"ok": False, "h": {}, "hist": 0}


def test_version_bumped_and_constants_defined_once():
    app = (APP_DIR / "app.py").read_text()
    version = re.search(r'^APP_VERSION = "([^"]+)"', app, re.M).group(1)   # single source of truth: app.py
    assert "Boundary Editor " + version in EDITOR
    for name in ("GRID_COPY_KEY", "GRID_PASTE_KEY", "GRID_CLIP_TYPE"):
        assert len(re.findall(r"^const %s\b" % name, EDITOR, re.M)) == 1
    assert EDITOR.count(CLIP_TYPE) == 1
