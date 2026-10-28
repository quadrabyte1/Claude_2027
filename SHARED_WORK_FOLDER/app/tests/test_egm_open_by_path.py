"""Open an EGM by full absolute path (v6.02): /api/boundaries/load_path, save write-back, /editor?egm= auto-load.

Temp dirs only -- never touches db/workspace.db, live EGMs or course folders.
"""
import json
import os
import re
import sys
from urllib.parse import quote

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import app as app_module  # noqa: E402
from tests import editor_constants as ec  # noqa: E402

SAMPLE_EGM = {"course": "TmpCourse", "hole": "07", "image": "h7.png", "polygons": []}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DB_PATH", str(tmp_path / "workspace.db"))
    base = tmp_path / "GolfCourses"
    monkeypatch.setattr(app_module, "_EGM_BASE", str(base))
    monkeypatch.setattr(app_module, "_TEAM_INBOX", str(tmp_path / "team_inbox"))
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        yield client, tmp_path, base


def _write(path, data=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(SAMPLE_EGM if data is None else data))
    return str(path)


def _load(client, path):
    return client.get(app_module.ROUTE_API_BOUNDARIES_LOAD_PATH + "?" + app_module.QUERY_PATH + "=" + quote(path, safe=""))


def test_valid_path_outside_course_folders(env):
    client, tmp, _ = env
    p = _write(tmp / "Desktop" / "x.egm")
    r = _load(client, p)
    assert r.status_code == 200
    j = r.get_json()
    assert j[app_module.KEY_STATUS] == app_module.STATUS_OK
    assert j[app_module.KEY_EGM_PATH] == os.path.realpath(p)
    assert app_module.KEY_IMAGE_WARNING in j  # image absent -> clear message, not silent


def test_course_implied_by_location_finds_image(env):
    client, _, base = env
    p = _write(base / "Other" / app_module.COURSE_SUBDIR_EGMS / "y.egm")
    img = base / "Other" / app_module.COURSE_SUBDIR_IMAGES / "h7.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"x")
    j = _load(client, p).get_json()
    assert j[app_module.KEY_IMAGE_COURSE] == "Other"
    assert app_module.KEY_IMAGE_WARNING not in j


def test_wrong_extension_rejected(env):
    client, tmp, _ = env
    p = tmp / "x.txt"
    p.write_text("{}")
    r = _load(client, str(p))
    assert r.status_code == 400


def test_missing_file(env):
    client, tmp, _ = env
    assert _load(client, str(tmp / "nope.egm")).status_code == 404


def test_relative_and_empty_rejected(env):
    client, _, _ = env
    assert _load(client, "x.egm").status_code == 400
    assert _load(client, "").status_code == 400


def test_directory_named_egm_rejected(env):
    client, tmp, _ = env
    d = tmp / "dir.egm"
    d.mkdir()
    assert _load(client, str(d)).status_code == 400


def test_traversal_to_non_egm_rejected(env):
    client, tmp, _ = env
    (tmp / "secret.txt").write_text("{}")
    (tmp / "a").mkdir()
    assert _load(client, str(tmp / "a" / ".." / "secret.txt")).status_code == 400


def test_symlink_to_non_egm_rejected(env):
    client, tmp, _ = env
    (tmp / "secret.txt").write_text("{}")
    link = tmp / "link.egm"
    os.symlink(tmp / "secret.txt", link)
    assert _load(client, str(link)).status_code == 400


def test_save_writes_back_to_same_file(env):
    client, tmp, base = env
    p = _write(tmp / "Downloads" / "z.egm")
    payload = dict(SAMPLE_EGM, hole="09", **{app_module.KEY_EGM_PATH: p})
    r = client.post(app_module.ROUTE_API_BOUNDARIES, json=payload)
    assert r.get_json()[app_module.KEY_PATH] == os.path.realpath(p)
    saved = json.loads(open(p).read())
    assert saved["hole"] == "09" and app_module.KEY_EGM_PATH not in saved
    assert not base.exists()  # no copy created in a course folder


def test_save_rejects_bad_path(env):
    client, tmp, _ = env
    (tmp / "t.txt").write_text("x")
    r = client.post(app_module.ROUTE_API_BOUNDARIES, json=dict(SAMPLE_EGM, **{app_module.KEY_EGM_PATH: str(tmp / "t.txt")}))
    assert r.status_code == 400 and (tmp / "t.txt").read_text() == "x"


def test_duplicate_filenames_resolved_by_path(env):
    client, _, base = env
    a = _write(base / "A" / "EGMs" / "same.egm", dict(SAMPLE_EGM, hole="A"))
    b = _write(base / "B" / "EGMs" / "same.egm", dict(SAMPLE_EGM, hole="B"))
    assert _load(client, a).get_json()["hole"] == "A"
    assert _load(client, b).get_json()["hole"] == "B"


def test_editor_route_embeds_egm_param(env):
    client, _, _ = env
    p = "/Users/x/My Maps/h'1.egm"
    html = client.get(app_module.ROUTE_EDITOR + "?" + app_module.QUERY_EGM + "=" + quote(p, safe="")).get_data(as_text=True)
    m = re.search(r"initialEgmPath:\s*(\".*?\"),", html)
    assert m and json.loads(m.group(1)) == p
    html2 = client.get(app_module.ROUTE_EDITOR).get_data(as_text=True)
    assert re.search(r'initialEgmPath:\s*"",', html2)


def test_editor_constants_match_server():
    assert ec.value("API_BOUNDARIES_LOAD_PATH") == app_module.ROUTE_API_BOUNDARIES_LOAD_PATH
    assert ec.value("QUERY_PATH") == "?" + app_module.QUERY_PATH + "="
    assert ec.value("EGM_PATH_FIELD") == app_module.KEY_EGM_PATH


def test_editor_autoloads_via_loadProject_and_autosave_includes_path():
    src = ec.EDITOR_PATH.read_text()
    init = src[src.index("    init() {"):src.index("loadImage() {")]
    assert "this.initialEgmPath" in init and "_egmAutoLoaded" in init and "this.loadProject(" in init
    assert "API_BOUNDARIES_LOAD_PATH + QUERY_PATH" in src
    assert src.count("data[EGM_PATH_FIELD] = this.egmPath") == 2  # autosave + generate
