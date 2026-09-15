# Ombra Roma - shade map and shade-aware routing for central Rome.
# Stages are ordered; each depends on the one above. `make` builds everything.
PY := python3

.PHONY: all fetch rasters shade web artifact test clean distclean

all: web

## fetch -- OpenStreetMap + elevation tiles into data/ (cached; safe to re-run)
fetch:
	$(PY) fetch_osm.py
	$(PY) terrain.py

## rasters -- 2 m building/canopy grid, 10 m terrain grid
rasters: build/dsm.npy build/ground.npy
build/dsm.npy:
	$(PY) build_dsm.py
build/ground.npy: build/terr.npy
	$(PY) ground.py
build/terr.npy:
	$(PY) terrain.py

## shade -- the expensive stage: 768 sun positions x 39k street segments (~7 min)
shade: build/frames.npy
build/frames.npy: build/dsm.npy build/ground.npy
	$(PY) shade.py

## web -- routing graph, destination list, payload, the standalone build
web: dist/ombra-roma.html
build/data.b64: build/frames.npy graph.py places.py pack.py
	$(PY) graph.py
	$(PY) places.py
	$(PY) pack.py
dist/ombra-roma.html: build/data.b64 web/template.html build_standalone.py
	$(PY) build_standalone.py

## artifact -- template + payload only; the platform supplies the document shell
artifact: build/artifact.html
build/artifact.html: build/data.b64 web/template.html build_artifact.py
	$(PY) build_artifact.py

test:
	$(PY) tests/validate.py
	node tests/smoke.mjs

clean:                      ## derived files only; keeps the downloaded data
	rm -rf build dist
distclean: clean            ## also drops the cached downloads (slow to refetch)
	rm -rf data/osm/tiles data/osm/extra_*.json data/dem
