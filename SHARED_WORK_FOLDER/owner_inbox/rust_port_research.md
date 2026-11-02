# Rust Port Experiment: Research Summary (Pax, 2026-11-02)
Full doc: `team/_hiring_research_rust_geometry_dev.md`

## Verdict
Feasible as an experiment, but not a free speedup. Strategy: strangler-fig, CLI-first generator, Python as golden oracle, PyO3/maturin hybrid as fallback.

## Crate mapping
| Python | Rust | Maturity |
|---|---|---|
| numpy | ndarray, nalgebra, glam | A |
| scipy RBF thin-plate spline | hand-written on faer (LU) | Gap (B) |
| shapely booleans | i_overlay (best), geo, clipper2 bindings | A- / B |
| shapely buffer/offset | i_overlay offset, geo-buffer, Clipper2 | B |
| triangle (CDT + quality) | spade (refine), cdt; C bindings | A- (not identical output) |
| trimesh | parry3d, meshopt + hand-written weld/watertight | Gap (B) |
| mesh booleans | manifold3d bindings (only if needed) | B |
| OpenCV / skimage | imageproc + image; opencv-rust for gaps | B (skeletonize etc. = gap) |
| PIL | image | A |
| matplotlib TextPath | ttf-parser, rustybuzz, lyon, kurbo (ship DejaVu TTF) | A |
| 3MF zip/XML | zip + quick-xml hand-written (lib3mf/threemf crates are young, no Bambu metadata) | A / C |
| Flask + Jinja | axum + tower-http + minijinja | A |
| parallelism | rayon | A |

## Top risks
1. TPS RBF parity (no drop-in crate; conditioning and semantics).
2. spade vs Shewchuk Triangle: different meshes, compare by height error not vertices.
3. Offset/buffer drift vs GEOS.
4. trimesh utility gap; no pure-Rust robust mesh booleans.
5. OpenCV/skimage parity (contours, morphology, skeletonize).
6. Bambu 3MF metadata has no crate; needs real Bambu Studio import check.
7. ~10-14k lines of Rust; do spikes first.

## Realistic expectations
- Speed: if time is in numpy/scipy/triangle C code, expect about 1x (0.8-1.5x). Gains of 3-30x only on Python-loop/shapely-churn sections; end-to-end 1.5-5x plausible, 1x if one solve dominates. Profile Python first (py-spy).
- Iteration: small edits slower (debug rebuild 2-15 s, cold release 1-5 min vs instant Python); large refactors safer. Use bacon, cargo check, nextest, opt-level=3 for dev deps.
- Put CARGO_TARGET_DIR on the boot volume (external volume is nosuid/slow).

## Milestones
Profile Python and build corpus; Spike A (3MF writer + golden diff); Spike B (TPS + CDT, mesh-error report); go/no-go with numbers; then axum on 5054.

## Tooling
rustup stable pinned via rust-toolchain.toml, clippy, rustfmt, rust-analyzer; cargo-nextest, bacon, criterion, hyperfine, cargo-flamegraph, cargo-instruments, samply. Release: lto="thin"/fat, codegen-units=1, debug="line-tables-only".

## Recommended tier: opus
Role is numerical-robustness and architecture judgment, and a bad port gives misleading go/no-go data. This is an exception to the Sonnet 5.5 standard; compromise is opus lead plus Sonnet for mechanical follow-on work.
