"""The safe-contract rule, the seed average, and one replay's summary."""

import math

import pytest

from backend.safe_contract import CONTRACTS, Summary, point, safest, summarise
from backend.schema import SafeContractPoint, ScenarioParams


def at(contract: float, storm_kept: float | None, critical_ran_out: float = 4.0) -> SafeContractPoint:
    return SafeContractPoint(
        contract=contract,
        storm_kept=storm_kept,
        pre_kept=1.0,
        contract_pnl_usd=0.0,
        backup_cost_usd=0.0,
        uncovered=0.0,
        critical_ran_out=critical_ran_out,
    )


def test_contracts_run_from_5_to_60_percent_in_steps_of_5() -> None:
    assert CONTRACTS == (0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6)


def test_safe_is_the_largest_contract_that_keeps_95_percent() -> None:
    curve = [at(0.05, 1.0), at(0.1, 0.97), at(0.15, 0.95), at(0.2, 0.9), at(0.25, 0.8)]
    assert safest(curve, baseline_critical_ran_out=4.0) == 0.15  # exactly 95% counts


def test_safe_is_the_largest_not_the_last_before_the_first_failure() -> None:
    curve = [at(0.05, 1.0), at(0.1, 0.9), at(0.15, 0.96)]
    assert safest(curve, baseline_critical_ran_out=4.0) == 0.15


def test_a_contract_that_runs_out_more_critical_homes_than_no_contract_is_not_safe() -> None:
    curve = [at(0.05, 1.0), at(0.1, 1.0, critical_ran_out=4 + 1 / 3), at(0.15, 0.94)]
    assert safest(curve, baseline_critical_ran_out=4.0) == 0.05


def test_a_contract_never_called_in_the_storm_is_vacuously_kept() -> None:
    assert safest([at(0.05, None), at(0.1, None)], baseline_critical_ran_out=4.0) == 0.1


def test_no_safe_contract() -> None:
    assert safest([at(0.05, 0.9), at(0.1, 1.0, critical_ran_out=5)], baseline_critical_ran_out=4.0) is None
    assert safest([], baseline_critical_ran_out=4.0) is None


def test_point_averages_seeds_and_skips_seeds_without_calls() -> None:
    runs = [
        Summary(storm_kept=0.9, pre_kept=math.nan, contract_pnl_usd=100.0, backup_cost_usd=10.0, uncovered=1,
                critical_ran_out=2),
        Summary(storm_kept=1.0, pre_kept=math.nan, contract_pnl_usd=200.0, backup_cost_usd=20.0, uncovered=2,
                critical_ran_out=5),
    ]
    p = point(0.1, runs)
    assert p.storm_kept == pytest.approx(0.95) and p.pre_kept is None
    assert (p.contract_pnl_usd, p.backup_cost_usd, p.uncovered, p.critical_ran_out) == (150.0, 15.0, 1.5, 3.5)


def test_summary_of_a_replay_with_and_without_a_contract() -> None:
    params = ScenarioParams(homes=50)
    none = summarise(params, None, seed=0)
    assert math.isnan(none.storm_kept) and math.isnan(none.pre_kept)
    assert none.contract_pnl_usd == 0 and none.uncovered == 0
    small = summarise(params, 0.05, seed=0)
    assert 0 < small.storm_kept <= 1 and small.pre_kept == 1.0
    assert small.contract_pnl_usd != 0 and small.backup_cost_usd > 0
