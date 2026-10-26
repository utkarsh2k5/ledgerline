"""Static charts for Word/PowerPoint/HTML reports (matplotlib, deterministic output).

Colour roles follow a validated, colour-blind-safe palette: categorical slots
in fixed order, one-hue sequential ramp for the fan chart, blue/red diverging
for gains/losses, and every series also distinguished by line style or labels.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]  # blue, orange, aqua (all-pairs CVD-safe)
POS, NEG = "#2a78d6", "#e34948"             # diverging poles
SEQ = {"outer": "#cde2fb", "inner": "#86b6ef", "median": "#1c5cab"}
INK, INK_2, INK_3, GRID = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e0"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 9,
    "axes.edgecolor": INK_3,
    "axes.labelcolor": INK_2,
    "axes.titlesize": 10,
    "axes.titleweight": "bold",
    "axes.titlecolor": INK,
    "xtick.color": INK_2,
    "ytick.color": INK_2,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "axes.axisbelow": True,
    "legend.frameon": False,
    "svg.hashsalt": "ledgerline",
})


def _save(fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=200, metadata={"Software": None})
    plt.close(fig)
    return path


def _pct(ax, axis="y", decimals=0):
    fmt = mticker.PercentFormatter(1.0, decimals=decimals)
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(fmt)


def cumulative(data: dict, path: Path) -> Path:
    """Growth of 1 for the fund vs benchmark."""
    months, port, bench = data["months"], data["portfolio"], data["benchmark"]
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    x = range(len(months))
    ax.plot(x, [v - 1 for v in port], color=SERIES[0], lw=2, label="Total fund")
    ax.plot(x, [v - 1 for v in bench], color=INK_2, lw=1.6, ls="--", label="Benchmark")
    ax.axhline(0, color=INK_3, lw=0.8)
    step = max(1, len(months) // 6)
    ax.set_xticks(list(x)[::step], [months[i] for i in range(0, len(months), step)])
    _pct(ax)
    ax.annotate(f"{port[-1] - 1:.1%}", (len(months) - 1, port[-1] - 1), xytext=(4, 0),
                textcoords="offset points", color=INK, fontsize=8, va="center")
    ax.annotate(f"{bench[-1] - 1:.1%}", (len(months) - 1, bench[-1] - 1), xytext=(4, 0),
                textcoords="offset points", color=INK_2, fontsize=8, va="center")
    ax.set_ylabel("Cumulative return")
    ax.legend(loc="upper left")
    ax.set_xlim(0, len(months) - 1 + len(months) * 0.08)
    return _save(fig, path)


def attribution(data: dict, path: Path) -> Path:
    """Horizontal grouped bars: allocation / selection / interaction per mandate."""
    segs = data["segments"]
    effects = ["allocation", "selection", "interaction"]
    fig, ax = plt.subplots(figsize=(7.2, 0.45 * len(segs) + 1.2))
    h = 0.24
    for i, e in enumerate(effects):
        ys = [j + (i - 1) * (h + 0.02) for j in range(len(segs))]
        ax.barh(ys, [data[e][s] for s in segs], height=h, color=SERIES[i], label=e.capitalize())
    ax.set_yticks(range(len(segs)), segs)
    ax.invert_yaxis()
    ax.axvline(0, color=INK_3, lw=0.8)
    _pct(ax, "x", 1)
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3)
    ax.set_xlabel("Contribution to excess return")
    return _save(fig, path)


def allocation(data: dict, path: Path) -> Path:
    segs = data["segments"]
    fig, ax = plt.subplots(figsize=(7.2, 2.9))
    ax.bar(range(len(segs)), [data["actual"][s] for s in segs], width=0.55, color=SERIES[0], label="Actual")
    ax.scatter(range(len(segs)), [data["target"][s] for s in segs], marker="_", s=900, linewidths=2.2,
               color=INK, label="Target", zorder=3)
    for i, s in enumerate(segs):
        top = max(data["actual"][s], data["target"][s])
        ax.text(i, top + 0.008, f"{data['actual'][s]:.1%}", ha="center", fontsize=8, color=INK_2)
    ax.set_xticks(range(len(segs)), segs)
    _pct(ax)
    ax.set_ylim(0, max(max(data["actual"].values()), max(data["target"].values())) * 1.18)
    ax.grid(axis="x", visible=False)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2)
    return _save(fig, path)


def funding_fan(data: dict, path: Path) -> Path:
    years, p = data["years"], data["percentiles"]
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.fill_between(years, p["5"], p["95"], color=SEQ["outer"], label="5th-95th percentile", lw=0)
    ax.fill_between(years, p["25"], p["75"], color=SEQ["inner"], label="25th-75th percentile", lw=0)
    ax.plot(years, p["50"], color=SEQ["median"], lw=2, label="Median")
    ax.axhline(1.0, color=INK_2, lw=1, ls=":")
    ax.text(years[-1], 1.0, " 100% funded", va="bottom", ha="right", fontsize=8, color=INK_2)
    _pct(ax)
    ax.set_xlabel("Years from today")
    ax.set_ylabel("Funding ratio")
    ax.legend(loc="upper left", fontsize=8)
    return _save(fig, path)


def stress(data: dict, path: Path) -> Path:
    names, vals = data["scenarios"], data["changes"]
    fig, ax = plt.subplots(figsize=(7.2, 0.5 * len(names) + 1.0))
    ax.barh(range(len(names)), vals, color=[POS if v >= 0 else NEG for v in vals], height=0.5)
    for i, v in enumerate(vals):
        ax.text(v, i, f" {v * 100:+.1f} pts ", va="center", ha="left" if v >= 0 else "right", fontsize=8, color=INK)
    ax.set_yticks(range(len(names)), names)
    ax.invert_yaxis()
    ax.axvline(0, color=INK_3, lw=0.8)
    lim = max(abs(v) for v in vals) * 1.45 or 0.01
    ax.set_xlim(-lim, lim)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v * 100:+.0f} pts"))
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Change in funding ratio")
    return _save(fig, path)


RENDERERS = {
    "cumulative": cumulative,
    "attribution": attribution,
    "allocation": allocation,
    "funding_fan": funding_fan,
    "stress": stress,
}
