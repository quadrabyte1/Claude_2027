"""Editor v5.99: image view switch gets a third segment, Hide (heat-map PNG not drawn; cells / boundaries stay).

Same technique as the other editor tests: the real constants block and the REAL methods are cut out of
templates/editor.html and run in node against a mock editor object.  Every literal is read back from the constants.
Run: python -m pytest app/tests/test_editor_image_hide.py -v
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
METHODS = ["setImageView", "_imageSrcKey", "_displayImageUrl", "_drawImageLayer"]


def _method(name):
    m = re.search(r"\n    (%s\(.*?\n    \}),\n" % re.escape(name), EDITOR, re.S)
    assert m, name + " missing"
    return m.group(1)


MOCK = """
const loads = [];
globalThis.Image = function () { loads.push(this); Object.defineProperty(this, 'src', {set: v => { this._src = v; }}); };
const calls = [];
const ctx = {fillRect() { calls.push('fillRect'); }, drawImage() { calls.push('drawImage'); },
  strokeRect() { calls.push('strokeRect'); }, save() {}, restore() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {},
  set fillStyle(v) { calls.push('fill:' + v); }, set strokeStyle(v) {}, set lineWidth(v) {}};
const o = {
  degridUrls: %s, imageView: IMAGE_VIEW_INIT, img: {tag: 'loaded'}, _imgSrcKey: null, selectedImage: 'a.png',
  selectedImageUrl: '/x/orig.png', imgW: 10, imgH: 10, scale: 1, offsetX: 0, offsetY: 0, draws: 0,
  DEGRID_VIEW_ORIGINAL, DEGRID_VIEW_CLEAN, DEGRID_VIEW_HIDE,
  draw() { this.draws++; },
};
const M = {%s};
for (const k in M) Object.defineProperty(o, k, Object.getOwnPropertyDescriptor(M, k));
"""


def _run(script, degrid="{original: '/x/orig.png', degridded: '/x/clean.png'}", init=V_CLEAN):
    body = ",\n".join(_method(n) for n in METHODS)
    js = C.prelude() + "const IMAGE_VIEW_INIT = %s;\n" % json.dumps(init) + MOCK % (degrid, body) + script
    out = subprocess.run([node, "-e", js], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_hide_constants():
    assert C.value("DEGRID_LABEL_HIDE") == "Hide"
    assert len({V_ORIG, V_CLEAN, V_HIDE}) == 3
    assert C.value("COLOR_CANVAS_HIDDEN_BG")


def test_markup_order_and_availability():
    i = EDITOR.index('data-testid="degrid-view-switch"')
    block = EDITOR[i:i + 1800]
    assert block.index("DEGRID_LABEL_ORIGINAL") < block.index("DEGRID_LABEL_CLEAN") < block.index("DEGRID_LABEL_HIDE")
    assert 'data-testid="degrid-view-hide"' in block and "setImageView(DEGRID_VIEW_HIDE)" in block
    assert 'x-show="degridUrls"' not in block.split("class=")[0]   # switch no longer needs a degridded copy
    assert re.search(r'data-testid="degrid-view-clean"[^>]*x-show="degridUrls"|x-show="degridUrls"[^>]*data-testid="degrid-view-clean"',
                     block, re.S) or 'x-show="degridUrls" data-testid="degrid-view-clean"' in block


def test_hide_does_not_refetch_and_draws():
    r = _run("o.setImageView(V_HIDE); console.log(JSON.stringify({view: o.imageView, loads: loads.length, draws: o.draws}));"
             .replace("V_HIDE", "DEGRID_VIEW_HIDE"))
    assert r == {"view": V_HIDE, "loads": 0, "draws": 1}


def test_restore_same_view_is_instant_other_view_loads():
    s = ("o._imgSrcKey = DEGRID_VIEW_CLEAN; o.setImageView(DEGRID_VIEW_HIDE); o.setImageView(DEGRID_VIEW_CLEAN);"
         "const a = loads.length; o.setImageView(DEGRID_VIEW_ORIGINAL);"
         "console.log(JSON.stringify({a, b: loads.length, view: o.imageView}));")
    assert _run(s) == {"a": 0, "b": 1, "view": V_ORIG}


def test_works_without_degridded_copy():
    s = ("o.setImageView(DEGRID_VIEW_HIDE); o._imgSrcKey = DEGRID_VIEW_ORIGINAL; o.setImageView(DEGRID_VIEW_ORIGINAL);"
         "console.log(JSON.stringify({loads: loads.length, view: o.imageView, key: o._imageSrcKey(), url: o._displayImageUrl()}));")
    r = _run(s, degrid="null", init=V_ORIG)
    assert r == {"loads": 0, "view": V_ORIG, "key": V_ORIG, "url": "/x/orig.png"}


def test_stale_degridded_without_copy_means_original():
    r = _run("console.log(JSON.stringify(o._imageSrcKey()));", degrid="null", init=V_CLEAN)
    assert r == V_ORIG


def test_draw_layer_skips_image_when_hidden():
    s = ("const canvas = {width: 100, height: 100};"
         "o.imageView = DEGRID_VIEW_HIDE; o._drawImageLayer(ctx, canvas, 1); const h = calls.slice(); calls.length = 0;"
         "o.imageView = DEGRID_VIEW_ORIGINAL; o._drawImageLayer(ctx, canvas, 1); const s = calls.slice();"
         "console.log(JSON.stringify({h, s}));")
    r = _run(s)
    assert "drawImage" not in r["h"] and "strokeRect" not in r["h"]
    assert "fill:" + C.value("COLOR_CANVAS_HIDDEN_BG") in r["h"]
    assert "drawImage" in r["s"] and "strokeRect" in r["s"]
