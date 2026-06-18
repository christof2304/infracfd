# Changelog

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
