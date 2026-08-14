"""
==========================================================
Market Situational Awareness
==========================================================

    "Market Situational Awareness is the ability to understand the
     complete market environment before making any trading decision &
     during open position. It combines global events, market sentiment,
     sector and industry strength, institutional activity, and price
     action to determine whether conditions favor deploying capital.
     The objective is not to find trades, but to trade only when the
     overall market context supports high-probability opportunities."
                                    -- operator, 3 August 2026

    "bot must inform the situation like a caution not block"

IT NEVER BLOCKS
---------------
This module has no gate, no veto and no power to grey out a button. It
returns a reading. He decides. That is the whole contract, and there is
a test that fails if anything in here starts returning something a
caller could use to refuse a trade.

WHY IT EXISTS
-------------
Every input below was already being fetched, stored and displayed. None
of it reached a decision. In dashboard/state.py:

    overall_score = round(breadth_pct)
    market_trend  = from breadth_pct
    regime        = from breadth_pct

Three separate labels on his screen -- Trend, Bias, Overall Score --
driven by ONE number, advances versus declines. The world markets, the
VIX, the fourteen sector indices and the FII/DII flows fed nothing at
all. This is the join that was missing.

TWO INPUTS ARE HONESTLY STALE
-----------------------------
    * core/premarket.py is fetched by the 08:45 job; main.py runs
      PreMarket(fetcher=None) and only reads the file. Until the
      collector refreshes it intraday, everything in the WORLD leg is
      as of the morning.
    * NSE publishes FII/DII once, after the close. During the session
      it is ALWAYS the previous day.

Both are reported as stale rather than counted as support. A stale
input that quietly votes is worse than no input.

WHERE THE DRIVERS CAME FROM
---------------------------
The operator named crude, gold, commodities, currencies, bond yields,
Fed, RBI, government decisions and the AI-driven IT sell-off, then
asked for research on what else moves this market. Checked 3 August
2026:

    * Global cues and FII flows are the primary drivers for the week;
      the US dollar index and US Treasury yields are the indicators
      that steer foreign flows into emerging markets.
    * The RBI MPC outcome is due 5 August 2026.
    * US-Iran, the Strait of Hormuz and crude are the live geopolitical
      risk to sentiment and inflation expectations.
    * Nifty IT is roughly 24% below its February 2026 peak, with TCS,
      Infosys, Wipro and LTIMindtree far off their highs, on fears that
      AI erodes billable outsourcing work -- a valuation reset rather
      than a collapse in profits.
    * Corrections in Korea and Taiwan may pull emerging-market weight
      back towards India, easing FII selling.

Scheduled events are NOT hardcoded here. A date in a source file goes
stale and then lies. Events are recognised from the news channels --
Day Trader Telugu for cause and effect, News Pulse for market-wide
items only, never for stock tagging.

Author : H&M Opportunity Trader
==========================================================
"""

from collections import namedtuple

from core.logger import diagnostic

# ---------------------------------------------------------------
# What counts as a real move
# ---------------------------------------------------------------
# Starting values, not laws. They are gathered here so core/outcomes.py
# can score them against what the tape actually did, the same way the
# two news readers are being scored after the MDR story.
CRUDE_MOVE_PCT = 2.0      # oil is noisy; under 2% is not a story
METAL_MOVE_PCT = 1.5      # gold, silver, copper
YIELD_MOVE_PCT = 2.0      # quoted as an index, so a 2% move is ~10bp
CURRENCY_MOVE_PCT = 0.35  # FX barely moves; 0.35% is a large day
EQUITY_MOVE_PCT = 0.75    # overnight US / Asia move worth reacting to

VIX_CALM = 14.0           # below this, fear is not the constraint
VIX_HOT = 20.0            # above this, position size is the constraint

BREADTH_GOOD = 60.0       # same threshold the engine's regime gate uses
BREADTH_WEAK = 40.0

SECTORS_BROAD = 0.60      # share of sectors green for a broad tape
FLOW_BIG_CR = 2000.0      # a genuinely large FII/DII day, in crore

Driver = namedtuple("Driver", "key label helps hurts why")

# ---------------------------------------------------------------
# Cause and effect, mapped to SECTORS -- never to hardcoded symbols
# ---------------------------------------------------------------
#
#     "pls make sure we will trade only NSE listed stocks"
#     "NEVER ASSUME ANYTHING. SEARCH RESOURCES, GET INFORMATION"
#
# The temptation was to write out symbol lists -- BPCL, HPCL, INDIGO,
# ASIANPAINT for a crude spike. Every one of those would be a symbol I
# typed from memory into a live trading system, which is exactly the
# mistake that put FINNIFTY in the config as "midcap".
#
# These map to the FOURTEEN SECTOR INDICES the bot actually subscribes
# to and prices live. The stock-level fan-out stays where it already
# works: the matcher and core/news_impact.py, against the verified
# master.
DRIVERS = (
    # ---- CORRECTED AGAINST THE REAL MASTER, 3 August 2026 ----
    #
    # crude first read helps=("Oil & Gas",). NIFTY Oil & Gas holds ONGC
    # and BPCL; crude up helps the first and hurts the second, so the
    # basket cancelled and the chain produced nothing for the one
    # driver the operator names most often. Split at industry level it
    # is sharp: OIL & GAS EXPLORATION up, OIL REFINING down.
    #
    # gold first read helps=("Consumer Durables",), which was simply
    # wrong. Checked in data/master_stocks.csv, TITAN, KALYANKJIL and
    # SENCO are CONSUMER DISCRETIONARY / "JEWELLERY / WATCHES RETAIL".
    # CONSUMER DURABLES is footwear, air conditioners and home
    # appliances. A gold headline was pointing at the wrong shops.
    Driver("crude", "Crude oil",
           helps=("Oil exploration",),
           hurts=("Oil refining", "Aviation", "Paints", "Tyres",
                  "Auto", "Infra"),
           why="Costlier crude lifts what a producer earns per barrel "
               "and raises the bill for everyone who burns or refines it"),
    Driver("gold", "Gold",
           helps=("Jewellery",),
           hurts=(),
           why="Higher gold lifts jewellery inventory value and gold "
               "loan cover, though it can cool buying volumes"),
    Driver("copper", "Copper",
           helps=("Metal",),
           hurts=("Auto", "Infra"),
           why="Copper is the global growth read-through and a direct "
               "input cost for everything that wires or builds"),
    Driver("natgas", "Natural gas",
           helps=(),
           hurts=("City gas", "Fertilisers"),
           why="Costlier gas is a direct input bill for city "
               "distributors and fertiliser plants"),
    Driver("dxy", "Dollar index",
           helps=(),
           hurts=("Realty", "PSU Bank", "Metal"),
           why="A strong dollar pulls foreign money out of emerging "
               "markets, and the rate-sensitive names go first"),
    Driver("usdinr", "USD / INR",
           helps=("IT", "Pharma", "Healthcare"),
           hurts=("Oil refining", "Aviation"),
           why="A weaker rupee pays exporters in stronger dollars and "
               "charges importers more for the same barrel"),
    Driver("us10y", "US 10Y yield",
           helps=(),
           hurts=("Realty", "IT", "Metal"),
           why="Rising long yields re-price every high-multiple stock "
               "and slow the flows that buy them"),
    Driver("us2y", "US 5Y yield",
           helps=(),
           hurts=("Realty", "PSU Bank", "Private Bank"),
           why="The front end is what the market thinks the Fed does "
               "next, and banks trade off it"),
    Driver("sp500", "S&P 500",
           helps=("IT",),
           hurts=(),
           why="US demand and US tech sentiment set the tone for "
               "Indian services exporters"),
    Driver("nasdaq", "Nasdaq",
           helps=("IT",),
           hurts=(),
           why="The AI trade lives here, and Nifty IT has been trading "
               "as its shadow all year"),
    Driver("hangseng", "Hang Seng",
           helps=(),
           hurts=(),
           why="Asian risk appetite, and a rival destination for the "
               "same emerging-market money"),
    Driver("nikkei", "Nikkei",
           helps=(),
           hurts=(),
           why="Asian risk appetite ahead of the Indian open"),
)

DRIVERS_BY_KEY = {d.key: d for d in DRIVERS}

# ---------------------------------------------------------------
# Event words -- read off the news channels, not off a calendar
# ---------------------------------------------------------------
#
#     "bot needed live news, events which will get sourced from our
#      news channels - Day trader & News Pulse"
#
# A hardcoded "RBI MPC on 5 August 2026" is correct for two days and
# wrong afterwards, forever. These are the words that mark a headline
# as market-wide rather than about one company.
EVENT_WORDS = {
    "policy": ("rbi", "mpc", "repo rate", "monetary policy", "fed",
               "fomc", "federal reserve", "rate cut", "rate hike",
               "crr", "liquidity"),
    "government": ("budget", "gst", "import duty", "export duty",
                   "tariff", "cess", "subsidy", "scheme", "sebi",
                   "ban", "cap on", "mdr", "psu", "divestment"),
    "geopolitics": ("war", "strait of hormuz", "iran", "sanction",
                    "conflict", "attack", "ceasefire", "border"),
    "disruption": ("ai", "artificial intelligence", "openai",
                   "automation", "disrupt"),
    "flows": ("fii", "dii", "foreign institutional", "msci",
              "index rebalance", "emerging market"),
}


def _pct(row):
    value = row.get("change_pct") if isinstance(row, dict) else None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_event(headline):
    """Which kind of market-wide event a headline is, or None.

    Deliberately returns None for anything that is only about one
    company. Those already have a home in core/news_impact.py and the
    cause-and-effect panel; duplicating them here would put the same
    story on his screen twice with two different words on it.
    """
    text = str(headline or "").lower()
    if not text.strip():
        return None
    for kind, words in EVENT_WORDS.items():
        for word in words:
            if word in text:
                return kind
    return None


def read_world(premarket):
    """Global markets, rates, currencies and commodities.

    Returns (verdict, one plain line, details). Never raises.
    """
    if premarket is None:
        return "unknown", "world markets not wired", []
    try:
        snap = premarket.snapshot() or {}
    except Exception as exc:                                # noqa: BLE001
        diagnostic(f"[AWARE] premarket unreadable: {exc}")
        return "unknown", "world markets unreadable", []

    if not snap.get("available"):
        return "unknown", "no world data yet today", []

    # ---- A FEED THAT STOPPED IS NOT A FEED THAT IS QUIET ----
    #      3 August 2026.
    #
    # Checked against his real data/premarket.json this evening: all
    # eighteen sources were in "failed" and every stored quote was
    # flagged stale. The numbers still in the file -- crude 80.22,
    # Nasdaq 25,373 -- are from an older successful run, and without
    # this branch they would have been read out as today's overnight
    # picture. That is the same class of mistake as drawing invented
    # prices in a panel and calling them real.
    failed = snap.get("failed") or []
    rows_total = sum(len(v) for v in (snap.get("groups") or {}).values())
    if rows_total and len(failed) >= rows_total:
        return ("unknown",
                f"world data is not updating — all {len(failed)} sources "
                f"failed on the last fetch", [])

    moves, stale = [], False
    for rows in (snap.get("groups") or {}).values():
        for row in rows:
            driver = DRIVERS_BY_KEY.get(row.get("key"))
            if driver is None:
                continue
            if row.get("stale"):
                stale = True
            pct = _pct(row)
            if pct is None:
                continue
            limit = _limit_for(row.get("key"))
            if abs(pct) >= limit:
                moves.append({"key": driver.key, "label": driver.label,
                              "change_pct": round(pct, 2),
                              "why": driver.why,
                              "helps": list(driver.helps),
                              "hurts": list(driver.hurts)})

    moves.sort(key=lambda m: -abs(m["change_pct"]))
    if stale:
        return "stale", _world_line(moves) + " (as of the morning fetch)", moves
    if not moves:
        return "supports", "nothing big moved overnight", moves
    # A day where several global inputs are all moving hard is a day to
    # be careful in, whichever way they point.
    verdict = "careful" if len(moves) >= 3 else "supports"
    return verdict, _world_line(moves), moves


def _limit_for(key):
    if key in ("crude", "natgas"):
        return CRUDE_MOVE_PCT
    if key in ("gold", "silver", "copper"):
        return METAL_MOVE_PCT
    if key in ("us10y", "us2y"):
        return YIELD_MOVE_PCT
    if key in ("dxy", "usdinr", "eurusd", "usdjpy"):
        return CURRENCY_MOVE_PCT
    return EQUITY_MOVE_PCT


def _world_line(moves):
    if not moves:
        return "nothing big moved overnight"
    parts = []
    for move in moves[:3]:
        way = "up" if move["change_pct"] > 0 else "down"
        parts.append(f"{move['label']} {way} "
                     f"{abs(move['change_pct']):.1f}%")
    return ", ".join(parts)


def read_sentiment(indices, breadth_pct):
    """VIX plus breadth. How much fear, and how wide the move is."""
    vix = (indices or {}).get("vix") or {}
    level = vix.get("ltp") if vix.get("available") else None

    if level is None and breadth_pct is None:
        return "unknown", "no sentiment reading yet", {}

    detail = {"vix": level, "breadth_pct": breadth_pct}
    if level is None:
        return ("supports" if (breadth_pct or 0) >= BREADTH_GOOD
                else "careful"), f"{breadth_pct:.0f}% of stocks up", detail

    if level >= VIX_HOT:
        return "against", f"VIX {level:.2f} — moves will be violent", detail
    if level <= VIX_CALM:
        return "supports", f"VIX {level:.2f}, fear is low", detail
    return "careful", f"VIX {level:.2f}, middling", detail


def read_sectors(sector_rows):
    """How many of the fourteen sector indices are green, and which."""
    rows = [r for r in (sector_rows or []) if r.get("pct") is not None]
    if not rows:
        return "unknown", "sector indices not delivering", {}

    up = [r for r in rows if r["pct"] > 0]
    share = len(up) / len(rows)
    leaders = sorted(rows, key=lambda r: -r["pct"])[:2]
    names = " and ".join(r.get("name", "?") for r in leaders)
    detail = {"green": len(up), "total": len(rows),
              "leaders": [r.get("name") for r in leaders]}

    if share >= SECTORS_BROAD:
        return "supports", f"{len(up)} of {len(rows)} sectors up, " \
                           f"{names} leading", detail
    if share <= (1 - SECTORS_BROAD):
        return "against", f"only {len(up)} of {len(rows)} sectors up", detail
    return "careful", f"{len(up)} of {len(rows)} sectors up, split tape", detail


def read_flows(market_flows):
    """FII and DII. Always the previous session -- said so, every time."""
    if market_flows is None:
        return "unknown", "institutional flows not wired", {}
    try:
        snap = market_flows.snapshot() or {}
    except Exception as exc:                                # noqa: BLE001
        diagnostic(f"[AWARE] flows unreadable: {exc}")
        return "unknown", "institutional flows unreadable", {}
    if not snap.get("available"):
        return "unknown", "no flow figure yet", {}

    fii = snap.get("fii_cr")
    detail = {"fii_cr": fii, "dii_cr": snap.get("dii_cr"),
              "as_of": snap.get("as_of")}
    if fii is None:
        return "stale", "DII only, no FII figure — previous session", detail

    way = "bought" if fii > 0 else "sold"
    size = " heavily" if abs(fii) >= FLOW_BIG_CR else ""
    # NSE publishes after the close. This is never live, so it is never
    # allowed to vote as support.
    return "stale", (f"FII {way}{size} {abs(fii):,.0f} Cr "
                     f"— previous session"), detail


def read_price_action(indices):
    """What the index is doing right now. The only leg that cannot be
    stale, because it comes off the live tick feed."""
    nifty = (indices or {}).get("nifty") or {}
    if not nifty.get("available") or nifty.get("pct") is None:
        return "unknown", "no live index feed", {}

    pct = float(nifty["pct"])
    detail = {"nifty_pct": pct, "nifty_ltp": nifty.get("ltp")}
    if pct >= 0.25:
        return "supports", f"NIFTY up {pct:.2f}%, holding", detail
    if pct <= -0.25:
        return "against", f"NIFTY down {abs(pct):.2f}%", detail
    return "careful", f"NIFTY flat at {pct:+.2f}%", detail


LEG_ORDER = ("world", "sentiment", "sectors", "flows", "price")
LEG_LABEL = {"world": "World markets", "sentiment": "Sentiment",
             "sectors": "Sectors", "flows": "Big money",
             "price": "Price action"}


def assess(premarket=None, indices=None, sector_rows=None,
           market_flows=None, breadth_pct=None, events=None):
    """The one reading. Informs; never blocks.

    Returns a dict the dashboard can draw without interpreting anything:
    a plain verdict, a one-line reason, and the five legs behind it.
    """
    legs = {}
    legs["world"] = read_world(premarket)
    legs["sentiment"] = read_sentiment(indices, breadth_pct)
    legs["sectors"] = read_sectors(sector_rows)
    legs["flows"] = read_flows(market_flows)
    legs["price"] = read_price_action(indices)

    rows = []
    for key in LEG_ORDER:
        verdict, line, detail = legs[key]
        rows.append({"key": key, "label": LEG_LABEL[key],
                     "verdict": verdict, "line": line, "detail": detail})

    supports = sum(1 for r in rows if r["verdict"] == "supports")
    against = sum(1 for r in rows if r["verdict"] == "against")

    # Live market-wide events are a caution in their own right. A rate
    # decision or a duty change mid-session moves everything at once,
    # and being long into one by accident is not a strategy.
    live_events = [e for e in (events or []) if classify_event(e.get("headline"))]
    for event in live_events[:3]:
        rows.append({"key": "event", "label": "Happening now",
                     "verdict": "careful",
                     "line": str(event.get("headline") or "")[:140],
                     "detail": {"kind": classify_event(event.get("headline")),
                                "source": event.get("source")}})

    if against >= 2 or (against >= 1 and supports <= 1):
        verdict, headline = "Stay out", "The tape is against you"
    elif supports >= 3 and not against:
        verdict, headline = "Good to trade", "Conditions are behind you"
    else:
        verdict, headline = "Be careful", "Mixed — size down"

    if live_events and verdict == "Good to trade":
        verdict, headline = "Be careful", "Something is happening right now"

    return {
        "verdict": verdict,
        "headline": headline,
        "rows": rows,
        "supports": supports,
        "against": against,
        # There is no "blocked" key and there never will be. See
        # tests/test_awareness.py.
        "informs_only": True,
    }
