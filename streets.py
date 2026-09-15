import json, glob, math, numpy as np
from paths import osm, dem, build, web, dist
from geo import to_xy

WIDTH = {"primary":20,"secondary":16,"tertiary":13,"residential":9,"unclassified":10,
         "living_street":8,"pedestrian":12,"footway":4.5,"steps":3.5,"path":3.5,
         "service":6,"track":4}
SEG_LEN = 40.0     # metres per rendered segment
SAMPLE  = 8.0      # metres between sample points

def street_width(t):
    for k in ("width","est_width"):
        v=t.get(k)
        if v:
            try:
                w=float(str(v).split()[0].replace(",","."))
                if 1<=w<=60: return w
            except Exception: pass
    return WIDTH.get(t.get("highway"), 9)

def load():
    seen=set(); ways=[]
    for fn in sorted(glob.glob(osm("tiles/str_*.json"))):
        for el in json.load(open(fn))["elements"]:
            if el["type"]!="way" or el["id"] in seen: continue
            g=el.get("geometry")
            if not g or len(g)<2: continue
            t=el.get("tags",{}) or {}
            if t.get("highway")=="service" and t.get("service") in ("parking_aisle","driveway"): continue
            seen.add(el["id"]); ways.append((el["id"],t,g))
    return ways

def build_segments():
    segs=[]     # each: dict(name, hw, w, pts=[(x,y)...], covered)
    for wid,t,g in load():
        lons=[p["lon"] for p in g]; lats=[p["lat"] for p in g]
        X,Y=to_xy(lons,lats)
        pts=list(zip(X,Y))
        w=street_width(t)
        name=t.get("name") or t.get("ref") or ""
        covered = (t.get("covered") in ("yes","booth") or t.get("tunnel") in ("building_passage","yes")
                   or t.get("layer","0").startswith("-") and t.get("tunnel"))
        hw=t.get("highway")
        # walk the polyline, cutting every SEG_LEN
        cur=[pts[0]]; acc=0.0
        for a,b in zip(pts[:-1],pts[1:]):
            dx,dy=b[0]-a[0],b[1]-a[1]; L=math.hypot(dx,dy)
            if L<1e-6: continue
            rem=L; px,py=a
            while acc+rem>=SEG_LEN:
                need=SEG_LEN-acc
                px,py = px+dx/L*need, py+dy/L*need
                cur.append((px,py))
                segs.append(dict(name=name,hw=hw,w=w,pts=cur,cov=bool(covered)))
                cur=[(px,py)]; acc=0.0; rem-=need
            if rem>0:
                cur.append(b); acc+=rem
        if len(cur)>=2 and acc>0.8:
            segs.append(dict(name=name,hw=hw,w=w,pts=cur,cov=bool(covered)))
    return segs

def sample_points(segs):
    """Centreline samples with side normals.
    Returns cx, cy, nx, ny, off, seg_idx (one row per centreline sample)."""
    CX=[];CY=[];NXa=[];NYa=[];OF=[];SI=[]
    for i,s in enumerate(segs):
        pts=s["pts"]; off=min(max(s["w"]/2-1.0,0.0),7.0)
        total=sum(math.hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(pts[:-1],pts[1:]))
        n=max(2,int(total//SAMPLE)+1)
        cum=[0.0]
        for a,b in zip(pts[:-1],pts[1:]): cum.append(cum[-1]+math.hypot(b[0]-a[0],b[1]-a[1]))
        for k in range(n):
            d=total*(k+0.5)/n
            j=0
            while j<len(cum)-2 and cum[j+1]<d: j+=1
            a,b=pts[j],pts[j+1]; L=max(cum[j+1]-cum[j],1e-6); f=(d-cum[j])/L
            x=a[0]+(b[0]-a[0])*f; y=a[1]+(b[1]-a[1])*f
            ux,uy=(b[0]-a[0])/L,(b[1]-a[1])/L
            CX.append(x);CY.append(y);NXa.append(-uy);NYa.append(ux);OF.append(off);SI.append(i)
    return (np.array(CX),np.array(CY),np.array(NXa),np.array(NYa),
            np.array(OF),np.array(SI,dtype=np.int32))
