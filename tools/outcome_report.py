"""
==========================================================
Which chips are worth reading?
==========================================================
    py tools/outcome_report.py

Every layer this bot has describes the PAST. Until now nothing checked
any of it against what the stock then DID.

For each chip the panel can show, this measures the move on the
session AFTER the event, against the market's median move that day.
What comes out is an EDGE, not a direction.

READ THE N COLUMN FIRST. A chip seen five times has no lesson in it.
Nothing here changes a score, and nothing in the trading path imports
core/outcomes.py -- re-weighting the panel on a week of data would be
the mistake tools/refused_review.py already warns about:

    "Do not change a rule on one day of this. Most buckets need a
     fortnight before they mean anything."

Author : H&M Opportunity Trader
==========================================================
"""

import sys

sys.path.insert(0, ".")

from core.logger import decision, warn                    # noqa: E402
from core.outcomes import (MIN_SAMPLE, by_sector, contrast,   # noqa: E402
                           from_chip_time,
                           measure)


def _bar(edge, width=18):
    """A cheap visual so the sign is readable at a glance."""
    steps = max(-width // 2, min(width // 2, int(round(edge * 3))))
    if steps == 0:
        return " " * (width // 2) + "|"
    if steps > 0:
        return " " * (width // 2) + "|" + "#" * steps
    return " " * (width // 2 + steps) + "#" * (-steps) + "|"


def main():
    result = measure()
    if not result or len(result) <= 1:
        warn("No measurable events yet. Needs at least one event with a "
             "trading session after it.")
        return 1
    unanswered = result.pop("_unanswered", 0)

    ranked = sorted(result.items(), key=lambda kv: -kv[1]["n"])

    decision("=" * 78)
    decision("  WHAT HAPPENED AFTER EACH CHIP")
    decision("=" * 78)
    decision("")
    decision("  EDGE = the stock's move MINUS the market's median that")
    decision("  session. A positive edge means the stock beat the market on")
    decision("  the day the chip was answered.")
    decision("")
    decision(f"  {'CHIP':20s} {'N':>5s} {'EDGE':>7s} {'UP%':>6s}   "
             f"{'':9s}worse | better")
    decision("  " + "-" * 74)
    for label, s in ranked:
        mark = " " if s["enough"] else "?"
        decision(f"  {label:20s} {s['n']:5d} {s['edge_median']:6.2f}% "
                 f"{s['up_pct']:5.1f}% {mark}  {_bar(s['edge_median'])}")

    thin = [k for k, v in ranked if not v["enough"]]
    if thin:
        decision("")
        decision(f"  ? = fewer than {MIN_SAMPLE} samples. Not a finding yet: "
                 f"{', '.join(thin)}")
    if unanswered:
        decision("")
        decision(f"  {unanswered} events have no session after them yet. "
                 f"They are excluded, never counted as zero.")

    # ---- THE NUMBER HE ACTUALLY TRADES ON ----
    #
    #     "before the movement i need to trust as early bird not in a
    #      over crowded place after rally done ... if i bought even a
    #      good stock at near Upper Circuit whats the use?"
    #
    # The table above reads the whole session, which credits a chip
    # with a rally that finished before he could click. This one
    # prices the MINUTE the chip landed and counts only what came
    # after. It is slower -- it reads a 3 GB minute store -- and it is
    # the honest answer.
    chip_time = from_chip_time()
    if chip_time and len(chip_time) > 1:
        unpriced = chip_time.pop("_unpriced", 0)
        decision("")
        decision("=" * 78)
        decision("  IF YOU BOUGHT THE MOMENT THE CHIP APPEARED")
        decision("=" * 78)
        decision("")
        decision("  Priced off the minute bar at the chip's own timestamp.")
        decision("  BEST and WORST are how far it ran, and how much heat you")
        decision("  took, AFTER that minute -- not across the whole day.")
        decision("")
        decision(f"  {'CHIP':20s} {'N':>4s} {'TO CLOSE':>9s} {'BEST':>7s} "
                 f"{'WORST':>7s} {'WIN%':>6s}")
        decision("  " + "-" * 58)
        for label, s in sorted(chip_time.items(), key=lambda kv: -kv[1]["n"]):
            mark = " " if s["enough"] else "?"
            decision(f"  {label:20s} {s['n']:4d} {s['to_close']:8.2f}% "
                     f"{s['best']:6.2f}% {s['worst']:6.2f}% "
                     f"{s['win_pct']:5.1f}% {mark}")
        if unpriced:
            decision("")
            decision(f"  {unpriced} events had no minute bar -- the intraday")
            decision(f"  store covers the subscribed universe only. Run")
            decision(f"  py tools/fetch_history.py --days 62 --intraday-only")
            decision(f"  to widen it.")

    gap = contrast()
    if gap:
        decision("")
        decision("=" * 78)
        decision("  THE NUMBER THAT PUTS THE REST IN CONTEXT")
        decision("=" * 78)
        decision("")
        decision(f"  stocks carrying ANY chip   {gap['with_chip_median']:+6.2f}%   "
                 f"(n={gap['with_chip_n']:,})")
        decision(f"  stocks carrying none       {gap['no_chip_median']:+6.2f}%   "
                 f"(n={gap['no_chip_n']:,})")
        decision(f"  gap                        {gap['gap']:+6.2f}%")
        decision("")
        decision("  Every EDGE above is measured against the WHOLE market,")
        decision("  which flatters it: a stock the channels wrote about is")
        decision("  not the same animal as one nobody mentioned. Subtract")
        decision(f"  this {gap['gap']:+.2f}% to read an edge as something the")
        decision("  PANEL added rather than something 'being in the news'")
        decision("  added.")
        decision(f"  Sessions measured: {len(gap['sessions'])}")

    # ---- THE LENDER QUESTION, LEFT OPEN ON PURPOSE ----
    #
    # The audit claimed the grader is blind to lenders because it
    # cannot see provisions. That came from ONE case: APTUS, graded
    # STRONG on +19% profit, down 5.77% on doubled provisions.
    #
    # Measured, lenders did FINE. Banks alone look worse, on eight
    # samples. So nothing was built; this table is here so the answer
    # arrives on evidence rather than on the memory of one bad day.
    try:
        from core.master_loader import MasterLoader
        loader = MasterLoader()
        loader.load()
    except Exception as exc:                               # noqa: BLE001
        warn(f"  (sector split unavailable: {exc})")
        loader = None

    sectors = by_sector(loader) if loader else {}
    if sectors:
        decision("")
        decision("=" * 78)
        decision("  A RESULTS GRADE, BY KIND OF BUSINESS")
        decision("=" * 78)
        decision("")
        decision(f"  {'GROUP':20s} {'N':>5s} {'EDGE':>7s} {'UP%':>6s}")
        decision("  " + "-" * 42)
        for label, s in sorted(sectors.items(), key=lambda kv: -kv[1]["n"]):
            mark = " " if s["enough"] else "?"
            decision(f"  {label:20s} {s['n']:5d} {s['edge_median']:6.2f}% "
                     f"{s['up_pct']:5.1f}% {mark}")
        decision("")
        decision("  The audit claimed lenders are graded on the wrong")
        decision("  numbers, from one case. Watch this table for a")
        decision("  fortnight before believing it or dismissing it.")

    decision("")
    decision("  Nothing here changes a score. Read the N column first, and")
    decision("  give a bucket a fortnight before believing it.")
    decision("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
