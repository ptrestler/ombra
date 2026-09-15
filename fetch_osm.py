"""Pull everything the model needs from OpenStreetMap, into data/osm/.

Overpass is the slowest and least reliable step in the pipeline: public mirrors
rate-limit hard and some serve empty results. Everything here is cached on disk
and safe to re-run - it only fetches what is missing. A cold fetch of the street
and building tiles took about an hour; the cache is worth keeping.
"""
import json, os, random, time, urllib.parse, urllib.request
from paths import osm

S, W, N, E = 41.878, 12.4500, 41.9150, 12.5100     # the mapped area
NLAT, NLON = 4, 4                                  # tiles, to keep queries small
BB = f"({S},{W},{N},{E})"

# overpass-api.de resets connections constantly from cloud IPs; this mirror has
# been the reliable one. osm.ch is deliberately absent: it answers with 0 elements.
ENDPOINTS = ["https://maps.mail.ru/osm/tools/overpass/api/interpreter",
             "https://overpass.private.coffee/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter",
             "https://overpass-api.de/api/interpreter"]

def post(query, rounds=8):
    for rnd in range(rounds):
        for ep in ENDPOINTS:
            try:
                data = urllib.parse.urlencode({"data": query}).encode()
                req = urllib.request.Request(ep, data=data,
                                             headers={"User-Agent": "ombra-roma/1.0"})
                with urllib.request.urlopen(req, timeout=300) as f:
                    j = json.loads(f.read())
                if j.get("elements") is not None:
                    return j
            except Exception:
                pass
            time.sleep(3)
        wait = min(90, 10 * (rnd + 1)) + random.random() * 10
        print(f"   all mirrors busy, backing off {wait:.0f}s", flush=True)
        time.sleep(wait)
    return None

def cached(path, query):
    if os.path.exists(path) and os.path.getsize(path) > 400:
        return False
    j = post(query)
    if j is None:
        raise SystemExit(f"could not fetch {path}")
    json.dump(j, open(path, "w"))
    print(f"   {os.path.basename(path)}: {len(j['elements'])} elements", flush=True)
    time.sleep(5)
    return True

# --- streets and buildings, tiled -------------------------------------------
# NB: area=yes ways are INCLUDED. They are the pedestrian piazzas, and dropping
# them severs the walking network across Piazza della Rotonda, Piazza Venezia
# and ~300 other squares. See CLAUDE.md.
STREET_CLASSES = ("primary|secondary|tertiary|residential|unclassified|living_street|"
                  "pedestrian|footway|steps|path|service|track")
for i in range(NLAT):
    for j in range(NLON):
        s = S + (N-S)*i/NLAT; n = S + (N-S)*(i+1)/NLAT
        w = W + (E-W)*j/NLON; e = W + (E-W)*(j+1)/NLON
        bb = f"({s:.5f},{w:.5f},{n:.5f},{e:.5f})"
        cached(osm(f"tiles/str_{i}_{j}.json"),
               f'[out:json][timeout:180];way["highway"~"^({STREET_CLASSES})$"]{bb};out body geom;')
        cached(osm(f"tiles/bld_{i}_{j}.json"),
               f'[out:json][timeout:180];(way["building"]{bb};relation["building"]{bb};);out body geom;')

# --- water, greenery, trees --------------------------------------------------
cached(osm("extra_water.json"),
       f'[out:json][timeout:180];(way["natural"="water"]{BB};relation["natural"="water"]{BB};'
       f'way["waterway"="riverbank"]{BB};);out body geom;')
cached(osm("extra_green.json"),
       f'[out:json][timeout:180];(way["leisure"~"^(park|garden)$"]{BB};'
       f'relation["leisure"~"^(park|garden)$"]{BB};way["natural"="wood"]{BB};'
       f'way["landuse"="forest"]{BB};way["landuse"="cemetery"]{BB};'
       f'relation["natural"="wood"]{BB};);out body geom;')
cached(osm("extra_trees.json"),
       f'[out:json][timeout:180];(node["natural"="tree"]{BB};way["natural"="tree_row"]{BB};);'
       f'out body geom;')

# --- named places, for the From/To search ------------------------------------
cached(osm("extra_poi.json"), f"""[out:json][timeout:200];
(
  nwr["tourism"~"^(attraction|museum|artwork|viewpoint|gallery)$"]["name"]{BB};
  nwr["historic"~"^(monument|memorial|ruins|castle|archaeological_site|church|building|city_gate|aqueduct)$"]["name"]{BB};
  nwr["amenity"="place_of_worship"]["name"]{BB};
  nwr["amenity"~"^(theatre|university|fountain)$"]["name"]{BB};
  nwr["man_made"="obelisk"]["name"]{BB};
  nwr["railway"~"^(station|halt)$"]["name"]{BB};
  nwr["public_transport"="station"]["name"]{BB};
  node["place"~"^(suburb|quarter|neighbourhood|city_block)$"]["name"]{BB};
  nwr["leisure"="park"]["name"]{BB};
  way["highway"="pedestrian"]["name"]["area"="yes"]{BB};
  way["man_made"="bridge"]["name"]{BB};
  way["bridge"]["name"]["highway"]{BB};
);
out center tags;""")
print("OSM data ready in data/osm/")
