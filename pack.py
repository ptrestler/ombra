import json, glob, math, numpy as np, gzip, struct, base64
from paths import osm, dem, build, web, dist
from geo import to_xy

QS=0.5; OX=-3400.0; OY=-2900.0
S,W,N,E = 41.878, 12.4500, 41.9150, 12.5100
bx0,by0=to_xy(W,S); bx1,by1=to_xy(E,N)

def q(v,o): return np.round((np.asarray(v)-o)/QS).astype("<u2")

def rdp(pts,eps):
    if len(pts)<3: return pts
    def d(p,a,b):
        dx,dy=b[0]-a[0],b[1]-a[1]; L=math.hypot(dx,dy)
        if L<1e-9: return math.hypot(p[0]-a[0],p[1]-a[1])
        return abs(dy*p[0]-dx*p[1]+b[0]*a[1]-b[1]*a[0])/L
    st=[(0,len(pts)-1)]; keep=[False]*len(pts); keep[0]=keep[-1]=True
    while st:
        i,j=st.pop()
        if j<=i+1: continue
        mx,mi=-1,-1
        for k in range(i+1,j):
            dd=d(pts[k],pts[i],pts[j])
            if dd>mx: mx,mi=dd,k
        if mx>eps: keep[mi]=True; st.append((i,mi)); st.append((mi,j))
    return [p for p,k in zip(pts,keep) if k]

def rings(el):
    if el["type"]=="way":
        g=el.get("geometry")
        if g and len(g)>=3: yield [(p["lon"],p["lat"]) for p in g]
    else:
        for m in el.get("members",[]):
            if m.get("type")=="way" and m.get("role") in ("outer",""):
                g=m.get("geometry")
                if g and len(g)>=3: yield [(p["lon"],p["lat"]) for p in g]

def polys_from(files, eps=1.2, tagfilter=None):
    seen=set(); out=[]
    for fn in files:
        for el in json.load(open(fn))["elements"]:
            k=(el["type"],el["id"])
            if k in seen: continue
            seen.add(k)
            if tagfilter and not tagfilter(el.get("tags",{}) or {}): continue
            for r in rings(el):
                xs,ys=to_xy([p[0] for p in r],[p[1] for p in r])
                p=rdp(list(zip(xs.tolist(),ys.tolist())),eps)
                if len(p)>=3: out.append(p)
    return out

def encode_polys(polys, maxpts=250):
    fixed=[]
    for p in polys:
        while len(p)>maxpts:
            fixed.append(p[:maxpts]); p=p[maxpts-1:]
        if len(p)>=3: fixed.append(p)
    cnt=np.array([len(p) for p in fixed],np.uint8)
    xs=np.array([a for p in fixed for a,b in p]); ys=np.array([b for p in fixed for a,b in p])
    return cnt.tobytes(), q(xs,OX).tobytes(), q(ys,OY).tobytes(), len(fixed)

# ---------- layers ----------
bld  = polys_from(sorted(glob.glob(osm("tiles/bld_*.json"))), 1.2)
wat  = polys_from([osm("extra_water.json")], 3.0)
grn  = polys_from([osm("extra_green.json")], 3.0,
                  lambda t: t.get("leisure") in ("park","garden") or t.get("natural")=="wood"
                            or t.get("landuse") in ("forest","cemetery"))
print("polys: bld",len(bld),"water",len(wat),"green",len(grn))

# ---------- streets + shade ----------
segs=json.load(open(build("segments.json"))); F=np.load(build("frames.npy")); meta=json.load(open(build("frames_meta.json")))
keep=[]
for i,s in enumerate(segs):
    xs,ys=to_xy([p[0] for p in s["g"]],[p[1] for p in s["g"]])
    if xs.min()>=bx0 and xs.max()<=bx1 and ys.min()>=by0 and ys.max()<=by1: keep.append(i)
keep=np.array(keep); print("segments kept",len(keep),"of",len(segs))
segs=[segs[i] for i in keep]; F=F[:,keep]

KINDS=["primary","secondary","tertiary","residential","unclassified","living_street",
       "pedestrian","footway","steps","path","service","track"]
names=sorted({s["n"] for s in segs if s["n"]})
nidx={n:i for i,n in enumerate(names)}
scnt=[];SXl=[];SYl=[];kind=[];nm=[];cov=[]
for s in segs:
    xs,ys=to_xy([p[0] for p in s["g"]],[p[1] for p in s["g"]])
    pts=list(zip(xs.tolist(),ys.tolist()))
    if len(pts)>250: pts=pts[:250]
    scnt.append(len(pts)); SXl+= [p[0] for p in pts]; SYl+=[p[1] for p in pts]
    kind.append(KINDS.index(s["k"]) if s["k"] in KINDS else 4)
    nm.append(nidx.get(s["n"],65535)); cov.append(1 if s["c"] else 0)

T=np.ascontiguousarray(F.T).astype(np.uint8)   # [seg, frame]

bc,bxs,bys,nb = encode_polys(bld)
wc,wxs,wys,nw = encode_polys(wat)
gc,gxs,gys,ng = encode_polys(grn)

parts=[]; hdr={}; off=0
def add(name, buf, dtype, n):
    global off
    hdr[name]=dict(o=off,n=n,t=dtype); parts.append(buf); off+=len(buf)
add("bcnt",bc,"u1",nb); add("bx",bxs,"u2",len(bxs)//2); add("by",bys,"u2",len(bys)//2)
add("wcnt",wc,"u1",nw); add("wx",wxs,"u2",len(wxs)//2); add("wy",wys,"u2",len(wys)//2)
add("gcnt",gc,"u1",ng); add("gx",gxs,"u2",len(gxs)//2); add("gy",gys,"u2",len(gys)//2)
add("scnt",np.array(scnt,np.uint8).tobytes(),"u1",len(scnt))
add("sx",q(np.array(SXl),OX).tobytes(),"u2",len(SXl))
add("sy",q(np.array(SYl),OY).tobytes(),"u2",len(SYl))
add("kind",np.array(kind,np.uint8).tobytes(),"u1",len(kind))
add("name",np.array(nm,"<u2").tobytes(),"u2",len(nm))
add("cov",np.array(cov,np.uint8).tobytes(),"u1",len(cov))
add("shade",T.tobytes(),"u1",T.size)

G=np.load(build("graph.npz"))
add("eSeg",G["eSeg"].tobytes(),"u2",len(G["eSeg"]))
add("eI0", G["eI0"].tobytes(), "u1",len(G["eI0"]))
add("eI1", G["eI1"].tobytes(), "u1",len(G["eI1"]))
add("eU",  G["eU"].tobytes(),  "u4",len(G["eU"]))
add("eV",  G["eV"].tobytes(),  "u4",len(G["eV"]))
add("eLen",G["eLen"].tobytes(),"u2",len(G["eLen"]))
NNODE=int(G["nnode"][0]); NEDGE=len(G["eSeg"])
print("graph packed: nodes",NNODE,"edges",NEDGE)

gj=json.load(open(build("grid.json")))
PP=json.load(open(build("places_pack.json")))
CATS=sorted({p["c"] for p in PP["places"]})
pl=[[p["n"], CATS.index(p["c"]),
     int(round((to_xy(p["lon"],p["lat"])[0]-OX)/QS)),
     int(round((to_xy(p["lon"],p["lat"])[1]-OY)/QS)), p["s"]] for p in PP["places"]]
print("places packed:", len(pl), "cats", CATS)
head=dict(sections=hdr, nbld=gj.get("nbld"), nknown=gj.get("nknown"),
          ncad=gj.get("ncadastre"),
          nnode=NNODE, nedge=NEDGE, pl=pl, cats=CATS, top=PP["top"], qs=QS, ox=OX, oy=OY, nseg=len(segs), nframe=T.shape[1],
          kinds=KINDS, names=names, frames=meta,
          bbox=dict(x0=float(bx0),y0=float(by0),x1=float(bx1),y1=float(by1)),
          proj=dict(lat0=41.8965, lon0=12.4800, mperlat=111132.0,
                    mperlon=111320.0*math.cos(math.radians(41.8965))))
hb=json.dumps(head,ensure_ascii=False,separators=(",",":")).encode()
blob=struct.pack("<I",len(hb))+hb+b"".join(parts)
gz=gzip.compress(blob,9)
b64=base64.b64encode(gz).decode()
open(build("data.b64"),"w").write(b64)
print("raw",len(blob)/1e6,"MB  gzip",len(gz)/1e6,"MB  b64",len(b64)/1e6,"MB")
