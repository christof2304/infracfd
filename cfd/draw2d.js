// draw2d.js — SVG-based 2D cross-section polygon editor

export class Draw2D {
    constructor(svgEl) {
        this.svg = svgEl;
        this.pts = [];        // [{x,y}] model coords (Y up, meters)
        this.closed = false;
        this.tool = 'draw';   // 'draw' | 'select'
        this.gridSize = 0.5;
        this.onChange = null; // (pts:[[x,y]], closed:bool) => void

        this._vx = 4;         // view center model X
        this._vy = 1;         // view center model Y
        this._scale = 80;     // px per meter
        this._hover = -1;
        this._selected = -1;
        this._preview = null; // {x,y} next point preview (model coords)
        this._drag = null;    // {type:'pan'|'point', ...}
        this._dirty = true;
        this._raf = null;
        this._layers = {};

        this._initLayers();
        this._bindEvents();
        this._scheduleRender();
    }

    // ── coordinate conversion ──────────────────────────────────────

    _rect() { return this.svg.getBoundingClientRect(); }

    _m2s(mx, my) {
        const r = this._rect();
        return [
            r.width  / 2 + (mx - this._vx) * this._scale,
            r.height / 2 - (my - this._vy) * this._scale
        ];
    }

    _s2m(sx, sy) {
        const r = this._rect();
        return [
            (sx - r.width  / 2) / this._scale + this._vx,
            -(sy - r.height / 2) / this._scale + this._vy
        ];
    }

    _snap(x, y) {
        const g = this.gridSize;
        return [Math.round(x / g) * g, Math.round(y / g) * g];
    }

    // ── layer setup ───────────────────────────────────────────────

    _initLayers() {
        this.svg.innerHTML = '';
        const ns = 'http://www.w3.org/2000/svg';
        for (const id of ['grid', 'axes', 'fill', 'edges', 'dims', 'pts', 'hint']) {
            const g = document.createElementNS(ns, 'g');
            g.id = 'dl-' + id;
            this.svg.appendChild(g);
            this._layers[id] = g;
        }
        this.svg.style.cursor = 'crosshair';
    }

    // ── event binding ─────────────────────────────────────────────

    _bindEvents() {
        const s = this.svg;
        s.addEventListener('mousedown',   e => this._onDown(e));
        s.addEventListener('mousemove',   e => this._onMove(e));
        s.addEventListener('mouseup',     e => this._onUp(e));
        s.addEventListener('dblclick',    e => this._onDblClick(e));
        s.addEventListener('wheel',       e => this._onWheel(e), { passive: false });
        s.addEventListener('contextmenu', e => { e.preventDefault(); this._onRightClick(e); });
        window.addEventListener('keydown', e => this._onKey(e));
    }

    _svgXY(e) {
        const r = this._rect();
        return [e.clientX - r.left, e.clientY - r.top];
    }

    _nearPoint(sx, sy, thresh = 12) {
        let best = -1, bestD = thresh * thresh;
        for (let i = 0; i < this.pts.length; i++) {
            const [px, py] = this._m2s(this.pts[i].x, this.pts[i].y);
            const d = (px - sx) ** 2 + (py - sy) ** 2;
            if (d < bestD) { bestD = d; best = i; }
        }
        return best;
    }

    _onDown(e) {
        // Middle button → pan
        if (e.button === 1) {
            const [sx, sy] = this._svgXY(e);
            this._drag = { type: 'pan', sx, sy, vx0: this._vx, vy0: this._vy };
            e.preventDefault();
            return;
        }
        if (e.button !== 0) return;
        const [sx, sy] = this._svgXY(e);

        if (this.tool === 'select') {
            const idx = this._nearPoint(sx, sy);
            this._selected = idx;
            if (idx >= 0) {
                const [mx, my] = this._s2m(sx, sy);
                this._drag = { type: 'point', idx,
                    px0: this.pts[idx].x, py0: this.pts[idx].y };
            }
            this._dirty = true;
            return;
        }

        // Draw mode
        if (this.closed) return;
        const [mx, my] = this._s2m(sx, sy);
        const [snx, sny] = this._snap(mx, my);

        // Close if near first point
        if (this.pts.length >= 3) {
            const [fpx, fpy] = this._m2s(this.pts[0].x, this.pts[0].y);
            if ((fpx - sx) ** 2 + (fpy - sy) ** 2 < 144) {
                this._closePolygon();
                return;
            }
        }

        this.pts.push({ x: snx, y: sny });
        this._dirty = true;
        this.onChange?.(this.pts.map(p => [p.x, p.y]), false);
    }

    _onMove(e) {
        const [sx, sy] = this._svgXY(e);

        if (this._drag?.type === 'pan') {
            const dx = (sx - this._drag.sx) / this._scale;
            const dy = -(sy - this._drag.sy) / this._scale;
            this._vx = this._drag.vx0 - dx;
            this._vy = this._drag.vy0 - dy;
            this._dirty = true;
            return;
        }

        if (this._drag?.type === 'point') {
            const [mx, my] = this._s2m(sx, sy);
            const [snx, sny] = this._snap(mx, my);
            this.pts[this._drag.idx] = { x: snx, y: sny };
            this._dirty = true;
            this.onChange?.(this.pts.map(p => [p.x, p.y]), this.closed);
            return;
        }

        const prevHover = this._hover;
        this._hover = this._nearPoint(sx, sy);
        if (this.tool === 'draw' && !this.closed) {
            const [mx, my] = this._s2m(sx, sy);
            const [snx, sny] = this._snap(mx, my);
            this._preview = { x: snx, y: sny };
        } else {
            this._preview = null;
        }
        if (this._hover !== prevHover || this._preview) this._dirty = true;
    }

    _onUp(e) {
        if (this._drag?.type === 'point') {
            this.onChange?.(this.pts.map(p => [p.x, p.y]), this.closed);
        }
        this._drag = null;
    }

    _onDblClick(e) {
        if (this.tool === 'draw' && !this.closed && this.pts.length >= 3) {
            // Remove the extra point added by the first click of the dblclick
            this.pts.pop();
            this._closePolygon();
        }
    }

    _onWheel(e) {
        e.preventDefault();
        const [sx, sy] = this._svgXY(e);
        const [mx0, my0] = this._s2m(sx, sy);
        const factor = e.deltaY > 0 ? 0.85 : 1.18;
        this._scale = Math.max(8, Math.min(3000, this._scale * factor));
        const [mx1, my1] = this._s2m(sx, sy);
        this._vx -= mx1 - mx0;
        this._vy -= my1 - my0;
        // Auto-adjust snap grid
        this.gridSize = this._scale < 15 ? 5 : this._scale < 30 ? 2 : this._scale < 60 ? 1
            : this._scale < 150 ? 0.5 : this._scale < 400 ? 0.25 : 0.1;
        this._dirty = true;
    }

    _onRightClick(e) {
        if (this.tool === 'draw' && !this.closed && this.pts.length > 0) {
            this.pts.pop();
        } else if (this.tool === 'select' && this._selected >= 0 && this.pts.length > 3) {
            this.pts.splice(this._selected, 1);
            this._selected = -1;
            this.onChange?.(this.pts.map(p => [p.x, p.y]), this.closed);
        }
        this._dirty = true;
    }

    _onKey(e) {
        if (e.key === 'Escape') {
            if (!this.closed && this.pts.length > 0) this.pts.pop();
            this._selected = -1;
            this._dirty = true;
        }
        if ((e.key === 'Delete' || e.key === 'Backspace') && this._selected >= 0 && this.pts.length > 3) {
            this.pts.splice(this._selected, 1);
            this._selected = -1;
            if (this.closed && this.pts.length < 3) this.closed = false;
            this._dirty = true;
            this.onChange?.(this.pts.map(p => [p.x, p.y]), this.closed);
        }
    }

    _closePolygon() {
        this.closed = true;
        this._preview = null;
        this.tool = 'select';
        this.svg.style.cursor = 'default';
        this._dirty = true;
        this.onChange?.(this.pts.map(p => [p.x, p.y]), true);
    }

    // ── public API ────────────────────────────────────────────────

    setPolygon(pts) {
        this.pts = pts.map(([x, y]) => ({ x, y }));
        this.closed = true;
        this.tool = 'select';
        this.svg.style.cursor = 'default';
        this._selected = -1;
        this._fitView();
        this._dirty = true;
        this.onChange?.(pts, true);
    }

    clear() {
        this.pts = [];
        this.closed = false;
        this._preview = null;
        this._selected = -1;
        this._hover = -1;
        this.tool = 'draw';
        this.svg.style.cursor = 'crosshair';
        this._dirty = true;
        this.onChange?.([], false);
    }

    setTool(t) {
        this.tool = t;
        this.svg.style.cursor = (t === 'draw' && !this.closed) ? 'crosshair' : 'default';
        this._preview = null;
        this._dirty = true;
    }

    getPolygon() {
        return this.closed ? this.pts.map(p => [p.x, p.y]) : null;
    }

    // Mirror around vertical axis (left ↔ right)
    flipH() {
        if (!this.pts.length) return;
        const xs = this.pts.map(p => p.x);
        const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
        this.pts = this.pts.map(p => ({ x: 2 * cx - p.x, y: p.y }));
        this._dirty = true;
        this.onChange?.(this.pts.map(p => [p.x, p.y]), this.closed);
    }

    // Mirror around horizontal axis (top ↕ bottom)
    flipV() {
        if (!this.pts.length) return;
        const ys = this.pts.map(p => p.y);
        const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
        this.pts = this.pts.map(p => ({ x: p.x, y: 2 * cy - p.y }));
        this._dirty = true;
        this.onChange?.(this.pts.map(p => [p.x, p.y]), this.closed);
    }

    // Returns the current viewport state so the 3D viewer can match it exactly
    getViewState() {
        const r = this._rect();
        return {
            cx:   this._vx,
            cy:   this._vy,
            scale: this._scale,   // pixels per meter
            svgW: r.width,
            svgH: r.height,
        };
    }

    _fitView() {
        if (!this.pts.length) return;
        const xs = this.pts.map(p => p.x), ys = this.pts.map(p => p.y);
        const xmid = (Math.min(...xs) + Math.max(...xs)) / 2;
        const ymid = (Math.min(...ys) + Math.max(...ys)) / 2;
        const xspan = Math.max(Math.max(...xs) - Math.min(...xs), 0.1);
        const yspan = Math.max(Math.max(...ys) - Math.min(...ys), 0.1);
        const r = this._rect();
        const sx = r.width  * 0.65 / xspan;
        const sy = r.height * 0.65 / yspan;
        this._scale = Math.max(8, Math.min(3000, Math.min(sx, sy)));
        this._vx = xmid;
        this._vy = ymid;
        this.gridSize = this._scale < 15 ? 5 : this._scale < 30 ? 2 : this._scale < 60 ? 1
            : this._scale < 150 ? 0.5 : this._scale < 400 ? 0.25 : 0.1;
    }

    // ── render loop ───────────────────────────────────────────────

    _scheduleRender() {
        this._raf = requestAnimationFrame(() => {
            if (this._dirty) { this._render(); this._dirty = false; }
            this._scheduleRender();
        });
    }

    _render() {
        const r = this._rect();
        if (r.width === 0) return;
        const w = r.width, h = r.height;
        this._renderGrid(w, h);
        this._renderAxes(w, h);
        this._renderFill();
        this._renderEdges();
        this._renderDims();
        this._renderPoints();
        this._renderHint(w, h);
    }

    _renderGrid(w, h) {
        const g = this.gridSize, step5 = g * 5;
        const [x0] = this._s2m(0, h), [x1] = this._s2m(w, 0);
        const [, y0] = this._s2m(0, h), [, y1] = this._s2m(w, 0);
        const xi0 = Math.floor(x0 / g) * g, yi0 = Math.floor(y0 / g) * g;
        let html = '';
        for (let x = xi0; x <= x1 + g; x += g) {
            const sx = this._m2s(x, 0)[0].toFixed(1);
            const maj = Math.abs(((x / g) % 5 + 5) % 5) < 0.02;
            html += `<line x1="${sx}" y1="0" x2="${sx}" y2="${h}" stroke="${maj ? '#22293a' : '#161b24'}" stroke-width="${maj ? 0.8 : 0.4}"/>`;
        }
        for (let y = yi0; y <= y1 + g; y += g) {
            const sy = this._m2s(0, y)[1].toFixed(1);
            const maj = Math.abs(((y / g) % 5 + 5) % 5) < 0.02;
            html += `<line x1="0" y1="${sy}" x2="${w}" y2="${sy}" stroke="${maj ? '#22293a' : '#161b24'}" stroke-width="${maj ? 0.8 : 0.4}"/>`;
        }
        this._layers.grid.innerHTML = html;
    }

    _renderAxes(w, h) {
        const [ox, oy] = this._m2s(0, 0);
        let html = '';
        if (ox >= 0 && ox <= w) html += `<line x1="${ox.toFixed(1)}" y1="0" x2="${ox.toFixed(1)}" y2="${h}" stroke="#253040" stroke-width="1.5"/>`;
        if (oy >= 0 && oy <= h) html += `<line x1="0" y1="${oy.toFixed(1)}" x2="${w}" y2="${oy.toFixed(1)}" stroke="#253040" stroke-width="1.5"/>`;
        this._layers.axes.innerHTML = html;
    }

    _renderFill() {
        if (!this.closed || this.pts.length < 3) { this._layers.fill.innerHTML = ''; return; }
        const pts = this.pts.map(p => this._m2s(p.x, p.y).map(v => v.toFixed(1)).join(',')).join(' ');
        this._layers.fill.innerHTML = `<polygon points="${pts}" fill="rgba(61,158,255,0.10)" stroke="none"/>`;
    }

    _renderEdges() {
        const allPts = [...this.pts];
        if (this._preview && !this.closed) allPts.push(this._preview);

        let html = '';
        if (this.closed && this.pts.length >= 2) {
            const pts = this.pts.map(p => this._m2s(p.x, p.y).map(v => v.toFixed(1)).join(',')).join(' ');
            html += `<polygon points="${pts}" fill="none" stroke="#3d9eff" stroke-width="1.8"/>`;
        } else if (allPts.length >= 2) {
            const pts = allPts.map(p => this._m2s(p.x, p.y).map(v => v.toFixed(1)).join(',')).join(' ');
            html += `<polyline points="${pts}" fill="none" stroke="#3d9eff" stroke-width="1.8"/>`;
            if (this._preview && this.pts.length > 0) {
                const [lx, ly] = this._m2s(this.pts.at(-1).x, this.pts.at(-1).y);
                const [px, py] = this._m2s(this._preview.x, this._preview.y);
                html += `<line x1="${lx.toFixed(1)}" y1="${ly.toFixed(1)}" x2="${px.toFixed(1)}" y2="${py.toFixed(1)}" stroke="#3d9eff" stroke-width="1" stroke-dasharray="5,3" opacity="0.55"/>`;
            }
        }
        this._layers.edges.innerHTML = html;
    }

    _renderDims() {
        if (!this.closed || this.pts.length < 2) { this._layers.dims.innerHTML = ''; return; }
        let html = '';
        const n = this.pts.length;
        for (let i = 0; i < n; i++) {
            const a = this.pts[i], b = this.pts[(i + 1) % n];
            const len = Math.hypot(b.x - a.x, b.y - a.y);
            if (len < 0.05) continue;
            const [sax, say] = this._m2s(a.x, a.y);
            const [sbx, sby] = this._m2s(b.x, b.y);
            const mx = (sax + sbx) / 2, my = (say + sby) / 2;
            const dx = sbx - sax, dy = sby - say;
            const nl = Math.hypot(dx, dy);
            const nx = -dy / nl * 13, ny = dx / nl * 13;
            const label = len >= 1 ? `${len.toFixed(2)}m` : `${(len * 100).toFixed(1)}cm`;
            const angle = (Math.atan2(dy, dx) * 180 / Math.PI).toFixed(1);
            const tx = (mx + nx).toFixed(1), ty = (my + ny).toFixed(1);
            html += `<text x="${tx}" y="${ty}" text-anchor="middle" dominant-baseline="middle" font-size="10" font-family="JetBrains Mono,monospace" fill="#4a5a6e" transform="rotate(${angle},${tx},${ty})">${label}</text>`;
        }
        this._layers.dims.innerHTML = html;
    }

    _renderPoints() {
        let html = '';
        const nearFirst = !this.closed && this.pts.length >= 3 && this._preview && (() => {
            const [fx, fy] = this._m2s(this.pts[0].x, this.pts[0].y);
            const [px, py] = this._m2s(this._preview.x, this._preview.y);
            return Math.hypot(fx - px, fy - py) < 14;
        })();

        for (let i = 0; i < this.pts.length; i++) {
            const [sx, sy] = this._m2s(this.pts[i].x, this.pts[i].y);
            const isSel = i === this._selected;
            const isHov = i === this._hover;
            const isClose = i === 0 && nearFirst;
            const r = isSel || isHov ? 6 : 4.5;
            const fill = isClose ? '#00e5b0' : isSel ? '#ff6b35' : isHov ? '#7ebbff' : '#3d9eff';
            html += `<circle cx="${sx.toFixed(1)}" cy="${sy.toFixed(1)}" r="${r}" fill="${fill}" stroke="#0d0f14" stroke-width="1.5"/>`;
            if (isClose) {
                html += `<circle cx="${sx.toFixed(1)}" cy="${sy.toFixed(1)}" r="13" fill="none" stroke="#00e5b0" stroke-width="1" stroke-dasharray="3,2" opacity="0.7"/>`;
            }
        }
        if (this._preview && !this.closed) {
            const [px, py] = this._m2s(this._preview.x, this._preview.y);
            html += `<circle cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="3" fill="#3d9eff" opacity="0.4"/>`;
        }
        this._layers.pts.innerHTML = html;
    }

    _renderHint(w, h) {
        let html = '';
        if (this._preview) {
            html += `<text x="10" y="${h - 10}" font-size="11" font-family="JetBrains Mono,monospace" fill="#445566">${this._preview.x.toFixed(2)} / ${this._preview.y.toFixed(2)} m</text>`;
        }
        const msg = !this.closed
            ? (this.pts.length === 0
                ? 'Klicken = Punkt setzen  ·  Scroll = Zoom  ·  Mitteltaste = Pan'
                : this.pts.length < 3
                ? `${this.pts.length} Punkt${this.pts.length > 1 ? 'e' : ''}  ·  Rechtsklick = letzten löschen  ·  Esc = abbrechen`
                : 'Doppelklick oder ersten Punkt anklicken zum Schließen')
            : 'Polygon geschlossen  ·  Punkte ziehen zum Anpassen  ·  Rechtsklick = Punkt löschen';
        html += `<text x="${w / 2}" y="${h - 10}" text-anchor="middle" font-size="11" font-family="Barlow Condensed,sans-serif" fill="#3a4a5a">${msg}</text>`;
        this._layers.hint.innerHTML = html;
    }

    destroy() {
        if (this._raf) cancelAnimationFrame(this._raf);
        this._raf = null;
    }
}
