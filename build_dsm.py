import json, glob, math, numpy as np, os
from paths import osm, dem, eub, build, web, dist
from PIL import Image, ImageDraw
from scipy.spatial import cKDTree
from geo import to_xy
from heights import building_height, cadastre_heights

RES=2.0
S,W,N,E = 41.878, 12.4500, 41.9150, 12.5100
x0,y0 = to_xy(W,S); x1,y1 = to_xy(E,N)
NX=int(math.ceil((x1-x0)/RES)); NY=int(math.ceil((y1-y0)/RES))
def px(x,y): return ((x-x0)/RES,(y1-y)/RES)

def rings(el):
    if el["type"]=="way":
        g=el.get("geometry")
        if g and len(g)>=3: yield [(p["lon"],p["lat"]) for p in g]
    else:
        for m in el.get("members",[]):
            if m.get("type")=="way" and m.get("role") in ("outer",""):
                g=m.get("geometry")
                if g and len(g)>=3: yield [(p["lon"],p["lat"]) for p in g]

blds=[]; seen=set()
for fn in sorted(glob.glob(osm("tiles/bld_*.json"))):
    for el in json.load(open(fn))["elements"]:
        k=(el["type"],el["id"])
        if k in seen: continue
        seen.add(k)
        t=el.get("tags",{}) or {}
        h,src=building_height(t)
        rr=list(rings(el))
        if not rr: continue
        allpts=[p for r in rr for p in r]
        cx=sum(p[0] for p in allpts)/len(allpts); cy=sum(p[1] for p in allpts)/len(allpts)
        blds.append(dict(h=h,src=src,rings=rr,c=(cx,cy)))

known=[b for b in blds if b["src"] in ("tag","levels")]
unk  =[b for b in blds if b["src"]=="default"]
print("buildings",len(blds),"known",len(known),"untagged",len(unk))
ncad=0
if known:
    # An untagged building gets a real cadastre height if one sits close enough,
    # and an interpolated one otherwise. OSM tags always win over both: they are
    # the yardstick everything else was measured against. See heights.py.
    CH = cadastre_heights(eub("rome.csv"),
                          [b["c"][0] for b in unk], [b["c"][1] for b in unk])

    KX,KY = to_xy([b["c"][0] for b in known],[b["c"][1] for b in known])
    tree = cKDTree(np.c_[KX,KY]); KH=np.array([b["h"] for b in known])
    gmed=float(np.median(KH))
    UX,UY = to_xy([b["c"][0] for b in unk],[b["c"][1] for b in unk])
    K=15
    d,i = tree.query(np.c_[UX,UY], k=K, distance_upper_bound=500.0)
    for j,b in enumerate(unk):
        if np.isfinite(CH[j]):
            b["h"]=float(CH[j]); b["src"]="cadastre"; ncad+=1
            continue
        idx=i[j]; dd=d[j]; ok=np.isfinite(dd)
        # Inverse-distance weighted mean, not a median. Measured by leave-one-out
        # against the 2,443 tagged heights: RMSE 6.47 m -> 5.83 m, and it removes a
        # +0.52 m bias. Blending in a per-type prior was tried and made both worse,
        # because buildings of a type already cluster spatially.
        if ok.any():
            w = 1.0/np.maximum(dd[ok], 1.0)
            est = float(np.sum(w*KH[idx[ok]])/np.sum(w))
        else:
            est = gmed
        b["h"]=float(np.clip(est, 7.0, 34.0))
    print(f"  cadastre {ncad} ({100*ncad/len(unk):.0f}% of untagged)   interpolated {len(unk)-ncad}")
    for lbl,sel in (("cadastre",  [b for b in unk if b["src"]=="cadastre"]),
                    ("interpolated",[b for b in unk if b["src"]=="default"]),
                    ("all untagged", unk)):
        hh=np.array([b["h"] for b in sel])
        print(f"  {lbl:<13} median {np.median(hh):5.1f}  p10 {np.percentile(hh,10):5.1f}  p90 {np.percentile(hh,90):5.1f}")

img=Image.new("I;16",(NX,NY),0); d=ImageDraw.Draw(img)
for b in blds:
    for r in b["rings"]:
        xs,ys=to_xy([p[0] for p in r],[p[1] for p in r])
        pts=[px(a,c) for a,c in zip(xs,ys)]
        if len(pts)>=3: d.polygon(pts, fill=int(min(b["h"],120)*10))
bmask=np.array(img,dtype=np.uint16)

# ---- canopy layer -------------------------------------------------------
cim=Image.new("I;16",(NX,NY),0); cd=ImageDraw.Draw(cim)
CAN_H=9.0; WOOD_H=11.0
ntree=0; nrow=0; nwood=0
for el in json.load(open(osm("extra_trees.json")))["elements"]:
    if el["type"]=="node":
        x,y=to_xy(el["lon"],el["lat"]); a,b=px(float(x),float(y)); r=4.0/RES
        cd.ellipse([a-r,b-r,a+r,b+r], fill=int(CAN_H*10)); ntree+=1
    elif el["type"]=="way" and el.get("geometry"):
        g=el["geometry"]; xs,ys=to_xy([p["lon"] for p in g],[p["lat"] for p in g])
        pts=[px(a,b) for a,b in zip(xs,ys)]
        if len(pts)>=2:
            cd.line(pts, fill=int(CAN_H*10), width=max(1,int(7.0/RES)), joint="curve")
            for a,b in pts:
                r=3.5/RES; cd.ellipse([a-r,b-r,a+r,b+r], fill=int(CAN_H*10))
            nrow+=1
green=json.load(open(osm("extra_green.json")))["elements"]
for el in green:
    t=el.get("tags",{}) or {}
    if t.get("natural")=="wood" or t.get("landuse")=="forest":
        for r in rings(el):
            xs,ys=to_xy([p[0] for p in r],[p[1] for p in r])
            pts=[px(a,b) for a,b in zip(xs,ys)]
            if len(pts)>=3: cd.polygon(pts, fill=int(WOOD_H*10)); nwood+=1
print("canopy: trees",ntree,"rows",nrow,"wood",nwood)
canopy=np.array(cim,dtype=np.uint16)
dsm=np.maximum(bmask,canopy)
np.save(build("dsm.npy"),dsm); np.save(build("canopy.npy"),canopy); np.save(build("bmask.npy"),bmask)
json.dump({"x0":float(x0),"y0":float(y0),"x1":float(x1),"y1":float(y1),"NX":NX,"NY":NY,"RES":RES,
           "S":S,"W":W,"N":N,"E":E,"nbld":len(blds),"nknown":len(known),"ncadastre":ncad},open(build("grid.json"),"w"))
print("dsm max",dsm.max()/10,"coverage",round(float((dsm>0).mean()),3))
