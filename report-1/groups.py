"""Stock groups taken from QSC_Lead_Lag_Research_Summary.pdf (14 Nov 2026).

Every sector follows the same naming scheme (= output folder names):

    <sector>/
      all_<N>                 every stock in the sector, across all research notes
      r<k>_all_<N>            every stock in research note k (only if the sector has 2+ notes)
      r<k>_<subgroup>         a sub-industry / type defined in note k
      r<k>_hyp_<nn>_<name>    a leader -> follower hypothesis group from note k

<N> is the number of stocks in the group definition. A run may use fewer if
some list late (run_groups.py then adds a '__with_late_listings' rerun).

`hypotheses` lists the leader -> follower pairs stated in the research summary,
so each one is checked directly in that group's hypothesis_tests.csv.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Group:
    sector: str               # Folder level 1
    slug: str                 # Folder level 2
    title: str                # Human-readable name for charts
    source: str               # Which research note the group comes from
    tickers: tuple[str, ...]
    benchmark: str = "SPY"    # ETF used for the market/sector-adjusted run
    hypotheses: tuple[tuple[str, str, str], ...] = field(default=())  # (leader, follower, label)


ETFS = {"XOP"}  # ETFs used as a "leader" in a hypothesis; never counted as a sector stock.


def _pairs(leaders, followers, label):
    return tuple((a, b, label) for a in leaders for b in followers if a != b)


def _union(groups: list[Group]) -> tuple[tuple[str, ...], tuple[tuple[str, str, str], ...]]:
    """Tickers and hypotheses of several groups, in first-seen order, without duplicates or ETFs."""
    tickers = tuple(dict.fromkeys(t for g in groups for t in g.tickers if t not in ETFS))
    hyps: dict[tuple[str, str], tuple[str, str, str]] = {}
    for g in groups:
        for h in g.hypotheses:
            if h[0] not in ETFS and h[1] not in ETFS:
                hyps.setdefault((h[0], h[1]), h)  # Same pair in two groups (e.g. FANG -> TPL): keep first.
    return tickers, tuple(hyps.values())


def _all_group(sector: str, title: str, source: str, benchmark: str, groups: list[Group],
               prefix: str = "") -> Group:
    """'all_<N>' group (or 'r<k>_all_<N>' with prefix) built from the union of `groups`."""
    tickers, hyps = _union(groups)
    return Group(sector, f"{prefix}all_{len(tickers)}", f"{title} – all {len(tickers)} stocks",
                 source, tickers, benchmark, hyps)


# --------------------------------------------------------------------------- #
# Technology – Research 1 (Jesaiah). One research note -> no r1_all.
# --------------------------------------------------------------------------- #
TECH_SUB = {
    "semiconductors": ("Semiconductors", "NVDA AMD AVGO MU INTC TXN ADI QCOM MRVL NXPI MPWR MCHP ON SWKS TSM "
                                         "STM LSCC CRUS SLAB POWI DIOD SYNA MTSI RMBS"),
    "semi_equipment": ("Semi equipment", "AMAT LRCX KLAC TER ASML ENTG ONTO AMKR"),
    "application_software": ("Application software", "CRM ADBE INTU NOW ADSK WDAY CDNS SNPS PTC TYL FICO ROP "
                                                     "MANH GWRE PEGA VEEV HUBS TEAM SHOP SAP BOX"),
    "infrastructure_software": ("Infrastructure software", "MSFT ORCL PANW FTNT GEN VRSN AKAM GDDY CHKP NICE CVLT"),
    "internet_platforms": ("Internet platforms", "GOOGL META AMZN NFLX"),
    "hardware_storage": ("Hardware & storage", "AAPL HPQ HPE NTAP STX WDC"),
    "networking": ("Networking", "CSCO ANET MSI FFIV CIEN LITE COHR ERIC NOK"),
    "components": ("Components", "APH TEL GLW KEYS TDY ZBRA TRMB FLEX JBL CDW FSLR"),
    "it_services": ("IT services", "ACN IBM CTSH IT EPAM GLOB"),
}
TECH_LINKS = (  # "Four links to test on 2024–26 data"
    ("ON", "DIOD", "Tech R1 link to test"),
    ("ADBE", "TEAM", "Tech R1 link to test"),
    ("MPWR", "MRVL", "Tech R1 link to test"),
    ("SAP", "NOW", "Tech R1 link to test"),
)


def _tech_groups() -> list[Group]:
    src = "Technology R1 (Jesaiah)"
    subs = []
    for slug, (title, names) in TECH_SUB.items():
        tickers = tuple(names.split())
        hyps = tuple(h for h in TECH_LINKS if h[0] in tickers and h[1] in tickers)
        subs.append(Group("technology", f"r1_{slug}", f"Technology R1 – {title}", src, tickers, "XLK", hyps))
    hyp = [Group("technology", "r1_hyp_01_chips_lead_hardware",
                 "Technology R1 hypothesis – chips & equipment lead hardware/components/networking",
                 src + " finding: chips lead, hardware follows",
                 tuple(TECH_SUB["semi_equipment"][1].split()
                       + "NVDA AMD AVGO MU INTC TXN ADI QCOM".split()
                       + TECH_SUB["hardware_storage"][1].split()
                       + "CSCO ANET APH TEL GLW KEYS".split()),
                 "XLK")]
    return [_all_group("technology", "Technology", src, "XLK", subs + hyp)] + subs + hyp


# --------------------------------------------------------------------------- #
# Technology x Industrials – Research 1 (Jesaiah). One group = the whole sector.
# --------------------------------------------------------------------------- #
CHIPS = ("NVDA", "AMD", "MU", "AMAT", "LRCX")
INDUS = ("CAT", "GE", "GEV", "RTX", "BA")


def _tech_x_ind_groups() -> list[Group]:
    src = "Tech×Ind R1 (Jesaiah)"
    base = Group("tech_x_industrials", "", "", src, CHIPS + INDUS, "SPY",
                 _pairs(CHIPS, INDUS, "chip -> industrial")
                 + (("CAT", "GE", "Only adjusted link found"), ("NVDA", "GEV", "Data-centre power demand")))
    return [_all_group("tech_x_industrials", "Tech × Industrials (chips vs industrials)", src, "SPY", [base])]


# --------------------------------------------------------------------------- #
# Industrials – Research 1 and Research 2 (Rohan)
# --------------------------------------------------------------------------- #
FARM = ("DE", "CNH", "AGCO", "LNN")
BUILD = ("CAT", "TEX", "MTW", "ASTE", "OSK", "ALG")
FARM_H = _pairs(("DE",), ("CNH", "AGCO", "LNN"), "Large farm name -> smaller")
BUILD_H = _pairs(("CAT",), ("TEX", "MTW", "ASTE", "OSK"), "Large construction name -> smaller")
POWER = ("ETN", "PWR", "HUBB", "POWL", "MYRG")
FREIGHT = ("UNP", "PCAR", "WAB", "GBX", "WNC")
POWER_H = (("ETN", "POWL", "H1"), ("ETN", "HUBB", "H2"), ("PWR", "MYRG", "H3"))
FREIGHT_H = (("UNP", "GBX", "H4"), ("WAB", "GBX", "H5"), ("PCAR", "WNC", "H6"), ("UNP", "PCAR", "Control pair"))


def _industrial_groups() -> list[Group]:
    s1, s2 = "Industrials R1", "Industrials R2 (Rohan)"
    r1 = [Group("industrials", "r1_agricultural", "Industrials R1 – agricultural machinery", s1, FARM, "XLI", FARM_H),
          Group("industrials", "r1_construction", "Industrials R1 – construction & lifting (+ALG)", s1, BUILD, "XLI",
                BUILD_H)]
    r2 = [Group("industrials", "r2_power_infrastructure", "Industrials R2 – power & electrical infrastructure", s2,
                POWER, "XLI", POWER_H),
          Group("industrials", "r2_freight_equipment", "Industrials R2 – freight transport equipment", s2,
                FREIGHT, "XLI", FREIGHT_H)]
    r1_all = _all_group("industrials", "Industrials R1", s1, "XLI", r1, prefix="r1_")
    r2_all = _all_group("industrials", "Industrials R2", s2, "XLI", r2, prefix="r2_")
    return ([_all_group("industrials", "Industrials", f"{s1} + {s2}", "XLI", [r1_all, r2_all])]
            + [r1_all] + r1 + [r2_all] + r2)


# --------------------------------------------------------------------------- #
# Energy – Research 1 and Research 2 (Szymon)
# --------------------------------------------------------------------------- #
ENERGY_TYPES = {
    "upstream_oil": ("Upstream: oil", "APA CHRD COP CRC CRGY DVN EOG FANG MTDR MUR OXY PR SM", "XLE"),
    "upstream_gas": ("Upstream: gas", "AR CNX CRK EQT EXE RRC", "XLE"),
    "integrated_majors": ("Integrated majors", "BP CVX EQNR SHEL TTE XOM", "XLE"),
    "oilfield_services": ("Oilfield services", "AESI BKR HAL HP PTEN SLB WFRD", "XLE"),
    "midstream": ("Midstream", "DTM EPD ET KMI OKE TRGP WMB", "XLE"),
    "lng_export": ("LNG export", "LNG VG", "XLE"),
    "refining": ("Refining", "DINO DK MPC PBF PSX VLO", "XLE"),
    "minerals_royalties": ("Minerals and royalties", "BSM TPL VNOM", "XLE"),
    "power_generators": ("Power generators", "CEG NRG TLN VST", "XLU"),
    "regulated_utilities": ("Regulated utilities", "AEP D DUK NEE SO", "XLU"),
    "nuclear_fuel": ("Nuclear fuel", "CCJ LEU", "XLE"),
}
PERMIAN = ("OXY", "FANG", "EOG", "DVN")
GAS_LEAD = ("EQT", "EXE")
REFINERS_BIG = ("VLO", "MPC", "PSX")
REFINERS_SMALL = ("PBF", "DINO", "DK")

# (slug, title, tickers, hypotheses) – the ten groups of Table 3, numbered as in the summary.
ENERGY_HYPOTHESES = [
    ("01_permian_basin", "Permian basin", PERMIAN + ("PR", "MTDR", "SM", "TPL"),
     _pairs(PERMIAN, ("PR", "MTDR", "SM", "TPL"), "G1 Permian")),
    ("02_gas_basins", "Gas basins", GAS_LEAD + ("AR", "RRC", "CNX", "CRK"),
     _pairs(GAS_LEAD, ("AR", "RRC", "CNX", "CRK"), "G2 Gas basins")),
    ("03_other_basins", "Other basins", ("COP", "XOM", "CHRD", "MUR", "CRC", "APA", "CRGY"),
     _pairs(("COP", "XOM"), ("CHRD", "MUR", "CRC", "APA", "CRGY"), "G3 Other basins")),
    ("04_activity_chain", "Activity chain", ("XOP", "COP") + PERMIAN
     + ("SLB", "HAL", "BKR", "WFRD", "PTEN", "HP", "AESI"),
     _pairs(("XOP", "COP") + PERMIAN, ("SLB", "HAL", "BKR", "WFRD", "PTEN", "HP", "AESI"), "G4 Activity chain")),
    ("05_pipelines", "Pipelines", PERMIAN + GAS_LEAD + ("TRGP", "OKE", "KMI", "ET", "EPD", "WMB", "DTM"),
     _pairs(PERMIAN + GAS_LEAD, ("TRGP", "OKE", "KMI", "ET", "EPD", "WMB", "DTM"), "G5 Pipelines")),
    ("06_lng_export", "LNG export", ("LNG", "VG", "CRK", "EXE", "EQT", "KMI", "WMB", "BKR"),
     _pairs(("LNG", "VG"), ("CRK", "EXE", "EQT", "KMI", "WMB", "BKR"), "G6 LNG export")),
    ("07_refiners", "Refiners", REFINERS_BIG + REFINERS_SMALL + ("COP", "OXY"),
     _pairs(REFINERS_BIG, REFINERS_SMALL, "G7 Large -> small refiner")
     + _pairs(("COP", "OXY"), REFINERS_BIG + REFINERS_SMALL, "G7 Crude -> refiner (expect inverse)")),
    ("08_power", "Power", GAS_LEAD + ("CCJ", "LEU", "VST", "NRG", "TLN", "CEG", "AEP", "D", "DUK", "NEE", "SO"),
     _pairs(GAS_LEAD, ("VST", "NRG", "TLN", "CEG"), "G8 Gas -> power")
     + _pairs(("CCJ", "LEU"), ("CEG", "TLN"), "G8 Nuclear fuel -> generator")),
    ("09_parent_royalty", "Parent and royalty", PERMIAN + ("VNOM", "TPL", "BSM"),
     (("FANG", "VNOM", "G9 Parent -> royalty"),) + _pairs(PERMIAN, ("TPL", "BSM"), "G9 Operator -> royalty")),
    ("10_time_zones", "Time zones (benchmark)", ("XOM", "CVX", "SHEL", "BP", "TTE", "EQNR"),
     _pairs(("XOM", "CVX"), ("SHEL", "BP", "TTE", "EQNR"), "G10 US -> Europe")),
]


def _energy_groups() -> list[Group]:
    s1, s2 = "Energy R1 (Szymon)", "Energy R2 (Szymon)"
    # Research 1 is a single list of ETF picks, so its r1_all_<N> IS the note.
    r1_picks = Group("energy", "", "", s1,
                     ("XOM", "CVX", "COP", "MPC", "PARR", "PBF", "DK", "DINO", "MUR", "VLO", "PSX"), "XLE",
                     _pairs(("XOM", "CVX", "COP", "MPC"), ("PARR", "PBF", "DK"), "Large XLE weight -> small VDE weight")
                     + _pairs(("VLO", "PSX"), ("DINO", "MUR"), "Large XOP name -> smaller"))
    r1_all = _all_group("energy", "Energy R1 ETF picks", s1, "XLE", [r1_picks], prefix="r1_")

    types = [Group("energy", f"r2_type_{slug}", f"Energy R2 – {title}", s2, tuple(names.split()), bench)
             for slug, (title, names, bench) in ENERGY_TYPES.items()]
    hyps = [Group("energy", f"r2_hyp_{slug}", f"Energy R2 hypothesis {slug[:2]} – {title}", s2,
                  tuple(dict.fromkeys(tickers)), "SPY" if "power" in slug else "XLE", h)
            for slug, title, tickers, h in ENERGY_HYPOTHESES]
    r2_all = _all_group("energy", "Energy R2", s2, "XLE", types + hyps, prefix="r2_")

    return ([_all_group("energy", "Energy", f"{s1} + {s2}", "XLE", [r1_all, r2_all])]
            + [r1_all, r2_all] + types + hyps)


GROUPS: list[Group] = _tech_groups() + _tech_x_ind_groups() + _industrial_groups() + _energy_groups()


def all_tickers() -> list[str]:
    seen = dict.fromkeys(t for g in GROUPS for t in g.tickers)
    seen.update(dict.fromkeys(g.benchmark for g in GROUPS))
    return list(seen)
