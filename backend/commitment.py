"""Commitment source seam: what the fleet has promised the utility, tick by tick.

Tonight's source is `UtilityContract` (docs/dispatch-design.md, "Utility contract"): a
capacity contract the utility calls when the price spikes. The sim asks it once per tick,
holds the fleet to the answer (penalties) and shows it to the policy in `FleetView`.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
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
    def commit(self, frame: Frame, forecast_min_f: Callable[[float], float]) -> Commitment:
        """The commitment for `frame`. Called once per tick, in order.

        `forecast_min_f(hours)`: the coldest forecast temperature over the next `hours`, °F.
        """
        ...


@dataclass
class UtilityContract:
    """A capacity contract, called when the price spikes. Stateful: one per replay.

    A call starts when the price reaches `trigger_usd` inside the daily call window, if the day
    (Central time) has a call left, and lasts while the price stays there and the window is open,
    for at most `max_call_ticks`; then there's no call for `cooldown_ticks`, however high the price.
    Shaped on residential battery programmes (docs/dispatch-design.md, "Assumptions and sources").
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
    max_calls_per_day: int = 1
    """Calls that may start per Central-time day (GVEC: one event per day on average)."""
    window_start_hour: int = 6
    window_end_hour: int = 22
    """Calls only in [06:00, 22:00) Central time (Austin Energy); a call still running at 22:00 ends."""
    skip_before_storm: bool = False
    """No call while the next `storm_hours` forecast goes below `storm_below_f` (Austin Energy:
    typically no events when a severe storm is forecast, so batteries stay full for backup)."""
    storm_hours: float = 24.0
    storm_below_f: float = 20.0
    emergency_uncapped: bool = False
    """The stress case: during an EEA a call may start whatever `max_calls_per_day` says, and
    doesn't count against it (Austin Energy's event limit excludes grid emergencies)."""
    _run: int = field(default=0, init=False, repr=False)
    """Ticks into the current call; 0 when there's none."""
    _cooldown: int = field(default=0, init=False, repr=False)
    """Cooldown ticks still to go."""
    _day: date | None = field(default=None, init=False, repr=False)
    _calls_today: int = field(default=0, init=False, repr=False)
    """Calls started on `_day` that count against `max_calls_per_day`."""

    @property
    def size_mw(self) -> float:
        return self.size_frac * self.nameplate_mw

    def commit(self, frame: Frame, forecast_min_f: Callable[[float], float]) -> Commitment:
        if frame.t.date() != self._day:
            self._day, self._calls_today = frame.t.date(), 0
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
        if not self._callable(frame, forecast_min_f):
            if self._run:  # the call ended early; this tick is the first of the cooldown
                self._run, self._cooldown = 0, max(0, self.cooldown_ticks - 1)
            return idle
        if not self._run:  # a new call
            emergency = self.emergency_uncapped and frame.eea != "Normal"
            if not emergency:
                if self._calls_today >= self.max_calls_per_day:
                    return idle
                self._calls_today += 1
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

    def _callable(self, frame: Frame, forecast_min_f: Callable[[float], float]) -> bool:
        """Whether this tick can be part of a call, before the daily limit."""
        if frame.price < self.trigger_usd:
            return False
        if not self.window_start_hour <= frame.t.hour < self.window_end_hour:
            return False
        return not (self.skip_before_storm and forecast_min_f(self.storm_hours) < self.storm_below_f)
