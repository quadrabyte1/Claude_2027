"""Editor v6.27: the 2-brush ramp stores in-between cell values in 0.25 mm steps; presentation constants unchanged."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import editor_constants as C

pytestmark = pytest.mark.skipif(not C.NODE, reason="node not installed")

RAMP_MM = C.value("RAMP_VALUE_STEP_MM")
PALETTE_MM = C.value("PALETTE_VALUE_STEP")
SLOPE_MM = C.value("SLOPE_VALUE_STEP")
EDITOR = C.EDITOR_PATH.read_text()
EXPECTED_RAMP_MM = 0.25
EXPECTED_PALETTE_MM = 0.5        # presentation rule: swatch step must not change
EXPECTED_SLOPE_MM = 0.1
LOW_MM, HIGH_MM, CELLS = 1, 3, 17
LABEL_DECIMALS = 1
FUNCS = ("roundToStep", "rampStepAt", "paintBrushValue", "roundGridValue", "gridValueText")


def _fn(name):
    i = EDITOR.index(f"function {name}(")
    depth, j = 0, EDITOR.index("{", i)
    k = j
    while True:
        depth += EDITOR[k] == "{"
        depth -= EDITOR[k] == "}"
        if depth == 0:
            return EDITOR[i:k + 1]
        k += 1


def _run(body):
    js = C.prelude() + "\n".join(_fn(n) for n in FUNCS) + "\n" + body
    return json.loads(subprocess.run([C.NODE, "-e", js], capture_output=True, text=True, check=True).stdout)


def test_constants():
    assert RAMP_MM == EXPECTED_RAMP_MM and PALETTE_MM == EXPECTED_PALETTE_MM and SLOPE_MM == EXPECTED_SLOPE_MM


def _delta_step(mm):
    return (mm - C.value("CELL_COLOR_DELTA_MIN_MM")) / PALETTE_MM


def test_ramp_between_two_values_yields_quarter_mm_intermediates():
    a, b = _delta_step(LOW_MM), _delta_step(HIGH_MM)
    vals = _run(f"console.log(JSON.stringify(Array.from({{length: {CELLS}}}, (_, k) => "
                f"paintBrushValue(rampStepAt(k, {CELLS}, {a}, {b}), 'delta'))));")
    assert vals[0] == LOW_MM and vals[-1] == HIGH_MM and vals == sorted(vals)
    assert all(abs(v / RAMP_MM - round(v / RAMP_MM)) < 1e-9 for v in vals)          # every value on the 0.25 grid
    assert any(abs(v / PALETTE_MM - round(v / PALETTE_MM)) > 1e-9 for v in vals)    # includes x.25 / x.75
    assert len(set(vals)) == round((HIGH_MM - LOW_MM) / RAMP_MM) + 1


def test_cell_label_format_unchanged_one_decimal():
    assert _run("console.log(JSON.stringify([gridValueText(2), gridValueText(2.5)]));") == [
        f"{2:.{LABEL_DECIMALS}f}", f"{2.5:.{LABEL_DECIMALS}f}"]
