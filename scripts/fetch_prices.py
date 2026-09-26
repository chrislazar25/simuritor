# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "pyarrow", "openpyxl"]
# ///
"""Rebuild data/ercot_rtm_spp_uri_2021-02.parquet from ERCOT's raw report.

    uv run scripts/fetch_prices.py

Source: ERCOT NP6-785-ER "Historical RTM Load Zone and Hub Prices", 2021 file.
We read it directly rather than via gridstatus: gridstatus 0.36 drops the
`Settlement Point Type` column for this report, so each load zone's standard
(LZ) and energy-weighted (LZEW) prices both come out named e.g. `LZ_AEN`.
Here energy-weighted rows are kept but renamed `<zone>_EW`, so `LZ_AEN` is
one row per interval: the standard load-zone price.

Output columns match the other gridstatus-sourced files in data/.
"""

import io
import json
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "ercot_rtm_spp_uri_2021-02.parquet"

DOC_LIST_URL = "https://www.ercot.com/misapp/servlets/IceDocListJsonWS?reportTypeId=13061"
DOWNLOAD_URL = "https://www.ercot.com/misdownload/servlets/mirDownload?doclookupId={}"
FRIENDLY_NAME = "RTMLZHBSPP_2021"
SHEET = "Feb"
WINDOW = ("2021-02-10", "2021-02-22")  # [start, end) local time
TZ = "US/Central"

LOCATION_TYPES = {
    "LZ": "Load Zone",
    "LZEW": "Load Zone Energy Weighted",
    "HU": "Trading Hub",
    "AH": "Trading Hub",  # HB_HUBAVG
    "SH": "Trading Hub",  # HB_BUSAVG
}


def download_report() -> bytes:
    with urllib.request.urlopen(DOC_LIST_URL) as resp:
        docs = json.load(resp)["ListDocsByRptTypeRes"]["DocumentList"]
    (doc,) = [d["Document"] for d in docs if d["Document"]["FriendlyName"] == FRIENDLY_NAME]
    print(f"downloading {doc['ConstructedName']} (published {doc['PublishDate']})")
    with urllib.request.urlopen(DOWNLOAD_URL.format(doc["DocID"])) as resp:
        return resp.read()


def tidy(raw: pd.DataFrame) -> pd.DataFrame:
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
    lo, hi = (pd.Timestamp(t, tz=TZ) for t in WINDOW)
    df = df[(df["Interval Start"] >= lo) & (df["Interval Start"] < hi)]
    df = df.sort_values(["Interval Start", "Location"]).reset_index(drop=True)

    if df.duplicated(["Interval Start", "Location"]).any():
        raise ValueError("duplicate (Interval Start, Location) rows after tidying")
    return df


def main() -> None:
    with zipfile.ZipFile(io.BytesIO(download_report())) as zf:
        (name,) = zf.namelist()
        raw = pd.read_excel(zf.open(name), sheet_name=SHEET)
    df = tidy(raw)
    df.to_parquet(OUT, index=False)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(df)} rows, {df['Location'].nunique()} locations")


if __name__ == "__main__":
    main()
