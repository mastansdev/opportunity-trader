"""
==========================================================
Who reports today, who reports tomorrow, and when in the day
==========================================================

    "what about watchlist = stocks reporting results during markets /
     after markets = todays + next day watchlist"
                                    -- operator, 2 August 2026

The bot already stores the split -- 462 REPORTED events carrying
DURING or AFTER for every company Earnings Pulse names. There was no
panel for them, so the question could only be answered by reading
chips off a ranked list of something else.

WHY THE SPLIT IS THE WHOLE POINT
--------------------------------
    DURING   it reports inside the session. The move happens while
             you are watching. Have it on screen.

    AFTER    it reports after 15:30. The market is shut when the
             numbers land, so nothing can be traded on them until the
             NEXT open -- which is the early-bird window:

                 "before the movement i need to trust as early bird
                  not in a over crowded place after rally done"

Mixing the two into one "reporting today" list -- which is what the
old panel did -- hides the only distinction that changes what you do
about it.

THE TENSE MATTERS AND IS EASY TO GET WRONG
------------------------------------------
Three cards carry the same split and mean different things:

    TODAY EARNINGS       REPORTS ...   has not reported yet
    TOMORROW'S CALENDAR  REPORTS ...   has not reported yet
    EARNINGS PULSE RECAP REPORTED ...  already out

A watchlist built from the RECAP would list companies whose numbers
are already public as though they were still ahead. So the forward
list is built only from headlines in the future tense, and the recap
is used for one thing: marking which of yesterday's after-close
reporters are still unpriced at this open.

Author : H&M Opportunity Trader
==========================================================
"""

import re
import sqlite3
from datetime import date, timedelta

from core.canslim import tier_rank
from core.chain import call_rank

EVENTS_DB = "data/stock_events.db"

DURING, AFTER = "DURING", "AFTER"
# The card named the company and printed no During / After columns.
# Ten of the nineteen forward cards Earnings Pulse has posted look like
# that -- see core/recap_card.py. A third bucket keeps them on screen
# without pretending to know the time of day.
UNKNOWN = "UNKNOWN"

# "REPORTS AFTER CLOSE (03 Aug) -- moves the next session"
# "REPORTS (02 Aug) -- the card did not say during or after the close"
# "REPORTED AFTER CLOSE (31 Jul) -- not yet priced by the market"
_FORWARD = re.compile(r"^REPORTS\b", re.I)
_BACKWARD = re.compile(r"^REPORTED\s+(AFTER CLOSE|DURING)", re.I)
_UNSTATED = re.compile(r"did not say during or after", re.I)
_WHEN = re.compile(r"\((\d{1,2}\s+[A-Za-z]{3})\)")

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}


def _stamp(headline, year):
    """The (dd Mon) on the chip, as a date, or None."""
    hit = _WHEN.search(str(headline or ""))
    if not hit:
        return None
    day, month = hit.group(1).split()
    try:
        return date(year, _MONTHS[month.lower()[:3]], int(day))
    except (KeyError, ValueError):
        return None


def _newest_first(iso):
    """A sort key that puts the LATEST date first inside an ascending
    sort. Negating a date is not possible, so the string is inverted
    character by character -- cheaper and clearer than splitting the
    sort in two passes."""
    return tuple(-ord(ch) for ch in str(iso or ""))


def _side(headline):
    text = str(headline or "")
    if _UNSTATED.search(text):
        return UNKNOWN
    return AFTER if "AFTER CLOSE" in text.upper() else DURING


def rows(events_db=EVENTS_DB, on=None):
    """Everything the store knows about who reports when.

    Returns {"forward": [...], "unpriced": [...]}.

    forward   companies that have NOT reported yet, with the day and
              the side of the close.
    unpriced  companies that reported after yesterday's close, so the
              market has not had a chance to answer them.
    """
    today = on or date.today()
    forward, unpriced = [], []
    try:
        conn = sqlite3.connect(events_db)
        found = conn.execute(
            "SELECT symbol, headline FROM events WHERE kind = 'REPORTED' "
            "AND symbol IS NOT NULL").fetchall()
        conn.close()
    except sqlite3.Error:
        return {"forward": [], "unpriced": []}

    seen_fwd, seen_unp = set(), set()
    for symbol, headline in found:
        when = _stamp(headline, today.year)
        side = _side(headline)
        if _FORWARD.match(headline or ""):
            key = (symbol, when, side)
            if key in seen_fwd:
                continue
            seen_fwd.add(key)
            forward.append({"symbol": symbol, "on": when, "side": side})
        elif _BACKWARD.match(headline or "") and side == AFTER:
            # Only the after-close half. A company that reported DURING
            # a past session has been fully traded and is not a
            # watchlist item.
            if (symbol, when) in seen_unp:
                continue
            seen_unp.add((symbol, when))
            unpriced.append({"symbol": symbol, "on": when})
    return {"forward": forward, "unpriced": unpriced}


def watchlist(events_db=EVENTS_DB, on=None, calls=None, tiers=None):
    """Today and tomorrow, each split during / after the close.

    `calls` is an optional {symbol: "BUY"|"WAIT"|"AVOID"} so a company
    that has already been read by the chain carries its call here too.
    A name with no call is not a gap -- most of these have not reported
    yet, so there is nothing to call.

    `tiers` is an optional {symbol: "EXCEPTIONAL"|"STRONG"|...} from the
    CANSLIM ratings list. 2 August 2026:

        "why divis, SHADOWFAX, AETHER, YASHO are not showing
         EXCEPTIONAL? in watchlist"

    Because the row carried the symbol and the call and nothing else.
    The four EXCEPTIONAL names were sitting in the store as SETUP
    events, reaching the gainers table as a collapsed why-chip and
    never reaching this panel at all -- the same build-without-render
    that has now happened to `support`, `chain` and the watchlist
    itself. The tier is the operator's own filter for what is worth
    watching, so it belongs on the watchlist above everything.
    """
    today = on or date.today()
    tomorrow = today + timedelta(days=1)
    calls = calls or {}
    tiers = tiers or {}
    found = rows(events_db=events_db, on=today)

    def entry(symbol):
        return {"symbol": symbol, "call": calls.get(symbol),
                "tier": tiers.get(symbol)}

    # ---- NOT ALPHABETICAL. 2 August 2026. ----
    #
    #     "no & never. some stocks had exceptional chip, strong chip,
    #      Mixed, weak ... but no refining of these ... NEVER TREAT
    #      WEAK = EXCEPTIONAL OR STRONG."
    #
    # Every bucket used to sort by symbol, which put AADHARHFC above
    # DIVISLAB whatever either of them was. Four names out of ninety
    # are EXCEPTIONAL; they were buried in a wall of sixty.
    #
    # TIER LEADS, on his instruction. The call settles ties inside a
    # tier, and AVOID sinks below an unread name -- see chain.CALL_ORDER
    # for why. The symbol is only the tiebreak of a tiebreak, so the
    # order is stable between refreshes.
    def order(row):
        return (tier_rank(row.get("tier")),
                call_rank(row.get("call")),
                row["symbol"])

    def bucket(day):
        out = {DURING: [], AFTER: [], UNKNOWN: []}
        for row in found["forward"]:
            if row["on"] != day:
                continue
            out[row["side"]].append(entry(row["symbol"]))
        for side in out:
            out[side].sort(key=order)
        return out

    # Reported after a PREVIOUS close and still unanswered at this
    # open. The reason the operator asked for the split in the first
    # place.
    # `on` is emitted as an ISO STRING, never a date object.
    #
    #     "A date object is not JSON. One un-encodable value here is a
    #      500 for the whole snapshot, not just this panel"
    #                        -- dashboard/state.py, learned the hard way
    # Same order here, and this is the list it matters on most: sixty
    # names, and the four that are EXCEPTIONAL were somewhere in the
    # middle of it. The date is now the THIRD key, not the first --
    # "reported most recently" is not the same as "worth looking at",
    # and it was being read as though it were.
    early = sorted(
        (dict(entry(r["symbol"]), on=r["on"].isoformat())
         for r in found["unpriced"] if r["on"] and r["on"] < today),
        key=lambda r: (tier_rank(r.get("tier")), call_rank(r.get("call")),
                       _newest_first(r["on"]), r["symbol"]))

    return {
        "today": today.isoformat(),
        "tomorrow": tomorrow.isoformat(),
        "reporting_today": bucket(today),
        "reporting_tomorrow": bucket(tomorrow),
        "unpriced_from_last_close": early[:60],
    }


def counts(view):
    """{today_during, today_after, tomorrow_during, tomorrow_after,
        unpriced} -- so a panel can say what it has without counting."""
    view = view or {}
    a = view.get("reporting_today") or {}
    b = view.get("reporting_tomorrow") or {}
    return {
        "today_during": len(a.get(DURING) or []),
        "today_after": len(a.get(AFTER) or []),
        "today_unstated": len(a.get(UNKNOWN) or []),
        "tomorrow_during": len(b.get(DURING) or []),
        "tomorrow_after": len(b.get(AFTER) or []),
        "tomorrow_unstated": len(b.get(UNKNOWN) or []),
        "unpriced": len(view.get("unpriced_from_last_close") or []),
    }
