"""
earnings_panel.py — per-company decision card for Opportunity Trader
====================================================================

Takes the publisher chips (PULSE EXCELLENT / CLEAN / ONE-OFF) that the bot
already relays, runs the quality layer from earnings_quality.py over the same
filing, and emits ONE action.

Design intent, per RULE_BOOK.md §2:
  - The publisher chips are NOT replaced. They keep their measured edge.
  - This adds the veto that is currently missing on the positive side.
    Today the only negative veto is ONE-OFF (-0.90%, n=27). Nothing catches
    "excellent, but the driver is exogenous".
  - Same class as the existing `SKIP - sources disagree`.

    SKIP - margin driver is price
      fires when: PULSE EXCELLENT or CLEAN present
      AND         margin_driver in {INVENTORY_GAIN, PRICE}
                  or cycle_position == PEAK

Sizing constants read from config.py (RULE_BOOK.md 2A):
    MTF_MARGIN_PER_POSITION_RS = 100_000
    HARD_STOP_FROM_ENTRY_PCT   = 2.5
    DAILY_LOSS_CAP_RS          = 40_000

    python earnings_panel.py
"""

from __future__ import annotations

from dataclasses import dataclass, field

from earnings_quality import (
    Filing, Quarter, Peer, ValueChain, evaluate,
)

# --- sizing constants (mirror config.py) -----------------------------------
MTF_MARGIN_PER_POSITION_RS = 100_000
HARD_STOP_FROM_ENTRY_PCT = 2.5
ROUND_TRIP_CHARGES_RS = 181
DAILY_LOSS_CAP_RS = 40_000
TYPICAL_MTF_LEVERAGE = 3.8          # stock value / own margin

# --- measured chip edges (RULE_BOOK.md 2, re-verified 1 Aug 2026) ----------
CHIP_EDGE = {
    "DOUBLE":           ("+3.04%", "77%", 22),
    "PULSE EXCELLENT":  ("+2.17%", "80%", 25),
    "CLEAN":            ("+0.81%", "59%", 54),
    "ONE-OFF":          ("-1.61%", "28%", 25),
}

W = 74


@dataclass
class PanelInput:
    ticker: str
    quarter: str
    as_of: str
    price: float
    chips: list[str] = field(default_factory=list)   # publisher chips relayed by bot
    filing: Filing = None
    peers: list[Peer] = field(default_factory=list)
    upstream_qoq: float | None = None
    upstream_name: str = "upstream"
    notes: list[str] = field(default_factory=list)


def _rule(ch="=") -> str:
    return ch * W


def _kv(k: str, v: str, indent: int = 1) -> str:
    return f"{' ' * indent}{k:<18}{v}"


def decide(p: PanelInput) -> dict:
    """Return the action and the evidence behind it."""
    q = evaluate(p.filing, p.peers, p.upstream_qoq, p.upstream_name)

    positives = [c for c in p.chips if c in ("PULSE EXCELLENT", "CLEAN")]
    has_oneoff = "ONE-OFF" in p.chips

    veto = None
    if positives and (q["margin_driver"] in ("INVENTORY_GAIN", "PRICE")
                      or q["cycle_position"] == "PEAK"):
        veto = "SKIP - margin driver is price"
    elif positives and has_oneoff:
        veto = "SKIP - sources disagree"

    if veto:
        action = "SKIP"
    elif len(positives) == 2:
        action = "DOUBLE - trade"
    elif positives:
        action = "TRADE"
    else:
        action = "NO SIGNAL"

    return {"quality": q, "veto": veto, "action": action, "positives": positives}


def render(p: PanelInput) -> str:
    d = decide(p)
    q, v = d["quality"], d["quality"]["valuation"]
    out: list[str] = []

    out.append(_rule())
    out.append(f" {p.ticker} · {p.quarter} · {p.as_of}".ljust(W - 12) + f"₹{p.price:,.2f}")
    out.append(_rule())

    # ---- publisher chips (what the bot relays today) ----
    if p.chips:
        chip_str = "   ".join(f"{c} ✦" if c in ("PULSE EXCELLENT", "CLEAN") else c
                              for c in p.chips)
        out.append(_kv("PUBLISHER CHIPS", chip_str))
        key = "DOUBLE" if len(d["positives"]) == 2 else (
            d["positives"][0] if d["positives"] else None)
        if key and key in CHIP_EDGE:
            e, hit, n = CHIP_EDGE[key]
            out.append(_kv("", f"historical edge {e}, beats mkt {hit} · n={n}"))
    else:
        out.append(_kv("PUBLISHER CHIPS", "none"))
    out.append("")

    # ---- quality layer ----
    if d["veto"]:
        out.append(_kv("QUALITY VETO", f"⛔ {d['veto']}"))
    else:
        out.append(_kv("QUALITY VETO", "none - quality layer clear"))
    out.append(" " + "-" * (W - 2))

    out.append(_kv("margin_driver", q["margin_driver"]))
    out.append(_kv("cycle_position", q["cycle_position"]))
    out.append(_kv("peer_correlation", q["peer_correlation"]))
    out.append(_kv("data", q["data_completeness"]))
    out.append(_kv("persistence", q["persistence"]))
    out.append(_kv("annualisable", "YES" if q["annualisable"] else "NO"))
    out.append("")

    # ---- why ----
    high = [f for f in q["flags"] if f.severity.value in ("HIGH", "BLOCK")]
    if high:
        out.append(_kv("WHY", ""))
        for f in high[:7]:
            msg = f.message.split(". ")[0].rstrip(".")
            if len(msg) > W - 6:
                msg = msg[:W - 9] + "..."
            out.append(f"  · {msg}")
        if len(high) > 7:
            out.append(f"  · (+{len(high) - 7} more flags)")
        out.append("")

    # ---- valuation ----
    if v.reported_pe:
        out.append(_kv("VALUATION",
                       f"reported {v.reported_pe:.1f}x  |  "
                       f"normalised {v.fully_normalised_pe:.1f}x"))
        out.append("")

    # ---- action + sizing ----
    out.append(_kv("ACTION", d["action"]))

    stock_value = MTF_MARGIN_PER_POSITION_RS * TYPICAL_MTF_LEVERAGE
    stop_rs = stock_value * HARD_STOP_FROM_ENTRY_PCT / 100 + ROUND_TRIP_CHARGES_RS

    if d["action"] == "SKIP":
        out.append(_kv("IF OVERRIDDEN",
                       f"intraday only · 0.25x size · stop {HARD_STOP_FROM_ENTRY_PCT}% "
                       f"= ₹{stop_rs * 0.25:,.0f}"))
    else:
        out.append(_kv("SIZE",
                       f"₹{MTF_MARGIN_PER_POSITION_RS:,} margin · stop "
                       f"{HARD_STOP_FROM_ENTRY_PCT}% = ₹{stop_rs:,.0f} "
                       f"({DAILY_LOSS_CAP_RS // int(stop_rs)} stop-outs = daily cap)"))

    out.append(_kv("HORIZON", "same-day - chip edge is measured from open/chip time"))
    out.append(_kv("FALSIFIER", q["flags"] and "see below" or "-"))
    out.append(f"  · {p.notes[0] if p.notes else 'n/a'}")
    out.append(_rule())
    return "\n".join(out)


# ===========================================================================
# LIVE CASES - Q1 FY27, all reported within 3 weeks of each other
# ===========================================================================

CONVERTER_PEERS = [
    Peer("GANDHAR", margin_delta_pp=+11.2, value_chain=ValueChain.CONVERTER),
    Peer("SAVITA",  margin_delta_pp=+18.6, value_chain=ValueChain.CONVERTER),
    Peer("PANAMA",  margin_delta_pp=+14.1, value_chain=ValueChain.CONVERTER),
    Peer("CPCL",    margin_delta_pp=+9.5,  value_chain=ValueChain.REFINER),
]


def _converter(ticker, rev_c, ebitda_c, pat_c, rev_p, ebitda_p, pat_p,
               prior_q_rev, prior_q_ebitda, prior_q_pat,
               margin_hist, rev_hist, shares, price, rm_c, rm_p, inv_days):
    return Filing(
        ticker=ticker, quarter_label="Q1", market="IN",
        value_chain=ValueChain.CONVERTER,
        current=Quarter("Q1FY27", revenue=rev_c, ebitda=ebitda_c, pat=pat_c,
                        depreciation=rev_c * 0.0023, employee_cost=rev_c * 0.013,
                        other_fixed_opex=rev_c * 0.007, material_cost=rev_c * rm_c),
        year_ago=Quarter("Q1FY26", revenue=rev_p, ebitda=ebitda_p, pat=pat_p,
                         depreciation=rev_p * 0.0043, employee_cost=rev_p * 0.025,
                         other_fixed_opex=rev_p * 0.014, material_cost=rev_p * rm_p),
        prior_quarter=Quarter("Q4FY26", revenue=prior_q_rev,
                              ebitda=prior_q_ebitda, pat=prior_q_pat),
        margin_history=margin_hist, revenue_history=rev_hist,
        has_balance_sheet=False, has_cash_flow=False,
        volume_disclosed=False, consensus_count=0,
        inventory_days=inv_days, input_price_direction="RISING",
        input_index_change_yoy=0.83,
        shares_cr=shares, price=price, tax_rate=0.19,
    )


CASES = [
    PanelInput(
        ticker="PANAMAPET", quarter="Q1 FY27", as_of="12 Aug 2026", price=518.75,
        chips=["PULSE EXCELLENT", "CLEAN"],
        filing=_converter("PANAMAPET", 1735.15, 391.76, 308.91, 693.22, 58.90, 42.60,
                          823.0, 91.0, 71.08,
                          [.10, .08, .09, .09, .08, .09, .08, .11],
                          [671, 699, 728, 695, 693, 773, 775, 823],
                          6.05, 518.75, 0.72, 0.86, 97),
        peers=CONVERTER_PEERS, upstream_qoq=-0.27, upstream_name="CPCL (refiner)",
        notes=["Q2 EBITDA margin holding >18%, or tonnage disclosure showing +100% volume"],
    ),
    PanelInput(
        ticker="GANDHAR", quarter="Q1 FY27", as_of="23 Jul 2026", price=184.55,
        chips=["PULSE EXCELLENT"],
        filing=_converter("GANDHAR", 1731.93, 281.26, 192.29, 907.0, 46.17, 26.20,
                          1093.37, 63.52, 40.68,
                          [.052, .048, .055, .051, .051, .058, .054, .058],
                          [850, 880, 920, 900, 907, 1010, 1050, 1093],
                          9.79, 184.55, 0.74, 0.88, 88),
        peers=CONVERTER_PEERS, upstream_qoq=-0.27, upstream_name="CPCL (refiner)",
        notes=["Q2 operating margin holding >12%"],
    ),
    PanelInput(
        ticker="SAVITA", quarter="Q1 FY27", as_of="Aug 2026", price=605.65,
        chips=["CLEAN"],
        filing=_converter("SAVITA", 1479.76, 364.00, 292.25, 989.14, 60.67, 58.92,
                          1005.0, 68.34, 55.10,
                          [.060, .058, .063, .061, .061, .066, .062, .068],
                          [930, 950, 985, 970, 989, 1020, 1040, 1005],
                          6.85, 605.65, 0.71, 0.87, 92),
        peers=CONVERTER_PEERS, upstream_qoq=-0.27, upstream_name="CPCL (refiner)",
        notes=["Q2 EBITDA margin holding >18%"],
    ),
]


if __name__ == "__main__":
    for case in CASES:
        print(render(case))
        print()

    print(_rule("#"))
    print(" PORTFOLIO-LEVEL WARNING")
    print(_rule("#"))
    print(" All three names are CONVERTER tag, same input (base oil), same")
    print(" driver (Hormuz supply dislocation), same quarter.")
    print("")
    print(" Holding 2+ of these is ONE position sized 2-3x, not diversification.")
    print(f" 3 full positions = ₹{3 * 9665:,} of correlated risk against a")
    print(f" ₹{DAILY_LOSS_CAP_RS:,} daily cap. A single Hormuz headline moves all three.")
    print("")
    print(" RULE: max 1 open position per value_chain tag per input commodity.")
    print(_rule("#"))
