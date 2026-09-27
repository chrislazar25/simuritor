# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "pyarrow", "openpyxl"]
# ///
"""Rebuild the real-time price files in data/ from ERCOT's raw report, one per scenario.

    uv run scripts/fetch_prices.py            # both
    uv run scripts/fetch_prices.py uri        # data/ercot_rtm_spp_uri_2021-02.parquet
    uv run scripts/fetch_prices.py normal     # data/ercot_rtm_spp_normal_2022-02.parquet

Source: ERCOT NP6-785-ER "Historical RTM Load Zone and Hub Prices", one file per year.
We read it directly rather than via gridstatus: gridstatus 0.36 drops the
`Settlement Point Type` column for this report, so each load zone's standard
(LZ) and energy-weighted (LZEW) prices both come out named e.g. `LZ_AEN`.
Here energy-weighted rows are kept but renamed `<zone>_EW`, so `LZ_AEN` is
one row per interval: the standard load-zone price.

Output columns match the other gridstatus-sourced files in data/.
"""

import argparse
import io
import json
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

DOC_LIST_URL = "https://www.ercot.com/misapp/servlets/IceDocListJsonWS?reportTypeId=13061"
DOWNLOAD_URL = "https://www.ercot.com/misdownload/servlets/mirDownload?doclookupId={}"
TZ = "US/Central"


@dataclass(frozen=True)
class Dataset:
    year: int
    sheet: str
    """The month's sheet in the year's workbook."""
    window: tuple[str, str]
    """[start, end) local time."""
    out: str

    @property
    def friendly_name(self) -> str:
        return f"RTMLZHBSPP_{self.year}"


DATASETS = {
    "uri": Dataset(2021, "Feb", ("2021-02-10", "2021-02-22"), "ercot_rtm_spp_uri_2021-02.parquet"),
    # The normal winter week (Feb 21-27, 2022; why in docs/notes.md), plus a day for the forecast edge.
    "normal": Dataset(2022, "Feb", ("2022-02-21", "2022-03-01"), "ercot_rtm_spp_normal_2022-02.parquet"),
}

LOCATION_TYPES = {
    "LZ": "Load Zone",
    "LZEW": "Load Zone Energy Weighted",
    "HU": "Trading Hub",
    "AH": "Trading Hub",  # HB_HUBAVG
    "SH": "Trading Hub",  # HB_BUSAVG
}


def download_report(friendly_name: str) -> bytes:
    with urllib.request.urlopen(DOC_LIST_URL) as resp:
        docs = json.load(resp)["ListDocsByRptTypeRes"]["DocumentList"]
    (doc,) = [d["Document"] for d in docs if d["Document"]["FriendlyName"] == friendly_name]
    print(f"downloading {doc['ConstructedName']} (published {doc['PublishDate']})")
    with urllib.request.urlopen(DOWNLOAD_URL.format(doc["DocID"])) as resp:
        return resp.read()


def tidy(raw: pd.DataFrame, window: tuple[str, str]) -> pd.DataFrame:
    if (raw["Repeated Hour Flag"] == "Y").any():
        raise ValueError("DST repeated hour in window; handle ambiguous times before using")

    # ERCOT uses hour-ending 1-24 and intervals 1-4 within the hour.
    start = (
        pd.to_datetime(raw["Delivery Date"], format="%m/%d/%Y")
        + pd.to_timedelta(raw["Delivery Hour"] - 1, unit="h")
        + pd.to_timedelta((raw["Delivery Interval"] - 1) * 15, unit="min")
    ).dt.tz_localize(TZ).dt.as_unit("ns")  # match the other files in data/

    kind = raw["Settlement Point Type"]
    unknown = set(kind) - set(LOCATION_TYPES)
    if unknown:
        raise ValueError(f"unmapped settlement point types: {unknown}")

    location = raw["Settlement Point Name"].where(kind != "LZEW", raw["Settlement Point Name"] + "_EW")
    df = pd.DataFrame(
        {
            "Time": start,
            "Interval Start": start,
            "Interval End": start + pd.Timedelta(minutes=15),
            "Location": location.astype("string"),
            "Location Type": kind.map(LOCATION_TYPES).astype("category"),
            "Market": "REAL_TIME_15_MIN",
            "SPP": raw["Settlement Point Price"].astype("float64"),
        }
    )
    lo, hi = (pd.Timestamp(t, tz=TZ) for t in window)
    df = df[(df["Interval Start"] >= lo) & (df["Interval Start"] < hi)]
    df = df.sort_values(["Interval Start", "Location"]).reset_index(drop=True)

    if df.duplicated(["Interval Start", "Location"]).any():
        raise ValueError("duplicate (Interval Start, Location) rows after tidying")
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("datasets", nargs="*", metavar="dataset", help=f"any of {', '.join(DATASETS)} (default: all)")
    keys = parser.parse_args().datasets or list(DATASETS)
    if unknown := set(keys) - set(DATASETS):
        parser.error(f"unknown dataset(s): {', '.join(sorted(unknown))}")
    for key in keys:
        dataset = DATASETS[key]
        with zipfile.ZipFile(io.BytesIO(download_report(dataset.friendly_name))) as zf:
            (name,) = zf.namelist()
            raw = pd.read_excel(zf.open(name), sheet_name=dataset.sheet)
        df = tidy(raw, dataset.window)
        out = ROOT / "data" / dataset.out
        df.to_parquet(out, index=False)
        print(f"wrote {out.relative_to(ROOT)}: {len(df)} rows, {df['Location'].nunique()} locations")


if __name__ == "__main__":
    main()
