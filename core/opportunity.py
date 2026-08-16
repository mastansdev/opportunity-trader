"""
==========================================================
What KIND of opportunity is this -- and what happened last time
==========================================================

    "bot itself act as an opportunity bot. in the world of stock market
     the opportunity arises in the form of many ways = company news,
     government schemes, multi year order wins, acquisitions, FDA
     approvals, mine ore approvals, commoditiy cycles, sector rotations,
     tarrif threats, wars, worldwide outrages, middle east tensions & to
     name some 100's of opportunites."
                                -- operator, 16 August 2026

    "i want you to develop a brain memory module in to bot with self
     evaluating & learning to find the opportunity on based of the
     memory."

WHAT WAS ACTUALLY MISSING
-------------------------
Not the data. On 16 August data/stock_events.db held 13,996 events and
a word-boundary scan found 959 of exactly the kinds he lists:

    war / geopolitics      196     acquisition / M&A     175
    capacity / expansion   166     govt scheme / PLI     138
    order win              115     commodity cycle        75
    tariff / duty           38     mining / ore           29
    FDA approval            27

Every one of them was already stored. Not one could be NAMED. They sit
under core/stock_events.py's generic kinds -- NEWS, MACRO, RESULT,
CONCALL -- because classify() is a priority cascade with exactly one
opportunity type in it, ORDER, and everything else falls through to
"NEWS if we know the symbol, MACRO otherwise".

So the bot could answer "did something happen to KAYNES" and could not
answer "what happens when an FDA approval lands", because the second
question needs a WORD FOR THE THING, and there wasn't one.

That is the whole gap this module fills. It is a second, ORTHOGONAL
dimension: an event keeps its kind and gains a type. A story can be
kind=NEWS and type=FDA_APPROVAL at the same time, so nothing about the
existing cascade has to move.

WHAT THIS DOES NOT DO -- READ THIS BEFORE WIRING IT ANYWHERE
------------------------------------------------------------
It does not vote. Same posture as core/trade_memory.py, core/
outcomes.py and dashboard/chip_stats.py, and for the same reason:

    "nothing from the guides becomes a rule until scored against real
     outcomes"

and his standing instruction:

    "Entry, exit, target and trail are DEFINED RULES. Your job is to
     make the bot follow them exactly -- not to discover new ones from
     history."

There is no tension between that and a learning brain, as long as the
line is drawn in the right place:

    RECOGNITION and RECALL   <- this module learns these
    ENTRY, STOP, SIZE, EXIT  <- core/position_plan.py, core/exit_plan.py

Naming an opportunity is not choosing a threshold. Remembering that
tariff news has moved this sector nine times is not a trading rule.
The moment a number out of here decides a trade, that is a different
change and it needs saying out loud.

A TYPE IS NOT A REASON
----------------------
core/ranker.py refuses keyword-matched reasons by name -- "reason is a
lookup, not a mechanism" -- and it is right. classify() below matches
words. So every match carries the PHRASE it matched on, and callers
must treat a type as a LABEL FOR RECALL, never as the evidence that
justifies a trade. core/rules.is_a_reason() still governs that.

HORIZON IS THE UNCOMFORTABLE PART
---------------------------------
He listed commodity cycles and sector rotations beside FDA approvals.
Those are not the same animal. An approval moves a stock in minutes; a
commodity cycle plays out over quarters, and this bot squares off at
15:15. Each type therefore declares a HORIZON, and the memory below
reports the same-session move separately -- so the answer to "can this
bot actually trade this type" is measured rather than assumed.

Author : H&M Opportunity Trader
==========================================================
"""

import re
import sqlite3
from datetime import datetime, timedelta

EVENTS_DB = "data/stock_events.db"
CANDLES_DB = "data/daily_candles.db"

# ---- HORIZONS ----------------------------------------------------
# Whether a 09:15-15:15 bot can act on it AT ALL. Not a judgement on
# the opportunity, a statement about this bot's holding period.
SESSION = "SESSION"        # moves the same day -- tradeable here
DAYS = "DAYS"              # plays out over days -- partly reachable
QUARTERS = "QUARTERS"      # a theme, not a trade for an intraday bot

# ---- FAMILIES ----------------------------------------------------
COMPANY = "COMPANY"
REGULATORY = "REGULATORY"
SECTOR = "SECTOR"
MACRO = "MACRO"
GEOPOLITICAL = "GEOPOLITICAL"

# ---- SIDE --------------------------------------------------------
# LONG ONLY is not negotiable ("only long positions"), so a headwind
# is never a trade. It is recorded because it EXPLAINS a fall the bot
# would otherwise treat as an unexplained move, and because the same
# tariff that hurts an importer helps a domestic producer.
TAILWIND = "TAILWIND"
HEADWIND = "HEADWIND"
EITHER = "EITHER"


def _rx(*alts):
    return re.compile("|".join(alts), re.I)


# ==================================================================
# THE TAXONOMY
# ==================================================================
# Deliberately NOT "100s of types". He named about a dozen families
# and said "to name some 100's" -- meaning the world is open-ended,
# not that he wants a list of 100 hand-written regexes that nobody can
# maintain and that would each fire twice a year.
#
# These are the families that (a) he named, and (b) actually occur in
# the 13,996 events already stored. Counts below are from that scan.
# A family with no matches in the store would be a guess, and this
# file does not guess -- add one when the data shows it arriving.
TYPES = (
    dict(key="ORDER_WIN", family=COMPANY, horizon=SESSION, side=TAILWIND,
         label="Order win / contract award",
         patterns=_rx(r"\border win", r"\bbags? (?:an? )?(?:order|contract)",
                      r"\breceive[ds]\b.{0,15}\b(?:order|contract)",
                      r"letter of award", r"\bLoA\b",
                      r"\bwins?\b.{0,18}\b(?:order|contract|tender)",
                      r"\bemerges? .{0,10}lowest bidder", r"\bL1 bidder"),
         note="Already has its own kind (ORDER). Typed here too so the "
              "memory can compare it against every other family."),

    dict(key="ORDER_BOOK_MULTIYEAR", family=COMPANY, horizon=DAYS,
         side=TAILWIND, label="Multi-year order book / execution runway",
         patterns=_rx(r"order book.{0,25}\b(?:cr|crore|bn)",
                      r"\b(?:executable|execution) (?:over|in)\b.{0,20}"
                      r"\b(?:year|month)", r"\bmulti[- ]year\b.{0,20}order",
                      r"\bbook to bill"),
         note="He named this separately from a single order win, and it "
              "is a different signal: the runway, not the day's award."),

    dict(key="FDA_APPROVAL", family=REGULATORY, horizon=SESSION,
         side=TAILWIND, label="Drug / device approval",
         patterns=_rx(r"\b(?:usfda|us fda|fda)\b", r"\bANDA\b", r"\bNDA\b",
                      r"drug approval", r"\bCEP\b", r"\bEIR\b",
                      r"establishment inspection report",
                      r"\bapproval\b.{0,20}\b(?:drug|molecule|injection|tablet)"),
         note="Also fires on FDA OBSERVATIONS, which are the opposite. "
              "direction_hint() separates them -- see below."),

    dict(key="REGULATORY_CLEARANCE", family=REGULATORY, horizon=DAYS,
         side=TAILWIND, label="Approval / clearance / licence",
         patterns=_rx(r"environment(?:al)? clearance", r"\bCCI approval",
                      r"\bNCLT\b.{0,20}approv", r"mining lease",
                      r"\bcoal block\b", r"\bore\b.{0,20}(?:approval|lease)",
                      r"\blicence\b|\blicense\b.{0,20}grant"),
         note="Mine/ore approvals he named live here."),

    dict(key="ACQUISITION", family=COMPANY, horizon=SESSION, side=EITHER,
         label="Acquisition / merger / stake change",
         patterns=_rx(r"\bacquisitions?\b", r"\bacquires?\b|\bacquired\b",
                      r"\bmerger\b", r"\btakeover\b", r"\bamalgamation\b",
                      r"\bstake (?:buy|sale|purchase|acquisition)",
                      r"\bopen offer\b", r"\bdivest"),
         note="EITHER on purpose: being acquired lifts the target and "
              "an expensive acquisition can sink the acquirer."),

    dict(key="CAPACITY_EXPANSION", family=COMPANY, horizon=DAYS,
         side=TAILWIND, label="Capacity / plant / expansion",
         patterns=_rx(r"capacity expansion", r"\bnew plant\b",
                      r"\bgreenfield\b", r"\bbrownfield\b",
                      r"\bcommission(?:ed|ing)\b", r"\bdebottleneck",
                      r"capex.{0,20}\b(?:cr|crore)"),
         note=""),

    dict(key="GOVT_SCHEME", family=SECTOR, horizon=DAYS, side=TAILWIND,
         label="Government scheme / PLI / subsidy",
         patterns=_rx(r"\bPLI\b", r"production[- ]linked", r"\bsubsid",
                      r"incentive scheme", r"\bbudget allocation",
                      r"\bgovernment (?:scheme|push|order|approval)",
                      r"\bcabinet approv"),
         note="Sector-wide. Which stocks it reaches is core/"
              "news_impact.py's job, not this module's."),

    dict(key="TARIFF_DUTY", family=MACRO, horizon=DAYS, side=EITHER,
         label="Tariff / duty / anti-dumping",
         patterns=_rx(r"\btariffs?\b", r"anti[- ]dumping",
                      r"\b(?:import|export) dut", r"duty (?:hike|cut|imposed)",
                      r"\bsafeguard duty", r"\bcustoms dut"),
         note="EITHER. A duty on imports is a headwind for the importer "
              "and a tailwind for the domestic producer -- the same "
              "sentence, opposite signs, which is exactly why direction "
              "must never be inferred from the type alone."),

    dict(key="GEOPOLITICS", family=GEOPOLITICAL, horizon=DAYS, side=EITHER,
         label="War / conflict / geopolitical shock",
         patterns=_rx(r"\bwar\b", r"\bisrael\b", r"\biran\b", r"\bukraine\b",
                      r"\brussia", r"middle east", r"\bred sea\b",
                      r"\bgeopolit", r"\bstrait of hormuz", r"\bsanction"),
         note="Reaches this bot as freight, crude and defence. Almost "
              "never a same-session single-stock trade."),

    dict(key="COMMODITY_CYCLE", family=MACRO, horizon=QUARTERS, side=EITHER,
         label="Commodity price / cycle",
         patterns=_rx(r"\bcrude\b", r"\bbrent\b", r"steel price",
                      r"cement price", r"commodity price", r"\brealisation",
                      r"\bspread\b.{0,15}\bexpand", r"\bmargin tailwind"),
         note="QUARTERS. Recorded so a move has an explanation, not "
              "because a position measured in days can trade a cycle "
              "that turns over quarters."),

    dict(key="SECTOR_ROTATION", family=SECTOR, horizon=QUARTERS, side=EITHER,
         label="Sector rotation / flows",
         patterns=_rx(r"sector rotation", r"\brotat(?:ing|ion)\b.{0,20}"
                      r"\b(?:into|out of)", r"\bFII\b.{0,20}\b(?:buy|sell)",
                      r"\bDII\b.{0,20}\b(?:buy|sell)",
                      r"\boutperform(?:ing|ance)\b.{0,20}\bsector"),
         note="core/sector_map.py already measures today's leadership "
              "from prices, which is a better answer than a headline."),

    dict(key="BUSINESS_UPDATE", family=COMPANY, horizon=SESSION,
         side=EITHER, label="Business update / operational filing",
         patterns=_rx(r"business update", r"operational update",
                      r"\bmonthly (?:sales|numbers|update)",
                      r"\bpre[- ]?quarter update", r"\bupdate on operations"),
         note="ADDED FROM EVIDENCE, 16 August 2026. He named it -- "
              "'a business update, expansion, capacity, guidance' -- and "
              "a scan of the 3,829 NEWS/MACRO events no family matched "
              "found 'business update' 128 times, the only opportunity "
              "phrase in the top of that list. Everything above it was "
              "earnings content (ebitda margin, investor presentation, "
              "cons profit), which already has its own kind and grade "
              "and is not an un-recognised family."),

    dict(key="GUIDANCE", family=COMPANY, horizon=SESSION, side=EITHER,
         label="Guidance / outlook change",
         patterns=_rx(r"\bguidance\b", r"\boutlook\b.{0,20}\b(?:raise|cut|revis)",
                      r"\braises? .{0,15}(?:target|guidance|estimate)",
                      r"\bupgrade[ds]?\b.{0,15}\b(?:to|from)\b",
                      r"\bdowngrade[ds]?\b"),
         note=""),
)

BY_KEY = {t["key"]: t for t in TYPES}

# ---- WORDS THAT FLIP THE SIGN ------------------------------------
# An FDA inspection with 8 observations matches FDA_APPROVAL's
# patterns and means the opposite. Direction is NEVER taken from the
# type; it is taken from the sentence, and left UNKNOWN when the
# sentence does not say. Unknown must stay unknown -- core/ranker.py
# already refuses UNKNOWN-direction links by name.
_NEGATIVE = _rx(r"\bobservation", r"\bForm 483\b", r"\bwarning letter\b",
                r"\bimport alert\b", r"\breject(?:ed|ion)\b",
                r"\bdenied\b", r"\bcancel(?:led|s)?\b", r"\bwithdraw",
                r"\blapse", r"\bdelay(?:ed)?\b", r"\bshortfall\b",
                r"\bcut\b", r"\bdowngrade", r"\bhalt(?:ed)?\b",
                r"\bsuspend", r"\bpenalt", r"\bfine[ds]?\b",
                r"\bstrike\b", r"\bshut(?:down)?\b", r"\bloss\b")

_POSITIVE = _rx(r"\bapprov", r"\bgrant(?:ed|s)?\b", r"\bwins?\b",
                r"\bbags?\b", r"\bsecure[ds]?\b", r"\bawarded?\b",
                r"\bclear(?:ed|ance)\b", r"\braise[ds]?\b",
                r"\bupgrade", r"\brecord\b", r"\bhighest ever\b",
                r"\bcommission(?:ed|ing)\b", r"\bexpand")

UP, DOWN, UNKNOWN = "UP", "DOWN", "UNKNOWN"


def direction_hint(text):
    """UP / DOWN / UNKNOWN from the SENTENCE, never from the type.

    Returns UNKNOWN when both or neither fire. A guess here would be
    worse than silence: core/ranker.py refuses UNKNOWN by name, which
    is the correct outcome for a sentence that does not say.
    """
    body = text or ""
    up = bool(_POSITIVE.search(body))
    down = bool(_NEGATIVE.search(body))
    if up and not down:
        return UP
    if down and not up:
        return DOWN
    return UNKNOWN


def classify(text):
    """Every opportunity family this text matches, with its evidence.

    A LIST, not one answer: "US tariff on steel imports lifts domestic
    mills" is a tariff AND a commodity story, and collapsing that to
    one label throws away half the reason it moved.

    Each hit carries `matched` -- the exact phrase -- because a type is
    a label for RECALL and never the reason for a trade. See the module
    docstring.
    """
    body = (text or "").strip()
    if not body:
        return []
    out = []
    for spec in TYPES:
        found = spec["patterns"].search(body)
        if not found:
            continue
        out.append({
            "key": spec["key"],
            "label": spec["label"],
            "family": spec["family"],
            "horizon": spec["horizon"],
            "side": spec["side"],
            "matched": found.group(0),
            "direction": direction_hint(body),
        })
    return out


def keys(text):
    """Just the type keys -- for storing on an event row."""
    return [hit["key"] for hit in classify(text)]


# ==================================================================
# THE MEMORY
# ==================================================================

def _rows(db, sql, params=()):
    """Read-only, never raises. An unreadable store must read as
    "cannot say", never as "nothing happened" -- those are opposite
    answers and only one of them is safe."""
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except Exception:                                       # noqa: BLE001
        return None
    try:
        return list(con.execute(sql, params))
    except Exception:                                       # noqa: BLE001
        return None
    finally:
        con.close()


def _next_session_move(symbol, on_date, sessions=1):
    """close-to-close % from the session after `on_date`.

    Uses data/daily_candles.db, the same store core/runup.py reads.
    None when the history is not there -- and None is not zero.
    """
    rows = _rows(CANDLES_DB,
                 "select date, close from daily_bars "
                 "where symbol = ? and date >= ? order by date limit ?",
                 (str(symbol).upper(), str(on_date)[:10], sessions + 1))
    if not rows or len(rows) < 2:
        return None
    first, last = rows[0][1], rows[min(sessions, len(rows) - 1)][1]
    try:
        first, last = float(first), float(last)
    except (TypeError, ValueError):
        return None
    if first <= 0:
        return None
    return (last - first) / first * 100.0


def scan(since_days=120, limit=None):
    """Type every stored event. Returns rows, never raises.

    This is the LEARNING half: it does not ask what should happen, it
    reads what did.
    """
    cutoff = (datetime.now() - timedelta(days=since_days)).strftime("%Y-%m-%d")
    sql = ("select symbol, at, kind, coalesce(headline,'') || ' ' || "
           "coalesce(detail,'') from events where at >= ? order by at")
    if limit:
        sql += f" limit {int(limit)}"
    rows = _rows(EVENTS_DB, sql, (cutoff,))
    if rows is None:
        return {"available": False, "hits": [],
                "note": f"{EVENTS_DB} could not be read"}
    hits = []
    for symbol, at, kind, body in rows:
        for hit in classify(body):
            hits.append(dict(hit, symbol=symbol, at=at, kind=kind))
    return {"available": True, "hits": hits, "scanned": len(rows)}


def evaluate(since_days=120, min_cases=10):
    """SELF-EVALUATION. What each family did, measured, with its n.

    min_cases defaults to 10 because he set that floor himself:

        "nothing concluded from fewer than 10 comparable cases. Say
         'insufficient data' and state exactly what more is needed."

    A family under the floor is REPORTED with its count and explicitly
    refuses to state an average. That refusal is the feature -- a mean
    of three is how a coincidence becomes a rule.
    """
    got = scan(since_days=since_days)
    if not got["available"]:
        return {"available": False, "note": got["note"], "families": []}

    buckets = {}
    for hit in got["hits"]:
        if not hit.get("symbol"):
            continue                       # market-wide, no stock to measure
        move = _next_session_move(hit["symbol"], hit["at"])
        b = buckets.setdefault(hit["key"], {"moves": [], "seen": 0,
                                            "unmeasurable": 0, "up": []})
        b["seen"] += 1
        if move is None:
            b["unmeasurable"] += 1
        else:
            b["moves"].append(move)
            # ---- THE MEAN OF BOTH SIGNS IS NOISE. ----
            #
            # FDA_APPROVAL first measured -0.48% over 23 cases, which
            # reads as "approvals are bad". They are not: the family
            # matches on "USFDA", so an approval and a Form 483 with
            # eight observations land in the same bucket and cancel.
            #
            # This bot is LONG ONLY, so the only sub-population it
            # could ever act on is the one the sentence says is
            # positive. Kept separate, with its own n.
            if hit.get("direction") == UP:
                b["up"].append(move)

    families = []
    for key, spec in BY_KEY.items():
        b = buckets.get(key, {"moves": [], "seen": 0, "unmeasurable": 0,
                              "up": []})
        moves, n = b["moves"], len(b["moves"])
        good, gn = b["up"], len(b["up"])
        row = {
            "key": key, "label": spec["label"], "family": spec["family"],
            "horizon": spec["horizon"], "side": spec["side"],
            "seen": b["seen"], "measured": n,
            "unmeasurable": b["unmeasurable"],
            "positive_cases": gn,
        }
        if n >= min_cases:
            row["avg_pct"] = round(sum(moves) / n, 2)
            row["up_rate"] = round(
                100.0 * sum(1 for m in moves if m > 0) / n, 1)
            row["verdict"] = "measured"
        else:
            row["avg_pct"] = None
            row["up_rate"] = None
            row["verdict"] = (
                f"insufficient data -- {n} measurable case(s), needs "
                f"{min_cases}")
        # The long-only sub-population, held to the SAME floor. A
        # family can be measurable overall and still refuse to speak
        # about its positive half, which is the honest outcome when
        # the split leaves too few.
        if gn >= min_cases:
            row["avg_pct_positive"] = round(sum(good) / gn, 2)
            row["up_rate_positive"] = round(
                100.0 * sum(1 for m in good if m > 0) / gn, 1)
        else:
            row["avg_pct_positive"] = None
            row["up_rate_positive"] = None
        families.append(row)

    families.sort(key=lambda r: (-r["seen"], r["key"]))
    return {"available": True, "families": families,
            "scanned": got.get("scanned", 0),
            "min_cases": min_cases,
            "note": "This bot may hold overnight on MTF -- config."
                    "FORCE_SQUARE_OFF_AT_CLOSE is False -- so SESSION "
                    "and DAYS are both reachable. QUARTERS is recorded "
                    "so a move has an explanation, not so it can be "
                    "traded: a theme that turns over in quarters is not "
                    "a position sized on a 2.5% stop."}


def verdict():
    """One line, honest, for a screen or a terminal."""
    got = evaluate()
    if not got["available"]:
        return "The opportunity memory could not be read."
    measured = [f for f in got["families"] if f["verdict"] == "measured"]
    seen = sum(f["seen"] for f in got["families"])
    if not measured:
        return (f"{seen} opportunity events recognised across "
                f"{len(got['families'])} families -- none yet has "
                f"{got['min_cases']} measurable cases, so none has an "
                f"average worth printing. It recognises and remembers; "
                f"it does not vote.")
    return (f"{seen} opportunity events across {len(got['families'])} "
            f"families, {len(measured)} with enough cases to measure. "
            f"It recognises and remembers; it does not vote.")
