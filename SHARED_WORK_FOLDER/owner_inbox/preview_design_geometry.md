# Live 3D Preview - Geometry Design (Topo)

For Thomas and Jim, with a short "Sienna note" per item. Based on Boundary Editor v6.33 code (`gradient_surface_diagnostic.py`) and the v6.31 flowchart (step numbers in brackets). Numbers marked **(measured)** come from a small stand-alone benchmark I ran on this Mac with synthetic data (no editor, server or EGM touched); **(est.)** is my estimate from reading the code.

**The big idea.** The preview does not build the printable mesh (that is the slow part of Generate: triangulating, boolean cuts, textures, manifold checks). It builds only the *height of the surface* on a coarse grid and lets three.js draw it. Heights are cheap; meshing is not.

---

## 1. What can be previewed live, and how

| Part | Preview method | Matches the print? |
|---|---|---|
| **Fringe** [13] | Server endpoint returns a low-res height grid (about 96 x 96) | Very close (shape yes; fine detail no) |
| **Bunkers** [17] | Same endpoint, floor height inside each bunker outline | Close (smooth floor, no rake) |
| **Water** [18] | Flat slab at one height | Exact in height |
| **Boulders** [19] | Flat ring/slab at one height | Exact in height |
| **Water-hole lift** [14] | +2 mm on green, fringe, bunkers, water, boulders | Exact |
| **Tee / flag** | Small marker shapes at the saved positions | Symbolic |
| **Terraced vs smooth** | Switch on the green (see 2) | Close |

**Fringe: browser or server?** The fringe is a thin-plate spline (TPS) through one value per painted cell (400 cells at 20x20, 1600 at 40x40). Cost of that step, measured: fitting takes 10 ms (20x20) / 26 ms (40x40). Evaluating it on the generator's real 200x200 grid takes 73 ms / 294 ms, but on a 64x64 preview grid only 7 ms / 30 ms. So the maths is not the bottleneck.

**Recommendation: server endpoint, not browser TPS.** Reasons: it reuses the real functions (`_build_tps_grid_height_field`, then `_normalize_green_fringe_interface`, the short blend toward the green rim), so the preview cannot drift from the generator; the inputs it needs (green rim heights, the IDW default per cell) come from the green anyway, which lives on the server; and a localhost round trip adds only about 10-30 ms **(est.)**. Expected total about 50-100 ms per edit **(est.)**.

*Sienna note:* the TPS is linear in the cell values, so if you ever want zero-latency painting you can ship the server's precomputed weight matrix (about 1600 cells x 9216 points, roughly 60 MB at 40x40, so only worth it at 20x20 or lower preview resolution) and update the surface in the browser as `z += weight_column * delta` per painted cell. Not needed for v1. Skip steps 13d-13f (median/spike filters, seam snapping, triangulation); show the field only where it is outside the green, bunker and water outlines.

**Bunkers.** In the current default ("cells" mode) the rim sits **2.0 mm** under the local fringe (`BUNKER_RIM_DROP_MM`; the older 1.0 mm constant is only for legacy mode), and the floor follows fully-inside painted cells with a smooth falloff over about 1.5 cells. Server returns the floor heights over each bunker footprint with the same endpoint. Bunker without painted cells: flat at rim level.

**Water** is flat at the lowest fringe height under its outline. **Boulders** are flat at the lowest fringe height under their footprint (a ring if it encloses water). Both are trivial extrusions once the fringe grid exists. The `Include boundary region` option (water shrunk 5 mm, 5 mm boulder ring) must be applied to the outlines first; reuse `_apply_boundary_region_derivation`.

**Terraced vs smooth** is a pure display choice for the green (quantise to `contourStep`); no server call.

---

## 2. The green (steps 9-12)

The green is **independent of painted cells**; it depends on the arrows in the picture, the green outline, Elevation range, Base thickness and Z scale. What the code does: detect arrows, build a 200x200 direction field (inverse-distance blend), solve least-squares for height (LSQR), then `soften_extremes`, rescale to Elevation range, `limit_max_slope` (no cell may rise more than 0.2 mm above its lowest neighbour), then Z scale.

Costs: LSQR on a 200x200 green **100 ms (measured; 43 ms at looser tolerance)**; inside-mask loop **12 ms (measured)**; the direction-field loop is plain Python, about 40,000 cells x every arrow, so roughly **0.3-1 s (est.)** and is the real hot spot; arrow detection from the image about **0.1-0.5 s (est.)**. Slope limiter: **under 15 ms (measured)** even in a harsh case (94 passes).

**Important finding for option (c):** the unit field cannot simply be *rescaled* when Elevation range or Z scale change. The limiter works in absolute millimetres, so it is not scale-proportional. I tested it: doubling the relief then limiting differs from limiting then doubling by up to **2.6 mm** on a test cone. `soften_extremes` also takes its thresholds in mm, so it depends on Elevation range too. The fix is cheap, though: cache the **raw LSQR field**, and re-run the fast tail (soften, rescale, limiter, Z scale) on each change.

| Option | What it is | Latency | Trade-off |
|---|---|---|---|
| (a) Last Generate | Show the heightfield saved by the last Generate | 0 ms | Stale as soon as the user changes anything green-related; empty before first Generate |
| (b) Fast "green only" recompute | Run steps 9-12 on a coarse path whenever a green setting changes | about 0.5-1.5 s (est.) | Always correct, but sluggish for slider drags |
| (c) Cache raw field, re-run tail | Cache raw LSQR Z per (image, green outline); re-run soften + rescale + limiter + Z scale | **about 30-60 ms (est.)** | Exact (same code as Generate); recompute needed only when the green outline or image changes |

**Recommendation: (c), with (b) as its fallback.** First open (or green outline edit, debounced about 400 ms after the drag ends) triggers the full (b) path once, about 1 s, and caches the raw field keyed by a hash of image + green outline. Elevation range, Z scale and Base thickness then update in tens of milliseconds. Note that moving the green outline also changes which arrows are "inside the green", so arrows must be re-detected then; that is why it needs the slow path. Easy extra win for the slow path: vectorise the direction-field loop (about 40x faster; same maths, so no output change). Green rim heights from this result also feed the fringe default, so one green result drives both.

*Sienna note:* endpoint returns the 200x200 height grid (Float32, about 160 KB) plus the mask; three.js builds a `PlaneGeometry` from it. No-arrows case: flat at 1.5 mm (5 mm on a water hole), just return that.

---

## 3. Accuracy vs the printed 3MF

**Will match:** green shape (same code path), fringe large-scale shape and painted-cell effects, bunker depth/contour, water and boulder heights, water-hole lift, outlines (holes in fringe where green/bunker/water sit), terraced steps.

**Will not match, and what to do:**
- **Grass texture** (step 13g): omit; it is random-looking bumps that hide the shape. Optionally a flat-shaded green-tinted fringe.
- **Rake texture** in bunkers (17c): omit; show a smooth sand-coloured floor.
- **Engraving** on the underside (21): omit (not visible from above anyway).
- **Seam polish** (16) and the median/spike filters and seam snap (13d-e): omit; differences are fractions of a millimetre. A thin gap line between green and fringe is acceptable.
- **Flag hole (3 mm) and tee hole/collar**: fake with a dark disc / small cylinder at the saved position. Real boolean cuts are too slow and add nothing for shape judgment.
- **Frame cap / 9 mm ceiling**: currently disabled in the generator (`BOUNDARY_HEIGHT_CAP_ENABLED = False`), so nothing to model unless that is turned on.
- **Vertical scale**: draw true proportion by default, with an optional 2-3x exaggeration toggle labelled clearly, because 0.2 mm slope steps are hard to see at real size.

Label the pane "Preview - approximate; texture, engraving and holes not shown".

---

## 4. Speed targets (all estimates unless marked measured)

| Edit | Work | Target latency |
|---|---|---|
| Paint a cell / Slope-tool fill | fringe + bunker endpoint | **60-120 ms**; send throttled (about every 60 ms) during a drag |
| Move a bunker / water / boulder polygon | fringe (bunker carve), bunker floor, water/boulder height | 80-150 ms; debounce 100 ms |
| Elevation range / Z scale / Base thickness | green tail (c) + fringe default refresh | 80-150 ms |
| Contour step / terraced toggle | browser only | under 16 ms |
| Grid resolution 20 <-> 40 | refit fringe | 100-200 ms (40x40 eval is 30 ms at 64x64 **measured**, about 70 ms at 96x96) |
| Move / reshape the **green outline** | full green recompute (slow path) | **0.5-1.5 s**, run after the drag ends; show previous green dimmed meanwhile |
| Load project | everything once | 1-2 s |

Use a "latest request wins" rule (cancel or ignore older responses) so a fast stroke never shows an old surface.

---

## 5. Phase 2: Blender import

Goal: sculpt a surface in Blender, import it so the painted cells reproduce it.

- **Sampling into Absolute cells.** Place the Blender surface in the same frame as the plate (square of side `2 * FRINGE_HALF_MM`, origin at plate centre). For each cell centre (20x20 or 40x40), cast a ray straight down (+Z) and read the hit height. Average a few samples across the cell if the surface is bumpy. Store as **Absolute** values, clamped to the editor's 0-30 mm and never below the 1.0 mm fringe minimum. Absolute (not Delta) is the right mode: Delta is relative to the generator's own default, which the Blender surface knows nothing about.
- **Why it is lossy.** Cells are 8.5 mm (20x20) or 4.3 mm (40x40); the TPS passes smoothly through the cell centres, so detail finer than a cell is lost and overshoot between cells is possible. A 40x40 import is noticeably more faithful. The importer should show the preview of the *result* so the user sees what survived.
- **Cells under a bunker** become the bunker floor targets (Absolute = the literal floor height), so sample the Blender surface directly there. Cells fully inside a bunker stop shaping the fringe.
- **Green limitation.** The green is *not* driven by cells; it comes only from arrows in the heat-map picture. A Blender green cannot be imported as cells. Options: (1) leave the green as arrow-driven and import only fringe/bunkers (recommended for phase 2); (2) later, synthesise arrows (or a replacement height source) from a Blender green, which is a new generator feature, not an import tweak. Also note the fringe is pulled toward the green rim over about a quarter of a cell near the green, so Blender fringe heights right at the green edge will be overridden by the arrow-derived rim.

---

## Key recommendations

1. Preview heights only (grid to three.js), never the full printable mesh.
2. Fringe + bunkers: one server endpoint reusing the real TPS code at about 96x96; TPS maths is cheap (7-30 ms at 64x64 measured), so no JavaScript port.
3. Green: cache the raw LSQR field per (image, green outline) and re-run only the fast tail on Elevation range / Z scale / Base thickness. Do **not** just rescale the cached field (limiter is not scale-proportional; up to 2.6 mm error).
4. Moving the green outline needs the slow recompute (about 1 s, est.); debounce to drag-end and show the old green dimmed. Vectorising the direction-field loop would cut it substantially.
5. Omit grass, rake, engraving, seam polish; fake flag/tee holes with markers; bunker rim is 2.0 mm below fringe.
6. Realistic latency: 60-150 ms per cell/polygon/setting edit, 0.5-1.5 s for green outline edits.
7. Phase 2 Blender import: ray-sample into Absolute cells; fringe and bunkers only; the green stays arrow-driven.
