"""The safe contract: the largest utility contract the fleet can promise and keep through the storm.

Replays every contract size in `CONTRACTS`, and no contract (the baseline), for each of `SEEDS`
in a process pool; summarises each replay, averages over the seeds and applies `safest`.
"""

import asyncio
import functools
import math
from collections.abc import Sequence
from concurrent.futures import Executor
from dataclasses import dataclass

import numpy as np

from backend.data import Frame, UriParquetSource
from backend.schema import SafeContractPoint, SafeContractResponse, ScenarioParams
from backend.serialize import build_sim

CONTRACTS = tuple(round(0.05 * k, 2) for k in range(1, 13))
"""0.05 to 0.60 of nameplate."""
SEEDS = (0, 1, 2)
SAFE_KEPT = 0.95
"""A safe contract keeps at least this share of its storm calls..."""
KEPT_SLACK = 1e-9
"""...within float error of a mean over seeds."""


@dataclass(frozen=True, slots=True)
class Summary:
    """What the safe rule needs from one replay."""

    storm_kept: float
    """Share of storm-window called intervals kept; NaN with no storm calls."""
    pre_kept: float
    contract_pnl_usd: float
    backup_cost_usd: float
    uncovered: int
    critical_ran_out: int
    """Critical-tier homes that were off grid with an empty battery at some point."""


@functools.cache
def uri_frames() -> list[Frame]:
    """Read once per worker process."""
    return UriParquetSource().frames()


def summarise(params: ScenarioParams, contract: float | None, seed: int) -> Summary:
    """One headless replay (runs in a worker process)."""
    sim = build_sim(params, contract, seed, uri_frames())
    critical = sim.fleet.tier == "critical"
    ran_out = np.zeros(len(sim.fleet), dtype=bool)
    windows = {"pre": UriParquetSource.PRE_STORM, "storm": UriParquetSource.STORM}
    called = dict.fromkeys(windows, 0)
    kept = dict.fromkeys(windows, 0)
    while not sim.done:
        r = sim.step()
        ran_out |= critical & ~r.grid & (r.soc == 0)
        for name, (start, end) in windows.items():
            if r.utility_call and start <= r.frame.t < end:
                called[name] += 1
                kept[name] += r.kept
    share = {name: kept[name] / called[name] if called[name] else math.nan for name in windows}
    return Summary(
        storm_kept=share["storm"],
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
        storm_kept=mean_or_none([r.storm_kept for r in runs]),
        pre_kept=mean_or_none([r.pre_kept for r in runs]),
        contract_pnl_usd=round(float(np.mean([r.contract_pnl_usd for r in runs])), 2),
        backup_cost_usd=round(float(np.mean([r.backup_cost_usd for r in runs])), 2),
        uncovered=float(np.mean([r.uncovered for r in runs])),
        critical_ran_out=float(np.mean([r.critical_ran_out for r in runs])),
    )


def safest(curve: Sequence[SafeContractPoint], baseline_critical_ran_out: float) -> float | None:
    """The largest contract that keeps at least `SAFE_KEPT` of its storm calls (vacuously, with none)
    and runs out no more critical homes than no contract does; None if no contract qualifies."""
    return max(
        (
            p.contract
            for p in curve
            if (p.storm_kept is None or p.storm_kept >= SAFE_KEPT - KEPT_SLACK)
            and p.critical_ran_out <= baseline_critical_ran_out
        ),
        default=None,
    )


async def safe_contract(params: ScenarioParams, pool: Executor) -> SafeContractResponse:
    """Every contract in `CONTRACTS` and the no-contract baseline, x `SEEDS`, replayed in `pool`."""
    loop = asyncio.get_running_loop()
    contracts = (None, *CONTRACTS)
    jobs = [(c, s) for c in contracts for s in SEEDS]
    summaries = await asyncio.gather(*(loop.run_in_executor(pool, summarise, params, c, s) for c, s in jobs))
    runs = {c: [r for (rc, _), r in zip(jobs, summaries, strict=True) if rc == c] for c in contracts}
    baseline = float(np.mean([r.critical_ran_out for r in runs[None]]))
    curve = [point(c, runs[c]) for c in CONTRACTS]
    return SafeContractResponse(
        params=params,
        seeds=list(SEEDS),
        curve=curve,
        baseline_critical_ran_out=baseline,
        safe=safest(curve, baseline),
    )
