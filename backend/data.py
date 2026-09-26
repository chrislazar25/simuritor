"""Data source seam: the outside world the sim replays, one `Frame` per 15-minute tick.

The sim core depends only on `Frame` and `DataSource`. Tonight's source reads the
Uri parquet files in `data/`; another crisis or a live feed is another `DataSource`.
"""

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from backend.schema import EEA

TZ = ZoneInfo("America/Chicago")
TICK = timedelta(minutes=15)


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
