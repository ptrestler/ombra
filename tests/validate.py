#!/usr/bin/env python3
"""Model checks. These guard the physics and the data, not the UI.
Run with `make test` or `python3 tests/validate.py`."""
import json, os, sys, calendar
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import build
from solar import solar_pos
from geo import to_xy

LAT, LON = 41.9028, 12.4964
fails = []
def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  ' + detail) if detail else ''}")
    if not ok: fails.append(name)

print("\nsolar position")
# max elevation at solar noon must equal 90 - latitude +/- declination
for mo, day, dec, label in [(6,21,23.44,"summer solstice"), (12,21,-23.44,"winter solstice")]:
    tz = 2 if mo == 6 else 1
    best = max(solar_pos(2026,mo,day,h,m,LAT,LON,tz)[0]
               for h in range(9,17) for m in (0,15,30,45))
    expect = 90 - LAT + dec
    check(f"{label} peak elevation", abs(best-expect) < 0.6, f"{best:.1f} vs {expect:.1f}")

def crossing(mo, d, tz, rising):
    lo, hi = (0,13) if rising else (13,24)
    for _ in range(40):
        m = (lo+hi)/2
        e,_ = solar_pos(2026, mo, d, int(m), (m-int(m))*60, LAT, LON, tz)
        if (e < -0.833) == rising: lo = m
        else: hi = m
    m = (lo+hi)/2
    return f"{int(m):02d}:{int(round((m-int(m))*60)):02d}"
for mo,d,tz,rise,setq,label in [(6,21,2,"05:35","20:49","Jun 21"),
                                (12,21,1,"07:34","16:42","Dec 21"),
                                (3,20,1,"06:12","18:20","Mar 20")]:
    got = (crossing(mo,d,tz,True), crossing(mo,d,tz,False))
    def mins(t): h,m = t.split(":"); return int(h)*60+int(m)
    ok = abs(mins(got[0])-mins(rise)) <= 4 and abs(mins(got[1])-mins(setq)) <= 4
    check(f"{label} sunrise/sunset", ok, f"{got[0]}/{got[1]} vs {rise}/{setq}")

print("\ndaylight saving (EU: last Sunday of March to last Sunday of October)")
def last_sunday(y, m):
    d = calendar.monthrange(y, m)[1]
    while calendar.weekday(y, m, d) != 6: d -= 1
    return d
check("2026 DST window", (last_sunday(2026,3), last_sunday(2026,10)) == (29, 25),
      f"Mar {last_sunday(2026,3)} - Oct {last_sunday(2026,10)}")
meta = json.load(open(build("frames_meta.json")))
tz = {(f["mo"], f["d"]): f["tz"] for f in meta}
check("March 15 is CET (+1), not CEST", tz[(3,15)] == 1, f"tz=+{tz[(3,15)]}")
check("October 15 is CEST (+2)", tz[(10,15)] == 2, f"tz=+{tz[(10,15)]}")

print("\nterrain")
gm = json.load(open(build("ground_meta.json")))
check("relief beats the flat-earth model", gm["relief_rmse_m"] < gm["flat_rmse_m"] / 3,
      f"{gm['relief_rmse_m']} m vs {gm['flat_rmse_m']} m flat")

print("\nshade, 15 August (street names are stable OSM data)")
F = np.load(build("frames.npy")); segs = json.load(open(build("segments.json")))
S,W,N,E = 41.878, 12.45, 41.915, 12.51
bx0,by0 = to_xy(W,S); bx1,by1 = to_xy(E,N)
keep = []
for i, s in enumerate(segs):
    xs, ys = to_xy([p[0] for p in s["g"]], [p[1] for p in s["g"]])
    if xs.min()>=bx0 and xs.max()<=bx1 and ys.min()>=by0 and ys.max()<=by1: keep.append(i)
segs = [segs[i] for i in keep]; F = F[:, keep]
idx = {}
for j, s in enumerate(segs):
    if s["n"]: idx.setdefault(s["n"], []).append(j)
def shade(name, hour, day=15, mo=8):
    ids = idx.get(name)
    if not ids: return None
    di = (mo-1)*2 + (1 if day == 15 else 0)
    return float(F[di*32 + (hour-6)*2, ids].mean())
# wide open boulevards vs narrow lanes - these are qualitative facts about Rome
for name, hour, lo, hi in [("Via dei Fori Imperiali", 14, 0, 8),
                           ("Viale delle Terme di Caracalla", 14, 10, 45),
                           ("Via dei Coronari", 14, 80, 100),
                           ("Via Margutta", 14, 85, 100),
                           ("Via Giulia", 14, 70, 100)]:
    v = shade(name, hour)
    check(f"{name} at {hour}:00", v is not None and lo <= v <= hi,
          f"{v:.0f}%" if v is not None else "missing")
# terrain-driven: Piazza Trilussa sits under the Janiculum
v = shade("Piazza Trilussa", 18)
check("Piazza Trilussa shaded by the Janiculum at 18:00", v is not None and v > 85,
      f"{v:.0f}%" if v is not None else "missing")

print("\nrouting graph")
G = np.load(build("graph.npz"))
deg = np.bincount(np.r_[G["eU"], G["eV"]])
live = deg > 0
check("mean node degree looks like a street network", 2.3 <= 2*len(G["eU"])/live.sum() <= 3.0,
      f"{2*len(G['eU'])/live.sum():.2f}")
check("dead ends under 10%", (deg[live] == 1).mean() < 0.10,
      f"{(deg[live]==1).mean()*100:.1f}%")

print(f"\n{'all checks passed' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
