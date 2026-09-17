"""The OSM building outlines, loaded once and shared.

build_dsm.py rasterises them; measure_heights.py scores the height sources
against them. They have to agree about what a building is -- an outline that one
of them drops and the other keeps would quietly move every number in the report
away from the thing it claims to describe -- so the loader lives here rather
than in either.
"""
import glob, json
from paths import osm
from heights import building_height


def rings(el):
    """Outer rings of a way or multipolygon, as lists of (lon, lat)."""
    if el["type"] == "way":
        g = el.get("geometry")
        if g and len(g) >= 3: yield [(p["lon"], p["lat"]) for p in g]
    else:
        for m in el.get("members", []):
            if m.get("type") == "way" and m.get("role") in ("outer", ""):
                g = m.get("geometry")
                if g and len(g) >= 3: yield [(p["lon"], p["lat"]) for p in g]


def load():
    """Every building in the tiles: height, where it came from, outline, centroid.

    Duplicated ways across tile boundaries are dropped by (type, id).
    """
    out, seen = [], set()
    for fn in sorted(glob.glob(osm("tiles/bld_*.json"))):
        for el in json.load(open(fn))["elements"]:
            k = (el["type"], el["id"])
            if k in seen: continue
            seen.add(k)
            t = el.get("tags", {}) or {}
            h, src = building_height(t)
            rr = list(rings(el))
            if not rr: continue
            pts = [p for r in rr for p in r]
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            out.append(dict(h=h, src=src, rings=rr, c=(cx, cy)))
    return out
