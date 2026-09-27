"""The safe contract: the largest utility contract the fleet can promise and keep, per scenario.

Replays every contract size in `CONTRACTS`, and no contract (the baseline), for each of `SEEDS`
and each scenario in `SCENARIOS`, in a process pool; summarises each replay, averages over the
seeds and applies `safest`.
"""

import asyncio
import math
from collections.abc import Sequence
from concurrent.futures import Executor
from dataclasses import dataclass
from typing import get_args

import numpy as np

from backend.schema import SafeContractCurve, SafeContractPoint, SafeContractResponse, ScenarioName, SweepParams
from backend.serialize import build_sim
from backend.sim import SCENARIOS

CONTRACTS = tuple(round(0.05 * k, 2) for k in range(1, 13))
"""0.05 to 0.60 of nameplate."""
SEEDS = (0, 1, 2)
SCENARIO_ORDER: tuple[ScenarioName, ...] = get_args(ScenarioName)
SAFE_KEPT = 0.95
"""A safe contract keeps at least this share of its calls in the scenario's test window..."""
KEPT_SLACK = 1e-9
"""...within float error of a mean over seeds."""


@dataclass(frozen=True, slots=True)
class Summary:
    """What the safe rule needs from one replay."""

    kept: float
    """Share of called intervals kept in the scenario's test window; NaN with no calls there."""
    pre_kept: float
    """The same in its pre window; NaN with none, or no calls there."""
    contract_pnl_usd: float
    backup_cost_usd: float
    uncovered: int
    critical_ran_out: int
    """Critical-tier homes that were off grid with an empty battery at some point."""


def summarise(params: SweepParams, scenario: ScenarioName, contract: float | None, seed: int) -> Summary:
    """One headless replay (runs in a worker process)."""
    sim = build_sim(params, scenario, contract, seed)
    source = SCENARIOS[scenario].source
    critical = sim.fleet.tier == "critical"
    ran_out = np.zeros(len(sim.fleet), dtype=bool)
    windows = {"test": source.TEST_WINDOW, "pre": source.PRE_WINDOW}
    called = dict.fromkeys(windows, 0)
    kept = dict.fromkeys(windows, 0)
    while not sim.done:
        r = sim.step()
        ran_out |= critical & ~r.grid & (r.soc == 0)
        for name, window in windows.items():
            if r.utility_call and window is not None and window[0] <= r.frame.t < window[1]:
                called[name] += 1
                kept[name] += r.kept
    share = {name: kept[name] / called[name] if called[name] else math.nan for name in windows}
    return Summary(
        kept=share["test"],
        pre_kept=share["pre"],
        contract_pnl_usd=sim.contract_pnl_usd,
        backup_cost_usd=sim.backup_cost_usd,
        uncovered=sim.failovers_uncovered,
        critical_ran_out=int(ran_out.sum()),
    )


def mean_or_none(values: Sequence[float]) -> float | None:
    """Mean of the non-NaN values; None if there are none."""
    kept = [v for v in values if not math.isnan(v)]
    return sum(kept) / len(kept) if kept else None


def point(contract: float, runs: Sequence[Summary]) -> SafeContractPoint:
    return SafeContractPoint(
        contract=contract,
        kept=mean_or_none([r.kept for r in runs]),
        pre_kept=mean_or_none([r.pre_kept for r in runs]),
        contract_pnl_usd=round(float(np.mean([r.contract_pnl_usd for r in runs])), 2),
        backup_cost_usd=round(float(np.mean([r.backup_cost_usd for r in runs])), 2),
        uncovered=float(np.mean([r.uncovered for r in runs])),
        critical_ran_out=float(np.mean([r.critical_ran_out for r in runs])),
    )


def safest(curve: Sequence[SafeContractPoint], baseline_critical_ran_out: float) -> float | None:
    """The largest contract that keeps at least `SAFE_KEPT` of its calls (vacuously, with none)
    and runs out no more critical homes than no contract does; None if no contract qualifies."""
    return max(
        (
            p.contract
            for p in curve
            if (p.kept is None or p.kept >= SAFE_KEPT - KEPT_SLACK) and p.critical_ran_out <= baseline_critical_ran_out
        ),
        default=None,
    )


async def safe_contract(params: SweepParams, pool: Executor) -> SafeContractResponse:
    """Every scenario x (every contract in `CONTRACTS` and the no-contract baseline) x `SEEDS`, in `pool`."""
    loop = asyncio.get_running_loop()
    contracts = (None, *CONTRACTS)
    jobs = [(sc, c, s) for sc in SCENARIO_ORDER for c in contracts for s in SEEDS]
    summaries = await asyncio.gather(*(loop.run_in_executor(pool, summarise, params, *job) for job in jobs))
    runs: dict[tuple[ScenarioName, float | None], list[Summary]] = {}
    for (scenario, contract, _), summary in zip(jobs, summaries, strict=True):
        runs.setdefault((scenario, contract), []).append(summary)
    curves = []
    for scenario in SCENARIO_ORDER:
        baseline = float(np.mean([r.critical_ran_out for r in runs[scenario, None]]))
        curve = [point(c, runs[scenario, c]) for c in CONTRACTS]
        curves.append(
            SafeContractCurve(
                scenario=scenario, curve=curve, baseline_critical_ran_out=baseline, safe=safest(curve, baseline)
            )
        )
    return SafeContractResponse(params=params, seeds=list(SEEDS), scenarios=curves)
