# Live 3D Preview Pane: UI and Architecture Design (Sienna)
Boundary Editor v6.33 baseline. Design only, no code touched. Topo's geometry doc (`preview_design_geometry.md`) did not exist yet when I wrote this, so the plumbing below works with either of his options.

## 1. Layout
**Today:** the page is one column. Header, action bar, collapsible Options panel, then a row with the Z-Painting palette strip on the left and the canvas filling the rest (`flex-1 min-w-0`). The canvas box is `relative` and `overflow-hidden`.

**Proposal:** put the canvas and a new 3D pane in a two-column flex row, canvas left and preview right, like VS Code's side-by-side markdown preview. The palette strip stays where it is, and the Options panel stays above both.
- **Divider:** a draggable bar between the two, with the split saved in localStorage (a view preference only, never written to the EGM, like `editorOptionsOpen`). Default is 50/50, with minimum widths so neither pane disappears.
- **Toggle:** a "3D" button in the action bar plus a hotkey. Hotkeys already in use are G (Generate), S (Slope), B (Paint), C and V (copy/paste), Esc, and Cmd+B/P/Z/Y. **Proposed hotkey: `3`** (plain key, ignored while typing in an input, same as B). It is free and easy to remember. Preview off means zero cost: no GL context, no computing.
- **Pop-out:** a "Pop out" button opens `/editor/preview` in a second window, which is useful on a second monitor. The editor sends it updates through a `BroadcastChannel` (same browser, no server). Phase 2, because the pane code is the same either way.
- **Small screens:** under about 1100 px wide the pane stacks below the canvas, or the pop-out is suggested instead.

## 2. What's in the pane
- **Camera:** orbit, zoom, pan (three.js OrbitControls). Buttons: Reset view, Top-down (orthographic), Perspective, Side.
- **Colours:** one mesh per part, using the same hexes as the print filaments (green, fringe, bunkers, water, boulders). Those hexes go in a single constants table that the 3D pane and the legend share.
- **Toggles:** a checkbox per part (show/hide), Wireframe, and a Vertical exaggeration slider (1x to 10x, default maybe 3x, since 2 mm of slope is hard to see at true scale). The exaggeration label must always be visible so nobody misreads it.
- **Hover readout:** hover over the 3D surface to see "x, y, height mm" and which part it is (raycast against the mesh).
- **Two-way cell highlight:** the cell under the 2D cursor lights up as an outlined patch on the 3D surface. Hovering the 3D surface draws a marker on the matching cell in 2D. This needs only a cell-index message in each direction, since the grid is already 20x20 or 40x40.
- **Hole outline:** the 2D polygons optionally draw as thin lines on the 3D surface, to help orientation.

## 3. Update loop
**Triggers** (all funnel into one function, `requestPreviewRefresh(reason)`): cell paint or erase, Slope commit, polygon vertex edit or move, tee-hole move, Options change (base thickness, amplitudes, and so on), undo/redo, and project open.

**Timing:**
- During a drag (painting, vertex drag, slope preview) use *throttle + trailing debounce*: refresh at most every ~100 ms while dragging, plus one final refresh about 150 ms after the last change. A one-stroke paint is one logical edit, so the final refresh happens on mouse-up.
- Discrete edits (single click, undo, Options field) refresh after a short debounce of ~50 ms.
- Requests carry a sequence number. Any result older than the newest request is thrown away, so you never see an out-of-date shape flash up.
- A small "updating..." dot in the pane corner appears only if a refresh takes more than ~300 ms. No spinner otherwise.

**Compute location, so Topo can choose** (the interface is the same either way):
- *Client:* a **Web Worker** receives a compact snapshot (grid values, polygons, options) and returns typed arrays (heightfield or vertices and indices). The main thread then only uploads buffers to the GPU. This keeps painting smooth.
- *Server:* a lightweight endpoint, e.g. `POST /api/preview` with the same snapshot, returns **binary** (a small header plus Float32 heights per part, or vertex/index buffers). It runs the same Python code the generator uses, so it cannot drift from the print result. It is the right choice if the full geometry (TPS, trap overrides) is too heavy or too fiddly to port to JS.
- The pane talks to a `PreviewSource` with one method, `compute(snapshot) -> buffers`, so a worker source and a fetch source are swappable (or the worker could call the server). The snapshot is taken from the editor state, never the file on disk.

**Autosave coexistence:** the preview reads the *in-memory* editor state and never touches EGM files, so it needs no save, and autosave is unchanged. The server endpoint must be stateless (no file writes, no live-DB access), and the preview must never block or delay `autoSave()`. Preview errors go to a quiet in-pane message, not the shared Error dialog, since a failed preview should not interrupt painting.

**three.js loading:** the app already loads Tailwind and Alpine from CDNs, but a 3D tool should work offline. Recommendation: **vendor a pinned three.js (module build + OrbitControls) in `app/static/vendor/three/`**, e.g. r160-era, version recorded in a constant and shown in the pane's "about" tooltip. Lazy-load it only when the pane is first opened, so the editor's start-up cost is unchanged. No build step needed (ES modules via importmap).

**Code placement:** write the pane as a separate file (`static/preview3d.js`, plus `preview_worker.js`) with a tiny interface to the editor: `Preview3D.mount(el)`, `.update(snapshot)`, `.setHoverCell(i,j)`, and an event for 3D hover. This keeps it out of the 5,800-line `editor.html`.

## 4. Effort (rough)
| Phase | Scope | Estimate |
|---|---|---|
| 1. Minimal pane | Toggle + hotkey, fixed split, vendored three.js, one coloured mesh per part from the heightfield, orbit/reset, refresh on cell paint/slope/Options with debounce + sequence numbers | 2-3 days (plus Topo's geometry work) |
| 2. Polish | Draggable divider + saved width, per-part toggles, exaggeration, wireframe, presets, hover readout, two-way cell highlight, polygon-drag refresh, pop-out window, Web Worker | 3-4 days |
| 3. Blender | "Open in Blender" button: export the current preview geometry (or call the existing generate path) to a temp file and launch Blender with an import script | 1-2 days, depends on the Blender setup |

## 5. Risks
- **Performance on 40x40:** 1,600 cells is small for the GPU, but the real cost is the *geometry compute* (TPS, fringe, bunkers). Mitigations: a coarser preview mesh while dragging with full detail on release, the Worker, and discarding stale results. Measure early with a real 40x40 EGM.
- **editor.html size:** it is already about 5,800 lines. Keep all preview code in separate files with a narrow API, and add only a button, a container div, a hotkey and the trigger calls to the editor.
- **Preview vs. print mismatch:** a preview that differs from the real 3MF would be worse than none. The server option avoids this; if client-side, a test must compare the preview heights against the generator's on fixture EGMs, within a stated tolerance.
- **Hotkey and focus:** the 3D pane must not steal keys (S, G, B, Cmd+Z) when it has focus. Keys should pass through to the editor's existing `handleKey`.
- **Testing:** headless-browser checks per our rule, with saves intercepted and temp DB/EGM copies only. Tests cover toggle and hotkey, divider persistence, and that a paint produces a refresh and the latest sequence wins. Python tests cover the endpoint (binary format, statelessness, no file writes) and the compare-to-generator check. Tests import the same named constants (hotkey, throttle/debounce ms, colours, version) as the code. **No literals: every value is a named constant.**

## Recommendations in brief
Side-by-side pane with draggable divider; `3` to toggle; vendored pinned three.js lazy-loaded; separate JS files; one refresh function with throttle + debounce + sequence numbers; Worker or binary endpoint behind one `compute()` interface; start with phase 1 and compare against the generator output before polishing.
