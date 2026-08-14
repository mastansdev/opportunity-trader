"""
==========================================================
Which trailing stop would have been right?
==========================================================

    py tools/trail_sweep.py
    py tools/trail_sweep.py --date 2026-07-29

    "keep 2.5 % for now but my strong feeling is we close much before
     this number touched"                -- operator, 28 July 2026

He was right to be suspicious. Measured over 80 real trades:

    TRAILING_STOP    46 trades   actual -Rs 33,542
                                 held to close +Rs 13,782

WHAT THIS DOES
--------------
Replays every recorded trade against the real minute candles from its
own entry, under several different trailing-stop widths, and reports
what each one would have paid.

Every run uses the SAME entries. Only the exit rule changes, so the
comparison is clean -- entry selection is not being flattered or
blamed.

HOW A CANDLE IS READ
--------------------
Peak tracked on the candle HIGH, stop tested against the candle LOW.
Within one minute the order of high and low is unknowable, so the
pessimistic reading is used: if a candle both makes a new high AND
breaches the stop, the stop wins. That understates every wide trail
slightly, which is the safe direction -- it cannot manufacture a
result that favours loosening.

A hard stop from the entry price is applied underneath every variant,
because that is the operator's own rule and it is never removed.

WHAT IT CANNOT TELL YOU
-----------------------
Three sessions is a small sample, and all three were in one market
mood. A width that wins here has not been proven; it has been
measured. Anything adopted on this basis should be re-measured after
another week.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TRADES_DB = os.path.join("data", "trade_memory.db")
CANDLES_DB = os.path.join("data", "backtest_candles.db")

# Trail widths to try, as a fraction of the running peak.
WIDTHS = (0.015, 0.025, 0.035, 0.050, 0.075)

# The operator's hard stop, applied under every variant. Never removed.
HARD_STOP_PCT = 0.025


def load(date=None):
    conn = sqlite3.connect(TRADES_DB)
    conn.row_factory = sqlite3.Row
    sql = "select * from trade_memory where entry_time is not null"
    args = ()
    if date:
        sql += " and trade_date = ?"
        args = (date,)
    rows = [dict(r) for r in conn.execute(sql, args)]
    conn.close()
    return rows


def candles_for(date, symbol, from_time):
    conn = sqlite3.connect(CANDLES_DB)
    minute = from_time[:16].replace(" ", "T")
    rows = conn.execute(
        "select minute, h, l, c from candles where date = ? and symbol = ? "
        "and minute >= ? order by minute", (date, symbol, minute)).fetchall()
    conn.close()
    return rows


def simulate(trade, bars, width):
    """Returns (exit_price, why). Long side only -- the book is
    long-only since 27 July and the three recorded sessions contain no
    shorts worth modelling separately."""
    entry = trade["entry_price"]
    if not bars or not entry:
        return None, None

    hard_stop = entry * (1 - HARD_STOP_PCT)
    peak = entry
    trail = peak * (1 - width)

    for _minute, high, low, _close in bars:
        # Pessimistic ordering: test the stop BEFORE letting a new high
        # lift the trail. A minute that did both is scored as a stop.
        stop = max(trail, hard_stop)
        if low <= stop:
            return stop, ("hard stop" if stop == hard_stop else "trail")
        if high > peak:
            peak = high
            trail = peak * (1 - width)

    return bars[-1][3], "held to close"


def main():
    date = None
    if "--date" in sys.argv:
        i = sys.argv.index("--date")
        if i + 1 < len(sys.argv):
            date = sys.argv[i + 1]

    trades = [t for t in load(date)
              if (t["direction"] or "LONG") == "LONG"]
    if not trades:
        print("\n  No long trades on record.\n")
        return 1

    print("=" * 78)
    print("  WHICH TRAILING STOP WOULD HAVE BEEN RIGHT?")
    print("=" * 78)
    print(f"  {len(trades)} long trades replayed on their own real candles.")
    print(f"  Same entries every time -- only the exit rule changes.")
    print(f"  A {HARD_STOP_PCT * 100:.1f}% hard stop from entry sits under "
          f"every variant.")
    print()

    results = defaultdict(lambda: {"pnl": 0.0, "wins": 0, "n": 0,
                                   "why": defaultdict(int)})
    skipped = 0

    for trade in trades:
        bars = candles_for(trade["trade_date"], trade["symbol"],
                           trade["entry_time"])
        if not bars:
            skipped += 1
            continue
        qty = trade["qty"] or 0
        entry = trade["entry_price"]
        for width in WIDTHS:
            price, why = simulate(trade, bars, width)
            if price is None:
                continue
            pnl = (price - entry) * qty
            bucket = results[width]
            bucket["pnl"] += pnl
            bucket["n"] += 1
            bucket["wins"] += 1 if pnl > 0 else 0
            bucket["why"][why] += 1

    print(f"  {'trail width':<14}{'trades':>8}{'win rate':>11}"
          f"{'total P&L':>14}{'per trade':>12}")
    print("  " + "-" * 60)
    best = None
    for width in WIDTHS:
        b = results[width]
        if not b["n"]:
            continue
        per = b["pnl"] / b["n"]
        if best is None or b["pnl"] > results[best]["pnl"]:
            best = width
        print(f"  {width * 100:>10.1f}%  {b['n']:>8}"
              f"{b['wins'] / b['n'] * 100:>10.0f}%"
              f"{b['pnl']:>14,.0f}{per:>12,.0f}")

    actual = sum(t["pnl"] or 0 for t in trades)
    print("  " + "-" * 60)
    print(f"  {'what happened':<14}{len(trades):>8}"
          f"{sum(1 for t in trades if (t['pnl'] or 0) > 0) / len(trades) * 100:>10.0f}%"
          f"{actual:>14,.0f}{actual / len(trades):>12,.0f}")

    if skipped:
        print(f"\n  ({skipped} trade(s) had no candle history to replay)")

    print()
    print("  HOW EACH WIDTH ENDED ITS TRADES")
    print(f"  {'trail width':<14}{'trail hit':>12}{'hard stop':>12}"
          f"{'held to close':>16}")
    print("  " + "-" * 54)
    for width in WIDTHS:
        b = results[width]
        if not b["n"]:
            continue
        w = b["why"]
        print(f"  {width * 100:>10.1f}%  {w['trail']:>12}"
              f"{w['hard stop']:>12}{w['held to close']:>16}")

    print()
    if best is not None:
        print(f"  Widest total on this sample: {best * 100:.1f}%")
    print("  Three sessions in one market mood. This is a measurement,")
    print("  not a proof -- re-run it after another week before trusting")
    print("  the ranking.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
