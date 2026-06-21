// flatten:begin
// repo-path: trace-core/extract_core.js
// generated: 2026-06-21T17:35:52Z by flatten.py — do not edit this block
// flatten:end

// extract_core.js — (re)build trace-core.js by slicing the CORE logic functions
// verbatim out of ../trace.html's inline <script>, then UMD-wrapping them with a
// spec-driven API. Verbatim bodies → byte-identical behaviour, proven by
// `node harness_golden.js core` (MATCH against golden.json).
//
//   node extract_core.js      regenerate ./trace-core.js from ../trace.html
const fs = require('fs');
const path = require('path');
const HTML = fs.readFileSync(path.join(__dirname, '..', 'trace.html'), 'utf8');
const m = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/i.exec(HTML);
const fileLines = HTML.split('\n');

const declRe = /^(?:async function|function|const|let|var|class)\s+([A-Za-z0-9_$]+)/;
const SCRIPT_START = 1739, SCRIPT_END = 3420;
const decls = [];
for (let ln = SCRIPT_START; ln <= SCRIPT_END; ln++) {
  const mm = declRe.exec(fileLines[ln - 1] || '');
  if (mm) decls.push({ name: mm[1], line: ln });
}
const nextLineOf = (idx) => (idx + 1 < decls.length ? decls[idx + 1].line : SCRIPT_END + 1);

const CORE = new Set([
  'sizeToken','DIFFS','targetWaypoints','bandsForArea','classify',
  'xmur3','mulberry32','makeRNG','k','wk','isAdj','isBlocked','playableCount','setBlocked',
  'onePenBlankCandidates','twoPenBlankCandidates','shuffle','neighbors',
  'findHoledHamiltonian','backbiteMix','generateHamiltonian',
  'WIGGLE_DEFAULT','WIGGLE_TARGET','WIGGLE_BIAS','WIGGLE_LABELS','DECISION_FLOOR_FRAC',
  'WALLS_DEFAULT','WALL_FRAC','WALL_LABELS','toOdd','enforceOddSizeForTwoPen',
  'gridArea','toOddUp','loneMaxPoints','pairMaxPerSnake','pointsRange','autoPerSnake','effectivePoints',
  'addExtraWalls','wiggleParamsFor','pathWiggliness','solutionWriggliness','decisionDensity','pickWaypoints',
  'buildSolverData','solve','enforceUniqueness','pickAlternate',
  'generateCandidate','generateForDifficulty','rollBlanksAndGenerate','snakeFallback','boardSignature',
]);

const pieces = [], seen = new Set();
decls.forEach((d, idx) => {
  if (!CORE.has(d.name) || seen.has(d.name)) return;
  seen.add(d.name);
  pieces.push(fileLines.slice(d.line - 1, nextLineOf(idx) - 1).join('\n'));
});
const missing = [...CORE].filter((n) => !seen.has(n));
if (missing.length) { console.error('MISSING core decls:', missing); process.exit(1); }

let body = pieces.join('\n');
const before = body;
body = body.replace('if (found.length < 2) found.push(cur.slice());',
                    'if (found.length < _COLLECT) found.push(cur.slice());');
if (body === before) { console.error('solve collect-cap anchor not found'); process.exit(1); }

const header = `// trace-core.js — shared game-logic core for Trace.
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
`;
const footer = `
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
`;
fs.writeFileSync(path.join(__dirname, 'trace-core.js'), header + body + footer);
console.log('trace-core.js regenerated:', pieces.length, 'core decls,', (header+body+footer).split('\n').length, 'lines');
