"""Government building heights for the map bbox, from EUBUCCO v0.2.

Rome is in NUTS region ITI4 (Lazio), and Lazio's heights in EUBUCCO come from
the Italian cadastre, not from OpenStreetMap. That matters: it makes this an
*independent* measurement of the same buildings, so it can be scored against
our OSM height tags without the comparison being circular.

Licence: EUBUCCO is ODbL v1.0, the same licence as OSM, so it mixes with the
rest of the pipeline's data without further conditions. The one Italian
exception in EUBUCCO's licence table is Abruzzo (CC-BY-NC) -- a different
region, and outside this bbox in any case. Attribution is in the page's
methodology panel.

The Lazio parquet lives on a remote S3 and is far larger than we need. DuckDB
reads it over HTTPS and pushes both the bbox filter and the column selection
down into the file, so only the relevant row groups come across the wire --
about 30 seconds rather than a full download.

Output is cached in data/eubucco/rome.csv and committed, like the OSM tiles,
so an ordinary build never touches the network. Delete the CSV and re-run to
refresh. Needs `pip install duckdb`, which the build itself does not.
"""
import os, sys, time
from paths import eub

URL = "https://s3.eubucco.com/eubucco/v0.2/buildings/parquet/nuts_id=ITI4/ITI4.parquet"
S, W, N, E = 41.878, 12.4500, 41.9150, 12.5100     # the mapped area
OUT = eub("rome.csv")

if os.path.exists(OUT) and "--force" not in sys.argv:
    print(f"cached: {OUT} ({os.path.getsize(OUT)/1e6:.1f} MB) -- --force to refetch")
    raise SystemExit(0)

try:
    import duckdb
except ImportError:
    print("fetch_eubucco.py needs duckdb:  pip install duckdb", file=sys.stderr)
    raise SystemExit(1)

con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")

# EUBUCCO geometry is EPSG:3035. Project the bbox corners into it once, then
# filter on raw coordinates -- a plain BETWEEN is what DuckDB can push down to
# the parquet's row-group statistics; a spatial predicate is not.
x0, y0, x1, y1 = con.execute(f"""
  SELECT ST_XMin(g), ST_YMin(g), ST_XMax(g), ST_YMax(g) FROM (
    SELECT ST_Transform(ST_MakeEnvelope({W},{S},{E},{N}),
                        'EPSG:4326','EPSG:3035', true) AS g)
""").fetchone()
print(f"bbox in EPSG:3035: {x0:.0f} {y0:.0f} {x1:.0f} {y1:.0f}")

t = time.time()
con.execute(f"""
COPY (
  SELECT height, height_source, floors, ST_X(c) AS lon, ST_Y(c) AS lat
  FROM (
    SELECT height, height_source, floors,
           ST_Transform(ST_Centroid(geometry), 'EPSG:3035','EPSG:4326', true) AS c
    FROM read_parquet('{URL}')
    WHERE ST_XMin(geometry) BETWEEN {x0} AND {x1}
      AND ST_YMin(geometry) BETWEEN {y0} AND {y1}
      AND height IS NOT NULL
  )
) TO '{OUT}' (HEADER, DELIMITER ',')
""")
print(f"wrote {OUT} in {time.time()-t:.0f}s")
for src, n in con.execute(
        f"SELECT height_source, count(*) FROM read_csv('{OUT}') GROUP BY 1 ORDER BY 2 DESC").fetchall():
    print(f"  {src:<18} {n:>7,}")
