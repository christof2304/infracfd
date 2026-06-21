"""Ad-hoc smoke test: do all 19 built-in 2D cases START and run in transient mode?

A smoke test, not a validation: it only checks that each case meshes, converts,
launches pimpleFoam and writes a few time steps without crashing — NOT that the
Cd/Cl values are physically right. Mirrors the /api/cfd/solve worker with
transient=True at a deliberately short end_time.

Reads cases from /tmp/cases2d.json (dumped from cfd/cfd-testcases.js via node).
Writes /tmp/smoke_results.json and prints one line per case as it finishes.

Usage:  python tools/_smoke_transient.py
"""
import sys, os, json, time, glob, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.cfd_mesh import generate_cfd_mesh
from tools.cfd_openfoam import create_openfoam_case, run_openfoam

END_TIME = 0.05      # sim seconds — enough to launch pimpleFoam and write frames
DT       = 0.005     # maxDeltaT (adaptive stepping seeds tiny and ramps to this)
TIMEOUT  = 240       # per-case wall-clock cap [s]; TIMEOUT counts as a smoke failure


def n_time_dirs(case_dir):
    """Count written solution time directories (named by sim time, >0)."""
    n = 0
    for d in glob.glob(os.path.join(case_dir, "*")):
        if not os.path.isdir(d):
            continue
        base = os.path.basename(d)
        try:
            if float(base) > 0:
                n += 1
        except ValueError:
            pass
    return n


def main():
    cases = json.load(open("/tmp/cases2d.json"))
    results = []
    print(f"Smoke test: {len(cases)} 2D cases, transient pimpleFoam, "
          f"end_time={END_TIME}s dt={DT} timeout={TIMEOUT}s\n", flush=True)
    for i, c in enumerate(cases, 1):
        name = c["name"]
        poly = c["polygon"]
        U    = c["windSpeed"]
        ms   = c["meshSize"]
        ff   = c["farField"]
        ang  = c["windAngle"]
        nu   = c["nu"]
        tm   = c["turbulenceModel"]
        tls  = c["turbulenceLengthScale"]
        ti   = c["turbulenceIntensity"]
        t0 = time.time()
        rec = {"name": name, "model": tm}
        try:
            cdir = tempfile.mkdtemp(prefix="smoke_")
            mesh = generate_cfd_mesh(poly, wind_angle=ang, mesh_size=ms,
                                     far_field_factor=ff, wind_speed=U)
            case = create_openfoam_case(
                mesh, wind_speed=U, wind_angle=ang, nu=nu,
                turbulence_intensity=ti, turbulence_model=tm,
                turbulence_length_scale=tls, output_dir=cdir,
                transient=True, end_time=END_TIME, dt=DT)
            res = run_openfoam(case, poly, mesh_size=ms, far_field_factor=ff,
                               n_procs=1, wind_speed=U, turbulence_model=tm,
                               timeout=TIMEOUT)
            frames = n_time_dirs(cdir)
            fc = res.get("force_coefficients")
            log = str(res.get("log", ""))
            rec.update(success=bool(res.get("success")), frames=frames,
                       has_fc=bool(fc),
                       err=None if res.get("success") else log[-500:])
        except Exception:
            rec.update(success=False, frames=0, has_fc=False,
                       err=traceback.format_exc()[-700:])
        rec["secs"] = round(time.time() - t0, 1)
        results.append(rec)
        json.dump(results, open("/tmp/smoke_results.json", "w"), indent=2)
        flag = "OK " if rec["success"] else "FAIL"
        print(f"[{i:2d}/{len(cases)}] {flag} {name:32.32s} "
              f"frames={rec['frames']:>3} fc={int(rec['has_fc'])} "
              f"{rec['secs']:>6.1f}s {tm}", flush=True)

    ok = sum(1 for r in results if r["success"])
    print(f"\n=== {ok}/{len(results)} cases ran in transient mode ===", flush=True)
    for r in results:
        if not r["success"]:
            print(f"\n--- FAIL: {r['name']} ---\n{r['err']}", flush=True)


if __name__ == "__main__":
    main()
