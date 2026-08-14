"""
==========================================================
Where the margin came from -- operations, or the whole sector at once
==========================================================

    "i took trade after seeing excellent reuslts & it dragged me
     around 10K now"
    "show me the details in this way respective to the company, based
     on that bot decision can be built & trade"
                                -- operator, 12 August 2026

WHAT HAPPENED
-------------
PANAMAPET printed Q1 FY27 with PULSE EXCELLENT and CLEAN -- the two
strongest chips on the screen, measured at +3.04% together. It made a
new all-time high at 599.60 and closed at 518.75. One stop-out.

The card was not wrong about the numbers. Revenue +150%, EBITDA margin
8.5% -> 22.6%, PAT +625%. Every figure on it was real.

What no card said is that GANDHAR had printed the same shape on
23 JULY -- twenty days earlier -- and SAVITA the same week. Three
companies that buy the same input (base oil) tripled margins in the
same quarter, because the Strait of Hormuz was shut and the input
price dislocated. Not one of them out-executed anything.

By the time PANAMAPET's card reached the screen the trade was twenty
days old.

WHAT THIS MODULE DOES, AND WHAT IT DELIBERATELY DOES NOT
--------------------------------------------------------
It does NOT touch the tag. See core/result_tag.py and SHILPAMED,
5 August 2026 -- a forensic flag was allowed to say SKIP and the stock
closed +11.96%. The rule that came out of that day stands:

    "It only becomes a rule if it earns one against real outcomes."

So this returns a NOTE and a CHIP. The chip is drawn, it is logged
against outcomes like every other chip, and it earns a rule or it does
not. Nothing here can stop a trade today.

WHY THIS IS NOT THE SAME ARGUMENT AS FORENSIC QUALITY
-----------------------------------------------------
This is the part that matters, and it is why the SHILPAMED lesson does
not simply kill this idea.

    FORENSIC QUALITY asks  "will this profit repeat next quarter?"
    -- an INVESTOR's question, on a horizon he does not trade.
    A one-off tax credit does not stop a stock running 12% today.

    PEER CORRELATION asks  "is this news, or is it twenty days old?"
    -- a question about whether the information has already been
    priced, which is exactly a 1-3 day question.

Those are different claims. The first was measured and demoted. The
second has never been measured here, and this module exists to make it
measurable rather than to assert it.

WHAT IT READS
-------------
Only fields core/result_read.py already produces. Nothing new is
fetched, no new source, no new key:

    quarters["sales"]  {now, prev, year}
    quarters["op"]     {now, prev, year}
    quarters["opm"]    {now, prev, year}     margin, in percent

and, for the peer test, the same three numbers for every OTHER symbol
that reported inside the same 36-hour window.

Author : H&M Opportunity Trader
==========================================================
"""

from __future__ import annotations

# Fixed opex as a share of revenue. Operating leverage means spreading
# a FIXED base over more revenue, so the gain it can produce is bounded
# by the size of that base -- arithmetic, not opinion.
#
# 15% is deliberately generous. Manufacturers run 8-12%; a commodity
# converter is nearer 4%. Being generous makes the flag HARDER to fire,
# which is the direction an unmeasured flag should err in.
#
# The first version guessed the business model from the ticker string
# and asked whether "PANAMAPET" contained "PETRO". It does not. Reading
# a business model out of the spelling of its symbol was never sound;
# one generous bound applied to everything needs no guess at all.
_FIXED_OPEX_SHARE = 0.15

MIN_PEERS = 2                     # below this, say nothing
PEER_SHARE = 0.5                  # peer must move >=50% as far, same way


def _q(fields, key):
    q = ((fields or {}).get("quarters") or {}).get(key) or {}
    now, year = q.get("now"), q.get("year")
    return (now, year) if now is not None and year is not None else (None, None)


def incremental_margin(fields):
    """Margin earned on the NEW revenue only, as a fraction. None if unreadable.

    A business whose through-cycle margin is 9% does not earn 32% on
    incremental revenue by operating better.
    """
    sales_now, sales_year = _q(fields, "sales")
    op_now, op_year = _q(fields, "op")
    if None in (sales_now, sales_year, op_now, op_year):
        return None
    d_sales = sales_now - sales_year
    if d_sales <= 0:
        return None
    return (op_now - op_year) / d_sales


def leverage_ceiling_pp(fields, symbol=None):
    """Most margin, in percentage points, that operating leverage can explain.

    Spreading a fixed base over more revenue is bounded by the size of
    that base. Returns None if unreadable.
    """
    sales_now, sales_year = _q(fields, "sales")
    if None in (sales_now, sales_year) or sales_now <= sales_year or sales_year <= 0:
        return None
    return _FIXED_OPEX_SHARE * (1 - sales_year / sales_now) * 100


def margin_delta_pp(fields):
    """Margin expansion in percentage points, YoY. None if unreadable."""
    opm_now, opm_year = _q(fields, "opm")
    if None not in (opm_now, opm_year):
        return opm_now - opm_year
    sales_now, sales_year = _q(fields, "sales")
    op_now, op_year = _q(fields, "op")
    if None in (sales_now, sales_year, op_now, op_year) or not (sales_now and sales_year):
        return None
    return (op_now / sales_now - op_year / sales_year) * 100


def peer_correlation(symbol, my_delta_pp, peers):
    """Which other names moved the same way, the same quarter.

    `peers` is [{"symbol", "delta_pp", "sector", "at"}, ...] for every
    OTHER stock that reported in the window. Returns the correlated
    subset, newest reporters last.
    """
    if my_delta_pp is None or abs(my_delta_pp) < 1.0:
        return []
    out = []
    for p in peers or []:
        if str(p.get("symbol") or "").upper() == str(symbol or "").upper():
            continue
        d = p.get("delta_pp")
        if d is None or abs(d) < 1.0:
            continue
        if (d > 0) != (my_delta_pp > 0):
            continue
        if abs(d) >= PEER_SHARE * abs(my_delta_pp):
            out.append(p)
    return out


def assess(symbol, fields, peers=None, sector=None):
    """{"driver", "chip", "note", "why"} -- or None when nothing is readable.

    NEVER returns a tag. It cannot stop a trade. It is drawn, logged and
    graded, and it earns a rule or it does not.
    """
    delta = margin_delta_pp(fields)
    if delta is None:
        return None

    why = []
    driver = "UNKNOWN"

    # ---- 1. did the whole sector print this? (same-day relevance) ----
    correlated = peer_correlation(symbol, delta, peers)
    if len(correlated) >= MIN_PEERS:
        driver = "SECTOR_WIDE"
        names = ", ".join(
            f'{p["symbol"]} {p["delta_pp"]:+.0f}pp' for p in correlated[:4])
        why.append(f"{len(correlated)} peers printed the same shape: {names}")
        first = min((p.get("at") or "") for p in correlated if p.get("at"))
        if first:
            why.append(f"first of them reported {first[:10]} -- "
                       "this is not new information today")

    # ---- 2. can operating leverage explain it at all? ----
    ceiling = leverage_ceiling_pp(fields, symbol)
    if ceiling and delta > 0 and delta > ceiling:
        why.append(f"margin +{delta:.1f}pp exceeds the +{ceiling:.1f}pp "
                   "operating leverage could give even assuming fixed "
                   "costs are 15% of revenue")
        if driver == "UNKNOWN":
            driver = "PRICE"

    # ---- 3. is the new revenue absurdly more profitable than the old? ----
    inc = incremental_margin(fields)
    opm_now, opm_year = _q(fields, "opm")
    if inc is not None and opm_year:
        base = opm_year / 100
        if base > 0 and inc > 2.5 * base:
            why.append(f"incremental margin {inc:.0%} vs {base:.0%} a year "
                       f"ago ({inc / base:.1f}x)")
            if driver == "UNKNOWN":
                driver = "PRICE"

    if driver == "UNKNOWN" or not why:
        return None

    if driver == "SECTOR_WIDE":
        chip = "SECTOR-WIDE MARGIN"
        note = ("every peer printed this same quarter -- the move is the "
                "input price, not this company. check if it is already "
                "priced in before paying up")
    else:
        chip = "MARGIN = PRICE"
        note = ("margin came from price, not operations -- fine to trade "
                "today, do not size it like a re-rating")

    return {"driver": driver, "chip": chip, "note": note,
            "why": why, "delta_pp": round(delta, 1),
            "peers": [p["symbol"] for p in correlated]}
