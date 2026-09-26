"""Fleet simulator: seeded homes and one 15-minute tick of physics and accounting.

Tick order: faults decide who has grid power and which devices are out -> the contracts
say what's owed (each home's reserve, the utility's call) -> the policy proposes actions ->
physics applies them within battery limits, on a timeline in seconds where homes drop out
and others cover for them (`backend/failover.py`) -> accounting. The sim keeps its own state (numpy arrays,
one entry per home); `backend/serialize.py` turns it into wire messages.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any

import numpy as np

from backend.commitment import CommitmentSource, UtilityContract
from backend.data import HOURS_PER_TICK, Frame, UriParquetSource
from backend.failover import Failover, FailoverConfig, drop_outs, run_tick
from backend.faults import DeviceFaults, Fault, RollingOutage, SilentDeviceFaults
from backend.policy import POLICIES, FleetView, Policy
from backend.schema import Household, Tier

SLACK_MW = 1e-9
"""Delivery this close to the promise counts as kept (float sums)."""


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
    tier_mix: tuple[tuple[Tier, float], ...] = (("none", 0.1), ("standard", 0.8), ("critical", 0.1))
    """⚠ Homeowner backup contracts (docs/dispatch-design.md). Every `medical` household is `critical`."""
    backup_hours: tuple[tuple[Tier, float], ...] = (("none", 0.0), ("standard", 8.0), ("critical", 16.0))
    """⚠ Hours of backup each tier's reserve must cover at the forecast temperature."""
    start_soc: tuple[float, float] = (0.60, 0.95)
    reserve_floor: float = 0.20
    max_kw: float = 12.0
    """⚠ Max charge/discharge power per home (25 kWh ÷ 1.5 h ≈ 17 kW is an upper bound; ask Base)."""
    drain_base_kw: float = 0.3
    drain_kw_per_degf: float = 0.042
    """⚠ House load on backup, kW = base + per_degf * max(0, 65 - temp °F): 2.48 kW at 13 °F.

    The spec's first formula (0.8 + 0.12 per °F, ~7 kW at 13 °F) is a whole home heating with
    electric resistance at full comfort; it empties a full battery in 3.5-5.6 h. On backup, homes
    shed load (thermostat setback, essential circuits only, and many Austin homes heat with gas),
    so we scale it to about a third: a full average battery (30.7 kWh) lasts ~12 h at 13 °F
    (25 kWh: ~10 h, 39.2 kWh: ~16 h). No single value makes both sizes last 10-14 h.
    """
    drain_noise: float = 0.20
    """⚠ Each home's load is the formula times a fixed factor in [1 - noise, 1 + noise]."""


def exact_mix[T](mix: Sequence[tuple[T, float]], n: int, rng: np.random.Generator) -> np.ndarray:
    """Exactly share * n of each value (largest remainder rounding), in random order."""
    values, shares = zip(*mix, strict=True)
    raw = np.array(shares) * n
    counts = np.floor(raw).astype(int)
    counts[np.argsort(counts - raw)[: n - counts.sum()]] += 1
    return rng.permutation(np.repeat(np.array(values), counts))


def assign_tiers(
    mix: Sequence[tuple[Tier, float]], household: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    """An exact tier mix with every `medical` household `critical`.

    Medical homes swap tiers with non-medical critical homes, so the mix stays exact
    unless there are more medical homes than critical slots; then critical grows.
    """
    tier = exact_mix(mix, len(household), rng)
    medical = household == "medical"
    wrong = np.flatnonzero(medical & (tier != "critical"))
    spare = np.flatnonzero(~medical & (tier == "critical"))[: len(wrong)]
    tier[spare] = tier[wrong[: len(spare)]]
    tier[wrong] = "critical"
    return tier


def forecast_min_f(frames: Sequence[Frame], i: int, hours: float) -> float:
    """Coldest temperature over the next `hours` from tick `i` (this tick included), °F.

    Perfect foresight for now: the actual temperatures, cut short at the end of the replay.
    The forecast error model (docs/dispatch-design.md, "Weather forecast error") replaces this.
    """
    n = max(1, math.ceil(hours / HOURS_PER_TICK))
    return min(f.temp_f for f in frames[i : i + n])


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
        # Drawn last so adding tiers left every earlier draw (and the replay) unchanged.
        self.tier = read_only(assign_tiers(config.tier_mix, self.household, rng))

    def __len__(self) -> int:
        return len(self.ids)

    def drain_kw(self, temp_f: float) -> np.ndarray:
        """House load on backup, kW (see `FleetConfig.drain_kw_per_degf`)."""
        cfg = self.config
        return (cfg.drain_base_kw + cfg.drain_kw_per_degf * max(0.0, 65.0 - temp_f)) * self.drain_factor

    def reserve_kwh(self, forecast_min_f: Callable[[float], float]) -> np.ndarray:
        """Homeowner contract: enough energy for the tier's backup hours at the coldest
        forecast temperature over those hours, capped at capacity. Tier `none` keeps none."""
        reserve = np.zeros(len(self))
        for tier, hours in self.config.backup_hours:
            if hours > 0:
                home = self.tier == tier
                reserve[home] = hours * self.drain_kw(forecast_min_f(hours))[home]
        return np.minimum(reserve, self.capacity_kwh)


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
    reserve_kwh: np.ndarray
    """Each home's contract reserve this tick."""
    available_mw: float
    """Exportable at the start of the tick: homes on grid, above the reserve floor."""
    delivered_mw: float
    utility_call: bool
    promised_mw: float | None
    """0 outside calls; None when no commitment source is configured."""
    homes_on_grid: int
    homes_on_battery: int
    homes_dark: int
    """Grid down and battery empty (ran out). Tier `none` homes count as dark by contract instead."""
    homes_dark_by_contract: int
    """Grid down, tier `none`: no backup, whatever the battery holds."""
    headroom_mwh: float
    """Fleet energy above each home's contract reserve, end of tick."""
    revenue_tick_usd: float
    """Energy (exports - imports at the price) + capacity payment - shortfall penalty."""
    revenue_usd: float
    penalty_usd: float
    """Cumulative shortfall penalties."""
    promise_kept: float | None
    """Share of called ticks so far where delivery met the promise; None before the first call."""
    failovers: list[Failover]
    """Homes that dropped out of a call this tick, and their cover."""
    failovers_warned: int
    """Cumulative, like the rest of the failover counts."""
    failovers_silent: int
    failovers_uncovered: int
    """Failovers whose share wasn't fully covered by the end of their tick."""
    failover_p50_s: float | None
    """Median seconds to cover, over fully covered failovers so far; None until one."""
    failover_max_s: float | None


class Sim:
    """Steps a fleet through a list of frames, one tick per `step()`."""

    def __init__(
        self,
        frames: list[Frame],
        fleet: Fleet,
        policy: Policy,
        faults: Sequence[Fault],
        commitment: CommitmentSource | None = None,
        devices: DeviceFaults | None = None,
        rng: np.random.Generator | None = None,
        failover: FailoverConfig = FailoverConfig(),
    ) -> None:
        """`rng` draws the failover timeline's random seconds and outage notices."""
        if not frames:
            raise ValueError("no frames to replay")
        self.frames = frames
        self.fleet = fleet
        self.policy = policy
        self.faults = faults
        self.commitment = commitment
        self.devices = devices
        self.rng = np.random.default_rng(0) if rng is None else rng
        self.failover = failover
        self.i = 0
        self.revenue_usd = 0.0
        self.penalty_usd = 0.0
        self.called_ticks = 0
        self.kept_ticks = 0
        self.failovers_warned = 0
        self.failovers_silent = 0
        self.failovers_uncovered = 0
        self.cover_s: list[float] = []

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

        grid = self.grid_at(self.i)
        grid_next = self.grid_at(self.i + 1) if self.i + 1 < len(self.frames) else grid
        if self.devices is None:
            faulted, fault_at_s = read_only(np.zeros(len(fleet), dtype=bool)), np.full(len(fleet), np.nan)
        else:
            device = self.devices.tick()
            faulted, fault_at_s = device.out, device.fails_at_s
        exportable = np.where(grid, np.clip(energy - cfg.reserve_floor * cap, 0.0, max_kwh), 0.0)

        forecast = partial(forecast_min_f, self.frames, self.i)
        reserve = read_only(fleet.reserve_kwh(forecast))
        owed = None if self.commitment is None else self.commitment.commit(frame, forecast)
        view = FleetView(
            soc=fleet.soc,
            grid=grid,
            faulted=faulted,
            capacity_kwh=cap,
            household=fleet.household,
            tier=fleet.tier,
            reserve_kwh=reserve,
            reserve_floor=cfg.reserve_floor,
            max_kw=cfg.max_kw,
            commitment=owed,
            forecast_min_f=forecast,
        )
        decisions = self.policy.decide(frame, view)

        # Physics has the last word: no grid means backup (except tier `none`: no backup by
        # contract, the battery keeps its energy), backup needs the grid down, and a known
        # device fault can't discharge.
        no_backup = fleet.tier == "none"
        action = np.where(
            grid,
            np.where(decisions.action == "backup", "hold", decisions.action),
            np.where(no_backup, "hold", "backup"),
        )
        action = np.where(faulted & (action == "discharge"), "hold", action)
        target_kwh = np.inf if decisions.kw is None else np.nan_to_num(decisions.kw, nan=np.inf) * HOURS_PER_TICK
        target_kwh = np.maximum(target_kwh, 0.0)

        # Exports play out second by second: homes drop out (device faults, the floor, an outage
        # next tick) and those with a call share are covered by healthy homes' spare.
        export_kw = np.where(action == "discharge", np.minimum(target_kwh, max_kwh), 0.0) / HOURS_PER_TICK
        share_kw = np.zeros(len(fleet)) if decisions.call_kw is None else np.minimum(decisions.call_kw, export_kw)
        floor_room = np.where(grid, np.maximum(energy - cfg.reserve_floor * cap, 0.0), 0.0)
        drops = drop_outs(export_kw, floor_room, share_kw, grid & ~grid_next, fault_at_s, self.rng, self.failover)
        export_floor = np.maximum(reserve, cfg.reserve_floor * cap)
        timeline = run_tick(
            drops,
            export_kw,
            share_kw,
            spare_kwh=energy - export_floor - export_kw * HOURS_PER_TICK,
            can_cover=grid & ~faulted & (action != "charge"),
            max_kw=cfg.max_kw,
            config=self.failover,
        )
        exported = np.minimum(timeline.exported_kwh, exportable)
        action = np.where(timeline.cover_kwh > 0, "discharge", action)
        imported = np.where(action == "charge", np.minimum(np.clip(cap - energy, 0.0, max_kwh), target_kwh), 0.0)
        # Backup may go below the reserve floor, down to empty: that's what the reserve is for.
        house_kwh = fleet.drain_kw(frame.temp_f) * HOURS_PER_TICK
        backed_up = np.where(action == "backup", np.minimum(house_kwh, np.minimum(energy, max_kwh)), 0.0)
        moved = exported + imported + backed_up
        # An action that moved no energy (e.g. a dark home) is reported as hold.
        action = read_only(np.where(moved > 0, action, "hold"))

        soc = read_only(np.clip((energy - exported - backed_up + imported) / cap, 0.0, 1.0))
        fleet.soc = soc

        delivered_mw = float(exported.sum() / HOURS_PER_TICK / 1000)
        revenue_tick = float((exported.sum() - imported.sum()) / 1000 * frame.price)
        if owed is not None:
            revenue_tick += owed.capacity_usd
            shortfall_mw = owed.promised_mw - delivered_mw
            if shortfall_mw > SLACK_MW:
                penalty = shortfall_mw * HOURS_PER_TICK * max(frame.price, 0.0)  # a penalty never pays out
                revenue_tick -= penalty
                self.penalty_usd += penalty
            if owed.call:
                self.called_ticks += 1
                self.kept_ticks += shortfall_mw <= SLACK_MW
        self.revenue_usd += revenue_tick
        for f in timeline.failovers:
            self.failovers_warned += f.warned
            self.failovers_silent += not f.warned
            if f.cover_s is None:
                self.failovers_uncovered += 1
            else:
                self.cover_s.append(f.cover_s)
        self.i += 1
        off = ~grid
        return TickResult(
            frame=frame,
            grid=grid,
            soc=soc,
            action=action,
            kw=read_only(moved / HOURS_PER_TICK),
            src=decisions.src,
            conf=decisions.conf,
            reserve_kwh=reserve,
            available_mw=float(exportable.sum() / HOURS_PER_TICK / 1000),
            delivered_mw=delivered_mw,
            utility_call=owed is not None and owed.call,
            promised_mw=None if owed is None else owed.promised_mw,
            homes_on_grid=int(grid.sum()),
            homes_on_battery=int((off & ~no_backup & (soc > 0)).sum()),
            homes_dark=int((off & ~no_backup & (soc == 0)).sum()),
            homes_dark_by_contract=int((off & no_backup).sum()),
            headroom_mwh=float(np.maximum(soc * cap - reserve, 0.0).sum() / 1000),
            revenue_tick_usd=revenue_tick,
            revenue_usd=self.revenue_usd,
            penalty_usd=self.penalty_usd,
            promise_kept=self.kept_ticks / self.called_ticks if self.called_ticks else None,
            failovers=timeline.failovers,
            failovers_warned=self.failovers_warned,
            failovers_silent=self.failovers_silent,
            failovers_uncovered=self.failovers_uncovered,
            failover_p50_s=float(np.median(self.cover_s)) if self.cover_s else None,
            failover_max_s=max(self.cover_s) if self.cover_s else None,
        )

    def grid_at(self, i: int) -> np.ndarray:
        """True where a home has grid power at tick `i`, by every fault."""
        grid = np.ones(len(self.fleet), dtype=bool)
        for fault in self.faults:
            grid &= ~fault.grid_down(self.frames[i].t)
        return read_only(grid)


def uri_replay(
    seed: int = 0,
    config: FleetConfig = FleetConfig(),
    frames: list[Frame] | None = None,
    policy: str = "contract",
    contract_size: float | None = UtilityContract.size_frac,
    fault_rate: float = SilentDeviceFaults.rate_per_home_hour,
    **contract_options: Any,
) -> Sim:
    """Tonight's wiring: Uri frames, a seeded fleet, a policy from `POLICIES`, rolling outages,
    silent device faults at `fault_rate` per home-hour, and a utility contract of `contract_size`
    x nameplate (None: no contract, `promised_mw` null) with any other `UtilityContract` options
    (e.g. `emergency_uncapped=True`).

    One seed, split into independent streams, so the fleet, the outage, the device faults and the
    failover timeline don't reshuffle each other.
    """
    fleet_rng, fault_rng, device_rng, failover_rng = (
        np.random.default_rng(s) for s in np.random.SeedSequence(seed).spawn(4)
    )
    fleet = Fleet(config, fleet_rng)
    nameplate_mw = config.n_homes * config.max_kw / 1000
    return Sim(
        frames=UriParquetSource().frames() if frames is None else frames,
        fleet=fleet,
        policy=POLICIES[policy](),
        faults=[RollingOutage(len(fleet), fault_rng)],
        commitment=None
        if contract_size is None
        else UtilityContract(nameplate_mw, size_frac=contract_size, **contract_options),
        devices=SilentDeviceFaults(len(fleet), device_rng, rate_per_home_hour=fault_rate),
        rng=failover_rng,
    )
