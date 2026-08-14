"""
==========================================================
What did every exit actually cost?  --  the evidence, not the anecdote
==========================================================

    py tools/exit_review.py                # all recorded sessions
    py tools/exit_review.py --date 2026-07-29
    py tools/exit_review.py --detail       # one line per trade

    "kaynes throwed out us & rallied made 3685 rs high"
    "another one - EPACKPED - same returned profits"
    "pcbl throwed us out & moved 3%"
                                        -- operator, 29 July 2026

He named five stocks in two sessions where the bot exited and the
stock kept going. Five is a story. This is the count.

WHAT IT MEASURES
----------------
For every closed trade, it reads the minute candles AFTER the exit on
the same day and answers one question:

    What would simply HOLDING have paid?

    peak after exit   the best the trade could have made
    close of day      what patience alone would have returned
    +30 / +60 min     whether the move continued or died

Grouped by exit reason, so the trailing stop, the fixed stop, the
partial and the manual exits are each judged on their own record.

WHAT IT DOES NOT DO
-------------------
It does not change a setting. It produces the table, and the setting
is decided afterwards, together.

ONE HONEST LIMIT, STATED UP FRONT
---------------------------------
"Hold to close" is not a free alternative. It ignores the risk carried
in between -- a trade that ends the day +2% may have been -4% at some
point, and on MTF that is real. So the report also prints the WORST
point after exit, not just the best. A rule that only looks at the
upside is how people talk themselves into removing stop losses.

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


def load_trades(date=None):
    conn = sqlite3.connect(TRADES_DB)
    conn.row_factory = sqlite3.Row
    sql = "select * from trade_memory"
    args = ()
    if date:
        sql += " where trade_date = ?"
        args = (date,)
    sql += " order by trade_date, exit_time"
    rows = [dict(r) for r in conn.execute(sql, args)]
    conn.close()
    return rows


def load_candles(dates):
    """{(date, symbol): [(minute, high, low, close), ...]} sorted."""
    conn = sqlite3.connect(CANDLES_DB)
    out = defaultdict(list)
    marks = ",".join("?" * len(dates))
    for date, symbol, minute, h, l, c in conn.execute(
            f"select date, symbol, minute, h, l, c from candles "
            f"where date in ({marks}) order by symbol, minute", tuple(dates)):
        out[(date, symbol)].append((minute, h, l, c))
    conn.close()
    return out


def after_exit(candles, exit_time):
    """Only the candles strictly after the exit minute."""
    minute = exit_time[:16].replace(" ", "T")
    return [c for c in candles if c[0] > minute]


def review(trade, candles):
    """What holding would have done. None if there is no history left --
    an exit in the last minute of the day cannot be judged, and is
    reported as such rather than scored as break-even."""
    rest = after_exit(candles, trade["exit_time"] or "")
    if not rest:
        return None

    long_side = (trade["direction"] or "LONG") == "LONG"
    qty = trade["qty"] or 0
    entry = trade["entry_price"] or 0
    exit_price = trade["exit_price"] or 0

    best = max(c[1] for c in rest) if long_side else min(c[2] for c in rest)
    worst = min(c[2] for c in rest) if long_side else max(c[1] for c in rest)
    close = rest[-1][3]

    def pnl(price):
        return (price - entry) * qty if long_side else (entry - price) * qty

    return {
        "peak_after": best,
        "worst_after": worst,
        "close": close,
        "actual": trade["pnl"] or 0.0,
        "if_held_to_close": pnl(close),
        "if_held_to_peak": pnl(best),
        "if_held_to_worst": pnl(worst),
        "left_on_table": pnl(close) - (trade["pnl"] or 0.0),
        "move_after_pct": ((best - exit_price) / exit_price * 100
                           if exit_price else 0.0),
    }


def _rs(value):
    return f"{value:>12,.0f}"


def main():
    date = None
    if "--date" in sys.argv:
        i = sys.argv.index("--date")
        if i + 1 < len(sys.argv):
            date = sys.argv[i + 1]
    detail = "--detail" in sys.argv

    trades = load_trades(date)
    if not trades:
        print("\n  No trades on record for that date.\n")
        return 1
    dates = sorted({t["trade_date"] for t in trades})
    candles = load_candles(dates)

    print("=" * 78)
    print("  WHAT EVERY EXIT COST  --  measured against holding")
    print("=" * 78)
    print(f"  {len(trades)} closed trades across {len(dates)} session(s): "
          f"{', '.join(dates)}")

    by_reason = defaultdict(list)
    unjudgeable = 0
    for trade in trades:
        result = review(trade, candles.get(
            (trade["trade_date"], trade["symbol"]), []))
        if result is None:
            unjudgeable += 1
            continue
        by_reason[trade["exit_reason"] or "UNKNOWN"].append((trade, result))

    print()
    print(f"  {'exit reason':<24}{'n':>4}{'actual':>13}"
          f"{'held to close':>15}{'difference':>14}")
    print("  " + "-" * 70)

    grand = [0.0, 0.0]
    for reason, entries in sorted(by_reason.items(),
                                  key=lambda kv: -len(kv[1])):
        actual = sum(r["actual"] for _, r in entries)
        held = sum(r["if_held_to_close"] for _, r in entries)
        grand[0] += actual
        grand[1] += held
        print(f"  {reason:<24}{len(entries):>4}{_rs(actual)}"
              f"{_rs(held)}{_rs(held - actual):>14}")
    print("  " + "-" * 70)
    print(f"  {'TOTAL':<24}{sum(len(v) for v in by_reason.values()):>4}"
          f"{_rs(grand[0])}{_rs(grand[1])}{_rs(grand[1] - grand[0]):>14}")
    if unjudgeable:
        print(f"\n  ({unjudgeable} trade(s) exited too late in the day to "
              f"judge -- no candles left after the exit)")

    # ---------------------------------------------------------
    # The honest other half: what holding would have RISKED.
    # ---------------------------------------------------------
    print()
    print("  THE RISK HOLDING WOULD HAVE CARRIED")
    print("  A rule judged only on its upside is how people talk")
    print("  themselves out of stop losses.")
    print()
    print(f"  {'exit reason':<24}{'n':>4}{'best case':>14}{'worst case':>14}")
    print("  " + "-" * 56)
    for reason, entries in sorted(by_reason.items(),
                                  key=lambda kv: -len(kv[1])):
        best = sum(r["if_held_to_peak"] for _, r in entries)
        worst = sum(r["if_held_to_worst"] for _, r in entries)
        print(f"  {reason:<24}{len(entries):>4}{_rs(best)}{_rs(worst)}")

    # ---------------------------------------------------------
    # How often did the stock keep going?
    # ---------------------------------------------------------
    print()
    print("  DID THE STOCK KEEP GOING AFTER WE LEFT?")
    print(f"  {'exit reason':<24}{'n':>4}{'kept going':>12}"
          f"{'median move':>14}")
    print("  " + "-" * 56)
    for reason, entries in sorted(by_reason.items(),
                                  key=lambda kv: -len(kv[1])):
        moves = sorted(r["move_after_pct"] for _, r in entries)
        kept = sum(1 for m in moves if m >= 1.0)
        median = moves[len(moves) // 2] if moves else 0.0
        print(f"  {reason:<24}{len(entries):>4}"
              f"{kept / len(moves) * 100:>11.0f}%{median:>13.2f}%")
    print()
    print("  'kept going' = the stock ran another 1% or more in our")
    print("  direction after the exit. 'median move' is the middle case.")

    # ---------------------------------------------------------
    # The worst individual give-backs
    # ---------------------------------------------------------
    print()
    print("  THE TEN WORST GIVE-BACKS")
    print(f"  {'symbol':<13}{'date':<12}{'reason':<20}"
          f"{'actual':>10}{'held':>10}{'lost':>10}")
    print("  " + "-" * 74)
    flat = [(t, r) for entries in by_reason.values() for t, r in entries]
    flat.sort(key=lambda tr: -tr[1]["left_on_table"])
    for trade, result in flat[:10]:
        print(f"  {trade['symbol']:<13}{trade['trade_date']:<12}"
              f"{(trade['exit_reason'] or '')[:19]:<20}"
              f"{result['actual']:>10,.0f}{result['if_held_to_close']:>10,.0f}"
              f"{result['left_on_table']:>10,.0f}")

    if detail:
        print()
        print("  EVERY TRADE")
        print(f"  {'symbol':<13}{'date':<12}{'reason':<20}{'exit':>10}"
              f"{'peak after':>12}{'close':>10}{'lost':>10}")
        print("  " + "-" * 88)
        for trade, result in flat:
            print(f"  {trade['symbol']:<13}{trade['trade_date']:<12}"
                  f"{(trade['exit_reason'] or '')[:19]:<20}"
                  f"{trade['exit_price']:>10,.2f}{result['peak_after']:>12,.2f}"
                  f"{result['close']:>10,.2f}{result['left_on_table']:>10,.0f}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
