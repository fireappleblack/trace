// Validate the hex prototype's engine (topology + generator + puzzle) headlessly.
const fs=require('fs'), vm=require('vm');
const HTML=fs.readFileSync('/tmp/hex-prototype.html','utf8');
const m=/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/i.exec(HTML);
let SRC=m[1]+`
;globalThis.__hex={ makeHexTopo, makeRNG, generateHamiltonian, pickWaypoints, isSolved };`;
const ctx={ document:undefined, console, Math, Set, Map, Array, Object, Number, JSON, URL, URLSearchParams };
ctx.globalThis=ctx; vm.createContext(ctx); vm.runInContext(SRC,ctx,{filename:'hex.js'});
const H=ctx.__hex;

let fail=0; const ok=(c,msg)=>{ if(!c){ console.log('  FAIL:',msg); fail++; } };

// ── topology invariants ──
const topo=H.makeHexTopo(6,26);
ok(topo.count===91, 'cell count 91 (got '+topo.count+')');
// all cells satisfy x+y+z=0 and radius<=5
ok(topo.cells.every(c=>c.x+c.y+c.z===0), 'cube invariant x+y+z=0');
ok(topo.cells.every(c=>Math.max(Math.abs(c.x),Math.abs(c.y),Math.abs(c.z))<=5),'radius<=5');
// adjacency symmetric + degree range (centre=6, corners=3)
let degCounts={}, asym=0;
for(const c of topo.cells){ const ns=topo.neighbors(c); degCounts[ns.length]=(degCounts[ns.length]||0)+1;
  for(const n of ns){ if(!topo.neighbors(n).some(x=>x.x===c.x&&x.y===c.y&&x.z===c.z)) asym++; } }
ok(asym===0,'adjacency symmetric');
ok(topo.neighbors({x:0,y:0,z:0}).length===6,'centre has 6 neighbours');
ok(degCounts[3]===6,'6 corners have degree 3 (got '+degCounts[3]+')');
console.log('  degree histogram:', JSON.stringify(degCounts));

// pixel round-trip: centre of each cell maps back to itself
let rtFail=0;
for(const c of topo.cells){ const p=topo.center(c); const back=topo.pixelToCell(p.px,p.py);
  if(!back||back.x!==c.x||back.y!==c.y||back.z!==c.z) rtFail++; }
ok(rtFail===0,'pixel→cell round-trip exact for all centres (fails '+rtFail+')');

// ── generator: true Hamiltonian path across many seeds ──
function validPath(path){
  if(!path||path.length!==topo.count) return 'len';
  const seen=new Set();
  for(let i=0;i<path.length;i++){ const k=topo.key(path[i]);
    if(seen.has(k)) return 'dup@'+i; seen.add(k);
    if(i>0 && !topo.neighbors(path[i-1]).some(n=>topo.key(n)===k)) return 'gap@'+i; }
  return null;
}
let gOk=0, gBad=0, attempts=200;
for(let i=0;i<attempts;i++){ const p=H.generateHamiltonian(topo,'seed'+i);
  const v=validPath(p); if(v){ gBad++; if(gBad<=3) console.log('  bad path seed'+i+':',v); } else gOk++; }
ok(gBad===0, 'all '+attempts+' generated paths are valid Hamiltonian paths ('+gOk+' ok, '+gBad+' bad)');

// determinism: same seed → same path
const a=H.generateHamiltonian(topo,'fixed'), b=H.generateHamiltonian(topo,'fixed');
ok(JSON.stringify(a)===JSON.stringify(b),'generation deterministic for a fixed seed');

// ── puzzle: waypoints in order, solution solves, partial does not ──
for(const pts of [5,6,8,10,12]){
  const path=H.generateHamiltonian(topo,'wp'+pts);
  const wps=H.pickWaypoints(path,pts);
  ok(wps.length>=Math.min(pts,2),'pts='+pts+' got '+wps.length+' waypoints');
  ok(wps.every((w,i)=>i===0||w.pathIndex>wps[i-1].pathIndex),'pts='+pts+' waypoints strictly ordered');
  ok(H.isSolved(topo,path,wps)===true,'pts='+pts+' full solution solves');
  ok(H.isSolved(topo,path.slice(0,-1),wps)===false,'pts='+pts+' partial line does NOT solve');
  // reversed full path should fail order (endpoints swap) — sanity that order matters
  ok(H.isSolved(topo,path.slice().reverse(),wps)===false || pts===2,'pts='+pts+' reversed fails order');
}

console.log(fail===0 ? '\nALL CHECKS PASSED' : '\n'+fail+' CHECK(S) FAILED');
process.exit(fail?1:0);
