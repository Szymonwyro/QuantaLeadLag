"""Run the lead-lag pipeline on every stock group in the research summary.

    python run_groups.py                  # all groups, cached prices if present
    python run_groups.py --refresh        # re-download prices
    python run_groups.py --only energy    # groups whose sector/slug contains 'energy'
    python run_groups.py --start 2016-01-01 --end 2024-01-01

For each group writes results/groups/<sector>/<slug>/ with the original
pipeline CSVs/PNGs plus report extras (see README.md in the output folder).
If a group contains late listings (e.g. GEV, VG, TLN, AESI) they are dropped
from the main run so the full window is kept, and a second run
'<slug>__with_late_listings' uses all tickers on the shorter common window.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from analysis import calculate_returns, calculate_matrices, rank_leaders, strongest_pairs
from config import START_DATE, END_DATE
from groups import GROUPS, TECH_SUB, Group, all_tickers
import report_plots as rp

ROOT = Path(__file__).resolve().parent / "results" / "groups"
LATE_SHARE = 0.05      # Ticker is "late" if it starts > 5% of the window (~3 months) after the start.
MAX_LAG = 5
ROLL_WINDOW = 252


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def load_prices(start: str, end: str, refresh: bool) -> pd.DataFrame:
    cache = ROOT / "_data" / f"prices_all_{start}_{end}.csv"
    if cache.exists() and not refresh:
        return pd.read_csv(cache, index_col="Date", parse_dates=True)
    import yfinance as yf

    tickers = all_tickers()
    print(f"Downloading {len(tickers)} tickers from Yahoo Finance ...")
    raw = yf.download(tickers=tickers, start=start, end=end, interval="1d", auto_adjust=True,
                      group_by="column", multi_level_index=True, threads=True, progress=False)
    prices = raw["Close"].reindex(columns=tickers)
    prices.index = pd.to_datetime(prices.index).tz_localize(None)
    prices.index.name = "Date"
    prices = prices.dropna(how="all")
    cache.parent.mkdir(parents=True, exist_ok=True)
    prices.to_csv(cache)
    return prices


def split_coverage(prices: pd.DataFrame, tickers: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Return (kept, late, missing) tickers."""
    missing = [t for t in tickers if t not in prices or prices[t].notna().sum() < 60]
    present = [t for t in tickers if t not in missing]
    firsts = {t: prices[t].first_valid_index() for t in present}
    start, end = prices.index[0], prices.index[-1]
    cutoff = start + (end - start) * LATE_SHARE
    late = [t for t in present if firsts[t] > cutoff]
    kept = [t for t in present if t not in late]
    return kept, late, missing


# --------------------------------------------------------------------------- #
# Extra statistics
# --------------------------------------------------------------------------- #
# These go beyond the original pipeline (analysis.py). They are here to answer
# the brief's other questions: "do links survive removing market moves?",
# "do they last?" and "is it only a one-day effect?".
#
# READ BEFORE QUOTING ANY p-VALUE IN A REPORT
# -------------------------------------------
# The z / p / q numbers below assume each day's return is independent of the
# day before. That is not true for these stocks: many reverse their own moves
# (negative lag-1 autocorrelation), and Rohan's simulation (Industrials R2)
# showed a simple test then flags ~42% of pairs with NO real lead, against
# ~4% for a test that keeps each stock's own reversal. So treat them as a
# ranking/screening device: "which pairs are worth a proper test", not
# "this pair is significant". The more defensible evidence is consistency:
# same sign on raw AND adjusted returns, AND in both halves of the sample.
# --------------------------------------------------------------------------- #
def norm_p(z: np.ndarray | float) -> np.ndarray | float:
    """Two-sided p-value of a standard-normal z: P(|Z| >= |z|) = erfc(|z| / sqrt 2).

    Uses math.erfc so we don't need SciPy as a dependency.
    """
    return np.vectorize(lambda v: math.erfc(abs(v) / math.sqrt(2)))(z)


def bh_qvalues(p: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg q-values: corrects for testing many pairs at once.

    A group of N stocks has N(N-1)/2 pairs (4,950 for the 100 tech stocks), so
    at p < 0.05 about 5% would look "significant" by luck alone. q < 0.05 means
    that, of all pairs flagged at that level, at most ~5% are expected to be
    false discoveries. Steps: sort p ascending, scale the k-th smallest by m/k,
    then take a running minimum from the top so q never decreases with p.
    Inherits the independence caveat above: correct q-values of an overstated p
    are still overstated.
    """
    p = np.asarray(p, dtype=float)
    m = len(p)
    order = np.argsort(p)
    ranked = p[order] * m / np.arange(1, m + 1)
    q = np.minimum.accumulate(ranked[::-1])[::-1].clip(max=1)
    out = np.empty(m)
    out[order] = q
    return out


def adjusted_returns(returns: pd.DataFrame, bench: pd.Series) -> pd.DataFrame:
    """Remove the market/sector move from each stock: r_adj = r_stock - beta * r_ETF.

    Why: on raw returns, most "leadership" is two stocks reacting to the same
    market or sector move with different speeds or reversals. The Energy notes
    ask for returns adjusted for XLE / the group's ETF before testing, and the
    Tech x Industrials work found only CAT -> GE survived this step.

    beta = cov(stock, ETF) / var(ETF), estimated once over the full sample.
    That uses future data, which is fine for describing the past but NOT for a
    trading backtest (there, estimate beta on a trailing window instead).
    The lead-lag score is then re-run on these residuals unchanged.
    """
    out = {}
    for c in returns.columns:
        both = pd.concat([returns[c], bench], axis=1).dropna()
        beta = np.cov(both.iloc[:, 0], both.iloc[:, 1], ddof=1)[0, 1] / both.iloc[:, 1].var(ddof=1)
        out[c] = returns[c] - beta * bench
    return pd.DataFrame(out).reindex(returns.index)


def complete_pairs_n(returns: pd.DataFrame) -> int:
    """Number of (today, tomorrow) day-pairs with returns for EVERY stock.

    Same rule as analysis.calculate_matrices, so n matches the sample the
    scores were actually computed on. n sets the standard error below.
    """
    a = returns.iloc[:-1].to_numpy()
    b = returns.iloc[1:].to_numpy()
    return int((np.isfinite(a).all(1) & np.isfinite(b).all(1)).sum())


def lagged_score(returns: pd.DataFrame, i: str, j: str, k: int) -> float:
    """Lead-lag score at a k-day lag: corr(r_i,t , r_j,t+k) - corr(r_j,t , r_i,t+k).

    k = 1 reproduces the pipeline's score. Looking at k = 2..5 checks the
    Technology finding that "only a one-day lag holds up": a genuine slow
    reaction should fade gradually, while noise jumps around zero.
    Pairwise-complete data is used here (pandas .corr), so values can differ
    very slightly from the all-stocks-complete matrix at k = 1.
    """
    x, y = returns[i], returns[j]
    return float(x.corr(y.shift(-k)) - y.corr(x.shift(-k)))


def rolling_score(returns: pd.DataFrame, i: str, j: str, window: int) -> pd.Series:
    """One-day lead-lag score recomputed over a moving window (default 252 days, ~1 year).

    Answers "do the links last?" visually: a durable link stays on one side of
    zero; a link that flips sign or only spikes in one stress period (e.g. a
    crash) is not something to trade. Dated at the END of each window.
    """
    x, y = returns[i], returns[j]
    f = x.rolling(window).corr(y.shift(-1))
    r = y.rolling(window).corr(x.shift(-1))
    return (f - r).dropna()


def enrich_pairs(pairs: pd.DataFrame, n: int, adj_ll: pd.DataFrame, adj_fwd: pd.DataFrame) -> pd.DataFrame:
    """Add screening statistics and the market-adjusted score to strongest_pairs.

    Columns added:
      Approx_z      S / SE with SE = sqrt(2/n). Under "no lead", each sample
                    correlation has SE ~ 1/sqrt(n); S is a difference of two
                    roughly independent correlations, so variances add -> 2/n.
                    Example: n = 1,200 days -> SE ~ 0.041, so |S| > 0.08 ~ z > 1.96.
      Approx_p      two-sided p-value of Approx_z (see caveat at top of section).
      BH_q          p corrected for the number of pairs in the group.
      Forward_Corr_t  t-stat of the one-way forecast corr(leader today, follower
                    tomorrow) = r * sqrt(n). This is the number that matters for
                    trading: S can be large purely because the REVERSE corr is
                    negative (the "leader" reverses itself), with no forecast.
      Score_Adjusted / Forward_Corr_Adjusted  the same pair on ETF-adjusted returns.
      Same_Sign_After_Adjustment  True if the leader still leads after adjustment.
    """
    p = pairs.copy()
    se = math.sqrt(2.0 / n)
    p["Approx_z"] = p["Score"] / se
    p["Approx_p"] = norm_p(p["Approx_z"].to_numpy())
    p["BH_q"] = bh_qvalues(p["Approx_p"].to_numpy())
    p["Forward_Corr_t"] = p["Forward_Corr"] * math.sqrt(n)
    p["Score_Adjusted"] = [adj_ll.loc[a, b] for a, b in zip(p["Candidate_Leader"], p["Candidate_Follower"])]
    p["Forward_Corr_Adjusted"] = [adj_fwd.loc[a, b] for a, b in zip(p["Candidate_Leader"], p["Candidate_Follower"])]
    p["Same_Sign_After_Adjustment"] = np.sign(p["Score_Adjusted"]) > 0
    return p


# --------------------------------------------------------------------------- #
# One group
# --------------------------------------------------------------------------- #
def run_group(g: Group, tickers: list[str], prices_all: pd.DataFrame, out: Path,
              meta_extra: dict) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*"):
        if old.is_file():
            old.unlink()

    prices = prices_all[tickers].dropna(how="all")
    first = max(prices[t].first_valid_index() for t in tickers)
    prices = prices.loc[first:]
    bench = prices_all[g.benchmark].reindex(prices.index) if g.benchmark in prices_all else None

    # ---- Original pipeline (unchanged functions) ----
    returns = calculate_returns(prices)
    same_day, forward, lead_lag = calculate_matrices(returns)
    leaders = rank_leaders(lead_lag)
    pairs = strongest_pairs(lead_lag, forward)
    n = complete_pairs_n(returns)
    se = math.sqrt(2.0 / n)

    # ---- Benchmark-adjusted version ----
    # If the ETF has no data, fall back to the group's own equal-weight average return.
    bench_ret = np.log(bench).diff() if bench is not None else returns.mean(axis=1)
    adj = adjusted_returns(returns, bench_ret)
    _, adj_fwd, adj_ll = calculate_matrices(adj)
    adj_leaders = rank_leaders(adj_ll)
    pairs = enrich_pairs(pairs, n, adj_ll, adj_fwd)

    # Lag-1 autocorrelation: how much a stock repeats (+) or reverses (-) its own
    # move the next day. Plotted against leadership in chart 07: a strong negative
    # relationship means "leaders" are mostly stocks that reverse themselves,
    # because reversal makes corr(follower today, leader tomorrow) negative.
    autocorr = pd.Series({t: returns[t].autocorr(1) for t in tickers}, name="Lag1_Autocorr")
    stock_stats = pd.DataFrame({
        "Leadership_Score_Raw": leaders,
        "Leadership_Score_Adjusted": adj_leaders,
        "Lag1_Autocorr": autocorr,
        "Ann_Volatility": returns.std() * math.sqrt(252),
        "Ann_Return": returns.mean() * 252,
        "Beta_to_" + g.benchmark: [returns[t].cov(bench_ret) / bench_ret.var() for t in tickers],
        "First_Date": [prices[t].first_valid_index().date() for t in tickers],
        "Obs": prices.notna().sum(),
    }).sort_values("Leadership_Score_Raw", ascending=False)
    stock_stats.index.name = "Ticker"

    # ---- Lag profile & rolling for top 3 pairs ----
    top3 = list(zip(pairs["Candidate_Leader"].head(3), pairs["Candidate_Follower"].head(3)))
    lags = range(1, MAX_LAG + 1)
    profile = pd.DataFrame({f"{a}→{b}": [lagged_score(returns, a, b, k) for k in lags] for a, b in top3},
                           index=pd.Index(lags, name="Lag"))
    rolling = pd.DataFrame({f"{a}→{b}": rolling_score(returns, a, b, ROLL_WINDOW) for a, b in top3})

    # ---- Stability across two halves ----
    # Re-run the pipeline separately on the first and second half of the days and
    # compare each pair's score. Simplest out-of-sample check: a real link should
    # keep its sign; noise agrees ~50% of the time.
    mid = len(returns) // 2
    h1, h2 = returns.iloc[:mid], returns.iloc[mid:]
    split_labels = (f"{h1.index[1]:%b %Y}–{h1.index[-1]:%b %Y}", f"{h2.index[0]:%b %Y}–{h2.index[-1]:%b %Y}")
    _, _, ll1 = calculate_matrices(h1)
    _, _, ll2 = calculate_matrices(h2)
    iu = np.triu_indices(len(tickers), 1)
    stab = pd.DataFrame({
        "Stock_i": np.array(tickers)[iu[0]], "Stock_j": np.array(tickers)[iu[1]],
        "S_full": lead_lag.to_numpy()[iu], "S_first_half": ll1.to_numpy()[iu], "S_second_half": ll2.to_numpy()[iu],
    })
    stab["Same_Sign"] = np.sign(stab["S_first_half"]) == np.sign(stab["S_second_half"])

    # ---- Stated hypotheses ----
    # Every leader -> follower pair written in the research summary (groups.py).
    # Positive S always means "the stated leader moved first", so a negative value
    # means the data points the opposite way to the hypothesis.
    hyps = [(a, b, h) for a, b, h in g.hypotheses if a in tickers and b in tickers]
    hyp_df = pd.DataFrame()
    if hyps:
        hyp_df = pd.DataFrame([{
            "Hypothesis": h, "Leader": a, "Follower": b,
            "S_raw": lead_lag.loc[a, b], "S_adjusted": adj_ll.loc[a, b],
            "Forward_Corr_raw": forward.loc[a, b], "Reverse_Corr_raw": forward.loc[b, a],
            "Forward_Corr_adjusted": adj_fwd.loc[a, b],
            "S_first_half": ll1.loc[a, b], "S_second_half": ll2.loc[a, b],
            "S_lag2": lagged_score(returns, a, b, 2), "S_lag3": lagged_score(returns, a, b, 3),
            "SE": se,
        } for a, b, h in hyps])
        hyp_df["z_raw"] = hyp_df["S_raw"] / se
        hyp_df["z_adjusted"] = hyp_df["S_adjusted"] / se
        hyp_df["p_raw"] = norm_p(hyp_df["z_raw"].to_numpy())
        hyp_df["p_adjusted"] = norm_p(hyp_df["z_adjusted"].to_numpy())
        hyp_df["BH_q_adjusted"] = bh_qvalues(hyp_df["p_adjusted"].to_numpy())
        hyp_df["Direction_as_stated_raw"] = hyp_df["S_raw"] > 0
        hyp_df["Direction_as_stated_adjusted"] = hyp_df["S_adjusted"] > 0
        hyp_df["Stable_both_halves"] = (hyp_df["S_first_half"] > 0) & (hyp_df["S_second_half"] > 0)
        # Verdict, in order of priority (first match wins):
        #   Supported (adjusted, stable)    adjusted S > 0, p < 0.05, AND positive in both halves
        #   Supported (adjusted, unstable)  adjusted S > 0, p < 0.05, but sign flips between halves
        #   Reversed                        adjusted S < 0, p < 0.05: the "follower" leads
        #   Not significant                 everything else
        # Uses the ADJUSTED score (market/sector moves removed) and the uncorrected p,
        # so expect some false "Supported" by chance; with many hypotheses in a group,
        # check BH_q_adjusted too. "Stable" is the more trustworthy part of the label.
        hyp_df["Verdict"] = np.select(
            [(hyp_df["S_adjusted"] > 0) & (hyp_df["p_adjusted"] < 0.05) & hyp_df["Stable_both_halves"],
             (hyp_df["S_adjusted"] > 0) & (hyp_df["p_adjusted"] < 0.05),
             (hyp_df["S_adjusted"] < 0) & (hyp_df["p_adjusted"] < 0.05)],
            ["Supported (adjusted, stable)", "Supported (adjusted, unstable)", "Reversed"],
            "Not significant")
        hyp_df.insert(0, "Group", g.title)

    # ---- CSV exports ----
    prices.to_csv(out / "prices.csv")
    returns.to_csv(out / "log_returns.csv")
    adj.to_csv(out / f"log_returns_adjusted_vs_{g.benchmark}.csv")
    same_day.to_csv(out / "same_day_correlations.csv")
    forward.to_csv(out / "forward_correlations.csv")
    lead_lag.to_csv(out / "lead_lag_scores.csv")
    adj_fwd.to_csv(out / "forward_correlations_adjusted.csv")
    adj_ll.to_csv(out / "lead_lag_scores_adjusted.csv")
    leaders.to_csv(out / "leadership_rankings.csv", header=True)
    adj_leaders.to_csv(out / "leadership_rankings_adjusted.csv", header=True)
    pairs.to_csv(out / "strongest_pairs.csv", index=False)
    stock_stats.to_csv(out / "stock_stats.csv")
    profile.to_csv(out / "lag_profile_top_pairs.csv")
    rolling.to_csv(out / "rolling_scores_top_pairs.csv")
    stab.to_csv(out / "stability_split_halves.csv", index=False)
    if not hyp_df.empty:
        hyp_df.to_csv(out / "hypothesis_tests.csv", index=False)

    # ---- Charts ----
    period = f"{returns.index[1]:%b %Y} – {returns.index[-1]:%b %Y}, {n} day-pairs"
    sub_of = {t: s for s, (_, names) in TECH_SUB.items() for t in names.split()} if g.sector == "technology" else None
    rp.heatmap(same_day, f"{g.title}: same-day correlation", period,
               out / "01_correlations.png", "Correlation of daily log returns", sub_of)
    rp.heatmap(lead_lag, f"{g.title}: lead-lag score (raw)",
               f"Row leads column when positive. {period}", out / "02_lead_lag.png", "S = fwd(i→j) − fwd(j→i)", sub_of)
    rp.ranking(leaders, f"{g.title}: net leadership (raw)",
               "Row sum of lead-lag scores. Exploratory, not a significance test",
               out / "03_leadership_rankings.png", "Sum of lead-lag scores")
    rp.cumulative(prices, bench, g.benchmark, f"{g.title}: performance", out / "04_cumulative_returns.png")
    rp.top_pairs(pairs, f"{g.title}: strongest candidate pairs", out / "05_top_pairs.png")
    rp.lag_profile(profile, f"{g.title}: lag profile", out / "06_lag_profile.png",
                   pd.Series(se, index=profile.index))
    rp.leadership_vs_reversal(leaders, autocorr, f"{g.title}: leadership vs own reversal",
                              out / "07_leadership_vs_reversal.png")
    rp.heatmap(adj_ll, f"{g.title}: lead-lag score, adjusted for {g.benchmark}",
               f"Residuals after removing each stock's {g.benchmark} beta. {period}",
               out / "08_lead_lag_adjusted.png", "S on benchmark residuals", sub_of)
    rp.ranking(adj_leaders, f"{g.title}: net leadership (adjusted for {g.benchmark})",
               "Row sum of adjusted lead-lag scores", out / "09_leadership_rankings_adjusted.png",
               "Sum of adjusted lead-lag scores")
    if not rolling.empty:
        rp.rolling_scores(rolling, ROLL_WINDOW, f"{g.title}: rolling lead-lag score, top pairs",
                          out / "10_rolling_scores.png")
    rp.stability(stab["S_first_half"], stab["S_second_half"], split_labels,
                 f"{g.title}: do scores persist?", out / "11_stability_split.png")
    if not hyp_df.empty:
        rp.hypotheses(hyp_df, f"{g.title}: stated hypotheses", out / "12_hypotheses.png")

    # ---- Summary for the report ----
    meta = {
        "group": g.title, "sector": g.sector, "slug": out.name, "source": g.source,
        "benchmark": g.benchmark, "tickers": tickers, "n_tickers": len(tickers),
        "start": str(returns.index[1].date()), "end": str(returns.index[-1].date()),
        "n_day_pairs": n, "score_standard_error": se,
        "avg_same_day_corr": float(same_day.to_numpy()[np.triu_indices(len(tickers), 1)].mean()),
        "top_leader_raw": leaders.index[0], "top_leader_adjusted": adj_leaders.index[0],
        "top_pair": f"{pairs.iloc[0]['Candidate_Leader']}→{pairs.iloc[0]['Candidate_Follower']}",
        "top_pair_score": float(pairs.iloc[0]["Score"]),
        "n_pairs": len(pairs), "pairs_q_below_0.05": int((pairs["BH_q"] < 0.05).sum()),
        "leadership_vs_autocorr_corr": float(np.corrcoef(autocorr[leaders.index], leaders)[0, 1]),
        "split_half_score_corr": (float(np.corrcoef(stab["S_first_half"], stab["S_second_half"])[0, 1])
                                  if len(stab) > 2 else float("nan")),
        "split_half_same_sign_share": float(stab["Same_Sign"].mean()),
        "n_hypotheses": len(hyp_df),
        "hypotheses_supported_adjusted": int(hyp_df["Verdict"].str.startswith("Supported").sum()) if len(hyp_df) else 0,
        **meta_extra,
    }
    (out / "summary.json").write_text(json.dumps(meta, indent=2, default=str))
    write_group_md(out, meta, pairs, stock_stats, hyp_df)
    return {"meta": meta, "hyp": hyp_df}


def write_group_md(out: Path, m: dict, pairs: pd.DataFrame, stats: pd.DataFrame, hyp: pd.DataFrame) -> None:
    f = lambda x: f"{x:+.3f}"
    lines = [
        f"# {m['group']}", "",
        f"Source: {m['source']}  ",
        f"Sample: {m['start']} to {m['end']} ({m['n_day_pairs']} next-day pairs), benchmark {m['benchmark']}  ",
        f"Stocks ({m['n_tickers']}): {', '.join(m['tickers'])}",
    ]
    if m.get("dropped_late"):
        lines.append(f"Left out for late listing (see the `__with_late_listings` run): {', '.join(m['dropped_late'])}  ")
    if m.get("missing"):
        lines.append(f"No price data: {', '.join(m['missing'])}  ")
    lines += [
        "", "## Key numbers", "",
        f"- Average same-day correlation: {m['avg_same_day_corr']:.2f}",
        f"- Top raw leader: **{m['top_leader_raw']}**; top adjusted leader: **{m['top_leader_adjusted']}**",
        f"- Strongest pair: **{m['top_pair']}**, S = {m['top_pair_score']:.3f} (approx. SE {m['score_standard_error']:.3f})",
        f"- Pairs with BH q < 0.05 (raw): {m['pairs_q_below_0.05']} of {m['n_pairs']}",
        f"- Correlation of leadership with own lag-1 autocorrelation: {m['leadership_vs_autocorr_corr']:+.2f}",
        f"- Split-half stability: score corr {m['split_half_score_corr']:+.2f}, same sign {m['split_half_same_sign_share']:.0%}",
        "", "## Top 10 pairs", "",
        "| Leader | Follower | S raw | z | BH q | S adjusted |", "|---|---|---|---|---|---|",
    ]
    for _, r in pairs.head(10).iterrows():
        lines.append(f"| {r.Candidate_Leader} | {r.Candidate_Follower} | {r.Score:.3f} | {r.Approx_z:.2f} | "
                     f"{r.BH_q:.3f} | {f(r.Score_Adjusted)} |")
    lines += ["", "## Stocks", "", "| Ticker | Lead raw | Lead adj | Lag-1 autocorr | Ann. vol |", "|---|---|---|---|---|"]
    for t, r in stats.iterrows():
        lines.append(f"| {t} | {f(r.Leadership_Score_Raw)} | {f(r.Leadership_Score_Adjusted)} | "
                     f"{f(r.Lag1_Autocorr)} | {r.Ann_Volatility:.0%} |")
    if not hyp.empty:
        lines += ["", "## Stated hypotheses", "",
                  f"{m['hypotheses_supported_adjusted']} of {m['n_hypotheses']} supported after adjustment (p < 0.05, positive).", "",
                  "| Hypothesis | Leader → Follower | S raw | S adj | p adj | Halves | Verdict |",
                  "|---|---|---|---|---|---|---|"]
        for _, r in hyp.iterrows():
            lines.append(f"| {r.Hypothesis} | {r.Leader} → {r.Follower} | {f(r.S_raw)} | {f(r.S_adjusted)} | "
                         f"{r.p_adjusted:.3f} | {f(r.S_first_half)} / {f(r.S_second_half)} | {r.Verdict} |")
    lines += ["", "## Files", "", FILES_DOC]
    (out / "README.md").write_text("\n".join(lines) + "\n")


FILES_DOC = """\
**Original pipeline** (unchanged): `prices.csv`, `log_returns.csv`, `same_day_correlations.csv`,
`forward_correlations.csv`, `lead_lag_scores.csv`, `leadership_rankings.csv`, `strongest_pairs.csv`,
`01_correlations.png`, `02_lead_lag.png`, `03_leadership_rankings.png`.

**Report extras, and what each one answers**

| File | Question | How to read it |
|---|---|---|
| `*_adjusted*`, `08_lead_lag_adjusted.png`, `09_leadership_rankings_adjusted.png` | Does the lead survive removing market/sector moves? | Same score on returns minus beta × ETF return. A pair that only leads on raw returns is probably reacting to the market, not to the other stock. |
| `strongest_pairs.csv` extra columns | Which pairs are worth a proper test? | `Approx_z` = S ÷ √(2/n); `Approx_p`; `BH_q` corrects for the number of pairs; `Forward_Corr_t` is the one-way forecast. **See the caveat below.** |
| `stock_stats.csv`, `07_leadership_vs_reversal.png` | Is "leadership" just a stock reversing its own moves? | Strong negative slope = yes. A leader that doesn't forecast its follower can't be traded. |
| `lag_profile_top_pairs.csv`, `06_lag_profile.png` | Is it only a one-day effect? | Score at lags 1–5. The gray band is ±1.96 SE; points inside it are indistinguishable from zero. |
| `rolling_scores_top_pairs.csv`, `10_rolling_scores.png` | Do the links last? | 252-day rolling score. Durable links stay on one side of zero. |
| `stability_split_halves.csv`, `11_stability_split.png` | Out of sample? | Each pair's score in the first vs second half. Noise lands near 50% same sign. |
| `hypothesis_tests.csv`, `12_hypotheses.png` | Do the research summary's hypotheses hold? | Positive S = the stated leader moved first. `Verdict` uses the adjusted score, p < 0.05 and both halves. |
| `04_cumulative_returns.png`, `05_top_pairs.png` | Context | Group vs ETF performance; forward vs reverse correlation of the top pairs. |

**Caveat on p-values.** The z / p / q columns assume each day's return is independent of the previous day.
Many of these stocks reverse their own moves, and in that case a simple test flags far too many pairs:
Industrials R2's simulation found 42% false positives, against ~4% for a test that keeps each stock's own
reversal. Use them to rank and shortlist pairs, not to claim significance. The stronger evidence is
consistency: same sign raw **and** adjusted **and** in both halves (the "Supported (adjusted, stable)" verdict).
Full-sample betas use the whole period, so they are fine for description but not for a backtest.
"""


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default=START_DATE)
    ap.add_argument("--end", default=END_DATE)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--only", default="", help="Substring filter on sector/slug")
    args = ap.parse_args()

    prices_all = load_prices(args.start, args.end, args.refresh)
    rows, hyps = [], []
    produced: set[Path] = set()
    for g in GROUPS:
        if args.only and args.only not in f"{g.sector}/{g.slug}":
            continue
        kept, late, missing = split_coverage(prices_all, list(g.tickers))
        runs = [(kept, g.slug, {"dropped_late": late, "missing": missing, "variant": "main"})]
        if late:
            runs.append((kept + late, f"{g.slug}__with_late_listings",
                         {"dropped_late": [], "missing": missing, "variant": "with_late_listings"}))
        for tickers, slug, extra in runs:
            if len(tickers) < 2:
                print(f"SKIP {g.sector}/{slug}: fewer than two stocks with data")
                continue
            try:
                produced.add(ROOT / g.sector / slug)
                res = run_group(g, tickers, prices_all, ROOT / g.sector / slug, extra)
            except Exception as exc:  # Keep the batch going; record failure.
                print(f"FAIL {g.sector}/{slug}: {exc}")
                rows.append({"sector": g.sector, "slug": slug, "group": g.title, "error": str(exc)})
                continue
            m = res["meta"]
            print(f"ok   {g.sector}/{slug}: {m['n_tickers']} stocks, {m['start']}→{m['end']}, top {m['top_pair']}")
            rows.append({k: (", ".join(v) if isinstance(v, list) else v) for k, v in m.items()})
            if not res["hyp"].empty:
                hyps.append(res["hyp"].assign(Run=f"{g.sector}/{slug}", Start=m["start"], End=m["end"]))

    if not args.only:
        # Full run: remove group folders that no longer exist in groups.py (e.g. after a rename),
        # so the results tree always matches the current group list. Only touches results/groups/<sector>/.
        import shutil
        for sector in {g.sector for g in GROUPS}:
            for d in (ROOT / sector).iterdir():
                if d.is_dir() and d not in produced:
                    print(f"removed stale folder {sector}/{d.name}")
                    shutil.rmtree(d)

    suffix = f"_{args.only.replace('/', '_')}" if args.only else ""
    overview = ROOT / f"groups_overview{suffix}.csv"
    pd.DataFrame(rows).to_csv(overview, index=False)
    if hyps:
        pd.concat(hyps).to_csv(ROOT / f"all_hypothesis_tests{suffix}.csv", index=False)
    print(f"\nOverview: {overview}")


if __name__ == "__main__":
    main()
