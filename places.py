"""Named destinations for the From/To search: OSM landmarks, deduplicated against
the street names already in the payload, plus a curated shortlist shown when the
search box is empty. Writes build/places_pack.json."""
import collections, json, unicodedata
from paths import osm, build

def centre(el):
    if el["type"] == "node": return el.get("lon"), el.get("lat")
    c = el.get("center")
    return (c["lon"], c["lat"]) if c else (None, None)

# (label, test, base score). Order matters: first match wins.
CAT = [
 ("Station", lambda t: t.get("railway") in ("station","halt")
             or t.get("public_transport")=="station" or t.get("amenity")=="bus_station", 6),
 ("Area",    lambda t: t.get("place") in ("suburb","quarter","neighbourhood","city_block"), 6),
 ("Piazza",  lambda t: t.get("place")=="square"
             or (t.get("highway")=="pedestrian" and t.get("area")=="yes"), 4),
 ("Museum",  lambda t: t.get("tourism") in ("museum","gallery"), 3),
 ("Park",    lambda t: t.get("leisure")=="park", 3),
 ("Bridge",  lambda t: bool(t.get("bridge")) and bool(t.get("highway")), 3),
 ("Sight",   lambda t: t.get("tourism") in ("attraction","viewpoint")
             or t.get("historic") in ("monument","archaeological_site","castle","city_gate",
                                      "ruins","aqueduct","building")
             or t.get("man_made")=="obelisk", 3),
 ("Church",  lambda t: t.get("amenity")=="place_of_worship" or t.get("historic")=="church", 1),
 ("Fountain",lambda t: t.get("amenity")=="fountain", 1),
 ("Theatre", lambda t: t.get("amenity") in ("theatre","university"), 2),
 ("Artwork", lambda t: t.get("tourism")=="artwork" or t.get("historic")=="memorial", 0),
]
def classify(t):
    for name, fn, base in CAT:
        if fn(t): return name, base
    return None, 0

def norm(s):
    s = s.replace("’","'").replace("‘","'")
    s = unicodedata.normalize("NFD", s.lower())
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).split())

rows = {}
for el in json.load(open(osm("extra_poi.json")))["elements"]:
    t = el.get("tags", {}) or {}
    nm = (t.get("name") or "").strip()
    if not nm or len(nm) > 46: continue
    lon, lat = centre(el)
    if lon is None: continue
    cat, score = classify(t)
    if not cat: continue
    # a wikipedia/wikidata tag is the best available proxy for "worth listing"
    if t.get("wikipedia"): score += 3
    if t.get("wikidata"):  score += 2
    if t.get("wikipedia") and cat in ("Church","Fountain","Artwork"): score += 1
    if t.get("tourism") == "attraction": score += 1
    if nm not in rows or score > rows[nm]["s"]:
        rows[nm] = dict(n=nm, c=cat, s=score, lon=lon, lat=lat)

places = [r for r in rows.values() if r["s"] >= 3]
# the street index already covers these and resolves them better (real geometry)
street_names = sorted({s["n"] for s in json.load(open(build("segments.json"))) if s["n"]})
NS = {norm(n) for n in street_names}
places = [p for p in places if norm(p["n"]) not in NS]
places.sort(key=lambda r: (-r["s"], r["n"]))
print("places:", len(places), dict(collections.Counter(p["c"] for p in places)))

PI = {}
for i, p in enumerate(places): PI.setdefault(norm(p["n"]), i)
SI = {norm(n): n for n in street_names}
def resolve(label, key):
    n = norm(key)
    if n in PI: return [label, 0, PI[n]]
    if n in SI: return [label, 1, SI[n]]
    for k, i in PI.items():
        if k.startswith(n): return [label, 0, i]
    for k, v in SI.items():
        if k.startswith(n): return [label, 1, v]
    for k, i in PI.items():
        if n in k: return [label, 0, i]
    return None

# shown when the search box is empty; resolved against real data so the
# coordinates are never hand-typed
SHORTLIST = [
 ("Colosseo","Colosseo"), ("Pantheon","Pantheon"), ("Fontana di Trevi","Fontana di Trevi"),
 ("Piazza Navona","Piazza Navona"), ("Piazza di Spagna","Piazza di Spagna"),
 ("San Pietro","Basilica di San Pietro"), ("Castel Sant'Angelo","Castel Sant'Angelo"),
 ("Piazza Venezia","Piazza Venezia"), ("Campo de' Fiori","Campo de' Fiori"),
 ("Trastevere","Trastevere"), ("Roma Termini","Roma Termini"), ("Villa Borghese","Villa Borghese"),
 ("Foro Romano","Foro Romano"), ("Circo Massimo","Circo Massimo"),
 ("Piazza del Popolo","Piazza del popolo"), ("Altare della Patria","Altare della Patria"),
 ("Musei Vaticani","Musei Vaticani"), ("Galleria Borghese","Galleria Borghese"),
 ("Isola Tiberina","Isola Tiberina"), ("Gianicolo","Terrazza del Gianicolo"),
 ("Campidoglio","Piazza del Campidoglio"), ("Santa Maria Maggiore","Basilica di Santa Maria Maggiore"),
 ("San Giovanni in Laterano","Basilica di San Giovanni in Laterano"),
 ("Terme di Caracalla","Terme di Caracalla"), ("Monti","Via dei Serpenti"),
 ("Testaccio","Testaccio"), ("Piazza Barberini","Piazza Barberini"),
 ("Ponte Sisto","Ponte Sisto"), ("Piazza Farnese","Piazza Farnese"),
]
top, missing = [], []
for label, key in SHORTLIST:
    r = resolve(label, key)
    (top if r else missing).append(r or label)
if missing: print("  shortlist entries with no match:", missing)
print("shortlist:", len(top))
json.dump({"places": places, "top": top}, open(build("places_pack.json"), "w"), ensure_ascii=False)
