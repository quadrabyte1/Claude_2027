# Fringe Print Speed - Where the Time Goes and How to Cut It

> Prepared by Finn (3D Print and Slicer Specialist). Analysis only; no code and no original 3MF was modified.
> Subject: `Delaveaga (Hole 11.40) [54cd493e-...].3mf` (Bambu Studio 02.08.02.61, Bambu Lab A1, 0.4 mm nozzle, PLA).
> Per Thomas's update: grass removal is already known (the "Include Fringe Without Grass" option). It gets one line here. **All savings below are measured against the grassless fringe baseline.**

**Method.** I ran the real Bambu Studio slicer headless (CLI) on fringe-only copies of the 3MF and read its time estimate and per-feature times. Estimates are the slicer's own and are usually within 5-10% of the real print; they are **not** stopwatch times. The grassless baseline was simulated by low-pass filtering the grass bumps out of the real fringe mesh (average change 0.08 mm per top vertex), so it is a close stand-in, not the generator's true smooth build. I did not see any printed or visually inspected result, so pillowing and look claims are judgement, not measurement.

---

## 0. The fringe, measured

| Item | Value |
|---|---|
| Plate size | 170.4 x 170.4 mm |
| Height | 0 to 21.0 mm (a full solid slab following the green's rim height) |
| Solid volume | 195 cm3 (about 242 g if 100% solid) |
| Top-surface footprint | about 15,560 mm2 (the green's hole is already cut out) |
| Average thickness | about 12.5 mm |
| Mesh | 428,629 vertices, 857,270 triangles (grass is almost all of this) |
| Embedded settings | 0.28 mm Extra Draft, 2 walls, top 4 / bottom 3 layers, 15% grid infill, monotonic-line top, no ironing, outer/inner/infill speed 200 mm/s, bridge 50 mm/s, filament slot 2 = eSUN PLA+ with **max volumetric speed 16 mm3/s** |

The project already prints at 0.28 mm. Layer height is already at the top of the range, which matters below.

### Slicer estimates (fringe alone)

| Case | Time |
|---|---|
| Fringe with grass (as shipped) | 2.59 h |
| **Grassless baseline (used for all comparisons)** | **2.25 h** (about 82 g) |
| Whole plate, all 4 objects, as shipped | 7.6 h (27,516 s) |

Grass costs about 0.35 h here (travel, gap fill, top-surface path). That is the one line on grass.

---

## 1. Where the time goes (grassless fringe, 2.25 h = 8,094 s)

| Feature | Seconds | Share | Note |
|---|---|---|---|
| Sparse infill (15% grid) | 1,788 | 22% | Biggest single feature |
| Internal solid infill | 1,481 | 18% | The 4 top layers plus the layers under sloped top surfaces, repeated as the top heights change |
| Outer + inner walls | 1,387 | 17% | 2 walls around every contour, including the green, bunker, water and tee cut-outs |
| Bridge | 812 | 10% | Internal bridges over sparse infill under each top shell, at 50 mm/s |
| Travel | 893 | 11% | |
| "Undefined" (unclassified moves) | 876 | 11% | Slicer-internal; tracks travel closely |
| Top surface | 685 | 8% | |
| Bottom surface | 515 | 6% | Layer 1 over 15,500 mm2 at 50 mm/s and 500 mm/s2; fixed floor |
| Start-up gcode | 367 | 5% | Fixed |
| Gap infill | 157 | 2% | |

Evidence for the key claims:

- **The print is flow-limited, not speed-limited.** 200 mm/s x 0.45 mm x 0.28 mm asks for about 25 mm3/s, but the fringe filament is capped at 16 mm3/s. Result: going 0.28 -> 0.32 mm layer height (66 layers instead of 75) saved only 2% (2.25 -> 2.21 h). Time is basically **plastic volume / 16 mm3/s**. So the winners are anything that **removes plastic**, not "bigger layers" or "faster speeds". Raising the cap from 16 to 21 mm3/s saved 7% (2.25 -> 2.09 h).
- **Hollowing is not free.** Setting infill to 0% only saved 0.23 h (2.25 -> 2.02 h) because the Bridge time doubled (812 -> 1,761 s) as every top shell then bridges over air. Lightning at 10% gives a better result (1.95 h) because it lays down support branches only where the top shells need them.
- **Whole-plate context (biggest hidden cost).** The 4-piece plate is 7.6 h but the fringe alone is 2.6 h. The plate carries 119 filament changes, **8,382 s of flush** plus 1,227 s of prime tower, about 2.7 h of pure colour-change overhead, because Bambu prints "by layer" and the pieces interlock at the same spot, so the AMS swaps colours on nearly every layer. Printing the fringe on its own plate (one filament, no tower, no flush) is the largest single saving if the pieces are not currently printed separately. If you already print it alone, ignore this.

---

## 2. Slicer tricks, ranked by time saved vs. visual risk

Savings are measured on the grassless fringe alone (baseline 2.25 h), one change at a time unless noted.

| Rank | Change | Time | Saved | Visual risk for a display piece |
|---|---|---|---|---|
| 1 | Sparse infill 15% grid -> **10% lightning** | 1.95 h | -0.30 h (-13%) | **Low** if top shells stay at 3+ layers. Lightning only builds support where the top shell needs it, so there is no infill pattern show-through when the top is solid. Infill is invisible from outside. |
| 2 | **Top shell layers 4 -> 3** (and top shell thickness 1 -> 0 so layers rule), **bottom 3 -> 2** | 2.10 h | -0.15 h (-7%) | **Low-medium.** 3 layers at 0.28 mm = 0.84 mm solid under the top. With grass (0.5 mm tall bumps) that still covers lightning branches. Do not go to 2 top layers; that is where pillowing and infill show-through start on a bumpy surface. |
| 3 | **Bridge speed 50 -> 100 mm/s** | 2.16 h | -0.09 h; about -0.17 h when combined with lightning | **Low.** Bridges are internal (hidden under the top shell). Only a sagging internal bridge could print rougher, which the top shells cover. |
| 4 | **Walls 2 -> 1** | 2.09 h | -0.16 h (-7%) | **Medium.** Fine on a bookshelf piece, but a single outer wall around thin necks (tee collar, cut-out edges) is fragile and the outer surface of the sides is less crisp. Try on the A/B plate before adopting. |
| 5 | Filament max volumetric speed 16 -> 21 mm3/s (eSUN PLA+ slot) | 2.09 h | -0.16 h (-7%) | **Low** visually, but it is a hotend-capacity question: 21 mm3/s is Bambu PLA Basic's A1 value; eSUN PLA+ may under-extrude (rough or weak layers) at that rate. Drop to 18 if you see it. |
| 6 | Initial layer speed 50 -> 120, first-layer infill 105 -> 200 | 2.23 h | -0.02 h | Medium (adhesion on a 170 mm plate). **Not worth it.** |
| 7 | Layer height 0.28 -> 0.32 mm | 2.21 h | -0.04 h (-2%) | Medium (coarser sides and top). **Not worth it** because the print is flow-limited. |
| - | Variable / adaptive layer height | not run | est. under 3% | Same flow-limit reason as above; skip. |
| - | Reduce crossing walls, reduce infill retraction | 2.26 h | none | None; it adds travel. Leave off. |
| - | Infill 0% (fully hollow) | 2.02 h | -0.23 h | **High risk.** Bridges over air; top shells sag. Not recommended. |
| - | Gyroid 8% | 2.09 h | -0.16 h | Low, but lightning at 10% beats it (1.95 h). |

Already off or no gain: ironing is already off; seam and "only one wall on top surfaces" were not measured (small effect against the volume-limited total). Acceleration is already high (6,000 default, 10,000 travel).

**Combined slicer-only result (rank 1 + 2 + 3):** 2.25 h -> **1.69 h** (-0.56 h, -25%). With the volumetric cap at 21 mm3/s also, an earlier test combination (lightning + 3/2 shells) reached 1.72 h before the bridge change, so expect about 1.55-1.6 h with everything. With walls = 1 and infill 5% on top: **1.37 h (-39%)**.

---

## 3. Model-side changes (generator / Topo work)

| Change | Est. benefit (fringe, on grassless) | Needs code? | Notes |
|---|---|---|---|
| **Lower the solid height of the fringe** (cap or scale the slab, e.g. keep the same surface shape but 60% of the height) | -25% by itself (2.25 -> 1.69 h in my 0.6x-Z proxy); stacks with slicer tricks to 1.31 h | Yes (Topo) | Biggest model-side win, because time scales with plastic volume. My test simply squashed the whole fringe 0.6x, so it also flattened the terrain, a **proxy, not the real design**. The real change is a lower floor of the slab, not less relief. The fringe is a full solid slab from Z=0 up to the green-edge height (up to 21 mm, average 12.5 mm). The green has to match its rim height, so the height can only drop if the green and fringe drop together (lower Base thickness / Z scale / Elevation range are existing user knobs that already do this). |
| **Underside pocket ("hollow slab" with a ribbed or open bottom)** | Uncertain, probably -10% to -20% | Yes (Topo) | Carve a large cavity from below, leaving about 1.5 mm base and about 3 mm walls. Must be tall-and-open from underneath, so the cavity ceiling is a bridge (my 0% infill test shows bridge cost kills most of the gain). Only worth it if the pocket is shaped so its ceiling is shallow-angled or ribbed. The underside also carries the engraved text; keep that area solid. High effort for medium gain. |
| **Do not add more Z-Paint relief than needed** | Variable | No (user choice) | Every mm of height is about 1/12 of the print. Painted peaks that add 5 mm over a large area cost real time. |
| **Cap fringe near the frame edge** (the dead "Cap fringe at frame height" checkbox, 9 mm) | Depends; likely -5% to -15% on high holes | Yes (re-enable cap) | Already built and then switched off in the generator. Flag for Topo. |
| **Lower triangle count for the grassless build** | Zero print time; faster slicing/Generate | Yes | The grass build is 857k triangles. Not a print-time issue. |
| **Grass amplitude / spacing, grass only on top layers** | Part of the 0.35 h grass cost | Mostly existing options | Already known; not analysed further. |
| **Pre-assign a print profile in the 3MF** | Convenience only | Yes (small) | The generator could write the recommended Strength/Speed values into the 3MF so Thomas does not retype them; per-object overrides are supported in `model_settings.config`. |

---

## 4. Ready-to-use Bambu Studio settings (fringe only)

Applies to the **fringe object**. Only fields that differ from the shipped defaults (0.28 mm Extra Draft @BBL A1 as embedded in the 3MF).

### Filament settings (eSUN PLA+ @BBL A1, the filament in slot 2)

Optional, global to the filament (not per-object). Skip it if you see rough extrusion.

1. **Filament tab > Basic > Flow ratio and pressure advance > Max volumetric speed:** 16 -> **18 to 21 mm3/s** (start at 18; 21 saved 7% in the test).

Nothing else changes in the Filament tab.

### Process settings (per-object overrides on the fringe)

**Quality**

- (No changes. Layer height stays at 0.28 mm; going to 0.32 mm saved only 2%.)

**Strength**

1. **Walls > Wall loops:** 2 (keep; optionally try 1 on the A/B plate, see rank 4).
2. **Top/bottom shells > Top shell layers:** 4 -> **3**
3. **Top/bottom shells > Top shell thickness:** 1 -> **0 mm** (so layers rule; otherwise 3 x 0.28 = 0.84 mm gets padded back up to 1 mm, which keeps 4 layers)
4. **Top/bottom shells > Bottom shell layers:** 3 -> **2**
5. **Sparse infill > Sparse infill density:** 15% -> **10%**
6. **Sparse infill > Sparse infill pattern:** Grid -> **Lightning**

**Speed**

1. **Overhang speed > Bridge speed:** 50 -> **100 mm/s**

**Support**

- (No changes.)

**Others**

- (No changes; leave Prime tower off for a single-filament fringe plate.)

### How to apply to the fringe only

1. In the Prepare view, right-click the **fringe** in the object list > **Add settings** > pick **Strength** (check Top shell layers, Top shell thickness, Bottom shell layers, Sparse infill density, Sparse infill pattern) and **Speed** (Bridge speed). Set the values above. This leaves green, bunkers, water and boulders on the global profile.
2. The Max volumetric speed change is a Filament-tab setting, not a per-object one; it affects every part printed in that slot.
3. Best of all: put the fringe on **its own plate** (see section 1), where you can also set these as the plate/project defaults and no prime tower or flush is needed.

---

## 5. Expected savings and A/B test

### Estimates (slicer, fringe alone; stack on top of dropping grass)

| Package | Time | Saving vs. grassless 2.25 h |
|---|---|---|
| Section 4 settings (lightning 10%, 3 top / 2 bottom, bridge 100) | **1.69 h** | **-25% (range -20% to -28%)** |
| Plus walls 1, infill 5%, volumetric cap 21 | 1.37 h | -39% (range -33% to -42%) |
| Section 4 settings **plus the model-side lowered slab (0.6x height proxy)** | 1.31 h | -42% (range -30% to -45%) |
| Same package **with grass**, for reference (2.59 h shipped) | 2.03 h | -22% vs. shipped grass |

The "with grass" row is the settings-only package on the real grass mesh; the shipped grass time is 2.59 h.

Real-world error: assume the slicer is optimistic by 5-10% on a high-travel print like this (many short moves); report the saving as a percentage, not hours.

### Suggested A/B test

Use the **"Include Fringe Without Grass"** option so both plates already exist, then compare like with like:

1. **Plate A (control):** grassless fringe, shipped profile (0.28 mm, 2 walls, 4 top / 3 bottom, 15% grid). Note the real print time.
2. **Plate B (candidate):** the same grassless fringe with the section-4 settings. Expect about 25% less.
3. Inspect plate B for: pillowing or shiny/dull patches on large flat top areas, any infill pattern visible through the top, rough sagging at the underside of bridges, and wobbly or thin walls around the tee collar. Press a thumb on the middle of the largest flat area; it should feel solid, not drum-like.
4. If B passes, repeat with the grass fringe. Watch for the grass tips: 3 top layers is the minimum for a 0.5 mm bump height, so if any lightning branch shadows through, go back to 4 top layers (that costs about 0.05 h).
5. Optional round 2: B plus walls 1 and infill 5%, to see if the extra 14 points of saving are worth the fragility.

### Top 5 recommendations

1. Print the fringe on its own plate (kills about 2.7 h of flush and tower overhead on the 4-piece plate).
2. Sparse infill 15% grid -> 10% lightning (-13%).
3. Top shell layers 4 -> 3 with top shell thickness 0, bottom 3 -> 2 (-7%).
4. Bridge speed 50 -> 100 mm/s (-4%, bigger with lightning).
5. Model-side: lower the fringe's solid slab height / re-enable the frame-edge height cap (about -25%, needs Topo).

Tests run (all CLI estimates, scratch files at `/private/tmp/claude-501/-Volumes-GIT-Claude-2027-SHARED-WORK-FOLDER/77d32619-f239-44bc-b530-b408948801bc/scratchpad/`; `results.txt` has every run).
