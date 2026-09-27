"""Faults / chaos seam: things that happen to homes or infrastructure during a replay.

Two kinds: grid faults (`Fault`) take homes off the grid; device faults (`DeviceFaults`)
stop a home's battery from discharging, without warning. Telemetry and model failures
add their own effects here when they arrive.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

import numpy as np

from backend.data import HOURS_PER_TICK, TICK, TZ

OUTAGE_START = datetime(2021, 2, 15, 2, 0, tzinfo=TZ)
"""⚠ Matches the ~10 GW ERCOT load drop 1-2am Feb 15 (see docs/dispatch-design.md)."""
OUTAGE_END = datetime(2021, 2, 18, 12, 0, tzinfo=TZ)
"""Exclusive. ⚠ Assumption, to verify."""


def feeders(lat: np.ndarray, lon: np.ndarray, k: int, rng: np.random.Generator, max_iter: int = 100) -> np.ndarray:
    """Each home's feeder, 0 to k - 1: seeded k-means on position (k-means++ start).

    ⚠ A stand-in for the real distribution network: homes near each other share a feeder, so an
    outage takes out a neighbourhood. Distances in degrees, longitude scaled by cos(latitude).
    """
    points = np.column_stack([lon * math.cos(math.radians(float(lat.mean()))), lat])
    n, k = len(points), min(k, len(points))
    centers = np.empty((k, 2))
    centers[0] = points[rng.integers(n)]
    nearest = ((points - centers[0]) ** 2).sum(axis=1)
    for j in range(1, k):
        pick = rng.choice(n, p=nearest / nearest.sum()) if nearest.sum() > 0 else rng.integers(n)
        centers[j] = points[pick]
        nearest = np.minimum(nearest, ((points - centers[j]) ** 2).sum(axis=1))
    label = np.full(n, -1)
    for _ in range(max_iter):
        new = ((points[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2).argmin(axis=1)
        if np.array_equal(new, label):
            break
        label = new
        for j in range(k):
            members = points[label == j]
            if len(members):
                centers[j] = members.mean(axis=0)
    return label


class Fault(Protocol):
    def grid_down(self, t: datetime) -> np.ndarray:
        """Bool per home: True where this fault cuts the home's grid power at `t`.

        A function of `t` alone: the sim also asks about the next tick, to warn homes ahead.
        """
        ...


@dataclass(frozen=True, slots=True)
class DeviceTick:
    """Device faults for one tick. One entry per home."""

    out: np.ndarray
    """True where a fault from an earlier tick is still out. Known (its heartbeats stopped): the
    policy sees it, and the home can't discharge this tick."""
    fails_at_s: np.ndarray
    """Second of this tick at which a new fault stops the home; NaN where none. Silent: nobody
    knows until the heartbeats are missed."""


class DeviceFaults(Protocol):
    def tick(self) -> DeviceTick:
        """The next tick's device faults. Called once per tick, in order."""
        ...


@dataclass
class SilentDeviceFaults:
    """Chaos: inverter faults, comms blips and reboots that stop a battery without warning.

    Each home faults at `rate_per_home_hour` (seeded), at a uniform random second of the tick.
    A fault is transient with probability `transient_frac` (a comms blip or reboot: back next
    tick), else hard (out for the rest of the replay: no truck rolls in an ice storm). A faulted
    home can't discharge while out; it still backs up its own house (the local controller runs on).
    """

    n_homes: int
    rng: np.random.Generator
    rate_per_home_hour: float = 0.001
    """⚠ Our guess; configurable (`run_replay --fault-rate`)."""
    transient_frac: float = 0.8
    """⚠ Our guess: the rest are hard faults."""
    hard: np.ndarray = field(init=False, repr=False)
    """True where a hard fault has taken the home out for good."""

    def __post_init__(self) -> None:
        self.hard = np.zeros(self.n_homes, dtype=bool)

    def tick(self) -> DeviceTick:
        n = self.n_homes
        out = self.hard.copy()
        out.setflags(write=False)
        new = (self.rng.random(n) < -math.expm1(-self.rate_per_home_hour * HOURS_PER_TICK)) & ~out
        at_s = np.where(new, self.rng.uniform(0.0, TICK.total_seconds(), n), np.nan)
        self.hard = self.hard | (new & (self.rng.random(n) >= self.transient_frac))
        at_s.setflags(write=False)
        return DeviceTick(out=out, fails_at_s=at_s)


@dataclass(frozen=True)
class RollingOutage:
    """Rotating outages over one window, plus a share of homes that are never restored.

    Utilities shed load a feeder at a time, so whole feeders (neighbourhoods, `feeders`) move
    together. A seeded random order of feeders fills the never-restored set first, out for the
    whole window, stopping at the total closest to `never_restored_share` of the fleet. The other
    feeders go to `n_groups` rotation groups, largest first, each to the group with the fewest homes
    so far. Each group cycles `off_hours` off, `on_hours` on. The groups' cycles are staggered
    evenly (5 groups: 2 h apart), then each is shifted by a seeded offset of 0 to
    `max_offset_ticks` whole ticks, so cuts land on varied quarter hours, not all on the hour.
    Over a cycle 40% of rotating homes are out (2 of 5 groups; ~46% of the fleet with the
    never-restored ~10%); at a given moment 1 to 3 groups.
    Groups are only roughly equal, because feeders are whole.

    ⚠ Assumption (docs/notes.md): ERCOT intended short rotations, but many circuits stayed
    out for days. The never-restored share is that second case, where reserve policy matters most.
    """

    feeder: np.ndarray
    """Each home's feeder (`feeders`)."""
    rng: np.random.Generator
    off_hours: float = 4.0
    on_hours: float = 6.0
    n_groups: int = 5
    never_restored_share: float = 0.10
    max_offset_ticks: int = 7
    """⚠ Each group's cycle starts 0 to this many ticks after its even stagger."""
    start: datetime = OUTAGE_START
    end: datetime = OUTAGE_END
    feeder_group: np.ndarray = field(init=False)
    """Rotation group per feeder, 0 to n_groups - 1; -1 for never restored."""
    group: np.ndarray = field(init=False)
    """Rotation group per home: its feeder's."""
    offset_ticks: np.ndarray = field(init=False)
    """Per group: whole ticks its cycle is shifted by."""

    def __post_init__(self) -> None:
        size = np.bincount(self.feeder)
        order = self.rng.permutation(len(size))
        total = np.concatenate([[0], np.cumsum(size[order])])
        n_never = int(np.abs(total - self.never_restored_share * len(self.feeder)).argmin())
        feeder_group = np.full(len(size), -1)
        homes = np.zeros(self.n_groups, dtype=int)
        rest = order[n_never:]
        for f in rest[np.argsort(-size[rest], kind="stable")]:
            g = int(homes.argmin())
            feeder_group[f] = g
            homes[g] += size[f]
        group = feeder_group[self.feeder]
        for a in (feeder_group, group):
            a.setflags(write=False)
        object.__setattr__(self, "feeder_group", feeder_group)
        object.__setattr__(self, "group", group)
        # Drawn after the groups, so adding offsets left the group split unchanged.
        offset = self.rng.integers(0, self.max_offset_ticks + 1, self.n_groups)
        offset.setflags(write=False)
        object.__setattr__(self, "offset_ticks", offset)

    @property
    def n_homes(self) -> int:
        return len(self.feeder)

    def grid_down(self, t: datetime) -> np.ndarray:
        if not self.start <= t < self.end:
            return np.zeros(self.n_homes, dtype=bool)
        cycle = self.off_hours + self.on_hours
        elapsed = (t - self.start) / timedelta(hours=1)
        # Each group's cycle starts `cycle / n_groups` hours after the previous group's, plus its offset.
        offset = np.where(self.group >= 0, self.offset_ticks[self.group], 0) * HOURS_PER_TICK
        phase = (elapsed - self.group * cycle / self.n_groups - offset) % cycle
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
