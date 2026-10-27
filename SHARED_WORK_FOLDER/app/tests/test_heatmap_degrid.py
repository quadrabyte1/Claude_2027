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
REAL_RESIDUAL_MAX_FRAC = 0.03        # <3% of background grid-line pixels may remain


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
            out += [q for q in sorted(d.glob("*.png")) if not q.stem.endswith(H.DEGRID_SUFFIX)]
    return out


NO_GRID_SAMPLES = (                  # GolfLogix / Firefly style screenshots: no baked-in grid
    ("Firefly", "Firefly Golf Links (14).png"),
    ("Firefly", "Firefly Golf Links (14a).png"),
    ("Seabright", "FantasyGolfCourse (5).png"),
    ("Stanford", "Stanford (Hole 8 gl).png"),
)
BIG_SAMPLE = GOLF_ROOT / "Delaveaga" / "Images" / "Delaveaga (Hole 11, 55171) 9 in.png"   # zoomed: 44 px period, ~5 px soft lines
NEUTRAL_MAX_SPREAD = 40              # same meaning as H.NEUTRAL_SPREAD, kept explicit for the measurement
FLAT_FLANK_GAP = 6.0                 # measurement: flanks of a background line pixel agree within this
HEAT_FLANK_GAP = 14.0                # measurement: ...and within this for heat-map pixels
LINE_MIN_DARKNESS = 2.0              # a pixel darker than its flanks by this is "a line pixel"
MIN_LINE_PIXELS = 50                 # lines with fewer measurable pixels are skipped
LINE_RESIDUAL_MAX_FRAC = 0.25        # every single line (major and minor): < this fraction may remain
HEAT_DEVIATION_RATIO_MAX = 0.5       # median colour deviation along the lines inside the heat map must at least halve
HEAT_DEVIATION_MAX = 60.0            # deviations beyond this are features, not grid
MAJOR_OVER_MEDIAN = 1.3              # a line this much darker than the median line is a "major" line
FEATURE_ALTERED_MAX_FRAC = 0.002     # <0.2% of dark feature pixels may change (outline shoulders at lattice crossings)
ARROW_GRAY_MAX = 70.0                # navy arrows / black outline: grey below this
WIDE_PERIOD, WIDE_HALF_WIDTH = 44, 3  # synthetic zoomed grid: soft 7 px wide lines


def _measure_lines(img, out, info):
    """Per line, on the INPUT's flanks: (axis, lo, mean_darkness, residual_frac, n) for the
    page-background pixels, and (median colour deviation before, after, n) for heat-map pixels."""
    g, spread = H._gray_spread(img)
    g_out, _ = H._gray_spread(out)
    c_in, c_out = img.astype(np.float32), out.astype(np.float32)
    bg_rows, heat_before, heat_after = [], [], []
    for transposed, key in ((False, H.INFO_X), (True, H.INFO_Y)):
        gi, si, go, ci, co = (g.T, spread.T, g_out.T, c_in.swapaxes(0, 1), c_out.swapaxes(0, 1)) if transposed \
            else (g, spread, g_out, c_in, c_out)
        for lo, hi in info[key][H.INFO_LINES]:
            c = (lo + hi) // 2
            flank = (gi[:, lo - 1] + gi[:, hi + 1]) / 2
            neutral = (si[:, c] <= NEUTRAL_MAX_SPREAD) & (si[:, lo - 1] <= NEUTRAL_MAX_SPREAD) & (si[:, hi + 1] <= NEUTRAL_MAX_SPREAD)
            sel = neutral & (np.abs(gi[:, lo - 1] - gi[:, hi + 1]) <= FLAT_FLANK_GAP) & (flank - gi[:, c] >= LINE_MIN_DARKNESS)
            if sel.sum() >= MIN_LINE_PIXELS:
                bg_rows.append((key, lo, float((flank - gi[:, c])[sel].mean()),
                                float(((flank - go[:, c])[sel] >= LINE_MIN_DARKNESS).mean()), int(sel.sum())))
            cl, cr = ci[:, lo - 1], ci[:, hi + 1]
            fm = (cl + cr) / 2
            hs = (~neutral) & (np.abs(cl - cr).max(axis=1) <= HEAT_FLANK_GAP)
            before = np.abs(fm - ci[:, c]).max(axis=1)
            after = np.abs(fm - co[:, c]).max(axis=1)
            hs &= before <= HEAT_DEVIATION_MAX
            heat_before += list(before[hs]); heat_after += list(after[hs])
    return bg_rows, np.array(heat_before), np.array(heat_after)


def _need_samples():
    if not _sample_paths():
        pytest.skip("no real heat-map samples in repo")


def test_wide_soft_lines_removed_synthetic():
    """A zoomed screenshot draws SOFT lines far wider than the old 3 px flank distance."""
    flat = _flat()
    img = flat.copy()
    bg = (flat == BG).all(axis=2)
    profile = np.array([-3, 3, 18, 32, 18, 3, -3], float)     # soft bar with sharpening ringing
    for x in range(10, FIX_W - 10, WIDE_PERIOD):
        for k, d in enumerate(profile):
            xx = x + k - WIDE_HALF_WIDTH
            img[:, xx][bg[:, xx]] = BG - d
    for y in range(12, FIX_H - 10, WIDE_PERIOD):
        for k, d in enumerate(profile):
            yy = y + k - WIDE_HALF_WIDTH
            img[yy][bg[yy]] = np.minimum(img[yy][bg[yy]], BG - d)
    out, info = H.degrid(img, return_info=True)
    assert info[H.INFO_FOUND]
    assert abs(info[H.INFO_X][H.INFO_PERIOD] - WIDE_PERIOD) < 0.5
    diff = np.abs(out.astype(int) - flat.astype(int)).max(axis=2)
    feat = (flat != BG).any(axis=2)
    near_feat = cv2.dilate(feat.astype(np.uint8), np.ones((H.FEATURE_PROTECT_KSIZE + H.MIN_RUN_PX,) * 2, np.uint8)).astype(bool)
    assert diff[~near_feat].max() <= TOLERANCE + 2


@pytest.mark.skipif(not BIG_SAMPLE.exists(), reason="9 in sample missing")
def test_big_sample_major_and_minor_lines_removed():
    img = cv2.imread(str(BIG_SAMPLE))
    out, info = H.degrid(img, return_info=True)
    assert info[H.INFO_FOUND]
    assert abs(info[H.INFO_X][H.INFO_PERIOD] - info[H.INFO_Y][H.INFO_PERIOD]) < 0.5
    rows, _, _ = _measure_lines(img, out, info)
    darkness = np.array([r[2] for r in rows])
    major = darkness > MAJOR_OVER_MEDIAN * np.median(darkness)
    assert major.sum() >= 2 and (~major).sum() >= 10, "sample should contain both major and minor lines"
    for (key, lo, dark, resid, n), is_major in zip(rows, major):
        assert resid < LINE_RESIDUAL_MAX_FRAC, f"{key} line at {lo} ({'major' if is_major else 'minor'}): {resid:.0%} remains"
    total = sum(r[3] * r[4] for r in rows) / sum(r[4] for r in rows)
    assert total < REAL_RESIDUAL_MAX_FRAC, f"{total:.1%} of line pixels remain"


@pytest.mark.skipif(not BIG_SAMPLE.exists(), reason="9 in sample missing")
def test_through_heatmap_line_contrast_reduced():
    img = cv2.imread(str(BIG_SAMPLE))
    out, info = H.degrid(img, return_info=True)
    _, before, after = _measure_lines(img, out, info)
    assert len(before) > 5000, "expected many line pixels inside the heat map"
    assert np.median(before) > 3 * H.HEAT_MIN_DEVIATION
    assert np.median(after) <= HEAT_DEVIATION_RATIO_MAX * np.median(before)
    assert (after >= H.HEAT_MIN_DEVIATION).mean() < 0.5 * (before >= H.HEAT_MIN_DEVIATION).mean()


@pytest.mark.skipif(not BIG_SAMPLE.exists(), reason="9 in sample missing")
def test_features_preserved_and_changes_confined_to_lattice():
    img = cv2.imread(str(BIG_SAMPLE))
    out, info = H.degrid(img, return_info=True)
    h, w = img.shape[:2]
    on_lattice = np.zeros((h, w), dtype=bool)
    for lo, hi in info[H.INFO_X][H.INFO_LINES]:
        on_lattice[:, lo:hi + 1] = True
    for lo, hi in info[H.INFO_Y][H.INFO_LINES]:
        on_lattice[lo:hi + 1, :] = True
    changed = (img != out).any(axis=2)
    assert changed.any() and not (changed & ~on_lattice).any(), "pixels changed OFF the grid lattice"
    gray, _ = H._gray_spread(img)
    dark_feature = gray < ARROW_GRAY_MAX             # navy arrows, black outline and label strokes
    assert dark_feature.sum() > 10000
    altered = (changed & dark_feature).sum() / dark_feature.sum()
    assert altered < FEATURE_ALTERED_MAX_FRAC, f"{altered:.2%} of arrow / outline / label pixels were altered"
    # faint contour lines inside the heat map: their pixels (colour-different from the local
    # background) off the lattice are untouched by construction; on the lattice the changed
    # fraction stays small, i.e. no wholesale repaint of the heat map
    assert changed.mean() < 0.2


@pytest.mark.skipif(not _sample_paths(), reason="no real heat-map samples in repo")
def test_all_real_samples_lines_removed():
    found = 0
    for path in _sample_paths():
        img = cv2.imread(str(path))
        out, info = H.degrid(img, return_info=True)
        if not info[H.INFO_FOUND]:
            continue
        found += 1
        rows, before, after = _measure_lines(img, out, info)
        total = sum(r[3] * r[4] for r in rows) / sum(r[4] for r in rows)
        assert total < REAL_RESIDUAL_MAX_FRAC, f"{path.name}: {total:.1%} of line pixels remain"
        assert max(r[3] for r in rows) < LINE_RESIDUAL_MAX_FRAC, f"{path.name}: a line mostly remains"
        assert np.median(after) <= HEAT_DEVIATION_RATIO_MAX * np.median(before), f"{path.name}: heat-map lines remain"
    assert found >= 10, "expected the Delaveaga + Stanford StrackaLine samples to have a detectable grid"


@pytest.mark.parametrize("course,name", NO_GRID_SAMPLES)
def test_no_grid_real_screenshots_pass_through(course, name):
    p = GOLF_ROOT / course / "Images" / name
    if not p.exists():
        pytest.skip(f"{name} missing")
    img = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
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


def test_cache_invalidated_when_algo_version_changes(client, monkeypatch):
    A, c, img_dir = client
    cached = img_dir / ("hole" + H.DEGRID_SUFFIX + H.DEGRID_EXT)
    c.post("/api/degrid_image", json={"image": "hole.png", "imageCourse": "TestCourse"})
    assert H.png_algo_version(str(cached)) == H.DEGRID_ALGO_VERSION
    first = cached.read_bytes()
    # fresh cache is reused: same bytes, not rewritten
    marker = cached.stat().st_mtime_ns
    c.post("/api/degrid_image", json={"image": "hole.png", "imageCourse": "TestCourse"})
    assert cached.stat().st_mtime_ns == marker
    # a newer algorithm makes the (newer-than-source) cache stale -> regenerated + restamped
    monkeypatch.setattr(H, "DEGRID_ALGO_VERSION", H.DEGRID_ALGO_VERSION + 1)
    r = c.post("/api/degrid_image", json={"image": "hole.png", "imageCourse": "TestCourse"}).get_json()
    assert r["found"]
    assert H.png_algo_version(str(cached)) == H.DEGRID_ALGO_VERSION
    assert cached.stat().st_mtime_ns != marker


def test_unstamped_legacy_cache_is_regenerated(client):
    A, c, img_dir = client
    cached = img_dir / ("hole" + H.DEGRID_SUFFIX + H.DEGRID_EXT)
    cv2.imwrite(str(cached), _gridded(_flat()))          # old-style file: no version stamp
    assert H.png_algo_version(str(cached)) is None
    assert not H.cache_is_fresh(str(img_dir / "hole.png"), str(cached))
    c.post("/api/degrid_image", json={"image": "hole.png", "imageCourse": "TestCourse"})
    assert H.png_algo_version(str(cached)) == H.DEGRID_ALGO_VERSION
    assert cv2.imread(str(cached)) is not None            # still a valid PNG


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
