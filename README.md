# infraCFD

**[infracfd.app](https://infracfd.app)** — browser-based wind analysis for civil engineering structures, powered by OpenFOAM.

**2D** — cross-section aerodynamics (bridge decks, building profiles)  
**3D** — building aerodynamics (single buildings or entire city blocks)

Draw a geometry in the browser, hit run, get pressure fields, velocity slices and streamlines — no pre-processing scripts, no local CFD installation beyond OpenFOAM in WSL.

> By [geobim.app](https://geobim.app)  
> Cross-sections and 3D geometries derived from the [SOFiSTiK Dolfyn](https://www.sofistik.com) CFD example library.

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | Vanilla JS, Three.js (no framework) |
| Backend | Python, FastAPI |
| Meshing | Gmsh (Python API) |
| Solver | OpenFOAM 2406/2412 via WSL (steady RANS, k-ε) |

---

## Requirements

- Python 3.10+
- WSL (Ubuntu) with OpenFOAM 2406 or 2412
- Gmsh (`pip install gmsh`)
- scipy, numpy

**Install OpenFOAM in WSL:**
```bash
# In WSL Ubuntu
sudo sh -c "wget -q -O - https://dl.openfoam.com/add-debian-repo.sh | bash"
sudo apt install openfoam2406-default
```

---

## Quickstart

```bash
git clone https://github.com/christof2304/infrafem-cfd.git
cd infrafem-cfd
pip install -r requirements.txt
pip install gmsh
```

**Windows (double-click):**
```
start-server.bat
```

**Or from terminal:**
```bash
uvicorn server.app:app --reload --port 8000
```

Then open **http://localhost:8000/cfd/**

---

## Features

### 2D Cross-Section
- Draw any polygon directly in the browser
- Automatic Gmsh mesh with boundary layer refinement
- Steady RANS or transient solve
- Pressure, velocity, vorticity, turbulent kinetic energy
- Client-side RK4 streamlines
- Force coefficients Cd / Cl

### 3D Building
- Footprint-based building extrusion
- Multi-building city block support
- Atmospheric boundary layer inlet (z₀-dependent log profile)
- Horizontal + vertical result slices with interactive slider
- Slice streamlines traced client-side (RK4 on cut plane)
- Force coefficients Cd / Cl / Cm

### General
- Wind angle, terrain roughness (z₀) and domain size configurable
- Live solver log stream (Server-Sent Events)
- Three.js 3D viewer with isometric OrthographicCamera

---

## Project Structure

```
cfd/            Browser app (HTML + JS)
  index.html    Entry point
  app.js        Main application logic
  viewer3d.js   Three.js 3D viewer + slice rendering
  draw2d.js     2D polygon drawing canvas
  cfd-testcases.js  Built-in example cases

tools/
  cfd_openfoam.py   OpenFOAM case generation, ABL inlet, force coefficients
  cfd_mesh.py       2D Gmsh mesh generation

server/
  app.py        FastAPI server (CFD endpoints only)

three/          Three.js (bundled, no npm required)
```

---

## License

MIT — see [LICENSE](LICENSE)
