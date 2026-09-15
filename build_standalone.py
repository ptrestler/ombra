import io, os
from paths import osm, dem, build, web, dist
body = io.open(web("template.html"), encoding="utf-8").read()
data = io.open(build("data.b64"), encoding="utf-8").read()
body = body.replace("__DATA__", data)

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
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><text y='14' font-size='14'>%E2%9B%B1</text></svg>">
</head>
<body>
"""
TAIL = "\n</body>\n</html>\n"

out = HEAD + body + TAIL
io.open(dist("ombra-roma.html"), "w", encoding="utf-8").write(out)
print("standalone:", round(os.path.getsize(dist("ombra-roma.html"))/1e6, 2), "MB")
print("starts:", repr(out[:60]))
