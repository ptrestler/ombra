import json, math, numpy as np, collections
from paths import osm, dem, build, web, dist
from geo import to_xy

S,W,N,E = 41.878, 12.4500, 41.9150, 12.5100
bx0,by0 = to_xy(W,S); bx1,by1 = to_xy(E,N)

segs = json.load(open(build("segments.json")))
keep = []
XY = []
for i,s in enumerate(segs):
    xs,ys = to_xy([p[0] for p in s["g"]],[p[1] for p in s["g"]])
    if xs.min()>=bx0 and xs.max()<=bx1 and ys.min()>=by0 and ys.max()<=by1:
        keep.append(i); XY.append(list(zip(xs.tolist(),ys.tolist())))
segs=[segs[i] for i in keep]
print("segments in bbox:", len(segs))

# a vertex shared by two or more segments (or any segment end) becomes a graph node
K = lambda p: (round(p[0]*20), round(p[1]*20))
touch = collections.defaultdict(set)
for si,pts in enumerate(XY):
    if len(pts)>250: pts=pts[:250]
    for p in pts: touch[K(p)].add(si)

nodekey = {}
def nid(p):
    k=K(p)
    if k not in nodekey: nodekey[k]=len(nodekey)
    return nodekey[k]

eSeg=[]; eI0=[]; eI1=[]; eU=[]; eV=[]; eLen=[]
for si,pts in enumerate(XY):
    if len(pts)>250: pts=pts[:250]
    n=len(pts)
    cuts=[0]+[j for j in range(1,n-1) if len(touch[K(pts[j])])>1]+[n-1]
    for a,b in zip(cuts[:-1],cuts[1:]):
        L=sum(math.dist(pts[j],pts[j+1]) for j in range(a,b))
        if L<0.4: continue
        u=nid(pts[a]); v=nid(pts[b])
        if u==v: continue
        eSeg.append(si); eI0.append(a); eI1.append(b)
        eU.append(u); eV.append(v); eLen.append(min(65535,int(round(L*10))))
print("nodes:", len(nodekey), " edges:", len(eSeg),
      " total length km:", round(sum(eLen)/10/1000,1))

# connected components (undirected)
NN=len(nodekey)
adj=collections.defaultdict(list)
for u,v in zip(eU,eV): adj[u].append(v); adj[v].append(u)
comp=[-1]*NN; sizes=[]
for s0 in range(NN):
    if comp[s0]>=0: continue
    c=len(sizes); stack=[s0]; comp[s0]=c; cnt=0
    while stack:
        x=stack.pop(); cnt+=1
        for y in adj[x]:
            if comp[y]<0: comp[y]=c; stack.append(y)
    sizes.append(cnt)
big=int(np.argmax(sizes))
print("components:", len(sizes), " largest:", sizes[big],
      f"({sizes[big]/NN*100:.1f}% of nodes)", " next:", sorted(sizes)[-4:])
np.savez(build("graph.npz"),
         eSeg=np.array(eSeg,np.uint16), eI0=np.array(eI0,np.uint8),
         eI1=np.array(eI1,np.uint8), eU=np.array(eU,np.uint32),
         eV=np.array(eV,np.uint32), eLen=np.array(eLen,np.uint16),
         comp=np.array(comp,np.uint16), big=np.array([big],np.uint16))

# ---- heal genuine breaks: merge a dangling endpoint into a nearby node ONLY
# ---- when the two sit in different components (never rewires connected areas)
from scipy.spatial import cKDTree
NC=np.zeros((NN,2))
for k,i in nodekey.items(): NC[i]=(k[0]/20.0,k[1]/20.0)
parent=list(range(NN))
def find(a):
    while parent[a]!=a: parent[a]=parent[parent[a]]; a=parent[a]
    return a
def union(a,b):
    ra,rb=find(a),find(b)
    if ra==rb: return False
    parent[rb]=ra; return True
for u,v in zip(eU,eV): union(u,v)

R=2.0
deg=np.bincount(np.r_[np.array(eU),np.array(eV)],minlength=NN)
dang=np.flatnonzero(deg==1)
tree2=cKDTree(NC)
cand=[]
for i in dang:
    dd,jj = tree2.query(NC[i], k=6, distance_upper_bound=R)
    for dv,j in zip(np.atleast_1d(dd),np.atleast_1d(jj)):
        if j<NN and j!=i and np.isfinite(dv): cand.append((float(dv),int(i),int(j)))
cand.sort()
remap=list(range(NN)); healed=0
for dv,i,j in cand:
    if find(i)!=find(j):
        union(i,j); remap[i]=j; healed+=1
print(f"healed {healed} breaks by snapping dangling endpoints within {R} m")

def rt(a):
    seen=0
    while remap[a]!=a and seen<8: a=remap[a]; seen+=1
    return a
eU2=np.array([rt(int(u)) for u in eU],np.uint32)
eV2=np.array([rt(int(v)) for v in eV],np.uint32)

adj2=collections.defaultdict(list)
for u,v in zip(eU2,eV2): adj2[int(u)].append(int(v)); adj2[int(v)].append(int(u))
comp2=[-1]*NN; sizes2=[]
live=set(int(x) for x in eU2)|set(int(x) for x in eV2)
for s0 in sorted(live):
    if comp2[s0]>=0: continue
    c=len(sizes2); stack=[s0]; comp2[s0]=c; cnt=0
    while stack:
        x=stack.pop(); cnt+=1
        for y in adj2[x]:
            if comp2[y]<0: comp2[y]=c; stack.append(y)
    sizes2.append(cnt)
big2=int(np.argmax(sizes2))
print("after healing -> components:",len(sizes2),
      " largest:",sizes2[big2], f"({sizes2[big2]/len(live)*100:.1f}% of live nodes)",
      " next:",sorted(sizes2)[-4:])
np.savez(build("graph.npz"),
         eSeg=np.array(eSeg,np.uint16), eI0=np.array(eI0,np.uint8), eI1=np.array(eI1,np.uint8),
         eU=eU2, eV=eV2, eLen=np.array(eLen,np.uint16),
         comp=np.array([comp2[i] if comp2[i]>=0 else 65535 for i in range(NN)],np.uint16),
         big=np.array([big2],np.uint16), nnode=np.array([NN],np.uint32))
