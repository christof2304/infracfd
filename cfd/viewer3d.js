// viewer3d.js — Three.js viewer for 3D GLB models and 2D CFD result colormaps

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { LineGeometry } from 'three/addons/lines/LineGeometry.js';
import { Line2 } from 'three/addons/lines/Line2.js';

export class Viewer3D {
    constructor(canvasEl) {
        this.canvas = canvasEl;
        this._scene = new THREE.Scene();
        this._scene.background = new THREE.Color(0x0d0f14);

        this._renderer = new THREE.WebGLRenderer({ canvas: canvasEl, antialias: true });
        this._renderer.setPixelRatio(Math.min(devicePixelRatio, 2));

        // Isometric orthographic camera (3D buildings + GLB)
        this._camera = new THREE.OrthographicCamera(-50, 50, 50, -50, -1000, 10000);
        this._camera.position.set(1, 1, 1);
        this._camera.up.set(0, 1, 0);
        this._isoSize = 50;

        // Orthographic camera (2D CFD, lazy-init)
        this._orthoCamera = null;
        this._activeCamera = this._camera;
        this._is2D = false;

        this._controls = new OrbitControls(this._camera, canvasEl);
        this._controls.enableDamping = true;
        this._controls.dampingFactor = 0.08;

        this._lights();
        this._modelGroup = new THREE.Group();
        this._cfdGroup   = new THREE.Group();
        this._scene.add(this._modelGroup);
        this._scene.add(this._cfdGroup);

        this._initGizmo();

        this._resizeObs = new ResizeObserver(() => this._resize());
        this._resizeObs.observe(canvasEl.parentElement || document.body);
        this._resize();
        this._animate();
    }

    _initGizmo() {
        this._gizmoScene = new THREE.Scene();

        // RGB axes: X=red, Y=green, Z=blue (standard convention)
        const L = 0.72;
        const axesDef = [
            { dir: [1,0,0], color: 0xee3333, label: 'X' },
            { dir: [0,1,0], color: 0x33cc55, label: 'Y' },
            { dir: [0,0,1], color: 0x3388ff, label: 'Z' },
        ];
        for (const { dir, color, label } of axesDef) {
            const d = new THREE.Vector3(...dir);

            // Shaft
            const shaftGeom = new THREE.BufferGeometry().setFromPoints([
                new THREE.Vector3(), d.clone().multiplyScalar(L)
            ]);
            this._gizmoScene.add(new THREE.Line(shaftGeom,
                new THREE.LineBasicMaterial({ color })));

            // Arrowhead cone
            const cone = new THREE.Mesh(
                new THREE.ConeGeometry(0.07, 0.18, 8),
                new THREE.MeshBasicMaterial({ color })
            );
            cone.position.copy(d.clone().multiplyScalar(L + 0.09));
            cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), d);
            this._gizmoScene.add(cone);

            // Text label via canvas sprite
            const cv = document.createElement('canvas');
            cv.width = 64; cv.height = 64;
            const ctx = cv.getContext('2d');
            ctx.font = 'bold 38px "Barlow Condensed", sans-serif';
            ctx.fillStyle = '#' + color.toString(16).padStart(6, '0');
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(label, 32, 32);
            const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
                map: new THREE.CanvasTexture(cv),
                transparent: true,
                depthTest: false,
            }));
            sprite.scale.set(0.38, 0.38, 1);
            sprite.position.copy(d.clone().multiplyScalar(L + 0.33));
            this._gizmoScene.add(sprite);
        }

        // Fixed orthographic camera — rotation is synced from active camera each frame
        this._gizmoCamera = new THREE.OrthographicCamera(-1.4, 1.4, 1.4, -1.4, -10, 10);
    }

    _lights() {
        this._scene.add(new THREE.AmbientLight(0xffffff, 0.5));
        const dir = new THREE.DirectionalLight(0xffffff, 1.0);
        dir.position.set(1, 2, 1.5);
        this._scene.add(dir);
        const dir2 = new THREE.DirectionalLight(0x8899cc, 0.3);
        dir2.position.set(-1, -1, -1);
        this._scene.add(dir2);
    }

    _resize() {
        const el = this.canvas.parentElement;
        if (!el) return;
        const w = el.clientWidth, h = el.clientHeight;
        if (w === 0 || h === 0) return;
        this._renderer.setSize(w, h, false);

        {
            const aspect = w / h;
            const s = this._isoSize || 50;
            this._camera.left   = -s * aspect;
            this._camera.right  =  s * aspect;
            this._camera.top    =  s;
            this._camera.bottom = -s;
            this._camera.updateProjectionMatrix();
        }

        if (this._orthoCamera) {
            const aspect = w / h;
            const s = this._orthoSize || 50;
            this._orthoCamera.left   = -s * aspect;
            this._orthoCamera.right  =  s * aspect;
            this._orthoCamera.top    =  s;
            this._orthoCamera.bottom = -s;
            this._orthoCamera.updateProjectionMatrix();
        }

        if (this._updateStreamlineResolution) this._updateStreamlineResolution();
        if (this._sliceStreamMats) {
            const sz = this._renderer.getSize(new THREE.Vector2());
            for (const mat of Object.values(this._sliceStreamMats)) mat.resolution.set(sz.x, sz.y);
        }
    }

    _animate() {
        this._rafId = requestAnimationFrame(() => this._animate());
        if (!this.canvas.offsetParent && this.canvas.style.display === 'none') return;
        this._controls.update();

        // Main scene
        this._renderer.setScissorTest(false);
        this._renderer.render(this._scene, this._activeCamera);

        // CRS gizmo — bottom-left corner, 3D mode only
        if (!this._is2D) {
            const GS = 88; // gizmo size in CSS pixels
            const sz = this._renderer.getSize(new THREE.Vector2());
            this._gizmoCamera.quaternion.copy(this._activeCamera.quaternion);
            this._renderer.autoClear = false;
            this._renderer.clearDepth();
            this._renderer.setScissorTest(true);
            this._renderer.setScissor(10, 10, GS, GS);
            this._renderer.setViewport(10, 10, GS, GS);
            this._renderer.render(this._gizmoScene, this._gizmoCamera);
            this._renderer.setScissorTest(false);
            this._renderer.setViewport(0, 0, sz.x, sz.y);
            this._renderer.autoClear = true;
        }
    }

    // ── 2D orthographic mode ──────────────────────────────────────

    // Sets up orthographic camera + 2D controls WITHOUT changing the view.
    // Always call syncViewWithSVG() afterwards to position the camera.
    _initOrthoMode() {
        if (!this._orthoCamera) {
            this._orthoCamera = new THREE.OrthographicCamera(
                -50, 50, 50, -50, -1000, 1000
            );
            this._orthoCamera.position.set(0, 0, 100);
            this._orthoCamera.up.set(0, 1, 0);
            this._orthoSize = 50;
        }

        if (!this._is2D) {
            this._controls.dispose();
            this._controls = new OrbitControls(this._orthoCamera, this.canvas);
            this._controls.enableRotate        = false;
            this._controls.enableDamping       = false;
            this._controls.screenSpacePanning  = true;
            this._activeCamera = this._orthoCamera;
            this._is2D = true;
        }
    }

    // Fits the orthographic camera to a bounding box (used for 3D footprint preview).
    enter2DView(box) {
        const size   = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        const el     = this.canvas.parentElement;
        const aspect = el ? el.clientWidth / Math.max(el.clientHeight, 1) : 1;
        const s = Math.max(size.x / aspect, size.y) * 0.65;

        this._initOrthoMode();

        this._orthoSize = s;
        this._orthoCamera.left   = -s * aspect;
        this._orthoCamera.right  =  s * aspect;
        this._orthoCamera.top    =  s;
        this._orthoCamera.bottom = -s;
        this._orthoCamera.zoom   = 1;
        this._orthoCamera.position.set(center.x, center.y, 100);
        this._orthoCamera.updateProjectionMatrix();
        this._controls.target.set(center.x, center.y, 0);
        this._controls.update();
    }

    exit2DView() {
        if (!this._is2D) return;
        this._controls.dispose();
        this._controls = new OrbitControls(this._camera, this.canvas);
        this._controls.enableDamping = true;
        this._controls.dampingFactor = 0.08;
        this._activeCamera = this._camera;
        this._is2D = false;
    }

    // ── GLB loading ───────────────────────────────────────────────

    loadGLB(url, scale = 1, onProgress) {
        this._clearModel();
        this.exit2DView();
        const loader = new GLTFLoader();
        loader.load(url, gltf => {
            const model = gltf.scene;
            model.scale.setScalar(scale);
            const box = new THREE.Box3().setFromObject(model);
            const center = box.getCenter(new THREE.Vector3());
            model.position.sub(center);
            this._modelGroup.add(model);
            const boxWorld = new THREE.Box3().setFromObject(this._modelGroup);
            this._fitCamera3D(boxWorld);
            this.showWindArrow3D(boxWorld);
            onProgress?.({ done: true, faces: this._countFaces(model), box: boxWorld });
        }, xhr => {
            if (xhr.total) onProgress?.({ pct: xhr.loaded / xhr.total });
        }, err => {
            onProgress?.({ error: err.message });
        });
    }

    _countFaces(obj) {
        let n = 0;
        obj.traverse(c => { if (c.isMesh) n += (c.geometry.index?.count ?? c.geometry.attributes.position.count) / 3; });
        return Math.round(n);
    }

    _fitCamera3D(box) {
        this.exit2DView();  // restore 3D orbit controls if coming from 2D mode
        const size   = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3()).sub(this._modelGroup.position);
        const maxDim = Math.max(size.x, size.y, size.z);
        const dist   = maxDim * 2.5;

        // Isometric: camera along (1,1,1) diagonal, equal 120° projection of all axes
        const isoDir = new THREE.Vector3(1, 1, 1).normalize();
        this._camera.position.copy(center).addScaledVector(isoDir, dist);
        this._camera.up.set(0, 1, 0);
        this._camera.lookAt(center.x, center.y, center.z);

        // Fit orthographic frustum to bounding box with some padding
        const el = this.canvas.parentElement;
        const aspect = el ? el.clientWidth / Math.max(el.clientHeight, 1) : 1;
        const s = maxDim * 0.75;
        this._isoSize = s;
        this._camera.left   = -s * aspect;
        this._camera.right  =  s * aspect;
        this._camera.top    =  s;
        this._camera.bottom = -s;
        this._camera.near   = -dist * 3;
        this._camera.far    =  dist * 3;
        this._camera.zoom   = 1;
        this._camera.updateProjectionMatrix();

        this._controls.target.set(center.x, center.y, center.z);
        this._controls.update();
    }

    // ── Mesh-only display ─────────────────────────────────────────
    // Handles two formats:
    //   A) solve result  — nodes:[{id,x,y}], triangles:[{nodes:[id,id,id]}]
    //   B) mesh endpoint — nodes:[[x,y]] or [{x,y}], triangles:[[i,j,k]]

    showMeshOnly(solveResult) {
        this._clearCFD();
        const field = solveResult?.field ?? solveResult;
        if (!field?.nodes || !field?.triangles) return;

        // Normalise nodes → sequential array of [x, y]
        const { nodeXY, idToIdx } = _normaliseNodes(field.nodes);

        // Normalise triangles → array of [i, j, k] (array indices)
        const triIndices = _normaliseTris(field.triangles, idToIdx);

        // Split quads into 2 triangles each so BL rows are rendered
        if (field.quads?.length) {
            for (const q of field.quads) {
                const ns = Array.isArray(q) ? q : q.nodes;
                const [a, b, c, d] = ns.map(id => idToIdx.has(id) ? idToIdx.get(id) : -1);
                if (a >= 0 && b >= 0 && c >= 0 && d >= 0)
                    triIndices.push([a, b, c], [a, c, d]);
            }
        }

        // Fill mesh
        const pos = new Float32Array(triIndices.length * 3 * 3);
        let vi = 0;
        for (const [a, b, c] of triIndices) {
            for (const idx of [a, b, c]) {
                const [x, y] = nodeXY[idx] || [0, 0];
                pos[vi++] = x; pos[vi++] = y; pos[vi++] = 0;
            }
        }
        const fillGeom = new THREE.BufferGeometry();
        fillGeom.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        const fillMesh = new THREE.Mesh(fillGeom,
            new THREE.MeshBasicMaterial({ color: 0x0d1828, side: THREE.DoubleSide }));
        this._cfdGroup.add(fillMesh);

        // Edge lines (subsample for perf — show every edge)
        const edgeArr = [];
        for (const [a, b, c] of triIndices) {
            const pairs = [[a, b], [b, c], [c, a]];
            for (const [p, q] of pairs) {
                const [x1, y1] = nodeXY[p] || [0, 0];
                const [x2, y2] = nodeXY[q] || [0, 0];
                edgeArr.push(x1, y1, 0.05, x2, y2, 0.05);
            }
        }
        const edgeGeom = new THREE.BufferGeometry();
        edgeGeom.setAttribute('position', new THREE.BufferAttribute(new Float32Array(edgeArr), 3));
        this._cfdGroup.add(new THREE.LineSegments(edgeGeom,
            new THREE.LineBasicMaterial({ color: 0x2a5090, transparent: true, opacity: 0.55 })));

        // Set up ortho mode — caller positions camera via fitOrthoView() or syncViewWithSVG()
        this._initOrthoMode();
    }

    // ── CFD result mesh (2D colormap) ─────────────────────────────
    // solveResult: full JSON from /api/cfd/solve
    // fieldName: 'pressure' | 'speed' | 'vorticity' | 'turb_k'
    // Field values are per-triangle; node IDs are non-sequential.

    showCFDResult(solveResult, fieldName) {
        this._clearCFD();
        const field = solveResult?.field;
        if (!field) return;

        const rawNodes = field.nodes;
        const rawTris  = field.triangles;
        const vals     = field[fieldName]; // may be undefined for timestep data

        if (!rawNodes || !rawTris) return;

        // Normalise to consistent format
        const { nodeXY, idToIdx } = _normaliseNodes(rawNodes);
        const triIndices = _normaliseTris(rawTris, idToIdx);

        // ── Per-triangle values via cell_id ─────────────────────────
        // vals[] is indexed by OpenFOAM CELL position, NOT by triangle index.
        // With BL quads split to 2 triangles, #triangles > #cells → vals[i]
        // would be undefined for i ≥ n_cells → black patches.
        // Fix: look up vals[tri.cell_id] for each triangle.
        // vals[] is per-cell by OpenFOAM cell index; tri.p holds the value for that triangle.
        // For timestep data vals is undefined — tri.p always contains the correct value.
        const triVals = rawTris.map(tri => {
            if (!vals || fieldName === 'pressure') return tri.p ?? 0;
            const cid = tri.cell_id;
            return (cid != null && cid >= 0 && cid < vals.length) ? vals[cid] : (tri.p ?? 0);
        });

        // Filter out triangles with out-of-bounds node indices OR NaN values
        const nNodes = nodeXY.length;
        const validMask = triIndices.map((tri, i) =>
            isFinite(triVals[i]) &&           // no NaN / Inf values
            tri.every(idx => idx >= 0 && idx < nNodes));

        const validVals = triVals.filter((_, i) => validMask[i]);

        // 5th/95th percentile — only finite values
        const finite = validVals.filter(isFinite);
        if (!finite.length) return;
        const sortedV = [...finite].sort((a, b) => a - b);
        const p05 = sortedV[Math.floor(sortedV.length * 0.05)] ?? 0;
        const p95 = sortedV[Math.floor(sortedV.length * 0.95)] ?? 1;
        // Signed fields (vorticity) get a symmetric range so 0 maps to the
        // diverging colormap's neutral centre (white); others use the raw p05–p95.
        const cmap = cmapFor(fieldName);
        let vmin, vmax;
        if (cmap === coolwarmColor) {
            const A = Math.max(Math.abs(p05), Math.abs(p95), 1e-9);
            vmin = -A; vmax = A;
        } else {
            vmin = p05; vmax = p95;
        }
        const range = Math.max(vmax - vmin, 1e-9);

        // ── Build geometry (smooth per-node coloring) ────────────────
        // OpenFOAM stores one value per cell (→ per triangle), which renders
        // blocky. Interpolate those cell values to the mesh nodes (mean of the
        // values of all valid triangles meeting at a node) and colour each
        // vertex by its node value, so the GPU interpolates across the face
        // (Gouraud). Accumulating over ONLY the rendered (valid) triangles
        // guarantees every emitted vertex's node has count ≥ 1 — this avoids
        // the black boundary-node artifacts a naive earlier attempt produced.
        const validIdxs = [];
        for (let i = 0; i < triIndices.length; i++) { if (validMask[i]) validIdxs.push(i); }
        const tris = validIdxs.map(i => triIndices[i]);

        const pos = new Float32Array(tris.length * 3 * 3);
        let pi = 0;
        for (const tri of tris) {
            for (const idx of tri) {
                const [x, y] = nodeXY[idx];
                pos[pi] = x; pos[pi+1] = y; pos[pi+2] = 0;
                pi += 3;
            }
        }
        const color = this._smoothNodeColors(
            tris, validIdxs.map(i => triVals[i]), nNodes, vmin, range, cmap);

        const geom = new THREE.BufferGeometry();
        geom.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        const colorAttr = new THREE.BufferAttribute(color, 3);
        colorAttr.usage = THREE.DynamicDrawUsage;
        geom.setAttribute('color', colorAttr);

        const mat  = new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide });
        const mesh = new THREE.Mesh(geom, mat);
        this._cfdGroup.add(mesh);

        this._cfdAnimMesh = mesh;
        this._cfdAnimMeta = { validIdxs, tris, nNodes, vmin, vmax, range, cmap };

        this._initOrthoMode();
        return { vmin, vmax };
    }

    // Interpolate per-triangle (cell) values to nodes and return a non-indexed
    // per-vertex color array for smooth (Gouraud) shading. `tris` are the
    // rendered triangles (node-index triples); `valsPerTri[k]` is the cell value
    // of tris[k]. Each node value is the mean of the values of the triangles
    // meeting at it — computed over exactly the rendered set, so every node in
    // `tris` is touched at least once (no zero-count / black-vertex artifacts).
    _smoothNodeColors(tris, valsPerTri, nNodes, vmin, range, cmap = jetColor) {
        const sum = new Float64Array(nNodes);
        const cnt = new Float64Array(nNodes);
        for (let k = 0; k < tris.length; k++) {
            const v = valsPerTri[k], tri = tris[k];
            sum[tri[0]] += v; cnt[tri[0]]++;
            sum[tri[1]] += v; cnt[tri[1]]++;
            sum[tri[2]] += v; cnt[tri[2]]++;
        }
        const color = new Float32Array(tris.length * 3 * 3);
        let vi = 0;
        for (let k = 0; k < tris.length; k++) {
            const tri = tris[k];
            for (let j = 0; j < 3; j++) {
                const idx = tri[j];
                const nv = cnt[idx] ? sum[idx] / cnt[idx] : valsPerTri[k];
                const t = Math.max(0, Math.min(1, (nv - vmin) / range));
                const [r, g, b] = cmap(t);
                color[vi] = r; color[vi+1] = g; color[vi+2] = b;
                vi += 3;
            }
        }
        return color;
    }

    // ── Animation color pre-computation ──────────────────────────

    // Compute a color Float32Array from timestep data, reusing the cached mesh mapping.
    // Returns null if no cached mesh exists yet. Uses the same node-averaged
    // smoothing as the static result so animation frames look identical.
    computeAnimColors(timestepData, vmin, vmax) {
        const meta = this._cfdAnimMeta;
        if (!meta) return null;
        const { validIdxs, tris, nNodes, range, cmap } = meta;
        const field = timestepData.field ?? timestepData;
        if (!field?.triangles) return null;
        const valsPerTri = validIdxs.map(rawIdx => field.triangles[rawIdx]?.p ?? vmin);
        return this._smoothNodeColors(tris, valsPerTri, nNodes, vmin, range, cmap ?? jetColor);
    }

    // Instantly apply a pre-computed color array to the CFD mesh (no geometry rebuild).
    applyAnimColors(colorArray) {
        const attr = this._cfdAnimMesh?.geometry?.getAttribute('color');
        if (!attr || !colorArray) return;
        if (colorArray.length !== attr.array.length) return; // size mismatch — stale cache
        attr.array.set(colorArray);
        attr.needsUpdate = true;
    }

    // ── 3D result: slices + streamlines ──────────────────────────

    // Show a plain semi-transparent plane (before results are computed).
    // Hz-plane = blue, Vt-plane = orange.
    show3DSlicePlane(plane, value, bbox, sliceId = 'hz') {
        this._ensure3DGroups();
        this._removeSlicePlane(sliceId);

        const [xMin, yMin, zMin] = bbox.min;
        const [xMax, yMax, zMax] = bbox.max;
        const m = 0.05; // 5% margin
        const color = sliceId === 'hz' ? 0x3d9eff : 0xffaa44;

        // OF→Three.js: (x, y, z) → (x, z, -y)  [OF Z=up → Three.js Y, OF Y → Three.js -Z]
        let geom, pos, rot;
        if (plane === 'z') {
            // Horizontal slice at OF height value → Three.js Y=value, plane in XZ
            const w = (xMax - xMin) * (1 + m), d = (yMax - yMin) * (1 + m);
            geom = new THREE.PlaneGeometry(w, d);
            pos  = new THREE.Vector3((xMin+xMax)/2, value, -(yMin+yMax)/2);
            rot  = new THREE.Euler(Math.PI / 2, 0, 0);
        } else {
            // Vertical crosswind slice at OF Y=value → Three.js Z=-value, plane in XY
            const w = (xMax - xMin) * (1 + m), h = (zMax - zMin) * (1 + m);
            geom = new THREE.PlaneGeometry(w, h);
            pos  = new THREE.Vector3((xMin+xMax)/2, (zMin+zMax)/2, -value);
            rot  = null;
        }

        const grp = new THREE.Group();
        const fill = new THREE.Mesh(geom,
            // depthWrite off + low renderOrder: the reference plane never z-fights the colored
            // result slice that sits on the same coordinate — the result always draws on top.
            new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.12, side: THREE.DoubleSide,
                                          depthWrite: false }));
        const edge = new THREE.LineSegments(new THREE.EdgesGeometry(geom),
            new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.6 }));
        grp.add(fill, edge);
        grp.renderOrder = 0;
        grp.position.copy(pos);
        if (rot) grp.rotation.copy(rot);

        this._planeMeshes = this._planeMeshes ?? {};
        this._planeMeshes[sliceId] = grp;
        this._sliceGroup.add(grp);
    }

    setSlicePlaneVisible(sliceId, visible) {
        const grp = this._planeMeshes?.[sliceId];
        if (grp) grp.visible = visible;
        const col = this._slices?.[sliceId];
        if (col) col.visible = visible;
        const vec = this._slices?.[sliceId + '_vec'];
        if (vec) vec.visible = visible;
        // Streamlines are independent of plane visibility — controlled by their own checkbox.
    }

    _removeSlicePlane(id) {
        const grp = this._planeMeshes?.[id];
        if (!grp) return;
        grp.traverse(c => { c.geometry?.dispose(); c.material?.dispose(); });
        this._sliceGroup.remove(grp);
        delete this._planeMeshes[id];
    }

    // Show a colored 2D slice in 3D space.
    // plane: 'z' | 'y', planeValue: world coordinate
    // sliceData: {nodes:[{id,x,y}], triangles:[{nodes,p}], p_range, vectors}
    show3DSlice(sliceData, fieldName, plane, planeValue, sliceId = 'hz') {
        this._ensure3DGroups();
        this._removeSlice(sliceId);

        if (!sliceData?.nodes?.length || !sliceData?.triangles?.length) return;

        // Build node 3D position map. OF→Three.js: (x,y,z) → (x, z, -y)
        // z-plane: node.(x=OF_x, y=OF_y), planeValue=OF_z → Three.js (x, OF_z, -OF_y)
        // y-plane: node.(x=OF_x, y=OF_z) [axes 0,2], planeValue=OF_y → Three.js (x, OF_z, -OF_y)
        const nodePos = {};
        for (const n of sliceData.nodes) {
            if (plane === 'z') nodePos[n.id] = [n.x, planeValue, -n.y];
            else               nodePos[n.id] = [n.x, n.y, -planeValue];
        }

        const tris = sliceData.triangles;
        const [vmin, vmax] = sliceData.p_range ?? [0, 1];
        const range = Math.max(vmax - vmin, 1e-9);

        // Vertex interpolation — accumulate triangle values onto nodes
        const nodeIds  = Object.keys(nodePos).map(Number);
        const nodeIdx  = {};
        nodeIds.forEach((id, i) => nodeIdx[id] = i);
        const nNodes   = nodeIds.length;
        const nodeSum  = new Float64Array(nNodes);
        const nodeCnt  = new Uint32Array(nNodes);

        for (const tri of tris) {
            const v = tri.p ?? 0;
            for (const nid of tri.nodes) {
                const i = nodeIdx[nid];
                if (i !== undefined) { nodeSum[i] += v; nodeCnt[i]++; }
            }
        }
        const nodeT = nodeIds.map((_, i) =>
            Math.max(0, Math.min(1, ((nodeCnt[i] ? nodeSum[i]/nodeCnt[i] : vmin) - vmin) / range)));

        const pos = new Float32Array(tris.length * 3 * 3);
        const col = new Float32Array(tris.length * 3 * 3);
        let vi = 0;
        for (const tri of tris) {
            for (const nid of tri.nodes) {
                const [x, y, z] = nodePos[nid] ?? [0, 0, 0];
                pos[vi] = x; pos[vi+1] = y; pos[vi+2] = z;
                const [r, g, b] = jetColor(nodeT[nodeIdx[nid] ?? 0] ?? 0);
                col[vi] = r; col[vi+1] = g; col[vi+2] = b;
                vi += 3;
            }
        }

        const geom = new THREE.BufferGeometry();
        geom.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        geom.setAttribute('color',    new THREE.BufferAttribute(col, 3));
        const mesh = new THREE.Mesh(geom,
            new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide,
                                          transparent: true, opacity: 0.88,
                                          // Pull the colored result slightly toward the camera in depth so it
                                          // consistently wins over the coplanar reference plane (no z-fighting).
                                          polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 }));
        mesh.renderOrder = 2;
        this._slices[sliceId] = mesh;
        this._sliceGroup.add(mesh);
        return { vmin, vmax };
    }

    // Show velocity vectors on a slice.
    // vectors: [{x,y,vx,vy,vz,speed}] — 2D positions, 3D velocity
    show3DSliceVectors(vectors, plane, planeValue, sliceId = 'hz') {
        this._ensure3DGroups();
        const key = sliceId + '_vec';
        this._removeSlice(key);
        if (!vectors?.length) return;

        const maxSpd = Math.max(...vectors.map(v => v.speed), 1);
        const charLen = 5; // world units per arrow max
        const lines = [];
        const Z = 0.5;
        const cos140 = Math.cos(Math.PI * 140 / 180);
        const sin140 = Math.sin(Math.PI * 140 / 180);

        // OF→Three.js: (x,y,z)→(x,z,-y)
        // z-plane: v.x=OF_x, v.y=OF_y; y-plane: v.x=OF_x, v.y=OF_z (axes=[0,2])
        for (const v of vectors) {
            // 2D base position in the slice plane
            const px = v.x, py = v.y;

            // In-plane velocity components
            let dx, dy;
            if (plane === 'z') { dx = v.vx; dy = v.vy; }
            else               { dx = v.vx; dy = v.vz; }
            const mag = Math.hypot(dx, dy);
            if (mag < 0.01) continue;
            dx /= mag; dy /= mag;

            const len = Math.min(v.speed / maxSpd, 1.5) * charLen * 0.4;
            const hLen = len * 0.35;

            // Arrow in 2D, then map to 3D with small normal offset
            const ax0 = px - dx * len * 0.3, ay0 = py - dy * len * 0.3;
            const ax1 = px + dx * len * 0.7, ay1 = py + dy * len * 0.7;

            // push3: ax moves in OF_x direction, ay moves in OF_y (z-plane) or OF_z (y-plane)
            const push3 = (ax, ay) => {
                if (plane === 'z') lines.push(ax, planeValue + 0.3, -ay);  // (x, OF_z+off, -OF_y)
                else               lines.push(ax, ay, -(planeValue + 0.3)); // (x, OF_z, -OF_y-off)
            };
            push3(ax0, ay0); push3(ax1, ay1);
            push3(ax1, ay1);
            push3(ax1 + (dx*cos140 - dy*sin140)*hLen, ay1 + (dx*sin140 + dy*cos140)*hLen);
            push3(ax1, ay1);
            push3(ax1 + (dx*cos140 + dy*sin140)*hLen, ay1 + (-dx*sin140 + dy*cos140)*hLen);
        }

        if (!lines.length) return;
        const geom = new THREE.BufferGeometry();
        geom.setAttribute('position', new THREE.BufferAttribute(new Float32Array(lines), 3));
        const obj = new THREE.LineSegments(geom,
            new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.7 }));
        this._slices[key] = obj;
        this._sliceGroup.add(obj);
    }

    // Show 3D streamlines ("spaghetti"), colored by speed.
    // streamlines: [{points:[[x,y,z],...], speed:[s,...]}]
    show3DStreamlines(streamlines) {
        this._ensure3DGroups();
        this._clearStreamlines();
        if (!streamlines?.length) return;

        const allSpeeds = streamlines.flatMap(l => l.speed ?? []);
        const maxSpd = Math.max(...allSpeeds, 1);

        // LineMaterial needs the canvas resolution for screen-space line width
        const sz = this._renderer.getSize(new THREE.Vector2());
        const mat = new LineMaterial({
            vertexColors: true,
            linewidth: 2.5,       // screen-space pixels
            transparent: true,
            opacity: 0.82,
            resolution: new THREE.Vector2(sz.x, sz.y),
        });
        this._streamLineMat = mat; // keep ref for resize updates

        for (const line of streamlines) {
            const pts  = line.points ?? [];
            const spds = line.speed  ?? [];
            if (pts.length < 2) continue;

            // LineGeometry expects flat [x,y,z, x,y,z, ...] positions
            // and flat [r,g,b, r,g,b, ...] colors — one entry per vertex (not per segment)
            const positions = [];
            const colors    = [];
            for (let i = 0; i < pts.length; i++) {
                const [x, y, z] = pts[i];
                // OpenFOAM: x=wind, y=lateral, z=height → Three.js Y-up: x=wind, y=height, z=-lateral
                positions.push(x, z, -y);
                const t = (spds[i] ?? 0) / maxSpd;
                const [r, g, b] = jetColor(t);
                colors.push(r, g, b);
            }

            const geom = new LineGeometry();
            geom.setPositions(positions);
            geom.setColors(colors);

            this._streamGroup.add(new Line2(geom, mat));
        }

        // Ensure line widths update if window is resized after streamlines are drawn
        this._updateStreamlineResolution = () => {
            const s = this._renderer.getSize(new THREE.Vector2());
            mat.resolution.set(s.x, s.y);
        };
    }

    _ensure3DGroups() {
        if (!this._sliceGroup) {
            this._sliceGroup = new THREE.Group();
            this._scene.add(this._sliceGroup);
            this._slices = {};
        }
        if (!this._streamGroup) {
            this._streamGroup = new THREE.Group();
            this._scene.add(this._streamGroup);
        }
    }

    _removeSlice(id) {
        if (!this._slices?.[id]) return;
        const obj = this._slices[id];
        obj.geometry?.dispose();
        obj.material?.dispose();
        this._sliceGroup.remove(obj);
        delete this._slices[id];
    }

    // Only clear colored result meshes — preserve plain plane outlines
    clearSliceResults() {
        ['hz', 'vt', 'hz_vec', 'vt_vec'].forEach(id => this._removeSlice(id));
    }

    clearSlices() {
        if (!this._sliceGroup) return;
        this._sliceGroup.traverse(c => {
            if (c.isMesh || c.isLine) {
                c.geometry?.dispose();
                (Array.isArray(c.material) ? c.material : [c.material]).forEach(m => m?.dispose());
            }
        });
        this._sliceGroup.clear();
        this._slices = {};
        this._planeMeshes = {};
    }

    _clearStreamlines() {
        if (!this._streamGroup) return;
        this._streamGroup.traverse(c => {
            if (c.isLine || c.isLine2) { c.geometry?.dispose(); c.material?.dispose(); }
        });
        this._streamLineMat = null;
        this._updateStreamlineResolution = null;
        this._sliceStreamMats = {};
        this._sliceStreamGroups = {};
        this._streamGroup.clear();
    }

    // ── Slice streamlines (RK4 on cut plane, client-side) ─────────

    // Trace 2D streamlines using node-embedded velocities from extract_slice.
    // Returns {paths, maxSpd} in 2D slice coordinates.
    _traceSliceStreamlines(sliceData, nSeeds = 24) {
        const nodes = sliceData?.nodes;
        const tris  = sliceData?.triangles;
        if (!nodes?.length || !tris?.length || nodes[0].vx === undefined) return null;

        const nodePos = {}, nodeVx = {}, nodeVy = {};
        for (const n of nodes) {
            nodePos[n.id] = { x: n.x, y: n.y };
            nodeVx[n.id] = n.vx ?? 0;
            nodeVy[n.id] = n.vy ?? 0;
        }

        let xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
        const triList = [];
        for (const tri of tris) {
            const [n1, n2, n3] = tri.nodes;
            const p1 = nodePos[n1], p2 = nodePos[n2], p3 = nodePos[n3];
            if (!p1 || !p2 || !p3) continue;
            triList.push({
                x1: p1.x, y1: p1.y, vx1: nodeVx[n1], vy1: nodeVy[n1],
                x2: p2.x, y2: p2.y, vx2: nodeVx[n2], vy2: nodeVy[n2],
                x3: p3.x, y3: p3.y, vx3: nodeVx[n3], vy3: nodeVy[n3],
            });
            if (Math.min(p1.x, p2.x, p3.x) < xMin) xMin = Math.min(p1.x, p2.x, p3.x);
            if (Math.max(p1.x, p2.x, p3.x) > xMax) xMax = Math.max(p1.x, p2.x, p3.x);
            if (Math.min(p1.y, p2.y, p3.y) < yMin) yMin = Math.min(p1.y, p2.y, p3.y);
            if (Math.max(p1.y, p2.y, p3.y) > yMax) yMax = Math.max(p1.y, p2.y, p3.y);
        }
        if (triList.length < 4) return null;

        const span  = Math.max(xMax - xMin, yMax - yMin, 0.1);
        const gridN = 100;
        const cellW = (xMax - xMin) / gridN || 1;
        const cellH = (yMax - yMin) / gridN || 1;
        const grid  = new Map();
        for (const tri of triList) {
            const gx0 = Math.floor((Math.min(tri.x1, tri.x2, tri.x3) - xMin) / cellW);
            const gx1 = Math.floor((Math.max(tri.x1, tri.x2, tri.x3) - xMin) / cellW);
            const gy0 = Math.floor((Math.min(tri.y1, tri.y2, tri.y3) - yMin) / cellH);
            const gy1 = Math.floor((Math.max(tri.y1, tri.y2, tri.y3) - yMin) / cellH);
            for (let gi = gx0; gi <= gx1; gi++) {
                for (let gj = gy0; gj <= gy1; gj++) {
                    const key = gi * 10000 + gj;
                    if (!grid.has(key)) grid.set(key, []);
                    grid.get(key).push(tri);
                }
            }
        }

        const lookupV = (px, py) => {
            const gi = Math.floor((px - xMin) / cellW);
            const gj = Math.floor((py - yMin) / cellH);
            const bucket = grid.get(gi * 10000 + gj);
            if (!bucket) return null;
            for (const tri of bucket) {
                const dx = px - tri.x3, dy = py - tri.y3;
                const dx31 = tri.x1 - tri.x3, dy31 = tri.y1 - tri.y3;
                const dx32 = tri.x2 - tri.x3, dy32 = tri.y2 - tri.y3;
                const det  = dx31 * dy32 - dx32 * dy31;
                if (Math.abs(det) < 1e-14) continue;
                const u = (dy32 * dx - dx32 * dy) / det;
                const v = (dx31 * dy - dy31 * dx) / det;
                if (u >= -0.01 && v >= -0.01 && u + v <= 1.01) {
                    const w = 1 - u - v;
                    return { vx: u*tri.vx1 + v*tri.vx2 + w*tri.vx3,
                             vy: u*tri.vy1 + v*tri.vy2 + w*tri.vy3 };
                }
            }
            return null;
        };

        const normV = v => {
            if (!v) return null;
            const s = Math.sqrt(v.vx * v.vx + v.vy * v.vy);
            return s > 1e-8 ? { dx: v.vx / s, dy: v.vy / s, spd: s } : null;
        };
        const rk4Step = (px, py, sign, h) => {
            const k1 = normV(lookupV(px, py));
            if (!k1) return null;
            const k2 = normV(lookupV(px + sign*k1.dx*h*0.5, py + sign*k1.dy*h*0.5)) ?? k1;
            const k3 = normV(lookupV(px + sign*k2.dx*h*0.5, py + sign*k2.dy*h*0.5)) ?? k2;
            const k4 = normV(lookupV(px + sign*k3.dx*h,     py + sign*k3.dy*h    )) ?? k3;
            const dx = sign * h / 6 * (k1.dx + 2*k2.dx + 2*k3.dx + k4.dx);
            const dy = sign * h / 6 * (k1.dy + 2*k2.dy + 2*k3.dy + k4.dy);
            return { x: px+dx, y: py+dy, speed: (k1.spd + 2*k2.spd + 2*k3.spd + k4.spd) / 6 };
        };

        // Seeds: upstream edge + top/bottom edges
        const nLeft = Math.ceil(nSeeds * 0.7);
        const nEdge = nSeeds - nLeft;
        const seeds = [];
        for (let s = 0; s < nLeft; s++)
            seeds.push({ x: xMin + span * 0.01, y: yMin + (s + 0.5) / nLeft * (yMax - yMin) });
        for (let s = 0; s < nEdge; s++) {
            const f = (s + 0.5) / nEdge;
            seeds.push({ x: xMin + f * (xMax - xMin), y: yMax - span * 0.01 });
            seeds.push({ x: xMin + f * (xMax - xMin), y: yMin + span * 0.01 });
        }

        const baseH    = span * 0.005;
        const maxSteps = Math.min(Math.ceil(span * 4 / baseH), 10000);
        const oob      = (x, y) => x < xMin || x > xMax || y < yMin || y > yMax;
        const paths    = [];
        for (const seed of seeds) {
            const fwd = [{ x: seed.x, y: seed.y, speed: 0 }];
            let px = seed.x, py = seed.y;
            for (let i = 0; i < maxSteps; i++) {
                const n = rk4Step(px, py, 1, baseH);
                if (!n || oob(n.x, n.y)) break;
                px = n.x; py = n.y; fwd.push(n);
            }
            const bwd = [];
            px = seed.x; py = seed.y;
            for (let i = 0; i < maxSteps; i++) {
                const n = rk4Step(px, py, -1, baseH);
                if (!n || oob(n.x, n.y)) break;
                px = n.x; py = n.y; bwd.push(n);
            }
            const line = [...bwd.reverse(), ...fwd];
            if (line.length > 8) paths.push(line);
        }
        let maxSpd = 0.01;
        for (const sl of paths) for (const p of sl) if ((p.speed||0) > maxSpd) maxSpd = p.speed;
        return { paths, maxSpd };
    }

    // Render slice streamlines in 3D space, constrained to the given plane.
    // plane: 'z' (horizontal) | 'y' (vertical)
    showSliceStreamlines(sliceData, plane, planeValue, sliceId, nSeeds = 24) {
        this._ensure3DGroups();
        this._clearSliceStreamlines(sliceId);

        const traced = this._traceSliceStreamlines(sliceData, nSeeds);
        if (!traced?.paths?.length) return;
        const { paths, maxSpd } = traced;

        const sz  = this._renderer.getSize(new THREE.Vector2());
        const mat = new LineMaterial({
            vertexColors: true,
            linewidth: 2.0,
            transparent: true,
            opacity: 0.85,
            depthTest: true,
            resolution: new THREE.Vector2(sz.x, sz.y),
        });

        const grp = new THREE.Group();
        for (const sl of paths) {
            if (sl.length < 2) continue;
            const positions = [], colors = [];
            for (const { x, y, speed } of sl) {
                // OF→Three.js: (x,y,z)→(x,z,-y)
                // z-plane: (sl.x=OF_x, sl.y=OF_y) → Three.js (x, OF_z+off, -OF_y)
                // y-plane: (sl.x=OF_x, sl.y=OF_z) → Three.js (x, OF_z, -(OF_y+off))
                if (plane === 'z') positions.push(x, planeValue + 0.2, -y);
                else               positions.push(x, y, -(planeValue + 0.2));
                const [r, g, b] = jetColor((speed || 0) / maxSpd);
                colors.push(r, g, b);
            }
            const geom = new LineGeometry();
            geom.setPositions(positions);
            geom.setColors(colors);
            grp.add(new Line2(geom, mat));
        }

        this._sliceStreamMats   = this._sliceStreamMats   ?? {};
        this._sliceStreamGroups = this._sliceStreamGroups ?? {};
        this._sliceStreamMats[sliceId]   = mat;
        this._sliceStreamGroups[sliceId] = grp;
        this._streamGroup.add(grp);
    }

    _clearSliceStreamlines(sliceId) {
        const grp = this._sliceStreamGroups?.[sliceId];
        if (!grp) return;
        grp.traverse(c => { if (c.isLine2) { c.geometry?.dispose(); c.material?.dispose(); } });
        this._streamGroup?.remove(grp);
        delete this._sliceStreamGroups[sliceId];
        delete this._sliceStreamMats?.[sliceId];
    }

    _clearAllSliceStreamlines() {
        for (const id of Object.keys(this._sliceStreamGroups ?? {}))
            this._clearSliceStreamlines(id);
    }

    clear3DResult() {
        this.clearSlices();
        this._clearStreamlines();
        this.clearSurfaceStreamlines();
    }

    // Fit the orthographic camera to a world-space region centred at (cx,cy).
    // halfSize: half the visible height in world units.
    fitOrthoView(cx, cy, halfSize) {
        if (!this._orthoCamera) return;
        const aspect = this.canvas.clientWidth / Math.max(this.canvas.clientHeight, 1);
        this._orthoCamera.zoom   = 1;
        this._orthoCamera.left   = -halfSize * aspect;
        this._orthoCamera.right  =  halfSize * aspect;
        this._orthoCamera.top    =  halfSize;
        this._orthoCamera.bottom = -halfSize;
        this._orthoCamera.position.set(cx, cy, 100);
        this._orthoCamera.updateProjectionMatrix();
        this._orthoSize = halfSize;
        if (this._controls) {
            this._controls.target.set(cx, cy, 0);
            this._controls.update();
        }
    }

    // ── Sync camera to SVG view ───────────────────────────────────
    // Makes the orthographic view match the SVG drawing zoom/pan exactly.
    // Call this after showCFDResult / showMeshOnly.

    syncViewWithSVG({ cx, cy, scale, svgW, svgH }) {
        // Guard: SVG returns 0 dimensions when hidden (display:none)
        if (!this._orthoCamera || svgH === 0 || svgW === 0 || scale === 0) return;
        const halfH = svgH / (2 * scale);
        const halfW = svgW / (2 * scale);

        // Reset accumulated zoom so OrbitControls doesn't override our frustum
        this._orthoCamera.zoom   = 1;
        this._orthoCamera.left   = -halfW;
        this._orthoCamera.right  =  halfW;
        this._orthoCamera.top    =  halfH;
        this._orthoCamera.bottom = -halfH;
        this._orthoCamera.position.set(cx, cy, 100);
        this._orthoCamera.updateProjectionMatrix();
        this._orthoSize = halfH;  // used by _resize() to preserve aspect ratio

        if (this._controls) {
            this._controls.target.set(cx, cy, 0);
            this._controls.update();
        }
    }

    // ── Velocity vectors (quiver plot) ───────────────────────────

    showVectors(solveResult) {
        this.clearVectors();
        const field = solveResult?.field;
        if (!field?.velocity || !field?.nodes || !field?.triangles) return;

        const { nodeXY, idToIdx } = _normaliseNodes(field.nodes);
        const triIndices          = _normaliseTris(field.triangles, idToIdx);
        const vel                 = field.velocity; // [[Ux,Uy], ...] per node

        // Characteristic length: rough bounding box of the section nodes
        // (the first ~100 nodes in OpenFOAM output are section boundary nodes)
        const sectionXY = nodeXY.slice(0, Math.min(100, nodeXY.length));
        const sxs = sectionXY.map(p => p[0]), sys = sectionXY.map(p => p[1]);
        const charLen = Math.max(
            Math.max(...sxs) - Math.min(...sxs),
            Math.max(...sys) - Math.min(...sys),
            0.5
        );
        const cx0 = (Math.min(...sxs) + Math.max(...sxs)) / 2;
        const cy0 = (Math.min(...sys) + Math.max(...sys)) / 2;
        const nearField = charLen * 3; // only show vectors within 3× char length

        // Target ~300 arrows; compute subsampling step
        const step = Math.max(1, Math.floor(triIndices.length / 300));

        // Reference speed: use 75th percentile of |U| for scaling
        const speeds = vel.map(v => Math.hypot(v?.[0] ?? 0, v?.[1] ?? 0));
        const refSpd = speeds.sort((a, b) => a - b)[Math.floor(speeds.length * 0.75)] || 20;
        const arrowLen = charLen * 0.06; // base arrow length

        const lines = [];
        const Z = 0.5; // slightly above colormap

        const cos140 = Math.cos(Math.PI * 140 / 180); // ≈ -0.766
        const sin140 = Math.sin(Math.PI * 140 / 180); // ≈  0.643

        for (let i = 0; i < triIndices.length; i += step) {
            const [a, b, c] = triIndices[i];
            if (a == null || b == null || c == null) continue;

            // Centroid
            const px = (nodeXY[a][0] + nodeXY[b][0] + nodeXY[c][0]) / 3;
            const py = (nodeXY[a][1] + nodeXY[b][1] + nodeXY[c][1]) / 3;

            // Skip far field
            if (Math.hypot(px - cx0, py - cy0) > nearField) continue;

            // Average velocity at centroid
            const va = vel[a] || [0, 0];
            const vb = vel[b] || [0, 0];
            const vc = vel[c] || [0, 0];
            const ux = (va[0] + vb[0] + vc[0]) / 3;
            const uy = (va[1] + vb[1] + vc[1]) / 3;
            const mag = Math.hypot(ux, uy);
            if (mag < 0.01) continue;

            const dx = ux / mag, dy = uy / mag;

            // Scale length by magnitude, cap at 1.5×base
            const len = Math.min(mag / refSpd, 1.5) * arrowLen;
            const headLen = len * 0.35;

            // Tail → tip (shaft)
            const tailX = px - dx * len * 0.4, tailY = py - dy * len * 0.4;
            const tipX  = px + dx * len * 0.6, tipY  = py + dy * len * 0.6;

            lines.push(tailX, tailY, Z, tipX,  tipY,  Z);

            // Arrowhead: two lines from tip at ±140°
            lines.push(
                tipX, tipY, Z,
                tipX + (dx * cos140 - dy * sin140) * headLen,
                tipY + (dx * sin140 + dy * cos140) * headLen, Z
            );
            lines.push(
                tipX, tipY, Z,
                tipX + (dx * cos140 + dy * sin140) * headLen,
                tipY + (-dx * sin140 + dy * cos140) * headLen, Z
            );
        }

        if (!lines.length) return;

        const geom = new THREE.BufferGeometry();
        geom.setAttribute('position', new THREE.BufferAttribute(new Float32Array(lines), 3));
        this._vectorGroup = new THREE.LineSegments(geom,
            new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.65 }));
        this._cfdGroup.add(this._vectorGroup);
    }

    clearVectors() {
        if (this._vectorGroup) {
            this._vectorGroup.geometry.dispose();
            this._vectorGroup.material.dispose();
            this._cfdGroup.remove(this._vectorGroup);
            this._vectorGroup = null;
        }
    }

    // ── 2D Streamlines (RK4, client-side) ────────────────────────

    clear2DStreamlines() {
        if (this._streamGroup2D) {
            this._streamGroup2D.traverse(c => { if (c.isLineSegments) c.geometry?.dispose(); });
            this._streamGroup2D.clear();
            this._streamGroup2D.visible = false;
        }
    }

    // Dark section fill used in isolated (no-background) mode
    showSectionFill(polygon) {
        if (!polygon?.length) return;
        const shape = new THREE.Shape(polygon.map(([x, y]) => new THREE.Vector2(x, y)));
        const geo   = new THREE.ShapeGeometry(shape);
        const mesh  = new THREE.Mesh(geo,
            new THREE.MeshBasicMaterial({ color: 0x0d1828, side: THREE.DoubleSide }));
        mesh.position.z = 0.01;
        this._cfdGroup.add(mesh);
    }

    // Pure RK4 computation — no Three.js. Returns { paths, maxSpd } or null.
    traceStreamlines2D(solveResult, polygon, nSeeds = 28) {
        const field = solveResult?.field;
        if (!field?.velocity || !field?.triangles || !field?.nodes) return null;

        const velocity  = field.velocity;
        const triangles = field.triangles;
        const nodePos   = {};
        for (const n of field.nodes) nodePos[n.id] = { x: n.x, y: n.y };

        const nodeVx = {}, nodeVy = {}, nodeW = {};
        for (const tri of triangles) {
            const cid = tri.cell_id;
            if (cid === undefined || cid < 0 || cid >= velocity.length) continue;
            const [n1, n2, n3] = tri.nodes;
            const p1 = nodePos[n1], p2 = nodePos[n2], p3 = nodePos[n3];
            if (!p1 || !p2 || !p3) continue;
            const area = Math.abs((p2.x-p1.x)*(p3.y-p1.y) - (p3.x-p1.x)*(p2.y-p1.y)) * 0.5;
            const [vx, vy] = velocity[cid];
            for (const nid of [n1, n2, n3]) {
                nodeVx[nid] = (nodeVx[nid] ?? 0) + vx * area;
                nodeVy[nid] = (nodeVy[nid] ?? 0) + vy * area;
                nodeW [nid] = (nodeW [nid] ?? 0) + area;
            }
        }
        for (const nid of Object.keys(nodeVx)) {
            const w = nodeW[nid] || 1;
            nodeVx[nid] /= w;
            nodeVy[nid] /= w;
        }

        const tris = [];
        for (const tri of triangles) {
            const [n1, n2, n3] = tri.nodes;
            const p1 = nodePos[n1], p2 = nodePos[n2], p3 = nodePos[n3];
            if (!p1 || !p2 || !p3) continue;
            if (nodeVx[n1] === undefined || nodeVx[n2] === undefined || nodeVx[n3] === undefined) continue;
            tris.push({
                x1: p1.x, y1: p1.y, vx1: nodeVx[n1], vy1: nodeVy[n1],
                x2: p2.x, y2: p2.y, vx2: nodeVx[n2], vy2: nodeVy[n2],
                x3: p3.x, y3: p3.y, vx3: nodeVx[n3], vy3: nodeVy[n3],
            });
        }
        if (tris.length < 10) return null;

        let xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
        for (const t of tris) {
            if (Math.min(t.x1, t.x2, t.x3) < xMin) xMin = Math.min(t.x1, t.x2, t.x3);
            if (Math.max(t.x1, t.x2, t.x3) > xMax) xMax = Math.max(t.x1, t.x2, t.x3);
            if (Math.min(t.y1, t.y2, t.y3) < yMin) yMin = Math.min(t.y1, t.y2, t.y3);
            if (Math.max(t.y1, t.y2, t.y3) > yMax) yMax = Math.max(t.y1, t.y2, t.y3);
        }
        const span  = Math.max(xMax - xMin, yMax - yMin, 0.1);
        const gridN = 100;
        const cellW = (xMax - xMin) / gridN || 1;
        const cellH = (yMax - yMin) / gridN || 1;
        const grid  = new Map();
        for (const tri of tris) {
            const gx0 = Math.floor((Math.min(tri.x1, tri.x2, tri.x3) - xMin) / cellW);
            const gx1 = Math.floor((Math.max(tri.x1, tri.x2, tri.x3) - xMin) / cellW);
            const gy0 = Math.floor((Math.min(tri.y1, tri.y2, tri.y3) - yMin) / cellH);
            const gy1 = Math.floor((Math.max(tri.y1, tri.y2, tri.y3) - yMin) / cellH);
            for (let gi = gx0; gi <= gx1; gi++) {
                for (let gj = gy0; gj <= gy1; gj++) {
                    const key = gi * 10000 + gj;
                    if (!grid.has(key)) grid.set(key, []);
                    grid.get(key).push(tri);
                }
            }
        }

        const lookupV = (px, py) => {
            const gi = Math.floor((px - xMin) / cellW);
            const gj = Math.floor((py - yMin) / cellH);
            const bucket = grid.get(gi * 10000 + gj);
            if (!bucket) return null;
            for (const tri of bucket) {
                const dx = px - tri.x3, dy = py - tri.y3;
                const dx31 = tri.x1 - tri.x3, dy31 = tri.y1 - tri.y3;
                const dx32 = tri.x2 - tri.x3, dy32 = tri.y2 - tri.y3;
                const det = dx31 * dy32 - dx32 * dy31;
                if (Math.abs(det) < 1e-14) continue;
                const u = (dy32 * dx - dx32 * dy) / det;
                const v = (dx31 * dy - dy31 * dx) / det;
                if (u >= -0.01 && v >= -0.01 && u + v <= 1.01) {
                    const w = 1 - u - v;
                    return {
                        vx: u * tri.vx1 + v * tri.vx2 + w * tri.vx3,
                        vy: u * tri.vy1 + v * tri.vy2 + w * tri.vy3,
                    };
                }
            }
            return null;
        };

        const inBody = (px, py) => {
            if (!polygon || polygon.length < 3) return false;
            let inside = false;
            for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
                const [xi, yi] = polygon[i], [xj, yj] = polygon[j];
                if (((yi > py) !== (yj > py)) && (px < (xj - xi) * (py - yi) / (yj - yi) + xi))
                    inside = !inside;
            }
            return inside;
        };

        const normV = v => {
            if (!v) return null;
            const s = Math.sqrt(v.vx * v.vx + v.vy * v.vy);
            return s > 1e-8 ? { dx: v.vx / s, dy: v.vy / s, spd: s } : null;
        };
        const rk4Step = (px, py, sign, h) => {
            const k1 = normV(lookupV(px, py));
            if (!k1) return null;
            const k2 = normV(lookupV(px + sign*k1.dx*h*0.5, py + sign*k1.dy*h*0.5)) ?? k1;
            const k3 = normV(lookupV(px + sign*k2.dx*h*0.5, py + sign*k2.dy*h*0.5)) ?? k2;
            const k4 = normV(lookupV(px + sign*k3.dx*h,     py + sign*k3.dy*h    )) ?? k3;
            const dx  = sign * h / 6 * (k1.dx + 2*k2.dx + 2*k3.dx + k4.dx);
            const dy  = sign * h / 6 * (k1.dy + 2*k2.dy + 2*k3.dy + k4.dy);
            const spd = (k1.spd + 2*k2.spd + 2*k3.spd + k4.spd) / 6;
            return { x: px + dx, y: py + dy, speed: spd };
        };

        const poly = polygon;
        const secXs   = poly ? poly.map(p => p[0]) : [0];
        const secYs   = poly ? poly.map(p => p[1]) : [0];
        const secMinX = Math.min(...secXs), secMaxX = Math.max(...secXs);
        const secMinY = Math.min(...secYs), secMaxY = Math.max(...secYs);
        const secW    = secMaxX - secMinX || span * 0.3;
        const secH    = secMaxY - secMinY || span * 0.3;
        const seeds   = [];
        const nUp     = Math.ceil(nSeeds * 0.5);
        const nWake   = Math.ceil(nSeeds * 0.25);
        const nNear   = nSeeds - nUp - nWake;
        const seedX   = secMinX - secH * 2.5;
        for (let s = 0; s < nUp; s++) {
            const f = s / Math.max(nUp - 1, 1);
            seeds.push({ x: seedX, y: (secMinY - secH * 2.5) + f * (secH * 5 + secMaxY - secMinY) });
        }
        for (let s = 0; s < nWake; s++) {
            const f = (s + 0.5) / nWake;
            const wy = secMinY - secH * 0.5 + f * (secH + secMaxY - secMinY);
            seeds.push({ x: secMaxX + secW * 0.3, y: wy });
            seeds.push({ x: secMaxX + secW * 1.0, y: wy });
        }
        const margin = Math.max(secW, secH) * 0.15;
        for (let s = 0; s < nNear; s++) {
            const f = s / Math.max(nNear - 1, 1);
            seeds.push({ x: secMinX - margin,                        y: secMinY + f * (secMaxY - secMinY) });
            seeds.push({ x: secMaxX + margin,                        y: secMinY + f * (secMaxY - secMinY) });
            seeds.push({ x: secMinX + f * (secMaxX - secMinX), y: secMaxY + margin });
            seeds.push({ x: secMinX + f * (secMaxX - secMinX), y: secMinY - margin });
        }

        const buildingSpan = Math.max(secW, secH, 0.1);
        const baseH    = buildingSpan * 0.006;
        const maxSteps = Math.min(Math.ceil(span * 3 / baseH), 12000);

        const outOfBounds = (x, y) => x < xMin || x > xMax || y < yMin || y > yMax;
        const paths = [];
        for (const seed of seeds) {
            if (inBody(seed.x, seed.y)) continue;
            const fwd = [{ x: seed.x, y: seed.y, speed: 0 }];
            let px = seed.x, py = seed.y;
            for (let step = 0; step < maxSteps; step++) {
                const next = rk4Step(px, py, 1, baseH);
                if (!next || outOfBounds(next.x, next.y)) break;
                if (inBody(next.x, next.y) || inBody((px+next.x)/2, (py+next.y)/2)) break;
                px = next.x; py = next.y;
                fwd.push(next);
            }
            const bwd = [];
            px = seed.x; py = seed.y;
            for (let step = 0; step < maxSteps; step++) {
                const next = rk4Step(px, py, -1, baseH);
                if (!next || outOfBounds(next.x, next.y)) break;
                if (inBody(next.x, next.y) || inBody((px+next.x)/2, (py+next.y)/2)) break;
                px = next.x; py = next.y;
                bwd.push(next);
            }
            const line = [...bwd.reverse(), ...fwd];
            if (line.length > 8) paths.push(line);
        }

        let maxSpd = 0.01;
        for (const sl of paths) for (const p of sl) if ((p.speed || 0) > maxSpd) maxSpd = p.speed;

        return { paths, maxSpd };
    }

    // Rebuild Line2 children from pre-traced paths.
    _buildStreamlinesGroup(traced) {
        const grp = new THREE.Group();
        if (!traced?.paths?.length) return { grp, maxSpd: 0 };
        const { paths, maxSpd } = traced;
        const mat = new THREE.LineBasicMaterial({ vertexColors: true, depthTest: false, transparent: true, opacity: 0.9 });
        for (const sl of paths) {
            if (sl.length < 2) continue;
            const positions = [], colors = [];
            for (let i = 0; i < sl.length - 1; i++) {
                const a = sl[i], b = sl[i + 1];
                positions.push(a.x, a.y, 0.04, b.x, b.y, 0.04);
                const t = Math.max(0, Math.min(1, (b.speed || 0) / maxSpd));
                const [r, g, bl] = jetColor(t);
                colors.push(r, g, bl, r, g, bl);
            }
            const geo = new THREE.BufferGeometry();
            geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
            geo.setAttribute('color',    new THREE.Float32BufferAttribute(colors,    3));
            grp.add(new THREE.LineSegments(geo, mat));
        }
        return { grp, maxSpd };
    }

    _ensureStreamGroup() {
        if (!this._streamGroup2D) {
            this._streamGroup2D = new THREE.Group();
            this._cfdGroup.add(this._streamGroup2D);
        }
        return this._streamGroup2D;
    }

    // Single-frame display (non-animation).
    show2DStreamlines(solveResult, polygon, nSeeds = 28) {
        const traced = this.traceStreamlines2D(solveResult, polygon, nSeeds);
        const outer = this._ensureStreamGroup();
        outer.traverse(c => { if (c.isLineSegments) c.geometry?.dispose(); });
        outer.clear();
        this._streamFrameGroups = null;
        this._renderer.resetState();
        if (!traced?.paths?.length) { outer.visible = false; return null; }
        const { grp, maxSpd } = this._buildStreamlinesGroup(traced);
        outer.add(grp);
        outer.visible = true;
        return maxSpd;
    }

    // Pre-build Three.js geometry for ALL animation frames at once.
    // During animation only visibility is toggled — no geometry creation/disposal in the render loop.
    preloadStreamlines2D(tracedArray) {
        const outer = this._ensureStreamGroup();
        outer.traverse(c => { if (c.isLineSegments) c.geometry?.dispose(); });
        outer.clear();
        this._streamFrameGroups = [];
        this._streamFrameMaxSpds = [];
        for (const traced of tracedArray) {
            const { grp, maxSpd } = this._buildStreamlinesGroup(traced);
            grp.visible = false;
            outer.add(grp);
            this._streamFrameGroups.push(grp);
            this._streamFrameMaxSpds.push(maxSpd);
        }
        outer.visible = true;
        this._streamCurrentFrame = -1;
        // Force Three.js to re-setup vertex attributes on next render.
        // geometry.dispose() frees WebGL VAO IDs which may be recycled, potentially
        // corrupting the binding state of sibling meshes. resetState() clears the
        // cached binding state so all objects get fresh VAO setup on the next frame.
        this._renderer.resetState();
    }

    // Toggle to a pre-built frame — no scene graph changes, only visible flag.
    applyAnimStreamlines(idx) {
        if (!this._streamFrameGroups) return null;
        if (this._streamCurrentFrame >= 0 && this._streamCurrentFrame < this._streamFrameGroups.length)
            this._streamFrameGroups[this._streamCurrentFrame].visible = false;
        if (idx >= 0 && idx < this._streamFrameGroups.length) {
            this._streamFrameGroups[idx].visible = true;
            this._streamCurrentFrame = idx;
            return this._streamFrameMaxSpds[idx] ?? null;
        }
        return null;
    }

    // ── Polygon overlay ───────────────────────────────────────────
    // Draws the cross-section outline over the CFD result

    showPolygon(polygon) {
        // Remove previous polygon line
        if (this._polygonLine) {
            this._polygonLine.geometry.dispose();
            this._polygonLine.material.dispose();
            this._cfdGroup.remove(this._polygonLine);
            this._polygonLine = null;
        }
        if (!polygon || polygon.length < 2) return;

        // Closed line loop slightly above z=0
        const pts = [...polygon, polygon[0]].map(([x, y]) => new THREE.Vector3(x, y, 0.5));
        const geom = new THREE.BufferGeometry().setFromPoints(pts);
        const mat  = new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.85 });
        this._polygonLine = new THREE.Line(geom, mat);
        this._cfdGroup.add(this._polygonLine);
    }

    // ── 3D wind direction arrow ───────────────────────────────────
    // box: THREE.Box3 of the building mesh (after rotateX, Y=height, X=wind dir)
    // Wind convention: from -X → arrow points +X, placed upstream of building.

    // angleDeg: wind direction in degrees (0 = from -X, 90 = from -Z, same convention as 2D)
    showWindArrow3D(box, angleDeg = 0) {
        if (this._windArrow3D) {
            this._modelGroup.remove(this._windArrow3D);
            this._windArrow3D = null;
        }

        const size   = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        const maxDim = Math.max(size.x, size.y, size.z);

        const arrowLen = maxDim * 0.55;
        const headLen  = arrowLen * 0.22;
        const headW    = headLen  * 0.55;

        // Wind direction in Three.js horizontal plane (Y = up after rotateX):
        // Python uses flow_x=cos(rad), flow_y=sin(rad) in the XY horizontal of OpenFOAM.
        // After rotateX(-π/2) the original polygon Y maps to Three.js -Z.
        // → Three.js wind dir = (cos(rad), 0, -sin(rad))
        const rad = angleDeg * Math.PI / 180;
        const dir = new THREE.Vector3(Math.cos(rad), 0, -Math.sin(rad));

        // Place origin upstream: center shifted against wind direction
        const upstream = maxDim * 1.1;
        const origin = new THREE.Vector3(
            center.x - dir.x * upstream,
            box.min.y + size.y * 0.35,
            center.z - dir.z * upstream,
        );

        const arrow = new THREE.ArrowHelper(dir, origin, arrowLen, 0x3d9eff, headLen, headW);
        this._modelGroup.add(arrow);
        this._windArrow3D = arrow;
    }

    // ── cleanup ───────────────────────────────────────────────────

    _clearModel() {
        this._modelGroup.clear();
        this._windArrow3D = null; // reference cleared; geometry disposed by .clear()
    }

    _clearCFD() {
        this._streamGroup2D      = null;
        this._streamFrameGroups  = null;
        this._streamFrameMaxSpds = null;
        this._streamCurrentFrame = -1;
        this._cfdAnimMesh        = null;
        this._cfdAnimMeta        = null;

        const disposedMats = new Set();
        this._cfdGroup.traverse(c => {
            if (c.isMesh || c.isLine || c.isLine2) {
                c.geometry?.dispose();
                const mats = Array.isArray(c.material) ? c.material : (c.material ? [c.material] : []);
                for (const m of mats) {
                    if (!disposedMats.has(m)) { m.dispose(); disposedMats.add(m); }
                }
            }
        });
        this._cfdGroup.clear();
    }

    clearSurfaceStreamlines() {
        if (this._surfaceLinesObj) {
            this._cfdGroup.remove(this._surfaceLinesObj);
            this._surfaceLinesObj.geometry.dispose();
            this._surfaceLinesObj.material.dispose();
            this._surfaceLinesObj = null;
        }
    }

    // lines: array of polylines [[x,y,z], ...]  in OpenFOAM Z-up coordinates
    // ofCenter: {x,y,z} offset in OF space to subtract before conversion (GLB centering)
    showSurfaceStreamlines(lines, ofCenter = null) {
        this.clearSurfaceStreamlines();
        if (!lines?.length) return;

        const cx = ofCenter?.x ?? 0;
        const cy = ofCenter?.y ?? 0;
        const cz = ofCenter?.z ?? 0;

        // Build LineSegments: each consecutive pair in each polyline becomes a segment
        // OF→Three.js: (x,y,z)→(x,z,-y)  then subtract center
        const positions = [];
        for (const line of lines) {
            for (let i = 0; i < line.length - 1; i++) {
                const [x0, y0, z0] = line[i];
                const [x1, y1, z1] = line[i + 1];
                positions.push(x0 - cx, z0 - cz, -(y0 - cy),
                               x1 - cx, z1 - cz, -(y1 - cy));
            }
        }
        if (!positions.length) return;

        const geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(positions), 3));
        const mat = new THREE.LineBasicMaterial({
            color: 0xffffff,
            transparent: true,
            opacity: 0.65,
        });
        this._surfaceLinesObj = new THREE.LineSegments(geo, mat);
        this._surfaceLinesObj.renderOrder = 4;
        this._cfdGroup.add(this._surfaceLinesObj);
    }

    clear() {
        this._clearModel();
        this._clearCFD();
    }

    dispose() {
        cancelAnimationFrame(this._rafId);
        this._resizeObs.disconnect();
        this._controls.dispose();
        this._renderer.dispose();
    }
}

// ── Jet colormap ──────────────────────────────────────────────────

function jetColor(t) {
    t = Math.max(0, Math.min(1, t));
    const r = Math.max(0, Math.min(1, 1.5 - Math.abs(4 * t - 3)));
    const g = Math.max(0, Math.min(1, 1.5 - Math.abs(4 * t - 2)));
    const b = Math.max(0, Math.min(1, 1.5 - Math.abs(4 * t - 1)));
    return [r, g, b];
}

// ── Coolwarm diverging colormap (blue → white → red) ──────────────
// For signed fields (vorticity): t=0.5 → white, so a symmetric value range
// puts zero at the neutral centre and the two vortex rotation senses read as
// clean blue vs red — the CFD-standard look for the Kármán street.
function coolwarmColor(t) {
    t = Math.max(0, Math.min(1, t));
    const blue = [0.23, 0.30, 0.75], white = [0.95, 0.95, 0.95], red = [0.71, 0.02, 0.15];
    const mix = (a, b, s) => [a[0] + (b[0] - a[0]) * s, a[1] + (b[1] - a[1]) * s, a[2] + (b[2] - a[2]) * s];
    return t < 0.5 ? mix(blue, white, t / 0.5) : mix(white, red, (t - 0.5) / 0.5);
}

// Colormap per field: vorticity is signed → diverging; everything else → jet.
function cmapFor(fieldName) {
    return fieldName === 'vorticity' ? coolwarmColor : jetColor;
}

// ── Data normalisation helpers ────────────────────────────────────

// Returns { nodeXY: [[x,y],...], idToIdx: Map<id→arrayIndex> }
// Handles: [{id,x,y}], [{x,y}], [[x,y]]
function _normaliseNodes(rawNodes) {
    const nodeXY  = [];
    const idToIdx = new Map();
    for (let i = 0; i < rawNodes.length; i++) {
        const n = rawNodes[i];
        if (Array.isArray(n)) {
            nodeXY.push([n[0], n[1]]);
            idToIdx.set(i, i);
        } else if (n.id !== undefined) {
            nodeXY.push([n.x, n.y]);
            idToIdx.set(n.id, i);
        } else {
            nodeXY.push([n.x, n.y]);
            idToIdx.set(i, i);
        }
    }
    return { nodeXY, idToIdx };
}

// Returns [[i,j,k],...] as array-index triplets.
// If a node ID is not in idToIdx, returns -1 so the triangle gets filtered later.
// Handles: [{nodes:[id,id,id],...}], [[i,j,k]]
function _normaliseTris(rawTris, idToIdx) {
    return rawTris.map(t => {
        const ids = Array.isArray(t) ? t : t.nodes;
        return ids.map(id => idToIdx.has(id) ? idToIdx.get(id) : -1);
    });
}
