# Boundary Editor v6.33 - Parameter Guide

> **Version badge: Boundary Editor v6.33 (Mode 2).** Prepared by Topo. Documentation only; no code was changed.
> Written for Thomas and Jim: what each control on the page does to the printed 3MF, in plain English.

**How to read this guide.**
- "Applied at" uses the step numbers of Gemma's Generate flowchart (`generate_algorithm_v6.31.md`, steps 1-26). I checked the order against the v6.33 code: **the pipeline order did not change between v6.31 and v6.33.** Only the base-thickness handling inside step 8 changed (see Base thickness). Where Gemma's numbering does not cover something cleanly, the caveat says so.
- "Code name" lines are for developers only.
- The 3MF is built from the **slope arrows in the heat-map image** (they shape the green) plus everything you draw and set on the page. The print is always 171.45 mm (6.75 in) on its longest side; that size is fixed and is not a setting.
- Generate first autosaves the project, then the server builds the model from that saved project. So the values on screen are the values used (see the "Settings that do nothing" section).

---

## Print size and base

### Source Image
**Applied at:** Step 8 (Load EGM and heat-map image), also Step 9 (Detect slope arrows)
**Default:** none; chosen once in the New Project dialog
The heat-map picture you pick when you create the project. Its longer side is stretched to the 171.45 mm print width, so every outline, cell and hole you place scales with it. Its dark slope arrows are what the program turns into the shape of the green. A cleaner picture with clear arrows gives a cleaner green.
**Caveat:** Not an Options field and cannot be changed after the project exists. If the picture contains no readable arrows, the green is printed flat (see "Settings that do nothing or get overridden").
**Code name:** `image` / `imageSize`

### Base thickness (mm)
**Applied at:** Step 8 (Load EGM; the value is resolved here), then used at Step 12 (Green meshes), Step 13 (Fringe mesh) and Step 17 (Bunkers)
**Default:** 1.5 mm (field minimum 0.1)
Sets the height of the lowest point of the green: the green is stretched between this height and this height plus the Elevation range. Raising it lifts the whole green surface and thickens the solid body underneath; lowering it makes a thinner part. It is also the starting point that Z scale multiplies from, and the lowest a bunker floor may go.
**Caveat:** Since v6.33 the value is worked out fresh on every Generate: an empty, zero, negative or invalid entry means 1.5 mm, and it no longer leaks into the next run (older versions carried the previous run's value forward). The bunker-floor minimum now follows it too. The fringe has its own separate 1.0 mm minimum thickness that does not follow this field.
**Code name:** `baseThicknessMm`

---

## Green surface

### Green outline (purple polygon)
**Applied at:** Step 8 (Load EGM, builds the smooth boundary), also Step 9 (arrows only count inside it), Step 12 (green mesh outline), Step 13 (fringe cut-out)
**Default:** one required polygon, auto-detected when the project is created; drag its control points in Boundary Editing
This is the edge of the green. It decides which arrows are used, the outline of the green piece, and the hole cut in the fringe where the green sits. The outline is smoothed into a flowing curve when printed, so small kinks you draw are rounded off.
**Caveat:** Arrows whose centre lies right on the edge (within about 3 image pixels) are discarded as likely labels. The slope itself comes from the arrows in the image, not from the outline.
**Code name:** polygon of type `green`

### Green style
**Applied at:** Step 12 (Green meshes; both versions are built), chosen at Step 20 (Assemble scene), also Step 16 (Seam polish snaps to the chosen one)
**Default:** Terraced (choices: Terraced, Smooth)
Smooth gives a continuous, flowing green. Terraced turns the same shape into flat steps, like a contour model you can feel with a fingertip. Only the chosen version goes into the 3MF.
**Caveat:** Both versions are always computed; the choice only decides which one ships.
**Code name:** `greenStyle`

### Contour step (mm)
**Applied at:** Step 12 (Green meshes, terraced version)
**Default:** 0.5 mm (minimum 0.1)
The height of each step on a terraced green. Smaller numbers give more, finer steps and a surface closer to smooth; larger numbers give fewer, chunkier terraces.
**Caveat:** Only matters when Green style is Terraced. The step is measured on the final height range (after Elevation range, the slope limiter and Z scale), and is nudged slightly so a whole number of steps fits exactly. A value of 0 or empty falls back to a built-in number of levels instead.
**Code name:** `contourStep`

### Elevation range (mm)
**Applied at:** Step 12 (Green meshes, height conversion), also Step 13 (Fringe mesh uses the same heights)
**Default:** 14.5 mm in the editor (minimum 0.1); if emptied, the program falls back to 20.09 mm
The total height difference between the lowest and highest point of the green. It is the main "how dramatic is the green" control: turn it up for steeper, more pronounced slopes, down for a gentler green. The lowest point sits at Base thickness; the highest at Base thickness plus this value.
**Caveat:** A slope limiter then caps how steeply neighbouring spots may rise, so very steep results can come out smaller than this number. If the image has no readable arrows the green is flat and this setting does nothing.
**Code name:** `elevationRange`

### Z scale x
**Applied at:** Step 12 (Green meshes), also Step 13 (Fringe mesh)
**Default:** 1.0 (allowed 0.5 to 5.0)
Multiplies the height of everything above the base on both the green and the fringe. 2.0 makes all the hills and valleys twice as tall without changing the footprint; 0.5 flattens them by half. Bunkers and water follow the fringe, so their height changes too.
**Caveat:** The server clamps values to 0.5-5.0. It is applied after the slope limiter, so it can exceed the limiter's slope. Terraced steps are cut after scaling.
**Code name:** `zScale`

### Green scale
**Applied at:** Step 8 (Load EGM, when the green outline is prepared)
**Default:** 1.0065 (field minimum 0.5; empty or 0 falls back to 1.0065)
Makes the green piece slightly larger or smaller in the flat directions only, around its own centre. The default is about 0.65% larger and exists so the green fits snugly into its cut-out in the fringe. A bigger number makes the green overhang its hole; a smaller one leaves a gap.
**Caveat:** Does not move the fringe cut-out, bunkers or water, so it changes the fit between green and fringe. Because a typed 0 reverts to the default, exactly 0 cannot be chosen. Leave at the default unless you are tuning fit.
**Code name:** `greenScale`

---

## Fringe, grid cells and grass

The fringe is the surrounding ground. Its shape comes from the height of the green's rim, extended outward, then adjusted by the cells you paint. With no painted cells the fringe is simply the green's edge height carried out to the frame. The "Cap fringe at frame height" checkbox lives here on the page but currently has no effect; see the "Settings that do nothing" section.

### Resolution
**Applied at:** Step 13 (Fringe mesh, the cell grid), also Step 17 (Bunkers, which are shaped by cells)
**Default:** 20x20 (choices: 20x20, 40x40)
Number of painting cells across the plate. 20x20 gives cells about 8.5 mm square; 40x40 gives about 4.3 mm squares for finer sculpting of the fringe and bunker floors.
**Caveat:** Switching resolution erases every painted cell (the page asks first).
**Code name:** `gridResolution`

### Grid mode
**Applied at:** Step 13 (Fringe mesh), also Step 17 (Bunkers)
**Default:** Delta (choices: Delta, Absolute, Off)
Delta: a painted number is added to the natural fringe height at that cell (raise or lower by that many mm). Absolute: a painted number replaces the natural height with that exact height in mm. Off: all painted cells are ignored for this print (the values stay saved so you can switch back).
**Caveat:** Off ignores cells for the fringe and for bunkers. Changing between Delta and Absolute reinterprets the same numbers, so repaint or check them. Painted values are clamped by the server: Delta to plus or minus 20 mm, Absolute to 0-30 mm, and the resulting fringe is never thinner than 1.0 mm.
**Code name:** `gridMode`

### Z-Painting (brush palette, Eraser, 2-brush ramp)
**Applied at:** Step 13 (Fringe mesh: cells become the fringe shape), also Step 17 (Bunkers: cells fully inside a bunker shape its floor)
**Default:** no cells set. Palette swatches run in 0.5 mm steps (Delta -15 to +15, Absolute 0 to 30); you can also click a palette number and type any value, stored to 0.01 mm
This is your direct sculpting tool. Each painted cell raises or lowers the ground around it, and the program blends smoothly between cells so you get rolling terrain, not square steps. Dragging with two brushes selected fills the path between them with a smooth ramp (in 0.25 mm steps). Holding Shift keeps a stroke on a straight row or column. The Eraser empties a cell. A painted 0 is a real value; an erased cell is "not set".
**Caveat:** Does not change the green; the green comes only from the arrows. Cells that sit **fully inside a bunker** belong to that bunker and stop shaping the fringe. Cells only partly in a bunker still shape the fringe. Cells right next to the green are blended toward the green's rim height over a very short distance (about a quarter of a cell).
**Code name:** `gridCellHeights`

### Slope (S) tool
**Applied at:** same as Z-Painting: Step 13 (Fringe mesh), also Step 17 (Bunkers)
**Default:** none; press S (or Shift+S) while in Z-Painting
Draw one boundary line with one brush, then a second line with another brush, and the area between them is filled with cells grading smoothly from the first value to the second in 0.1 mm steps. It is the quick way to build a ramp, a tilted lawn or a berm. It writes ordinary painted cells, so it behaves exactly like Z-Painting afterwards.
**Caveat:** v6.33 made Shift+S work as well as S. Esc cancels. It is one undo step. The "Show Slope prompts" option (Options) only controls whether the instruction pop-ups appear; it does not change the model.
**Code name:** `gridCellHeights` (written by the slope command)

### Grass amplitude (mm)
**Applied at:** Step 13 (Fringe mesh, grass texture)
**Default:** 0.5 mm (minimum 0)
Height of the tiny grass-blade bumps on the top of the fringe. Higher means shaggier, more visible texture; 0 gives a perfectly smooth fringe. Each blade is varied randomly by about half its height so it does not look machine-made.
**Caveat:** The fringe only. The green is never grass-textured (the v6.33 tooltip now says this). Bumps are kept away from the edges of the green, bunker and water cut-outs (about 0.3 mm) so those seams stay clean. The pattern is repeatable: the same settings give the same grass.
**Code name:** `grassAmplitude`

### Grass spacing (mm)
**Applied at:** Step 13 (Fringe mesh, grass texture)
**Default:** 1.0 mm (field minimum 1.0)
Centre-to-centre distance between grass blades. Smaller is denser and finer; larger is sparser and coarser.
**Caveat:** 1.0 mm is also the pipeline's floor; any smaller number is raised to 1.0 mm. The editor default and minimum were changed to 1.0 in v6.33 so the field no longer shows a number that is silently overridden. A project saved earlier with a smaller value (such as 0.05) still loads that number but prints at 1.0 mm.
**Code name:** `grassSpacing`

### Include Fringe Without Grass
**Applied at:** Step 13 (Fringe mesh, the second smooth build), also Step 20 (Assemble scene)
**Default:** unchecked
Adds a second plate to the 3MF holding a smooth, grass-free copy of the fringe so you can compare grass and no grass in the same file. Plate 1 always has grass.
**Caveat:** Generate takes longer because the fringe is built twice. The extra piece is not engraved with the underside text. It is read from the checkbox at click time.
**Code name:** `includeFringeWithoutGrass`

---

## Bunkers

### Add Trap (red polygons)
**Applied at:** Step 13 (Fringe mesh, carves the bunker-shaped hole), then Step 17 (Bunkers), also Step 14 (water-hole lift) and Step 21 (not engraved)
**Default:** none; each click adds one polygon, shaped by dragging its control points
Each red polygon becomes a separate sand-coloured bunker body fitted into a matching hole in the fringe. The sand surface sits 2 mm below the surrounding fringe at the rim, then dips or rises inside according to any cells you painted fully inside it. The top is covered in a raked-sand ridge texture about 1 mm peak to valley.
**Caveat:** With no painted cells inside, the floor is not flat: it tilts along the downhill direction of the surrounding fringe, 2 mm below the fringe at the rim. (Gemma's narrative says "1 mm below the fringe"; the code uses 2 mm.) The floor is kept above a minimum height that follows Base thickness. If the rake texture cannot be built cleanly, the bunker ships as a plain smooth slab and a warning appears; a bunker is never dropped. On a hole with water, bunkers are lifted 2 mm along with the green and fringe.
**Code name:** polygons of type `trap`

### Cells fully inside a bunker (Z-Painting over a bunker)
**Applied at:** Step 17 (Bunkers, floor shape), also Step 13 (those cells are removed from the fringe)
**Default:** none
Paint cells that lie completely within a bunker's outline to sculpt its floor: in Delta mode the numbers are added to the bunker's natural level, in Absolute mode they are the literal floor heights. A pocket, a ridge or a tilted bunker are all possible. The floor blends smoothly from the rim into the cell-shaped surface over about 1.5 cells.
**Caveat:** Only cells whose whole square is inside the outline count. Grid mode Off disables this. If a bunker has no such cells it uses the tilted default floor described above.
**Code name:** `gridCellHeights` (ownership rule)

---

## Water and boulders

### Add Water (yellow polygons)
**Applied at:** Step 13 (Fringe mesh, cut-out), Step 14 (Water on this hole? lift), Step 18 (Water)
**Default:** none
Each yellow polygon becomes a flat water slab with a matching hole in the fringe. Its top is set to the lowest fringe height found under its outline, so water never rises above its banks. It has a smooth, flat top (the ripple texture is switched off).
**Caveat:** Having **any** water polygon on the hole makes the green, fringe and bunkers rise 2 mm (extra base under them) while the water is not lifted, so the water ends up as a basin about 2 mm below the lifted surroundings. With no arrows on a water hole, the flat green is set 5 mm high to clear the water.
**Code name:** polygons of type `water`

### Include boundary region
**Applied at:** Step 8 (Load EGM, derives the ring), then Step 13 (Fringe mesh, ring hole), Step 18 (Water, shrunk) and Step 19 (Boulders)
**Default:** unchecked
When ticked, each water polygon is shrunk inward by 5 mm and a 5 mm ring of "boulders" is printed in the gap around it (its own piece and filament). Use it to get a rocky edge around ponds without drawing it.
**Caveat:** It replaces any boulders polygons already in the project. Water too small to shrink by 5 mm is left unchanged. There is no button to draw boulders by hand; they only exist from this checkbox or in older projects. The ring's height comes from the lowest fringe height beneath it. It is read from the checkbox at click time.
**Code name:** `includeBoundaryRegion`

---

## Tee and flag

### Add T Hole / Remove T Hole
**Applied at:** Step 15 (Tee marker on green?), the hole is drilled in the fringe right after
**Default:** none until added; the marker starts 40 mm from the left and 40 mm down from the top of the print and can be dragged
Punches a round tee hole (about 5.6 mm wide, sized for a real tee) through the fringe, with a thin reinforcing collar around it. Drag the marker anywhere on the fringe.
**Caveat:** If the collar would touch the green, **Generate stops with an error and writes no 3MF** until you move the marker clear of the green. Tee diameter and collar size are fixed in code. The hole is drilled in the fringe only; I did not check what happens if you drop the marker inside a bunker or water polygon.
**Code name:** `tee_hole`

### Flag offset - X offset (mm)
**Applied at:** Step 12 (Green meshes, flag hole)
**Default:** 0 (can be negative)
Moves the flag-pin hole sideways from the centre of the green: positive is right, negative is left. At 0 the 3 mm hole sits at the middle of the green.
**Caveat:** Measured from the middle of the green piece's bounding box, not the middle of its shape, so on an oddly shaped green the "centre" may sit near an edge. The hole size (3 mm) is fixed. The same hole is cut in both the smooth and terraced versions.
**Code name:** `flagOffsetXMm`

### Flag offset - Y offset (mm)
**Applied at:** Step 12 (Green meshes, flag hole)
**Default:** 0 (can be negative)
Moves the flag-pin hole up (positive) or down (negative) in the view you see in the slicer.
**Caveat:** Same as X offset. Nothing stops you from placing the hole off the green; I did not find a check for that and have not tested what happens.
**Code name:** `flagOffsetYMm`

---

## Output and slicer

### Golf Course
**Applied at:** Step 2 (Pre-check), Step 6 (Locate EGM), Step 20 (file name), Step 21 (Engrave underside)
**Default:** required (New Project dialog)
Names the course folder the 3MF is saved into and appears in the file name and in the label engraved on the underside of the fringe (about 8 pt bold lettering, shrunk to fit if long).
**Caveat:** Generate is blocked until it is set.
**Code name:** `course`

### Hole Number
**Applied at:** Step 2 (Pre-check), Step 20 (file name), Step 21 (Engrave underside)
**Default:** required (New Project dialog)
Appears in the output file name (padded to two digits when numeric) and in the engraved underside label.
**Caveat:** Each Generate also adds a short random ID to the file name and engraves its first 8 characters on the underside of the green and the fringe, so every print is traceable. This is automatic and cannot be changed.
**Code name:** `hole`

### Open in default slicer
**Applied at:** Step 24 (Open in slicer)
**Default:** unchecked
After a successful Generate, hands the finished 3MF to your computer's default 3MF app. It does not change the model.
**Caveat:** If opening fails, you get a warning, not an error, and the 3MF is still saved.
**Code name:** `open_in_slicer`

### Generate
**Applied at:** Steps 1-4 (Click, pre-check, autosave, send), with the whole pipeline running behind it (Steps 5-26)
**Default:** disabled until a course, a hole number and at least one polygon exist; shortcut G or Cmd/Ctrl+G
Saves the project and builds the 3MF. The Options and drawn shapes above are the entire input.
**Caveat:** If the autosave fails, Generate stops with an error and builds nothing. Missing software packages, a tee on the green, or a model that fails the final watertight check also stop it with an error.
**Code name:** `generateSTL`

---

## Settings that do nothing or get overridden

- **Fringe edge height (mm)** - Removed from the page in v6.33. It had been ignored by the generator for a long time (the fringe now simply follows the green's edge height out to the frame). Older projects may still carry the value in their file; it is loaded and ignored. To change the fringe's height, use Z-Painting cells.
- **Cap fringe at frame height (checkbox)** - Greyed out in v6.33 and tooltip explains why. The cap that would clip the fringe (and bunkers) to 9 mm near the edge is switched off in the program, so the checkbox has no effect whether ticked or not. The water-hole 2 mm lift still happens. To limit height near the edge, lower the cells there with Z-Painting.
- **Grass spacing below 1.0 mm** - Raised to 1.0 mm. v6.33 made 1.0 the field's default and minimum; only older saved projects can still hold a smaller number.
- **Grass on the green** - Never applied. Grass amplitude and spacing change only the fringe; the green looks different only through Smooth vs Terraced.
- **Z-painted cells do not shape the green** - The green is built only from the arrows in the heat-map image. Painting cells under or near the green changes the fringe around it, and at most blends a thin band at the seam. To change the green, change Elevation range, Z scale, or the image arrows.
- **Cells fully inside a bunker belong to the bunker** - They shape the bunker floor and are removed from the fringe calculation. Cells only partly inside a bunker still shape the fringe.
- **Grid mode Off** - All painted cells are ignored for both fringe and bunkers (values are kept). Bunkers then use their default tilted floor.
- **Contour step** - Only used when Green style is Terraced; ignored for Smooth.
- **No slope arrows in the image** - The green is printed flat at a fixed height (the base thickness on dry holes, 5 mm on water holes). Elevation range and Contour step then do nothing visible, and Z scale only acts if the flat height is above the base. To get relief, use a heat map with arrows.
- **Generate uses the autosaved project file** - Generate saves first and then the server reads that file, so the on-screen Options are what you get. The three checkboxes (Include boundary region, Include Fringe Without Grass, Cap fringe) and Open in default slicer are also sent directly at click time. Two browser tabs on the same project can overwrite each other's autosave, so keep one open.
- **Base thickness left empty or 0** - Uses 1.5 mm (and from v6.33 no longer inherits the previous run's value).
- **Green scale left empty or 0** - Uses 1.0065.
- **Elevation range left empty or 0** - Uses the program's 20.09 mm fallback, not the editor's 14.5 default.
- **Z scale outside 0.5-5.0** - Clamped to that range by the server.
- **Painted values outside the limits** - Delta values beyond plus or minus 20 mm and Absolute values outside 0-30 mm are clamped. The fringe is never thinner than 1.0 mm.
- **Show Slope prompts, Image (Original / Degridded / Hide), Color cells by height** - View or convenience only; they never change the 3MF. Generate always uses the original heat-map picture saved inside the project.
- **Boulders** - There is no draw button; they come only from Include boundary region (or very old projects).
- **Tee diameter, collar, flag-hole size, engraving text size, grass shape, bunker rake pattern** - Fixed in the program; not adjustable from the page.

---

## Quick reference

Page order, top to bottom.

| Page field | Section | Applied at step(s) | One-line effect |
|---|---|---|---|
| Source Image (New Project) | Print size and base | 8, 9 | Sets print scale and supplies the slope arrows that shape the green |
| Golf Course (New Project) | Output and slicer | 2, 6, 20, 21 | Output folder, file name and engraved label |
| Hole Number (New Project) | Output and slicer | 2, 20, 21 | File name and engraved label |
| Green style | Green surface | 12, 20 (16) | Smooth or terraced green ships |
| Contour step (mm) | Green surface | 12 | Height of each terrace (Terraced only) |
| Grass amplitude (mm) | Fringe, grid cells and grass | 13 | Height of fringe grass bumps; 0 = smooth |
| Grass spacing (mm) | Fringe, grid cells and grass | 13 | Distance between grass blades; floor 1.0 mm |
| Elevation range (mm) | Green surface | 12, 13 | Total height difference across the green |
| Z scale x | Green surface | 12, 13 | Multiplies relief above the base on green and fringe |
| Green scale | Green surface | 8 | Slightly enlarges or shrinks the green piece (fit) |
| Base thickness (mm) | Print size and base | 8, then 12, 13, 17 | Height of the lowest green point and the solid base |
| Include boundary region | Water and boulders | 8, 13, 18, 19 | 5 mm boulders ring around water |
| Cap fringe at frame height | Settings that do nothing | none (disabled) | No effect; frame cap is off in code |
| Include Fringe Without Grass | Fringe, grid cells and grass | 13, 20 | Adds a smooth, grass-free fringe on plate 2 |
| Flag offset - X offset (mm) | Tee and flag | 12 | Moves the flag hole left or right |
| Flag offset - Y offset (mm) | Tee and flag | 12 | Moves the flag hole up or down |
| Add Trap | Bunkers | 13, 17 (14) | Adds a raked-sand bunker and its fringe cut-out |
| Add Water | Water and boulders | 13, 14, 18 | Adds a flat water slab; lifts the rest 2 mm |
| Add T Hole / Remove T Hole | Tee and flag | 15 | Tee hole in fringe; error if on the green |
| Green outline (purple polygon) | Green surface | 8, 9, 12, 13 | Edge of the green and its fringe cut-out |
| Open in default slicer | Output and slicer | 24 | Opens the 3MF in your slicer afterwards |
| Generate | Output and slicer | 1-4 (then 5-26) | Saves, then builds the 3MF |
| Grid mode | Fringe, grid cells and grass | 13, 17 | Delta, Absolute or Off for painted cells |
| Resolution | Fringe, grid cells and grass | 13, 17 | 20x20 or 40x40 cell grid |
| Z-Painting (palette, Eraser, ramp) | Fringe, grid cells and grass | 13, 17 | Sculpts the fringe and bunker floors |
| Slope (S) tool | Fringe, grid cells and grass | 13, 17 | Fills a graded ramp between two painted lines |
| Cells fully inside a bunker | Bunkers | 17, 13 | Shapes that bunker's floor instead of the fringe |
