"""Isolated Flask instance for the Boundary Editor 3D preview browser checks (v7.2).

SAFETY (strict): this process never touches the real workspace.
  * the app source is exec'd with DB_PATH replaced by a temp SQLite file (the real db/workspace.db is never opened),
  * _EGM_BASE / _TEAM_INBOX / _OWNER_INBOX point at a temp tree holding a COPY of the fixture EGM + its heat-map PNG,
  * every POST/PUT/DELETE except /api/preview, /api/degrid* (writes inside the temp tree only) and /api/boundaries is refused (403), and /api/boundaries (the editor's
    autosave) is INTERCEPTED: counted, answered ok, never written anywhere,
  * the listening port is chosen by the caller (a spare port, never 5051/5052/5053).

Usage (CLI):  python preview3d_harness.py <port> <temp_root> [grid 20|40]
Library:      start_harness(tmp_path, grid) -> Harness (context manager) with .base_url / .egm_path / .state()
"""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import time
import types
import urllib.request
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
APP_PY = APP_DIR / "app.py"
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "delaveaga_thomas_test4"
FIXTURE_EGM = FIXTURE_DIR / "thomas_test4.egm"
FIXTURE_PNG_GLOB = "*.png"
FIXTURE_GRID_FINE = 40
FIXTURE_GRID_COARSE = 20
DB_PATH_LINE = 'DB_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "workspace.db")'
FORBIDDEN_PORTS = (5051, 5052, 5053)
HOST = "127.0.0.1"
ROUTE_STATE = "/__harness/state"
ROUTE_PREVIEW = "/api/preview"
ROUTE_SAVE = "/api/boundaries"
WRITE_METHODS = ("POST", "PUT", "DELETE", "PATCH")
ROUTE_PREFIX_DEGRID = "/api/degrid"   # writes only a cleaned copy of the heat-map next to the TEMP image
STARTUP_TIMEOUT_S = 40.0
POLL_S = 0.25
SUBDIR_COURSES = "GolfCourses"
COURSE_NAME = "Delaveaga"
SUBDIR_IMAGES = "Images"
SUBDIR_EGMS = "EGMs"
SUBDIR_INBOX_TEAM = "team_inbox"
SUBDIR_INBOX_OWNER = "owner_inbox"
EGM_COPY_NAME = "preview_harness.egm"
DB_NAME = "harness.db"


def build_temp_tree(root: Path, grid: int = FIXTURE_GRID_FINE) -> Path:
    """Copy the fixture EGM (+ PNG) into <root>/GolfCourses/Delaveaga/...; returns the EGM copy's path."""
    img_dir = root / SUBDIR_COURSES / COURSE_NAME / SUBDIR_IMAGES
    egm_dir = root / SUBDIR_COURSES / COURSE_NAME / SUBDIR_EGMS
    for d in (img_dir, egm_dir, root / SUBDIR_INBOX_TEAM, root / SUBDIR_INBOX_OWNER):
        d.mkdir(parents=True, exist_ok=True)
    for png in FIXTURE_DIR.glob(FIXTURE_PNG_GLOB):
        shutil.copy2(png, img_dir / png.name)
    snap = json.loads(FIXTURE_EGM.read_text())
    if grid == FIXTURE_GRID_COARSE:
        coarse: dict = {}
        for key, val in snap["gridCellHeights"].items():
            r, c = divmod(int(key), FIXTURE_GRID_FINE)
            coarse[str((r // 2) * FIXTURE_GRID_COARSE + c // 2)] = val
        snap["gridCellHeights"] = coarse
        snap["gridResolution"] = FIXTURE_GRID_COARSE
    out = egm_dir / EGM_COPY_NAME
    out.write_text(json.dumps(snap))
    return out


def free_port() -> int:
    with socket.socket() as s:
        s.bind((HOST, 0))
        port = s.getsockname()[1]
    assert port not in FORBIDDEN_PORTS
    return port


def serve(port: int, root: Path) -> None:
    """Run the isolated app in THIS process (blocking)."""
    assert port not in FORBIDDEN_PORTS, "refusing to bind a live-server port"
    src = APP_PY.read_text()
    assert DB_PATH_LINE in src, "app.py DB_PATH line changed; update the harness"
    src = src.replace(DB_PATH_LINE, f"DB_PATH = {str(root / DB_NAME)!r}", 1)
    sys.path.insert(0, str(APP_DIR))
    mod = types.ModuleType("app")
    mod.__file__ = str(APP_PY)
    sys.modules["app"] = mod
    exec(compile(src, str(APP_PY), "exec"), mod.__dict__)
    mod._EGM_BASE = str(root / SUBDIR_COURSES)
    mod._TEAM_INBOX = str(root / SUBDIR_INBOX_TEAM)
    mod._OWNER_INBOX = str(root / SUBDIR_INBOX_OWNER)
    app = mod.app
    state = {"saves": 0, "refused": [], "previews": 0}

    from flask import jsonify, request

    @app.before_request
    def _guard():
        if request.path == ROUTE_STATE:
            return jsonify(state)
        if request.method in WRITE_METHODS:
            if request.path == ROUTE_PREVIEW:
                state["previews"] += 1
                return None
            if request.path == ROUTE_SAVE:       # autosave intercepted: counted, never written
                state["saves"] += 1
                return jsonify({"status": "ok"})
            if request.path.startswith(ROUTE_PREFIX_DEGRID):
                return None
            state["refused"].append(request.path)
            return jsonify({"status": "error", "msg": "refused by preview harness"}), 403
        return None

    app.run(host=HOST, port=port, threaded=True, use_reloader=False, debug=False)


class Harness:
    def __init__(self, tmp_root: Path, grid: int = FIXTURE_GRID_FINE):
        self.root = Path(tmp_root)
        self.egm_path = build_temp_tree(self.root, grid)
        self.port = free_port()
        self.base_url = f"http://{HOST}:{self.port}"
        self.proc: subprocess.Popen | None = None

    def start(self) -> "Harness":
        self.proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), str(self.port), str(self.root)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + STARTUP_TIMEOUT_S
        while time.time() < deadline:
            try:
                urllib.request.urlopen(self.base_url + ROUTE_STATE, timeout=2).read()
                return self
            except Exception:
                if self.proc.poll() is not None:
                    raise RuntimeError("harness server exited during startup")
                time.sleep(POLL_S)
        raise RuntimeError("harness server did not start")

    def state(self) -> dict:
        return json.loads(urllib.request.urlopen(self.base_url + ROUTE_STATE, timeout=5).read())

    def editor_url(self) -> str:
        from urllib.parse import quote
        return f"{self.base_url}/editor?egm={quote(str(self.egm_path))}"

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def __enter__(self) -> "Harness":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


def start_harness(tmp_root: Path, grid: int = FIXTURE_GRID_FINE) -> Harness:
    return Harness(tmp_root, grid)


if __name__ == "__main__":
    serve(int(sys.argv[1]), Path(sys.argv[2]))
