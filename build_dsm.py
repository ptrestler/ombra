import json, math, numpy as np, os
from paths import osm, dem, eub, build, web, dist
from PIL import Image, ImageDraw
from scipy.spatial import cKDTree
from geo import to_xy
from heights import cadastre_heights, CADASTRE_RMSE_M, INTERP_RMSE_M
from buildings import load as load_buildings, rings   # rings: the wooded areas below

RES=2.0
S,W,N,E = 41.878, 12.4500, 41.9150, 12.5100
x0,y0 = to_xy(W,S); x1,y1 = to_xy(E,N)
NX=int(math.ceil((x1-x0)/RES)); NY=int(math.ceil((y1-y0)/RES))
def px(x,y): return ((x-x0)/RES,(y1-y)/RES)

blds = load_buildings()
known=[b for b in blds if b["src"] in ("tag","levels")]
unk  =[b for b in blds if b["src"]=="default"]
print("buildings",len(blds),"known",len(known),"untagged",len(unk))
ncad=0
if known:
    # An untagged building gets a real cadastre height if the cadastre reaches
    # it -- by the parcels inside its own outline, or failing that the nearest
    # parcel centroid -- and an interpolated one otherwise. OSM tags always win
    # over both: they are the yardstick everything else was measured against.
    # See heights.py.
    CH = cadastre_heights(eub("rome.csv"), [b["rings"] for b in unk],
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

# How much of the map rests on the estimates? Set OMBRA_JITTER=<seed> and every
# estimated height moves by its own measured error, so the frames this produces
# can be diffed against the real ones. The claim in the UI's methodology panel
# comes from that diff, and this is the only way to re-derive it. A build with
# no such variable set is untouched.
seed = os.environ.get("OMBRA_JITTER")
if seed:
    rng = np.random.default_rng(int(seed))
    for b in blds:
        if b["src"] == "cadastre":  sd = CADASTRE_RMSE_M
        elif b["src"] == "default": sd = INTERP_RMSE_M
        else:                       continue         # a tag is not an estimate
        b["h"] = float(max(2.0, b["h"] + rng.normal(0.0, sd)))
    print(f"  JITTERED with seed {seed}: this build is a sensitivity probe, not a map")

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
