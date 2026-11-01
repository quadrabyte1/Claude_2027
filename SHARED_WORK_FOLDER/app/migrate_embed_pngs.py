#!/usr/bin/env python3
"""Back-fill the embedded heat-map PNG (v6.21) into existing EGMs.

For every ``<GolfCourses>/<Course>/EGMs/*.egm`` that has no valid ``embeddedImage`` block, find its
source PNG (same search order as the editor: imageCourse, course, the EGM's own course, every other
course Images/, team_inbox, owner_inbox), embed it, and write the EGM back (JSON, indent = the
editor's).  A backup copy ``<name>.egm.<BACKUP_SUFFIX>`` is written BEFORE any modification and the
rewrite is atomic (temp file + rename).  EGMs whose PNG cannot be found are listed, never failed.

    python3 migrate_embed_pngs.py --dry-run     # report only, touches nothing
    python3 migrate_embed_pngs.py               # real run (backup + embed)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from typing import Any

import egm_embed
import heatmap_degrid

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, ".."))
DIR_GOLF_COURSES_PARENT = "ItWentIn"
DIR_GOLF_COURSES = "GolfCourses"
DEFAULT_BASE = os.path.join(REPO_ROOT, DIR_GOLF_COURSES_PARENT, DIR_GOLF_COURSES)
DIR_TEAM_INBOX = "team_inbox"
DIR_OWNER_INBOX = "owner_inbox"
SUBDIR_EGMS = "EGMs"
SUBDIR_IMAGES = "Images"
EXT_EGM = ".egm"
EGM_JSON_INDENT = 2
BACKUP_SUFFIX = ".pre_embed.bak"
TMP_SUFFIX = ".tmp"
ENCODING = "utf-8"

# result statuses
ST_EMBEDDED = "embedded"            # real run: block written
ST_WOULD_EMBED = "would_embed"      # dry run
ST_ALREADY = "already_embedded"
ST_NO_IMAGE_FIELD = "no_image_field"
ST_PNG_MISSING = "png_missing"
ST_UNREADABLE = "unreadable"
ST_NOT_PNG = "not_a_png"
ST_ORDER = (ST_EMBEDDED, ST_WOULD_EMBED, ST_ALREADY, ST_PNG_MISSING, ST_NO_IMAGE_FIELD, ST_NOT_PNG, ST_UNREADABLE)

RES_EGM = "egm"
RES_STATUS = "status"
RES_IMAGE = "image"
RES_PNG_PATH = "png_path"
RES_BACKUP = "backup"
RES_BYTES_ADDED = "bytes_added"
RES_DETAIL = "detail"

EXIT_OK = 0
USAGE_DESC = __doc__.split("\n")[0]


def _images_dir(base: str, course: str) -> str:
    return os.path.join(base, course, SUBDIR_IMAGES)


def _course_of_egm(egm_path: str, base: str) -> str:
    egm_dir = os.path.dirname(os.path.abspath(egm_path))
    root = os.path.dirname(egm_dir)
    if os.path.basename(egm_dir) == SUBDIR_EGMS and os.path.realpath(os.path.dirname(root)) == os.path.realpath(base):
        return os.path.basename(root)
    return ""


def candidate_dirs(data: dict, egm_path: str, base: str, extra_dirs: list[str]) -> list[str]:
    """Folders searched for the PNG, most specific first."""
    names: list[str] = []
    for n in (data.get(egm_embed.KEY_EGM_IMAGE_COURSE), data.get("course"), _course_of_egm(egm_path, base)):
        if n and n not in names:
            names.append(n)
    if os.path.isdir(base):
        names += [n for n in sorted(os.listdir(base)) if n not in names]
    dirs = [_images_dir(base, n) for n in names] + list(extra_dirs)
    return [d for d in dirs if os.path.isdir(d)]


def find_source_png(data: dict, egm_path: str, base: str, extra_dirs: list[str]) -> str | None:
    """Path of the ORIGINAL (non-degridded) PNG for this EGM, or None."""
    image = data.get(egm_embed.KEY_EGM_IMAGE)
    if not egm_embed.safe_filename(image):
        return None
    stem, ext = os.path.splitext(image)
    names = [image]
    if stem.endswith(heatmap_degrid.DEGRID_SUFFIX):     # EGM names a cleaned copy -> prefer the original
        names.insert(0, stem[: -len(heatmap_degrid.DEGRID_SUFFIX)] + ext)
    for d in candidate_dirs(data, egm_path, base, extra_dirs):
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
    return None


def _source_course(png_path: str, base: str) -> str:
    folder = os.path.abspath(os.path.dirname(png_path))
    parent, leaf = os.path.split(folder)
    if leaf == SUBDIR_IMAGES and os.path.realpath(os.path.dirname(parent)) == os.path.realpath(base):
        return os.path.basename(parent)
    return ""


def _backup_path(egm_path: str) -> str:
    path = egm_path + BACKUP_SUFFIX
    n = 1
    while os.path.exists(path):          # never clobber an earlier backup
        n += 1
        path = f"{egm_path}{BACKUP_SUFFIX}{n}"
    return path


def migrate_one(egm_path: str, base: str, extra_dirs: list[str], dry_run: bool) -> dict[str, Any]:
    res: dict[str, Any] = {RES_EGM: egm_path, RES_STATUS: None, RES_IMAGE: None, RES_PNG_PATH: None,
                           RES_BACKUP: None, RES_BYTES_ADDED: 0, RES_DETAIL: ""}
    try:
        with open(egm_path, encoding=ENCODING) as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError) as exc:
        res.update({RES_STATUS: ST_UNREADABLE, RES_DETAIL: str(exc)})
        return res
    res[RES_IMAGE] = data.get(egm_embed.KEY_EGM_IMAGE)
    if egm_embed.has_valid_embedded(data):
        res[RES_STATUS] = ST_ALREADY
        return res
    if not data.get(egm_embed.KEY_EGM_IMAGE):
        res[RES_STATUS] = ST_NO_IMAGE_FIELD
        return res
    png = find_source_png(data, egm_path, base, extra_dirs)
    if png is None:
        res[RES_STATUS] = ST_PNG_MISSING
        return res
    res[RES_PNG_PATH] = png
    with open(png, "rb") as fh:
        raw = fh.read()
    if not raw.startswith(egm_embed.PNG_SIGNATURE):
        res.update({RES_STATUS: ST_NOT_PNG, RES_DETAIL: "file does not start with the PNG signature"})
        return res
    block = egm_embed.build_block(raw, os.path.basename(png), _source_course(png, base))
    original_size = os.path.getsize(egm_path)
    if dry_run:
        res[RES_STATUS] = ST_WOULD_EMBED
        res[RES_BYTES_ADDED] = len(json.dumps(block)) 
        return res
    backup = _backup_path(egm_path)
    shutil.copy2(egm_path, backup)                      # backup BEFORE any change
    if os.path.getsize(backup) != original_size:
        raise RuntimeError(f"backup size mismatch for {egm_path}")
    data[egm_embed.KEY_EGM_IMAGE] = block[egm_embed.KEY_EMB_FILENAME]
    data[egm_embed.KEY_EMBEDDED_IMAGE] = block
    tmp = egm_path + TMP_SUFFIX
    with open(tmp, "w", encoding=ENCODING) as fh:
        json.dump(data, fh, indent=EGM_JSON_INDENT)
    os.replace(tmp, egm_path)
    res.update({RES_STATUS: ST_EMBEDDED, RES_BACKUP: backup, RES_BYTES_ADDED: os.path.getsize(egm_path) - original_size})
    return res


def find_egms(base: str) -> list[str]:
    out = []
    if os.path.isdir(base):
        for course in sorted(os.listdir(base), key=str.casefold):
            d = os.path.join(base, course, SUBDIR_EGMS)
            if os.path.isdir(d):
                out += [os.path.join(d, f) for f in sorted(os.listdir(d), key=str.casefold) if f.endswith(EXT_EGM)]
    return out


def migrate(base: str = DEFAULT_BASE, extra_dirs: list[str] | None = None, dry_run: bool = True) -> list[dict[str, Any]]:
    if extra_dirs is None:
        extra_dirs = [os.path.join(REPO_ROOT, DIR_TEAM_INBOX), os.path.join(REPO_ROOT, DIR_OWNER_INBOX)]
    return [migrate_one(p, base, extra_dirs, dry_run) for p in find_egms(base)]


def format_report(results: list[dict[str, Any]], dry_run: bool) -> str:
    lines = [f"EGM PNG embed migration ({'DRY RUN' if dry_run else 'REAL RUN'}): {len(results)} EGM(s)"]
    for st in ST_ORDER:
        group = [r for r in results if r[RES_STATUS] == st]
        if not group:
            continue
        lines.append(f"\n[{st}] {len(group)}")
        for r in group:
            extra = r[RES_PNG_PATH] or r[RES_DETAIL] or ""
            if r[RES_BACKUP]:
                extra += f"  (backup: {r[RES_BACKUP]}, +{r[RES_BYTES_ADDED]} bytes)"
            lines.append(f"  {r[RES_EGM]}  image={r[RES_IMAGE]!r}  {extra}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=USAGE_DESC)
    ap.add_argument("--dry-run", action="store_true", help="report only; modify nothing")
    ap.add_argument("--base", default=DEFAULT_BASE, help="GolfCourses folder")
    args = ap.parse_args(argv)
    results = migrate(args.base, dry_run=args.dry_run)
    print(format_report(results, args.dry_run))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
