"""
infraFEM-CFD — standalone FastAPI server for browser-based CFD wind analysis.

Requirements: Python 3.10+, OpenFOAM 2406/2412 via WSL (Ubuntu), Gmsh

Usage:
    pip install fastapi uvicorn scipy numpy
    uvicorn server.app:app --reload --port 8000

Then open: http://localhost:8000/cfd/
"""

import os
import sys
import json
import queue
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, RedirectResponse

PROJECT_ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(title="infraFEM-CFD", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Static files
CFD_DIR   = PROJECT_ROOT / "cfd"
THREE_DIR = PROJECT_ROOT / "three"
app.mount("/cfd",   StaticFiles(directory=str(CFD_DIR),   html=True), name="cfd")
app.mount("/three", StaticFiles(directory=str(THREE_DIR)),             name="three")

UPLOADS_DIR = PROJECT_ROOT / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")


@app.get("/")
def root():
    return RedirectResponse(url="/cfd/")


# ── Global log queue (shared by 2D + 3D solve) ───────────────────────────────

_cfd_log_queue = queue.Queue()
_cfd_status = {"running": False, "result": None}


# ── 2D CFD ───────────────────────────────────────────────────────────────────

@app.post("/api/cfd/mesh")
def cfd_mesh(body: dict):
    """Generate 2D CFD mesh around a cross-section polygon (Gmsh)."""
    import subprocess

    polygon = body.get("polygon", [])
    if len(polygon) < 3:
        raise HTTPException(status_code=400, detail="Polygon needs at least 3 points")

    mesh_size  = body.get("meshSize", 0.2)
    far_field  = body.get("farFieldFactor", 15)
    wind_angle = body.get("windAngle", 0)

    input_data = json.dumps({"polygon": polygon, "meshSize": mesh_size,
                              "farFieldFactor": far_field, "windAngle": wind_angle})
    script = f"""
import json, sys
sys.path.insert(0, r'{PROJECT_ROOT}')
from tools.cfd_mesh import generate_cfd_mesh
data = json.loads('''{input_data}''')
result = generate_cfd_mesh(data['polygon'], wind_angle=data['windAngle'],
    mesh_size=data['meshSize'], far_field_factor=data['farFieldFactor'])
print(json.dumps(result))
"""
    try:
        r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise HTTPException(status_code=500, detail=r.stderr[:500])
        return json.loads(r.stdout)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Mesh generation timed out")


@app.get("/api/cfd/log-stream")
def cfd_log_stream():
    """Server-Sent Events stream of CFD solver output."""
    def event_generator():
        while True:
            try:
                msg = _cfd_log_queue.get(timeout=1)
                if msg == "__DONE__":
                    yield "data: __DONE__\n\n"
                    break
                yield f"data: {msg}\n\n"
            except queue.Empty:
                yield "data: \n\n"
                if not _cfd_status["running"]:
                    yield "data: __DONE__\n\n"
                    break
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/cfd/solve")
def cfd_solve(body: dict):
    """Run 2D OpenFOAM steady/transient CFD for a cross-section polygon."""
    import subprocess as sp

    polygon    = body.get("polygon", [])
    if len(polygon) < 3:
        raise HTTPException(status_code=400, detail="Need at least 3 polygon points")

    mesh_size  = body.get("meshSize", 0.2)
    far_field  = body.get("farFieldFactor", 15)
    wind_speed = body.get("windSpeed", 20.0)
    wind_angle = body.get("windAngle", 0)
    transient  = body.get("transient", False)
    end_time   = body.get("endTime", 2.0)
    dt         = body.get("dt", 0.002)
    bl_layers  = int(body.get("blLayers", 4))
    bl_ratio   = float(body.get("blRatio", 1.4))

    import tempfile
    case_dir = tempfile.mkdtemp(prefix="cfd_")

    while not _cfd_log_queue.empty():
        try: _cfd_log_queue.get_nowait()
        except: break
    _cfd_status["running"] = True
    _cfd_status["result"]  = None

    script = f"""
import sys, json
sys.path.insert(0, r'{PROJECT_ROOT}')
from tools.cfd_mesh import generate_cfd_mesh
from tools.cfd_openfoam import create_openfoam_case, run_openfoam, parse_cfd_results

polygon = {json.dumps(polygon)}
mesh = generate_cfd_mesh(polygon, mesh_size={mesh_size}, far_field_factor={far_field})
case = create_openfoam_case(mesh, wind_speed={wind_speed}, wind_angle={wind_angle},
    output_dir=r'{case_dir}', transient={transient}, end_time={end_time}, dt={dt})
result = run_openfoam(case, polygon, mesh_size={mesh_size}, far_field_factor={far_field},
    bl_layers={bl_layers}, bl_ratio={bl_ratio})
result["stats"]    = mesh["stats"]
result["case_dir"] = r'{case_dir}'
field_data = parse_cfd_results(r'{case_dir}', section_polygon=polygon)
if field_data:
    result["field"] = field_data
print(json.dumps(result))
"""
    try:
        proc = sp.Popen([sys.executable, "-c", script], stdout=sp.PIPE, stderr=sp.STDOUT, text=True, bufsize=1)
        output_lines = []
        for line in proc.stdout:
            line = line.rstrip()
            output_lines.append(line)
            if any(kw in line for kw in ["Time =", "Cd:", "Cl:", "===", "Mesh", "Re =", "FOAM", "End"]):
                _cfd_log_queue.put(line)
        proc.wait()
        _cfd_status["running"] = False
        _cfd_log_queue.put("__DONE__")

        if proc.returncode != 0:
            raise HTTPException(status_code=500, detail=f"CFD failed: {''.join(output_lines[-10:])}")
        for line in reversed(output_lines):
            if line.strip().startswith("{"):
                result = json.loads(line.strip())
                _cfd_status["result"] = result
                return result
        raise HTTPException(status_code=500, detail="No result JSON")
    except HTTPException:
        _cfd_status["running"] = False
        raise
    except Exception as e:
        _cfd_status["running"] = False
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/cfd/timestep")
def cfd_timestep(body: dict):
    """Return pressure/velocity field for a specific time step (transient animation)."""
    import math
    from tools.cfd_openfoam import _parse_of_scalar_field, _parse_of_vector_field, _parse_of_faces, _parse_of_int_list

    case_dir = body.get("caseDir", "")
    if not case_dir or not os.path.isdir(case_dir):
        raise HTTPException(status_code=400, detail="Invalid case directory")

    case_path  = Path(case_dir)
    time_dirs  = []
    for d in case_path.iterdir():
        if d.is_dir():
            try: time_dirs.append((float(d.name), d))
            except ValueError: pass
    if not time_dirs:
        raise HTTPException(status_code=404, detail="No time steps found")

    time_dirs.sort()
    time      = body.get("time", 0)
    closest   = min(time_dirs, key=lambda t: abs(t[0] - time))
    time_dir  = closest[1]
    field_name = body.get("field", "pressure")

    pressure      = _parse_of_scalar_field(time_dir / "p")
    velocity      = _parse_of_vector_field(time_dir / "U")
    vorticity_vec = _parse_of_vector_field(time_dir / "vorticity")

    if field_name == "speed" and velocity:
        cell_values = [math.sqrt(v[0]**2 + v[1]**2 + v[2]**2) for v in velocity]
    elif field_name == "vorticity" and vorticity_vec:
        cell_values = [v[2] for v in vorticity_vec]
    elif field_name == "turb_k":
        cell_values = _parse_of_scalar_field(time_dir / "k") or []
    else:
        cell_values = pressure or []

    points = _parse_of_vector_field(case_path / "constant" / "polyMesh" / "points")
    faces  = _parse_of_faces(case_path / "constant" / "polyMesh" / "faces")
    owner  = _parse_of_int_list(case_path / "constant" / "polyMesh" / "owner")

    nodes_2d = []
    if points:
        for i, pt in enumerate(points):
            if abs(pt[2]) < 0.01:
                nodes_2d.append({"id": i, "x": round(pt[0], 4), "y": round(pt[1], 4)})

    triangles = []
    if faces and owner and points and cell_values:
        for i, face in enumerate(faces):
            if len(face) < 3: continue
            face_pts = [points[n] for n in face if n < len(points)]
            if not face_pts: continue
            if abs(sum(p[2] for p in face_pts) / len(face_pts)) > 0.01: continue
            cell_id = owner[i] if i < len(owner) else -1
            p_val   = cell_values[cell_id] if 0 <= cell_id < len(cell_values) else 0
            for j in range(1, len(face) - 1):
                triangles.append({"nodes": [face[0], face[j], face[j+1]], "p": p_val})

    v_range = [min(cell_values), max(cell_values)] if cell_values else [0, 0]
    return {"time": closest[0], "nodes": nodes_2d, "triangles": triangles[:80000], "p_range": v_range}


# ── 3D CFD ───────────────────────────────────────────────────────────────────

@app.post("/api/cfd/solve3d")
def cfd_solve3d(body: dict):
    """Run 3D OpenFOAM building CFD (footprint extrusion or multi-building)."""
    import subprocess as sp

    footprint = body.get("footprint", [])
    buildings = body.get("buildings", None)
    height    = body.get("height", 40)
    if not buildings and len(footprint) < 3:
        raise HTTPException(status_code=400, detail="Need footprint or buildings array")

    wind_speed    = body.get("windSpeed", 10)
    wind_angle    = body.get("windAngle", 0)
    z0            = body.get("z0", 0.1)
    mesh_size     = body.get("meshSize", None)
    n_iterations  = body.get("nIterations", 500)
    n_procs       = body.get("nProcs", 4)
    domain_factor = body.get("domainFactor", 3)

    max_height = max(b["height"] for b in buildings) if buildings else height
    buildings_json = json.dumps(buildings) if buildings else "None"

    _cfd_status["running"] = True
    _cfd_status["result"]  = None

    script = f"""
import sys, json
sys.path.insert(0, r'{PROJECT_ROOT}')
from tools.cfd_openfoam import create_openfoam_case_3d, run_openfoam_3d

footprint = {json.dumps(footprint)}
buildings = {buildings_json}
case_dir  = create_openfoam_case_3d(
    footprint, height={max_height}, wind_speed={wind_speed},
    wind_angle={wind_angle}, z0={z0}, n_iterations={n_iterations},
    n_procs={n_procs}, buildings=buildings)

domain_factors = {{"upstream": {domain_factor}, "downstream": {domain_factor}*2.5,
                   "lateral": {domain_factor}, "top": {domain_factor}}}
result = run_openfoam_3d(case_dir, footprint, height={max_height},
    mesh_size={mesh_size if mesh_size else 'None'}, n_procs={n_procs},
    domain_factors=domain_factors, buildings=buildings)
result["case_dir"]       = case_dir
result["mode"]           = "3d"
result["building_height"] = {max_height}
print(json.dumps(result))
"""
    try:
        proc = sp.Popen([sys.executable, "-c", script], stdout=sp.PIPE, stderr=sp.STDOUT, text=True)
        output_lines = []
        for line in iter(proc.stdout.readline, ""):
            output_lines.append(line)
            if any(kw in line for kw in ["Time =", "Cd:", "Cl:", "===", "Mesh", "Re =", "3D CFD", "FOAM"]):
                _cfd_log_queue.put(line.rstrip())
        proc.wait()
        _cfd_status["running"] = False
        _cfd_log_queue.put("__DONE__")

        if proc.returncode != 0:
            raise HTTPException(status_code=500, detail=f"3D CFD failed: {''.join(output_lines[-10:])}")
        for line in reversed(output_lines):
            if line.strip().startswith("{"):
                result = json.loads(line.strip())
                _cfd_status["result"] = result
                return result
        raise HTTPException(status_code=500, detail="No result JSON")
    except HTTPException:
        _cfd_status["running"] = False
        raise
    except Exception as e:
        _cfd_status["running"] = False
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/cfd/slice3d")
def cfd_slice3d(body: dict):
    """Extract a colored 2D slice from 3D CFD results."""
    case_dir = body.get("caseDir", "")
    if not case_dir or not os.path.isdir(case_dir):
        raise HTTPException(status_code=400, detail="Invalid case directory")

    from tools.cfd_openfoam import extract_slice
    result = extract_slice(case_dir, plane=body.get("plane", "z"),
                           value=body.get("value", 0), field=body.get("field", "pressure"))
    if not result:
        raise HTTPException(status_code=404, detail="No data for this slice")
    return result


@app.post("/api/cfd/streamlines3d")
def cfd_streamlines3d(body: dict):
    """Extract 3D streamlines from a completed OpenFOAM case."""
    case_dir = body.get("caseDir", "")
    if not case_dir or not os.path.isdir(case_dir):
        raise HTTPException(status_code=400, detail="Invalid case directory")

    from tools.cfd_openfoam import extract_streamlines
    lines = extract_streamlines(case_dir, n_seeds=body.get("nSeeds", 30),
                                 seed_z_min=body.get("seedZmin", 0.0),
                                 seed_z_max=body.get("seedZmax", 1.0))
    return {"streamlines": lines, "count": len(lines)}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.app:app", host="0.0.0.0", port=8000, reload=True)
