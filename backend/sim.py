"""Fleet simulator: seeded homes and one 15-minute tick of physics and accounting.

Tick order: faults decide who has grid power -> the policy proposes actions ->
physics applies them within battery limits -> accounting. The sim keeps its own
state (numpy arrays, one entry per home); `backend/serialize.py` turns it into
wire messages.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

import numpy as np

from backend.data import TICK, Frame, UriParquetSource
from backend.faults import Fault, FixedOutage
from backend.policy import FleetView, NaivePolicy, Policy
from backend.schema import Household

HOURS_PER_TICK = TICK / timedelta(hours=1)  # 0.25


@dataclass(frozen=True)
class FleetConfig:
    """Spec defaults (docs/slice-spec.md); ⚠ marks assumptions to state in the README."""

    n_homes: int = 500
    lat_range: tuple[float, float] = (30.15, 30.45)
    lon_range: tuple[float, float] = (-97.90, -97.60)
    capacity_mix: tuple[tuple[float, float], ...] = ((25.0, 0.6), (39.2, 0.4))
    """(kWh, share): Base Gen2 and Core batteries."""
    household_mix: tuple[tuple[Household, float], ...] = (
        ("standard", 0.7),
        ("medical", 0.1),
        ("elderly", 0.1),
        ("wfh", 0.1),
    )
    start_soc: tuple[float, float] = (0.60, 0.95)
    reserve_floor: float = 0.20
    max_kw: float = 10.0
    """⚠ Max charge/discharge power per home."""
    drain_noise: float = 0.20
    """⚠ Each home's load is the spec formula times a fixed factor in [1 - noise, 1 + noise]."""


def exact_mix[T](mix: Sequence[tuple[T, float]], n: int, rng: np.random.Generator) -> np.ndarray:
    """Exactly share * n of each value (largest remainder rounding), in random order."""
    values, shares = zip(*mix, strict=True)
    raw = np.array(shares) * n
    counts = np.floor(raw).astype(int)
    counts[np.argsort(counts - raw)[: n - counts.sum()]] += 1
    return rng.permutation(np.repeat(np.array(values), counts))


def read_only(a: np.ndarray) -> np.ndarray:
    a.setflags(write=False)
    return a


class Fleet:
    """N homes as parallel arrays. Static facts are fixed at construction; `soc` is replaced each tick."""

    def __init__(self, config: FleetConfig, rng: np.random.Generator) -> None:
        n = config.n_homes
        self.config = config
        self.ids = [f"h{k:04d}" for k in range(n)]
        self.lat = read_only(rng.uniform(*config.lat_range, n))
        self.lon = read_only(rng.uniform(*config.lon_range, n))
        self.capacity_kwh = read_only(exact_mix(config.capacity_mix, n, rng))
        self.household = read_only(exact_mix(config.household_mix, n, rng))
        self.drain_factor = read_only(rng.uniform(1 - config.drain_noise, 1 + config.drain_noise, n))
        self.soc = read_only(rng.uniform(*config.start_soc, n))

    def __len__(self) -> int:
        return len(self.ids)

    def drain_kw(self, temp_f: float) -> np.ndarray:
        """House load, kW. ⚠ Spec formula: 0.8 + 0.12 per °F below 65 (≈ 7 kW at 13 °F)."""
        return (0.8 + 0.12 * max(0.0, 65.0 - temp_f)) * self.drain_factor


@dataclass(frozen=True, slots=True)
class TickResult:
    """What happened in one tick. Per-home arrays hold end-of-tick state."""

    frame: Frame
    grid: np.ndarray
    soc: np.ndarray
    action: np.ndarray
    kw: np.ndarray
    """Battery power magnitude; direction comes from `action`."""
    src: np.ndarray
    conf: np.ndarray
    available_mw: float
    """Exportable at the start of the tick: homes on grid, above the reserve floor."""
    delivered_mw: float
    promised_mw: float | None
    homes_on_grid: int
    homes_on_battery: int
    homes_dark: int
    revenue_tick_usd: float
    revenue_usd: float


class Sim:
    """Steps a fleet through a list of frames, one tick per `step()`."""

    def __init__(self, frames: list[Frame], fleet: Fleet, policy: Policy, faults: Sequence[Fault]) -> None:
        if not frames:
            raise ValueError("no frames to replay")
        self.frames = frames
        self.fleet = fleet
        self.policy = policy
        self.faults = faults
        self.i = 0
        self.revenue_usd = 0.0

    @property
    def done(self) -> bool:
        return self.i >= len(self.frames)

    def step(self) -> TickResult:
        if self.done:
            raise IndexError("replay finished")
        frame, fleet, cfg = self.frames[self.i], self.fleet, self.fleet.config
        cap = fleet.capacity_kwh
        energy = fleet.soc * cap
        max_kwh = cfg.max_kw * HOURS_PER_TICK

        grid = np.ones(len(fleet), dtype=bool)
        for fault in self.faults:
            grid &= ~fault.grid_down(frame.t)
        read_only(grid)
        exportable = np.where(grid, np.clip(energy - cfg.reserve_floor * cap, 0.0, max_kwh), 0.0)

        view = FleetView(
            soc=fleet.soc,
            grid=grid,
            capacity_kwh=cap,
            household=fleet.household,
            reserve_floor=cfg.reserve_floor,
        )
        decisions = self.policy.decide(frame, view)

        # Physics has the last word: no grid means backup, and backup needs the grid down.
        action = np.where(grid, np.where(decisions.action == "backup", "hold", decisions.action), "backup")
        exported = np.where(action == "discharge", exportable, 0.0)
        imported = np.where(action == "charge", np.clip(cap - energy, 0.0, max_kwh), 0.0)
        # Backup may go below the reserve floor, down to empty: that's what the reserve is for.
        house_kwh = fleet.drain_kw(frame.temp_f) * HOURS_PER_TICK
        backed_up = np.where(action == "backup", np.minimum(house_kwh, np.minimum(energy, max_kwh)), 0.0)
        moved = exported + imported + backed_up
        # An action that moved no energy (e.g. a dark home) is reported as hold.
        action = read_only(np.where(moved > 0, action, "hold"))

        soc = read_only(np.clip((energy - exported - backed_up + imported) / cap, 0.0, 1.0))
        fleet.soc = soc

        revenue_tick = float((exported.sum() - imported.sum()) / 1000 * frame.price)
        self.revenue_usd += revenue_tick
        self.i += 1
        return TickResult(
            frame=frame,
            grid=grid,
            soc=soc,
            action=action,
            kw=read_only(moved / HOURS_PER_TICK),
            src=decisions.src,
            conf=decisions.conf,
            available_mw=float(exportable.sum() / HOURS_PER_TICK / 1000),
            delivered_mw=float(exported.sum() / HOURS_PER_TICK / 1000),
            promised_mw=None,  # no commitment source yet
            homes_on_grid=int(grid.sum()),
            homes_on_battery=int((~grid & (soc > 0)).sum()),
            homes_dark=int((~grid & (soc == 0)).sum()),
            revenue_tick_usd=revenue_tick,
            revenue_usd=self.revenue_usd,
        )


def uri_replay(seed: int = 0, config: FleetConfig = FleetConfig(), frames: list[Frame] | None = None) -> Sim:
    """Tonight's wiring: Uri frames, a seeded fleet, the naive policy and the fixed outage.

    One seed, split into independent streams, so the fleet and the outage don't reshuffle each other.
    """
    fleet_rng, fault_rng = (np.random.default_rng(s) for s in np.random.SeedSequence(seed).spawn(2))
    fleet = Fleet(config, fleet_rng)
    return Sim(
        frames=UriParquetSource().frames() if frames is None else frames,
        fleet=fleet,
        policy=NaivePolicy(),
        faults=[FixedOutage(len(fleet), fault_rng)],
    )
