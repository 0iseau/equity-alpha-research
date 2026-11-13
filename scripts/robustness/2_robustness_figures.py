"""Figures of the robustness tests of version A (run after the out-of-sample test).

Reads the CSV files written by 1_robustness_tests.py, against the hashes of
reports/robustness/robustness_report.json, and draws three figures. It computes
nothing new.

Run from Project/:  python scripts/robustness/2_robustness_figures.py
Outputs: reports/figures/R_decile_returns.png, R_cost_multiplier.png, R_capital.png
"""
import hashlib
import io
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "reports" / "robustness"
OUT = ROOT / "reports" / "figures"
BLUE, ORANGE = "#2a78d6", "#eb6834"          # two series, fixed order
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
STATUS = "Computed after the out-of-sample test, on the same years (1993-2025)."
MARKET = 9.06                                 # market excess return, % a year (summary_A.csv)


def read(name: str) -> pd.DataFrame:
    expected = json.loads((SRC / "robustness_report.json").read_text(encoding="utf-8"))["outputs_sha256"][name]
    data = (SRC / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit(f"{name} does not have the SHA-256 of robustness_report.json")
    return pd.read_csv(io.BytesIO(data))


def style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, length=0, labelsize=9)
    ax.yaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def finish(fig, name: str) -> None:
    fig.text(0.01, 0.01, STATUS, fontsize=8, color=MUTED, ha="left", va="bottom")
    fig.patch.set_facecolor(SURFACE)
    fig.savefig(OUT / name, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def decile_returns() -> None:
    s = read("decile_sorts_A.csv")
    s = s[(s.period == "1993-2025") & (s.universe == "all") & (s.breakpoints == "nyse")]
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.4), sharey=True)
    x = np.arange(1, 11)
    for ax, model, title in ((axes[0], "gbrt", "Boosted trees"), (axes[1], "ridge", "Ridge regression")):
        for offset, weighting, color, label in ((-0.2, "equal", BLUE, "Equal weights"), (0.2, "value", ORANGE, "Value weights")):
            row = s[(s.model == model) & (s.weighting == weighting)].iloc[0]
            y = np.array([100 * row[f"g{d}_excess_return_annual"] for d in x])
            ax.bar(x + offset, y, width=0.36, color=color, label=label, linewidth=0)
            for d in (1, 10):                              # direct labels on the two groups that matter
                v = y[d - 1]
                shift = 0.3 if (d == 10 and weighting == "value") else 0.0   # clear of the taller neighbour
                ax.text(d + offset + shift, v + (0.5 if v >= 0 else -0.5), f"{v:.1f}", ha="center",
                        va="bottom" if v >= 0 else "top", fontsize=8, color=INK)
        ax.axhline(MARKET, color=MUTED, lw=1, ls=(0, (4, 3)))
        ax.text(0.45, MARKET + 0.4, "Market 9.1", fontsize=8, color=MUTED, ha="left", va="bottom")
        ax.axhline(0, color=MUTED, lw=0.8)
        ax.set_title(title, fontsize=11, color=INK, loc="left")
        ax.set_xticks(x)
        ax.set_xlim(0.3, 11.0)
        ax.set_ylim(-5, 23)
        ax.set_xlabel("Group of forecasts (1 = lowest, 10 = highest; NYSE breakpoints)", fontsize=9, color=MUTED)
        style(ax)
    axes[0].set_ylabel("Mean excess return, % a year", fontsize=9, color=MUTED)
    axes[0].legend(frameon=False, fontsize=9, loc="upper left", bbox_to_anchor=(0.0, 0.9))
    fig.suptitle("The forecasts order the stocks, mostly where small stocks weigh more (paper portfolios, no costs)",
                 fontsize=12, color=INK, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    finish(fig, "R_decile_returns.png")


def cost_multiplier() -> None:
    c = read("cost_multiplier_A.csv")
    c = c[c.period == "1993-2025"]
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    for key, color, label, dy in (("gbrt_all", BLUE, "Boosted trees", -2.6), ("ridge_all", ORANGE, "Ridge regression", 0.9)):
        t = c[c.model_universe == key].sort_values("cost_multiplier")
        k, a = t.cost_multiplier.to_numpy(), 100 * t.alpha_ff5mom_net_annual.to_numpy()
        ax.plot(k, a, color=color, lw=2, marker="o", ms=6, label=label)
        ax.text(k[0], a[0] + dy, f"{label}: {a[0]:.2f} at zero cost", fontsize=8.5, color=INK,
                va="bottom" if dy > 0 else "top")
        above = key == "ridge_all"
        ax.text(1.04 if above else 0.96, a[3] + (0.6 if above else -0.6), f"{a[3]:.2f}", fontsize=8.5, color=INK,
                va="bottom" if above else "top", ha="left" if above else "right")
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.axvline(1, color=MUTED, lw=1, ls=(0, (4, 3)))
    ax.text(1.02, -11.2, "Costs of the test (k = 1)", fontsize=8, color=MUTED, ha="left")
    ax.set_xticks([0, 0.25, 0.5, 1, 2])
    ax.set_xlabel("Multiplier k applied to the half spread and the price impact", fontsize=9, color=MUTED)
    ax.set_ylabel("Net alpha against FF5 + momentum, % a year", fontsize=9, color=MUTED)
    ax.set_ylim(-12, 4)
    ax.legend(frameon=False, fontsize=9, loc="lower left")
    style(ax)
    ax.set_title("No cost level gives the trees a positive alpha;\nthe ridge breaks even near a third of our costs",
                 fontsize=11.5, color=INK, loc="left")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    finish(fig, "R_cost_multiplier.png")


def capital() -> None:
    c = read("capital_A.csv")
    c = c[c.period == "1993-2025"]
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    sizes = [1e7, 1e8, 1e9]
    x = np.arange(3)
    for offset, key, color, label in ((-0.2, "gbrt_all", BLUE, "Boosted trees"), (0.2, "ridge_all", ORANGE, "Ridge regression")):
        t = c[c.model_universe == key].set_index("capital_usd").loc[sizes]
        y = 100 * t.alpha_ff5mom_net_annual.to_numpy()
        ax.bar(x + offset, y, width=0.36, color=color, label=label, linewidth=0)
        for xi, v, cash in zip(x + offset, y, 100 * t.cash_after_trades_mean.to_numpy()):
            ax.text(xi, v - 0.12, f"{v:.2f}", ha="center", va="top", fontsize=8.5, color=INK)
            ax.text(xi, 0.1, f"cash {cash:.0f} %", ha="center", va="bottom", fontsize=8, color=MUTED)
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(["USD 10 million", "USD 100 million\n(the test)", "USD 1 billion"])
    ax.set_ylabel("Net alpha against FF5 + momentum, % a year", fontsize=9, color=MUTED)
    ax.set_ylim(-7.2, 0.9)
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    style(ax)
    ax.set_title("A fund ten times smaller still has a negative alpha", fontsize=11.5, color=INK, loc="left")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    finish(fig, "R_capital.png")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    decile_returns()
    cost_multiplier()
    capital()
    print("3 figures written to", OUT)
