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
# of the tags above. Matching is nearest-centroid, because EUBUCCO subdivides
# blocks more finely than OSM does and the footprints do not correspond 1:1.
#
# The radius is the whole design. Scored against the 2,443 OSM-tagged heights,
# widening it buys coverage and loses accuracy, and it crosses over:
#
#     radius   guesses covered   cadastre RMSE   IDW RMSE on the same buildings
#        5 m         44 %            4.80 m            5.44 m
#        8 m         61 %            5.02 m            5.50 m
#       12 m         74 %            5.56 m            5.48 m
#
# Past ~10 m the nearest centroid is usually the neighbouring building, and the
# cadastre stops beating the interpolation it replaces. 8 m is the last radius
# that is clearly better, so it is the one used; the other 39 % keep the IDW
# estimate.
#
# OFFSET is fitted, not assumed: the cadastre reads 1.36 m taller than OSM tags
# on average, steadily across every height band from 10 m up, which is what a
# ridge-or-parapet versus eaves definition looks like. Five-fold cross
# validation puts the out-of-sample error at exactly the in-sample 5.02 m, so
# the single parameter is not fitting noise. FLOOR is a sanity bound only --
# the cadastre records genuine 3-4 m courtyard annexes that the 7 m floor on
# the IDW estimate would wrongly inflate.
CADASTRE_SOURCE   = "gov-italy-lazio"
CADASTRE_RADIUS_M = 8.0
CADASTRE_OFFSET_M = 1.36
CADASTRE_FLOOR_M  = 2.0

def cadastre_heights(csv_path, lons, lats):
    """Cadastre height for each (lon, lat), or NaN where none is close enough."""
    import csv, numpy as np
    from scipy.spatial import cKDTree
    from geo import to_xy
    hs, xs, ys = [], [], []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["height_source"] != CADASTRE_SOURCE: continue
            try: h = float(r["height"]); lon = float(r["lon"]); lat = float(r["lat"])
            except (TypeError, ValueError): continue
            hs.append(h); xs.append(lon); ys.append(lat)
    if not hs: return np.full(len(lons), np.nan)
    EH = np.asarray(hs)
    EX, EY = to_xy(xs, ys)
    QX, QY = to_xy(lons, lats)
    d, i = cKDTree(np.c_[EX, EY]).query(np.c_[QX, QY], k=1,
                                        distance_upper_bound=CADASTRE_RADIUS_M)
    hit = np.isfinite(d)                      # a miss returns inf and len(EH)
    i = np.where(hit, np.minimum(i, len(EH)-1), 0)
    out = np.maximum(EH[i] - CADASTRE_OFFSET_M, CADASTRE_FLOOR_M)
    return np.where(hit, out, np.nan)
