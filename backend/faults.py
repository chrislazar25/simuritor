"""Faults seam: things that happen to homes or infrastructure during a replay.

Tonight a fault can only take homes off the grid. Device, telemetry and model
failures add their own effects here when they arrive.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

import numpy as np

from backend.data import TZ

OUTAGE_START = datetime(2021, 2, 15, 2, 0, tzinfo=TZ)
"""⚠ Matches the ~10 GW ERCOT load drop 1-2am Feb 15 (docs/slice-spec.md)."""
OUTAGE_END = datetime(2021, 2, 18, 12, 0, tzinfo=TZ)
"""Exclusive. ⚠ Assumption, to verify."""


class Fault(Protocol):
    def grid_down(self, t: datetime) -> np.ndarray:
        """Bool per home: True where this fault cuts the home's grid power at `t`."""
        ...


@dataclass(frozen=True)
class RollingOutage:
    """Rotating outages over one window, plus a share of homes that are never restored.

    Homes are split (seeded) into `never_restored_share` of the fleet, out for the whole
    window, and `n_groups` rotation groups for the rest. Each group cycles `off_hours` off,
    `on_hours` on, with the groups' cycles staggered evenly. With the defaults (4 h off of a
    10 h cycle, 5 groups 2 h apart) exactly 2 groups, i.e. 40% of rotating homes, are out
    at any moment; with the never-restored 10% that's 46% of the fleet.

    ⚠ Assumption (docs/notes.md): ERCOT intended short rotations, but many circuits stayed
    out for days. The never-restored share is that second case, where reserve policy matters most.
    """

    n_homes: int
    rng: np.random.Generator
    off_hours: float = 4.0
    on_hours: float = 6.0
    n_groups: int = 5
    never_restored_share: float = 0.10
    start: datetime = OUTAGE_START
    end: datetime = OUTAGE_END
    group: np.ndarray = field(init=False)
    """Rotation group per home, 0 to n_groups - 1; -1 for never restored."""

    def __post_init__(self) -> None:
        order = self.rng.permutation(self.n_homes)
        n_never = round(self.never_restored_share * self.n_homes)
        group = np.full(self.n_homes, -1)
        group[order[n_never:]] = np.arange(self.n_homes - n_never) % self.n_groups
        group.setflags(write=False)
        object.__setattr__(self, "group", group)

    def grid_down(self, t: datetime) -> np.ndarray:
        if not self.start <= t < self.end:
            return np.zeros(self.n_homes, dtype=bool)
        cycle = self.off_hours + self.on_hours
        elapsed = (t - self.start) / timedelta(hours=1)
        # Each group's cycle starts `cycle / n_groups` hours after the previous group's.
        phase = (elapsed - self.group * cycle / self.n_groups) % cycle
        return (self.group < 0) | (phase < self.off_hours)


@dataclass(frozen=True)
class FixedOutage:
    """A fixed share of homes, picked once at random, lose the grid for the whole window. Used in tests."""

    n_homes: int
    rng: np.random.Generator
    share: float = 0.40
    start: datetime = OUTAGE_START
    end: datetime = OUTAGE_END
    homes: np.ndarray = field(init=False)
    """Bool per home: True for the homes this outage hits."""

    def __post_init__(self) -> None:
        hit = np.zeros(self.n_homes, dtype=bool)
        hit[self.rng.choice(self.n_homes, size=round(self.share * self.n_homes), replace=False)] = True
        hit.setflags(write=False)
        object.__setattr__(self, "homes", hit)

    def grid_down(self, t: datetime) -> np.ndarray:
        if self.start <= t < self.end:
            return self.homes
        return np.zeros(self.n_homes, dtype=bool)
