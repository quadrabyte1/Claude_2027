"""Editor v6.00: the Degridded segment must be available whenever an image is loaded (Open Project too).

Bug (v5.99): loadImage() asked the server for the degridded copy only for Create New Project
(_pendingDegrid), so after Open Project degridUrls stayed null and the Degridded button was hidden.
The REAL loadImage() is cut out of templates/editor.html and run in node with a mocked fetch.
Run: python -m pytest app/tests/test_editor_degrid_on_open.py -v
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

V_ORIG, V_CLEAN, V_HIDE = C.value("DEGRID_VIEW_ORIGINAL"), C.value("DEGRID_VIEW_CLEAN"), C.value("DEGRID_VIEW_HIDE")
API_URL = C.value("DEGRID_API_URL")
ORIG_URL, CLEAN_URL = "/img/a.png", "/img/a__degridded.png"
FOUND = {"status": "ok", "found": True, "originalUrl": ORIG_URL, "degriddedUrl": CLEAN_URL}
NOT_FOUND = {"status": "ok", "found": False, "originalUrl": ORIG_URL, "degriddedUrl": None}


def _method(name):
    m = re.search(r"\n    (%s\(.*?\n    \}),\n" % re.escape(name), EDITOR, re.S)
    assert m, name + " missing"
    return m.group(1)


def _run(pending, view, response):
    js = C.prelude() + """
const fetched = [];
globalThis.fetch = (url, opts) => { fetched.push(url); return Promise.resolve({json: () => Promise.resolve(%s)}); };
const o = {selectedImage: 'a.png', selectedImageCourse: 'C', degridUrls: null, imageView: %s, imgLoaded: true,
  _pendingDegrid: %s, _degridTabId: 't', _degridHeld: null, nowLoads: 0, _loadImageNow() { this.nowLoads++; }};
const M = {%s};
for (const k in M) Object.defineProperty(o, k, Object.getOwnPropertyDescriptor(M, k));
o.loadImage();
setTimeout(() => console.log(JSON.stringify({fetched, urls: o.degridUrls, view: o.imageView, loads: o.nowLoads})), 20);
""" % (json.dumps(response), json.dumps(view), json.dumps(pending), _method("loadImage") + "," + _method("_requestDegrid") + "," + _method("releaseDegrid"))
    out = subprocess.run([node, "-e", js], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_open_project_gets_degridded_copy():
    r = _run(False, V_ORIG, FOUND)
    assert r["fetched"] == [API_URL]
    assert r["urls"] == {"original": ORIG_URL, "degridded": CLEAN_URL}
    assert r["view"] == V_ORIG          # Open Project keeps the user's current view
    assert r["loads"] == 1


def test_open_project_keeps_hide_and_clean_views():
    assert _run(False, V_HIDE, FOUND)["view"] == V_HIDE
    assert _run(False, V_CLEAN, FOUND)["view"] == V_CLEAN


def test_open_project_clean_view_falls_back_when_not_found():
    r = _run(False, V_CLEAN, NOT_FOUND)
    assert r["urls"] is None and r["view"] == V_ORIG and r["loads"] == 1


def test_create_new_defaults_to_degridded():
    r = _run(True, V_ORIG, FOUND)
    assert r["urls"] and r["view"] == V_CLEAN and r["loads"] == 1


def test_create_new_hide_is_kept():
    assert _run(True, V_HIDE, FOUND)["view"] == V_HIDE


def test_server_route_creates_copy_on_demand():
    app_src = (APP_DIR / "app.py").read_text()
    assert "heatmap_degrid.degrid_file(img_path, out_path)" in app_src   # generated if missing/stale


def test_markup_order_original_degridded_hide():
    i = EDITOR.index('data-testid="degrid-view-switch"')
    block = EDITOR[i:i + 1800]
    assert block.index("DEGRID_LABEL_ORIGINAL") < block.index("DEGRID_LABEL_CLEAN") < block.index("DEGRID_LABEL_HIDE")
