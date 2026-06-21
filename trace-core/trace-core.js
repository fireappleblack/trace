// flatten:begin
// repo-path: trace-core/trace-core.js
// generated: 2026-06-21T17:35:52Z by flatten.py — do not edit this block
// flatten:end

// trace-core.js — shared game-logic core for Trace.
// GENERATED from ../trace.html by extract_core.js (verbatim function bodies).
// Loaded by trace.html (browser) and admin.html, and importable by Node.
// No DOM, no localStorage — driven entirely by a spec.
//
//   TraceCore.generate(spec)       -> { sol, waypoints, walls:Set, blocked:[], bx, rows, cols, sizeToken, sig }
//   TraceCore.enumerate(spec, cap) -> { count, found:[paths], aborted }
//   TraceCore.signatureFor(spec)   -> string
//   TraceCore.solutionWriggliness/pathWiggliness/decisionDensity/solve/makeRNG/...
//   spec = { rows, cols, difficulty, wiggle, walls, points, twoPen, seed, bx }
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.TraceCore = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  let ROWS = 6, COLS = 6, SEED = '', DIFFICULTY = 'tricky';
  let WIGGLE = 2, WALLS = 0, POINTS = 0, TWO_PEN = false;
  let BX = -1, BLOCKED = new Set();
  let solution = [], waypoints = [], walls = new Set();
  let rng = Math.random, genWiggle = null, genNodes = 0;
  let _COLLECT = 2;   // solve(): max stored solutions (2 = verbatim default)

  // ───────────── verbatim engine (sliced from trace.html) ─────────────
function sizeToken() { return (ROWS === COLS) ? COLS : (ROWS * 10 + COLS); }
const DIFFS = ['gentle', 'tricky', 'knotty', 'fiendish'];

// Waypoint count per difficulty, scaled by grid area.
// Fewer waypoints = more freedom = harder for both solver and human.
// Larger grids get a slightly higher floor so uniqueness enforcement
// stays tractable.
function targetWaypoints(diff, area) {
  const ratios = { gentle: 0.22, tricky: 0.16, knotty: 0.12, fiendish: 0.095 };
  return Math.max(4, Math.round(area * ratios[diff]));
}

// Difficulty band thresholds (solver nodes), per grid size.
// Calibrated against actual generation distributions — what a 5×5
// can produce is fundamentally less spread out than what an 8×8 can,
// so a single formula misrepresents both ends.
function bandsForArea(area) {
  const table = {
    25: { gentle: [0, 100],   tricky: [100, 200],     knotty: [200, 500],      fiendish: [500, Infinity] },
    36: { gentle: [0, 300],   tricky: [300, 700],     knotty: [700, 1500],     fiendish: [1500, Infinity] },
    49: { gentle: [0, 700],   tricky: [700, 1800],    knotty: [1800, 4500],    fiendish: [4500, Infinity] },
    64: { gentle: [0, 4000],  tricky: [4000, 12000],  knotty: [12000, 35000],  fiendish: [35000, Infinity] }
  };
  if (table[area]) return table[area];
  // Fallback for unusual sizes — interpolate via a power law.
  const u = Math.pow(area, 2.2);
  return { gentle: [0, u*0.05], tricky: [u*0.05, u*0.2], knotty: [u*0.2, u*1.0], fiendish: [u*1.0, Infinity] };
}

function classify(nodes, area) {
  const b = bandsForArea(area);
  for (const d of DIFFS) if (nodes >= b[d][0] && nodes < b[d][1]) return d;
  return 'fiendish';
}

// ─── State ──────────────────────────────────────────
function xmur3(str) {
  let h = 1779033703 ^ str.length;
  for (let i = 0; i < str.length; i++) {
    h = Math.imul(h ^ str.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  return function() {
    h = Math.imul(h ^ (h >>> 16), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    return (h ^= h >>> 16) >>> 0;
  };
}
function mulberry32(a) {
  return function() {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function makeRNG(seedStr) {
  const h = xmur3(String(seedStr));
  return mulberry32(h());
}
const k = (r, c) => r + ',' + c;
const wk = (r1, c1, r2, c2) => {
  if (r1 < r2 || (r1 === r2 && c1 < c2)) return r1 + ',' + c1 + '|' + r2 + ',' + c2;
  return r2 + ',' + c2 + '|' + r1 + ',' + c1;
};
const isAdj = (a, b) => Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]) === 1;

// ─── Blanked-off cells ──────────────────────────────
// Cells removed from play, to break the board's symmetry so the rectangle's own
// rotations/reflections can't mint mirror-image "twin" solutions.
//   One-pen: a single blank placed at seeded-random inside the bottom-left
//     quadrant (bottom ⌊R/2⌋ rows × left ⌊C/2⌋ cols — which already excludes the
//     middle row/col on odd dims). On odd×odd grids only the Hamiltonian-feasible
//     checkerboard parity is legal; on squares the anti-diagonal is excluded too
//     (unless that would empty the set, e.g. 5×5).
//   Two-pen: the bottom-left CORNER is always blanked, PLUS one rolled cell
//     anywhere except the top-right corner — two blanks keep the playable count
//     odd so the centre "kiss" still exists.
// The rolled cell's index is pinned to the URL as `bx`, so any link reproduces.
const isBlocked = (r, c) => BLOCKED.has(k(r, c));
const playableCount = () => ROWS * COLS - BLOCKED.size;

// Recompute BLOCKED from the current mode, size and rolled index BX.
function setBlocked() {
  BLOCKED = new Set();
  if (TWO_PEN) BLOCKED.add(k(ROWS - 1, 0));            // bottom-left corner notch
  if (BX >= 0) BLOCKED.add(k((BX / COLS) | 0, BX % COLS));
}

// Legal candidate cell indices for the one-pen rolled blank.
function onePenBlankCandidates() {
  const r0 = ROWS - Math.floor(ROWS / 2);   // first quadrant row (drops middle row on odd R)
  const c1 = Math.floor(COLS / 2);          // one past last quadrant col (drops middle col on odd C)
  const oddOdd = (ROWS % 2 === 1) && (COLS % 2 === 1);
  const base = [];
  for (let r = r0; r < ROWS; r++) for (let c = 0; c < c1; c++) {
    if (oddOdd && ((r + c) % 2 !== 0)) continue;   // parity: only even (r+c) keep a Hamiltonian path
    base.push(r * COLS + c);
  }
  if (ROWS === COLS) {
    const off = base.filter(i => (((i / COLS) | 0) + (i % COLS)) !== (ROWS - 1));  // drop anti-diagonal
    if (off.length) return off;                                                   // unless empty (5×5)
  }
  return base;
}

// Legal candidate cell indices for the two-pen rolled blank X. v0.40.0 confines
// X to the bottom-left quadrant (Game-Definition §13). That confinement makes
// the symmetry guarantee clean: the fixed corner blank breaks every symmetry
// that MOVES it, and a quadrant cell can never mirror-pair with the corner
// across any axis (its partner lands in another quadrant), so X cannot re-impose
// a broken symmetry. The only symmetry the corner can't break is the
// anti-diagonal (which fixes it), so on a square X must stay off it. No parity
// filter is needed: removing the majority-colour corner already rebalances, so
// either colour of X still admits a Hamiltonian path.
function twoPenBlankCandidates() {
  const R = ROWS, C = COLS;
  const r0 = R - Math.floor(R / 2);   // first quadrant row
  const c1 = Math.floor(C / 2);       // one past last quadrant col
  const cornerIdx = (R - 1) * C;      // bottom-left corner = the fixed first blank
  const square = (R === C);
  const out = [];
  for (let r = r0; r < R; r++) for (let c = 0; c < c1; c++) {
    const i = r * C + c;
    if (i === cornerIdx) continue;
    if (square && (r + c) === (R - 1)) continue;    // off the anti-diagonal
    out.push(i);
  }
  return out;
}

function shuffle(a) {
  for (let i = a.length - 1; i > 0; i--) {
    const j = (rng() * (i + 1)) | 0;
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function neighbors(r, c) {
  const out = [];
  if (r > 0)        out.push([r - 1, c]);
  if (r < ROWS - 1) out.push([r + 1, c]);
  if (c > 0)        out.push([r, c - 1]);
  if (c < COLS - 1) out.push([r, c + 1]);
  return out;
}

// ─── Hamiltonian path (DFS + Warnsdorff + backbite) ──
// Generation is "blank-aware": the path covers only the non-blanked (playable)
// cells. Two stages:
//   findHoledHamiltonian — finds ONE Hamiltonian path over the playable cells
//     via Warnsdorff-ordered DFS with a connectivity prune AND a leaf prune (at
//     most one remaining cell of degree ≤1 besides the head). With blanks in
//     arbitrary positions a constructive boustrophedon no longer works, so this
//     search supplies the seed. It restarts over shuffled start cells within a
//     time budget. Validated to find a seed reliably and fast for every legal
//     blank across all sizes (worst case 9×9 two-pen, 79 cells).
//   backbiteMix — given that seed, applies seeded "backbite" moves over the
//     blank-aware adjacency to produce a well-mixed path (same idea as before:
//     re-link an end to a neighbour and reverse the tail; always valid).
// Legacy squares ≤8×8 keep the DFS path directly (so the wiggle bias still
// shapes them); other configs mix it.
function findHoledHamiltonian(nodeBudget, wig) {
  const R = ROWS, C = COLS, Nfull = R * C;
  const blk = new Uint8Array(Nfull);
  for (const key of BLOCKED) { const ci = key.indexOf(','); blk[(+key.slice(0, ci)) * C + (+key.slice(ci + 1))] = 1; }
  const playable = [];
  for (let i = 0; i < Nfull; i++) if (!blk[i]) playable.push(i);
  const Np = playable.length;
  const adj = [];
  for (let i = 0; i < Nfull; i++) {
    const r = (i / C) | 0, c = i % C, a = [];
    if (r > 0)      { const v = i - C; if (!blk[v]) a.push(v); }
    if (r < R - 1)  { const v = i + C; if (!blk[v]) a.push(v); }
    if (c > 0)      { const v = i - 1; if (!blk[v]) a.push(v); }
    if (c < C - 1)  { const v = i + 1; if (!blk[v]) a.push(v); }
    adj.push(a);
  }
  // Work is bounded by a DETERMINISTIC node counter, never wall-clock, so the
  // same (seed, blanks) always yields the same path on any machine/load — which
  // is what makes a shared `bx` link reproduce exactly.
  const visited = new Uint8Array(Nfull);
  const seen = new Uint8Array(Nfull), stack = new Int32Array(Nfull);
  const isHeadNbr = new Uint8Array(Nfull);
  const remDeg = (i) => { let d = 0; const A = adj[i]; for (let q = 0; q < A.length; q++) if (!visited[A[q]]) d++; return d; };
  function prune(head, curLen) {
    // connectivity: every remaining cell must be reachable from the head
    seen.fill(0); let top = 0;
    for (const v of adj[head]) if (!visited[v] && !seen[v]) { seen[v] = 1; stack[top++] = v; }
    let cnt = 0;
    while (top > 0) { const x = stack[--top]; cnt++; for (const y of adj[x]) if (!visited[y] && !seen[y]) { seen[y] = 1; stack[top++] = y; } }
    if (cnt !== (Np - curLen)) return false;
    // leaf prune: at most one remaining cell may have effective degree ≤1
    // (it would have to be the path's free end); none may be isolated. The head
    // contributes a degree to each of its unvisited neighbours.
    isHeadNbr.fill(0); for (const v of adj[head]) if (!visited[v]) isHeadNbr[v] = 1;
    let leaves = 0;
    for (let i = 0; i < Nfull; i++) {
      if (blk[i] || visited[i] || i === head) continue;
      const d = remDeg(i) + (isHeadNbr[i] ? 1 : 0);
      if (d === 0) return false;
      if (d === 1) { leaves++; if (leaves > 1) return false; }
    }
    return true;
  }
  const pathIdx = [];
  let nodes = 0, budgetHit = false;
  function dfs() {
    if (nodes > nodeBudget) { budgetHit = true; return null; }
    nodes++;
    if (pathIdx.length === Np) return pathIdx.slice();
    const last = pathIdx[pathIdx.length - 1];
    const lr = (last / C) | 0, lc = last % C;
    let ldr = 0, ldc = 0;
    if (pathIdx.length >= 2) { const pv = pathIdx[pathIdx.length - 2]; ldr = lr - ((pv / C) | 0); ldc = lc - (pv % C); }
    const cands = [];
    for (const v of adj[last]) if (!visited[v]) cands.push(v);
    cands.sort((a, b) => {
      let sa = remDeg(a), sb = remDeg(b);
      if (wig) {   // bias ties toward/away from turns, like the legacy square search
        const aTurn = !(((a / C) | 0) - lr === ldr && (a % C) - lc === ldc);
        const bTurn = !(((b / C) | 0) - lr === ldr && (b % C) - lc === ldc);
        sa += (-wig.bias * (aTurn ? 1 : -1)) * 0.3;
        sb += (-wig.bias * (bTurn ? 1 : -1)) * 0.3;
      }
      return (sa - sb) + (rng() - 0.5) * 0.01;
    });
    for (const nx of cands) {
      visited[nx] = 1; pathIdx.push(nx);
      let ok = true;
      if (pathIdx.length < Np) ok = prune(nx, pathIdx.length);
      if (ok) { const r = dfs(); if (r) return r; }
      pathIdx.pop(); visited[nx] = 0;
      if (budgetHit) return null;
    }
    return null;
  }
  const starts = playable.slice();
  for (let i = starts.length - 1; i > 0; i--) { const j = (rng() * (i + 1)) | 0; [starts[i], starts[j]] = [starts[j], starts[i]]; }
  for (const s of starts) {
    visited.fill(0); pathIdx.length = 0; visited[s] = 1; pathIdx.push(s);
    const r = dfs(); if (r) return r.map(idx => [(idx / C) | 0, idx % C]);
    if (budgetHit) break;
  }
  return null;
}

function backbiteMix(seedPath) {
  const R = ROWS, C = COLS, Nfull = R * C;
  const blk = new Uint8Array(Nfull);
  for (const key of BLOCKED) { const ci = key.indexOf(','); blk[(+key.slice(0, ci)) * C + (+key.slice(ci + 1))] = 1; }
  const arr = seedPath.map(([r, c]) => r * C + c);
  const total = arr.length;
  const pos = new Int32Array(Nfull); pos.fill(-1);
  for (let i = 0; i < total; i++) pos[arr[i]] = i;
  const nbrs = (idx) => {
    const r = (idx / C) | 0, c = idx % C, o = [];
    if (r > 0)     { const v = idx - C; if (!blk[v]) o.push(v); }
    if (r < R - 1) { const v = idx + C; if (!blk[v]) o.push(v); }
    if (c > 0)     { const v = idx - 1; if (!blk[v]) o.push(v); }
    if (c < C - 1) { const v = idx + 1; if (!blk[v]) o.push(v); }
    return o;
  };
  const moves = total * 8;   // strong mixing
  for (let m = 0; m < moves; m++) {
    const useTail = rng() < 0.5;
    const end = useTail ? arr[total - 1] : arr[0];
    const ns = nbrs(end);
    if (ns.length === 0) continue;
    const w = ns[(rng() * ns.length) | 0];
    const j = pos[w];
    if (j < 0) continue;
    let lo, hi;
    if (useTail) { if (j >= total - 2) continue; lo = j + 1; hi = total - 1; }
    else         { if (j <= 1) continue;         lo = 0;     hi = j - 1; }
    while (lo < hi) {
      const a = arr[lo], b = arr[hi];
      arr[lo] = b; arr[hi] = a; pos[b] = lo; pos[a] = hi; lo++; hi--;
    }
  }
  return arr.map(idx => [(idx / C) | 0, idx % C]);
}

function generateHamiltonian() {
  // Find a seed Hamiltonian path over the playable cells, then (for non legacy-
  // square configs) mix it. Legacy squares ≤8×8 keep the DFS path directly so
  // the wiggle bias still shapes their look.
  const square8 = (ROWS === COLS && ROWS <= 8);
  const wig = square8 ? genWiggle : null;
  const area = ROWS * COLS;
  // Deterministic node budget: generous enough that any feasible board is found
  // (easy boards use a tiny fraction of it), bounded so a pathological blank
  // still terminates and we roll the next candidate.
  const nodeBudget = Math.max(60000, area * 1500);
  const seed = findHoledHamiltonian(nodeBudget, wig);
  if (!seed) return null;
  return square8 ? seed : backbiteMix(seed);
}

// ─── Wiggliness ─────────────────────────────────────
// "Wiggliness" = turn ratio of the solution path: the fraction of interior
// cells where the path changes direction rather than going straight through.
// Empirically, snake-like paths sit ~0.28 and very twisty paths reach ~0.85;
// the natural generator averages ~0.5. The slider biases generation toward a
// target turn ratio (and, at the wiggly end, away from long straight runs —
// the thing that makes a path feel un-wiggly).
//
// Wiggliness is a first-class puzzle parameter, exactly like SIZE and
// DIFFICULTY: it lives in WIGGLE (level 0..4), travels in the URL as `w`, and
// is reflected by the on-board slider. A puzzle is therefore reproducible from
// (seed, size, difficulty, w). Level 2 = the natural generator (no bias), so
// w=2 / a missing `w` param (the daily, any old link) generates exactly as
// before. The last-used level is also remembered in localStorage as the
// default for fresh sessions.
const WIGGLE_DEFAULT = 2;                          // midpoint = natural, no bias
// Targets/biases for the wiggly end were lowered off a pathological ceiling.
// The old w=4 (target 0.75, bias 1.0) turned at nearly every opportunity,
// which paradoxically made it EASIER: it minimised the cells where the path
// goes straight while a turn is available — the only points where a blind
// "always turn" strategy diverges from the solution — so always-turning
// tracked the answer. We now top out lower and select for decision density
// (see DECISION_FLOOR_FRAC + the scorer in generateForDifficulty).
const WIGGLE_TARGET = { 0: 0.30, 1: 0.42, 3: 0.56, 4: 0.66 };
const WIGGLE_BIAS   = { 0: -1.0, 1: -0.6, 3: 0.45, 4: 0.62 };
const WIGGLE_LABELS = ['Almost straight', 'Fairly straight', 'Balanced', 'Fairly wiggly', 'Really wiggly'];
// Minimum "straight-against-turn" decision points at the wiggly end, as a
// fraction of interior cells. Below this floor a candidate is penalised, which
// lifts the low tail (the trivially always-turn-solvable puzzles) without
// flattening the wiggly look. w4 looks wigglier (higher turn target) so it
// carries a lower floor than w3 — still far above the old broken baseline.
const DECISION_FLOOR_FRAC = { 3: 0.36, 4: 0.30 };
const WALLS_DEFAULT = 0;                            // no extra walls = today's behaviour
const WALL_FRAC   = { 0: 0, 1: 0.18, 2: 0.34, 3: 0.52, 4: 0.72 };
const WALL_LABELS = ['Fewest walls', 'A few walls', 'Some walls', 'Many walls', 'A-maze-ing'];

const toOdd = (d) => (d % 2 === 1) ? d : (d > 5 ? d - 1 : d + 1);   // even → nearest odd in 5..9
// Snap BOTH dimensions to odd when in two-pen mode (even grids have no centre
// cell). Returns true if either dimension changed.
function enforceOddSizeForTwoPen() {
  if (!TWO_PEN) return false;
  const r = toOdd(ROWS), c = toOdd(COLS);
  if (r === ROWS && c === COLS) return false;
  ROWS = r; COLS = c;
  return true;
}

// ─── Point count — decoupled from grid size ─────────
// One-pen: the player threads N TOTAL points, 5 .. ⌊2√area⌋ (8×8 → 5–16, by area
// for rectangles). Two-pen: the player threads m points PER SNAKE, ODD only,
// 3 .. pairMax where pairMax = largest odd ≤ ⌊√area⌋+1 (8×8 → 9). The two snakes
// share the centre kiss, so m per snake = a combined path of 2m−1 points.
// POINTS===0 means "auto": one-pen falls back to the legacy difficulty×area
// count (so classic links without a `pts` param reproduce byte-identically);
// two-pen derives a sensible odd default from difficulty.
const gridArea = () => ROWS * COLS;
const toOddUp = (v) => (v % 2 === 1) ? v : v + 1;
// One-pen total-point ceiling: 2×side for squares, area-proportional otherwise.
function loneMaxPoints() {
  const a = gridArea();
  return Math.max(5, Math.min(Math.floor(a / 2), Math.floor(2 * Math.sqrt(a))));
}
// Two-pen per-snake ceiling (odd): largest odd ≤ ⌊√area⌋+1.
function pairMaxPerSnake() {
  let m = Math.floor(Math.sqrt(gridArea())) + 1;
  if (m % 2 === 0) m--;
  return Math.max(3, m);
}
function pointsRange() {
  return TWO_PEN ? { min: 3, max: pairMaxPerSnake(), step: 2 }
                 : { min: 5, max: loneMaxPoints(),  step: 1 };
}
// Auto per-snake count for two-pen (no legacy to preserve): scale with
// difficulty — gentler puzzles get more points, fiendish the fewest.
function autoPerSnake() {
  const max = pairMaxPerSnake();
  const frac = ({ gentle: 1.0, tricky: 0.75, knotty: 0.55, fiendish: 0.0 })[DIFFICULTY];
  let m = toOddUp(Math.round(3 + (frac == null ? 0.6 : frac) * (max - 3)));
  return Math.max(3, Math.min(m, max));
}
// Count handed to generation. One-pen → total K (0 = legacy auto). Two-pen →
// per-snake m (always concrete, never 0).
function effectivePoints() {
  if (TWO_PEN) {
    const m = (POINTS >= 3) ? toOddUp(POINTS) : autoPerSnake();
    return Math.max(3, Math.min(m, pairMaxPerSnake()));
  }
  if (POINTS <= 0) return 0;                          // auto (legacy)
  return Math.max(5, Math.min(POINTS, loneMaxPoints()));
}
function addExtraWalls(sol) {
  const frac = WALL_FRAC[WALLS] || 0;
  if (frac <= 0) return;
  const solEdge = new Set();
  for (let i = 0; i < sol.length - 1; i++) {
    const a = sol[i], b = sol[i + 1];
    solEdge.add(wk(a[0], a[1], b[0], b[1]));
  }
  const avail = [];
  for (let r = 0; r < ROWS; r++) for (let c = 0; c < COLS; c++) {
    if (isBlocked(r, c)) continue;
    if (c < COLS - 1 && !isBlocked(r, c + 1)) { const e = wk(r, c, r, c + 1); if (!solEdge.has(e) && !walls.has(e)) avail.push(e); }
    if (r < ROWS - 1 && !isBlocked(r + 1, c)) { const e = wk(r, c, r + 1, c); if (!solEdge.has(e) && !walls.has(e)) avail.push(e); }
  }
  shuffle(avail);
  const take = Math.floor(avail.length * frac);
  for (let i = 0; i < take; i++) walls.add(avail[i]);
}

function wiggleParamsFor(level) {
  if (!(level in WIGGLE_TARGET)) return null;       // default level → no bias
  return { target: WIGGLE_TARGET[level], bias: WIGGLE_BIAS[level],
           floorFrac: DECISION_FLOOR_FRAC[level] || 0 };
}
// Keep the on-board slider + label in step with the current WIGGLE level.
function pathWiggliness(path) {
  if (!path || path.length < 3) return { turnRatio: 0, longestRun: path ? path.length - 1 : 0 };
  let turns = 0, run = 1, longest = 1;
  for (let i = 1; i < path.length - 1; i++) {
    const a = path[i - 1], b = path[i], c = path[i + 1];
    const straight = (b[0] - a[0] === c[0] - b[0]) && (b[1] - a[1] === c[1] - b[1]);
    if (straight) { run++; } else { turns++; if (run > longest) longest = run; run = 1; }
  }
  if (run > longest) longest = run;
  return { turnRatio: turns / (path.length - 2), longestRun: longest };
}

// Solution-wriggliness (Game-Definition §15): the raw count of direction changes
// (turns) along a completed path — an interior cell whose incoming direction
// differs from its outgoing direction; the two ends aren't turns. This is the
// competitive score (least / most wriggly), and is deliberately distinct from
// the build-time wiggle bias `w` (which only shapes generation). Works on a
// one-pen path or on either snake of a two-pen solve.
function solutionWriggliness(path) {
  if (!path || path.length < 3) return 0;
  let turns = 0;
  for (let i = 1; i < path.length - 1; i++) {
    const a = path[i - 1], b = path[i], c = path[i + 1];
    const straight = (b[0] - a[0] === c[0] - b[0]) && (b[1] - a[1] === c[1] - b[1]);
    if (!straight) turns++;
  }
  return turns;
}

// "Decision density": the count of interior cells where the solution goes
// STRAIGHT while an unvisited, un-walled TURN was available. These are exactly
// the cells where a blind "always turn" strategy diverges from the solution —
// the puzzle's real teeth at the wiggly end. We select for keeping this above
// a floor so high-wiggle puzzles can't collapse into a forced always-turn walk.
function decisionDensity(path, wallSet) {
  if (!path || path.length < 3) return 0;
  const seen = new Set([k(path[0][0], path[0][1])]);
  let pts = 0;
  for (let i = 1; i < path.length - 1; i++) {
    const pr = path[i - 1], cu = path[i], nx = path[i + 1];
    seen.add(k(cu[0], cu[1]));
    const ldr = cu[0] - pr[0], ldc = cu[1] - pr[1];
    let turnAvail = false;
    for (const [nr, nc] of neighbors(cu[0], cu[1])) {
      if (isBlocked(nr, nc)) continue;
      if (seen.has(k(nr, nc))) continue;
      if (wallSet.has(wk(cu[0], cu[1], nr, nc))) continue;
      if (!((nr - cu[0]) === ldr && (nc - cu[1]) === ldc)) { turnAvail = true; break; }
    }
    const solStraight = (nx[0] - cu[0] === ldr && nx[1] - cu[1] === ldc);
    if (solStraight && turnAvail) pts++;
  }
  return pts;
}

function pickWaypoints(sol, count) {
  // Two-pen mode: waypoints must be symmetric about the path midpoint, with the
  // centre cell as a shared waypoint, so the two snakes are equal-length and
  // meet at one kiss. Labels stay classic (1..K in index order) for the solver /
  // uniqueness enforcement; the two-snake relabelling happens at display time.
  if (TWO_PEN) {
    const N = sol.length;            // odd grid → odd N → integer midpoint
    const mid = (N - 1) / 2;
    const half = Math.max(2, Math.min(count, mid + 1)); // count = points PER SNAKE (incl. shared peak)
    const aIdx = [0];
    for (let i = 1; i < half - 1; i++) aIdx.push(Math.round((i * mid) / (half - 1)));
    aIdx.push(mid);
    const uniqA = [...new Set(aIdx)].sort((a, b) => a - b);
    const idxSet = new Set(uniqA);
    for (const i of uniqA) idxSet.add(N - 1 - i);   // mirror to the second half
    const all = [...idxSet].sort((a, b) => a - b);
    return all.map((p, i) => ({ r: sol[p][0], c: sol[p][1], n: i + 1 }));
  }
  const N = Math.min(count, Math.floor(sol.length / 2));
  const idx = [0];
  for (let i = 1; i < N - 1; i++) {
    const base = Math.round((i * (sol.length - 1)) / (N - 1));
    const wiggle = Math.floor((rng() - 0.5) * 3);
    let p = base + wiggle;
    p = Math.max(idx[idx.length - 1] + 2, Math.min(sol.length - 2, p));
    idx.push(p);
  }
  idx.push(sol.length - 1);
  const uniq = [...new Set(idx)].sort((a, b) => a - b);
  return uniq.map((p, i) => ({ r: sol[p][0], c: sol[p][1], n: i + 1 }));
}

// ─── Solver ─────────────────────────────────────────
// Generation-wide solver-work counter. Accumulates every solve()'s node count
// so generateForDifficulty can cap total work DETERMINISTICALLY (node counts
// are a pure function of seed+blanks), giving the old wall-clock budget's
// early-stop behaviour without its non-reproducibility.
function buildSolverData(wallSet) {
  const N = ROWS * COLS;               // index space (arrays); blanks live here but get no edges
  const isWp = new Int8Array(N); isWp.fill(-1);
  for (const w of waypoints) isWp[w.r * COLS + w.c] = w.n - 1;
  const blk = new Uint8Array(N);
  for (const key of BLOCKED) { const ci = key.indexOf(','); blk[(+key.slice(0, ci)) * COLS + (+key.slice(ci + 1))] = 1; }
  const adj = [];
  for (let i = 0; i < N; i++) {
    const r = (i / COLS) | 0, c = i % COLS;
    const a = [];
    if (!blk[i]) {
      if (r > 0          && !blk[i - COLS] && !wallSet.has(wk(r - 1, c, r, c))) a.push((r - 1) * COLS + c);
      if (r < ROWS - 1   && !blk[i + COLS] && !wallSet.has(wk(r, c, r + 1, c))) a.push((r + 1) * COLS + c);
      if (c > 0          && !blk[i - 1]    && !wallSet.has(wk(r, c - 1, r, c))) a.push(r * COLS + c - 1);
      if (c < COLS - 1   && !blk[i + 1]    && !wallSet.has(wk(r, c, r, c + 1))) a.push(r * COLS + c + 1);
    }
    adj.push(a);
  }
  return { adj, isWp, N, Nplay: N - BLOCKED.size };
}

function solve(wallSet, maxCount, nodeCap) {
  nodeCap = nodeCap || 200000;
  const { adj, isWp, N, Nplay } = buildSolverData(wallSet);
  const startIdx = waypoints[0].r * COLS + waypoints[0].c;
  const visited = new Uint8Array(N);
  visited[startIdx] = 1;
  const cur = [startIdx];
  let nextWp = 1;
  let nodes = 0;
  let count = 0;
  let aborted = false;
  const found = [];

  // Reusable BFS scratch — avoids GC pressure inside the hot loop.
  const seen = new Uint8Array(N);
  const stack = new Int32Array(N);

  // Pruning: if any unvisited cell is unreachable from `from` via
  // remaining unvisited cells, this branch is dead. This single check
  // makes 8×8 enumeration tractable.
  function unvisitedReachableFrom(from) {
    seen.fill(0);
    let top = 0;
    for (const v of adj[from]) {
      if (!visited[v] && !seen[v]) { seen[v] = 1; stack[top++] = v; }
    }
    let cnt = 0;
    while (top > 0) {
      const x = stack[--top]; cnt++;
      for (const y of adj[x]) {
        if (!visited[y] && !seen[y]) { seen[y] = 1; stack[top++] = y; }
      }
    }
    return cnt === (Nplay - cur.length);
  }

  function dfs() {
    if (aborted || count >= maxCount) return;
    nodes++;
    if (nodes > nodeCap) { aborted = true; return; }

    if (cur.length === Nplay) {
      if (nextWp === waypoints.length) {
        if (found.length < _COLLECT) found.push(cur.slice());
        count++;
      }
      return;
    }
    const last = cur[cur.length - 1];
    const opts = adj[last];
    for (let i = 0; i < opts.length; i++) {
      const next = opts[i];
      if (visited[next]) continue;
      const wIdx = isWp[next];
      if (wIdx !== -1 && wIdx !== nextWp) continue;
      visited[next] = 1;
      cur.push(next);
      let ok = true;
      if (cur.length < Nplay) ok = unvisitedReachableFrom(next);
      if (ok) {
        if (wIdx !== -1) nextWp++;
        dfs();
        if (wIdx !== -1) nextWp--;
      }
      cur.pop();
      visited[next] = 0;
      if (aborted || count >= maxCount) return;
    }
  }
  dfs();
  genNodes += nodes;        // deterministic generation-wide work counter (see generateForDifficulty)
  return { count, nodes, found, aborted };
}

// ─── Uniqueness enforcement ─────────────────────────
// Find alternate solution; add a wall on an edge it uses
// that the canonical doesn't. Repeat until unique.
function enforceUniqueness(sol, cap) {
  const solEdgeSet = new Set();
  for (let i = 0; i < sol.length - 1; i++) {
    const a = sol[i], b = sol[i + 1];
    solEdgeSet.add(wk(a[0], a[1], b[0], b[1]));
  }
  const candidate = new Set(walls);
  for (let attempt = 0; attempt < 25; attempt++) {
    const r = solve(candidate, 2, cap);
    if (r.aborted) return null;
    if (r.count <= 1) return candidate;
    const altPath = pickAlternate(r.found, sol);
    if (!altPath) return candidate;
    let placed = false;
    const idxs = [];
    for (let i = 0; i < altPath.length - 1; i++) idxs.push(i);
    shuffle(idxs);
    for (const i of idxs) {
      const a = altPath[i], b = altPath[i + 1];
      const ar = (a / COLS) | 0, ac = a % COLS;
      const br = (b / COLS) | 0, bc = b % COLS;
      const ek = wk(ar, ac, br, bc);
      if (!solEdgeSet.has(ek) && !candidate.has(ek)) {
        candidate.add(ek);
        placed = true;
        break;
      }
    }
    if (!placed) return null;
  }
  return null;
}

function pickAlternate(found, sol) {
  const solStr = sol.map(([r, c]) => r * COLS + c).join(',');
  for (const f of found) {
    if (f.join(',') !== solStr) return f;
  }
  return null;
}

// ─── Full generation with difficulty targeting ──────
// Try several sub-seeds. For each: generate path, pick waypoints,
// enforce uniqueness, measure solver nodes. Keep the candidate
// closest to target difficulty.
function generateCandidate(subSeed, wpCount) {
  rng = makeRNG(SEED + ':' + subSeed);
  const sol = generateHamiltonian();
  if (!sol) return null;
  solution = sol;
  waypoints = pickWaypoints(sol, wpCount);
  walls = new Set();
  // v0.40.0: boards may have MANY solutions (see Game-Definition §14). We no
  // longer add walls to force a unique solution, and we no longer run the
  // (expensive) uniqueness solve — generation just lays the ordered nodes along
  // a real Hamiltonian path, which guarantees ≥1 solution by construction. The
  // optional WALLS-level walls are solution-safe (placed only on non-path edges),
  // so the constructed path always remains valid. This removes the solver from
  // the hot path, so large grids (esp. 9×9) generate fast.
  addExtraWalls(sol);
  return { sol, waypoints: waypoints.slice(), walls: new Set(walls) };
}

function generateForDifficulty() {
  const area = ROWS * COLS;
  // Waypoint count K: POINTS>0 fixes K (the player's choice); POINTS===0 is the
  // "auto" behaviour where K tracks DIFFICULTY × area. DIFFICULTY now only
  // influences the auto node count — it no longer targets solver effort, since
  // boards needn't be uniquely solvable (Game-Definition §14).
  const fixedK = effectivePoints();          // 0 when auto
  const baseWp = fixedK > 0 ? fixedK : targetWaypoints(DIFFICULTY, area);

  // Build-wiggle target from the current puzzle's WIGGLE level. null = default/
  // natural look.
  genWiggle = wiggleParamsFor(WIGGLE);
  const wiggleActive = !!genWiggle;

  // Every attempt is now cheap (a path generation + node placement + optional
  // solution-safe walls — no solver), so a handful gives variety / wiggle choice
  // without the old latency. Each generateCandidate fully reseeds the RNG, so the
  // result is deterministic for (seed, size, w, m, pts, bx).
  const ATTEMPTS = wiggleActive ? (area <= 56 ? 14 : 8) : 1;

  if (!wiggleActive) {
    // Natural look: the first valid candidate wins (fast, deterministic).
    for (let i = 0; i < ATTEMPTS + 7; i++) {
      const wp = Math.max(3, baseWp + (fixedK > 0 ? 0 : (i % 5) - 2));
      const cand = generateCandidate(i, wp);
      if (cand) return cand;
    }
    return null;
  }

  // Build-wiggle active: pick the candidate whose path wiggliness sits closest to
  // the target, lifting the low tail via the decision-density floor (kills the
  // trivially always-turn-solvable look). All measures are O(path) — no solver.
  let wBest = null, wBestScore = Infinity;
  for (let i = 0; i < ATTEMPTS; i++) {
    const wp = Math.max(3, baseWp + (fixedK > 0 ? 0 : (i % 5) - 2));
    const cand = generateCandidate(i, wp);
    if (!cand) continue;
    const w = pathWiggliness(cand.sol);
    let ws = Math.abs(w.turnRatio - genWiggle.target);
    if (genWiggle.floorFrac) {
      const interior = cand.sol.length - 2;
      const floor = genWiggle.floorFrac * interior;
      const dens = decisionDensity(cand.sol, cand.walls);
      if (dens < floor) ws += (floor - dens) * 0.03;
    }
    if (ws < wBestScore) { wBestScore = ws; wBest = cand; }
  }
  return wBest;
}

// Roll the blanked-off cell(s) and generate. The blank position is fixed for a
// given (seed, size, mode) across the difficulty attempts inside
// generateForDifficulty; only on the rare unrollable board do we advance to the
// next seed-derived blank candidate. `fixedBx` (a shared link's pinned `bx`)
// forces exactly that blank. Sets BLOCKED/BX to the winning roll.
function rollBlanksAndGenerate(fixedBx) {
  if (Number.isInteger(fixedBx) && fixedBx >= 0) {
    BX = fixedBx; setBlocked();
    return generateForDifficulty();
  }
  const cands = TWO_PEN ? twoPenBlankCandidates() : onePenBlankCandidates();
  if (!cands.length) { BX = -1; setBlocked(); return generateForDifficulty(); }
  const hr = makeRNG(SEED + ':blankseq');
  const order = cands.slice();
  for (let i = order.length - 1; i > 0; i--) { const j = (hr() * (i + 1)) | 0; [order[i], order[j]] = [order[j], order[i]]; }
  for (const bx of order) {
    BX = bx; setBlocked();
    const cand = generateForDifficulty();
    if (cand) return cand;
  }
  return null;
}

// ─── Snake fallback (should almost never trigger) ───
function snakeFallback() {
  rng = makeRNG(SEED + ':fallback');
  let sol = findHoledHamiltonian(Math.max(150000, ROWS * COLS * 3000), null);   // honour the current blanks if at all possible
  if (!sol) {
    // Absolute last resort: drop the blanks entirely and snake the full grid.
    BLOCKED = new Set(); BX = -1;
    sol = [];
    for (let r = 0; r < ROWS; r++) {
      if (r % 2 === 0) for (let c = 0; c < COLS; c++) sol.push([r, c]);
      else              for (let c = COLS - 1; c >= 0; c--) sol.push([r, c]);
    }
  }
  solution = sol;
  const fixedK = effectivePoints();
  waypoints = pickWaypoints(sol, fixedK > 0 ? fixedK : targetWaypoints(DIFFICULTY, playableCount()));
  walls = new Set();
}

// ─── Boot a puzzle ──────────────────────────────────
function boardSignature() {
  // Full board identity for the new multiple-solutions model. (seed, size,
  // difficulty) no longer names a board on its own, since mode/wiggle/walls/
  // points/blank also vary. Used as the local wriggliness key AND the server
  // leaderboard board_key, so a personal best and the global board agree.
  return [sizeToken(), TWO_PEN ? 't' : '1', WIGGLE, WALLS, POINTS, BX, SEED].join(':');
}
  // ───────────── spec-driven public API ─────────────
  function _applySpec(spec) {
    ROWS = spec.rows; COLS = spec.cols; DIFFICULTY = spec.difficulty; SEED = spec.seed;
    WIGGLE = spec.wiggle; WALLS = spec.walls; POINTS = spec.points; TWO_PEN = !!spec.twoPen;
    BX = -1; BLOCKED = new Set(); genNodes = 0; genWiggle = null; rng = Math.random;
    solution = []; waypoints = []; walls = new Set();
    enforceOddSizeForTwoPen();
  }
  function generate(spec) {
    _applySpec(spec);
    const fixedBx = (Number.isInteger(spec.bx) && spec.bx >= 0) ? spec.bx : null;
    const cand = rollBlanksAndGenerate(fixedBx);
    if (cand) { solution = cand.sol; waypoints = cand.waypoints; walls = cand.walls; }
    else { snakeFallback(); }
    return { sol: solution, waypoints: waypoints.slice(), walls: new Set(walls),
      blocked: [...BLOCKED].sort(), bx: BX, rows: ROWS, cols: COLS,
      sizeToken: sizeToken(), sig: boardSignature() };
  }
  function enumerate(spec, cap) {
    cap = cap || 1000;
    generate(spec);
    _COLLECT = cap;
    try { const r = solve(walls, cap, (spec.nodeCap || 500000));
      return { count: r.count, found: r.found, aborted: r.aborted }; }
    finally { _COLLECT = 2; }
  }
  function signatureFor(spec) { _applySpec(spec); if (Number.isInteger(spec.bx)) BX = spec.bx; return boardSignature(); }

  return { generate, enumerate, signatureFor, boardSignature, solve, buildSolverData,
    pathWiggliness, solutionWriggliness, decisionDensity, makeRNG, sizeToken,
    effectivePoints, pointsRange, wiggleParamsFor, WIGGLE_LABELS, WALL_LABELS, DIFFS,
    VERSION: 'core-0.1.0' };
});
