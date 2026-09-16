# Ombra Roma

A street-by-street shade map of central Rome, plus shade-aware walking routes.
Built because walking Rome in 38 °C is miserable and the shady lane is usually
only a block away from the one you'd have taken.

Output is a **single self-contained HTML file** (~5.3 MB) with all data embedded:
no server, no network, works offline.

## Commands

```
pip install -r requirements.txt && npm install
npx playwright install chromium webkit    # both; make test needs WebKit too
make            # full build (data is cached, so ~10 min)
make artifact   # build/artifact.html, the file you publish as an Artifact
make test       # needs a build first; model + browser checks (Chromium, WebKit)
make clean      # drop derived files, keep downloads
```

`make` rebuilds `dist/ombra-roma.html`. The expensive stage is `shade.py` (~7 min).

## Pipeline

Each stage reads `build/` and writes `build/`. Paths always go through `paths.py`
so scripts run from any directory.

| stage | what it does | out |
|---|---|---|
| `fetch_osm.py` | streets, buildings, water, greenery, trees, named places | `data/osm/` |
| `terrain.py` | elevation tiles → 10 m grid, map bbox + 2 km margin | `build/terr.npy` |
| `ground.py` | picks terrain smoothing by scoring relief error | `build/ground.npy` |
| `build_dsm.py` | 2 m raster of building + canopy height above ground | `build/dsm.npy` |
| `shade.py` | **the model.** 768 sun positions × ~39 k segments | `build/frames.npy` |
| `graph.py` | walking graph from segment geometry, junction-split | `build/graph.npz` |
| `places.py` | searchable destinations + curated shortlist | `build/places_pack.json` |
| `pack.py` | everything → one gzipped binary blob, base64 | `build/data.b64` |
| `build_standalone.py` | template + payload + document shell | `dist/ombra-roma.html` |
| `build_artifact.py` | template + payload, no shell — for publishing | `build/artifact.html` |

Supporting modules: `geo.py` (local metre projection), `solar.py` (NOAA solar
position), `heights.py` (OSM height tags → metres), `streets.py` (segmentation).

## How the shade model works

Street centrelines are cut into 40 m segments and sampled every 8 m. Each sample
is tested on **both sides** of the street, offset to where a pavement would be;
the reported number assumes you walk on the shadier side. From each sample a ray
is cast at the sun and tested against absolute surface elevation — `ground(q) +
object(q)` — starting from the observer's own ground height. That last part is
what lets the Janiculum shadow Trastevere.

Frames are the 1st and 15th of each month, every 30 min from 06:00 to 21:30
(24 dates × 32 slots = 768). Times are Rome civil time with real EU DST dates.

## Things that will bite you

**`make test` needs a build first.** The Commands block above is in dependency
order, not a menu. On a fresh clone `build/` is empty, so `tests/validate.py`
has nothing to read and exits with `build it first: make`. Run `make` first.
`make clean` deliberately returns you to that state.

**Overpass mirrors are the worst part of this project.** `overpass-api.de`
resets connections from cloud IPs; `overpass.osm.ch` answers with *zero
elements* rather than an error, which silently produces an empty map. The mirror
list in `fetch_osm.py` is ordered by what actually worked. Everything is cached
in `data/osm/` — a cold fetch took about an hour. Don't delete the cache casually.

**`area=yes` ways are pedestrian piazzas and must be included.** Dropping them
(the obvious-looking filter) severs the walking network across Piazza della
Rotonda, Piazza Venezia and ~300 other squares. Including them took dead-end
nodes from 17.9 % to 7.0 % and the median detour index from 1.31 to 1.22.
Piazzas are modelled as their **perimeter**, so routes walk round a square, not
across it — conservative, and the edge is the shadier line anyway.

**`web/template.html` is not a valid HTML document and will look broken if you
open it directly.** It is written for the claude.ai Artifact wrapper, which
supplies the doctype, `<head>`, charset and viewport at publish time.
`build_standalone.py` adds a real document shell for the downloadable build.
Anything you test must be `dist/ombra-roma.html`.

**Don't use `DecompressionStream` to unpack the payload.** Some embedded web
views — iOS Quick Look among them — expose the Streams API but never resolve it,
so the page hangs on the loading screen with no error to catch. `ozInflate` in
`web/template.html` is a ~90-line DEFLATE decoder written inline for that reason;
it is verified byte-identical to zlib and takes ~0.4 s on desktop, ~1.5 s on a
phone. There is also a `window.addEventListener('error')` handler that writes
failures onto the loading screen, so nothing fails silently again.

**Geolocation cannot work in the hosted artifact.** Artifacts render in a
cross-origin iframe, and geolocation's default allowlist is `self`, so it is off
unless the parent passes `allow="geolocation"`. Detect this **structurally**
(cross-origin parent, `isSecureContext`) — the previous version sniffed the
browser's error message for "policy", which is Chromium's wording, so Safari
fell through and wrongly told the user they had blocked location. Never assert a
cause the page cannot verify.

**Overlay UI must be listed in `UIHIT`.** `#stage` captures pointer events for
pan/zoom; any panel not in that selector list gets its taps *also* treated as map
taps. This silently broke the route picker — selecting "Pantheon" set the start
to whatever street sat under the panel.

**Test in WebKit, not just Chromium.** Three separate bugs (the Streams hang, the
geolocation message, an unclickable close button behind a stacking context) were
invisible in Chromium. `npx playwright install webkit` if it is missing.
`tests/smoke.mjs` honours `PLAYWRIGHT_CHROMIUM_PATH` and `PLAYWRIGHT_WEBKIT_PATH`
for unusual installs; leave both unset unless you actually need them.

## Publishing

Two different builds, and mixing them up wastes an afternoon:

- **`dist/ombra-roma.html`** — the standalone. A complete document, works offline,
  from disk, anywhere. This is what you send people and what the tests load.
- **`build/artifact.html`** — what gets published as a claude.ai Artifact:
  `web/template.html` + `build/data.b64`, assembled by `make artifact`. The
  platform wraps it in the document shell, so it carries no doctype or `<head>`
  of its own. Never publish the standalone — the shells would nest.

The artifact already exists; publishing without pointing at it creates a *second*
one instead of a new version. Run `/artifacts`, pick "Ombra Roma" and press Enter
to attach it to the session — or hand over the URL:

    https://claude.ai/code/artifact/a0e7160c-d33b-4d62-abd1-5f35bce2f649

Publishing to that URL is refused unless the session has read the live version
first. That's deliberate: it stops one session silently overwriting another's.
Read it, merge, publish.

Two things the hosted copy cannot do that the standalone can: **geolocation**
(blocked by the cross-origin iframe) and **offline use**. And sharing is *pinned
to a version* — viewers keep seeing whichever version was pinned when the link
was shared, so after a meaningful change, update the pin from the artifact's
share menu or the link still shows the old build.

## Payload format

One gzip blob, base64 in a `<script type="text/plain">`. Layout:
`[uint32 header length][header JSON][binary sections]`. The header names each
section's offset, length and dtype, and carries the projection, frame metadata,
street names, place list and shortlist. Coordinates are `uint16`, quantised to
0.5 m against an origin in the header. Shade is one byte per segment per frame,
**segment-major** — that ordering alone halves the gzipped size, because a
segment's shade over consecutive half-hours is smooth.

`window.ombra` exposes state and helpers (`st`, `head`, `data`, `setEnd`,
`recompute`, `nearestNode`, `labelForNode`) for debugging and for the tests.

## Accuracy, measured

| | |
|---|---|
| Relief error vs known heights | **9.8 m** (flat-earth model was 44.9 m) |
| Buildings with a real OSM height | 2,443 of 14,158 — the other 83 % are estimated from tagged neighbours |
| Walking network | 54,530 links, ~988 km, 97 % one connected component |
| Median detour index | 1.22 (healthy pedestrian networks are 1.20–1.35) |
| Sunrise/sunset vs published | within 4 min at both solstices and the equinox |

**The elevation data is a surface model, not bare earth** — buildings are baked
in, so the dense centre reads ~12 m high and hill-to-valley relief is compressed
by ~8 m. Three corrections were tried and *all made relief worse*: morphological
opening (fails — the centro storico is continuously built up, so no window
contains ground), interpolation through OSM-derived open cells (drags built-up
hilltops down), and subtracting modelled building lift (flattens hills more than
valleys). The raw DEM stands. Most of the bias cancels, because you and the
building beside you sit on the same slightly-wrong ground.

Not modelled: awnings, scaffolding, parked buses, cloud, humidity, or the radiant
heat coming off travertine. Tree canopy comes from 4,800 mapped trees and is
patchy — some leafy streets score drier than they feel.

## Possible next steps

- **Nasoni and cool refuges.** Rome's public drinking fountains
  (`amenity=drinking_water`), churches and shaded squares, routable as waypoints.
  Cheap, and at 38 °C arguably worth as much as the shade itself.
- **Better building heights.** 83 % are currently imputed. A European building-height
  dataset would tighten every number on the map.
- **Wider coverage.** The bbox stops at the historic core; Quartiere Coppedè,
  Testaccio, Ostiense and EUR are just outside.
- **Multi-stop day planning** — order a day's sights to minimise sun exposure.
- **Another city.** Nothing in the pipeline is Rome-specific except the bbox in
  `fetch_osm.py`/`terrain.py`, the landmark shortlist in `places.py`, and the
  timezone/DST rule in `shade.py`.

## Conventions

- Never hand-type coordinates. Everything resolves against real OSM data —
  the shortlist in `places.py` is a list of *names*, matched at build time.
- Claims in the UI's methodology panel are measured, not asserted. If you change
  the model, re-measure and update the numbers there.
- `tests/validate.py` guards the physics; `tests/smoke.mjs` guards the page.
  Run both before publishing.
