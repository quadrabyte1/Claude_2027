"""heatmap_degrid.py -- erase the baked-in background grid from StrackaLine /
Golf Intelligence heat-map PNGs.

What the grid looks like (Delaveaga / Stanford samples): 1-2 px axis-aligned
lines, slightly darker than the flat light-grey page (RGB 226 -> ~150-200), on a
perfectly regular lattice (period ~27.7 px on Delaveaga, ~20.7 px on Stanford,
i.e. it scales with the screenshot) with every 5th line (Delaveaga) darker.  The
heat map, outline, arrows and labels are drawn on top of the grid, so the grid is
only visible on the background.

Method (structural, not a colour threshold):
  1. "Line-ness" map per axis: a pixel is a vertical-line candidate when it is
     slightly darker than BOTH its left and right neighbours FLANK_PX away, those
     neighbours agree with each other (the line sits on a flat patch) and all
     three are neutral grey/beige (never heat-map colours).
  2. Column profile = fraction of candidate pixels.  The grid shows up as a
     periodic comb; the period comes from the profile's autocorrelation and the
     lattice (period + offset) is fitted by least squares over the strong peaks,
     so lines hidden under the heat map still land on the lattice.
  3. Mask = candidates inside a +/-BAND_PX band around each lattice line, minus
     pixels near strongly dark features (outline/arrows/text), minus short blips
     (< MIN_RUN_PX) and pixels much darker than that lattice line's own core.
  4. Fill: each masked pixel is linearly interpolated from the nearest unmasked
     pixels on either side (exact for a flat background).
  Vertical lines are removed first; horizontal lines are then detected on the
  vertically-cleaned image so line crossings leave no "+" stubs.

If no grid lattice is found on both axes the input array is returned unchanged.
"""
from __future__ import annotations

import os

import cv2
import numpy as np

# -- detection / fill constants (all tunables live here) ----------------------
FLANK_PX = 3                 # px from the line centre to the flank samples
BAND_PX = 2                  # lattice half-width (px) in which candidates are accepted
MIN_DARKEN = 2.0             # min gray darkening vs flanks
MAX_DARKEN = 130.0           # max gray darkening (darker = a real feature, not grid)
FLANK_TOL = 6.0              # flanks must agree within this (flat background)
NEUTRAL_SPREAD = 40.0        # max channel spread (max-min) of a grid pixel / its flanks
FEATURE_DARKEN = 130.0       # a pixel this much darker than its local median is a real feature
FEATURE_MEDIAN_KSIZE = 9     # median-blur kernel for the feature test
FEATURE_PROTECT_KSIZE = 5    # dilation kernel: protect radius around features
MIN_RUN_PX = 7               # min continuous run (px) of a grid-line pixel column (ODD: symmetric opening kernel)
LINE_CORE_PERCENTILE = 90    # percentile of a line's darkening taken as its "core" darkness
LINE_LIMIT_RATIO = 1.5       # accept darkening up to this x the line core...
LINE_LIMIT_ADD = 10.0        # ...or core + this, whichever is larger
MIN_PERIOD_PX = 8
MAX_PERIOD_PX = 200
MIN_LINES = 4                # lattice lines confirmed per axis
MIN_PROFILE_PEAK = 0.05      # weakest comb the detector will believe (fraction of pixels)
PEAK_SMOOTH_PX = 3           # box width used to smooth the profile before peak picking
PEAK_CUTOFF_RATIO = 0.4      # a peak must reach this fraction of the strongest peak
CENTROID_HALF_PX = 2         # half-window for sub-pixel peak centroid
AUTOCORR_MIN = 0.15          # minimum autocorrelation for a period candidate
AUTOCORR_REL = 0.5           # ...and this fraction of the strongest lag
PERIOD_FIT_ITERATIONS = 3
FIT_RESIDUAL_PX = 1.5        # peaks further than this from the fitted lattice are dropped
MIN_PROFILE_PERIODS = 3      # image must span at least this many periods
ROUND_HALF = 0.5             # rounding offset
GRAY_MAX = 255
LATTICE_EDGE_SLACK_PX = 1    # lattice positions this far outside the image still count
PERIOD_PAD = 2               # period search must have this many lags of room

# -- file / info-dict naming ---------------------------------------------------
DEGRID_SUFFIX = "__degridded"        # cleaned copy: "<stem>__degridded.png"
DEGRID_EXT = ".png"
INFO_FOUND = "found"
INFO_X = "x"
INFO_Y = "y"
INFO_MASKED = "masked_px"
INFO_PERIOD = "period"
INFO_OFFSET = "offset"
INFO_WRITTEN = "written"
INFO_ERROR = "error"
ERR_UNREADABLE = "unreadable"


def degridded_path(src_path: str) -> str:
    """Path of the cleaned copy that sits next to ``src_path``."""
    stem, _ = os.path.splitext(src_path)
    return stem + DEGRID_SUFFIX + DEGRID_EXT


def _axis_candidates(gray: np.ndarray, spread: np.ndarray) -> np.ndarray:
    """Vertical-line candidate mask (H, W)."""
    h, w = gray.shape
    cand = np.zeros((h, w), dtype=bool)
    f = FLANK_PX
    if w <= 2 * f + 1:
        return cand
    c = gray[:, f:w - f]
    left = gray[:, 0:w - 2 * f]
    right = gray[:, 2 * f:w]
    dark = (left + right) / 2.0 - c
    ok = (np.abs(left - right) <= FLANK_TOL) & (dark >= MIN_DARKEN) & (dark <= MAX_DARKEN)
    ok &= (spread[:, 0:w - 2 * f] <= NEUTRAL_SPREAD) & (spread[:, 2 * f:w] <= NEUTRAL_SPREAD) \
        & (spread[:, f:w - f] <= NEUTRAL_SPREAD)
    cand[:, f:w - f] = ok
    return cand


def _darkening(gray: np.ndarray) -> np.ndarray:
    """Per-pixel (flank mean - pixel) for vertical lines; 0 at the image edges."""
    h, w = gray.shape
    f = FLANK_PX
    out = np.zeros((h, w), dtype=np.float32)
    if w > 2 * f + 1:
        out[:, f:w - f] = (gray[:, 0:w - 2 * f] + gray[:, 2 * f:w]) / 2.0 - gray[:, f:w - f]
    return out


def _fit_lattice(profile: np.ndarray):
    """Return (period, offset) of the periodic comb in ``profile`` or None."""
    n = len(profile)
    if n < MIN_PROFILE_PERIODS * MIN_PERIOD_PX:
        return None
    smooth = np.convolve(profile, np.ones(PEAK_SMOOTH_PX), mode="same")
    if smooth.max() < MIN_PROFILE_PEAK:
        return None
    x = smooth - smooth.mean()
    ac = np.correlate(x, x, mode="full")[n - 1:]
    ac = ac / (ac[0] + np.finfo(float).eps)
    hi = min(MAX_PERIOD_PX, n // MIN_PROFILE_PERIODS)
    if hi <= MIN_PERIOD_PX + PERIOD_PAD:
        return None
    seg = ac[MIN_PERIOD_PX:hi]
    best = None
    thr = max(AUTOCORR_MIN, AUTOCORR_REL * seg.max())
    for i in range(1, len(seg) - 1):   # first strong local max (avoids multiples)
        if seg[i] >= thr and seg[i] >= seg[i - 1] and seg[i] >= seg[i + 1]:
            best = i + MIN_PERIOD_PX
            break
    if best is None:
        return None
    cut = PEAK_CUTOFF_RATIO * smooth.max()
    peaks = []
    for i in range(1, n - 1):
        if smooth[i] >= cut and smooth[i] >= smooth[i - 1] and smooth[i] > smooth[i + 1]:
            lo, up = max(0, i - CENTROID_HALF_PX), min(n, i + CENTROID_HALF_PX + 1)
            wts = profile[lo:up]
            if wts.sum() <= 0:
                continue
            peaks.append(float((np.arange(lo, up) * wts).sum() / wts.sum()))
    if len(peaks) < MIN_LINES:
        return None
    peaks = np.sort(np.array(peaks))
    period = float(best)
    a = None
    for _ in range(PERIOD_FIT_ITERATIONS):
        # cumulative integer index from successive gaps (tolerates a rough period)
        k = np.concatenate([[0.0], np.cumsum(np.maximum(1.0, np.round(np.diff(peaks) / period)))])
        design = np.vstack([np.ones_like(k), k]).T
        (a, period), *_ = np.linalg.lstsq(design, peaks, rcond=None)
        keep = np.abs(peaks - (a + period * k)) < FIT_RESIDUAL_PX
        if keep.sum() < MIN_LINES:
            return None
        peaks = peaks[keep]
    if not (MIN_PERIOD_PX <= period <= MAX_PERIOD_PX):
        return None
    return float(period), float(a)


def _lattice_positions(period: float, offset: float, n: int):
    k0 = int(np.floor(-offset / period)) - 1
    k1 = int(np.ceil((n - offset) / period)) + 1
    return [offset + k * period for k in range(k0, k1 + 1)
            if -LATTICE_EDGE_SLACK_PX <= offset + k * period <= n]


def _protect_features(gray: np.ndarray) -> np.ndarray:
    """Pixels near a strongly dark feature (outline, arrow, text): never touched."""
    g8 = np.clip(gray, 0, GRAY_MAX).astype(np.uint8)
    med = cv2.medianBlur(g8, FEATURE_MEDIAN_KSIZE).astype(np.float32)
    feat = ((med - gray) > FEATURE_DARKEN).astype(np.uint8)
    return cv2.dilate(feat, np.ones((FEATURE_PROTECT_KSIZE, FEATURE_PROTECT_KSIZE), np.uint8)).astype(bool)


def _keep_long_runs(mask: np.ndarray, min_run: int) -> np.ndarray:
    """Drop vertical runs (per column) shorter than ``min_run``."""
    kernel = np.ones((min_run, 1), dtype=np.uint8)
    m8 = mask.astype(np.uint8)
    return cv2.dilate(cv2.erode(m8, kernel), kernel).astype(bool)


def _axis_mask(gray: np.ndarray, protect: np.ndarray, spread: np.ndarray):
    """Boolean mask of grid pixels for VERTICAL lines + lattice info, or (None, None)."""
    cand = _axis_candidates(gray, spread)
    lat = _fit_lattice(cand.mean(axis=0))
    if lat is None:
        return None, None
    period, offset = lat
    w = gray.shape[1]
    positions = _lattice_positions(period, offset, w)
    band = np.zeros(w, dtype=bool)
    for p in positions:
        lo = int(np.floor(p - BAND_PX))
        hi = int(np.ceil(p + BAND_PX))
        band[max(lo, 0):min(hi, w - 1) + 1] = True
    mask = cand & band[None, :] & ~protect
    mask = _keep_long_runs(mask, MIN_RUN_PX)
    if mask.any():
        dark = _darkening(gray)
        for p in positions:
            lo = max(int(np.floor(p - BAND_PX)), 0)
            hi = min(int(np.ceil(p + BAND_PX)), w - 1) + 1
            sub = mask[:, lo:hi]
            if not sub.any():
                continue
            core = float(np.percentile(dark[:, lo:hi][sub], LINE_CORE_PERCENTILE))
            lim = max(LINE_LIMIT_RATIO * core, core + LINE_LIMIT_ADD)
            mask[:, lo:hi] = sub & (dark[:, lo:hi] <= lim)
    return mask, {INFO_PERIOD: period, INFO_OFFSET: offset}


def _fill_rows(img: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Fill masked pixels by linear interpolation from the nearest unmasked pixels
    left/right on the same row.  ``img`` is a float (H, W[, C]) array."""
    w = mask.shape[1]
    out = img.copy()
    for y in np.where(mask.any(axis=1))[0]:
        row = mask[y]
        xs = np.where(row)[0]
        runs = []
        start = prev = xs[0]
        for x in xs[1:]:
            if x != prev + 1:
                runs.append((start, prev))
                start = x
            prev = x
        runs.append((start, prev))
        for a, b in runs:
            li, ri = a - 1, b + 1
            while li >= 0 and row[li]:
                li -= 1
            while ri < w and row[ri]:
                ri += 1
            if li < 0 or ri >= w:
                continue
            for x in range(a, b + 1):
                t = (x - li) / float(ri - li)
                out[y, x] = img[y, li] * (1 - t) + img[y, ri] * t
    return out


def _gray_spread(work: np.ndarray):
    f = work.astype(np.float32)
    if f.ndim == 3:
        return f.mean(axis=2), f.max(axis=2) - f.min(axis=2)
    return f, np.zeros_like(f)


def _transpose(a: np.ndarray) -> np.ndarray:
    return a.swapaxes(0, 1).copy()


def degrid(img: np.ndarray, return_info: bool = False):
    """Remove the baked-in grid from a BGR/RGB/gray uint8 image.

    Returns the cleaned image (a copy), or the INPUT UNCHANGED (same object) when
    no grid lattice is found on both axes.  With ``return_info`` returns
    ``(img, info)``; info = {found, x:{period,offset}|None, y:{...}|None, masked_px}.
    """
    info = {INFO_FOUND: False, INFO_X: None, INFO_Y: None, INFO_MASKED: 0}

    def _ret(value):
        return (value, info) if return_info else value

    if img is None or img.ndim not in (2, 3) or img.dtype != np.uint8:
        return _ret(img)
    work = img[:, :, :3] if img.ndim == 3 else img
    gray, spread = _gray_spread(work)
    protect = _protect_features(gray)

    # pass 1: vertical lines on the original
    mx, ix = _axis_mask(gray, protect, spread)
    if mx is None:
        return _ret(img)
    after_v = _fill_rows(work.astype(np.float32), mx)

    # pass 2: horizontal lines on the vertically-cleaned image (transposed)
    gray2, spread2 = _gray_spread(np.clip(after_v + ROUND_HALF, 0, GRAY_MAX).astype(np.uint8))
    my_t, iy = _axis_mask(_transpose(gray2), _transpose(protect), _transpose(spread2))
    if my_t is None:
        return _ret(img)
    out = _transpose(_fill_rows(_transpose(after_v), my_t))

    fixed = np.clip(out + ROUND_HALF, 0, GRAY_MAX).astype(np.uint8)
    result = img.copy()
    if img.ndim == 3:
        result[:, :, :3] = fixed
    else:
        result = fixed
    info.update({INFO_FOUND: True, INFO_X: ix, INFO_Y: iy,
                 INFO_MASKED: int(mx.sum() + my_t.sum())})
    return _ret(result)


def degrid_file(src_path: str, dst_path: str | None = None) -> dict:
    """Read ``src_path`` and write the degridded copy to ``dst_path`` (default:
    ``degridded_path(src_path)``).  The original is never modified; if no grid is
    found nothing is written.  Returns the info dict plus ``written``."""
    dst_path = dst_path or degridded_path(src_path)
    img = cv2.imread(src_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        return {INFO_FOUND: False, INFO_WRITTEN: False, INFO_ERROR: ERR_UNREADABLE}
    cleaned, info = degrid(img, return_info=True)
    info[INFO_WRITTEN] = False
    if info[INFO_FOUND]:
        cv2.imwrite(dst_path, cleaned)
        info[INFO_WRITTEN] = True
    return info
