"""Where everything lives. Every script resolves paths through here, so the
pipeline runs the same from any working directory."""
import os
ROOT  = os.path.dirname(os.path.abspath(__file__))
DATA  = os.path.join(ROOT, "data")
OSMD  = os.path.join(DATA, "osm")
DEMD  = os.path.join(DATA, "dem")
EUBD  = os.path.join(DATA, "eubucco")
BUILDD= os.path.join(ROOT, "build")
WEBD  = os.path.join(ROOT, "web")
DISTD = os.path.join(ROOT, "dist")
for _d in (OSMD, os.path.join(OSMD,"tiles"), DEMD, EUBD, BUILDD, DISTD):
    os.makedirs(_d, exist_ok=True)
osm   = lambda n: os.path.join(OSMD, n)
dem   = lambda n: os.path.join(DEMD, n)
eub   = lambda n: os.path.join(EUBD, n)
build = lambda n: os.path.join(BUILDD, n)
web   = lambda n: os.path.join(WEBD, n)
dist  = lambda n: os.path.join(DISTD, n)
