import io, os
from buildstamp import stamp
from paths import osm, dem, build, web, dist
body = io.open(web("template.html"), encoding="utf-8").read()
data = io.open(build("data.b64"), encoding="utf-8").read()
body = body.replace("__DATA__", data)
BUILD = stamp()
assert "__BUILD__" in body, "build stamp placeholder not found"
body = body.replace("__BUILD__", BUILD)

# a downloaded file may be opened with no network (or a blocked font host):
# load the webfont without blocking first paint, and fall back cleanly.
FONT = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bodoni+Moda:'
        'opsz,wght@6..96,400;6..96,600;6..96,700&family=Archivo:wght@400;500;600;700&display=swap">')
assert FONT in body, "font link not found"
body = body.replace(FONT,
    FONT.replace('rel="stylesheet"', 'rel="stylesheet" media="print" onload="this.media=\'all\'"')
    + "\n<noscript>" + FONT + "</noscript>")

# the artifact platform supplies the document shell; a downloadable file needs its own
HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, maximum-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="description" content="Ray-traced shade map and shade-aware walking routes for the historic centre of Rome.">
<meta name="theme-color" content="#f2ece1" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#131217" media="(prefers-color-scheme: dark)">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Ombra">
<meta name="ombra-app" content="1">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><text y='14' font-size='14'>%E2%9B%B1</text></svg>">
</head>
<body>
"""
TAIL = "\n</body>\n</html>\n"

out = HEAD + body + TAIL
# newline="\n" to match build_artifact.py and .gitattributes, which both
# say the build writes LF. Without it Python translates on Windows: the
# standalone came out CRLF while the artifact did not, so git rewrote all
# 5 MB of it on the way in.
io.open(dist("ombra-roma.html"), "w", encoding="utf-8", newline="\n").write(out)
# what the deployed page polls to notice a newer build exists
io.open(dist("version.txt"), "w", encoding="utf-8", newline="\n").write(BUILD + "\n")

# --- the installable app ------------------------------------------------------
# Deployed beside the page on Pages, where it is index.html. The page only reads
# these when it was opened over http(s) from this shell (meta ombra-app): never
# in the artifact, whose shell is the platform's, and never from a file:// copy,
# where a service worker cannot run. Built here so they carry the same stamp.
os.makedirs(dist("icons"), exist_ok=True)
MANIFEST = {
    "name": "Ombra Roma", "short_name": "Ombra",
    "description": "Shade on every street of central Rome, and walks that keep to it.",
    "start_url": "./", "scope": "./", "id": "./",
    "display": "standalone", "orientation": "portrait",
    "background_color": "#f2ece1", "theme_color": "#f2ece1",
    "icons": [
        {"src": "icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
        {"src": "icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png",
         "purpose": "maskable"},
    ],
}
import json
io.open(dist("manifest.webmanifest"), "w", encoding="utf-8", newline="\n").write(
    json.dumps(MANIFEST, indent=2) + "\n")

# The icon is the map's own key: a disc half in the sun colour, half in the
# shade colour, on travertine - no hue the map does not already use. Drawn at 4x and scaled down for clean edges.
from PIL import Image, ImageDraw
def icon(size, r_frac):
    S = size * 4
    im = Image.new("RGB", (S, S), "#f2ece1")
    d = ImageDraw.Draw(im)
    r = S * r_frac; c = S / 2
    box = [c - r, c - r, c + r, c + r]
    # split on the diagonal, the way a building's shadow cuts across a street
    d.pieslice(box, 45, 225, fill="#1c60ab")    # shade, lower left (PIL angles run clockwise)
    d.pieslice(box, 225, 45, fill="#c9203c")    # sun, upper right
    return im.resize((size, size), Image.LANCZOS)
# maskable icons are cropped to a circle of 80 % of the canvas, so the disc
# stays well inside it; the plain ones can fill more
icon(192, 0.34).save(dist("icons/icon-192.png"))
icon(512, 0.34).save(dist("icons/icon-512.png"))
icon(512, 0.27).save(dist("icons/icon-maskable-512.png"))
icon(180, 0.34).save(dist("icons/apple-touch-icon.png"))

# The service worker. A new build writes a new sw.js (the stamp is in it), and
# that is how a browser learns there is something to fetch: Pages serves the
# page with max-age=600, but a service worker script is always revalidated.
SW = r"""// Ombra Roma - built __BUILD__
const V = "__BUILD__";
const PAGE = "ombra-page-" + V, FONTS = "ombra-fonts";
const CORE = ["./", "manifest.webmanifest", "icons/icon-192.png",
              "icons/icon-512.png", "icons/icon-maskable-512.png",
              "icons/apple-touch-icon.png"];

// no-cache, not reload: revalidate, so a first visit gets a 304 for the 6 MB it
// just downloaded instead of fetching it twice, and an update gets the new page
// rather than whatever the HTTP cache still holds from ten minutes ago
self.addEventListener("install", e => e.waitUntil(
  caches.open(PAGE).then(c => c.addAll(CORE.map(u => new Request(u, {cache: "no-cache"}))))));

// it waits until the page says so: swapping the page under someone mid-walk
// would lose their route
self.addEventListener("message", e => { if (e.data === "skip") self.skipWaiting(); });

self.addEventListener("activate", e => e.waitUntil(
  caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith("ombra-page-") && k !== PAGE)
                                         .map(k => caches.delete(k))))
    .then(() => self.clients.claim())));

self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET") return;
  // the freshness check has to reach the network, or it can never see a deploy
  if (url.origin === location.origin && url.pathname.endsWith("/version.txt")) return;
  if (req.mode === "navigate" && url.origin === location.origin) {
    e.respondWith(caches.match("./", {cacheName: PAGE}).then(r => r || fetch(req)));
    return;
  }
  if (url.origin === location.origin) {
    e.respondWith(caches.match(req, {cacheName: PAGE, ignoreSearch: true}).then(r => r || fetch(req)));
    return;
  }
  // the webfonts: from the cache when there is one, refreshed behind it
  if (/^fonts\.(googleapis|gstatic)\.com$/.test(url.hostname)) {
    e.respondWith(caches.open(FONTS).then(c => c.match(req).then(hit => {
      const net = fetch(req).then(r => { if (r.ok || r.type === "opaque") c.put(req, r.clone()); return r; })
                            .catch(() => hit);
      return hit || net;
    })));
  }
});
""".replace("__BUILD__", BUILD)
io.open(dist("sw.js"), "w", encoding="utf-8", newline="\n").write(SW)

print("standalone:", round(os.path.getsize(dist("ombra-roma.html"))/1e6, 2), "MB")
print("build:", BUILD)
print("starts:", repr(out[:60]))
