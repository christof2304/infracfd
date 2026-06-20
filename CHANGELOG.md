# Changelog

## Unreleased — toward v0.2

### Changed
- **Mesh preview ↔ solver consistency (boundary layer):** the preview mesh and
  the solver mesh now derive their boundary-layer sizing (first-layer height,
  layer count, growth ratio) from a single shared function
  (`tools/cfd_mesh.py:boundary_layer_params`), so *what you preview is what gets
  solved*. Previously the preview used a wind-dependent y⁺=50 first layer with an
  adaptive layer count while the solver used a fixed geometric sizing — the
  preview could show a finer/different boundary layer than was actually solved.
  The shared sizing keeps the solver's **first-layer height bit-identical** (same
  geometric formula), so sharp-corner and smooth sections produce identical
  node/element counts. This change also removes a redundant full mesh that was
  generated and discarded on every solve; dropping that pre-pass perturbs Gmsh's
  global state slightly, so **bluff sections shift by ≲1 %** (e.g. RUB deck:
  12130→12054 nodes). Re-validation confirms this is within benchmark scatter:
  RUB @α=4 gives Cd/Cl/Cm = 0.093 / 0.412 / 0.113 (Exp. ref 0.095 / 0.380 /
  0.109), unchanged from the pre-refactor mesh. v0.1 conclusions stand.

### Fixed
- **2D domain-size slider had no effect.** The front-end sent the slider as
  `farField` while the backend read `farFieldFactor`, so every 2D mesh/solve
  silently used the default factor 15 regardless of the slider. The backend now
  accepts `farField` (falling back to `farFieldFactor`). Default 15 is unchanged,
  so v0.1 validation results (run at the default) are unaffected.

### Planned — v0.2

- **Boundary-layer physics upgrade (step 2):** switch the shared sizing to the
  physics-based y⁺=50 first layer (`50·ν/u_τ`, wind-dependent). This changes the
  solved mesh, so it must land **behind a re-validation** of the DFG cylinder and
  RUB bridge-deck benchmarks. One-line change in `boundary_layer_params`.
- **Per-case far-field is currently dead data.** Each 2D test case declares a
  `farField` (e.g. DFG cylinder and RUB both 25) but `_loadCase` never applies it
  to the domain-size slider, so cases run at whatever the slider shows (default
  15). The v0.1 validation numbers were therefore produced at far_field=15, not
  the declared 25. Decide during the step-2 re-validation whether to wire
  `tc.farField` into the slider — using the benchmark runs to confirm which
  far-field actually best matches the references — rather than guessing now.
- Optionally show mesh edges in the result view so the boundary layer is visible.
- k-ω SST sweep of the 2D cases at their reference angles → more validated examples.
- Take 3D building CFD and transient solving out of *beta*.

## v0.1.0 — first public release

First open-source release. Scope: **2D cross-section aerodynamics, steady RANS.**

### Added
- Browser-based 2D CFD: draw a cross-section, mesh (Gmsh), solve (OpenFOAM
  `simpleFoam`), view pressure / velocity / vorticity / k fields, streamlines
  and force coefficients (cd / cl / cm).
- Selectable turbulence model: k-ε, RNG k-ε, realizable k-ε, **k-ω SST**.
- 19 built-in 2D example cases (bridge decks, profiles, airfoils, noise barrier,
  cylinder), derived from the SOFiSTiK/Dolfyn example library.
- Validation against published benchmarks — DFG laminar cylinder (Re=20, matched
  essentially exactly) and the RUB bridge deck wind-tunnel case (k-ω SST, within
  a few percent). See README.

### Experimental (present, marked *beta*, not yet benchmark-validated)
- 3D building CFD via snappyHexMesh (single buildings, city blocks, GLB upload).
- Transient solving (`pimpleFoam`) with vortex-shedding animation.

### Known limitations
- NACA airfoil cd is unreliable with k-ε at high Re (treat as lift/flow demos).
- Standard k-ε under-predicts lift and bluff-body drag — use k-ω SST for those.

### License
- Released under **GPLv3** (the Gmsh Python API it links is GPL). See LICENSE / NOTICE.
