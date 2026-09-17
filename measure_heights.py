"""Where the height numbers in heights.py and CLAUDE.md come from.

Five buildings in six have no height in OpenStreetMap, so most of the shade
model rests on heights that came from somewhere else. This scores those sources
against the ones OSM does tag, which is the only ground truth available, and
prints the tables those comments quote. Run it after changing anything about
matching, and paste the numbers rather than adjusting them.

The shipped rule is measured by calling `cadastre_heights` itself, so the
headline rows describe the code that runs. The alternatives it is compared
against are implemented here, because by definition they are not in the build.

    python measure_heights.py            # needs data/, not build/
"""
import csv, numpy as np
from scipy.spatial import cKDTree
from paths import eub
from geo import to_xy
from buildings import load
from heights import cadastre_heights, CADASTRE_SOURCE, CADASTRE_OFFSET_M

RNG = np.random.default_rng(11)      # bootstrap only; nothing shipped depends on it
BOOT = 2000


def rmse(e):
    """Spread about the mean: an offset is fitted, so bias is not error."""
    return float(np.sqrt(((e - e.mean()) ** 2).mean()))


def inside(ring, px, py):
    """Ray casting, vectorised over the query points. Odd crossings are in."""
    x, y = ring[:, 0], ring[:, 1]
    res = np.zeros(len(px), bool)
    j = len(x) - 1
    for i in range(len(x)):
        res ^= ((y[i] > py) != (y[j] > py)) & (
            px < (x[j] - x[i]) * (py - y[i]) / (y[j] - y[i] + 1e-12) + x[i])
        j = i
    return res


blds = load()
TAG = np.array([b["h"] for b in blds])
tagged = np.array([b["src"] in ("tag", "levels") for b in blds])
guess = ~tagged
mrings = [[np.c_[to_xy([p[0] for p in r], [p[1] for p in r])] for r in b["rings"]]
          for b in blds]
MC = np.array([np.vstack(r).mean(0) for r in mrings])
print(f"{len(blds):,} buildings   {tagged.sum():,} tagged   {guess.sum():,} not")

EH, EF, ex, ey = [], [], [], []
with open(eub("rome.csv"), newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r["height_source"] != CADASTRE_SOURCE:
            continue
        try:
            h = float(r["height"]); lon = float(r["lon"]); lat = float(r["lat"])
        except (TypeError, ValueError):
            continue
        try:
            n = float(r["floors"])
        except (TypeError, ValueError):
            n = 1.0
        EH.append(h); EF.append(n if n > 0 else 1.0); ex.append(lon); ey.append(lat)
EH = np.array(EH); EF = np.array(EF)
exm, eym = to_xy(ex, ey)
EP = np.c_[exm, eym]
tree = cKDTree(EP)
print(f"{len(EH):,} cadastre parcels in the bbox")

# what each outline contains, computed once; every containment variant reuses it
contains = []
for i, rr in enumerate(mrings):
    allp = np.vstack(rr)
    rad = float(np.hypot(*(allp - MC[i]).T).max()) + 1.0
    cand = np.fromiter(tree.query_ball_point(MC[i], rad), int)
    if cand.size:
        hit = np.zeros(cand.size, bool)
        for ring in rr:
            hit |= inside(ring, EP[cand, 0], EP[cand, 1])
        cand = cand[hit]
    contains.append(cand)


def near(radius):
    d, j = tree.query(MC, k=1, distance_upper_bound=float(radius))
    ok = np.isfinite(d)
    return np.where(ok, EH[np.where(ok, np.minimum(j, len(EH) - 1), 0)], np.nan)


def held(how):
    out = np.full(len(blds), np.nan)
    for i, sel in enumerate(contains):
        if not len(sel):
            continue
        h = EH[sel]
        out[i] = (float(np.median(h)) if how == "median" else
                  float(h.mean()) if how == "mean" else
                  float(h.max()) if how == "max" else
                  float(np.sum(h * EF[sel]) / np.sum(EF[sel])))
    return out


# the interpolation every cadastre match displaces, scored leave-one-out so a
# tagged building is never estimated from itself
ki = np.where(tagged)[0]
KH = TAG[ki]
d, j = cKDTree(MC[ki]).query(MC[ki], k=16, distance_upper_bound=500.0)
IDW = np.full(len(blds), np.nan)
for n, gi in enumerate(ki):
    dd, jj = d[n][1:], j[n][1:]
    ok = np.isfinite(dd)
    if ok.any():
        w = 1.0 / np.maximum(dd[ok], 1.0)
        IDW[gi] = float(np.sum(w * KH[jj[ok]]) / np.sum(w))


def row(pred, label):
    m = tagged & np.isfinite(pred)
    mi = m & np.isfinite(IDW)
    print(f"  {label:<44} {100 * np.isfinite(pred[guess]).mean():>4.0f} %   "
          f"{rmse(pred[m] - TAG[m]):5.2f}   {rmse(IDW[mi] - TAG[mi]):5.2f}   n={m.sum():,}")


print()
print("MATCHING RULES       coverage of the untagged, error where there is a tag")
print(f"  {'rule':<44} {'covers':>6}   {'RMSE':>5}   {'IDW':>5}")
for r in (5, 8, 12):
    row(near(r), f"nearest centroid <= {r} m")
for how in ("median", "mean", "max", "floors-weighted"):
    row(held(how), f"parcels inside the outline, {how}")
FW = held("floors-weighted")
NEW = np.where(np.isfinite(FW), FW, near(8))
row(NEW, "...and nearest <= 8 m for the rest")

print()
print("OLD AGAINST NEW, on the buildings both rules reach")
OLD = near(8)
both = tagged & np.isfinite(OLD) & np.isfinite(NEW)
eo, en = OLD[both] - TAG[both], NEW[both] - TAG[both]
print(f"  nearest <= 8 m          {rmse(eo):5.2f}")
print(f"  containment first       {rmse(en):5.2f}        n={both.sum():,}")
k = RNG.integers(0, both.sum(), (BOOT, both.sum()))
dif = np.array([rmse(eo[i]) - rmse(en[i]) for i in k])
lo, hi = np.percentile(dif, [2.5, 97.5])
print(f"  difference {dif.mean():+.2f} m  [{lo:+.2f}, {hi:+.2f}]  "
      f"{'real' if lo > 0 or hi < 0 else 'noise'}")

only = tagged & ~np.isfinite(OLD) & np.isfinite(NEW)
ec, ei = NEW[only] - TAG[only], IDW[only] - TAG[only]
k = RNG.integers(0, only.sum(), (BOOT, only.sum()))
dif = np.array([rmse(ec[i]) - rmse(ei[i]) for i in k])
lo, hi = np.percentile(dif, [2.5, 97.5])
print(f"  on the {only.sum():,} it reaches that the radius missed: "
      f"{rmse(ec):.2f} against interpolation's {rmse(ei):.2f}")
print(f"  difference {dif.mean():+.2f} m  [{lo:+.2f}, {hi:+.2f}]  "
      f"{'real' if lo > 0 or hi < 0 else 'noise'}")

print()
print("THE FALLBACK, on the buildings containment misses")
miss = ~np.isfinite(FW)
for r in (8, 12):
    p = np.where(miss, near(r), np.nan)
    m = tagged & np.isfinite(p) & np.isfinite(IDW)
    print(f"  nearest <= {r:>2} m   {rmse(p[m] - TAG[m]):5.2f}   "
          f"against interpolation's {rmse(IDW[m] - TAG[m]):5.2f}   n={m.sum():,}")

print()
print("THE OFFSET, five-fold")
m = tagged & np.isfinite(NEW)
idx = np.where(m)[0]
RNG.shuffle(idx)
folds = np.array_split(idx, 5)
errs, offs = [], []
for f in range(5):
    tr = np.concatenate([folds[g] for g in range(5) if g != f])
    o = float(np.mean(NEW[tr] - TAG[tr]))
    offs.append(o)
    errs.append(NEW[folds[f]] - TAG[folds[f]] - o)
errs = np.concatenate(errs)
print(f"  fitted on everything {np.mean(NEW[m] - TAG[m]):+.2f} m, "
      f"shipped as {CADASTRE_OFFSET_M:+.2f}")
print(f"  per fold {' '.join(f'{o:+.2f}' for o in offs)}")
print(f"  out of sample RMSE {np.sqrt((errs ** 2).mean()):.2f}   "
      f"in sample {rmse(NEW[m] - TAG[m]):.2f}")

print()
print("WHAT THE BUILD ACTUALLY DOES   (cadastre_heights, as shipped)")
CH = cadastre_heights(eub("rome.csv"), [b["rings"] for b in blds],
                      [b["c"][0] for b in blds], [b["c"][1] for b in blds])
hit = np.isfinite(CH)
print(f"  the cadastre reaches {int(hit[guess].sum()):,} of the {int(guess.sum()):,} "
      f"untagged ({100 * hit[guess].mean():.0f} %); "
      f"{int((~hit[guess]).sum()):,} stay interpolated")
for label, pred, m in (
        ("cadastre height", CH, tagged & hit),
        ("interpolation left", IDW, tagged & ~hit & np.isfinite(IDW)),
        ("every untagged height", np.where(hit, CH, IDW), tagged & np.isfinite(np.where(hit, CH, IDW)))):
    e = pred[m] - TAG[m]
    print(f"  {label:<22} RMSE {np.sqrt((e ** 2).mean()):5.2f}  "
          f"MAE {np.abs(e).mean():5.2f}  bias {e.mean():+5.2f}   n={m.sum():,}")
