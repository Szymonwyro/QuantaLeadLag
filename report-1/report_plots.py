"""Report-ready PNG charts for the per-group lead-lag runs (run_groups.py).

Colour rules: categorical series use a fixed slot order (never cycled, max 3
coloured series per chart); signed values use a blue <-> red diverging scale
with a neutral gray midpoint; everything else is gray ink.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import pandas as pd

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
MEMBER = "#c9c8c2"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]          # slots 1-3: valid for every pair
POS, NEG, MID = "#2a78d6", "#e34948", "#f0efec"
DIVERGING = LinearSegmentedColormap.from_list("qsc_div", [NEG, MID, POS])
DPI = 200

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
    "text.color": INK, "axes.titlecolor": INK, "axes.titlesize": 12, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "axes.labelsize": 9.5, "xtick.labelsize": 8.5, "ytick.labelsize": 8.5,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": False,
    "grid.color": GRID, "grid.linewidth": 0.7, "legend.frameon": False, "legend.fontsize": 8.5,
    "font.family": "sans-serif", "lines.linewidth": 2,
})


def _subtitle(fig, ax, text: str) -> None:
    ax.annotate(text, (0, 1), xycoords="axes fraction", xytext=(0, 5), textcoords="offset points",
                fontsize=8.5, color=INK_2, va="bottom", ha="left")


def _save(fig, path: Path) -> None:
    fig.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)


def heatmap(values: pd.DataFrame, title: str, subtitle: str, path: Path,
            cbar_label: str, groups: dict[str, str] | None = None) -> None:
    """Square signed heatmap; annotates cells when the matrix is small."""
    n = len(values)
    arr = values.to_numpy(dtype=float)
    off = arr[~np.eye(n, dtype=bool)] if n > 1 else arr.ravel()
    bound = max(float(np.nanmax(np.abs(off))), 0.01)
    side = min(max(6.5, 0.24 * n + 3), 26)
    fig, ax = plt.subplots(figsize=(side + 1.2, side))
    img = ax.imshow(arr, cmap=DIVERGING, vmin=-bound, vmax=bound, interpolation="nearest")
    fs = 8.5 if n <= 15 else 7 if n <= 30 else 5.5 if n <= 65 else 4.5
    ax.set_xticks(range(n), values.columns, rotation=90, fontsize=fs)
    ax.set_yticks(range(n), values.index, fontsize=fs)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    if n <= 14:
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                ax.text(j, i, f"{arr[i, j]:+.2f}", ha="center", va="center", fontsize=7,
                        color="white" if abs(arr[i, j]) > 0.6 * bound else INK)
    if groups:  # Thin separators between consecutive sub-groups (ordered input).
        labels = [groups.get(t, "") for t in values.index]
        for k in range(1, n):
            if labels[k] != labels[k - 1]:
                ax.axhline(k - 0.5, color=INK_2, lw=0.6)
                ax.axvline(k - 0.5, color=INK_2, lw=0.6)
    cb = fig.colorbar(img, ax=ax, shrink=0.7, pad=0.02)
    cb.set_label(cbar_label, color=INK_2)
    cb.outline.set_visible(False)
    ax.set_title(title, pad=22)
    _subtitle(fig, ax, subtitle)
    _save(fig, path)


def ranking(scores: pd.Series, title: str, subtitle: str, path: Path, xlabel: str) -> None:
    s = scores.sort_values()
    n = len(s)
    fig, ax = plt.subplots(figsize=(8, max(3.2, 0.2 * n + 1.4)))
    colors = [POS if v >= 0 else NEG for v in s.values]
    ax.barh(range(n), s.values, color=colors, height=0.72)
    ax.set_yticks(range(n), s.index, fontsize=8.5 if n <= 30 else 6 if n <= 65 else 4.5)
    ax.axvline(0, color=INK_2, lw=0.8)
    ax.grid(axis="x")
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel(xlabel)
    ax.set_title(title, pad=22)
    _subtitle(fig, ax, subtitle)
    _save(fig, path)


def cumulative(prices: pd.DataFrame, bench: pd.Series | None, bench_name: str,
               title: str, path: Path) -> None:
    """Members as faint gray lines; equal-weight group index and benchmark coloured."""
    norm = 100 * prices / prices.bfill().iloc[0]
    rets = np.log(prices).diff()
    group_idx = 100 * np.exp(rets.mean(axis=1, skipna=True).fillna(0).cumsum())
    fig, ax = plt.subplots(figsize=(10, 5.2))
    for c in norm.columns:
        ax.plot(norm.index, norm[c], color=MEMBER, lw=0.8, zorder=1)
    ax.plot(group_idx.index, group_idx, color=SERIES[0], lw=2.2, label="Equal-weight group", zorder=3)
    if bench is not None:
        b = bench.reindex(prices.index).dropna()
        ax.plot(b.index, 100 * b / b.iloc[0], color=SERIES[1], lw=2, label=bench_name, zorder=2)
    # Label up to 12 members at their line end, plus the two highlighted series.
    if len(norm.columns) <= 12:
        # End labels, nudged apart in log space so they don't collide.
        ends = sorted(((float(np.log10(norm[c].dropna().iloc[-1])), c) for c in norm.columns))
        lo, hi = np.log10(norm.min().min()), np.log10(norm.max().max())
        gap = max(hi - lo, 0.1) * 0.035
        placed = []
        for y, c in ends:
            y = max(y, placed[-1] + gap) if placed else y
            placed.append(y)
        x_end = norm.index[-1]
        x_lab = x_end + (norm.index[-1] - norm.index[0]) * 0.012
        for (y0, c), y in zip(ends, placed):
            ax.annotate(c, (x_end, 10 ** y0), xytext=(x_lab, 10 ** y), textcoords="data",
                        fontsize=7, color=INK_2, va="center", ha="left",
                        arrowprops=dict(arrowstyle="-", color=MEMBER, lw=0.5) if abs(y - y0) > gap / 2 else None)
    ax.set_yscale("log")
    ax.axhline(100, color=INK_2, lw=0.6, ls=":")
    ax.grid(axis="y")
    ax.set_ylabel("Growth of 100 (log scale, dividends reinvested)")
    ax.legend(loc="upper left")
    ax.set_title(title, pad=22)
    _subtitle(fig, ax, f"{len(norm.columns)} stocks in gray; {prices.index[0]:%d %b %Y} – {prices.index[-1]:%d %b %Y}")
    _save(fig, path)


def top_pairs(pairs: pd.DataFrame, title: str, path: Path, k: int = 15) -> None:
    """Dot plot: forward vs reverse correlation for the strongest pairs."""
    top = pairs.head(k).iloc[::-1]
    y = np.arange(len(top))
    fig, ax = plt.subplots(figsize=(9, max(3.4, 0.36 * len(top) + 1.6)))
    for yi, (f, r) in zip(y, zip(top["Forward_Corr"], top["Reverse_Corr"])):
        ax.plot([r, f], [yi, yi], color=MEMBER, lw=2, zorder=1)
    ax.scatter(top["Forward_Corr"], y, s=48, color=SERIES[0], zorder=3,
               edgecolor=SURFACE, linewidth=1.5, label="Leader today → follower tomorrow")
    ax.scatter(top["Reverse_Corr"], y, s=48, color=SERIES[1], zorder=3,
               edgecolor=SURFACE, linewidth=1.5, label="Follower today → leader tomorrow")
    labels = [f"{a} → {b}   S={s:.3f}" for a, b, s in zip(top["Candidate_Leader"],
                                                          top["Candidate_Follower"], top["Score"])]
    ax.set_yticks(y, labels, fontsize=8)
    ax.axvline(0, color=INK_2, lw=0.8)
    ax.grid(axis="x")
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("Next-day correlation")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), borderaxespad=0.2, ncol=2)
    ax.set_title(title, pad=40)
    _save(fig, path)


def lag_profile(profile: pd.DataFrame, title: str, path: Path, se: pd.Series) -> None:
    """S_k for k=1..K for up to three pairs, with a ±1.96·SE null band."""
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    lags = profile.index.to_numpy()
    band = 1.96 * se.reindex(lags).to_numpy()
    ax.fill_between(lags, -band, band, color=GRID, alpha=0.8, lw=0, label="±1.96 SE (no-lead null)")
    for color, col in zip(SERIES, profile.columns[:3]):
        ax.plot(lags, profile[col], color=color, marker="o", ms=6, label=col,
                markeredgecolor=SURFACE, markeredgewidth=1.5)
    ax.axhline(0, color=INK_2, lw=0.8)
    ax.set_xticks(lags)
    ax.set_xlabel("Lag k (trading days)")
    ax.set_ylabel("S_k = corr(r_i,t , r_j,t+k) − corr(r_j,t , r_i,t+k)")
    ax.grid(axis="y")
    ax.legend(loc="upper right")
    ax.set_title(title, pad=22)
    _subtitle(fig, ax, "Does the lead fade after one day? Top pairs by one-day score")
    _save(fig, path)


def leadership_vs_reversal(lead: pd.Series, autocorr: pd.Series, title: str, path: Path) -> None:
    x = autocorr.reindex(lead.index)
    fig, ax = plt.subplots(figsize=(8, 5.4))
    ax.scatter(x, lead, s=46, color=SERIES[0], edgecolor=SURFACE, linewidth=1.5, zorder=3)
    if len(lead) >= 3:
        b, a = np.polyfit(x, lead, 1)
        xs = np.linspace(x.min(), x.max(), 50)
        ax.plot(xs, a + b * xs, color=INK_2, lw=1, ls="--", zorder=2)
        rho = np.corrcoef(x, lead)[0, 1]
        _subtitle(fig, ax, f"corr = {rho:+.2f}. A strong negative slope means the 'leadership' "
                           "mostly comes from leaders reversing their own moves")
    show = lead.index if len(lead) <= 25 else lead.abs().sort_values().index[-12:]
    for t in show:
        ax.annotate(t, (x[t], lead[t]), xytext=(4, 3), textcoords="offset points", fontsize=7, color=INK_2)
    ax.axhline(0, color=INK_2, lw=0.6)
    ax.axvline(0, color=INK_2, lw=0.6)
    ax.grid()
    ax.set_axisbelow(True)
    ax.set_xlabel("Own lag-1 autocorrelation (negative = reverses its own moves)")
    ax.set_ylabel("Net leadership score (raw)")
    ax.set_title(title, pad=22)
    _save(fig, path)


def rolling_scores(rolling: pd.DataFrame, window: int, title: str, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 4.6))
    for color, col in zip(SERIES, rolling.columns[:3]):
        ax.plot(rolling.index, rolling[col], color=color, lw=1.6, label=col)
    ax.axhline(0, color=INK_2, lw=0.8)
    ax.grid(axis="y")
    ax.set_ylabel(f"Rolling {window}-day lead-lag score S")
    ax.legend(loc="upper left", ncol=3)
    ax.set_title(title, pad=22)
    _subtitle(fig, ax, "Do the links last? A durable link stays on one side of zero")
    _save(fig, path)


def stability(first: pd.Series, second: pd.Series, labels: tuple[str, str], title: str, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(6.4, 6))
    ax.scatter(first, second, s=14 if len(first) > 300 else 30, color=SERIES[0], alpha=0.55 if len(first) > 300 else 0.85,
               edgecolor="none")
    lim = max(float(np.nanmax(np.abs(np.r_[first, second]))), 0.01) * 1.08
    ax.plot([-lim, lim], [-lim, lim], color=INK_2, lw=0.8, ls=":")
    ax.axhline(0, color=INK_2, lw=0.6)
    ax.axvline(0, color=INK_2, lw=0.6)
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_aspect("equal")
    ax.grid()
    ax.set_axisbelow(True)
    ax.set_xlabel(f"Score S, {labels[0]}")
    ax.set_ylabel(f"Score S, {labels[1]}")
    rho = np.corrcoef(first, second)[0, 1] if len(first) > 2 else np.nan
    agree = float((np.sign(first) == np.sign(second)).mean())
    ax.set_title(title, pad=22)
    _subtitle(fig, ax, f"Each dot is a pair. Corr across halves {rho:+.2f}; same sign {agree:.0%}")
    _save(fig, path)


def hypotheses(table: pd.DataFrame, title: str, path: Path) -> None:
    """Raw and adjusted S for each stated leader -> follower hypothesis, with 95% intervals."""
    t = table
    if len(t) > 40:  # Too many rows to read: keep the 40 strongest by |adjusted z|.
        t = t.loc[t["z_adjusted"].abs().sort_values(ascending=False).index[:40]]
        title += f" (40 strongest of {len(table)}; all in hypothesis_tests.csv)"
    t = t.iloc[::-1].reset_index(drop=True)
    n = len(t)
    y = np.arange(n)
    fig, ax = plt.subplots(figsize=(9, max(3.2, 0.3 * n + 1.8)))
    off = 0.17
    ax.errorbar(t["S_raw"], y + off, xerr=1.96 * t["SE"], fmt="o", ms=5, color=SERIES[0],
                ecolor=SERIES[0], elinewidth=1, capsize=0, label="Raw returns")
    ax.errorbar(t["S_adjusted"], y - off, xerr=1.96 * t["SE"], fmt="s", ms=5, color=SERIES[1],
                ecolor=SERIES[1], elinewidth=1, capsize=0, label="Benchmark-adjusted")
    labels = [f"{a} → {b}" + (f"  ({h})" if len(t) <= 25 else "") for a, b, h in
              zip(t["Leader"], t["Follower"], t["Hypothesis"])]
    ax.set_yticks(y, labels, fontsize=8 if n <= 40 else 6 if n <= 80 else 4.5)
    ax.axvline(0, color=INK_2, lw=0.8)
    ax.grid(axis="x")
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel("Lead-lag score S (positive = stated leader moves first); bars are 95% intervals")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), borderaxespad=0.2, ncol=2)
    ax.set_title(title, pad=36)
    _save(fig, path)
