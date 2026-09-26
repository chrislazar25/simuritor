"""Commitment source seam: what the fleet has promised the utility, tick by tick.

Tonight's source is `UtilityContract` (docs/dispatch-design.md, "Utility contract"): a
capacity contract the utility calls when the price spikes. The sim asks it once per tick,
holds the fleet to the answer (penalties) and shows it to the policy in `FleetView`.
"""

from dataclasses import dataclass, field
from typing import Protocol

from backend.data import HOURS_PER_TICK, Frame

HOURS_PER_WEEK = 168.0


@dataclass(frozen=True, slots=True)
class Commitment:
    """What the fleet owes the utility this tick."""

    call: bool
    """True while the utility has called the contract."""
    promised_mw: float
    """MW to deliver this tick; 0 outside calls."""
    ticks_left: int
    """Call ticks still to come, this one included, if the call runs to its limit; 0 outside calls."""
    contract_mw: float
    """What the next call will ask for, called or not."""
    max_call_ticks: int
    """The longest a call can run."""
    buffer_frac: float
    """Spare each home keeps on top of its call share, as a fraction of the share, for failover."""
    capacity_usd: float
    """Capacity payment earned this tick, called or not."""


class CommitmentSource(Protocol):
    def commit(self, frame: Frame) -> Commitment:
        """The commitment for `frame`. Called once per tick, in order."""
        ...


@dataclass
class UtilityContract:
    """A capacity contract, called when the price spikes. Stateful: one per replay.

    A call starts when the price reaches `trigger_usd` and lasts while it stays there, for at
    most `max_call_ticks`; then there's no call for `cooldown_ticks`, however high the price.
    """

    nameplate_mw: float
    """Fleet nameplate power: homes x max kW."""
    size_frac: float = 0.6
    """⚠ Contract size as a share of nameplate: the knob the insight sweep turns."""
    trigger_usd: float = 1000.0
    """Call when the price is at least this, $/MWh."""
    max_call_ticks: int = 6
    """1.5 h."""
    cooldown_ticks: int = 8
    """2 h."""
    capacity_usd_per_mw_week: float = 2000.0
    """⚠ Placeholder (≈ $100/kW-yr); Base's contract rates aren't public."""
    buffer_frac: float = 0.2
    """⚠ Failover spare per home, as a fraction of its call share."""
    _run: int = field(default=0, init=False, repr=False)
    """Ticks into the current call; 0 when there's none."""
    _cooldown: int = field(default=0, init=False, repr=False)
    """Cooldown ticks still to go."""

    @property
    def size_mw(self) -> float:
        return self.size_frac * self.nameplate_mw

    def commit(self, frame: Frame) -> Commitment:
        capacity_usd = self.capacity_usd_per_mw_week * self.size_mw * HOURS_PER_TICK / HOURS_PER_WEEK
        idle = Commitment(
            call=False,
            promised_mw=0.0,
            ticks_left=0,
            contract_mw=self.size_mw,
            max_call_ticks=self.max_call_ticks,
            buffer_frac=self.buffer_frac,
            capacity_usd=capacity_usd,
        )
        if self._cooldown:
            self._cooldown -= 1
            return idle
        if frame.price < self.trigger_usd:
            if self._run:  # the call ended early; this tick is the first of the cooldown
                self._run, self._cooldown = 0, max(0, self.cooldown_ticks - 1)
            return idle
        self._run += 1
        ticks_left = self.max_call_ticks - self._run + 1
        if ticks_left == 1:
            self._run, self._cooldown = 0, self.cooldown_ticks
        return Commitment(
            call=True,
            promised_mw=self.size_mw,
            ticks_left=ticks_left,
            contract_mw=self.size_mw,
            max_call_ticks=self.max_call_ticks,
            buffer_frac=self.buffer_frac,
            capacity_usd=capacity_usd,
        )
