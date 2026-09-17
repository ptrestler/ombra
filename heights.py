import re
LEVEL_M = 3.6
def parse_len(v):
    if v is None: return None
    v = str(v).strip().lower().replace(",", ".")
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s*(m|meter|meters|metre|metres)?$", v)
    if m: return float(m.group(1))
    m = re.match(r"^(\d+(?:\.\d+)?)\s*'(?:\s*(\d+(?:\.\d+)?)\s*\")?$", v)
    if m: return (float(m.group(1))*12 + float(m.group(2) or 0))*0.0254
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s*ft$", v)
    if m: return float(m.group(1))*0.3048
    return None
DEFAULTS = {"church":24,"cathedral":30,"chapel":12,"basilica":30,"garage":4,"garages":4,
            "shed":3,"hut":3,"roof":4,"carport":3,"kiosk":3,"ruins":8,"greenhouse":4,
            "civic":20,"public":20,"palace":24,"hotel":20,"apartments":19,"residential":18,
            "commercial":18,"retail":14,"school":14,"university":18,"office":20,
            "industrial":10,"warehouse":10,"train_station":15,"terrace":16,"house":9,
            "detached":9,"bungalow":5,"service":4,"toilets":3,"wall":3}
def building_height(tags):
    """Returns (height_m, source) where source in {tag, levels, default}."""
    h = parse_len(tags.get("height"))
    if h and 1.5 <= h <= 200: return h, "tag"
    h = parse_len(tags.get("building:height"))
    if h and 1.5 <= h <= 200: return h, "tag"
    lv = tags.get("building:levels") or tags.get("levels")
    try:
        if lv is not None:
            n = float(str(lv).split(";")[0].split(",")[0])
            if 0 < n <= 60:
                extra = parse_len(tags.get("roof:height")) or 0
                return n*LEVEL_M + 1.2 + min(extra, 12), "levels"
    except Exception: pass
    bt = str(tags.get("building","yes")).lower()
    if bt in DEFAULTS: return DEFAULTS[bt], "default"
    return 17.0, "default"

# ---- cadastre heights, for buildings OSM does not tag --------------------
# EUBUCCO's Lazio rows are the Italian cadastre (see fetch_eubucco.py), so they
# are an independent measurement of the same buildings rather than a re-import
# of the tags above.
#
# Matching is by containment: a cadastre parcel belongs to this building when
# its centroid falls inside the building's own outline. That is the relationship
# the two datasets actually have. The cadastre splits a block into parcels where
# OSM draws one outline, so a building typically contains one, two or a dozen of
# them and corresponds to no single one. Nearest-centroid matching had to work
# around that with a radius, and the radius was the whole design:
#
#     rule                               covers the guesses   RMSE   IDW on the same
#     nearest centroid <= 5 m                   44 %          4.80        5.44
#     nearest centroid <= 8 m                   61 %          5.02        5.50
#     nearest centroid <= 12 m                  74 %          5.56        5.48  <- crossover
#     parcel centroids inside the outline       62 %          4.85        5.54
#     ...and nearest <= 8 m for the rest        70 %          4.90        5.54
#
# (Coverage is of the untagged buildings, which is what it buys; error is
# measured where there is a tag to measure against.)
#
# Containment moves both columns the right way at once, which no radius could.
# On the 1,620 buildings both rules reach it scores 4.65 against 5.02 -- a
# difference of -0.41 m, bootstrap interval [-0.71, -0.16], so not noise. It also
# reaches 376 tagged buildings the radius missed, where it is indistinguishable
# from the interpolation it replaces (+0.25 m, [-0.54, +1.10]); those are kept
# because a surveyed height that ties with a guess is still not a guess.
#
# The 8 m fallback stays, for the other direction: buildings OSM draws more
# finely than the cadastre, which contain no parcel centroid at all. Widening it
# was re-tested now that containment takes the agreeing cases first, and it is
# worse than it was, not better -- on the buildings containment misses, 8 m
# scores 5.30 against interpolation's 5.55, and 12 m scores 6.81 against 5.69.
#
# Several parcels inside one outline are averaged, weighted by floor count, so a
# six-storey block counts for more than the single-storey annex in its
# courtyard. Against a plain mean that is worth 0.03 m [0.005, 0.065] -- real,
# but small enough that the reason to prefer it is the argument and not the
# number. The tallest parcel was clearly wrong (5.43): a building is not as tall
# as its tallest part.
#
# OFFSET is fitted, not assumed: the cadastre reads 1.00 m taller than OSM tags
# on average, which is what a ridge-or-parapet versus eaves definition looks
# like. Five-fold cross validation puts the out-of-sample error at the in-sample
# 4.93 m, with per-fold offsets from +0.91 to +1.01, so the one parameter is not
# fitting noise. A separate offset per branch buys 0.002 m and is not worth a
# second number. FLOOR is a sanity bound only -- the cadastre records genuine
# 3-4 m courtyard annexes that the 7 m floor on the IDW estimate would wrongly
# inflate.
CADASTRE_SOURCE   = "gov-italy-lazio"
CADASTRE_RADIUS_M = 8.0
CADASTRE_OFFSET_M = 1.00
CADASTRE_FLOOR_M  = 2.0

# What each estimate is worth, measured by measure_heights.py against the tags.
# These are not used to compute a height; they are how wrong a height is allowed
# to be, and build_dsm.py's OMBRA_JITTER check moves every estimate by its own
# figure to see how much of the map depends on them. Re-measure when matching
# changes: a stale sigma makes the sensitivity claim in the UI a fiction.
CADASTRE_RMSE_M = 4.90
INTERP_RMSE_M   = 6.94


def cadastre_heights(csv_path, footprints, lons, lats):
    """Cadastre height per building, or NaN where the cadastre does not reach it.

    footprints[i] is that building's outer rings, each a list of (lon, lat).
    (lons[i], lats[i]) is its centroid, used only by the fallback.
    """
    import csv, numpy as np
    from scipy.spatial import cKDTree
    from geo import to_xy

    def inside(ring, px, py):
        """Ray casting, vectorised over the query points. Odd crossings are in."""
        x, y = ring[:, 0], ring[:, 1]
        res = np.zeros(len(px), bool)
        j = len(x) - 1
        for i in range(len(x)):
            res ^= ((y[i] > py) != (y[j] > py)) & (
                px < (x[j]-x[i]) * (py-y[i]) / (y[j]-y[i] + 1e-12) + x[i])
            j = i
        return res

    hs, fl, xs, ys = [], [], [], []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["height_source"] != CADASTRE_SOURCE: continue
            try: h = float(r["height"]); lon = float(r["lon"]); lat = float(r["lat"])
            except (TypeError, ValueError): continue
            try: n = float(r["floors"])
            except (TypeError, ValueError): n = 1.0
            hs.append(h); fl.append(n if n > 0 else 1.0); xs.append(lon); ys.append(lat)
    out = np.full(len(lons), np.nan)
    if not hs: return out
    EH = np.asarray(hs); EF = np.asarray(fl)
    ex, ey = to_xy(xs, ys)
    EP = np.c_[ex, ey]
    tree = cKDTree(EP)

    for i, rr in enumerate(footprints):
        rings_m = []
        for r in rr:
            rx, ry = to_xy([p[0] for p in r], [p[1] for p in r])
            rings_m.append(np.c_[rx, ry])
        if not rings_m: continue
        allp = np.vstack(rings_m)
        c = allp.mean(0)
        # every parcel that could be inside is within the outline's own reach
        rad = float(np.hypot(*(allp - c).T).max()) + 1.0
        cand = np.fromiter(tree.query_ball_point(c, rad), int)
        if cand.size == 0: continue
        hit = np.zeros(cand.size, bool)
        for ring in rings_m:
            hit |= inside(ring, EP[cand, 0], EP[cand, 1])   # outer rings, so a union
        sel = cand[hit]
        if sel.size:
            out[i] = float(np.sum(EH[sel] * EF[sel]) / np.sum(EF[sel]))

    # and for outlines finer than the cadastre's own, which contain nothing
    miss = np.isnan(out)
    if miss.any():
        qx, qy = to_xy(np.asarray(lons)[miss], np.asarray(lats)[miss])
        d, j = tree.query(np.c_[qx, qy], k=1, distance_upper_bound=CADASTRE_RADIUS_M)
        ok = np.isfinite(d)
        out[miss] = np.where(ok, EH[np.where(ok, np.minimum(j, len(EH)-1), 0)], np.nan)

    return np.where(np.isfinite(out),
                    np.maximum(out - CADASTRE_OFFSET_M, CADASTRE_FLOOR_M), np.nan)
