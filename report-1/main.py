"""Run the Quanta Student Capital stock lead-lag pilot.

    python main.py --demo                      # Runs offline; explicitly fictional stocks
    python main.py --group energy/all_62       # Downloads real adjusted closes for one group in groups.py
    python main.py --group industrials/r2_all_10

To run every group with the full set of report charts, use run_groups.py instead.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from analysis import calculate_returns, calculate_matrices, rank_leaders, strongest_pairs
from config import START_DATE, END_DATE
from data import download_prices, simulated_prices
from groups import GROUPS
from plots import save_heatmap, save_ranking

# Fictional labels for the offline demo; simulated_prices() needs MSFT and AMD.
DEMO_TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMD", "ORCL",  # Technology
    "CAT", "DE", "HON", "GE", "RTX",       # Industrials
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Quanta lead-lag stock pilot")
    parser.add_argument("--demo", action="store_true", help="Use synthetic offline dataset")
    parser.add_argument("--group", default="energy/all_62",
                        help="<sector>/<slug> from groups.py, e.g. technology/r1_semiconductors")
    args = parser.parse_args()

    if args.demo:
        mode, tickers = "demo", DEMO_TICKERS
    else:
        by_name = {f"{g.sector}/{g.slug}": g for g in GROUPS}
        if args.group not in by_name:
            parser.error(f"unknown group {args.group!r}. Choose from: {', '.join(by_name)}")
        mode, tickers = "market", list(by_name[args.group].tickers)
    out = Path(__file__).resolve().parent / "results" / mode
    out.mkdir(parents=True, exist_ok=True)

    if args.demo:
        prices = simulated_prices(tickers)
    else:
        prices = download_prices(tickers, START_DATE, END_DATE)

    returns = calculate_returns(prices)
    same_day, forward, lead_lag = calculate_matrices(returns)
    leaders = rank_leaders(lead_lag)
    pairs = strongest_pairs(lead_lag, forward)

    # Save reproducible tabular outputs.
    prices.to_csv(out / "prices.csv")
    returns.to_csv(out / "log_returns.csv")
    same_day.to_csv(out / "same_day_correlations.csv")
    forward.to_csv(out / "forward_correlations.csv")
    lead_lag.to_csv(out / "lead_lag_scores.csv")
    leaders.to_csv(out / "leadership_rankings.csv", header=True)
    pairs.to_csv(out / "strongest_pairs.csv", index=False)

    # Save three charts for Sunday's meeting.
    save_heatmap(same_day, "Same-day correlations of stock returns", out / "01_correlations.png")
    save_heatmap(lead_lag, "Next-day directional lead-lag score", out / "02_lead_lag.png")
    save_ranking(leaders, out / "03_leadership_rankings.png")

    print(f"\nMode: {mode.upper()}; tickers: {len(tickers)}; price observations: {len(prices)}")
    print("\nCandidate strongest directional pairs (exploratory only):")
    print(pairs.head(5).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    if args.demo:
        print("\nSIMULATED EXAMPLE: MSFT -> AMD was deliberately programmed; no real claim.")
        print(f"Observed MSFT -> AMD directional score: {lead_lag.loc['MSFT', 'AMD']:.3f}")
    print(f"\nCharts and CSVs saved in: {out.resolve()}")


if __name__ == "__main__":
    main()
