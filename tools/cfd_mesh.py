"""
CFD Mesh Generator for 2D bridge cross-section aerodynamics.

Generates a 2D mesh around a cross-section polygon using Gmsh:
- O-grid topology around the section
- Boundary layer refinement
- Far-field boundary at configurable distance
- Output as JSON (nodes, elements) for visualization and solver input

Usage:
    from tools.cfd_mesh import generate_cfd_mesh
    result = generate_cfd_mesh(polygon, wind_angle=0, mesh_size=0.1, far_field=20)
"""

import json
import math
import os
import tempfile


def generate_cfd_mesh(polygon, wind_angle=0, mesh_size=0.5, far_field_factor=15,
                      bl_layers=4, bl_ratio=1.4):
    """
    Generate a 2D CFD mesh around a cross-section polygon.

    Args:
        polygon: list of [x, y] points defining the cross-section (closed, CCW)
        wind_angle: wind direction in degrees (0 = from left)
        mesh_size: target element size near the section [m]
        far_field_factor: far-field radius as multiple of section width
        bl_thickness: total boundary layer thickness [m]
        bl_layers: number of boundary layer elements
        bl_ratio: growth ratio for boundary layer

    Returns:
        dict with:
            nodes: [{id, x, y}]
            triangles: [{id, nodes: [n1, n2, n3]}]
            quads: [{id, nodes: [n1, n2, n3, n4]}]  (boundary layer)
            boundary_section: [node_ids on section surface]
            boundary_farfield: [node_ids on far-field]
            section_polygon: [[x,y], ...] (input polygon)
            stats: {n_nodes, n_elements, n_bl_elements}
    """
    import gmsh

    gmsh.initialize()
    gmsh.option.setNumber("General.Verbosity", 0)
    gmsh.model.add("cfd_section")

    # Compute section dimensions
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    char_dim = max(width, height)
    far_field_r = char_dim * far_field_factor

    # Far-field mesh size (coarser away from section)
    ff_mesh_size = char_dim * 2

    # Create section polygon points
    section_points = []
    for i, (x, y) in enumerate(polygon):
        pid = gmsh.model.geo.addPoint(x, y, 0, mesh_size)
        section_points.append(pid)

    # Create section lines (closed loop)
    section_lines = []
    n = len(section_points)
    for i in range(n):
        lid = gmsh.model.geo.addLine(section_points[i], section_points[(i + 1) % n])
        section_lines.append(lid)

    section_loop = gmsh.model.geo.addCurveLoop(section_lines)

    # Create circular far-field boundary
    ff_points = []
    ff_n = 32  # points on far-field circle
    for i in range(ff_n):
        angle = 2 * math.pi * i / ff_n
        x = cx + far_field_r * math.cos(angle)
        y = cy + far_field_r * math.sin(angle)
        pid = gmsh.model.geo.addPoint(x, y, 0, ff_mesh_size)
        ff_points.append(pid)

    # Far-field arcs (4 quarter circles)
    center_pt = gmsh.model.geo.addPoint(cx, cy, 0, ff_mesh_size)
    ff_arcs = []
    quarter = ff_n // 4
    for i in range(4):
        start = ff_points[i * quarter]
        end = ff_points[((i + 1) * quarter) % ff_n]
        arc = gmsh.model.geo.addCircleArc(start, center_pt, end)
        ff_arcs.append(arc)

    ff_loop = gmsh.model.geo.addCurveLoop(ff_arcs)

    # Create surface between section and far-field (annular domain)
    surface = gmsh.model.geo.addPlaneSurface([ff_loop, section_loop])

    gmsh.model.geo.synchronize()

    # ── Size fields ──────────────────────────────────────────────────────────
    # 1. Distance from section surface
    dist_field = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(dist_field, "CurvesList", section_lines)

    # 2. Three-zone threshold:
    #    - Very fine immediately outside BL (near-wake, shear layers)
    #    - Medium in near-field
    #    - Coarse in far-field
    near_size  = mesh_size * 0.6          # just outside BL
    trans_size = mesh_size                  # mid near-field
    dist_near  = char_dim * 0.3            # end of very fine zone
    dist_trans = char_dim * 1.5            # end of near-field

    thresh1 = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(thresh1, "InField",  dist_field)
    gmsh.model.mesh.field.setNumber(thresh1, "SizeMin",  near_size)
    gmsh.model.mesh.field.setNumber(thresh1, "SizeMax",  ff_mesh_size)
    gmsh.model.mesh.field.setNumber(thresh1, "DistMin",  dist_near)
    gmsh.model.mesh.field.setNumber(thresh1, "DistMax",  far_field_r * 0.4)
    gmsh.model.mesh.field.setNumber(thresh1, "Sigmoid",  1)   # smooth S-curve transition

    gmsh.model.mesh.field.setAsBackgroundMesh(thresh1)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints",         0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature",      0)
    gmsh.option.setNumber("Mesh.Smoothing",                  5)  # Laplacian smoothing passes

    # ── Boundary Layer ────────────────────────────────────────────────────────
    # Tuned for k-epsilon wall functions (y+ ≈ 30–100):
    #   first_layer ≈ char_dim * 0.003   →  y+ ~ 50 at Re ~ 10^6
    #   4 layers at ratio 1.4  →  total ≈ 12× first_layer
    if bl_layers > 0:
        first_layer = max(2e-4, min(mesh_size * 0.04, char_dim * 0.004))

        bl_field = gmsh.model.mesh.field.add("BoundaryLayer")
        gmsh.model.mesh.field.setNumbers(bl_field, "CurvesList",    section_lines)
        gmsh.model.mesh.field.setNumbers(bl_field, "PointsList",    section_points)
        gmsh.model.mesh.field.setNumber (bl_field, "Size",          first_layer)
        gmsh.model.mesh.field.setNumber (bl_field, "Ratio",         bl_ratio)
        gmsh.model.mesh.field.setNumber (bl_field, "NbLayers",      bl_layers)
        gmsh.model.mesh.field.setNumber (bl_field, "Quads",         1)
        # IntersectMetrics=1 avoids element collapse at sharp concave corners
        gmsh.model.mesh.field.setNumber (bl_field, "IntersectMetrics", 1)
        gmsh.model.mesh.field.setAsBoundaryLayer(bl_field)

    # Physical groups for boundary conditions
    gmsh.model.addPhysicalGroup(1, section_lines, tag=1, name="section")
    gmsh.model.addPhysicalGroup(1, ff_arcs, tag=2, name="farfield")
    gmsh.model.addPhysicalGroup(2, [surface], tag=1, name="fluid")

    # Generate 2D mesh
    gmsh.model.mesh.generate(2)

    # Extract mesh data
    node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
    nodes = []
    node_map = {}
    for i, tag in enumerate(node_tags):
        x = node_coords[i * 3]
        y = node_coords[i * 3 + 1]
        nodes.append({"id": int(tag), "x": round(x, 6), "y": round(y, 6)})
        node_map[int(tag)] = (x, y)

    # Get elements
    triangles = []
    quads = []
    elem_types, elem_tags, elem_node_tags = gmsh.model.mesh.getElements(dim=2)
    eid = 1
    for etype, etags, enodes in zip(elem_types, elem_tags, elem_node_tags):
        if etype == 2:  # 3-node triangle
            for i in range(len(etags)):
                n1 = int(enodes[i * 3])
                n2 = int(enodes[i * 3 + 1])
                n3 = int(enodes[i * 3 + 2])
                triangles.append({"id": eid, "nodes": [n1, n2, n3]})
                eid += 1
        elif etype == 3:  # 4-node quad
            for i in range(len(etags)):
                n1 = int(enodes[i * 4])
                n2 = int(enodes[i * 4 + 1])
                n3 = int(enodes[i * 4 + 2])
                n4 = int(enodes[i * 4 + 3])
                quads.append({"id": eid, "nodes": [n1, n2, n3, n4]})
                eid += 1

    # Get boundary nodes
    section_node_ids = set()
    for line in section_lines:
        _, tags, _ = gmsh.model.mesh.getElements(dim=1, tag=line)
        for tag_arr in tags:
            for t in tag_arr:
                pass
        node_tags_line = gmsh.model.mesh.getNodes(dim=1, tag=line)[0]
        for nt in node_tags_line:
            section_node_ids.add(int(nt))

    ff_node_ids = set()
    for arc in ff_arcs:
        node_tags_arc = gmsh.model.mesh.getNodes(dim=1, tag=arc)[0]
        for nt in node_tags_arc:
            ff_node_ids.add(int(nt))

    stats = {
        "n_nodes": len(nodes),
        "n_triangles": len(triangles),
        "n_quads": len(quads),
        "n_elements": len(triangles) + len(quads),
        "n_section_nodes": len(section_node_ids),
        "n_farfield_nodes": len(ff_node_ids),
        "char_dim": round(char_dim, 3),
        "far_field_r": round(far_field_r, 3),
    }

    gmsh.finalize()

    return {
        "nodes": nodes,
        "triangles": triangles,
        "quads": quads,
        "boundary_section": sorted(section_node_ids),
        "boundary_farfield": sorted(ff_node_ids),
        "section_polygon": polygon,
        "wind_angle": wind_angle,
        "stats": stats,
    }


if __name__ == "__main__":
    # Test: rectangular cross-section
    rect = [[0, 0], [4, 0], [4, 0.5], [0, 0.5]]
    result = generate_cfd_mesh(rect, mesh_size=0.2, far_field_factor=10)
    print(f"Mesh: {result['stats']['n_nodes']} nodes, {result['stats']['n_elements']} elements")
    print(f"Section boundary: {result['stats']['n_section_nodes']} nodes")
    print(f"Far-field: {result['stats']['n_farfield_nodes']} nodes")

    # Save for inspection
    with open("tests/_output/cfd_mesh_test.json", "w") as f:
        json.dump(result, f, indent=2)
    print("Saved to tests/_output/cfd_mesh_test.json")
