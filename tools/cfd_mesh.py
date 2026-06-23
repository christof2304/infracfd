"""
CFD Mesh Generator for 2D cross-section aerodynamics.

Generates a 2D mesh around a cross-section polygon using Gmsh:
- Structured quad boundary-layer (inflation) rows near the wall
- Unstructured Frontal-Delaunay fill in the free-stream
- Circular far-field boundary

Usage:
    from tools.cfd_mesh import generate_cfd_mesh
    result = generate_cfd_mesh(polygon, wind_speed=90, mesh_size=0.02, far_field_factor=20)
"""

import math
import os
import tempfile


# ── Boundary-layer sizing — single source of truth ─────────────────────────────

def boundary_layer_params(char_dim, mesh_size, wind_speed=None, nu=1.5e-5,
                          bl_layers=4, bl_ratio=1.4):
    """Compute boundary-layer (inflation) sizing for the cross-section wall.

    This is the SINGLE source of truth shared by both the UI preview mesh
    (``generate_cfd_mesh``) and the solver mesh (``generate_gmsh_msh`` in
    ``cfd_openfoam.py``), so that *what you preview is what gets solved*. Both
    paths must route their first-layer height / layer count / growth ratio
    through here — never inline the formula again.

    Args:
        char_dim:   characteristic section size max(width, height) [m]
        mesh_size:  target bulk element size [m] (UI density slider)
        wind_speed: free-stream speed [m/s]; accepted for the planned y+=50
                    variant but NOT yet used (see note below)
        nu:         kinematic viscosity [m^2/s]; reserved like wind_speed
        bl_layers:  number of inflation layers (UI control); None -> default 4
        bl_ratio:   geometric growth ratio between layers

    Returns:
        (first_layer, bl_layers, bl_ratio, bl_outer)
            first_layer  first wall-normal cell height [m]
            bl_layers    resolved layer count
            bl_ratio     growth ratio (passed through unchanged)
            bl_outer     outermost BL cell height [m]

    Sizing reproduces the historical solver mesh exactly: a geometric first
    layer tuned for k-epsilon wall functions (y+ ~ 30-100), independent of
    wind speed. The physics-based y+=50 first layer
    (``max(5e-6, 50*nu/u_tau)`` with ``u_tau = U*sqrt(Cf/2)``,
    ``Cf = 0.074*Re**-0.2``) is the planned v0.2-step-2 upgrade and must be
    introduced here behind a re-validation of the DFG cylinder and RUB
    bridge-deck benchmarks.
    """
    if bl_layers is None:
        bl_layers = 4
    first_layer = max(2e-4, min(mesh_size * 0.04, char_dim * 0.004))
    bl_outer = first_layer * bl_ratio ** bl_layers
    return first_layer, bl_layers, bl_ratio, bl_outer


# ── Structured O-mesh helpers ──────────────────────────────────────────────────

def _cosine_resample(pts, n):
    """Resample pts to n+1 cosine-spaced points by arc length (clusters at both ends)."""
    cum = [0.0]
    for i in range(1, len(pts)):
        dx, dy = pts[i][0] - pts[i-1][0], pts[i][1] - pts[i-1][1]
        cum.append(cum[-1] + math.sqrt(dx*dx + dy*dy))
    total = cum[-1]
    if total < 1e-14:
        return [list(pts[0])] * (n + 1)
    result = []
    for j in range(n + 1):
        t = min(total * (1 - math.cos(math.pi * j / n)) / 2, total)
        lo, hi = 0, len(cum) - 2
        while lo < hi:
            mid = (lo + hi) // 2
            if cum[mid + 1] < t:
                lo = mid + 1
            else:
                hi = mid
        seg = cum[lo + 1] - cum[lo]
        alpha = (t - cum[lo]) / seg if seg > 1e-14 else 0.0
        result.append([
            pts[lo][0] + alpha * (pts[lo+1][0] - pts[lo][0]),
            pts[lo][1] + alpha * (pts[lo+1][1] - pts[lo][1]),
        ])
    return result


def _omesh(polygon, wind_speed, mesh_size, far_field_factor, nu):
    """Fully-structured O-grid quad mesh for smooth closed profiles (airfoils, cylinders).

    Uses Spline curves so each surface side is ONE curve entity, which is required
    for Gmsh TransfiniteSurface to work correctly. Returns n_triangles = 0.
    """
    import gmsh

    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    cx = (max(xs) + min(xs)) / 2
    cy = (max(ys) + min(ys)) / 2
    char_dim = max(max(xs) - min(xs), max(ys) - min(ys))
    far_r = char_dim * far_field_factor

    # First wall-normal cell (y+ = 50)
    if wind_speed and wind_speed > 0:
        Re = max(wind_speed * char_dim / nu, 1e4)
        Cf = 0.074 / Re ** 0.2
        u_tau = wind_speed * math.sqrt(max(Cf / 2.0, 1e-10))
        # Cap at 1% of the body: the y+ formula divides by u_tau, which for the
        # low-Re vortex-shedding demos (high nu / low U) blows the first layer up
        # to metres — far bigger than the body. The cap is inert at high Re (the
        # y+ layer is already microns there) and only rescues the low-Re regime.
        first_layer = max(5e-6, min(50.0 * nu / u_tau, char_dim * 0.01))
    else:
        first_layer = max(2e-4, char_dim * 0.003)

    # Radial layers: geometric growth from first_layer to far_r
    r_g = 1.15
    N_r = int(math.ceil(math.log(far_r * (r_g - 1) / first_layer + 1) / math.log(r_g)))
    N_r = max(40, min(N_r, 120))
    N_s = 60  # segments per half-surface

    # ── Split polygon into upper / lower arcs ─────────────────────────────────
    n = len(polygon)
    le_idx = min(range(n), key=lambda i: polygon[i][0])
    te_idx = max(range(n), key=lambda i: polygon[i][0])

    le_pt = [polygon[le_idx][0], polygon[le_idx][1]]
    te_pt = [polygon[te_idx][0], 0.0]   # close TE symmetrically

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

    upper_raw[0]  = le_pt[:]
    upper_raw[-1] = te_pt[:]
    lower_raw[0]  = te_pt[:]
    lower_raw[-1] = le_pt[:]

    upper_pts = _cosine_resample(upper_raw, N_s)   # LE→TE, N_s+1 pts
    lower_pts = _cosine_resample(lower_raw, N_s)   # TE→LE, N_s+1 pts

    # Radial projection to far-field circle
    def to_ff(pt):
        dx, dy = pt[0] - cx, pt[1] - cy
        d = math.sqrt(dx*dx + dy*dy)
        if d < 1e-10:
            return [cx + far_r, cy]
        return [cx + dx * far_r / d, cy + dy * far_r / d]

    upper_ff = [to_ff(p) for p in upper_pts]   # LE_ff→TE_ff
    lower_ff = [to_ff(p) for p in lower_pts]   # TE_ff→LE_ff

    # ── Gmsh geometry ─────────────────────────────────────────────────────────
    gmsh.initialize()
    gmsh.option.setNumber("General.Verbosity", 0)
    gmsh.model.add("omesh")

    def gpt(x, y):
        return gmsh.model.geo.addPoint(x, y, 0, 1.0)

    # Upper airfoil arc: N_s+1 points (ut[0]=LE, ut[N_s]=TE)
    ut = [gpt(*p) for p in upper_pts]

    # Lower airfoil arc: reuse TE=ut[N_s] and LE=ut[0]; N_s-1 interior points
    lt_int = [gpt(*p) for p in lower_pts[1:-1]]
    lt = [ut[N_s]] + lt_int + [ut[0]]          # lt[0]=TE, lt[N_s]=LE

    # Upper far-field arc: N_s+1 points (uft[0]=LE_ff, uft[N_s]=TE_ff)
    uft = [gpt(*p) for p in upper_ff]

    # Lower far-field arc: reuse TE_ff=uft[N_s] and LE_ff=uft[0]
    lft_int = [gpt(*p) for p in lower_ff[1:-1]]
    lft = [uft[N_s]] + lft_int + [uft[0]]      # lft[0]=TE_ff, lft[N_s]=LE_ff

    # Radial connectors (single straight lines, LE/TE to far-field)
    le_rad = gmsh.model.geo.addLine(ut[0],   uft[0])    # LE→LE_ff
    te_rad = gmsh.model.geo.addLine(ut[N_s], uft[N_s])  # TE→TE_ff

    # One spline per arc (Gmsh TransfiniteSurface requires one curve per side)
    u_spl  = gmsh.model.geo.addSpline(ut)    # upper airfoil  LE→TE
    l_spl  = gmsh.model.geo.addSpline(lt)    # lower airfoil  TE→LE
    uf_spl = gmsh.model.geo.addSpline(uft)   # upper far-field LE_ff→TE_ff
    lf_spl = gmsh.model.geo.addSpline(lft)   # lower far-field TE_ff→LE_ff

    # Upper surface: LE→TE (u_spl) + TE→TE_ff (te_rad) + TE_ff→LE_ff (-uf_spl) + LE_ff→LE (-le_rad)
    uloop = gmsh.model.geo.addCurveLoop([u_spl, te_rad, -uf_spl, -le_rad])
    usurf = gmsh.model.geo.addPlaneSurface([uloop])

    # Lower surface: TE→LE (l_spl) + LE→LE_ff (le_rad) + LE_ff→TE_ff (-lf_spl) + TE_ff→TE (-te_rad)
    lloop = gmsh.model.geo.addCurveLoop([l_spl, le_rad, -lf_spl, -te_rad])
    lsurf = gmsh.model.geo.addPlaneSurface([lloop])

    gmsh.model.addPhysicalGroup(1, [u_spl, l_spl],   tag=1, name="section")
    gmsh.model.addPhysicalGroup(1, [uf_spl, lf_spl], tag=2, name="farfield")
    gmsh.model.addPhysicalGroup(2, [usurf, lsurf],    tag=1, name="fluid")

    # ONE synchronize at the end, then set all mesh attributes
    gmsh.model.geo.synchronize()

    # Transfinite distributions — must be set AFTER final synchronize()
    gmsh.model.mesh.setTransfiniteCurve(u_spl,  N_s + 1)
    gmsh.model.mesh.setTransfiniteCurve(l_spl,  N_s + 1)
    gmsh.model.mesh.setTransfiniteCurve(uf_spl, N_s + 1)
    gmsh.model.mesh.setTransfiniteCurve(lf_spl, N_s + 1)
    gmsh.model.mesh.setTransfiniteCurve(le_rad, N_r + 1, "Progression", r_g)
    gmsh.model.mesh.setTransfiniteCurve(te_rad, N_r + 1, "Progression", r_g)
    gmsh.model.mesh.setTransfiniteSurface(usurf, "Left",
        [ut[0], ut[N_s], uft[N_s], uft[0]])
    gmsh.model.mesh.setTransfiniteSurface(lsurf, "Left",
        [lt[0], lt[N_s], lft[N_s], lft[0]])
    gmsh.model.mesh.setRecombine(2, usurf)
    gmsh.model.mesh.setRecombine(2, lsurf)

    gmsh.model.mesh.generate(2)

    # ── Extract mesh data ──────────────────────────────────────────────────────
    node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
    nodes, node_map = [], {}
    for i, tag in enumerate(node_tags):
        x, y = node_coords[i * 3], node_coords[i * 3 + 1]
        nodes.append({"id": int(tag), "x": round(x, 6), "y": round(y, 6)})
        node_map[int(tag)] = (x, y)

    triangles, quads = [], []
    eid = 1
    for etype, etags, enodes in zip(*gmsh.model.mesh.getElements(dim=2)):
        if etype == 2:
            for i in range(len(etags)):
                triangles.append({"id": eid, "nodes": [int(enodes[i*3+j]) for j in range(3)]})
                eid += 1
        elif etype == 3:
            for i in range(len(etags)):
                quads.append({"id": eid, "nodes": [int(enodes[i*4+j]) for j in range(4)]})
                eid += 1

    sec_nodes = set()
    for l in [u_spl, l_spl]:
        for nt in gmsh.model.mesh.getNodes(dim=1, tag=l)[0]:
            sec_nodes.add(int(nt))

    ff_nodes = set()
    for l in [uf_spl, lf_spl]:
        for nt in gmsh.model.mesh.getNodes(dim=1, tag=l)[0]:
            ff_nodes.add(int(nt))

    stats = {
        "n_nodes":           len(nodes),
        "n_triangles":       len(triangles),
        "n_quads":           len(quads),
        "n_elements":        len(triangles) + len(quads),
        "n_section_nodes":   len(sec_nodes),
        "n_farfield_nodes":  len(ff_nodes),
        "char_dim":          round(char_dim, 4),
        "far_field_r":       round(far_r, 3),
        "bl_layers":         N_r,
        "bl_first_layer_mm": round(first_layer * 1000, 4),
        "n_corners":         0,
    }

    gmsh.finalize()

    return {
        "nodes":             nodes,
        "triangles":         triangles,
        "quads":             quads,
        "boundary_section":  sorted(sec_nodes),
        "boundary_farfield": sorted(ff_nodes),
        "section_polygon":   polygon,
        "wind_angle":        0,
        "stats":             stats,
    }


# ── Main unstructured mesh (hybrid BL quads + Delaunay triangles) ──────────────

def _grounded_mesh(chain, wind_speed, mesh_size, far_field_factor,
                   bl_layers, bl_ratio, nu):
    """Rectangular domain with a ground wall for ground-mounted bodies.

    `chain` is an OPEN polyline running from the left ground contact (y=0) over
    the body/bodies — dipping back to y=0 between separate bodies — to the right
    ground contact (y=0). The mesher extends y=0 to the inlet/outlet, closes the
    box with outlet/top/inlet, and classifies edges:
      * chain edges with both ends on y=0  → ground (wall)
      * the inlet→chain[0] and chain[-1]→outlet stubs → ground (wall)
      * all other chain edges → section (body wall, where forces are measured)
    No flow passes under the bodies, i.e. they stand on the ground.
    """
    import gmsh
    eps = 1e-6

    xs = [p[0] for p in chain]
    ys = [p[1] for p in chain]
    xL, xR = min(xs), max(xs)
    H       = max(ys)
    width   = xR - xL
    char_dim = max(width, H)
    margin  = char_dim * far_field_factor
    x_in, x_out = xL - margin, xR + margin
    y_top   = margin
    ff_mesh_size = char_dim * 2.0

    # First BL layer height (y⁺ = 50, wall functions) — same model as the free path
    if wind_speed is not None and wind_speed > 0:
        Re    = wind_speed * char_dim / nu
        Cf    = 0.074 / max(Re, 1e4) ** 0.2
        u_tau = wind_speed * math.sqrt(max(Cf / 2.0, 1e-10))
        first_layer = max(5e-6, 50.0 * nu / u_tau)
    else:
        first_layer = max(2e-4, char_dim * 0.003)

    if bl_layers is None:
        max_total = char_dim * 0.08
        max_cell  = mesh_size * 0.3
        n_ly = 1
        while n_ly < 25:
            if first_layer * bl_ratio ** n_ly > max_cell:
                break
            if first_layer * (bl_ratio ** n_ly - 1.0) / (bl_ratio - 1.0) > max_total:
                break
            n_ly += 1
        bl_layers = max(4, n_ly)
    bl_outer = first_layer * bl_ratio ** bl_layers

    gmsh.initialize()
    gmsh.option.setNumber("General.Verbosity", 0)
    gmsh.model.add("cfd_grounded")
    geo = gmsh.model.geo

    def pt(x, y, h=mesh_size):
        return geo.addPoint(x, y, 0, h)

    p_in_bot  = pt(x_in,  0.0, ff_mesh_size)
    chain_ids = [pt(x, y) for x, y in chain]
    p_out_bot = pt(x_out, 0.0, ff_mesh_size)
    p_out_top = pt(x_out, y_top, ff_mesh_size)
    p_in_top  = pt(x_in,  y_top, ff_mesh_size)

    # Ordered boundary as (a, b, type)
    boundary = [(p_in_bot, chain_ids[0], "ground")]
    for i in range(len(chain) - 1):
        on_ground = abs(chain[i][1]) < eps and abs(chain[i + 1][1]) < eps
        boundary.append((chain_ids[i], chain_ids[i + 1],
                         "ground" if on_ground else "section"))
    boundary += [
        (chain_ids[-1], p_out_bot, "ground"),
        (p_out_bot, p_out_top, "outlet"),
        (p_out_top, p_in_top, "top"),
        (p_in_top, p_in_bot, "inlet"),
    ]

    loop_lines = []
    groups = {"ground": [], "section": [], "outlet": [], "top": [], "inlet": []}
    for a, b, typ in boundary:
        lid = geo.addLine(a, b)
        loop_lines.append(lid)
        groups[typ].append(lid)

    surface = geo.addPlaneSurface([geo.addCurveLoop(loop_lines)])
    geo.synchronize()

    # Background size field — refine near body + ground
    refine_curves = groups["section"] + groups["ground"]
    dist_field = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(dist_field, "CurvesList", groups["section"])
    near_size = max(bl_outer * 2.5, mesh_size * 0.4)
    thresh = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(thresh, "InField", dist_field)
    gmsh.model.mesh.field.setNumber(thresh, "SizeMin", near_size)
    gmsh.model.mesh.field.setNumber(thresh, "SizeMax", ff_mesh_size)
    gmsh.model.mesh.field.setNumber(thresh, "DistMin", char_dim * 0.3)
    gmsh.model.mesh.field.setNumber(thresh, "DistMax", margin * 0.4)
    gmsh.model.mesh.field.setNumber(thresh, "Sigmoid", 1)
    gmsh.model.mesh.field.setAsBackgroundMesh(thresh)

    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    gmsh.option.setNumber("Mesh.Smoothing", 5)

    # Boundary layer on the body walls (and the ground for a clean near-wall layer)
    corner_pts = []
    for i in range(1, len(chain) - 1):
        p0, p1, p2 = chain[i - 1], chain[i], chain[i + 1]
        v1 = (p0[0] - p1[0], p0[1] - p1[1])
        v2 = (p2[0] - p1[0], p2[1] - p1[1])
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        if l1 < 1e-10 or l2 < 1e-10 or p1[1] < eps:
            continue
        cos_a = max(-1.0, min(1.0, (v1[0]*v2[0] + v1[1]*v2[1]) / (l1 * l2)))
        if math.degrees(math.acos(cos_a)) < 150.0:
            corner_pts.append(chain_ids[i])

    bl_field = gmsh.model.mesh.field.add("BoundaryLayer")
    gmsh.model.mesh.field.setNumbers(bl_field, "CurvesList", refine_curves)
    if corner_pts:
        gmsh.model.mesh.field.setNumbers(bl_field, "PointsList", corner_pts)
    gmsh.model.mesh.field.setNumber(bl_field, "Size", first_layer)
    gmsh.model.mesh.field.setNumber(bl_field, "Ratio", bl_ratio)
    gmsh.model.mesh.field.setNumber(bl_field, "NbLayers", bl_layers)
    gmsh.model.mesh.field.setNumber(bl_field, "Quads", 1)
    gmsh.model.mesh.field.setAsBoundaryLayer(bl_field)
    gmsh.option.setNumber("Mesh.Algorithm", 6)

    gmsh.model.addPhysicalGroup(1, groups["section"], tag=1, name="section")
    gmsh.model.addPhysicalGroup(1, groups["inlet"],   tag=2, name="inlet")
    gmsh.model.addPhysicalGroup(1, groups["outlet"],  tag=3, name="outlet")
    gmsh.model.addPhysicalGroup(1, groups["top"],     tag=4, name="top")
    gmsh.model.addPhysicalGroup(1, groups["ground"],  tag=5, name="ground")
    gmsh.model.addPhysicalGroup(2, [surface],         tag=1, name="fluid")

    gmsh.model.mesh.generate(2)

    node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
    nodes, node_map = [], {}
    for i, tag in enumerate(node_tags):
        x, y = node_coords[i*3], node_coords[i*3+1]
        nodes.append({"id": int(tag), "x": round(x, 6), "y": round(y, 6)})
        node_map[int(tag)] = (x, y)

    triangles, quads = [], []
    elem_types, elem_tags, elem_node_tags = gmsh.model.mesh.getElements(dim=2)
    eid = 1
    for etype, etags, enodes in zip(elem_types, elem_tags, elem_node_tags):
        if etype == 2:
            for i in range(len(etags)):
                triangles.append({"id": eid, "nodes": [int(enodes[i*3]), int(enodes[i*3+1]), int(enodes[i*3+2])]})
                eid += 1
        elif etype == 3:
            for i in range(len(etags)):
                quads.append({"id": eid, "nodes": [int(enodes[i*4]), int(enodes[i*4+1]), int(enodes[i*4+2]), int(enodes[i*4+3])]})
                eid += 1

    def node_ids_of(line_ids):
        s = set()
        for lid in line_ids:
            for nt in gmsh.model.mesh.getNodes(dim=1, tag=lid)[0]:
                s.add(int(nt))
        return sorted(s)

    section_nodes = node_ids_of(groups["section"])
    ground_nodes  = node_ids_of(groups["ground"])

    stats = {
        "n_nodes": len(nodes), "n_triangles": len(triangles), "n_quads": len(quads),
        "n_elements": len(triangles) + len(quads),
        "n_section_nodes": len(section_nodes), "n_farfield_nodes": 0,
        "char_dim": round(char_dim, 4), "far_field_r": round(margin, 3),
        "bl_layers": bl_layers, "bl_first_layer_mm": round(first_layer * 1000, 4),
        "n_corners": len(corner_pts), "grounded": True,
    }
    gmsh.finalize()

    return {
        "nodes": nodes, "triangles": triangles, "quads": quads,
        "boundary_section": section_nodes,
        "boundary_ground":  ground_nodes,
        "boundary_farfield": [],
        "section_polygon": chain,
        "grounded": True,
        "wind_angle": 0,
        "stats": stats,
    }


def generate_cfd_mesh(polygon, wind_angle=0, mesh_size=0.5, far_field_factor=15,
                      bl_layers=None, bl_ratio=1.4, wind_speed=None, nu=1.5e-5,
                      structured=False, grounded=False):
    """Generate a 2D CFD mesh around a cross-section polygon.

    Args:
        polygon:          [[x,y],...] — closed CCW cross-section boundary
        wind_angle:       flow direction in degrees (0 = from left, unused for mesh)
        mesh_size:        target element size in the bulk domain [m]
        far_field_factor: far-field radius as multiple of section width
        bl_layers:        number of quad BL rows (None → computed adaptively)
        bl_ratio:         BL cell height growth ratio
        wind_speed:       free-stream speed [m/s] used to size first BL row via y⁺=50
        nu:               kinematic viscosity [m²/s]
        structured:       use fully-structured O-grid (quads only, best for smooth profiles)

    Returns:
        dict: nodes, triangles, quads, boundary_section, boundary_farfield,
              section_polygon, wind_angle, stats
    """
    if grounded:
        return _grounded_mesh(polygon, wind_speed, mesh_size, far_field_factor,
                              bl_layers, bl_ratio, nu)

    if structured:
        return _omesh(polygon, wind_speed, mesh_size, far_field_factor, nu)

    import gmsh

    gmsh.initialize()
    gmsh.option.setNumber("General.Verbosity", 0)
    gmsh.model.add("cfd_section")

    # ── Section geometry ─────────────────────────────────────────────
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    cx       = sum(xs) / len(xs)
    cy       = sum(ys) / len(ys)
    width    = max(xs) - min(xs)
    height   = max(ys) - min(ys)
    char_dim = max(width, height)
    far_field_r  = char_dim * far_field_factor
    ff_mesh_size = char_dim * 2.0

    # ── Boundary-layer sizing (shared with the solver mesh) ───────────
    # Single source of truth so the preview matches what gets solved.
    first_layer, bl_layers, bl_ratio, bl_outer = boundary_layer_params(
        char_dim, mesh_size, wind_speed=wind_speed, nu=nu,
        bl_layers=bl_layers, bl_ratio=bl_ratio)

    # ── Gmsh geometry ─────────────────────────────────────────────────
    section_points = []
    for x, y in polygon:
        pid = gmsh.model.geo.addPoint(x, y, 0, mesh_size)
        section_points.append(pid)

    section_lines = []
    n_pts = len(section_points)
    for i in range(n_pts):
        lid = gmsh.model.geo.addLine(section_points[i],
                                      section_points[(i + 1) % n_pts])
        section_lines.append(lid)

    section_loop = gmsh.model.geo.addCurveLoop(section_lines)

    ff_n      = 32
    ff_points = []
    for i in range(ff_n):
        a   = 2.0 * math.pi * i / ff_n
        pid = gmsh.model.geo.addPoint(cx + far_field_r * math.cos(a),
                                       cy + far_field_r * math.sin(a),
                                       0, ff_mesh_size)
        ff_points.append(pid)

    center_pt = gmsh.model.geo.addPoint(cx, cy, 0, ff_mesh_size)
    ff_arcs   = []
    quarter   = ff_n // 4
    for i in range(4):
        arc = gmsh.model.geo.addCircleArc(ff_points[i * quarter],
                                           center_pt,
                                           ff_points[((i + 1) * quarter) % ff_n])
        ff_arcs.append(arc)

    ff_loop = gmsh.model.geo.addCurveLoop(ff_arcs)
    surface = gmsh.model.geo.addPlaneSurface([ff_loop, section_loop])

    gmsh.model.geo.synchronize()

    # ── Background size field ─────────────────────────────────────────
    dist_field = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(dist_field, "CurvesList", section_lines)

    # Near-body background size. Tie this to mesh_size so the preview actually
    # refines with the density slider (track the solver-mesh resolution) instead of
    # saturating. Floor at the outer BL cell so the first bulk triangle is not finer
    # than the boundary-layer it sits on (avoids inverted sizing at sharp corners).
    near_size = max(mesh_size * 0.5, first_layer)

    thresh = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(thresh, "InField",  dist_field)
    gmsh.model.mesh.field.setNumber(thresh, "SizeMin",  near_size)
    gmsh.model.mesh.field.setNumber(thresh, "SizeMax",  ff_mesh_size)
    gmsh.model.mesh.field.setNumber(thresh, "DistMin",  char_dim * 0.3)
    gmsh.model.mesh.field.setNumber(thresh, "DistMax",  far_field_r * 0.4)
    gmsh.model.mesh.field.setNumber(thresh, "Sigmoid",  1)
    gmsh.model.mesh.field.setAsBackgroundMesh(thresh)

    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints",         0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature",      0)
    gmsh.option.setNumber("Mesh.Smoothing",                  5)

    # ── Boundary layer field ──────────────────────────────────────────
    # PointsList: only vertices with interior angle < 150° (genuine sharp corners).
    # For smooth profiles (airfoils, cylinders): PointsList stays empty.
    # For bluff bodies (rectangles, box girders): corner points are added so
    # Gmsh generates fan elements that prevent quad overlap at corners.
    corner_pts = []
    for i in range(n_pts):
        p0 = polygon[(i - 1) % n_pts]
        p1 = polygon[i]
        p2 = polygon[(i + 1) % n_pts]
        v1 = (p0[0] - p1[0], p0[1] - p1[1])
        v2 = (p2[0] - p1[0], p2[1] - p1[1])
        l1 = math.hypot(*v1)
        l2 = math.hypot(*v2)
        if l1 < 1e-10 or l2 < 1e-10:
            continue
        cos_a = max(-1.0, min(1.0, (v1[0]*v2[0] + v1[1]*v2[1]) / (l1 * l2)))
        if math.degrees(math.acos(cos_a)) < 150.0:
            corner_pts.append(section_points[i])

    bl_field = gmsh.model.mesh.field.add("BoundaryLayer")
    gmsh.model.mesh.field.setNumbers(bl_field, "CurvesList", section_lines)
    if corner_pts:
        gmsh.model.mesh.field.setNumbers(bl_field, "PointsList", corner_pts)
    gmsh.model.mesh.field.setNumber(bl_field, "Size",     first_layer)
    gmsh.model.mesh.field.setNumber(bl_field, "Ratio",    bl_ratio)
    gmsh.model.mesh.field.setNumber(bl_field, "NbLayers", bl_layers)
    gmsh.model.mesh.field.setNumber(bl_field, "Quads",    1)
    gmsh.model.mesh.field.setAsBoundaryLayer(bl_field)

    # Algorithm 6 (Frontal-Delaunay) integrates best with BoundaryLayer fields
    gmsh.option.setNumber("Mesh.Algorithm", 6)

    # ── Physical groups ───────────────────────────────────────────────
    gmsh.model.addPhysicalGroup(1, section_lines, tag=1, name="section")
    gmsh.model.addPhysicalGroup(1, ff_arcs,       tag=2, name="farfield")
    gmsh.model.addPhysicalGroup(2, [surface],     tag=1, name="fluid")

    gmsh.model.mesh.generate(2)

    # ── Extract mesh data ─────────────────────────────────────────────
    node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
    nodes    = []
    node_map = {}
    for i, tag in enumerate(node_tags):
        x = node_coords[i * 3]
        y = node_coords[i * 3 + 1]
        nodes.append({"id": int(tag), "x": round(x, 6), "y": round(y, 6)})
        node_map[int(tag)] = (x, y)

    triangles = []
    quads     = []
    elem_types, elem_tags, elem_node_tags = gmsh.model.mesh.getElements(dim=2)
    eid = 1
    for etype, etags, enodes in zip(elem_types, elem_tags, elem_node_tags):
        if etype == 2:   # 3-node triangle
            for i in range(len(etags)):
                triangles.append({"id": eid,
                                   "nodes": [int(enodes[i*3]),
                                             int(enodes[i*3+1]),
                                             int(enodes[i*3+2])]})
                eid += 1
        elif etype == 3: # 4-node quad
            for i in range(len(etags)):
                quads.append({"id": eid,
                               "nodes": [int(enodes[i*4]),
                                         int(enodes[i*4+1]),
                                         int(enodes[i*4+2]),
                                         int(enodes[i*4+3])]})
                eid += 1

    section_node_ids = set()
    for line in section_lines:
        for nt in gmsh.model.mesh.getNodes(dim=1, tag=line)[0]:
            section_node_ids.add(int(nt))

    ff_node_ids = set()
    for arc in ff_arcs:
        for nt in gmsh.model.mesh.getNodes(dim=1, tag=arc)[0]:
            ff_node_ids.add(int(nt))

    stats = {
        "n_nodes":          len(nodes),
        "n_triangles":      len(triangles),
        "n_quads":          len(quads),
        "n_elements":       len(triangles) + len(quads),
        "n_section_nodes":  len(section_node_ids),
        "n_farfield_nodes": len(ff_node_ids),
        "char_dim":         round(char_dim, 4),
        "far_field_r":      round(far_field_r, 3),
        "bl_layers":        bl_layers,
        "bl_first_layer_mm": round(first_layer * 1000, 4),
        "n_corners":        len(corner_pts),
    }

    gmsh.finalize()

    return {
        "nodes":              nodes,
        "triangles":          triangles,
        "quads":              quads,
        "boundary_section":   sorted(section_node_ids),
        "boundary_farfield":  sorted(ff_node_ids),
        "section_polygon":    polygon,
        "wind_angle":         wind_angle,
        "stats":              stats,
    }


if __name__ == "__main__":
    # Quick smoke-test: rectangle (bluff body) + NACA0012 (smooth profile)
    import json, math

    rect = [[0, 0], [4, 0], [4, 0.5], [0, 0.5]]
    r = generate_cfd_mesh(rect, wind_speed=25, mesh_size=0.2, far_field_factor=10)
    print(f"Rect:  {r['stats']['n_nodes']} nodes, {r['stats']['n_elements']} elems, "
          f"{r['stats']['n_quads']} quads, {r['stats']['bl_layers']} BL layers, "
          f"y1={r['stats']['bl_first_layer_mm']:.3f} mm, corners={r['stats']['n_corners']}")

    N = 40
    yt = lambda x: (0.12/0.2)*(0.2969*x**0.5 - 0.126*x - 0.3516*x**2 + 0.2843*x**3 - 0.1015*x**4)
    naca = []
    for i in range(N+1):
        x = (1 - math.cos(math.pi*i/N)) / 2
        naca.append([round(x,4),  round(yt(x),4)])
    for i in range(N, 0, -1):
        x = (1 - math.cos(math.pi*i/N)) / 2
        naca.append([round(x,4), -round(yt(x),4)])

    a = generate_cfd_mesh(naca, wind_speed=90, mesh_size=0.02, far_field_factor=20)
    print(f"NACA:  {a['stats']['n_nodes']} nodes, {a['stats']['n_elements']} elems, "
          f"{a['stats']['n_quads']} quads, {a['stats']['bl_layers']} BL layers, "
          f"y1={a['stats']['bl_first_layer_mm']:.3f} mm, corners={a['stats']['n_corners']}")
