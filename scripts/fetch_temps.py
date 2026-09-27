# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "pyarrow"]
# ///
"""Rebuild the hourly Austin temperature files in data/, one per scenario.

    uv run scripts/fetch_temps.py            # both
    uv run scripts/fetch_temps.py uri        # data/austin_temp_hourly_2021-02.parquet
    uv run scripts/fetch_temps.py normal     # data/austin_temp_hourly_2022-02.parquet

Source: Open-Meteo historical weather API (reanalysis), 2 m temperature at (30.27, -97.74),
central Austin. It reproduces the Uri file we started from exactly.
"""

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
URL = "https://archive-api.open-meteo.com/v1/archive"
LAT, LON = 30.27, -97.74
TZ = "America/Chicago"

DATASETS = {
    "uri": (("2021-02-10", "2021-02-21"), "austin_temp_hourly_2021-02.parquet"),
    # The normal winter week (Feb 21-27, 2022), plus a day so the last tick interpolates.
    "normal": (("2022-02-21", "2022-02-28"), "austin_temp_hourly_2022-02.parquet"),
}
"""Key -> ([first day, last day] inclusive, output file)."""


def fetch(first: str, last: str) -> pd.DataFrame:
    query = urllib.parse.urlencode(
        {
            "latitude": LAT,
            "longitude": LON,
            "start_date": first,
            "end_date": last,
            "hourly": "temperature_2m",
            "temperature_unit": "fahrenheit",
            "timezone": TZ,
        }
    )
    with urllib.request.urlopen(f"{URL}?{query}") as resp:
        hourly = json.load(resp)["hourly"]
    time = pd.to_datetime(hourly["time"]).tz_localize(TZ).as_unit("ns")
    return pd.DataFrame({"time": time, "temp_f": pd.Series(hourly["temperature_2m"], dtype="float64")})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("datasets", nargs="*", metavar="dataset", help=f"any of {', '.join(DATASETS)} (default: all)")
    keys = parser.parse_args().datasets or list(DATASETS)
    if unknown := set(keys) - set(DATASETS):
        parser.error(f"unknown dataset(s): {', '.join(sorted(unknown))}")
    for key in keys:
        (first, last), name = DATASETS[key]
        df = fetch(first, last)
        if df["temp_f"].isna().any():
            raise ValueError(f"{key}: {df['temp_f'].isna().sum()} missing hours")
        out = ROOT / "data" / name
        df.to_parquet(out, index=False)
        print(f"wrote {out.relative_to(ROOT)}: {len(df)} hours, {df['temp_f'].min()}-{df['temp_f'].max()} °F")


if __name__ == "__main__":
    main()
