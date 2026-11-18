# Lead–lag pipeline: user guide

Quanta Student Capital, quantitative equity research.

This folder runs the lead–lag analysis from *QSC Lead-Lag Research Summary* (14 Nov 2026) on
every stock group in that summary. It writes the CSVs, charts and short write-ups you need to
draft a report section. This guide covers:

1. [Setup](#1-setup)
2. [How to run it](#2-how-to-run-it) (`run_groups.py`, `main.py --group`)
3. [How the groups are broken down](#3-how-the-groups-are-broken-down)
4. [What you get for each group](#4-what-you-get-for-each-group)
5. [Using the output in a report](#5-using-the-output-in-a-report), with caveats
6. [Changing groups, dates and benchmarks](#6-changing-groups-dates-and-benchmarks)
7. [Code map](#7-code-map)

---

## The one formula

For every pair of stocks *i*, *j*:

```
S_ij = corr(r_i today, r_j tomorrow) − corr(r_j today, r_i tomorrow)
```

`r` is the daily log return of the adjusted close. **S > 0 means i tends to move first.** It does
not mean i *causes* j to move, and it does not mean you can trade it (see §5).

---

## 1. Setup

Everything runs from inside `report-1/`, using the project's Python 3.12 virtual environment in
the folder above:

```bash
cd QSC
python3.12 -m venv .venv                  # only once, if .venv doesn't exist yet
.venv/bin/pip install -r requirements.txt # numpy, pandas, matplotlib, yfinance
cd report-1
```

All commands below assume you are in `report-1/` and use `../.venv/bin/python`. If you've
activated the environment (`source ../.venv/bin/activate`), plain `python` works too.

Prices come from Yahoo Finance (adjusted closes, so splits and dividends are handled), which
needs an internet connection. The date range lives in **`config.py`**, the only setting there:

```python
START_DATE = "2022-01-01"
END_DATE   = "2026-10-23"   # Yahoo's end date is exclusive, so data runs to 2026-10-22
```

---

## 2. How to run it

There are two entry points. **For report work, use `run_groups.py`.**

### `run_groups.py`: every group, the full report pack

```bash
../.venv/bin/python run_groups.py                    # all groups (about 2–3 min)
../.venv/bin/python run_groups.py --only energy      # just groups whose "<sector>/<slug>" contains "energy"
../.venv/bin/python run_groups.py --only industrials/r2
../.venv/bin/python run_groups.py --refresh          # download prices again instead of using the cache
../.venv/bin/python run_groups.py --start 2016-01-01 --end 2024-01-01   # a different window
```

| Option | What it does |
|---|---|
| `--only TEXT` | Runs only groups whose `<sector>/<slug>` contains `TEXT`. The overview files then get a suffix (e.g. `groups_overview_energy.csv`) so the full overview isn't overwritten. |
| `--refresh` | Downloads prices again. Otherwise the cached `results/groups/_data/prices_all_<start>_<end>.csv` is reused. |
| `--start`, `--end` | Overrides the `config.py` dates for this run only. A different window gets its own price cache. |

Output goes to `results/groups/<sector>/<slug>/`, one folder per group (see §4).

> A full run (without `--only`) also **deletes group folders that no longer exist in `groups.py`**,
> e.g. after you rename a group, so the results tree always matches the group list. It only ever
> touches `results/groups/<sector>/`.

### `main.py`: one group, the original pilot outputs

`main.py` is the original pilot script. It runs a single group and produces only the original 7
CSVs and 3 charts, with none of the report extras. It's handy for a quick look at one group, or for
showing how the method works without downloading data.

```bash
../.venv/bin/python main.py --group industrials/r2_all_10   # one group from groups.py
../.venv/bin/python main.py --group technology/r1_semiconductors
../.venv/bin/python main.py --demo                          # offline, simulated data
```

- `--group <sector>/<slug>` takes any group listed in §3. A wrong name prints the full list of
  valid names. The default is `energy/all_62`.
- `--demo` uses **fictional** simulated prices in which a one-day MSFT → AMD link was
  deliberately built in. The pipeline should find it (score ≈ 0.68), which shows the method works.
  The numbers aren't real.
- Output goes to `results/market/` (or `results/demo/`) and is **overwritten on every run**.
- Unlike `run_groups.py`, `main.py` does **not** leave out late-listed stocks. A group containing
  VG, for example, will only start in January 2025. For full-period results use `run_groups.py`.

### Tests

```bash
../.venv/bin/python -m unittest test_analysis
```

These five tests check that the date alignment (today vs tomorrow) and the sign of the score are
right, using simulated data with a known lead.

---

## 3. How the groups are broken down

All groups are defined in **`groups.py`**, taken from the research summary. Every sector uses the
same naming scheme, and each name is also the output folder name:

```
results/groups/<sector>/
  all_<N>                  every stock in the sector, across all of its research notes
  r<k>_all_<N>             every stock in research note k (only for sectors with 2+ notes)
  r<k>_<subgroup>          a sub-industry or type defined in note k
  r<k>_hyp_<nn>_<name>     a leader → follower hypothesis group from note k
  <any of the above>__with_late_listings
```

- **`<N>`** is the number of stocks in the group's definition.
- **`all_<N>` and `r<k>_all_<N>` are built automatically** as the union of the groups below them,
  so their stock lists and hypotheses update themselves when you edit a subgroup. A hypothesis
  that appears in two groups is counted once. ETFs (e.g. XOP) are never counted as stocks.
- **Benchmark** is the ETF removed in the adjusted analysis (§4). Groups that mix sectors use SPY.
- **Hyps** is the number of leader → follower hypotheses from the summary that are tested in that
  group's `hypothesis_tests.csv`.

### Late listings and the `__with_late_listings` runs

The score uses only days on which **every** stock in the group has a price. One stock that listed in
2025 would therefore cut the whole group's history down to 2025. So for each group:

- the **main run** leaves out any stock that started more than ~3 months after the window start,
  keeping the full 2022–26 history;
- a second run, **`…__with_late_listings`**, includes them on the shorter common window, so their
  hypotheses still get tested.

| Late stock | First price | Groups affected |
|---|---|---|
| AESI | Mar 2023 | Energy: `all_62`, `r2_all_61`, `r2_type_oilfield_services`, `r2_hyp_04_activity_chain` |
| TLN  | Jun 2023 | Energy: `all_62`, `r2_all_61`, `r2_type_power_generators`, `r2_hyp_08_power` |
| GEV  | Mar 2024 | Tech × Industrials: `all_10` |
| VG   | Jan 2025 | Energy: `all_62`, `r2_all_61`, `r2_type_lng_export`, `r2_hyp_06_lng_export` |

`energy/r2_type_lng_export` has only two stocks (LNG, VG), so it exists **only** as the
`__with_late_listings` run. Each group's `README.md` lists what was left out.

### Technology (Research 1, Jesaiah)

There is one research note, so there is no `r1_all`.

| Folder | Stocks | Benchmark | Hyps | Tickers |
|---|---|---|---|---|
| `all_100` | 100 | XLK | 4 | All nine sub-industries below |
| `r1_semiconductors` | 24 | XLK | 2 | NVDA, AMD, AVGO, MU, INTC, TXN, ADI, QCOM, MRVL, NXPI, MPWR, MCHP, ON, SWKS, TSM, STM, LSCC, CRUS, SLAB, POWI, DIOD, SYNA, MTSI, RMBS |
| `r1_semi_equipment` | 8 | XLK | 0 | AMAT, LRCX, KLAC, TER, ASML, ENTG, ONTO, AMKR |
| `r1_application_software` | 21 | XLK | 2 | CRM, ADBE, INTU, NOW, ADSK, WDAY, CDNS, SNPS, PTC, TYL, FICO, ROP, MANH, GWRE, PEGA, VEEV, HUBS, TEAM, SHOP, SAP, BOX |
| `r1_infrastructure_software` | 11 | XLK | 0 | MSFT, ORCL, PANW, FTNT, GEN, VRSN, AKAM, GDDY, CHKP, NICE, CVLT |
| `r1_internet_platforms` | 4 | XLK | 0 | GOOGL, META, AMZN, NFLX |
| `r1_hardware_storage` | 6 | XLK | 0 | AAPL, HPQ, HPE, NTAP, STX, WDC |
| `r1_networking` | 9 | XLK | 0 | CSCO, ANET, MSI, FFIV, CIEN, LITE, COHR, ERIC, NOK |
| `r1_components` | 11 | XLK | 0 | APH, TEL, GLW, KEYS, TDY, ZBRA, TRMB, FLEX, JBL, CDW, FSLR |
| `r1_it_services` | 6 | XLK | 0 | ACN, IBM, CTSH, IT, EPAM, GLOB |
| `r1_hyp_01_chips_lead_hardware` | 28 | XLK | 0 | Semi equipment + 8 large chips → hardware & storage + CSCO, ANET, APH, TEL, GLW, KEYS |

Hypotheses: the four "links to test on 2024–26 data", which are **ON → DIOD, MPWR → MRVL**
(semiconductors) and **ADBE → TEAM, SAP → NOW** (application software). All four are also in
`all_100`. The 100-stock heatmaps have thin lines separating the sub-industries.

### Tech × Industrials (Research 1, Jesaiah)

| Folder | Stocks | Benchmark | Hyps | Tickers |
|---|---|---|---|---|
| `all_10` | 10 (9 in main run) | SPY | 26 | Chips: NVDA, AMD, MU, AMAT, LRCX · Industrials: CAT, GE, GEV, RTX, BA |

Hypotheses: every chip → industrial pair (25), plus **CAT → GE** (the only adjusted link found
in the note) and **NVDA → GEV** (data-centre power demand). GEV is in `all_10__with_late_listings`
only, from March 2024.

### Industrials (Research 1; Research 2, Rohan)

| Folder | Stocks | Benchmark | Hyps | Tickers |
|---|---|---|---|---|
| `all_20` | 20 | XLI | 14 | R1 + R2 |
| `r1_all_10` | 10 | XLI | 7 | Both R1 subgroups |
| `r1_agricultural` | 4 | XLI | 3 | DE, CNH, AGCO, LNN |
| `r1_construction` | 6 | XLI | 4 | CAT, TEX, MTW, ASTE, OSK, ALG |
| `r2_all_10` | 10 | XLI | 7 | Both R2 subgroups |
| `r2_power_infrastructure` | 5 | XLI | 3 | ETN, PWR, HUBB, POWL, MYRG |
| `r2_freight_equipment` | 5 | XLI | 4 | UNP, PCAR, WAB, GBX, WNC |

Hypotheses:
- **R1:** the largest name leads the smaller ones. DE → CNH, AGCO, LNN and CAT → TEX, MTW, ASTE, OSK.
- **R2:** H1 ETN → POWL, H2 ETN → HUBB, H3 PWR → MYRG, H4 UNP → GBX, H5 WAB → GBX,
  H6 PCAR → WNC, plus the control pair UNP → PCAR.

### Energy (Research 1 and 2, Szymon)

| Folder | Stocks | Benchmark | Hyps | Tickers |
|---|---|---|---|---|
| `all_62` | 62 (59 in main run) | XLE | 179 | R1 + R2 (PARR is the one R1-only stock) |
| `r1_all_11` | 11 | XLE | 16 | XLE: XOM, CVX, COP, MPC · VDE: PARR, PBF, DK · XOP: DINO, MUR, VLO, PSX |
| `r2_all_61` | 61 (58 in main run) | XLE | 169 | All R2 types below |
| **R2 types** | | | | |
| `r2_type_upstream_oil` | 13 | XLE | 0 | APA, CHRD, COP, CRC, CRGY, DVN, EOG, FANG, MTDR, MUR, OXY, PR, SM |
| `r2_type_upstream_gas` | 6 | XLE | 0 | AR, CNX, CRK, EQT, EXE, RRC |
| `r2_type_integrated_majors` | 6 | XLE | 0 | BP, CVX, EQNR, SHEL, TTE, XOM |
| `r2_type_oilfield_services` | 7 | XLE | 0 | AESI, BKR, HAL, HP, PTEN, SLB, WFRD |
| `r2_type_midstream` | 7 | XLE | 0 | DTM, EPD, ET, KMI, OKE, TRGP, WMB |
| `r2_type_lng_export` | 2 | XLE | 0 | LNG, VG (late-listing run only) |
| `r2_type_refining` | 6 | XLE | 0 | DINO, DK, MPC, PBF, PSX, VLO |
| `r2_type_minerals_royalties` | 3 | XLE | 0 | BSM, TPL, VNOM |
| `r2_type_power_generators` | 4 | XLU | 0 | CEG, NRG, TLN, VST |
| `r2_type_regulated_utilities` | 5 | XLU | 0 | AEP, D, DUK, NEE, SO |
| `r2_type_nuclear_fuel` | 2 | XLE | 0 | CCJ, LEU |
| **R2 hypothesis groups** (Table 3 of the summary) | | | | **Leaders → followers** |
| `r2_hyp_01_permian_basin` | 8 | XLE | 16 | OXY, FANG, EOG, DVN → PR, MTDR, SM, TPL |
| `r2_hyp_02_gas_basins` | 6 | XLE | 8 | EQT, EXE → AR, RRC, CNX, CRK |
| `r2_hyp_03_other_basins` | 7 | XLE | 10 | COP, XOM → CHRD, MUR, CRC, APA, CRGY |
| `r2_hyp_04_activity_chain` | 13 | XLE | 42 | XOP, COP, OXY, FANG, EOG, DVN → SLB, HAL, BKR, WFRD, PTEN, HP, AESI |
| `r2_hyp_05_pipelines` | 13 | XLE | 42 | OXY, FANG, EOG, DVN, EQT, EXE → TRGP, OKE, KMI, ET, EPD, WMB, DTM |
| `r2_hyp_06_lng_export` | 8 | XLE | 12 | LNG, VG → CRK, EXE, EQT, KMI, WMB, BKR |
| `r2_hyp_07_refiners` | 8 | XLE | 21 | VLO, MPC, PSX → PBF, DINO, DK; COP, OXY → all six refiners (expected **negative**) |
| `r2_hyp_08_power` | 13 | SPY | 12 | EQT, EXE → VST, NRG, TLN, CEG; CCJ, LEU → CEG, TLN (utilities included as a control) |
| `r2_hyp_09_parent_royalty` | 7 | XLE | 9 | FANG → VNOM; OXY, FANG, EOG, DVN → TPL, BSM |
| `r2_hyp_10_time_zones` | 6 | XLE | 8 | XOM, CVX → SHEL, BP, TTE, EQNR (a benchmark, not a finding) |

R1 hypotheses: XOM, CVX, COP, MPC (large XLE weights) → PARR, PBF, DK (small VDE weights), and
VLO, PSX → DINO, MUR.

The **types** group stocks by business. The **hypothesis groups** group them by *why* one should
lead another. The two overlap, which is intended: the types give a clean picture of each business
line, and the hypothesis groups test the specific claims. The summary's 10-year-yield control for
group 8 isn't included, because a yield isn't a price series.

---

## 4. What you get for each group

Each `results/groups/<sector>/<slug>/` folder contains the same files, so a chart from one group
can be compared directly with the same chart from another.

### Start here

| File | What it is |
|---|---|
| `README.md` | One-page summary: sample, key numbers, top 10 pairs, each stock's scores, hypothesis verdicts. **Read this first.** |
| `summary.json` | The same key numbers in machine-readable form. |

### Charts (PNG, 200 dpi, ready to paste)

| # | File | What it answers |
|---|---|---|
| 01 | `01_correlations.png` | How closely do the stocks move together on the same day? |
| 02 | `02_lead_lag.png` | The lead–lag score S for every pair. **Row leads column when blue.** |
| 03 | `03_leadership_rankings.png` | Net leadership: the row sum of S. Who leads the group overall? |
| 04 | `04_cumulative_returns.png` | Context: growth of 100 for each stock (gray), the equal-weight group (blue) and the benchmark ETF (orange). |
| 05 | `05_top_pairs.png` | The 15 strongest pairs: forward correlation (blue) vs reverse correlation (orange). |
| 06 | `06_lag_profile.png` | Is it only a one-day effect? Score at lags 1–5 for the top 3 pairs. Points inside the gray band can't be told apart from zero. |
| 07 | `07_leadership_vs_reversal.png` | Is "leadership" just stocks reversing their own moves? A strong negative slope means yes. |
| 08 | `08_lead_lag_adjusted.png` | Chart 02 after removing each stock's benchmark-ETF move. |
| 09 | `09_leadership_rankings_adjusted.png` | Chart 03 after the same adjustment. |
| 10 | `10_rolling_scores.png` | Do the links last? 252-day rolling score for the top 3 pairs. |
| 11 | `11_stability_split.png` | Out of sample: each pair's score in the first half vs the second half of the period. |
| 12 | `12_hypotheses.png` | Each stated hypothesis, raw (blue) and adjusted (orange), with 95% intervals. Only in groups that have hypotheses; above 40 rows it shows the 40 strongest. |

### Data (CSV)

| File | Contents |
|---|---|
| `prices.csv` | Adjusted closes used for the run. |
| `log_returns.csv` | Daily log returns. |
| `log_returns_adjusted_vs_<ETF>.csv` | Returns minus beta × the benchmark ETF return. |
| `same_day_correlations.csv` | Matrix behind chart 01. |
| `forward_correlations.csv` / `_adjusted.csv` | Matrix of corr(row today, column tomorrow). The diagonal is each stock's own lag-1 autocorrelation. |
| `lead_lag_scores.csv` / `_adjusted.csv` | Matrix of S (row leads column when positive). |
| `leadership_rankings.csv` / `_adjusted.csv` | Net leadership per stock. |
| `strongest_pairs.csv` | Every pair, sorted by \|S\|, with the leader first. Also has the approximate z, p, BH q, forward-correlation t-stat and the adjusted score. |
| `stock_stats.csv` | Per stock: raw and adjusted leadership, lag-1 autocorrelation, annual volatility and return, beta to the benchmark, first date. |
| `lag_profile_top_pairs.csv` | Data behind chart 06. |
| `rolling_scores_top_pairs.csv` | Data behind chart 10. |
| `stability_split_halves.csv` | Every pair's S over the full sample, the first half and the second half, and whether the sign held. |
| `hypothesis_tests.csv` | One row per stated hypothesis (see below). |

### Cross-group files (in `results/groups/`)

| File | Contents |
|---|---|
| `groups_overview.csv` | One row per run: sample dates, number of stocks, top leader, top pair, number of significant pairs, reversal correlation, split-half stability, hypotheses supported. **Good for a summary table.** |
| `all_hypothesis_tests.csv` | Every hypothesis from every run in one table. Filter by `Run` or `Verdict`. |
| `_data/prices_all_<start>_<end>.csv` | The downloaded price cache (all tickers and benchmark ETFs). |

### Reading `hypothesis_tests.csv`

S is always signed so that **positive = the stated leader moved first**. A negative value means
the data points the opposite way to the hypothesis.

| Column | Meaning |
|---|---|
| `S_raw`, `S_adjusted` | Score on raw returns, and on returns with the benchmark ETF move removed. |
| `Forward_Corr_raw` / `Reverse_Corr_raw` | The two halves of S. Only the forward correlation is a forecast. |
| `S_first_half`, `S_second_half` | The score in each half of the sample. |
| `S_lag2`, `S_lag3` | The score at 2- and 3-day lags. |
| `z_*`, `p_*`, `BH_q_adjusted` | Approximate screening statistics (see §5). |
| `Verdict` | **Supported (adjusted, stable)**: adjusted S > 0, p < 0.05 and positive in both halves. **Supported (adjusted, unstable)**: as before, but the sign flips between halves. **Reversed**: adjusted S < 0 with p < 0.05, so the "follower" leads. **Not significant**: everything else. |

---

## 5. Using the output in a report

### Suggested structure for a group section

1. **Universe and context:** the group's `README.md` header (stocks, sample, what was left out)
   and chart 04.
2. **Do the stocks move together?** Chart 01 and the average same-day correlation.
3. **Who leads?** Charts 02 and 03, with the top pairs from chart 05.
4. **Does it survive removing market moves?** Charts 08 and 09. This is the more honest version.
5. **Is it real?** Chart 07 (reversal), chart 11 (stability) and chart 06 (lag profile).
6. **The hypotheses:** chart 12 and the verdict table from the group's `README.md`.

### Caveats to state in any write-up

- **S is not a forecast.** S is large when the forward correlation is positive *or* when the
  reverse correlation is negative. The second case usually means the "leader" reverses its own
  moves, and nothing about it can be traded. Check `Forward_Corr` and chart 07. The research
  summary found this was the main driver in Technology and Tech × Industrials.
- **The p-values are a screen, not a test.** z = S ÷ √(2/n) assumes each day is independent of the
  last. When stocks reverse their own moves this overstates significance: Industrials R2's
  simulation found 42% of pairs flagged with no real lead. Use p and q to *shortlist* pairs. The
  stronger evidence is **consistency**: same sign on raw and adjusted returns, and in both halves
  (the "Supported (adjusted, stable)" verdict).
- **Multiple testing.** A group of N stocks has N(N−1)/2 pairs (4,950 for `all_100`), so some
  pairs will look strong by chance. Quote `BH_q` rather than raw p for pair rankings.
- **Adjustment uses one beta for the whole period.** That's fine for describing the past, but it
  uses future information, so it's not suitable for a trading backtest.
- **Sample period matters.** The default window (2022–26) is different from Jesaiah's 2016–23
  results, so Technology numbers won't match the summary exactly. Use `--start/--end` to reproduce
  a specific window.
- **Daily closes only.** Stocks that close at different times (European ADRs in
  `r2_hyp_10_time_zones`, for example) can show a mechanical one-day "lead". That is why group 10
  is a benchmark, not a finding.

### Chart style

All charts share one style, so they sit together in a document: blue = positive, red = negative,
gray = neutral; the same fonts and background throughout; titles carry the group name. On light
backgrounds they can be pasted as they are.

---

## 6. Changing groups, dates and benchmarks

- **Dates:** edit `START_DATE` / `END_DATE` in `config.py`, or pass `--start` / `--end`.
- **Add or edit a group:** add a `Group(...)` in the right sector function in `groups.py`
  (`_tech_groups`, `_industrial_groups`, `_energy_groups`, …):

  ```python
  Group("energy", "r2_type_shipping", "Energy R2 – Shipping", "Energy R2 (Szymon)",
        ("FRO", "STNG", "INSW"), "XLE",
        hypotheses=(("FRO", "INSW", "Large tanker owner leads smaller"),))
  ```

  Follow the naming scheme in §3. The sector's `all_<N>` group picks up the new stocks
  automatically, and the next full run creates the folder (and removes folders of any renamed
  groups). New tickers are downloaded automatically. Use `--refresh` if the cache is from before
  you added them.
- **Benchmark:** the 6th argument of `Group`. Any ticker Yahoo knows works (XLE, XLK, XLI, XLU,
  SPY, XOP, …).
- **Late-listing cutoff:** `LATE_SHARE` in `run_groups.py` (default 0.05, about 3 months of the
  window).
- **Rolling window / maximum lag:** `ROLL_WINDOW` (252) and `MAX_LAG` (5) in `run_groups.py`.

---

## 7. Code map

| File | Role |
|---|---|
| `config.py` | Date range only. |
| `groups.py` | Every stock group and hypothesis from the research summary. |
| `run_groups.py` | Batch runner: downloads prices, runs every group, writes all outputs. The "Extra statistics" section is annotated in detail. |
| `main.py` | Single-group run (`--group`) or offline demo (`--demo`), original outputs only. |
| `analysis.py` | Core maths: log returns, same-day and forward correlations, S, rankings, pairs. Used by both scripts and unchanged from the pilot. |
| `data.py` | Yahoo Finance download and the simulated demo data. |
| `plots.py` | The pilot's original charts (used by `main.py`). |
| `report_plots.py` | Report charts (used by `run_groups.py`). |
| `test_analysis.py` | Unit tests for date alignment and the sign of the score. |
| `results/` | Generated output. It's git-ignored, so regenerate it rather than committing it. |
