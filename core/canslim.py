"""
==========================================================
Layer 06 -- the actionable setup, as THEY grade it
==========================================================

    "Have you forgot SEBI mandates about no stock buy / sell
     recommendations? no one gives that signals. these channels
     provide data with vedict. after connecting all points (we used to
     do this - hectic work gone by outsourcing them) now your only
     work is to show me as instant as possible"
                                    -- operator, 2 August 2026

That settles a design argument that ran for an hour. A chip reading
"BUY" would be a RECOMMENDATION, which is the one thing nobody in this
chain issues -- Earnings Pulse says so on their own page:

    "We don't tell you whether to buy, hold, or skip a name."
    "Earnings Pulse is not registered with SEBI as an Investment
     Adviser or Research Analyst."

So this module reports a TIER. It never says buy, sell, hold or skip,
and the test file fails if those words appear in a headline.

WHAT THIS IS
------------
CANSLIM Ratings (TechnoFunda) is the sixth and last read in their
chain. Every Indian filing is scored the same evening and placed in
one of four tiers by 11 PM IST:

    EXCEPTIONAL  best-in-class, rare -- typically 0-3 names a day
    STRONG       clear pass on the strongest lenses
    MIXED        some lenses pass, some fail
    WEAK         multiple weakness signals dominate

1 August 2026: 92 candidates -> 4 / 15 / 42 / 31.

WHY IT IS NOT THE SAME AS THE PULSE GRADE
-----------------------------------------
Checked against the store the day it arrived, and TWELVE OF THIRTEEN
disagreed:

    SHADOWFAX   CANSLIM EXCEPTIONAL   Pulse GOOD
    AETHER      CANSLIM EXCEPTIONAL   Pulse GOOD
    DIVISLAB    CANSLIM EXCEPTIONAL   Pulse GOOD
    CORONA      CANSLIM STRONG        Pulse OK

Neither is wrong. They measure different things. The Pulse grade is
the QUARTER; their own beginner guide says "Good -- positive, can go
either way", and outcome tracking measured PULSE GOOD at +0.02% on 149
samples, which is nothing.

CANSLIM adds the rest of the lenses. Their words:

    "EXCEPTIONAL -- exceptional fit on multiple lenses, clean earnings
     quality, TECHNICALLY PRIMED"

"Technically primed" is the chart. That is the leg this bot has never
had, and it closes the Stockbee-versus-Stage-2 question without the
operator having to choose: they already blend fundamental and
technical.

WHY A FILE AND NOT A PARSER
---------------------------
The tiers live on a WEBPAGE, not a channel -- only 4 of 2,967 stored
messages even mention CANSLIM. But the page exports a TradingView
watchlist, which is clean structured text:

    ### EXCEPTIONAL,
    NSE:DIVISLAB,
    NSE:AETHER,

No OCR, nothing to misread, no grade attached to the wrong company.
After a weekend of fighting damaged screenshots this is the only
source in the whole system that cannot be misread.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import re
import sqlite3

TIERS = ("EXCEPTIONAL", "STRONG", "MIXED", "WEAK")

# ---- THE ORDER IS THE WHOLE POINT. 2 August 2026. ----
#
#     "watchlist is just like bot decision first come = first serve. no
#      & never. some stocks had exceptional chip, strong chip, Mixed,
#      weak ... but no refining of these. in general Exceptional,
#      Strong stocks will be in primary focus in any table or any
#      where. NEVER TREAT WEAK = EXCEPTIONAL OR STRONG."
#
# He is right and the panel was indefensible: every bucket sorted
# ALPHABETICALLY, so AADHARHFC came before DIVISLAB whatever either of
# them was. Four names out of ninety are EXCEPTIONAL and they were
# sitting in the middle of a wall of sixty.
#
# One order, defined once, used by every list that shows a tier --
# defining it twice is how two panels start disagreeing about the same
# stock.
# ---- WHERE "NOBODY HAS RATED IT" GOES, AND WHY IT IS A JUDGEMENT ----
#
# He ruled on the top and on the bottom: EXCEPTIONAL and STRONG lead,
# WEAK is never treated as either. He did not rule on the case that is
# actually most common, and this is my reading of it, stated plainly so
# he can overrule it in one line.
#
# The ratings export covers 90 names. The master holds 1,245. So most
# companies reporting on any given day carry NO tier, and the question
# is whether an unrated name sorts above or below a WEAK one.
#
# Above. WEAK is a JUDGEMENT -- their own guide says the tier counts
# how many of three frameworks agree, so WEAK means the frameworks
# examined the stock and conflicted. Unrated is the ABSENCE of one.
# Sorting an examined-and-conflicted name above an unexamined one
# would be asserting something nobody measured.
#
# The counter-argument, which is real: that export is HIS OWN
# TradingView screen, so a name missing from it is a name his screen
# did not pick up. If he wants unrated at the bottom, this dict is the
# only thing that changes.
TIER_ORDER = {"EXCEPTIONAL": 0, "STRONG": 1, "MIXED": 2, "WEAK": 4}
NO_TIER = 3


def tier_rank(tier):
    """0 EXCEPTIONAL, 1 STRONG, 2 MIXED, 3 unrated, 4 WEAK."""
    return TIER_ORDER.get(str(tier or "").strip().upper(), NO_TIER)

# "### EXCEPTIONAL," -- the trailing comma is the exporter's, not ours.
_HEADING = re.compile(r"^\s*#{1,6}\s*([A-Za-z][A-Za-z ]{2,20})\s*,?\s*$")
_ROW = re.compile(r"^\s*NSE:([A-Za-z0-9&_\-]+)\s*,?\s*$")

# The export prefixes everything NSE:, including BSE-only scrips --
# "NSE:BSE-526935" is a BSE code wearing an NSE label. Two of them were
# in the 1 August file.
#
#     "pls make sure we will trade only NSE listed stocks"
#
# So a symbol carrying a BSE code, or one that is all digits, is
# refused rather than stored under a name that does not trade on NSE.
_BSE_CODE = re.compile(r"^BSE[-_]?\d+$|^\d+$", re.I)

DEFAULT_PATH = os.path.join("data", "opportunities_watchlist.txt")


def parse_watchlist(text, known=None):
    """[{symbol, tier}] from the exported watchlist.

    `known` optionally gates against the NSE master. The file is clean
    enough not to need it -- unlike every OCR source in this project --
    but a symbol that is not tradeable is still worth dropping before
    it reaches a panel.
    """
    body = str(text or "")
    if not body.strip():
        return []
    if known is not None:
        known = {str(s).upper() for s in known}

    out, seen = [], set()
    tier = None
    for line in body.splitlines():
        head = _HEADING.match(line)
        if head:
            word = head.group(1).strip().upper()
            tier = word if word in TIERS else None
            continue
        row = _ROW.match(line)
        if not row or tier is None:
            continue
        symbol = row.group(1).upper()
        if _BSE_CODE.match(symbol) or symbol in seen:
            continue
        if known is not None and symbol not in known:
            continue
        seen.add(symbol)
        out.append({"symbol": symbol, "tier": tier})
    return out


def counts(rows):
    """{tier: n}, in their own order."""
    got = {t: 0 for t in TIERS}
    for row in rows:
        got[row["tier"]] = got.get(row["tier"], 0) + 1
    return got


def headline_for(row, on=None):
    """The chip line. A TIER, never an instruction.

    SEBI, and their own disclaimer. The words buy, sell, hold and skip
    do not appear here and a test enforces that. What the operator does
    with "EXCEPTIONAL -- 1 of 4 today" is his decision, which is the
    only place that decision has ever lived.

    The RARITY is carried because it is most of the meaning. Their
    page says EXCEPTIONAL is "typically 0-3 names per day" out of
    around 92 -- a tier badge without that context reads like a
    grade rather than a shortlist.
    """
    tier = (row.get("tier") or "").upper()
    if tier not in TIERS:
        return None
    head = f"CANSLIM {tier}"
    rank = row.get("rank")
    total = row.get("of")
    if rank and total:
        head += f" -- {rank} of {total} today"
    if on:
        head += f" ({on.strftime('%d %b')})"
    return head[:200]


def stored_tiers(events_db="data/stock_events.db"):
    """{symbol: tier} from the SETUP events already in the store.

        "why divis, SHADOWFAX, AETHER, YASHO are not showing
         EXCEPTIONAL? in watchlist"
                                    -- operator, 2 August 2026

    All four were stored, all four EXCEPTIONAL, and none of them
    reached the watchlist -- the panel carried the symbol and the call
    and nothing else. This is the lookup that closes that gap.

    NEWEST WINS. tools/load_canslim.py files a fresh row every night,
    so a symbol has one entry per load and the tier can genuinely
    change between them. Reading an older one would show a tier the
    operator's own export no longer says.

    Never raises. A missing store means an empty dict and a watchlist
    with no tiers, which is what it looked like before.
    """
    out = {}
    try:
        conn = sqlite3.connect(events_db)
        rows = conn.execute(
            "SELECT symbol, headline FROM events WHERE kind = 'SETUP' "
            "AND source = 'CANSLIM' AND symbol IS NOT NULL "
            "ORDER BY at ASC").fetchall()
        conn.close()
    except sqlite3.Error:
        return {}
    for symbol, headline in rows:
        for tier in TIERS:
            if re.search(rf"CANSLIM\s+{tier}\b", str(headline or ""), re.I):
                out[str(symbol).upper()] = tier
                break
    return out


def with_rarity(rows):
    """Each row tagged with how many share its tier, and the day size.

    Done here rather than at the panel so the rarity travels with the
    reading. Four names out of ninety-two is the finding; the word
    EXCEPTIONAL on its own is not.
    """
    tally = counts(rows)
    total = len(rows)
    return [dict(r, rank=tally.get(r["tier"], 0), of=total) for r in rows]
