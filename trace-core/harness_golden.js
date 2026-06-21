// flatten:begin
// repo-path: trace-core/harness_golden.js
// generated: 2026-06-21T17:35:52Z by flatten.py — do not edit this block
// flatten:end

// harness_golden.js — golden baseline + equivalence net for the trace-core extraction.
//
//   node harness_golden.js            capture golden from trace.html -> golden.json
//   node harness_golden.js verify     re-run trace.html, diff vs golden.json
//   node harness_golden.js core       run trace-core.js over the SAME battery, diff vs golden.json
//
// The battery (buildCases) and record shape (mkRecord) are shared, so the three
// modes are directly comparable. "core" MATCHing golden proves the extracted
// engine reproduces trace.html's boards byte-for-byte.
const fs = require('fs');
const vm = require('vm');
const crypto = require('crypto');

const MODE = process.argv[2] || 'capture';
const sha1 = (s) => crypto.createHash('sha1').update(s).digest('hex').slice(0, 12);

function buildCases() {
  const DIFFS = ['gentle', 'tricky', 'knotty', 'fiendish'];
  const SIZES = [[5,5],[6,6],[7,7],[8,8],[9,9],[5,7],[7,5],[6,9],[9,6],[5,9]];
  const cases = [];
  for (const [rows, cols] of SIZES)
    for (const difficulty of DIFFS)
      for (const twoPen of [false, true])
        for (const [wiggle, walls, points] of [[2,0,0],[4,2,0],[0,1,0]])
          cases.push({ rows, cols, difficulty, wiggle, walls, points, twoPen,
            seed: 'gold:' + rows + 'x' + cols + ':' + difficulty + ':' + (twoPen?'t':'1') + ':' + wiggle + '-' + walls + '-' + points });
  return cases;
}

function mkRecord(o) {
  if (o.ok === false) return { ok: false };
  return {
    sizeToken: o.sizeToken, rows: o.rows, cols: o.cols, bx: o.bx, blocked: o.blocked,
    sig: o.sig, solLen: o.solLen, wp: o.wp, wallN: o.wallN,
    turns: o.turns, solveCount: o.solveCount, solveAborted: o.solveAborted, solHash: o.solHash,
  };
}

function loadInlineEngine() {
  const HTML = fs.readFileSync(__dirname + '/../trace.html', 'utf8');
  const m = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/i.exec(HTML);
  if (!m) throw new Error('no inline <script> found');
  let SRC = m[1] + "\n;globalThis.__engine = {"
    + "setState(s){ ROWS=s.rows; COLS=s.cols; DIFFICULTY=s.difficulty; SEED=s.seed;"
    + " WIGGLE=s.wiggle; WALLS=s.walls; POINTS=s.points; TWO_PEN=!!s.twoPen;"
    + " BX=-1; BLOCKED=new Set(); genNodes=0; genWiggle=null; },"
    + "oddFix(){ enforceOddSizeForTwoPen(); },"
    + "gen(){ return rollBlanksAndGenerate(null); },"
    + "sync(c){ solution=c.sol; waypoints=c.waypoints; walls=c.walls; },"
    + "read(){ return { rows:ROWS, cols:COLS, bx:BX, blocked:[...BLOCKED].sort(), sizeToken:sizeToken() }; },"
    + "sig(){ return boardSignature(); },"
    + "wrig(sol){ return solutionWriggliness(sol); },"
    + "solveCount(w){ const r=solve(w,3,50000); return { count:r.count, aborted:r.aborted }; },"
    + "};";
  const stub = (() => { const fn = function(){ return s; };
    const s = new Proxy(fn, { get(_,k){
      if (k==='classList') return { add(){},remove(){},toggle(){},contains(){return false;} };
      if (k==='style') return {}; if (k==='value'||k==='textContent') return '';
      if (k==='length') return 0; if (k===Symbol.iterator) return function*(){};
      if (k==='dataset') return {}; return s;
    }, set(){return true;}, apply(){return s;} }); return s; })();
  const ctx = {
    document: { getElementById:()=>stub, querySelector:()=>stub, querySelectorAll:()=>[],
      createElement:()=>stub, addEventListener(){}, body:stub, documentElement:stub },
    navigator:{userAgent:'node'}, location:{href:'http://x/',search:'',hash:'',pathname:'/'},
    localStorage:(()=>{const mm={};return{getItem:(k)=>k in mm?mm[k]:null,setItem:(k,v)=>{mm[k]=String(v);},removeItem:(k)=>{delete mm[k];}};})(),
    console, setTimeout, clearTimeout, setInterval, clearInterval, Promise, Math, Date, JSON,
    Set, Map, Array, Object, Number, String, Boolean, Int8Array, Uint8Array, Int32Array, Float64Array, URLSearchParams,
    requestAnimationFrame:(cb)=>setTimeout(()=>cb(0),0), getComputedStyle:()=>({getPropertyValue:()=>''}),
    crypto:{getRandomValues:(a)=>a, randomUUID:()=>'x'}, fetch:()=>Promise.reject(new Error('no fetch')),
    initSqlJs:()=>Promise.reject(new Error('no sql')), alert(){}, history:{replaceState(){},pushState(){}},
    addEventListener(){}, removeEventListener(){},
    matchMedia:()=>({matches:false,addEventListener(){},removeEventListener(){},addListener(){},removeListener(){}}),
    scrollTo(){}, dispatchEvent:()=>true,
  };
  ctx.window = ctx; ctx.globalThis = ctx;
  process.on('unhandledRejection', () => {});
  vm.createContext(ctx);
  vm.runInContext(SRC, ctx, { filename: 'trace-inline.js' });
  const E = ctx.__engine;
  return (spec) => {
    E.setState(spec); E.oddFix();
    const cand = E.gen();
    const st = E.read();
    if (!cand) return mkRecord({ ok: false });
    E.sync(cand);   // mirror newPuzzle: module state follows the winning candidate
    const wr = E.wrig(cand.sol), sc = E.solveCount(cand.walls);
    return mkRecord({ sizeToken: st.sizeToken, rows: st.rows, cols: st.cols, bx: st.bx,
      blocked: st.blocked, sig: E.sig(), solLen: cand.sol.length, wp: cand.waypoints.length,
      wallN: cand.walls.size, turns: wr.turns, solveCount: sc.count, solveAborted: sc.aborted,
      solHash: sha1(cand.sol.map(c=>c.join(',')).join(';')) });
  };
}

function loadCoreEngine() {
  const TC = require(__dirname + '/trace-core.js');
  return (spec) => {
    const c = TC.generate(spec);
    if (!c) return mkRecord({ ok: false });
    const wr = TC.solutionWriggliness(c.sol), sc = TC.solve(c.walls, 3, 50000);
    return mkRecord({ sizeToken: c.sizeToken, rows: c.rows, cols: c.cols, bx: c.bx,
      blocked: c.blocked, sig: c.sig, solLen: c.sol.length, wp: c.waypoints.length,
      wallN: c.walls.size, turns: wr.turns, solveCount: sc.count, solveAborted: sc.aborted,
      solHash: sha1(c.sol.map(x=>x.join(',')).join(';')) });
  };
}

const cases = buildCases();
const run = (MODE === 'core') ? loadCoreEngine() : loadInlineEngine();
const results = cases.map((s) => { try { return run(s); } catch (e) { return { err: e.message }; } });
const digest = crypto.createHash('sha256').update(JSON.stringify(results)).digest('hex');

function diffAgainstGolden(label) {
  const prev = JSON.parse(fs.readFileSync(__dirname + '/golden.json', 'utf8'));
  if (prev.digest === digest) { console.log(label + ': MATCH - ' + results.length + ' cases, digest ' + digest.slice(0,16) + '...'); return 0; }
  console.log(label + ': MISMATCH - golden ' + prev.digest.slice(0,16) + '... vs ' + digest.slice(0,16) + '...');
  let diffs = 0;
  for (let i = 0; i < results.length; i++) {
    if (JSON.stringify(results[i]) !== JSON.stringify(prev.results[i])) {
      if (diffs < 6) console.log('  diff', cases[i].seed, '\n    golden', JSON.stringify(prev.results[i]), '\n    now   ', JSON.stringify(results[i]));
      diffs++;
    }
  }
  console.log('  ' + diffs + '/' + results.length + ' case(s) differ');
  return 1;
}

if (MODE === 'verify') process.exit(diffAgainstGolden('verify (trace.html)'));
else if (MODE === 'core') process.exit(diffAgainstGolden('core (trace-core.js)'));
else {
  fs.writeFileSync(__dirname + '/golden.json', JSON.stringify({ digest, results, n: results.length }, null, 0));
  const nbad = results.filter(r => r.err || r.ok === false).length;
  console.log('captured ' + results.length + ' cases (' + nbad + ' null/err), digest ' + digest.slice(0,16) + '...');
}
