// app.js — CFD Wind Analysis standalone app

import * as THREE from 'three';
import { Draw2D } from './draw2d.js';
import { Viewer3D } from './viewer3d.js';
import { CFD_TEST_CASES } from './cfd-testcases.js';

// API base: localhost:8000 in dev (when served from a different port), same-origin in prod
const API_BASE = (location.hostname === 'localhost' || location.hostname === '127.0.0.1') && location.port !== '8000'
    ? 'http://localhost:8000' : '';

const api = path => API_BASE + path;

// ── Group test cases ─────────────────────────────────────────────

const CASES_2D = CFD_TEST_CASES.filter(tc => tc.mode !== '3d');
const CASES_3D = CFD_TEST_CASES.filter(tc => tc.mode === '3d');

// ── App ───────────────────────────────────────────────────────────

class CFDApp {
    constructor() {
        this._tab      = '2d';
        this._viewMode = 'draw';
        this._polygon  = null;

        // Animation state
        this._animTimeSteps = [];
        this._animIdx       = 0;
        this._animPlaying   = false;
        this._animTimer     = null;
        this._animCaseDir   = null;
        this._animFps       = 4;
        this._glbUrl  = null;
        this._glbScale = 1;
        this._glbBounds = null;
        this._meshData  = null;
        this._solveResult = null;
        this._solving = false;
        this._logLines = [];

        this._draw   = new Draw2D(document.getElementById('svg-canvas'));
        this._viewer = new Viewer3D(document.getElementById('gl-canvas'));

        this._draw.onChange = (pts, closed) => {
            this._polygon = closed ? pts : null;
            this._updateRunBtn();
        };

        this._renderExampleList();
        this._bindControls();
        this._setTab('2d');
        this._setView('draw');
    }

    // ── view mode ──────────────────────────────────────────────────

    _setView(mode) {
        this._viewMode = mode;
        const ca = document.getElementById('canvas-area');
        ca.classList.remove('view-draw', 'view-result');
        ca.classList.add('view-' + mode);

        document.querySelectorAll('.vbtn').forEach(b =>
            b.classList.toggle('active', b.dataset.view === mode));
        // ResizeObserver in viewer3d.js handles _resize() automatically
        // when the GL canvas becomes visible — no explicit call needed here.
    }

    _enableResultBtn() {
        const btn = document.getElementById('vbtn-result');
        if (btn) btn.disabled = false;
    }

    // Clears result state and switches back to draw mode.
    // Called when loading a new example or clearing the canvas.
    _resetResult() {
        this._solveResult = null;
        this._meshData = null;
        this._viewer.clear();
        this._viewer.clearVectors();
        this._viewer.clear3DResult?.();
        this._3dCaseDir = null;
        this._lastSlice = null;
        document.getElementById('show-vectors').checked = false;
        document.getElementById('show-streamlines-2d').checked = false;
        document.getElementById('sl2d-opts').style.display = 'none';
        document.getElementById('result-controls-3d').style.display = 'none';
        document.getElementById('forces-section').style.display = 'none';
        document.getElementById('cp-chart-wrap').style.display = 'none';
        document.getElementById('statusbar-stats').style.display = 'none';
        document.getElementById('show-streamlines-3d').checked = false;
        this._animStop?.();
        this._animTimeSteps = [];
        document.getElementById('anim-bar').classList.add('hidden');
        document.getElementById('btn-clear-2d').style.display = 'none';
        document.getElementById('btn-clear-3d').style.display = 'none';
        this._setView('draw');
        const btn = document.getElementById('vbtn-result');
        if (btn) btn.disabled = true;
    }

    _showClearBtn() {
        const id = this._tab === '3d' ? 'btn-clear-3d' : 'btn-clear-2d';
        document.getElementById(id).style.display = 'block';
    }

    // ── tabs ───────────────────────────────────────────────────────

    _setTab(tab) {
        this._tab = tab;
        const ca  = document.getElementById('canvas-area');
        const log = document.getElementById('log-panel');
        const res = document.getElementById('result-panel');

        if (tab === '3d') {
            ca.classList.add('tab-3d');
            document.getElementById('view-toggle').style.visibility = 'hidden';
        } else {
            ca.classList.remove('tab-3d');
            document.getElementById('view-toggle').style.visibility = 'visible';
            this._setView(this._viewMode);
        }

        log.style.display = 'none';
        res.style.display = 'none';

        document.querySelectorAll('.tab-btn').forEach(b =>
            b.classList.toggle('active', b.dataset.tab === tab));

        document.getElementById('sidebar-2d').style.display = tab === '2d' ? 'flex' : 'none';
        document.getElementById('sidebar-3d').style.display = tab === '3d' ? 'flex' : 'none';
        document.getElementById('params-2d').style.display  = tab !== '3d' ? 'block' : 'none';
        document.getElementById('params-3d').style.display  = tab === '3d' ? 'block' : 'none';

        if (tab === '3d') requestAnimationFrame(() => this._viewer._resize());
        this._updateRunBtn();
    }

    // ── example library ───────────────────────────────────────────

    _renderExampleList() {
        const list2d = document.getElementById('example-list-2d');
        const list3d = document.getElementById('example-list-3d');

        list2d.innerHTML = CASES_2D.map((tc, i) => `
            <div class="example-item" data-idx="${CFD_TEST_CASES.indexOf(tc)}" title="${tc.desc}">
                <div class="example-name">${tc.name}</div>
                <div class="example-meta">${tc.windSpeed} m/s · cD ${tc.expected.cD}</div>
            </div>`).join('');

        list3d.innerHTML = CASES_3D.map((tc, i) => `
            <div class="example-item" data-idx="${CFD_TEST_CASES.indexOf(tc)}" title="${tc.desc}">
                <div class="example-name">${tc.name}</div>
                <div class="example-meta">${tc.height}m · ${tc.windSpeed} m/s</div>
            </div>`).join('');

        list2d.querySelectorAll('.example-item').forEach(el => {
            el.addEventListener('click', () => this._loadCase(+el.dataset.idx));
        });
        list3d.querySelectorAll('.example-item').forEach(el => {
            el.addEventListener('click', () => this._loadCase3D(+el.dataset.idx));
        });
    }

    _loadCase(idx) {
        const tc = CFD_TEST_CASES[idx];
        if (!tc || tc.mode === '3d') return;
        this._draw.setPolygon(tc.polygon);
        document.getElementById('wind-speed').value = tc.windSpeed;
        document.getElementById('wind-angle').value = 0;
        document.getElementById('mesh-density').value = 50;
        this._setTab('2d');
        this._resetResult();
        this._drawWindIndicator(0, tc.windSpeed);
        this._setStatus(`Geladen: ${tc.name} — ${tc.desc}`);
    }

    _loadCase3D(idx) {
        const tc = CFD_TEST_CASES[idx];
        if (!tc || tc.mode !== '3d') return;
        const maxH = tc.buildings ? Math.max(...tc.buildings.map(b => b.height)) : tc.height;
        document.getElementById('wind-speed-3d').value = tc.windSpeed;
        document.getElementById('building-height').value = maxH;
        document.getElementById('roughness').value = tc.z0 || 0.1;
        this._tc3d = tc;
        this._setTab('3d');
        this._setStatus(`Geladen: ${tc.name} — ${tc.desc}`);
        this._viewer.clear();
        this._viewer.clear3DResult?.();
        this._3dCaseDir = null;
        this._lastSlice = null;
        document.getElementById('result-controls-3d').style.display = 'none';
        if (tc.buildings?.length > 1) {
            this._showMultiBuildingPreview(tc.buildings);
        } else {
            this._showFootprintPreview(tc.polygon, maxH);
        }
    }

    _showMultiBuildingPreview(buildings) {
        const colors = [0x2a4a8a, 0x2a7a4a, 0x7a4a2a, 0x7a2a6a, 0x4a7a2a];
        let allXs = [], allYs = [], maxH = 0;
        buildings.forEach((b, i) => {
            const pts2d = b.footprint.map(([x, y]) => new THREE.Vector2(x, y));
            const shape  = new THREE.Shape(pts2d);
            const geom   = new THREE.ExtrudeGeometry(shape, { depth: b.height, bevelEnabled: false });
            geom.rotateX(-Math.PI / 2);
            const mesh  = new THREE.Mesh(geom,
                new THREE.MeshPhongMaterial({ color: colors[i % colors.length], transparent: true, opacity: 0.55, side: THREE.DoubleSide }));
            const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geom),
                new THREE.LineBasicMaterial({ color: 0x3d9eff, opacity: 0.7, transparent: true }));
            this._viewer._modelGroup.add(mesh, edges);
            b.footprint.forEach(([x, y]) => { allXs.push(x); allYs.push(y); });
            if (b.height > maxH) maxH = b.height;
        });

        const box = new THREE.Box3().setFromObject(this._viewer._modelGroup);
        this._viewer._fitCamera3D(box);
        this._3dModelBox = box;
        this._viewer.showWindArrow3D(box, parseFloat(document.getElementById('wind-angle-3d').value) || 0);

        const bw = Math.max(...allXs) - Math.min(...allXs);
        const bd = Math.max(...allYs) - Math.min(...allYs);
        const dom = Math.max(bw, bd) * 3;
        this._3dBbox = {
            min: [Math.min(...allXs) - dom, Math.min(...allYs) - dom, 0],
            max: [Math.max(...allXs) + dom, Math.max(...allYs) + dom, maxH * 2],
        };
        this._init3DSlicePlanes();
    }

    _showFootprintPreview(polygon, height) {
        const pts2d = polygon.map(([x, y]) => new THREE.Vector2(x, y));
        const shape  = new THREE.Shape(pts2d);
        const geom   = new THREE.ExtrudeGeometry(shape, { depth: height, bevelEnabled: false });
        geom.rotateX(-Math.PI / 2);
        const mesh  = new THREE.Mesh(geom,
            new THREE.MeshPhongMaterial({ color: 0x2a4a8a, transparent: true, opacity: 0.55, side: THREE.DoubleSide }));
        const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geom),
            new THREE.LineBasicMaterial({ color: 0x3d9eff, opacity: 0.8, transparent: true }));
        this._viewer._modelGroup.add(mesh, edges);

        const box = new THREE.Box3().setFromObject(mesh);
        this._viewer._fitCamera3D(box);
        this._3dModelBox = box;
        this._viewer.showWindArrow3D(box, parseFloat(document.getElementById('wind-angle-3d').value) || 0);

        // Estimate domain bbox from footprint + height
        const xs = polygon.map(p => p[0]), ys = polygon.map(p => p[1]);
        const bw = Math.max(...xs) - Math.min(...xs);
        const bd = Math.max(...ys) - Math.min(...ys);
        const dom = Math.max(bw, bd) * 3;
        this._3dBbox = {
            min: [Math.min(...xs) - dom, Math.min(...ys) - dom, 0],
            max: [Math.max(...xs) + dom, Math.max(...ys) + dom, height * 2],
        };

        // Show slice planes immediately
        this._init3DSlicePlanes();
    }

    _init3DSlicePlanes() {
        document.getElementById('slices-3d-controls').style.display = 'block';
        // Bind controls once
        if (!this._3dPlanesBound) {
            this._3dPlanesBound = true;
            const update = () => this._update3DSlicePlanes();
            document.getElementById('sl3d-hz').addEventListener('input', update);
            document.getElementById('sl3d-vt').addEventListener('input', update);
            document.getElementById('show-hz-plane').addEventListener('change', e =>
                this._viewer.setSlicePlaneVisible('hz', e.target.checked));
            document.getElementById('show-vt-plane').addEventListener('change', e =>
                this._viewer.setSlicePlaneVisible('vt', e.target.checked));
        }
        this._update3DSlicePlanes();
    }

    _update3DSlicePlanes() {
        if (!this._3dBbox) return;
        const [,,zMin] = this._3dBbox.min;
        const [xMax, yMax, zMax] = this._3dBbox.max;
        const [xMin, yMin] = this._3dBbox.min;
        const H = zMax - zMin;
        const Dy = yMax - yMin;

        const hzFrac = parseFloat(document.getElementById('sl3d-hz').value);
        const vtFrac = parseFloat(document.getElementById('sl3d-vt').value);
        const hzVal  = zMin + hzFrac * H;
        const vtVal  = yMin + vtFrac * Dy;

        document.getElementById('sl3d-hz-val').textContent = `${hzVal.toFixed(1)} m`;
        document.getElementById('sl3d-vt-val').textContent = `${vtVal.toFixed(1)} m`;

        // Show plain outlines; if we have results, fetch colored data
        if (this._3dCaseDir) {
            this._update3DSlices(); // fetch colored result
        } else {
            this._viewer.show3DSlicePlane('z', hzVal, this._3dBbox, 'hz');
            this._viewer.show3DSlicePlane('y', vtVal, this._3dBbox, 'vt');
            // Respect toggle state
            this._viewer.setSlicePlaneVisible('hz', document.getElementById('show-hz-plane').checked);
            this._viewer.setSlicePlaneVisible('vt', document.getElementById('show-vt-plane').checked);
        }
    }

    // ── GLB import ────────────────────────────────────────────────

    _bindGLBUpload() {
        const btn   = document.getElementById('btn-upload-glb');
        const input = document.getElementById('input-glb');
        const scale = document.getElementById('glb-scale');

        btn.addEventListener('click', () => input.click());
        input.addEventListener('change', async () => {
            const file = input.files?.[0];
            if (!file) return;
            this._setStatus('Hochladen…');
            const fd = new FormData();
            fd.append('file', file);
            try {
                const res = await fetch(api('/api/cfd/upload-model'), { method: 'POST', body: fd });
                if (!res.ok) throw new Error(await res.text());
                const data = await res.json();
                this._glbUrl    = data.url;
                this._glbBounds = data.bounds;
                this._glbScale  = parseFloat(scale.value) || 1;
                const b = data.bounds;
                const dx = ((b.max[0] - b.min[0]) * this._glbScale).toFixed(1);
                const dy = ((b.max[1] - b.min[1]) * this._glbScale).toFixed(1);
                const dz = ((b.max[2] - b.min[2]) * this._glbScale).toFixed(1);
                document.getElementById('glb-info').textContent = `${file.name}  ${dx}×${dy}×${dz} m`;
                document.getElementById('building-height').value = Math.round(data.height);
                this._viewer.clear();
                this._viewer.loadGLB(API_BASE + data.url, this._glbScale, ({ done, pct, error }) => {
                    if (error) this._setStatus(`Fehler: ${error}`, 'error');
                    else if (done) this._setStatus(`Modell geladen`);
                    else this._setStatus(`Laden ${Math.round((pct || 0) * 100)}%`);
                });
            } catch (e) {
                this._setStatus(`Upload-Fehler: ${e.message}`, 'error');
            }
        });

        document.getElementById('btn-apply-scale').addEventListener('click', () => {
            if (!this._glbUrl) return;
            this._glbScale = parseFloat(scale.value) || 1;
            this._viewer.clear();
            this._viewer.loadGLB(API_BASE + this._glbUrl, this._glbScale);
        });
    }

    // ── controls ──────────────────────────────────────────────────

    _bindControls() {
        // Tab buttons
        document.querySelectorAll('.tab-btn').forEach(b => {
            b.addEventListener('click', () => this._setTab(b.dataset.tab));
        });

        // View toggle buttons
        document.querySelectorAll('.vbtn').forEach(b => {
            b.addEventListener('click', () => {
                if (b.disabled) return;
                this._setView(b.dataset.view);
            });
        });


        // Draw tools
        document.getElementById('btn-draw').addEventListener('click', () => {
            this._draw.setTool('draw');
            this._setToolActive('btn-draw');
        });
        document.getElementById('btn-select').addEventListener('click', () => {
            this._draw.setTool('select');
            this._setToolActive('btn-select');
        });
        document.getElementById('btn-clear').addEventListener('click', () => {
            this._draw.clear();
            this._polygon = null;
            this._resetResult();
            this._updateRunBtn();
        });

        document.getElementById('btn-flip-h').addEventListener('click', () => this._draw.flipH());
        document.getElementById('btn-flip-v').addEventListener('click', () => this._draw.flipV());

        // Run buttons
        document.getElementById('btn-run-2d').addEventListener('click', () => this._run2D());
        document.getElementById('btn-mesh-only').addEventListener('click', () => this._runMeshOnly());
        document.getElementById('btn-run-3d').addEventListener('click', () => this._run3D());
        document.getElementById('btn-clear-2d').addEventListener('click', () => this._resetResult());
        document.getElementById('btn-clear-3d').addEventListener('click', () => this._resetResult());

        // Transient checkbox
        const transientCb = document.getElementById('transient');
        const transientOpts = document.getElementById('transient-opts');
        transientCb.addEventListener('change', () => {
            transientOpts.style.display = transientCb.checked ? 'block' : 'none';
        });

        // Result field selector
        document.getElementById('result-field').addEventListener('change', e => {
            if (!this._solveResult) return;
            this._showResultField(e.target.value);
            // Invalidate animation cache — needs to be re-fetched for the new field
            if (this._animTimeSteps?.length > 1) {
                this._animColorCache = new Array(this._animTimeSteps.length).fill(null);
                this._animSLCache    = new Array(this._animTimeSteps.length).fill(null);
                this._animCacheReady = false;
                this._prefetchAnimFrames();
            }
        });

        // Wind indicator — update live when inputs change
        const updateWind = () => {
            const angle = parseFloat(document.getElementById('wind-angle').value) || 0;
            const speed = parseFloat(document.getElementById('wind-speed').value) || 20;
            this._drawWindIndicator(angle, speed);
        };
        document.getElementById('wind-angle').addEventListener('input', updateWind);
        document.getElementById('wind-speed').addEventListener('input', updateWind);
        updateWind(); // draw on init

        // Vector toggle
        document.getElementById('show-vectors').addEventListener('change', e => {
            if (!this._solveResult) return;
            if (e.target.checked) {
                this._viewer.showVectors(this._solveResult);
            } else {
                this._viewer.clearVectors();
            }
        });

        // 2D streamline toggle
        document.getElementById('show-streamlines-2d').addEventListener('change', e => {
            document.getElementById('sl2d-opts').style.display = e.target.checked ? 'block' : 'none';
            if (!this._solveResult) return;
            if (e.target.checked) {
                this._refreshStreamlines2D();
                // If transient animation is loaded, re-prefetch all frames with SL
                if (this._animTimeSteps?.length > 1) {
                    this._animColorCache = new Array(this._animTimeSteps.length).fill(null);
                    this._animSLCache    = new Array(this._animTimeSteps.length).fill(null);
                    this._animCacheReady = false;
                    this._prefetchAnimFrames();
                }
            } else {
                this._viewer.clear2DStreamlines();
                if (this._animSLCache) this._animSLCache = new Array(this._animTimeSteps?.length ?? 0).fill(null);
                // Restore field display + colorbar
                this._showResultField(document.getElementById('result-field').value);
            }
        });

        // 2D streamline sub-options
        document.getElementById('sl2d-nseeds').addEventListener('change', () => {
            if (document.getElementById('show-streamlines-2d').checked && this._solveResult) {
                this._refreshStreamlines2D();
                if (this._animTimeSteps?.length > 1) {
                    this._animColorCache = new Array(this._animTimeSteps.length).fill(null);
                    this._animSLCache    = new Array(this._animTimeSteps.length).fill(null);
                    this._animCacheReady = false;
                    this._prefetchAnimFrames();
                }
            }
        });
        document.getElementById('sl2d-no-bg').addEventListener('change', () => {
            if (!this._solveResult) return;
            this._showResultField(document.getElementById('result-field').value);
        });

        // 3D wind angle — update arrow live
        document.getElementById('wind-angle-3d').addEventListener('input', () => {
            if (this._3dModelBox) {
                const angle = parseFloat(document.getElementById('wind-angle-3d').value) || 0;
                this._viewer.showWindArrow3D(this._3dModelBox, angle);
            }
        });

        // GLB upload
        this._bindGLBUpload();
    }

    _setToolActive(id) {
        ['btn-draw', 'btn-select'].forEach(bid => {
            document.getElementById(bid).classList.toggle('active', bid === id);
        });
    }

    _updateRunBtn() {
        const ready = this._polygon !== null && !this._solving;
        for (const id of ['btn-run-2d', 'btn-mesh-only']) {
            const btn = document.getElementById(id);
            if (btn) { btn.disabled = !ready; btn.style.opacity = ready ? '1' : '0.45'; }
        }
    }

    // ── mesh only ────────────────────────────────────────────────

    async _runMeshOnly() {
        if (!this._polygon || this._solving) return;
        this._solving = true;
        this._solveResult = null;
        this._meshData = null;
        this._viewer.clear();
        this._updateRunBtn();
        this._setStatus('Mesh generieren…');
        this._showLog();

        const density    = parseInt(document.getElementById('mesh-density').value) || 50;
        const domainSize = parseFloat(document.getElementById('domain-size').value) || 15;
        const windAngle  = parseFloat(document.getElementById('wind-angle').value) || 0;
        const meshSize   = 0.5 * (1 - density / 100) + 0.05;

        try {
            const res = await fetch(api('/api/cfd/mesh'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ polygon: this._polygon, windAngle, meshSize, farField: domainSize })
            });
            if (!res.ok) throw new Error(await res.text());
            const data = await res.json();
            this._meshData = data;

            // Build a fake solveResult so showMeshOnly can use the same data structure
            // The mesh endpoint returns {nodes: [...], triangles: [...], stats: {...}}
            // Convert to the field format expected by showMeshOnly
            const fakeResult = { field: data };
            this._setStatus(`Mesh: ${data.stats?.n_nodes ?? '?'} Knoten, ${data.stats?.n_triangles ?? '?'} Dreiecke`, 'ok');
            this._appendLog(`✓ Mesh erzeugt: ${data.stats?.n_nodes} Knoten, ${data.stats?.n_triangles} Dreiecke`);

            this._viewer.showMeshOnly(fakeResult);
            this._viewer.showPolygon(this._polygon);
            this._viewer.syncViewWithSVG(this._draw.getViewState());
            document.getElementById('log-panel').style.display = 'none';
            document.getElementById('result-panel').style.display = 'block';
            document.getElementById('result-field').value = 'mesh';
            this._enableResultBtn();
            this._setView('result');
        } catch (e) {
            this._setStatus('Mesh-Fehler: ' + e.message, 'error');
            this._appendLog('Fehler: ' + e.message);
        }

        this._solving = false;
        this._updateRunBtn();
    }

    // ── solve 2D ─────────────────────────────────────────────────

    async _run2D() {
        if (!this._polygon || this._solving) return;
        this._solving = true;
        this._logLines = [];
        this._solveResult = null;
        this._meshData = null;
        this._viewer.clear();

        // Switch to draw mode so SVG is visible (and has correct dimensions)
        // while the calculation runs. syncViewWithSVG() needs the SVG rect.
        this._setView('draw');

        this._updateRunBtn();

        const windSpeed  = parseFloat(document.getElementById('wind-speed').value) || 20;
        const windAngle  = parseFloat(document.getElementById('wind-angle').value) || 0;
        this._windSpeed  = windSpeed;
        this._windAngle  = windAngle;
        const density    = parseInt(document.getElementById('mesh-density').value) || 50;
        const transient  = document.getElementById('transient').checked;
        const endTime    = parseFloat(document.getElementById('end-time').value) || 2;
        const dt         = parseFloat(document.getElementById('dt').value) || 0.002;
        const domainSize = parseFloat(document.getElementById('domain-size').value) || 15;

        const meshSize   = 0.5 * (1 - density / 100) + 0.05;

        this._setStatus('Mesh generieren…');
        this._showLog();

        try {
            const meshRes = await fetch(api('/api/cfd/mesh'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    polygon: this._polygon,
                    windAngle, meshSize, farField: domainSize
                })
            });
            if (!meshRes.ok) throw new Error(await meshRes.text());
            this._meshData = await meshRes.json();
            this._appendLog(`Mesh: ${this._meshData.stats?.n_nodes ?? '?'} Knoten, ${this._meshData.stats?.n_triangles ?? '?'} Dreiecke`);
        } catch (e) {
            this._appendLog(`Mesh-Fehler: ${e.message}`);
            this._setStatus('Mesh-Fehler', 'error');
            this._solving = false;
            this._updateRunBtn();
            return;
        }

        this._setStatus('OpenFOAM läuft…');
        this._appendLog('▶ OpenFOAM Berechnung gestartet…');

        // Await solve start — ensures server has cleared old queue before we open the stream
        try {
            const solveRes = await fetch(api('/api/cfd/solve'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    polygon: this._polygon, windSpeed, windAngle,
                    meshSize, farField: domainSize, transient, endTime, dt
                })
            });
            if (!solveRes.ok) throw new Error(await solveRes.text());
        } catch (e) {
            this._appendLog(`Fehler beim Starten: ${e.message}`);
            this._setStatus('Fehler', 'error');
            this._solving = false;
            this._updateRunBtn();
            return;
        }

        // Stream log (server has now cleared old queue and set running=True)
        await this._streamLog('/api/cfd/log-stream');

        this._solving = false;
        this._updateRunBtn();
    }

    // ── solve 3D ─────────────────────────────────────────────────

    async _run3D() {
        if (this._solving) return;
        this._solving = true;
        this._logLines = [];
        this._solveResult = null;
        this._setStatus('3D Berechnung startet…');
        this._showLog();

        const windSpeed  = parseFloat(document.getElementById('wind-speed-3d').value) || 20;
        const windAngle  = parseFloat(document.getElementById('wind-angle-3d').value) || 0;
        const height     = parseFloat(document.getElementById('building-height').value) || 40;
        const z0         = parseFloat(document.getElementById('roughness').value) || 0.1;
        const domainMul  = parseFloat(document.getElementById('domain-size-3d').value) || 3;

        let body;
        if (this._glbUrl) {
            body = { stlPath: this._glbUrl.replace('/uploads/', ''), stlScale: this._glbScale,
                     windSpeed, windAngle, buildingHeight: height, z0, domainFactor: domainMul };
        } else {
            const tc = this._tc3d || CASES_3D[0];
            if (!tc) { this._setStatus('Kein 3D Modell geladen', 'error'); this._solving = false; return; }
            body = { footprint: tc.polygon, height: tc.height || height,
                     windSpeed, windAngle, z0, domainFactor: domainMul };
            if (tc.buildings?.length > 0) {
                body.buildings = tc.buildings;
                body.height = Math.max(...tc.buildings.map(b => b.height));
            }
        }

        const endpoint = this._glbUrl ? '/api/cfd/solve3d-stl' : '/api/cfd/solve3d';

        // Await start (clears queue, sets running=True) before opening log stream
        try {
            const r = await fetch(api(endpoint), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            if (!r.ok) throw new Error(await r.text());
        } catch (e) {
            this._appendLog(`Fehler: ${e.message}`);
            this._setStatus('Fehler', 'error');
            this._solving = false;
            return;
        }

        await this._streamLog('/api/cfd/log-stream');
        this._solving = false;
    }

    // ── log streaming ─────────────────────────────────────────────

    async _streamLog(path) {
        const logEl = document.getElementById('log-output');
        return new Promise(resolve => {
            const es = new EventSource(api(path) + '?t=' + Date.now());
            es.onmessage = ev => {
                const line = ev.data;
                if (line === '__DONE__') {
                    es.close();
                    this._clearSolveProgress();
                    this._fetchResult();
                    resolve();
                    return;
                }
                // Detect result JSON embedded in log stream
                if (line.startsWith('{"success":') || line.startsWith('{"log":')) {
                    try {
                        const result = JSON.parse(line);
                        if (result.success) {
                            this._solveResult = result;
                            if (result.field) {
                                this._appendLog(`✓ cD=${result.force_coefficients?.Cd?.toFixed(4)} cL=${result.force_coefficients?.Cl?.toFixed(4)}`);
                            } else if (result.case_dir) {
                                const fc = result.force_coefficients;
                                if (fc) this._appendLog(`✓ cD=${(fc.Cd??fc.cd??0).toFixed(4)} cL=${(fc.Cl??fc.cl??0).toFixed(4)}`);
                                else    this._appendLog('✓ 3D Berechnung abgeschlossen');
                            }
                        }
                    } catch (_) {}
                    return;
                }
                this._parseSolveLog(line);
                this._appendLog(line);
            };
            es.onerror = () => {
                es.close();
                resolve();
            };
        });
    }

    _showLog() {
        document.getElementById('log-panel').style.display = 'block';
        document.getElementById('result-panel').style.display = 'none';
        document.getElementById('log-output').innerHTML = '';
    }

    _appendLog(line) {
        this._logLines.push(line);
        const el = document.getElementById('log-output');
        el.textContent = this._logLines.slice(-200).join('\n');
        el.scrollTop = el.scrollHeight;
    }

    // ── results ───────────────────────────────────────────────────

    async _fetchResult() {
        this._setStatus('Berechnung abgeschlossen', 'ok');
        if (!this._solveResult) {
            this._appendLog('⚠ Ergebnis-Daten nicht empfangen. Bitte erneut versuchen.');
            return;
        }
        // 2D result: has field data inline
        if (this._solveResult.field) {
            this._showResults(this._solveResult);
            this._showClearBtn();
        }
        // 3D result: has case_dir, needs slice extraction
        else if (this._solveResult.case_dir) {
            this._setup3DResult(this._solveResult);
            this._showClearBtn();
        }
    }

    _showResults(result) {
        document.getElementById('log-panel').style.display = 'none';
        document.getElementById('result-panel').style.display = 'block';

        // Force coefficients
        const fc = result.force_coefficients;
        if (fc) {
            const fmt = v => v != null ? (+v).toFixed(4) : '—';
            document.getElementById('coeff-cd').textContent = fmt(fc.Cd ?? fc.cD ?? fc.cd);
            document.getElementById('coeff-cl').textContent = fmt(fc.Cl ?? fc.cL ?? fc.cl);
            document.getElementById('coeff-cm').textContent = fmt(fc.Cm ?? fc.cM ?? fc.cm);
        }

        // Show colormap — default to pressure
        if (result.field) {
            const sel = document.getElementById('result-field');
            if (sel.value === 'mesh') sel.value = 'pressure';
            this._showResultField(sel.value);
        }

        // Draw polygon outline and match SVG zoom/pan
        this._viewer.showPolygon(this._polygon);
        this._viewer.syncViewWithSVG(this._draw.getViewState());
        this._drawWindIndicator(this._windAngle ?? 0, this._windSpeed ?? 20);

        // Stats in status bar
        this._updateSolveStats(result);

        // Engineering output: dimensional forces + Cp chart
        this._showEngineeringResults(result);

        // Set up animation controls for transient results
        this._setupAnimation(result);

        this._enableResultBtn();
        this._setView('result');
    }

    _nSeeds2D() {
        return parseInt(document.getElementById('sl2d-nseeds')?.value) || 28;
    }

    _refreshStreamlines2D() {
        if (!this._solveResult) return;
        const maxSpd = this._viewer.show2DStreamlines(this._solveResult, this._polygon, this._nSeeds2D());
        if (maxSpd != null) this._updateColorbar('speed', 0, maxSpd);
    }

    _showResultField(fieldName) {
        const vs       = this._draw.getViewState();
        const slActive = document.getElementById('show-streamlines-2d').checked;
        const noBg     = slActive && document.getElementById('sl2d-no-bg')?.checked;

        if (fieldName === 'mesh') {
            const fakeResult = this._solveResult ?? (this._meshData ? { field: this._meshData } : null);
            if (fakeResult) {
                this._viewer.showMeshOnly(fakeResult);
                this._viewer.showPolygon(this._polygon);
                this._viewer.syncViewWithSVG(vs);
            }
            this._updateColorbar(fieldName, null, null);
            return;
        }

        const result = this._solveResult;
        if (!result?.field) return;

        // "Ohne Hintergrund": skip CFD contour, show dark section fill instead
        let bounds;
        if (noBg) {
            this._viewer._clearCFD();
            this._viewer.showSectionFill(this._polygon);
        } else {
            bounds = this._viewer.showCFDResult(result, fieldName);
        }
        this._viewer.showPolygon(this._polygon);
        if (document.getElementById('show-vectors').checked) {
            this._viewer.showVectors(result);
        }
        if (slActive) {
            const maxSpd = this._viewer.show2DStreamlines(result, this._polygon, this._nSeeds2D());
            if (maxSpd != null) this._updateColorbar('speed', 0, maxSpd);
        }
        this._viewer.syncViewWithSVG(vs);

        if (bounds) {
            this._updateColorbar(fieldName, bounds.vmin, bounds.vmax);
        }
    }

    _updateColorbar(fieldName, vmin, vmax) {
        const FIELDS = {
            pressure: { label: 'Druck p',          unit: 'm²/s²' },
            speed:    { label: 'Geschw. |U|',       unit: 'm/s'   },
            vorticity:{ label: 'Vorticity ωz',      unit: '1/s'   },
            turb_k:   { label: 'Turb.-energie k',   unit: 'm²/s²' },
            mesh:     { label: 'Netz',               unit: ''      },
        };
        const info = FIELDS[fieldName] ?? { label: fieldName, unit: '' };

        document.getElementById('cb-title').textContent = info.label;
        document.getElementById('cb-unit').textContent  = info.unit;

        const tickEls = document.getElementById('cb-ticks').children;

        if (vmin == null || vmax == null) {
            for (const el of tickEls) el.textContent = '—';
            return;
        }

        // 5 ticks: max → min (top to bottom matches gradient direction)
        const fmt = v => {
            const abs = Math.abs(v);
            if (abs === 0) return '0';
            if (abs >= 1e4 || (abs < 0.01 && abs > 0)) return v.toExponential(1);
            return v.toFixed(abs >= 100 ? 0 : abs >= 10 ? 1 : 2);
        };

        const n = tickEls.length;
        for (let i = 0; i < n; i++) {
            const t = i / (n - 1);
            tickEls[i].textContent = fmt(vmax - t * (vmax - vmin));
        }
    }

    // ── wind direction indicator ──────────────────────────────────

    _drawWindIndicator(angleDeg, speed) {
        const canvas = document.getElementById('wind-canvas');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const W = 76, H = 90;
        const cx = 38, cy = 41, R = 28;

        ctx.clearRect(0, 0, W, H);

        // Background circle
        ctx.beginPath();
        ctx.arc(cx, cy, R, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(10,12,18,0.82)';
        ctx.fill();
        ctx.strokeStyle = 'rgba(42,52,68,0.9)';
        ctx.lineWidth = 1;
        ctx.stroke();

        // Subtle compass tick marks
        ctx.strokeStyle = 'rgba(100,120,140,0.35)';
        ctx.lineWidth = 0.8;
        for (let a = 0; a < 360; a += 45) {
            const rad = (a - 90) * Math.PI / 180;
            const inner = a % 90 === 0 ? R - 7 : R - 4;
            ctx.beginPath();
            ctx.moveTo(cx + Math.cos(rad) * inner, cy + Math.sin(rad) * inner);
            ctx.lineTo(cx + Math.cos(rad) * (R - 1), cy + Math.sin(rad) * (R - 1));
            ctx.stroke();
        }

        // Wind arrow: angle=0 → right (+X), canvas Y inverted
        const rad = angleDeg * Math.PI / 180;
        const dx  =  Math.cos(rad);   // screen X component
        const dy  = -Math.sin(rad);   // screen Y component (inverted)

        const tailX = cx - dx * (R - 5), tailY = cy - dy * (R - 5);
        const tipX  = cx + dx * (R - 5), tipY  = cy + dy * (R - 5);

        // Shaft
        ctx.beginPath();
        ctx.moveTo(tailX, tailY);
        ctx.lineTo(tipX, tipY);
        ctx.strokeStyle = '#3d9eff';
        ctx.lineWidth = 2.2;
        ctx.lineCap = 'round';
        ctx.stroke();

        // Arrowhead
        const headLen = 9;
        const cos140 = Math.cos(Math.PI * 140 / 180);
        const sin140 = Math.sin(Math.PI * 140 / 180);
        ctx.beginPath();
        ctx.moveTo(tipX, tipY);
        ctx.lineTo(tipX + (dx * cos140 - dy * sin140) * headLen,
                   tipY + (dx * sin140 + dy * cos140) * headLen);
        ctx.moveTo(tipX, tipY);
        ctx.lineTo(tipX + (dx * cos140 + dy * sin140) * headLen,
                   tipY + (-dx * sin140 + dy * cos140) * headLen);
        ctx.strokeStyle = '#3d9eff';
        ctx.lineWidth = 2;
        ctx.stroke();

        // Angle label
        const angleLabel = `${angleDeg >= 0 ? '+' : ''}${angleDeg}°`;
        ctx.fillStyle = 'rgba(100,120,140,0.8)';
        ctx.font = '9px JetBrains Mono, monospace';
        ctx.textAlign = 'center';
        ctx.fillText(angleLabel, cx, cy + R + 11);

        // Speed label
        ctx.fillStyle = '#6a7a8e';
        ctx.font = 'bold 9px JetBrains Mono, monospace';
        ctx.fillText(`${speed} m/s`, cx, cy + R + 22);
    }

    // ── status ────────────────────────────────────────────────────

    _setStatus(msg, type = 'info') {
        const el = document.getElementById('statusbar-msg');
        el.textContent = msg;
        el.className = 'status-msg status-' + type;
    }

    // ── dimensional forces + Cp chart ────────────────────────────

    _showEngineeringResults(solveResult) {
        const fc  = solveResult.force_coefficients;
        if (!fc) return;

        const cD = fc.Cd ?? fc.cD ?? 0;
        const cL = fc.Cl ?? fc.cL ?? 0;
        const cM = fc.Cm ?? fc.cM ?? 0;

        // Reference geometry from polygon
        const poly = this._polygon;
        if (!poly?.length) return;

        const xs = poly.map(p => p[0]), ys = poly.map(p => p[1]);
        const W  = Math.max(...xs) - Math.min(...xs); // width
        const H  = Math.max(...ys) - Math.min(...ys); // height (ref for cD)
        const Href = H;  // frontal height ⊥ wind (wind from left → Href = H)

        const rho   = 1.25;   // kg/m³  air density
        const v     = this._windSpeed ?? 20;  // m/s
        const q_Pa  = 0.5 * rho * v * v;     // [Pa = N/m²]
        const q_kPa = q_Pa / 1000;            // [kPa]

        const FD = cD * q_Pa * Href / 1000;   // kN/m
        const FL = cL * q_Pa * Href / 1000;   // kN/m
        const MT = cM * q_Pa * Href * Href / 1000; // kNm/m

        const fmt = (v, dec = 2) => isFinite(v) ? v.toFixed(dec) : '—';

        document.getElementById('f-q').textContent    = `${fmt(q_kPa,3)} kPa`;
        document.getElementById('f-href').textContent = `${fmt(Href,2)} m`;
        document.getElementById('f-fd').textContent   = `${fmt(FD)} kN/m`;
        document.getElementById('f-fl').textContent   = `${fmt(FL)} kN/m`;
        document.getElementById('f-mt').textContent   = `${fmt(MT)} kNm/m`;
        document.getElementById('forces-section').style.display = 'block';

        // Draw Cp chart
        this._drawCpChart(solveResult, poly, q_Pa);
    }

    _drawCpChart(solveResult, polygon, q_Pa) {
        const field = solveResult?.field;
        if (!field?.triangles || !field?.nodes || q_Pa < 1) return;

        // Build node position map
        const nodePos = {};
        for (const n of field.nodes) nodePos[n.id] = [n.x, n.y];

        // Polygon edges with cumulative arc length
        const np    = polygon.length;
        const edges = [];
        let totalS  = 0;
        for (let i = 0; i < np; i++) {
            const [x1,y1] = polygon[i], [x2,y2] = polygon[(i+1)%np];
            const len = Math.hypot(x2-x1, y2-y1);
            edges.push({x1,y1,x2,y2, s0: totalS, len});
            totalS += len;
        }

        // Characteristic size for near-wall threshold
        const xs = polygon.map(p=>p[0]), ys = polygon.map(p=>p[1]);
        const charDim = Math.max(Math.max(...xs)-Math.min(...xs), Math.max(...ys)-Math.min(...ys));
        const threshold = charDim * 0.12; // within 12% of char_dim

        // Sample Cp at triangle centroids near the section
        const raw = [];
        for (const tri of field.triangles) {
            const ids = tri.nodes;
            const pts = ids.map(id => nodePos[id]).filter(Boolean);
            if (pts.length < 3) continue;

            const cx = (pts[0][0]+pts[1][0]+pts[2][0])/3;
            const cy = (pts[0][1]+pts[1][1]+pts[2][1])/3;

            // Distance and arc-length to nearest polygon edge
            let minD = Infinity, bestS = 0;
            for (const {x1,y1,x2,y2,s0,len} of edges) {
                const dx=x2-x1, dy=y2-y1;
                const t = Math.max(0,Math.min(1,((cx-x1)*dx+(cy-y1)*dy)/(len*len)));
                const dist = Math.hypot(x1+t*dx-cx, y1+t*dy-cy);
                if (dist < minD) { minD = dist; bestS = s0 + t*len; }
            }

            if (minD < threshold) {
                raw.push({s: bestS, cp: (tri.p ?? 0) / q_Pa});
            }
        }

        if (raw.length < 4) return;
        raw.sort((a,b) => a.s - b.s);

        // Bin into ~50 points for smooth curve
        const BINS = 50;
        const binW = totalS / BINS;
        const pts  = [];
        for (let i = 0; i < BINS; i++) {
            const s0 = i*binW, s1 = s0+binW;
            const bucket = raw.filter(p => p.s >= s0 && p.s < s1);
            if (bucket.length) {
                pts.push({
                    s:  (s0+s1)/2,
                    cp: bucket.reduce((a,b)=>a+b.cp,0)/bucket.length
                });
            }
        }
        if (pts.length < 2) return;

        // SVG chart dimensions
        const SVG_W = 240, SVG_H = 90;
        const PAD   = {l:28, r:6, t:8, b:18};
        const cw    = SVG_W - PAD.l - PAD.r;
        const ch    = SVG_H - PAD.t - PAD.b;

        const cpVals = pts.map(p=>p.cp);
        const cpMin  = Math.min(...cpVals, -0.5);
        const cpMax  = Math.max(...cpVals,  1.0);
        const cpRange= Math.max(cpMax - cpMin, 0.5);

        const sx = s  => PAD.l + (s  / totalS) * cw;
        const sy = cp => PAD.t + (1 - (cp - cpMin) / cpRange) * ch;
        const y0 = sy(0); // y-position of Cp=0 line

        // Build polyline
        const polyPts = pts.map(p => `${sx(p.s).toFixed(1)},${sy(p.cp).toFixed(1)}`).join(' ');

        // Tick values on y-axis
        const ticks = [];
        const step  = cpRange > 3 ? 1 : cpRange > 1.5 ? 0.5 : 0.25;
        const t0    = Math.ceil(cpMin / step) * step;
        for (let v = t0; v <= cpMax + step*0.1; v += step) {
            ticks.push({v, y: sy(v)});
        }

        const fmtCp = v => v === 0 ? '0' : v.toFixed(v % 1 === 0 ? 0 : 2);

        const svg = `
<svg id="cp-svg" height="${SVG_H}" viewBox="0 0 ${SVG_W} ${SVG_H}"
     xmlns="http://www.w3.org/2000/svg" style="background:none">

  <!-- Grid lines + y-axis ticks -->
  ${ticks.map(({v,y}) => `
    <line x1="${PAD.l}" y1="${y.toFixed(1)}" x2="${SVG_W-PAD.r}" y2="${y.toFixed(1)}"
          stroke="${v===0?'#2a3444':'#181e28'}" stroke-width="${v===0?0.8:0.4}"/>
    <text x="${PAD.l-3}" y="${(y+3.5).toFixed(1)}" text-anchor="end"
          font-size="7" font-family="JetBrains Mono,monospace" fill="#445566">${fmtCp(v)}</text>
  `).join('')}

  <!-- X-axis -->
  <line x1="${PAD.l}" y1="${(y0).toFixed(1)}" x2="${SVG_W-PAD.r}" y2="${(y0).toFixed(1)}"
        stroke="#2a3444" stroke-width="0.8"/>

  <!-- Cp curve — filled area above/below zero -->
  <polyline points="${polyPts}" fill="none" stroke="#3d9eff" stroke-width="1.4"
            stroke-linejoin="round" stroke-linecap="round"/>

  <!-- X-axis label -->
  <text x="${PAD.l + cw/2}" y="${SVG_H-2}" text-anchor="middle"
        font-size="7.5" font-family="Barlow Condensed,sans-serif" fill="#445566">
        Konturlänge s [m]  (s=0 = Vorderkante)
  </text>

  <!-- Cp label -->
  <text x="5" y="${PAD.t + ch/2}" text-anchor="middle"
        font-size="7.5" font-family="Barlow Condensed,sans-serif" fill="#445566"
        transform="rotate(-90,5,${PAD.t+ch/2})">Cp</text>
</svg>`;

        const wrap = document.getElementById('cp-chart-wrap');
        wrap.style.display = 'block';
        wrap.innerHTML = svg;
    }

    // ── live log parsing → status bar ────────────────────────────

    _parseSolveLog(line) {
        const prog = document.getElementById('statusbar-progress');

        // "Time = 45" or "Time = 0.5"
        const timeM = line.match(/^Time = ([\d.e+-]+)/);
        if (timeM) {
            this._sp_time = parseFloat(timeM[1]);
        }

        // "ExecutionTime = 1.23 s  ClockTime = 3 s"
        const execM = line.match(/ExecutionTime = ([\d.]+) s\s+ClockTime = ([\d.]+) s/);
        if (execM) {
            this._sp_exec = parseFloat(execM[1]);
        }

        // "[N/N] Force coefficients: {...}"
        const forceM = line.match(/\[(\d+)\/(\d+)\] Force coefficients:.*?'Cd':\s*([\d.e+-]+).*?'Cl':\s*([\d.e+-]+)/);
        if (forceM) {
            this._sp_iter = parseInt(forceM[1]);
            this._sp_imax = parseInt(forceM[2]);
            this._sp_cd   = parseFloat(forceM[3]);
            this._sp_cl   = parseFloat(forceM[4]);
        }

        // "SIMPLE solution converged in N iterations"
        const convM = line.match(/converged in (\d+) iterations/);
        if (convM) {
            this._sp_iter = parseInt(convM[1]);
        }

        // Build progress string
        const parts = [];
        if (this._sp_iter != null) parts.push(`Iter ${this._sp_iter}${this._sp_imax ? '/'+this._sp_imax : ''}`);
        if (this._sp_cd   != null) parts.push(`cD ${this._sp_cd.toFixed(4)}`);
        if (this._sp_cl   != null) parts.push(`cL ${this._sp_cl.toFixed(4)}`);
        if (this._sp_exec != null) parts.push(`t ${this._sp_exec.toFixed(1)}s`);

        if (parts.length) {
            prog.style.display = '';
            prog.textContent = parts.join('  ·  ');
        }
    }

    _clearSolveProgress() {
        // Save final execution time before clearing
        this._lastExecTime = this._sp_exec ?? null;
        this._sp_iter = this._sp_imax = this._sp_cd = this._sp_cl = this._sp_exec = null;
        document.getElementById('statusbar-progress').style.display = 'none';
    }

    _updateSolveStats(result) {
        const stats = result.stats ?? result.field?.stats;
        const nNodes = stats?.n_nodes  ?? stats?.n_points ?? '—';
        const nCells = stats?.n_elements ?? stats?.n_triangles ?? '—';
        // DOF = cells × equations (k-epsilon: Ux, Uy, p, k, ε = 5)
        const dof  = typeof nCells === 'number' ? nCells * 5 : '—';
        const zeit = this._lastExecTime != null ? `${this._lastExecTime.toFixed(1)} s` : '—';

        const parts = [];
        if (nNodes !== '—') parts.push(`${Number(nNodes).toLocaleString('de')} Kn.`);
        if (nCells !== '—') parts.push(`${Number(nCells).toLocaleString('de')} Zellen`);
        if (dof    !== '—') parts.push(`${Number(dof).toLocaleString('de')} DOF`);
        parts.push(`t = ${zeit}`);

        const el = document.getElementById('statusbar-stats');
        el.textContent = parts.join('  ·  ');
        el.style.display = '';
    }

    // ── 3D result ─────────────────────────────────────────────────

    _setup3DResult(result) {
        this._3dCaseDir = result.case_dir;
        // Update bbox from actual solve result if available
        if (result.bbox) this._3dBbox = result.bbox;

        // Show result controls
        document.getElementById('result-controls-3d').style.display = 'block';

        // Bind result-specific controls (once)
        if (!this._3dResultBound) {
            this._3dResultBound = true;
            document.getElementById('result-field-3d').addEventListener('change', () => this._update3DSlices());
            document.getElementById('show-vectors-3d').addEventListener('change', () => this._update3DSlices());
            document.getElementById('show-streamlines-3d').addEventListener('change', e => {
                document.getElementById('sl3d-stream-opts').style.display = e.target.checked ? 'block' : 'none';
                if (e.target.checked) this._update3DStreamlines();
                else this._viewer._clearStreamlines();
            });
            document.getElementById('sl3d-seeds').addEventListener('change', () => {
                if (document.getElementById('show-streamlines-3d').checked) this._update3DStreamlines();
            });
            // Slider events now also trigger colored result fetch (override plain plane update)
            // (already bound in _init3DSlicePlanes via _update3DSlicePlanes → _update3DSlices)
        }

        this._enableResultBtn();
        this._setView('result');
        this._update3DSlices(); // fetch colored slices at current positions
        this._setStatus('3D Ergebnisse geladen', 'ok');
    }

    async _update3DSlices() {
        if (!this._3dCaseDir) return;
        const [xMin, yMin, zMin] = this._3dBbox.min;
        const [xMax, yMax, zMax] = this._3dBbox.max;

        const hzFrac = parseFloat(document.getElementById('sl3d-hz').value);
        const vtFrac = parseFloat(document.getElementById('sl3d-vt').value);
        const hzVal  = zMin + hzFrac * (zMax - zMin);
        const vtVal  = yMin + vtFrac * (yMax - yMin);
        const field  = document.getElementById('result-field-3d').value;
        const showVec = document.getElementById('show-vectors-3d').checked;

        document.getElementById('sl3d-hz-val').textContent = `${hzVal.toFixed(1)} m`;
        document.getElementById('sl3d-vt-val').textContent = `${vtVal.toFixed(1)} m`;

        // Clear only colored result, keep plane outlines
        this._viewer.clearSliceResults?.();
        this._viewer._clearAllSliceStreamlines?.();

        // Fetch both slices in parallel
        const [hzData, vtData] = await Promise.all([
            this._fetchSlice('z', hzVal, field),
            this._fetchSlice('y', vtVal, field),
        ]);

        const hzOn = document.getElementById('show-hz-plane').checked;
        const vtOn = document.getElementById('show-vt-plane').checked;

        if (hzData) {
            const b = this._viewer.show3DSlice(hzData, field, 'z', hzVal, 'hz');
            if (showVec && hzData.vectors) this._viewer.show3DSliceVectors(hzData.vectors, 'z', hzVal, 'hz');
            if (b) this._updateColorbar(field, b.vmin, b.vmax);
            this._viewer.setSlicePlaneVisible('hz', hzOn);
        } else {
            // No data yet — show plain outline
            this._viewer.show3DSlicePlane('z', hzVal, this._3dBbox, 'hz');
            this._viewer.setSlicePlaneVisible('hz', hzOn);
        }
        if (vtData) {
            this._viewer.show3DSlice(vtData, field, 'y', vtVal, 'vt');
            if (showVec && vtData.vectors) this._viewer.show3DSliceVectors(vtData.vectors, 'y', vtVal, 'vt');
            this._viewer.setSlicePlaneVisible('vt', vtOn);
        } else {
            this._viewer.show3DSlicePlane('y', vtVal, this._3dBbox, 'vt');
            this._viewer.setSlicePlaneVisible('vt', vtOn);
        }

        // Cache slice data and redraw streamlines if toggle is active
        this._lastSlice = { hz: { data: hzData, val: hzVal }, vt: { data: vtData, val: vtVal } };
        if (document.getElementById('show-streamlines-3d')?.checked) {
            const nSeeds = parseInt(document.getElementById('sl3d-seeds')?.value) || 24;
            if (hzData && hzOn) this._viewer.showSliceStreamlines(hzData, 'z', hzVal, 'hz', nSeeds);
            if (vtData && vtOn) this._viewer.showSliceStreamlines(vtData, 'y', vtVal, 'vt', nSeeds);
        }
    }

    async _fetchTimestep(time, fieldName) {
        try {
            const res = await fetch(api('/api/cfd/timestep'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    caseDir: this._animCaseDir,
                    time,
                    field: fieldName,
                    polygon: this._polygon,  // enables near-field filter matching initial solve
                })
            });
            if (!res.ok) return null;
            const data = await res.json();
            return data.field ? data : { field: data };
        } catch { return null; }
    }

    async _fetchSlice(plane, value, field) {
        try {
            const res = await fetch(api('/api/cfd/slice3d'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ caseDir: this._3dCaseDir, plane, value, field })
            });
            if (!res.ok) return null;
            return await res.json();
        } catch { return null; }
    }

    async _update3DStreamlines() {
        if (!this._3dCaseDir) return;
        const nSeeds = parseInt(document.getElementById('sl3d-seeds').value) || 24;

        // Prefer client-side RK4 on slice planes if slice data is available
        if (this._lastSlice) {
            const { hz, vt } = this._lastSlice;
            this._viewer._clearAllSliceStreamlines?.();
            const hzOn = document.getElementById('show-hz-plane')?.checked !== false;
            const vtOn = document.getElementById('show-vt-plane')?.checked !== false;
            if (hz?.data && hzOn) this._viewer.showSliceStreamlines(hz.data, 'z', hz.val, 'hz', nSeeds);
            if (vt?.data && vtOn) this._viewer.showSliceStreamlines(vt.data, 'y', vt.val, 'vt', nSeeds);
            return;
        }

        // Fallback: fetch spaghetti streamlines from backend
        const zMinPct = parseInt(document.getElementById('sl3d-szmin').value) / 100;
        const zMaxPct = parseInt(document.getElementById('sl3d-szmax').value) / 100;
        this._setStatus('Stromlinien werden berechnet…');
        try {
            const res = await fetch(api('/api/cfd/streamlines3d'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ caseDir: this._3dCaseDir, nSeeds, seedZmin: zMinPct, seedZmax: zMaxPct })
            });
            if (!res.ok) throw new Error(await res.text());
            const data = await res.json();
            this._viewer.show3DStreamlines(data.streamlines ?? []);
            this._setStatus(`${data.count ?? 0} Stromlinien geladen`, 'ok');
        } catch (e) {
            this._setStatus('Stromlinien-Fehler: ' + e.message, 'error');
        }
    }

    // ── animation ─────────────────────────────────────────────────

    _setupAnimation(result) {
        const ts = result.field?.time_steps;
        if (!ts || ts.length <= 1) {
            document.getElementById('anim-bar').classList.add('hidden');
            return;
        }

        this._animTimeSteps  = ts;
        this._animIdx        = ts.length - 1;
        this._animCaseDir    = result.case_dir;
        this._animPlaying    = false;
        this._animColorCache = new Array(ts.length).fill(null);
        this._animSLCache    = new Array(ts.length).fill(null);
        this._animCacheReady = false;

        const bar    = document.getElementById('anim-bar');
        const slider = document.getElementById('anim-slider');
        bar.classList.remove('hidden');
        slider.max   = ts.length - 1;
        slider.value = this._animIdx;
        this._updateAnimTime();

        // Bind controls (once)
        if (!this._animBound) {
            this._animBound = true;
            document.getElementById('anim-play').addEventListener('click', () => this._animToggle());
            document.getElementById('anim-first').addEventListener('click', () => { this._animStop(); this._animGoto(0); });
            document.getElementById('anim-last').addEventListener('click',  () => { this._animStop(); this._animGoto(ts.length - 1); });
            document.getElementById('anim-prev').addEventListener('click',  () => { this._animStop(); this._animGoto(this._animIdx - 1); });
            document.getElementById('anim-next').addEventListener('click',  () => { this._animStop(); this._animGoto(this._animIdx + 1); });
            slider.addEventListener('input', () => { this._animStop(); this._animGoto(+slider.value); });
        }

        // Pre-fetch all frames in background for smooth playback
        this._prefetchAnimFrames();
    }

    // Pre-fetch all animation frames (runs in background, non-blocking).
    // Uses a generation counter to abort if field changes mid-prefetch.
    async _prefetchAnimFrames() {
        if (!this._animTimeSteps?.length || !this._animCaseDir) return;
        const fieldName = document.getElementById('result-field').value;
        if (fieldName === 'mesh') return;

        const n = this._animTimeSteps.length;
        this._animColorCache = new Array(n).fill(null);
        this._animSLCache    = new Array(n).fill(null);
        this._animCacheReady = false;

        // Stamp this prefetch run — if field or SL settings change, a new run starts
        const myGen = (this._animPrefetchGen = (this._animPrefetchGen ?? 0) + 1);

        // Consistent color range from current (last) frame
        const meta = this._viewer._cfdAnimMeta;
        const vmin = meta?.vmin ?? -10, vmax = meta?.vmax ?? 10;

        const slActive = document.getElementById('show-streamlines-2d').checked;
        const nSeeds   = this._nSeeds2D();

        // Temp storage for raw field data — used in SL phase to avoid re-fetching
        const rawData = slActive ? new Array(n).fill(null) : null;

        // Phase 1: fetch color data in parallel batches (fast, no blocking)
        const BATCH = 3;
        let loaded = 0;
        for (let i = 0; i < n; i += BATCH) {
            if (this._animPrefetchGen !== myGen) return;

            const batch = [];
            for (let j = i; j < Math.min(i + BATCH, n); j++) {
                batch.push(
                    this._fetchTimestep(this._animTimeSteps[j], fieldName)
                        .then(data => {
                            if (this._animPrefetchGen !== myGen) return; // stale
                            if (data) {
                                this._animColorCache[j] = this._viewer.computeAnimColors(data, vmin, vmax);
                                if (rawData) rawData[j] = data;
                            }
                            loaded++;
                            const pct = Math.round(loaded / n * (slActive ? 50 : 100));
                            document.getElementById('anim-time').textContent = `Laden ${pct}%`;
                        })
                        .catch(() => { loaded++; })
                );
            }
            await Promise.all(batch);
        }

        if (this._animPrefetchGen !== myGen) return;
        this._animCacheReady = true;
        this._animFps = 12;
        this._updateAnimTime();

        // Phase 2: trace streamlines one frame at a time, yielding to the RAF between each.
        // RK4 tracing is CPU-heavy; yielding via setTimeout(0) prevents blocking animation frames.
        if (slActive && rawData) {
            for (let j = 0; j < n; j++) {
                if (this._animPrefetchGen !== myGen) return;
                await new Promise(resolve => setTimeout(resolve, 0)); // yield — let RAF render
                if (rawData[j]) {
                    this._animSLCache[j] = this._viewer.traceStreamlines2D(rawData[j], this._polygon, nSeeds);
                    rawData[j] = null; // free memory as we go
                }
                const pct = 50 + Math.round((j + 1) / n * 50);
                document.getElementById('anim-time').textContent = `Stromlinien ${pct}%`;
            }
        }

        if (this._animPrefetchGen !== myGen) return;

        // Pre-build all streamline Three.js geometries once — animation only toggles visibility.
        if (slActive && this._animSLCache.some(s => s !== null)) {
            this._viewer.preloadStreamlines2D(this._animSLCache);
        }

        this._updateAnimTime(); // restore "t = X s" label
    }

    _animToggle() {
        this._animPlaying ? this._animStop() : this._animStart();
    }

    _animStart() {
        this._animPlaying = true;
        document.getElementById('anim-play').textContent = '⏸';
        document.getElementById('anim-play').classList.add('active');
        this._animStep();
    }

    _animStop() {
        this._animPlaying = false;
        clearTimeout(this._animTimer);
        document.getElementById('anim-play').textContent = '▶';
        document.getElementById('anim-play').classList.remove('active');
    }

    _animStep() {
        if (!this._animPlaying) return;
        const n = this._animTimeSteps.length;
        const next = (this._animIdx + 1) % n;
        this._animGoto(next).then(() => {
            if (!this._animPlaying) return;
            let delay;
            if (!this._animCacheReady) {
                delay = 500; // 2 FPS while loading
            } else {
                // Real-time playback: hold each frame for its actual simulation dt
                const curr = this._animIdx;
                const nxt  = (curr + 1) % n;
                const dt = nxt > curr
                    ? this._animTimeSteps[nxt] - this._animTimeSteps[curr]
                    : (n > 1 ? this._animTimeSteps[n-1] - this._animTimeSteps[n-2] : 0.1);
                delay = Math.max(50, dt * 1000);
            }
            this._animTimer = setTimeout(() => this._animStep(), delay);
        });
    }

    async _animGoto(idx) {
        if (!this._animTimeSteps.length) return;
        idx = Math.max(0, Math.min(idx, this._animTimeSteps.length - 1));
        this._animIdx = idx;

        document.getElementById('anim-slider').value = idx;
        this._updateAnimTime();

        const fieldName = document.getElementById('result-field').value;
        if (fieldName === 'mesh') return;

        const slActive = document.getElementById('show-streamlines-2d').checked;

        // Fast path: use pre-cached color array (no network, just GPU buffer update)
        const cached = this._animColorCache?.[idx];
        if (cached) {
            this._viewer.applyAnimColors(cached);
            if (slActive) {
                const maxSpd = this._viewer.applyAnimStreamlines(idx);
                if (maxSpd != null) this._updateColorbar('speed', 0, maxSpd);
            }
            return;
        }

        // Slow path: fetch from server (cache not ready yet)
        // Skip during playback — showCFDResult calls _clearCFD which nullifies _streamGroup2D,
        // causing _buildStreamlines2D to re-add it to _cfdGroup on the next fast-path frame,
        // which corrupts Three.js's render state for the sibling contour mesh.
        if (this._animPlaying) return;

        try {
            const data = await this._fetchTimestep(this._animTimeSteps[idx], fieldName);
            if (!data) return;
            const vs = this._draw.getViewState();
            const bounds = this._viewer.showCFDResult(data, fieldName);
            this._viewer.showPolygon(this._polygon);
            this._viewer.syncViewWithSVG(vs);
            if (bounds) this._updateColorbar(fieldName, bounds.vmin, bounds.vmax);
            if (slActive) {
                const maxSpd = this._viewer.show2DStreamlines(data, this._polygon, this._nSeeds2D());
                if (maxSpd != null) this._updateColorbar('speed', 0, maxSpd);
            }
        } catch (_) {}
    }

    _updateAnimTime() {
        const t = this._animTimeSteps[this._animIdx];
        document.getElementById('anim-time').textContent =
            `t = ${t % 1 === 0 ? t.toFixed(0) : t.toFixed(3)} s`;
    }
}

// ── Bootstrap ─────────────────────────────────────────────────────

// ES modules are deferred — DOM is fully parsed before this runs
try {
    window._app = new CFDApp();
} catch (e) {
    console.error('CFDApp init failed:', e);
    const sb = document.getElementById('statusbar-msg');
    if (sb) { sb.textContent = 'Init-Fehler: ' + e.message; sb.style.color = 'var(--danger)'; }
}

export { CFDApp };
