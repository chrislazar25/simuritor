"""The fleet sim: physics on hand-built cases, then invariants over the full Uri replay."""

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pytest

from backend.commitment import UtilityContract
from backend.data import TZ, Frame
from backend.faults import OUTAGE_END, OUTAGE_START
from backend.policy import ContractPolicy, Decisions, FleetView
from backend.sim import Fleet, FleetConfig, Sim, TickResult, forecast_min_f, read_only, uri_replay

FLOOR = FleetConfig().reserve_floor
DRAIN_13F = FleetConfig().drain_base_kw + FleetConfig().drain_kw_per_degf * (65 - 13)  # 2.484 kW


def ct(day: int, hour: int = 0) -> datetime:
    return datetime(2021, 2, day, hour, tzinfo=TZ)


# --- Physics on hand-built cases ----------------------------------------------


@dataclass
class Scripted:
    """A policy that always proposes the same actions (and kW targets, if given)."""

    actions: list[str]
    kw: list[float] | None = None

    def decide(self, frame: Frame, fleet: FleetView) -> Decisions:
        n = len(self.actions)
        kw = None if self.kw is None else np.array(self.kw)
        return Decisions(action=np.array(self.actions), src=np.full(n, "rule"), conf=np.full(n, np.nan), kw=kw)


@dataclass
class GridDown:
    """A fault that cuts the given homes for the whole replay."""

    down: list[bool]

    def grid_down(self, t: datetime) -> np.ndarray:
        return np.array(self.down)


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
    frames = [Frame(i=k, t=ct(15), price=p, temp_f=temp_f, eea="EEA3") for k, p in enumerate(prices)]
    contract = None if promised_kw is None else UtilityContract(nameplate_mw=promised_kw / 1000, size_frac=1.0)
    return Sim(frames, fleet, Scripted(actions, kw), [GridDown(down or [False] * n)], contract)


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
    assert all(r.homes_on_battery + r.homes_dark + r.homes_dark_by_contract == 230 for r in during)  # RollingOutage
    grid = np.array([r.grid for r in during])
    cycled = (grid.any(axis=0) & ~grid.all(axis=0)).sum()
    assert cycled == 450  # every rotating home is on grid at some point in the window, and off at another


def test_fleet_stats_agree_with_homes(replay: list[TickResult]) -> None:
    for r in replay:
        assert r.homes_on_grid + r.homes_on_battery + r.homes_dark + r.homes_dark_by_contract == 500
        assert r.delivered_mw == pytest.approx(r.kw[r.action == "discharge"].sum() / 1000)
        assert r.delivered_mw <= r.available_mw + 1e-12
    assert replay[-1].revenue_usd == pytest.approx(sum(r.revenue_tick_usd for r in replay))


def test_precharge_fills_the_fleet_before_the_storm(replay: list[TickResult]) -> None:
    """Feb 10-12 has a sub-32 °F forecast and prices ≤ $200 to charge at; from Feb 13 it's ≥ $700."""
    without = uri_replay(seed=0)
    without.policy = ContractPolicy(precharge=False)
    at_13 = next(r for r in replay if r.frame.t == ct(13))
    without_at_13 = next(r for r in run(without) if r.frame.t == ct(13))
    assert at_13.soc.mean() > 0.9 and without_at_13.soc.mean() < 0.6


@pytest.fixture(scope="module")
def naive_replay() -> list[TickResult]:
    """The naive baseline, on the market alone (no utility contract)."""
    return run(uri_replay(seed=0, policy="naive", contract_size=None))


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


def test_contract_policy_leaves_fewer_homes_dark_than_naive(replay: list[TickResult]) -> None:
    """Same fleet, outages and 60% contract: keeping the reserve halves the home-hours dark (ran out)."""
    naive = run(uri_replay(seed=0, policy="naive"))
    assert sum(r.homes_dark for r in replay) < 0.6 * sum(r.homes_dark for r in naive)
