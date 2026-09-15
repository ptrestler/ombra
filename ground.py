"""Terrain for the shade model.

The elevation tiles are a SURFACE model: buildings are baked into them. Measured
against known heights, open ground and hilltops read accurately but the dense
centre sits ~12 m high, and the relief between hill and valley is compressed by
~8 m (valleys are built up, hilltops often are not).

Three ways of recovering bare earth were tried and ALL made the relief worse:
  * morphological opening  - fails because the centro storico is continuously
    built up, so no window contains ground to erode to
  * interpolating through OSM-derived open cells - drags built-up hilltops down
  * subtracting modelled building lift - flattens hills more than valleys

Relief is what drives hill shadowing, so the raw DEM wins and its residual bias
is documented rather than "corrected". This script picks the smoothing that
minimises relief error and records the score.
"""
import json
import numpy as np
from scipy import ndimage as ndi
from paths import build
from geo import to_xy

t = np.load(build("terr.npy")).astype(np.float64)
m = json.load(open(build("terr.json")))
TX0, TY0, TRES, TNY = m["TX0"], m["TY0"], m["RES"], m["NY"]

def sample(g, lat, lon):
    x, y = to_xy(lon, lat)
    c = int((x - TX0) / TRES); r = int(TNY - 1 - (y - TY0) / TRES)
    return float(g[np.clip(r, 0, g.shape[0]-1), np.clip(c, 0, g.shape[1]-1)])

# approximate published ground heights, used only to score relief (differences),
# which is far less sensitive to a few metres of error in any single reference
P = {"Tiber":(41.8927,12.4707), "Trastevere":(41.8894,12.4695), "Gianicolo":(41.8917,12.4614),
     "CircoMassimo":(41.8860,12.4853), "Aventino":(41.8842,12.4794), "Venezia":(41.8959,12.4823),
     "Campidoglio":(41.8933,12.4828), "Quirinale":(41.8996,12.4870), "Colosseo":(41.8902,12.4922),
     "Palatino":(41.8892,12.4874), "Popolo":(41.9109,12.4763), "Pincio":(41.9110,12.4785)}
PAIRS = [("Gianicolo","Trastevere",68), ("Gianicolo","Tiber",72), ("Aventino","CircoMassimo",28),
         ("Campidoglio","Venezia",26), ("Quirinale","Venezia",41), ("Palatino","Colosseo",26),
         ("Pincio","Popolo",35), ("Aventino","Tiber",36)]

def relief_rmse(g):
    e = np.array([sample(g,*P[a]) - sample(g,*P[b]) - r for a, b, r in PAIRS])
    return float(np.sqrt(np.mean(e**2))), float(e.mean())

flat = float(np.sqrt(np.mean(np.array([r for _,_,r in PAIRS], float)**2)))
print(f"flat ground (no terrain at all)   relief RMSE {flat:5.1f} m")
best = None
for sig_m in (0, 20, 30, 50, 80):
    g = t if sig_m == 0 else ndi.gaussian_filter(t, sig_m / TRES)
    rmse, bias = relief_rmse(g)
    print(f"DEM terrain, {sig_m:2d} m smoothing       relief RMSE {rmse:5.1f} m  (bias {bias:+.1f})")
    if best is None or rmse < best[0]:
        best = (rmse, sig_m)
rmse, sig_m = best
g = t if sig_m == 0 else ndi.gaussian_filter(t, sig_m / TRES)
np.save(build("ground.npy"), g.astype(np.float32))
json.dump({"smoothing_m": sig_m, "relief_rmse_m": round(rmse,1), "flat_rmse_m": round(flat,1)},
          open(build("ground_meta.json"), "w"))
print(f"\nchosen: {sig_m} m smoothing, relief RMSE {rmse:.1f} m "
      f"({flat/rmse:.1f}x better than flat) -> build/ground.npy")
