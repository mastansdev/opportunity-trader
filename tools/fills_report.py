"""
What your fills actually cost -- measured, not modelled.

    py tools/fills_report.py              everything recorded so far
    py tools/fills_report.py --today      just today
    py tools/fills_report.py --paper      the model's own output

Run this after the first live orders. Until there are real fills it
has nothing to say, and says so rather than filling the screen with
the model's guesses dressed up as measurements.

WHAT IT IS FOR
--------------
config.SLIPPAGE_BASE_PCT (0.05%) and SLIPPAGE_THIN_PCT (0.20%) are
conventional retail figures, not this bot's data. trading/slippage.py
says so itself. Once there are enough real fills, the `suggested`
figure at the bottom is what should replace them.

Only THEN is the limit-order question answerable: a market order costs
a few basis points every time, a limit order costs the whole move on
the days it does not fill. That trade-off needs a real number on one
side of it.
"""

import sys
from datetime import datetime

sys.path.insert(0, ".")

from core.fill_log import FillLog
from core.logger import decision, warn


def _line(title, rows):
    if not rows:
        return
    pcts = sorted(r["slip_pct"] for r in rows)
    total = sum(r["slip_rs"] for r in rows)
    decision(f"  {title:<22}{len(rows):>5} fills  "
             f"Rs {total:>10,.0f}  median {pcts[len(pcts) // 2]:>7.3f}%  "
             f"worst {pcts[-1]:>7.3f}%")


def main():
    log = FillLog()
    date = datetime.now().strftime("%Y-%m-%d") if "--today" in sys.argv else None
    mode = "PAPER" if "--paper" in sys.argv else "LIVE"

    rows = log.rows(mode=mode, date=date)
    decision("=" * 72)
    decision(f"  FILLS -- {mode}{'  (today)' if date else ''}")
    decision("=" * 72)

    if not rows:
        if mode == "LIVE":
            warn("  No real fills recorded yet.\n"
                 "  Until there are, config.SLIPPAGE_BASE_PCT / "
                 "SLIPPAGE_THIN_PCT stay guesses\n"
                 "  and the limit-order question cannot be answered with "
                 "your own numbers.\n"
                 "  First real orders: py tools/live_order_test.py "
                 "--symbol COFORGE")
        else:
            warn("  Nothing recorded. Run a session first.")
        return

    by_side, by_reason = {}, {}
    for row in rows:
        by_side.setdefault(row["side"], []).append(row)
        kind = "MANUAL" if "MANUAL" in (row["reason"] or "") else "BOT"
        by_reason.setdefault(kind, []).append(row)

    _line("ALL", rows)
    decision("")
    for side in sorted(by_side):
        _line(side, by_side[side])
    decision("")
    for kind in sorted(by_reason):
        _line(kind, by_reason[kind])

    decision("")
    decision("  WORST FIVE")
    for row in sorted(rows, key=lambda r: -r["slip_pct"])[:5]:
        decision(f"    {row['at'][11:16]}  {row['symbol']:<12}{row['side']:<5}"
                 f"wanted {row['intent_price']:>9.2f}  got "
                 f"{row['fill_price']:>9.2f}  "
                 f"Rs {row['slip_rs']:>8,.0f}  ({row['slip_pct']:+.3f}%)")

    better = sum(1 for r in rows if r["slip_rs"] < 0)
    if better:
        decision(f"\n  {better} of {len(rows)} filled BETTER than asked.")

    stats = log.stats(mode=mode, date=date)
    decision("")
    decision("=" * 72)
    if mode == "LIVE":
        decision(f"  MEASURED average: {stats['suggested_pct'] * 100:.4f}% "
                 f"per fill, from {stats['fills']} real fills.")
        if stats["fills"] < 30:
            warn(f"  Only {stats['fills']} fills -- too few to replace the "
                 f"config constants yet. Aim for 30+.")
        else:
            decision(f"  Enough to act on. Set SLIPPAGE_BASE_PCT = "
                     f"{stats['suggested_pct']:.5f} and re-run the exit "
                     f"study, which currently assumes a guess.")
    decision("=" * 72)


if __name__ == "__main__":
    main()
