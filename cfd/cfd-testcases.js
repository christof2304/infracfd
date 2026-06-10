// cfd-testcases.js — Predefined cross-section test cases for CFD analysis
// Based on common bridge deck geometries and Dolfyn examples

export const CFD_TEST_CASES = [
    {
        name: "Flaches Rechteck 10:1",
        desc: "Klassischer Brückendecks-Querschnitt, B/H = 10",
        polygon: [[0, 0], [5, 0], [5, 0.5], [0, 0.5]],
        windSpeed: 20,
        meshSize: 0.15,
        farField: 15,
        expected: { cD: "~0.1-0.2", cL: "~0", cM: "~0" },
    },
    {
        name: "Quadrat",
        desc: "Stumpfer Querschnitt, starke Wirbelablösung",
        polygon: [[0, 0], [1, 0], [1, 1], [0, 1]],
        windSpeed: 20,
        meshSize: 0.05,
        farField: 20,
        expected: { cD: "~2.0", cL: "~0", cM: "~0" },
    },
    {
        name: "Hohlkasten schmal",
        desc: "Typischer Autobahnbrücken-Hohlkasten",
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
        name: "Hohlkasten breit",
        desc: "Breiter Hohlkasten mit Windnasen",
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
        name: "Plattenbalken T",
        desc: "T-förmiger Plattenbalken-Querschnitt",
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
        name: "Doppel-T Stahlträger",
        desc: "I-Profil, offener Querschnitt",
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
        name: "Kreiszylinder",
        desc: "Referenz: Re-abhängiger cD (~1.2 bei Re>10^5)",
        polygon: (() => {
            const pts = [];
            const n = 32;
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
        name: "Seilbrücken-Deck",
        desc: "Aerodynamisch optimiertes Deck mit Windnasen",
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
        name: "Dreieck",
        desc: "Spitzer Querschnitt — asymmetrische Umströmung",
        polygon: [[0, 0], [4, 0], [2, 3]],
        windSpeed: 20,
        meshSize: 0.15,
        farField: 15,
        expected: { cD: "~1.5", cL: "~0.5", cM: "~0.3" },
    },

    // ── SOFiSTiK/Dolfyn Beispiele ──────────────────────────
    {
        name: "Harbour Bridge Deck (Dolfyn)",
        desc: "Sydney Harbour Bridge Querschnitt, B=22.95m, H=3.75m, α=0°",
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
        desc: "Ruhr-Universität Windkanal-Modell, trapezförmig, α=4°",
        polygon: [
            [-0.142, 0.031], [-0.183, 0.005], [-0.103, -0.035],
            [0.103, -0.035], [0.183, 0.005], [0.142, 0.031],
        ],
        windSpeed: 15,
        meshSize: 0.005,
        farField: 25,
        expected: { cD: "Dolfyn ref", cL: "Dolfyn ref", cM: "Dolfyn ref" },
    },
    {
        name: "Vortex T-Profil (Dolfyn)",
        desc: "T-Profil für Kármán-Wirbelablösung, B/D=2",
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
        name: "Vortex Doppel-T (Dolfyn)",
        desc: "Doppel-T Profil für Kármán-Wirbelablösung, B/D=2",
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
        name: "Millau-Viadukt (Dolfyn)",
        desc: "Millau-Viadukt Deck, aerodynamisches Profil",
        polygon: [
            [-16, 0], [-16.5, -0.5], [-16.5, -1.5], [-14, -4.5],
            [14, -4.5], [16.5, -1.5], [16.5, -0.5], [16, 0],
        ],
        windSpeed: 40,
        meshSize: 0.5,
        farField: 10,
        expected: { cD: "~0.05-0.1", cL: "~0.1", cM: "~0.02" },
    },

    // ── Dolfyn Gebäude 3D — Grundrisse ──────────────────────────
    {
        name: "AIJ Hochhaus T114 (Dolfyn 3D)",
        desc: "AIJ Evaluation Example T114-4c, quadratisch 10×10m, H=40m",
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
        name: "Hochhaus Baines (Dolfyn 3D)",
        desc: "Tall building Baines, quadratisch 19.7×19.7m, H=160m, Re~2×10⁷",
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
        name: "Zylindrisches Hochhaus (Dolfyn 3D)",
        desc: "Park/Lee Zylinder D=30m, H=180m, Grenzschicht-Anströmung",
        mode: '3d',
        height: 180,
        z0: 0.3,
        polygon: (() => {
            const pts = [];
            const n = 24;
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
        name: "L-Gebäude (3D)",
        desc: "L-förmiger Grundriss 30×30m, Schenkelbreite 10m, H=25m",
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
        name: "Schlankes Hochhaus (3D)",
        desc: "Generisches Hochhaus 20×20×120m, Seitenverhältnis 6:1",
        mode: '3d',
        height: 120,
        z0: 0.1,
        polygon: [[-10, -10], [10, -10], [10, 10], [-10, 10]],
        windSpeed: 20,
        meshSize: 8.0,
        farField: 15,
        expected: { cD: "~1.0-1.3", cL: "~0", cM: "Dolfyn ref" },
    },

    // ── Multi-Building Stadtquartier ─────────────────────────────
    {
        name: "Stadtquartier (5 Gebäude)",
        desc: "Mini-Quartier: Hochhaus, L-Gebäude, 2 Wohnblöcke, Rundbau — Fußgängerkomfort",
        mode: '3d',
        height: 40,  // reference height (tallest building)
        z0: 0.3,
        buildings: [
            // Schlankes Hochhaus (Turm, Zentrum)
            { footprint: [[-5, -5], [5, -5], [5, 5], [-5, 5]], height: 80 },
            // L-Gebäude (Nordwest)
            { footprint: [[-60, 30], [-30, 30], [-30, 40], [-50, 40], [-50, 60], [-60, 60]], height: 25 },
            // Wohnblock 1 (Südwest)
            { footprint: [[-55, -50], [-25, -50], [-25, -40], [-55, -40]], height: 18 },
            // Wohnblock 2 (Südost)
            { footprint: [[25, -55], [60, -55], [60, -40], [25, -40]], height: 22 },
            // Zylindrischer Bau (Nordost)
            { footprint: (() => {
                const pts = [];
                for (let i = 0; i < 16; i++) {
                    const a = 2 * Math.PI * i / 16;
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

    // ── Dolfyn Gebäude 2D ───────────────────────────────────────
    {
        name: "Zwei Häuser (Dolfyn 2D)",
        desc: "Zwei Satteldach-Häuser mit Abstand, v=25 m/s",
        polygon: [
            [8, 0], [8, 4], [12, 6], [16, 4], [16, 0],
            [20, 0], [24, 0], [24, 4], [28, 6], [32, 4], [32, 0],
        ],
        windSpeed: 25,
        meshSize: 0.3,
        farField: 12,
        expected: { cD: "Dolfyn ref", cL: "Dolfyn ref", cM: "Dolfyn ref" },
    },
    {
        name: "Lärmschutzwand (Dolfyn 2D)",
        desc: "Lärmschutzwand mit Bohrpfahl und Schallschutzschale, v=16.2 m/s",
        polygon: [
            [0, 0], [0, 0.8], [1.53, 1.683], [2.1, 1.683],
            [2.1, 2.984], [1.53, 2.984], [1.021, 2.5],
            [0.057, 8.923], [0.156, 9.0],
            [1.715, 4.0], [2.7, 4.0], [2.7, -0.4],
        ],
        windSpeed: 16.17,
        meshSize: 0.1,
        farField: 15,
        expected: { cD: "Dolfyn ref", cL: "Dolfyn ref", cM: "Dolfyn ref" },
    },
    {
        name: "Doppel-Lärmschutzwand (Dolfyn 2D)",
        desc: "Zwei Lärmschutzwände beidseitig der Autobahn, B=35m",
        polygon: [
            // Rechte Wand (x=+17.5)
            [17.5, 0], [17.5, 0.8], [19.03, 1.683], [19.6, 1.683],
            [19.6, 2.984], [19.03, 2.984], [18.521, 2.5],
            [17.557, 8.923], [17.656, 9.0],
            [19.215, 4.0], [20.2, 4.0], [20.2, -0.4],
        ],
        windSpeed: 16.17,
        meshSize: 0.15,
        farField: 12,
        expected: { cD: "Dolfyn ref", cL: "Dolfyn ref", cM: "Dolfyn ref" },
    },
    {
        name: "Airrail-Hülle (Dolfyn 2D)",
        desc: "Airrail Außenhülle, ovale Querschnittsform, B≈56m, H≈23.5m",
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
];
