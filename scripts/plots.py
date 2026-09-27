"""README charts from the insight sweep: results/sweep.csv -> docs/img/*.png.

Colours are the UI's tokens (frontend/src/index.css) on its dark surface; the storm amber is the
backup token toned down to pass the dataviz palette checks against that surface.

Usage: uv run python -m scripts.plots [--csv results/sweep.csv] [--out docs/img]
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import PercentFormatter  # noqa: E402

SURFACE = "#1c1b1a"
TEXT = "#f0eeeb"
MUTED = "#8c8a87"
BORDER = "#3a3937"
PRE_STORM = "#048ee5"  # --accent / --state-export
STORM = "#b8891f"  # --state-backup, toned down
NORMAL = "#26a08f"  # teal: passes the palette checks next to both (the UI's grid green is too close to the amber)
CONTRACT_10 = "#ddb04a"  # storm amber, light -> dark as the contract grows
CONTRACT_30 = "#9a7316"
SPREAD = "#048ee5"  # --accent: the failure-domain split, next to the storm amber for the default
FAULT_RATE = 0.001
"""Both charts use the default device fault rate, per home-hour."""


def style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "text.color": TEXT,
            "axes.labelcolor": MUTED,
            "axes.edgecolor": BORDER,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "axes.axisbelow": True,
            "grid.color": BORDER,
            "grid.linewidth": 0.6,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.spines.left": False,
            "font.size": 11,
            "axes.titlesize": 13,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "legend.frameon": False,
        }
    )


def titled(fig: plt.Figure, ax: plt.Axes, title: str, subtitle: str) -> None:
    ax.set_title(title, pad=14 + 14 * (subtitle.count("\n") + 1))
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, color=MUTED, fontsize=10, va="bottom")


def fleet_size(runs: pd.DataFrame) -> str:
    (homes,) = runs["homes"].unique()
    return f"{homes:,}"


def safe_contract(df: pd.DataFrame, out: Path) -> None:
    """Promise kept vs contract size: Uri pre-storm and storm, and the normal winter week; mean over
    seeds, min-max band. The normal week is drawn first, with larger square markers, because it
    coincides with pre-storm at 100%."""
    runs = df[(df["variant"] == "default") & (df["fault_rate"] == FAULT_RATE)]
    uri, normal = runs[runs["scenario"] == "uri"], runs[runs["scenario"] == "normal"]
    fig, ax = plt.subplots(figsize=(9, 5))
    lines = (
        (normal, "kept", "Normal winter week (Feb 21–27, 2022)", NORMAL, "s", 12),
        (uri, "pre_kept", "Uri, pre-storm (Feb 10–12)", PRE_STORM, "o", 7),
        (uri, "storm_kept", "Uri, storm (Feb 14–18)", STORM, "o", 8),
    )
    for data, col, label, color, marker, size in lines:
        g = data.groupby("contract")[col].agg(["mean", "min", "max"]) * 100
        x = g.index * 100
        ax.fill_between(x, g["min"], g["max"], color=color, alpha=0.18, linewidth=0)
        ax.plot(x, g["mean"], color=color, linewidth=2, marker=marker, markersize=size, markeredgecolor=SURFACE,
                markeredgewidth=2, label=label)
    storm = uri.groupby("contract")["storm_kept"].mean() * 100
    ax.annotate(f"{storm.iloc[0]:.1f}%", (storm.index[0] * 100, storm.iloc[0]), xytext=(-9, 0),
                textcoords="offset points", color=TEXT, fontsize=10, ha="right", va="center",
                bbox={"facecolor": SURFACE, "edgecolor": "none", "pad": 1})
    ax.axhline(95, color=MUTED, linewidth=1, linestyle=(0, (4, 3)))
    ax.text(63.5, 94, "95%", color=MUTED, fontsize=10, ha="right", va="top")
    ax.set_xlabel("Contract size, % of fleet nameplate")
    ax.set_ylabel("Promise kept, % of called intervals")
    ax.set_xticks(storm.index * 100)
    ax.xaxis.set_major_formatter(PercentFormatter(decimals=0))
    ax.yaxis.set_major_formatter(PercentFormatter(decimals=0))
    ax.set_ylim(0, 105)
    ax.set_xlim(2, 64)
    ax.legend(loc="lower left")
    titled(fig, ax, "In a normal week every size keeps its promise; in Uri's storm only 10% stays above 95%",
           f"{fleet_size(runs)} homes, seeds 0–2, mean with min–max band, device faults {FAULT_RATE:g}/home-h. "
           "Called intervals:\n"
           "normal week 6, pre-storm 5, storm 30. The normal-week and pre-storm lines coincide at 100%.")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


def backup_vs_promise(df: pd.DataFrame, out: Path) -> None:
    """Storm promise kept by standard-tier backup hours, at 10% and 30%, labelled with the reserve recharge cost."""
    variants = ("default", "standard backup 4 h", "standard backup 12 h")
    runs = df[
        (df["scenario"] == "uri")
        & df["variant"].isin(variants)
        & (df["fault_rate"] == FAULT_RATE)
        & df["contract"].isin((0.1, 0.3))
    ]
    g = runs.groupby(["contract", "backup_standard_h"])[["storm_kept", "reserve_recharge_usd"]].mean()
    hours = sorted(runs["backup_standard_h"].unique())
    width = 0.38
    fig, ax = plt.subplots(figsize=(8, 4.6))
    for k, (contract, color) in enumerate(((0.1, CONTRACT_10), (0.3, CONTRACT_30))):
        rows = g.loc[contract].reindex(hours)
        x = [i + (k - 0.5) * width for i in range(len(hours))]
        kept = rows["storm_kept"] * 100
        ax.bar(x, kept, width, color=color, edgecolor=SURFACE, linewidth=2, label=f"Contract {contract:.0%}")
        for xi, v, usd in zip(x, kept, rows["reserve_recharge_usd"], strict=True):
            ax.text(xi, v + 1.5, f"{v:.1f}%\n${usd / 1000:,.0f}k", ha="center", va="bottom", fontsize=9,
                    color=TEXT, linespacing=1.3)
    ax.set_xticks(range(len(hours)), [f"{h:g} h" + (" (default)" if h == 8 else "") for h in hours])
    ax.set_xlabel("Standard-tier backup reserve, hours at the forecast temperature")
    ax.set_ylabel("Storm promise kept, % of called intervals")
    ax.yaxis.set_major_formatter(PercentFormatter(decimals=0))
    ax.set_ylim(0, 128)
    ax.set_yticks(range(0, 101, 20))
    ax.tick_params(axis="x", length=0)
    ax.legend(loc="upper right", ncols=2)
    titled(fig, ax, "A smaller backup reserve keeps more storm promises and costs less to refill",
           "Labels: storm promise kept / reserve recharge cost over the replay.\n"
           f"{fleet_size(runs)} homes, seeds 0–2 mean, device faults {FAULT_RATE:g}/home-h.")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


def failure_domains(df: pd.DataFrame, out: Path) -> None:
    """Storm promise kept and uncovered failovers by contract size, the default split (pro rata to
    charge) vs spread by failure domain; mean over seeds with min-max whiskers."""
    runs = df[
        (df["scenario"] == "uri")
        & (df["fault_rate"] == FAULT_RATE)
        & df["variant"].isin(("default", "spread by domain"))
        & df["contract"].isin((0.1, 0.2, 0.3))
    ]
    contracts = sorted(runs["contract"].unique())
    width = 0.38
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.6))
    panels = (
        (axes[0], "storm_kept", 100, "Storm promise kept, % of called intervals", "{:.1f}%"),
        (axes[1], "storm_failovers_uncovered", 1, "Uncovered failovers in the storm", "{:.0f}"),
    )
    series = (
        (False, STORM, "Pro rata to charge, 20% buffer (default)"),
        (True, SPREAD, "Spread by outage block, N-1 buffer"),
    )
    for ax, col, scale, label, fmt in panels:
        top = runs[col].max() * scale
        for k, (spread, color, name) in enumerate(series):
            g = runs[runs["spread_by_domain"] == spread].groupby("contract")[col].agg(["mean", "min", "max"]) * scale
            g = g.reindex(contracts)
            x = np.arange(len(contracts)) + (k - 0.5) * width
            ax.bar(x, g["mean"], width, color=color, edgecolor=SURFACE, linewidth=2, label=name)
            ax.errorbar(x, g["mean"], yerr=[g["mean"] - g["min"], g["max"] - g["mean"]], fmt="none", ecolor=MUTED,
                        elinewidth=1, capsize=3)
            for xi, mean, high in zip(x, g["mean"], g["max"], strict=True):
                ax.text(xi, high + 0.03 * top, fmt.format(mean), ha="center", va="bottom", fontsize=9, color=TEXT)
        ax.set_xticks(range(len(contracts)), [f"{c:.0%}" for c in contracts])
        ax.set_xlabel("Contract size, % of fleet nameplate")
        ax.set_title(label, fontsize=11, fontweight="normal", color=TEXT)
        ax.set_ylim(0, top * 1.18)
        ax.tick_params(axis="x", length=0)
    axes[0].yaxis.set_major_formatter(PercentFormatter(decimals=0))
    axes[0].axhline(95, color=MUTED, linewidth=1, linestyle=(0, (4, 3)))
    axes[0].set_yticks(range(0, 101, 20))
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower left", bbox_to_anchor=(0.0, 0.93), ncols=2, fontsize=10)
    fig.text(0.0, 1.10, "Splitting calls by outage block only helps the 10% contract", fontsize=13,
             fontweight="bold", color=TEXT)
    fig.text(0.0, 1.03, f"Uri storm (Feb 14–18), {fleet_size(runs)} homes, seeds 0–2 mean with min–max whiskers, "
             f"device faults {FAULT_RATE:g}/home-h. Dashed: 95%.", fontsize=10, color=MUTED)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--csv", type=Path, default=Path("results/sweep.csv"))
    parser.add_argument("--out", type=Path, default=Path("docs/img"))
    args = parser.parse_args(argv)
    df = pd.read_csv(args.csv)
    args.out.mkdir(parents=True, exist_ok=True)
    style()
    safe_contract(df, args.out / "safe-contract.png")
    backup_vs_promise(df, args.out / "backup-vs-promise.png")
    failure_domains(df, args.out / "failure-domains.png")
    print(f"Wrote safe-contract.png, backup-vs-promise.png and failure-domains.png to {args.out}")


if __name__ == "__main__":
    main()
