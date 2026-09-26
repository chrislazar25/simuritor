"""Policy seam: decides every home's action each tick.

A policy sees the whole fleet at once (arrays, one entry per home), so a
model-backed policy can batch its calls. It only proposes: the sim enforces
physics afterwards, so a home without grid power always runs on `backup`
whatever the policy asked for.
"""

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from backend.data import Frame


@dataclass(frozen=True, slots=True)
class FleetView:
    """What a policy may look at this tick. Arrays are read-only, one entry per home."""

    soc: np.ndarray
    """State of charge, 0-1, at the start of the tick."""
    grid: np.ndarray
    """True where the home has grid power this tick."""
    capacity_kwh: np.ndarray
    household: np.ndarray
    reserve_floor: float
    """SoC below which the fleet never exports."""


@dataclass(frozen=True, slots=True)
class Decisions:
    """One entry per home."""

    action: np.ndarray
    """`Action` strings."""
    src: np.ndarray
    """`Source` strings: which tier of the decision stack decided."""
    conf: np.ndarray
    """Confidence 0-1; NaN where the tier has none (rules)."""


class Policy(Protocol):
    def decide(self, frame: Frame, fleet: FleetView) -> Decisions: ...


@dataclass(frozen=True, slots=True)
class NaivePolicy:
    """Price rules only (docs/slice-spec.md): sell high, buy low, otherwise hold."""

    discharge_at_usd: float = 1000.0
    """Discharge when the price is at least this, $/MWh..."""
    discharge_margin: float = 0.10
    """...and SoC is above reserve floor + this margin."""
    charge_at_usd: float = 30.0
    """Charge when the price is at most this, $/MWh..."""
    charge_below_soc: float = 0.90
    """...and SoC is below this."""

    def decide(self, frame: Frame, fleet: FleetView) -> Decisions:
        discharge = (frame.price >= self.discharge_at_usd) & (
            fleet.soc > fleet.reserve_floor + self.discharge_margin
        )
        charge = (frame.price <= self.charge_at_usd) & (fleet.soc < self.charge_below_soc)
        action = np.where(discharge, "discharge", np.where(charge, "charge", "hold"))
        n = len(fleet.soc)
        return Decisions(action=action, src=np.full(n, "rule"), conf=np.full(n, np.nan))
