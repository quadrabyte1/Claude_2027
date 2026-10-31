"""Editor v6.15: degridded PNG cleanup -- guard, endpoint, sweep, multi-tab, Generate pin, regeneration, JS wiring.

Temp dirs only -- never real course folders or the live DB.
Run: python -m pytest app/tests/test_degrid_cleanup.py -v
"""
import os
import re
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import app as app_module  # noqa: E402
import degrid_cleanup as dc  # noqa: E402
import heatmap_degrid as hd  # noqa: E402
from tests import editor_constants as ec  # noqa: E402

EDITOR_SRC = ec.EDITOR_PATH.read_text()
COURSE = "TmpCourse"
ORIGINAL = "h1.png"
TAB_A, TAB_B = "tabA", "tabB"
HOUR = 3600


def _make_png(path, stamped=True):
    """A real degridded-style PNG (stamped with the algo version) or a plain PNG."""
    import cv2
    ok, buf = cv2.imencode(".png", np.full((20, 20, 3), 200, np.uint8))
    open(path, "wb").write(buf.tobytes())
    if stamped:
        _stamp(path)


def _stamp(path):
    """Insert the DegridAlgoVersion tEXt chunk after IHDR, exactly as heatmap_degrid reads it."""
    import struct, zlib
    data = open(path, "rb").read()
    payload = hd.PNG_TEXT_KEY.encode() + hd.PNG_TEXT_SEPARATOR + str(hd.DEGRID_ALGO_VERSION).encode()
    chunk = struct.pack(">I", len(payload)) + hd.PNG_CHUNK_TEXT + payload + struct.pack(">I", zlib.crc32(hd.PNG_CHUNK_TEXT + payload))
    pos = len(hd.PNG_SIGNATURE)
    (ihdr_len,) = struct.unpack(">I", data[pos:pos + 4])
    cut = pos + hd.PNG_CHUNK_HEADER_BYTES + ihdr_len + hd.PNG_CHUNK_CRC_BYTES
    open(path, "wb").write(data[:cut] + chunk + data[cut:])


@pytest.fixture()
def env(tmp_path, monkeypatch):
    base = tmp_path / "GolfCourses"
    images = base / COURSE / "Images"
    images.mkdir(parents=True)
    inbox = tmp_path / "team_inbox"
    inbox.mkdir()
    monkeypatch.setattr(app_module, "DB_PATH", str(tmp_path / "workspace.db"))
    monkeypatch.setattr(app_module, "_EGM_BASE", str(base))
    monkeypatch.setattr(app_module, "_TEAM_INBOX", str(inbox))
    monkeypatch.setattr(dc, "TRACKER", dc.DegridTracker())
    monkeypatch.setattr(app_module.degrid_cleanup, "TRACKER", dc.TRACKER)
    import cv2
    cv2.imwrite(str(images / ORIGINAL), np.full((20, 20, 3), 200, np.uint8))

    def fake_degrid(src, out):   # a flat test image has no grid, so stand in for the real cleaner
        _make_png(out)
        return {hd.INFO_WRITTEN: True}
    monkeypatch.setattr(hd, "degrid_file", fake_degrid)
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        yield client, images, inbox


def _deg(images):
    return images / (ORIGINAL[:-4] + hd.DEGRID_SUFFIX + hd.DEGRID_EXT)


def _make_deg(images):
    p = _deg(images)
    _make_png(p)
    return p


def _release(client, tab=TAB_A, image=ORIGINAL):
    return client.post(app_module.ROUTE_API_DEGRID_RELEASE,
                       json={app_module.KEY_IMAGE: image, app_module.KEY_IMAGE_COURSE: COURSE, app_module.KEY_TAB_ID: tab}).get_json()


# ---- guard ----------------------------------------------------------------------------
def test_stamp_helper_is_recognised(tmp_path):
    p = tmp_path / "x__degridded.png"
    _make_png(p)
    assert hd.png_algo_version(str(p)) == hd.DEGRID_ALGO_VERSION


@pytest.mark.parametrize("name", ["h1.png", "h1__degridded.jpg", "h1__degridded.PNG", "__degridded.png",
                                  "h1__degridded.png.bak", "h1__degridded", "h1_degridded.png", "Hole 11, 55171.png"])
def test_bad_names_rejected_and_untouched(tmp_path, name):
    p = tmp_path / name
    _make_png(p)
    assert dc.delete_degridded(str(p), [str(tmp_path)]) == dc.R_REJECTED_NAME
    assert p.exists()


def test_original_never_deleted_even_when_stamped(env):
    _, images, _ = env
    orig = images / ORIGINAL
    _stamp(orig)
    assert dc.delete_degridded(str(orig), [str(images)]) == dc.R_REJECTED_NAME
    assert orig.exists()


def test_valid_file_deleted(env):
    _, images, _ = env
    p = _make_deg(images)
    assert dc.delete_degridded(str(p), [str(images)]) == dc.R_DELETED
    assert not p.exists()


def test_outside_allowed_dir_rejected(env, tmp_path):
    _, images, _ = env
    other = tmp_path / "elsewhere"
    other.mkdir()
    p = other / _deg(images).name
    _make_png(p)
    assert dc.delete_degridded(str(p), [str(images)]) == dc.R_REJECTED_DIR
    assert p.exists()


def test_traversal_path_rejected(env, tmp_path):
    _, images, _ = env
    other = tmp_path / "elsewhere"
    other.mkdir()
    victim = other / _deg(images).name
    _make_png(victim)
    sneaky = os.path.join(str(images), "..", "..", "..", "elsewhere", victim.name)
    assert dc.delete_degridded(sneaky, [str(images)]) == dc.R_REJECTED_DIR
    assert victim.exists()


def test_symlink_file_rejected_target_survives(env, tmp_path):
    _, images, _ = env
    target = tmp_path / "precious.png"
    _make_png(target)
    link = _deg(images)
    link.symlink_to(target)
    assert dc.delete_degridded(str(link), [str(images)]) == dc.R_REJECTED_SYMLINK
    assert target.exists() and link.is_symlink()


def test_symlinked_directory_escape_rejected(env, tmp_path):
    _, images, _ = env
    real = tmp_path / "realdir"
    real.mkdir()
    victim = real / _deg(images).name
    _make_png(victim)
    linkdir = tmp_path / "linkdir"
    linkdir.symlink_to(real)
    assert dc.delete_degridded(str(linkdir / victim.name), [str(images)]) == dc.R_REJECTED_DIR
    assert victim.exists()


def test_unstamped_png_rejected(env):
    _, images, _ = env
    p = _deg(images)
    _make_png(p, stamped=False)
    assert dc.delete_degridded(str(p), [str(images)]) == dc.R_REJECTED_UNSTAMPED
    assert p.exists()


def test_directory_with_valid_name_rejected(env):
    _, images, _ = env
    d = _deg(images)
    d.mkdir()
    assert dc.delete_degridded(str(d), [str(images)]) == dc.R_REJECTED_NOT_FILE
    assert d.is_dir()


def test_missing_file_is_harmless(env):
    _, images, _ = env
    assert dc.delete_degridded(str(_deg(images)), [str(images)]) == dc.R_MISSING


# ---- endpoint -------------------------------------------------------------------------
def test_release_endpoint_deletes_copy_keeps_original(env):
    client, images, _ = env
    p = _make_deg(images)
    out = _release(client)
    assert out[app_module.KEY_REASON] == dc.R_DELETED
    assert not p.exists() and (images / ORIGINAL).exists()


def test_release_endpoint_unknown_image(env):
    client, images, _ = env
    assert _release(client, image="nope.png")[app_module.KEY_REASON] == dc.R_MISSING


def test_release_endpoint_rejects_path_style_image_names(env, tmp_path):
    client, images, _ = env
    victim = tmp_path / "victim__degridded.png"
    _make_png(victim)
    for name in ("../../victim.png", str(tmp_path / "victim.png")):
        _release(client, image=name)
    assert victim.exists()


def test_beacon_style_blob_body_accepted(env):
    client, images, _ = env
    p = _make_deg(images)
    body = '{"%s":"%s","%s":"%s","%s":"%s"}' % (app_module.KEY_IMAGE, ORIGINAL, app_module.KEY_IMAGE_COURSE, COURSE, app_module.KEY_TAB_ID, TAB_A)
    r = client.post(app_module.ROUTE_API_DEGRID_RELEASE, data=body, content_type=ec.value("DEGRID_RELEASE_MIME"))
    assert r.get_json()[app_module.KEY_REASON] == dc.R_DELETED and not p.exists()


# ---- multi-tab / generate -------------------------------------------------------------
def test_other_live_tab_keeps_file(env):
    client, images, _ = env
    for tab in (TAB_A, TAB_B):
        client.post(app_module.ROUTE_API_DEGRID_IMAGE, json={app_module.KEY_IMAGE: ORIGINAL, app_module.KEY_IMAGE_COURSE: COURSE, app_module.KEY_TAB_ID: tab})
    assert _deg(images).exists()
    assert _release(client, TAB_A)[app_module.KEY_REASON] == dc.R_KEPT_IN_USE
    assert _deg(images).exists()
    assert _release(client, TAB_B)[app_module.KEY_REASON] == dc.R_DELETED
    assert not _deg(images).exists()


def test_stale_tab_claim_expires(env):
    _, images, _ = env
    p = _make_deg(images)
    t0 = 1_000_000.0
    dc.TRACKER.touch(str(p), TAB_B, now=t0)
    assert dc.TRACKER.release(str(p), TAB_A, [str(images)], now=t0 + dc.USER_TTL_S + 1) == dc.R_DELETED


def test_generate_pins_file_until_finished(env):
    client, images, _ = env
    p = _make_deg(images)
    with dc.TRACKER.generate_guard():
        assert _release(client)[app_module.KEY_REASON] == dc.R_KEPT_GENERATING
        assert p.exists()
        assert dc.TRACKER.sweep([str(images)], now=time.time() + 100 * HOUR) == []
    assert _release(client)[app_module.KEY_REASON] == dc.R_DELETED


def test_generate_route_wraps_pipeline_in_guard(env, monkeypatch):
    client, images, _ = env
    seen = {}
    monkeypatch.setattr(app_module, "_generate_models_impl", lambda: seen.setdefault("g", dc.TRACKER.generating) and "ok")
    client.post(app_module.ROUTE_API_GENERATE_MODELS, json={})
    assert seen["g"] is True and dc.TRACKER.generating is False


# ---- sweep ----------------------------------------------------------------------------
def test_sweep_removes_only_old_orphans(env):
    _, images, inbox = env
    old = _make_deg(images)
    old_inbox = inbox / "t__degridded.png"
    _make_png(old_inbox)
    young = images / "y__degridded.png"
    _make_png(young)
    orig = images / ORIGINAL
    now = time.time()
    for f in (old, old_inbox):
        os.utime(f, (now - dc.ORPHAN_MAX_AGE_S - 5,) * 2)
    removed = dc.TRACKER.sweep(app_module._degrid_allowed_dirs(), now=now)
    assert sorted(removed) == sorted(str(p.resolve()) if False else os.path.join(os.path.realpath(p.parent), p.name) for p in (old, old_inbox))
    assert young.exists() and orig.exists()


def test_sweep_skips_in_use_and_never_touches_non_degridded(env):
    _, images, _ = env
    p = _make_deg(images)
    keep = images / "notes.txt"
    keep.write_text("x")
    now = time.time()
    os.utime(p, (now - 10 * dc.ORPHAN_MAX_AGE_S,) * 2)
    dc.TRACKER.touch(str(p), TAB_A, now=now)
    assert dc.TRACKER.sweep([str(images)], now=now) == []
    assert p.exists() and keep.exists()


def test_startup_wiring_runs_sweep_then_thread(env):
    _, images, _ = env
    p = _make_deg(images)
    os.utime(p, (time.time() - 10 * dc.ORPHAN_MAX_AGE_S,) * 2)
    t = dc.start_sweeper(lambda: [str(images)], tracker=dc.DegridTracker(), interval_s=10 ** 6)
    assert not p.exists() and t.daemon and t.name == dc.SWEEP_THREAD_NAME
    main_src = open(os.path.join(os.path.dirname(__file__), "..", "app.py")).read().split('if __name__ == "__main__":')[1]
    assert "degrid_cleanup.start_sweeper(_degrid_allowed_dirs)" in main_src


# ---- regeneration after deletion ------------------------------------------------------
def test_degrid_image_regenerates_after_release(env, monkeypatch):
    client, images, _ = env

    body = {app_module.KEY_IMAGE: ORIGINAL, app_module.KEY_IMAGE_COURSE: COURSE, app_module.KEY_TAB_ID: TAB_A}
    r1 = client.post(app_module.ROUTE_API_DEGRID_IMAGE, json=body).get_json()
    assert r1[app_module.KEY_FOUND] and _deg(images).exists()
    assert _release(client)[app_module.KEY_REASON] == dc.R_DELETED
    assert not _deg(images).exists()
    r2 = client.post(app_module.ROUTE_API_DEGRID_IMAGE, json=body).get_json()
    assert r2[app_module.KEY_FOUND] and r2[app_module.KEY_DEGRIDDED_URL] == r1[app_module.KEY_DEGRIDDED_URL] and _deg(images).exists()


# ---- constants sync + JS trigger wiring ----------------------------------------------
def test_editor_release_url_matches_server_route():
    assert ec.value("DEGRID_RELEASE_URL") == app_module.ROUTE_API_DEGRID_RELEASE


def _method(name):
    m = re.search(r"\n    (?:async )?(%s\(.*?\n    \}),\n" % re.escape(name), EDITOR_SRC, re.S)
    assert m, name
    return m.group(1)


def test_close_project_releases_after_autosave():
    src = _method("closeProject")
    assert src.index("await this.autoSave()") < src.index("this.releaseDegrid(false)") < src.index("this.clearEditorState()")


def test_new_and_open_project_release_only_a_different_previous_image():
    src = _method("loadImage")   # New Project and Open Project both end in loadImage()
    assert "held.image !== this.selectedImage" in src and "held.imageCourse !== this.selectedImageCourse" in src
    assert src.index("this.releaseDegrid(false)") < src.index("this._requestDegrid()")
    assert "this.loadImage()" in _method("startNewProject") and "this.loadImage()" in EDITOR_SRC


def test_pagehide_beacon_wired_once():
    init = _method("init")
    assert "addEventListener(DEGRID_PAGE_HIDE_EVENT, () => this.releaseDegrid(true))" in init
    assert init.index("if (!this._degridTabId)") < init.index("addEventListener(DEGRID_PAGE_HIDE_EVENT")
    assert "navigator.sendBeacon(DEGRID_RELEASE_URL" in _method("releaseDegrid")
    assert ec.value("DEGRID_PAGE_HIDE_EVENT") == "pagehide"


def test_lost_png_self_heals_in_image_switch():
    src = _method("setImageView")
    assert "next.onerror" in src and "this._requestDegrid()" in src and "DEGRID_VIEW_ORIGINAL" in src


def test_version_bumped():
    assert app_module.APP_VERSION == "v6.17"
    assert "Boundary Editor v6.17" in EDITOR_SRC.split("\n", 2)[1]
