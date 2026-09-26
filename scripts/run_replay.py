"""Run the full Uri replay headless and print a daily summary.

Usage: uv run python -m scripts.run_replay [--seed N] [--homes N] [--policy contract|naive]
       [--contract-size FRAC | --no-contract]
"""

import argparse
import time

import numpy as np
import pandas as pd

from backend.commitment import UtilityContract
from backend.policy import POLICIES
from backend.sim import HOURS_PER_TICK, FleetConfig, uri_replay


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--homes", type=int, default=FleetConfig().n_homes)
    parser.add_argument("--policy", choices=POLICIES, default="contract")
    parser.add_argument(
        "--contract-size", type=float, default=UtilityContract.size_frac, help="share of fleet nameplate"
    )
    parser.add_argument("--no-contract", action="store_true", help="no utility contract (promised_mw null)")
    args = parser.parse_args()

    contract_size = None if args.no_contract else args.contract_size
    sim = uri_replay(
        seed=args.seed, config=FleetConfig(n_homes=args.homes), policy=args.policy, contract_size=contract_size
    )
    started = time.perf_counter()
    rows = []
    prev_grid = np.ones(args.homes, dtype=bool)
    prev_penalty = 0.0
    while not sim.done:
        r = sim.step()
        rows.append(
            {
                "day": r.frame.t.strftime("%a %b %d"),
                "price": r.frame.price,
                "on_grid": r.homes_on_grid,
                "on_battery": r.homes_on_battery,
                "dark": r.homes_dark,
                "dark_contract": r.homes_dark_by_contract,
                "grid_cuts": int((prev_grid & ~r.grid).sum()),
                "called": r.utility_call,
                "kept": r.utility_call and r.delivered_mw >= (r.promised_mw or 0) - 1e-9,
                "delivered_mw": r.delivered_mw,
                "headroom_mwh": r.headroom_mwh,
                "penalty_usd": r.penalty_usd - prev_penalty,
                "revenue_usd": r.revenue_usd,
            }
        )
        prev_grid = r.grid
        prev_penalty = r.penalty_usd
    elapsed = time.perf_counter() - started

    df = pd.DataFrame(rows)
    daily = df.groupby("day", sort=False).agg(
        price_min=("price", "min"),
        price_max=("price", "max"),
        on_grid_min=("on_grid", "min"),
        on_battery_max=("on_battery", "max"),
        dark_max=("dark", "max"),
        dark_home_h=("dark", lambda d: d.sum() * HOURS_PER_TICK),
        dark_contract_max=("dark_contract", "max"),
        grid_cuts=("grid_cuts", "sum"),
        called=("called", "sum"),
        kept=("kept", "sum"),
        delivered_mw_max=("delivered_mw", "max"),
        headroom_mwh=("headroom_mwh", "mean"),
        penalty_usd=("penalty_usd", "sum"),
        revenue_usd=("revenue_usd", "last"),
    )
    contract = "no contract" if contract_size is None else f"contract {contract_size:.0%} of nameplate"
    print(
        f"Uri replay: {len(df)} ticks, {args.homes} homes, seed {args.seed}, "
        f"{args.policy} policy, {contract}, {elapsed * 1000:.0f} ms\n"
    )
    with pd.option_context("display.width", 200):
        print(daily.round(2).to_string())
    print(f"\nTotal dark home-hours (ran out): {df['dark'].sum() * HOURS_PER_TICK:,.0f}")
    if contract_size is not None:
        kept = "n/a" if r.promise_kept is None else f"{r.promise_kept:.1%}"
        print(f"Called ticks: {df['called'].sum()}, promise kept: {kept}, penalties: ${r.penalty_usd:,.0f}")
        print(f"Headroom (time average): {df['headroom_mwh'].mean():.2f} MWh")
    print(f"Net revenue: ${r.revenue_usd:,.0f}")
    print("\nPer day: min/max price ($/MWh), min homes on grid, max homes on battery / dark (ran out), dark")
    print("home-hours, max homes dark by contract, grid cuts (times a home lost the grid), called/kept ticks,")
    print("max delivered MW, mean headroom MWh, penalties that day ($), cumulative net revenue at end of day ($).")


if __name__ == "__main__":
    main()
