// cfd-testcases.js — Predefined cross-section test cases for CFD analysis
// Based on common bridge deck geometries and Dolfyn examples

export const CFD_TEST_CASES = [
    {
        name: "Flat rectangle 10:1",
        desc: "Classic bridge-deck cross-section, B/H = 10",
        polygon: [[0, 0], [5, 0], [5, 0.5], [0, 0.5]],
        windSpeed: 20,
        meshSize: 0.15,
        farField: 15,
        expected: { cD: "~0.1-0.2", cL: "~0", cM: "~0" },
    },
    {
        name: "Square",
        desc: "Bluff cross-section, strong vortex shedding",
        polygon: [[0, 0], [1, 0], [1, 1], [0, 1]],
        windSpeed: 20,
        meshSize: 0.05,
        farField: 20,
        expected: { cD: "~2.0", cL: "~0", cM: "~0" },
    },
    {
        name: "Box girder narrow",
        desc: "Typical motorway-bridge box girder",
        polygon: [
            [0, 0], [12, 0], [12, 0.25], [11, 0.25],
            [10.5, 2.5], [1.5, 2.5], [1, 0.25], [0, 0.25],
        ],
        windSpeed: 25,
        meshSize: 0.3,
        farField: 15,
        expected: { cD: "~0.1-0.3", cL: "~0.1-0.5", cM: "~0.05" },
    },
    {
        name: "Box girder wide",
        desc: "Wide box girder with wind fairings",
        polygon: [
            [-1, 0], [0, -0.5], [14, -0.5], [15, 0],
            [15, 0.3], [14, 0.3], [13, 3], [2, 3],
            [1, 0.3], [0, 0.3], [-1, 0.3],
        ],
        windSpeed: 30,
        meshSize: 0.3,
        farField: 12,
        expected: { cD: "~0.05-0.15", cL: "variable", cM: "~0.02" },
    },
    {
        name: "T-beam",
        desc: "T-shaped T-beam cross-section",
        polygon: [
            [0, 0], [8, 0], [8, 0.3],
            [5.5, 0.3], [5.5, 2], [2.5, 2],
            [2.5, 0.3], [0, 0.3],
        ],
        windSpeed: 20,
        meshSize: 0.15,
        farField: 15,
        expected: { cD: "~0.5-1.0", cL: "~0.2-0.5", cM: "~0.1-0.3" },
    },
    {
        name: "Double-T steel girder",
        desc: "I-profile, open section",
        polygon: [
            [0, 0], [3, 0], [3, 0.2],
            [1.8, 0.2], [1.8, 1.8], [3, 1.8],
            [3, 2], [0, 2], [0, 1.8],
            [1.2, 1.8], [1.2, 0.2], [0, 0.2],
        ],
        windSpeed: 20,
        meshSize: 0.08,
        farField: 20,
        expected: { cD: "~1.5-2.0", cL: "~0.5", cM: "~0.3" },
    },
    {
        name: "Circular cylinder",
        desc: "Reference: Re-dependent cD (~1.2 at Re>10^5)",
        polygon: (() => {
            const pts = [];
            const n = 64;
            for (let i = 0; i < n; i++) {
                const a = 2 * Math.PI * i / n;
                pts.push([0.5 * Math.cos(a), 0.5 * Math.sin(a)]);
            }
            return pts;
        })(),
        windSpeed: 15,
        meshSize: 0.03,
        farField: 25,
        expected: { cD: "~1.0-1.2", cL: "~0 (mean)", cM: "~0" },
    },
    {
        name: "Cable-stayed bridge deck",
        desc: "Aerodynamically optimised deck with wind fairings",
        polygon: [
            [-0.5, 0], [0, -0.3], [15, -0.3], [15.5, 0],
            [15.5, 0.15], [15, 0.15], [14.5, 0.8],
            [0.5, 0.8], [0, 0.15], [-0.5, 0.15],
        ],
        windSpeed: 30,
        meshSize: 0.2,
        farField: 12,
        expected: { cD: "~0.05-0.1", cL: "~0.1", cM: "~0.02" },
    },
    {
        name: "Triangle",
        desc: "Sharp cross-section — asymmetric flow",
        polygon: [[0, 0], [4, 0], [2, 3]],
        windSpeed: 20,
        meshSize: 0.15,
        farField: 15,
        expected: { cD: "~1.5", cL: "~0.5", cM: "~0.3" },
    },

    // ── SOFiSTiK/Dolfyn examples ──────────────────────────
    {
        name: "Harbour Bridge Deck (Dolfyn)",
        desc: "Sydney Harbour Bridge cross-section, B=22.95m, H=3.75m, α=0°",
        polygon: [
            [0.66, 0], [0.66, -1], [0.83, -1], [1, 0],
            [11, 0.2], [11.17, -0.8], [11.34, -0.8], [11.34, 0.48],
            [6.7, 0.75], [3.6, 3.75],
            [-3.6, 3.75], [-6.7, 0.75],
            [-11.34, 0.48], [-11.34, -0.8], [-11.17, -0.8], [-11, 0.2],
            [-1, 0], [-0.83, -1], [-0.66, -1], [-0.66, 0],
        ],
        windSpeed: 34,
        meshSize: 0.3,
        farField: 12,
        expected: { cD: "Dolfyn ref", cL: "Dolfyn ref", cM: "Dolfyn ref" },
    },
    {
        name: "RUB Bridge Deck (Dolfyn)",
        desc: "Ruhr University wind-tunnel model, trapezoidal. SOFiSTiK parity: U=5 m/s, ν=1.373e-5, k-ω SST, EPS length scale 20mm. For α=4° set windAngle=4.",
        polygon: [
            [-0.142, 0.031], [-0.183, 0.005], [-0.103, -0.035],
            [0.103, -0.035], [0.183, 0.005], [0.142, 0.031],
        ],
        windSpeed: 5.0,
        meshSize: 0.005,
        farField: 25,
        // SOFiSTiK/Dolfyn-identical input parameters (rub_bridge.dat) for the cross-check
        nu: 1.373e-5,
        turbulenceIntensity: 0.03,
        turbulenceModel: 'kOmegaSST',
        turbulenceLengthScale: 0.02,
        // Reference (rub_bridge.dat): Exp cd/cl/cm @α=4° = 0.095 / 0.380 / 0.109
        expected: { cD: "0.095 (Exp, α=4°)", cL: "0.380 (Exp, α=4°)", cM: "0.109 (Exp, α=4°)" },
    },
    {
        name: "Vortex T-profile (Dolfyn)",
        desc: "T-profile for Kármán vortex shedding, B/D=2",
        polygon: [
            [-0.25, 0], [-0.25, 5], [0.25, 5], [0.25, 0],
            [10, 0], [10, -0.5], [-10, -0.5], [-10, 0],
        ],
        windSpeed: 20,
        meshSize: 0.2,
        farField: 15,
        expected: { cD: "~1.5-2", cL: "oscillating", cM: "oscillating" },
    },
    {
        name: "Vortex Double-T (Dolfyn)",
        desc: "Double-T profile for Kármán vortex shedding, B/D=2",
        polygon: [
            [0, 0.25], [9.75, 0.25], [9.75, 5], [10.25, 5],
            [10.25, -5], [9.75, -5], [9.75, -0.25],
            [0, -0.25], [-9.75, -0.25], [-9.75, -5],
            [-10.25, -5], [-10.25, 5], [-9.75, 5], [-9.75, 0.25],
        ],
        windSpeed: 20,
        meshSize: 0.3,
        farField: 12,
        expected: { cD: "~1.5", cL: "oscillating", cM: "oscillating" },
    },
    {
        name: "Millau viaduct (Dolfyn)",
        desc: "Millau viaduct deck, aerodynamic profile",
        polygon: [
            [-16, 0], [-16.5, -0.5], [-16.5, -1.5], [-14, -4.5],
            [14, -4.5], [16.5, -1.5], [16.5, -0.5], [16, 0],
        ],
        windSpeed: 40,
        meshSize: 0.5,
        farField: 10,
        expected: { cD: "~0.05-0.1", cL: "~0.1", cM: "~0.02" },
    },

    // ── Dolfyn buildings 3D — footprints ──────────────────────────
    {
        name: "AIJ Hochhaus T114 (Dolfyn 3D)",
        desc: "AIJ Evaluation Example T114-4c, square 10×10m, H=40m",
        mode: '3d',
        height: 40,
        z0: 0.1,
        polygon: [[-5, -5], [5, -5], [5, 5], [-5, 5]],
        windSpeed: 6.75,
        meshSize: 3.0,
        farField: 15,
        expected: { cD: "~1.0-1.4", cL: "~0", cM: "Dolfyn ref" },
    },
    {
        name: "Baines tall building (Dolfyn 3D)",
        desc: "Tall building Baines, square 19.7×19.7m, H=160m, Re~2×10⁷",
        mode: '3d',
        height: 160,
        z0: 0.3,
        polygon: [[-9.86, -9.86], [9.86, -9.86], [9.86, 9.86], [-9.86, 9.86]],
        windSpeed: 25,
        meshSize: 10.0,
        farField: 15,
        expected: { cD: "Dolfyn ref", cL: "Dolfyn ref", cM: "Dolfyn ref" },
    },
    {
        name: "Cylindrical tall building (Dolfyn 3D)",
        desc: "Park/Lee cylinder D=30m, H=180m, boundary-layer inflow",
        mode: '3d',
        height: 180,
        z0: 0.3,
        polygon: (() => {
            const pts = [];
            const n = 48;
            for (let i = 0; i < n; i++) {
                const a = 2 * Math.PI * i / n;
                pts.push([15 * Math.cos(a), 15 * Math.sin(a)]);
            }
            return pts;
        })(),
        windSpeed: 25,
        meshSize: 10.0,
        farField: 15,
        expected: { cD: "~0.4-0.7", cL: "~0 (mean)", cM: "~0" },
    },
    {
        name: "L-shaped building (3D)",
        desc: "L-shaped footprint 30×30m, leg width 10m, H=25m",
        mode: '3d',
        height: 25,
        z0: 0.1,
        polygon: [[-15, -15], [15, -15], [15, -5], [-5, -5], [-5, 15], [-15, 15]],
        windSpeed: 15,
        meshSize: 2.0,
        farField: 15,
        expected: { cD: "~1.0-1.5", cL: "variable", cM: "variable" },
    },
    {
        name: "Slender tall building (3D)",
        desc: "Generic tall building 20×20×120m, aspect ratio 6:1",
        mode: '3d',
        height: 120,
        z0: 0.1,
        polygon: [[-10, -10], [10, -10], [10, 10], [-10, 10]],
        windSpeed: 20,
        meshSize: 8.0,
        farField: 15,
        expected: { cD: "~1.0-1.3", cL: "~0", cM: "Dolfyn ref" },
    },

    // ── Multi-building urban district ─────────────────────────────
    {
        name: "Urban district (5 buildings)",
        desc: "Mini district: tall building, L-shaped building, 2 residential blocks, round building — pedestrian comfort",
        mode: '3d',
        height: 40,  // reference height (tallest building)
        z0: 0.3,
        buildings: [
            // Slender tall building (tower, centre)
            { footprint: [[-5, -5], [5, -5], [5, 5], [-5, 5]], height: 80 },
            // L-shaped building (northwest)
            { footprint: [[-60, 30], [-30, 30], [-30, 40], [-50, 40], [-50, 60], [-60, 60]], height: 25 },
            // Residential block 1 (southwest)
            { footprint: [[-55, -50], [-25, -50], [-25, -40], [-55, -40]], height: 18 },
            // Residential block 2 (southeast)
            { footprint: [[25, -55], [60, -55], [60, -40], [25, -40]], height: 22 },
            // Cylindrical building (northeast)
            { footprint: (() => {
                const pts = [];
                const n = 40;
                for (let i = 0; i < n; i++) {
                    const a = 2 * Math.PI * i / n;
                    pts.push([45 + 12 * Math.cos(a), 40 + 12 * Math.sin(a)]);
                }
                return pts;
            })(), height: 30 },
        ],
        // polygon = bounding box for backward compat (preview)
        polygon: [[-5, -5], [5, -5], [5, 5], [-5, 5]],
        windSpeed: 12,
        meshSize: 5.0,
        farField: 15,
        expected: { cD: "multi-building", cL: "variable", cM: "variable" },
    },

    // ── OpenFOAM validation case ────────────────────────────────
    {
        name: "Cube Martinuzzi & Tropea (3D)",
        desc: "Surface-mounted cube, channel flow, Re_H=40000 (Martinuzzi & Tropea 1993)",
        mode: '3d',
        height: 1,
        z0: 0,
        flowType: 'channel',
        polygon: [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]],
        windSpeed: 0.6,   // Re_H = U_H·H/ν = 0.6·1/1.5e-5 = 40 000
        meshSize: 0.06,
        farField: 4,
        expected: { cD: "~1.0–1.4", cL: "~0", cM: "~0" },
    },

    // ── Dolfyn buildings 2D ───────────────────────────────────────
    {
        name: "Two houses (Dolfyn 2D)",
        desc: "Two gable-roof houses with spacing at ground, v=25 m/s",
        grounded: true,
        // Open chain: left ground point → over house 1 → ground in between → over house 2 → right ground point
        polygon: [
            [8, 0], [8, 4], [12, 6], [16, 4], [16, 0],
            [24, 0], [24, 4], [28, 6], [32, 4], [32, 0],
        ],
        windSpeed: 25,
        meshSize: 0.3,
        farField: 12,
        expected: { cD: "Dolfyn ref", cL: "Dolfyn ref", cM: "Dolfyn ref" },
    },
    {
        name: "Noise barrier (Dolfyn 2D)",
        desc: "Noise barrier with acoustic shell at ground, v=16.2 m/s",
        grounded: true,
        // Open chain from the left ground point over the wall to the right ground point (y=0)
        polygon: [
            [0, 0], [0, 0.8], [1.53, 1.683], [2.1, 1.683],
            [2.1, 2.984], [1.53, 2.984], [1.021, 2.5],
            [0.057, 8.923], [0.156, 9.0],
            [1.715, 4.0], [2.7, 4.0], [2.7, 0],
        ],
        windSpeed: 16.17,
        meshSize: 0.1,
        farField: 15,
        expected: { cD: "Dolfyn ref", cL: "Dolfyn ref", cM: "Dolfyn ref" },
    },
    {
        name: "Airrail shell (Dolfyn 2D)",
        desc: "Airrail outer shell at ground, oval cross-section, B≈56m, H≈23.5m",
        grounded: true,
        // Open chain (upper arc) from the left to the right ground point (y=0); lower edge = ground
        polygon: [
            [-25.42, 0], [-25.94, 1.77], [-26.70, 4.02], [-27.34, 6.34],
            [-27.83, 8.88], [-28.08, 11.23], [-27.98, 13.37], [-27.59, 15.57],
            [-26.66, 17.42], [-25.48, 19.06], [-23.91, 20.31], [-21.86, 21.51],
            [-19.46, 22.41], [-16.66, 22.96], [-13.68, 23.26], [-10.89, 23.31],
            [-8.00, 23.36], [-5.50, 23.41], [-2.61, 23.46],
            [0, 23.46],
            [2.61, 23.46], [5.50, 23.41], [8.00, 23.36], [10.89, 23.31],
            [13.68, 23.26], [16.66, 22.96], [19.46, 22.41], [21.86, 21.51],
            [23.91, 20.31], [25.48, 19.06], [26.66, 17.42], [27.59, 15.57],
            [27.98, 13.37], [28.08, 11.23], [27.83, 8.88], [27.34, 6.34],
            [26.70, 4.02], [25.94, 1.77], [25.42, 0],
        ],
        windSpeed: 20,
        meshSize: 0.5,
        farField: 12,
        expected: { cD: "~0.3-0.5", cL: "~0.1", cM: "Dolfyn ref" },
    },

    // ── OpenFOAM validation case 2D ─────────────────────────────
    {
        name: "NACA0012 (2D)",
        desc: "Airfoil c=1m, Re=6×10⁶. Angle of attack = angle of attack α. (Gregory & O'Reilly 1970)",
        polygon: (() => {
            const N = 40;
            const yt = x => (0.12 / 0.2) * (
                0.2969 * Math.sqrt(x)
                - 0.126  * x
                - 0.3516 * x * x
                + 0.2843 * x * x * x
                - 0.1015 * x * x * x * x
            );
            const r = v => Math.round(v * 1e4) / 1e4;
            const pts = [];
            // Upper surface: LE (i=0) → TE (i=N), cosine spacing
            for (let i = 0; i <= N; i++) {
                const x = (1 - Math.cos(Math.PI * i / N)) / 2;
                pts.push([r(x),  r(yt(x))]);
            }
            // Lower surface: TE (i=N) → near-LE (i=1), skip LE to avoid duplicate
            for (let i = N; i >= 1; i--) {
                const x = (1 - Math.cos(Math.PI * i / N)) / 2;
                pts.push([r(x), -r(yt(x))]);
            }
            return pts;
        })(),
        windSpeed: 90,    // Re = U·c/ν = 90·1/1.5e-5 = 6×10⁶
        meshSize: 0.02,
        farField: 20,
        structured: true,
        expected: { cD: "~0.006–0.008", cL: "~0 (α=0°)", cM: "~0" },
    },

    // ── Stall study: cambered aircraft airfoil ──
    {
        name: "NACA4412 airfoil (2D)",
        desc: "Cambered aircraft airfoil c=1m, Re≈3.3×10⁶. Angle of attack = angle of attack α — for stall study sweep 0…18°; enable transient (end time ~0.2s, Δt 0.001s; time step is automatically reduced under the Courant limit). Stall ~15°. (Abbott & von Doenhoff)",
        polygon: (() => {
            // NACA 4-digit 4412: max. camber m=4%, camber position p=0.4, thickness t=12%
            const m = 0.04, p = 0.4, t = 0.12;
            const N = 60;
            // Thickness distribution (symmetric about the camber line)
            const yt = x => (t / 0.2) * (
                0.2969 * Math.sqrt(x)
                - 0.126  * x
                - 0.3516 * x * x
                + 0.2843 * x * x * x
                - 0.1015 * x * x * x * x
            );
            // Camber line yc and its slope dyc/dx
            const yc  = x => x < p
                ? (m / (p * p)) * (2 * p * x - x * x)
                : (m / ((1 - p) * (1 - p))) * ((1 - 2 * p) + 2 * p * x - x * x);
            const dyc = x => x < p
                ? (2 * m / (p * p)) * (p - x)
                : (2 * m / ((1 - p) * (1 - p))) * (p - x);
            const r = v => Math.round(v * 1e4) / 1e4;
            // Upper surface (xu,yu) and lower surface (xl,yl) offset perpendicular to the camber line
            const upper = x => { const th = Math.atan(dyc(x)), d = yt(x);
                return [r(x - d * Math.sin(th)), r(yc(x) + d * Math.cos(th))]; };
            const lower = x => { const th = Math.atan(dyc(x)), d = yt(x);
                return [r(x + d * Math.sin(th)), r(yc(x) - d * Math.cos(th))]; };
            const pts = [];
            // Upper surface: LE (i=0) → TE (i=N), cosine spacing
            for (let i = 0; i <= N; i++) {
                const x = (1 - Math.cos(Math.PI * i / N)) / 2;
                pts.push(upper(x));
            }
            // Lower surface: TE (i=N) → near-LE (i=1), skip LE (no duplicate)
            for (let i = N; i >= 1; i--) {
                const x = (1 - Math.cos(Math.PI * i / N)) / 2;
                pts.push(lower(x));
            }
            return pts;
        })(),
        windSpeed: 50,    // Re = U·c/ν = 50·1/1.5e-5 ≈ 3.3×10⁶
        meshSize: 0.02,
        farField: 25,     // larger outer domain: stalling wake stays within the domain
        structured: true,
        expected: { cD: "~0.007 (α=0°)", cL: "~0.45 (α=0°), cL,max≈1.5 at α≈15°", cM: "~-0.1" },
    },
];
