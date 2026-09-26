"""Faults seam: things that happen to homes or infrastructure during a replay.

Tonight a fault can only take homes off the grid. Device, telemetry and model
failures add their own effects here when they arrive.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

import numpy as np

from backend.data import TZ


class Fault(Protocol):
    def grid_down(self, t: datetime) -> np.ndarray:
        """Bool per home: True where this fault cuts the home's grid power at `t`."""
        ...


@dataclass(frozen=True)
class FixedOutage:
    """A fixed share of homes, picked once at random, lose the grid for a fixed window."""

    n_homes: int
    rng: np.random.Generator
    share: float = 0.40
    start: datetime = datetime(2021, 2, 15, 2, 0, tzinfo=TZ)
    """⚠ Matches the ~10 GW ERCOT load drop 1-2am Feb 15 (docs/slice-spec.md)."""
    end: datetime = datetime(2021, 2, 18, 12, 0, tzinfo=TZ)
    """Exclusive. ⚠ Assumption, to verify."""
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
