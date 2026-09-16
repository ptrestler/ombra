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
`make fetch` is the only target that needs the network, and the only one that needs
`duckdb` (for `fetch_eubucco.py`); everything it downloads is committed under `data/`.

## Pipeline

Each stage reads `build/` and writes `build/`. Paths always go through `paths.py`
so scripts run from any directory.

| stage | what it does | out |
|---|---|---|
| `fetch_osm.py` | streets, buildings, water, greenery, trees, named places | `data/osm/` |
| `fetch_eubucco.py` | cadastre building heights for the bbox, from EUBUCCO | `data/eubucco/` |
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
position), `heights.py` (OSM height tags → metres, plus the cadastre lookup),
`streets.py` (segmentation).

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

**The six named streets in `tests/validate.py` sit in shade's insensitive
majority.** Scrambling every non-tagged building height by its full measured
error changes 5.9 % of the map by more than 10 percentage points, and moves the
six fixtures by at most 2 pp — all six still pass. They guard the physics and
the data wiring, not the model's sensitivity: a change that wrecks one street in
seventeen passes them clean. When you touch the model, diff `build/frames.npy`
against the old one rather than trusting the named streets.

**The cadastre match radius is load-bearing.** `heights.py` accepts a EUBUCCO
height only when its centroid lands within 8 m of ours. That is not a rounding
tolerance, it is where the data stops being better than the interpolation it
replaces. EUBUCCO subdivides blocks more finely than OSM does, so past about
10 m the nearest centroid is usually the building next door: widening to 12 m
lifts coverage from 61 % to 74 % and pushes the error *above* what interpolation
achieves on the same buildings. The measured table is in `heights.py`. The
−1.36 m offset next to it is fitted, not assumed — re-measure both if you touch
either, and never move one by eye.

**The standalone is useless inside a document previewer, and that is not
fixable.** Opened from iOS Files (Quick Look) it suspends the JavaScript partway
and sits on the loading screen forever; opened from the Google Drive app it runs
the whole boot, paints the map correctly, and then hands you a letterboxed
static card that ignores every tap. Both look like bugs in the page and are not:
a canvas app needs live JavaScript *and* pointer events, and those viewers give
you at most one. iOS also will not open a local `.html` in Safari. So the
standalone is a desktop and offline build; **the hosted artifact is the answer
for a phone**, because it runs in a real browser.

**Never paint text with `rampFor`.** The ramp is built for thin lines over the
map; as 31 px numerals on a panel its middle disappears, and a route reading
73 % rendered as an indigo you could not make out against the dark card. Use
`rampInk`, which keeps the hue and walks it toward the panel's own text colour
until it clears 4.5:1 against *both* `--panel` and `--panel-2` — the route card
sits on one in the sidebar and the other on a phone. Note it returns
`rgb(r,g,b)` while the tokens are hex; mixing the two up is what made the first
attempt paint every number the same flat ink.

**A push can be live and still not be on the screen.** Pages serves
`index.html` with `Cache-Control: max-age=600` and gives no way to change that,
so for up to ten minutes a browser that already has the page keeps answering
from its own copy. Closing the tab is what fixes it. That cost two rounds of
"it's not there" over a button that was in every build, and the wrong conclusion
both times was that the deploy had failed. The page cannot beat the cache, so it
notices instead: `buildstamp.py` makes a time-and-commit string, both builders
stamp it into the template, the standalone writes the same string to
`dist/version.txt`, CI deploys the two together, and `checkFresh` fetches
`version.txt` with `no-store` on load and again whenever the tab comes back to
the front. If they disagree, a **Reload** pill appears. It only fetches on
http(s) — a `file://` copy cannot make that request, and what comes back is a
console error the browser logs before `.catch` ever sees it. The artifact is on
https and just 404s, which is the same as silence. So the prompt can only appear
where something deployed a `version.txt`, which is the only place it means
anything.

**Test in WebKit, not just Chromium.** Three separate bugs (the Streams hang, the
geolocation message, an unclickable close button behind a stacking context) were
invisible in Chromium. `npx playwright install webkit` if it is missing.
`tests/smoke.mjs` honours `PLAYWRIGHT_CHROMIUM_PATH` and `PLAYWRIGHT_WEBKIT_PATH`
for unusual installs; leave both unset unless you actually need them.

## Publishing

Three places the page ends up, and mixing them up wastes an afternoon:

- **<https://ptrestler.github.io/ombra/>** — GitHub Pages, deployed by the
  `deploy` job from the same build the tests ran against. Nothing is committed
  for it. This is the link to send someone: a top-level HTTPS document, so it is
  the only hosted copy where **geolocation works**. It is deployed with a `version.txt`
  beside it, which is how the page spots a browser holding a cached build.

Two builds feed all of this:

- **`dist/ombra-roma.html`** — the standalone. A complete document, works offline,
  from disk, anywhere. This is what you send people and what the tests load.
  Not committed: it is 5.3 MB of base64 over gzip, which barely compresses and
  cannot be delta'd, so every rebuild added that much to the history for good.
  CI uploads it to a release asset on a fixed `build` tag instead, replaced in
  place on every push to `main`, so the download is always current, the URL never
  changes and the repository pays nothing:
  `https://github.com/ptrestler/ombra/releases/download/build/ombra-roma.html`
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

That pin is easy to mistake for a failed publish. Signed in as the owner you get
the newest version; signed out — which is what a fresh browser is — the same URL
serves the pinned one, frame version and all. Check which you are looking at
before concluding the publish did not land:

    document.querySelector('iframe').src     // .../_f/<version>/...

The share URL is the same artifact under a shorter slug:
`https://claude.ai/artifact/LsQ9MwiwY46nuxBJGoDkuN`. Either form works as `url`
when publishing.

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
| Buildings with a real OSM height | 2,443 of 14,158 |
| …matched to the Lazio cadastre instead | 7,140 more — 61 % of the untagged |
| …still interpolated from neighbours | 4,575, the ones neither source reaches |
| Error of the cadastre heights | **RMSE 5.01 m**, MAE 3.53 m, bias +0.00 m — against the OSM tags, on the 1,620 buildings that have both. Interpolation scored 5.50 m on those same buildings |
| Error of the interpolation that is left | RMSE 6.42 m, MAE 4.40 m (n = 823). The buildings the cadastre misses are the harder ones, so this is worse than the 5.83 m the old build averaged |
| Error of every non-tagged height | **RMSE 5.53 m**, MAE 3.83 m, bias +0.04 m — was 5.83 m / 4.19 m |
| Shade's sensitivity to that error | 94.1 % of segment-frames unmoved, city mean shifts 0.36 pp — but 5.9 % move by >10 pp |
| Walking network | 54,530 links, ~988 km, 97 % one connected component |
| Median detour index | 1.22 (healthy pedestrian networks are 1.20–1.35) |
| Sunrise/sunset vs published | within 4 min at both solstices and the equinox |

**Height error does not average out, it concentrates.** Perturbing every
non-tagged height by its own measured error (σ = 5.01 m for the cadastre ones,
6.42 m for the interpolated) leaves 94.1 % of the 30.4 M segment-frame values
*bit-identical* and moves the city-wide mean shade by 0.36 pp. The 5.9 % that do
move, move hard: >1 pp, >5 pp and >10 pp are all the same 5.9 % of values, and
3.7 % move by more than 20 pp. Ray blocking is a threshold — a few metres either
does not change whether the sun is occluded, or changes it completely. So the
aggregate numbers are robust and individual streets are not, which is the
opposite of what "a third of the heights are estimated" suggests.

**Adding the cadastre did not change that shape, and was not expected to.**
Before it, the same test moved 5.5 % of values; after, 5.9 %. Fewer heights are
now guessed and the guesses that remain are better measured, but the fraction of
the map that sits near a blocking threshold is a property of Rome's geometry,
not of the height data. Switching the cadastre on moved 5.0 % of segment-frames
and the city mean by −0.80 pp — the same order as the noise above, so **the diff
alone does not show the map got better.** The case for it is the measurement:
5.01 m against 5.50 m on the same 1,620 buildings, and a height that was
surveyed rather than inferred from the neighbours.

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
- **The 4,575 heights still guessed.** The cadastre reaches 61 % of the untagged
  buildings; the rest have no EUBUCCO centroid within 8 m, usually because OSM
  and the cadastre disagree about where one building stops and the next starts.
  Matching on footprint overlap instead of centroid distance would reach most of
  them, and it is a geometry problem rather than a data problem — the data is
  already downloaded. This is the largest remaining gain in the model.
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
