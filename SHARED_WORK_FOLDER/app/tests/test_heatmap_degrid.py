"""
test_heatmap_degrid.py -- task #590: erase the baked-in grid from heat-map PNGs.

Run: python -m pytest app/tests/test_heatmap_degrid.py -v
All file I/O is in pytest tmp dirs; no live DB / EGM is touched.  Tunables are
imported from heatmap_degrid / app so a change there cannot leave a stale copy here.
"""
import hashlib
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

APP_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(APP_DIR))

import heatmap_degrid as H  # noqa: E402

# ---- fixture parameters (test-only) -----------------------------------------
BG = 226
LINE_VALUE = 190
MAJOR_VALUE = 160
FIX_W, FIX_H = 400, 300
FIX_PERIOD = 25
FIX_OFFSET_X, FIX_OFFSET_Y = 7, 11
MAJOR_EVERY = 5
FEATURE_COLOR = (80, 40, 0)          # dark navy-ish BGR "arrow"
FEATURE_BOX = (150, 120, 230, 190)   # x0, y0, x1, y1
HEAT_COLOR = (60, 220, 20)           # saturated green BGR
SAMPLE_COURSES = ("Delaveaga", "Stanford")
GOLF_ROOT = APP_DIR.parent / "ItWentIn" / "GolfCourses"
TOLERANCE = 2                        # max abs gray diff regarded as "restored"
REAL_RESIDUAL_MAX_FRAC = 0.05        # <5% of background grid-line pixels may remain


def _flat():
    img = np.full((FIX_H, FIX_W, 3), BG, np.uint8)
    cv2.rectangle(img, FEATURE_BOX[:2], FEATURE_BOX[2:], HEAT_COLOR, -1)          # heat blob
    cv2.line(img, (20, 20), (380, 40), FEATURE_COLOR, 3)                           # dark outline-ish stroke
    cv2.rectangle(img, (300, 200), (340, 260), FEATURE_COLOR, -1)                  # "arrow"
    return img


def _gridded(flat):
    img = flat.copy()
    bg_mask = (flat == BG).all(axis=2)   # grid only drawn on the page background
    for k, x in enumerate(range(FIX_OFFSET_X, FIX_W, FIX_PERIOD)):
        v = MAJOR_VALUE if k % MAJOR_EVERY == 0 else LINE_VALUE
        col = img[:, x]; m = bg_mask[:, x]; col[m] = v
    for k, y in enumerate(range(FIX_OFFSET_Y, FIX_H, FIX_PERIOD)):
        v = MAJOR_VALUE if k % MAJOR_EVERY == 0 else LINE_VALUE
        row = img[y]; m = bg_mask[y]; row[m] = v
    return img


def test_synthetic_grid_removed_and_features_intact():
    flat = _flat()
    gridded = _gridded(flat)
    assert np.abs(gridded.astype(int) - flat.astype(int)).max() > TOLERANCE
    out, info = H.degrid(gridded, return_info=True)
    assert info[H.INFO_FOUND]
    assert abs(info[H.INFO_X][H.INFO_PERIOD] - FIX_PERIOD) < 0.5
    assert abs(info[H.INFO_Y][H.INFO_PERIOD] - FIX_PERIOD) < 0.5
    diff = np.abs(out.astype(int) - flat.astype(int)).max(axis=2)
    feat = (flat != BG).any(axis=2)
    near_feat = cv2.dilate(feat.astype(np.uint8), np.ones((H.FEATURE_PROTECT_KSIZE + H.MIN_RUN_PX,) * 2, np.uint8)).astype(bool)
    assert diff[~near_feat].max() <= TOLERANCE, "grid residue on the plain background"
    assert diff[feat].max() <= TOLERANCE, "feature pixels were damaged"


def test_input_not_mutated():
    gridded = _gridded(_flat())
    before = gridded.copy()
    H.degrid(gridded)
    assert np.array_equal(gridded, before)


def test_no_grid_passthrough_unchanged():
    flat = _flat()
    out, info = H.degrid(flat, return_info=True)
    assert not info[H.INFO_FOUND]
    assert out is flat
    assert np.array_equal(out, _flat())


def test_non_uint8_and_none_passthrough():
    assert H.degrid(None) is None
    f = np.zeros((10, 10, 3), np.float32)
    assert H.degrid(f) is f


def _sample_paths():
    out = []
    for c in SAMPLE_COURSES:
        d = GOLF_ROOT / c / "Images"
        if d.is_dir():
            out += sorted(d.glob("*.png"))
    return out


@pytest.mark.skipif(not _sample_paths(), reason="no real heat-map samples in repo")
def test_real_samples_lines_removed():
    checked = 0
    for path in _sample_paths():
        img = cv2.imread(str(path))
        if img is None:
            continue
        out, info = H.degrid(img, return_info=True)
        if not info[H.INFO_FOUND]:
            continue
        checked += 1
        g_in = img.astype(np.float32).mean(axis=2)
        g_out = out.astype(np.float32).mean(axis=2)
        dark_in = H._darkening(g_in)
        dark_out = H._darkening(g_out)
        w = img.shape[1]
        cols = [int(round(p)) for p in H._lattice_positions(info[H.INFO_X][H.INFO_PERIOD], info[H.INFO_X][H.INFO_OFFSET], w)
                if 0 <= int(round(p)) < w]
        # bg-flanked grid pixels on the vertical lines before/after
        spread = img.astype(np.float32).max(axis=2) - img.astype(np.float32).min(axis=2)
        cand = H._axis_candidates(g_in, spread)
        sel = np.zeros_like(cand); sel[:, cols] = True
        sel &= cand
        assert sel.sum() > 0
        remaining = (dark_out[sel] >= H.MIN_DARKEN).mean()
        assert remaining < REAL_RESIDUAL_MAX_FRAC, f"{path.name}: {remaining:.1%} of grid-line pixels remain"
        if checked >= 2:
            break
    assert checked >= 1, "no sample had a detectable grid"


@pytest.mark.skipif(not _sample_paths(), reason="no real heat-map samples in repo")
def test_golflogix_style_screenshot_has_no_grid():
    # Firefly (GolfLogix screenshot) has no baked-in grid -> untouched
    p = GOLF_ROOT / "Firefly" / "Images" / "Firefly Golf Links (14).png"
    if not p.exists():
        pytest.skip("Firefly sample missing")
    img = cv2.imread(str(p))
    out, info = H.degrid(img, return_info=True)
    assert not info[H.INFO_FOUND] and out is img


def test_degrid_file_leaves_original_untouched(tmp_path):
    src = tmp_path / "hole.png"
    cv2.imwrite(str(src), _gridded(_flat()))
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    info = H.degrid_file(str(src))
    assert info[H.INFO_WRITTEN]
    dst = Path(H.degridded_path(str(src)))
    assert dst.exists() and dst.parent == src.parent and dst.name.endswith(H.DEGRID_SUFFIX + H.DEGRID_EXT)
    assert hashlib.sha256(src.read_bytes()).hexdigest() == digest


def test_degrid_file_no_grid_writes_nothing(tmp_path):
    src = tmp_path / "plain.png"
    cv2.imwrite(str(src), _flat())
    info = H.degrid_file(str(src))
    assert not info[H.INFO_WRITTEN]
    assert not Path(H.degridded_path(str(src))).exists()


def test_degrid_file_unreadable(tmp_path):
    info = H.degrid_file(str(tmp_path / "missing.png"))
    assert info[H.INFO_ERROR] == H.ERR_UNREADABLE


# ---- server wiring ----------------------------------------------------------
@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app as A
    base = tmp_path / "GolfCourses"
    img_dir = base / "TestCourse" / "Images"
    img_dir.mkdir(parents=True)
    cv2.imwrite(str(img_dir / "hole.png"), _gridded(_flat()))
    monkeypatch.setattr(A, "_EGM_BASE", str(base))
    monkeypatch.setattr(A, "_TEAM_INBOX", str(tmp_path / "team_inbox"))
    return A, A.app.test_client(), img_dir


def test_degrid_route_writes_next_to_original_and_hides_from_picker(client):
    A, c, img_dir = client
    orig = img_dir / "hole.png"
    digest = hashlib.sha256(orig.read_bytes()).hexdigest()
    r = c.post("/api/degrid_image", json={"image": "hole.png", "imageCourse": "TestCourse"}).get_json()
    assert r["status"] == "ok" and r["found"]
    assert (img_dir / ("hole" + H.DEGRID_SUFFIX + H.DEGRID_EXT)).exists()
    assert r["degriddedUrl"] == A.EGM_IMAGE_URL_FMT.format(course="TestCourse", filename="hole" + H.DEGRID_SUFFIX + H.DEGRID_EXT)
    assert hashlib.sha256(orig.read_bytes()).hexdigest() == digest
    names = [i["filename"] for i in A._collect_course_images()]
    assert names == ["hole.png"]


def test_degrid_route_missing_image_400(client):
    A, c, _ = client
    assert c.post("/api/degrid_image", json={"image": "nope.png"}).status_code == 400


def test_detection_input_follows_flag(client, monkeypatch):
    A, c, img_dir = client
    c.post("/api/degrid_image", json={"image": "hole.png", "imageCourse": "TestCourse"})
    seen = []
    real = cv2.imread
    monkeypatch.setattr(cv2, "imread", lambda p, *a, **k: (seen.append(p), real(p, *a, **k))[1])
    for flag in (False, True):
        seen.clear()
        monkeypatch.setattr(A, "DEGRID_DETECT_ON_CLEANED", flag)
        c.post("/api/detect_boundaries", json={"image": "hole.png", "course": "TestCourse", "imageCourse": "TestCourse"})
        assert seen, "detect_boundaries did not read the image"
        assert seen[0].endswith(H.DEGRID_SUFFIX + H.DEGRID_EXT) == flag


# ---- editor wiring ----------------------------------------------------------
EDITOR_HEADER_RE = r"\{#\s*Boundary Editor (v\d+(?:\.\d+)+) "


def _version_tuple(version: str) -> tuple:
    """'v5.73' -> (5, 73) so versions compare numerically (v5.9 < v5.10)."""
    return tuple(int(part) for part in version.lstrip("v").split("."))


def test_editor_wiring():
    import app as A
    html = (APP_DIR / "templates" / "editor.html").read_text()
    # The editor.html changelog header ("{# Boundary Editor vX.Y ...") carries the editor's own
    # last-changed version.  APP_VERSION is the unified app-wide footer version, so it can run
    # ahead of the editor changelog (other pages bump it); read the header instead of
    # hard-coding a version, and require it to be well-formed and never newer than APP_VERSION.
    m = re.search(EDITOR_HEADER_RE, html)
    assert m, "editor.html must start with a '{# Boundary Editor vX.Y ' changelog header"
    assert _version_tuple(m.group(1)) <= _version_tuple(A.APP_VERSION)
    assert "{{ app_version }}" in html          # footer renders the unified app version
    assert "degrid-view-switch" in html
    assert "this._pendingDegrid = true;   // v5.69: Create New Project only" in html
    # the degrid fetch is only reachable from the pending flag (Open Project never sets it)
    assert html.count("_pendingDegrid = true") == 1
    assert "this.DEGRID_API_URL" in html
