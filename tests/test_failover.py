"""Failover: who drops out of a tick and when, and how healthy homes cover a lost call share."""

import numpy as np
import pytest

from backend.failover import TICK_S, DropOuts, FailoverConfig, Timeline, drop_outs, greedy, run_tick


def play(
    share: list[float],
    export: list[float],
    at_s: list[float | None],
    warned: list[bool] | None = None,
    spare_kwh: list[float] | None = None,
    can_cover: list[bool] | None = None,
) -> Timeline:
    """12 kW homes; `at_s` None: exports the whole tick. Spare energy is plenty unless given."""
    n = len(share)
    drops = DropOuts(
        at_s=np.array([TICK_S if s is None else s for s in at_s]), warned=np.array(warned or [False] * n)
    )
    return run_tick(
        drops,
        export_kw=np.array(export),
        share_kw=np.array(share),
        spare_kwh=np.array(spare_kwh or [100.0] * n),
        can_cover=np.array(can_cover or [True] * n),
        max_kw=12.0,
    )


# --- The timeline --------------------------------------------------------------


@pytest.mark.parametrize(("warned", "cover_s"), [(True, 5.0), (False, 11.0)])
def test_warned_is_covered_after_reassign_silent_after_missed_heartbeats_too(warned: bool, cover_s: float) -> None:
    """Warned: detected at once, 5 s to reassign. Silent: 3 missed 2 s heartbeats, then 5 s."""
    t = play(share=[6.0, 6.0], export=[6.0, 6.0], at_s=[100.0, None], warned=[warned, False])
    [f] = t.failovers
    assert (f.home, f.warned, f.at_s, f.cover_s, f.covered_by) == (0, warned, 100.0, cover_s, 1)
    assert f.uncovered_kwh == pytest.approx(6.0 * cover_s / 3600)  # only the gap before cover
    assert t.exported_kwh.tolist() == pytest.approx([6.0 * 100 / 3600, 6.0 * 0.25 + 6.0 * (800 - cover_s) / 3600])
    assert t.cover_kwh.tolist() == pytest.approx([0.0, 6.0 * (800 - cover_s) / 3600])


def test_cover_comes_from_the_most_spare_first_fewest_homes() -> None:
    """Spare power is max kW minus what the home already exports: 2, 6 and 4 kW spare.
    4 kW lost: the 6 kW home takes it all. 9 kW lost: 6 kW, then 3 of the 4 kW home's."""
    left_h = (TICK_S - 11) / 3600
    t = play(share=[4.0, 4.0, 4.0, 4.0], export=[4.0, 10.0, 6.0, 8.0], at_s=[0.0, None, None, None])
    assert t.cover_kwh.tolist() == pytest.approx([0.0, 0.0, 4.0 * left_h, 0.0])
    assert t.failovers[0].covered_by == 1 and t.failovers[0].cover_s == 11.0
    t = play(share=[9.0, 4.0, 4.0, 4.0], export=[9.0, 10.0, 6.0, 8.0], at_s=[0.0, None, None, None])
    assert t.cover_kwh.tolist() == pytest.approx([0.0, 0.0, 6.0 * left_h, 3.0 * left_h])
    assert t.failovers[0].covered_by == 2


def test_greedy_ties_go_to_the_lowest_index_and_spare_can_run_out() -> None:
    assert greedy(5.0, np.array([3.0, 0.0, 3.0])).tolist() == [3.0, 0.0, 2.0]
    assert greedy(8.0, np.array([3.0, 0.0, 3.0])).tolist() == [3.0, 0.0, 3.0]


def test_partial_cover_leaves_the_rest_uncovered_to_the_end_of_the_tick() -> None:
    """Only 2 kW spare for a 6 kW share: not covered (cover_s None), 4 kW short from 111 s to 900 s."""
    t = play(share=[6.0, 10.0], export=[6.0, 10.0], at_s=[100.0, None])
    [f] = t.failovers
    assert f.cover_s is None and f.covered_by == 1
    assert f.uncovered_kwh == pytest.approx(6.0 * 11 / 3600 + 4.0 * 789 / 3600)


def test_spare_energy_limits_cover_too() -> None:
    """0.5 kWh above the floor lasts 2.28 kW for the 789 s left: a partial cover."""
    t = play(share=[6.0, 0.0], export=[6.0, 0.0], at_s=[100.0, None], spare_kwh=[0.0, 0.5])
    [f] = t.failovers
    assert f.cover_s is None
    assert t.cover_kwh.tolist() == pytest.approx([0.0, 0.5])


def test_nobody_to_cover_means_uncovered_for_the_rest_of_the_tick() -> None:
    t = play(share=[6.0, 6.0], export=[6.0, 6.0], at_s=[300.0, None], can_cover=[True, False])
    [f] = t.failovers
    assert (f.cover_s, f.covered_by) == (None, 0)
    assert f.uncovered_kwh == pytest.approx(6.0 * 600 / 3600)


def test_buffer_runs_out_across_failovers_in_the_same_tick() -> None:
    """Home 1's 6 kW spare covers the first drop-out; the second, later, finds nothing left."""
    t = play(share=[6.0, 6.0, 6.0], export=[6.0, 6.0, 6.0], at_s=[200.0, None, 100.0], can_cover=[True, True, False])
    first, second = t.failovers
    assert (first.home, first.cover_s, first.covered_by) == (2, 11.0, 1)  # in drop-out order
    assert (second.home, second.cover_s, second.covered_by) == (0, None, 0)
    assert second.uncovered_kwh == pytest.approx(6.0 * 700 / 3600)


def test_a_home_that_drops_out_this_tick_covers_nobody() -> None:
    """Home 1 drops out later (at 800 s, no share of its own): it can't cover home 0 at 100 s."""
    t = play(share=[6.0, 0.0], export=[6.0, 0.0], at_s=[100.0, 800.0])
    assert t.failovers[0].covered_by == 0 and t.failovers[0].cover_s is None


def test_a_cover_due_after_the_tick_ends_leaves_the_rest_of_the_tick_uncovered() -> None:
    """Silent at 895 s: cover lands at 906 s, in the next tick's plan. The last 5 s are short."""
    t = play(share=[6.0, 6.0], export=[6.0, 6.0], at_s=[895.0, None])
    [f] = t.failovers
    assert (f.cover_s, f.covered_by) == (11.0, 1)
    assert f.uncovered_kwh == pytest.approx(6.0 * 5 / 3600)
    assert t.cover_kwh.tolist() == [0.0, 0.0]


def test_a_drop_out_without_a_call_share_only_stops_its_own_export() -> None:
    t = play(share=[0.0, 6.0], export=[8.0, 6.0], at_s=[450.0, None])
    assert t.failovers == []
    assert t.exported_kwh.tolist() == pytest.approx([8.0 * 450 / 3600, 6.0 * 0.25])


# --- Who drops out ---------------------------------------------------------------


def drops(
    export: list[float],
    share: list[float],
    floor_room: list[float] | None = None,
    outage_next: list[bool] | None = None,
    fault_at_s: list[float] | None = None,
    notice: float = 0.5,
) -> DropOuts:
    n = len(export)
    return drop_outs(
        export_kw=np.array(export),
        floor_room_kwh=np.array(floor_room or [100.0] * n),
        share_kw=np.array(share),
        outage_next=np.array(outage_next or [False] * n),
        fault_at_s=np.array(fault_at_s or [np.nan] * n),
        rng=np.random.default_rng(0),
        config=FailoverConfig(outage_notice_frac=notice),
    )


def test_device_faults_are_silent_at_their_second() -> None:
    d = drops(export=[6.0, 6.0, 0.0], share=[6.0, 0.0, 0.0], fault_at_s=[300.0, np.nan, 10.0])
    assert d.at_s.tolist() == [300.0, TICK_S, 10.0]
    assert d.warned.tolist() == [False, False, False]


def test_a_home_reaching_its_floor_warns_at_the_second_it_gets_there() -> None:
    """12 kW with 1.5 kWh above the floor: out at 450 s. Exactly 3 kWh lasts the whole tick."""
    d = drops(export=[12.0, 12.0], share=[6.0, 6.0], floor_room=[1.5, 3.0])
    assert d.at_s.tolist() == pytest.approx([450.0, TICK_S])
    assert d.warned.tolist() == [True, False]


@pytest.mark.parametrize(("notice", "warned"), [(1.0, True), (0.0, False)])
def test_a_home_losing_the_grid_next_tick_drops_out_warned_or_silent(notice: float, warned: bool) -> None:
    """Only homes with a call share: the others have no promise to hand over."""
    d = drops(export=[6.0, 6.0], share=[6.0, 0.0], outage_next=[True, True], notice=notice)
    assert 0 <= d.at_s[0] < TICK_S and d.at_s[1] == TICK_S
    assert d.warned.tolist() == [warned, False]


def test_the_earliest_reason_wins() -> None:
    """A silent fault at 100 s beats the floor at 450 s; the floor at 450 s beats a fault at 800 s."""
    d = drops(export=[12.0, 12.0], share=[6.0, 6.0], floor_room=[1.5, 1.5], fault_at_s=[100.0, 800.0])
    assert d.at_s.tolist() == pytest.approx([100.0, 450.0])
    assert d.warned.tolist() == [False, True]
