"""
==========================================================
Structure Performance -- does the daily trend predict anything?
==========================================================

    py tools/structure_performance.py
    py tools/structure_performance.py --min 5      # only buckets with 5+
    py tools/structure_performance.py --since 2026-07-01

THE QUESTION THIS EXISTS TO SETTLE
----------------------------------
POST_MONDAY_TODO H1: "5 clean sessions, then bucket win rate by the
structure label the stock had that morning. If STRONG_UP longs beat
RANGE longs, wire it as a gate -- one line. If not, delete the module."

That plan had a hole in it. core/trend_structure.py's own docstring
claimed the label was "recorded against every trade the bot takes" --
and it was not. Nothing imported the module except tools/trend_report.py.
Five sessions from now there would have been nothing to bucket.

This closes the hole WITHOUT touching core/engine.py, because the label
does not need to be recorded live: it is a pure function of daily bars
we already store. Given a trade on 2026-07-24 in PARAS, the structure
the bot would have seen at 09:15 that morning is exactly
analyse(daily_store.history("PARAS", days=8, upto="2026-07-23")).

THE upto CUTOFF IS THE WHOLE POINT
-----------------------------------
`upto` is the day BEFORE the trade. Include the trade day itself and
the label is computed from a bar that had not finished forming when the
entry was taken -- the structure would "know" how the day ended. That is
lookahead bias, it always flatters the result, and it is the single
easiest way to talk yourself into a rule that does not work.

WHAT IT REPORTS
---------------
Win rate and expectancy grouped three ways:

  by STRUCTURE      does STRONG_UP beat RANGE?
  by DIRECTION x STRUCTURE   do LONGS in uptrends beat LONGS in
                             downtrends? (the actual gating question)
  by ALIGNMENT      trades WITH the daily trend vs AGAINST it -- the
                    continuation-vs-mean-reversion question from
                    POST_MONDAY_TODO H2, asked on the daily timeframe

R is approximated as pnl / RISK_PER_TRADE_RS. That is what the
risk-based sizing is built to make true (qty = risk / stop_distance),
but MAX_NOTIONAL_PER_TRADE_RS can cap a tight-stop trade below full
risk, so treat R here as close-but-not-exact.

READ THE SAMPLE SIZE COLUMN BEFORE READING ANYTHING ELSE. Four trades
in a bucket is not a finding. This tool prints n first, deliberately.

Author : H&M Opportunity Trader
==========================================================
"""

import argparse
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import RISK_PER_TRADE_RS  # noqa: E402
from core.daily_store import DailyStore  # noqa: E402
from core.logger import decision, warn  # noqa: E402
from core.trade_memory import TradeMemory  # noqa: E402
from core.trend_structure import analyse  # noqa: E402

WINDOW_DAYS = 8
UP = ("STRONG_UP", "UPTREND")
DOWN = ("STRONG_DOWN", "DOWNTREND")
STRUCTURE_ORDER = ["STRONG_UP", "UPTREND", "RANGE", "DOWNTREND",
                   "STRONG_DOWN"]


def previous_day(trade_date):
    """The calendar day before a trade. `history(upto=...)` filters on
    <=, and DailyStore only holds trading days, so a plain -1 day is
    enough -- a weekend or holiday simply has no rows to exclude."""
    try:
        return (date.fromisoformat(str(trade_date)[:10])
                - timedelta(days=1)).isoformat()
    except (TypeError, ValueError):
        return None


def label_for(store, symbol, trade_date, window=WINDOW_DAYS):
    """
    The structure this stock had on the MORNING of trade_date, using
    only bars that had closed before it. Returns None when there isn't
    enough history -- never a guess.
    """
    upto = previous_day(trade_date)
    if not upto:
        return None
    bars = store.history(symbol, days=window, upto=upto)
    result = analyse(bars)
    if result.get("structure") in (None, "UNKNOWN"):
        return None
    return result


def alignment_of(direction, structure):
    if structure in UP:
        return "WITH_TREND" if direction == "LONG" else "AGAINST_TREND"
    if structure in DOWN:
        return "WITH_TREND" if direction == "SHORT" else "AGAINST_TREND"
    return "RANGE"


def bucket(trades, key_fn):
    """{key: {n, wins, win_rate, total_pnl, avg_pnl, avg_r}}"""
    out = {}
    for t in trades:
        key = key_fn(t)
        if key is None:
            continue
        rec = out.setdefault(key, dict(n=0, wins=0, total_pnl=0.0))
        rec["n"] += 1
        pnl = t.get("pnl") or 0.0
        rec["total_pnl"] += pnl
        if pnl > 0:
            rec["wins"] += 1
    for rec in out.values():
        rec["win_rate"] = 100.0 * rec["wins"] / rec["n"] if rec["n"] else 0.0
        rec["avg_pnl"] = rec["total_pnl"] / rec["n"] if rec["n"] else 0.0
        rec["avg_r"] = (rec["avg_pnl"] / RISK_PER_TRADE_RS
                        if RISK_PER_TRADE_RS else 0.0)
    return out


def _print_table(title, buckets, min_trades, order=None):
    decision("")
    decision("-" * 68)
    decision(f"  {title}")
    decision("-" * 68)
    keys = order or sorted(buckets, key=lambda k: -buckets[k]["n"])
    shown = 0
    decision(f"  {'bucket':<26}{'n':>5}{'win%':>8}{'avg Rs':>10}"
             f"{'avg R':>8}{'total':>11}")
    for key in keys:
        rec = buckets.get(key)
        if not rec or rec["n"] < min_trades:
            continue
        shown += 1
        decision(f"  {str(key):<26}{rec['n']:>5}{rec['win_rate']:>7.1f}%"
                 f"{rec['avg_pnl']:>10.0f}{rec['avg_r']:>8.2f}"
                 f"{rec['total_pnl']:>11.0f}")
    thin = [k for k in keys
            if buckets.get(k) and buckets[k]["n"] < min_trades]
    if thin:
        decision(f"  ({len(thin)} bucket(s) below {min_trades} trades "
                 f"hidden: {', '.join(str(k) for k in thin[:6])})")
    if not shown:
        warn(f"  Nothing has {min_trades}+ trades yet.")


def run(min_trades=3, since=None, memory=None, store=None):
    memory = memory or TradeMemory()
    store = store or DailyStore()

    trades = memory.all_trades(since=since)
    if not trades:
        warn("No trades in memory yet. Run some sessions first.")
        return 1

    stats = store.stats()
    if stats.get("days", 0) < 3:
        warn(f"Only {stats.get('days', 0)} day(s) of daily history. "
             f"Run: py tools/build_daily_history.py 30")
        return 1

    labelled, unlabelled = [], 0
    for t in trades:
        result = label_for(store, t.get("symbol"), t.get("trade_date"))
        if result is None:
            unlabelled += 1
            continue
        t = dict(t)
        t["structure"] = result["structure"]
        t["broke"] = result.get("broke_structure")
        t["alignment"] = alignment_of(t.get("direction"), t["structure"])
        labelled.append(t)

    decision("=" * 68)
    decision("  DOES THE DAILY STRUCTURE PREDICT ANYTHING?")
    decision("=" * 68)
    decision(f"  trades in memory        : {len(trades)}")
    decision(f"  with a usable structure : {len(labelled)}")
    if unlabelled:
        decision(f"  skipped (no history before the trade): {unlabelled}")
    decision(f"  daily history           : {stats['days']} days "
             f"({stats['first']} -> {stats['last']})")
    decision(f"  R approximated as pnl / Rs {RISK_PER_TRADE_RS:.0f}")

    if not labelled:
        warn("")
        warn("  No trade could be labelled. That usually means the daily "
             "history does not reach back before the trades. Run: "
             "py tools/build_daily_history.py 60")
        return 1

    _print_table("BY STRUCTURE -- does STRONG_UP beat RANGE?",
                 bucket(labelled, lambda t: t["structure"]),
                 min_trades, order=STRUCTURE_ORDER)

    _print_table("BY DIRECTION x STRUCTURE -- the actual gating question",
                 bucket(labelled,
                        lambda t: f"{t.get('direction')} in {t['structure']}"),
                 min_trades)

    _print_table("BY ALIGNMENT -- ride the daily trend, or fade it?",
                 bucket(labelled, lambda t: t["alignment"]),
                 min_trades,
                 order=["WITH_TREND", "AGAINST_TREND", "RANGE"])

    _print_table("AFTER A BREAK OF STRUCTURE",
                 bucket(labelled,
                        lambda t: f"broke {t['broke']}" if t["broke"]
                        else None),
                 min_trades)

    _verdict(labelled, min_trades)
    return 0


def _verdict(labelled, min_trades):
    """State what the numbers do and do not support -- and refuse to
    conclude anything from a thin sample, which is the failure mode
    this whole file exists to avoid."""
    by_align = bucket(labelled, lambda t: t["alignment"])
    with_t = by_align.get("WITH_TREND")
    against = by_align.get("AGAINST_TREND")

    decision("")
    decision("=" * 68)
    decision("  WHAT THIS DOES AND DOES NOT SUPPORT")
    decision("=" * 68)

    if not with_t or not against or min(with_t["n"], against["n"]) < 20:
        n_with = with_t["n"] if with_t else 0
        n_against = against["n"] if against else 0
        warn(f"  NOT ENOUGH DATA. {n_with} with-trend / {n_against} "
             f"against-trend.")
        warn("  Nothing here should change a single config value yet. "
             "20+ on BOTH sides, across sessions of mixed character, "
             "before this means anything.")
        decision("  Get there faster: py tools/fetch_history.py "
                 "then py backtest/monday_replay.py")
        return

    gap = with_t["avg_r"] - against["avg_r"]
    decision(f"  with-trend    {with_t['n']:>4} trades  "
             f"{with_t['win_rate']:.1f}% win  {with_t['avg_r']:+.2f}R")
    decision(f"  against-trend {against['n']:>4} trades  "
             f"{against['win_rate']:.1f}% win  {against['avg_r']:+.2f}R")
    decision(f"  difference    {gap:+.2f}R per trade")

    if abs(gap) < 0.10:
        decision("  -> No meaningful difference. The daily structure is "
                 "not earning its place as a gate.")
    elif gap > 0:
        decision("  -> Trading WITH the daily trend looks better. A gate "
                 "is now arguable -- test it on recorded sessions "
                 "(backtest/monday_replay.py) before changing config.")
    else:
        decision("  -> Trading AGAINST the daily trend looks better, i.e. "
                 "mean reversion. That matches 2026-07-24 and would mean "
                 "the bot is currently pointed the wrong way. See "
                 "POST_MONDAY_TODO H2.")
    decision("  Either way: change ONE thing, then re-measure.")


def main():
    p = argparse.ArgumentParser(
        description="Bucket trade performance by the daily trend "
                    "structure the stock had that morning.")
    p.add_argument("--min", type=int, default=3, dest="min_trades",
                   help="hide buckets with fewer than N trades "
                        "(default 3)")
    p.add_argument("--since", default=None,
                   help="only trades on/after this YYYY-MM-DD")
    args = p.parse_args()
    return run(min_trades=args.min_trades, since=args.since)


if __name__ == "__main__":
    raise SystemExit(main())
