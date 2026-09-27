"""Insight sweep: many headless replays, one row per run in results/sweep.csv.

Uri: contract size x device fault rate x seeds, plus one-at-a-time variants of the other knobs at
two contract sizes (docs/dispatch-design.md, "Insight experiment") and the failure-domain split at
three. The normal winter week: the
same contract x fault rate x seeds grid. Every metric is reported for the whole replay and, for
Uri, for the pre-storm and storm windows (`pre_*`, `storm_*` columns; empty for the normal week).
Fleets are the served replay's size (`ReplayParams().homes`); runs go to a process pool.

Usage: uv run python -m scripts.sweep [--out results/sweep.csv]
"""

import argparse
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from backend.commitment import UtilityContract
from backend.data import UriParquetSource
from backend.faults import SilentDeviceFaults
from backend.policy import ContractPolicy
from backend.schema import ReplayParams, ScenarioName
from backend.sim import HOURS_PER_TICK, FleetConfig, build_replay

CONTRACTS = (0.1, 0.2, 0.3, 0.4, 0.6)
FAULT_RATES = (0.001, 0.005)
SEEDS = (0, 1, 2)
HOMES = ReplayParams().homes
VARIANT_CONTRACTS = (0.1, 0.3)
"""The variants run at these contract sizes, the default fault rate and every seed..."""
DOMAIN_CONTRACTS = (0.1, 0.2, 0.3)
"""...except "spread by domain", at these."""


WINDOWS = {"": None, "pre_": UriParquetSource.PRE_STORM, "storm_": UriParquetSource.STORM}
"""Column prefix -> [start, end) Central time; "" is the whole replay (Feb 10-20)."""


@dataclass(frozen=True)
class Run:
    scenario: ScenarioName
    contract: float
    """Contract size, share of fleet nameplate."""
    fault_rate: float
    """Silent device faults per home-hour."""
    seed: int
    homes: int = HOMES
    variant: str = "default"
    trigger_usd: float = UtilityContract.trigger_usd
    backup_standard_h: float = dict(FleetConfig().backup_hours)["standard"]
    precharge: bool = ContractPolicy().precharge
    skip_before_storm: bool = UtilityContract.skip_before_storm
    headroom_mode: str = ContractPolicy().headroom_mode
    spread_by_domain: bool = ContractPolicy().spread_by_domain


VARIANTS = {
    "trigger $500": {"trigger_usd": 500.0},
    "trigger $3,000": {"trigger_usd": 3000.0},
    "standard backup 4 h": {"backup_standard_h": 4.0},
    "standard backup 12 h": {"backup_standard_h": 12.0},
    "precharge off": {"precharge": False},
    "skip before storm": {"skip_before_storm": True},
    "sell headroom": {"headroom_mode": "sell"},
    "spread by domain": {"spread_by_domain": True},
}
"""One knob changed from the default each."""


def runs() -> list[Run]:
    grid = [Run(sc, c, f, s) for sc in ("uri", "normal") for c in CONTRACTS for f in FAULT_RATES for s in SEEDS]
    base = SilentDeviceFaults.rate_per_home_hour
    variants = [
        replace(Run("uri", c, base, s), variant=name, **knobs)
        for name, knobs in VARIANTS.items()
        for c in (DOMAIN_CONTRACTS if name == "spread by domain" else VARIANT_CONTRACTS)
        for s in SEEDS
    ]
    return grid + variants


def replay(run: Run) -> dict:
    """One replay; its row: the run's knobs, then every metric per window."""
    sim = build_replay(
        scenario=run.scenario,
        seed=run.seed,
        config=FleetConfig(n_homes=run.homes).with_backup_hours("standard", run.backup_standard_h),
        contract_size=run.contract,
        fault_rate=run.fault_rate,
        policy_options={
            "precharge": run.precharge,
            "headroom_mode": run.headroom_mode,
            "spread_by_domain": run.spread_by_domain,
        },
        trigger_usd=run.trigger_usd,
        skip_before_storm=run.skip_before_storm,
    )
    critical = sim.fleet.tier == "critical"
    ticks, critical_dark, events = [], [], []
    prev_penalty = prev_contract = prev_backup = 0.0
    while not sim.done:
        r = sim.step()
        ticks.append(
            {
                "t": r.frame.t,
                "called": r.utility_call,
                "kept": r.kept,
                "penalty_usd": r.penalty_usd - prev_penalty,
                "dark": r.homes_dark,
                "headroom_mwh": r.headroom_mwh,
                "headroom_sold_mwh": r.headroom_sold_mwh,
                "revenue_usd": r.revenue_tick_usd,
                "reserve_recharge_usd": r.reserve_recharge_usd,
                "contract_pnl_usd": r.contract_pnl_usd - prev_contract,
                "backup_cost_usd": r.backup_cost_usd - prev_backup,
            }
        )
        critical_dark.append(~r.grid & (r.soc == 0) & critical)
        events += [(r.frame.t, f) for f in r.failovers]
        prev_penalty, prev_contract, prev_backup = r.penalty_usd, r.contract_pnl_usd, r.backup_cost_usd
    df = pd.DataFrame(ticks)
    dark = np.array(critical_dark)

    row = asdict(run)
    for prefix, window in WINDOWS.items():
        if prefix and run.scenario != "uri":  # the storm windows are Uri's; "" (first) set `metrics`
            row |= {prefix + k: np.nan for k in metrics}
            continue
        if window is None:
            in_window = np.ones(len(df), dtype=bool)
        else:
            in_window = ((df["t"] >= window[0]) & (df["t"] < window[1])).to_numpy()
        w = df[in_window]
        fs = [f for t, f in events if window is None or window[0] <= t < window[1]]
        covered = [f.cover_s for f in fs if f.cover_s is not None]
        called = int(w["called"].sum())
        metrics = {
            "called_ticks": called,
            "kept": w["kept"].sum() / called if called else np.nan,
            "penalty_usd": w["penalty_usd"].sum(),
            "failovers_warned": sum(f.warned for f in fs),
            "failovers_silent": sum(not f.warned for f in fs),
            "failovers_uncovered": sum(f.cover_s is None for f in fs),
            "cover_p50_s": float(np.median(covered)) if covered else np.nan,
            "cover_max_s": max(covered) if covered else np.nan,
            "dark_home_h": w["dark"].sum() * HOURS_PER_TICK,
            "critical_ran_out": int(dark[in_window].any(axis=0).sum()),
            "headroom_mwh_avg": w["headroom_mwh"].mean(),
            "headroom_sold_mwh": w["headroom_sold_mwh"].sum(),
            "net_revenue_usd": w["revenue_usd"].sum(),
            "reserve_recharge_usd": w["reserve_recharge_usd"].sum(),
            "contract_pnl_usd": w["contract_pnl_usd"].sum(),
            "backup_cost_usd": w["backup_cost_usd"].sum(),
        }
        row |= {prefix + k: v for k, v in metrics.items()}
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("results/sweep.csv"))
    args = parser.parse_args()

    started = time.perf_counter()
    plan = runs()
    with ProcessPoolExecutor() as pool:
        df = pd.DataFrame(pool.map(replay, plan))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    elapsed = time.perf_counter() - started
    print(f"{len(plan)} runs of {HOMES:,} homes in {elapsed:.0f} s -> {args.out}\n")

    grid = df[(df["variant"] == "default") & (df["scenario"] == "uri")]
    pivot = grid.pivot_table(
        index="contract", columns="fault_rate", values=["pre_kept", "storm_kept", "kept"], aggfunc="mean"
    )
    pivot = pivot.reorder_levels([1, 0], axis=1).sort_index(axis=1, level=0, sort_remaining=False)
    pivot = pivot.reindex(columns=[(f, k) for f in FAULT_RATES for k in ("pre_kept", "storm_kept", "kept")])
    print("Uri: promise kept by contract size x window (mean over seeds), per device fault rate /home-h:")
    print((pivot * 100).round(1).to_string())
    normal = df[df["scenario"] == "normal"].assign(kept=lambda d: d["kept"] * 100)
    normal = normal.pivot_table(
        index="contract", columns="fault_rate", values=["called_ticks", "kept", "net_revenue_usd"], aggfunc="mean"
    )
    print("\nNormal winter week: called ticks, promise kept (%) and net revenue ($), mean over seeds:")
    print(normal.round(1).to_string())

    base = SilentDeviceFaults.rate_per_home_hour
    uri = df[(df["scenario"] == "uri") & (df["fault_rate"] == base)]
    at = uri[uri["contract"].isin(VARIANT_CONTRACTS) & (uri["variant"] != "spread by domain")]
    table = at.groupby(["contract", "variant"], sort=False)[
        [
            "called_ticks",
            "pre_kept",
            "storm_kept",
            "kept",
            "penalty_usd",
            "storm_dark_home_h",
            "critical_ran_out",
            "headroom_mwh_avg",
            "reserve_recharge_usd",
            "net_revenue_usd",
        ]
    ].mean()
    table = table.sort_index(level=0, sort_remaining=False)
    table[["pre_kept", "storm_kept", "kept"]] *= 100
    print(f"\nVariants at fault rate {base:g} /home-h (mean over seeds; kept in %, $ and home-h totals):")
    with pd.option_context("display.width", 200):
        print(table.round(1).to_string())

    domains = uri[uri["contract"].isin(DOMAIN_CONTRACTS) & uri["variant"].isin(["default", "spread by domain"])]
    columns = ["storm_kept", "storm_failovers_uncovered", "storm_cover_p50_s", "storm_cover_max_s", "contract_pnl_usd"]
    table = domains.groupby(["contract", "spread_by_domain"])[columns].mean()
    table["storm_kept"] *= 100
    print(
        f"\nFailure domains, Uri at fault rate {base:g} /home-h "
        "(mean over seeds; storm window, contract P&L whole replay):"
    )
    with pd.option_context("display.width", 200):
        print(table.round(1).to_string())


if __name__ == "__main__":
    main()
