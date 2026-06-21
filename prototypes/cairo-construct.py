import math, json, sys
from collections import Counter, defaultdict
sys.setrecursionlimit(1000000)
EPS=1e-3
def rk(p): return (round(p[0],3), round(p[1],3))
def cen(poly): return (sum(x for x,_ in poly)/len(poly), sum(y for _,y in poly)/len(poly))
def proj(poly,nx,ny): ds=[x*nx+y*ny for x,y in poly]; return min(ds),max(ds)
def overlap(P,Q):
    for poly in (P,Q):
        n=len(poly)
        for i in range(n):
            x1,y1=poly[i]; x2,y2=poly[(i+1)%n]
            nx,ny=-(y2-y1),(x2-x1); L=math.hypot(nx,ny); nx/=L; ny/=L
            a0,a1=proj(P,nx,ny); c0,c1=proj(Q,nx,ny)
            if a1<=c0+EPS or c1<=a0+EPS: return False
    return True
def nb(a): return (math.cos(math.radians(a)), math.sin(math.radians(a)))
n0,n1,n2,n3,n4=nb(0),nb(60),nb(120),nb(210),nb(270)
SEED=[[(0,0),n4,(n4[0]+n0[0],n4[1]+n0[1]),n0],
      [(0,0),n2,(n2[0]+n3[0],n2[1]+n3[1]),n3],
      [(0,0),n0,n1],[(0,0),n1,n2],[(0,0),n3,n4]]
def kind(poly): return 'S' if len(poly)==4 else 'T'
placed=[]; centroids=set(); vsq=Counter(); vtri=Counter()
edgeowner={}  # ekey -> list of face indices (for square-border rule)
def ekey(a,e): a,e=rk(a),rk(e); return (a,e) if a<=e else (e,a)
def feasible(poly):
    k=kind(poly)
    for v in poly:
        kk=rk(v)
        if k=='S' and vsq[kk]>=2: return False
        if k=='T' and vtri[kk]>=3: return False
        if vsq[kk]*90+vtri[kk]*60+(90 if k=='S' else 60)>360+1: return False
    # square borders only triangles
    n=len(poly)
    for i in range(n):
        K=ekey(poly[i],poly[(i+1)%n])
        if K in edgeowner:
            ok=kind(placed[edgeowner[K][0]])
            if k=='S' and ok=='S': return False
            if k=='S' and ok=='T': pass
            if k=='T' and ok=='S': pass
    for Q in placed:
        if overlap(poly,Q): return False
    return True
def commit(poly):
    idx=len(placed); placed.append(poly); centroids.add(rk(cen(poly)))
    for v in poly:
        if kind(poly)=='S': vsq[rk(v)]+=1
        else: vtri[rk(v)]+=1
    n=len(poly)
    for i in range(n): edgeowner.setdefault(ekey(poly[i],poly[(i+1)%n]),[]).append(idx)
def uncommit(poly):
    idx=len(placed)-1; placed.pop(); centroids.discard(rk(cen(poly)))
    for v in poly:
        if kind(poly)=='S': vsq[rk(v)]-=1
        else: vtri[rk(v)]-=1
    n=len(poly)
    for i in range(n):
        K=ekey(poly[i],poly[(i+1)%n]); edgeowner[K].remove(idx)
        if not edgeowner[K]: del edgeowner[K]
RFILL=3.6
def make_cands(e0,e1):
    e,a=e1,e0; d=(a[0]-e[0],a[1]-e[1]); nrm=(-d[1],d[0])
    sq=[e,a,(a[0]+nrm[0],a[1]+nrm[1]),(e[0]+nrm[0],e[1]+nrm[1])]
    mid=((e[0]+a[0])/2,(e[1]+a[1])/2); apex=(mid[0]+math.sqrt(3)/2*nrm[0],mid[1]+math.sqrt(3)/2*nrm[1])
    return [sq,[e,a,apex]]
def open_edges():
    ec=Counter(); store={}
    for poly in placed:
        n=len(poly)
        for i in range(n):
            k=ekey(poly[i],poly[(i+1)%n]); ec[k]+=1; store.setdefault(k,(poly[i],poly[(i+1)%n]))
    return [store[k] for k,c in ec.items() if c==1]
def feas_cands(e0,e1):
    out=[]
    for poly in make_cands(e0,e1):
        if rk(cen(poly)) in centroids: continue
        if math.hypot(*cen(poly))>RFILL+0.6: continue
        if feasible(poly): out.append(poly)
    return out
for f in SEED: commit(f)
NODES=[0]; CAP=2000000; best=[0,None]
def vsum(v): return vsq[v]*90+vtri[v]*60
def dfs():
    NODES[0]+=1
    if NODES[0]>CAP: return False
    oe=open_edges()
    needed=[]; frontier=[]
    for (e0,e1) in oe:
        mid=((e0[0]+e1[0])/2,(e0[1]+e1[1])/2)
        inside=math.hypot(*mid)<=RFILL
        cs=feas_cands(e0,e1)
        if inside and math.hypot(*e0)<=RFILL-0.6 and math.hypot(*e1)<=RFILL-0.6:
            needed.append(((e0,e1),cs))
        if cs and math.hypot(*cen(cs[0]))<=RFILL:
            frontier.append(((e0,e1),cs))
    if len(placed)>best[0]: best[0]=len(placed); best[1]=[ [tuple(p) for p in f] for f in placed]
    for (E,cs) in needed:
        if len(cs)==0: return False     # interior edge can't be filled -> contradiction
    if not frontier: return True
    frontier.sort(key=lambda w: len(w[1]))
    (E,cs)=frontier[0]
    for poly in cs:
        commit(poly)
        if dfs(): return True
        uncommit(poly)
    return False
ok=dfs()
faces=best[1] if best[1] else placed
sq=[f for f in faces if kind(f)=='S']; tri=[f for f in faces if kind(f)=='T']
print("dfs",ok,"nodes",NODES[0],"faces",len(faces),"S",len(sq),"T",len(tri),"T/S=%.2f"%(len(tri)/max(len(sq),1)))
json.dump({'faces':[[list(p) for p in f] for f in faces]}, open('/tmp/snub.json','w'))

# ---- DUALISE to Cairo ----
faces=[[tuple(p) for p in f] for f in faces]
fcen=[cen(f) for f in faces]
vert2faces=defaultdict(list)
for fi,f in enumerate(faces):
    for v in f: vert2faces[rk(v)].append(fi)
pentagons=[]
for v,fis in vert2faces.items():
    if len(fis)!=5: continue              # interior degree-5 vertex
    # order incident face centroids by angle around v
    fis=sorted(fis, key=lambda fi: math.atan2(fcen[fi][1]-v[1], fcen[fi][0]-v[0]))
    poly=[fcen[fi] for fi in fis]
    pentagons.append(poly)
print("Cairo pentagons (from degree-5 vertices):", len(pentagons))
# validate
def sides(poly): return tuple(sorted(round(math.dist(poly[i],poly[(i+1)%5]),3) for i in range(5)))
def iang(poly):
    n=5; out=[]
    for i in range(n):
        a=poly[(i-1)%n]; c=poly[i]; d=poly[(i+1)%n]
        v1=(a[0]-c[0],a[1]-c[1]); v2=(d[0]-c[0],d[1]-c[1])
        out.append(round(abs(math.degrees(math.atan2(v1[0]*v2[1]-v1[1]*v2[0],v1[0]*v2[0]+v1[1]*v2[1])))))
    return tuple(sorted(out))
print("distinct side-length sigs:", set(sides(p) for p in pentagons))
print("distinct angle sigs:", set(iang(p) for p in pentagons))
ec=Counter()
for p in pentagons:
    for i in range(5): ec[ekey(p[i],p[(i+1)%5])]+=1
print("pentagon edge multiplicity:", dict(Counter(ec.values())))
print("pentagon orientations:", dict(Counter(round(math.degrees(math.atan2(p[1][1]-p[0][1],p[1][0]-p[0][0])))%360 for p in pentagons)))
json.dump({'tiles':[[list(pt) for pt in p] for p in pentagons]}, open('/tmp/cairo_final.json','w'))
