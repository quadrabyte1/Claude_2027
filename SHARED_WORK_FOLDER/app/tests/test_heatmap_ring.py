"""
test_heatmap_ring.py -- erase the offset distance ring (+ its multiples-of-five numbers)
from StrackaLine heat-map PNGs, keeping the real green outline, heat map, arrows,
value labels and compass.

Run: python -m pytest app/tests/test_heatmap_ring.py -v
All file I/O is in pytest tmp dirs.  Tunables are imported from heatmap_degrid.
"""
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

APP_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(APP_DIR))

import heatmap_degrid as H  # noqa: E402

# ---- fixture parameters (test-only) -----------------------------------------
PAGE = 226
W, HT = 800, 600
CENTER = (400, 300)
GREEN_AXES = (200, 140)
RING_AXES = (240, 180)
RING_COLOR = (60, 60, 60)
RING_THICK = 2
GREEN_COLOR = (60, 220, 20)          # BGR heat map
OUTLINE_COLOR = (255, 255, 255)
ARROW_COLOR = (96, 48, 0)
VALUE_TEXT_COLOR = (20, 20, 20)
FONT = cv2.FONT_HERSHEY_SIMPLEX
NUMBER_SCALE = 0.9
VALUE_SCALE = 0.5
NUMBER_POS = [(146, 300), (640, 300), (390, 100)]      # on the ring (left, right, top)
NUMBER_TEXTS = ["15", "10", "25"]
VALUE_POS = (330, 290)               # inside the green
VALUE_TEXT = "2.5"
ARROW_P0, ARROW_P1 = (560, 130), (590, 190)   # crosses the ring
COMPASS_CENTER, COMPASS_R = (700, 60), 30
SAMPLE_COURSES = ("Delaveaga", "Stanford")
GOLF_ROOT = APP_DIR.parent / "ItWentIn" / "GolfCourses"
RING_RESIDUAL_MAX_FRAC = 0.03        # <3% of the ring's dark pixels may remain
SAMPLE_MIN_FOUND = 8


def _page():
    img = np.full((HT, W, 3), PAGE, np.uint8)
    cv2.ellipse(img, CENTER, RING_AXES, 0, 0, 360, RING_COLOR, RING_THICK, cv2.LINE_AA)
    for pos, txt in zip(NUMBER_POS, NUMBER_TEXTS):
        cv2.rectangle(img, (pos[0] - 4, pos[1] - 24), (pos[0] + 40, pos[1] + 6), (PAGE,) * 3, -1)
        cv2.putText(img, txt, pos, FONT, NUMBER_SCALE, RING_COLOR, RING_THICK, cv2.LINE_AA)
    cv2.circle(img, COMPASS_CENTER, COMPASS_R, RING_COLOR, RING_THICK, cv2.LINE_AA)
    cv2.ellipse(img, CENTER, GREEN_AXES, 0, 0, 360, OUTLINE_COLOR, RING_THICK + 2, cv2.LINE_AA)
    cv2.ellipse(img, CENTER, GREEN_AXES, 0, 0, 360, GREEN_COLOR, -1)
    cv2.putText(img, VALUE_TEXT, VALUE_POS, FONT, VALUE_SCALE, VALUE_TEXT_COLOR, 1, cv2.LINE_AA)
    cv2.arrowedLine(img, ARROW_P0, ARROW_P1, ARROW_COLOR, 4, cv2.LINE_AA)
    return img


def _heat_mask(img):
    """Pixels inside the green outline (heat map + value labels)."""
    m = np.zeros(img.shape[:2], np.uint8)
    cv2.ellipse(m, CENTER, GREEN_AXES, 0, 0, 360, 1, -1)
    return m.astype(bool)


def _dark_neutral(img):
    gray, spread = H._gray_spread(img)
    return (spread <= H.RING_SPREAD_MAX) & (gray <= H.RING_MAX_GRAY)


def _ring_zone():
    """Annulus holding the ring and its numbers (outside the green)."""
    m = np.zeros((HT, W), np.uint8)
    cv2.ellipse(m, CENTER, (RING_AXES[0] + 40, RING_AXES[1] + 40), 0, 0, 360, 1, -1)
    return m.astype(bool) & ~_heat_mask(_page())


def test_ring_and_numbers_erased():
    img = _page()
    before = (_dark_neutral(img) & _ring_zone()).sum()
    out = H.remove_ring(img)
    after = (_dark_neutral(out) & _ring_zone()).sum()
    assert before > 0 and after <= RING_RESIDUAL_MAX_FRAC * before


def test_everything_else_untouched():
    img = _page()
    out, info = H.remove_ring(img, return_info=True)
    assert info[H.INFO_FOUND] and info[H.INFO_RING] > 0
    changed = (out != img).any(axis=2)
    allowed = cv2.dilate(_ring_zone().astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    compass = np.zeros((HT, W), bool)
    cv2.circle(compass.view(np.uint8), COMPASS_CENTER, COMPASS_R + 5, 1, -1)
    assert not (changed & ~allowed).any()             # nothing changes away from the ring
    assert not (changed & _heat_mask(img)).any()      # heat map, outline interior, value label intact
    assert not (changed & compass).any()              # compass kept
    arrow = np.zeros((HT, W), np.uint8)
    cv2.line(arrow, ARROW_P0, ARROW_P1, 1, 3)
    arrow = arrow.astype(bool) & ((H._gray_spread(img)[1]) > H.RING_COLOR_SPREAD_MIN)
    assert not (changed & arrow).any()                # arrow body intact where it crosses the ring


def test_value_label_survives_next_to_ring_number():
    img = _page()
    out = H.remove_ring(img)
    y, x = VALUE_POS[1] - 20, VALUE_POS[0]
    box = (slice(y, y + 30), slice(x, x + 50))
    assert (out[box] == img[box]).all()


def test_input_not_mutated_and_unchanged_without_ring():
    img = _page()
    snap = img.copy()
    H.remove_ring(img)
    assert (img == snap).all()
    plain = np.full((HT, W, 3), PAGE, np.uint8)
    cv2.ellipse(plain, CENTER, GREEN_AXES, 0, 0, 360, GREEN_COLOR, -1)
    out, info = H.remove_ring(plain, return_info=True)
    assert out is plain and not info[H.INFO_FOUND]


def test_satellite_style_passthrough():
    sat = np.full((HT, W, 3), (30, 70, 30), np.uint8)       # dark green, no grey page
    cv2.ellipse(sat, CENTER, GREEN_AXES, 0, 0, 360, (0, 0, 0), RING_THICK + 2)   # black outline = real green edge
    out, info = H.remove_ring(sat, return_info=True)
    assert out is sat and not info[H.INFO_FOUND]


def test_non_uint8_and_none_passthrough():
    assert H.remove_ring(None) is None
    f = np.zeros((HT, W, 3), np.float32)
    assert H.remove_ring(f) is f


def test_algo_version_bumped_and_file_written(tmp_path):
    assert H.DEGRID_ALGO_VERSION >= 3
    src = tmp_path / "hole.png"
    cv2.imwrite(str(src), _page())
    before = src.read_bytes()
    info = H.degrid_file(str(src))
    assert info[H.INFO_WRITTEN] and info[H.INFO_RING] > 0
    dst = Path(H.degridded_path(str(src)))
    assert H.png_algo_version(str(dst)) == H.DEGRID_ALGO_VERSION
    assert src.read_bytes() == before
    out = cv2.imread(str(dst))
    assert (_dark_neutral(out) & _ring_zone()).sum() <= RING_RESIDUAL_MAX_FRAC * (_dark_neutral(_page()) & _ring_zone()).sum()


def test_app_version_ticked():
    import re
    import app as A
    assert re.fullmatch(r"v\d+\.\d+", A.APP_VERSION)
    major, minor = (int(p) for p in A.APP_VERSION[1:].split("."))
    assert (major, minor) >= (5, 93)


def _samples():
    return sorted(p for c in SAMPLE_COURSES for p in (GOLF_ROOT / c / "Images").glob("*.png")
                  if H.DEGRID_SUFFIX not in p.name)


@pytest.mark.skipif(not _samples(), reason="no real heat-map samples in repo")
def test_real_samples_ring_removed_heat_map_kept():
    found = 0
    for path in _samples():
        img = cv2.imread(str(path))
        stage1 = H.degrid(img)
        out, info = H.remove_ring(stage1, return_info=True)
        if not info[H.INFO_FOUND]:
            continue
        found += 1
        mask = H.ring_mask(stage1)
        assert (_dark_neutral(out) & mask).sum() <= RING_RESIDUAL_MAX_FRAC * max(1, (_dark_neutral(stage1) & mask).sum()), path.name
        # coloured pixels (heat map / arrows) are never altered
        colored = H._gray_spread(stage1)[1] > H.RING_COLOR_SPREAD_MIN
        assert (out[colored] == stage1[colored]).all(), path.name
        assert not (mask & colored).any(), path.name
    assert found >= SAMPLE_MIN_FOUND, "expected the StrackaLine samples to have a detectable ring"
