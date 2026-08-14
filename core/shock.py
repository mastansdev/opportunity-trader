"""
==========================================================
Something big just happened
==========================================================

    "if any major thing happened & how the bot knows? how it will alert
     the trader to look into the matter for necessary action. ex
     scenario - war news will move all stocks fall. & cease fire
     agreement done all stocks were positive . in this situation also
     some stocks get more benifits & some stocks will fall. remember
     crude raise & fall concept?"
                                    -- operator, 3 August 2026

He is right that nothing here did this. A war headline arrived as one
row in a list of eleven, in the same typeface as an order win, and the
tape moving 800 stocks in four minutes produced no reaction at all.

TWO SIGNALS, BECAUSE EITHER ALONE IS WRONG
------------------------------------------
    THE WORDS   geopolitics / policy / government wording off Day
                Trader Telugu and News Pulse. Fast, and often first --
                but News Pulse posts commentary under the same heading
                all day, so words alone would shout constantly.

    THE TAPE    how many stocks moved, how far, in how few minutes.
                Needs no trust in any reader: 800 stocks falling in
                four minutes is a fact. But it is late, and it cannot
                tell a shock from an index rebalance on its own.

TWO TIERS, BECAUSE WAITING FOR BOTH THROWS AWAY THE EDGE
--------------------------------------------------------
On 3 August the bot had the MDR story with five affected stocks and a
written mechanism for each FOURTEEN MINUTES before News Pulse carried
it. An alert that waited for the tape to confirm would have discarded
that head start, every single time.

    HEADS UP    the words alone. Quiet, one line, no siren.
    ALERT       the words and the tape together. Banner, sound,
                positions first.

THE CRUDE CHAIN IS TWO HOPS, NOT ONE
------------------------------------
War is not a driver. War moves CRUDE, GOLD and the DOLLAR, and those
move sectors -- which is exactly the concept he asked me to remember:

    ceasefire -> crude falls, gold falls -> airlines, paints and tyres
                 up; upstream oil and jewellers down

Everything rallies on a ceasefire. The bot's job is to say which ones
rally hardest and which two do not. The second hop already exists in
core/awareness.py's DRIVERS table, mapped to the fourteen sector
indices the bot actually prices. This module adds the first hop.

IT NEVER BLOCKS AND IT NEVER TRADES
-----------------------------------
    "bot must inform the situation like a caution not block"

It returns a reading with buttons on it. Nothing here can refuse an
order, cancel one, or place one.

Author : H&M Opportunity Trader
==========================================================
"""

from core.awareness import DRIVERS_BY_KEY
from core.logger import diagnostic
from core.sector_map import spread

# ---------------------------------------------------------------
# What counts as "the whole market is moving"
# ---------------------------------------------------------------
# Chosen with the operator, 3 August 2026: breadth has to flip hard AND
# fast, and the index has to agree. Either alone is a false alarm --
# one sector rotating can move hundreds of stocks without it being a
# shock, and a handful of heavyweights can drag NIFTY without the
# market going anywhere.
SHOCK_STOCKS = 500          # stocks moving the same way
SHOCK_WINDOW_MINUTES = 5    # inside this many minutes
SHOCK_INDEX_PCT = 0.5       # and NIFTY itself moving at least this much
SHOCK_STOCK_PCT = 0.5       # what counts as a stock "moving" at all

# How long an alert stays up once it fires. Long enough to act on,
# short enough that it is not still shouting about a 10:00 event at
# 14:00.
ALERT_MINUTES = 20

# ---------------------------------------------------------------
# First hop: the event pushes these drivers, this way
# ---------------------------------------------------------------
#
# +1 means the event pushes that driver UP. The second hop -- driver to
# sector -- is core/awareness.py's DRIVERS table, so nothing is
# duplicated and a correction there flows through to here.
#
# These are the relationships the operator named, and the ones the
# 3 August research supports: US-Iran and the Strait of Hormuz as the
# live risk to crude and therefore to inflation expectations.
EVENT_DRIVERS = {
    "war": {"crude": +1, "gold": +1, "dxy": +1, "usdinr": +1},
    "ceasefire": {"crude": -1, "gold": -1, "dxy": -1, "usdinr": -1},
    "rate_cut": {"us10y": -1, "us2y": -1, "dxy": -1},
    "rate_hike": {"us10y": +1, "us2y": +1, "dxy": +1},
    "ai_disruption": {"nasdaq": -1},
}

# The wording that picks one of the above. Checked in order, and the
# peace words are checked FIRST -- "ceasefire in the war" must not read
# as a war headline, and it would if "war" were tested first.
EVENT_WORDS = (
    ("ceasefire", ("ceasefire", "cease fire", "truce", "peace deal",
                   "peace agreement", "de-escalat", "deescalat",
                   "withdraw troops", "talks agreed")),
    ("war", ("war", "strike", "missile", "attack", "invasion",
             "strait of hormuz", "sanction", "escalat", "conflict",
             "airspace closed", "blockade")),
    ("rate_cut", ("rate cut", "cuts rate", "cuts repo", "lowers rate",
                  "dovish", "eases policy")),
    ("rate_hike", ("rate hike", "hikes rate", "raises rate",
                   "hikes repo", "hawkish", "tightens policy")),
    ("ai_disruption", ("ai", "artificial intelligence", "openai",
                       "automation")),
)


def event_kind(headline):
    """Which shock, if any, a headline describes.

    Distinct from core.awareness.classify_event(), which answers the
    broader question "is this market-wide at all". This one answers
    "does this push crude, gold or rates, and which way".
    """
    text = str(headline or "").lower()
    if not text.strip():
        return None
    for kind, words in EVENT_WORDS:
        for word in words:
            if word in text:
                return kind
    return None


def sectors_for(kind):
    """Event -> {sector: +1 or -1}, walked through the drivers.

    A sector pushed both ways by the same event nets out, and a sector
    that nets to zero is DROPPED rather than shown as neutral. On a war
    headline crude hurts Auto while a weaker rupee helps nothing there,
    so Auto stays; where two drivers genuinely cancel, the bot has no
    view and says nothing.
    """
    pushes = EVENT_DRIVERS.get(kind)
    if not pushes:
        return {}

    score = {}
    for key, way in pushes.items():
        driver = DRIVERS_BY_KEY.get(key)
        if driver is None:
            diagnostic(f"[SHOCK] no driver mapped for '{key}'")
            continue
        for sector in driver.helps:
            score[sector] = score.get(sector, 0) + way
        for sector in driver.hurts:
            score[sector] = score.get(sector, 0) - way
    return {s: (1 if v > 0 else -1) for s, v in score.items() if v}


def why_for(kind, sector):
    """One plain sentence, built from the drivers that reached it."""
    pushes = EVENT_DRIVERS.get(kind) or {}
    reasons = []
    for key, way in pushes.items():
        driver = DRIVERS_BY_KEY.get(key)
        if driver is None:
            continue
        if sector in driver.helps or sector in driver.hurts:
            moved = "up" if way > 0 else "down"
            reasons.append(f"{driver.label.lower()} {moved}")
    if not reasons:
        return ""
    return ", ".join(sorted(set(reasons)))


def tape_moved(movers, index_pct, window_minutes=SHOCK_WINDOW_MINUTES):
    """Is the WHOLE market moving right now?

    `movers` are rows carrying recent_pct -- the move over the last few
    minutes, not the day change. Day change would call a stock that
    gapped at 09:15 and has not ticked since a mover, which is the flaw
    that put stalled gainers at the top of his screen all morning.
    """
    rows = [r for r in (movers or []) if r.get("recent_pct") is not None]
    if not rows:
        return None

    up = [r for r in rows if r["recent_pct"] >= SHOCK_STOCK_PCT]
    down = [r for r in rows if r["recent_pct"] <= -SHOCK_STOCK_PCT]
    side, crowd = ("down", down) if len(down) > len(up) else ("up", up)

    if len(crowd) < SHOCK_STOCKS:
        return None
    if index_pct is None or abs(index_pct) < SHOCK_INDEX_PCT:
        return None
    # The index has to agree with the crowd, or this is a rotation.
    if (index_pct > 0) != (side == "up"):
        return None

    return {"side": side, "count": len(crowd), "index_pct": index_pct,
            "window_minutes": window_minutes}


def _fmt(kind, side):
    if kind == "ceasefire":
        return "A ceasefire has been reported"
    if kind == "war":
        return "Conflict news is hitting the market"
    if kind == "rate_cut":
        return "A rate cut has been announced"
    if kind == "rate_hike":
        return "A rate rise has been announced"
    if kind == "ai_disruption":
        return "AI disruption news is hitting IT"
    return "The whole market is moving " + (side or "")


def assess(headlines=None, movers=None, index_pct=None, positions=None,
           sector_rows=None):
    """The alert, or None when nothing is happening.

    Returns a dict the banner can draw without interpreting anything:
    what happened, what it does to his open positions, and two lists of
    stocks with a direction each.
    """
    headlines = headlines or []
    hit, kind = None, None
    for item in headlines:
        line = item.get("headline") if isinstance(item, dict) else item
        found = event_kind(line)
        if found:
            hit, kind = item if isinstance(item, dict) else {"headline": line}, found
            break

    tape = tape_moved(movers, index_pct)

    # Nothing in the words and nothing in the tape: say nothing. A
    # screen that finds a crisis every day finds none on the day there
    # is one.
    if hit is None and tape is None:
        return None

    # Words alone -> a quiet heads up, so the head start survives.
    # Words and tape together, or the tape alone -> the full alert.
    tier = "alert" if tape is not None else "heads_up"

    side = tape["side"] if tape else None
    pushes = sectors_for(kind) if kind else {}

    # ---- THE LAST HOP. 3 August 2026. ----
    #
    # Membership comes from core/sector_map.py, which reads the
    # verified master -- not from whichever movers happen to carry a
    # sector label, and never from a symbol list typed from memory.
    #
    # Reading only the movers feed meant a sector with no stock in
    # today's top movers produced nothing, so in the first seconds of
    # an event -- the seconds that matter -- the alert was empty.
    up_rows, down_rows = spread(pushes, movers=movers, per_sector=3)
    for row in up_rows + down_rows:
        row["why"] = why_for(kind, row["sector"])

    held = []
    for position in (positions or []):
        held.append({"symbol": position.get("symbol"),
                     "qty": position.get("qty"),
                     "change_pct": position.get("change_pct"),
                     "pnl": position.get("pnl")})

    line = _fmt(kind, side)
    detail = ""
    if tape:
        detail = (f"{tape['count']} stocks moved {tape['side']} in the last "
                  f"{tape['window_minutes']} minutes")

    return {
        "tier": tier,
        "kind": kind,
        "headline": line,
        "quote": str((hit or {}).get("headline") or "")[:180],
        "source": (hit or {}).get("source"),
        "detail": detail,
        "positions": held,
        "up": up_rows,
        "down": down_rows,
        # Same contract as core/awareness.py. Nothing here is permission.
        "informs_only": True,
    }
