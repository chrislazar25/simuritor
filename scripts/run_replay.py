"""Run the full Uri replay headless and print a daily summary.

Usage: uv run python -m scripts.run_replay [--seed N] [--homes N]
"""

import argparse
import time

import pandas as pd

from backend.sim import FleetConfig, uri_replay


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--homes", type=int, default=FleetConfig().n_homes)
    args = parser.parse_args()

    sim = uri_replay(seed=args.seed, config=FleetConfig(n_homes=args.homes))
    started = time.perf_counter()
    rows = []
    while not sim.done:
        r = sim.step()
        rows.append(
            {
                "day": r.frame.t.strftime("%a %b %d"),
                "price": r.frame.price,
                "on_grid": r.homes_on_grid,
                "on_battery": r.homes_on_battery,
                "dark": r.homes_dark,
                "delivered_mw": r.delivered_mw,
                "revenue_usd": r.revenue_usd,
            }
        )
    elapsed = time.perf_counter() - started

    df = pd.DataFrame(rows)
    daily = df.groupby("day", sort=False).agg(
        price_min=("price", "min"),
        price_max=("price", "max"),
        on_grid_min=("on_grid", "min"),
        on_battery_max=("on_battery", "max"),
        dark_max=("dark", "max"),
        delivered_mw_max=("delivered_mw", "max"),
        revenue_usd=("revenue_usd", "last"),
    )
    print(f"Uri replay: {len(df)} ticks, {args.homes} homes, seed {args.seed}, {elapsed * 1000:.0f} ms\n")
    print(daily.round(2).to_string())
    print("\nPer day: min/max price ($/MWh), min homes on grid, max on battery / dark, max delivered MW,")
    print("cumulative revenue at end of day ($).")


if __name__ == "__main__":
    main()
