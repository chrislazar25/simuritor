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
import pandas as pd  # noqa: E402
from matplotlib.ticker import PercentFormatter  # noqa: E402

SURFACE = "#1c1b1a"
TEXT = "#f0eeeb"
MUTED = "#8c8a87"
BORDER = "#3a3937"
PRE_STORM = "#048ee5"  # --accent / --state-export
STORM = "#b8891f"  # --state-backup, toned down
CONTRACT_10 = "#ddb04a"  # storm amber, light -> dark as the contract grows
CONTRACT_30 = "#9a7316"
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
    ax.set_title(title, pad=28)
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, color=MUTED, fontsize=10, va="bottom")


def safe_contract(df: pd.DataFrame, out: Path) -> None:
    """Promise kept vs contract size, pre-storm and storm: mean over seeds, min-max band."""
    runs = df[(df["variant"] == "default") & (df["fault_rate"] == FAULT_RATE)]
    fig, ax = plt.subplots(figsize=(8, 4.6))
    windows = (("pre_kept", "Pre-storm (Feb 10–12)", PRE_STORM), ("storm_kept", "Storm (Feb 14–18)", STORM))
    for col, label, color in windows:
        g = runs.groupby("contract")[col].agg(["mean", "min", "max"]) * 100
        x = g.index * 100
        ax.fill_between(x, g["min"], g["max"], color=color, alpha=0.18, linewidth=0)
        ax.plot(x, g["mean"], color=color, linewidth=2, marker="o", markersize=8, markeredgecolor=SURFACE,
                markeredgewidth=2, label=label)
    storm = runs.groupby("contract")["storm_kept"].mean() * 100
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
    titled(fig, ax, "Before the storm every size keeps its promise; in it, only 10% stays above 95%",
           f"Seeds 0–2, mean with min–max band. Device faults {FAULT_RATE:g}/home-h. "
           "Pre-storm has 5 called intervals, the storm 30.")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


def backup_vs_promise(df: pd.DataFrame, out: Path) -> None:
    """Storm promise kept by standard-tier backup hours, at 10% and 30%, labelled with the reserve recharge cost."""
    variants = ("default", "standard backup 4 h", "standard backup 12 h")
    runs = df[df["variant"].isin(variants) & (df["fault_rate"] == FAULT_RATE) & df["contract"].isin((0.1, 0.3))]
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
            ax.text(xi, v + 1.5, f"{v:.1f}%\n${usd / 1000:.0f}k", ha="center", va="bottom", fontsize=9,
                    color=TEXT, linespacing=1.3)
    ax.set_xticks(range(len(hours)), [f"{h:g} h" + (" (default)" if h == 8 else "") for h in hours])
    ax.set_xlabel("Standard-tier backup reserve, hours at the forecast temperature")
    ax.set_ylabel("Storm promise kept, % of called intervals")
    ax.yaxis.set_major_formatter(PercentFormatter(decimals=0))
    ax.set_ylim(0, 118)
    ax.set_yticks(range(0, 101, 20))
    ax.tick_params(axis="x", length=0)
    ax.legend(loc="upper right", ncols=2)
    titled(fig, ax, "A smaller backup reserve keeps more storm promises and costs less to refill",
           "Labels: storm promise kept / reserve recharge cost over the replay. "
           f"Seeds 0–2 mean, device faults {FAULT_RATE:g}/home-h.")
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
    print(f"Wrote {args.out}/safe-contract.png and {args.out}/backup-vs-promise.png")


if __name__ == "__main__":
    main()
