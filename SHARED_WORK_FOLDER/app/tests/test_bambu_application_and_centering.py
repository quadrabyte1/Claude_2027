"""
Regression tests: generated Bambu 3MFs must
  R1. carry exactly one <metadata name="Application">BambuStudio-<ver></metadata>
      (without it Bambu Studio refuses project_settings.config and shows
      "The 3mf file has invalid config, load geometry data only"),
  R2. have every plate-1 <build> item translated to the A1 bed centre (128,128),
      derived from project_settings.config printable_area,
  R3. be idempotent (second injection: no duplicate tag, no double shift).
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_bambu_config_injection import _load_gsd_module, _make_minimal_trimesh_3mf  # noqa: E402


@pytest.fixture(scope="module")
def gsd():
    try:
        return _load_gsd_module()
    except Exception as exc:
        pytest.skip(f"gradient_surface_diagnostic unavailable: {exc}")


def _make_3mf(path: Path, names):
    data = _make_minimal_trimesh_3mf(names)
    src = zipfile.ZipFile(__import__("io").BytesIO(data))
    model = src.read("3D/3dmodel.model").decode()
    items = "".join(
        f'<item objectid="{i}" transform="1.0 0.0 0.0 0.0 1.0 0.0 0.0 0.0 1.0 0.0 0.0 0.0"/>'
        for i in range(1, len(names) + 1)
    )
    model = model.replace("<build/>", f"<build>{items}</build>")
    with zipfile.ZipFile(path, "w") as zf:
        for n in src.namelist():
            zf.writestr(n, model if n == "3D/3dmodel.model" else src.read(n))


def _model(path):
    with zipfile.ZipFile(path) as zf:
        return zf.read("3D/3dmodel.model").decode()


def _translations(xml):
    out = []
    for m in re.finditer(r'<item\b[^>]*\btransform="([^"]*)"', xml):
        v = m.group(1).split()
        out.append((float(v[9]), float(v[10]), float(v[11])))
    return out


NAMES = ["green_surface", "fairway"]


def test_application_tag_exactly_once_before_3mfversion(gsd, tmp_path):
    p = tmp_path / "a.3mf"
    _make_3mf(p, NAMES)
    gsd._inject_bambu_extruder_metadata(str(p), NAMES)
    xml = _model(p)
    assert xml.count('<metadata name="Application">BambuStudio-02.08.02.61</metadata>') == 1
    assert xml.count('name="Application"') == 1
    assert xml.index('name="Application"') < xml.index('name="BambuStudio:3mfVersion"')


def test_build_items_centred_on_bed(gsd, tmp_path):
    p = tmp_path / "b.3mf"
    _make_3mf(p, NAMES)
    gsd._inject_bambu_extruder_metadata(str(p), NAMES)
    t = _translations(_model(p))
    assert len(t) == 2
    assert all(x == (128.0, 128.0, 0.0) for x in t), t


def test_injection_idempotent(gsd, tmp_path):
    p = tmp_path / "c.3mf"
    _make_3mf(p, NAMES)
    gsd._inject_bambu_extruder_metadata(str(p), NAMES)
    gsd._inject_bambu_extruder_metadata(str(p), NAMES)
    xml = _model(p)
    assert xml.count('name="Application"') == 1
    assert xml.count('name="BambuStudio:3mfVersion"') == 1
    assert all(x == (128.0, 128.0, 0.0) for x in _translations(xml))
