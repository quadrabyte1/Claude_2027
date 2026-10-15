#!/usr/bin/env python3
"""Idempotently patch existing generated Bambu 3MFs in place.

Adds <metadata name="Application">BambuStudio-<ver></metadata> (before the
3mfVersion metadata) if missing, and moves build items still at translation
x=y=0 to the bed centre (128,128). Skips files without BambuStudio:3mfVersion.
Usage: patch_bambu_3mfs.py [root ...]   (default: ItWentIn/GolfCourses)
"""
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

CENTER = (128.0, 128.0)  # A1 printable_area 0x0..256x256
VER_RE = re.compile(r'<metadata name="BambuStudio:3mfVersion">([^<]*)</metadata>')


def patch_xml(xml, skip_oids=frozenset()):
    """Return (new_xml, changed) or (None, False) if not a Bambu-flagged model."""
    m = VER_RE.search(xml)
    if not m:
        return None, False
    new = xml
    if 'name="Application"' not in new:
        new = new[:m.start()] + f'<metadata name="Application">BambuStudio-{m.group(1)}</metadata>' + new[m.start():]

    def shift(mm):
        tag = mm.group(0)
        om = re.search(r'\bobjectid="([^"]*)"', tag)
        if om and om.group(1) in skip_oids:
            return tag  # plate-2 objects: layout left as generated
        tm = re.search(r'\btransform="([^"]*)"', tag)
        if not tm:
            return tag
        v = tm.group(1).split()
        if len(v) != 12:
            return tag
        try:
            if abs(float(v[9])) > 1e-9 or abs(float(v[10])) > 1e-9:
                return tag
        except ValueError:
            return tag
        v[9], v[10] = repr(CENTER[0]), repr(CENTER[1])
        return tag[:tm.start(1)] + " ".join(v) + tag[tm.end(1):]

    new = re.sub(r"<item\b[^>]*>", shift, new)
    return new, new != xml


def patch_file(path):
    with zipfile.ZipFile(path) as zin:
        if "3D/3dmodel.model" not in zin.namelist():
            return "skipped"
        xml = zin.read("3D/3dmodel.model").decode("utf-8")
        skip = frozenset()
        if "Metadata/model_settings.config" in zin.namelist():
            cfg = zin.read("Metadata/model_settings.config").decode("utf-8", "replace")
            for pm in re.finditer(r"<plate>.*?</plate>", cfg, re.S):
                if 'key="plater_id" value="2"' in pm.group(0):
                    skip = frozenset(re.findall(r'key="object_id" value="([^"]*)"', pm.group(0)))
        new, changed = patch_xml(xml, skip)
        if new is None:
            return "skipped"
        if not changed:
            return "ok"
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        os.close(fd)
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
                for info in zin.infolist():
                    data = new.encode("utf-8") if info.filename == "3D/3dmodel.model" else zin.read(info.filename)
                    zout.writestr(info, data)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    return "patched"


def main(argv):
    roots = [Path(a) for a in argv] or [Path(__file__).resolve().parent.parent / "ItWentIn" / "GolfCourses"]
    counts = {"patched": 0, "ok": 0, "skipped": 0}
    for root in roots:
        for p in sorted(root.glob("**/3MFs/*.3mf")):
            try:
                r = patch_file(str(p))
            except zipfile.BadZipFile:
                r = "skipped"
            counts[r] += 1
            if r != "ok":
                print(f"{r}: {p}")
    print(f"patched={counts['patched']} already-OK={counts['ok']} skipped={counts['skipped']}")


if __name__ == "__main__":
    main(sys.argv[1:])
