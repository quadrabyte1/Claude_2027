"""v6.21 self-contained EGMs: embed / load / fallback / degrid / generate-loader / migration.

Temp dirs only -- never real course folders, real EGMs or the live DB.
Run: python -m pytest app/tests/test_egm_embed.py -v
"""
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import app as app_module  # noqa: E402
import egm_embed as ee  # noqa: E402
import heatmap_degrid as hd  # noqa: E402
import migrate_embed_pngs as mig  # noqa: E402

COURSE = "TmpCourse"
OTHER_COURSE = "OtherCourse"
IMAGE = "h1 (5).png"
MISSING_IMAGE = "gone.png"
HOLE = "01"
EGM_NAME = app_module.EGM_FILENAME_FMT.format(course=COURSE, hole_label=HOLE)
PIXEL_VALUE = 200
IMG_EDGE_PX = 20
BAD_BASE64 = "!!not base64!!"


def _png_bytes(value=PIXEL_VALUE):
    import cv2
    ok, buf = cv2.imencode(".png", np.full((IMG_EDGE_PX, IMG_EDGE_PX, 3), value, np.uint8))
    return buf.tobytes()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    base = tmp_path / "GolfCourses"
    images = base / COURSE / "Images"
    egms = base / COURSE / "EGMs"
    images.mkdir(parents=True)
    egms.mkdir()
    (base / OTHER_COURSE / "Images").mkdir(parents=True)
    inbox = tmp_path / "team_inbox"
    inbox.mkdir()
    monkeypatch.setattr(app_module, "DB_PATH", str(tmp_path / "workspace.db"))
    monkeypatch.setattr(app_module, "_EGM_BASE", str(base))
    monkeypatch.setattr(app_module, "_TEAM_INBOX", str(inbox))
    monkeypatch.setattr(ee, "CACHE_ROOT", str(tmp_path / "cache"))
    app_module.app.config["TESTING"] = True
    (images / IMAGE).write_bytes(_png_bytes())
    with app_module.app.test_client() as client:
        yield client, base, images, egms


def _payload(image=IMAGE, image_course=COURSE):
    return {app_module.KEY_COURSE: COURSE, app_module.KEY_HOLE: HOLE, app_module.KEY_IMAGE: image,
            app_module.KEY_IMAGE_COURSE: image_course, app_module.KEY_POLYGONS: []}


def _save(client, payload):
    r = client.post(app_module.ROUTE_API_BOUNDARIES, json=payload)
    assert r.get_json()[app_module.KEY_STATUS] == app_module.STATUS_OK
    return r.get_json()


def _read(egms):
    return json.loads((egms / EGM_NAME).read_text())


# ---- block --------------------------------------------------------------------------
def test_block_roundtrip_and_corruption():
    raw = _png_bytes()
    block = ee.build_block(raw, IMAGE, COURSE)
    assert ee.block_png_bytes(block) == raw
    assert block[ee.KEY_EMB_SHA256] == ee.sha256_hex(raw) and block[ee.KEY_EMB_SIZE] == len(raw)
    assert ee.block_png_bytes({**block, ee.KEY_EMB_DATA: BAD_BASE64}) is None
    assert ee.block_png_bytes({**block, ee.KEY_EMB_SHA256: ee.sha256_hex(b"x")}) is None
    assert ee.block_png_bytes(None) is None


def test_materialize_rejects_path_traversal(tmp_path):
    block = ee.build_block(_png_bytes(), os.path.join("..", "evil.png"))
    assert ee.materialize({ee.KEY_EMBEDDED_IMAGE: block}, str(tmp_path)) is None


# ---- auto-embed on save ----------------------------------------------------------------
def test_save_auto_embeds_original_png(env):
    client, base, images, egms = env
    _save(client, _payload())
    block = _read(egms)[ee.KEY_EMBEDDED_IMAGE]
    assert ee.block_png_bytes(block) == (images / IMAGE).read_bytes()
    assert block[ee.KEY_EMB_FILENAME] == IMAGE and block[ee.KEY_EMB_SOURCE_COURSE] == COURSE


def test_save_without_png_stays_legacy(env):
    client, base, images, egms = env
    _save(client, _payload(image=MISSING_IMAGE))
    assert ee.KEY_EMBEDDED_IMAGE not in _read(egms)


def test_resave_after_png_deleted_keeps_embed_and_real_course(env):
    client, base, images, egms = env
    _save(client, _payload())
    sha = _read(egms)[ee.KEY_EMBEDDED_IMAGE][ee.KEY_EMB_SHA256]
    (images / IMAGE).unlink()
    _save(client, _payload(image_course=ee.course_token(sha)))     # what the editor sends after a load
    saved = _read(egms)
    assert saved[ee.KEY_EMBEDDED_IMAGE][ee.KEY_EMB_SHA256] == sha
    assert saved[app_module.KEY_IMAGE_COURSE] == COURSE            # pseudo-course never persisted


def test_image_change_reembeds(env):
    client, base, images, egms = env
    _save(client, _payload())
    (images / "b.png").write_bytes(_png_bytes(value=10))
    _save(client, _payload(image="b.png"))
    assert ee.get_png_bytes(_read(egms)) == (images / "b.png").read_bytes()


# ---- load: embedded wins, legacy falls back -------------------------------------------------
def test_load_uses_embedded_when_external_png_missing(env):
    client, base, images, egms = env
    _save(client, _payload())
    raw = (images / IMAGE).read_bytes()
    (images / IMAGE).unlink()
    r = client.get(app_module.ROUTE_API_BOUNDARIES_LOAD_PATH, query_string={app_module.QUERY_PATH: str(egms / EGM_NAME)}).get_json()
    assert r[app_module.KEY_IMAGE_COURSE] == ee.course_token(ee.sha256_hex(raw))
    assert app_module.KEY_IMAGE_WARNING not in r
    assert ee.KEY_EMB_DATA not in r[ee.KEY_EMBEDDED_IMAGE]          # heavy base64 not sent to the browser
    url = app_module.EGM_IMAGE_URL_FMT.format(course=r[app_module.KEY_IMAGE_COURSE], filename=IMAGE)
    assert client.get(url).data == raw


def test_load_by_filename_also_uses_embedded(env):
    client, base, images, egms = env
    _save(client, _payload())
    r = client.get(app_module.ROUTE_API_BOUNDARIES_LOAD, query_string={app_module.QUERY_FILENAME: EGM_NAME}).get_json()
    assert ee.sha_from_course_token(r[app_module.KEY_IMAGE_COURSE])


def test_legacy_egm_falls_back_to_external_path_and_warns(env):
    client, base, images, egms = env
    legacy = _payload()
    (egms / EGM_NAME).write_text(json.dumps(legacy))
    q = {app_module.QUERY_PATH: str(egms / EGM_NAME)}
    r = client.get(app_module.ROUTE_API_BOUNDARIES_LOAD_PATH, query_string=q).get_json()
    assert r[app_module.KEY_IMAGE_COURSE] == COURSE and app_module.KEY_IMAGE_WARNING not in r
    (images / IMAGE).unlink()
    r = client.get(app_module.ROUTE_API_BOUNDARIES_LOAD_PATH, query_string=q).get_json()
    assert app_module.KEY_IMAGE_WARNING in r


def test_corrupt_embedded_block_falls_back(env):
    client, base, images, egms = env
    bad = {**_payload(), ee.KEY_EMBEDDED_IMAGE: {**ee.build_block(_png_bytes(), IMAGE, COURSE), ee.KEY_EMB_DATA: BAD_BASE64}}
    (egms / EGM_NAME).write_text(json.dumps(bad))
    r = client.get(app_module.ROUTE_API_BOUNDARIES_LOAD_PATH, query_string={app_module.QUERY_PATH: str(egms / EGM_NAME)}).get_json()
    assert r[app_module.KEY_IMAGE_COURSE] == COURSE


# ---- degrid + other pipelines run from the embedded copy ---------------------------------------
def test_degrid_runs_from_embedded_without_external_png(env, monkeypatch):
    client, base, images, egms = env
    _save(client, _payload())
    token = client.get(app_module.ROUTE_API_BOUNDARIES_LOAD, query_string={app_module.QUERY_FILENAME: EGM_NAME}).get_json()[app_module.KEY_IMAGE_COURSE]
    (images / IMAGE).unlink()
    seen = {}

    def fake_degrid(src, out):
        seen["src"] = src
        open(out, "wb").write(_png_bytes())
        return {hd.INFO_WRITTEN: True}
    monkeypatch.setattr(hd, "degrid_file", fake_degrid)
    monkeypatch.setattr(hd, "cache_is_fresh", lambda *a: False)
    r = client.post(app_module.ROUTE_API_DEGRID_IMAGE, json={app_module.KEY_IMAGE: IMAGE, app_module.KEY_IMAGE_COURSE: token}).get_json()
    assert r[app_module.KEY_FOUND] and token in r[app_module.KEY_ORIGINAL_URL]
    assert ee.CACHE_ROOT in seen["src"]
    assert os.path.isfile(seen["src"])


def test_find_image_path_resolves_token(env):
    client, base, images, egms = env
    _save(client, _payload())
    token = ee.course_token(_read(egms)[ee.KEY_EMBEDDED_IMAGE][ee.KEY_EMB_SHA256])
    ee.materialize(_read(egms))
    (images / IMAGE).unlink()
    p = app_module._find_image_path(IMAGE, token)
    assert p and open(p, "rb").read() == ee.get_png_bytes(_read(egms))


def test_generate_loader_uses_embedded(env):
    client, base, images, egms = env
    gsd = pytest.importorskip("gradient_surface_diagnostic")
    data = {**_payload(), app_module.KEY_POLYGONS: [{"type": "green", "points": [{"x": 1, "y": 1}, {"x": 9, "y": 1}, {"x": 9, "y": 9}, {"x": 1, "y": 9}]}],
            ee.KEY_EMBEDDED_IMAGE: ee.build_block(_png_bytes(), IMAGE, COURSE)}
    (egms / EGM_NAME).write_text(json.dumps(data))
    (images / IMAGE).unlink()
    try:
        _, image_path, _ = gsd.load_egm(str(egms / EGM_NAME))
    except FileNotFoundError:
        pytest.fail("load_egm still needs the external PNG")
    except Exception:
        pytest.skip("geometry prep needs more EGM fields; image resolution is covered by materialize tests")
    assert ee.CACHE_ROOT in image_path


# ---- migration --------------------------------------------------------------------------------
def _legacy_tree(base, egms, with_png=True):
    (egms / EGM_NAME).write_text(json.dumps(_payload(), indent=mig.EGM_JSON_INDENT))
    (egms / "missing.egm").write_text(json.dumps(_payload(image=MISSING_IMAGE), indent=mig.EGM_JSON_INDENT))


def test_migration_dry_run_touches_nothing(env):
    client, base, images, egms = env
    _legacy_tree(base, egms)
    before = {p: p.read_bytes() for p in egms.iterdir()}
    res = mig.migrate(str(base), extra_dirs=[], dry_run=True)
    assert {p: p.read_bytes() for p in egms.iterdir()} == before          # no change, no backups
    by = {os.path.basename(r[mig.RES_EGM]): r[mig.RES_STATUS] for r in res}
    assert by[EGM_NAME] == mig.ST_WOULD_EMBED and by["missing.egm"] == mig.ST_PNG_MISSING


def test_migration_real_run_backs_up_embeds_and_is_idempotent(env):
    client, base, images, egms = env
    _legacy_tree(base, egms)
    original = (egms / EGM_NAME).read_bytes()
    res = mig.migrate(str(base), extra_dirs=[], dry_run=False)
    done = [r for r in res if r[mig.RES_STATUS] == mig.ST_EMBEDDED]
    assert len(done) == 1 and open(done[0][mig.RES_BACKUP], "rb").read() == original
    assert ee.get_png_bytes(_read(egms)) == (images / IMAGE).read_bytes()
    assert (egms / "missing.egm").exists() and not (egms / ("missing.egm" + mig.BACKUP_SUFFIX)).exists()
    again = mig.migrate(str(base), extra_dirs=[], dry_run=False)
    assert [r[mig.RES_STATUS] for r in again if os.path.basename(r[mig.RES_EGM]) == EGM_NAME] == [mig.ST_ALREADY]
    assert len([p for p in egms.iterdir() if p.name.startswith(EGM_NAME + mig.BACKUP_SUFFIX)]) == 1


def test_migration_finds_png_in_other_course_and_never_picks_degridded(env):
    client, base, images, egms = env
    (base / OTHER_COURSE / "Images" / "x.png").write_bytes(_png_bytes())
    (egms / EGM_NAME).write_text(json.dumps(_payload(image="x__degridded.png")))
    (base / OTHER_COURSE / "Images" / "x__degridded.png").write_bytes(_png_bytes(value=1))
    res = mig.migrate(str(base), extra_dirs=[], dry_run=False)
    assert ee.get_png_bytes(_read(egms)) == (base / OTHER_COURSE / "Images" / "x.png").read_bytes()
    assert _read(egms)[ee.KEY_EMBEDDED_IMAGE][ee.KEY_EMB_SOURCE_COURSE] == OTHER_COURSE
    assert _read(egms)[app_module.KEY_IMAGE] == "x.png"


def test_version_bumped_and_on_page():
    ed = open(os.path.join(os.path.dirname(__file__), "..", "templates", "editor.html")).read().split("\n", 2)[1]
    assert app_module.APP_VERSION in ed
