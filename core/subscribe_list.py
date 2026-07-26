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
MIN_TURNOVER_RS = 50_000_000

# NSE publishes a price band per scrip in its daily securities list.
# Anything banded at or below this cannot produce a tradeable ORB
# breakout -- it just locks. Surveillance (ASM/GSM) names show up here.
MIN_PRICE_BAND_PCT = 10.0

# New listings are added to the master file so their SECURITY ID is
# captured while we have it, but never traded until a human fills in
# the sector. This is the reason text that keeps them out.
UNCLASSIFIED_REASON = "new listing -- awaiting sector classification"


def decide(symbol, bhav=None, sector="", excluded=None, bands=None,
           corporate_actions=None, min_turnover=MIN_TURNOVER_RS):
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
        return False, "ETF / fund / SGB -- not company equity"

    if not str(sector or "").strip():
        return False, UNCLASSIFIED_REASON

    if symbol in corporate_actions:
        return False, ("corporate action today -- price scale changes, "
                       "%-moves vs yesterday are not comparable")

    band = bands.get(symbol)
    if band is not None and band <= MIN_PRICE_BAND_PCT:
        return False, (f"{band:g}% price band (surveillance/ASM) -- "
                       f"too narrow for an ORB breakout")

    # -- checks that need yesterday's bhavcopy --

    if bhav is None:
        # FAIL-OPEN. Could be a genuinely delisted name, or simply a
        # bhavcopy we failed to download. Never silently drop a stock
        # over a network problem -- the caller reports these instead.
        return True, ""

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
        return False, (f"turnover Rs {turnover/1e7:.2f}cr below "
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


def apply(rows, bhav_index, excluded=None, bands=None,
          corporate_actions=None, min_turnover=MIN_TURNOVER_RS):
    """
    Stamp SUBSCRIBE / SUBSCRIBE_REASON onto every row. Mutates and
    returns the rows, plus a summary dict for the operator.
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
