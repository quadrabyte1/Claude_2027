"""
test_preview3d_v72.py -- Boundary Editor live 3D preview pane, client side (APP_VERSION v7.2).

N*  core logic of static/preview3d.js under node (refresh engine, sequence numbers, errors, terrace, snapshot)
W*  source wiring: hotkey/constants single-sourced, no autosave coupling, vendored three.js, version
B*  REAL headless-browser checks against an ISOLATED Flask instance (tests/preview3d_harness.py: temp DB, temp COPY of
    the fixture EGM, autosave intercepted, spare port).  Nothing here can write to ItWentIn/ (verified at the end).

Run: python -m pytest app/tests/test_preview3d_v72.py -v -s
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest
from PIL import Image

APP_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = APP_DIR.parent
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import preview3d_harness as H  # noqa: E402
import app as app_module  # noqa: E402  (read APP_VERSION / routes only)
import preview_geometry as pg  # noqa: E402

NODE = shutil.which("node")
PREVIEW_JS = APP_DIR / "static" / "preview3d.js"
CORE_CHECKS_JS = Path(__file__).parent / "preview3d_core_checks.js"
VENDOR_DIR = APP_DIR / "static" / "vendor" / "three"
EDITOR_HTML = APP_DIR / "templates" / "editor.html"
REAL_ITWENTIN = REPO_DIR / "ItWentIn"
SCREENSHOT_DIR = REPO_DIR / "owner_inbox"
SCREENSHOT_NAME = "preview3d_phase1_v7.2.png"
SCREENSHOT_40_NAME = "preview3d_phase1_v7.2_40x40_painted.png"

VIEWPORT = {"width": 1500, "height": 1000}
CHROMIUM_ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
EDITOR_ROOT_SEL = '[x-data="polygonEditor()"]'
TOGGLE_SEL = "[data-testid=preview3d-toggle]"
PANE_SEL = "[data-testid=preview3d-pane]"
MSG_SEL = "[data-testid=preview3d-msg]"
HOST_SEL = "[data-testid=preview3d-host]"
SWATCH_SEL = "[data-testid=palette-swatch][data-step='{step}']"
EDITOR_CANVAS_SEL = "canvas[x-ref=canvas]"
OPTIONS_TOGGLE_SEL = "#options-toggle"
Z_SCALE_INPUT_SEL = 'input[x-model\\.number="zScale"]'
GREEN_STYLE_SEL = 'select[x-model="greenStyle"]'
NOTICE_BACKDROP_SEL = "#notice-dialog-backdrop"
LOAD_TIMEOUT_MS = 60_000
COLD_TIMEOUT_MS = 90_000
PAINT_STEPS = ("0", "60", "10", "50", "20", "40")       # palette swatch data-step indices (0 = +15 mm ... 60 = -15 mm), alternating high/low
PAINT_CLICK_FRACTION = (0.04, 0.04)                      # a fringe-corner cell of the editor canvas
TIMING_RUNS = 6
CANVAS_SAMPLE_PX = 48
RGB_CHANNELS = 3
CANVAS_MIN_DISTINCT_COLORS = 40
KEY_TOGGLE_PAINT = "Control+p"
STALE_WAIT_MS = 900
SERVER_ERROR_JSON = {"status": "error", "code": "internal_error", "msg": "synthetic failure"}
ROUTE_PREVIEW_GLOB = "**/api/preview"

CORE = json.loads(subprocess.run([NODE, str(CORE_CHECKS_JS), str(PREVIEW_JS)], capture_output=True, text=True, check=True).stdout) if NODE else {}
CONFIG = json.loads(subprocess.run([NODE, "-e", f"console.log(JSON.stringify(require({str(PREVIEW_JS)!r}).CONFIG))"],
                                   capture_output=True, text=True, check=True).stdout) if NODE else {}


def _tree_signature(root: Path):
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            p = Path(dirpath) / f
            try:
                st = p.stat()
                out.append((str(p), st.st_mtime_ns, st.st_size))
            except OSError:
                pass
    return sorted(out)


# --------------------------------------------------------------------------------------------------
# N: core logic under node
# --------------------------------------------------------------------------------------------------
@pytest.mark.skipif(not NODE, reason="node required")
@pytest.mark.parametrize("name", sorted(CORE))
def test_n_core(name):
    assert CORE[name] == "ok", CORE[name]


@pytest.mark.skipif(not NODE, reason="node required")
def test_n_core_covers_the_required_behaviours():
    needed = ("closed_pane_sends_nothing_and_arms_no_timer", "older_sequence_is_discarded", "one_request_in_flight_latest_wins",
              "green_cache_miss_409_keeps_surface_and_marks_stale", "busy_503_keeps_surface_and_retries",
              "server_error_and_network_failure_are_quiet_statuses", "slow_indicator_only_past_threshold",
              "drag_throttles_cheap_then_release_sends_one_full")
    assert all(n in CORE for n in needed)


# --------------------------------------------------------------------------------------------------
# W: wiring
# --------------------------------------------------------------------------------------------------
def test_w_version_matches_everywhere():
    assert CONFIG["VERSION"] == app_module.APP_VERSION
    assert app_module.APP_VERSION in EDITOR_HTML.read_text().split("\n", 2)[1]


def test_w_editor_holds_only_button_container_hotkey_and_trigger_calls():
    src = EDITOR_HTML.read_text()
    assert "Preview3D.CONFIG.HOTKEY" in src and "PREVIEW3D_HOTKEY" in src                       # hotkey is single-sourced in preview3d.js
    assert not re.search(r"e\.key\s*===\s*['\"]3['\"]", src)       # ...and never re-typed in the editor
    assert "static', filename='preview3d.js'" in src
    assert 'x-ref="preview3dPane"' in src and 'data-testid="preview3d-toggle"' in src
    assert "Preview3D.requestPreviewRefresh" in src and "Preview3D.attach" in src
    assert "THREE" not in src                                      # no three.js in the editor


def test_w_preview_code_never_touches_autosave_or_save_route():
    js = re.sub(r"/\*.*?\*/", "", PREVIEW_JS.read_text(), flags=re.S)       # code only, comments stripped
    js = re.sub(r"(?m)//.*$", "", js)
    assert "autoSave" not in js and "API_BOUNDARIES" not in js and "/api/boundaries" not in js
    assert CONFIG["API_ROUTE"] == app_module.ROUTE_API_PREVIEW
    assert CONFIG["GREEN_MODE_AUTO"] == pg.GREEN_MODE_AUTO and CONFIG["GREEN_MODE_CACHED_ONLY"] == pg.GREEN_MODE_CACHED_ONLY
    assert CONFIG["WIRE_MAGIC"] == pg.WIRE_MAGIC.decode() if isinstance(pg.WIRE_MAGIC, bytes) else CONFIG["WIRE_MAGIC"] == pg.WIRE_MAGIC
    assert CONFIG["KIND_GREEN"] == pg.KIND_GREEN and CONFIG["KIND_BOULDERS"] == pg.KIND_BOULDERS
    assert CONFIG["FRINGE_RES_FULL"] == pg.FRINGE_RES_DEFAULT


def test_w_vendored_three_is_pinned_and_offline():
    assert (VENDOR_DIR / "three.module.min.js").is_file() and (VENDOR_DIR / "OrbitControls.js").is_file()
    assert (VENDOR_DIR / "LICENSE").is_file()
    orbit = (VENDOR_DIR / "OrbitControls.js").read_text()
    assert "from './three.module.min.js'" in orbit and "from 'three'" not in orbit      # no importmap needed
    assert f'"{CONFIG["THREE_VERSION"].lstrip("r")}"' in (VENDOR_DIR / "three.module.min.js").read_text()[:600]
    assert "http" not in CONFIG["VENDOR_DIR"]


def test_w_flask_serves_the_static_files():
    client = app_module.app.test_client()
    for name in (f"/static/preview3d.js", f"/static/{CONFIG['VENDOR_DIR']}{CONFIG['THREE_FILE']}", f"/static/{CONFIG['VENDOR_DIR']}{CONFIG['ORBIT_FILE']}"):
        r = client.get(name)
        assert r.status_code == 200, name
        r.close()


# --------------------------------------------------------------------------------------------------
# B: real headless browser
# --------------------------------------------------------------------------------------------------
playwright_sync = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module", autouse=True)
def real_tree_before():
    return _tree_signature(REAL_ITWENTIN) if REAL_ITWENTIN.exists() else []


@pytest.fixture(scope="module")
def browser():
    with playwright_sync.sync_playwright() as p:
        b = p.chromium.launch(args=CHROMIUM_ARGS)
        yield b
        b.close()


@pytest.fixture(scope="module")
def harness40(tmp_path_factory):
    with H.start_harness(tmp_path_factory.mktemp("p3d40"), H.FIXTURE_GRID_FINE) as h:
        yield h


@pytest.fixture(scope="module")
def harness20(tmp_path_factory):
    with H.start_harness(tmp_path_factory.mktemp("p3d20"), H.FIXTURE_GRID_COARSE) as h:
        yield h


def open_editor(browser, h, record=None):
    page = browser.new_page(viewport=VIEWPORT)
    page.on("pageerror", lambda e: (record if record is not None else []).append(str(e)))
    if record is not None:
        page.on("request", lambda r: record.append(r.url))
    page.route("**/api/boundaries", lambda route: route.fulfill(status=200, content_type="application/json", body='{"status":"ok"}')
               if route.request.method == "POST" else route.continue_())      # second layer: autosave intercepted in the browser too
    page.goto(h.editor_url())
    page.wait_for_function(f"document.querySelector('{EDITOR_ROOT_SEL}') && Alpine.$data(document.querySelector('{EDITOR_ROOT_SEL}')).imgLoaded", timeout=LOAD_TIMEOUT_MS)
    page.wait_for_timeout(500)
    return page


def state(page, expr):
    return page.evaluate(f"(() => {{ const d = Alpine.$data(document.querySelector('{EDITOR_ROOT_SEL}')); return {expr}; }})()")


def wait_shown(page, n, timeout=COLD_TIMEOUT_MS):
    page.wait_for_function(f"Preview3D.debug().shown >= {n} && Preview3D.debug().status === 'idle'", timeout=timeout)


def paint_cell(page, step):
    page.click(SWATCH_SEL.format(step=step))
    box = page.locator(EDITOR_CANVAS_SEL).bounding_box()
    page.mouse.click(box["x"] + box["width"] * PAINT_CLICK_FRACTION[0], box["y"] + box["height"] * PAINT_CLICK_FRACTION[1])


TIMER_JS = """
window.__t = { up: null, shownAt: null, renderedAt: null };
(() => {
  document.addEventListener('mouseup', () => { window.__t.up = performance.now(); window.__t.shownAt = null; window.__t.renderedAt = null;
      window.__t.s0 = Preview3D.debug().shown; window.__t.r0 = Preview3D.debug().renderCount; }, true);
  const tick = () => { const d = Preview3D.debug(), t = window.__t;
    if (t.up !== null && t.shownAt === null && d.shown > t.s0) t.shownAt = performance.now();
    if (t.shownAt !== null && t.renderedAt === null && d.renderCount > t.r0) t.renderedAt = performance.now();
    requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
})();
"""


def test_b_hotkey_button_typing_and_no_traffic_while_closed(browser, harness40):
    log: list[str] = []
    page = open_editor(browser, harness40, log)
    try:
        # closed by default: no pane, no GL canvas, no three.js download, no preview request, even while editing
        assert state(page, "d.preview3dOpen") is False
        assert page.locator(HOST_SEL).count() == 0 and page.locator(f"{PANE_SEL} canvas").count() == 0
        paint_cell(page, PAINT_STEPS[0])
        page.wait_for_timeout(STALE_WAIT_MS)
        assert harness40.state()["previews"] == 0
        assert not any("three.module" in u or "/api/preview" in u for u in log)

        # typing in an input never toggles
        if not state(page, "d.optionsOpen"):
            page.click(OPTIONS_TOGGLE_SEL)
        page.wait_for_selector(Z_SCALE_INPUT_SEL, state="visible")
        page.focus(Z_SCALE_INPUT_SEL)
        assert page.evaluate("document.activeElement.tagName") == "INPUT"      # really typing in a field
        page.keyboard.press(CONFIG["HOTKEY"])
        assert state(page, "d.preview3dOpen") is False
        page.keyboard.press("Escape")
        page.evaluate("document.activeElement.blur()")

        # plain key opens, plain key closes
        page.keyboard.press(CONFIG["HOTKEY"])
        assert state(page, "d.preview3dOpen") is True
        page.wait_for_selector(HOST_SEL)
        wait_shown(page, 1)
        assert any("three.module" in u for u in log)           # lazy-loaded on first open
        page.keyboard.press(CONFIG["HOTKEY"])
        assert state(page, "d.preview3dOpen") is False
        page.wait_for_timeout(300)
        assert page.evaluate("Preview3D.debug().glActive") is False      # GL context released when closed
        sent = harness40.state()["previews"]
        paint_cell(page, PAINT_STEPS[1])
        page.wait_for_timeout(STALE_WAIT_MS)
        assert harness40.state()["previews"] == sent             # closed again: no more requests

        # the 3D button does the same
        page.click(TOGGLE_SEL)
        assert state(page, "d.preview3dOpen") is True
        page.click(TOGGLE_SEL)
        assert state(page, "d.preview3dOpen") is False
        assert page.query_selector(NOTICE_BACKDROP_SEL) is None
        assert harness40.state()["saves"] >= 0 and harness40.state()["refused"] == []
    finally:
        page.close()


def test_b_keys_pass_through_to_the_editor_when_pane_has_focus(browser, harness40):
    page = open_editor(browser, harness40)
    try:
        page.keyboard.press(CONFIG["HOTKEY"])
        page.wait_for_selector(HOST_SEL)
        wait_shown(page, 1)
        page.focus(HOST_SEL)
        assert page.evaluate("document.activeElement.getAttribute('data-testid')") == "preview3d-host"
        before = state(page, "d.paintMode")
        page.keyboard.press(KEY_TOGGLE_PAINT)                     # editor's own chord, pressed while the pane is focused
        assert state(page, "d.paintMode") != before
        page.keyboard.press(CONFIG["HOTKEY"])                     # the hotkey also works from inside the pane
        assert state(page, "d.preview3dOpen") is False
    finally:
        page.close()


def test_b_decoder_matches_python_decoder_on_a_real_response(browser, harness40):
    page = open_editor(browser, harness40)
    try:
        snap = json.loads(H.FIXTURE_EGM.read_text())
        body = json.dumps({"snapshot": snap, "seq": 11, "fringeRes": 64})
        summary_js = page.evaluate("""async (body) => {
            const r = await fetch('/api/preview', {method:'POST', headers:{'Content-Type':'application/json'}, body});
            const d = Preview3D.decodePreview(await r.arrayBuffer());
            const sum = (a) => { let t = 0; for (const v of a) t += v; return t; };
            return { seq: d.header.seq, plate: d.header.plateHalf, parts: d.parts.map(p => [p.kind, p.index, p.nx, p.ny, sum(p.heights), sum(p.mask), p.zmin, p.zmax]),
                     markers: d.markers.map(m => [m.kind, m.x, m.y, m.z, m.radius]) };
        }""", body)
        req = urllib.request.Request(harness40.base_url + "/api/preview", data=body.encode(), headers={"Content-Type": "application/json"})
        dec = pg.decode_preview(urllib.request.urlopen(req, timeout=120).read())
        assert summary_js["seq"] == 11
        assert len(summary_js["parts"]) == len(dec["parts"])
        for js_p, py_p in zip(summary_js["parts"], dec["parts"]):
            assert js_p[0] == py_p["kind"] and js_p[1] == py_p["index"] and js_p[2] == py_p["nx"] and js_p[3] == py_p["ny"]
            assert js_p[4] == pytest.approx(float(py_p["heights"].sum()), rel=1e-4, abs=1e-2)
            assert js_p[5] == int(py_p["mask"].sum())
        assert len(summary_js["markers"]) == len(dec["markers"])
    finally:
        page.close()


def test_b_smooth_terraced_switch_makes_no_server_call(browser, harness40):
    page = open_editor(browser, harness40)
    try:
        page.keyboard.press(CONFIG["HOTKEY"])
        wait_shown(page, 1)
        if not state(page, "d.optionsOpen"):
            page.click(OPTIONS_TOGGLE_SEL)
        sent = harness40.state()["previews"]
        for style in (CONFIG["GREEN_STYLE_SMOOTH"], CONFIG["GREEN_STYLE_TERRACED"]):
            page.select_option(GREEN_STYLE_SEL, style)
            page.wait_for_function(f"Preview3D.debug().greenStyle === '{style}'")
            page.wait_for_timeout(STALE_WAIT_MS)
            assert harness40.state()["previews"] == sent
        assert CONFIG["LABEL_STYLE_TERRACED"] in page.locator("[data-testid=preview3d-scale]").inner_text()
    finally:
        page.close()


def test_b_preview_errors_are_quiet_in_pane_not_the_error_dialog(browser, harness40):
    page = open_editor(browser, harness40)
    try:
        page.route(ROUTE_PREVIEW_GLOB, lambda route: route.fulfill(status=500, content_type="application/json", body=json.dumps(SERVER_ERROR_JSON)))
        page.keyboard.press(CONFIG["HOTKEY"])
        page.wait_for_selector(MSG_SEL, state="visible", timeout=LOAD_TIMEOUT_MS)
        assert "synthetic failure" in page.locator(MSG_SEL).inner_text()
        assert page.query_selector(NOTICE_BACKDROP_SEL) is None            # the shared Error dialog never appeared
        assert page.locator(HOST_SEL).count() == 1                          # pane still usable; painting unaffected
        paint_cell(page, PAINT_STEPS[2])
        assert page.query_selector(NOTICE_BACKDROP_SEL) is None
        assert CONFIG["LABEL_APPROX"] in page.locator(PANE_SEL).inner_text()
    finally:
        page.close()


def test_b_green_cache_miss_and_busy_are_handled_in_the_browser(browser, harness40):
    page = open_editor(browser, harness40)
    try:
        page.keyboard.press(CONFIG["HOTKEY"])
        wait_shown(page, 1)
        shown = page.evaluate("Preview3D.debug().shown")
        page.route(ROUTE_PREVIEW_GLOB, lambda route: route.fulfill(
            status=CONFIG["HTTP_STATUS_UNAVAILABLE"], content_type="application/json",
            body=json.dumps({"status": "error", "code": CONFIG["ERR_CODE_BUSY"], "msg": "busy"})))
        paint_cell(page, PAINT_STEPS[3])
        page.wait_for_selector(f"{MSG_SEL}[data-kind=busy]", state="visible")
        assert page.evaluate("Preview3D.debug().shown") == shown          # last good surface kept
        assert page.evaluate("Preview3D.debug().meshCount") > 0
        page.unroute(ROUTE_PREVIEW_GLOB)
        page.wait_for_function(f"Preview3D.debug().shown > {shown}", timeout=CONFIG["BUSY_RETRY_MS"] * 5)   # resumes by itself
    finally:
        page.close()


def _measure(browser, h, label, shot_name=None):
    page = open_editor(browser, h)
    try:
        page.evaluate(TIMER_JS)
        page.keyboard.press(CONFIG["HOTKEY"])
        page.wait_for_selector(HOST_SEL)
        cold_t0 = page.evaluate("performance.now()")
        wait_shown(page, 1)
        cold_ms = page.evaluate("performance.now()") - cold_t0
        page.wait_for_function("Preview3D.debug().meshCount > 0 && Preview3D.debug().renderCount > 0")
        assert page.evaluate("Preview3D.debug().glActive") is True
        assert page.locator(f"{PANE_SEL} canvas").count() == 1
        # a WebGL canvas that really rendered: the element screenshot holds many distinct colours, not one flat fill
        page.wait_for_timeout(500)
        shot = Image.open(io.BytesIO(page.locator(f"{PANE_SEL} canvas").screenshot())).convert("RGB")
        assert len({tuple(px) for px in zip(*[iter(shot.resize((CANVAS_SAMPLE_PX, CANVAS_SAMPLE_PX)).tobytes())] * RGB_CHANNELS)}) > CANVAS_MIN_DISTINCT_COLORS
        d0 = page.evaluate("Preview3D.debug()")
        assert set(d0["parts"]) >= {pg.KIND_GREEN, pg.KIND_FRINGE}
        if shot_name:
            SCREENSHOT_DIR.mkdir(exist_ok=True)
            page.wait_for_timeout(600)
            page.screenshot(path=str(SCREENSHOT_DIR / SCREENSHOT_NAME))
        sums = [d0["fringeSum"]]
        shown_ms, render_ms = [], []
        for i in range(TIMING_RUNS):
            n = page.evaluate("Preview3D.debug().shown")
            paint_cell(page, PAINT_STEPS[i % len(PAINT_STEPS)])
            wait_shown(page, n + 1, timeout=LOAD_TIMEOUT_MS)
            page.wait_for_function("window.__t.renderedAt !== null")
            t = page.evaluate("window.__t")
            shown_ms.append(t["shownAt"] - t["up"]); render_ms.append(t["renderedAt"] - t["up"])
            sums.append(page.evaluate("Preview3D.debug().fringeSum"))
        assert len(set(round(s, 3) for s in sums)) > 1, "the fringe surface never changed after painting cells"
        if shot_name:
            page.wait_for_timeout(400)
            page.screenshot(path=str(SCREENSHOT_DIR / SCREENSHOT_40_NAME))
        stats = {"label": label, "cold_ms": round(cold_ms), "median_mouseup_to_surface_ms": round(statistics.median(shown_ms)),
                 "median_mouseup_to_rendered_ms": round(statistics.median(render_ms)), "max_rendered_ms": round(max(render_ms)),
                 "server_ms_last": round(page.evaluate("Preview3D.debug().serverMs")), "all_rendered_ms": [round(v) for v in render_ms]}
        print("\nPREVIEW3D-TIMING", json.dumps(stats))
        assert h.state()["refused"] == []
        return stats
    finally:
        page.close()


def test_b_real_round_trip_paint_updates_surface_40x40(browser, harness40):
    saves0 = harness40.state()["saves"]
    stats = _measure(browser, harness40, "40x40", shot_name=SCREENSHOT_NAME)
    assert stats["max_rendered_ms"] < 5000
    assert harness40.state()["saves"] >= saves0            # autosave belongs to the editor; the preview adds none (checked in the next test)


def test_b_real_round_trip_paint_updates_surface_20x20(browser, harness20):
    stats = _measure(browser, harness20, "20x20")
    assert stats["max_rendered_ms"] < 5000


def test_b_preview_alone_never_triggers_autosave(browser, harness20):
    page = open_editor(browser, harness20)
    try:
        page.wait_for_timeout(STALE_WAIT_MS)
        saves0 = harness20.state()["saves"]
        page.keyboard.press(CONFIG["HOTKEY"])
        wait_shown(page, 1)
        page.keyboard.press(CONFIG["HOTKEY"])
        page.wait_for_timeout(STALE_WAIT_MS)
        assert harness20.state()["saves"] == saves0
    finally:
        page.close()


def test_z_real_itwentin_tree_untouched(real_tree_before):
    after = _tree_signature(REAL_ITWENTIN) if REAL_ITWENTIN.exists() else []
    assert after == real_tree_before
