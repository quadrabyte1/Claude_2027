"""Editor v5.88: the green boundary polygon is drawn in COLOR_POLY_GREEN (purple), whatever colour is stored on it.

Constants come from the real editor constants block via editor_constants; the real draw loop's colour selection is
checked by source, and polyColorForType is run in node.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import editor_constants as C

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
LEGACY_GREEN = "#22C55E"  # the pre-v5.88 stored colour in old EGMs (test fixture only; the editor no longer defines it)


def _run(expr):
    js = C.prelude() + "\n" + C.EDITOR_PATH.read_text().split("function polyColorForType", 1)[1].join(
        ["function polyColorForType", ""]).split("function isRemovablePolyType")[0] + "\nconsole.log(JSON.stringify(%s));" % expr
    out = subprocess.run([C.NODE, "-e", js], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_green_type_maps_to_constant():
    assert _run("polyColorForType(POLY_TYPE_GREEN)") == C.value("COLOR_POLY_GREEN")


def test_green_constant_is_no_longer_green():
    assert C.value("COLOR_POLY_GREEN").upper() != LEGACY_GREEN


def test_green_colour_distinct_from_other_polygon_colours():
    g = C.value("COLOR_POLY_GREEN")
    for n in ("COLOR_POLY_WATER", "COLOR_POLY_BOULDERS", "COLOR_POLY_TRAP", "COLOR_CONTOUR", "COLOR_PALETTE_SELECTED"):
        assert g.upper() != C.value(n).upper()


def test_draw_uses_type_colour_not_stored_colour():
    src = C.EDITOR_PATH.read_text()
    body = src.split("// Draw polygons", 1)[1].split("// Vertices", 1)[0]
    assert "polyColorForType(poly.type)" in body
    assert "poly.color" not in re.sub(r"//.*", "", body)  # legacy stored colour is never drawn
    verts = src.split("// Vertices", 1)[1][:1500]
    assert "poly.color" not in re.sub(r"//.*", "", verts)


def test_default_green_polygon_uses_constant():
    assert "color: COLOR_POLY_GREEN" in C.EDITOR_PATH.read_text()
