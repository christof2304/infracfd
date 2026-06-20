"""Ad-hoc re-validation harness for the v0.2 boundary-layer change.
Mirrors the /api/cfd/solve worker. Runs a named benchmark case and prints
Cd/Cl/Cm so we can compare current-BL vs y+ -BL against published references.

Usage:  python tools/_revalidate.py rub      (or: dfg)
Keeps everything at the validated baseline (far_field=15) so the only thing
that changes between runs is whatever boundary_layer_params() currently does.
"""
import sys, json, math, tempfile
from tools.cfd_mesh import generate_cfd_mesh
from tools.cfd_openfoam import create_openfoam_case, run_openfoam

def rub_polygon():
    return [[-0.142, 0.031], [-0.183, 0.005], [-0.103, -0.035],
            [0.103, -0.035], [0.183, 0.005], [0.142, 0.031]]

def dfg_cylinder(n=64, D=0.1):
    return [[0.5*D*math.cos(2*math.pi*i/n), 0.5*D*math.sin(2*math.pi*i/n)]
            for i in range(n)]

CASES = {
    # RUB bridge deck — SOFiSTiK/Dolfyn parity. Reference (Exp @a=4): 0.095/0.380/0.109
    "rub": dict(polygon=rub_polygon(), wind_speed=5.0, wind_angle=4.0,
                nu=1.373e-5, turbulence_intensity=0.03, turbulence_model="kOmegaSST",
                turbulence_length_scale=0.02, mesh_size=0.005, far_field=15,
                ref="cd/cl/cm @a=4 = 0.095 / 0.380 / 0.109 (Exp)"),
    # DFG 2D-1 laminar cylinder, Re=20: D=0.1, Umean=0.2, nu=1e-3. Ref: 5.5795/0.0106 (cd/cl)
    # NOTE: laminar -> use a tiny turbulence intensity; the pipeline still runs RANS,
    # this is only a rough reproduction of the README number.
    "dfg": dict(polygon=dfg_cylinder(), wind_speed=0.2, wind_angle=0.0,
                nu=1e-3, turbulence_intensity=0.01, turbulence_model="kEpsilon",
                turbulence_length_scale=None, mesh_size=0.01, far_field=15,
                ref="cd/cl/dp = 5.5795 / 0.0106 / 0.1172 (Schaefer&Turek)"),
}

def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "rub"
    c = CASES[name]
    case_dir = tempfile.mkdtemp(prefix=f"reval_{name}_")
    print(f"[{name}] dir={case_dir}  ref: {c['ref']}")
    mesh = generate_cfd_mesh(c["polygon"], mesh_size=c["mesh_size"],
                             far_field_factor=c["far_field"], wind_speed=c["wind_speed"])
    s = mesh["stats"]
    print(f"[{name}] BL: layers={s['bl_layers']} first={s['bl_first_layer_mm']}mm "
          f"nodes={s['n_nodes']} quads={s['n_quads']}")
    case = create_openfoam_case(mesh, wind_speed=c["wind_speed"], wind_angle=c["wind_angle"],
                                nu=c["nu"], turbulence_intensity=c["turbulence_intensity"],
                                turbulence_model=c["turbulence_model"],
                                turbulence_length_scale=c["turbulence_length_scale"],
                                output_dir=case_dir)
    res = run_openfoam(case, c["polygon"], mesh_size=c["mesh_size"], far_field_factor=c["far_field"],
                       bl_layers=4, bl_ratio=1.4, wind_speed=c["wind_speed"],
                       turbulence_model=c["turbulence_model"])
    fc = res.get("force_coefficients")
    print(f"[{name}] success={res['success']}")
    print(f"[{name}] RESULT Cd/Cl/Cm = "
          + (f"{fc['Cd']:.4f} / {fc['Cl']:.4f} / {fc['Cm']:.4f}" if fc else "None"))
    if not res["success"]:
        print(res["log"][-1500:])

if __name__ == "__main__":
    main()
