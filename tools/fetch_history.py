"""
==========================================================
Fetch History -- fill the replay bench with real market
==========================================================

    py tools/fetch_history.py                 # 62 sessions, 1-min + daily
    py tools/fetch_history.py --days 250      # a year
    py tools/fetch_history.py --daily-only    # daily bars only (fast)
    py tools/fetch_history.py --days 30 --symbols PARAS KALYANKJIL
    py tools/fetch_history.py --check         # what's already stored

WHY
---
backtest/monday_replay.py already runs the bot's REAL rules -- top-20
movers, top-8 sectors, RS band, staged seats, rotation, ATR stops,
charges. It is not missing logic. It is missing MARKET: one recorded
session, and that one restart-muddied.

This fills it from Dhan, which serves 1-minute candles five years back
for every active instrument. After a run:

    py backtest/monday_replay.py     # 62 sessions instead of 1

WHAT IT WRITES
--------------
    data/history_candles.db   1-minute bars   (backtest/candle_store.py)
    data/daily_candles.db     daily bars      (core/daily_store.py)

The intraday file is DELIBERATELY separate from the live recorder's
data/backtest_candles.db. Two reasons: a 12-million-row historical pull
should not sit in the same file the live bot writes to during a session,
and if the split check below turns up bad data we can delete this file
without touching anything the bot recorded itself.

The daily bars DO go to the normal store, because that is what
core/trend_structure.py reads and more history there is strictly better.
Dedup is ON CONFLICT DO NOTHING, so bhavcopy-sourced bars already stored
win and are never overwritten.

COST
----
Dhan's Data API allows 5 requests/second and 100,000/day; the intraday
endpoint caps a request at 90 days. So one request per symbol covers ~62
trading days:

    62 sessions x 545 symbols  =    545 requests   ~2 min
     1 year     x 545 symbols  =  2,725 requests   ~10 min
     5 years    x 545 symbols  = 13,600 requests   ~45 min

RESUMABLE. Dedup is on (date, symbol, minute), so a re-run after a
network drop costs time and nothing else.

READ THE SPLIT WARNING AT THE END OF THE RUN
--------------------------------------------
It is not documented whether Dhan's historical candles are adjusted for
splits and bonuses. If they are not, a 1:10 split reads as a -90% bar
and invents an ORB gap that never happened. Every suspect jump is
printed and cross-checked against core/stock_memory.py's recorded
corporate actions. Do not trust a backtest over a window with unexplained
flags in it.

Author : H&M Opportunity Trader
==========================================================
"""

import argparse
import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.candle_store import CandleStore  # noqa: E402
from config import DHAN_ACCESS_TOKEN, DHAN_CLIENT_ID  # noqa: E402
from core.daily_store import DailyStore  # noqa: E402
from core.history_fetch import (  # noqa: E402
    HistoryFetcher, suspect_price_jumps,
)
from core.logger import decision, warn  # noqa: E402
from core.master_loader import MasterLoader  # noqa: E402

HISTORY_DB = "sqlite:///data/history_candles.db"

# Calendar days to ask for, given roughly 5 trading days a week. 90
# calendar days is the API ceiling and buys ~62 sessions.
CALENDAR_PER_TRADING_DAY = 1.45



def _live_token():
    """The token main.py ACTUALLY uses, not the one sitting in .env.

    ---- THE STORE STOPPED FILLING ON 31 JULY. 19 Aug 2026. ----

        "next build - complete the missing history_candles.db - fix it
         completely"

    Two faults, and this is the second. main.py has not used
    DHAN_ACCESS_TOKEN as its first choice since core/dhan_auth.py
    arrived -- it mints over TOTP and caches in data/dhan_token.json:

        dhan_token = dhan_auth.access_token() or DHAN_ACCESS_TOKEN

    So this command, run today with a long-dead value in .env, would
    have returned DH-901 Invalid_Authentication and looked like a
    broken account. tools/dhan_funds_probe.py and
    tools/dhan_account_check.py carried the identical bug and were
    fixed on 18 August; this is the third and last caller.

    access_token() reads the cache and mints only when it must.
    """
    try:
        from core import dhan_auth
        return dhan_auth.access_token() or DHAN_ACCESS_TOKEN
    except Exception:                                       # noqa: BLE001
        return DHAN_ACCESS_TOKEN


def make_post(timeout=60):
    """A requests-backed POST with Dhan's auth headers. Kept behind a
    factory so core/history_fetch.py stays importable (and testable)
    with no network and no credentials."""
    import requests

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "access-token": _live_token(),
        "client-id": DHAN_CLIENT_ID,
    }

    def post(url, body):
        resp = requests.post(url, json=body, headers=headers,
                             timeout=timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:180]}")
        return resp.json()

    return post


def show_state(candles, daily):
    c_dates = candles.dates()
    d = daily.stats()
    decision("=" * 62)
    decision("  WHAT IS STORED")
    decision("=" * 62)
    decision(f"  1-minute bars : {candles.count():>12,}  "
             f"{len(c_dates)} session(s)"
             + (f"  {c_dates[0]} -> {c_dates[-1]}" if c_dates else ""))
    decision(f"  daily bars    : {d['bars']:>12,}  "
             f"{d['days']} day(s), {d['symbols']} symbols"
             + (f"  {d['first']} -> {d['last']}" if d['first'] else ""))
    return 0


def run(days=62, symbols=None, daily_only=False, intraday_only=False,
        post=None, candles=None, daily=None, loader=None, interval="1"):
    candles = candles if candles is not None else CandleStore(url=HISTORY_DB)
    daily = daily if daily is not None else DailyStore()

    if loader is None:
        loader = MasterLoader()
        loader.load()

    if not symbols:
        symbols = loader.all_symbols()          # SUBSCRIBE = YES only

    if not symbols:
        warn("No symbols. Run py tools/morning_universe.py first.")
        return 1

    to_date = date.today()
    from_date = to_date - timedelta(
        days=int(days * CALENDAR_PER_TRADING_DAY))

    fetcher = HistoryFetcher(post or make_post())

    decision("=" * 62)
    decision(f"  FETCHING HISTORY  {from_date} -> {to_date}")
    decision("=" * 62)
    decision(f"  symbols        : {len(symbols)}")
    decision(f"  target         : ~{days} trading sessions")
    decision(f"  writing 1-min  : {'no' if daily_only else HISTORY_DB}")
    decision(f"  writing daily  : {'no' if intraday_only else 'daily_candles.db'}")
    decision("-" * 62)

    started = time.time()
    total_min, total_day, no_data = 0, 0, []
    all_daily_rows = []

    for i, symbol in enumerate(symbols, start=1):
        security_id = loader.security_id(symbol)
        if not security_id:
            no_data.append(symbol)
            continue

        if not daily_only:
            rows = fetcher.intraday(security_id, symbol, from_date,
                                    to_date, interval=interval)
            if rows:
                total_min += candles.add_many(rows)
            else:
                no_data.append(symbol)

        if not intraday_only:
            rows = fetcher.daily(security_id, symbol, from_date, to_date)
            if rows:
                all_daily_rows.extend(rows)
                total_day += daily.upsert_many(rows)

        if i % 25 == 0 or i == len(symbols):
            elapsed = time.time() - started
            rate = i / elapsed if elapsed else 0
            left = (len(symbols) - i) / rate if rate else 0
            decision(f"  {i:>4}/{len(symbols)}  "
                     f"{total_min:>10,} min-bars  "
                     f"{total_day:>7,} daily  "
                     f"{fetcher.requests_made:>5} reqs  "
                     f"~{left/60:.1f} min left")

    elapsed = time.time() - started
    decision("-" * 62)
    decision(f"  DONE in {elapsed/60:.1f} min")
    decision(f"  1-minute bars written : {total_min:,}")
    decision(f"  daily bars written    : {total_day:,}")
    decision(f"  API requests used     : {fetcher.requests_made:,} "
             f"of 100,000/day")

    sessions = candles.dates()
    if sessions:
        decision(f"  sessions now stored   : {len(sessions)}  "
                 f"({sessions[0]} -> {sessions[-1]})")

    if no_data:
        warn(f"  No data for {len(no_data)} symbol(s): "
             + ", ".join(no_data[:15])
             + (" ..." if len(no_data) > 15 else ""))
    if fetcher.failures:
        warn(f"  {len(fetcher.failures)} request(s) failed after retries. "
             f"Re-run to fill the gaps -- dedup makes that safe.")

    _report_splits(all_daily_rows)

    decision("-" * 62)
    decision("  Next:  py backtest/monday_replay.py")
    return 0


def _days_between(a, b):
    """Signed day difference between two YYYY-MM-DD strings, or a big
    number if either is unparseable (so it never matches)."""
    try:
        return (date.fromisoformat(a) - date.fromisoformat(b)).days
    except (TypeError, ValueError):
        return 10 ** 6


def _report_splits(daily_rows, threshold=25.0):
    """The check that decides whether any of this data can be believed."""
    if not daily_rows:
        return
    flagged = suspect_price_jumps(daily_rows, threshold_pct=threshold)
    if not flagged:
        decision(f"  Split check: no day-on-day close move over "
                 f"{threshold:.0f}%. Data looks adjusted.")
        return

    known = {}
    try:
        from core.stock_memory import StockMemory
        memory = StockMemory()
        cache = {}
        for f in flagged:
            if f["symbol"] not in cache:
                cache[f["symbol"]] = memory.history_for(f["symbol"]) or []
            for a in cache[f["symbol"]]:
                # ex_date is when the price rescales. Allow a one-day
                # window either side: the exchange's ex-date and the
                # session the gap actually prints in are often adjacent.
                ex = str(a.get("ex_date") or "")[:10]
                if ex and abs(_days_between(ex, f["date"])) <= 1:
                    known[(f["symbol"], f["date"])] = a.get("action_type")
                    break
    except Exception as exc:                    # noqa: BLE001 -- advisory
        warn(f"  (could not cross-check stock memory: {exc})")

    unexplained = [f for f in flagged
                   if (f["symbol"], f["date"]) not in known]

    warn("")
    warn(f"  SPLIT CHECK: {len(flagged)} day-on-day close move(s) over "
         f"{threshold:.0f}% -- almost always an UNADJUSTED corporate "
         f"action, not a real move.")
    for f in flagged[:15]:
        tag = known.get((f["symbol"], f["date"]))
        warn(f"      {f['symbol']:<14} {f['date']}  "
             f"{f['prev_close']:>9.2f} -> {f['close']:<9.2f} "
             f"{f['pct']:>+7.1f}%   "
             + (f"[known {tag}]" if tag else "[UNEXPLAINED]"))
    if unexplained:
        warn(f"  {len(unexplained)} are UNEXPLAINED by recorded corporate "
             f"actions. Do NOT trust a backtest over these windows until "
             f"you know what they were.")


def main():
    p = argparse.ArgumentParser(
        description="Pull historical candles from Dhan into the replay "
                    "bench.")
    p.add_argument("--days", type=int, default=62,
                   help="approximate trading sessions to fetch "
                        "(default 62 = one API request per symbol)")
    p.add_argument("--symbols", nargs="*", default=None,
                   help="specific symbols instead of the whole "
                        "SUBSCRIBE=YES universe")
    p.add_argument("--daily-only", action="store_true",
                   help="daily bars only -- fast, feeds trend structure")
    p.add_argument("--intraday-only", action="store_true",
                   help="1-minute bars only")
    p.add_argument("--interval", default="1",
                   choices=["1", "5", "15", "25", "60"],
                   help="candle size in minutes (default 1)")
    p.add_argument("--check", action="store_true",
                   help="show what's already stored and exit")
    args = p.parse_args()

    if args.check:
        return show_state(CandleStore(url=HISTORY_DB), DailyStore())

    if not DHAN_CLIENT_ID or not _live_token():
        warn("DHAN_CLIENT_ID / no usable access token. This command "
             "needs the same credentials main.py uses -- check with "
             "py tools/dhan_account_check.py")
        return 1

    return run(days=args.days,
               symbols=[s.upper() for s in args.symbols]
               if args.symbols else None,
               daily_only=args.daily_only,
               intraday_only=args.intraday_only,
               interval=args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
