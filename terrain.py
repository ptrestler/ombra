"""Terrain grid for the Rome shade model.
Source: AWS Open Data terrain tiles (Terrarium encoding), SRTM/NED-derived, ~30 m.
Sampled onto a 10 m grid covering the map bbox plus a 2 km pad, so hills outside
the mapped area can still cast shadows into it."""
import math, io, json, os, time, urllib.request
from paths import osm, dem, build, web, dist
import numpy as np
from PIL import Image
from geo import to_xy, to_ll

Z    = 14
PAD  = 2000.0      # metres beyond the bbox
RES  = 10.0        # metres per cell
S,W,N,E = 41.878, 12.4500, 41.9150, 12.5100
bx0,by0 = to_xy(W,S); bx1,by1 = to_xy(E,N)
TX0,TY0 = bx0-PAD, by0-PAD
TX1,TY1 = bx1+PAD, by1+PAD
NX = int(math.ceil((TX1-TX0)/RES)); NY = int(math.ceil((TY1-TY0)/RES))
print(f"terrain grid {NX} x {NY} @ {RES:.0f} m  ({(TX1-TX0)/1000:.1f} x {(TY1-TY0)/1000:.1f} km)")

def lonlat_to_px(lon, lat, z):
    n = 2.0**z
    x = (lon+180.0)/360.0*n*256.0
    lr = math.radians(lat)
    y = (1.0 - math.log(math.tan(lr)+1.0/math.cos(lr))/math.pi)/2.0*n*256.0
    return x, y


def tile(z,x,y):
    fn=dem(f"{z}_{x}_{y}.png")
    if not os.path.exists(fn):
        url=f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
        for a in range(4):
            try:
                r=urllib.request.Request(url,headers={"User-Agent":"rome-shade/1.0"})
                with urllib.request.urlopen(r,timeout=90) as f: raw=f.read()
                open(fn,"wb").write(raw); break
            except Exception as e:
                if a==3: raise
                time.sleep(2+2*a)
    return np.asarray(Image.open(fn).convert("RGB"), dtype=np.float64)

# which tiles do we need?
corners=[(TX0,TY0),(TX1,TY0),(TX0,TY1),(TX1,TY1)]
pxs=[]
for cx,cy in corners:
    lo,la = to_ll(np.array([cx]),np.array([cy]))
    pxs.append(lonlat_to_px(float(lo[0]),float(la[0]),Z))
px0=min(p[0] for p in pxs); px1=max(p[0] for p in pxs)
py0=min(p[1] for p in pxs); py1=max(p[1] for p in pxs)
tx0,tx1=int(px0//256),int(px1//256); ty0,ty1=int(py0//256),int(py1//256)
print("tiles:", (tx1-tx0+1)*(ty1-ty0+1), f"x {tx0}..{tx1}  y {ty0}..{ty1}")

# stitch into one array covering the tile range
H=(ty1-ty0+1)*256; Wd=(tx1-tx0+1)*256
big=np.zeros((H,Wd),dtype=np.float64)
for ty in range(ty0,ty1+1):
    for tx in range(tx0,tx1+1):
        a=tile(Z,tx,ty)
        big[(ty-ty0)*256:(ty-ty0+1)*256,(tx-tx0)*256:(tx-tx0+1)*256] = \
            a[:,:,0]*256.0 + a[:,:,1] + a[:,:,2]/256.0 - 32768.0
print("stitched", big.shape, "elev range", round(big.min(),1), "to", round(big.max(),1), "m")

# sample onto the local grid (bilinear)
gx = TX0 + (np.arange(NX)+0.5)*RES
gy = TY0 + (np.arange(NY)+0.5)*RES
GX,GY = np.meshgrid(gx, gy)
LO,LA = to_ll(GX, GY)
n=2.0**Z
fx=(LO+180.0)/360.0*n*256.0 - tx0*256.0
lr=np.radians(LA)
fy=(1.0-np.log(np.tan(lr)+1.0/np.cos(lr))/np.pi)/2.0*n*256.0 - ty0*256.0
x0=np.clip(np.floor(fx).astype(int),0,Wd-2); y0=np.clip(np.floor(fy).astype(int),0,H-2)
dx=np.clip(fx-x0,0,1); dy=np.clip(fy-y0,0,1)
terr=(big[y0,x0]*(1-dx)*(1-dy) + big[y0,x0+1]*dx*(1-dy) +
      big[y0+1,x0]*(1-dx)*dy   + big[y0+1,x0+1]*dx*dy)
terr=terr[::-1]                    # row 0 = north, matching the building raster
np.save(build("terr.npy"), terr.astype(np.float32))
json.dump(dict(TX0=TX0,TY0=TY0,TX1=TX1,TY1=TY1,NX=NX,NY=NY,RES=RES,PAD=PAD,Z=Z),
          open(build("terr.json"),"w"))
print("terrain saved:", terr.shape, "min", round(float(terr.min()),1),
      "max", round(float(terr.max()),1), "mean", round(float(terr.mean()),1))
