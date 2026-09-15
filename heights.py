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
