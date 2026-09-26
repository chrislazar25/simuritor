"""The fleet sim: physics on hand-built cases, then invariants over the full Uri replay."""

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pytest

from backend.data import TZ, Frame
from backend.faults import OUTAGE_END, OUTAGE_START
from backend.policy import Decisions, FleetView
from backend.sim import Fleet, FleetConfig, Sim, TickResult, read_only, uri_replay

FLOOR = FleetConfig().reserve_floor
DRAIN_13F = FleetConfig().drain_base_kw + FleetConfig().drain_kw_per_degf * (65 - 13)  # 2.484 kW


def ct(day: int, hour: int = 0) -> datetime:
    return datetime(2021, 2, day, hour, tzinfo=TZ)


# --- Physics on hand-built cases ----------------------------------------------


@dataclass
class Scripted:
    """A policy that always proposes the same actions."""

    actions: list[str]

    def decide(self, frame: Frame, fleet: FleetView) -> Decisions:
        n = len(self.actions)
        return Decisions(action=np.array(self.actions), src=np.full(n, "rule"), conf=np.full(n, np.nan))


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
    price: float = 1000.0,
    temp_f: float = 13.0,
    ticks: int = 1,
) -> Sim:
    """25 kWh homes with the exact default drain (no noise): `DRAIN_13F` at 13 °F."""
    n = len(soc)
    fleet = Fleet(FleetConfig(n_homes=n, drain_noise=0.0), np.random.default_rng(0))
    fleet.capacity_kwh = read_only(np.full(n, 25.0))
    fleet.soc = read_only(np.array(soc))
    frames = [Frame(i=k, t=ct(15), price=price, temp_f=temp_f, eea="EEA3") for k in range(ticks)]
    return Sim(frames, fleet, Scripted(actions), [GridDown(down or [False] * n)])


def test_discharge_is_10kw_and_stops_at_the_floor() -> None:
    r = tiny_sim(soc=[0.90, 0.25], actions=["discharge", "discharge"]).step()
    assert r.kw.tolist() == pytest.approx([10.0, 5.0])  # 2.5 kWh; only 1.25 kWh above the floor
    assert r.soc.tolist() == pytest.approx([0.80, FLOOR])
    assert r.delivered_mw == pytest.approx(0.015)
    assert r.revenue_tick_usd == pytest.approx(3.75 * 1000 / 1000)  # 3.75 kWh at $1,000/MWh


def test_charge_is_10kw_and_stops_at_full() -> None:
    r = tiny_sim(soc=[0.50, 0.95], actions=["charge", "charge"], price=20.0).step()
    assert r.kw.tolist() == pytest.approx([10.0, 5.0])
    assert r.soc.tolist() == pytest.approx([0.60, 1.0])
    assert r.revenue_tick_usd == pytest.approx(-3.75 * 20 / 1000)  # charging costs money


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
    assert r.available_mw == pytest.approx((10.0 + 5.0) / 1000)
    assert r.delivered_mw == 0


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
    return run(uri_replay(seed=0))


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


def test_no_trading_while_grid_is_down(replay: list[TickResult]) -> None:
    for r in replay:
        down = ~r.grid
        assert np.isin(r.action[down], ["backup", "hold"]).all()
        assert (r.soc[down & (r.action == "hold")] == 0).all()  # hold while down only when dark


def test_everyone_on_grid_outside_the_outage(replay: list[TickResult]) -> None:
    for r in replay:
        if not OUTAGE_START <= r.frame.t < OUTAGE_END:
            assert r.homes_on_grid == 500


def test_rolling_outage_keeps_46_percent_out_and_homes_cycle(replay: list[TickResult]) -> None:
    during = [r for r in replay if OUTAGE_START <= r.frame.t < OUTAGE_END]
    assert during
    assert all(r.homes_on_battery + r.homes_dark == 230 for r in during)  # see RollingOutage
    grid = np.array([r.grid for r in during])
    cycled = (grid.any(axis=0) & ~grid.all(axis=0)).sum()
    assert cycled == 450  # every rotating home is on grid at some point in the window, and off at another


def test_fleet_stats_agree_with_homes(replay: list[TickResult]) -> None:
    for r in replay:
        assert r.homes_on_grid + r.homes_on_battery + r.homes_dark == 500
        assert r.delivered_mw == pytest.approx(r.kw[r.action == "discharge"].sum() / 1000)
        assert r.delivered_mw <= r.available_mw + 1e-12
    assert replay[-1].revenue_usd == pytest.approx(sum(r.revenue_tick_usd for r in replay))


def test_naive_baseline_sells_the_reserve_then_buys_it_back_at_crisis_prices(replay: list[TickResult]) -> None:
    """The naive policy's story on real Uri prices (docs/notes.md, "Data findings").

    Prices sit above $1,000 from Feb 13 and never reach $30 until Feb 19. The fleet exports
    down to the floor on Feb 13, then the recovery rule refills homes back from each rotation
    at ~$9,000/MWh, so the replay ends deep in the red. Never-restored homes go dark within hours.
    """
    earned = [r for r in replay if r.revenue_tick_usd > 0]
    assert earned and all(r.frame.price >= 1000 for r in earned)
    assert all(r.frame.t < ct(14) for r in earned)  # everything is sold on Feb 13
    assert all(r.delivered_mw == 0 for r in replay if ct(16) <= r.frame.t < ct(19))

    end_of_13 = next(r for r in replay if r.frame.t == ct(14)).revenue_usd
    end_of_outage = next(r for r in replay if r.frame.t == OUTAGE_END).revenue_usd
    assert end_of_13 > 0 > end_of_outage
    assert all(r.frame.price >= 1000 for r in replay if r.revenue_tick_usd < 0 and r.frame.t < ct(19))

    sim = uri_replay(seed=0)
    never_restored = sim.faults[0].group < 0
    at_noon = next(r for r in replay if r.frame.t == ct(15, 12))
    assert (at_noon.soc[never_restored] == 0).all()  # dark within 10 hours
