"""
earnings_quality.py — margin-driver attribution layer for EarningsPulse
=======================================================================

Deterministic implementation of the tests in `earnings_quality_rules.md`.

These are arithmetic checks, not LLM judgment. Run them BEFORE the model writes
narrative, and pass the fired flags in as constraints. The model should not be
free to write "operational leverage" when B2 has already proven it impossible.

Self-test at the bottom reproduces PANAMAPET Q1 FY27, which the current bot
graded "Excellent / Clean / Trust is high".

    python earnings_quality.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from statistics import median
from typing import Optional


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class Severity(Enum):
    BLOCK = "BLOCK"    # caps the grade; downstream conclusions forbidden
    HIGH = "HIGH"
    INFO = "INFO"


class ValueChain(Enum):
    REFINER = "REFINER"        # driver: GRM / crack spread
    CONVERTER = "CONVERTER"    # driver: blending spread + inventory gain
    BRANDED = "BRANDED"        # driver: brand margin, low commodity beta
    OTHER = "OTHER"


@dataclass
class Flag:
    code: str
    severity: Severity
    message: str
    forbids: tuple[str, ...] = ()   # narrative tokens the model may not emit

    def __str__(self) -> str:
        return f"[{self.severity.value:5}] {self.code:34} {self.message}"


@dataclass
class Quarter:
    """One reporting period. Amounts in consistent units (Rs Cr)."""
    label: str
    revenue: float
    ebitda: float
    pat: Optional[float] = None
    depreciation: float = 0.0
    employee_cost: float = 0.0
    other_fixed_opex: float = 0.0
    material_cost: Optional[float] = None

    @property
    def margin(self) -> float:
        return self.ebitda / self.revenue

    @property
    def fixed_costs(self) -> float:
        return self.depreciation + self.employee_cost + self.other_fixed_opex

    @property
    def rm_pct(self) -> Optional[float]:
        return None if self.material_cost is None else self.material_cost / self.revenue


@dataclass
class Filing:
    ticker: str
    quarter_label: str          # "Q1", "Q2", "Q3", "Q4"
    market: str                 # "IN", "US", ...
    current: Quarter
    year_ago: Quarter
    prior_quarter: Optional[Quarter] = None
    margin_history: list[float] = field(default_factory=list)   # trailing, oldest->newest
    revenue_history: list[float] = field(default_factory=list)
    value_chain: ValueChain = ValueChain.OTHER

    has_balance_sheet: bool = False
    has_cash_flow: bool = False
    volume_disclosed: bool = False
    consensus_count: int = 0

    inventory_days: Optional[float] = None
    input_price_direction: Optional[str] = None      # "RISING" | "FALLING" | "FLAT"
    input_index_change_yoy: Optional[float] = None   # 0.85 == +85%

    shares_cr: Optional[float] = None
    price: Optional[float] = None
    tax_rate: float = 0.19

    reported_margin: Optional[float] = None          # as printed in the brief, for H3


# ---------------------------------------------------------------------------
# Group A — data sufficiency gates
# ---------------------------------------------------------------------------

def gate_a1_interim_filing(f: Filing) -> list[Flag]:
    if f.market == "IN" and f.quarter_label in ("Q1", "Q3") and not f.has_cash_flow:
        return [Flag(
            "A1_NO_CASHFLOW_THIS_QUARTER", Severity.BLOCK,
            f"{f.quarter_label} filing under SEBI LODR Reg 33 contains P&L only. "
            "No cash flow statement exists. Quality capped at UNVERIFIED.",
            forbids=("Cash Flow: Healthy", "Cash Flow: Weak", "Earnings Quality: CLEAN"),
        )]
    return []


def gate_a2_empty_is_not_clean(f: Filing) -> list[Flag]:
    if not f.has_balance_sheet:
        return [Flag(
            "A2_BALANCE_SHEET_ABSENT", Severity.BLOCK,
            "Balance sheet not filed. Inventory and receivables unverified — "
            "'no distortions' is unsupported.",
            forbids=("No distortions flagged", "numbers appear clean", "Trust is high"),
        )]
    return []


def gate_a3_no_consensus_no_verdict(f: Filing) -> list[Flag]:
    if f.consensus_count == 0:
        return [Flag(
            "A3_NO_CONSENSUS", Severity.HIGH,
            "No quantitative estimates exist. Verdict field must be suppressed.",
            forbids=("MET", "BEAT", "MISSED"),
        )]
    return []


# ---------------------------------------------------------------------------
# Group B — margin decomposition
# ---------------------------------------------------------------------------

def test_b1_incremental_margin(f: Filing, threshold: float = 2.5) -> list[Flag]:
    d_rev = f.current.revenue - f.year_ago.revenue
    d_ebitda = f.current.ebitda - f.year_ago.ebitda
    if d_rev <= 0:
        return []

    incremental = d_ebitda / d_rev
    baseline = median(f.margin_history) if f.margin_history else f.year_ago.margin
    if baseline <= 0:
        return []

    ratio = incremental / baseline
    if ratio > threshold:
        return [Flag(
            "B1_ANOMALOUS_INCREMENTAL_MARGIN", Severity.HIGH,
            f"Incremental margin {incremental:.1%} vs {baseline:.1%} median ({ratio:.1f}x). "
            "New revenue is far more profitable than the base business.",
        )]
    return []


def test_b2_operating_leverage_ceiling(f: Filing, tolerance: float = 3.0) -> list[Flag]:
    """The decisive test.

    Operating leverage is bounded by the size of the fixed cost base. If observed
    margin expansion materially exceeds that ceiling, leverage is not the cause.
    """
    if f.year_ago.fixed_costs <= 0 or f.current.revenue <= f.year_ago.revenue:
        return []

    fixed_ratio = f.year_ago.fixed_costs / f.year_ago.revenue
    ceiling_pp = fixed_ratio * (1 - f.year_ago.revenue / f.current.revenue) * 100
    observed_pp = (f.current.margin - f.year_ago.margin) * 100

    if ceiling_pp <= 0:
        return []

    ratio = observed_pp / ceiling_pp
    if ratio > tolerance:
        return [Flag(
            "B2_OPERATING_LEVERAGE_INSUFFICIENT", Severity.HIGH,
            f"Observed margin gain {observed_pp:.1f}pp vs theoretical leverage ceiling "
            f"{ceiling_pp:.1f}pp ({ratio:.1f}x). Fixed costs are only {fixed_ratio:.1%} of "
            "revenue — leverage arithmetically cannot produce this.",
            forbids=("operational leverage", "operating leverage",
                     "significant operational leverage realized"),
        )]
    return []


def test_b3_material_cost_direction(f: Filing) -> list[Flag]:
    cur, prev = f.current.rm_pct, f.year_ago.rm_pct
    if cur is None or prev is None or prev <= 0.70:
        return []

    growth = f.current.revenue / f.year_ago.revenue - 1
    if cur < prev and growth > 0.50:
        return [Flag(
            "B3_MARGIN_SOURCE_PRICE_NOT_OPERATIONS", Severity.HIGH,
            f"Raw material fell to {cur:.1%} of revenue from {prev:.1%} while revenue rose "
            f"{growth:.0%}. Realisations outran input costs — inventory holding gain or "
            "scarcity pricing, not operational improvement.",
        )]
    return []


# ---------------------------------------------------------------------------
# Group C — price vs volume
# ---------------------------------------------------------------------------

def test_c1_no_volume_no_demand_claim(f: Filing) -> list[Flag]:
    if not f.volume_disclosed:
        return [Flag(
            "C1_VOLUME_NOT_DISCLOSED", Severity.HIGH,
            "Revenue growth not decomposed into price vs volume. Demand attribution blocked.",
            forbids=("strong demand", "volume-led", "demand-driven",
                     "core operations", "explosive growth"),
        )]
    return []


def test_c2_commodity_crosscheck(f: Filing) -> list[Flag]:
    if f.input_index_change_yoy is None or f.volume_disclosed:
        return []
    growth = f.current.revenue / f.year_ago.revenue - 1
    if f.input_index_change_yoy > 0.50 and growth > 0.50:
        return [Flag(
            "C2_PRESUMED_PRICE_DRIVEN", Severity.HIGH,
            f"Input index +{f.input_index_change_yoy:.0%} against revenue +{growth:.0%}. "
            "Presume price-driven until volume is disclosed.",
        )]
    return []


# ---------------------------------------------------------------------------
# Group D — peer correlation
# ---------------------------------------------------------------------------

@dataclass
class Peer:
    ticker: str
    margin_delta_pp: float
    value_chain: ValueChain


def test_d2_peer_correlation(f: Filing, peers: list[Peer]) -> list[Flag]:
    same_chain = [p for p in peers if p.value_chain == f.value_chain]
    if len(same_chain) < 2:
        return [Flag(
            "D1_INSUFFICIENT_PEERS", Severity.BLOCK,
            f"Only {len(same_chain)} same-value-chain peers available. "
            "Cannot distinguish idiosyncratic from sector-wide.",
        )]

    subject_delta = (f.current.margin - f.year_ago.margin) * 100
    correlated = [
        p for p in same_chain
        if (p.margin_delta_pp > 0) == (subject_delta > 0)
        and abs(p.margin_delta_pp) > 0.5 * abs(subject_delta)
    ]

    if len(correlated) >= 2:
        names = ", ".join(f"{p.ticker} {p.margin_delta_pp:+.1f}pp" for p in correlated)
        return [Flag(
            "D2_SECTOR_WIDE_INPUT_PRICE_EVENT", Severity.HIGH,
            f"{len(correlated)} unrelated peers moved the same way, same quarter ({names}). "
            "Driver is exogenous, not company execution.",
            forbids=("core operations", "strong operational performance",
                     "exceptional operational performance"),
        )]
    return []


def test_d3_wrong_peer_set(f: Filing, peers: list[Peer]) -> list[Flag]:
    wrong = [p for p in peers if p.value_chain != f.value_chain]
    if wrong:
        names = ", ".join(f"{p.ticker}({p.value_chain.value})" for p in wrong)
        return [Flag(
            "D3_CROSS_CHAIN_PEER", Severity.INFO,
            f"Excluded from peer maths — different value-chain position: {names}. "
            f"Subject is {f.value_chain.value}.",
        )]
    return []


# ---------------------------------------------------------------------------
# Group E — cyclical logic
# ---------------------------------------------------------------------------

def test_e2_peak_margin_is_bearish(f: Filing) -> list[Flag]:
    if f.value_chain != ValueChain.CONVERTER or not f.margin_history:
        return []
    if f.current.margin > max(f.margin_history):
        return [Flag(
            "E2_CYCLE_PEAK", Severity.HIGH,
            f"Margin {f.current.margin:.1%} is the highest in {len(f.margin_history)} quarters "
            "for a spread business. For a converter this indicates cycle position, not durable "
            "improvement. Base rate is mean reversion.",
        )]
    return []


def test_e3_inventory_price_exposure(f: Filing) -> list[Flag]:
    if f.inventory_days is None or f.input_price_direction is None:
        return []
    quarters = f.inventory_days / 90
    if quarters < 0.5:
        return []

    if f.input_price_direction == "RISING":
        effect = "HOLDING GAIN — transient profit, reverses symmetrically when prices fall"
    elif f.input_price_direction == "FALLING":
        effect = "HOLDING LOSS + inventory writedown"
    else:
        return []

    return [Flag(
        "E3_INVENTORY_PRICE_EXPOSURE", Severity.HIGH,
        f"{f.inventory_days:.0f} inventory days = {quarters:.2f} quarters carried at "
        f"historical cost. Input prices {f.input_price_direction}. Effect: {effect}",
    )]


def test_e4_upstream_leading_indicator(
    f: Filing, upstream_qoq_change: Optional[float], upstream_name: str = "upstream"
) -> list[Flag]:
    if upstream_qoq_change is None or f.prior_quarter is None:
        return []
    subject_qoq = f.current.pat / f.prior_quarter.pat - 1 if (
        f.current.pat and f.prior_quarter.pat) else None
    if subject_qoq is None:
        return []

    if upstream_qoq_change < 0 < subject_qoq:
        return [Flag(
            "E4_UPSTREAM_ALREADY_ROLLED_OVER", Severity.HIGH,
            f"{upstream_name} {upstream_qoq_change:+.0%} QoQ while subject {subject_qoq:+.0%} QoQ. "
            "Upstream peaked one quarter earlier — inventory lag means the roll reaches the "
            "converter next print.",
        )]
    return []


# ---------------------------------------------------------------------------
# Group F — normalisation
# ---------------------------------------------------------------------------

@dataclass
class Valuation:
    reported_pe: Optional[float]
    margin_normalised_pe: Optional[float]
    fully_normalised_pe: Optional[float]


def compute_valuations(f: Filing) -> Valuation:
    if not (f.shares_cr and f.price and f.current.pat):
        return Valuation(None, None, None)

    norm_margin = median(f.margin_history) if f.margin_history else f.year_ago.margin
    trend_rev = median(f.revenue_history) if f.revenue_history else f.year_ago.revenue

    reported_eps_annual = (f.current.pat / f.shares_cr) * 4

    margin_norm_pat = f.current.revenue * norm_margin * (1 - f.tax_rate)
    margin_norm_eps = (margin_norm_pat / f.shares_cr) * 4

    full_norm_pat = trend_rev * norm_margin * (1 - f.tax_rate)
    full_norm_eps = (full_norm_pat / f.shares_cr) * 4

    return Valuation(
        reported_pe=f.price / reported_eps_annual,
        margin_normalised_pe=f.price / margin_norm_eps,
        fully_normalised_pe=f.price / full_norm_eps,
    )


def test_f3_earnings_rejection(v: Valuation) -> list[Flag]:
    if v.reported_pe is not None and v.reported_pe < 5:
        return [Flag(
            "F3_MARKET_IMPLIED_EARNINGS_REJECTION", Severity.HIGH,
            f"Forward P/E on reported earnings is {v.reported_pe:.1f}x. Markets do not price "
            "durable earnings this low. The refusal to re-rate is the market's own "
            "earnings-quality verdict.",
        )]
    return []


# ---------------------------------------------------------------------------
# Group H — signal hygiene
# ---------------------------------------------------------------------------

TRIVIAL_FLAG_PATTERNS = (
    "board meeting", "meeting duration", "concluded in", "minutes",
    "pdf", "page count", "file size", "filing time",
)

BANNED_TRUST_PHRASES = (
    "trust is high", "numbers appear clean", "no distortions",
    "can be trusted", "verified clean",
)


def strip_trivial_flags(flags: list[str]) -> tuple[list[str], list[str]]:
    kept, dropped = [], []
    for fl in flags:
        (dropped if any(p in fl.lower() for p in TRIVIAL_FLAG_PATTERNS) else kept).append(fl)
    return kept, dropped


def test_h3_internal_consistency(f: Filing, tol_pp: float = 0.2) -> list[Flag]:
    if f.reported_margin is None:
        return []
    diff = abs(f.current.margin - f.reported_margin) * 100
    if diff > tol_pp:
        return [Flag(
            "H3_INPUT_INCONSISTENCY", Severity.HIGH,
            f"Computed margin {f.current.margin:.2%} vs reported {f.reported_margin:.2%} "
            f"({diff:.2f}pp apart). Reconcile before publishing any confidence language.",
        )]
    return []


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def evaluate(
    f: Filing,
    peers: list[Peer] | None = None,
    upstream_qoq: Optional[float] = None,
    upstream_name: str = "upstream",
) -> dict:
    peers = peers or []
    flags: list[Flag] = []

    flags += gate_a1_interim_filing(f)
    flags += gate_a2_empty_is_not_clean(f)
    flags += gate_a3_no_consensus_no_verdict(f)
    flags += test_b1_incremental_margin(f)
    flags += test_b2_operating_leverage_ceiling(f)
    flags += test_b3_material_cost_direction(f)
    flags += test_c1_no_volume_no_demand_claim(f)
    flags += test_c2_commodity_crosscheck(f)
    flags += test_d2_peer_correlation(f, peers)
    flags += test_d3_wrong_peer_set(f, peers)
    flags += test_e2_peak_margin_is_bearish(f)
    flags += test_e3_inventory_price_exposure(f)
    flags += test_e4_upstream_leading_indicator(f, upstream_qoq, upstream_name)
    flags += test_h3_internal_consistency(f)

    valuation = compute_valuations(f)
    flags += test_f3_earnings_rejection(valuation)

    codes = {fl.code for fl in flags}
    price_driven = codes & {
        "B1_ANOMALOUS_INCREMENTAL_MARGIN",
        "B2_OPERATING_LEVERAGE_INSUFFICIENT",
        "B3_MARGIN_SOURCE_PRICE_NOT_OPERATIONS",
    }

    if "E3_INVENTORY_PRICE_EXPOSURE" in codes and price_driven:
        driver = "INVENTORY_GAIN"
    elif price_driven or "C2_PRESUMED_PRICE_DRIVEN" in codes:
        driver = "PRICE"
    elif "A1_NO_CASHFLOW_THIS_QUARTER" in codes:
        driver = "UNVERIFIED"
    else:
        driver = "OPERATIONS"

    forbidden = sorted({tok for fl in flags for tok in fl.forbids})

    return {
        "ticker": f.ticker,
        "margin_driver": driver,
        "cycle_position": "PEAK" if "E2_CYCLE_PEAK" in codes else "UNKNOWN",
        "data_completeness": "FULL" if (f.has_balance_sheet and f.has_cash_flow) else "P&L_ONLY",
        "peer_correlation": ("SECTOR_WIDE" if "D2_SECTOR_WIDE_INPUT_PRICE_EVENT" in codes
                             else "UNKNOWN"),
        "persistence": "TRANSIENT" if driver in ("INVENTORY_GAIN", "PRICE") else "UNKNOWN",
        "annualisable": not bool(price_driven),
        "valuation": valuation,
        "flags": flags,
        "forbidden_narrative": forbidden,
    }


# ---------------------------------------------------------------------------
# Self-test — PANAMAPET Q1 FY27
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    panama = Filing(
        ticker="PANAMAPET",
        quarter_label="Q1",
        market="IN",
        value_chain=ValueChain.CONVERTER,
        current=Quarter(
            "Q1FY27", revenue=1735.15, ebitda=391.76, pat=308.91,
            depreciation=4.0, employee_cost=22.0, other_fixed_opex=12.0,
            material_cost=1735.15 * 0.72,
        ),
        year_ago=Quarter(
            "Q1FY26", revenue=693.22, ebitda=58.90, pat=42.60,
            depreciation=3.0, employee_cost=17.0, other_fixed_opex=10.0,
            material_cost=693.22 * 0.86,
        ),
        prior_quarter=Quarter("Q4FY26", revenue=823.0, ebitda=91.0, pat=71.08),
        # trailing 8 quarters of OPM, oldest -> newest
        margin_history=[0.10, 0.08, 0.09, 0.09, 0.08, 0.09, 0.08, 0.11],
        revenue_history=[671, 699, 728, 695, 693, 773, 775, 823],
        has_balance_sheet=False,
        has_cash_flow=False,
        volume_disclosed=False,
        consensus_count=0,
        inventory_days=97,
        input_price_direction="RISING",
        input_index_change_yoy=0.83,      # crude basket $69 -> $126
        shares_cr=6.05,
        price=518.75,
        tax_rate=0.19,
        reported_margin=0.2235,           # the brief printed 22.35%; computed is 22.58%
    )

    peer_set = [
        Peer("GANDHAR", margin_delta_pp=+11.2, value_chain=ValueChain.CONVERTER),
        Peer("SAVITA",  margin_delta_pp=+20.8, value_chain=ValueChain.CONVERTER),
        Peer("CPCL",    margin_delta_pp=+9.5,  value_chain=ValueChain.REFINER),
    ]

    result = evaluate(panama, peer_set, upstream_qoq=-0.27, upstream_name="CPCL (refiner)")

    print("=" * 78)
    print(f"  {result['ticker']}  Q1 FY27  —  earnings quality evaluation")
    print("=" * 78)
    for k in ("margin_driver", "cycle_position", "data_completeness",
              "peer_correlation", "persistence", "annualisable"):
        print(f"  {k:20} {result[k]}")

    v = result["valuation"]
    print(f"\n  Valuation")
    print(f"  {'reported P/E':20} {v.reported_pe:.1f}x   <- what retail annualises")
    print(f"  {'margin-normalised':20} {v.margin_normalised_pe:.1f}x")
    print(f"  {'fully normalised':20} {v.fully_normalised_pe:.1f}x   <- decision-useful")

    print(f"\n  Flags fired: {len(result['flags'])}")
    for fl in result["flags"]:
        print(f"   {fl}")

    print(f"\n  Narrative tokens now forbidden:")
    for tok in result["forbidden_narrative"]:
        print(f"   - {tok}")

    kept, dropped = strip_trivial_flags([
        "Board meeting concluded in just 40 minutes",
        "Promoter holding decreased over 3 years",
    ])
    print(f"\n  Trivial flags dropped by H1: {dropped}")
    print(f"  Real flags kept:              {kept}")
    print("=" * 78)
