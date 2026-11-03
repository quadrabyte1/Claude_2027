"""
test_wash_contrast.py — V3.32: the blue wash is defined once (templates/_wash_vars.html),
both pages include it, and white text passes WCAG AA along the whole gradient.
All values are read from the partial / templates, never re-typed.
"""
import re
from pathlib import Path

from .test_plot_filter import _make_app

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
WASH_PARTIAL = "_wash_vars.html"
PAGE_TEMPLATES = ("index.html", "config_import.html")
WASH_VAR_NAMES = ("--wash-start", "--wash-end", "--text-on-blue")
MIN_CONTRAST = 4.5
GRADIENT_SAMPLES = 101
HEX_RE = r"(#[0-9A-Fa-f]{6})"


def _var(css: str, name: str) -> str:
    return re.search(re.escape(name) + r":\s*" + HEX_RE, css).group(1)


def _lum(h: str) -> float:
    chans = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in chans]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _mix(a: str, b: str, t: float) -> str:
    return "#" + "".join(
        "%02x" % round(int(a[i:i + 2], 16) * (1 - t) + int(b[i:i + 2], 16) * t) for i in (1, 3, 5))


def test_wash_defined_once_in_partial_only():
    for name in PAGE_TEMPLATES:
        src = (TEMPLATES / name).read_text()
        assert WASH_PARTIAL in src
        for var in WASH_VAR_NAMES:
            assert var + ":" not in src, f"{name} re-defines {var}"


def test_both_rendered_pages_use_identical_wash(tmp_path):
    _, client, _ = _make_app(tmp_path)
    partial = (TEMPLATES / WASH_PARTIAL).read_text()
    expected = {v: _var(partial, v) for v in WASH_VAR_NAMES}
    for url in ("/", "/config/import_form"):
        html = client.get(url).get_data(as_text=True)
        assert {v: _var(html, v) for v in WASH_VAR_NAMES} == expected, url


def test_white_text_passes_aa_along_whole_gradient():
    css = (TEMPLATES / WASH_PARTIAL).read_text()
    start, end, text = (_var(css, v) for v in WASH_VAR_NAMES)
    for i in range(GRADIENT_SAMPLES):
        bg = _mix(start, end, i / (GRADIENT_SAMPLES - 1))
        assert _ratio(text, bg) >= MIN_CONTRAST, bg
