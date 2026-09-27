"""Data source seam: the outside world the sim replays, one `Frame` per 15-minute tick.

The sim core depends only on `Frame` and `DataSource`. Tonight's source reads the
Uri parquet files in `data/`; another crisis or a live feed is another `DataSource`.
"""

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

import pandas as pd

from backend.schema import EEA

TZ = ZoneInfo("America/Chicago")
TICK = timedelta(minutes=15)
HOURS_PER_TICK = TICK / timedelta(hours=1)  # 0.25
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True, slots=True)
class Frame:
    i: int
    """Tick index, 0 at the start of the requested window."""
    t: datetime
    """Interval start, tz-aware America/Chicago."""
    price: float
    """Real-time price, $/MWh. Can be negative."""
    temp_f: float
    eea: EEA


class DataSource(Protocol):
    def frames(self, start: datetime, end: datetime) -> list[Frame]:
        """One frame per 15-minute interval in [start, end). Raises rather than fill a gap."""
        ...


# ERCOT Energy Emergency Alert levels during Uri: (time the level took effect, level).
# Normal before the first entry. ERCOT itself calls these times approximate.
# Sources:
#   [UT]    UT Austin Energy Institute, "The Timeline and Events of the February 2021 Texas
#           Electric Grid Blackouts" (2021), p. 26 and p. 37.
#           https://energy.utexas.edu/sites/default/files/UTAustin%20(2021)%20EventsFebruary2021TexasBlackout.pdf
#   [ERCOT] ERCOT, "Review of February 2021 Extreme Cold Weather Event", Board presentation,
#           2021-02-24, slide 16. https://www.ercot.com/files/docs/2021/02/24/2.2_REVISED_ERCOT_Presentation.pdf
EEA_TIMELINE: tuple[tuple[datetime, EEA], ...] = (
    (datetime(2021, 2, 15, 0, 15, tzinfo=TZ), "EEA1"),  # [UT] p. 26
    (datetime(2021, 2, 15, 1, 7, tzinfo=TZ), "EEA2"),  # [UT] p. 26
    # ⚠ [UT] gives 01:20 on p. 26 and 01:25 (with firm load shed) on p. 37. Either way the
    # 01:15 interval starts in EEA2 and 01:30 in EEA3, so the replay doesn't change.
    (datetime(2021, 2, 15, 1, 25, tzinfo=TZ), "EEA3"),
    (datetime(2021, 2, 19, 9, 0, tzinfo=TZ), "EEA2"),  # [ERCOT] "9 a.m."
    (datetime(2021, 2, 19, 10, 0, tzinfo=TZ), "EEA1"),  # [ERCOT] "10 a.m."
    (datetime(2021, 2, 19, 10, 35, tzinfo=TZ), "Normal"),  # [ERCOT] 10:35; [UT] says 10:36
)


def eea_at(t: datetime) -> EEA:
    """The EEA level in effect at `t` (an interval takes the level in effect at its start)."""
    k = bisect_right([when for when, _ in EEA_TIMELINE], t)
    return EEA_TIMELINE[k - 1][1] if k else "Normal"


class UriParquetSource:
    """Winter Storm Uri from the parquet files in `data/`: Austin prices and temperature, ERCOT EEA levels."""

    PRICE_FILE = "ercot_rtm_spp_uri_2021-02.parquet"
    TEMP_FILE = "austin_temp_hourly_2021-02.parquet"
    # The standard load-zone price, not the energy-weighted `LZ_AEN_EW` (docs/notes.md).
    LOCATION = "LZ_AEN"
    LOCATION_TYPE = "Load Zone"

    DEFAULT_START = datetime(2021, 2, 10, tzinfo=TZ)
    """Three pre-storm days before prices spike on Feb 13 (the insight experiment compares them)."""
    DEFAULT_END = datetime(2021, 2, 20, tzinfo=TZ)
    PRE_STORM = (DEFAULT_START, datetime(2021, 2, 13, tzinfo=TZ))
    """[start, end) of the insight experiment's pre-storm window."""
    STORM = (datetime(2021, 2, 14, tzinfo=TZ), datetime(2021, 2, 19, tzinfo=TZ))
    """[start, end) of its storm window."""

    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self.data_dir = data_dir

    def frames(self, start: datetime = DEFAULT_START, end: datetime = DEFAULT_END) -> list[Frame]:
        grid = tick_grid(start, end)
        price = self._prices().reindex(grid)
        require_complete(price, "price")
        temp = self._temps(grid)
        require_complete(temp, "temperature")
        return [
            Frame(i=i, t=t.to_pydatetime(), price=float(p), temp_f=float(f), eea=eea_at(t))
            for i, (t, p, f) in enumerate(zip(grid, price, temp, strict=True))
        ]

    def _prices(self) -> pd.Series:
        df = pd.read_parquet(self.data_dir / self.PRICE_FILE)
        df = df[(df["Location"] == self.LOCATION) & (df["Location Type"] == self.LOCATION_TYPE)]
        prices = df.set_index(df["Interval Start"].dt.tz_convert(TZ))["SPP"]
        if not prices.index.is_unique:
            raise ValueError(f"duplicate {self.LOCATION} price intervals in {self.PRICE_FILE}")
        return prices

    def _temps(self, grid: pd.DatetimeIndex) -> pd.Series:
        """Hourly readings, linearly interpolated onto the 15-minute grid.

        Every hour spanning the grid must be present, so interpolation never bridges a gap.
        """
        df = pd.read_parquet(self.data_dir / self.TEMP_FILE)
        hourly = df.set_index(df["time"].dt.tz_convert(TZ))["temp_f"]
        if not hourly.index.is_unique:
            raise ValueError(f"duplicate hours in {self.TEMP_FILE}")
        hours = pd.date_range(grid[0].floor("h"), grid[-1].ceil("h"), freq="h")
        hourly = hourly.reindex(hours)
        require_complete(hourly, "hourly temperature")
        return hourly.reindex(hours.union(grid)).interpolate(method="time").reindex(grid)


def tick_grid(start: datetime, end: datetime) -> pd.DatetimeIndex:
    """Interval starts in [start, end), 15 minutes apart. Both ends must be tz-aware and on the grid."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be tz-aware")
    if not start < end:
        raise ValueError(f"empty window: {start} to {end}")
    for when in (start, end):
        if when.minute % 15 or when.second or when.microsecond:
            raise ValueError(f"{when} is not on the 15-minute grid")
    return pd.date_range(start.astimezone(TZ), end.astimezone(TZ), freq=TICK, inclusive="left")


def require_complete(series: pd.Series, what: str) -> None:
    """Fail loudly on missing values; the sim never replays invented data."""
    missing = series.index[series.isna()]
    if len(missing):
        raise ValueError(f"{what}: {len(missing)} missing interval(s), first at {missing[0]}")
