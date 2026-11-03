# Bambu "Conflicts of gcode paths at layer 20" diagnosis (Finn)

File: `Delaveaga (Hole 11.40) [69d372da-...].3mf` (worked on a copy in scratchpad; nothing written to ItWentIn).

## What the file contains
Single plate, 4 objects, each a single part, all build transforms = pure translate (128,128,0), no rotation. No plate 2 in this file (no plate-2 mis-placement).

| Bambu name | our `partnumber` | faces | bounds (mm, centred) | extruder |
|---|---|---|---|---|
| geometry_0 | green_surface | 56,828 | x/y -55..55 / -76..75, z 0..20.5 | 1 |
| geometry_1 | fringe | 852,340 | +-85.2, z 0..21.06 | 2 |
| geometry_2 | trap_1 | 42,790 | z 0..12.7 | 3 |
| geometry_3 | trap_2 | **160** | z 0..4.8 | 3 |

Naming: the generator writes `name="geometry_N"` (trimesh default) in the model and in `model_settings.config`. Our `partnumber="green_surface"` etc. lives only on the build `<item>`, which Bambu ignores. So Bambu's "geometry_0 <-> geometry_1" is **green vs fringe**. Layer height 0.28, first layer 0.2, so layer 20 = z 5.40-5.68.

## Root cause
Green (geometry_0) and fringe (geometry_1) are separate objects whose solids overlap in XY by a **constant 20.54 mm^2 sliver** (perimeter 41 mm, bbox x -31.8..-24.2, y 58.0..65.6; erodes to zero at 0.5 mm so it is <= ~1 mm thick, ~20 mm long) on the green's outer boundary. It exists for every Z from 0 up to ~6.0 (layers 1-21), and vanishes at layer 22 where the fringe top ends. Bambu reports one layer (20). Other pairs: green/trap_1 0.0, fringe/trap_1 0.09 mm^2 (negligible), trap_2 none.
Cause: the fringe's inner cutout does not exactly match the green outline (fringe hole is ~1 mm too small along one arc), so the two meshes interpenetrate and Bambu sees two objects extruding the same spot at the same layer.

## Is it new?
No. Older builds (2026-11-01 08:56, 18:26, 18:39) show the identical 20.54 mm^2 overlap at z = 1, 3, 5.66. It is not caused by v6.23/v6.25 fringe-height changes; it is a long-standing green/fringe cutout mismatch (the older 08:56 build also had a 5th mesh, a full-footprint fringe copy, overlapping the fringe by 15,617 mm^2; that is gone now).
All of those used the same unnamed `geometry_N` objects.

## Separate observation
trap_2 (geometry_3) is **160 faces / 3,784 mm^3** in this build vs 32,810 faces in the Nov 1 builds. Not part of this warning, but it looks like a decimated/degenerate trap mesh; Topo should check whether that is intentional.

## Will the print fail?
Almost certainly not. The conflict is a ~1 mm x 20 mm sliver where two filaments (extruders 1 and 2) both want the same toolpath; the slicer prints both in sequence, so that strip gets double extrusion / slight over-extrusion and possible tiny surface bump, not a failed print. The warning is a safety check, benign here, but it is a real (small) geometry error.

## Recommended fix (for Topo)
1. Preferred: make the fringe inner cutout exactly the green outline (boolean-subtract green from fringe, or build fringe hole from the same polygon, with 0 offset), so the objects touch but do not overlap. Optionally leave 0.0-0.05 mm gap.
2. Alternatively subtract fringe from green or clip the green outline inward by ~1 mm along that arc.
3. Better structural option: emit green+fringe+traps as **parts of one Bambu object** (`<object>` with `<part>` per colour/extruder in model_settings.config). Then Bambu never runs the inter-object path-conflict check, and overlaps are resolved by part priority.
4. Naming: write meaningful names (`green_surface`, `fringe`, `trap_1`, ...) in the object `name` and `model_settings.config` `<metadata key="name">` so the warning is readable.

Slicer-side: no safe setting silences it; the check is not user-configurable. Cheap workaround is to ignore it. A real fix is the cutout (1) or single-object (3).
