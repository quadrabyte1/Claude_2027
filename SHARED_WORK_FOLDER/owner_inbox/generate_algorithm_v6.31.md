# Boundary Editor v6.31 - What happens when you click Generate

Companion to `generate_algorithm_v6.31.svg` (Level 0 overview), `generate_algorithm_v6.31_surface.svg` (Zoom A, steps 8-13) and `generate_algorithm_v6.31_regions.svg` (Zoom B, steps 17-19). The same three figures are pages in `generate_algorithm_v6.31.drawio` (editable). Step numbers below match the black number badges in the figures; sub-steps (9a, 13c ...) are on the zoom pages.

**One-line summary.** The browser saves the project (EGM) and posts all parameters; the server checks prerequisites and mints a UUID4; `run_pipeline()` turns the EGM's heat-map image and polygons into meshes (green, fringe, bunkers, water, boulders); the meshes are assembled, engraved on the underside, validated and written as one `.3mf`; the browser reports the result.

**Input:** one `.egm` project file (JSON: polygons, painted grid-cell values, parameters, embedded heat-map PNG since v6.21).
**Output:** `<Course> Hole NN [<uuid4>].3mf` in the course's `3MFs/` folder (plus diagnostic PNGs in `owner_inbox/diagnostics/`).

Notes on scope: Generate has no result cache; every click recomputes everything (the only "cache" nearby is the degridded heat-map PNG, which a running Generate pins so cleanup cannot delete it). `generate_stl_3mf.py` is not on the Generate path (the Flask app only shares constants with it); the geometry lives in `gradient_surface_diagnostic.py`. `plate_text.py` supplies the text-to-mesh routine used by the engraver. The v6.30 speed-up is `_PolylineIndex` (exact spatial index replacing a brute-force nearest-segment search), used when seam-snapping fringe cells in `build_fringe_mesh` and when snapping green-boundary vertices in `_build_heightmap_mesh`. App version in the working tree has since moved to v6.32 (UI only); the pipeline described here is the v6.31 one.

---

## Browser lane

**1. Click Generate.** The Generate button (`editor.html`, `generateSTL()`), or key G / Cmd+G (`handleGenerateKey`, ignored while typing or while a dialog is open or a run is in progress). *In:* click. *Out:* call to `generateSTL()`.

**2. Pre-check (decision).** Course name and hole must be non-empty and at least one polygon must exist. *No ->* shared modal ERROR dialog ("Set course name and hole number first" / "No polygons to generate models from"). *Parameters:* course name, hole number, drawn polygons.

**3. Auto-save EGM.** `autoSave()` writes the current project to disk so the server reads the latest state (grid cells, grass parameters, tee marker). A save failure shows "Auto-save failed before generate" and stops.

**4. POST `/api/generate_models`.** Builds the JSON payload: course, hole, image, imageSize, `contourStep`, `grassAmplitude`, `grassSpacing`, `greenStyle`, `elevationRange`, `zScale`, `greenScale`, `fringeEdgeHeight`, `baseThicknessMm`, `includeBoundaryRegion`, `applyFringeFrameCap`, `includeFringeWithoutGrass`, `flagOffsetXMm/YMm`, all polygons and contours, `tee_hole` (mm), `egm_path` (if opened by path), `open_in_slicer`. Sets `generating`, shows "Generation started", and starts an elapsed-seconds ticker on the button. The request stays open until the server replies (dashed grey arrow in the figure).

## Server lane (`app.py`, `generate_models` -> `_generate_models_impl`)

**5. Dependency pre-flight (decision).** `dependency_preflight.check_dependencies()` before any heavy work. Missing package (e.g. `triangle`) -> HTTP 500 and the ERROR dialog; no degraded model is ever produced.

**6. Locate EGM and check GPS prerequisites (decision).** Request must be JSON with course and hole. EGM is resolved as: explicit `egm_path` (`_validate_egm_path`), else `GolfCourses/<course>/EGMs/<name>`, else `owner_inbox/<name>`. The file is read, and `_validate_gps_prereqs` fails fast if a GPS backend is enabled but its file or geo-reference is missing. Failures -> HTTP 400/404 -> ERROR dialog. The v6.15 degrid guard (`degrid_cleanup.TRACKER.generate_guard`) wraps the whole request.

**7. Generation ID and pipeline call.** `generation_id.make_generation_id()` returns a UUID4 (one per click). `run_pipeline(egm_path, include_boundary_region, apply_fringe_frame_cap, include_fringe_without_grass, generation_id)` is called; any exception becomes HTTP 500 with the message shown in the ERROR dialog (this is how `TeeOnGreenError` reaches the user).

## Geometry pipeline (`gradient_surface_diagnostic.py`, `run_pipeline`)

**8. Load EGM and heat-map image.** `load_egm`: reads the JSON, materializes the embedded PNG (`egm_embed.materialize`; legacy EGMs search the course Images folders), requires a green polygon, and builds the dense spline green boundary in pixels. Applies `baseThicknessMm` override. If *Include boundary region* is on, `_apply_boundary_region_derivation` shrinks each water polygon by 5 mm and replaces boulder polygons with a 5 mm ring around the water. *In:* EGM. *Out:* image, green boundary (px), polygon list.

**9. Detect slope arrows** (`detect_arrows`; sub-steps on Zoom A). 9a: `build_dark_mask_inside_green` keeps dark pixels inside the green (value below threshold, or navy hue for StrackaLine arrows). 9b/9c: **LOOP over every connected dark blob** (`cv2.connectedComponentsWithStats`): reject decimal-dot companions, oversize blobs, blobs on the boundary; for survivors `pca_orientation` gives the axis and `resolve_arrow_direction` picks the head (downhill) end. *Out:* list of arrows `{cx, cy, dx, dy}`.

**10. Any arrows? (decision).** *No ->* flat-green fallback: Z = 1.5 mm (5 mm if the hole has water, to clear the 2 mm water slab plus 3 mm), skip steps 11's solve and soften. *Yes ->* step 11.

**11. Height surface** (Zoom A 11a-c). 11a `build_gradient_field`: 200 x 200 grid (`GRADIENT_GRID_RES`), inside-green mask, then **LOOP over every inside cell x every arrow** for inverse-distance-weighted (power 2) blending of arrow directions into a gradient field (sign flipped so it points uphill). 11b `solve_poisson_height` -> `solve_lsq_height`: sparse least-squares (**iterative LSQR**) for Z with grad Z = G. 11c `soften_extremes` clips spurious peaks/valleys against a local window. *Parameters:* arrows in the heat-map image, `elevationRange`.

**12. Green meshes** (`save_stl_meshes`). 12a: convert Z to millimetres using `elevationRange`, then `limit_max_slope` (**LOOP: cap each cell at its lowest neighbour + a maximum step, repeat until nothing changes, at most 400 passes**), then `apply_z_scale` (`zScale`, clamped 0.5-5; relief above the base only). 12b: `_build_heightmap_mesh` builds both a smooth and a terraced mesh (`contourStep`); `drill_flag_hole` cuts the 3 mm flag hole (`flagOffsetXMm/YMm`). `greenStyle` later selects which of the two ships. The green is never grass-textured. Diagnostic PNGs (arrows, height map, overlay) are saved before this step.

**13. Fringe mesh** (`build_fringe_mesh`; Zoom A 13a-h). 13a: fringe heights from the same green Z (same limiter and `zScale`). 13b/c: `_build_tps_grid_height_field` - a 20 x 20 (or 40 x 40) cell grid: each cell defaults to the nearest green-boundary height, user-set cell values override it (delta, absolute or off), cells fully inside a bunker are excluded; one thin-plate-spline (SciPy `RBFInterpolator`) fit through the cell centres gives a smooth field. 13d: **LOOP over each cell of the 200 x 200 fringe grid** (`FRINGE_GRID_RES`): sample the field, median and spike filters. 13e: **LOOP over boundary vertices/cells** snapping onto the green, bunker and water outlines via `_PolylineIndex` (the v6.30 spatial index). 13f: triangulate (earcut polygon-with-holes), carve green / bunker / water / boulder-annulus holes, drop tiny components, watertight rewrite. 13g: `apply_grass_texture_v2` (Bridson Poisson-disk bump placement; `grassAmplitude`, `grassSpacing`, minimum spacing clamp, seam exclusion). 13h: *if Include fringe without grass* a second, smooth fringe is built for plate 2 (loop repeats 13a-f once). A flat copy of the fringe (`fringe_mesh_flat`) is kept without grass for the bunker/water/boulder heights. *Parameters:* painted grid cells and mode, grid resolution, `applyFringeFrameCap`, grass settings.

**14. Water on this hole? (decision).** *Yes ->* `_apply_lift_and_cap`: green meshes and fringe are lifted 2 mm (base-slab thickness under lifted pieces) and capped at 9 mm near the frame (fringe cap raised if painted cells exceed 9 mm; skipped when *Fringe frame cap* is off). *No ->* no lift.

**15. Tee marker on green? (decision).** Only if a tee hole is set (`tee_hole`): `ensure_tee_off_green` raises `TeeOnGreenError` if the collar touches the green; Generate stops with the "tee is on green" ERROR dialog and writes no 3MF (v6.31). Otherwise `drill_tee_hole` punches the tee hole and collar in the fringe (step 16 box).

**16. Seam polish.** `polish_green_fringe_seam` closes the remaining gap between green rim and fringe (applied to the plate-2 sample too).

**17. Bunkers** (`export_trap_stls`; Zoom B). **LOOP over each bunker polygon:** 17a inset outline by the print tolerance (skip if empty); 17b floor = fringe height minus 1 mm at the rim, shaped by the grid cells fully inside the bunker (or a ruled surface across the strongest gradient when none are set); 17c `apply_sand_texture`; 17d/e if the texture mesh is not watertight, **LOOP: retry with the next of 6 alternative sample pitches** (`_texture_trap_or_fallback`); all fail -> plain slab with a warning (body never dropped); 17f lift/cap if water hole, add to scene.

**18. Water** (`export_water_meshes`). **LOOP over each water polygon:** inset, clip to plaque, subtract mount pipe (if enabled); top height = lowest fringe height under the outline; flat slab, no ripple (disabled); lift/cap if water hole.

**19. Boulders** (`export_boulders_meshes`). **LOOP over each boulder ring:** if the ring fully encloses a water polygon -> annulus (ring minus water), else a filled flat slab; height from the fringe minimum under the footprint.

## Output lane

**20. Assemble scene.** A `trimesh.Scene` with `green_surface` (smooth or terraced per `greenStyle`), `fringe`, `trap_N`, `water_N`, `boulders_N`, and optional `fringe_no_grass_sample`. File name `<Course> Hole NN [<uuid>].3mf`.

**21. Engrave underside** (`fringe_label_engraver.engrave_fringe_label`, text meshes from `plate_text.render_text_mesh`). Fringe: course/hole label plus short ID; green: short ID (first UUID segment, 8 hex chars) centred; other bodies untouched.

**22. Clean-up and manifold check (decision).** Per mesh: merge vertices, drop degenerate and duplicate faces, drop micro-components (20 faces or fewer). `assert_manifold` raises if boundary-edge or triple-shared-edge counts exceed tolerance -> HTTP 500 -> ERROR dialog. `strict_manifold_problems` adds warnings for the engraved bodies.

**23. Write 3MF.** `scene.export`, then `_inject_bambu_extruder_metadata` (filament/extruder assignment by body name); diagnostic images are listed in the log.

**24. Open in slicer.** If *Open in slicer* is ticked, macOS `open <file>`; failure or timeout is reported as a warning, not an error.

**25. JSON reply.** `{status, file{name,path,type}, generationId, slicerOpened, slicerError, warnings}` (warnings include texture fallbacks and manifold notes).

**26. Browser result.** Status line "Generated in Ns" (plus slicer note, plus any WARNING text, which keeps the message sticky); failures open the modal ERROR dialog.

---

## Loops at a glance

| Where | Repeats over | Ends when |
|---|---|---|
| 9 arrow detection | each dark blob | all blobs processed |
| 11a gradient field | each inside cell x each arrow | grid done |
| 11b height solve | LSQR iterations | solver converges |
| 12a slope limiter | passes over the height grid | no cell changes, max 400 |
| 13d fringe sampling | each of 200 x 200 fringe cells | grid done |
| 13e seam reseat | each boundary vertex/cell (spatial index) | all snapped |
| 13h plate-2 sample | fringe build repeated once | only if ticked |
| 17 bunkers | each bunker polygon | none left |
| 17d/e texture retry | up to 6 alternative pitches | watertight, or fall back to plain slab |
| 18 water | each water polygon | none left |
| 19 boulders | each boulder ring | none left |

## Branches and stops at a glance

Browser: missing course/hole/polygons; auto-save failure. Server: missing package; EGM not found; GPS prerequisites. Pipeline: no arrows (flat green); water hole (lift and cap); tee on green (error); bunker texture failure (plain slab + warning); manifold failure (error); slicer open failure (warning). Any uncaught pipeline exception reaches the browser as an ERROR dialog.
