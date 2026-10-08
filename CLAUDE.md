# Ombra Roma

A street-by-street shade map of central Rome, plus shade-aware walking routes.
Built because walking Rome in 38 °C is miserable and the shady lane is usually
only a block away from the one you'd have taken.

Output is a **single self-contained HTML file** (~6.4 MB) with all data embedded:
no server, no network, works offline.

## Commands

```
pip install -r requirements.txt && npm install
npx playwright install chromium webkit    # both; make test needs WebKit too
make            # full build (data is cached, so ~10 min)
make artifact   # build/artifact.html, the file you publish as an Artifact
make test       # needs a build first; model + browser checks (Chromium, WebKit)
make heights    # score every height source against the OSM tags; needs data/ only
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
| `fetch_osm.py` | streets, buildings, water, greenery, trees, nasoni, named places | `data/osm/` |
| `fetch_eubucco.py` | cadastre building heights for the bbox, from EUBUCCO | `data/eubucco/` |
| `terrain.py` | elevation tiles → 10 m grid, map bbox + 2 km margin | `build/terr.npy` |
| `ground.py` | picks terrain smoothing by scoring relief error | `build/ground.npy` |
| `build_dsm.py` | 2 m raster of building + canopy height above ground | `build/dsm.npy` |
| `shade.py` | **the model.** 768 sun positions × ~39 k segments | `build/frames.npy` |
| `graph.py` | walking graph from segment geometry, junction-split | `build/graph.npz` |
| `places.py` | searchable destinations + curated shortlist | `build/places_pack.json` |
| `pack.py` | everything → one gzipped binary blob, base64 | `build/data.b64` |
| `build_standalone.py` | template + payload + document shell; the app's manifest, service worker and icons | `dist/` |
| `build_artifact.py` | template + payload, no shell — for publishing | `build/artifact.html` |

Supporting modules: `geo.py` (local metre projection), `solar.py` (NOAA solar
position), `heights.py` (OSM height tags → metres, plus the cadastre lookup),
`buildings.py` (the outlines, shared by the build and the report),
`streets.py` (segmentation).

Six scripts that measure rather than build, none on the `make` path:
`measure_heights.py` (`make heights`) scores every height source against the OSM
tags and prints the tables `heights.py` quotes; `compare_frames.py` diffs two
`build/frames.npy` so a model change can be seen rather than assumed; and
`measure_overlap.py` (`make overlap`, needs the network and `duckdb`) re-tests
footprint-overlap matching, which sounds like the obvious next win and is not;
`measure_via.mjs` (needs a build) scores which fountain "Route via one"
picks, on 300 random dry walks; and `measure_boot.mjs` (needs a build) times
each boot stage at desktop speed and with the CPU slowed 4×, from the
`window.ombra.BOOT` laps the page records; and `measure_dates.py` (needs a
build, ~4 min) computes the real shade for the 8th and 23rd of every month
with `shade.frame()` and scores the ways the page can stand in for a day it
does not sample.

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
it is verified byte-identical to zlib. Native `DecompressionStream` would not
have been faster anyway: on this payload in Chromium it took 529 ms where
`ozInflate` took 320 ms. There is also a `window.addEventListener('error')` handler that writes
failures onto the loading screen, so nothing fails silently again.

**Geolocation cannot work in the hosted artifact.** Artifacts render in a
cross-origin iframe, and geolocation's default allowlist is `self`, so it is off
unless the parent passes `allow="geolocation"`. Detect this **structurally**
(cross-origin parent, `isSecureContext`) — the previous version sniffed the
browser's error message for "policy", which is Chromium's wording, so Safari
fell through and wrongly told the user they had blocked location. Never assert a
cause the page cannot verify.

**A new thing on the map competes with the only thing it is for.** Two rules the
nasoni had to obey, and both were learned by putting 460 dots on the screen and
looking at it. *Colour is the shade ramp* — every hue on the map already means a
percentage, so a blue fountain reads as a shaded street. New marks are drawn in
`--ink` and `--panel`, with no hue of their own. *Density is measured, not
guessed* — the whole set is 382 dots on a 390×664 phone at the default zoom, one
per 678 px², which is not a map any more. `NASO_ZOOM` is 0.40 px/m because that
leaves about 45 of them on screen, and the number came from counting, not from
taste. The legend row appears and disappears with them, because a key for
something you cannot see is furniture.

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

**Nothing about the cadastre match is a free parameter — `make heights` is how
you find out.** `heights.py` matches by containment: a cadastre parcel belongs
to a building when its centroid falls inside that building's own outline. That
is the relationship the two datasets have, because the cadastre splits a block
into parcels where OSM draws one outline. An 8 m nearest-centroid radius is kept
as a fallback for the other direction — outlines OSM draws more finely than the
cadastre, which contain no parcel at all — and that radius is *not* a rounding
tolerance: it is where the data stops beating the interpolation it replaces. It
was re-tested after containment went in and got tighter, not looser. The +1.00 m
offset is fitted, and five-fold cross validated. Every one of those numbers comes
out of `measure_heights.py`, which scores the shipped `cadastre_heights` against
the 2,443 OSM-tagged buildings — run it, read it, and paste what it says. Never
move one of these by eye, and never quote a number this file already carries
without re-deriving it.

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

**The route panel resizes the map, so frame the map last.** On a phone the whole
console is hidden while the panel is up (`#app.routing`), which makes the map
area grow by about 250 px and shrink again on close; the picker on top of that
is a sheet over the lower 54 %. `setEnd` used to call `frameEnds` before it asked
the next question, so the start pin was centred for a layout that no longer
existed and landed under the sheet — visible in a screenshot, not visible on the
phone. Anything that measures `W`/`Hh` or `#rcard.offsetHeight` has to run after
the class changes, and every class change that moves the console has to call
`resize()`, or the canvas keeps the old size.

**Hiding the console took the clock with it, so the day strip had to become a
control.** It had always looked like one and been a hover readout — a
distinction a touchscreen cannot even express. With the console gone it was the
only way left to change the hour, so `bindStrip` now scrubs on tap and drag, and
previews only for a mouse that is passing over. That is also the better control
here: `#rstrip` plots the route's own shade through the day, so "worst 13:00" is
something you can act on. If you hide more of the console, check what else was
the only copy of something.

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

**Never `closePath` in a path with thousands of subpaths.** In Chromium it
costs time proportional to the path so far, so drawing every outline in one
path is quadratic: 2 k outlines 22 ms, 16 k 1,340 ms, 32 k 5,431 ms. `drawPolys`
did exactly that, and it was 1.15 s of a 1.7 s desktop boot — about 5 s of 7 on
a phone — and the same again on every whole-city redraw. Ending each outline
with `lineTo` back to its first point costs 4 ms at 16 k and fills identically,
because `fill` closes subpaths itself. Boot went from 1.7 s to 0.5 s, and at 4×
CPU from ~6.8 s to 2.0 s. It hid for so long because it is invisible zoomed in,
where culling leaves a few hundred outlines, and because nothing timed the
boot by stage: `measure_boot.mjs` does now.

**The Pages copy is an installable app, and nothing else is.** `build_standalone.py`
writes `manifest.webmanifest`, `sw.js` and `icons/` beside the page and puts
`<meta name="ombra-app">` in the standalone's head. `startApp()` only registers
the service worker and adds the manifest link when that meta is there *and* the
page came over http(s) — so not in the artifact (the platform's shell has no
meta) and not from a downloaded `file://` copy (no service worker can run, and a
static manifest link would be fetched and fail loudly). Three rules it depends on:

- *`sw.js` carries the build stamp.* That is how a browser learns of a deploy:
  Pages serves the page with `max-age=600`, but a service worker script is always
  revalidated. A build that left `sw.js` byte-identical would never update an
  installed copy.
- *The worker never takes over by itself.* It installs, waits, and the page shows
  the **Reload** pill; only the tap sends `skip`. Swapping the page under someone
  mid-walk would lose their route.
- *Installed, `checkFresh` asks the worker, not the page.* A reload would only
  serve the same cached build, so a newer `version.txt` triggers `update()`; if
  that finds nothing to install, the worker already holds the newer page (the
  HTTP cache served an old one on the way in) and the pill offers a plain reload.

`version.txt` always goes to the network, or no deploy could ever be seen. The
worker precaches with `cache: "no-cache"` — revalidate, so a first visit gets a
304 for the 6 MB it just downloaded and an update gets the new page rather than
the HTTP cache's ten-minute-old one. Playwright's WebKit runs no service workers,
so `tests/smoke.mjs` checks all of this in Chromium only: manifest and icon
sizes, install, control, an offline boot, and a deploy offered and taken.
If a broken build ever ships, an installed copy cannot show the pill that would
replace it — but the browser still fetches the next `sw.js` on launch, and a
waiting worker takes over once every window using the old one is closed. So the
fix for a bad deploy is another deploy, and "close the app and reopen it" is
what to tell anyone stuck on it.

**Today is answered with the closest sun, not the nearest date.** The model
samples the 1st and 15th; every other day the page used to show the nearest of
those at the same clock time. `measure_dates.py` scored that against the real
shade of the 8th and 23rd of every month: **3.03 pp** mean error, 4.37 % of
street-frames off by more than 20 — and **12.9 pp** around the clock changes,
where 23 October at 14:00 was answered with 1 November at 14:00, after the
clocks go back: an hour of sun away. Blending the two dates either side scored
2.29. Taking the stored frame, from *any* date, whose sun is closest in the sky
scored **1.63 pp** (2.37 %), 2.47 across the clock changes; blending the two
closest suns did no better (1.67). Shade depends on the sun's direction and
nothing else in this model, so 23 October is answered from 15 February, whose
afternoon sun is 1° away. `solarPos` in the template is `solar.py` line for
line, and the smoke test holds it to the build's own sun on all 768 frames
(0.005° worst) and to `shade.py`'s clock-change rule. `sunAt(t)` is the one place
a slot becomes a frame; it does not unpack shade, `frameAt(t)` does — the
daylight band needs only the sun's height, and loading through it unpacked two
dates at boot. Choosing a month or the 1st/15th still shows that sampled date
exactly.

**Location, now and saved places are the installed app's, and each is
cautious in a specific way.** The dot is ink and panel like every other mark,
with a halo the size of the fix's accuracy. It starts by itself only where
permission is *already* granted — never a prompt at launch — and a fix far off
the map stops the GPS silently at launch and explains itself only when the
button asked. The clock follows real time (every 30 s, and on return to the
front) until the hour is moved by hand; moving the hour keeps today's date,
choosing a date leaves it, and **Back to now** restores both. Saved places are
stored as positions, not node numbers — every rebuild renumbers the nodes and a
saved hotel would quietly move — and matched back within 25 m.

**"Route via one" is scored on the dry stretch, not on the detour.** The
obvious rule — the fountain that adds least — chose one the walk already passed
97 % of the time: median detour 0 m, and every dry walk exactly as dry. The
minimax rule (shortest longer leg) ignores the fountains already on the way and
only moved the median dry stretch from 841 m to 776 m. What ships scores each
fountain as *longest dry stretch of the new walk + metres it adds*, both in
walked metres, so there is no weight to tune: 841 m → 581 m median, p90
1,412 m → 844 m, for a median 17 m more walking (Balanced, `node
measure_via.mjs`). "Metres added" can be negative — the stop can pull a
shade-weighted walk onto a shorter line. Two sweeps (from A, from B) give every
fountain both legs at once; candidates are tried in order of a lower bound on
their detour (crow-flies A→F→B, and cost/(1+k)) and stop when that alone loses,
which took Shadiest from 188 ms a recompute to 74 ms. The button only appears
where the dry-stretch line does, and the line must stay one line on a phone:
two pushes the card past half the map.

## Publishing

Three places the page ends up, and mixing them up wastes an afternoon:

- **<https://ptrestler.github.io/ombra/>** — GitHub Pages, deployed by the
  `deploy` job from the same build the tests ran against. Nothing is committed
  for it. This is the link to send someone: a top-level HTTPS document, so it is
  the only hosted copy where **geolocation works**. It is deployed with a `version.txt`
  beside it, which is how the page spots a browser holding a cached build, and
  with the manifest, service worker and icons that make it **installable**: Add to
  Home Screen on iOS, Install app in Chrome. Installed, it opens full screen and
  boots with no network.

Two builds feed all of this:

- **`dist/ombra-roma.html`** — the standalone. A complete document, works offline,
  from disk, anywhere. This is what you send people and what the tests load.
  Not committed: it is 6.4 MB of base64 over gzip, which barely compresses and
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

Base64 lines in a `<script type="text/plain">`: one gzip blob, then one gzip
stream of shade per date. The blob is `[uint32 header length][header JSON][binary
sections]`. The header names each section's offset, length and dtype, and
carries the projection, frame metadata, street names, place list, shortlist and
`city`, the city-wide mean shade of every frame. Coordinates are `uint16`,
quantised to 0.5 m against an origin in the header. Shade is one byte per
segment per frame, **segment-major** within each date — that ordering alone
halves the gzipped size, because a segment's shade over consecutive half-hours
is smooth.

**Shade is split by date because unpacking it was most of a phone's boot.** It
is 29 MB of the 31 MB unpacked, and the page only ever reads one date of it, so
each of the 24 dates (`head.ndate`, `head.slots` = 32 frames each) is its own
gzip stream and boot inflates only the one it opens on. `D.shade` keeps its full
`[segment][frame]` shape and `dateBase()` — which every shade read goes through —
fills a date the first time it is asked for. Measured with `measure_boot.mjs`:
boot 2.04 s → 0.91 s with the CPU slowed 4×, 0.49 s → 0.28 s on desktop. A date
then costs 155 ms / 56 ms the first time you switch to it. The price is size:
24 separate streams lose some of the segment-major compression, 2.76 → 3.56 MB
of gzip, and the file grew 5.4 → 6.4 MB. Twelve monthly streams would have cost
+20 % instead of +29 %, but they unpack twice as much at boot. Anything that
reads `D.shade` without going through `dateBase()` must call
`window.ombra.loadDate(d)` first — the smoke test does, and checks every date
lands in its own frames against `head.city`.

`window.ombra` exposes state and helpers (`st`, `head`, `data`, `setEnd`,
`recompute`, `nearestNode`, `labelForNode`, `screenXY`, `loadDate`, `BOOT`) for debugging and for the
tests.

Nasoni ride along in two `u2` sections, `nax`/`nay`, quantised like everything
else; `head.nnaso` is the count. They carry no names — 460 points cost under 2 kB
packed, and what you want from a fountain is that it is there.

## Accuracy, measured

| | |
|---|---|
| Relief error vs known heights | **9.8 m** (flat-earth model was 44.9 m) |
| Buildings with a real OSM height | 2,443 of 14,158 |
| …matched to the Lazio cadastre instead | 8,180 more — 70 % of the untagged |
| …still interpolated from neighbours | 3,535, the ones neither source reaches |
| Error of the cadastre heights | **RMSE 4.90 m**, MAE 3.46 m, bias −0.00 m — against the OSM tags, on the 1,996 buildings that have both. Interpolation scored 5.53 m on those same buildings |
| Error of the interpolation that is left | RMSE 6.94 m, MAE 4.70 m (n = 447). The buildings the cadastre cannot reach are the hardest ones, so this number gets *worse* every time the matching gets better |
| Error of every non-tagged height | **RMSE 5.33 m**, MAE 3.69 m, bias +0.19 m — was 5.53 m / 3.83 m |
| Shade's sensitivity to that error | 94.5 % of segment-frames unmoved, city mean shifts 0.29 pp — but 5.5 % move by >10 pp |
| Walking network | 54,530 links, ~988 km, 97 % one connected component |
| Median detour index | 1.22 (healthy pedestrian networks are 1.20–1.35) |
| Sunrise/sunset vs published | within 4 min at both solstices and the equinox |

**Height error does not average out, it concentrates.** Perturbing every
non-tagged height by its own measured error (σ = 4.90 m for the cadastre ones,
6.94 m for the interpolated) leaves 94.5 % of the 30.4 M segment-frame values
*bit-identical* and moves the city-wide mean shade by 0.29 pp. The 5.5 % that do
move, move hard: >1 pp, >5 pp and >10 pp are all the same 5.5 % of values, and
3.4 % move by more than 20 pp. Ray blocking is a threshold — a few metres either
does not change whether the sun is occluded, or changes it completely. So the
aggregate numbers are robust and individual streets are not, which is the
opposite of what "a quarter of the heights are estimated" suggests.

That paragraph is re-derivable, and should be re-derived rather than copied:
`OMBRA_JITTER=<seed> python build_dsm.py && python shade.py` builds the same map
with every estimate moved by its own σ, and `compare_frames.py` diffs it against
the real one. Call the two scripts, not `make`: the grid is already up to date as
far as make is concerned, so it would skip the rebuild and diff a map against
itself. The
σ values it uses live in `heights.py` next to the matching rules, so they go
stale together or not at all.

**Neither cadastre change moved that shape, and neither was expected to.** The
same test moved 5.5 % of values before the cadastre went in, 5.9 % after it, and
5.5 % again once matching moved to containment. Fewer heights are guessed each
time and the guesses that remain are better measured, but the fraction of the map
sitting near a blocking threshold is a property of Rome's geometry, not of the
height data.

**And the diff alone never shows the map got better.** Switching the cadastre on
moved 5.0 % of segment-frames and the city mean by −0.80 pp; switching to
containment moved 3.5 % and +0.29 pp. Both are the same order as the noise above,
so a diff can only tell you *how much* changed, never whether it improved. The
case each time is the measurement against the OSM tags — for containment, 4.65 m
against 5.02 m on the 1,620 buildings both rules reach, bootstrap interval
[−0.71, −0.16] — plus 1,040 more buildings whose height was surveyed instead of
inferred from the neighbours.

**Footprint overlap does not beat the interpolation it would replace, and the
reason is in the data rather than the geometry.** Containment handles the
cadastre splitting a block more finely than OSM draws it. The reverse case — our
outline inside one big parcel, containing no parcel centroid — looks like a
geometry problem with an obvious fix, and `measure_overlap.py` tests both forms
of it against the OSM tags. The parcel our centre falls in scores 5.00 m where
the interpolation it would displace scores 4.96 m; the parcel covering most of
us scores 5.54 m against 5.40 m. Both bootstrap intervals straddle zero. Taking
either lifts coverage from 70 % to 83 % and makes the model's overall error
slightly *worse*, 5.33 m to 5.37 m.

That is not a near miss to be tuned. When the cadastre lumps several buildings
into one parcel, that parcel's height is an average over a block, which is the
same kind of estimate the inverse-distance interpolation already builds out of
tagged neighbours — so the swap trades one average for another and pays 19 MB of
polygons for it. The cadastre holds no separate measurement for those 3,535
buildings. Getting them measured means a different source, not a better match.

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

- **Cool refuges.** Churches and shaded squares, as places to stop rather than
  walk through. Deliberately left out of the nasoni change: a church is only a
  refuge when it is open, and nothing in the pipeline knows opening hours, so the
  map would be promising something it cannot check. Needs `opening_hours` parsing
  before it is honest.
- ~~**The 3,535 heights still guessed, via footprint overlap.**~~ Tried and
  measured: it does not pay. See below — `measure_overlap.py` is the receipt.
  If you want those buildings measured rather than estimated, the cadastre is
  not where the measurement is.
- **Wider coverage.** The bbox stops at the historic core; Quartiere Coppedè,
  Testaccio, Ostiense and EUR are just outside. What it costs is measured, not
  the streets themselves (the cache ends at the bbox): almost all of the file is
  per-segment data, about **152 B of HTML per segment and 31 B per building**
  since shade was split by date. The bbox's own 1 km cells run from 800
  segments/km² (Villa Pamphili) to 2,700 (centro storico), mean 1,936, so a km²
  costs **245–380 kB** of file but only **+35–55 ms of phone boot**, because
  boot unpacks one date of shade, not 24 (`measure_boot.mjs`). A 1 km strip on
  one side is ~5 km²: +1.2–1.9 MB, ~1.1 s phone boot. Strips on the south,
  north and east together: ~11.6 MB, ~1.7 s. File size, not boot, is now the
  limit — the artifact cap is 16 MB. EUR, 4–5 km south, would roughly double
  the file on its own; it wants its own bbox, not a stretched one. Terrain
  already reaches 2 km past the bbox.
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
