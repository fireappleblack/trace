const fs=require('fs'),vm=require('vm');
const HTML=fs.readFileSync('/tmp/cairo-prototype.html','utf8');
const m=/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/i.exec(HTML);
let SRC=m[1]+`\n;globalThis.__t={CairoTopo,makeRNG,generateHamiltonian,pickWaypoints,selectWalls,isSolved,ekeyOf,BOARD};`;
const ctx={document:undefined,console,Math,Set,Map,Array,Object,Number,JSON,URL,URLSearchParams,location:{search:''}};
ctx.globalThis=ctx;vm.createContext(ctx);vm.runInContext(SRC,ctx,{filename:'cairo.js'});
const T=ctx.__t,topo=T.CairoTopo;
let fail=0;const ok=(c,m)=>{if(!c){console.log('  FAIL:',m);fail++;}};
ok(topo.count===70,'70 cells (got '+topo.count+')');
let asym=0;for(let i=0;i<topo.count;i++)for(const j of topo.neighbors(i))if(!topo.neighbors(j).includes(i))asym++;
ok(asym===0,'adjacency symmetric');
let nodeg2=topo.cells.every(i=>topo.neighbors(i).length>=3);
ok(nodeg2,'no degree<3 cells (rounded boundary)');
let rt=0;for(let i=0;i<topo.count;i++){const c=topo.center(i);if(topo.pixelToCell(c[0],c[1])!==i)rt++;}
ok(rt===0,'hit-test exact for all cells (fails '+rt+')');
// edgeBetween exists for every adjacency
let eb=0;for(let i=0;i<topo.count;i++)for(const j of topo.neighbors(i))if(i<j&&!topo.edgeBetween(i,j))eb++;
ok(eb===0,'edgeBetween found for every adjacency (missing '+eb+')');
function valid(p){if(!p||p.length!==topo.count)return 'len';const s=new Set();
  for(let i=0;i<p.length;i++){if(s.has(p[i]))return'dup';s.add(p[i]);if(i>0&&!topo.neighbors(p[i-1]).includes(p[i]))return'gap@'+i;}return null;}
let good=0,bad=0;
for(let s=0;s<40;s++){const p=T.generateHamiltonian(topo,'seed'+s);const v=valid(p);if(v){bad++;if(bad<=3)console.log('  bad',s,v);}else good++;}
ok(bad===0,'40 Hamiltonian paths all valid ('+good+'/'+(good+bad)+')');
// WALLS: solution must never cross a wall, for every fraction
let wallViol=0,wallCounts=[];
for(const frac of [0,0.18,0.34,0.5]){
  for(let s=0;s<30;s++){
    const sol=T.generateHamiltonian(topo,'w'+s);
    const walls=T.selectWalls(topo,sol,frac,'w'+s);
    if(frac===0.34&&s===0) wallCounts.push('frac'+frac+'→'+walls.size+' walls');
    for(let i=1;i<sol.length;i++) if(walls.has(T.ekeyOf(sol[i-1],sol[i]))) wallViol++;
  }
}
ok(wallViol===0,'solution never crosses a wall across all fractions (violations '+wallViol+')');
console.log('  '+wallCounts.join(', '));
// puzzle ordering / solve
for(const pts of [5,8,12]){const path=T.generateHamiltonian(topo,'p'+pts),wps=T.pickWaypoints(path,pts);
  ok(wps.every((w,i)=>i===0||w.pathIndex>wps[i-1].pathIndex),'pts='+pts+' ordered');
  ok(T.isSolved(topo,path,wps)===true,'pts='+pts+' solves');
  ok(T.isSolved(topo,path.slice(0,-1),wps)===false,'pts='+pts+' partial no-solve');}
console.log(fail===0?'\nALL CHECKS PASSED':'\n'+fail+' FAILED');
process.exit(fail?1:0);
