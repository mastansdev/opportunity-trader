"""
==========================================================
Subscribe List -- the pre-market YES/NO gate
==========================================================

Operator request, 2026-07-25:

    "i want bot to select/remove/add those stocks in
     master-stocks.csv. i'll run every morning before trading
     starts (around 08:30-08:50), bot needs to add a column:
     Subscribe - YES OR NO against each stock. YES = tradeable
     stocks as simple as that; NO = all issues we discussed like
     T2T, & other which are basically non tradable in intraday."

So the master file grows two columns:

    SUBSCRIBE          YES / NO
    SUBSCRIBE_REASON   why, in plain words (blank when YES)

WHY MARK, NOT DELETE
--------------------
A removed row loses its SECTOR / INDUSTRY / KEYWORDS / THEMES --
hand-built data that took real effort and that the sector gate and the
news matcher both depend on. A stock that falls under Rs 200 this month
may well be back over it next month, and deleting it would mean
rebuilding all of that from scratch. So nothing is ever deleted: it is
flipped to NO with a reason, and flips back to YES on its own the
morning it qualifies again.

WHAT MAKES A STOCK "NO"
-----------------------
Every one of these is a reason the stock cannot be traded intraday by
THIS bot, checked against the previous session's official NSE data:

  1. SERIES is not EQ  -- BE/BZ is trade-to-trade. No intraday at all.
     This is the one that costs real money: on 2026-07-24 the bot
     "traded" STLTECH and SUDEEPPHRM, both T2T. Harmless in PAPER;
     in LIVE it becomes compulsory delivery and the short is impossible.
  2. ETF / SGB / SME -- not company equity. Every rule in this bot
     (sector strength, relative strength, corporate actions, news
     keywords) is meaningless for a fund. Operator, explicitly:
     "we will trade only in Equity series - do not subscribe to any
     other (silverbees/gold/inrusd)".
  3. Price outside Rs 200 - Rs 10,000. Below: one tick is a large
     fraction of price, so a 0.4% stop cannot survive the granularity.
     Above: a Rs 2L position buys 11 shares, and whole-share rounding
     throws the Rs 800 risk model off by 30-50%.
  4. Turnover below the floor. TURNOVER IS THE PREVIOUS DAY'S total
     traded VALUE in rupees, straight from NSE's bhavcopy -- not
     intraday, because at 08:30 the market has not opened. It answers
     one question: did enough money change hands yesterday that we can
     get in and out today without moving the price ourselves?
  5. Narrow price band (2% / 5%). NSE's own daily securities list
     carries each scrip's band. A stock that can only move 2% cannot
     produce a tradeable opening-range breakout -- it locks. This is
     the ASM/GSM surveillance answer the operator asked for: those
     names get banded, and the band is published before the open.
  6. A price-adjusting corporate action today (split / bonus / rights /
     demerger / dividend ex-date). The price SCALE changes, so every
     %-move against yesterday's close is a lie. Excluded from the feed
     entirely rather than merely blocked from entry, because a fake
     -80% would otherwise poison the gainers/losers table, the sector
     strength ranking and the market-breadth regime read.
  7. Absent from yesterday's bhavcopy -- delisted, suspended, renamed.
  8. Not yet classified (no SECTOR). New listings land here.

NOT a reason for NO: an earnings date. The engine already refuses
entries on a reporting stock, but its move is REAL, so it should still
feed sector strength and breadth. Excluding it would distort the
market read to fix a problem that is already fixed elsewhere.

FAIL-OPEN, EVERYWHERE
---------------------
If the bhavcopy cannot be downloaded, if NSE's ETF list is down, if the
price-band report is missing -- the affected check is SKIPPED, not
failed. A stock is never marked NO because a website was slow. The one
exception is data we already hold locally (series, price, turnover from
a bhavcopy we did read), which is authoritative.

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import os
import re
from datetime import datetime

from core.master_loader import MASTER_CSV_PATH, REQUIRED_COLUMNS
from core.universe_builder import (
    MAX_PRICE, MIN_PRICE, TRADEABLE_SERIES, looks_like_a_fund,
)

SUBSCRIBE_COL = "SUBSCRIBE"
REASON_COL = "SUBSCRIBE_REASON"

YES = "YES"
NO = "NO"

# Rs 5 crore of PREVIOUS-DAY turnover. Deliberately stricter than the
# live engine's MIN_TURNOVER_RS (Rs 2cr) so the pre-market list is the
# real filter and the live gate is only a backstop. Measured on
# 2026-07-24's bhavcopy: Rs 2cr keeps 581 of our 750 but pulls in 384
# new symbols to hand-classify; Rs 5cr keeps 543 and pulls in 247;
# Rs 10cr keeps 474 and pulls in 152.
# ---- THE BAR IS A SHARE OF THE DAY, NOT A RUPEE FIGURE ----
#
#     "whats your call on this? suggest"   -- operator, 2 August 2026
#
# My call is to KEEP the number and change its FORM. Measured on the
# live store, dropping the bar from Rs 5cr to Rs 3cr buys:
#
#     channel-graded names   233 -> 251   (+18, of which 2 EXCELLENT)
#     CANSLIM rated           54 ->  60
#     CANSLIM EXCEPTIONAL      4 ->   4   (all four already clear it)
#     CANSLIM STRONG          10 ->  11   (+1)
#
# Eighteen names, two of them well graded. That is a small gain, and
# the standing rule on this book is that there is no room for error.
#
# What was wrong was the FORM. Rs 5 crore is meaningless on its own --
# it only means anything next to the size of a position. His own rule
# is Rs 1 lakh per MTF position, so Rs 5cr means:
#
#     my order is 0.2% of what the stock trades on a NORMAL day
#
# THAT is the invariant worth keeping, and a flat rupee constant does
# not keep it: raise the position to Rs 2 lakh and the same Rs 5cr bar
# silently becomes 0.4%, with nothing anywhere saying so. So the bar is
# derived. Today it computes to exactly 50,000,000 and nothing changes;
# the day position size moves, it moves with it.
#
# Why 0.2% and not the 1-5%-of-ADV rule of thumb: those assume exiting
# over a whole session. This book exits at a 2.5% stop, in minutes, and
# carries MTF overnight -- so the number that matters is what can be
# sold in a hurry on a quiet day, not what can be worked all day.
MAX_POSITION_SHARE_OF_DAY = 0.002        # 0.2% of a normal day's value

try:
    from config import MTF_MARGIN_PER_POSITION_RS as _POSITION_RS
except Exception:                                          # noqa: BLE001
    # ---- THE FALLBACK WAS THREE TIMES HIS REAL SIZE. 6 Aug 2026. ----
    # config.MTF_MARGIN_PER_POSITION_RS moved to 30,000 and this
    # hard-coded fallback stayed at the old 1,00,000. It only bites
    # when config cannot be imported -- and that is precisely the
    # moment nothing else is around to catch a position sized 3.3x too
    # large. It tracks the live value now.
    _POSITION_RS = 30_000.0              # his rule, as at 6 August 2026

MIN_TURNOVER_RS = _POSITION_RS / MAX_POSITION_SHARE_OF_DAY

# ---- ONE DAY WAS NOT A MEASUREMENT. 2 August 2026. ----
#
#     "fix both"
#
# CENTURYPLY was blocked as illiquid on Rs 1.76cr. That is its 30 July
# figure. On 31 July it traded Rs 62.29 crore:
#
#     22 Jul  23 Jul  24 Jul  27 Jul  28 Jul  29 Jul  30 Jul  31 Jul
#      1.25    2.64    2.68    2.94    1.66    6.29    1.76   62.29
#
# A single previous session decides both ways: one quiet day blocks a
# liquid stock, one busy day passes an illiquid one. Measured over the
# 106 names blocked as illiquid, 40 of them have a ten-session MEDIAN
# above the bar -- KROSS Rs 18.62cr, INDOBORAX 14.77, VRLLOG 12.25,
# ALKYLAMINE 10.16, DOMS 8.63. None of those is illiquid.
#
# MEDIAN, not mean. CENTURYPLY's mean over those eight sessions is
# Rs 10.2cr and its median is Rs 2.66cr -- the mean is carried
# entirely by the one 62-crore results day, which is exactly the kind
# of day you cannot count on being able to exit into. The median
# answers "on a normal day, can I get in and out", which is the
# question the bar was written for.
TURNOVER_SESSIONS = 10

# Below this many sessions the median is not a median, it is a small
# sample wearing one. A newly listed stock with two days of history
# falls back to what it has, and the reason text says how many days it
# is speaking from so a thin read is never mistaken for a firm one.
TURNOVER_MIN_SESSIONS = 3

# NSE publishes a price band per scrip in its daily securities list.
# A band this tight or tighter cannot produce a tradeable ORB breakout
# -- the stock locks before the move finishes, and a locked stock
# cannot be exited.
#
# ---- THIS WAS 10.0 AND IT WAS WRONG. 2 August 2026. ----
#
#     "10% is not issue why block?"
#
# He was right, and the comment that used to sit here -- "surveillance
# (ASM/GSM) names show up here" -- was the assumption doing the work.
# Measured against NSE's own 30 July securities list:
#
#     band 20     2,202 scrips      18 with a GSM remark
#     band 5        655             32
#     band 10       201              6
#     band 2         51              9
#
# A 10% band is not a surveillance flag. It is NSE's ordinary band for
# a non-F&O scrip that has been a bit livelier than average, and only
# 1 of the 57 in OUR master carried any GSM remark at all.
#
# Then measured on ten sessions of real bhavcopy -- day range as a
# percentage of the previous close, and how often the stock actually
# LOCKED at its limit:
#
#     band       median range   days locked   days with >=5% range
#     No Band        2.13%          0.0%           4.4%
#     20             2.95%          0.2%          17.8%
#     10             3.92%          4.0%          32.3%
#     5              3.59%         25.6%          32.4%
#     2              2.57%         90.0%           0.0%
#
# A 10%-band stock is MORE volatile than the average listed name and
# gives an ORB more room, not less. It locks one day in twenty-five.
# The 5% band is the one that matters: it locks ONE DAY IN FOUR, and a
# locked stock held overnight on MTF is a position you cannot close.
#
# What it was costing: 41 liquid names, among them INDOMIM at Rs 2,120
# crore of median daily turnover, JSWINFRA 108, PARAS 84, ACMESOLAR 73,
# JUSTDIAL 66, ICICIAMC 62. Calling those "too narrow for an ORB
# breakout" was indefensible.
MIN_PRICE_BAND_PCT = 5.0

# ---- "WITHOUT ISSUES IN THEIR MANAGEMENT" ----
#
#     "we will trade NSE STOCKS, without issues in their management =
#      trusted companies will be tradable"
#                                    -- operator, 2 August 2026
#
# So the governance question is asked DIRECTLY instead of being
# smuggled in through the band width, which is what the old rule was
# doing badly. NSE's securities list carries the Graded Surveillance
# Measure stage in its Remarks column, and GSM exists for exactly this
# -- price/earnings disconnects, low net worth, auditor concerns.
#
# STAGE 0 COUNTS. It is the "shortlisted, no restriction yet" rung, and
# on a book that runs 4X MTF overnight, being on the exchange's list at
# all is the answer to "is this a company I trust". Three names in the
# master carry it today and none of them was tradeable anyway, so this
# costs nothing now and is there for when it does.
#
# Fails OPEN. A missing or unreadable Remarks column must not blank the
# universe -- see the `remarks` default in decide().
_SURVEILLANCE = re.compile(r"\bGSM\b|\bASM\b|SURVEILLANCE", re.I)

# New listings are added to the master file so their SECURITY ID is
# captured while we have it, but never traded until a human fills in
# the sector. This is the reason text that keeps them out.
UNCLASSIFIED_REASON = "new listing -- awaiting sector classification"


def decide(symbol, bhav=None, sector="", excluded=None, bands=None,
           corporate_actions=None, min_turnover=MIN_TURNOVER_RS,
           remarks=None, seen_recently=True):
    """
    The whole YES/NO decision for one symbol. Pure function -- no I/O,
    no network, no clock. Returns (subscribe_bool, reason_string); the
    reason is "" when the answer is YES.

    bhav               dict(series, close, turnover) or None if the
                       symbol wasn't in yesterday's bhavcopy
    sector             its SECTOR cell from master_stocks.csv
    excluded           set of NSE-classified ETF/SGB/SME symbols
    bands              {symbol: band_pct} from NSE's securities list
    corporate_actions  set of symbols with a price-adjusting action today
    """
    excluded = excluded or set()
    bands = bands or {}
    corporate_actions = corporate_actions or set()
    symbol = (symbol or "").strip().upper()

    # -- checks that need no market data, so they work even offline --

    if symbol in excluded or looks_like_a_fund(symbol):
        return False, "ETF / SGB / SME -- not on our board"

    if not str(sector or "").strip():
        return False, UNCLASSIFIED_REASON

    if symbol in corporate_actions:
        return False, ("corporate action today -- price scale changes, "
                       "%-moves vs yesterday are not comparable")

    # ---- THE GOVERNANCE QUESTION, ASKED DIRECTLY ----
    # Before the band, because "the exchange has this company under
    # surveillance" outranks "how far can it move today".
    flag = str((remarks or {}).get(symbol) or "").strip()
    if flag and flag not in ("-", "nan") and _SURVEILLANCE.search(flag):
        return False, (f"{flag} -- under exchange surveillance, "
                       f"not a company to hold overnight on margin")

    band = bands.get(symbol)
    if band is not None and band <= MIN_PRICE_BAND_PCT:
        return False, (f"{band:g}% price band -- locks before the move "
                       f"finishes, and a locked stock cannot be exited")

    # -- checks that need yesterday's bhavcopy --

    if bhav is None:
        # ---- NEVER IN ANY BHAVCOPY IS NOT A NETWORK PROBLEM ----
        #      20 August 2026.
        #
        # FAIL-OPEN is right for a MISSED download: a genuine stock
        # must never be dropped because a file did not arrive.
        #
        # But it fails open on ABSENCE, and KEL has never appeared in
        # any bhavcopy because it is not traded on NSE at all -- its
        # security id 18708 belongs to VISDEM TECHNOSYS. So it came
        # back SUBSCRIBE=YES every single night, was set to NO by hand
        # on 18 August, on the 19th, and on the 20th, and the guard in
        # tests/test_master_loader.py caught it all three times.
        #
        # A guard that only fails a test does not stop a rewrite.
        #
        # `seen_recently` is what the caller knows and this function
        # cannot: was this symbol in ANY of the recent bhavcopies. It
        # defaults True so nothing changes for a caller that does not
        # pass it -- absence has to be PROVEN before a stock is
        # dropped, never assumed from one missing file.
        if seen_recently:
            return True, ""
        return False, ("not in any recent bhavcopy -- not traded on "
                       "NSE. A security id that still resolves is "
                       "pointing at a DIFFERENT company")

    series = str(bhav.get("series") or "").strip().upper()
    if series and series not in TRADEABLE_SERIES:
        return False, f"series {series} (T2T) -- NO intraday trading allowed"

    close = bhav.get("close")
    if close is None or close <= 0:
        return False, "no usable closing price in yesterday's bhavcopy"
    if close < MIN_PRICE:
        return False, (f"price Rs {close:,.2f} below Rs {MIN_PRICE:,.0f} -- "
                       f"tick granularity breaks a 0.4% stop")
    if close > MAX_PRICE:
        return False, (f"price Rs {close:,.0f} above Rs {MAX_PRICE:,.0f} -- "
                       f"whole-share rounding breaks position sizing")

    turnover = bhav.get("turnover") or 0.0
    if turnover < min_turnover:
        # Say what the number IS, so a block can be argued with. "days"
        # is present when the index was built over several sessions.
        days = bhav.get("turnover_days")
        over = (f" median of {days} sessions" if days and days > 1
                else " last session")
        return False, (f"turnover Rs {turnover/1e7:.2f}cr{over} below "
                       f"Rs {min_turnover/1e7:.0f}cr -- too illiquid to "
                       f"enter and exit cleanly")

    return True, ""


def read_master(path=MASTER_CSV_PATH):
    """Every row of the master file, in order, as dicts."""
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def build_bhav_index(rows):
    """
    Collapse raw bhavcopy rows into {symbol: dict(series, close,
    turnover)}. An EQ row always wins over a non-EQ row for the same
    symbol, so a name that trades in both series is judged on EQ.
    """
    from core.universe_builder import _num, _pick

    out = {}
    for row in rows:
        symbol = _pick(row, "symbol")
        if not symbol:
            continue
        symbol = str(symbol).strip().upper()
        series = str(_pick(row, "series") or "").strip().upper()
        close = _num(_pick(row, "close"))
        volume = _num(_pick(row, "volume")) or 0.0
        turnover = _num(_pick(row, "turnover"))
        if turnover is None and close is not None:
            turnover = close * volume
        rec = dict(series=series, close=close, turnover=turnover or 0.0)

        prior = out.get(symbol)
        if prior is None or (series in TRADEABLE_SERIES
                             and prior["series"] not in TRADEABLE_SERIES):
            out[symbol] = rec
    return out


def build_bhav_index_over(day_rows, min_sessions=TURNOVER_MIN_SESSIONS):
    """The same index, but turnover is the MEDIAN across several days.

    `day_rows` is a list of raw bhavcopy row-lists, OLDEST FIRST. The
    LAST one is the reference session: series, close and the T2T check
    all come from it, because those are facts about today and a median
    of them would be meaningless. Only TURNOVER is pooled.

    Why -- see TURNOVER_SESSIONS above. CENTURYPLY was blocked on one
    quiet day while its normal volume is many times the bar.

    Each record gains `turnover_days`, the number of sessions the
    median actually speaks from. A stock listed on Thursday has two,
    and decide() prints that in the reason so a thin read is never
    mistaken for a firm one.

    Falls back cleanly: one day in, and this is build_bhav_index() with
    turnover_days=1. Nothing in the caller has to know which it got.
    """
    import statistics

    day_rows = [d for d in (day_rows or []) if d]
    if not day_rows:
        return {}

    per_day = [build_bhav_index(rows) for rows in day_rows]
    latest = per_day[-1]

    out = {}
    for symbol, rec in latest.items():
        seen = [day[symbol]["turnover"] for day in per_day
                if symbol in day and day[symbol].get("turnover") is not None]
        # A day the stock did not trade at all is not a zero to average
        # in -- it is a day with no reading. Bhavcopy only lists scrips
        # that traded, so an absent day is simply dropped, and
        # turnover_days says how many were really there.
        if not seen:
            out[symbol] = dict(rec, turnover_days=0)
            continue
        if len(seen) < max(1, min_sessions):
            # Too few to call it a median. Use the WORST of what we
            # have rather than the best: a two-day-old listing that
            # traded heavily once has not shown it can be exited on a
            # normal day, and this bar exists to answer that.
            out[symbol] = dict(rec, turnover=min(seen),
                               turnover_days=len(seen))
            continue
        out[symbol] = dict(rec, turnover=statistics.median(seen),
                           turnover_days=len(seen))
    return out


def apply(rows, bhav_index, excluded=None, bands=None,
          corporate_actions=None, min_turnover=MIN_TURNOVER_RS,
          remarks=None, seen_recently=None):
    """
    Stamp SUBSCRIBE / SUBSCRIBE_REASON onto every row. Mutates and
    returns the rows, plus a summary dict for the operator.

    `remarks` is {symbol: NSE's Remarks cell} -- the GSM surveillance
    stage. Optional and fails open, so a file that predates the column
    behaves exactly as before.
    """
    flipped_on, flipped_off = [], []
    yes = no = 0

    for row in rows:
        symbol = str(row.get("SYMBOL") or "").strip().upper()
        was = str(row.get(SUBSCRIBE_COL) or "").strip().upper()

        ok, reason = decide(
            symbol,
            bhav=bhav_index.get(symbol),
            sector=row.get("SECTOR"),
            excluded=excluded,
            bands=bands,
            corporate_actions=corporate_actions,
            min_turnover=min_turnover,
            remarks=remarks,
            # The one thing decide() cannot know for itself: has this
            # symbol appeared in ANY recent bhavcopy. Absent from all
            # of them is not a missed download, it is a stock that
            # does not trade -- see the NEVER IN ANY BHAVCOPY note in
            # decide(). None means the caller could not tell, and the
            # old fail-open behaviour is kept exactly.
            seen_recently=(symbol in seen_recently
                           if seen_recently is not None else True),
        )
        row[SUBSCRIBE_COL] = YES if ok else NO
        row[REASON_COL] = "" if ok else reason

        if ok:
            yes += 1
            if was == NO:
                flipped_on.append(symbol)
        else:
            no += 1
            if was == YES:
                flipped_off.append((symbol, reason))

    return rows, dict(
        yes=yes, no=no,
        flipped_on=sorted(flipped_on),
        flipped_off=sorted(flipped_off),
        not_in_bhavcopy=sorted(
            str(r.get("SYMBOL") or "").strip().upper() for r in rows
            if str(r.get("SYMBOL") or "").strip().upper() not in bhav_index
        ),
    )


def write_master(rows, path=MASTER_CSV_PATH):
    """
    Rewrite the master file with the two new columns, ATOMICALLY.

    Written to a temp file and swapped into place, so a crash or a
    Ctrl-C halfway through can never leave a half-written universe --
    the bot validates this file at startup and refuses to run on a
    broken one, which at 08:45 would mean no trading that day.
    """
    fieldnames = list(REQUIRED_COLUMNS)
    for extra in (SUBSCRIBE_COL, REASON_COL):
        if extra not in fieldnames:
            fieldnames.append(extra)

    # ---- IT SILENTLY DROPPED A COLUMN EVERY NIGHT. 19 Aug 2026 ----
    #
    # The header came from REQUIRED_COLUMNS alone, and extrasaction
    # was "ignore" -- so any column NOT on that hardcoded list was
    # deleted on every nightly run, without a word.
    #
    # SERIES is not on the list. It was restored by hand on 18 August
    # and again on the 19th, and the guard in
    # tests/test_master_loader.py caught it both times:
    #
    #     1306 tradeable row(s) have no SERIES, so the T2T gate
    #     cannot see them
    #
    # A T2T name is settlement-only -- it cannot be squared off
    # intraday -- so a blind gate is a real trading fault, not a
    # cosmetic one. And the guard only fails a test; it never stopped
    # the rewrite, which is why this happened three times.
    #
    # Any column present on the ROWS is now preserved, appended after
    # the required ones so the familiar order is unchanged. This file
    # does not own the columns other tools add, and a writer that
    # silently discards data it does not recognise is the wrong shape
    # for a file five commands take turns editing.
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for column in row:
            if column not in fieldnames:
                fieldnames.append(column)

    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    os.replace(tmp, path)
    return path


def find_new_listings(bhav_index, known_symbols, excluded=None,
                      bands=None, min_turnover=MIN_TURNOVER_RS):
    """
    Symbols that pass every MARKET test but aren't in our file at all.
    Sorted by turnover, biggest first -- so the operator classifies the
    ones that matter before the ones that don't.
    """
    excluded = excluded or set()
    bands = bands or {}
    out = []
    for symbol, rec in bhav_index.items():
        if symbol in known_symbols:
            continue
        # sector="x" so the unclassified check doesn't fire here -- being
        # unclassified is the whole POINT of this list.
        ok, _ = decide(symbol, bhav=rec, sector="x", excluded=excluded,
                       bands=bands, min_turnover=min_turnover)
        if ok:
            out.append(dict(symbol=symbol, **rec))
    return sorted(out, key=lambda r: -(r["turnover"] or 0))


def write_new_stocks_md(new_listings, path="NEW_STOCKS.md",
                        security_ids=None, when=None):
    """
    The operator's daily classification queue:

        "create a file name NEW_STOCKS.md, I'LL check them everyday &
         manually enter those data if possible instantly or by EOD."

    One markdown table, ready to work through. Each row already carries
    the Dhan SECURITY ID where we could resolve it, because that is the
    one field that cannot be looked up by hand.
    """
    security_ids = security_ids or {}
    when = when or datetime.now()

    lines = [
        "# New Stocks -- awaiting classification",
        "",
        f"Generated {when:%Y-%m-%d %H:%M} by `py tools/morning_universe.py`.",
        "",
        "These passed every market test (EQ series, Rs 200-10,000, ",
        "liquid, not a fund) but have no SECTOR in `data/master_stocks.csv`,",
        "so they are sitting at **SUBSCRIBE = NO** and are not being traded.",
        "",
        "Fill in SECTOR / INDUSTRY / KEYWORDS / THEMES for a row and the",
        "next morning's run flips it to **YES** on its own.",
        "",
        f"**{len(new_listings)} waiting.**",
        "",
        "| Symbol | Security ID | Close | Turnover (cr) | Sector? |",
        "|---|---|---|---|---|",
    ]
    for rec in new_listings:
        sid = security_ids.get(rec["symbol"], "")
        close = rec.get("close") or 0
        turnover = (rec.get("turnover") or 0) / 1e7
        flag = "" if sid else " **(no Dhan ID -- cannot trade)**"
        lines.append(
            f"| {rec['symbol']} | {sid}{flag} | {close:,.2f} | "
            f"{turnover:,.2f} | |"
        )
    lines.append("")
    lines.append("Rows with no Dhan security ID cannot be subscribed to at ")
    lines.append("all -- the feed is keyed on that ID, not the symbol.")
    lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path
