"""
==========================================================
Nightly review -- did the reason make any difference?
==========================================================

    py tools/reason_review.py

Reads trade_memory and answers, in plain English, the one question this
whole project turns on:

    "no info why gaining = no entry at all"   -- operator, 2026-07-28

Are trades taken WITH a reason better than trades taken without? And if
so, which reasons?

HOW MANY TRADES BEFORE THIS MEANS ANYTHING
------------------------------------------
Two-proportion test, 80% power, 5% significance, assuming a 45%
baseline win rate:

    if "with reason" wins at    gap     trades needed per group
                         70%   25pp                  63
                         65%   20pp                  99
                         60%   15pp                 176
                         55%   10pp                 396

At ~7 trades per group per day that is 9 sessions for a large effect and
25 for a modest one. Below those counts this report prints the numbers
but refuses to call them a finding -- a handful of samples looks like a
pattern long before it is one, which has already caught this project out
three times.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.trade_memory import TradeMemory                  # noqa: E402

# Enough per group before a difference is called real rather than noise.
CONFIDENT_N = 63
SUGGESTIVE_N = 25


def _stats(rows):
    n = len(rows)
    if not n:
        return dict(n=0, wins=0, win_rate=0.0, total=0.0, avg=0.0,
                    avg_win=0.0, avg_loss=0.0, payoff=0.0)
    pnls = [r["pnl"] or 0.0 for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    return dict(
        n=n, wins=len(wins), win_rate=len(wins) / n * 100,
        total=sum(pnls), avg=sum(pnls) / n,
        avg_win=avg_win, avg_loss=avg_loss,
        payoff=(avg_win / avg_loss) if avg_loss else 0.0,
    )


def _line(label, s):
    return (f"  {label:26} {s['n']:>5} {s['win_rate']:>7.1f}% "
            f"{s['avg']:>10,.0f} {s['total']:>12,.0f} {s['payoff']:>8.2f}")


def _verdict(a, b):
    """a = with reason, b = without. Deliberately hard to satisfy."""
    smaller = min(a["n"], b["n"])
    if smaller == 0:
        return ("NOT ENOUGH DATA -- one of the two groups is empty. "
                "Nothing to compare yet.")
    gap = a["avg"] - b["avg"]
    if smaller < SUGGESTIVE_N:
        return (f"TOO EARLY. Smallest group has {smaller} trades; {SUGGESTIVE_N} "
                f"is the point where a large effect would start to show, "
                f"{CONFIDENT_N} before it can be called real. The gap of "
                f"Rs {gap:,.0f} a trade means nothing yet.")
    if smaller < CONFIDENT_N:
        return (f"SUGGESTIVE, NOT PROVEN. {smaller} trades in the smaller "
                f"group. Reason trades are Rs {gap:,.0f} a trade "
                f"{'better' if gap > 0 else 'WORSE'}. Keep collecting -- "
                f"{CONFIDENT_N} per group before acting on it.")
    if gap > 0:
        return (f"REASON TRADES ARE BETTER by Rs {gap:,.0f} a trade, on "
                f"{smaller}+ per group. This is enough to start sizing by "
                f"proven reason.")
    return (f"REASON TRADES ARE NOT BETTER (Rs {gap:,.0f} a trade). "
            f"On {smaller}+ per group that is a real answer, and it says "
            f"the gate needs rethinking rather than more data.")


def main():
    memory = TradeMemory()
    with memory.engine.begin() as conn:
        rows = [dict(r) for r in
                conn.execute(memory.trades.select()).mappings().all()]

    if not rows:
        print("No trades recorded yet.")
        return

    print("=" * 78)
    print("  DID THE REASON MAKE ANY DIFFERENCE?")
    print("=" * 78)
    print(f"\n  {'group':26} {'n':>5} {'win %':>8} {'avg P&L':>10} "
          f"{'total':>12} {'payoff':>8}")
    print("  " + "-" * 74)

    with_r = [r for r in rows if r.get("had_reason")]
    without = [r for r in rows if not r.get("had_reason")]
    a, b = _stats(with_r), _stats(without)
    print(_line("WITH a reason", a))
    print(_line("WITHOUT a reason", b))

    print(f"\n  VERDICT: {_verdict(a, b)}\n")

    # ---- by kind of reason ----
    for column, title in (("news_kind", "BY NEWS TYPE"),
                          ("results_grade", "BY RESULTS GRADE"),
                          ("filing_kind", "BY FILING TYPE"),
                          ("exit_reason", "BY HOW IT ENDED")):
        buckets = defaultdict(list)
        for r in rows:
            key = r.get(column)
            if key:
                buckets[key].append(r)
        if not buckets:
            continue
        print("=" * 78)
        print(f"  {title}")
        print("=" * 78)
        print(f"\n  {'':26} {'n':>5} {'win %':>8} {'avg P&L':>10} "
              f"{'total':>12} {'payoff':>8}")
        print("  " + "-" * 74)
        for key, group in sorted(buckets.items(),
                                 key=lambda kv: -_stats(kv[1])["avg"]):
            s = _stats(group)
            flag = "" if s["n"] >= SUGGESTIVE_N else "   (too few to judge)"
            print(_line(str(key), s) + flag)
        print()

    print("=" * 78)
    total = _stats(rows)
    print(f"  {len(rows)} trades on record. Overall win rate "
          f"{total['win_rate']:.1f}%, payoff {total['payoff']:.2f}:1, "
          f"expectancy Rs {total['avg']:,.0f} a trade.")
    if total["payoff"] < 1.5:
        print(f"\n  NOTE: at a {total['win_rate']:.0f}% win rate you need a "
              f"payoff above ~1.4:1 just to break even. Currently "
              f"{total['payoff']:.2f}:1.")
    print("=" * 78)


if __name__ == "__main__":
    main()
