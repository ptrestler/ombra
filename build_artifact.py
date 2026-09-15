# The claude.ai Artifact build: template + payload, and nothing else.
# The platform supplies the doctype, <head>, charset and viewport at publish
# time, so unlike build_standalone.py this adds no document shell. The font
# link is left alone too - the hosted page always has a network.
import io, os
from paths import build, web
body = io.open(web("template.html"), encoding="utf-8").read()
data = io.open(build("data.b64"), encoding="utf-8").read()
assert "__DATA__" in body, "payload placeholder not found in template"
out = body.replace("__DATA__", data)
assert "__DATA__" not in out
assert not out.lstrip().lower().startswith("<!doctype"), "artifact build must not carry a document shell"
io.open(build("artifact.html"), "w", encoding="utf-8", newline="\n").write(out)
print("artifact:", round(os.path.getsize(build("artifact.html"))/1e6, 2), "MB")
print("starts:", repr(out[:40]))
