"""The fleet sim: physics on hand-built cases, then invariants over the full Uri replay."""

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pytest

from backend.commitment import UtilityContract
from backend.data import TICK, TZ, Frame
from backend.failover import FailoverConfig
from backend.faults import OUTAGE_END, OUTAGE_START, DeviceTick
from backend.policy import ContractPolicy, Decisions, FleetView
from backend.sim import Fleet, FleetConfig, Sim, TickResult, forecast_min_f, read_only, uri_replay

FLOOR = FleetConfig().reserve_floor
DRAIN_13F = FleetConfig().drain_base_kw + FleetConfig().drain_kw_per_degf * (65 - 13)  # 2.484 kW


def ct(day: int, hour: int = 0) -> datetime:
    return datetime(2021, 2, day, hour, tzinfo=TZ)


# --- Physics on hand-built cases ----------------------------------------------


@dataclass
class Scripted:
    """A policy that always proposes the same actions (and kW targets, call shares and refill levels, if given)."""

    actions: list[str]
    kw: list[float] | None = None
    call_kw: list[float] | None = None
    refill_kwh: list[float] | None = None

    def decide(self, frame: Frame, fleet: FleetView) -> Decisions:
        n = len(self.actions)
        kw = None if self.kw is None else np.array(self.kw)
        call_kw = None if self.call_kw is None else np.array(self.call_kw)
        refill_kwh = None if self.refill_kwh is None else np.array(self.refill_kwh)
        return Decisions(
            action=np.array(self.actions),
            src=np.full(n, "rule"),
            conf=np.full(n, np.nan),
            kw=kw,
            call_kw=call_kw,
            refill_kwh=refill_kwh,
        )


@dataclass
class GridDown:
    """A fault that cuts the given homes for the whole replay."""

    down: list[bool]

    def grid_down(self, t: datetime) -> np.ndarray:
        return np.array(self.down)


@dataclass
class DownFrom:
    """A fault that cuts the given homes from tick `k` of `tiny_sim` on."""

    down: list[bool]
    k: int

    def grid_down(self, t: datetime) -> np.ndarray:
        return np.array(self.down) & ((t - ct(15, 12)) // TICK >= self.k)


@dataclass
class ScriptedDevices:
    """Device faults on a script: per tick, the second each home faults (NaN: none) and who's known out."""

    fails_at_s: list[list[float]]
    out: list[list[bool]] | None = None
    k: int = 0

    def tick(self) -> DeviceTick:
        n = len(self.fails_at_s[0])
        out = np.array(self.out[self.k] if self.out else [False] * n)
        at_s = np.array(self.fails_at_s[self.k])
        self.k += 1
        return DeviceTick(out=out, fails_at_s=at_s)


def tiny_sim(
    soc: list[float],
    actions: list[str],
    down: list[bool] | None = None,
    price: float | list[float] = 1000.0,
    temp_f: float = 13.0,
    ticks: int = 1,
    tiers: list[str] | None = None,
    kw: list[float] | None = None,
    promised_kw: float | None = None,
    call_kw: list[float] | None = None,
    refill_kwh: list[float] | None = None,
) -> Sim:
    """25 kWh `standard` homes with the exact default drain (no noise): `DRAIN_13F` at 13 °F.

    `price` may give one price per tick. `promised_kw`: a utility contract of that size (default call rules).
    """
    n = len(soc)
    fleet = Fleet(FleetConfig(n_homes=n, drain_noise=0.0), np.random.default_rng(0))
    fleet.capacity_kwh = read_only(np.full(n, 25.0))
    fleet.soc = read_only(np.array(soc))
    fleet.tier = read_only(np.array(tiers or ["standard"] * n))
    prices = price if isinstance(price, list) else [price] * ticks
    frames = [Frame(i=k, t=ct(15, 12) + k * TICK, price=p, temp_f=temp_f, eea="EEA3") for k, p in enumerate(prices)]
    contract = None if promised_kw is None else UtilityContract(nameplate_mw=promised_kw / 1000, size_frac=1.0)
    return Sim(frames, fleet, Scripted(actions, kw, call_kw, refill_kwh), [GridDown(down or [False] * n)], contract)


def test_discharge_is_12kw_and_stops_at_the_floor() -> None:
    r = tiny_sim(soc=[0.90, 0.25], actions=["discharge", "discharge"]).step()
    assert r.kw.tolist() == pytest.approx([12.0, 5.0])  # 3 kWh; only 1.25 kWh above the floor
    assert r.soc.tolist() == pytest.approx([0.78, FLOOR])
    assert r.delivered_mw == pytest.approx(0.017)
    assert r.revenue_tick_usd == pytest.approx(4.25 * 1000 / 1000)  # 4.25 kWh at $1,000/MWh


def test_charge_is_12kw_and_stops_at_full() -> None:
    r = tiny_sim(soc=[0.50, 0.95], actions=["charge", "charge"], price=20.0).step()
    assert r.kw.tolist() == pytest.approx([12.0, 5.0])
    assert r.soc.tolist() == pytest.approx([0.62, 1.0])
    assert r.revenue_tick_usd == pytest.approx(-4.25 * 20 / 1000)  # charging costs money


def test_kw_targets_are_clipped_to_physics() -> None:
    """NaN = as much as allowed; a target above 12 kW or above what's left gets what physics allows."""
    sim = tiny_sim(
        soc=[0.90, 0.90, 0.90, 0.25, 0.50, 0.99],
        actions=["discharge", "discharge", "discharge", "discharge", "charge", "charge"],
        kw=[5.0, 50.0, np.nan, 8.0, 4.0, 8.0],
    )
    assert sim.step().kw.tolist() == pytest.approx([5.0, 12.0, 12.0, 5.0, 4.0, 1.0])


def test_grid_down_forces_backup_whatever_the_policy_says() -> None:
    r = tiny_sim(soc=[0.50], actions=["discharge"], down=[True]).step()
    assert r.action.tolist() == ["backup"]
    assert r.kw.tolist() == pytest.approx([DRAIN_13F])  # the house load, not an export
    assert r.soc.tolist() == pytest.approx([0.50 - DRAIN_13F * 0.25 / 25])
    assert r.delivered_mw == 0 and r.available_mw == 0 and r.revenue_tick_usd == 0


def test_backup_runs_through_the_floor_to_dark() -> None:
    sim = tiny_sim(soc=[0.02], actions=["hold"], down=[True], ticks=2)
    first, second = sim.step(), sim.step()
    assert first.action.tolist() == ["backup"] and first.kw.tolist() == pytest.approx([2.0])  # last 0.5 kWh
    assert first.soc.tolist() == [0.0] and first.homes_dark == 1 and first.homes_on_battery == 0
    assert second.action.tolist() == ["hold"] and second.kw.tolist() == [0.0]  # dark: nothing left to give


def test_backup_on_grid_is_not_allowed() -> None:
    r = tiny_sim(soc=[0.50], actions=["backup"]).step()
    assert r.action.tolist() == ["hold"] and r.soc.tolist() == [0.50]


def test_available_counts_only_homes_on_grid_above_the_floor() -> None:
    r = tiny_sim(soc=[0.90, 0.25, 0.10, 0.90], actions=["hold"] * 4, down=[False, False, False, True]).step()
    assert r.available_mw == pytest.approx((12.0 + 5.0) / 1000)
    assert r.delivered_mw == 0


def test_tier_none_goes_dark_by_contract_and_keeps_its_energy() -> None:
    r = tiny_sim(
        soc=[0.50, 0.0, 0.50], actions=["discharge"] * 3, down=[True] * 3, tiers=["none", "none", "standard"]
    ).step()
    assert r.action.tolist() == ["hold", "hold", "backup"]
    assert r.soc.tolist()[:2] == [0.50, 0.0] and r.kw.tolist()[:2] == [0.0, 0.0]
    assert (r.homes_dark_by_contract, r.homes_dark, r.homes_on_battery) == (2, 0, 1)
    # Reserve 0 for `none`: all 12.5 kWh is headroom. The standard home is below its reserve: none.
    assert r.headroom_mwh == pytest.approx(0.0125)


def test_reserve_is_tier_hours_of_drain_at_the_coldest_forecast() -> None:
    fleet = Fleet(FleetConfig(n_homes=4, drain_noise=0.0), np.random.default_rng(0))
    fleet.capacity_kwh = read_only(np.array([25.0, 25.0, 25.0, 39.2]))
    fleet.tier = read_only(np.array(["none", "standard", "critical", "critical"]))
    drain_40f = FleetConfig().drain_base_kw + FleetConfig().drain_kw_per_degf * (65 - 40)  # 1.35 kW
    # Each tier looks as far ahead as its hours: 8 h out it's 40 °F, 16 h out it reaches 13 °F.
    reserve = fleet.reserve_kwh(lambda hours: 40.0 if hours <= 8 else 13.0)
    assert reserve.tolist() == pytest.approx([0.0, 8 * drain_40f, 25.0, 39.2])  # 16 x 2.48 = 39.7: capped
    assert fleet.reserve_kwh(lambda hours: 70.0).tolist() == pytest.approx([0.0, 8 * 0.3, 16 * 0.3, 16 * 0.3])


def test_forecast_is_the_coldest_temperature_in_the_window() -> None:
    frames = [Frame(i=k, t=ct(15), price=0.0, temp_f=t, eea="Normal") for k, t in enumerate([30, 20, 25, 10, 40])]
    assert forecast_min_f(frames, 0, 0.25) == 30  # this tick only
    assert forecast_min_f(frames, 0, 0.5) == 20
    assert forecast_min_f(frames, 1, 0.5) == 20
    assert forecast_min_f(frames, 1, 0.75) == 10
    assert forecast_min_f(frames, 4, 8.0) == 40  # cut short at the end of the replay


def test_penalty_and_promise_kept() -> None:
    """One home promises 12 kW. 17.5 kWh above the floor at 3 kWh a tick: short on the 5th and 6th called ticks.

    Tick 0 isn't called (below the $1,000 trigger), so its export counts only as energy.
    """
    sim = tiny_sim(soc=[0.90], actions=["discharge"], price=[500.0] + [1000.0] * 6, promised_kw=12.0)
    rs = [sim.step() for _ in range(7)]
    assert [r.utility_call for r in rs] == [False] + [True] * 6
    assert [r.promised_mw for r in rs] == pytest.approx([0.0] + [0.012] * 6)
    assert [r.delivered_mw * 1000 for r in rs] == pytest.approx([12, 12, 12, 12, 12, 10, 0])
    assert rs[0].promise_kept is None
    assert [r.promise_kept for r in rs[1:]] == pytest.approx([1, 1, 1, 1, 4 / 5, 4 / 6])
    shortfall_mwh = (2 + 12) / 1000 * 0.25
    assert rs[-1].penalty_usd == pytest.approx(shortfall_mwh * 1000)
    energy = 3 * 0.5 + 14.5 * 1.0  # $/kWh: tick 0's 3 kWh at $500/MWh, the other 14.5 kWh at $1,000
    capacity = 7 * 2000 * 0.012 / 672  # $2,000/MW-week, 672 ticks a week
    assert rs[-1].revenue_usd == pytest.approx(energy + capacity - rs[-1].penalty_usd)
    # All 14.5 called kWh went to the call; tick 0's export was the market's.
    assert rs[-1].contract_pnl_usd == pytest.approx(14.5 + capacity - rs[-1].penalty_usd)
    assert rs[-1].market_usd == pytest.approx(1.5) and rs[-1].backup_cost_usd == 0


def test_call_energy_is_delivery_up_to_the_promise() -> None:
    """4 kW promised, 12 kW exported in a call: 1 kWh for the call, 2 kWh for the market, at $1,000/MWh."""
    r = tiny_sim(soc=[0.90], actions=["discharge"], promised_kw=4.0).step()
    assert r.utility_call and r.kept
    capacity = 2000 * 0.004 / 672
    assert r.contract_pnl_usd == pytest.approx(1.0 + capacity)
    assert r.market_usd == pytest.approx(2.0)
    assert r.revenue_usd == pytest.approx(r.contract_pnl_usd - r.backup_cost_usd + r.market_usd)


def test_backup_cost_is_charging_up_to_the_policys_refill_level() -> None:
    """3 kWh charged each at $9,000/MWh. Home 0 starts 1.5 kWh below its refill level, home 1 7.5 kWh
    below: 4.5 kWh of backup, the other 1.5 kWh is the market's."""
    sim = tiny_sim(soc=[0.10, 0.50], actions=["charge", "charge"], price=9000.0, refill_kwh=[4.0, 20.0])
    r = sim.step()
    assert r.backup_cost_usd == pytest.approx(4.5 * 9)
    assert r.market_usd == pytest.approx(-1.5 * 9)
    assert r.contract_pnl_usd == 0
    assert r.revenue_usd == pytest.approx(-6 * 9)


def test_headroom_sold_is_export_beyond_the_call_share() -> None:
    """3 kWh exported each. Home 0 has a 4 kW call share, so 2 kWh of it is headroom; home 1 has
    no share, so all 3 kWh is."""
    r = tiny_sim(soc=[0.90, 0.90], actions=["discharge", "discharge"], call_kw=[4.0, 0.0]).step()
    assert r.headroom_sold_mwh * 1000 == pytest.approx(2.0 + 3.0)


def test_reserve_recharge_cost_is_charging_up_to_the_export_floor() -> None:
    """Tier `none` (no contract reserve): the 20% floor is 5 kWh. Home 0 charges 3 kWh from 2.5 kWh,
    2.5 of it up to the floor; home 1 is above it already. 2.5 kWh at $9,000/MWh."""
    r = tiny_sim(soc=[0.10, 0.50], actions=["charge", "charge"], price=9000.0, tiers=["none", "none"]).step()
    assert r.reserve_recharge_usd == pytest.approx(2.5 * 9)


def test_a_known_device_fault_cant_discharge() -> None:
    sim = tiny_sim(soc=[0.90, 0.90], actions=["discharge", "charge"], kw=[6.0, 6.0], price=20.0)
    sim.devices = ScriptedDevices(fails_at_s=[[np.nan, np.nan]], out=[[True, True]])
    r = sim.step()
    assert r.action.tolist() == ["hold", "charge"] and r.kw.tolist() == pytest.approx([0.0, 6.0])


def test_a_new_device_fault_stops_the_export_at_its_second() -> None:
    sim = tiny_sim(soc=[0.90], actions=["discharge"], kw=[8.0])
    sim.devices = ScriptedDevices(fails_at_s=[[450.0]])
    r = sim.step()
    assert r.kw.tolist() == pytest.approx([4.0]) and r.failovers == []  # no call share: nothing to cover


def test_a_silent_fault_in_a_call_is_covered_in_11_s_and_the_gap_is_charged() -> None:
    """12 kW promised, 6 kW each. Home 0 goes silent at 450 s; home 1 covers from 461 s.

    The 11 s gap (6 kW) is a shortfall of 0.6% of the promise: within the 2% tolerance, so the
    interval is kept, but the penalty still charges it at the price.
    At 65 °F the reserve (2.4 kWh) is below the 20% floor (5 kWh), so home 1 has 16 kWh spare.
    """
    sim = tiny_sim(
        soc=[0.90, 0.90], actions=["discharge"] * 2, kw=[6.0, 6.0], call_kw=[6.0, 6.0], temp_f=65.0, promised_kw=12.0
    )
    sim.devices = ScriptedDevices(fails_at_s=[[450.0, np.nan]])
    r = sim.step()
    [f] = r.failovers
    assert (f.home, f.warned, f.cover_s, f.covered_by) == (0, False, 11.0, 1)
    assert r.kw.tolist() == pytest.approx([3.0, 6.0 + 6.0 * 439 / 900])
    shortfall_kwh = 6.0 * 11 / 3600
    assert r.delivered_mw == pytest.approx(0.012 - shortfall_kwh / 0.25 / 1000)
    assert r.kept and r.promise_kept == 1 and r.penalty_usd == pytest.approx(shortfall_kwh / 1000 * 1000)
    assert (r.failovers_warned, r.failovers_silent, r.failovers_uncovered) == (0, 1, 0)
    assert r.failover_p50_s == r.failover_max_s == 11.0


@pytest.mark.parametrize(("kw", "kept"), [(11.76, True), (11.75, False)])
def test_an_interval_is_kept_within_2_percent_of_the_promise(kw: float, kept: bool) -> None:
    sim = tiny_sim(soc=[0.90], actions=["discharge"], kw=[kw], promised_kw=12.0)
    r = sim.step()
    assert r.kept == kept and r.promise_kept == int(kept)
    assert r.penalty_usd == pytest.approx((12.0 - kw) / 1000 * 0.25 * 1000)  # the whole shortfall, kept or not


def test_failover_stats_are_cumulative() -> None:
    """Three call ticks, 4 kW from each of three homes (8 kW spare each):
    0. home 0 silent at 300 s: covered in 11 s by one home (the first of two with the same spare);
    1. home 1 loses the grid next tick and warns (every outage warns here): covered in 5 s by one;
    2. homes 0 and 2 go silent; home 1 is off grid: nobody left to cover either.
    """
    sim = tiny_sim(
        soc=[0.90] * 3,
        actions=["discharge"] * 3,
        kw=[4.0] * 3,
        call_kw=[4.0] * 3,
        temp_f=65.0,
        promised_kw=12.0,
        ticks=3,
    )
    sim.faults = [DownFrom([False, True, False], k=2)]
    sim.devices = ScriptedDevices(fails_at_s=[[300.0, np.nan, np.nan], [np.nan] * 3, [100.0, np.nan, 200.0]])
    sim.failover = FailoverConfig(outage_notice_frac=1.0)
    rs = [sim.step() for _ in range(3)]
    assert [[(f.home, f.warned, f.cover_s, f.covered_by) for f in r.failovers] for r in rs] == [
        [(0, False, 11.0, 1)],
        [(1, True, 5.0, 1)],
        [(0, False, None, 0), (2, False, None, 0)],
    ]
    assert [(r.failovers_warned, r.failovers_silent, r.failovers_uncovered) for r in rs] == [
        (0, 1, 0),
        (1, 1, 0),
        (1, 3, 2),
    ]
    assert [(r.failover_p50_s, r.failover_max_s) for r in rs] == [(11.0, 11.0), (8.0, 11.0), (8.0, 11.0)]


def test_no_contract_means_nothing_promised() -> None:
    r = tiny_sim(soc=[0.90], actions=["discharge"]).step()
    assert r.promised_mw is None and not r.utility_call and r.promise_kept is None and r.penalty_usd == 0


def test_replay_ends() -> None:
    sim = tiny_sim(soc=[0.5], actions=["hold"], ticks=2)
    sim.step(), sim.step()
    assert sim.done
    with pytest.raises(IndexError):
        sim.step()


# --- The full Uri replay (seed 0) ---------------------------------------------


def run(sim: Sim) -> list[TickResult]:
    results = []
    while not sim.done:
        results.append(sim.step())
    return results


@pytest.fixture(scope="module")
def replay() -> list[TickResult]:
    """ContractPolicy under the default 60% contract."""
    return run(uri_replay(seed=0))


@pytest.fixture(scope="module")
def fleet() -> Fleet:
    return uri_replay(seed=0).fleet


def test_fleet_matches_the_spec_mix() -> None:
    fleet = uri_replay(seed=0).fleet
    assert len(fleet) == 500 and len(set(fleet.ids)) == 500
    assert (fleet.capacity_kwh == 25.0).sum() == 300 and (fleet.capacity_kwh == 39.2).sum() == 200
    assert {h: int((fleet.household == h).sum()) for h in ("standard", "medical", "elderly", "wfh")} == {
        "standard": 350,
        "medical": 50,
        "elderly": 50,
        "wfh": 50,
    }
    assert ((0.60 <= fleet.soc) & (fleet.soc <= 0.95)).all()
    assert ((30.15 <= fleet.lat) & (fleet.lat <= 30.45)).all()
    assert ((-97.90 <= fleet.lon) & (fleet.lon <= -97.60)).all()


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_tier_mix_is_exact_and_medical_is_critical(seed: int) -> None:
    fleet = uri_replay(seed=seed).fleet
    assert {t: int((fleet.tier == t).sum()) for t in ("none", "standard", "critical")} == {
        "none": 50,
        "standard": 400,
        "critical": 50,
    }
    assert (fleet.tier[fleet.household == "medical"] == "critical").all()


def test_more_medical_homes_than_critical_slots_grows_critical() -> None:
    config = FleetConfig(n_homes=100, household_mix=(("standard", 0.7), ("medical", 0.3)))
    fleet = Fleet(config, np.random.default_rng(0))
    medical = fleet.household == "medical"
    assert (fleet.tier[medical] == "critical").all()
    assert (fleet.tier == "critical").sum() == 30
    assert (fleet.tier == "none").sum() <= 10


def test_same_seed_same_replay(replay: list[TickResult]) -> None:
    again = run(uri_replay(seed=0))
    for a, b in zip(replay, again, strict=True):
        assert np.array_equal(a.soc, b.soc) and np.array_equal(a.action, b.action)
    assert again[-1].revenue_usd == replay[-1].revenue_usd
    other = uri_replay(seed=1)
    assert not np.array_equal(other.fleet.soc, uri_replay(seed=0).fleet.soc)


def test_soc_stays_in_bounds(replay: list[TickResult]) -> None:
    assert all(((0 <= r.soc) & (r.soc <= 1)).all() for r in replay)


def test_discharging_never_goes_below_the_floor(replay: list[TickResult]) -> None:
    for r in replay:
        assert (r.soc[r.action == "discharge"] >= FLOOR - 1e-9).all()


def test_no_trading_while_grid_is_down(replay: list[TickResult], fleet: Fleet) -> None:
    none = fleet.tier == "none"
    for r in replay:
        down = ~r.grid
        assert np.isin(r.action[down], ["backup", "hold"]).all()
        assert (r.action[down & none] == "hold").all()  # no backup by contract
        assert (r.soc[down & ~none & (r.action == "hold")] == 0).all()  # otherwise hold while down only when dark


def test_contract_policy_never_exports_below_the_reserve(replay: list[TickResult], fleet: Fleet) -> None:
    for r in replay:
        exporting = r.action == "discharge"
        assert (r.soc[exporting] * fleet.capacity_kwh[exporting] >= r.reserve_kwh[exporting] - 1e-9).all()


def test_promise_is_the_contract_during_calls_and_zero_outside(replay: list[TickResult]) -> None:
    assert all(r.promised_mw == pytest.approx(0.6 * 500 * 12 / 1000) for r in replay if r.utility_call)
    assert all(r.promised_mw == 0.0 for r in replay if not r.utility_call)
    assert any(r.utility_call for r in replay)
    assert all(b.penalty_usd >= a.penalty_usd for a, b in zip(replay, replay[1:]))


def test_everyone_on_grid_outside_the_outage(replay: list[TickResult]) -> None:
    for r in replay:
        if not OUTAGE_START <= r.frame.t < OUTAGE_END:
            assert r.homes_on_grid == 500


def test_rolling_outage_keeps_46_percent_out_and_homes_cycle(replay: list[TickResult]) -> None:
    during = [r for r in replay if OUTAGE_START <= r.frame.t < OUTAGE_END]
    assert during
    off = [r.homes_on_battery + r.homes_dark + r.homes_dark_by_contract for r in during]
    assert np.mean(off) == pytest.approx(230, rel=0.05)  # RollingOutage: 46% on average
    grid = np.array([r.grid for r in during])
    cycled = (grid.any(axis=0) & ~grid.all(axis=0)).sum()
    assert cycled == 450  # every rotating home is on grid at some point in the window, and off at another


def test_fleet_stats_agree_with_homes(replay: list[TickResult]) -> None:
    for r in replay:
        assert r.homes_on_grid + r.homes_on_battery + r.homes_dark + r.homes_dark_by_contract == 500
        assert r.delivered_mw == pytest.approx(r.kw[r.action == "discharge"].sum() / 1000)
        assert r.delivered_mw <= r.available_mw + 1e-12
    assert replay[-1].revenue_usd == pytest.approx(sum(r.revenue_tick_usd for r in replay))


@pytest.mark.parametrize("which", ["replay", "naive_replay"])
def test_money_split_adds_up_to_revenue(which: str, request: pytest.FixtureRequest) -> None:
    replay: list[TickResult] = request.getfixturevalue(which)
    for r in replay:
        assert r.contract_pnl_usd - r.backup_cost_usd + r.market_usd == pytest.approx(r.revenue_usd, abs=1e-6)
    end = replay[-1]
    assert end.backup_cost_usd > 0  # homes back from the outage refill their reserve at storm prices
    if which == "naive_replay":
        assert end.contract_pnl_usd == 0  # no contract
    else:
        assert end.contract_pnl_usd != 0


def test_precharge_fills_the_fleet_before_the_storm() -> None:
    """Feb 10-12 has a sub-32 °F forecast and prices ≤ $200 to charge at; from Feb 13 it's ≥ $700.

    No utility contract, so call-ready recharge doesn't fill the fleet too, and selling headroom:
    one that keeps it is full by Feb 13 either way (it fills at ≤ $30 on Feb 10 and never sells).
    """
    at_13 = []
    for precharge in (True, False):
        sim = uri_replay(seed=0, contract_size=None)
        sim.policy = ContractPolicy(precharge=precharge, headroom_mode="sell")
        at_13.append(next(r for r in run(sim) if r.frame.t == ct(13)).soc.mean())
    assert at_13[0] > 0.8 and at_13[1] < 0.6


def test_calls_follow_the_contract_rules(replay: list[TickResult]) -> None:
    """At most one call a day (default), inside 06:00-22:00, at most 6 ticks long."""
    starts = [b for a, b in zip(replay, replay[1:]) if b.utility_call and not a.utility_call]
    assert len({r.frame.t.date() for r in starts}) == len(starts)
    assert all(6 <= r.frame.t.hour < 22 for r in replay if r.utility_call)
    run_length = 0
    for r in replay:
        run_length = run_length + 1 if r.utility_call else 0
        assert run_length <= 6


def test_emergency_uncapped_calls_more_during_the_eea() -> None:
    capped = sum(r.utility_call for r in run(uri_replay(seed=0)))
    uncapped = sum(r.utility_call for r in run(uri_replay(seed=0, emergency_uncapped=True)))
    assert uncapped > 2 * capped


@pytest.fixture(scope="module")
def naive_replay() -> list[TickResult]:
    """The naive baseline, on the market alone (no utility contract, no device faults: a home
    hard-faulted before Feb 11 can't sell its reserve, so it wouldn't be dark by Feb 15)."""
    return run(uri_replay(seed=0, policy="naive", contract_size=None, fault_rate=0.0))


def test_naive_baseline_sells_the_reserve_then_buys_it_back_at_crisis_prices(
    naive_replay: list[TickResult], fleet: Fleet
) -> None:
    """The naive policy's story on real Uri prices (docs/notes.md, "Data findings").

    It fills up at ≤ $30 on Feb 10, then sells down to the floor on the first spike on Feb 11,
    two days before prices sit above $1,000 for good (Feb 13; they never reach $30 again until
    Feb 19). The recovery rule then refills homes back from each rotation at ~$9,000/MWh, so the
    replay ends deep in the red. Never-restored homes go dark within hours.
    (At 12 kW one recovery charge overshoots floor + 10%, so a few homes resell a sliver of it.)
    """
    replay = naive_replay
    earned = [r for r in replay if r.revenue_tick_usd > 0]
    assert earned and all(r.frame.price >= 1000 for r in earned)
    late = sum(r.revenue_tick_usd for r in earned if r.frame.t >= ct(12))
    assert late < 0.05 * sum(r.revenue_tick_usd for r in earned)  # nearly everything is sold on Feb 11
    assert all(r.delivered_mw == 0 for r in replay if ct(12) <= r.frame.t < ct(15))  # nothing left to sell
    assert all(r.delivered_mw == 0 for r in replay if ct(16) <= r.frame.t < OUTAGE_END)

    end_of_11 = next(r for r in replay if r.frame.t == ct(12)).revenue_usd
    end_of_outage = next(r for r in replay if r.frame.t == OUTAGE_END).revenue_usd
    assert end_of_11 > 0 > end_of_outage
    assert all(r.frame.price >= 1000 for r in replay if r.revenue_tick_usd < 0 and ct(12) <= r.frame.t < ct(19))

    sim = uri_replay(seed=0)
    never_restored = (sim.faults[0].group < 0) & (fleet.tier != "none")  # `none` keeps its energy
    at_noon = next(r for r in replay if r.frame.t == ct(15, 12))
    assert (at_noon.soc[never_restored] == 0).all()  # dark within 10 hours


def test_failover_counts_add_up_over_the_replay(replay: list[TickResult]) -> None:
    """Default chaos: failovers happen only in calls, both warned and silent (rolling cuts land
    mid-call), and every count is the running total of the events."""
    events = [f for r in replay for f in r.failovers]
    assert events and all(r.utility_call for r in replay if r.failovers)
    last = replay[-1]
    assert last.failovers_warned == sum(f.warned for f in events) > 0
    assert last.failovers_silent == sum(not f.warned for f in events) > 0
    assert last.failovers_uncovered == sum(f.cover_s is None for f in events)
    covered = [f.cover_s for f in events if f.cover_s is not None]
    assert last.failover_max_s == (max(covered) if covered else None)


def test_without_device_faults_every_failover_is_a_home_losing_the_grid_next_tick() -> None:
    replay = run(uri_replay(seed=0, fault_rate=0.0))
    events = [(r, n, f) for r, n in zip(replay, replay[1:]) for f in r.failovers]
    assert events and all(r.grid[f.home] and not n.grid[f.home] for r, n, f in events)


def test_keep_sells_no_headroom_and_sell_sells_it_at_the_export_price(replay: list[TickResult]) -> None:
    assert sum(r.headroom_sold_mwh for r in replay) == 0
    sell = run(uri_replay(seed=0, policy_options={"headroom_mode": "sell"}))
    assert sum(r.headroom_sold_mwh for r in sell) > 1
    assert all(r.frame.price >= ContractPolicy().export_at_usd for r in sell if r.headroom_sold_mwh > 0)


def test_contract_policy_leaves_fewer_homes_dark_than_naive(replay: list[TickResult]) -> None:
    """Same fleet, outages and 60% contract: keeping the reserve halves the home-hours dark (ran out)."""
    naive = run(uri_replay(seed=0, policy="naive"))
    assert sum(r.homes_dark for r in replay) < 0.6 * sum(r.homes_dark for r in naive)
