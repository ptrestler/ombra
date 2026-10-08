"""OSM opening_hours -> a schedule the page can evaluate, or None.

Deliberately a subset. It reads what Rome's churches actually use: rules
separated by ';', each an optional month range ("Oct-Jun"), optional weekdays
("Mo-Fr", "Sa,Su"), and either times ("08:00-12:30,15:00-18:00") or "off" /
"closed". A later rule replaces an earlier one on the days it names, as the
OSM spec says. Anything else - "Su[-1]", "sunrise", public holidays on their
own, comments, "+" - and the whole string is refused: a church the page cannot
read is left off the map rather than given hours it does not have.

A schedule is a list of rules, each (months, days, intervals): a 12-bit month
mask, a 7-bit weekday mask (bit 0 = Monday) and a flat list of minute pairs,
empty for closed. Public holidays ("PH") are dropped from day lists - the page
cannot know them - and a rule that named only PH is skipped.
"""
import re

DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
ALL_M, ALL_D = (1 << 12) - 1, (1 << 7) - 1

def _span(names, a, b):
    i, j = names.index(a), names.index(b)
    out, k = 0, i
    while True:                       # wraps: "Oct-Jun", "Sa-Mo"
        out |= 1 << k
        if k == j: return out
        k = (k + 1) % len(names)

TIME = r"(\d{1,2}):(\d\d)-(\d{1,2}):(\d\d)"

def _times(s):
    out = []
    for part in s.split(","):
        m = re.fullmatch(r"\s*" + TIME + r"\s*", part)
        if not m: return None
        a = int(m[1]) * 60 + int(m[2]); b = int(m[3]) * 60 + int(m[4])
        if not (0 <= a < 24 * 60 and 0 < b <= 24 * 60 and a < b): return None
        out += [a, b]
    return out

def _days(s):
    mask, ph = 0, False
    for part in s.split(","):
        part = part.strip()
        if part == "PH": ph = True; continue
        m = re.fullmatch(r"(Mo|Tu|We|Th|Fr|Sa|Su)(?:-(Mo|Tu|We|Th|Fr|Sa|Su))?", part)
        if not m: return None
        mask |= _span(DAYS, m[1], m[2] or m[1])
    return mask, ph

def parse(text):
    if not text or not text.strip(): return None
    text = text.strip()
    if text.lower() in ("closed", "off"): return None     # permanently: not a refuge
    rules = []
    for raw in text.split(";"):
        r = raw.strip()
        if not r: continue
        months = ALL_M
        m = re.match(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
                     r"(?:-(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec))?\s+", r)
        if m:
            months = _span(MONTHS, m[1], m[2] or m[1]); r = r[m.end():]
        days, only_ph = ALL_D, False
        m = re.match(r"((?:PH|Mo|Tu|We|Th|Fr|Sa|Su)(?:-(?:Mo|Tu|We|Th|Fr|Sa|Su))?"
                     r"(?:\s*,\s*(?:PH|Mo|Tu|We|Th|Fr|Sa|Su)(?:-(?:Mo|Tu|We|Th|Fr|Sa|Su))?)*)\s+", r)
        if m:
            d = _days(m[1].replace(" ", ""))
            if d is None: return None
            days, ph = d
            only_ph = ph and days == 0
            r = r[m.end():]
        r = r.strip()
        if r in ("off", "closed"): iv = []
        else:
            iv = _times(r)
            if iv is None: return None
        if only_ph: continue
        rules.append((months, days, iv))
    return rules or None

if __name__ == "__main__":
    import json, sys
    from fetch_osm import S, W, N, E
    from paths import osm
    els = json.load(open(osm("extra_poi.json")))["elements"]
    def ll(e):
        if "lat" in e: return e["lat"], e["lon"]
        c = e.get("center"); return (c["lat"], c["lon"]) if c else (None, None)
    ch = [e for e in els if e.get("tags", {}).get("amenity") == "place_of_worship"
          and (lambda a, b: a is not None and S <= a <= N and W <= b <= E)(*ll(e))]
    oh = [e for e in ch if "opening_hours" in e["tags"]]
    ok = [e for e in oh if parse(e["tags"]["opening_hours"])]
    print(f"churches {len(ch)}, with hours {len(oh)}, readable {len(ok)}")
    for e in oh:
        if not parse(e["tags"]["opening_hours"]):
            print("  refused:", e["tags"].get("name", "?")[:40], "|", e["tags"]["opening_hours"][:80])
