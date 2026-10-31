"""Safe cleanup of generated degridded heat-map PNGs (Editor v6.15).

The editor asks the server for a "<stem>__degridded.png" copy of the heat-map image
(heatmap_degrid.py) on every load.  It is a pure cache -- /api/degrid_image rebuilds it on
demand -- so once no editor needs it, it is deleted.  Everything here is built around ONE rule:
only a file that is positively identified as a generated degridded artifact may be removed.

A file is deleted only if ALL of these hold (see ``is_deletable_degridded``):
  * its name is exactly "<non-empty stem>__degridded.png" (no path separators, case-exact);
  * it is not a symlink and is a regular file;
  * its realpath's folder IS one of the allowed image folders (realpath-compared);
  * it carries our PNG ``DegridAlgoVersion`` tEXt stamp (written only by heatmap_degrid).
The original heat-map image never satisfies the name pattern, so it can never be deleted.

Multi-tab handling: tabs register a (image, tab id, last-seen) entry when they load the image.
A release removes only that tab's entry and deletes the file only if no OTHER live tab (seen
within USER_TTL_S) still holds it and no Generate is running.  A tab that loses its PNG anyway
self-heals: the editor re-requests /api/degrid_image.
"""
import contextlib
import os
import re
import threading
import time

import heatmap_degrid

# -- tunables (single definitions; tests import these) ----------------------------------
ORPHAN_MAX_AGE_S = 3600          # sweep: a degridded PNG untouched this long, with no live tab, is an orphan
USER_TTL_S = 4 * 3600            # a tab's claim on an image expires this long after it was last seen
SWEEP_INTERVAL_S = 3600          # periodic sweep period (a sweep also runs once at startup)
SWEEP_THREAD_NAME = "degrid-sweeper"

# -- result reasons ---------------------------------------------------------------------
R_DELETED = "deleted"
R_MISSING = "missing"
R_REJECTED_NAME = "rejected_name"
R_REJECTED_SYMLINK = "rejected_symlink"
R_REJECTED_NOT_FILE = "rejected_not_file"
R_REJECTED_DIR = "rejected_dir"
R_REJECTED_UNSTAMPED = "rejected_unstamped"
R_KEPT_IN_USE = "kept_in_use"
R_KEPT_GENERATING = "kept_generating"
R_KEPT_YOUNG = "kept_young"
R_ERROR = "error"

# "<stem>__degridded.png" -- stem non-empty, no separators.  Built from heatmap_degrid's constants.
NAME_RE = re.compile(r"^[^/\\\x00]+" + re.escape(heatmap_degrid.DEGRID_SUFFIX) + re.escape(heatmap_degrid.DEGRID_EXT) + r"$")


def _real_dirs(allowed_dirs):
    return {os.path.realpath(d) for d in allowed_dirs if d and os.path.isdir(d)}


def classify(path, allowed_dirs):
    """Return R_DELETED-compatible verdict: None if deletable, else a rejection reason."""
    name = os.path.basename(path)
    if not NAME_RE.match(name) or name != os.path.basename(os.path.normpath(path)):
        return R_REJECTED_NAME
    if os.path.islink(path):
        return R_REJECTED_SYMLINK
    if not os.path.lexists(path):
        return R_MISSING
    if not os.path.isfile(path):
        return R_REJECTED_NOT_FILE
    if os.path.dirname(os.path.realpath(path)) not in _real_dirs(allowed_dirs):
        return R_REJECTED_DIR
    if heatmap_degrid.png_algo_version(path) is None:
        return R_REJECTED_UNSTAMPED
    return None


def is_deletable_degridded(path, allowed_dirs):
    return classify(path, allowed_dirs) is None


def delete_degridded(path, allowed_dirs):
    """Delete ``path`` only if it passes the guard.  Returns a reason string (R_DELETED on success)."""
    verdict = classify(path, allowed_dirs)
    if verdict is not None:
        return verdict
    try:
        os.unlink(path)
    except FileNotFoundError:
        return R_MISSING
    except OSError:
        return R_ERROR
    return R_DELETED


class DegridTracker:
    """Which tabs hold which degridded file, and whether a Generate is running."""

    def __init__(self):
        self._lock = threading.RLock()
        self._users = {}          # realpath -> {tab_id: last_seen}
        self._generating = 0

    @staticmethod
    def _key(path):
        return os.path.realpath(path)

    def touch(self, path, tab_id, now=None):
        if not tab_id:
            return
        now = time.time() if now is None else now
        with self._lock:
            self._users.setdefault(self._key(path), {})[tab_id] = now

    def _live_others(self, key, tab_id, now):
        users = self._users.get(key, {})
        return [t for t, seen in users.items() if t != tab_id and now - seen <= USER_TTL_S]

    def in_use(self, path, now=None):
        now = time.time() if now is None else now
        with self._lock:
            return bool(self._live_others(self._key(path), None, now))

    @property
    def generating(self):
        with self._lock:
            return self._generating > 0

    @contextlib.contextmanager
    def generate_guard(self):
        with self._lock:
            self._generating += 1
        try:
            yield
        finally:
            with self._lock:
                self._generating -= 1

    def release(self, path, tab_id, allowed_dirs, now=None):
        """A tab no longer needs ``path``.  Delete it only if nobody else does."""
        now = time.time() if now is None else now
        key = self._key(path)
        with self._lock:
            users = self._users.get(key, {})
            if tab_id:
                users.pop(tab_id, None)
            live = self._live_others(key, tab_id, now)
            if not users:
                self._users.pop(key, None)
            if live:
                return R_KEPT_IN_USE
            if self._generating:
                return R_KEPT_GENERATING
            result = delete_degridded(path, allowed_dirs)
            if result == R_DELETED:
                self._users.pop(key, None)
            return result

    def sweep(self, allowed_dirs, now=None, max_age_s=None):
        """Delete orphaned degridded PNGs (older than max_age_s, no live tab, no Generate).
        Returns the list of deleted paths."""
        now = time.time() if now is None else now
        max_age_s = ORPHAN_MAX_AGE_S if max_age_s is None else max_age_s
        deleted = []
        with self._lock:
            if self._generating:
                return deleted
            for folder in sorted(_real_dirs(allowed_dirs)):
                try:
                    names = os.listdir(folder)
                except OSError:
                    continue
                for name in names:
                    if not NAME_RE.match(name):
                        continue
                    path = os.path.join(folder, name)
                    try:
                        age = now - os.path.getmtime(path)
                    except OSError:
                        continue
                    if age < max_age_s or self._live_others(self._key(path), None, now):
                        continue
                    if delete_degridded(path, [folder]) == R_DELETED:
                        deleted.append(path)
                        self._users.pop(self._key(path), None)
        return deleted


TRACKER = DegridTracker()


def start_sweeper(allowed_dirs_fn, tracker=None, interval_s=None):
    """Sweep once now, then every SWEEP_INTERVAL_S on a daemon thread."""
    tracker = tracker or TRACKER
    interval_s = SWEEP_INTERVAL_S if interval_s is None else interval_s

    def _once():
        try:
            for p in tracker.sweep(allowed_dirs_fn()):
                print(f"[degrid-sweep] removed orphan {p}")
        except Exception as exc:  # never let cleanup take the server down
            print(f"[degrid-sweep] failed: {exc}")

    def _loop():
        while True:
            time.sleep(interval_s)
            _once()

    _once()
    t = threading.Thread(target=_loop, name=SWEEP_THREAD_NAME, daemon=True)
    t.start()
    return t
