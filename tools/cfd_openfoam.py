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

_IS_WINDOWS = sys.platform == "win32"


def _of_path(case_dir):
    """Return the path string usable inside the bash script (WSL path on Windows, native on Linux)."""
    if _IS_WINDOWS:
        return str(case_dir).replace("C:\\", "/mnt/c/").replace("\\", "/")
    return str(case_dir)


def _run_of_script(script_path, case_dir, timeout=600):
    """Run an OpenFOAM bash script via WSL (Windows) or directly (Linux)."""
    bash_script = _of_path(script_path)
    if _IS_WINDOWS:
        cmd = [r"C:\Windows\system32\wsl.exe", "-d", "Ubuntu", "--", "bash", bash_script]
    else:
        cmd = ["bash", str(script_path)]
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def create_openfoam_case(mesh_result, wind_speed=20.0, wind_angle=0.0,
                         nu=1.5e-5, turbulence_intensity=0.05,
                         turbulence_model='kEpsilon', turbulence_length_scale=None,
                         output_dir=None, transient=False, end_time=5.0, dt=0.001,
                         write_interval=100, grounded=None, quiescent_start=False):
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

    # Grounded cases use a rectangular domain (inlet/outlet/top/ground patches)
    # instead of the free-flow circular farfield. Inferred from the mesh unless
    # the caller forces it.
    if grounded is None:
        grounded = bool(mesh_result.get("grounded"))

    # Wind velocity components
    rad = math.radians(wind_angle)
    Ux = wind_speed * math.cos(rad)
    Uy = wind_speed * math.sin(rad)

    # Soft start for transient runs on sharp/thin sections (e.g. bridge-deck
    # legs): initialise the interior at rest so the free stream arrives by
    # diffusion from the far field instead of as an impulsive shock that blows
    # up the under-resolved edges. The far-field / inlet BC stays at the target
    # velocity; only the initial internal field changes. Steady runs and cases
    # that don't opt in keep the uniform free-stream IC.
    ic_U = "0 0 0" if (transient and quiescent_start) else f"{Ux} {Uy} 0"

    # Turbulence model + inlet turbulence.
    # tvar = second turbulence field: "epsilon" (k-epsilon family) or "omega" (k-omega SST).
    # turbulence_length_scale lets callers match a reference inflow length scale (e.g.
    # SOFiSTiK/Dolfyn EPS 20mm); default keeps the historical 0.1*char_dim (k-epsilon
    # results stay bit-identical).
    Cmu = 0.09
    char_dim = mesh_result["stats"]["char_dim"]
    L_turb = turbulence_length_scale or (0.1 * char_dim)
    k_inlet = 1.5 * (wind_speed * turbulence_intensity) ** 2
    sst = turbulence_model in ("kOmegaSST", "kOmega")
    if sst:
        tvar, tvar_dims, tvar_wallfn = "omega", "[0 0 -1 0 0 0 0]", "omegaWallFunction"
        tvar_inlet = math.sqrt(k_inlet) / (Cmu ** 0.25 * L_turb)
        nut_inlet = k_inlet / max(tvar_inlet, 1e-10)
    else:
        tvar, tvar_dims, tvar_wallfn = "epsilon", "[0 2 -3 0 0 0 0]", "epsilonWallFunction"
        tvar_inlet = Cmu * k_inlet ** 1.5 / L_turb
        nut_inlet = Cmu * k_inlet ** 2 / max(tvar_inlet, 1e-10)

    # Reynolds number
    Re = wind_speed * char_dim / nu
    print(f"  Re = {Re:.0f}, model = {turbulence_model}, k = {k_inlet:.4f}, {tvar} = {tvar_inlet:.4f}")

    # ── Create directory structure ──
    for d in ["0", "constant", "system", "constant/polyMesh"]:
        (case_dir / d).mkdir(parents=True, exist_ok=True)

    # ── 0/ — Initial and boundary conditions ──

    if grounded:
        # Rectangular domain: inlet (fixed velocity), outlet (fixed pressure),
        # top (slip / frictionless), ground + section (no-slip walls). No flow
        # passes under the bodies — they stand on the ground.
        _write_of_file(case_dir / "0" / "U", "volVectorField", "U", f"""
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform ({ic_U});
boundaryField
{{
    inlet   {{ type fixedValue; value uniform ({Ux} {Uy} 0); }}
    outlet  {{ type inletOutlet; inletValue uniform (0 0 0); value uniform ({Ux} {Uy} 0); }}
    top     {{ type slip; }}
    ground  {{ type noSlip; }}
    section {{ type noSlip; }}
    defaultFaces {{ type empty; }}
}}
""")
        _write_of_file(case_dir / "0" / "p", "volScalarField", "p", f"""
dimensions      [0 2 -2 0 0 0 0];
internalField   uniform 0;
boundaryField
{{
    inlet   {{ type zeroGradient; }}
    outlet  {{ type fixedValue; value uniform 0; }}
    top     {{ type zeroGradient; }}
    ground  {{ type zeroGradient; }}
    section {{ type zeroGradient; }}
    defaultFaces {{ type empty; }}
}}
""")
        _write_of_file(case_dir / "0" / "k", "volScalarField", "k", f"""
dimensions      [0 2 -2 0 0 0 0];
internalField   uniform {k_inlet};
boundaryField
{{
    inlet   {{ type fixedValue; value uniform {k_inlet}; }}
    outlet  {{ type inletOutlet; inletValue uniform {k_inlet}; value uniform {k_inlet}; }}
    top     {{ type zeroGradient; }}
    ground  {{ type kqRWallFunction; value uniform {k_inlet}; }}
    section {{ type kqRWallFunction; value uniform {k_inlet}; }}
    defaultFaces {{ type empty; }}
}}
""")
        _write_of_file(case_dir / "0" / tvar, "volScalarField", tvar, f"""
dimensions      {tvar_dims};
internalField   uniform {tvar_inlet};
boundaryField
{{
    inlet   {{ type fixedValue; value uniform {tvar_inlet}; }}
    outlet  {{ type inletOutlet; inletValue uniform {tvar_inlet}; value uniform {tvar_inlet}; }}
    top     {{ type zeroGradient; }}
    ground  {{ type {tvar_wallfn}; value uniform {tvar_inlet}; }}
    section {{ type {tvar_wallfn}; value uniform {tvar_inlet}; }}
    defaultFaces {{ type empty; }}
}}
""")
        _write_of_file(case_dir / "0" / "nut", "volScalarField", "nut", f"""
dimensions      [0 2 -1 0 0 0 0];
internalField   uniform {nut_inlet};
boundaryField
{{
    inlet   {{ type calculated; value uniform {nut_inlet}; }}
    outlet  {{ type calculated; value uniform {nut_inlet}; }}
    top     {{ type calculated; value uniform {nut_inlet}; }}
    ground  {{ type nutkWallFunction; value uniform 0; }}
    section {{ type nutUSpaldingWallFunction; value uniform 0; }}
    defaultFaces {{ type empty; }}
}}
""")
    else:
      # U (velocity)
      _write_of_file(case_dir / "0" / "U", "volVectorField", "U", f"""
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform ({ic_U});
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

      # epsilon / omega (second turbulence field)
      _write_of_file(case_dir / "0" / tvar, "volScalarField", tvar, f"""
dimensions      {tvar_dims};
internalField   uniform {tvar_inlet};
boundaryField
{{
    farfield
    {{
        type            freestream;
        freestreamValue uniform {tvar_inlet};
    }}
    section
    {{
        type            {tvar_wallfn};
        value           uniform {tvar_inlet};
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

    # "laminar" runs a direct (no turbulence-model) 2D simulation — used by the
    # low-Re vortex-shedding demos (clean Kármán street; RAS eddy-viscosity over-
    # damps the wake). k/epsilon|omega/nut fields are still written but go unused.
    if turbulence_model == "laminar":
        sim_block = "simulationType  laminar;"
    else:
        sim_block = (f"simulationType  RAS;\nRAS\n{{\n"
                     f"    RASModel        {turbulence_model};\n"
                     f"    turbulence      on;\n    printCoeffs     on;\n}}")
    _write_of_file(case_dir / "constant" / "turbulenceProperties", None, None, f"""
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      turbulenceProperties;
}}
{sim_block}
""")

    # ── system/ — Solver settings ──

    if transient:
        solver_app = "pimpleFoam"
        end_t = end_time
        # Adaptive timestep: the user-supplied dt is only the upper bound (maxDeltaT).
        # Two failure modes are handled:
        #  1) A fixed dt diverges because the thin near-wall layers reach high
        #     convective Courant numbers (an airfoil at U=50 m/s hits Co≈18 at
        #     dt=1e-3) — so pimpleFoam shrinks dt to honour maxCo.
        #  2) The impulsive start (free stream applied instantly) overshoots on the
        #     skewed trailing-edge cells; if the very first step already runs at a
        #     large dt the local velocity blows up irrecoverably. So we SEED with a
        #     tiny deltaT (gentle start, first-step Co≈0.2) and let adjustTimeStep
        #     ramp it up toward maxDeltaT as the field develops.
        # Frames are written on a fixed sim-time interval so animation spacing stays
        # uniform regardless of the varying dt.
        delta_t = min(dt, 1.0e-5)
        write_ctrl = "adjustableRunTime"
        # ~150 animation frames, never finer than the timestep. Targeting a frame
        # COUNT keeps animation spacing uniform across short and long runs. 150
        # (up from 40) gives smooth, shareable video of the vortex shedding —
        # ~10 frames per shedding cycle — at a modest reconstructPar/IO cost (the
        # old 600-frame writeControl bloated reconstruct to minutes; 150 stays
        # well under that). The frontend prefetches frames in parallel batches.
        write_int  = round(max(end_time / 150.0, dt), 6)  # ~150 frames
        purge = 0  # keep all time steps for animation
        adjust_block = f"adjustTimeStep  yes;\nmaxCo           5;\nmaxDeltaT       {dt};"
    else:
        solver_app = "simpleFoam"
        delta_t = 1
        # k-omega SST lift/moment on bluff bodies need ~1500+ iterations to plateau,
        # whereas k-epsilon-family runs converge (and early-stop via residualControl)
        # well within 500. Raise the cap only for SST so existing k-epsilon runtimes
        # and results stay unchanged; residualControl still stops converged cases early.
        end_t = 2000 if sst else 500
        write_ctrl = "timeStep"
        write_int = end_t
        purge = 1
        adjust_block = "adjustTimeStep  no;"

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
writeControl    {write_ctrl};
writeInterval   {write_int};
purgeWrite      {purge};
writeFormat     ascii;
writePrecision  8;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;
{adjust_block}

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
        liftDir         ({-math.sin(rad)} {math.cos(rad)} 0);
        dragDir         ({math.cos(rad)} {math.sin(rad)} 0);
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
    div(phi,{tvar})    bounded Gauss upwind;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}}
laplacianSchemes {{ default Gauss linear corrected; }}
interpolationSchemes {{ default linear; }}
snGradSchemes {{ default corrected; }}
wallDist {{ method meshWave; }}
""")

    if transient:
        _write_of_file(case_dir / "system" / "fvSolution", None, None, ("""
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
    Phi { solver PCG; preconditioner DIC; tolerance 1e-06; relTol 0.01; }
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
""").replace("epsilon", tvar))
    else:
        _write_of_file(case_dir / "system" / "fvSolution", None, None, ("""
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
    Phi { solver PCG; preconditioner DIC; tolerance 1e-06; relTol 0.01; }
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
""").replace("epsilon", tvar))

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
        "turbulence_model": turbulence_model,
        f"{tvar}_inlet": tvar_inlet,
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


def _omesh_to_msh(polygon, msh_path, wind_speed, far_field_factor):
    """Generate a structured O-grid .msh for OpenFOAM via subprocess."""
    script = f"""
import sys, json, math
sys.path.insert(0, r'{str(Path(__file__).resolve().parent.parent)}')
from tools.cfd_mesh import _cosine_resample
import gmsh

polygon = {json.dumps(polygon)}
wind_speed = {wind_speed}
far_field_factor = {far_field_factor}
nu = 1.5e-5

xs = [p[0] for p in polygon]
ys = [p[1] for p in polygon]
cx = (max(xs) + min(xs)) / 2
cy = (max(ys) + min(ys)) / 2
char_dim = max(max(xs) - min(xs), max(ys) - min(ys))
far_r = char_dim * far_field_factor

Re = max(wind_speed * char_dim / nu, 1e4)
Cf = 0.074 / Re ** 0.2
u_tau = wind_speed * math.sqrt(max(Cf / 2.0, 1e-10))
first_layer = max(5e-6, 50.0 * nu / u_tau)

r_g = 1.15
N_r = int(math.ceil(math.log(far_r * (r_g - 1) / first_layer + 1) / math.log(r_g)))
N_r = max(40, min(N_r, 120))
N_s = 60

n = len(polygon)
le_idx = min(range(n), key=lambda i: polygon[i][0])
te_idx = max(range(n), key=lambda i: polygon[i][0])
le_pt = [polygon[le_idx][0], polygon[le_idx][1]]
te_pt = [polygon[te_idx][0], 0.0]

def walk(start, end, step):
    pts, i = [], start
    while i != end:
        pts.append(list(polygon[i]))
        i = (i + step) % n
    pts.append(list(polygon[end]))
    return pts

fwd = walk(le_idx, te_idx,  1)
bwd = walk(le_idx, te_idx, -1)
if sum(p[1] for p in fwd) >= sum(p[1] for p in bwd):
    upper_raw, lower_raw = fwd, list(reversed(bwd))
else:
    upper_raw, lower_raw = bwd, list(reversed(fwd))

upper_raw[0] = le_pt[:]
upper_raw[-1] = te_pt[:]
lower_raw[0] = te_pt[:]
lower_raw[-1] = le_pt[:]

upper_pts = _cosine_resample(upper_raw, N_s)
lower_pts = _cosine_resample(lower_raw, N_s)

def to_ff(pt):
    dx, dy = pt[0] - cx, pt[1] - cy
    d = math.sqrt(dx*dx + dy*dy)
    if d < 1e-10:
        return [cx + far_r, cy]
    return [cx + dx * far_r / d, cy + dy * far_r / d]

upper_ff = [to_ff(p) for p in upper_pts]
lower_ff = [to_ff(p) for p in lower_pts]

gmsh.initialize()
gmsh.option.setNumber("General.Verbosity", 0)
gmsh.model.add("omesh")

def gpt(x, y):
    return gmsh.model.geo.addPoint(x, y, 0, 1.0)

ut = [gpt(*p) for p in upper_pts]
lt_int = [gpt(*p) for p in lower_pts[1:-1]]
lt = [ut[N_s]] + lt_int + [ut[0]]
uft = [gpt(*p) for p in upper_ff]
lft_int = [gpt(*p) for p in lower_ff[1:-1]]
lft = [uft[N_s]] + lft_int + [uft[0]]

le_rad = gmsh.model.geo.addLine(ut[0],   uft[0])
te_rad = gmsh.model.geo.addLine(ut[N_s], uft[N_s])
u_spl  = gmsh.model.geo.addSpline(ut)
l_spl  = gmsh.model.geo.addSpline(lt)
uf_spl = gmsh.model.geo.addSpline(uft)
lf_spl = gmsh.model.geo.addSpline(lft)

uloop = gmsh.model.geo.addCurveLoop([u_spl, te_rad, -uf_spl, -le_rad])
usurf = gmsh.model.geo.addPlaneSurface([uloop])
lloop = gmsh.model.geo.addCurveLoop([l_spl, le_rad, -lf_spl, -te_rad])
lsurf = gmsh.model.geo.addPlaneSurface([lloop])

# Extrude BEFORE synchronize so we only need ONE synchronize() call.
# Two synchronize() calls would reset transfinite attributes set between them.
# Lateral ordering follows the CurveLoop order:
#   uloop=[u_spl, te_rad, -uf_spl, -le_rad] -> ext[2]=lat_u_spl [3]=lat_te_rad [4]=lat_uf_spl [5]=lat_le_rad
#   lloop=[l_spl, le_rad, -lf_spl, -te_rad] -> ext[8]=lat_l_spl [9]=lat_le_rad [10]=lat_lf_spl [11]=lat_te_rad
#   ext[3,5,9,11] = TE/LE radial laterals (shared between upper and lower -> internal)
ext = gmsh.model.geo.extrude(
    [(2, usurf), (2, lsurf)], 0, 0, 1.0,
    numElements=[1], recombine=True
)

# Single synchronize: transfers all geometry (surfaces + extruded volumes) to Gmsh model
gmsh.model.geo.synchronize()

# Set ALL transfinite/recombine attributes after the ONE synchronize
gmsh.model.mesh.setTransfiniteCurve(u_spl,  N_s + 1)
gmsh.model.mesh.setTransfiniteCurve(l_spl,  N_s + 1)
gmsh.model.mesh.setTransfiniteCurve(uf_spl, N_s + 1)
gmsh.model.mesh.setTransfiniteCurve(lf_spl, N_s + 1)
gmsh.model.mesh.setTransfiniteCurve(le_rad, N_r + 1, "Progression", r_g)
gmsh.model.mesh.setTransfiniteCurve(te_rad, N_r + 1, "Progression", r_g)
gmsh.model.mesh.setTransfiniteSurface(usurf, "Left", [ut[0], ut[N_s], uft[N_s], uft[0]])
gmsh.model.mesh.setTransfiniteSurface(lsurf, "Left", [lt[0], lt[N_s], lft[N_s], lft[0]])
gmsh.model.mesh.setRecombine(2, usurf)
gmsh.model.mesh.setRecombine(2, lsurf)

# Physical groups using explicit ext indices (set before generate)
gmsh.model.removePhysicalGroups()
gmsh.model.addPhysicalGroup(3, [ext[1][1], ext[7][1]],               tag=10, name="internal")
gmsh.model.addPhysicalGroup(2, [ext[2][1], ext[8][1]],               tag=1,  name="section")
gmsh.model.addPhysicalGroup(2, [ext[4][1], ext[10][1]],              tag=2,  name="farfield")
gmsh.model.addPhysicalGroup(2, [usurf, ext[0][1], lsurf, ext[6][1]], tag=3,  name="frontAndBack")

gmsh.model.mesh.generate(3)
gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
gmsh.write(r'{msh_path}')
print("MSH_OK")
gmsh.finalize()
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=120,
    )
    if "MSH_OK" not in result.stdout:
        raise RuntimeError(f"Structured Gmsh export failed: {result.stderr[:500]}")


def _grounded_to_msh(polygon, msh_path, mesh_size, far_field_factor, bl_layers, bl_ratio):
    """Gmsh .msh for a ground-mounted case: rectangular domain with a ground wall,
    bodies as bumps on y=0, extruded to a 1-cell slab. `polygon` is the open chain
    (left ground contact → over bodies → right ground contact, ends on y=0)."""
    script = f"""
import gmsh, math
gmsh.initialize()
gmsh.option.setNumber("General.Verbosity", 0)
gmsh.model.add("cfd_grounded")
geo = gmsh.model.geo
eps = 1e-6
ms  = {mesh_size}

chain = {json.dumps(polygon)}
xs = [p[0] for p in chain]; ys = [p[1] for p in chain]
xL, xR = min(xs), max(xs); H = max(ys)
char_dim = max(xR - xL, H)
margin = char_dim * {far_field_factor}
x_in, x_out = xL - margin, xR + margin
y_top = margin
ff_ms = char_dim * 2.0

# Ordered boundary segments (a, b, type)
segs = [((x_in, 0.0), tuple(chain[0]), 'ground')]
for i in range(len(chain) - 1):
    a, b = chain[i], chain[i + 1]
    t = 'ground' if (abs(a[1]) < eps and abs(b[1]) < eps) else 'section'
    segs.append((tuple(a), tuple(b), t))
segs += [
    (tuple(chain[-1]), (x_out, 0.0), 'ground'),
    ((x_out, 0.0), (x_out, y_top), 'outlet'),
    ((x_out, y_top), (x_in, y_top), 'top'),
    ((x_in, y_top), (x_in, 0.0), 'inlet'),
]

ptmap = {{}}
def getp(xy, h):
    key = (round(xy[0], 9), round(xy[1], 9))
    if key not in ptmap:
        ptmap[key] = geo.addPoint(xy[0], xy[1], 0, h)
    return ptmap[key]

loop_lines, types = [], []
wall_pts = set()
for a, b, t in segs:
    L = math.hypot(b[0]-a[0], b[1]-a[1])
    if t in ('section', 'ground'):
        step, h = ms * 3.0, ms
    else:
        step, h = max(ff_ms, L), ff_ms
    nseg = max(1, int(math.ceil(L / step)))
    for j in range(nseg):
        p0 = (a[0]+(b[0]-a[0])*j/nseg,     a[1]+(b[1]-a[1])*j/nseg)
        p1 = (a[0]+(b[0]-a[0])*(j+1)/nseg, a[1]+(b[1]-a[1])*(j+1)/nseg)
        g0, g1 = getp(p0, h), getp(p1, h)
        lid = geo.addLine(g0, g1)
        loop_lines.append(lid); types.append(t)
        if t in ('section', 'ground'):
            wall_pts.add(g0); wall_pts.add(g1)

surf = geo.addPlaneSurface([geo.addCurveLoop(loop_lines)])
geo.synchronize()

sec_lines = [loop_lines[i] for i in range(len(loop_lines)) if types[i] == 'section']
wall_lines = [loop_lines[i] for i in range(len(loop_lines)) if types[i] in ('section', 'ground')]

df = gmsh.model.mesh.field.add("Distance")
gmsh.model.mesh.field.setNumbers(df, "CurvesList", sec_lines)
tf = gmsh.model.mesh.field.add("Threshold")
gmsh.model.mesh.field.setNumber(tf, "InField", df)
gmsh.model.mesh.field.setNumber(tf, "SizeMin", ms * 0.6)
gmsh.model.mesh.field.setNumber(tf, "SizeMax", ff_ms)
gmsh.model.mesh.field.setNumber(tf, "DistMin", char_dim * 0.3)
gmsh.model.mesh.field.setNumber(tf, "DistMax", margin * 0.4)
gmsh.model.mesh.field.setNumber(tf, "Sigmoid", 1)
gmsh.model.mesh.field.setAsBackgroundMesh(tf)
gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
gmsh.option.setNumber("Mesh.Smoothing", 5)

if {bl_layers} > 0:
    first_layer = max(2e-4, min(ms * 0.04, char_dim * 0.004))
    bl = gmsh.model.mesh.field.add("BoundaryLayer")
    gmsh.model.mesh.field.setNumbers(bl, "CurvesList", wall_lines)
    gmsh.model.mesh.field.setNumbers(bl, "PointsList", sorted(wall_pts))
    gmsh.model.mesh.field.setNumber(bl, "Size", first_layer)
    gmsh.model.mesh.field.setNumber(bl, "Ratio", {bl_ratio})
    gmsh.model.mesh.field.setNumber(bl, "NbLayers", {bl_layers})
    gmsh.model.mesh.field.setNumber(bl, "Quads", 1)
    gmsh.model.mesh.field.setNumber(bl, "IntersectMetrics", 1)
    gmsh.model.mesh.field.setAsBoundaryLayer(bl)

gmsh.model.mesh.generate(2)

ext = geo.extrude([(2, surf)], 0, 0, 1.0, numElements=[1], recombine=True)
geo.synchronize()
top_surf = ext[0][1]; vol = ext[1][1]
lat = [ext[2 + i][1] for i in range(len(loop_lines))]
def by(t): return [lat[i] for i in range(len(loop_lines)) if types[i] == t]

gmsh.model.removePhysicalGroups()
gmsh.model.addPhysicalGroup(3, [vol], tag=10, name="internal")
gmsh.model.addPhysicalGroup(2, by('section'), tag=1, name="section")
gmsh.model.addPhysicalGroup(2, by('inlet'),   tag=2, name="inlet")
gmsh.model.addPhysicalGroup(2, by('outlet'),  tag=3, name="outlet")
gmsh.model.addPhysicalGroup(2, by('top'),     tag=4, name="top")
gmsh.model.addPhysicalGroup(2, by('ground'),  tag=5, name="ground")
gmsh.model.addPhysicalGroup(2, [surf, top_surf], tag=6, name="frontAndBack")

gmsh.model.mesh.generate(3)
gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
gmsh.write(r'{msh_path}')
print("MSH_OK")
gmsh.finalize()
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=120,
    )
    if "MSH_OK" not in result.stdout:
        raise RuntimeError(f"Grounded Gmsh export failed: {result.stderr[:800]}")


def generate_gmsh_msh(polygon, msh_path, mesh_size=0.2, far_field_factor=15,
                      bl_layers=4, bl_ratio=1.4, structured=False, wind_speed=20.0,
                      grounded=False):
    """Generate a Gmsh .msh file for OpenFOAM (run in subprocess due to signal issues)."""
    if grounded:
        return _grounded_to_msh(polygon, msh_path, mesh_size, far_field_factor,
                                bl_layers, bl_ratio)
    if structured:
        return _omesh_to_msh(polygon, msh_path, wind_speed, far_field_factor)
    script = f"""
import sys, json
sys.path.insert(0, r'{str(Path(__file__).resolve().parent.parent)}')
from tools.cfd_mesh import boundary_layer_params
import gmsh

polygon = {json.dumps(polygon)}

gmsh.initialize()
gmsh.option.setNumber("General.Verbosity", 0)
gmsh.model.add("cfd")

import math

# Densify long edges so BL quads can anchor on every segment.
# Without this, a coarse polygon (e.g. rectangle) has no intermediate
# points along edges → Gmsh BoundaryLayer field fails or leaves gaps.
_dense = []
for i in range(len(polygon)):
    p1, p2 = polygon[i], polygon[(i+1) % len(polygon)]
    edge = math.hypot(p2[0]-p1[0], p2[1]-p1[1])
    n_seg = max(1, int(math.ceil(edge / ({mesh_size} * 3))))
    for j in range(n_seg):
        t = j / n_seg
        _dense.append([p1[0]+t*(p2[0]-p1[0]), p1[1]+t*(p2[1]-p1[1])])
polygon = _dense

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
# first_layer comes from the shared single-source-of-truth sizing so the
# solved mesh matches the UI preview (tools/cfd_mesh.py:boundary_layer_params).
if {bl_layers} > 0:
    first_layer, _bl_n, _bl_r, _bl_outer = boundary_layer_params(
        char_dim, {mesh_size}, wind_speed={wind_speed},
        bl_layers={bl_layers}, bl_ratio={bl_ratio})
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
        capture_output=True, text=True, timeout=120,
    )
    if "MSH_OK" not in result.stdout:
        raise RuntimeError(f"Gmsh export failed: {result.stderr[:500]}")


def run_openfoam(case_dir, polygon, mesh_size=0.2, far_field_factor=15,
                 bl_layers=5, bl_ratio=1.3, n_procs=1, timeout=None,
                 structured=False, wind_speed=20.0, grounded=False,
                 turbulence_model='kEpsilon'):
    """
    Run OpenFOAM simpleFoam via WSL.

    Steps:
    1. Generate Gmsh .msh file
    2. Convert to OpenFOAM polyMesh via gmshToFoam (WSL)
    3. Fix boundary types
    4. renumberMesh (bandwidth reduction) + run simpleFoam (parallel if n_procs>1)
    5. Parse force coefficients

    n_procs > 1 runs decomposePar → mpirun simpleFoam -parallel → reconstructPar.
    Only used for steady runs on large meshes (caller forces n_procs=1 for transient).

    Returns:
        dict with success, log, force_coefficients
    """
    case_dir = Path(case_dir).resolve()
    msh_path = str(case_dir / "mesh.msh")

    # decomposeParDict for parallel runs (scotch auto-partitions)
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

    # Step 1: Generate Gmsh .msh (with boundary layer)
    print(f"  [1/4] Generating Gmsh mesh (BL: {bl_layers} layers, ratio {bl_ratio})...")
    generate_gmsh_msh(polygon, msh_path, mesh_size, far_field_factor,
                      bl_layers=bl_layers, bl_ratio=bl_ratio,
                      structured=structured, wind_speed=wind_speed, grounded=grounded)

    # Detect the solver the controlDict launches (pimpleFoam=transient, simpleFoam=steady).
    # Used by the structured solver override, the parallel reconstruct step, and the
    # timeout estimate below.
    is_transient = "pimpleFoam" in (case_dir / "system" / "controlDict").read_text()

    # For structured O-grid meshes, overwrite solver settings with more robust options.
    # The O-grid topology creates high skewness (>11) and non-orthogonality (>70°) near
    # the sharp TE, which causes GAMG to diverge. PCG+DIC has no coarse grid hierarchy
    # and handles skewed meshes better. Limited correction prevents over-correction in
    # highly skewed cells.
    #
    # Grounded meshes need the same treatment: the body/ground junctions and the BL
    # produce ~hundreds of >70° non-orthogonal faces, on which the default GAMG diverges.
    #
    # The override must stay consistent with the solver the controlDict launches:
    # create_openfoam_case() selects pimpleFoam (transient) or simpleFoam (steady).
    # A steady-only fvSolution (SIMPLE block, no *Final solvers / no PIMPLE dict) makes
    # pimpleFoam abort with "Entry 'UFinal' not found", so branch on the actual solver.
    if structured or grounded:
        # Second turbulence field name must match the model written by create_openfoam_case.
        tvar = "omega" if turbulence_model in ("kOmegaSST", "kOmega") else "epsilon"
        ddt_scheme = "Euler" if is_transient else "steadyState"
        _write_of_file(case_dir / "system" / "fvSchemes", None, None, f"""
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSchemes;
}}
ddtSchemes      {{ default {ddt_scheme}; }}
gradSchemes     {{ default cellLimited Gauss linear 1; }}
divSchemes
{{
    default             none;
    div(phi,U)          bounded Gauss linearUpwind grad(U);
    div(phi,k)          bounded Gauss upwind;
    div(phi,{tvar})    bounded Gauss upwind;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}}
laplacianSchemes {{ default Gauss linear limited 0.5; }}
interpolationSchemes {{ default skewCorrected linear; }}
snGradSchemes {{ default limited 0.5; }}
wallDist {{ method meshWave; }}
""")
        if is_transient:
            # Transient "robust PIMPLE" on the skewed O-grid: keep the robust
            # PCG/PBiCGStab solvers and provide the *Final variants + PIMPLE dict
            # pimpleFoam needs (regex keys "p.*" / "(U|k|epsilon).*" cover base and
            # Final solves). The highly skewed trailing-edge cells trigger a local
            # velocity spike that, without damping, makes the local Courant number
            # explode (→2800) and adjustTimeStep collapse dt toward zero. The cure
            # is the transient analogue of what makes the steady run stable:
            # several outer correctors with under-relaxation. Because the outer
            # loop is iterated to convergence (outerCorrectorResidualControl), the
            # under-relaxation does NOT cost time accuracy — only the within-step
            # path to the converged state is damped.
            _write_of_file(case_dir / "system" / "fvSolution", None, None, ("""
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSolution;
}
solvers
{
    "p.*"            { solver PCG; preconditioner DIC; tolerance 1e-06; relTol 0.01; }
    pFinal           { solver PCG; preconditioner DIC; tolerance 1e-06; relTol 0; }
    "(U|k|epsilon).*" { solver PBiCGStab; preconditioner DILU; tolerance 1e-07; relTol 0.01; }
    Phi              { solver PCG; preconditioner DIC; tolerance 1e-06; relTol 0.01; }
}
PIMPLE
{
    nNonOrthogonalCorrectors 2;
    nCorrectors 2;
    nOuterCorrectors 15;
    pRefCell 0;
    pRefValue 0;
    outerCorrectorResidualControl
    {
        U { tolerance 1e-4; relTol 0; }
        p { tolerance 1e-4; relTol 0; }
    }
}
relaxationFactors
{
    fields    { p 0.3; }
    equations { U 0.7; "(k|epsilon)" 0.7; }
}
""").replace("epsilon", tvar))
        else:
            _write_of_file(case_dir / "system" / "fvSolution", None, None, ("""
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSolution;
}
solvers
{
    p   { solver PCG; preconditioner DIC; tolerance 1e-06; relTol 0.01; }
    pFinal { $p; relTol 0; }
    U   { solver PBiCGStab; preconditioner DILU; tolerance 1e-07; relTol 0.01; }
    k   { solver PBiCGStab; preconditioner DILU; tolerance 1e-07; relTol 0.01; }
    epsilon { solver PBiCGStab; preconditioner DILU; tolerance 1e-07; relTol 0.01; }
    Phi { solver PCG; preconditioner DIC; tolerance 1e-06; relTol 0.01; }
}
SIMPLE
{
    nNonOrthogonalCorrectors 10;
    pRefCell 0;
    pRefValue 0;
    residualControl { p 1e-4; U 1e-4; k 1e-4; epsilon 1e-4; }
}
relaxationFactors
{
    fields    { p 0.1; }
    equations { U 0.3; k 0.3; epsilon 0.3; }
}
""").replace("epsilon", tvar))

    of_case = _of_path(case_dir)

    print(f"  [2/4] Converting mesh + running {'pimpleFoam' if is_transient else 'simpleFoam'} ({n_procs} procs)...")
    if n_procs > 1:
        # Transient animation needs every written time step, so reconstruct them all;
        # steady only needs the converged final state.
        reconstruct = "reconstructPar" if is_transient else "reconstructPar -latestTime"
        run_block = (
            f'echo "=== decomposePar ({n_procs} domains) ==="\n'
            f'decomposePar -force 2>&1 | tail -3\n'
            f'mpirun --allow-run-as-root --oversubscribe -np {n_procs} $SOLVER -parallel 2>&1 || $SOLVER 2>&1\n'
            f'echo "=== SOLVER_RC=$? ==="\n'
            f'echo "=== reconstructPar ==="\n'
            f'{reconstruct} 2>&1 | tail -3'
        )
    else:
        run_block = '$SOLVER 2>&1\necho "=== SOLVER_RC=$? ==="'
    of_script = f"""#!/bin/bash
for _of in /usr/lib/openfoam/openfoam2412/etc/bashrc /usr/lib/openfoam/openfoam2406/etc/bashrc /opt/openfoam*/etc/bashrc; do [ -f "$_of" ] && source "$_of" && break; done
cd "{of_case}"

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
txt = re.sub(r'(section[^{{]*{{[^}}]*type\\s+)\\w+', r'\\g<1>wall', txt)
txt = re.sub(r'(ground[^{{]*{{[^}}]*type\\s+)\\w+', r'\\g<1>wall', txt)
txt = re.sub(r'(frontAndBack[^{{]*{{[^}}]*type\\s+)\\w+', r'\\g<1>empty', txt)
with open('boundary','w') as f: f.write(txt)
print('Boundary: section/ground=wall, frontAndBack=empty')
" 2>&1
cd "{of_case}"

echo "=== renumberMesh ==="
renumberMesh -overwrite 2>&1 | tail -3 || true

echo "=== potentialFoam ==="
potentialFoam -writep 2>&1 | tail -5 || true

echo "=== Starting solver ==="
SOLVER=$(grep "application" system/controlDict | awk '{{print $2}}' | tr -d ';\\r\\n')
echo "Solver: $SOLVER"
{run_block}

echo "=== Post-processing: vorticity ==="
postProcess -func vorticity 2>&1 | tail -5 || true

echo "=== DONE ==="
"""
    script_path = case_dir / "run_of.sh"
    with open(script_path, "w", newline="\n") as f:
        f.write(of_script)

    # Auto-scale the timeout. The transient timestep is adaptive (Courant-limited)
    # and seeded tiny, so it can't be derived from controlDict's deltaT — estimate
    # instead from the simulated duration. Measured cost on this skewed O-grid with
    # the robust PIMPLE setup is ~1500 s per simulated second on 4 cores; the formula
    # below keeps ~1.5x headroom over that, capped at 1h, so healthy runs never get
    # killed mid-solve (the old deltaT-based estimate misparsed the 1e-5 seed and
    # always clamped to 300s, killing transient runs partway through).
    if timeout is None:
        try:
            ctrl = (case_dir / "system" / "controlDict").read_text()
            import re as _re
            end_t = float(_re.search(r'endTime\s+([\d.eE+-]+)', ctrl).group(1))
            if is_transient:
                timeout = int(min(3600, max(300, end_t * 6500 / max(1, n_procs) * 1.4 + 90)))
            else:
                timeout = 300
        except Exception:
            timeout = 300

    try:
        result = _run_of_script(script_path, case_dir, timeout=timeout)
        log = result.stdout.decode("utf-8", errors="replace")
        log += result.stderr.decode("utf-8", errors="replace")
        success = _solver_succeeded(log)

        # Step 4: Parse results
        force_coeffs = _parse_force_coeffs(case_dir)
        # A solver can exit 0 yet have diverged: with FOAM_SIGFPE off, an
        # impulsive-start blow-up on thin/sharp sections propagates NaN instead
        # of trapping, so pimpleFoam finishes the loop with coefficients at
        # 1e+70+ or NaN. Treat that as a failed solve rather than surfacing
        # garbage as success.
        if success and _coeffs_diverged(force_coeffs):
            success = False
            log += "\n=== SOLVER DIVERGED (force coefficients non-finite / abnormal) ==="

        print(f"  [3/4] simpleFoam {'OK' if success else 'FAILED'}")
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


def _coeffs_diverged(fc):
    """True if force coefficients are non-finite or absurdly large.

    A transient pimpleFoam run can print "=== DONE ===" without a FOAM FATAL
    yet have blown up numerically — the impulsive free-stream start overshoots
    on thin/sharp sections and the field diverges, leaving Cd/Cl/Cm at 1e+70+
    or NaN/Inf. No physical force coefficient, however undeveloped a snapshot,
    approaches 1e6, so that threshold cleanly separates divergence from a merely
    unconverged early-time value. Used to stop run_openfoam reporting a blown-up
    solve as success with garbage coefficients.
    """
    if not fc:
        return False
    for k in ("Cd", "Cl", "Cm"):
        v = fc.get(k)
        if v is None:
            continue
        if not math.isfinite(v) or abs(v) > 1e6:
            return True
    return False


def _solver_succeeded(log):
    """True if the solver ran to completion with a zero exit code.

    The run scripts echo `=== SOLVER_RC=$? ===` immediately after the solver
    invocation (before reconstructPar / post-processing), so the solver's exit
    status is captured authoritatively — an FPE/segfault exits non-zero and is
    caught here even though it produces no "FOAM FATAL" line. This is
    deliberately narrower than scanning the whole log for a crash signature:
    potentialFoam initialisation (before the solver) and the trailing
    postProcess steps (after it) run under `|| true` and are ALLOWED to crash
    without failing the solve. An FPE in potentialFoam is common on skewed
    meshes and does not affect the pimpleFoam solve, so a log-wide crash scan
    false-positives on it. The `=== DONE ===` marker additionally guards against
    the script being killed (timeout) between the solver and DONE.
    """
    return "=== SOLVER_RC=0 ===" in log and "=== DONE ===" in log


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
                      z0=0.1, mesh_size=None, domain_factor=3, n_procs=6,
                      n_iterations=500, rot_x=0, rot_y=0, rot_z=0,
                      transient=False, end_time=5.0, dt=0.05):
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
        transient=transient, end_time=end_time, dt=dt,
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


def run_openfoam_3d_stl(case_dir, n_procs=6, transient=False):
    """Run OpenFOAM with snappyHexMesh for STL-based geometry."""
    case_dir = Path(case_dir).resolve()
    of_case = _of_path(case_dir)

    of_script = f"""#!/bin/bash
for _of in /usr/lib/openfoam/openfoam2412/etc/bashrc /usr/lib/openfoam/openfoam2406/etc/bashrc /opt/openfoam*/etc/bashrc; do [ -f "$_of" ] && source "$_of" && break; done
cd "{of_case}"

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
cd "{of_case}"

echo "=== renumberMesh ==="
renumberMesh -overwrite 2>&1 | tail -3 || true

echo "=== simpleFoam ({n_procs} procs) ==="
{"decomposePar 2>&1 | tail -3 && mpirun --allow-run-as-root --oversubscribe -np " + str(n_procs) + " simpleFoam -parallel 2>&1 || simpleFoam 2>&1" if n_procs > 1 else "simpleFoam 2>&1"}
echo "=== SOLVER_RC=$? ==="

{"reconstructPar 2>&1 | tail -3" if n_procs > 1 and transient else ("reconstructPar -latestTime 2>&1 | tail -3" if n_procs > 1 else "")}

echo "=== Post-processing ==="
postProcess -func writeCellCentres -latestTime 2>&1 | tail -3 || true
postProcess -func wallShearStress -latestTime 2>&1 | tail -3 || true

echo "=== DONE ==="
"""
    script_path = case_dir / "run_snappy.sh"
    with open(script_path, "w", newline="\n") as f:
        f.write(of_script)

    try:
        result = _run_of_script(script_path, case_dir, timeout=900)
        log = result.stdout.decode("utf-8", errors="replace")
        log += result.stderr.decode("utf-8", errors="replace")
        success = _solver_succeeded(log)

        force_coeffs  = _parse_force_coeffs(case_dir)
        force_history = _parse_force_history(case_dir) if transient else None
        time_steps    = _list_time_steps(case_dir) if transient else []

        # A run can reach "=== DONE ===" yet have diverged (impulsive start on
        # sharp building edges): the coefficients then read 1e+70+ or NaN.
        if success and _coeffs_diverged(force_coeffs):
            success = False
            log += "\n=== SOLVER DIVERGED (force coefficients non-finite / abnormal) ==="

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
            "time_steps": time_steps,
            "force_history": force_history,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "log": "Timed out (900s)", "force_coefficients": None}


def create_openfoam_case_3d(footprint, height, wind_speed=10.0, wind_angle=0.0,
                             z0=0.1, zref=None, nu=1.5e-5,
                             output_dir=None, n_iterations=1000, n_procs=6,
                             buildings=None, transient=False, end_time=5.0, dt=0.05,
                             flow_type='abl'):
    """Create a 3D OpenFOAM case for building aerodynamics.

    flow_type: 'abl'     — atmospheric boundary layer inlet (log-law)
               'channel' — uniform channel flow inlet (fixedValue)
    """
    H = max(b["height"] for b in buildings) if buildings else height
    if zref is None:
        zref = H  # Reference height = building height
    if output_dir is None:
        import tempfile
        output_dir = tempfile.mkdtemp(prefix="cfd3d_")
    case_dir = Path(output_dir)

    # Wind direction: the domain inlet is always at x_min, so we rotate the building
    # footprint by -wind_angle to face the wind, and keep flow in +x direction.
    # This matches how prepare_stl_case handles oblique wind (rot_z = -wind_angle).
    rad = math.radians(wind_angle)
    rot_footprint = list(footprint)
    rot_buildings = buildings

    if abs(wind_angle) > 0.1:
        cos_r = math.cos(-rad)
        sin_r = math.sin(-rad)
        # Rotate around the centroid of all buildings
        if buildings:
            all_pts = [p for b in buildings for p in b["footprint"]]
        else:
            all_pts = list(footprint)
        cx_r = sum(p[0] for p in all_pts) / max(len(all_pts), 1)
        cy_r = sum(p[1] for p in all_pts) / max(len(all_pts), 1)

        def _rot2d(fp):
            return [
                [cx_r + (x - cx_r) * cos_r - (y - cy_r) * sin_r,
                 cy_r + (x - cx_r) * sin_r + (y - cy_r) * cos_r]
                for x, y in fp
            ]

        rot_footprint = _rot2d(footprint)
        if buildings:
            rot_buildings = [{**b, "footprint": _rot2d(b["footprint"])} for b in buildings]
        print(f"  Rotated footprint by -{wind_angle}° so wind flows in +x")

    # Wind always flows in +x after rotation
    flow_x, flow_y = 1.0, 0.0

    # Turbulence parameters — kOmegaSST
    kappa = 0.41
    Cmu = 0.09
    if flow_type == 'channel':
        # Uniform channel flow: simple intensity + length-scale approach
        I_turb = 0.05           # 5 % turbulence intensity
        L_turb = max(0.1 * H, 0.001)
        k_inlet     = 1.5 * (I_turb * wind_speed) ** 2
        omega_inlet = math.sqrt(k_inlet) / (Cmu ** 0.25 * L_turb)
        nut_inlet   = k_inlet / max(omega_inlet, 1e-10)
    else:
        # ABL log-law based
        u_star      = wind_speed * kappa / math.log(max(zref, 1.0) / max(z0, 0.001))
        k_inlet     = u_star ** 2 / math.sqrt(Cmu)
        omega_inlet = u_star / (math.sqrt(Cmu) * kappa * max(zref, 1.0))
        nut_inlet   = k_inlet / max(omega_inlet, 1e-10)

    # Footprint dimensions for force coefficients (use rotated footprint; wind is +x)
    if rot_buildings:
        xs = [p[0] for b in rot_buildings for p in b["footprint"]]
        ys = [p[1] for b in rot_buildings for p in b["footprint"]]
    else:
        xs = [p[0] for p in rot_footprint]
        ys = [p[1] for p in rot_footprint]
    char_w = max(xs) - min(xs)
    char_d = max(ys) - min(ys)
    # Frontal area: with wind in +x, the frontal width is the y-extent of the building
    frontal_width = char_d
    a_ref = frontal_width * H

    Re = wind_speed * H / nu
    print(f"  3D CFD: H={H}m, v={wind_speed}m/s, Re={Re:.0f}, z0={z0}m")

    for d in ["0", "constant", "system", "constant/polyMesh"]:
        (case_dir / d).mkdir(parents=True, exist_ok=True)

    # ── ABL include file (only needed for ABL inlet) ──
    (case_dir / "0" / "include").mkdir(exist_ok=True)
    if flow_type != 'channel':
        with open(case_dir / "0" / "include" / "ABLConditions", "w", newline="\n") as f:
            f.write(f"""Uref    {wind_speed};
Zref    {zref};
zDir    (0 0 1);
flowDir ({flow_x} {flow_y} 0);
z0      uniform {z0};
d       uniform 0.0;
""")

    # ── 0/U ──
    _inlet_U_bc = (
        f"        type            fixedValue;\n"
        f"        value           uniform ({wind_speed * flow_x:.6g} {wind_speed * flow_y:.6g} 0);"
        if flow_type == 'channel' else
        f"        type            atmBoundaryLayerInletVelocity;\n"
        f"        #include        \"include/ABLConditions\""
    )
    _write_of_file(case_dir / "0" / "U", "volVectorField", "U", f"""
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform ({wind_speed * flow_x} {wind_speed * flow_y} 0);
boundaryField
{{
    inlet
    {{
{_inlet_U_bc}
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
    _inlet_k_bc = (
        f"        type            fixedValue;\n"
        f"        value           uniform {k_inlet:.6g};"
        if flow_type == 'channel' else
        f"        type            atmBoundaryLayerInletK;\n"
        f"        #include        \"include/ABLConditions\""
    )
    _write_of_file(case_dir / "0" / "k", "volScalarField", "k", f"""
dimensions      [0 2 -2 0 0 0 0];
internalField   uniform {k_inlet};
boundaryField
{{
    inlet
    {{
{_inlet_k_bc}
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

    # ── 0/omega ──
    _write_of_file(case_dir / "0" / "omega", "volScalarField", "omega", f"""
dimensions      [0 0 -1 0 0 0 0];
internalField   uniform {omega_inlet};
boundaryField
{{
    inlet
    {{
        type            fixedValue;
        value           uniform {omega_inlet};
    }}
    outlet
    {{
        type            inletOutlet;
        inletValue      uniform {omega_inlet};
        value           $internalField;
    }}
    ground
    {{
        type            omegaWallFunction;
        value           uniform {omega_inlet};
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
        type            omegaWallFunction;
        value           uniform {omega_inlet};
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
        type            nutkWallFunction;
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
        type            nutkWallFunction;
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
    RASModel        kOmegaSST;
    turbulence      on;
    printCoeffs     on;
}
""")

    # ── system/ ──
    if transient:
        _solver_app   = "pimpleFoam"
        _end_t        = end_time
        _delta_t      = dt
        _write_int    = max(1, int(round(0.1 / dt)))  # write every ~0.1 s
        _purge        = 0   # keep all time steps for animation
    else:
        _solver_app   = "simpleFoam"
        _end_t        = n_iterations
        _delta_t      = 1
        _write_int    = max(50, n_iterations // 5)
        _purge        = 2

    _write_of_file(case_dir / "system" / "controlDict", None, None, f"""
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}}
libs            ("libatmosphericModels.so");
application     {_solver_app};
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         {_end_t};
deltaT          {_delta_t};
writeControl    timeStep;
writeInterval   {_write_int};
purgeWrite      {_purge};
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

    _ddt = "Euler" if transient else "steadyState"
    _write_of_file(case_dir / "system" / "fvSchemes", None, None, f"""
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSchemes;
}}
ddtSchemes      {{ default {_ddt}; }}
gradSchemes     {{ default Gauss linear; }}
divSchemes
{{
    default             none;
    div(phi,U)          {"Gauss linearUpwind grad(U)" if transient else "bounded Gauss linearUpwind grad(U)"};
    div(phi,k)          {"Gauss upwind" if transient else "bounded Gauss upwind"};
    div(phi,omega)      {"Gauss upwind" if transient else "bounded Gauss upwind"};
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}}
laplacianSchemes {{ default Gauss linear corrected; }}
interpolationSchemes {{ default linear; }}
snGradSchemes {{ default corrected; }}
wallDist {{ method meshWave; }}
""")

    if transient:
        _fv_solution = f"""
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSolution;
}}
solvers
{{
    p       {{ solver GAMG; smoother GaussSeidel; tolerance 1e-06; relTol 0.01; }}
    pFinal  {{ $p; relTol 0; }}
    U       {{ solver smoothSolver; smoother GaussSeidel; tolerance 1e-07; relTol 0.01; }}
    UFinal  {{ $U; relTol 0; }}
    k       {{ solver smoothSolver; smoother GaussSeidel; tolerance 1e-07; relTol 0.01; }}
    kFinal  {{ $k; relTol 0; }}
    omega   {{ solver smoothSolver; smoother GaussSeidel; tolerance 1e-07; relTol 0.01; }}
    omegaFinal {{ $omega; relTol 0; }}
}}
PIMPLE
{{
    nOuterCorrectors        2;
    nCorrectors             2;
    nNonOrthogonalCorrectors 1;
    pRefCell 0;
    pRefValue 0;
}}
relaxationFactors
{{
    fields    {{ p 0.7; }}
    equations {{ U 0.9; k 0.9; omega 0.9; }}
}}
"""
    else:
        _fv_solution = f"""
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
    omega {{ solver smoothSolver; smoother GaussSeidel; tolerance 1e-07; relTol 0.01; }}
}}
SIMPLE
{{
    nNonOrthogonalCorrectors 2;
    consistent      yes;
    pRefCell 0;
    pRefValue 0;
    residualControl {{ p 1e-4; U 1e-4; k 1e-4; omega 1e-4; }}
}}
relaxationFactors
{{
    fields {{ p 0.3; }}
    equations {{ U 0.5; k 0.5; omega 0.5; }}
}}
"""
    _write_of_file(case_dir / "system" / "fvSolution", None, None, _fv_solution)

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
        "footprint": footprint,            # original (unrotated) footprint
        "rot_footprint": rot_footprint,    # rotated for mesh generation
        "height": H,
        "wind_speed": wind_speed,
        "wind_angle": wind_angle,
        "z0": z0,
        "Re": Re,
        "n_procs": n_procs,
    }
    if buildings:
        meta["buildings"] = buildings
    if rot_buildings and rot_buildings is not buildings:
        meta["rot_buildings"] = rot_buildings
    with open(case_dir / "case_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print(f"  3D OpenFOAM case created: {case_dir}")
    return str(case_dir)


def run_openfoam_3d(case_dir, footprint, height, mesh_size=None,
                     domain_factors=None, n_procs=6, buildings=None, transient=False):
    """Run 3D OpenFOAM building simulation via WSL."""
    case_dir = Path(case_dir).resolve()
    msh_path = str(case_dir / "mesh.msh")

    # Use rotated footprint if create_openfoam_case_3d already applied the wind rotation
    meta_path = case_dir / "case_meta.json"
    if meta_path.exists():
        with open(meta_path) as _f:
            _meta = json.load(_f)
        if "rot_footprint" in _meta:
            footprint = _meta["rot_footprint"]
        if "rot_buildings" in _meta:
            buildings = _meta["rot_buildings"]

    print("  [1/4] Generating 3D Gmsh mesh...")
    mesh_stats = generate_gmsh_msh_3d(footprint, height, msh_path,
                                       mesh_size=mesh_size,
                                       domain_factors=domain_factors,
                                       buildings=buildings)
    print(f"  Mesh: {mesh_stats['n_nodes']} nodes, {mesh_stats['n_cells']} cells")

    of_case = _of_path(case_dir)

    use_parallel = n_procs > 1
    print(f"  [2/4] Converting mesh + running simpleFoam ({n_procs} procs)...")
    of_script = f"""#!/bin/bash
for _of in /usr/lib/openfoam/openfoam2412/etc/bashrc /usr/lib/openfoam/openfoam2406/etc/bashrc /opt/openfoam*/etc/bashrc; do [ -f "$_of" ] && source "$_of" && break; done
cd "{of_case}"

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
cd "{of_case}"

echo "=== checkMesh ==="
checkMesh 2>&1 | grep -E "cells|faces|Maximum|Minimum|FAILED|OK|WARNING" || true

echo "=== renumberMesh ==="
renumberMesh -overwrite 2>&1 | tail -3 || true

{"" if not use_parallel else f'''echo "=== decomposePar ({n_procs} domains) ==="
decomposePar 2>&1 | tail -5
'''}
echo "=== Starting simpleFoam ==="
{"mpirun --allow-run-as-root --oversubscribe -np " + str(n_procs) + " simpleFoam -parallel 2>&1 || simpleFoam 2>&1" if use_parallel else "simpleFoam 2>&1"}
echo "=== SOLVER_RC=$? ==="

{"" if not use_parallel else ('echo "=== reconstructPar ==="\nreconstructPar 2>&1 | tail -3' if transient else 'echo "=== reconstructPar ==="\nreconstructPar -latestTime 2>&1 | tail -3')}

echo "=== Post-processing: writeCellCentres ==="
postProcess -func writeCellCentres -latestTime 2>&1 | tail -3 || true

echo "=== Post-processing: vorticity ==="
postProcess -func vorticity -latestTime 2>&1 | tail -3 || true

echo "=== Post-processing: wallShearStress ==="
postProcess -func wallShearStress -latestTime 2>&1 | tail -3 || true

echo "=== DONE ==="
"""
    script_path = case_dir / "run_of_3d.sh"
    with open(script_path, "w", newline="\n") as f:
        f.write(of_script)

    try:
        result = _run_of_script(script_path, case_dir, timeout=600)
        log = result.stdout.decode("utf-8", errors="replace")
        log += result.stderr.decode("utf-8", errors="replace")
        success = _solver_succeeded(log)

        force_coeffs  = _parse_force_coeffs(case_dir)
        force_history = _parse_force_history(case_dir) if transient else None
        time_steps    = _list_time_steps(case_dir) if transient else []

        # A run can reach "=== DONE ===" yet have diverged (impulsive start on
        # sharp building edges): the coefficients then read 1e+70+ or NaN.
        if success and _coeffs_diverged(force_coeffs):
            success = False
            log += "\n=== SOLVER DIVERGED (force coefficients non-finite / abnormal) ==="

        print(f"  [3/4] simpleFoam {'OK' if success else 'FAILED'}")
        print(f"  [4/4] Force coefficients: {force_coeffs}, time steps: {len(time_steps)}")

        return {
            "success": success,
            "log": log[-3000:],
            "force_coefficients": force_coeffs,
            "mesh_stats": mesh_stats,
            "time_steps": time_steps,
            "force_history": force_history,
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

    # Parse cell centers — try several locations then fall back to mesh computation
    cell_centers = None
    c_path = latest / "C"
    if c_path.exists():
        cell_centers = _parse_of_vector_field(c_path)
    if not cell_centers:
        pp_wcc = case_dir / "postProcessing" / "writeCellCentres"
        if pp_wcc.exists():
            pp_times = sorted([d for d in pp_wcc.iterdir() if d.is_dir()],
                              key=lambda d: float(d.name) if d.name.replace('.','',1).isdigit() else 0)
            for pt in reversed(pp_times):
                cell_centers = _parse_of_vector_field(pt / "C")
                if cell_centers:
                    break
    if not cell_centers:
        cell_centers = _cell_centers_from_mesh(case_dir / "constant" / "polyMesh")
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


def _cell_centers_from_mesh(mesh_dir):
    """Compute approximate cell centers from constant/polyMesh (always available).

    Averages the face centers of all faces belonging to each cell — fast enough
    for meshes up to ~500 k cells using numpy.
    """
    mesh_dir = Path(mesh_dir)
    points_raw = _parse_of_vector_field(mesh_dir / "points")
    faces_raw  = _parse_of_faces(mesh_dir / "faces")
    owner_raw  = _parse_of_int_list(mesh_dir / "owner")
    if not points_raw or not faces_raw or not owner_raw:
        return None
    try:
        import numpy as np
        pts   = np.array(points_raw, dtype=np.float64)
        owner = np.array(owner_raw,  dtype=np.int32)

        n_cells = int(owner.max()) + 1
        cell_sum = np.zeros((n_cells, 3), dtype=np.float64)
        cell_cnt = np.zeros(n_cells, dtype=np.int32)
        for fi, face in enumerate(faces_raw):
            if fi >= len(owner_raw):
                break
            fc = pts[face].mean(axis=0)
            c  = owner_raw[fi]
            cell_sum[c] += fc
            cell_cnt[c] += 1

        neighbour_raw = _parse_of_int_list(mesh_dir / "neighbour")
        if neighbour_raw:
            for fi, face in enumerate(faces_raw):
                if fi >= len(neighbour_raw):
                    break
                fc = pts[face].mean(axis=0)
                c  = neighbour_raw[fi]
                if 0 <= c < n_cells:
                    cell_sum[c] += fc
                    cell_cnt[c] += 1

        mask = cell_cnt > 0
        cell_sum[mask] /= cell_cnt[mask, np.newaxis]
        return [tuple(row) for row in cell_sum]
    except Exception:
        return None


def _list_time_steps(case_dir):
    """Return sorted list of solved time step values (float) from a case directory."""
    steps = []
    for d in Path(case_dir).iterdir():
        if d.is_dir():
            try:
                t = float(d.name)
                if t > 0 and (d / "p").exists():
                    steps.append(t)
            except ValueError:
                pass
    return sorted(steps)


def extract_slice(case_dir, plane="z", value=0, field="pressure", tolerance=None, time_step=None):
    """Extract a 2D slice from 3D CFD results.

    Args:
        case_dir: Path to OpenFOAM case
        plane: 'x', 'y', or 'z'
        value: coordinate value for the slice
        field: 'pressure', 'speed', or 'turb_k'
        tolerance: slice thickness (auto if None)
        time_step: specific time value to read (None = latest)

    Returns dict compatible with 2D visualization: {nodes, triangles, p_range}
    """
    case_dir = Path(case_dir)

    # Find target time directory (specific step or latest)
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
    if time_step is not None:
        latest = min(time_dirs, key=lambda d: abs(float(d.name) - float(time_step)))
    else:
        latest = time_dirs[-1]

    # Parse cell centers — try several locations then fall back to mesh computation
    cell_centers = None
    c_path = latest / "C"
    if c_path.exists():
        cell_centers = _parse_of_vector_field(c_path)
    if not cell_centers:
        pp_wcc = case_dir / "postProcessing" / "writeCellCentres"
        if pp_wcc.exists():
            pp_times = sorted([d for d in pp_wcc.iterdir() if d.is_dir()],
                              key=lambda d: float(d.name) if d.name.replace('.','',1).isdigit() else 0)
            for pt in reversed(pp_times):
                cell_centers = _parse_of_vector_field(pt / "C")
                if cell_centers:
                    break
    if not cell_centers:
        cell_centers = _cell_centers_from_mesh(case_dir / "constant" / "polyMesh")
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
    # Use rotated footprint if available — that's the actual geometry in the CFD domain.
    footprint = meta.get("rot_footprint") or meta.get("footprint", [])
    bld_height = meta.get("height", 0)
    # Use rotated buildings footprints for the mask
    raw_bld = meta.get("rot_buildings") or meta.get("buildings", [])
    bld_list = raw_bld if raw_bld else []

    # Compute building-centered crop region (all buildings).
    # The crop sets the grid resolution near the body (grid spacing = crop_span / n_grid).
    # On a HORIZONTAL (z) slice the cutout is the footprint, so the crop must scale with
    # the footprint span — NOT the building height, otherwise a tall slim tower (e.g. a
    # cylinder) gets a huge height-driven crop and its round cross-section renders as a
    # coarse grid staircase. Vertical slices keep the height-based crop (they need the
    # full vertical extent for the wake).
    crop_radius = None
    bld_cx, bld_cy = 0, 0
    if bld_list:
        all_xs = [p[0] for b in bld_list for p in b["footprint"]]
        all_ys = [p[1] for b in bld_list for p in b["footprint"]]
        bld_cx = (min(all_xs) + max(all_xs)) / 2
        bld_cy = (min(all_ys) + max(all_ys)) / 2
        bld_span = max(max(all_xs) - min(all_xs), max(all_ys) - min(all_ys))
        crop_radius = (bld_span * 3.0) if plane == "z" else (max(bld_span, bld_height) * 2.0)
    elif footprint and bld_height > 0:
        fp_xs = [p[0] for p in footprint]
        fp_ys = [p[1] for p in footprint]
        bld_cx = (min(fp_xs) + max(fp_xs)) / 2
        bld_cy = (min(fp_ys) + max(fp_ys)) / 2
        bld_span = max(max(fp_xs) - min(fp_xs), max(fp_ys) - min(fp_ys))
        # Horizontal: ~4× footprint span (building + near wake) → fine grid on the cutout.
        # Vertical: 3× max(span, height) as before.
        crop_radius = (bld_span * 4.0) if plane == "z" else (max(bld_span, bld_height) * 3.0)

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

    # Build footprint polygon mask to exclude building interior.
    # plane == "z" (horizontal): 2D coords are (x, y) — check if inside footprint.
    # plane == "y" (vertical):   2D coords are (x, z) — check if (x, y_slice) inside
    #                             footprint AND z <= building height.
    # plane == "x": not yet handled (rare).
    fp_polys = []          # for plane=="z": list of footprint polygons
    fp_polys_vert = []     # for plane=="y": list of (footprint, max_z)

    if plane == "z":
        if bld_list:
            for b in bld_list:
                if 0 <= value <= b["height"]:
                    fp_polys.append(b["footprint"])
        elif footprint and 0 <= value <= bld_height:
            fp_polys = [footprint]
    elif plane == "y":
        # For vertical slice at y=value: a grid node at 2D (px=x, py=z) is inside a
        # building if (px, value) lies inside the footprint and py <= building height.
        if bld_list:
            for b in bld_list:
                fp_polys_vert.append((b["footprint"], b["height"]))
        elif footprint and bld_height > 0:
            fp_polys_vert = [(footprint, bld_height)]

    # Build grid nodes and triangles (two tris per quad cell)
    grid_nodes = []
    node_id_map = {}  # (iy, ix) → sequential node id
    nid = 0
    for iy in range(n_grid):
        for ix in range(n_grid):
            v = grid_vals[iy, ix]
            if np.isnan(v):
                continue
            # Skip points inside any building
            px, py = gx[ix], gy[iy]
            if fp_polys and any(_point_in_polygon(px, py, fp) for fp in fp_polys):
                continue
            if fp_polys_vert and any(
                py <= h and _point_in_polygon(px, value, fp)
                for fp, h in fp_polys_vert
            ):
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
    of_case = _of_path(case_dir)
    script = f"""#!/bin/bash
for _of in /usr/lib/openfoam/openfoam2412/etc/bashrc /usr/lib/openfoam/openfoam2406/etc/bashrc /opt/openfoam*/etc/bashrc; do [ -f "$_of" ] && source "$_of" && break; done
cd "{of_case}"
postProcess -func streamLineDict -latestTime 2>&1 | tail -5
echo "STREAMLINE_DONE"
"""
    script_path = case_dir / "run_streamlines.sh"
    with open(script_path, "w", newline="\n") as f:
        f.write(script)

    try:
        result = _run_of_script(script_path, case_dir, timeout=60)
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


###############################################################################
# ── Surface streamlines (wallShearStress) ────────────────────────────────────
###############################################################################


def _parse_of_boundary(filepath):
    """Parse constant/polyMesh/boundary → {name: {type, nFaces, startFace}} per patch."""
    import re
    filepath = Path(filepath)
    if not filepath.exists():
        return {}
    content = filepath.read_text(errors='replace')
    patches = {}
    pat = re.compile(
        r'(\w+)\s*\{[^}]*?type\s+(\w+)\s*;[^}]*?nFaces\s+(\d+)\s*;[^}]*?startFace\s+(\d+)\s*;',
        re.DOTALL
    )
    skip = {'FoamFile', 'class', 'object', 'format', 'version', 'location'}
    for m in pat.finditer(content):
        name = m.group(1)
        if name not in skip:
            patches[name] = {
                'type': m.group(2),
                'nFaces': int(m.group(3)),
                'startFace': int(m.group(4)),
            }
    return patches


def _parse_of_points_np(filepath):
    """Parse OpenFOAM points file → numpy array (N, 3)."""
    import numpy as np, re
    filepath = Path(filepath)
    if not filepath.exists():
        return None
    content = filepath.read_text(errors='replace')
    hdr_end = content.find('}', content.find('FoamFile') if 'FoamFile' in content else 0)
    after_hdr = content[hdr_end:] if hdr_end >= 0 else content
    m = re.search(r'\b(\d+)\s*\n\s*\(', after_hdr)
    if not m:
        return None
    matches = re.findall(r'\(\s*([\S]+)\s+([\S]+)\s+([\S]+)\s*\)', after_hdr[m.end():])
    if not matches:
        return None
    return np.array([[float(x), float(y), float(z)] for x, y, z in matches], dtype=np.float64)


def _parse_patch_vector_field(filepath, patch_name):
    """Parse nonuniform vector values for one boundary patch in an OF vector field file.
    Returns list of (x,y,z) tuples or None if the patch is not found / uses uniform value."""
    import re
    filepath = Path(filepath)
    if not filepath.exists():
        return None
    content = filepath.read_text(errors='replace')
    bf_start = content.find('boundaryField')
    if bf_start < 0:
        return None
    bf_text = content[bf_start:]
    m = re.compile(r'\b' + re.escape(patch_name) + r'\s*\{').search(bf_text)
    if not m:
        return None
    brace = bf_text.index('{', m.start())
    depth = 1; pos = brace + 1
    while pos < len(bf_text) and depth > 0:
        if bf_text[pos] == '{': depth += 1
        elif bf_text[pos] == '}': depth -= 1
        pos += 1
    block = bf_text[brace:pos]
    vm = re.search(
        r'value\s+nonuniform\s+List<vector>\s*\d+\s*\(([^;]+)\)',
        block, re.DOTALL
    )
    if not vm:
        return None
    vecs = re.findall(r'\(\s*([\S]+)\s+([\S]+)\s+([\S]+)\s*\)', vm.group(1))
    return [(float(x), float(y), float(z)) for x, y, z in vecs]


def _integrate_surface_streamlines(centers, normals, vectors, n_seeds=40, n_steps=200):
    """Euler-based nearest-neighbour streamline integration on a surface mesh.
    Returns list of polylines [[x,y,z], ...] in input coordinate space."""
    import numpy as np
    try:
        from scipy.spatial import cKDTree
    except ImportError:
        return []

    magnitudes = np.linalg.norm(vectors, axis=1)
    if not (magnitudes > 1e-10).any():
        return []

    tree = cKDTree(centers)
    # Estimate step size from typical face-centre spacing
    sample = centers[::max(1, len(centers) // 300)]
    dists, _ = tree.query(sample, k=min(3, len(sample)))
    ds = float(np.median(dists[:, 1])) * 0.7 if dists.shape[1] > 1 else 0.5
    ds = max(0.02, min(ds, 10.0))

    # Weight seeds by shear stress magnitude
    w = magnitudes / magnitudes.sum()
    rng = np.random.default_rng(42)
    n_actual = min(n_seeds, int((magnitudes > 1e-10).sum()))
    seed_ids = rng.choice(len(centers), size=n_actual, replace=False, p=w)

    lines = []
    for si in seed_ids:
        pts = [centers[si].tolist()]
        pos = centers[si].copy()
        seen: set = {si}

        for step in range(n_steps):
            _, idx = tree.query(pos)
            if magnitudes[idx] < 1e-10:
                break
            if step > 5 and idx in seen:
                break
            if step % 4 == 0:
                seen.add(idx)

            v = np.array(vectors[idx], dtype=np.float64)
            n = normals[idx]
            v -= np.dot(v, n) * n  # project onto surface tangent
            v_mag = np.linalg.norm(v)
            if v_mag < 1e-10:
                break
            pos = pos + (v / v_mag) * ds
            pts.append([round(float(pos[0]), 3), round(float(pos[1]), 3), round(float(pos[2]), 3)])

        if len(pts) > 5:
            lines.append(pts)

    return lines


def extract_surface_streamlines(case_dir, n_seeds=40, n_steps=200):
    """Extract surface streamlines from wallShearStress on building wall patches.

    Returns list of polylines [[x,y,z], ...] in OpenFOAM Z-up coordinates.
    Returns [] if wallShearStress was not computed or mesh files are too large.
    """
    import numpy as np
    case_dir = Path(case_dir)

    # Find latest time directory that contains wallShearStress
    wss_file = None
    best_t = -1.0
    for d in case_dir.iterdir():
        if not d.is_dir():
            continue
        try:
            t = float(d.name)
            if t > 0 and t > best_t and (d / 'wallShearStress').exists():
                best_t = t
                wss_file = d / 'wallShearStress'
        except ValueError:
            pass

    if wss_file is None:
        print('  [surface-lines] wallShearStress not found in any time directory')
        return []

    print(f'  [surface-lines] using {wss_file}')

    # Read boundary patch info
    boundary_file = case_dir / 'constant' / 'polyMesh' / 'boundary'
    patches = _parse_of_boundary(boundary_file)
    if not patches:
        print('  [surface-lines] no boundary patches found')
        return []

    # Skip non-building patches (ground, inlet, outlet, etc.)
    _skip = {'ground', 'terrain', 'floor', 'bottom', 'sky', 'top',
             'inlet', 'outlet', 'atmosphere', 'front', 'back', 'left', 'right',
             'frontandback', 'sides', 'symmetry', 'side', 'wall'}
    building_patches = {}
    for name, info in patches.items():
        if info['type'] != 'wall':
            continue
        if name.lower() in _skip:
            continue
        if any(s in name.lower() for s in ('ground', 'terrain', 'inlet', 'outlet', 'atm')):
            continue
        wss_vals = _parse_patch_vector_field(wss_file, name)
        if wss_vals and len(wss_vals) == info['nFaces']:
            building_patches[name] = {'info': info, 'wss': wss_vals}

    if not building_patches:
        print(f'  [surface-lines] no building patches found (available: {list(patches.keys())})')
        return []

    # Guard against very large meshes (would be too slow to parse)
    faces_file  = case_dir / 'constant' / 'polyMesh' / 'faces'
    points_file = case_dir / 'constant' / 'polyMesh' / 'points'
    SIZE_LIMIT = 60 * 1024 * 1024  # 60 MB
    for f in (faces_file, points_file):
        if f.exists() and f.stat().st_size > SIZE_LIMIT:
            print(f'  [surface-lines] mesh file {f.name} exceeds size limit, skipping')
            return []

    faces = _parse_of_faces(faces_file)
    pts   = _parse_of_points_np(points_file)
    if faces is None or pts is None or len(faces) == 0:
        print('  [surface-lines] could not read mesh geometry')
        return []

    print(f'  [surface-lines] {len(faces)} faces, {len(pts)} points, patches: {list(building_patches.keys())}')

    # Collect face geometry
    all_centers, all_normals, all_vectors = [], [], []
    for pname, data in building_patches.items():
        info = data['info']
        wss  = data['wss']
        nf, sf = info['nFaces'], info['startFace']
        for i in range(nf):
            fi = sf + i
            if fi >= len(faces):
                continue
            fv = faces[fi]
            if not fv or max(fv) >= len(pts):
                continue
            verts = pts[fv]
            center = verts.mean(axis=0)
            e1 = verts[1] - verts[0] if len(verts) > 1 else np.array([0., 0., 1.])
            e2 = verts[-1] - verts[0] if len(verts) > 2 else np.array([0., 1., 0.])
            normal = np.cross(e1, e2)
            n_mag = np.linalg.norm(normal)
            if n_mag > 1e-15:
                normal /= n_mag
            all_centers.append(center)
            all_normals.append(normal)
            all_vectors.append(wss[i])

    if len(all_centers) < 10:
        print(f'  [surface-lines] too few surface faces: {len(all_centers)}')
        return []

    centers = np.array(all_centers, dtype=np.float64)
    normals = np.array(all_normals, dtype=np.float64)
    vectors = np.array(all_vectors, dtype=np.float64)

    print(f'  [surface-lines] {len(centers)} surface face centres, integrating…')
    lines = _integrate_surface_streamlines(centers, normals, vectors, n_seeds, n_steps)
    print(f'  [surface-lines] {len(lines)} streamlines generated')
    return lines

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
