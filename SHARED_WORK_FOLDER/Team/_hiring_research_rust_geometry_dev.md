# Hiring Research: Senior Rust Developer (Computational Geometry / Mesh Processing / 3D-Printing Pipelines)

Researcher: Pax | Date: 2026-11-02 | Dashboard task 728
Evidence note: web search was thin (two queries; results confirmed 3MF crate landscape only). The rest is from established knowledge of the Rust ecosystem (to mid-2026) and is flagged "verify" where version/maturity may have moved. The new hire should do a crates.io/GitHub-activity check as step 1 of any spike.

## 1. The role: what senior Rust geometry developers actually do

Typical employers: CAD/CAM kernels (Fornjot, truck, Bambu/Prusa-adjacent tooling, Slicer startups), GIS (georust/geo), robotics/sim (parry/rapier, Dimforge), game-engine tooling (Bevy), CNC/toolpath firms.

Core skills
- Ownership/borrowing fluency, iterators, traits and generics (numeric traits over f32/f64), error handling (thiserror/anyhow), unsafe-free numerics, feature flags, workspace layout.
- Numerical robustness: knowing that floating-point predicates (orientation, in-circle) fail on near-degenerate input; using adaptive/exact predicates (the `robust` crate, used by spade and geo); epsilon policy; snapping/quantising coordinates (integer grids as i_overlay does); watertightness and manifoldness invariants; winding/orientation conventions.
- Data-structure choice: indexed triangle meshes, half-edge vs. flat index buffers, structure-of-arrays for cache locality, spatial indices (rstar, BVH via parry/bvh).
- Linear algebra: nalgebra (small fixed-size vectors/matrices), ndarray (n-d arrays, numpy analogue), faer (dense/sparse factorisations, LU/QR/Cholesky; fast, pure Rust).
- Performance: rayon data-parallelism, avoiding allocations in hot loops, SIMD-friendly layouts, profiling.
- Interop: PyO3/maturin, C FFI, WASM.

Typical workflow
1. Characterise the reference implementation (inputs, outputs, tolerances, hot spots) before writing Rust.
2. Build a deterministic test corpus; capture "golden" outputs from the reference.
3. Port bottom-up in small crates/modules, each with property tests (proptest) and golden tests.
4. Compare via tolerance-aware comparators, not byte equality (see section 4).
5. Profile (flamegraph, samply, Instruments), then optimise only measured hot spots.
6. Gate in CI: cargo fmt --check, clippy -D warnings, tests, benchmarks (criterion) with regression thresholds.

Decision patterns: prefer a mature crate over hand-rolling any robust geometry algorithm; wrap C/C++ (manifold, OpenCV, Clipper2) when no pure-Rust equivalent exists, accepting build complexity; keep the numeric core pure and the IO/web shell thin; treat bit-identical float output across languages as a non-goal.

## 2. Ecosystem mapping (Python dependency -> Rust)

Maturity legend: A = production-grade, widely used; B = usable, smaller community / some rough edges; C = experimental / gap risk.

| Python dep / use | Rust candidate(s) | Maturity | Notes / gaps |
|---|---|---|---|
| numpy arrays | `ndarray` (+ `ndarray-linalg` or `faer`) | A | API differs from numpy (no implicit broadcasting niceties, strict shapes). Heavy vectorised code ports well; expect more verbose code. |
| numpy small vec math | `nalgebra`, `glam` | A | nalgebra for general linear algebra; glam for fast f32/f64 3D vec ops. |
| scipy RBFInterpolator (thin-plate-spline, dense solve) | Hand-write: build kernel matrix + polynomial block, solve with `faer` (LU/PartialPivLu) or nalgebra | B (no ready crate) | **Gap.** There is an `rbf`-style crate or two (e.g. small RBF/`interpolation` crates) but nothing matching scipy's neighbours/smoothing/degree options. TPS is ~100 lines on top of a dense solver; the risk is performance for large N (scipy uses LAPACK; faer is competitive with OpenBLAS on dense LU) and matching scipy's polynomial-degree/smoothing semantics exactly. Verify with golden tests. |
| scipy inverse-distance blends, cKDTree | `kiddo`, `kd-tree`, `rstar` | A/B | Straightforward. |
| scipy.ndimage / interpolate grids | `ndarray` + `ndarray-ndimage`, hand-rolled bilinear/cubic | B | ndimage-equivalents are patchy; expect to hand-write some filters. |
| shapely polygon booleans | `i_overlay` (pure Rust, robust, integer-snapped, fast), `geo` BooleanOps (uses sweep-line; historically fragile on degenerates), `geo-clipper` / `clipper2` bindings (wrap C++ Clipper) | A- (i_overlay), B (geo booleans, clipper bindings) | i_overlay is the best pure-Rust choice (2024-26 active; verify version). Shapely uses GEOS: semantics (validity repair, `buffer(0)`, `make_valid`) differ. |
| shapely offset / buffer | `i_overlay` outline/offset feature (`i_overlay` ships offsetting; also `i_shape`), `geo-buffer` (straight skeleton-based), Clipper2 offset via bindings | B | **Risk.** Round-join / mitre behaviour and arc approximation need to match GEOS `buffer` (quad_segs, join_style, mitre_limit). Verify output with area/Hausdorff tolerances. |
| shapely predicates, simplify, centroid, etc. | `geo` (algorithms: Simplify (RDP), VW, Area, Centroid, Contains, Intersects, ConvexHull, ConcaveHull), `rstar` | A | Mature; `geo` is the georust core. |
| triangle (Shewchuk CDT w/ min-angle + max-area) | `spade` (pure Rust CDT, refinement with angle/area limits; uses robust predicates), `cdt` (simple, no refinement), `triangle-rs`/`triangle` C bindings (Shewchuk license is non-commercial-ish: check) | A- (spade), B (bindings) | **Key risk area.** spade's `refine()` supports min angle and max-area (global or per-face via closure), but the exact triangulation will differ from Shewchuk's Triangle (different Steiner placement). Meshes will not be vertex-identical; compare via surface-height error, not vertex lists. Triangle's licence is not OSI-open: relevant only if commercialising. |
| trimesh (mesh assembly, merge verts, watertight, volume) | `parry3d` (TriMesh, BVH, queries), `tri-mesh`, `meshopt` (simplify/optimise), `hashbrown` vertex welding by hand, `baby_shark`, `russimp`(import) | B | **Gap.** No single crate = trimesh. Vertex merging, watertight/manifold check (edge-count map), winding fix, volume/area are each ~20-50 lines to hand-write. Boolean on meshes: see Manifold below. |
| trimesh/manifold booleans | `manifold3d` / `manifold-rs` bindings to Manifold (C++) | B (bindings young) | Watertight mesh booleans are the hardest thing to do natively in Rust; there is no mature pure-Rust equivalent (`cgar` is aspirational; `csgrs` exists, is BSP-based, not robust). Only needed if the pipeline does 3D booleans; if it uses polygon extrusion + stacking only, avoid. Verify how the generator combines solids. |
| OpenCV (contours, morphology, grid removal, connected components) | `opencv` crate (opencv-rust, bindings to system OpenCV) vs pure-Rust `imageproc` + `image` | opencv: A- but heavy install (brew opencv, LLVM/clang for bindgen); imageproc: B | imageproc has: contours (`find_contours`), morphology, connected components, Gaussian/median filters, Hough, distance transform, flood fill. Missing or weaker: inpainting, some adaptive ops, exact cv2 flag semantics. Decision: start with imageproc; fall back to opencv-rust on specific gaps. |
| scikit-image (label, morphology, find_contours, skeletonize) | `imageproc`, `contour-tracing`, `marching-squares`, hand-rolled | B/C | **Gap.** skimage's marching-squares `find_contours` (subpixel) -> `contour` / `marching-squares` crates; skeletonize / regionprops have no mature equivalent. |
| PIL / Pillow | `image` | A | Decode/encode PNG, resize, crop; resampling filter names/results differ slightly from PIL (Lanczos kernels). |
| matplotlib TextPath -> polygons -> extruded text | `ttf-parser` (outlines), `rustybuzz` (shaping), `lyon` (path flattening/tessellation), `fontdue`, `swash`, `cosmic-text`; `kurbo` for curve flattening | A | Need the **same font file** (matplotlib bundles DejaVu Sans; ship that TTF). Glyph advance/kerning from matplotlib TextPath vs rustybuzz can differ; golden-compare label bounding boxes. |
| zipfile + XML 3MF writing | `zip`, `quick-xml`; or 3MF crates: `lib3mf` (pure-Rust, parse+write, 0.1.x, young), `threemf` (writer, extracted from Fornjot, basic), `threemf2` (fork, read/write, 2024 edition) | zip/quick-xml: A; 3MF crates: C/B | No official Rust bindings to 3MF Consortium lib3mf (only Go/C++/Python etc.). The Bambu-specific `Metadata/model_settings.config`, plate JSON, thumbnails and slice-info are not covered by any crate: write them by hand with `quick-xml`/`zip` (this is what we already do in Python). Recommend: hand-written writer, mirrors existing Python line for line. |
| Flask + Jinja templates | `axum` + `tower-http` (static, trace, compression, cors), `minijinja` (Jinja2-compatible, runtime templates, closest drop-in for existing editor.html), `askama` (compile-time, Jinja-like but stricter) | A | minijinja is the pragmatic choice: it renders most existing templates with small edits (differences in filters/macros/inheritance edge cases). Flask `url_for`, `request`, `session` must be reimplemented. Large JS inside editor.html is just text. |
| Flask JSON/file upload/multipart | `axum` (+`axum-extra` multipart), `serde`/`serde_json` | A | |
| SQLite (if app uses it) | `rusqlite` / `sqlx` | A | |
| multiprocessing/threads | `rayon`, `tokio` (spawn_blocking for CPU work) | A | Do not run CPU-heavy generation on the async executor. |
| Hybrid | `PyO3` + `maturin` | A | Call Rust from Python (keep Flask) -- fallback strategy. |

### Gaps and risks (ranked)
1. **TPS RBFInterpolator parity** - no drop-in crate; numerics (conditioning, polynomial terms, smoothing) must be reproduced and validated. Dense solve size drives runtime.
2. **Constrained Delaunay with quality refinement** - spade is good but not identical to Shewchuk Triangle; mesh topology will differ; downstream code that assumes Triangle's output ordering/attributes (regions, holes) needs rework.
3. **Polygon offset/buffer semantic drift** vs GEOS (join styles, arc segments, degenerate/invalid input, `buffer(0)` cleanups).
4. **Watertight mesh booleans / trimesh utility surface** - hand-written utilities; if any 3D boolean is used, Manifold bindings or a redesign (2.5D stacking) is needed.
5. **OpenCV/skimage image-analysis parity** (contours, grid removal, morphology edge handling, subpixel contouring) - bindings vs reimplementation tradeoff; border modes and connectivity subtle.
6. **Text-outline fidelity** (matplotlib TextPath vs ttf-parser curve flattening/kerning).
7. **Bambu-specific 3MF metadata** - no crate; hand-written; need byte/semantic diff and a real Bambu Studio import test (human-in-the-loop).
8. **Size of the work**: 17k lines, an 11.7k-line single generator file; likely 10-14k lines of Rust. A feasibility spike, not a full port, is the right first milestone.
9. **Floating-point non-identity**: f64 vs numpy float64 usually matches, but summation order (BLAS vs faer) and f32 intermediates differ; outputs equal only within tolerance.
10. **Licensing**: Shewchuk Triangle (restrictive), Clipper2 (Boost, fine), Manifold (Apache-2), OpenCV (Apache-2). Matters given the commercial-intent note for other projects.

## 3. Porting best practices

Strategy
- **Strangler fig, not big-bang.** Order: (a) CLI-first generator in Rust producing a 3MF from the same input bundle as Python; (b) golden diff against Python for N reference holes; (c) only then HTTP layer on port 5054 serving the same editor.html and JSON routes; (d) migrate route by route, proxying unported routes to 5051 (axum reverse proxy) so the Rust app is usable early.
- **Module-by-module vertical slices**: start with the cheapest/most measurable stages (3MF writer, text engraving, polygon booleans), then TPS+height grid, then CDT meshing, then image analysis.
- **Oracle testing**: Python is the oracle. Dump intermediate artifacts from Python at each pipeline stage (height grid .npy, polygon WKT/GeoJSON, mesh vertices/faces .npz, labels) so each Rust stage can be tested in isolation. Rust reads .npy via `ndarray-npy`.
- **Golden-output comparison (tolerance-based)**
  - Heightfield/grids: max abs error, RMSE in mm.
  - Polygons: area difference, symmetric-difference area ratio, Hausdorff distance.
  - Meshes: vertex counts will differ (CDT); compare via bounding box, total volume, surface area, watertight/manifold flags, per-sample height at a grid of XY points (ray cast or interpolation), Chamfer/Hausdorff distance (use `trimesh.proximity` on the Python side in the test harness).
  - 3MF: unzip and compare file lists, XML structure (canonicalised), metadata keys/values exactly; object/plate counts; transform matrices within epsilon.
  - Final gate: slice both in Bambu Studio and compare print time/filament estimates, plus eyeball.
- **Property tests** (proptest) for invariants: every edge shared by exactly two faces, no degenerate triangles, outward normals, polygon validity.
- **Fixed seeds and deterministic ordering** (avoid HashMap iteration order in output; use IndexMap/BTreeMap).
- **Benchmarking**: `criterion` (stage-level benches, statistical comparison), end-to-end wall-clock via `hyperfine` against the Python CLI on identical inputs, `cargo flamegraph` / `samply` for CPU profiles, and on macOS Instruments Time Profiler through `cargo-instruments` (needs Xcode CLT; requires debug symbols in release: `[profile.release] debug = true` or `debug = "line-tables-only"`). Measure Python too: py-spy / cProfile to see where time actually goes before the port.
- **PyO3/maturin hybrid fallback**: expose the Rust hot functions (TPS solve, CDT meshing, 3MF write) as a Python module; Flask stays; gives measurable speedups with the smallest change, and doubles as a stage-by-stage migration path (swap one function at a time and keep golden tests green).

### Realistic expectations
Speed
- Where Python already spends its time inside numpy/scipy/OpenCV/triangle C code, a Rust rewrite gains little (often 0.8-1.5x; possibly slower if dense solves are slower than LAPACK-backed scipy, or if the CDT library differs). Gains are real only where Python-level loops, per-vertex Python code, shapely object churn, and repeated array conversion dominate: expect 3-30x on those sections. Overall end-to-end for this pipeline: plausible 1.5-5x if profiling shows interpreter overhead; ~1x if time is dominated by one RBF solve or one library call. **Profile Python first**; that determines whether the experiment can show a speed win.
- Rayon can give near-linear multi-core wins on embarrassingly parallel parts (per-hole/per-plate generation, grid evaluation) -- Python can only match with multiprocessing.
- Startup and memory: Rust server starts in ms and uses far less RAM; this matters for per-request generation latency, little for batch.
Iteration speed ("are changes faster to make?")
- Likely **slower** for edits in Rust: cold release builds of a medium crate tree with heavy deps (opencv, nalgebra, faer, i_overlay) take 1-5+ minutes; incremental debug rebuilds are typically 2-15 s; `cargo check` 1-5 s incremental. Python edit-to-run is instant. Numeric code in debug builds is 10-50x slower, so you need `opt-level = 1-3` for dev-profile deps (`[profile.dev.package."*"] opt-level = 3`).
- Mitigations: `bacon` or `cargo watch -x check -x test`, split into a workspace of small crates, `sccache`, the `mold`-equivalent linker on Linux (macOS: Apple's new `ld` is already fast; `lld` optional), avoid heavy proc-macros, keep OpenCV out of the hot dev loop, `cargo nextest`.
- Where Rust helps: refactors are safer (compiler catches shape/type mistakes that Python finds at runtime), and a 17k-line codebase with an 11.7k-line file becomes easier to restructure. Net verdict for Thomas's question 3: expect slower tiny edits, faster/safer large refactors. This is a hypothesis the experiment should measure (time per standardized change request).

Suggested experiment milestones (for Larry/Thomas)
1. Day 0-1: profile Python (py-spy, per-stage timings), extract reference corpus, decide spike scope.
2. Spike A: Rust CLI that reads exported grid + polygons and writes a Bambu-style 3MF; golden diff vs Python's.
3. Spike B: TPS (faer) + CDT (spade) on one hole; mesh-error report.
4. Go/no-go checkpoint with numbers (speed, error, LOC, build times).
5. Only then axum server on 5054.

## 4. macOS tooling setup
- `curl https://sh.rustup.rs -sSf | sh` (or `brew install rustup`); stable toolchain pinned with `rust-toolchain.toml` (channel = "stable", components = ["clippy","rustfmt","rust-analyzer"]).
- Xcode Command Line Tools (`xcode-select --install`) for the linker; `brew install cmake pkg-config` for C/C++ sys crates; `brew install opencv llvm` only if using opencv-rust (set `DYLD_FALLBACK_LIBRARY_PATH`/`LIBCLANG_PATH`).
- Cargo plugins: `cargo install cargo-nextest bacon cargo-watch cargo-flamegraph cargo-instruments hyperfine samply cargo-criterion cargo-deny cargo-udeps` (as needed).
- clippy (`cargo clippy --all-targets -- -D warnings`), rustfmt (`rustfmt.toml`), rust-analyzer in the editor.
- Profiles:
  ```toml
  [profile.dev.package."*"]
  opt-level = 3        # fast deps in dev
  [profile.release]
  opt-level = 3
  lto = "thin"         # "fat" for final benchmarks
  codegen-units = 1    # for final benchmarks
  debug = "line-tables-only"   # for flamegraph / Instruments
  panic = "abort"      # optional
  ```
- `target-cpu=native` via `.cargo/config.toml` for benchmarks only (non-portable).
- Note from project memory: /Volumes/GIT is an external volume mounted nosuid; build artifacts (`target/`) on external volume can be slow and may trip execute restrictions. Set `CARGO_TARGET_DIR` to a boot-volume path (e.g. ~/.cargo-targets/rust_port) and keep sources in the repo. Also: coding standard in CLAUDE.md (named constants, no literals) applies to Rust (`const NAME: T`), tests reference the same constants.

## 5. Recommended model tier

**Recommend: opus.** Reasoning
- The role is dominated by novel reasoning: numerical-robustness judgement, matching floating-point behaviour across libraries, deciding where tolerances belong, diagnosing mesh topology failures, interpreting profiling data, and making architecture calls (strangler vs hybrid, which C++ to wrap). These are the "architectural judgment / deep research" criteria for opus in Nolan's rubric.
- Rust's borrow checker plus an unfamiliar crate surface raises the cost of weak reasoning (long compile-fix loops burn more tokens/time than a stronger model that gets it right).
- The experiment's value is the quality of the go/no-go answer; a cheaper model that mis-ports TPS or CDT would produce misleading speed/feasibility conclusions.
- Exception to the 2026-10-22 Sonnet 5.5 standardisation: justified for this role. Optional compromise: opus for the lead/architect (spikes, design, numerical parity, review), with mechanical follow-on tasks (route-by-route axum handlers, boilerplate, test scaffolding) delegated to the existing Sonnet 5.5 team. If Thomas wants zero exceptions, Sonnet 5.5 can do it but expect more iteration on numerics.

## 6. Suggested persona skeleton for Nolan
Name suggestion: any; Title: Senior Rust Engineer, Geometry and Mesh Pipelines. Responsibilities: profile the Python reference first; build golden corpus and tolerance comparators; port in vertical slices with CLI-first approach; benchmark (criterion, hyperfine, flamegraph); report honest go/no-go numbers on feasibility, speed, and change-velocity; maintain Rust server on port 5054 without touching port 5051 or live DB (temp DB for verification, per standing rule); follow named-constants rule; never claim a speedup without a reproducible measurement; flag licensing issues (Triangle).

## Sources
- lib3mf (pure Rust): https://docs.rs/lib3mf
- threemf: https://docs.rs/threemf
- threemf2: https://docs.rs/threemf2/latest/threemf2/
- cgar (aspirational CGAL-like): https://docs.rs/crate/cgar/latest
- Remaining crate status from prior knowledge; verify versions on crates.io.
