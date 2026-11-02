"""Shared pytest safety net: tests never write into the real ItWentIn/GolfCourses tree.

Root cause this prevents (2026-11-01): pipeline tests that call
``gradient_surface_diagnostic.run_pipeline`` on a copy of a real EGM resolved the
output folder via ``course_paths(<course name in the EGM>)`` and so wrote
stub 3MFs (``b"PK\\x03\\x04"``, 4 bytes, from a no-op ``Scene.export`` mock) into the
real ``ItWentIn/GolfCourses/<course>/3MFs/`` folder.

Defaults, applied to every test:
  * ``course_paths`` (in ``generate_stl_3mf`` and every module that imported it)
    returns the real paths for read-only dirs (images, egms) but redirects the
    OUTPUT dirs (3MFs, STLs) to a per-test tmp_path.  A test that wants something
    else can still monkeypatch ``course_paths`` itself; its patch wins.
  * A session-wide guard fails the run if any file appears in / disappears from a
    real ``GolfCourses/*/3MFs`` folder while the tests ran.
"""
import os
import sys
from pathlib import Path

import pytest

TESTS_APP_DIR = Path(__file__).resolve().parent.parent
if str(TESTS_APP_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_APP_DIR))

import generate_stl_3mf as _gen  # noqa: E402  (source of course_paths / EGM_BASE / path keys)

SANDBOX_OUTPUT_ROOT_NAME = "course_outputs"          # under each test's tmp_path
SANDBOXED_PATH_KEYS = (_gen.PATH_KEY_3MFS, _gen.PATH_KEY_STLS)   # output-only dirs
GUARDED_SUBDIR = _gen.COURSE_SUBDIR_3MFS
GUARD_FAILURE_MSG = (
    "Tests modified the REAL course output folder(s); a test is writing outside tmp_path: "
)

_ORIGINAL_COURSE_PATHS = _gen.course_paths


def _real_output_listing() -> set:
    """Set of (path, size, mtime_ns) for every file in the real GolfCourses/*/3MFs folders."""
    found = set()
    base = Path(_gen.EGM_BASE)
    if not base.is_dir():
        return found
    for f in base.glob(f"*/{GUARDED_SUBDIR}/*"):
        if f.is_file():
            st = f.stat()
            found.add((str(f), st.st_size, st.st_mtime_ns))
    return found


@pytest.fixture(autouse=True)
def _sandbox_course_output_dirs(tmp_path, monkeypatch):
    """Redirect course output dirs (3MFs/STLs) into tmp_path for every test."""
    sandbox = tmp_path / SANDBOX_OUTPUT_ROOT_NAME

    def _sandboxed_course_paths(course: str) -> dict:
        paths = dict(_ORIGINAL_COURSE_PATHS(course))
        for key in SANDBOXED_PATH_KEYS:
            paths[key] = str(sandbox / course / os.path.basename(paths[key]))
        return paths

    monkeypatch.setattr(_gen, "course_paths", _sandboxed_course_paths)
    for mod in list(sys.modules.values()):
        if mod is not _gen and getattr(mod, "course_paths", None) is _ORIGINAL_COURSE_PATHS:
            monkeypatch.setattr(mod, "course_paths", _sandboxed_course_paths)
    yield


@pytest.fixture(autouse=True, scope="session")
def _guard_real_course_outputs():
    """Fail the session if the real course 3MFs folders changed during the run."""
    before = _real_output_listing()
    yield
    after = _real_output_listing()
    changed = sorted(p for p, _, _ in (before ^ after))
    assert not changed, GUARD_FAILURE_MSG + ", ".join(changed)
