"""Editor v5.81: the canvas must fit its (palette-narrowed) container and cover the whole expanded image.

Real resizeCanvas() body is run in node against a mock editor; the ResizeObserver wiring is checked in source.
No server, no DB, no EGM files.
"""
import json, re, shutil, subprocess, sys
from pathlib import Path
import pytest

APP_DIR = Path(__file__).parent.parent
EDITOR = (APP_DIR / "templates" / "editor.html").read_text()
sys.path.insert(0, str(Path(__file__).parent))
import editor_constants as C

node = shutil.which("node")
pytestmark = pytest.mark.skipif(not node, reason="node not installed")


def _fit(container_w, win_h, img_w=809, img_h=1057):
    m = re.search(r"\n    (resizeCanvas\(\) \{.*?\n    \}),\n", EDITOR, re.S)
    js = C.prelude() + """
const style = {};
const canvas = {width:0, height:0, style, parentElement:{clientWidth:%s}};
const o = {imgLoaded:true, imgW:%d, imgH:%d, printSizeMm:PRINT_SIZE_MM_DEFAULT_PLACEHOLDER, fringeXyExpansionMm:FRINGE_XY_EXPANSION_MM_PLACEHOLDER,
  $refs:{canvas}, draw(){}, %s};
global.window = {innerHeight:%s, devicePixelRatio:1};
o.resizeCanvas();
const ew = o.imgW + 2*o.fringePadXpx, eh = o.imgH + 2*o.fringePadYpx;
console.log(JSON.stringify({cw:parseFloat(style.width), ch:parseFloat(style.height), scale:o.scale, ew, eh, offX:o.offsetX, imgW:o.imgW}));
""" % (container_w, img_w, img_h, m.group(1), win_h)
    js = js.replace("PRINT_SIZE_MM_DEFAULT_PLACEHOLDER", "(typeof PRINT_SIZE_MM !== 'undefined' ? PRINT_SIZE_MM : 179.25)")
    js = js.replace("FRINGE_XY_EXPANSION_MM_PLACEHOLDER", "(typeof FRINGE_XY_EXPANSION_MM !== 'undefined' ? FRINGE_XY_EXPANSION_MM : 30)")
    out = subprocess.run([node, "-e", js], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("container_w", [822, 894, 1014, 400])
@pytest.mark.parametrize("win_h", [800, 1400, 1800])
def test_canvas_never_wider_than_container_and_covers_image(container_w, win_h):
    r = _fit(container_w, win_h)
    assert r["cw"] <= container_w + 1e-6
    assert abs(r["scale"] * r["ew"] - r["cw"]) < 0.01 and abs(r["scale"] * r["eh"] - r["ch"]) < 0.01   # aspect kept
    assert r["offX"] + r["imgW"] * r["scale"] <= r["cw"] + 1e-6                                       # image fully inside


def test_container_width_changes_trigger_a_remeasure():
    """Palette show/hide changes the container width after the first measure -> ResizeObserver re-runs resizeCanvas."""
    assert "new ResizeObserver(" in EDITOR and "CANVAS_RESIZE_EPSILON_PX" in EDITOR
    i = EDITOR.index("new ResizeObserver(")
    assert "this.resizeCanvas()" in EDITOR[i:i + 400] and ".observe(box)" in EDITOR[i:i + 500]
