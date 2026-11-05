# Boundary Editor 3D Preview — Design

Nov 5, 2026 · @Qwaz

## Recommendation

Build a 3D preview pane inside the Boundary Editor that redraws the hole about a tenth of a second after each edit, using the generator's own height math so the preview matches the print. It uses three.js in the browser, not Blender: nothing extra to install and no second app to keep in sync.

The preview shows height surfaces only. It skips the slow parts of Generate (building the printable mesh, cutting holes, textures, engraving), which is why it can be fast. A new server endpoint reuses the real fringe, bunker and green functions on a coarse grid and sends back just the heights.

**Effort:** about 2–3 days for a minimal pane (Sienna), plus Topo's geometry endpoint, which isn't estimated yet. Polish and a pop-out window add about 3–4 days; a Blender import button about 1–2 days more.

## What the preview shows

Every part's shape and height, at true vertical scale, in its print colour; surface textures and small details are left out or shown as markers.

| Part | Shown live | How it's computed |
| --- | --- | --- |
| Fringe | Yes | The real fringe spline through your painted cells, on a coarse grid |
| Bunkers | Yes | Rim 2 mm below the fringe, floor following cells fully inside |
| Water | Yes | Flat at the lowest fringe height under its outline |
| Boulders ring | Yes | 5 mm ring around water when Include boundary region is on |
| Water-hole lift | Yes | Everything but water raised 2 mm |
| Green | Yes, see "Handling the green" | Cached arrow solve, with fast re-scaling steps |
| Smooth vs Terraced | Yes, instant | Switched in the browser, no server call |
| Tee and flag holes | As markers | Pins at their positions, not cut holes |
| Grass, sand rake, engraving, seam polish | No | Left out: slow to compute and too fine to judge on screen |

## How it stays live

The browser sends a snapshot of your edits; the local server runs the generator's own height math and returns only height grids for three.js to draw.

&#91;embedded content: preview update loop · browser and local server\]

Only two cases skip the usual path: Smooth/Terraced switches in the browser instantly, and moving the green outline takes the slow re-solve once you let go. The preview reads the editor's in-memory state, so it never touches autosave or the project file.

## Handling the green

Cache the green's raw arrow solve once per image and outline, then re-run only the cheap final steps when a green setting changes, an estimated 30–60 ms.

The green is the hard part because it comes from the arrows (flowchart steps 9–12), not from cells. Three options were considered:

| Option | Update time | Verdict |
| --- | --- | --- |
| Show the green from the last Generate | Instant | Too stale: Elevation range and Z scale changes wouldn't show |
| Cache the solve, rescale the result | Instant | Wrong: the slope limiter works in absolute mm, so scaling after it differs by up to 2.6 mm in Topo's test |
| **Cache the solve, re-run the final steps** | \~30–60 ms (estimate) | **Recommended:** soften, rescale to Elevation range, slope limit, Z scale, exactly as Generate does |

**Moving the green outline** is the one slow case. It changes which arrows count as inside the green, so they must be re-found and re-solved: an estimated 0.5–1.5 s. The preview runs that once when you let go of the outline, showing the old green dimmed meanwhile. A later speed-up of one Python loop could shorten it without changing the output.

## Screen layout and controls

The 3D view opens as a side-by-side pane next to the drawing canvas, toggled with the **3** key, and is off by default so it costs nothing until you want it.

- **Placement:** the canvas and the 3D pane share one row with a draggable divider. The palette strip and Options panel stay where they are. The divider position is remembered per browser, not saved in the project.
- **Hotkey:** **3** toggles the pane. It is free today; G, S, B, C, V, Esc and Cmd+B/P/Z/Y are already taken.
- **Second monitor (phase 2):** a pop-out button opens the 3D view in its own window, kept in sync without the server.
- **Camera:** orbit, zoom, pan, a reset button, and presets for top-down, perspective and side views.
- **Parts:** each part in its print filament colour (green, fringe, bunkers, water, boulders), each with a show/hide toggle.
- **Aids:** wireframe toggle, vertical exaggeration (always labelled on screen so a stretched view isn't mistaken for the real part), and a height readout under the mouse.
- **Two-way highlight:** the cell under your 2D cursor glows in 3D, and hovering in 3D highlights the matching cell on the canvas.

The preview code lives in its own files, so the editor page only gains a button, a container and a few refresh calls. three.js is bundled with the app at a fixed version and loads only the first time the pane opens.

## Accuracy and speed

Most edits should show in 60–150 ms, and heights should match the print because the preview calls the generator's own functions.

| Edit | Target update time |
| --- | --- |
| Paint cells, Slope tool, Grid mode | 60–150 ms |
| Move a bunker, water or tee | 60–150 ms |
| Elevation range, Z scale, Base thickness | 60–150 ms |
| Smooth / Terraced | Instant |
| Move the green outline | 0.5–1.5 s, once on release |

These are estimates, except the fringe spline itself, which Topo measured at 7 ms (20x20) and 30 ms (40x40) on a coarse grid. While you drag, the preview uses a coarser grid and refreshes about 10 times a second, then redraws in full when you let go. If a newer edit arrives, an older result is thrown away, so a fast stroke never shows a stale surface.

To keep the preview honest, a test will compare its heights against real Generate output. A preview that disagrees with the print would be worse than none.

## Phases

1. **Minimal pane (about 2–3 days UI, plus the geometry endpoint):** side-by-side 3D view, all parts in colour, live fringe and bunkers, green from the cached solve, toggle with **3**.
2. **Polish (about 3–4 days):** pop-out window for a second monitor, two-way cell highlight, height readout, camera presets, coarse-while-dragging refresh.
3. **Blender import (about 1–2 days):** sample a surface sculpted in Blender at each cell centre and write it as Absolute cell values. This shapes the fringe and bunkers only; the green still comes from the heat-map arrows.

## Open questions for Thomas and Jim

- [ ] Is **3** a good key for showing and hiding the pane?
- [ ] Should the view open at true vertical scale, or slightly exaggerated so slopes are easier to see?
- [ ] Is a 0.5–1.5 s wait after moving the green outline acceptable, or is speeding it up a phase-1 must?
- [ ] Do you want a rough grass look in the preview, or is a plain fringe fine?
- [ ] For phase 2, which matters more: the pop-out window or the Blender import?
- [ ] For Blender import, is it acceptable that the green can't be sculpted there?
