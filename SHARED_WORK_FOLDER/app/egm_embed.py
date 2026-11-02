"""Self-contained EGMs (v6.21): an .egm carries its own ORIGINAL heat-map PNG.

The PNG is stored once, as base64, in the EGM's ``embeddedImage`` block together with its original
filename, SHA-256 and byte size.  Readers extract it to a content-addressed cache folder
(``<cache>/<sha256>/<filename>``) so the existing path-based pipelines (degrid, detect, Generate)
can run from a real file without depending on any course Images/ folder.

Pure stdlib, no Flask: shared by app.py, gradient_surface_diagnostic.py, generate_stl_3mf.py and
the migration script (migrate_embed_pngs.py).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
from typing import Any

# -- EGM field names ---------------------------------------------------------------------
KEY_EMBEDDED_IMAGE = "embeddedImage"      # block inside the EGM JSON
KEY_EMB_FILENAME = "filename"             # original heat-map file name (e.g. "Delaveaga (Hole 11, 55171).png")
KEY_EMB_SHA256 = "sha256"                 # hex digest of the PNG bytes
KEY_EMB_SIZE = "sizeBytes"                # PNG byte length
KEY_EMB_ENCODING = "encoding"
KEY_EMB_DATA = "data"                     # the base64 text
KEY_EMB_SOURCE_COURSE = "sourceCourse"    # course folder the PNG was originally read from ('' = team_inbox)
EMB_ENCODING_BASE64 = "base64"
KEY_EGM_IMAGE = "image"
KEY_EGM_IMAGE_COURSE = "imageCourse"

# -- cache -------------------------------------------------------------------------------
CACHE_DIR_NAME = ".embedded_png_cache"
CACHE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), CACHE_DIR_NAME)
SHA256_HEX_LEN = 64
SHA256_RE = re.compile(r"^[0-9a-f]{%d}$" % SHA256_HEX_LEN)
ENCODE_CHARSET = "ascii"

# -- pseudo-course used in the editor's imageCourse while an embedded image is in play ------
EMBEDDED_COURSE_PREFIX = "_embedded_"     # imageCourse == "_embedded_<sha256>"; never persisted to the EGM
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def build_block(png_bytes: bytes, filename: str, source_course: str = "") -> dict[str, Any]:
    """The ``embeddedImage`` block for ``png_bytes``."""
    return {
        KEY_EMB_FILENAME: filename,
        KEY_EMB_SHA256: sha256_hex(png_bytes),
        KEY_EMB_SIZE: len(png_bytes),
        KEY_EMB_ENCODING: EMB_ENCODING_BASE64,
        KEY_EMB_SOURCE_COURSE: source_course or "",
        KEY_EMB_DATA: base64.b64encode(png_bytes).decode(ENCODE_CHARSET),
    }


def block_png_bytes(block: Any) -> bytes | None:
    """Decode and verify a block (hash + size + PNG signature); None if absent or corrupt."""
    if not isinstance(block, dict) or block.get(KEY_EMB_ENCODING) != EMB_ENCODING_BASE64:
        return None
    text = block.get(KEY_EMB_DATA)
    if not isinstance(text, str) or not text:
        return None
    try:
        raw = base64.b64decode(text.encode(ENCODE_CHARSET), validate=True)
    except (binascii.Error, ValueError):
        return None
    if (sha256_hex(raw) != block.get(KEY_EMB_SHA256) or len(raw) != block.get(KEY_EMB_SIZE)
            or not raw.startswith(PNG_SIGNATURE)):
        return None
    return raw


def get_png_bytes(egm_data: dict) -> bytes | None:
    return block_png_bytes((egm_data or {}).get(KEY_EMBEDDED_IMAGE))


def has_valid_embedded(egm_data: dict) -> bool:
    return get_png_bytes(egm_data) is not None


def safe_filename(name: Any) -> bool:
    """A bare file name (no separators / traversal) - the only kind ever joined onto the cache."""
    return (isinstance(name, str) and bool(name) and name == os.path.basename(name)
            and name not in (os.curdir, os.pardir) and "\x00" not in name and "\\" not in name)


def materialize(egm_data: dict, cache_root: str | None = None) -> str | None:
    """Write the embedded PNG to ``<cache>/<sha256>/<filename>`` (once) and return that path, else None."""
    block = (egm_data or {}).get(KEY_EMBEDDED_IMAGE)
    raw = block_png_bytes(block)
    if raw is None or not safe_filename(block.get(KEY_EMB_FILENAME)):
        return None
    folder = os.path.join(cache_root or CACHE_ROOT, block[KEY_EMB_SHA256])
    path = os.path.join(folder, block[KEY_EMB_FILENAME])
    if os.path.isfile(path) and os.path.getsize(path) == len(raw):
        return path
    os.makedirs(folder, exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(raw)
    os.replace(tmp, path)
    return path


def course_token(sha256: str) -> str:
    return EMBEDDED_COURSE_PREFIX + sha256


def sha_from_course_token(course: Any) -> str | None:
    """The sha256 in an ``_embedded_<sha>`` pseudo-course, or None for any other course value."""
    if not isinstance(course, str) or not course.startswith(EMBEDDED_COURSE_PREFIX):
        return None
    sha = course[len(EMBEDDED_COURSE_PREFIX):]
    return sha if SHA256_RE.match(sha) else None


def cached_path(course: Any, image_name: Any, cache_root: str | None = None) -> str | None:
    """Existing cache file for an ``_embedded_<sha>`` pseudo-course + image name, else None."""
    sha = sha_from_course_token(course)
    if sha is None or not safe_filename(image_name):
        return None
    path = os.path.join(cache_root or CACHE_ROOT, sha, image_name)
    return path if os.path.isfile(path) else None


def cache_subdirs(cache_root: str | None = None) -> list[str]:
    root = cache_root or CACHE_ROOT
    if not os.path.isdir(root):
        return []
    return [os.path.join(root, d) for d in os.listdir(root) if SHA256_RE.match(d)]


def public_view(egm_data: dict) -> dict:
    """Copy of the EGM with the heavy base64 ``data`` removed from the embedded block (metadata kept)."""
    out = dict(egm_data)
    block = out.get(KEY_EMBEDDED_IMAGE)
    if isinstance(block, dict):
        out[KEY_EMBEDDED_IMAGE] = {k: v for k, v in block.items() if k != KEY_EMB_DATA}
    return out
