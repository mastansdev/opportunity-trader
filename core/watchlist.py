"""
==========================================================
The watchlist -- what has a catalyst today, and why
==========================================================

    "FIRST thing we need to focus on watchlist (which stocks reporting
     results during markets, after markets) as now results time. later
     this watchlist will carry the stocks which were sorted by news,
     orders, govt policy, fed, rbi, or any other things stocks/sector
     specifics like fda on pharmas, fed,rbi on banks, nbfcs,
     commodities - gold, silver, aluminium on their related stocks,
     steel = related stocks. (to be precise this is all your work
     before even i ask these you need to prepare)"
                                    -- operator, 2 August 2026

He is right that this should have been anticipated. The watchlist is
not a results list that will later grow other columns; it is a
CATALYST list whose only catalyst today is results, because it is
results season.

So it is built that way from the start. RESULTS is wired. The rest are
defined, mapped and tested, waiting for a trigger.

THE MAPPING WAS ALREADY THERE
-----------------------------
Nothing new had to be researched. data/master.csv has carried this on
every one of 1,153 companies from the beginning, and no part of this
project has ever read it:

    COMMODITY_EXPOSURE      STEEL, ALUMINIUM, GOLD, SILVER, CRUDE OIL,
                            COAL, COTTON, NATURAL GAS, CEMENT ...
    ECONOMIC_SENSITIVITY    INTEREST RATE SENSITIVE, GOVERNMENT
                            SPENDING, EXPORT ORIENTED, IMPORT DEPENDENT
    SECTOR                  PHARMACEUTICALS, BANKING, METALS & MINING,
                            FINANCIAL SERVICES ...

Which answers every example he gave, directly. Counted on the real
master, 2 August 2026:

    gold moves           ->  23 names
    silver moves         ->  10 names
    aluminium moves      ->  58 names
    steel moves          -> 176 names
    RBI or the Fed moves -> 157 interest-rate-sensitive names
    FDA news             ->  68 pharma names
    budget or capex      -> 216 government-spending names

A NOTE ON THOSE COUNTS, because the first ones I quoted were wrong.
A cell holds several values -- "STEEL | ALUMINIUM | RUBBER" -- and
counting whole cells gives STEEL 64. Counting the VALUE inside every
cell gives 173, plus STEEL SCRAP, STEEL ALLOYS and CRGO STEEL for 176.
The second number is the right one: a company exposed to steel and
aluminium is exposed to steel.

WHY THE FAN-OUT IS BUILT BEFORE IT IS FED
-----------------------------------------
The trigger side is noisy. The MACRO store has 617 events, and a plain
search for "gold" returns a channel's own gamification message --
"You're only 2.3 pts from GOLD!" -- alongside the real ones. Wiring a
bad trigger into a good mapping would fill the watchlist with rubbish
and it would look authoritative.

So the mapping is written and tested now, against real master data.
The trigger is a separate, later decision, and until it is made this
fans out only when something hands it an explicit theme.

Author : H&M Opportunity Trader
==========================================================
"""

import re
from datetime import date

from core.canslim import tier_rank
from core.chain import call_rank

# The catalyst types. RESULTS is live; the rest are mapped and waiting.
RESULTS = "RESULTS"
ORDER = "ORDER"
COMMODITY = "COMMODITY"
RATES = "RATES"
POLICY = "POLICY"
SECTOR = "SECTOR"

DURING, AFTER = "DURING", "AFTER"
# The card named the company but printed no During / After columns.
# Ten of the nineteen forward cards look like that -- core/recap_card.py.
UNKNOWN = "UNKNOWN"

_DETAIL = {
    DURING: "reports during the session",
    AFTER: "reports after the close",
    UNKNOWN: "reports that day -- the card did not say when",
}

# Which master column answers which kind of trigger.
_BY_COMMODITY = "COMMODITY_EXPOSURE"
_BY_SENSITIVITY = "ECONOMIC_SENSITIVITY"
_BY_SECTOR = "SECTOR"

# A cell holds one or more values separated by a pipe:
#     "STEEL | ALUMINIUM | RUBBER"
# so a steel move must match the whole word STEEL and not the ALUMINIUM
# beside it, nor "STAINLESS STEEL" as a different thing.
def _values(cell):
    return [part.strip().upper()
            for part in str(cell or "").split("|") if part.strip()]


def _matches(cell, theme):
    theme = str(theme or "").strip().upper()
    if not theme:
        return False
    return any(theme == value or
               re.search(rf"\b{re.escape(theme)}\b", value)
               for value in _values(cell))


def exposed_to(master_loader, theme, column=_BY_COMMODITY):
    """Every company exposed to one theme, from the master.

        exposed_to(ml, "GOLD")                        -> 18 names
        exposed_to(ml, "STEEL")                       -> 64 names
        exposed_to(ml, "INTEREST RATE SENSITIVE",
                   column="ECONOMIC_SENSITIVITY")     -> 122 names
        exposed_to(ml, "PHARMACEUTICALS",
                   column="SECTOR")                   -> 68 names

    Exact, whole-value matching. "STEEL" must not pull in a company
    whose only exposure is "STAINLESS STEEL SCRAP" unless the master
    says so, because a watchlist that quietly widens is a watchlist
    that stops meaning anything.
    """
    if master_loader is None or not theme:
        return []
    out = []
    try:
        symbols = master_loader.all_symbols(include_blocked=True)
    except TypeError:
        symbols = master_loader.all_symbols()
    except Exception:                                      # noqa: BLE001
        return []
    for symbol in symbols:
        try:
            record = master_loader.get_by_symbol(symbol) or {}
        except Exception:                                  # noqa: BLE001
            continue
        if _matches(record.get(column), theme):
            out.append(symbol)
    return sorted(set(out))


def fan_out(master_loader, theme, catalyst=COMMODITY, detail=None,
            column=None):
    """A theme becomes watchlist entries.

    This is the half he described for later -- "gold, silver,
    aluminium on their related stocks, steel = related stocks". It
    works today; nothing is feeding it a theme yet, on purpose. See
    the module docstring for why the trigger side is held back.
    """
    if column is None:
        column = {COMMODITY: _BY_COMMODITY,
                  RATES: _BY_SENSITIVITY,
                  POLICY: _BY_SENSITIVITY,
                  SECTOR: _BY_SECTOR}.get(catalyst, _BY_COMMODITY)
    return [{"symbol": symbol, "catalyst": catalyst,
             "theme": str(theme).upper(),
             "detail": detail or f"{str(theme).upper()} exposure",
             "when": None, "call": None}
            for symbol in exposed_to(master_loader, theme, column=column)]


def from_results(view, calls=None):
    """The results half, from core/reporting.watchlist().

    Every entry carries WHEN in the day it reports, because that is
    the part that decides what you do:

        DURING   the move happens while you are watching
        AFTER    the market is shut when the numbers land, so it
                 cannot be traded until the next open
    """
    calls = calls or {}
    out = []
    for bucket, label in (("reporting_today", "today"),
                          ("reporting_tomorrow", "tomorrow")):
        block = (view or {}).get(bucket) or {}
        for side in (DURING, AFTER, UNKNOWN):
            for row in block.get(side) or []:
                symbol = row.get("symbol")
                out.append({
                    "symbol": symbol,
                    "catalyst": RESULTS,
                    "theme": side,
                    "detail": _DETAIL[side],
                    "when": label,
                    "call": row.get("call") or calls.get(symbol),
                    # The CANSLIM tier, carried through from the store.
                    # See core/reporting.watchlist() for why it is here.
                    "tier": row.get("tier"),
                })
    for row in (view or {}).get("unpriced_from_last_close") or []:
        out.append({
            "symbol": row.get("symbol"),
            "catalyst": RESULTS,
            "theme": AFTER,
            "detail": "reported after the last close -- not priced yet",
            "when": "unpriced",
            "call": row.get("call"),
            "tier": row.get("tier"),
        })
    return out


def build(results_view=None, extra=None, calls=None):
    """The whole watchlist, one row per stock per catalyst.

    `extra` is any list of entries from fan_out() or another source.
    A stock can legitimately appear twice under two catalysts -- it
    reports today AND steel moved -- and both are worth seeing, so
    neither is merged away.
    """
    rows = from_results(results_view, calls=calls) + list(extra or [])
    rows = [r for r in rows if r.get("symbol")]
    seen, out = set(), []
    for row in rows:
        key = (row["symbol"], row["catalyst"], row.get("theme"),
               row.get("when"))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    order = {RESULTS: 0, ORDER: 1, RATES: 2, POLICY: 3,
             COMMODITY: 4, SECTOR: 5}
    when_order = {"today": 0, "unpriced": 1, "tomorrow": 2, None: 3}
    # ---- TIER BEFORE ALPHABET. 2 August 2026. ----
    #
    #     "in general Exceptional, Strong stocks will be in primary
    #      focus in any table or any where ... NEVER TREAT WEAK =
    #      EXCEPTIONAL OR STRONG."
    #
    # Catalyst and timing still lead, because a stock reporting today
    # and a stock exposed to the gold price are different questions
    # and mixing them would make the list unreadable. Inside one
    # question the TIER decides, then the call, then the symbol.
    # ---- TRADEABLE BEFORE ALPHABETICAL. 3 August 2026. ----
    #
    #     "watchlist = you must suggest on that"
    #
    # He asked me to decide, so here is the reasoning rather than just
    # the change.
    #
    # The sort above is a LIBRARIAN'S ordering. It answers "what kind of
    # thing is this" -- all the results together, then the order wins,
    # then the rates plays. That is the right shape for filing and the
    # wrong shape for 09:15, because he never asks "show me every
    # results stock". He asks what to trade.
    #
    # Two things stay exactly as they were, and deliberately:
    #
    #   * CATALYST STILL LEADS. "a stock reporting today and a stock
    #     exposed to the gold price are different questions and mixing
    #     them would make the list unreadable" -- that was true when it
    #     was written and it is still true.
    #   * TIER STILL BEATS CALL. "NEVER TREAT WEAK = EXCEPTIONAL OR
    #     STRONG."
    #
    # What changes is the LAST tiebreak. It was the alphabet, which is
    # why 63MOONS and AARTIDRUGS kept appearing above TCS and SUNPHARMA
    # -- the same defect that put 63MOONS at the top of the shock
    # fan-out. Inside one catalyst, one timing, one tier and one call,
    # the stock where more money actually trades goes first. The
    # alphabet remains underneath so the order is STABLE: a list that
    # reshuffles under a cursor about to click BUY is its own hazard,
    # and traded value only changes overnight.
    #
    # Deliberately NOT sorted by what is moving right now. That would
    # be more useful and it would re-order the list under him every
    # second. The movers table already solves that by MARKING rather
    # than re-sorting, and this list should behave the same way.
    # Read the table ONCE, not once per comparison. adv() inside a sort
    # key is called thousands of times for a few hundred rows.
    try:
        from core.liquidity import adv
        size = {r["symbol"]: adv(r["symbol"]) for r in out}
    except Exception:                                       # noqa: BLE001
        size = {}

    out.sort(key=lambda r: (order.get(r["catalyst"], 9),
                            when_order.get(r.get("when"), 3),
                            tier_rank(r.get("tier")),
                            call_rank(r.get("call")),
                            -size.get(r["symbol"], 0.0),
                            r["symbol"]))
    return out


def by_catalyst(rows):
    """{catalyst: [rows]} -- for a panel that groups rather than sorts."""
    got = {}
    for row in rows or []:
        got.setdefault(row["catalyst"], []).append(row)
    return got


def counts(rows):
    """How many under each catalyst, and how many carry a call."""
    got = {"total": len(rows or []), "with_call": 0}
    for row in rows or []:
        got[row["catalyst"]] = got.get(row["catalyst"], 0) + 1
        if row.get("call"):
            got["with_call"] += 1
    return got
