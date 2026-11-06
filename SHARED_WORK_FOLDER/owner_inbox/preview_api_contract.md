# Boundary Editor live 3D preview: server API contract (phase 1)

For Sienna. Written by Topo against app v6.34. Server code: `app/preview_geometry.py` (maths and wire format), route in `app/app.py` (`api_preview`). Everything below is enough to write the client without reading the source.

## 1. Route

| | |
| --- | --- |
| Method and path | `POST /api/preview` (constant `ROUTE_API_PREVIEW` in `app.py`) |
| Request | `Content-Type: application/json` |
| Success response | `200`, `Content-Type: application/octet-stream`, `Cache-Control: no-store`, header `X-Preview-Seq: <seq>`, body = the binary layout in section 4 |
| Error response | JSON `{"status":"error","code":"<code>","msg":"<text>"}` with the HTTP status in section 5 |

The endpoint is stateless. It never writes a file, never touches an `.egm`, never opens a database, and never calls autosave. It reads only the JSON body (plus the heat-map image file, read-only, to find arrows). It is safe to call at any time, including while autosave is running.

## 2. Request body

```json
{
  "snapshot": { ...editor state, see 2.1... },
  "seq": 17,
  "fringeRes": 96,
  "greenMode": "auto"
}
```

| Key | Type | Required | Meaning |
| --- | --- | --- | --- |
| `snapshot` | object | yes | In-memory editor state (2.1). |
| `seq` | integer 0..4294967295 | no (default 0) | Your sequence number. Echoed in the `X-Preview-Seq` header and in the binary header (`seq`). Drop any response whose `seq` is older than the newest request you sent. |
| `fringeRes` | integer 32..200 | no (default 96) | Fringe grid size (cells per side). Use a smaller value (e.g. 48) while dragging, 96 on release. |
| `greenMode` | `"auto"` or `"cachedOnly"` | no (default `"auto"`) | `"auto"`: on a green cache miss, run the slow solve. `"cachedOnly"`: on a miss, do NOT solve; reply `409 green_cache_miss` immediately (see 6). |

### 2.1 `snapshot`

It is exactly the object the editor already POSTs to `/api/boundaries` to save an EGM (same keys, same shapes), taken from in-memory state, not from disk. You can pass that object unchanged. The server reads only these keys and ignores the rest:

| Key | Used for |
| --- | --- |
| `image`, `imageCourse` | Find the heat-map PNG (same lookup as Generate; `imageCourse` may be the editor's `_embedded_<sha>` pseudo-course). Required. |
| `imageSize` `{width,height}` | Pixel-to-mm scale. |
| `polygons[]` | Each `{type, points:[{x,y}...], closed, name}` with `type` in `green` (exactly one required), `trap` (bunkers), `water`, `boulders`. Points are image pixels, the same control points the editor draws (the server applies the same Catmull-Rom, spline and Chaikin smoothing Generate does). |
| `gridCellHeights` | Sparse map `{ "<row*N+col>": mm }`. Key present means set; an explicit 0 counts. |
| `gridMode` | `"delta"`, `"absolute"` or `"off"`. |
| `gridResolution` | 20 or 40 (cells per side; absent means 20). |
| `elevationRange` | Green relief range in mm. |
| `zScale` | Vertical amplitude multiplier (clamped 0.5..5). |
| `baseThicknessMm` | Base thickness (blank, 0 or invalid means 1.5). |
| `greenScale` | XY scale of the green polygon about its centroid. |
| `includeBoundaryRegion` | When true, the 5 mm boulders ring and shrunk water are derived exactly as Generate does. |
| `tee_hole` `{x_mm,y_mm}` | Tee marker position (mm from the plate's top-left corner). |
| `flagOffsetXMm`, `flagOffsetYMm` | Flag marker offset from the green centre. |
| `fringeBoundaryHeights` | Legacy anchors, honoured if present. |

Ignored by the server (client concerns): `greenStyle`, `contourStep` (smooth versus terraced is done in the browser, section 7), all grass, rake and engraving settings, `applyFringeFrameCap` (the frame cap is switched off in the generator), `includeFringeWithoutGrass`.

## 3. Coordinates and conventions (apply to every part)

- **World frame**: millimetres, origin at the plate centre, **+X right, +Y up** (the image's Y axis is flipped). The plate spans `±plate_half_mm` (header field, 85.1965 today) on both axes.
- **Height (Z)**: millimetres above the plate bottom (z = 0), **true scale, no exaggeration**. Exaggeration is yours to apply (scale `z` about 0).
- **Grid layout** (every part): row-major, `heights[row*nx + col]`. **Row 0 is the smallest Y (bottom of the plate), column 0 is the smallest X.** Node `(row,col)` is at `x = xmin + col*(xmax-xmin)/(nx-1)`, `y = ymin + row*(ymax-ymin)/(ny-1)`. Grids are node-based: draw `(nx-1)*(ny-1)` quads, two triangles each.
- **Mask**: one byte per node, `1` = this node belongs to the part's surface, `0` = not. Emit a triangle only if all three of its nodes are `1`.
- **Heights are always finite** (never NaN). Where the mask is 0 the height is a filler value (see per part); do not draw it.
- **Water-hole lift**: when the hole has a water polygon, green, fringe, bunkers, and both markers include the +2 mm lift already (`flags & 4`, `lift_mm = 2`). **Water and boulders are not lifted** (Generate sizes them from the unlifted fringe). You do nothing; the numbers are final.

## 4. Binary layout (little endian, no padding)

```
[ header (40 B) ][ part table: n_parts * 36 B ][ marker table: n_markers * 20 B ][ data blob ]
```

### 4.1 Header, 40 bytes

| Offset | Type | Name | Meaning |
| --- | --- | --- | --- |
| 0 | char[4] | `magic` | `"EGMP"` |
| 4 | uint16 | `version` | `1`. Reject anything else. |
| 6 | uint16 | `flags` | Bit 0 (1): green cache hit. Bit 1 (2): green is flat because no arrows were found. Bit 2 (4): water-hole lift included. Bit 3 (8): tail cache hit. |
| 8 | uint32 | `seq` | Echo of the request `seq`. |
| 12 | float32 | `plate_half_mm` | Half the plate side. |
| 16 | float32 | `lift_mm` | 0 or 2. |
| 20 | float32 | `base_mm` | Base thickness used. |
| 24 | float32 | `total_ms` | Server compute time. |
| 28 | float32 | `green_ms` | Time spent on the green (about 0 on a cache hit; includes the solve on a miss). |
| 32 | float32 | `fringe_ms` | Time spent on fringe and all other parts. |
| 36 | uint16 | `n_parts` | Rows in the part table. |
| 38 | uint16 | `n_markers` | Rows in the marker table. |

### 4.2 Part table row, 36 bytes (`n_parts` rows, right after the header)

| Offset | Type | Name | Meaning |
| --- | --- | --- | --- |
| 0 | uint8 | `kind` | 1 green, 2 fringe, 3 bunker, 4 water, 5 boulders |
| 1 | uint8 | `index` | 1-based within its kind (bunker 1, bunker 2 ... match the order of `trap` polygons in the snapshot; water and boulders likewise). Green and fringe are always 1. |
| 2 | uint16 | `nx` | Nodes along X |
| 4 | uint16 | `ny` | Nodes along Y |
| 6 | uint16 | reserved | 0 |
| 8 | float32 | `xmin` | World X of column 0 |
| 12 | float32 | `ymin` | World Y of row 0 |
| 16 | float32 | `xmax` | World X of the last column |
| 20 | float32 | `ymax` | World Y of the last row |
| 24 | float32 | `zmin` | Minimum height over mask=1 nodes |
| 28 | float32 | `zmax` | Maximum height over mask=1 nodes |
| 32 | uint32 | `data_offset` | Byte offset of this part's data, **relative to the start of the data blob** |

Parts that fail to build (for example a bunker whose outline collapses) are simply absent, as in Generate. Never assume a fixed part count.

### 4.3 Marker table row, 20 bytes (`n_markers` rows, after the part table)

| Offset | Type | Name | Meaning |
| --- | --- | --- | --- |
| 0 | uint8 | `kind` | 1 tee, 2 flag |
| 1..3 | uint8 x3 | padding | 0 |
| 4 | float32 | `x` | World X |
| 8 | float32 | `y` | World Y |
| 12 | float32 | `z` | Surface height at the marker (lift included), where to put the base of the pin |
| 16 | float32 | `radius` | Hole radius in mm (tee 2.78, flag 1.5) |

The tee marker is present only if the snapshot has `tee_hole`. The flag marker is at the green's bounding-box centre plus the flag offset.

### 4.4 Data blob

Starts at byte `40 + 36*n_parts + 20*n_markers`. For each part, at `blob_start + data_offset`:

```
float32[ny*nx]  heights   (nx*ny*4 bytes)
uint8  [ny*nx]  mask      (nx*ny bytes)
padding to a multiple of 4 bytes
```

Alignment: `data_offset` is always a multiple of 4 and the heights start there, so `new Float32Array(buf, blob_start + data_offset, nx*ny)` works directly. The mask is a plain `new Uint8Array(buf, blob_start + data_offset + 4*nx*ny, nx*ny)`. Total length = `blob_start + sum(round_up_4(5*nx*ny))`.

### 4.5 Per-part specifics

| Part | Grid | Mask meaning | Filler where mask = 0 |
| --- | --- | --- | --- |
| Green (1) | 200 x 200 (the generator's own grid), bounding box of the green. Row 0 = bottom (the server flips the image's top-down order for you). | Node inside the green outline | The part's minimum |
| Fringe (2) | `fringeRes` x `fringeRes` (96 by default) over the whole plate, `xmin..xmax = ±plate_half_mm` | 1 only where the fringe surface exists: outside the green, bunkers, water and boulders-ring cut-outs (the same one-cell margin Generate uses) | The continued fringe surface (the height the fringe would have under a bunker or under the green). Useful for sampling "the fringe under the cursor"; do not draw it. |
| Bunker (3) | Per bunker: its own bounding box, about 1 mm spacing, 8..64 nodes per side | Node within one grid step of the bunker outline | Floor function value (finite) |
| Water (4) | Same scheme as bunkers; every node of the grid has the same height (flat slab) | As bunkers | The same flat value |
| Boulders (5) | Same scheme; flat. With Include boundary region this is the 5 mm ring around the water (annulus), so the mask has a hole where the water is | As bunkers | The same flat value |

Bunker heights are the **mean** of the raked sand surface (Generate adds a +/-0.5 mm rake on top; the preview omits the rake). Bunker rim is 2 mm below the fringe.

## 5. HTTP errors

All errors are JSON `{"status":"error","code":...,"msg":...}`, `Cache-Control: no-store`. Show them quietly in the pane, not in the shared Error dialog.

| HTTP | `code` | When |
| --- | --- | --- |
| 400 | `bad_request` | Body is not JSON; `snapshot` missing or not an object, or `polygons` missing; `seq` not an integer in range; `fringeRes` out of range; `greenMode` unknown |
| 400 | `no_green` | No polygon of type `green` |
| 404 | `image_not_found` | `image` / `imageCourse` do not resolve to a file |
| 409 | `green_cache_miss` | `greenMode:"cachedOnly"` and the green must be solved first |
| 503 | `busy` | A Generate run is in progress. Keep the last good surface, retry after Generate finishes |
| 500 | `internal_error` | Unexpected server error (the msg has the text). Keep the last good surface |

A failed preview must never disturb painting or autosave; just leave the previous surface on screen.

## 6. What triggers the slow path, and how to use it

The green is not drawn from cells: it comes from the arrows in the heat-map picture. The server caches the **raw** least-squares field (not the finished heights) in memory.

- **Cache key**: the heat-map image identity (path, size, modified time) plus the **green outline** (after `greenScale` and the spline smoothing). Nothing else.
- **Slow path (cache miss)**: the first preview of a project, or any change to the green outline or `greenScale`, or a different image. It re-detects arrows and re-solves: measured below, about 2.6 to 2.7 seconds on this Mac. The result is cached (6 entries, least recently used out).
- **Not slow** (cache hit, all of these reuse the cached raw field): painting cells, Slope, grid mode or resolution, moving or editing a bunker, water, boulders, tee, flag offset, Elevation range, Z scale, Base thickness, Smooth versus Terraced, toggling Include boundary region. For Elevation range, Z scale and Base thickness the server re-runs the cheap tail (soften, rescale, slope limit, Z scale) each time, because the slope limiter works in absolute millimetres and is not scale-proportional. Do not rescale the cached green yourself.
- **Recommended client behaviour**:
  1. While the user drags a green control point, send nothing for the green (or send `"greenMode":"cachedOnly"`, which fails fast with 409 and costs about nothing). Keep showing the old green dimmed.
  2. On release, send one `"greenMode":"auto"` request. Expect a few seconds. Latest-seq-wins applies as usual.
  3. Everything else can use `"auto"` freely: after the first solve it is a cache hit.
- A snapshot with **no arrows detected** (blank or arrow-less picture) is not an error: the green is flat (`flags & 2`) at 1.5 mm (5 mm on a water hole; plus the 2 mm lift).

## 7. Smooth versus Terraced (client only)

Green heights arrive smooth. For terraced, replicate Generate's quantiser on the green's mask=1 nodes. With `zmin`, `zmax` from the part table (lift cancels out) and `contourStep` from the editor:

```
range  = zmax - zmin
levels = max(1, round(range / contourStep))      // if contourStep > 0, else use 27 levels: step = range / 27
step   = range / levels
z'     = round((z - zmin) / step) * step + zmin
```

The fringe is always smooth (never terraced) in the print, so leave it alone.

## 8. Not included (by decision)

Rake texture, grass, engraving, seam polish, the median and spike filters, seam snapping, triangulation and boolean hole cuts. Consequences you will see: a thin visual gap between the green and the fringe outline; within about 2 mm of the green the fringe can differ from the print by up to about 4 mm on the steepest banks (Generate snaps that ring onto the green rim); the tee and flag holes are markers only.

## 9. Limits and cost

- One preview computes at a time on the server (a lock; later requests queue). Send at most one in flight, latest wins.
- Typical response size: about 260 KB (green 200x200 = 200 KB, fringe 96x96 = 46 KB, bunkers 8 KB each).
- Latency measured on this Mac (warm green cache, Flask test client, median of 6; design target 60 to 150 ms): 20x20 cell edit 53 ms, Elevation-range/Z-scale change 114 ms; 40x40 cell edit 135 ms, Elevation-range/Z-scale change 218 ms (misses the band); cold first request (slow path) about 2.6 to 2.7 s. Reproduce with `pytest -s app/tests/test_preview_geometry_v634.py -k l1`.
- `fringeRes` 48 is roughly 2x faster than 96 for the TPS evaluation; use it during drags.

## 10. Reference decoder

`preview_geometry.decode_preview(bytes)` (Python) is the executable spec of section 4 and is what the tests use. Constants (`WIRE_MAGIC`, `KIND_*`, `FLAG_*`, `HEADER_FIELDS`, `PART_FIELDS`, `MARKER_FIELDS`) live in `app/preview_geometry.py`. If the client needs them in JS, expose them from one JS constants block, not as repeated literals.
