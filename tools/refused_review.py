"""
==========================================================
Did the setups we REFUSED do better than the ones we TOOK?
==========================================================

    py tools/refused_review.py
    py tools/refused_review.py --date 2026-07-30
    py tools/refused_review.py --detail

    "real movers are ignored by bot. as first see = buy & 10 slots
     filled."                            -- operator, 29 July 2026

For six months this question had no answer, because core/breakout_feed
holds signals in memory and the process exits at 15:30. Every refused
setup was deleted daily.

From 29 July core/signal_journal.py writes them to disk. This reads
them back, joins each one against the minute candles that followed,
and reports what the refusals were worth.

WHAT IT ANSWERS
---------------
    1. What did refused breakouts do afterwards, versus taken ones?
    2. Which refusal reason costs the most?
    3. Do the operator's three confirmations -- good results, volume,
       news -- actually separate winners from losers?

Question 3 is the one that matters most, and it needs about two weeks
of sessions before the counts mean anything. Until then this prints
the sample size honestly and refuses to draw a conclusion from four
rows.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

JOURNAL_DB = os.path.join("data", "signal_journal.db")
CANDLES_DB = os.path.join("data", "backtest_candles.db")

# Below this many rows in a bucket, no conclusion is offered. Two data
# points produced a very confident wrong answer on 29 July; this is the
# guard against repeating that.
MIN_SAMPLE = 10


def load_signals(date=None):
    if not os.path.exists(JOURNAL_DB):
        return []
    conn = sqlite3.connect(JOURNAL_DB)
    conn.row_factory = sqlite3.Row
    sql = "select * from signals"
    args = ()
    if date:
        sql += " where trade_date = ?"
        args = (date,)
    rows = [dict(r) for r in conn.execute(sql, args)]
    conn.close()
    return rows


def outcome(signal):
    """What the stock did in the rest of the session after the signal.

    Returns the best move as a percentage of the break price, or None
    when there is no history left to judge -- a signal in the closing
    minutes is not scored as flat, it is left out.
    """
    if not signal.get("break_price") or not signal.get("first_seen"):
        return None
    conn = sqlite3.connect(CANDLES_DB)
    minute = signal["first_seen"][:16].replace(" ", "T")
    rows = conn.execute(
        "select max(h), min(l) from candles where date = ? and symbol = ? "
        "and minute > ?",
        (signal["trade_date"], signal["symbol"], minute)).fetchone()
    conn.close()
    if not rows or rows[0] is None:
        return None
    high, low = rows
    price = signal["break_price"]
    if (signal["direction"] or "LONG") == "LONG":
        return {"best": (high - price) / price * 100,
                "worst": (low - price) / price * 100}
    return {"best": (price - low) / price * 100,
            "worst": (price - high) / price * 100}


def summarise(name, groups):
    print(f"\n  {name}")
    print(f"    {'bucket':<30}{'n':>5}{'ran 1%+':>10}{'median best':>14}"
          f"{'median worst':>14}")
    print("    " + "-" * 71)
    for key, moves in sorted(groups.items(),
                             key=lambda kv: -len(kv[1])):
        if not moves:
            continue
        best = sorted(m["best"] for m in moves)
        worst = sorted(m["worst"] for m in moves)
        ran = sum(1 for b in best if b >= 1.0) / len(best) * 100
        mark = "" if len(moves) >= MIN_SAMPLE else "   (too few to read)"
        print(f"    {str(key)[:29]:<30}{len(moves):>5}{ran:>9.0f}%"
              f"{best[len(best) // 2]:>13.2f}%"
              f"{worst[len(worst) // 2]:>13.2f}%{mark}")


def main():
    date = None
    if "--date" in sys.argv:
        i = sys.argv.index("--date")
        if i + 1 < len(sys.argv):
            date = sys.argv[i + 1]
    detail = "--detail" in sys.argv

    signals = load_signals(date)
    print("=" * 78)
    print("  TAKEN vs REFUSED  --  what the signals did afterwards")
    print("=" * 78)

    if not signals:
        print("\n  The journal is empty.")
        print("  It starts filling from the next session -- every")
        print("  structural signal, taken and refused, is written to")
        print("  data/signal_journal.db as it happens.\n")
        return 0

    dates = sorted({s["trade_date"] for s in signals})
    print(f"  {len(signals)} signals across {len(dates)} session(s): "
          f"{', '.join(dates)}")

    scored = []
    unjudgeable = 0
    for signal in signals:
        move = outcome(signal)
        if move is None:
            unjudgeable += 1
            continue
        scored.append((signal, move))

    if not scored:
        print("\n  Nothing could be scored yet -- no candle history "
              "after these signals.\n")
        return 0

    taken = defaultdict(list)
    for signal, move in scored:
        taken["TAKEN" if signal["taken"] else "REFUSED"].append(move)
    summarise("TAKEN vs REFUSED", taken)

    refusals = defaultdict(list)
    for signal, move in scored:
        if not signal["taken"]:
            refusals[(signal["refused_why"] or "unknown")[:29]].append(move)
    if refusals:
        summarise("WHY IT WAS REFUSED", refusals)

    confirmed = defaultdict(list)
    for signal, move in scored:
        confirmed[f"{signal.get('confirmations') or 0} of 3"].append(move)
    summarise("THE OPERATOR'S THREE CONFIRMATIONS", confirmed)

    news = defaultdict(list)
    for signal, move in scored:
        label = "news or filing" if (signal.get("news_kind")
                                     or signal.get("filing_kind")) else "nothing"
        news[label].append(move)
    summarise("NEWS PRESENT?", news)

    grades = defaultdict(list)
    for signal, move in scored:
        grades[signal.get("results_grade") or "no grade"].append(move)
    summarise("RESULTS GRADE", grades)

    volume = defaultdict(list)
    for signal, move in scored:
        mult = signal.get("volume_mult")
        if mult is None:
            label = "not measurable"
        elif mult >= 3:
            label = "3x or more"
        elif mult >= 1.5:
            label = "1.5x - 3x"
        else:
            label = "under 1.5x"
        volume[label].append(move)
    summarise("VOLUME ON THE BREAKOUT", volume)

    attempts = defaultdict(list)
    for signal, move in scored:
        attempts[f"attempt {signal.get('attempt') or 1}"].append(move)
    summarise("WHICH ATTEMPT AT THE LEVEL", attempts)

    if unjudgeable:
        print(f"\n  ({unjudgeable} signal(s) fired too late in the day "
              f"to score)")

    if detail:
        print()
        print("  EVERY REFUSED SIGNAL, WORST FIRST")
        print(f"    {'symbol':<13}{'date':<12}{'best after':>11}"
              f"{'conf':>6}  why")
        print("    " + "-" * 70)
        rows = [(s, m) for s, m in scored if not s["taken"]]
        rows.sort(key=lambda sm: -sm[1]["best"])
        for signal, move in rows[:40]:
            print(f"    {signal['symbol']:<13}{signal['trade_date']:<12}"
                  f"{move['best']:>10.2f}%{signal.get('confirmations') or 0:>6}"
                  f"  {(signal['refused_why'] or '')[:32]}")

    print()
    print(f"  Buckets with fewer than {MIN_SAMPLE} rows are marked and")
    print("  should not be read as a result. On 29 July a two-row bucket")
    print("  looked like a clear signal and would have cut the bot to one")
    print("  trade a week. Give this two weeks before changing a rule.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
