"""Ad-hoc tuning harness for the two transient demo cases (cylinder, harbour bridge).

Runs ONE case with explicit param overrides, reports wall-clock, frames written,
and — crucially — the Cl(t) oscillation that signals vortex shedding, plus an
estimated Strouhal number from Cl peak spacing. NOT a validation; a tuning probe.

Usage:
  python tools/_tune_transient.py <case> [k=v ...]
    case      : cyl | harbour
    overrides : U, ms, ff, endTime, dt, model, angle  (e.g. U=15 ff=15 endTime=2)
"""
import sys, os, json, time, glob, tempfile, math, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.cfd_mesh import generate_cfd_mesh
from tools.cfd_openfoam import create_openfoam_case, run_openfoam, _parse_force_history


def cylinder_poly(n=64, r=0.5):
    return [[r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)]
            for i in range(n)]


HARBOUR = [
    [0.66, 0], [0.66, -1], [0.83, -1], [1, 0],
    [11, 0.2], [11.17, -0.8], [11.34, -0.8], [11.34, 0.48],
    [6.7, 0.75], [3.6, 3.75],
    [-3.6, 3.75], [-6.7, 0.75],
    [-11.34, 0.48], [-11.34, -0.8], [-11.17, -0.8], [-11, 0.2],
    [-1, 0], [-0.83, -1], [-0.66, -1], [-0.66, 0],
]

CASES = {
    "cyl":     dict(poly=cylinder_poly(), U=15, ms=0.03, ff=25, char=1.0),
    "harbour": dict(poly=HARBOUR,         U=34, ms=0.30, ff=12, char=22.68),
    "square":  dict(poly=[[0,0],[1,0],[1,1],[0,1]], U=20, ms=0.05, ff=20, char=1.0),
}


def n_time_dirs(case_dir):
    n = 0
    for d in glob.glob(os.path.join(case_dir, "*")):
        if os.path.isdir(d):
            try:
                if float(os.path.basename(d)) > 0:
                    n += 1
            except ValueError:
                pass
    return n


def shedding_stats(fh, char, U):
    """Amplitude/std of Cl over the developed second half + Strouhal estimate."""
    if not fh or not fh.get("Cl"):
        return {}
    t, cl = fh["time"], fh["Cl"]
    half = len(cl) // 2
    t2, cl2 = t[half:], cl[half:]
    if len(cl2) < 4:
        return {"npts": len(cl2)}
    mean = sum(cl2) / len(cl2)
    amp = (max(cl2) - min(cl2)) / 2.0
    std = (sum((c - mean) ** 2 for c in cl2) / len(cl2)) ** 0.5
    # Strouhal from mean-crossing spacing (full period = 2 crossings of same sign slope)
    crossings = [t2[i] for i in range(1, len(cl2))
                 if (cl2[i - 1] - mean) <= 0 < (cl2[i] - mean)]
    St = None
    if len(crossings) >= 2:
        periods = [crossings[i + 1] - crossings[i] for i in range(len(crossings) - 1)]
        Tper = sum(periods) / len(periods)
        if Tper > 0:
            St = (1.0 / Tper) * char / U
    return {"Cl_mean": round(mean, 4), "Cl_amp": round(amp, 4),
            "Cl_std": round(std, 4), "St": round(St, 3) if St else None,
            "npts": len(cl2), "cycles": len(crossings)}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in CASES:
        print("usage: _tune_transient.py <cyl|harbour> [U=.. ms=.. ff=.. endTime=.. dt=.. model=.. angle=..]")
        sys.exit(1)
    name = sys.argv[1]
    base = CASES[name]
    ov = {}
    for arg in sys.argv[2:]:
        k, v = arg.split("=")
        ov[k] = v

    U      = float(ov.get("U", base["U"]))
    ms     = float(ov.get("ms", base["ms"]))
    ff     = float(ov.get("ff", base["ff"]))
    endT   = float(ov.get("endTime", 2.0))
    dt     = float(ov.get("dt", 0.01))
    model  = ov.get("model", "kOmegaSST")
    angle  = float(ov.get("angle", 0))
    nu     = float(ov.get("nu", 1.5e-5))
    struct = ov.get("struct", "0") in ("1", "true", "True")
    char   = base["char"]
    Re     = U * char / nu
    print(f"== {name}  U={U} ms={ms} ff={ff} endTime={endT} dt={dt} model={model} "
          f"angle={angle} struct={struct}  Re={Re:.2e} ==", flush=True)

    t0 = time.time()
    cdir = tempfile.mkdtemp(prefix=f"tune_{name}_")
    try:
        mesh = generate_cfd_mesh(base["poly"], wind_angle=angle, mesh_size=ms,
                                 far_field_factor=ff, wind_speed=U, structured=struct)
        stats = mesh.get("stats", {})
        print(f"   mesh: {stats.get('n_nodes','?')} nodes, "
              f"{stats.get('n_quads',0)} quads / {stats.get('n_triangles',0)} tris", flush=True)
        case = create_openfoam_case(
            mesh, wind_speed=U, wind_angle=angle, nu=nu,
            turbulence_intensity=0.05, turbulence_model=model,
            output_dir=cdir, transient=True, end_time=endT, dt=dt)
        res = run_openfoam(case, base["poly"], mesh_size=ms, far_field_factor=ff,
                           n_procs=4, wind_speed=U, turbulence_model=model,
                           structured=struct, timeout=900)
        secs = round(time.time() - t0, 1)
        frames = n_time_dirs(cdir)
        fh = _parse_force_history(cdir)
        sh = shedding_stats(fh, char, U)
        print(f"   -> success={res.get('success')} frames={frames} secs={secs} "
              f"dir={cdir}", flush=True)
        print(f"   -> final coeffs: {res.get('force_coefficients')}", flush=True)
        print(f"   -> shedding: {sh}", flush=True)
    except Exception:
        print("   EXC:\n" + traceback.format_exc()[-1500:], flush=True)


if __name__ == "__main__":
    main()
