"""Failover: covering homes that drop out of a utility call, on a timeline in seconds inside one tick.

The sim ticks every 15 min, but a promise is kept or missed second by second
(docs/dispatch-design.md, "Failover"). Each tick some homes stop exporting at a second
of the tick: a device fault, a battery about to hit its floor, a home about to lose the
grid. When a home with a call share drops out, the controller notices (at once if the
home warned, after missed heartbeats if not), then reassigns the share to the healthy homes
with the most spare power and energy first, so as few homes as possible take it. What they
can't take stays uncovered to the end of the tick.

Pure: arrays in, arrays out; the caller passes the random generator.
"""

from dataclasses import dataclass

import numpy as np

from backend.data import TICK

TICK_S = TICK.total_seconds()
"""900."""
SLACK_KW = 1e-9
"""Cover this close to the lost share counts as full (float sums)."""
SLACK_KWH = 1e-9
"""An export this close to the floor room doesn't count as hitting the floor (float sums)."""


@dataclass(frozen=True, slots=True)
class FailoverConfig:
    heartbeat_s: float = 2.0
    """ADER real-time telemetry interval."""
    missed_heartbeats: int = 3
    """A silent home is declared out after this many missed heartbeats."""
    reassign_s: float = 5.0
    """⚠ From detection to healthy homes exporting the cover."""
    outage_notice_frac: float = 0.5
    """⚠ Share of homes about to lose the grid that warn first; the rest drop out silently."""

    def cover_delay_s(self, warned: bool) -> float:
        """Seconds from drop-out to cover: detection (0 s if warned), then reassignment."""
        return (0.0 if warned else self.heartbeat_s * self.missed_heartbeats) + self.reassign_s


@dataclass(frozen=True, slots=True)
class DropOuts:
    """Who stops exporting this tick, and when. One entry per home."""

    at_s: np.ndarray
    """Second of the tick the home stops exporting; `TICK_S` where it exports the whole tick."""
    warned: np.ndarray
    """True where the home announced it (floor ahead, outage notice); False where it went silent."""


@dataclass(frozen=True, slots=True)
class Failover:
    """One home with a call share dropping out, and how the fleet covered it."""

    home: int
    """Index into the fleet."""
    warned: bool
    at_s: float
    cover_s: float | None
    """Seconds from drop-out to full cover; None when the share wasn't fully covered."""
    covered_by: int
    """Homes that took part of the share."""
    uncovered_kwh: float
    """Share energy not delivered: lost kW x uncovered seconds (before cover, and what cover couldn't take)."""


@dataclass(frozen=True, slots=True)
class Timeline:
    exported_kwh: np.ndarray
    """Per home, this tick: its own export up to its drop-out, plus any cover it took."""
    cover_kwh: np.ndarray
    """The part of `exported_kwh` that covered other homes."""
    failovers: list[Failover]
    """In drop-out order."""


def drop_outs(
    export_kw: np.ndarray,
    floor_room_kwh: np.ndarray,
    share_kw: np.ndarray,
    outage_next: np.ndarray,
    fault_at_s: np.ndarray,
    rng: np.random.Generator,
    config: FailoverConfig = FailoverConfig(),
) -> DropOuts:
    """The earliest reason each home stops exporting this tick:

    - a device fault at `fault_at_s` (NaN: none), any home: silent;
    - its export at `export_kw` would reach its floor (`floor_room_kwh` from now) mid-tick: warned,
      at the second it gets there;
    - it has a call share and loses the grid next tick (`outage_next`): at a random second,
      warned with probability `outage_notice_frac`, else silent.

    Draws the same amount of randomness every tick, so one tick's events don't reshuffle the next.
    """
    n = len(export_kw)
    random_s = rng.uniform(0.0, TICK_S, n)
    notice = rng.random(n) < config.outage_notice_frac
    hits = floor_room_kwh < export_kw * TICK_S / 3600 - SLACK_KWH
    floor_s = np.where(hits, floor_room_kwh / np.where(hits, export_kw, 1.0) * 3600, np.inf)
    reasons = np.stack(
        [
            np.nan_to_num(fault_at_s, nan=np.inf),
            floor_s,
            np.where((share_kw > 0) & outage_next, random_s, np.inf),
        ]
    )
    warned_if = np.stack([np.zeros(n, dtype=bool), np.ones(n, dtype=bool), notice])
    first = reasons.argmin(axis=0)
    at_s = np.minimum(reasons.min(axis=0), TICK_S)
    return DropOuts(at_s=at_s, warned=warned_if[first, np.arange(n)] & (at_s < TICK_S))


def run_tick(
    drops: DropOuts,
    export_kw: np.ndarray,
    share_kw: np.ndarray,
    spare_kwh: np.ndarray,
    can_cover: np.ndarray,
    max_kw: float,
    config: FailoverConfig = FailoverConfig(),
) -> Timeline:
    """Play one tick second by second.

    Every home exports `export_kw` until its drop-out. Each drop-out of a home with a call share
    (`share_kw`, part of `export_kw`) is covered `cover_delay_s` later by the homes in `can_cover`
    that don't drop out themselves this tick, most spare first (`greedy`), for the rest of the tick:
    spare power is max kW minus their export and the cover they already took; spare energy is
    `spare_kwh` (above their floor after their own export) minus the cover they already gave.
    Cover can be partial; the rest of the share stays uncovered to the end of the tick.
    A cover due at or after the tick's end has nothing left to cover in this tick (next tick's plan
    takes over), so only power limits it.
    """
    exported = export_kw * drops.at_s / 3600
    healthy = can_cover & (drops.at_s >= TICK_S)
    power = np.where(healthy, np.maximum(max_kw - export_kw, 0.0), 0.0)
    energy = np.where(healthy, np.maximum(spare_kwh, 0.0), 0.0)
    cover = np.zeros(len(export_kw))
    failovers = []
    dropped = np.flatnonzero((share_kw > 0) & (drops.at_s < TICK_S))
    for home in dropped[np.argsort(drops.at_s[dropped], kind="stable")]:
        lost_kw, at_s, warned = float(share_kw[home]), float(drops.at_s[home]), bool(drops.warned[home])
        delay_s = config.cover_delay_s(warned)
        start_s = min(at_s + delay_s, TICK_S)
        left_h = (TICK_S - start_s) / 3600
        spare_kw = power if left_h == 0 else np.minimum(power, energy / left_h)
        take = greedy(lost_kw, spare_kw)
        power -= take
        energy -= take * left_h
        cover += take * left_h
        covered_kw = float(take.sum())
        full = covered_kw >= lost_kw - SLACK_KW
        failovers.append(
            Failover(
                home=int(home),
                warned=warned,
                at_s=at_s,
                cover_s=delay_s if full else None,
                covered_by=int((take > 0).sum()),
                uncovered_kwh=lost_kw * (start_s - at_s) / 3600 + max(lost_kw - covered_kw, 0.0) * left_h,
            )
        )
    return Timeline(exported_kwh=exported + cover, cover_kwh=cover, failovers=failovers)


def greedy(total: float, spare: np.ndarray) -> np.ndarray:
    """Take `total` from the entries with the most `spare` first (ties: lowest index), none
    above its spare: the fewest entries that can cover it. Sums to less only when spare runs out."""
    take = np.zeros(len(spare))
    left = total
    for k in np.argsort(-spare, kind="stable"):
        if left <= 0 or spare[k] <= 0:
            break
        take[k] = min(spare[k], left)
        left -= take[k]
    return take
