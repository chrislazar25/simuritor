# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "pyarrow", "numpy"]
# ///
"""Rebuild data/austin_homes.parquet: residential building centroids in the fleet's bounding box.

    uv run scripts/fetch_homes.py

Source: OpenStreetMap via the Overpass API, one query. Data © OpenStreetMap contributors, ODbL
(https://www.openstreetmap.org/copyright): credit it wherever the map or the file is shown.

Austin's building footprints came in through a city import that tags almost every building
`building=yes`, so "residential" can't come from the building tag alone. A home here is a
building that is a house-like type (yes, house, detached, semidetached_house, bungalow, terrace),
has a house number (detached garages and sheds don't), and stands inside a `landuse=residential`
area. Capped at `CAP` homes, a seeded sample, so the committed file stays small.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "austin_homes.parquet"

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "Simuritor/0.1 (Base Power hackathon: home-battery fleet simulator; one-off fetch)"
BBOX = (30.15, -97.90, 30.45, -97.60)
"""South, west, north, east: `FleetConfig.lat_range` x `lon_range`."""
CAP = 50_000
SEED = 0
RETRY_WAIT_S = (60, 180)
"""Overpass answers 429/504 when it's busy: wait, then ask again (at most 3 tries in all)."""

QUERY = """
[out:json][timeout:180][bbox:{s},{w},{n},{e}];
(way["landuse"="residential"]; relation["landuse"="residential"];)->.res;
.res map_to_area->.zones;
way["building"~"^(yes|house|detached|semidetached_house|bungalow|terrace)$"]["addr:housenumber"](area.zones);
out ids center qt;
"""


def fetch() -> dict:
    s, w, n, e = BBOX
    body = urllib.parse.urlencode({"data": QUERY.format(s=s, w=w, n=n, e=e)}).encode()
    request = urllib.request.Request(OVERPASS_URL, data=body, headers={"User-Agent": USER_AGENT})
    for wait in (*RETRY_WAIT_S, None):
        try:
            with urllib.request.urlopen(request, timeout=240) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as err:
            if err.code not in (429, 504) or wait is None:
                raise
            print(f"Overpass busy (HTTP {err.code}); trying again in {wait} s")
            time.sleep(wait)
    raise AssertionError("unreachable")


def main() -> None:
    result = fetch()
    homes = pd.DataFrame(
        [(el["id"], el["center"]["lat"], el["center"]["lon"]) for el in result["elements"]],
        columns=["osm_id", "lat", "lon"],
    ).drop_duplicates("osm_id")
    found = len(homes)
    if found > CAP:
        keep = np.random.default_rng(SEED).choice(found, CAP, replace=False)
        homes = homes.iloc[np.sort(keep)]
    homes = homes.sort_values("osm_id").reset_index(drop=True)
    homes.attrs = {
        "source": "OpenStreetMap via Overpass API; © OpenStreetMap contributors, ODbL",
        "osm_base": result["osm3s"]["timestamp_osm_base"],
        "found": str(found),
    }
    homes.to_parquet(OUT, index=False)
    print(
        f"wrote {OUT.relative_to(ROOT)}: {len(homes)} of {found} homes "
        f"(OSM data as of {result['osm3s']['timestamp_osm_base']})"
    )


if __name__ == "__main__":
    main()
