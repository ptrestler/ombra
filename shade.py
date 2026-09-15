import json, math, numpy as np, time
from paths import osm, dem, build, web, dist
from solar import solar_pos
from streets import build_segments, sample_points
from geo import to_ll

LAT,LON = 41.8965, 12.4800
import calendar as _cal
def _last_sunday(y,m):
    d=_cal.monthrange(y,m)[1]
    while _cal.weekday(y,m,d)!=6: d-=1
    return d
def tz_for(y,mo,day):
    """EU civil time in Rome: CEST (+2) from the last Sunday of March
    to the last Sunday of October, otherwise CET (+1)."""
    start=(3,_last_sunday(y,3)); end=(10,_last_sunday(y,10))
    return 2 if start <= (mo,day) < end else 1
EYE=1.7
DATES=[(mo,d) for mo in range(1,13) for d in (1,15)]
TIMES=[(h,m) for h in range(6,22) for m in (0,30)]

g=json.load(open(build("grid.json")))
dsm=np.load(build("dsm.npy")); bmask=np.load(build("bmask.npy"))
NY,NX=dsm.shape; x0,y1,RES=g["x0"],g["y1"],g["RES"]

# --- terrain -------------------------------------------------------------
# dsm holds object height ABOVE LOCAL GROUND; ground holds the ground itself.
# A surface elevation is therefore ground(q) + object(q), and the observer's
# eye sits at ground(p) + EYE. This is what lets a hill shadow a valley.
G=np.load(build("ground.npy")); gm=json.load(open(build("terr.json")))
GX0,GY0,GRES,GNY,GNX = gm["TX0"],gm["TY0"],gm["RES"],gm["NY"],gm["NX"]
def gnd(x,y):
    c=np.clip(((np.asarray(x)-GX0)/GRES).astype(np.int32),0,GNX-1)
    r=np.clip((GNY-1-((np.asarray(y)-GY0)/GRES)).astype(np.int32),0,GNY-1)
    return G[r,c].astype(np.float64)
MAXSURF=float(G.max())+float(dsm.max())/10.0
DMAX_CAP=2500.0
print("ground",G.shape,"range",round(float(G.min()),1),"-",round(float(G.max()),1),
      "m; max surface",round(MAXSURF,1),"m")

segs=build_segments()
CX,CY,NXn,NYn,OFF,SI=sample_points(segs)
print("segments",len(segs),"centreline samples",len(CX))

def cell(x,y):
    c=np.clip(((x-x0)/RES).astype(np.int32),0,NX-1)
    r=np.clip(((y1-y)/RES).astype(np.int32),0,NY-1)
    return r,c

def in_bldg(x,y):
    r,c=cell(x,y); return bmask[r,c]>30

# choose a walkable point on each side: outermost offset that isn't inside a building
FRACS=[1.0,0.65,0.35,0.0]
PX=np.zeros((2,len(CX))); PY=np.zeros((2,len(CX))); COV=np.zeros(len(CX),bool)
for si,sgn in enumerate((1.0,-1.0)):
    chosen=np.zeros(len(CX),bool)
    px=CX.copy(); py=CY.copy()
    for f in FRACS:
        x=CX+NXn*OFF*sgn*f; y=CY+NYn*OFF*sgn*f
        good=(~in_bldg(x,y)) & (~chosen)
        px[good]=x[good]; py[good]=y[good]; chosen |= good
    PX[si]=px; PY[si]=py
    if sgn==1.0: COV = in_bldg(CX,CY)
print("centreline inside a building (arcade/passage):", round(float(COV.mean())*100,2),"%")

SX=np.concatenate([PX[0],PX[1]]); SY=np.concatenate([PY[0],PY[1]])
inside=in_bldg(SX,SY)
print("chosen sample pts still inside a building:", round(float(inside.mean())*100,2),"%")

EYEZ = gnd(SX,SY) + EYE          # absolute eye elevation per sample point
MINOBS = float(EYEZ.min())

def shade_mask(elev,az):
    if elev<=3.0: return np.ones(len(SX),bool)
    er=math.radians(elev); ar=math.radians(az)
    ex,nv=math.sin(ar),math.cos(ar); te=math.tan(er)
    dmax=min(DMAX_CAP,(MAXSURF-MINOBS)/te+5)
    blocked=inside.copy(); act=np.flatnonzero(~blocked)
    ax,ay=SX[act],SY[act]; az0=EYEZ[act]; d=0.0
    while d<dmax and act.size:
        step=2.0 if d<50 else (4.0 if d<140 else (8.0 if d<400 else 25.0))
        d+=step
        qx=ax+ex*d; qy=ay+nv*d
        c=((qx-x0)/RES).astype(np.int32); r=((y1-qy)/RES).astype(np.int32)
        ok=(c>=0)&(c<NX)&(r>=0)&(r<NY)
        obj=np.zeros(act.size); cc=np.clip(c,0,NX-1); rr=np.clip(r,0,NY-1)
        obj[ok]=dsm[rr[ok],cc[ok]]/10.0
        surf=gnd(qx,qy)+obj
        hit=surf>(az0+d*te)
        if hit.any():
            blocked[act[hit]]=True; k=~hit
            act=act[k]; ax=ax[k]; ay=ay[k]; az0=az0[k]
    return blocked

n=len(CX); cnt=np.bincount(SI,minlength=len(segs)).astype(np.float64)
frames=[]; meta=[]; t0=time.time()
for (mo,day) in DATES:
    tz=tz_for(2026,mo,day)
    for (h,mi) in TIMES:
        e,a=solar_pos(2026,mo,day,h,mi,LAT,LON,tz); e=float(e); a=float(a)
        meta.append(dict(mo=mo,d=day,h=h,mi=mi,el=round(e,2),az=round(a,2),tz=tz))
        if e<=3.0:
            frames.append(np.full(len(segs),100,np.uint8)); continue
        b=shade_mask(e,a)
        pair=b[:n]|b[n:]
        sh=np.bincount(SI,weights=pair.astype(np.float64),minlength=len(segs))
        frames.append(np.round(np.where(cnt>0,sh/np.maximum(cnt,1)*100,0)).astype(np.uint8))
    print("date",mo,day,"tz+%d"%tz,f"{time.time()-t0:.0f}s",flush=True)

F=np.stack(frames)
np.save(build("frames.npy"),F); json.dump(meta,open(build("frames_meta.json"),"w"))
out=[]
for s in segs:
    lo,la=to_ll(np.array([p[0] for p in s["pts"]]),np.array([p[1] for p in s["pts"]]))
    out.append(dict(n=s["name"],k=s["hw"],w=round(s["w"],1),c=1 if s["cov"] else 0,
                    g=[[float(a),float(b)] for a,b in zip(lo,la)]))
json.dump(out,open(build("segments.json"),"w"))
print("frames",F.shape,f"{time.time()-t0:.0f}s")
