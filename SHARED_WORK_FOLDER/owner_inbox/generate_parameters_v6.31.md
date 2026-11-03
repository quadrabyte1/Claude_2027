# Boundary Editor v6.31 — Generate Parameters

> **Version badge:** Boundary Editor **v6.31** — catalog of every parameter that shapes what the **Generate** button produces (Mode 2 UI only).
> Prepared by Topo (3D Modeling / Computational Geometry). Documentation only; no code was changed.
> Note for the record: `APP_VERSION` in `app/app.py:32` read `"v6.32"` when this was written; the editor template header comment still tops out at v6.28 text. The parameter set below was read from the code as it stands, so treat it as "v6.31 as shipped plus anything v6.32 added".

**Source abbreviations** (all paths under `/Volumes/GIT/Claude_2027/SHARED_WORK_FOLDER/app/`):

| Short | File |
|---|---|
| `ED` | `templates/editor.html` |
| `APP` | `app.py` |
| `GSD` | `gradient_surface_diagnostic.py` (the generation pipeline, 11,975 lines) |
| `GEN` | `generate_stl_3mf.py` (shared constants and slab builder) |
| `ENG` | `fringe_label_engraver.py` |
| `GID` | `generation_id.py` |

---

## 0. How Generate works (what the knobs feed)

1. **Button.** `Generate` (Output group, right end of the bar under the canvas; shortcut **G** or Cmd/Ctrl+G) calls `generateSTL()` (`ED:5458`).
2. **Auto-save first.** The editor autosaves the whole project to the `.egm` file (`ED:~4670`, route `POST /api/boundaries`). **This saved EGM is what the pipeline actually reads.**
3. **Request.** `POST /api/generate_models` (`APP:114`, handler `APP:2272-2279`). The JSON repeats most Options fields, but the route only *uses* `course`, `hole`, `egm_path`, `includeBoundaryRegion`, `applyFringeFrameCap`, `includeFringeWithoutGrass` and `open_in_slicer`. Everything else (contourStep, zScale, greenScale, grass, tee hole, flag offsets, base thickness, polygons...) is re-read from the freshly autosaved EGM file by `run_pipeline`. In practice the two are identical because of step 2.
4. **Pipeline.** `run_pipeline()` (`GSD:11023`): load EGM (+ embedded heat-map PNG) -> detect slope arrows in the image -> solve green height field -> mesh green (smooth *and* terraced) -> drill flag hole -> build fringe from a thin-plate-spline (TPS) height field over the 20x20 or 40x40 grid -> grass texture -> water-hole lift -> tee hole -> seam polish -> bunkers, water, boulders -> engrave underside text -> manifold checks -> write `.3mf` and inject Bambu/Orca extruder metadata.
5. **Output.** One `.3mf` named `"<Course> (Hole NN) [<uuid>].3mf"` in the course `3MFs/` folder.

**Physical frame of reference.** The heat-map image's *longer side* is scaled to `PRINT_SIZE_MM` = 171.45 mm (6.75 in). The fringe plaque is slightly smaller (half-side 85.1965 mm, i.e. a 170.39 mm square). All "mm" below are print millimetres. Z = 0 is the bottom face of the print.

**Mode scope.** Only Mode 2 (Boundary Editing / Z-Painting) is catalogued. Mode 1 is dormant behind `UI_MODE_SWITCH_ENABLED = false` (`ED:886`); Mode-1-only items are in Appendix A.

**Where "Options" lives.** Most numeric fields are in a collapsible **Options** panel (button labelled `Options`, collapsed by default, `ED:871`, markup `ED:120-280`). The grid, shape and Generate controls are in the bar under the canvas.

---

## 1. Print size and base

| Parameter | Web-page field | Default / range | Effect on generated part | Source |
|---|---|---|---|---|
| `PRINT_SIZE_MM` | not exposed in UI, code constant (editor mirrors it as `DEFAULT_PRINT_SIZE_MM`, display only) | 171.45 mm | Sets overall scale: the longer side of the heat-map image maps to this length, so px-to-mm scale = 171.45 / max(image width, image height). Every polygon, cell and hole position scales with it. | `GEN:75`, `GSD:2271 _compute_px_to_mm`, `ED:1250` |
| `imageSize` (EGM / payload) | not a field; taken from the loaded image automatically | image pixel width x height | Defines the px-to-mm scale and the origin (image centre = print centre). A different image size at the same polygons changes the print scale. | `ED:4680`, `GSD:2276` |
| `FRINGE_XY_EXPANSION_MM` / `FRINGE_HALF_MM` | not exposed in UI, code constant | -1.057 mm total per axis; half-side 85.1965 mm | Shrinks the fringe plaque (outer frame) slightly below the nominal 171.45 mm so printed plates mate. Defines the square on which the fringe and the whole grid sit. (A comment in `GEN:134` says ~88.47 mm; the formula actually gives 85.1965 mm.) | `GEN:133-134` |
| `baseThicknessMm` | **Base thickness (mm)** - number box in Options, step 0.1, min 0.1 | 1.5 mm | Sets `BASE_THICKNESS_MM`: the lowest allowed height of the *green top surface* (green heights are mapped into [base, base + elevation range]); also the zero-point that Z scale multiplies from and the floor of several clamps. The solid below it is the part's body (bottom face is Z = 0). **Side effect:** the pipeline overwrites a module global, so a later run with an empty/zero value keeps the previous run's value until the server restarts. | `ED:213`, default `ED:1262`, `GSD:1950`, override `GSD:11100-11112` |
| `FRINGE_MIN_THICKNESS_MM` | not exposed, code constant | 1.0 mm | Printability floor of the fringe top: the fringe is never thinner than this above the bottom face (v6.20 - it follows the EGM slope all the way and is no longer floored at the base thickness). Also the floor for any grid-cell override. | `GSD:1960` |
| `FRINGE_PLATEAU_TILT_MM` | not exposed, code constant | 0.10 mm peak-to-peak | Adds a tiny diagonal ramp so a region clamped to the floor is never exactly horizontal (avoids slicer "layer conflict" warnings). Invisible to the eye. | `GSD:1963`, `GSD:4812` |
| `WATER_HOLE_LIFT_ENABLED` / `WATER_HOLE_LIFT_MM` | not exposed, code constants (triggered automatically when the hole has a water polygon) | True / 2.0 mm | If the hole contains any water polygon, green, fringe and bunkers are all raised 2 mm (a 2 mm base slab is added under them) so water sits in a basin. Bottom face stays at Z = 0. Water itself is not lifted. | `GSD:2072-2073`, `GSD:11663-11727`, `GSD:7659-7665` |
| `FLAT_FALLBACK_Z_MM` / `FLAT_FALLBACK_Z_WATER_MM` | not exposed, code constants | 0.0 mm / 5.0 mm | If **no slope arrows are detected** in the image, the green becomes a flat plane at this height (5 mm on water holes so it clears the 2 mm water slab), then is clamped up to at least the base thickness. | `GSD:696-697`, `GSD:11190-11215` |

---

## 2. Green surface (terrain relief)

The green's shape comes from **slope arrows in the heat-map image**, not from user-typed heights. Arrows are detected, integrated to a height field (least squares), normalised to the elevation range, then slope-limited and scaled.

| Parameter | Web-page field | Default / range | Effect on generated part | Source |
|---|---|---|---|---|
| Green polygon (EGM `polygons`, type `green`) | the **fuchsia/purple** polygon on the canvas; drag its control points in *Boundary Editing* | one required | Defines the green's outline and *where* arrows are accepted. After Catmull-Rom interpolation it is spline-smoothed and Chaikin-polished, so the printed outline is smooth rather than polygonal. | `GSD:1051 _prepare_egm_geometry`, `GSD:1189 load_egm` |
| `greenStyle` | **Green style** - dropdown in Options: `Terraced` / `Smooth` | Terraced in editor (`ED:1257`); code fallback `smooth` | Chooses which of two meshes ships. *Smooth* = continuous surface. *Terraced* = height quantised into flat steps (stair-step contours). Both are built; only one goes in the 3MF. Also decides which green the seam polish snaps to. | `ED:139`, `GSD:11831`, `GSD:11768`, `GSD:2515 _build_heightmap_mesh` |
| `contourStep` | **Contour step (mm)** - number box in Options, step 0.1, min 0.1 | 0.5 mm | Terraced style only: the height of each step. The number of levels = round(height range / step) and the step is then adjusted so levels divide the range evenly. Smaller = finer steps. No effect on the Smooth style. (If 0/missing the code uses 27 levels.) | `ED:150`, `ED:1254`, `GSD:3443`, `GSD:2542-2553`, `N_CONTOUR_LEVELS GSD:1964` |
| `elevationRange` | **Elevation range (mm)** - number box in Options, step 0.1, min 0.1 | 14.5 mm in editor (`ED:1258`); code fallback 20.09 mm (`GSD:1949`) when empty/0 | Total height spread of the green: lowest point = base thickness, highest = base + this value (before the slope limiter and Z scale). The main "how dramatic is the green" knob. Also sets the ceiling used by the fringe. | `ED:177`, `GSD:3396`, `GSD:11277`, `_height_to_mm GSD:2306` |
| `zScale` | **Z scale x** - number box in Options, step 0.1, **0.5 to 5.0** | 1.0 | Multiplies relief *above the base thickness* on the green and the fringe (so bunkers/water that follow the fringe move too). Base plate and XY unchanged. Applied after the slope limiter. Server clamps to 0.5-5.0. | `ED:186`, `ED:1259`, `GSD:3358 apply_z_scale`, `GSD:386-387` |
| `greenScale` | **Green scale** - number box in Options, step 0.001, min 0.5 | 1.0065 (empty/0 falls back to 1.0065, so exactly 0 cannot be set) | Scales the green polygon about its own centroid in XY only (about 0.65% larger by default) so it mates with the fringe cut-out. Fringe, bunkers, water unaffected. | `ED:195`, `ED:1260`, `GSD:1060`, `GSD:379` |
| `ARROW_DARK_V_THRESHOLD` | not exposed, code constant | 50 (HSV value) | Pixels darker than this inside the green are treated as arrow ink. Raising it picks up lighter marks (and more false positives). | `GSD:454`, call `GSD:11174` |
| `ARROW_MAX_AREA_PX_PIPELINE` (and `_DEFAULT` 1200, `ARROW_MIN_AREA_PX` 25) | not exposed, code constants | 600 px max, 25 px min blob area | Blobs outside this size band are rejected as text/noise rather than arrows. | `GSD:455-457` |
| `NAVY_HUE_MIN/MAX`, `NAVY_SAT_MIN`, `NAVY_VAL_MAX` | not exposed, code constants | hue 90-135, sat > 150, value < 105 | Extra colour test so StrackaLine's navy arrows are caught. | `GSD:459-462` |
| `BOUNDARY_PROXIMITY_PX` | not exposed, code constant | 3.0 px | Arrows whose centroid is closer than this to the green edge are discarded (usually labels). | `GSD:717` |
| `ARROW_FULL_GLYPH` | not exposed, code constant | True | Use the whole arrow glyph to decide its direction (rather than the polygon-clipped piece). | `GSD:715` |
| `GRADIENT_GRID_RES` | not exposed, code constant | 200 x 200 samples | Resolution of the height field across the green; also the sampling of the green mesh (about 0.85 mm per cell at print scale). | `GSD:392` |
| `HEIGHT_SOLVER` | not exposed, code constant | `"lsq"` (unpinned least squares) | Method used to integrate arrow directions into heights (`poisson_pinned` is the legacy option). | `GSD:716`, `GSD:1706` |
| `IDW_NEIGHBOURS` | not exposed, code constant | 4 | Number of neighbouring arrows blended when building the gradient field. | `GSD:408` |
| `_PEAK_LIMIT_MM`, `_VALLEY_LIMIT_MM`, `_SOFTEN_SIGMA_PX`, `_LOCAL_WINDOW_PX` | not exposed, code constants | +6.0 mm, -4.0 mm, 2 px, 11 px window | `soften_extremes`: clips spurious spikes/dips more than 6 mm above or 4 mm below the local average and blends the correction. | `GSD:657-673`, `GSD:720` |
| `_MAX_SLOPE_DELTA_MM` (+ `_MAX_SLOPE_ITERS` 400) | not exposed, code constant | 0.20 mm per cell (about 22% grade) | `limit_max_slope`: no cell may rise more than this above its lowest neighbour, so single-cell spikes become gentle hills. This can compress the achieved relief below the "Elevation range" figure. Applied to the green and again to the fringe seam heights. | `GSD:836-843`, `GSD:846` |
| `PERIMETER_MEDIAN_WINDOW_PX` | not exposed, code constant | 7 cells | Median-filters heights along the green's rim to remove edge spikes. | `GSD:407`, `GSD:2351` |
| `GREEN_BOUNDARY_SPLINE_SMOOTHING_PX`, `_RESAMPLE_PX`, `GREEN_BOUNDARY_SMOOTH_ITERATIONS` | not exposed, code constants | 48.0 px smoothing, 1.5 px resample, 5 Chaikin passes | How strongly the green outline is smoothed (spline fit then corner-cutting). Larger smoothing = rounder, slightly shifted outline. | `GSD:2138-2160` |
| `GREEN_FRINGE_GAP_MM` | not exposed, code constant | 0.02 mm | Clearance between the green's outer edge and the fringe's inner cut-out ("exact cut" fit; 20 micrometres). | `GSD:2184` |
| `SEAM_POLISH_ENABLED`, `_BAND_MM`, `_BLEND_MM` | not exposed, code constants | True, 0.6 mm, 3.0 mm | Final pass that snaps fringe vertices next to the green rim onto the green's height so the join is flush, fading out over 3 mm. | `GSD:6056-6058`, `GSD:6079` |

---

## 3. Fringe surface, grid cells and grass

The fringe is the surrounding terrain. Its height field is a **thin-plate spline fitted through one value per grid cell** (400 cells at 20x20, 1600 at 40x40). Unset cells default to a smooth blend of the green rim's height, so with no cells painted the fringe is simply the green's edge height extended outward.

| Parameter | Web-page field | Default / range | Effect on generated part | Source |
|---|---|---|---|---|
| `gridResolution` | **Resolution** - segmented switch in the Grid row: `20x20` / `40x40` (switching erases all cell values after a confirm) | 20 (EGM omits key when 20) | Number of cells per side. Cell side = 170.39 / N: about 8.52 mm (20x20) or 4.26 mm (40x40). Finer grid = finer sculpting of the fringe and bunker floors. | `ED:752-769`, `ED:1250 GRID_N_*`, `GSD:363-365`, `GSD:4094` |
| `gridMode` | **Grid mode** - segmented switch in the Grid row: `Delta` / `Absolute` / `Off` | Delta | *Delta*: painted values are mm offsets added to the default fringe height. *Absolute*: painted values replace the default with a literal height in mm. *Off*: all painted values ignored (kept on disk). | `ED:737-757`, `ED:952-956`, `GSD:366-370`, `GSD:4123-4147` |
| `gridCellHeights` | **Z-Painting** (sub-mode switch `Boundary Editing` / `Z-Painting`, or Cmd/Ctrl-P): left colour palette, Eraser, right-click popup palette, drag to paint; 2-brush ramp (Cmd-click second swatch); **Slope (S)** tool; click a palette number to type any value; Shift locks a stroke to a row/column | Sparse map cell -> value. Palette: delta -15 to +15 mm, absolute 0 to 30 mm, swatches in 0.5 mm steps, stored to 0.01 mm; ramp interior cells 0.25 mm steps; Slope tool 0.1 mm steps. Server clamps delta to +/-20, absolute to 0-30. A painted 0 is a real value; Eraser empties a cell | The user's direct sculpting input. Each set cell becomes a spline constraint, so a cell raises/lowers the fringe locally with a smooth falloff (no kinks at cell edges). Resolved height is floored at 1.0 mm. **Does not alter the green** (the green comes from arrows). Cells fully inside a bunker belong to that bunker and no longer shape the fringe (see Section 4). | `ED` (Z-Painting, palette: `ED:1017-1027`, `1467-1470`), `GSD:355`, `GSD:4027 _build_tps_grid_height_field`, `GSD:371-374` |
| `FRINGE_DEFAULT_IDW_POWER`, `_RIM_SAMPLE_MM`, `_MIN_DIST_MM`, `_CHUNK_POINTS` | not exposed, code constants | power 5.0, 0.5 mm rim bins, 1e-6 mm, 4000 pts | Controls the "default" fringe height used for unpainted cells: an inverse-distance blend (power 5) of the whole green rim, binned every 0.5 mm. Higher power = more local to the nearest rim; this prevents cliffs where the nearest rim point switches (v6.25). | `GSD:1974-1977`, `GSD:3993 _fringe_default_z` |
| `FRINGE_BLEND_CELLS` | not exposed, code constant | 0.25 cell widths | Width of a cosine blend that pulls the fringe toward the green rim height next to the seam (about 2 mm at 20x20). v6.23 reduced it from 3 cells so painted cells close to the green are honoured. | `GSD:2249`, `GSD:4197` |
| `FRINGE_GRID_RES` | not exposed, code constant | 200 x 200 | Sample grid on which the fringe height is evaluated before triangulation. | `GSD:391` |
| `FRINGE_TOP_MAX_TRIANGLE_AREA_MM2` (+ `TRIANGLE_MIN_ANGLE_DEG` 30) | not exposed, code constants | 1.0 mm2, 30 degrees | Maximum triangle area (about 1.5 mm edges) and minimum angle for the fringe top mesh. Sets mesh density, hence how fine the grass can be. | `GSD:2239`, `GSD:404`, `GSD:3720` |
| `FRINGE_GREEN_EDGE_TAPER_MM` | not exposed, code constant | 15.0 mm | Intended to pull very tall fringe plateaus down toward 9 mm over 15 mm of distance from the green. In practice the target cap is raised to the fringe's own ceiling, so it is likely inert at normal settings. | `GSD:2115`, `GSD:4773-4791` |
| `FRINGE_SPIKE_THRESHOLD_MM` and local `FRINGE_MEDIAN_BLEND` | not exposed (threshold is a module constant; blend is a local variable) | 1.5 mm; 0.5 | The fringe height grid is always smoothed with a 3x3 median blended 50/50 with the original (escalating to 5x5 if any cell is still more than 1.5 mm above its 8-neighbour median). This softens fine detail painted into the grid slightly. | `GSD:411`, `GSD:5198-5232` |
| `SEAM_RADIUS_CELLS`, `TW_SEAM_RADIUS_CELLS` | not exposed, code constants | 1.5 / 0.9 fringe cells | Capture radius for pinning fringe heights at the green seam and at bunker/water seams. | `GSD:413-414` |
| `grassAmplitude` | **Grass amplitude (mm)** - number box in Options, step 0.1, min 0 | 0.5 mm | Height of the cone-shaped grass bumps on the **fringe top** (jittered +/-50% per blade). 0 = no bumps. (The field's tooltip says "on the green surface", but the code never textures the green.) | `ED:159`, `ED:1255`, `GSD:11361`, `GSD:11536` |
| `grassSpacing` | **Grass spacing (mm)** - number box in Options, step 0.1, min 0.5 | Editor default **0.05 mm**; code fallback 2.4 mm | Centre-to-centre distance of grass blades (Poisson-disk placement). **Clamped up to 1.0 mm** by the pipeline, so the default 0.05 mm and any value below 1.0 all behave as 1.0 mm. Larger = sparser, coarser blades. | `ED:168`, `ED:1256`, `GSD:2268 FRINGE_GRASS_MIN_SPACING_MM`, `GSD:11517-11527` |
| `GRASS_ALGORITHM` and v2 kernel args (`profile="cone"`, `amplitude_jitter=0.5`, `xy_shear_mm=0.15`, `poisson_k=30`, `rng_seed=GRASS_RNG_SEED=42`) | not exposed, code constants | v2, cone, 0.5, 0.15 mm, 30, 42 | Shape of the grass: cone profile, +/-50% height jitter, 0.15 mm sideways shear of vertices, deterministic layout (seed 42, so the same inputs give the same grass). | `GSD:2262`, `GSD:10100-10110`, `GSD:449` |
| `FRINGE_GRASS_SEAM_EXCLUDE_MM` | not exposed, code constant | 0.325 mm | Vertices within this distance of the green/bunker/water cut-out edges are not grass-displaced, so seams stay clean. | `GSD:2240` |
| `FRINGE_TOP_MASK_FRACTION` / `FRINGE_TOP_MASK_Z_MM` | not exposed, code constants | 0.5 -> 0.5 mm | Which vertices count as "top surface" for texturing (excludes floor and walls). | `GSD:1961-1962` |
| `applyFringeFrameCap` | **Cap fringe at frame height** - checkbox in Options (group caption "Fringe cap") | checked (True) | Intended: clip fringe (and bunker) heights within 1 mm of the plaque edge to 9 mm, tapering over 5 mm. **In v6.31 this has no effect on geometry**: the whole cap step is disabled by `BOUNDARY_HEIGHT_CAP_ENABLED = False`, so only the water-hole lift is applied. The checkbox is saved and logged only. | `ED:235`, `GSD:2076-2096` (cap constants `BOUNDARY_HEIGHT_CAP_MM` 9.0, `BOUNDARY_CAP_BAND_MM` 1.0, `BOUNDARY_CAP_TAPER_MM` 5.0), disabled at `GSD:2082`, gate `GSD:6632` |
| `includeFringeWithoutGrass` | **Include Fringe Without Grass** - checkbox in Options (caption "Fringe comparison") | unchecked | Adds a **second plate** to the 3MF holding a smooth, grass-less copy of the fringe (`fringe_no_grass_sample`, same filament as fringe) for comparison. Plate 1 always has grass. | `ED:247`, `GSD:11544-11571`, `SCENE_NAME_FRINGE_NO_GRASS_SAMPLE GSD:475` |

---

## 4. Bunkers (sand traps)

| Parameter | Web-page field | Default / range | Effect on generated part | Source |
|---|---|---|---|---|
| Trap polygons (EGM `polygons`, type `trap`) | **Add Trap** button (Shapes group); red polygons, edit control points in *Boundary Editing* | any number | Each becomes a separate bunker body (extruder 3) and a matching cavity cut in the fringe. Outlines get the same spline + Chaikin smoothing as the green. | `ED:652-660`, `GSD:7393 export_trap_stls` |
| `TRAP_BOUNDARY_SPLINE_SMOOTHING_PX`, `_RESAMPLE_PX`, `TRAP_BOUNDARY_SMOOTH_ITERATIONS` | not exposed, code constants | 48.0 px, 1.5 px, 5 passes | Outline smoothness of bunker (and water) polygons. | `GSD:2208-2214` |
| `TRAP_FRINGE_GAP_MM` | not exposed, code constant | 0.125 mm | Clearance between a bunker outline and the fringe cut-out edge. | `GSD:2211` |
| `PRINT_TOLERANCE_MM` | not exposed, code constant | 0.03125 mm (1/32 mm) | Each bunker/water/boulder body is inset by this on every side for a better fit. | `GSD:6394` |
| `TRAP_OUTLINE_SIMPLIFY_TOL_MM` | not exposed, code constant | 0.05 mm | Douglas-Peucker simplification of the bunker outline to remove near-duplicate vertices. | `GSD:429` |
| `BUNKER_BODY_MODE` (`cells` / `ruled` / `legacy`) | not exposed, code constant | `cells` | Selects how the bunker floor is shaped: **cells** (default) follows the grid-cell values inside the bunker; **ruled** is straight chords across the downhill direction; **legacy** is the v5.82 cell-driven floor. | `GSD:6410-6413` |
| `BUNKER_RIM_DROP_MM` | not exposed, code constant | 2.0 mm | At the bunker rim the sand surface sits 2 mm below the local fringe surface. | `GSD:6414` |
| `BUNKER_DROP_BELOW_FRINGE_MM` | not exposed, code constant | 1.0 mm | Used by the legacy (v5.82) floor only. | `GSD:6403` |
| `BUNKER_CELLS_BLEND_BAND_CELLS` (+ `BUNKER_CELLS_RIM_SAMPLE_MM` 0.1, `BUNKER_CELLS_MIN_TPS_CELLS` 3, `BUNKER_CELLS_IDW_POWER` 2.0, `BUNKER_CELLS_QUINTIC` smootherstep) | not exposed, code constants | 1.5 cell widths | In cells mode the floor blends from the rim reference into the cell-driven surface over 1.5 cell widths with a smootherstep curve. Fewer than 3 owned cells falls back to inverse-distance weighting. | `GSD:6419-6424` |
| Cells owned by a bunker (rule, not a number) | **Z-Painting** over a bunker | cells **fully inside** the outline | Painted cells entirely inside a bunker reshape the bunker floor (delta = offsets, absolute = literal floor heights) and are removed from the fringe constraints. Partly-inside cells still shape the fringe. A bunker with no owned cell stays flat. | `GSD:6781 bunker_owned_cells`, `GSD:6813`, `GSD:7011` |
| `TRAP_FRINGE_BOUNDARY_BAND_MM`, `TRAP_FRINGE_OFFSET_MM`, `TRAP_SURFACE_CURVED` | not exposed, code constants | 6.0 mm, -2.0 mm, False | Flat-bunker rule (used when no owned cells): top = lowest fringe height within 6 mm of the outline, minus 2 mm. `TRAP_SURFACE_CURVED=True` would follow the fringe per point (kept, not used). | `GSD:6400-6401`, `GSD:6435`, `GSD:7088` |
| `TRAP_THICKNESS_MM` | not exposed, code constant | 10.0 mm | Fallback flat bunker height only when no fringe mesh is available (should not occur). | `GSD:6393` |
| `BUNKER_MIN_CLEARANCE_BELOW_FRINGE_MM`, `BUNKER_FLOOR_MIN_MM`, `BUNKER_MIN_SOLID_MM` | not exposed, code constants | 0.3 mm, base thickness (1.5, evaluated at import), 0.6 mm | Guard rails: rake crests stay at least 0.3 mm below the fringe; valleys never sink below the plate base; at least 0.6 mm of solid remains. (`BUNKER_FLOOR_MIN_MM` is set from the base thickness at import time, so it does not follow the "Base thickness" field.) | `GSD:6404-6406` |
| `SAND_RAKE_AMPLITUDE_MM` | not exposed, code constant | 1.0 mm peak-to-valley (the `apply_sand_texture` docstring still says 0.35) | Height of the raked-sand ridges on top of the bunker floor. | `GSD:6407`, `GSD:9008` |
| `grain_spacing` (argument default) | not exposed, hard-coded literal | 1.125 mm | Centre-to-centre spacing of rake ridges. | `GSD:9011` |
| `SAND_RAKE_ALIGN_TO_MAJOR_AXIS`, `SAND_RAKE_ISOTROPIC_RATIO` | not exposed, code constants | True, 1.05 | Rake ridges run along the bunker's long axis (area-moment axis); near-round bunkers (ratio < 1.05) fall back to ridges along Y. | `GSD:6446-6447`, `GSD:8969` |
| `SAND_GRID_STEP_FRACTION` + `SAND_RETRY_GRID_STEP_FRACTIONS` | not exposed, code constants | 0.2; retries 0.19, 0.21, 0.18, 0.22, 0.17, 0.23 | Rake sampling pitch = spacing x fraction. If the textured mesh is not watertight, other pitches are tried; if all fail the bunker ships as a plain flat slab and a warning is shown in the editor (a bunker is never dropped). | `GSD:442-447`, `GSD:7365` |
| `TRAP_BASE_Z_GRID_STEP_MM` | not exposed, code constant | 0.225 mm | Sampling pitch for the bunker base height. | `GSD:416` |

---

## 5. Water and boulders

| Parameter | Web-page field | Default / range | Effect on generated part | Source |
|---|---|---|---|---|
| Water polygons (type `water`) | **Add Water** button (Shapes group); yellow polygons | any number | Each becomes a flat slab (extruder 4) and a cut-out in the fringe. Top height = the **lowest fringe height** sampled (12 x 12 points) over its footprint, so it never pokes above its surroundings. Water is not lifted by the 2 mm water-hole lift, so (inferred from the code) it ends up about 2 mm below the lifted fringe on water holes. Smooth, flat top (ripple texture is off). | `ED:662-668`, `GSD:7697 export_water_meshes`, `FRINGE_SAMPLE_GRID_N GSD:415` |
| `WATER_BOUNDARY_SPLINE_*`, `WATER_BOUNDARY_SMOOTH_ITERATIONS`, `WATER_FRINGE_GAP_MM` | not exposed, code constants | 48.0 px / 1.5 px / 5 passes / 0.125 mm | Outline smoothing and the clearance between water slab and fringe cut-out. | `GSD:2212-2215` |
| `WATER_RIPPLE_ENABLED` (+ `WATER_RIPPLE_A1` 0.20, `_A2` 0.08, `_LAMBDA1` 4.0, `_LAMBDA2` 2.5, `_GRID_STEP` 0.5) | not exposed, code constants | **False** | Would add a two-wave "wind chop" ripple on the water top. Disabled since fix #600 because it displaced the slab low. | `GSD:6467-6483` |
| `includeBoundaryRegion` | **Include boundary region** - checkbox in Options (caption "Boundary region") | unchecked | When on, the pipeline *replaces* any hand-made boulders polygons with an auto-generated 5 mm ring around every water polygon: the water slab shrinks inward by 5 mm and a boulders ring (extruder 5) fills the gap. Water too small to shrink is left alone. | `ED:223`, `GSD:11126-11139`, `GSD:8161 _apply_boundary_region_derivation` |
| `BOUNDARY_REGION_BAND_MM` | not exposed, code constant | 5.0 mm | Width of that boulders ring. | `GSD:8062` |
| `BOUNDARY_REGION_COVERS_TOL_MM` | not exposed, code constant | 0.1 mm | Tolerance when deciding that a boulders polygon encloses a water polygon (ring vs. plain slab mode). | `GSD:8071` |
| Boulders polygons (type `boulders`) | **no button in the Shapes group**; only exist in older EGMs or as the auto-ring above | n/a | Ring (annulus) mode if it encloses water, otherwise a flat slab at the lowest fringe height. | `GSD:7855 export_boulders_meshes` |
| `WATER_SHRINK_SIMPLIFY_TOL_MM`, `WATER_SHRINK_SNAP_TOL_MM` | not exposed, code constants | 0.01 mm, 0.02 mm | Geometry clean-up tolerances for the shrunken water outline. | `GSD:469-470` |

---

## 6. Holes and pins (flag, tee, mount bore)

| Parameter | Web-page field | Default / range | Effect on generated part | Source |
|---|---|---|---|---|
| `flagOffsetXMm` | **Flag offset - X offset (mm)** - number box in Options, step 0.5 | 0 | Moves the flag-pin hole right (+) or left (-) from the centre of the green mesh's bounding box. | `ED:267`, `ED:1263`, `GSD:3473` |
| `flagOffsetYMm` | **Flag offset - Y offset (mm)** - number box in Options, step 0.5 | 0 | Moves the flag-pin hole up (+) or down (-). | `ED:274`, `GSD:3474` |
| Flag hole diameter | not exposed, hard-coded literal (`diameter=3.0`) | 3.0 mm | Through-hole drilled in the green (both smooth and terraced meshes). The function's own default is 2.5 mm; the call passes 3.0. | `GSD:3479`, `GSD:3484`, `GSD:2815` |
| `tee_hole` (EGM `x_mm`, `y_mm`) | **Add T Hole / Remove T Hole** button (Shapes group); drag the marker on the canvas | absent until added; default marker 40 mm in from left and 40 mm down from the top of the print bounds (`TEE_HOLE_DEFAULT_X_MM/Y_MM`) | Adds a tee through-hole in the fringe with a reinforcing collar. Position is millimetres from the print's top-left corner. If the collar would touch the green, **Generate stops with the error "Tee is on the green. Move the tee off the green in the editor, then Generate again."** (v6.31). | `ED:671-681`, `ED:1884-1885`, `GSD:11734-11766`, `GSD:3098-3121` |
| `TEE_HOLE_DIAMETER_MM`, `TEE_HOLE_COLLAR_OD_MM`, `TEE_HOLE_COLLAR_PROTRUDE_MM` | not exposed, code constants | 5.55625 mm (7/32 in), 7.55625 mm (1 mm wall each side), 0.0 mm | Tee bore size, collar outer diameter, and how far the collar stands above the fringe (flush). | `GSD:2040-2042` |
| `TEE_HOLE_GUARD_MM`, `TEE_ISLAND_MARGIN_MM`, `TEE_COLLAR_GREEN_CLEARANCE_MM`, `TEE_COLLAR_SEGMENTS` | not exposed, code constants | 0.15 mm, 1.5 mm, 0.0 mm, 48 | Keep-out around the bore, fringe island radius beyond the bore, how close the collar may come to the green, tube tessellation. | `GSD:428-432`, `GSD:397` |
| `ENABLE_MOUNT_BORE` (+ `MOUNT_BORE_INNER_DIAMETER_MM` 4.7625, `WALL_THICKNESS_MM` 1.6, `MOUNT_BORE_INSET_MM` 20.0) | not exposed, code constants | **False** | Optional 3/16 in mounting pipe in the upper-left corner (outer diameter about 7.96 mm). Switched off, so no pipe, no hole in fringe/bunkers/water. | `GSD:1998-2016` |

---

## 7. Text and engraving

Only underside engraving exists in Generate (the large plaque text of `plate_text.py` belongs to the separate Plaque page, `/api/generate_plate`, not to this button; `ENG` merely reuses its text-to-mesh routine).

| Parameter | Web-page field | Default / range | Effect on generated part | Source |
|---|---|---|---|---|
| Label text (course + hole) | **Indirect**: the course name and hole number typed in *New Project* | `"<Course> H<hole>"`, e.g. `Delaveaga H11` (hole as written in the output file name, 2-digit padded, so `H05`) | Engraved into the **back (lowest) face of the fringe** only, reading correctly when the print is turned over (mirrored). Long names shrink to fit 56 mm. | `ENG:54-56`, `GSD:11875`, `APP:200` (`HOLE_LABEL_WIDTH`) |
| Short generation ID | not exposed, automatic (a new UUID4 per Generate click) | first 8 hex characters of the UUID | Engraved on the underside of the **green** (centred) and the **fringe** (second line under the label). Not on bunkers, water, boulders or the plate-2 sample. Gives each printed piece a traceable identity matching the file name. | `GID:30-69`, `ENG:65-68`, `GSD:11875` |
| `ENGRAVE_DEPTH_MM` | not exposed, code constant | 1.0 mm | Depth of the cut into the back face. | `ENG:43` |
| `ENGRAVE_FONT_PT`, `PT_TO_MM`, `ENGRAVE_FONT_FAMILY`, `ENGRAVE_BOLD` | not exposed, code constants | 8 pt (cap height about 2.8 mm), DejaVu Sans, bold | Type size and face of the engraving. | `ENG:44-47` |
| `ENGRAVE_OFFSET_XY` | not exposed, code constant | (0, 0) | Offset from the back-face centre (the engraver moves to an interior point if the centre is over a hole, e.g. the green cut-out). | `ENG:49` |
| `LABEL_MAX_WIDTH_MM` | not exposed, code constant | 56.0 mm | Maximum width of the label line; longer text is scaled down proportionally. | `ENG:52` |
| `ID_LINE_GAP_MM` | not exposed, code constant | 1.5 mm | Gap between the label line and the ID line on the fringe. | `ENG:66` |
| `CUTTER_BOTTOM_EPS_MM` | not exposed, code constant | 0.05 mm | Cutter overshoot below the back face so the Boolean cut is clean. | `ENG:57` |

---

## 8. Output, 3MF and slicer

| Parameter | Web-page field | Default / range | Effect on generated part | Source |
|---|---|---|---|---|
| `open_in_slicer` | **Open in default slicer** - checkbox beside Generate | unchecked | After a successful run, hands the 3MF to the macOS default app for `.3mf` (`open <file>`). Does not change geometry. | `ED:706-713`, `APP:2306`, `APP:2395-2430`, `SLICER_OPEN_COMMAND APP:331` |
| Course name / Hole number | **New Project** dialog (course, hole) and the project label in the bar; Generate is disabled until both are set and at least one polygon exists | required | Names the output file and engraved label; selects the course folder and EGM. | `ED:715-720`, `APP:2290-2300` |
| Output file name | not exposed | `"{course} (Hole {NN}) [{uuid}].3mf"` | One file per click; the UUID makes every run unique. | `GSD:520`, `GID` |
| Scene objects and extruders | not exposed, code constants | green 1, fringe 2 (and `fringe_no_grass_sample` on plate 2), bunkers 3, water 4, boulders 5 | Each body is a separate named object; Bambu/Orca per-object extruder metadata is injected so each part prints in its own filament. | `GSD:473-494`, `GSD:10529 _inject_bambu_extruder_metadata` |
| Bambu bed fallback (`BAMBU_BED_CENTER_MM`, `BAMBU_BED_WIDTH_MM`, `BAMBU_PLATE_GAP_FACTOR`, `BAMBU_PART_ID_BASE`) | not exposed, code constants | (128,128), 256 mm, 0.2, 1000 | Plate geometry used when injecting the Bambu project settings; the bundled `templates/bambu/project_settings.config` supplies printer/process presets. | `GSD:502-507`, `GSD:10524` |
| Manifold gate (`MANIFOLD_TOLERATE_BOUNDARY_EDGES`, `_TRIPLE_SHARED`) and `_MICRO_LIMIT` | not exposed, code constants | 30 open edges, 5 triple-shared, 20 faces | Acceptance thresholds for the mesh check; micro-fragments of 20 faces or fewer are deleted so the slicer sees no floating specks. | `GSD:495-499`, `GSD:11911` |
| Required packages | not exposed | e.g. `triangle` | Generate refuses to run (clear error) if a required Python package is missing, rather than shipping a degraded model. | `dependency_preflight.py`, `APP:2287-2293` |
| Other mesh quality constants | not exposed, code constants | `CIRCLE_SEGMENTS_DEFAULT` 64, `CIRCLE_BUFFER_RESOLUTION` 32, `VERTEX_MERGE_DIGITS` 6, `BOOLEAN_ENGINES` manifold then blender | Tessellation of drilled holes, merge tolerance, and the Boolean engines used for holes and engraving. | `GSD:396-400` |

---

## 9. Editor controls that do NOT change the generated part

| Control | Field label | Why it has no effect |
|---|---|---|
| Fringe edge height | **Fringe edge height (mm)** (Options, default 10.0, min 0.5) | **Ignored.** Sent in the payload and saved in the EGM, but the pipeline stopped reading it in task 483 (fringe now follows the slope to the frame). `GSD:1951-1956`, `GSD:3398`. |
| Fringe cap | **Cap fringe at frame height** | Saved, logged, but the cap step is globally switched off (see Section 3). |
| Contour polygons (type `contour`) | not reachable in Mode 2 | Sent in the Generate payload but the pipeline has no code path that reads them (arrows, not contour lines, drive the green). |
| Image view | **Image:** `Original` / `Degridded` / `Hide` | View only; Generate always uses the original PNG embedded in the EGM. |
| Colour cells | **Color cells by height** | View only (localStorage). |
| Slope prompts | **Show Slope prompts** | UI only. |
| Autosave / undo | n/a | Does not change geometry; it only guarantees the latest values are in the EGM when Generate runs. |
| `gpsBackend`, `courseGeoRef`, `elevationSpikes`, `fringeBoundaryHeights` | no UI (GPS removed v5.16; geo-ref removed v5.17) | Round-tripped in the EGM for old projects but ignored by Generate (spikes and fringe-boundary heights were deliberately stripped, tasks 690/698). |

---

## Appendix A - Mode-1-only items (dormant; not reachable in v6.31)

Behind `UI_MODE_SWITCH_ENABLED = false` (`ED:886`): contour-line drawing, the single-cell grid **value box** (type a value for a selected cell), grid copy/paste (Cmd/Ctrl+C / V), the B-key paint toggle and Cmd/Ctrl-drag cell selection with first/last ramp popup. They write the same `gridCellHeights` / `contours` data; contours are ignored by Generate as noted above, and cell values are covered in Section 3.

## Appendix B - Count of catalogued parameters per group

| Group | Rows | of which have a visible web-page field |
|---|---|---|
| 1. Print size and base | 7 | 1 (Base thickness) |
| 2. Green surface | 21 | 5 (Green style, Contour step, Elevation range, Z scale, Green scale) + the green polygon itself |
| 3. Fringe, grid cells, grass | 17 | 7 (Resolution, Grid mode, Z-Painting cells, Grass amplitude, Grass spacing, Cap fringe, Include Fringe Without Grass) |
| 4. Bunkers | 17 | 1 (Add Trap + Z-Painting inside bunkers) |
| 5. Water and boulders | 8 | 2 (Add Water, Include boundary region) |
| 6. Holes and pins | 7 | 3 (Flag X, Flag Y, Add T Hole) |
| 7. Text and engraving | 8 | 0 directly (course/hole come from New Project) |
| 8. Output / 3MF / slicer | 8 | 2 (Open in default slicer, course/hole) |
| 9. No-effect controls | 8 | 6 |

Row counts include grouped constants (a row sometimes lists 2-5 closely related constants). Of the roughly 100 individual named values, **about 15 are reachable from the web page; the rest are code constants.**
