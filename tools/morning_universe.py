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
    MIN_TURNOVER_RS, NO, YES, apply, build_bhav_index, find_new_listings,
    read_master, write_master, write_new_stocks_md,
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


def fetch_price_bands(date, folder="data"):
    """
    {symbol: band_pct} from NSE's daily securities list. This is how the
    bot learns, before the open, that a stock is under surveillance --
    ASM/GSM names get banded down to 2% or 5%, and a 2% band cannot
    produce a tradeable breakout.

    Fails open: {} on any problem, and the band check is then skipped.
    """
    import csv as _csv
    try:
        from nse import NSE
        with NSE(download_folder=folder) as n:
            path = n.priceband_report(date=date, folder=folder)
    except Exception as exc:
        warn(f"[MORNING] Price-band report unavailable ({exc}). "
             f"Surveillance/ASM check skipped -- no stock is marked NO "
             f"because of it.")
        return {}

    out = {}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for row in _csv.DictReader(f):
                row = {(k or "").strip().upper(): v for k, v in row.items()}
                symbol = (row.get("SYMBOL") or "").strip().upper()
                band = row.get("BAND") or row.get("PRICE BAND") or ""
                if not symbol:
                    continue
                try:
                    out[symbol] = float(str(band).replace("%", "").strip())
                except (TypeError, ValueError):
                    continue
    except Exception as exc:
        warn(f"[MORNING] Could not read the price-band report: {exc}")
        return {}
    return out


def fetch_corporate_actions(known_symbols):
    """
    Symbols going ex-split / ex-bonus / ex-rights / ex-dividend TODAY.
    Their price scale changes overnight, so every %-move against
    yesterday's close is meaningless -- and would poison the gainers/
    losers table and the sector ranking if left on the feed.

    Fails open: empty set on any problem.
    """
    try:
        from core.corporate_actions import refresh
        from core.stock_memory import default_memory
        memory = default_memory()
        refresh(memory=memory, known_symbols=known_symbols)
        return set(memory.price_distorting_symbols())
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

    bhav_index = build_bhav_index(bhav_rows)
    excluded = fetch_excluded_symbols()
    bands = fetch_price_bands(bhav_date)
    actions = fetch_corporate_actions(known)

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

    rows, summary = apply(rows, bhav_index, excluded=excluded, bands=bands,
                          corporate_actions=actions,
                          min_turnover=MIN_TURNOVER_RS)
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
