"""How wrong is the map on the days it does not sample, and what fixes it?

The model computes shade for the 1st and 15th of each month. The page shows
those 24 dates and nothing in between, so on 8 October it shows the 15th. This
computes the real shade for the days furthest from any sample - the 8th and
the 23rd of every month - and scores ways of standing in for them from the
768 frames the build already has:

  nearest   what the page does: the closest sampled date, same civil time
  linear    blend the two sampled dates either side by distance in days,
            same civil time
  sun-1     the frame, from any date, whose sun is closest in the sky -
            shade depends on nothing but the sun's direction
  sun-2     the two closest-sun frames, blended by inverse angular distance

Scored on daylight segment-frames (sun above 3 degrees at the true time):
mean absolute error in percentage points, and the share off by more than 10
and 20 points. Needs a build (build/frames.npy and what shade.py reads); about
3-4 min, the daylight half of 24 dates. Run it, don't quote it.
"""
import math, json, time, numpy as np
import shade
from paths import build

F = np.load(build("frames.npy")).astype(np.float32)          # [768, nseg]
META = json.load(open(build("frames_meta.json")))
EL = np.array([m["el"] for m in META]); AZ = np.array([m["az"] for m in META])
DATES = shade.DATES; TIMES = shade.TIMES; S = len(TIMES)
idx = {(m, d): i for i, (m, d) in enumerate(DATES)}
DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

def doy(mo, d): return sum(DAYS[:mo - 1]) + d

def unit(el, az):
    e, a = np.radians(el), np.radians(az)
    return np.stack([np.cos(e) * np.sin(a), np.cos(e) * np.cos(a), np.sin(e)], -1)
U = unit(EL, AZ)
LIT = EL > 3.0

def bracket(mo, d):
    """the sampled dates either side, and how far between them (0..1)"""
    lo = (mo, 1) if d < 15 else (mo, 15)
    hi = (mo, 15) if d < 15 else (mo % 12 + 1, 1)
    a, b = doy(*lo), doy(*hi)
    if b < a: b += 365
    return lo, hi, (doy(mo, d) - a) / (b - a)

def nearest(mo, d):                       # nowFrame's rule
    if d < 8: return (mo, 1)
    if d < 23: return (mo, 15)
    return (mo % 12 + 1, 1)

tests = [(mo, d) for mo in range(1, 13) for d in (8, 23)]
err = {k: [] for k in ("nearest", "linear", "sun-1", "sun-2")}
dst = {k: [] for k in err}               # the two brackets that straddle a clock change
t0 = time.time()
for (mo, d) in tests:
    lo, hi, w = bracket(mo, d)
    crosses = shade.tz_for(2026, *lo) != shade.tz_for(2026, *hi)
    for s, (h, mi) in enumerate(TIMES):
        m, truth = shade.frame(mo, d, h, mi)
        if m["el"] <= 3.0: continue
        truth = truth.astype(np.float32)
        u = unit(np.array(m["el"]), np.array(m["az"]))
        ang = np.degrees(np.arccos(np.clip(U @ u, -1, 1)))
        ang[~LIT] = 1e9                    # a night frame is not a stand-in for day
        o = np.argsort(ang)
        a1, a2 = ang[o[0]], ang[o[1]]
        w1, w2 = (1 / max(a1, 1e-3)), (1 / max(a2, 1e-3))
        guess = {
            "nearest": F[idx[nearest(mo, d)] * S + s],
            "linear":  (1 - w) * F[idx[lo] * S + s] + w * F[idx[hi] * S + s],
            "sun-1":   F[o[0]],
            "sun-2":   (w1 * F[o[0]] + w2 * F[o[1]]) / (w1 + w2),
        }
        for k, g in guess.items():
            e = np.abs(np.round(g) - truth)
            err[k].append(e)
            if crosses: dst[k].append(e)
    print(f"{mo:2d}/{d:2d}  {time.time() - t0:4.0f}s", flush=True)

def row(name, es):
    e = np.concatenate(es)
    return (f"{name:8s}  MAE {e.mean():5.2f} pp   >10 pp {100 * (e > 10).mean():5.2f} %"
            f"   >20 pp {100 * (e > 20).mean():5.2f} %")
print(f"\n{len(tests)} unsampled dates, {sum(len(v) for v in err['nearest'][:1]) and len(err['nearest'])} "
      f"daylight frames x {F.shape[1]} segments")
for k in err: print(row(k, err[k]))
print("\nthe dates whose brackets straddle a clock change (late March, late October)")
for k in dst: print(row(k, dst[k]))
