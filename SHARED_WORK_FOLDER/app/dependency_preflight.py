"""Dependency preflight for the 3MF generation pipeline.

Stdlib-only on purpose: it must be importable (and report a useful message)
even when numpy / cv2 / trimesh themselves are missing.

Thomas's decision (v5.75): generation must STOP with a clear error instead of
silently producing a degraded model (e.g. missing `triangle` -> flat earcut
fringe with no grid heights or grass).
"""
from __future__ import annotations

import importlib
from typing import NamedTuple


class RequiredModule(NamedTuple):
    import_name: str   # name passed to importlib.import_module
    pip_name: str      # name in requirements.txt
    why: str           # what breaks without it (shown to the user)


# Hard imports of the pipeline plus trimesh soft deps on the code paths we use.
REQUIRED_MODULES: tuple = (
    RequiredModule("numpy", "numpy", "numerics"),
    RequiredModule("scipy", "scipy", "Poisson solve, KD-trees, smoothing"),
    RequiredModule("cv2", "opencv-python", "image / arrow detection"),
    RequiredModule("skimage", "scikit-image", "contour finding"),
    RequiredModule("matplotlib", "matplotlib", "diagnostic images"),
    RequiredModule("shapely", "shapely", "polygon geometry"),
    RequiredModule("trimesh", "trimesh", "mesh construction"),
    RequiredModule("triangle", "triangle", "fringe top triangulation (grid heights and grass)"),
    RequiredModule("manifold3d", "manifold3d", "boolean cuts (tee hole, pin holes)"),
    RequiredModule("lxml", "lxml", "3MF export"),
    RequiredModule("mapbox_earcut", "mapbox_earcut", "bottom-cap triangulation"),
    RequiredModule("networkx", "networkx", "trimesh graph / split operations"),
)

INSTALL_COMMAND: str = ".venv/bin/python -m pip install -r requirements.txt"

MSG_MISSING_FMT: str = (
    "Cannot generate: missing Python package(s): {names}. "
    "Fix: run `{cmd}` from the project folder, then restart the web server."
)


class MissingDependencyError(RuntimeError):
    """Raised when one or more required modules cannot be imported."""

    def __init__(self, missing: list):
        self.missing = list(missing)
        names = ", ".join(f"{m.pip_name} (needed for {m.why})" for m in self.missing)
        super().__init__(MSG_MISSING_FMT.format(names=names, cmd=INSTALL_COMMAND))


def find_missing(required: tuple | None = None) -> list:
    """Return the RequiredModule entries that fail to import."""
    missing = []
    for mod in (REQUIRED_MODULES if required is None else required):
        try:
            importlib.import_module(mod.import_name)
        except Exception:  # ImportError, or a broken binary wheel
            missing.append(mod)
    return missing


def check_dependencies(required: tuple | None = None) -> None:
    """Raise MissingDependencyError naming every missing module."""
    missing = find_missing(required)
    if missing:
        raise MissingDependencyError(missing)


def status_report(required: tuple | None = None) -> dict:
    """JSON-friendly status: {"ok": bool, "missing": [...], "message": str|None}."""
    missing = find_missing(required)
    return {
        "ok": not missing,
        "missing": [m.pip_name for m in missing],
        "message": str(MissingDependencyError(missing)) if missing else None,
    }
