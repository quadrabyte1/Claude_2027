"""
test_trap_controlling_cell_ring.py -- editor v5.11: red ring around the grid cell(s)
that control each bunker's height (absolute mode).

Single source of truth: gradient_surface_diagnostic._trap_inside_cells is the
generator's 'inside the trap' test; controlling_cells_for_trap /
compute_trap_controlling_cells reuse it; /api/trap_controlling_cells exposes it.

Run: python -m pytest app/tests/test_trap_controlling_cell_ring.py -v
"""
import importlib.util, json, re, sys
from pathlib import Path
import pytest

APP_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(APP_DIR))


def _gsd():
    spec = importlib.util.spec_from_file_location("gsd_ring_test", APP_DIR / "gradient_surface_diagnostic.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def _geom(g):
    half = g.PRINT_SIZE_MM / 2.0 + g.FRINGE_XY_EXPANSION_MM / 2.0
    return half, 2 * half / 20


def _box_mm(g, rows, cols, margin=-0.05):  # margin<0: box slightly larger than the cells => cells FULLY inside
    from shapely.geometry import box
    half, side = _geom(g)
    return box(-half + (cols[0] + margin) * side, -half + (rows[0] + margin) * side,
               -half + (cols[1] + 1 - margin) * side, -half + (rows[1] + 1 - margin) * side)


def idx(r, c):
    return r * 20 + c


# ---- unit: controlling_cells_for_trap --------------------------------------
def test_single_max_cell_controls():
    g = _gsd(); half, side = _geom(g)
    cells = {str(idx(5, 5)): 4.0, str(idx(5, 6)): 13.0, str(idx(6, 5)): 2.0}
    assert g.controlling_cells_for_trap(_box_mm(g, (5, 6), (5, 6)), cells, side, half) == [idx(5, 6)]


def test_ties_all_returned():
    g = _gsd(); half, side = _geom(g)
    cells = {str(idx(5, 5)): 13.0, str(idx(6, 6)): 13.0, str(idx(5, 6)): 3.0}
    assert g.controlling_cells_for_trap(_box_mm(g, (5, 6), (5, 6)), cells, side, half) == sorted([idx(5, 5), idx(6, 6)])


def test_partial_cell_whose_centre_is_outside_is_ignored():
    """Cell (5,7) is half covered but its centre is outside -> not eligible, even if highest."""
    g = _gsd(); half, side = _geom(g)
    from shapely.geometry import box
    x0 = -half + 4.9 * side; x1 = -half + 7.7 * side   # col 7 centre inside but cell only partly
    y0 = -half + 4.9 * side; y1 = -half + 6.1 * side
    cells = {str(idx(5, 5)): 4.0, str(idx(5, 7)): 20.0}
    assert g.controlling_cells_for_trap(box(x0, y0, x1, y1), cells, side, half) == [idx(5, 5)]


def test_zero_cells_not_set_and_none_inside_gives_empty():
    g = _gsd(); half, side = _geom(g)
    assert g.controlling_cells_for_trap(_box_mm(g, (5, 6), (5, 6)), {str(idx(5, 5)): 0}, side, half) == []
    assert g.controlling_cells_for_trap(_box_mm(g, (5, 6), (5, 6)), {str(idx(15, 15)): 9}, side, half) == []


def test_matches_generator_height_for_random_layouts():
    """Value at the circled cell == what _resolve_trap_height_from_grid uses (absolute)."""
    import random
    g = _gsd(); half, side = _geom(g); rnd = random.Random(7)
    for _ in range(40):
        cells = {str(rnd.randrange(400)): rnd.choice([1, 2.5, 5, 13, 13, 27]) for _ in range(60)}
        poly = _box_mm(g, (rnd.randrange(0, 8), rnd.randrange(8, 20)), (rnd.randrange(0, 8), rnd.randrange(8, 20)))
        ctl = g.controlling_cells_for_trap(poly, cells, side, half)
        h = g._resolve_trap_height_from_grid(poly, cells, "absolute", 1.0, side, half)
        if not ctl:
            assert h is None
        else:
            assert h == pytest.approx(max(g.BASE_THICKNESS_MM, min(30.0, float(cells[str(ctl[0])]))))
            assert len({cells[str(i)] for i in ctl}) == 1


# ---- integration: compute_trap_controlling_cells / endpoint ----------------
def _egm(g, trap_box_cells, cells, mode="absolute"):
    import math
    W = H = 800
    scale = g.PRINT_SIZE_MM / max(W, H)
    half, side = _geom(g)

    def px(xmm, ymm):
        return {"x": W / 2 + xmm / scale, "y": H / 2 - ymm / scale}
    green = [{"x": 400 + 90 * math.cos(a * math.pi / 12), "y": 400 + 90 * math.sin(a * math.pi / 12)} for a in range(24)]
    (r0, r1), (c0, c1) = trap_box_cells
    x0 = -half + (c0 - 0.05) * side; x1 = -half + (c1 + 1.05) * side
    y0 = -half + (r0 - 0.05) * side; y1 = -half + (r1 + 1.05) * side
    trap = [px(x0, y0), px(x1, y0), px(x1, y1), px(x0, y1)]
    return {"course": "T", "hole": "1", "image": "x.jpg", "imageSize": {"width": W, "height": H},
            "gridMode": mode, "gridCellHeights": cells,
            "polygons": [{"type": "green", "closed": True, "points": green},
                         {"type": "trap", "closed": True, "points": trap}]}


def test_compute_absolute_finds_cell_and_other_modes_none():
    g = _gsd()
    cells = {str(idx(3, 3)): 13.0, str(idx(3, 4)): 2.5, str(idx(15, 15)): 30.0}
    out = g.compute_trap_controlling_cells(_egm(g, ((2, 4), (2, 5)), cells))
    assert out["mode"] == "absolute"
    assert out["traps"] == [{"trap": 1, "cells": [idx(3, 3)]}]
    # delta: ring too (v5.12) -- highest signed delta; missing mode == delta
    out = g.compute_trap_controlling_cells(_egm(g, ((2, 4), (2, 5)), cells, "delta"))
    assert out["traps"] == [{"trap": 1, "cells": [idx(3, 3)]}]
    e = _egm(g, ((2, 4), (2, 5)), cells); del e["gridMode"]
    assert g.compute_trap_controlling_cells(e)["traps"] == [{"trap": 1, "cells": [idx(3, 3)]}]
    assert g.compute_trap_controlling_cells(_egm(g, ((2, 4), (2, 5)), cells, "off"))["traps"] == []


def test_delta_height_matches_circled_cell():
    g = _gsd(); half, side = _geom(g)
    cells = {str(idx(5, 5)): 4.0, str(idx(5, 6)): -2.0, str(idx(6, 5)): 7.5}
    poly = _box_mm(g, (5, 6), (5, 6))
    ctl = g.controlling_cells_for_trap(poly, cells, side, half)
    assert ctl == [idx(6, 5)]
    assert g._resolve_trap_height_from_grid(poly, cells, "delta", 3.0, side, half) == pytest.approx(10.5)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app as _app
    monkeypatch.setattr(_app, "DB_PATH", str(tmp_path / "workspace.db"))   # never the live DB
    _app.app.config["TESTING"] = True
    with _app.app.test_client() as c:
        yield c


def test_endpoint(client):
    g = _gsd()
    cells = {str(idx(3, 3)): 13.0, str(idx(3, 4)): 2.5}
    r = client.post("/api/trap_controlling_cells", json=_egm(g, ((2, 4), (2, 5)), cells))
    assert r.status_code == 200
    j = r.get_json()
    assert j["status"] == "ok" and j["traps"] == [{"trap": 1, "cells": [idx(3, 3)]}]


# ---- editor wiring (DOM/JS source checks, same style as other editor tests) -
EDITOR = (APP_DIR / "templates" / "editor.html").read_text()


def test_editor_draws_red_ring_on_top_of_numbers():
    assert "/api/trap_controlling_cells" in EDITOR
    ring = EDITOR.index("Trap-controlling cell ring")
    nums = EDITOR.index("Numeric value text for set cells")
    assert ring > nums                                  # drawn after numbers
    seg = EDITOR[ring:ring + 1500]
    assert "#dc2626" in seg and "ctx.arc(" in seg and "ctx.stroke()" in seg
    assert "fill(" not in seg                           # ring only, number stays visible
    assert "this.gridMode !== 'off'" in seg


def test_editor_refreshes_live():
    m = re.search(r"_scheduleTrapCtl\(\) \{(.*?)\n    \},", EDITOR, re.S)
    assert m, "scheduler missing"
    body = m.group(1)
    assert "gridCellHeights" in body and "polygons" in body and "gridMode" in body and "setTimeout" in body
    assert "this._scheduleTrapCtl();" in EDITOR[EDITOR.index("draw() {"):]   # called from draw()


def test_versions_bumped():
    src = (APP_DIR / "app.py").read_text()
    m = re.search(r'APP_VERSION\s*=\s*"v(\d+)\.(\d+)"', src)
    assert (int(m[1]), int(m[2])) >= (5, 51)
    em = re.search(r"Boundary Editor v5\.(\d+)", EDITOR)
    assert em, "editor version string 'Boundary Editor v5.N' missing"
    assert int(em[1]) >= 15, f"editor version should be >= v5.15, got v5.{em[1]}"


# ---- v5.13: only cells FULLY inside the trap are eligible -------------------
def test_half_in_cell_never_controls_even_if_higher():
    g = _gsd(); half, side = _geom(g)
    from shapely.geometry import box
    # trap covers cell (5,5) fully, and cell (5,6) only up to 60% of its width (centre inside, cell NOT fully inside)
    poly = box(-half + 4.9 * side, -half + 4.9 * side, -half + 6.6 * side, -half + 6.1 * side)
    cells = {str(idx(5, 5)): 4.0, str(idx(5, 6)): 20.0}
    assert g.controlling_cells_for_trap(poly, cells, side, half) == [idx(5, 5)]
    for mode in ("absolute", "delta"):
        h = g._resolve_trap_height_from_grid(poly, cells, mode, 1.0, side, half)
        assert h == pytest.approx(4.0 if mode == "absolute" else 5.0)


def test_only_partial_cells_means_no_override_no_ring():
    g = _gsd(); half, side = _geom(g)
    from shapely.geometry import box
    poly = box(-half + 5.2 * side, -half + 5.2 * side, -half + 6.8 * side, -half + 5.9 * side)  # covers centres, no full cell
    cells = {str(idx(5, 5)): 9.0, str(idx(5, 6)): 9.0}
    assert g.controlling_cells_for_trap(poly, cells, side, half) == []
    assert g._resolve_trap_height_from_grid(poly, cells, "absolute", 1.0, side, half) is None
    assert g._resolve_trap_height_from_grid(poly, cells, "delta", 1.0, side, half) is None
