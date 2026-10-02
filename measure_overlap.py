"""Does matching on footprint *overlap* beat what we already do? Measured: no.

This file exists because the answer is counter-intuitive and the data needed to
check it is too big to commit. CLAUDE.md listed overlap matching as the largest
remaining gain in the model for months; it is not, and anyone who thinks it must
be should run this before spending a day on it.

The shipped rule (heights.py) matches a cadastre parcel to a building when the
parcel's centroid falls inside the building's outline. That handles the cadastre
splitting a block more finely than OSM draws it. The reverse case is what is
left: OSM draws the building more finely, so our outline sits inside one parcel
and contains no centroid at all. Overlap matching is the obvious fix, in two
forms, both tested here:

  * the parcel our centre falls inside
  * the parcel covering most of us, by a plurality vote over points inside our
    own outline

Neither beats the interpolation it would replace. The reason is in the data, not
the geometry: when the cadastre lumps several buildings into one parcel, that
parcel's height is an average over a block -- which is the same kind of estimate
the inverse-distance interpolation already builds out of tagged neighbours. The
cadastre holds no separate measurement for those buildings, and no amount of
geometry conjures one.

Needs `pip install duckdb` and the network, like fetch_eubucco.py. The 21 MB of
geometry lands in build/, which is derived and not committed.

    python measure_overlap.py
"""
import csv, os, re, sys
import numpy as np
from collections import defaultdict
from scipy.spatial import cKDTree

from paths import build, eub
from geo import to_xy
from buildings import load
from heights import cadastre_heights, CADASTRE_SOURCE

csv.field_size_limit(10 ** 7)
GEOM = build("eubucco_geom.csv")
URL = "https://s3.eubucco.com/eubucco/v0.2/buildings/parquet/nuts_id=ITI4/ITI4.parquet"
S, W, N, E = 41.878, 12.4500, 41.9150, 12.5100     # the same window as fetch_eubucco.py
CELL = 60.0                                        # bucket size for the parcel index
BOOT = 2000
RNG = np.random.default_rng(3)


def fetch():
    """The cadastre again, with the polygons this time."""
    try:
        import duckdb
    except ImportError:
        print("measure_overlap.py needs duckdb:  pip install duckdb", file=sys.stderr)
        raise SystemExit(1)
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
    x0, y0, x1, y1 = con.execute(f"""
      SELECT ST_XMin(g), ST_YMin(g), ST_XMax(g), ST_YMax(g) FROM (
        SELECT ST_Transform(ST_MakeEnvelope({W},{S},{E},{N}),
                            'EPSG:4326','EPSG:3035', true) AS g)
    """).fetchone()
    os.makedirs(os.path.dirname(GEOM), exist_ok=True)
    con.execute(f"""
    COPY (
      SELECT height, height_source,
             ST_AsText(ST_Transform(geometry,'EPSG:3035','EPSG:4326', true)) AS wkt
      FROM read_parquet('{URL}')
      WHERE ST_XMin(geometry) BETWEEN {x0} AND {x1}
        AND ST_YMin(geometry) BETWEEN {y0} AND {y1}
        AND height IS NOT NULL
    ) TO '{GEOM}' (HEADER, DELIMITER ',')
    """)
    print(f"fetched {os.path.getsize(GEOM)/1e6:.1f} MB of parcel geometry into build/")


def wkt_rings(w):
    """Outer ring of each polygon, in lon/lat. Holes are ignored: a courtyard is
    not worth the parsing, and a stray hit inside one is a metre-scale error."""
    if w.startswith("MULTIPOLYGON"):
        polys = re.split(r"\)\s*,\s*\(", w[w.index("(") + 1: w.rindex(")")])
    else:
        polys = [w[w.index("("):]]
    out = []
    for part in polys:
        m = re.search(r"\(([-0-9eE. ,]+)\)", part)
        if not m:
            continue
        try:
            out.append(np.array([[float(a), float(b)]
                                 for a, b in (q.split() for q in m.group(1).split(","))]))
        except ValueError:
            pass
    return out


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


def rmse(e):
    """Spread about the mean: an offset is fitted, so bias is not error."""
    return float(np.sqrt(((e - e.mean()) ** 2).mean()))


if not os.path.exists(GEOM):
    fetch()

blds = load()
TAG = np.array([b["h"] for b in blds])
tagged = np.array([b["src"] in ("tag", "levels") for b in blds])
MR = [[np.c_[to_xy([p[0] for p in r], [p[1] for p in r])] for r in b["rings"]] for b in blds]
MC = np.array([np.vstack(r).mean(0) for r in MR])
print(f"{len(blds):,} buildings   {tagged.sum():,} tagged")

PH, RINGS = [], []
with open(GEOM, newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r["height_source"] != CADASTRE_SOURCE:
            continue
        try:
            h = float(r["height"])
        except (TypeError, ValueError):
            continue
        PH.append(h)
        RINGS.append([np.c_[to_xy(g[:, 0], g[:, 1])] for g in wkt_rings(r["wkt"])])
PH = np.array(PH)
print(f"{len(PH):,} cadastre parcels, as polygons")

grid = defaultdict(list)
for i, rr in enumerate(RINGS):
    a = np.vstack(rr)
    x0, y0 = a.min(0)
    x1, y1 = a.max(0)
    for gx in range(int(x0 // CELL), int(x1 // CELL) + 1):
        for gy in range(int(y0 // CELL), int(y1 // CELL) + 1):
            grid[(gx, gy)].append(i)


def parcel_at(px, py):
    for j in grid.get((int(px // CELL), int(py // CELL)), ()):
        for ring in RINGS[j]:
            if inside(ring, np.array([px]), np.array([py]))[0]:
                return j
    return -1


centre = np.full(len(blds), -1)
covers = np.full(len(blds), -1)
for i in range(len(blds)):
    a = np.vstack(MR[i])
    c = MC[i]
    centre[i] = parcel_at(c[0], c[1])
    # the centroid plus the ring pulled a quarter of the way in, which stays
    # inside anything that is not pathologically concave
    tally = defaultdict(int)
    for px, py in np.vstack([c[None, :], c + (a[:12] - c) * 0.75]):
        j = parcel_at(px, py)
        if j >= 0:
            tally[j] += 1
    if tally:
        covers[i] = max(tally, key=tally.get)

CH = cadastre_heights(eub("rome.csv"), [b["rings"] for b in blds],
                      [b["c"][0] for b in blds], [b["c"][1] for b in blds])
hit = np.isfinite(CH)

# the interpolation any new match would displace, leave-one-out so a tagged
# building is never estimated from itself
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

RULES = (("the parcel our centre falls in", np.where(centre >= 0, PH[np.maximum(centre, 0)], np.nan)),
         ("the parcel covering most of us", np.where(covers >= 0, PH[np.maximum(covers, 0)], np.nan)))

print()
print(f"shipped rule reaches {100 * hit[~tagged].mean():.0f} % of the untagged buildings")
for lbl, p in RULES:
    print(f"  {lbl:<32} would reach {100 * np.isfinite(p[~tagged]).mean():.0f} %")

print()
print("ON THE BUILDINGS THE SHIPPED RULE MISSES  (tagged, so there is an answer)")
miss = tagged & ~hit
for lbl, p in RULES:
    m = miss & np.isfinite(p) & np.isfinite(IDW)
    ec, ei = p[m] - TAG[m], IDW[m] - TAG[m]
    k = RNG.integers(0, m.sum(), (BOOT, m.sum()))
    dif = np.array([rmse(ec[s]) - rmse(ei[s]) for s in k])
    lo, hi = np.percentile(dif, [2.5, 97.5])
    print(f"  {lbl:<32} n={m.sum():>4}   {rmse(ec):5.2f} against interpolation's {rmse(ei):5.2f}")
    print(f"  {'':<32}        {dif.mean():+.2f} m  [{lo:+.2f}, {hi:+.2f}]  "
          f"{'REAL' if lo > 0 or hi < 0 else 'noise, so it buys nothing'}")

print()
print("AND WHAT THE WHOLE MODEL WOULD SCORE")
for lbl, p in (("today", None),) + RULES:
    comb = CH if p is None else np.where(hit, CH, p)
    allp = np.where(np.isfinite(comb), comb, IDW)
    m = tagged & np.isfinite(allp)
    e = allp[m] - TAG[m]
    print(f"  {lbl:<32} untagged covered {100 * np.isfinite(comb[~tagged]).mean():>3.0f} %   "
          f"every untagged height {np.sqrt((e ** 2).mean()):.2f} m")
