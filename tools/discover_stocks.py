"""
==========================================================
Stocks the channels name that we cannot identify
==========================================================
    py tools/discover_stocks.py            look, change nothing
    py tools/discover_stocks.py --apply    add the real ones

Needs the network -- it checks every candidate against Dhan's live
scrip master before writing anything.

WHY
---
    "what ever stocks name we are not having in our database. pls add
     them into our database for sure . we will get all possible quality
     stocks from these channels. do not throw away any information we
     are receiving."          -- operator, 1 August 2026

Measured that morning: the channels had named 427 tickers and 191 of
them were not in data/master_stocks.csv. A stock we cannot identify is
a stock whose results, orders and broker calls are collected, stored,
and then attached to nothing:

    LGBBROSLTD   4 mentions   an Earnings 360 brief, graded, orphaned
    BLUSPRING    4            "margins Compressing" -- nowhere to show it
    NEUEON       4
    SASKEN       4

WHY IT IS NOT SIMPLY "ADD ALL 191"
----------------------------------
Because most of them are not Indian stocks, and some are not stocks:

    META MSFT AMZN NVDA XOM CVX      US tickers from macro posts
    STOCKSTOWATCH TRADING INFRA      hashtags, not companies
    M_M NDTV_RE GSTL_RE              mangled or suffixed forms

Adding those would put junk in the file every other tool trusts, and
this bot has already been bitten by a master file that lied -- on 31
July it held CHOLAFIN as security id 685 when Dhan says 19257, which
would have bought a different company.

So Dhan's own scrip master is the judge. If Dhan lists it as an NSE
EQUITY, it is real and tradeable and gets added. If not, it is
reported and skipped.

WHAT A NEW ROW LOOKS LIKE
-------------------------
SECURITY ID and SYMBOL come from Dhan and are exact. The curated
columns -- SECTOR, CORE BUSINESS, KEYWORDS -- are left blank, because
inventing them is how a matcher starts guessing.

SUBSCRIBE is set to NO. Being identifiable and being tradeable are
different things: this makes the stock's news attach correctly, and
leaves the decision to trade it to morning_universe.py, which measures
turnover.

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import os
import re
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime

sys.path.insert(0, ".")

from core.logger import decision, warn                     # noqa: E402
from core.master_loader import MasterLoader                # noqa: E402

MASTER_CSV = os.path.join("data", "master_stocks.csv")
TELEGRAM_DB = os.path.join("data", "telegram.db")

_TICKER = re.compile(r"#([A-Z][A-Z0-9&_-]{1,14})\b")

# Hashtags these channels use that are not companies. Everything else
# is decided by Dhan, not by this list -- it exists only to keep the
# report readable.
_NOT_A_COMPANY = {
    "STOCKSTOWATCH", "TRADING", "INFRA", "NIFTY", "SENSEX", "BANKNIFTY",
    "IPO", "RESULTS", "EARNINGS", "MARKET", "STOCKS", "NSE", "BSE",
    "JUSTIN", "BREAKING", "IQWITHCNBCTV18", "STOCKPICK",
}


def _line():
    decision("-" * 70)


def candidates(min_mentions=1):
    """Tickers the channels have named, newest first by frequency.

    ---- THREE SOURCES, ONE JUDGE. 2 August 2026. ----

        "yeah what ever the stocks we are not maintained in our master
         data base pls add them in our universe."

    This used to read the typed caption only. BIRLACABLE was on the
    02 August calendar card, tagged in the caption AND printed on the
    picture, and never reached this list.

        1  hashtags in the typed caption      the original source
        2  hashtags in the image transcript   the channel's own ticker,
                                              just read off the picture
        3  tokens inside the During / After
           company blocks of a calendar card  a list of companies by
                                              construction

    THE THIRD ONE IS NOT "READ ALL THE OCR". Measured on the store,
    every ticker-shaped word in every transcript is 14,052 unknown
    tokens and the top of that list is YOY, REVENUE, GROWTH, THE, AND.
    Narrowed to the company blocks of the calendar cards it is 508,
    and the real names come out of it -- BIRLACABLE, SHANTIGEAR,
    HAWKINCOOK, HEIDELBERG, KAMDHENU.

    English prose still comes with it (AND, THE, COMPANIES, HOURS) and
    that is fine, because nothing here decides anything. Dhan's scrip
    master is the judge, and it does not list a company called THE.
    """
    seen = Counter()
    try:
        conn = sqlite3.connect(TELEGRAM_DB)
        rows = conn.execute("select coalesce(text,''), "
                            "coalesce(ocr_text,'') from messages").fetchall()
        conn.close()
    except sqlite3.Error as exc:
        warn(f"  Could not read {TELEGRAM_DB}: {exc}")
        return {}

    for text, read in rows:
        for source in (text, read):
            for tag in _TICKER.findall(str(source).upper()):
                seen[tag] += 1
        for tag in _from_calendar_card((text or "") + "\n" + (read or "")):
            seen[tag] += 1

    return {t: n for t, n in seen.items()
            if n >= min_mentions and t not in _NOT_A_COMPANY}


def _from_calendar_card(body):
    """Ticker-shaped words from the company lists on a calendar card.

    Only from the DURING / AFTER blocks when the card has them, and
    from the whole card when it does not -- ten of the nineteen
    forward cards print no columns at all, and 02 August was one of
    them. Returns nothing for any message that is not one of these
    cards, which is what keeps the 14,052-token flood out.
    """
    try:
        from core import recap_card as rc
    except Exception:                                      # noqa: BLE001
        return []
    if not rc.is_recap_card(body):
        return []
    during = rc._DURING.search(body)
    after = rc._AFTER.search(body)
    if during and after and after.start() > during.start():
        blocks = (body[during.end():after.start()], body[after.end():])
    else:
        blocks = (body,)
    out = []
    for block in blocks:
        out.extend(t for t in rc._TOKEN.findall(block.upper())
                   if t not in rc._FURNITURE)
    return out


def main(apply=False, min_mentions=1):
    decision("=" * 70)
    decision("  DISCOVER -- stocks the channels name that we cannot identify")
    decision("=" * 70)

    loader = MasterLoader()
    loader.load()

    named = candidates(min_mentions)
    unknown = {t: n for t, n in named.items() if not loader.get_by_symbol(t)}

    _line()
    decision(f"  tickers named by the channels : {len(named)}")
    decision(f"  already in the master file    : {len(named) - len(unknown)}")
    decision(f"  unknown, to be checked        : {len(unknown)}")
    _line()

    if not unknown:
        decision("  Nothing to add. Every company these channels name is "
                 "already identifiable.")
        return

    decision("  Asking Dhan which of these are real NSE equities...")
    try:
        from core.instrument_master import InstrumentMaster
        live = InstrumentMaster()
        live.load()
    except Exception as exc:                               # noqa: BLE001
        warn(f"  Could not fetch Dhan's scrip master: {exc}")
        warn("  This needs the network. Nothing was changed.")
        return

    # ---- NOT A FUND, NOT AN SME. 15 September 2026. ----
    #
    #     "remove ... ETFs, gold bonds, SME stocks"   -- the operator
    #
    # 74 such rows were deleted from the master that evening. Dhan lists
    # ETFs as NSE equities, so without this the first channel post that
    # named GOLDBEES would have put it straight back. NSE's own ETF / SGB
    # / SME list decides; the name test catches a fund when that list
    # cannot be downloaded.
    try:
        from core.universe_builder import fetch_excluded_symbols, looks_like_a_fund
        funds = set(fetch_excluded_symbols() or ())
    except Exception as exc:                               # noqa: BLE001
        warn(f"  NSE's ETF/SGB/SME list unavailable ({exc}); the name test "
             f"alone keeps funds out.")
        from core.universe_builder import looks_like_a_fund
        funds = set()
    skipped_funds = [t for t in unknown if t in funds or looks_like_a_fund(t)]
    for t in skipped_funds:
        unknown.pop(t, None)
    if skipped_funds:
        decision(f"  funds / SME, never added      : {len(skipped_funds)} "
                 f"({', '.join(sorted(skipped_funds)[:10])})")

    real, not_listed = [], []
    for tag, count in sorted(unknown.items(), key=lambda x: -x[1]):
        try:
            security_id = live.resolve(tag)
        except Exception:                                  # noqa: BLE001
            security_id = None
        (real if security_id else not_listed).append(
            (tag, count, security_id))

    _line()
    decision(f"  REAL NSE equities we are missing : {len(real)}")
    for tag, count, sid in real:
        decision(f"    {tag:16} id={str(sid):8} named {count}x")
    decision("")
    decision(f"  not listed on NSE (US tickers, hashtags, mangled) : "
             f"{len(not_listed)}")
    decision("    " + "  ".join(t for t, _, _ in not_listed[:18]))

    if not real:
        _line()
        decision("  Nothing real to add.")
        return

    if not apply:
        _line()
        decision("  DRY RUN -- master_stocks.csv was not touched.")
        decision("  To add the real ones:")
        decision("      py tools/discover_stocks.py --apply")
        return

    # ---- write ------------------------------------------------------
    backup = f"{MASTER_CSV}.{datetime.now():%Y%m%d-%H%M%S}.bak"
    shutil.copy(MASTER_CSV, backup)

    with open(MASTER_CSV, encoding="utf-8", errors="replace") as handle:
        fields = csv.DictReader(handle).fieldnames

    added = 0
    with open(MASTER_CSV, "a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        for tag, count, sid in real:
            row = {name: "" for name in fields}
            row["SECURITY ID"] = sid
            row["SYMBOL"] = tag
            # A PLACEHOLDER, AND MARKED AS ONE. Dhan's compact master
            # carries no company name, and inventing one would put a
            # guess in the file every other tool trusts. The ticker
            # keeps the identity check happy; core/telegram_feed.py
            # refuses to index a COMPANY NAME that equals the SYMBOL,
            # so this never becomes a name the matcher hunts for in
            # prose -- which is how URBAN COMPANY cost a wrong tag.
            row["COMPANY NAME"] = tag
            # NOT subscribed. Identifiable and tradeable are different
            # things -- morning_universe.py decides the second one by
            # measuring turnover, and it should keep deciding it.
            row["SUBSCRIBE"] = "NO"
            row["SUBSCRIBE_REASON"] = (
                f"discovered from Telegram {datetime.now():%Y-%m-%d}; "
                f"identity only, sector/business not curated")
            writer.writerow(row)
            added += 1

    _line()
    decision(f"  ADDED {added} stock(s) to {MASTER_CSV}")
    decision(f"  Backup of the old file: {backup}")
    decision("")
    decision("  They are identifiable now, so their results and orders will")
    decision("  attach correctly. They are NOT subscribed -- run")
    decision("      py tools/morning_universe.py")
    decision("      py tools/verify_master_database.py")
    decision("  before the next session, which is the same rule as any")
    decision("  other change to this file.")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
