"""
==========================================================
Morning Universe -- run this at 08:30, before the market opens
==========================================================

    py tools/morning_universe.py

One command. It:

  1. Downloads yesterday's official NSE bhavcopy (series, close,
     turnover for every scrip that traded).
  2. Downloads NSE's ETF / SGB / SME lists, and the daily securities
     list that carries each scrip's PRICE BAND (this is where ASM/GSM
     surveillance names give themselves away).
  3. Refreshes corporate actions into the stock memory, so a stock
     going ex-split today is known before the open.
  4. Stamps SUBSCRIBE = YES / NO on every row of
     data/master_stocks.csv, with the reason in plain words.
  5. Appends any brand-new listing that passes every market test,
     resolving its Dhan SECURITY ID, and writes NEW_STOCKS.md for you
     to classify.
  6. Prints what changed since yesterday.

SAFE TO RUN TWICE. It is idempotent -- running it again on the same
data produces the same file. The master file is rewritten atomically
(temp file, then swap), so a Ctrl-C cannot leave you with a corrupt
universe at 08:45.

SAFE WHEN THE INTERNET IS DOWN. Every fetch fails open: a check whose
data is unavailable is SKIPPED rather than failed, so no stock is ever
marked NO because a website was slow. If the bhavcopy itself cannot be
downloaded, the run aborts without touching the file at all -- the
previous day's YES/NO list stays in force, which is far better than a
list built on nothing.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import decision, warn  # noqa: E402
from core.master_loader import MASTER_CSV_PATH  # noqa: E402
from core.subscribe_list import (  # noqa: E402
    MIN_TURNOVER_RS, NO, TURNOVER_SESSIONS, YES, apply, build_bhav_index,
    build_bhav_index_over, find_new_listings, read_master, write_master,
    write_new_stocks_md,
)
from core.universe_builder import fetch_bhavcopy, fetch_excluded_symbols  # noqa: E402


def latest_bhavcopy(max_lookback=6, folder="data"):
    """
    Yesterday's bhavcopy -- or the most recent trading day's, walking
    back over weekends and holidays. Returns (rows, date) or ([], None).
    """
    today = datetime.now()
    for back in range(1, max_lookback + 1):
        day = today - timedelta(days=back)
        if day.weekday() >= 5:          # Saturday/Sunday never have one
            continue
        rows = fetch_bhavcopy(date=day, folder=folder)
        if rows:
            return rows, day
    return [], None


def recent_bhavcopies(sessions=TURNOVER_SESSIONS, folder="data",
                      max_lookback=30):
    """The last `sessions` trading days of bhavcopy, OLDEST FIRST.

    ---- WHY MORE THAN ONE. 2 August 2026. ----
    See core/subscribe_list.TURNOVER_SESSIONS. One previous session
    decides the liquidity bar in both directions and gets it wrong both
    ways: SIGMA traded Rs 31.74cr on its results day and its ten-day
    median is Rs 0.15 crore. On the single-day rule that stock was
    tradeable, on MTF, overnight, into a book you cannot get out of.

    Reads from disk first -- fetch_bhavcopy() caches every file it
    downloads into data/, and there are 35 of them there already, so a
    normal morning does ONE download and reads the other nine.

    Never raises and never returns fewer than it can: a holiday, a
    missing file or a dead network simply gives a shorter list, and
    build_bhav_index_over() reports how many sessions it really had.
    """
    got, day, checked = [], datetime.now(), 0
    while len(got) < sessions and checked < max_lookback:
        checked += 1
        day = day - timedelta(days=1)
        if day.weekday() >= 5:
            continue
        rows = fetch_bhavcopy(date=day, folder=folder, quiet=True)
        if rows:
            got.append((day, rows))
    got.reverse()                                   # oldest first
    return got


def fetch_price_bands(date, folder="data"):
    """
    ({symbol: band_pct}, {symbol: remarks}) from NSE's daily securities
    list.

    THE BAND AND THE SURVEILLANCE FLAG ARE TWO DIFFERENT THINGS, and
    the comment that used to be here said they were the same:

        "ASM/GSM names get banded down to 2% or 5%"

    Measured on the 30 July list, that is false. 655 scrips sit on a 5%
    band and only 32 of them carry a GSM remark; 2,202 sit on 20% and
    18 of those carry one. The band says how far the stock may move
    today. The REMARKS column says whether the exchange has a problem
    with the company. core/subscribe_list.decide() now reads both, and
    reads them as separate questions.

    Fails open: ({}, {}) on any problem, and both checks are skipped.
    """
    import csv as _csv
    try:
        from nse import NSE
        with NSE(download_folder=folder) as n:
            path = n.priceband_report(date=date, folder=folder)
    except Exception as exc:
        warn(f"[MORNING] Price-band report unavailable ({exc}). "
             f"Band and surveillance checks skipped -- no stock is "
             f"marked NO because of it.")
        return {}, {}

    bands, remarks = {}, {}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for row in _csv.DictReader(f):
                row = {(k or "").strip().upper(): v for k, v in row.items()}
                symbol = (row.get("SYMBOL") or "").strip().upper()
                band = row.get("BAND") or row.get("PRICE BAND") or ""
                if not symbol:
                    continue
                note = str(row.get("REMARKS") or "").strip()
                if note and note != "-":
                    remarks[symbol] = note
                try:
                    bands[symbol] = float(str(band).replace("%", "").strip())
                except (TypeError, ValueError):
                    continue
    except Exception as exc:
        warn(f"[MORNING] Could not read the price-band report: {exc}")
        return {}, {}
    return bands, remarks


def fetch_corporate_actions(known_symbols, on_date=None):
    """
    Symbols going ex-split / ex-bonus / ex-rights / ex-dividend on the
    session this list is being built FOR. Their price scale changes
    overnight, so every %-move against yesterday's close is meaningless
    -- and would poison the gainers/losers table and the sector ranking
    if left on the feed.

    ---- on_date EXISTS BECAUSE THIS NOW RUNS AT NIGHT. 2 Aug 2026 ----

        "every night we will complete the necessary works, & in morning
         only small pending can be completed by bot within 15-20 mins"

    price_distorting_symbols() defaults to TODAY. Run at 22:00 on a
    Sunday that means Sunday -- and a stock going ex-split on MONDAY
    would not be blocked on the Monday list this run is building. The
    one job of this function, missed by a date.

    Fails open: empty set on any problem.
    """
    try:
        from core.corporate_actions import refresh
        from core.stock_memory import default_memory
        memory = default_memory()
        refresh(memory=memory, known_symbols=known_symbols)
        return set(memory.price_distorting_symbols(on_date=on_date))
    except Exception as exc:
        warn(f"[MORNING] Corporate-action refresh failed ({exc}). "
             f"Ex-date check skipped for today.")
        return set()


def fetch_dhan_security_ids(symbols):
    """
    Resolve NSE equity SECURITY IDs from Dhan's public scrip master, for
    brand-new listings only. Without this a new row is useless: the feed
    subscribes by security ID, not by symbol.

    Fails open: {} on any problem, and the new rows are written with a
    blank ID and clearly flagged in NEW_STOCKS.md.
    """
    if not symbols:
        return {}
    try:
        import pandas as pd
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        df = pd.read_csv(url, low_memory=False)
        cols = {c.upper().strip(): c for c in df.columns}
        sym_col = cols.get("SEM_TRADING_SYMBOL") or cols.get("SM_SYMBOL_NAME")
        id_col = cols.get("SEM_SMST_SECURITY_ID")
        seg_col = cols.get("SEM_EXM_EXCH_ID")
        inst_col = cols.get("SEM_INSTRUMENT_NAME")
        if not sym_col or not id_col:
            return {}
        if seg_col:
            df = df[df[seg_col].astype(str).str.upper() == "NSE"]
        if inst_col:
            df = df[df[inst_col].astype(str).str.upper() == "EQUITY"]
        wanted = {s.upper() for s in symbols}
        out = {}
        for sym, sid in zip(df[sym_col].astype(str), df[id_col].astype(str)):
            s = sym.strip().upper()
            if s in wanted and s not in out:
                out[s] = sid.strip()
        return out
    except Exception as exc:
        warn(f"[MORNING] Dhan scrip master unavailable ({exc}). New "
             f"listings will be written without a security ID.")
        return {}


def next_session(today=None):
    """The session this list is being built FOR.

    Run in the morning that is today. Run the night before -- which is
    the point of tools/nightly.py -- it is the next weekday. Getting it
    wrong means the ex-date block is applied to the wrong day, and a
    stock whose price scale changes overnight stays on the feed.
    """
    day = (today or datetime.now()).date()
    if (today or datetime.now()).hour >= 16:      # after the close
        day = day + timedelta(days=1)
    while day.weekday() >= 5:                     # Sat / Sun
        day = day + timedelta(days=1)
    return day


def main():
    decision("=" * 62)
    decision("  MORNING UNIVERSE -- pre-market subscribe list")
    decision("=" * 62)

    rows, fieldnames = read_master(MASTER_CSV_PATH)
    known = {str(r.get("SYMBOL") or "").strip().upper() for r in rows}
    decision(f"  Master file            : {len(rows)} rows")

    bhav_rows, bhav_date = latest_bhavcopy()
    if not bhav_rows:
        warn("  ABORTED -- could not download any recent bhavcopy. The "
             "master file was NOT touched; yesterday's SUBSCRIBE list "
             "stays in force. Check your connection and re-run.")
        return 1
    decision(f"  Bhavcopy               : {bhav_date:%Y-%m-%d} "
             f"({len(bhav_rows)} rows)")

    # Keep the daily candle before anything else touches the rows. The
    # bhavcopy's OpnPric/HghPric/LwPric/ClsPric ARE a daily bar -- we
    # were reading three columns for the SUBSCRIBE decision and throwing
    # the rest away. Storing them is what lets the bot finally see
    # YESTERDAY (core/trend_structure.py). Dedup is on (date, symbol),
    # so running this twice in a morning stores nothing the second time.
    try:
        from core.daily_store import DailyStore, bars_from_bhavcopy
        store = DailyStore()
        written = store.upsert_many(
            bars_from_bhavcopy(bhav_rows, bhav_date.strftime("%Y-%m-%d"))
        )
        st = store.stats()
        decision(f"  Daily candles          : +{written} today, "
                 f"{st['bars']:,} bars over {st['days']} day(s)")
        if st["days"] < 8:
            warn(f"  Only {st['days']} day(s) of daily history -- a 7-day "
                 f"structure read needs 8. Run: "
                 f"py tools/build_daily_history.py")
    except Exception as exc:
        warn(f"[MORNING] Daily-candle store failed ({exc}). Subscribe "
             f"list is unaffected.")

    # ---- LIQUIDITY IS MEASURED OVER SESSIONS, NOT ONE DAY ----
    #
    # The reference day above still decides series, close and the T2T
    # check -- those are facts about today. Only TURNOVER is pooled.
    # See core/subscribe_list.TURNOVER_SESSIONS for the measurement.
    #
    # Degrades rather than fails: if only one bhavcopy can be read this
    # is exactly the old behaviour, and the reason text on every block
    # says how many sessions it spoke from.
    history = recent_bhavcopies()
    if len(history) > 1:
        bhav_index = build_bhav_index_over([rows_ for _, rows_ in history])
        span = f"{history[0][0]:%d %b} to {history[-1][0]:%d %b}"
        decision(f"  Turnover window        : {len(history)} sessions "
                 f"({span}), median per stock")
    else:
        bhav_index = build_bhav_index(bhav_rows)
        warn("  Turnover window        : 1 session only -- could not read "
             "enough recent bhavcopies, so a single quiet or busy day "
             "decides the liquidity bar. Re-run when the network is up.")
    excluded = fetch_excluded_symbols()
    bands, remarks = fetch_price_bands(bhav_date)
    if remarks:
        decision(f"  Under surveillance     : {len(remarks)} scrip(s) "
                 f"carry a GSM remark on NSE's list")
    for_day = next_session()
    if for_day != datetime.now().date():
        decision(f"  Building the list FOR : {for_day:%a %d %b} "
                 f"(run after the close, so ex-dates are read for that "
                 f"session, not tonight)")
    actions = fetch_corporate_actions(known, on_date=for_day)

    decision(f"  NSE ETF/SGB/SME list   : {len(excluded)} symbols")
    decision(f"  Price bands            : {len(bands)} symbols"
             + ("" if bands else "  (skipped -- unavailable)"))
    decision(f"  Ex-date actions today  : {len(actions)}"
             + (f"  ({', '.join(sorted(actions)[:6])})" if actions else ""))

    # -- new listings, added but never traded until classified --
    new_listings = find_new_listings(bhav_index, known, excluded=excluded,
                                     bands=bands)
    sec_ids = fetch_dhan_security_ids([r["symbol"] for r in new_listings])
    for rec in new_listings:
        sid = sec_ids.get(rec["symbol"], "")
        if not sid:
            continue          # no Dhan ID -> cannot subscribe -> don't add
        blank = {k: "" for k in fieldnames}
        blank.update({
            "SECURITY ID": sid,
            "SYMBOL": rec["symbol"],
            "COMPANY NAME": rec["symbol"],
        })
        rows.append(blank)

    # ---- market calendar + results calendar -------------------------
    # Both fail open and neither can affect the SUBSCRIBE decision --
    # they are refreshed here purely because this is the one command
    # that already runs every morning.
    try:
        from core.market_calendar import refresh as refresh_calendar
        cal = refresh_calendar()
        nxt = cal.next_trading_day(datetime.now().date())
        upcoming_holidays = cal.upcoming(days=30)
        if upcoming_holidays:
            decision("  Holidays within 30 days: "
                     + ", ".join(f"{d} ({desc})"
                                 for d, desc in upcoming_holidays[:4]))
        decision(f"  Next trading session   : {nxt}")
    except Exception as exc:
        warn(f"[MORNING] Market calendar refresh failed ({exc}).")

    try:
        from core.results_calendar import refresh as refresh_results
        res = refresh_results(known_symbols=known)
        today_names = res.symbols_on(datetime.now().date())
        if today_names:
            decision(f"  Reporting TODAY ({len(today_names)}): "
                     + ", ".join(sorted(today_names)[:10])
                     + ("..." if len(today_names) > 10 else ""))
    except Exception as exc:
        warn(f"[MORNING] Results calendar refresh failed ({exc}).")

    rows, summary = apply(rows, bhav_index, excluded=excluded, bands=bands,
                          corporate_actions=actions,
                          min_turnover=MIN_TURNOVER_RS,
                          remarks=remarks)
    write_master(rows, MASTER_CSV_PATH)
    md = write_new_stocks_md(new_listings, security_ids=sec_ids)

    decision("-" * 62)
    decision(f"  SUBSCRIBE = {YES:<3}          : {summary['yes']}")
    decision(f"  SUBSCRIBE = {NO:<3}          : {summary['no']}")
    decision(f"  New listings queued    : {len(new_listings)}  -> {md}")

    if summary["flipped_off"]:
        warn(f"  Newly BLOCKED today ({len(summary['flipped_off'])}):")
        for symbol, reason in summary["flipped_off"][:15]:
            warn(f"      {symbol:<14} {reason}")
        if len(summary["flipped_off"]) > 15:
            warn(f"      ... and {len(summary['flipped_off']) - 15} more "
                 f"(see the SUBSCRIBE_REASON column)")

    if summary["flipped_on"]:
        decision(f"  Newly TRADEABLE today ({len(summary['flipped_on'])}): "
                 + ", ".join(summary["flipped_on"][:15])
                 + ("..." if len(summary["flipped_on"]) > 15 else ""))

    if summary["not_in_bhavcopy"]:
        warn(f"  Not in the bhavcopy at all "
             f"({len(summary['not_in_bhavcopy'])}) -- delisted, suspended "
             f"or renamed. Left as-is, NOT auto-blocked: "
             + ", ".join(summary["not_in_bhavcopy"][:10])
             + ("..." if len(summary["not_in_bhavcopy"]) > 10 else ""))

    decision("=" * 62)
    decision("  Done. Start the bot normally -- it subscribes to the "
             "YES rows only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
