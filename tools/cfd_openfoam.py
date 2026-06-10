"""
OpenFOAM case generator for 2D bridge cross-section aerodynamics.

Converts a Gmsh mesh + wind parameters into a complete OpenFOAM case directory:
  - 0/: Initial + boundary conditions (U, p, k, epsilon, nut)
  - constant/: transportProperties, turbulenceProperties
  - system/: controlDict, fvSchemes, fvSolution

Uses simpleFoam (steady RANS) with k-epsilon turbulence model.

Usage:
    from tools.cfd_openfoam import create_openfoam_case, run_openfoam, parse_results
    case_dir = create_openfoam_case(mesh_data, wind_speed=20, wind_angle=0)
    run_openfoam(case_dir)  # requires Docker
    results = parse_results(case_dir)
"""

import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path


def create_openfoam_case(mesh_result, wind_speed=20.0, wind_angle=0.0,
                         nu=1.5e-5, turbulence_intensity=0.05,
                         output_dir=None, transient=False, end_time=5.0, dt=0.001,
                         write_interval=100):
    """
    Create an OpenFOAM case directory from a CFD mesh result.

    Args:
        mesh_result: Output from generate_cfd_mesh() — has nodes, triangles, section_polygon
        wind_speed: Free-stream wind velocity [m/s]
        wind_angle: Wind direction [degrees] (0 = from left, +X)
        nu: Kinematic viscosity [m²/s] (air at 20°C = 1.5e-5)
        turbulence_intensity: TI at inlet (typically 0.01-0.10)
        output_dir: Directory for the case (default: temp dir)

    Returns:
        case_dir: Path to the OpenFOAM case directory
    """
    if output_dir is None:
        import tempfile
        output_dir = tempfile.mkdtemp(prefix="cfd_case_")
    case_dir = Path(output_dir)

    # Wind velocity components
    rad = math.radians(wind_angle)
    Ux = wind_speed * math.cos(rad)
    Uy = wind_speed * math.sin(rad)

    # Turbulence parameters (k-epsilon)
    char_dim = mesh_result["stats"]["char_dim"]
    k_inlet = 1.5 * (wind_speed * turbulence_intensity) ** 2
    epsilon_inlet = 0.09 * k_inlet ** 1.5 / (0.1 * char_dim)
    nut_inlet = 0.09 * k_inlet ** 2 / max(epsilon_inlet, 1e-10)

    # Reynolds number
    Re = wind_speed * char_dim / nu
    print(f"  Re = {Re:.0f}, k = {k_inlet:.4f}, epsilon = {epsilon_inlet:.4f}")

    # ── Create directory structure ──
    for d in ["0", "constant", "system", "constant/polyMesh"]:
        (case_dir / d).mkdir(parents=True, exist_ok=True)

    # ── 0/ — Initial and boundary conditions ──

    # U (velocity)
    _write_of_file(case_dir / "0" / "U", "volVectorField", "U", f"""
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform ({Ux} {Uy} 0);
boundaryField
{{
    farfield
    {{
        type            freestreamVelocity;
        freestreamValue uniform ({Ux} {Uy} 0);
    }}
    section
    {{
        type            noSlip;
    }}
    defaultFaces
    {{
        type            empty;
    }}
}}
""")

    # p (pressure)
    _write_of_file(case_dir / "0" / "p", "volScalarField", "p", f"""
dimensions      [0 2 -2 0 0 0 0];
internalField   uniform 0;
boundaryField
{{
    farfield
    {{
        type            freestreamPressure;
        freestreamValue uniform 0;
    }}
    section
    {{
        type            zeroGradient;
    }}
    defaultFaces
    {{
        type            empty;
    }}
}}
""")

    # k (turbulent kinetic energy)
    _write_of_file(case_dir / "0" / "k", "volScalarField", "k", f"""
dimensions      [0 2 -2 0 0 0 0];
internalField   uniform {k_inlet};
boundaryField
{{
    farfield
    {{
        type            freestream;
        freestreamValue uniform {k_inlet};
    }}
    section
    {{
        type            kqRWallFunction;
        value           uniform {k_inlet};
    }}
    defaultFaces
    {{
        type            empty;
    }}
}}
""")

    # epsilon (turbulent dissipation)
    _write_of_file(case_dir / "0" / "epsilon", "volScalarField", "epsilon", f"""
dimensions      [0 2 -3 0 0 0 0];
internalField   uniform {epsilon_inlet};
boundaryField
{{
    farfield
    {{
        type            freestream;
        freestreamValue uniform {epsilon_inlet};
    }}
    section
    {{
        type            epsilonWallFunction;
        value           uniform {epsilon_inlet};
    }}
    defaultFaces
    {{
        type            empty;
    }}
}}
""")

    # nut (turbulent viscosity)
    _write_of_file(case_dir / "0" / "nut", "volScalarField", "nut", f"""
dimensions      [0 2 -1 0 0 0 0];
internalField   uniform {nut_inlet};
boundaryField
{{
    farfield
    {{
        type            freestream;
        freestreamValue uniform {nut_inlet};
    }}
    section
    {{
        type            nutUSpaldingWallFunction;
        value           uniform 0;
    }}
    defaultFaces
    {{
        type            empty;
    }}
}}
""")

    # ── constant/ — Physical properties ──

    _write_of_file(case_dir / "constant" / "transportProperties", None, None, f"""
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      transportProperties;
}}
transportModel  Newtonian;
nu              [0 2 -1 0 0 0 0] {nu};
""")

    _write_of_file(case_dir / "constant" / "turbulenceProperties", None, None, f"""
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      turbulenceProperties;
}}
simulationType  RAS;
RAS
{{
    RASModel        kEpsilon;
    turbulence      on;
    printCoeffs     on;
}}
""")

    # ── system/ — Solver settings ──

    if transient:
        solver_app = "pimpleFoam"
        delta_t = dt
        end_t = end_time
        write_int = write_interval
        purge = 0  # keep all time steps for animation
    else:
        solver_app = "simpleFoam"
        delta_t = 1
        end_t = 500
        write_int = 500
        purge = 1

    _write_of_file(case_dir / "system" / "controlDict", None, None, f"""
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}}
application     {solver_app};
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         {end_t};
deltaT          {delta_t};
writeControl    timeStep;
writeInterval   {write_int};
purgeWrite      {purge};
writeFormat     ascii;
writePrecision  8;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;

functions
{{
    forces
    {{
        type            forceCoeffs;
        libs            ("libforces.so");
        writeControl    timeStep;
        writeInterval   1;
        patches         (section);
        rho             rhoInf;
        rhoInf          1.225;
        CofR            (0 0 0);
        liftDir         (0 1 0);
        dragDir         (1 0 0);
        pitchAxis       (0 0 1);
        magUInf         {wind_speed};
        lRef            {char_dim};
        Aref            {char_dim};
    }}
}}
""")

    ddt_scheme = "Euler" if transient else "steadyState"
    _write_of_file(case_dir / "system" / "fvSchemes", None, None, f"""
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSchemes;
}}
ddtSchemes      {{ default {ddt_scheme}; }}
gradSchemes     {{ default Gauss linear; }}
divSchemes
{{
    default             none;
    div(phi,U)          bounded Gauss linearUpwind grad(U);
    div(phi,k)          bounded Gauss upwind;
    div(phi,epsilon)    bounded Gauss upwind;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}}
laplacianSchemes {{ default Gauss linear corrected; }}
interpolationSchemes {{ default linear; }}
snGradSchemes {{ default corrected; }}
""")

    if transient:
        _write_of_file(case_dir / "system" / "fvSolution", None, None, """
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSolution;
}
solvers
{
    p   { solver GAMG; smoother GaussSeidel; tolerance 1e-06; relTol 0.01; }
    pFinal { $p; relTol 0; }
    U   { solver smoothSolver; smoother GaussSeidel; tolerance 1e-07; relTol 0.01; }
    UFinal { $U; relTol 0; }
    k   { solver smoothSolver; smoother GaussSeidel; tolerance 1e-07; relTol 0.01; }
    kFinal { $k; relTol 0; }
    epsilon { solver smoothSolver; smoother GaussSeidel; tolerance 1e-07; relTol 0.01; }
    epsilonFinal { $epsilon; relTol 0; }
}
PIMPLE
{
    nNonOrthogonalCorrectors 1;
    nCorrectors 2;
    nOuterCorrectors 1;
    pRefCell 0;
    pRefValue 0;
}
relaxationFactors
{
    equations { ".*" 1; }
}
""")
    else:
        _write_of_file(case_dir / "system" / "fvSolution", None, None, """
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSolution;
}
solvers
{
    p   { solver GAMG; smoother GaussSeidel; tolerance 1e-06; relTol 0.01; }
    U   { solver smoothSolver; smoother GaussSeidel; tolerance 1e-07; relTol 0.01; }
    k   { solver smoothSolver; smoother GaussSeidel; tolerance 1e-07; relTol 0.01; }
    epsilon { solver smoothSolver; smoother GaussSeidel; tolerance 1e-07; relTol 0.01; }
}
SIMPLE
{
    nNonOrthogonalCorrectors 1;
    pRefCell 0;
    pRefValue 0;
    residualControl { p 1e-4; U 1e-4; k 1e-4; epsilon 1e-4; }
}
relaxationFactors
{
    fields { p 0.3; }
    equations { U 0.7; k 0.7; epsilon 0.7; }
}
""")

    # ── Save mesh data for Gmsh → OpenFOAM conversion ──
    with open(case_dir / "mesh_data.json", "w") as f:
        json.dump(mesh_result, f)

    # Save case metadata
    meta = {
        "wind_speed": wind_speed,
        "wind_angle": wind_angle,
        "Re": Re,
        "char_dim": char_dim,
        "nu": nu,
        "k_inlet": k_inlet,
        "epsilon_inlet": epsilon_inlet,
    }
    with open(case_dir / "case_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print(f"  OpenFOAM case created: {case_dir}")
    return str(case_dir)


def _write_of_file(path, class_name, object_name, content):
    """Write an OpenFOAM file with standard FoamFile header (Unix line endings)."""
    path = Path(path)
    if class_name and object_name:
        header = f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       {class_name};
    object      {object_name};
}}
"""
        with open(path, "w", newline="\n") as f:
            f.write(header + content)
    else:
        with open(path, "w", newline="\n") as f:
            f.write(content)


def generate_gmsh_msh(polygon, msh_path, mesh_size=0.2, far_field_factor=15,
                      bl_layers=4, bl_ratio=1.4):
    """Generate a Gmsh .msh file for OpenFOAM (run in subprocess due to signal issues)."""
    script = f"""
import sys, json
sys.path.insert(0, r'{str(Path(__file__).resolve().parent.parent)}')
from tools.cfd_mesh import generate_cfd_mesh
import gmsh

# Generate the mesh (this also initializes gmsh)
polygon = {json.dumps(polygon)}
generate_cfd_mesh(polygon, mesh_size={mesh_size}, far_field_factor={far_field_factor})

# Gmsh is finalized in generate_cfd_mesh, re-init to export
# Actually, let's do it differently: generate mesh and save .msh directly

gmsh.initialize()
gmsh.option.setNumber("General.Verbosity", 0)
gmsh.model.add("cfd")

import math
cx = sum(p[0] for p in polygon) / len(polygon)
cy = sum(p[1] for p in polygon) / len(polygon)
xs = [p[0] for p in polygon]
ys = [p[1] for p in polygon]
char_dim = max(max(xs)-min(xs), max(ys)-min(ys))
ff_r = char_dim * {far_field_factor}
ff_ms = char_dim * 2

# Section points
spts = []
for x, y in polygon:
    spts.append(gmsh.model.geo.addPoint(x, y, 0, {mesh_size}))
slines = []
n = len(spts)
for i in range(n):
    slines.append(gmsh.model.geo.addLine(spts[i], spts[(i+1)%n]))
sloop = gmsh.model.geo.addCurveLoop(slines)

# Far-field circle
ff_pts = []
for i in range(32):
    a = 2*math.pi*i/32
    ff_pts.append(gmsh.model.geo.addPoint(cx+ff_r*math.cos(a), cy+ff_r*math.sin(a), 0, ff_ms))
cpt = gmsh.model.geo.addPoint(cx, cy, 0, ff_ms)
ff_arcs = []
for i in range(4):
    s = ff_pts[i*8]
    e = ff_pts[((i+1)*8)%32]
    ff_arcs.append(gmsh.model.geo.addCircleArc(s, cpt, e))
ff_loop = gmsh.model.geo.addCurveLoop(ff_arcs)

surf = gmsh.model.geo.addPlaneSurface([ff_loop, sloop])
gmsh.model.geo.synchronize()

# Size fields — three-zone with sigmoid transition
df = gmsh.model.mesh.field.add("Distance")
gmsh.model.mesh.field.setNumbers(df, "CurvesList", slines)
tf = gmsh.model.mesh.field.add("Threshold")
gmsh.model.mesh.field.setNumber(tf, "InField",  df)
gmsh.model.mesh.field.setNumber(tf, "SizeMin",  {mesh_size} * 0.6)
gmsh.model.mesh.field.setNumber(tf, "SizeMax",  ff_ms)
gmsh.model.mesh.field.setNumber(tf, "DistMin",  char_dim * 0.3)
gmsh.model.mesh.field.setNumber(tf, "DistMax",  ff_r * 0.4)
gmsh.model.mesh.field.setNumber(tf, "Sigmoid",  1)
gmsh.model.mesh.field.setAsBackgroundMesh(tf)
gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
gmsh.option.setNumber("Mesh.MeshSizeFromPoints",         0)
gmsh.option.setNumber("Mesh.MeshSizeFromCurvature",      0)
gmsh.option.setNumber("Mesh.Smoothing",                  5)

# Boundary Layer: tuned for k-epsilon wall functions (y+ 30-100)
if {bl_layers} > 0:
    first_layer = max(2e-4, min({mesh_size} * 0.04, char_dim * 0.004))
    bl = gmsh.model.mesh.field.add("BoundaryLayer")
    gmsh.model.mesh.field.setNumbers(bl, "CurvesList",       slines)
    gmsh.model.mesh.field.setNumbers(bl, "PointsList",       spts)
    gmsh.model.mesh.field.setNumber (bl, "Size",             first_layer)
    gmsh.model.mesh.field.setNumber (bl, "Ratio",            {bl_ratio})
    gmsh.model.mesh.field.setNumber (bl, "NbLayers",         {bl_layers})
    gmsh.model.mesh.field.setNumber (bl, "Quads",            1)
    gmsh.model.mesh.field.setNumber (bl, "IntersectMetrics", 1)
    gmsh.model.mesh.field.setAsBoundaryLayer(bl)

# Physical groups
gmsh.model.addPhysicalGroup(1, slines, tag=1, name="section")
gmsh.model.addPhysicalGroup(1, ff_arcs, tag=2, name="farfield")
gmsh.model.addPhysicalGroup(2, [surf], tag=1, name="fluid")

# Generate 2D mesh (BL quads + background triangles)
gmsh.model.mesh.generate(2)

# Extrude to thin 3D slab for OpenFOAM
ext = gmsh.model.geo.extrude([(2, surf)], 0, 0, 1.0, numElements=[1], recombine=True)
gmsh.model.geo.synchronize()

# Parse extrude results:
# ext[0] = (2, top_surface)
# ext[1] = (3, volume)
# ext[2..2+n_ff-1] = (2, farfield lateral surfaces) — one per ff_arc
# ext[2+n_ff..] = (2, section lateral surfaces) — one per section line
top_surf = ext[0][1]
vol = ext[1][1]
n_ff = len(ff_arcs)
n_sec = len(slines)
ff_lateral = [ext[2 + i][1] for i in range(n_ff)]
sec_lateral = [ext[2 + n_ff + i][1] for i in range(n_sec)]

# Remove old 2D physical groups and set new 3D ones
gmsh.model.removePhysicalGroups()
gmsh.model.addPhysicalGroup(3, [vol], tag=10, name="internal")
gmsh.model.addPhysicalGroup(2, sec_lateral, tag=1, name="section")
gmsh.model.addPhysicalGroup(2, ff_lateral, tag=2, name="farfield")
gmsh.model.addPhysicalGroup(2, [surf, top_surf], tag=3, name="frontAndBack")

gmsh.model.mesh.generate(3)
gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
gmsh.write(r'{msh_path}')
print("MSH_OK")
gmsh.finalize()
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=30,
    )
    if "MSH_OK" not in result.stdout:
        raise RuntimeError(f"Gmsh export failed: {result.stderr[:500]}")


def run_openfoam(case_dir, polygon, mesh_size=0.2, far_field_factor=15,
                 bl_layers=5, bl_ratio=1.3):
    """
    Run OpenFOAM simpleFoam via WSL.

    Steps:
    1. Generate Gmsh .msh file
    2. Convert to OpenFOAM polyMesh via gmshToFoam (WSL)
    3. Fix boundary types
    4. Run simpleFoam (WSL)
    5. Parse force coefficients

    Returns:
        dict with success, log, force_coefficients
    """
    case_dir = Path(case_dir).resolve()
    msh_path = str(case_dir / "mesh.msh")

    # Step 1: Generate Gmsh .msh (with boundary layer)
    print(f"  [1/4] Generating Gmsh mesh (BL: {bl_layers} layers, ratio {bl_ratio})...")
    generate_gmsh_msh(polygon, msh_path, mesh_size, far_field_factor,
                      bl_layers=bl_layers, bl_ratio=bl_ratio)

    # Convert Windows path to WSL path
    wsl_case = str(case_dir).replace("C:\\", "/mnt/c/").replace("\\", "/")

    # Step 2-4: Run in WSL
    print("  [2/4] Converting mesh + running simpleFoam in WSL...")
    of_script = f"""#!/bin/bash
source /usr/lib/openfoam/openfoam2406/etc/bashrc 2>/dev/null
cd "{wsl_case}"

echo "=== gmshToFoam ==="
gmshToFoam mesh.msh 2>&1 | tail -5

if [ ! -f constant/polyMesh/points ]; then
    echo "ERROR: gmshToFoam failed"
    exit 1
fi

# Fix boundary types for 2D CFD
cd constant/polyMesh
python3 -c "
import re
with open('boundary','r') as f: txt=f.read()
txt = re.sub(r'(section[^{{]*{{[^}}]*type\s+)\w+', r'\g<1>wall', txt)
txt = re.sub(r'(frontAndBack[^{{]*{{[^}}]*type\s+)\w+', r'\g<1>empty', txt)
with open('boundary','w') as f: f.write(txt)
print('Boundary: section=wall, frontAndBack=empty, farfield=patch')
" 2>&1
cd "{wsl_case}"

echo "=== Starting solver ==="
# Detect solver from controlDict (strip Windows CR)
SOLVER=$(grep "application" system/controlDict | awk '{{print $2}}' | tr -d ';\\r\\n')
echo "Solver: $SOLVER"
$SOLVER 2>&1 || true

echo "=== Post-processing: vorticity ==="
postProcess -func vorticity -latestTime 2>&1 | tail -3 || true

echo "=== DONE ==="
"""
    script_path = case_dir / "run_of.sh"
    with open(script_path, "w", newline="\n") as f:
        f.write(of_script)

    try:
        result = subprocess.run(
            [r"C:\Windows\system32\wsl.exe", "-d", "Ubuntu", "--", "bash", f"{wsl_case}/run_of.sh"],
            capture_output=True, timeout=300,
        )
        log = result.stdout.decode("utf-8", errors="replace")
        log += result.stderr.decode("utf-8", errors="replace")
        success = "=== DONE ===" in log and "FOAM FATAL" not in log

        print(f"  [3/4] simpleFoam {'OK' if success else 'FAILED'}")

        # Step 4: Parse results
        force_coeffs = _parse_force_coeffs(case_dir)
        print(f"  [4/4] Force coefficients: {force_coeffs}")

        return {
            "success": success,
            "log": log[-3000:],
            "force_coefficients": force_coeffs,
        }
    except FileNotFoundError:
        return {"success": False, "log": "WSL not found", "force_coefficients": None}
    except subprocess.TimeoutExpired:
        return {"success": False, "log": "simpleFoam timed out (300s)", "force_coefficients": None}


def _parse_force_coeffs(case_dir):
    """Parse OpenFOAM forceCoeffs output."""
    case_dir = Path(case_dir)
    # Try multiple possible file names/paths
    candidates = [
        case_dir / "postProcessing" / "forces" / "0" / "forceCoeffs.dat",
        case_dir / "postProcessing" / "forces" / "0" / "coefficient.dat",
        case_dir / "postProcessing" / "forceCoeffs" / "0" / "forceCoeffs.dat",
        case_dir / "postProcessing" / "forceCoeffs" / "0" / "coefficient.dat",
    ]
    coeffs_file = None
    for c in candidates:
        if c.exists():
            coeffs_file = c
            break
    if not coeffs_file:
        # List what's in postProcessing for debugging
        pp = case_dir / "postProcessing"
        if pp.exists():
            print(f"  postProcessing contents: {list(pp.rglob('*'))[:10]}")
        return None

    try:
        with open(coeffs_file) as f:
            lines = f.readlines()

        # Parse column names from header (# Time  Cd  Cd(f)  Cd(r)  Cl ...)
        col_names = []
        for line in lines:
            if line.startswith("# Time") or line.strip().startswith("# Time"):
                col_names = line.lstrip("# ").split()
                break

        # Last non-comment line has the final values
        for line in reversed(lines):
            if not line.startswith("#") and line.strip():
                parts = line.split()
                if len(parts) < 2:
                    continue
                if col_names:
                    data = dict(zip(col_names, parts))
                    return {
                        "time": float(parts[0]),
                        "Cd": float(data.get("Cd", parts[1])),
                        "Cl": float(data.get("Cl", parts[min(4, len(parts)-1)])),
                        "Cm": float(data.get("CmPitch", parts[min(7, len(parts)-1)])),
                    }
                else:
                    # Fallback: old format (Time Cd Cl Cm)
                    if len(parts) >= 4:
                        return {
                            "time": float(parts[0]),
                            "Cd": float(parts[1]),
                            "Cl": float(parts[2]),
                            "Cm": float(parts[3]),
                        }
    except Exception:
        pass
    return None


def parse_cfd_results(case_dir, section_polygon=None):
    """Parse OpenFOAM results: cell centers, pressure, velocity."""
    case_dir = Path(case_dir)

    # Find all time directories
    time_dirs = []
    for d in case_dir.iterdir():
        if d.is_dir():
            try:
                float(d.name)
                time_dirs.append(d)
            except ValueError:
                pass
    if not time_dirs:
        return None
    time_dirs = sorted(time_dirs, key=lambda d: float(d.name))
    latest = time_dirs[-1]

    # Parse points (cell centers via mesh)
    points_file = case_dir / "constant" / "polyMesh" / "points"
    points = _parse_of_vector_field(points_file)
    if not points:
        return None

    # Parse fields
    pressure = _parse_of_scalar_field(latest / "p")
    velocity = _parse_of_vector_field(latest / "U")
    turb_k = _parse_of_scalar_field(latest / "k")

    # Parse vorticity (computed by postProcess -func vorticity)
    vorticity_vec = _parse_of_vector_field(latest / "vorticity")
    # Vorticity Z-component (for 2D: only ωz matters)
    vorticity_z = None
    if vorticity_vec:
        vorticity_z = [v[2] for v in vorticity_vec]

    # Compute derived fields
    speed = None
    if velocity:
        speed = [math.sqrt(v[0]**2 + v[1]**2 + v[2]**2) for v in velocity]

    # Compute cell centers from mesh (approximate: average of face centers)
    # For visualization, use the points directly (they're vertex positions)
    # We need cell center values, but p/U are already cell-centered in OpenFOAM

    # Get the 2D slice (z=0 layer only for visualization)
    nodes_2d = []
    p_2d = []
    u_2d = []
    for i, pt in enumerate(points):
        if abs(pt[2]) < 0.01:  # z ≈ 0 (bottom face)
            nodes_2d.append({"id": i, "x": round(pt[0], 4), "y": round(pt[1], 4)})

    # Cell-centered values: need cell→point mapping
    # Simpler: just return all values and let the client filter
    n_cells = len(pressure) if pressure else 0

    # Force coefficients
    force_coeffs = _parse_force_coeffs(case_dir)

    # Pressure range
    pMin = min(pressure) if pressure else 0
    pMax = max(pressure) if pressure else 0

    # Parse faces + owner for cell→node connectivity (2D slice)
    faces_file = case_dir / "constant" / "polyMesh" / "faces"
    owner_file = case_dir / "constant" / "polyMesh" / "owner"
    faces = _parse_of_faces(faces_file)
    owner = _parse_of_int_list(owner_file)

    # Build triangles from faces on z=0 plane
    # Clip to near-field only: far-field faces have nearly uniform flow and
    # would blow the triangle budget at high mesh density (was: fixed 20k cutoff).
    triangles_2d = []
    near_r2 = None
    sec_cx = sec_cy = 0.0
    if section_polygon:
        sx = [p[0] for p in section_polygon]
        sy = [p[1] for p in section_polygon]
        sec_cx = sum(sx) / len(sx)
        sec_cy = sum(sy) / len(sy)
        char_dim = max(max(sx) - min(sx), max(sy) - min(sy), 0.1)
        near_r2 = max(char_dim * 8, 10.0) ** 2  # keep 8× char_dim, min 10 m

    if faces and owner and points:
        for i, face in enumerate(faces):
            if len(face) < 3:
                continue
            # Check if face is on z=0 plane
            face_pts = [points[n] for n in face if n < len(points)]
            if not face_pts:
                continue
            avg_z = sum(p[2] for p in face_pts) / len(face_pts)
            if abs(avg_z) > 0.01:
                continue
            # Near-field filter — skip faces far from section
            if near_r2 is not None:
                cx = sum(p[0] for p in face_pts) / len(face_pts)
                cy = sum(p[1] for p in face_pts) / len(face_pts)
                if (cx - sec_cx) ** 2 + (cy - sec_cy) ** 2 > near_r2:
                    continue
            # Get cell (owner) pressure value
            cell_id = owner[i] if i < len(owner) else -1
            p_val = pressure[cell_id] if pressure and 0 <= cell_id < len(pressure) else 0
            # Add triangle fan for this face
            for j in range(1, len(face) - 1):
                triangles_2d.append({
                    "nodes": [face[0], face[j], face[j+1]],
                    "p": p_val,
                    "cell_id": cell_id,
                })

    # Available time steps for animation
    time_steps = [float(d.name) for d in time_dirs if float(d.name) > 0]

    # Force coefficient time series (for transient simulations)
    force_history = _parse_force_history(case_dir)

    # Compute ranges for all fields
    def field_range(vals):
        if not vals: return [0, 0]
        return [min(vals), max(vals)]

    return {
        "nodes": nodes_2d,
        "pressure": pressure[:n_cells] if pressure else [],
        "velocity": [(v[0], v[1]) for v in (velocity or [])[:n_cells]],
        "speed": speed[:n_cells] if speed else [],
        "vorticity": vorticity_z[:n_cells] if vorticity_z else [],
        "turb_k": turb_k[:n_cells] if turb_k else [],
        "triangles": triangles_2d[:80000],
        "n_cells": n_cells,
        "n_points": len(points),
        "p_range": field_range(pressure),
        "speed_range": field_range(speed),
        "vorticity_range": field_range(vorticity_z),
        "k_range": field_range(turb_k),
        "force_coefficients": force_coeffs,
        "time_steps": time_steps[:200],
        "force_history": force_history,
        "available_fields": [
            f for f in ["pressure", "speed", "vorticity", "turb_k"]
            if locals().get(f) or (f == "pressure" and pressure) or (f == "speed" and speed)
            or (f == "vorticity" and vorticity_z) or (f == "turb_k" and turb_k)
        ],
    }


def _parse_of_faces(filepath):
    """Parse OpenFOAM faces file: list of face→node indices."""
    if not filepath.exists():
        return None
    with open(filepath) as f:
        content = f.read()

    faces = []
    import re
    # Find the data block after the count
    match = re.search(r'(\d+)\s*\(', content)
    if not match:
        return None
    # Extract face definitions: N(n1 n2 n3 ...)
    for m in re.finditer(r'(\d+)\(([^)]+)\)', content[match.start():]):
        n = int(m.group(1))
        indices = [int(x) for x in m.group(2).split()]
        if len(indices) == n:
            faces.append(indices)
    return faces


def _parse_of_int_list(filepath):
    """Parse OpenFOAM integer list (owner, neighbour)."""
    if not filepath.exists():
        return None
    with open(filepath) as f:
        lines = f.readlines()

    values = []
    in_data = False
    for line in lines:
        line = line.strip()
        if line == '(':
            in_data = True
            continue
        if line == ')':
            break
        if in_data:
            try:
                values.append(int(line))
            except ValueError:
                pass
    return values


def _parse_force_history(case_dir):
    """Parse forceCoeffs time series for transient results."""
    case_dir = Path(case_dir)
    candidates = [
        case_dir / "postProcessing" / "forces" / "0" / "coefficient.dat",
        case_dir / "postProcessing" / "forces" / "0" / "forceCoeffs.dat",
        case_dir / "postProcessing" / "forceCoeffs" / "0" / "coefficient.dat",
    ]
    coeffs_file = None
    for c in candidates:
        if c.exists():
            coeffs_file = c
            break
    if not coeffs_file:
        return None

    try:
        times, cds, cls, cms = [], [], [], []
        with open(coeffs_file) as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 4:
                    times.append(float(parts[0]))
                    cds.append(float(parts[1]))
                    cls.append(float(parts[2]))
                    cms.append(float(parts[3]))
        # Subsample if too many points
        n = len(times)
        if n > 500:
            step = n // 500
            times = times[::step]
            cds = cds[::step]
            cls = cls[::step]
            cms = cms[::step]
        return {"time": times, "Cd": cds, "Cl": cls, "Cm": cms}
    except Exception:
        return None


def _parse_of_scalar_field(filepath):
    """Parse OpenFOAM scalar field file."""
    if not filepath.exists():
        return None
    with open(filepath) as f:
        lines = f.readlines()

    values = []
    in_data = False
    for line in lines:
        line = line.strip()
        if line == '(':
            in_data = True
            continue
        if line == ')' or line.startswith(');'):
            break
        if in_data:
            try:
                values.append(float(line))
            except ValueError:
                pass
    return values


def _parse_of_vector_field(filepath):
    """Parse OpenFOAM vector field file (points, U)."""
    if not filepath.exists():
        return None
    with open(filepath) as f:
        lines = f.readlines()

    values = []
    in_data = False
    for line in lines:
        line = line.strip()
        if line == '(':
            in_data = True
            continue
        if line == ')' or line.startswith(');'):
            if in_data and values:
                break
            continue
        if in_data and line.startswith('(') and line.endswith(')'):
            parts = line[1:-1].split()
            if len(parts) >= 3:
                try:
                    values.append((float(parts[0]), float(parts[1]), float(parts[2])))
                except ValueError:
                    pass
    return values


###############################################################################
# ── 3D Building CFD ─────────────────────────────────────────────────────────
###############################################################################


def generate_gmsh_msh_3d(footprint, height, msh_path, mesh_size=None,
                          domain_factors=None, buildings=None):
    """Generate a 3D Gmsh mesh for building aerodynamics (OCC Boolean).

    Args:
        footprint: List of [x, y] vertices (single building, for backward compat)
        height: Building height [m] (single building or max height)
        msh_path: Output .msh file path
        mesh_size: Element size near building (default H/20)
        domain_factors: dict with upstream, downstream, lateral, top multipliers
        buildings: List of {footprint: [[x,y],...], height: H} dicts (multi-building mode)

    Creates a box domain with building-shaped cutout(s) using OCC BooleanDifference.
    """
    # Build list of buildings
    if buildings and len(buildings) > 0:
        bld_list = buildings
        H = max(b["height"] for b in bld_list)
    else:
        bld_list = [{"footprint": footprint, "height": height}]
        H = height

    if mesh_size is None:
        mesh_size = max(H / 25, 0.3)

    # Compute overall bounding box of all buildings
    all_xs, all_ys = [], []
    for b in bld_list:
        all_xs.extend(p[0] for p in b["footprint"])
        all_ys.extend(p[1] for p in b["footprint"])
    cx = (min(all_xs) + max(all_xs)) / 2
    cy = (min(all_ys) + max(all_ys)) / 2
    char_w = max(all_xs) - min(all_xs)
    char_d = max(all_ys) - min(all_ys)
    char_dim = max(char_w, char_d, H)

    df = domain_factors or {}
    f_up = df.get("upstream", 3)
    f_down = df.get("downstream", 8)
    f_lat = df.get("lateral", 3)
    f_top = df.get("top", 3)

    # Domain bounds — based on overall extent, not single building
    x_min = min(all_xs) - f_up * H
    x_max = max(all_xs) + f_down * H
    y_min = min(all_ys) - f_lat * H
    y_max = max(all_ys) + f_lat * H
    z_min = 0
    z_max = f_top * H

    ms_far = char_dim * 0.8
    ms_bld = mesh_size

    script = f"""
import sys, json, math
sys.path.insert(0, r'{str(Path(__file__).resolve().parent.parent)}')
import gmsh

gmsh.initialize()
gmsh.option.setNumber("General.Verbosity", 1)
gmsh.model.add("cfd3d")
occ = gmsh.model.occ

# Domain box
domain = occ.addBox({x_min}, {y_min}, {z_min},
                    {x_max - x_min}, {y_max - y_min}, {z_max - z_min})

# Buildings: extrude each footprint polygon
buildings = {json.dumps(bld_list)}
print(f"BUILDINGS: {{len(buildings)}} buildings to mesh")
building_vols = []
for idx, bld in enumerate(buildings):
    fp = bld["footprint"]
    bH = bld["height"]
    print(f"  Building {{idx}}: {{len(fp)}} pts, H={{bH}}m")
    pts = []
    for x, y in fp:
        pts.append(occ.addPoint(x, y, 0))
    lines = []
    n = len(pts)
    for i in range(n):
        lines.append(occ.addLine(pts[i], pts[(i+1) % n]))
    loop = occ.addCurveLoop(lines)
    face = occ.addPlaneSurface([loop])
    ext = occ.extrude([(2, face)], 0, 0, bH)
    for dim, tag in ext:
        if dim == 3:
            building_vols.append((3, tag))
            break

print(f"BOOLEAN CUT: domain - {{len(building_vols)}} volumes")
# Boolean cut: domain - all buildings at once
result, result_map = occ.cut([(3, domain)], building_vols,
                              removeObject=True, removeTool=True)
occ.synchronize()
print(f"RESULT: {{len(result)}} volume(s) after cut")

# Identify boundary surfaces by their bounding box center
fluid_vol = result[0][1]
surfs = gmsh.model.getBoundary([(3, fluid_vol)], oriented=False)
surf_tags = [s[1] for s in surfs]

inlet_tags, outlet_tags, ground_tags, top_tags, side_tags, building_tags = [], [], [], [], [], []

for stag in surf_tags:
    bb = gmsh.model.getBoundingBox(2, stag)
    sx_min, sy_min, sz_min, sx_max, sy_max, sz_max = bb
    sx_c = (sx_min + sx_max) / 2
    sy_c = (sy_min + sy_max) / 2
    sz_c = (sz_min + sz_max) / 2
    sx_span = sx_max - sx_min
    sy_span = sy_max - sy_min
    sz_span = sz_max - sz_min
    tol = 0.1

    # Classify surfaces
    if abs(sx_min - {x_min}) < tol and abs(sx_max - {x_min}) < tol:
        inlet_tags.append(stag)
    elif abs(sx_min - {x_max}) < tol and abs(sx_max - {x_max}) < tol:
        outlet_tags.append(stag)
    elif abs(sz_min) < tol and abs(sz_max) < tol:
        ground_tags.append(stag)
    elif abs(sz_min - {z_max}) < tol and abs(sz_max - {z_max}) < tol:
        top_tags.append(stag)
    elif abs(sy_min - {y_min}) < tol and abs(sy_max - {y_min}) < tol:
        side_tags.append(stag)
    elif abs(sy_min - {y_max}) < tol and abs(sy_max - {y_max}) < tol:
        side_tags.append(stag)
    else:
        # Must be a building surface (wall or roof)
        building_tags.append(stag)

print(f"Surfaces: inlet={{len(inlet_tags)}}, outlet={{len(outlet_tags)}}, "
      f"ground={{len(ground_tags)}}, top={{len(top_tags)}}, sides={{len(side_tags)}}, "
      f"building={{len(building_tags)}}")

# Physical groups
gmsh.model.addPhysicalGroup(3, [fluid_vol], tag=1, name="internal")
if inlet_tags:   gmsh.model.addPhysicalGroup(2, inlet_tags,   tag=10, name="inlet")
if outlet_tags:  gmsh.model.addPhysicalGroup(2, outlet_tags,  tag=11, name="outlet")
if ground_tags:  gmsh.model.addPhysicalGroup(2, ground_tags,  tag=12, name="ground")
if top_tags:     gmsh.model.addPhysicalGroup(2, top_tags,     tag=13, name="top")
if side_tags:    gmsh.model.addPhysicalGroup(2, side_tags,    tag=14, name="sides")
if building_tags: gmsh.model.addPhysicalGroup(2, building_tags, tag=15, name="building")

# Mesh sizing: fine near building, coarse at far-field
bld_curves = []
for stag in building_tags:
    edges = gmsh.model.getBoundary([(2, stag)], oriented=False)
    bld_curves.extend([abs(e[1]) for e in edges])
bld_curves = list(set(bld_curves))

if bld_curves:
    df = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(df, "CurvesList", bld_curves)
    gmsh.model.mesh.field.setNumbers(df, "SurfacesList", building_tags)
    tf = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(tf, "InField", df)
    gmsh.model.mesh.field.setNumber(tf, "SizeMin", {ms_bld})
    gmsh.model.mesh.field.setNumber(tf, "SizeMax", {ms_far})
    gmsh.model.mesh.field.setNumber(tf, "DistMin", {H * 0.5})
    gmsh.model.mesh.field.setNumber(tf, "DistMax", {H * 5})
    gmsh.model.mesh.field.setAsBackgroundMesh(tf)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)

gmsh.model.mesh.generate(3)

# Stats
node_data = gmsh.model.mesh.getNodes()
n_nodes = len(node_data[0])
elem_types, elem_tags, _ = gmsh.model.mesh.getElements(3)
n_cells = sum(len(t) for t in elem_tags)
print(f"MESH3D_OK nodes={{n_nodes}} cells={{n_cells}}")

gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
gmsh.write(r'{msh_path}')
gmsh.finalize()
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=120,
    )
    stdout = result.stdout
    stderr = result.stderr
    # Forward Gmsh subprocess output to parent stdout
    for line in stdout.splitlines():
        if any(kw in line for kw in ["BUILDINGS", "BOOLEAN", "RESULT", "Building", "MESH3D"]):
            print(f"  [Gmsh] {line}")
    if "MESH3D_OK" not in stdout:
        raise RuntimeError(f"3D mesh generation failed:\n{stdout[-500:]}\n{stderr[-500:]}")
    # Parse stats
    for line in stdout.splitlines():
        if "MESH3D_OK" in line:
            parts = line.split()
            n_nodes = int(parts[1].split("=")[1])
            n_cells = int(parts[2].split("=")[1])
            return {
                "n_nodes": n_nodes,
                "n_cells": n_cells,
                "domain": {"x": [x_min, x_max], "y": [y_min, y_max], "z": [z_min, z_max]},
                "building_height": H,
                "mesh_size": mesh_size,
                "char_dim": char_dim,
            }
    return {"n_nodes": 0, "n_cells": 0}


def prepare_stl_case(glb_or_stl_path, case_dir, scale=1.0, wind_speed=10.0,
                      z0=0.1, mesh_size=None, domain_factor=3, n_procs=4,
                      n_iterations=500, rot_x=0, rot_y=0, rot_z=0):
    """Prepare a complete OpenFOAM case from a GLB/STL file using snappyHexMesh.

    Pipeline: GLB→STL → blockMesh (background) → snappyHexMesh → simpleFoam

    Args:
        glb_or_stl_path: Path to .glb or .stl file
        case_dir: Output case directory
        scale: Scale factor for geometry (1.0 = as-is)
    Returns:
        dict with stl_path, bounds, char_dim
    """
    import trimesh

    src = Path(glb_or_stl_path)
    case_dir = Path(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)

    # Load and optionally scale geometry
    scene = trimesh.load(str(src))
    if isinstance(scene, trimesh.Scene):
        mesh = trimesh.util.concatenate(list(scene.geometry.values()))
    else:
        mesh = scene
    if scale != 1.0:
        mesh.apply_scale(scale)

    # Apply rotation (degrees → radians) around mesh center
    import numpy as np
    from scipy.spatial.transform import Rotation as R
    if rot_x or rot_y or rot_z:
        angles = [math.radians(rot_x), math.radians(rot_y), math.radians(rot_z)]
        rot_matrix = R.from_euler('xyz', angles).as_matrix()
        center = mesh.centroid.copy()
        mesh.vertices -= center
        mesh.vertices = (rot_matrix @ mesh.vertices.T).T
        mesh.vertices += center
        print(f"  Rotated model: ({rot_x}°, {rot_y}°, {rot_z}°)")

    # Center model at origin: XY centered, Z_min = 0 (on ground)
    bb = mesh.bounds
    cx = (bb[0][0] + bb[1][0]) / 2
    cy = (bb[0][1] + bb[1][1]) / 2
    z_min = bb[0][2]
    mesh.apply_translation([-cx, -cy, -z_min])
    print(f"  Centered model: offset=({-cx:.2f}, {-cy:.2f}, {-z_min:.2f})")

    # Export STL into case
    stl_dir = case_dir / "constant" / "triSurface"
    stl_dir.mkdir(parents=True, exist_ok=True)
    stl_path = stl_dir / "building.stl"
    mesh.export(str(stl_path))

    bb = mesh.bounds  # re-read after centering
    cx = 0.0
    cy = 0.0
    H = bb[1][2] - bb[0][2]
    char_dim = max(bb[1][0] - bb[0][0], bb[1][1] - bb[0][1], H)

    if mesh_size is None:
        mesh_size = max(char_dim / 20, 1.0)

    f = domain_factor
    x_min = cx - f * char_dim
    x_max = cx + f * 2.5 * char_dim
    y_min = cy - f * char_dim
    y_max = cy + f * char_dim
    z_min = min(bb[0][2], 0) - 1
    z_max = bb[1][2] + f * char_dim

    # Background mesh cells (blockMesh) — coarser far-field, snappy refines near body
    bg_size = mesh_size * 8  # background ~8× surface mesh → snappy does the work
    nx = max(6, int((x_max - x_min) / bg_size))
    ny = max(6, int((y_max - y_min) / bg_size))
    nz = max(6, int((z_max - z_min) / bg_size))

    # Create OpenFOAM case with ABL + snappyHexMesh
    create_openfoam_case_3d(
        footprint=[[bb[0][0], bb[0][1]], [bb[1][0], bb[0][1]],
                    [bb[1][0], bb[1][1]], [bb[0][0], bb[1][1]]],
        height=H, wind_speed=wind_speed, z0=z0,
        output_dir=str(case_dir), n_iterations=n_iterations, n_procs=n_procs,
    )

    # ── blockMeshDict ──
    _write_of_file(case_dir / "system" / "blockMeshDict", None, None, f"""
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      blockMeshDict;
}}
scale 1;
vertices
(
    ({x_min} {y_min} {z_min})
    ({x_max} {y_min} {z_min})
    ({x_max} {y_max} {z_min})
    ({x_min} {y_max} {z_min})
    ({x_min} {y_min} {z_max})
    ({x_max} {y_min} {z_max})
    ({x_max} {y_max} {z_max})
    ({x_min} {y_max} {z_max})
);
blocks ( hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading (1 1 1) );
edges ( );
boundary
(
    inlet  {{ type patch; faces ( (0 4 7 3) ); }}
    outlet {{ type patch; faces ( (1 2 6 5) ); }}
    ground {{ type wall;  faces ( (0 1 2 3) ); }}
    top    {{ type patch; faces ( (4 5 6 7) ); }}
    sides  {{ type patch; faces ( (0 1 5 4) (2 3 7 6) ); }}
);
""")

    # ── snappyHexMeshDict ──
    # Surface refinement: enough levels to go from bg_size down to mesh_size
    surf_level = max(2, min(6, int(round(math.log2(bg_size / mesh_size)))))
    # Near-body volume refinement zone: 1.5× char_dim around building
    near_r = char_dim * 1.5
    near_level = max(1, surf_level - 2)
    # Wake region: elongated downstream, medium refinement
    wake_level = max(1, surf_level - 3)

    print(f"  snappy: bg={bg_size:.1f}m, surface level={surf_level}-{surf_level+1}, "
          f"near={near_level}, wake={wake_level}")

    _write_of_file(case_dir / "system" / "snappyHexMeshDict", None, None, f"""
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      snappyHexMeshDict;
}}
castellatedMesh true;
snap            true;
addLayers       true;

geometry
{{
    building.stl
    {{
        type triSurfaceMesh;
        name building;
    }}
    nearBody
    {{
        type searchableBox;
        min ({bb[0][0] - near_r} {bb[0][1] - near_r} {max(bb[0][2] - 1, z_min)});
        max ({bb[1][0] + near_r} {bb[1][1] + near_r} {bb[1][2] + near_r});
    }}
    wakeRegion
    {{
        type searchableBox;
        min ({bb[0][0] - near_r * 0.5} {bb[0][1] - near_r * 0.8} {max(bb[0][2] - 1, z_min)});
        max ({bb[1][0] + char_dim * 3} {bb[1][1] + near_r * 0.8} {bb[1][2] + near_r * 0.5});
    }}
}}

castellatedMeshControls
{{
    maxLocalCells   3000000;
    maxGlobalCells  6000000;
    minRefinementCells 5;
    maxLoadUnbalance 0.10;
    nCellsBetweenLevels 4;
    features ( );
    refinementSurfaces
    {{
        building
        {{
            level ({surf_level} {surf_level + 1});
            patchInfo {{ type wall; }}
        }}
    }}
    resolveFeatureAngle 20;
    refinementRegions
    {{
        nearBody
        {{
            mode inside;
            levels (({near_level} {near_level}));
        }}
        wakeRegion
        {{
            mode inside;
            levels (({wake_level} {wake_level}));
        }}
    }}
    locationInMesh ({cx + char_dim * 2} {cy} {(z_min + z_max) / 2});
    allowFreeStandingZoneFaces true;
}}

snapControls
{{
    nSmoothPatch 5;
    tolerance 2.0;
    nSolveIter 200;
    nRelaxIter 8;
    nFeatureSnapIter 15;
    implicitFeatureSnap true;
    explicitFeatureSnap false;
    multiRegionFeatureSnap false;
}}

addLayersControls
{{
    relativeSizes true;
    layers
    {{
        building
        {{
            nSurfaceLayers 3;
        }}
    }}
    expansionRatio 1.3;
    finalLayerThickness 0.3;
    minThickness 0.05;
    nGrow 0;
    featureAngle 130;
    slipFeatureAngle 30;
    nRelaxIter 5;
    nSmoothSurfaceNormals 3;
    nSmoothNormals 5;
    nSmoothThickness 10;
    maxFaceThicknessRatio 0.5;
    maxThicknessToMedialRatio 0.3;
    minMedialAxisAngle 90;
    nBufferCellsNoExtrude 0;
    nLayerIter 50;
}}

meshQualityControls
{{
    maxNonOrtho 65;
    maxBoundarySkewness 20;
    maxInternalSkewness 4;
    maxConcave 80;
    minVol 1e-13;
    minTetQuality -1e30;
    minArea -1;
    minTwist 0.02;
    minDeterminant 0.001;
    minFaceWeight 0.05;
    minVolRatio 0.01;
    minTriangleTwist -1;
    nSmoothScale 4;
    errorReduction 0.75;
    relaxed {{ maxNonOrtho 75; }}
}}

writeFlags ( );
mergeTolerance 1e-6;
""")

    # Save metadata
    meta_path = case_dir / "case_meta.json"
    meta = {
        "mode": "3d_stl",
        "stl_source": str(src),
        "height": H,
        "char_dim": char_dim,
        "wind_speed": wind_speed,
        "z0": z0,
        "bounds": {"min": bb[0].tolist(), "max": bb[1].tolist()},
        "n_procs": n_procs,
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    return {
        "case_dir": str(case_dir),
        "stl_path": str(stl_path),
        "bounds": {"min": bb[0].tolist(), "max": bb[1].tolist()},
        "char_dim": char_dim,
        "height": H,
        "bg_cells": f"{nx}x{ny}x{nz}",
        "refine_level": surf_level,
    }


def run_openfoam_3d_stl(case_dir, n_procs=4):
    """Run OpenFOAM with snappyHexMesh for STL-based geometry."""
    case_dir = Path(case_dir).resolve()
    wsl_case = str(case_dir).replace("C:\\", "/mnt/c/").replace("\\", "/")

    of_script = f"""#!/bin/bash
source /usr/lib/openfoam/openfoam2406/etc/bashrc 2>/dev/null
cd "{wsl_case}"

echo "=== blockMesh ==="
blockMesh 2>&1 | tail -5

echo "=== snappyHexMesh ==="
snappyHexMesh -overwrite 2>&1 | tail -10

# Fix boundary: building patch from snappy becomes wall
cd constant/polyMesh
if [ -f boundary ]; then
python3 -c "
import re
with open('boundary','r') as f: txt=f.read()
txt = re.sub(r'(building[^{{]*{{[^}}]*type\\s+)\\w+', r'\\g<1>wall', txt)
txt = re.sub(r'(ground[^{{]*{{[^}}]*type\\s+)\\w+', r'\\g<1>wall', txt)
with open('boundary','w') as f: f.write(txt)
print('Boundary patched')
" 2>&1
fi
cd "{wsl_case}"

echo "=== simpleFoam ({n_procs} procs) ==="
{"decomposePar 2>&1 | tail -3 && mpirun --oversubscribe -np " + str(n_procs) + " simpleFoam -parallel 2>&1 || simpleFoam 2>&1" if n_procs > 1 else "simpleFoam 2>&1"} || true

{"reconstructPar -latestTime 2>&1 | tail -3" if n_procs > 1 else ""}

echo "=== Post-processing ==="
postProcess -func writeCellCentres -latestTime 2>&1 | tail -3 || true

echo "=== DONE ==="
"""
    script_path = case_dir / "run_snappy.sh"
    with open(script_path, "w", newline="\n") as f:
        f.write(of_script)

    try:
        result = subprocess.run(
            [r"C:\Windows\system32\wsl.exe", "-d", "Ubuntu", "--", "bash", f"{wsl_case}/run_snappy.sh"],
            capture_output=True, timeout=900,
        )
        log = result.stdout.decode("utf-8", errors="replace")
        log += result.stderr.decode("utf-8", errors="replace")
        success = "=== DONE ===" in log and "FOAM FATAL" not in log

        force_coeffs = _parse_force_coeffs(case_dir)

        # Parse mesh cell count from polyMesh/owner (one entry per cell)
        n_cells = 0
        n_points = 0
        owner_file = case_dir / "constant" / "polyMesh" / "owner"
        points_file = case_dir / "constant" / "polyMesh" / "points"
        if owner_file.exists():
            owner_data = _parse_of_int_list(owner_file)
            if owner_data:
                n_cells = max(owner_data) + 1
        if points_file.exists():
            pts = _parse_of_vector_field(points_file)
            if pts:
                n_points = len(pts)

        return {
            "success": success,
            "log": log[-3000:],
            "force_coefficients": force_coeffs,
            "n_cells": n_cells,
            "n_points": n_points,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "log": "Timed out (900s)", "force_coefficients": None}


def create_openfoam_case_3d(footprint, height, wind_speed=10.0, wind_angle=0.0,
                             z0=0.1, zref=None, nu=1.5e-5,
                             output_dir=None, n_iterations=1000, n_procs=4,
                             buildings=None):
    """Create a 3D OpenFOAM case for building aerodynamics with ABL inlet."""
    H = max(b["height"] for b in buildings) if buildings else height
    if zref is None:
        zref = H  # Reference height = building height
    if output_dir is None:
        import tempfile
        output_dir = tempfile.mkdtemp(prefix="cfd3d_")
    case_dir = Path(output_dir)

    # Wind direction
    rad = math.radians(wind_angle)
    flow_x = math.cos(rad)
    flow_y = math.sin(rad)

    # Turbulence parameters — ABL log-law based (z0-dependent)
    kappa = 0.41
    u_star = wind_speed * kappa / math.log(max(zref, 1.0) / max(z0, 0.001))
    k_inlet = u_star ** 2 / math.sqrt(0.09)
    epsilon_inlet = u_star ** 3 / (kappa * max(zref, 1.0))
    nut_inlet = 0.09 * k_inlet ** 2 / max(epsilon_inlet, 1e-10)

    # Footprint dimensions for force coefficients (all buildings)
    if buildings:
        xs = [p[0] for b in buildings for p in b["footprint"]]
        ys = [p[1] for b in buildings for p in b["footprint"]]
    else:
        xs = [p[0] for p in footprint]
        ys = [p[1] for p in footprint]
    char_w = max(xs) - min(xs)
    char_d = max(ys) - min(ys)
    # Projected frontal area perpendicular to wind direction
    frontal_width = char_w * abs(math.sin(rad)) + char_d * abs(math.cos(rad))
    a_ref = frontal_width * H

    Re = wind_speed * H / nu
    print(f"  3D CFD: H={H}m, v={wind_speed}m/s, Re={Re:.0f}, z0={z0}m")

    for d in ["0", "constant", "system", "constant/polyMesh"]:
        (case_dir / d).mkdir(parents=True, exist_ok=True)

    # ── ABL include file ──
    (case_dir / "0" / "include").mkdir(exist_ok=True)
    with open(case_dir / "0" / "include" / "ABLConditions", "w", newline="\n") as f:
        f.write(f"""Uref    {wind_speed};
Zref    {zref};
zDir    (0 0 1);
flowDir ({flow_x} {flow_y} 0);
z0      uniform {z0};
d       uniform 0.0;
""")

    # ── 0/U ──
    _write_of_file(case_dir / "0" / "U", "volVectorField", "U", f"""
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform ({wind_speed * flow_x} {wind_speed * flow_y} 0);
boundaryField
{{
    inlet
    {{
        type            atmBoundaryLayerInletVelocity;
        #include        "include/ABLConditions"
    }}
    outlet
    {{
        type            inletOutlet;
        inletValue      uniform (0 0 0);
        value           $internalField;
    }}
    ground
    {{
        type            noSlip;
    }}
    top
    {{
        type            slip;
    }}
    sides
    {{
        type            slip;
    }}
    building
    {{
        type            noSlip;
    }}
}}
""")

    # ── 0/p ──
    _write_of_file(case_dir / "0" / "p", "volScalarField", "p", f"""
dimensions      [0 2 -2 0 0 0 0];
internalField   uniform 0;
boundaryField
{{
    inlet
    {{
        type            zeroGradient;
    }}
    outlet
    {{
        type            fixedValue;
        value           uniform 0;
    }}
    ground
    {{
        type            zeroGradient;
    }}
    top
    {{
        type            slip;
    }}
    sides
    {{
        type            slip;
    }}
    building
    {{
        type            zeroGradient;
    }}
}}
""")

    # ── 0/k ──
    _write_of_file(case_dir / "0" / "k", "volScalarField", "k", f"""
dimensions      [0 2 -2 0 0 0 0];
internalField   uniform {k_inlet};
boundaryField
{{
    inlet
    {{
        type            atmBoundaryLayerInletK;
        #include        "include/ABLConditions"
    }}
    outlet
    {{
        type            inletOutlet;
        inletValue      uniform {k_inlet};
        value           $internalField;
    }}
    ground
    {{
        type            kqRWallFunction;
        value           uniform {k_inlet};
    }}
    top
    {{
        type            slip;
    }}
    sides
    {{
        type            slip;
    }}
    building
    {{
        type            kqRWallFunction;
        value           uniform {k_inlet};
    }}
}}
""")

    # ── 0/epsilon ──
    _write_of_file(case_dir / "0" / "epsilon", "volScalarField", "epsilon", f"""
dimensions      [0 2 -3 0 0 0 0];
internalField   uniform {epsilon_inlet};
boundaryField
{{
    inlet
    {{
        type            atmBoundaryLayerInletEpsilon;
        #include        "include/ABLConditions"
    }}
    outlet
    {{
        type            inletOutlet;
        inletValue      uniform {epsilon_inlet};
        value           $internalField;
    }}
    ground
    {{
        type            epsilonWallFunction;
        value           uniform {epsilon_inlet};
    }}
    top
    {{
        type            slip;
    }}
    sides
    {{
        type            slip;
    }}
    building
    {{
        type            epsilonWallFunction;
        value           uniform {epsilon_inlet};
    }}
}}
""")

    # ── 0/nut ──
    _write_of_file(case_dir / "0" / "nut", "volScalarField", "nut", f"""
dimensions      [0 2 -1 0 0 0 0];
internalField   uniform {nut_inlet};
boundaryField
{{
    inlet
    {{
        type            calculated;
        value           uniform 0;
    }}
    outlet
    {{
        type            calculated;
        value           uniform 0;
    }}
    ground
    {{
        type            nutUSpaldingWallFunction;
        value           uniform 0;
    }}
    top
    {{
        type            calculated;
        value           uniform 0;
    }}
    sides
    {{
        type            calculated;
        value           uniform 0;
    }}
    building
    {{
        type            nutUSpaldingWallFunction;
        value           uniform 0;
    }}
}}
""")

    # ── constant/ ──
    _write_of_file(case_dir / "constant" / "transportProperties", None, None, f"""
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      transportProperties;
}}
transportModel  Newtonian;
nu              [0 2 -1 0 0 0 0] {nu};
""")

    _write_of_file(case_dir / "constant" / "turbulenceProperties", None, None, """
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      turbulenceProperties;
}
simulationType  RAS;
RAS
{
    RASModel        kEpsilon;
    turbulence      on;
    printCoeffs     on;
}
""")

    # ── system/ ──
    _write_of_file(case_dir / "system" / "controlDict", None, None, f"""
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}}
libs            ("libatmosphericModels.so");
application     simpleFoam;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         {n_iterations};
deltaT          1;
writeControl    timeStep;
writeInterval   {n_iterations};
purgeWrite      1;
writeFormat     ascii;
writePrecision  8;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;

functions
{{
    forces
    {{
        type            forceCoeffs;
        libs            ("libforces.so");
        writeControl    timeStep;
        writeInterval   1;
        patches         (building);
        rho             rhoInf;
        rhoInf          1.225;
        CofR            (0 0 {H / 2});
        liftDir         ({-flow_y} {flow_x} 0);
        dragDir         ({flow_x} {flow_y} 0);
        pitchAxis       (0 0 1);
        magUInf         {wind_speed};
        lRef            {H};
        Aref            {a_ref};
    }}
}}
""")

    _write_of_file(case_dir / "system" / "fvSchemes", None, None, """
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSchemes;
}
ddtSchemes      { default steadyState; }
gradSchemes     { default Gauss linear; }
divSchemes
{
    default             none;
    div(phi,U)          bounded Gauss linearUpwind grad(U);
    div(phi,k)          bounded Gauss upwind;
    div(phi,epsilon)    bounded Gauss upwind;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes { default corrected; }
""")

    _write_of_file(case_dir / "system" / "fvSolution", None, None, f"""
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSolution;
}}
solvers
{{
    p   {{ solver GAMG; smoother GaussSeidel; tolerance 1e-06; relTol 0.01; }}
    U   {{ solver smoothSolver; smoother GaussSeidel; tolerance 1e-07; relTol 0.01; }}
    k   {{ solver smoothSolver; smoother GaussSeidel; tolerance 1e-07; relTol 0.01; }}
    epsilon {{ solver smoothSolver; smoother GaussSeidel; tolerance 1e-07; relTol 0.01; }}
}}
SIMPLE
{{
    nNonOrthogonalCorrectors 1;
    pRefCell 0;
    pRefValue 0;
    residualControl {{ p 1e-4; U 1e-4; k 1e-4; epsilon 1e-4; }}
}}
relaxationFactors
{{
    fields {{ p 0.3; }}
    equations {{ U 0.7; k 0.7; epsilon 0.7; }}
}}
""")

    # ── decomposeParDict for parallel runs ──
    if n_procs > 1:
        _write_of_file(case_dir / "system" / "decomposeParDict", None, None, f"""
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      decomposeParDict;
}}
numberOfSubdomains {n_procs};
method          scotch;
""")

    # Save metadata
    meta = {
        "mode": "3d",
        "footprint": footprint,
        "height": H,
        "wind_speed": wind_speed,
        "wind_angle": wind_angle,
        "z0": z0,
        "Re": Re,
        "n_procs": n_procs,
    }
    if buildings:
        meta["buildings"] = buildings
    with open(case_dir / "case_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print(f"  3D OpenFOAM case created: {case_dir}")
    return str(case_dir)


def run_openfoam_3d(case_dir, footprint, height, mesh_size=None,
                     domain_factors=None, n_procs=4, buildings=None):
    """Run 3D OpenFOAM building simulation via WSL."""
    case_dir = Path(case_dir).resolve()
    msh_path = str(case_dir / "mesh.msh")

    print("  [1/4] Generating 3D Gmsh mesh...")
    mesh_stats = generate_gmsh_msh_3d(footprint, height, msh_path,
                                       mesh_size=mesh_size,
                                       domain_factors=domain_factors,
                                       buildings=buildings)
    print(f"  Mesh: {mesh_stats['n_nodes']} nodes, {mesh_stats['n_cells']} cells")

    wsl_case = str(case_dir).replace("C:\\", "/mnt/c/").replace("\\", "/")

    use_parallel = n_procs > 1
    print(f"  [2/4] Converting mesh + running simpleFoam in WSL ({n_procs} procs)...")
    of_script = f"""#!/bin/bash
source /usr/lib/openfoam/openfoam2406/etc/bashrc 2>/dev/null
cd "{wsl_case}"

echo "=== gmshToFoam ==="
gmshToFoam mesh.msh 2>&1 | tail -5

if [ ! -f constant/polyMesh/points ]; then
    echo "ERROR: gmshToFoam failed"
    exit 1
fi

# Fix boundary types
cd constant/polyMesh
python3 -c "
import re
with open('boundary','r') as f: txt=f.read()
txt = re.sub(r'(inlet[^{{]*{{[^}}]*type\\s+)\\w+', r'\\g<1>patch', txt)
txt = re.sub(r'(outlet[^{{]*{{[^}}]*type\\s+)\\w+', r'\\g<1>patch', txt)
txt = re.sub(r'(ground[^{{]*{{[^}}]*type\\s+)\\w+', r'\\g<1>wall', txt)
txt = re.sub(r'(top[^{{]*{{[^}}]*type\\s+)\\w+', r'\\g<1>patch', txt)
txt = re.sub(r'(sides[^{{]*{{[^}}]*type\\s+)\\w+', r'\\g<1>patch', txt)
txt = re.sub(r'(building[^{{]*{{[^}}]*type\\s+)\\w+', r'\\g<1>wall', txt)
with open('boundary','w') as f: f.write(txt)
print('Boundary types patched')
" 2>&1
cd "{wsl_case}"

echo "=== checkMesh ==="
checkMesh 2>&1 | grep -E "cells|faces|Maximum|Minimum|FAILED|OK|WARNING" || true

{"" if not use_parallel else f'''echo "=== decomposePar ({n_procs} domains) ==="
decomposePar 2>&1 | tail -5
'''}
echo "=== Starting simpleFoam ==="
{"mpirun --oversubscribe -np " + str(n_procs) + " simpleFoam -parallel 2>&1 || simpleFoam 2>&1" if use_parallel else "simpleFoam 2>&1"} || true

{"" if not use_parallel else '''echo "=== reconstructPar ==="
reconstructPar -latestTime 2>&1 | tail -3
'''}
echo "=== Post-processing: writeCellCentres ==="
postProcess -func writeCellCentres -latestTime 2>&1 | tail -3 || true

echo "=== Post-processing: vorticity ==="
postProcess -func vorticity -latestTime 2>&1 | tail -3 || true

echo "=== DONE ==="
"""
    script_path = case_dir / "run_of_3d.sh"
    with open(script_path, "w", newline="\n") as f:
        f.write(of_script)

    try:
        result = subprocess.run(
            [r"C:\Windows\system32\wsl.exe", "-d", "Ubuntu", "--", "bash", f"{wsl_case}/run_of_3d.sh"],
            capture_output=True, timeout=600,
        )
        log = result.stdout.decode("utf-8", errors="replace")
        log += result.stderr.decode("utf-8", errors="replace")
        success = "=== DONE ===" in log and "FOAM FATAL" not in log

        print(f"  [3/4] simpleFoam {'OK' if success else 'FAILED'}")

        force_coeffs = _parse_force_coeffs(case_dir)
        print(f"  [4/4] Force coefficients: {force_coeffs}")

        return {
            "success": success,
            "log": log[-3000:],
            "force_coefficients": force_coeffs,
            "mesh_stats": mesh_stats,
        }
    except FileNotFoundError:
        return {"success": False, "log": "WSL not found", "force_coefficients": None}
    except subprocess.TimeoutExpired:
        return {"success": False, "log": "simpleFoam timed out (600s)", "force_coefficients": None}


def parse_cfd_results_3d(case_dir):
    """Parse 3D CFD results: metadata + available fields."""
    case_dir = Path(case_dir)

    # Find latest time directory
    time_dirs = []
    for d in case_dir.iterdir():
        if d.is_dir():
            try:
                t = float(d.name)
                if t > 0:
                    time_dirs.append(d)
            except ValueError:
                pass
    if not time_dirs:
        return None
    time_dirs.sort(key=lambda d: float(d.name))
    latest = time_dirs[-1]

    # Parse cell centers — OpenFOAM 2406+ writes to postProcessing/writeCellCentres/<time>/C
    c_path = latest / "C"
    if not c_path.exists():
        pp_wcc = case_dir / "postProcessing" / "writeCellCentres"
        if pp_wcc.exists():
            pp_times = sorted([d for d in pp_wcc.iterdir() if d.is_dir()],
                              key=lambda d: float(d.name) if d.name.replace('.','',1).isdigit() else 0)
            if pp_times:
                c_path = pp_times[-1] / "C"
    cell_centers = _parse_of_vector_field(c_path)
    if not cell_centers:
        return None

    # Parse fields
    pressure = _parse_of_scalar_field(latest / "p")
    velocity = _parse_of_vector_field(latest / "U")
    turb_k = _parse_of_scalar_field(latest / "k")

    speed = None
    if velocity:
        speed = [math.sqrt(v[0]**2 + v[1]**2 + v[2]**2) for v in velocity]

    n_cells = len(cell_centers)

    # Bounding box of cells
    xs = [c[0] for c in cell_centers]
    ys = [c[1] for c in cell_centers]
    zs = [c[2] for c in cell_centers]

    # Load case metadata
    meta = {}
    meta_path = case_dir / "case_meta.json"
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)

    force_coeffs = _parse_force_coeffs(case_dir)

    return {
        "n_cells": n_cells,
        "bbox": {
            "min": [min(xs), min(ys), min(zs)],
            "max": [max(xs), max(ys), max(zs)],
        },
        "building_height": meta.get("height", 0),
        "force_coefficients": force_coeffs,
        "available_fields": ["pressure", "speed", "turb_k"],
        # Store parsed data in memory for slice extraction
        "_cell_centers": cell_centers,
        "_pressure": pressure,
        "_speed": speed,
        "_turb_k": turb_k,
    }


def extract_slice(case_dir, plane="z", value=0, field="pressure", tolerance=None):
    """Extract a 2D slice from 3D CFD results.

    Args:
        case_dir: Path to OpenFOAM case
        plane: 'x', 'y', or 'z'
        value: coordinate value for the slice
        field: 'pressure', 'speed', or 'turb_k'
        tolerance: slice thickness (auto if None)

    Returns dict compatible with 2D visualization: {nodes, triangles, p_range}
    """
    case_dir = Path(case_dir)

    # Find latest time directory
    time_dirs = []
    for d in case_dir.iterdir():
        if d.is_dir():
            try:
                t = float(d.name)
                if t > 0:
                    time_dirs.append(d)
            except ValueError:
                pass
    if not time_dirs:
        return None
    time_dirs.sort(key=lambda d: float(d.name))
    latest = time_dirs[-1]

    # Parse cell centers — OpenFOAM 2406+ writes to postProcessing/writeCellCentres/<time>/C
    c_path = latest / "C"
    if not c_path.exists():
        pp_wcc = case_dir / "postProcessing" / "writeCellCentres"
        if pp_wcc.exists():
            pp_times = sorted([d for d in pp_wcc.iterdir() if d.is_dir()],
                              key=lambda d: float(d.name) if d.name.replace('.','',1).isdigit() else 0)
            if pp_times:
                c_path = pp_times[-1] / "C"
    cell_centers = _parse_of_vector_field(c_path)
    if not cell_centers:
        return None

    # Always parse velocity for vector visualization
    velocity = _parse_of_vector_field(latest / "U")

    # Parse requested scalar field
    if field == "speed":
        if not velocity:
            return None
        field_values = [math.sqrt(v[0]**2 + v[1]**2 + v[2]**2) for v in velocity]
    elif field == "turb_k":
        field_values = _parse_of_scalar_field(latest / "k")
    else:  # pressure
        field_values = _parse_of_scalar_field(latest / "p")

    if not field_values:
        return None

    # Load case metadata for building bounds
    meta = {}
    meta_path = case_dir / "case_meta.json"
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
    footprint = meta.get("footprint", [])
    bld_height = meta.get("height", 0)
    bld_list = meta.get("buildings", [])

    # Compute building-centered crop region (all buildings)
    crop_radius = None
    bld_cx, bld_cy = 0, 0
    if bld_list:
        all_xs = [p[0] for b in bld_list for p in b["footprint"]]
        all_ys = [p[1] for b in bld_list for p in b["footprint"]]
        bld_cx = (min(all_xs) + max(all_xs)) / 2
        bld_cy = (min(all_ys) + max(all_ys)) / 2
        bld_span = max(max(all_xs) - min(all_xs), max(all_ys) - min(all_ys))
        crop_radius = max(bld_span, bld_height) * 2.0
    elif footprint and bld_height > 0:
        fp_xs = [p[0] for p in footprint]
        fp_ys = [p[1] for p in footprint]
        bld_cx = (min(fp_xs) + max(fp_xs)) / 2
        bld_cy = (min(fp_ys) + max(fp_ys)) / 2
        bld_span = max(max(fp_xs) - min(fp_xs), max(fp_ys) - min(fp_ys))
        # Crop: 3× body span (captures wake + near-field)
        crop_radius = max(bld_span, bld_height) * 3.0

    # Auto tolerance: use the smallest cells near the body, not the average
    if tolerance is None:
        n = len(cell_centers)
        xs = [c[0] for c in cell_centers]
        ys = [c[1] for c in cell_centers]
        zs = [c[2] for c in cell_centers]
        # Estimate from average cell size
        vol = (max(xs) - min(xs)) * (max(ys) - min(ys)) * (max(zs) - min(zs))
        avg_cell_size = (vol / max(n, 1)) ** (1 / 3)
        # Use smaller tolerance for finer resolution near body
        tolerance = avg_cell_size * 1.5

    # Filter cells on the slice plane + crop to near-building region
    plane_idx = {"x": 0, "y": 1, "z": 2}[plane]
    axes = [i for i in range(3) if i != plane_idx]

    nodes_2d = []
    values_2d = []
    vectors_raw = []  # (x2d, y2d, vx, vy, vz, speed) for vector visualization
    for i, cc in enumerate(cell_centers):
        if abs(cc[plane_idx] - value) > tolerance:
            continue
        if i >= len(field_values):
            continue
        # Spatial crop around building
        if crop_radius:
            dx = cc[0] - bld_cx
            dy = cc[1] - bld_cy
            if abs(dx) > crop_radius or abs(dy) > crop_radius:
                continue
        x2d = round(cc[axes[0]], 4)
        y2d = round(cc[axes[1]], 4)
        nodes_2d.append({"id": i, "x": x2d, "y": y2d})
        values_2d.append(field_values[i])
        if velocity and i < len(velocity):
            v = velocity[i]
            spd = math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)
            vectors_raw.append((x2d, y2d, v[0], v[1], v[2], spd))

    if len(nodes_2d) < 3:
        return {"nodes": [], "triangles": [], "p_range": [0, 0]}

    import numpy as np
    from scipy.interpolate import griddata

    pts = np.array([[n["x"], n["y"]] for n in nodes_2d])
    vals = np.array(values_2d)

    # Compute grid resolution from data extent
    x_min, x_max = pts[:, 0].min(), pts[:, 0].max()
    y_min, y_max = pts[:, 1].min(), pts[:, 1].max()
    span = max(x_max - x_min, y_max - y_min, 1e-6)

    # Estimate local cell size near center (body region) for grid resolution
    center_pts = pts[np.abs(pts[:, 0] - (x_min+x_max)/2) < span*0.2]
    if len(center_pts) > 10:
        # Use nearest-neighbor distance in center region as resolution target
        from scipy.spatial import cKDTree
        tree = cKDTree(center_pts[:500])  # sample
        dd, _ = tree.query(center_pts[:500], k=2)
        local_cell_size = float(np.median(dd[:, 1]))
        n_grid = min(400, max(80, int(span / local_cell_size)))
    else:
        n_grid = min(300, max(80, int(span / tolerance)))
    gx = np.linspace(x_min, x_max, n_grid)
    gy = np.linspace(y_min, y_max, n_grid)
    grid_x, grid_y = np.meshgrid(gx, gy)

    # Interpolate field values onto regular grid (linear, NaN outside convex hull)
    grid_vals = griddata(pts, vals, (grid_x, grid_y), method='linear')

    # Interpolate in-plane velocity onto grid for client-side streamline tracing
    grid_vx_arr = grid_vy_arr = None
    if vectors_raw:
        pts_v  = np.array([[vr[0], vr[1]] for vr in vectors_raw])
        vx_arr = np.array([vr[2 + axes[0]] for vr in vectors_raw])
        vy_arr = np.array([vr[2 + axes[1]] for vr in vectors_raw])
        grid_vx_arr = griddata(pts_v, vx_arr, (grid_x, grid_y), method='linear', fill_value=0.0)
        grid_vy_arr = griddata(pts_v, vy_arr, (grid_x, grid_y), method='linear', fill_value=0.0)
        np.nan_to_num(grid_vx_arr, nan=0.0, copy=False)
        np.nan_to_num(grid_vy_arr, nan=0.0, copy=False)

    # Build footprint polygon mask (exclude building interior on horizontal slices)
    fp_polys = []
    if bld_list and plane == "z":
        for b in bld_list:
            if 0 <= value <= b["height"]:
                fp_polys.append(b["footprint"])
    elif footprint and plane == "z" and 0 <= value <= bld_height:
        fp_polys = [footprint]

    def _point_in_polygon(px, py, poly):
        n = len(poly)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = poly[i]
            xj, yj = poly[j]
            if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    # Build grid nodes and triangles (two tris per quad cell)
    grid_nodes = []
    node_id_map = {}  # (iy, ix) → sequential node id
    nid = 0
    for iy in range(n_grid):
        for ix in range(n_grid):
            v = grid_vals[iy, ix]
            if np.isnan(v):
                continue
            # Skip points inside any building footprint
            px, py = gx[ix], gy[iy]
            if fp_polys and any(_point_in_polygon(px, py, fp) for fp in fp_polys):
                continue
            vx_n = round(float(grid_vx_arr[iy, ix]), 4) if grid_vx_arr is not None else 0.0
            vy_n = round(float(grid_vy_arr[iy, ix]), 4) if grid_vy_arr is not None else 0.0
            grid_nodes.append({"id": nid, "x": round(float(px), 4), "y": round(float(py), 4), "vx": vx_n, "vy": vy_n})
            node_id_map[(iy, ix)] = nid
            nid += 1

    triangles = []
    for iy in range(n_grid - 1):
        for ix in range(n_grid - 1):
            # Four corners of this quad cell
            k00 = node_id_map.get((iy, ix))
            k10 = node_id_map.get((iy + 1, ix))
            k01 = node_id_map.get((iy, ix + 1))
            k11 = node_id_map.get((iy + 1, ix + 1))
            if k00 is None or k10 is None or k01 is None or k11 is None:
                continue
            v00 = grid_vals[iy, ix]
            v10 = grid_vals[iy + 1, ix]
            v01 = grid_vals[iy, ix + 1]
            v11 = grid_vals[iy + 1, ix + 1]
            # Two triangles per quad
            triangles.append({"nodes": [k00, k10, k01], "p": float((v00 + v10 + v01) / 3)})
            triangles.append({"nodes": [k10, k11, k01], "p": float((v10 + v11 + v01) / 3)})

    v_min = float(vals.min()) if len(vals) > 0 else 0
    v_max = float(vals.max()) if len(vals) > 0 else 0

    # Subsample velocity vectors for arrow visualization (~500 arrows max)
    vectors_out = []
    if vectors_raw:
        step = max(1, len(vectors_raw) // 500)
        for j in range(0, len(vectors_raw), step):
            vr = vectors_raw[j]
            vectors_out.append({
                "x": vr[0], "y": vr[1],
                "vx": round(vr[2], 4), "vy": round(vr[3], 4), "vz": round(vr[4], 4),
                "speed": round(vr[5], 4),
            })

    return {
        "nodes": grid_nodes,
        "triangles": triangles[:160000],
        "p_range": [v_min, v_max],
        "vectors": vectors_out,
    }


def extract_streamlines(case_dir, n_seeds=30, seed_plane="inlet",
                         seed_z_min=0.0, seed_z_max=1.0):
    """Extract 3D streamlines from OpenFOAM results using postProcess.

    Runs streamLine function object, parses VTK output, returns polylines
    colored by velocity magnitude.

    Args:
        case_dir: Path to OpenFOAM case
        n_seeds: Number of seed points
        seed_plane: 'inlet' (upstream of building) or 'center' (y=0 plane)
        seed_z_min: Minimum seed height as fraction of H (0.0 = ground, 1.0 = roof)
        seed_z_max: Maximum seed height as fraction of H

    Returns list of polylines: [{points: [[x,y,z],...], speed: [s1,...]}]
    """
    case_dir = Path(case_dir)

    # Load metadata for building bounds
    meta = {}
    meta_path = case_dir / "case_meta.json"
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
    footprint = meta.get("footprint", [])
    bld_list = meta.get("buildings", [])
    H = meta.get("height", 40)

    # Compute seed line position (from all buildings or single footprint)
    if bld_list:
        all_xs = [p[0] for b in bld_list for p in b["footprint"]]
        all_ys = [p[1] for b in bld_list for p in b["footprint"]]
        cx = (min(all_xs) + max(all_xs)) / 2
        cy = (min(all_ys) + max(all_ys)) / 2
        bw = max(all_xs) - min(all_xs)
        bd = max(all_ys) - min(all_ys)
    elif footprint:
        fp_xs = [p[0] for p in footprint]
        fp_ys = [p[1] for p in footprint]
        cx = (min(fp_xs) + max(fp_xs)) / 2
        cy = (min(fp_ys) + max(fp_ys)) / 2
        bw = max(fp_xs) - min(fp_xs)
        bd = max(fp_ys) - min(fp_ys)
    else:
        cx, cy, bw, bd = 0, 0, 10, 10

    # Seed line: upstream of building, spanning height and width
    x_seed = cx - max(bw, bd) * 2  # 2× building size upstream
    y_min_seed = cy - max(bd, bw) * 1.5
    y_max_seed = cy + max(bd, bw) * 1.5
    # Seed height range (fraction of H, clamped)
    z_min_seed = max(0.5, seed_z_min * H * 1.5)  # at least 0.5m above ground
    z_max_seed = max(z_min_seed + 0.5, seed_z_max * H * 1.5)
    print(f"  Streamline seeds: z={z_min_seed:.1f}..{z_max_seed:.1f}m ({seed_z_min*100:.0f}–{seed_z_max*100:.0f}%H)")

    # Write streamline dict (OpenFOAM 2406 syntax)
    streamline_dict = f"""
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      streamLineDict;
}}
type            streamLine;
libs            (fieldFunctionObjects);
writeControl    writeTime;
setFormat       raw;
U               U;
trackForward    true;
lifeTime        10000;
fields          (p U k);
nSubCycle       5;
cloud           particleTracks;
seedSampleSet
{{
    type        uniform;
    axis        xyz;
    start       ({x_seed} {y_min_seed} {z_min_seed});
    end         ({x_seed} {y_max_seed} {z_max_seed});
    nPoints     {n_seeds};
}}
"""
    dict_path = case_dir / "system" / "streamLineDict"
    with open(dict_path, "w", newline="\n") as f:
        f.write(streamline_dict)

    # Run postProcess
    wsl_case = str(case_dir).replace("C:\\", "/mnt/c/").replace("\\", "/")
    script = f"""#!/bin/bash
source /usr/lib/openfoam/openfoam2406/etc/bashrc 2>/dev/null
cd "{wsl_case}"
postProcess -func streamLineDict -latestTime 2>&1 | tail -5
echo "STREAMLINE_DONE"
"""
    script_path = case_dir / "run_streamlines.sh"
    with open(script_path, "w", newline="\n") as f:
        f.write(script)

    try:
        result = subprocess.run(
            [r"C:\Windows\system32\wsl.exe", "-d", "Ubuntu", "--", "bash", f"{wsl_case}/run_streamlines.sh"],
            capture_output=True, timeout=60,
        )
        log = result.stdout.decode("utf-8", errors="replace")
        if "STREAMLINE_DONE" not in log:
            print(f"  Streamline postProcess failed: {log[-300:]}")
            return []
    except Exception as e:
        print(f"  Streamline error: {e}")
        return []

    # Find output — OpenFOAM puts streamlines under postProcessing/sets/
    pp_base = case_dir / "postProcessing"
    if not pp_base.exists():
        print(f"  No postProcessing directory")
        return []

    # Search for raw streamline files (U_track0.raw or track0_U.raw)
    raw_files = list(pp_base.rglob("U_track*.raw"))
    if not raw_files:
        raw_files = list(pp_base.rglob("track*_U*"))
    if not raw_files:
        raw_files = list(pp_base.rglob("track*.xy"))
    if not raw_files:
        # Fallback: try VTK/VTP
        vtk_files = list(pp_base.rglob("track*.vtk")) + list(pp_base.rglob("track*.vtp"))
        if vtk_files:
            polylines = []
            for vf in vtk_files:
                polylines.extend(_parse_vtk_streamlines(vf))
            print(f"  Streamlines: {len(polylines)} from VTK")
            return polylines
        print(f"  No streamline files found in {pp_base}")
        content = list(pp_base.rglob("*"))[:20]
        print(f"  Available: {[str(f.relative_to(pp_base)) for f in content]}")
        return []

    # Parse raw format: U_track0.raw has all tracks concatenated
    # Split at large jumps (back to seed x position)
    polylines = []
    for f in raw_files:
        if "U_" in f.name or f.name.startswith("U"):
            all_pts, all_speeds = _parse_raw_streamline(f)
            # Split into individual tracks at large position jumps
            if len(all_pts) < 2:
                continue
            current_pts = [all_pts[0]]
            current_spd = [all_speeds[0]]
            for i in range(1, len(all_pts)):
                dx = abs(all_pts[i][0] - all_pts[i-1][0])
                dy = abs(all_pts[i][1] - all_pts[i-1][1])
                dz = abs(all_pts[i][2] - all_pts[i-1][2])
                jump = math.sqrt(dx*dx + dy*dy + dz*dz)
                # If jump is > 10× typical step, it's a new track
                if jump > H * 0.5 and len(current_pts) >= 2:
                    polylines.append({"points": current_pts, "speed": current_spd})
                    current_pts = []
                    current_spd = []
                current_pts.append(all_pts[i])
                current_spd.append(all_speeds[i])
            if len(current_pts) >= 2:
                polylines.append({"points": current_pts, "speed": current_spd})

    print(f"  Streamlines: {len(polylines)} tracks, {sum(len(sl['points']) for sl in polylines)} total points")
    return polylines


def _parse_raw_streamline(filepath):
    """Parse a raw-format streamline file (x y z Ux Uy Uz)."""
    pts = []
    speeds = []
    try:
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("(") or line.startswith(")"):
                    continue
                parts = line.split()
                if len(parts) >= 6:
                    x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
                    vx, vy, vz = float(parts[3]), float(parts[4]), float(parts[5])
                    spd = math.sqrt(vx*vx + vy*vy + vz*vz)
                    pts.append([round(x, 3), round(y, 3), round(z, 3)])
                    speeds.append(round(spd, 3))
                elif len(parts) >= 3:
                    # Just coordinates, no velocity
                    x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
                    pts.append([round(x, 3), round(y, 3), round(z, 3)])
                    speeds.append(0)
    except Exception as e:
        print(f"  Error parsing {filepath}: {e}")
    return pts, speeds


def _parse_vtk_streamlines(vtk_path):
    """Parse a VTK polydata file with streamlines. Returns list of polylines."""
    with open(vtk_path) as f:
        content = f.read()

    lines_out = []

    # Parse POINTS
    import re
    pts_match = re.search(r'POINTS\s+(\d+)\s+\w+\n(.*?)(?=LINES|POLYGONS|VERTICES|POINT_DATA|\Z)',
                          content, re.DOTALL)
    if not pts_match:
        return []

    n_pts = int(pts_match.group(1))
    pts_data = pts_match.group(2).split()
    points = []
    for i in range(0, min(len(pts_data), n_pts * 3), 3):
        try:
            points.append((float(pts_data[i]), float(pts_data[i+1]), float(pts_data[i+2])))
        except (ValueError, IndexError):
            break

    if not points:
        return []

    # Parse LINES connectivity
    lines_match = re.search(r'LINES\s+(\d+)\s+(\d+)\n(.*?)(?=POINT_DATA|CELL_DATA|\Z)',
                            content, re.DOTALL)

    # Parse U field for speed coloring
    u_match = re.search(r'U\s+3\s+(\d+)\s+float\n(.*?)(?=\n\w|\Z)', content, re.DOTALL)
    velocities = []
    if u_match:
        u_data = u_match.group(2).split()
        for i in range(0, len(u_data) - 2, 3):
            try:
                vx, vy, vz = float(u_data[i]), float(u_data[i+1]), float(u_data[i+2])
                velocities.append(math.sqrt(vx*vx + vy*vy + vz*vz))
            except (ValueError, IndexError):
                velocities.append(0)

    if lines_match:
        lines_data = lines_match.group(3).split()
        idx = 0
        while idx < len(lines_data):
            try:
                n = int(lines_data[idx])
                idx += 1
                pt_indices = []
                for _ in range(n):
                    pt_indices.append(int(lines_data[idx]))
                    idx += 1
                if len(pt_indices) >= 2:
                    line_pts = []
                    line_speeds = []
                    for pi in pt_indices:
                        if pi < len(points):
                            p = points[pi]
                            line_pts.append([round(p[0], 3), round(p[1], 3), round(p[2], 3)])
                            if pi < len(velocities):
                                line_speeds.append(round(velocities[pi], 3))
                            else:
                                line_speeds.append(0)
                    if len(line_pts) >= 2:
                        lines_out.append({"points": line_pts, "speed": line_speeds})
            except (ValueError, IndexError):
                break
    else:
        # No LINES section — treat all points as one polyline
        all_pts = [[round(p[0], 3), round(p[1], 3), round(p[2], 3)] for p in points]
        all_speeds = [round(v, 3) for v in velocities[:len(points)]]
        if not all_speeds:
            all_speeds = [0] * len(all_pts)
        if len(all_pts) >= 2:
            lines_out.append({"points": all_pts, "speed": all_speeds})

    return lines_out


if __name__ == "__main__":
    from tools.cfd_mesh import generate_cfd_mesh

    # Test: create case for rectangular section
    rect = [[0, 0], [4, 0], [4, 0.5], [0, 0.5]]
    mesh = generate_cfd_mesh(rect, mesh_size=0.2, far_field_factor=10)

    case_dir = create_openfoam_case(mesh, wind_speed=20, wind_angle=0,
                                     output_dir="tests/_output/cfd_case")
    print(f"Case: {case_dir}")
    print(f"Files: {list(Path(case_dir).rglob('*'))[:20]}")
