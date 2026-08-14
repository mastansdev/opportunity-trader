"""
==========================================================
Were the bot's picks any good?
==========================================================

    py tools/verify_picks.py            # today
    py tools/verify_picks.py 2026-08-05

    "phase-1 bot will trade (assumption) & record . after tomorrow
     market closing we will verify & start the next phase-2"
                                    -- operator, 4 August 2026

WHAT THIS ANSWERS
-----------------
core/ranker.py picked. core/decision_log.py wrote down what it picked,
when, and at what price. This reads both back against what those
stocks actually did, from NSE's own daily bars, and produces a number
instead of an argument.

For every pick:

    entry     the price at the MOMENT the bot named it -- not the open,
              not the close, and not the best fill of the day
    close     where NSE says the stock finished
    result    what the trade would have made, in the direction the bot
              actually called

RUN IT AFTER build_daily_history
--------------------------------
The close comes from DailyStore, which tools/build_daily_history.py
fills from the bhavcopy. Run this before that and today's bars do not
exist yet, and it will say so rather than reporting zero.

WHAT THE REFUSALS COLUMN IS FOR
-------------------------------
A strategy is also its declines. If "no reason found" turned away
eleven names, that gate is either protecting him or blinding him, and
only the count over several days can say which. The verdict at the
bottom deliberately does not average the two.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.daily_store import DailyStore                   # noqa: E402
from core.decision_log import DecisionLog                 # noqa: E402
from core.logger import decision, warn                    # noqa: E402


def _line():
    decision("=" * 76)


def closes_on(day):
    """{symbol: (close, prev_close)} from NSE's bars for that day."""
    from sqlalchemy import select

    store = DailyStore()
    bars = store.bars
    out = {}
    with store.engine.connect() as conn:
        for row in conn.execute(
                select(bars.c.symbol, bars.c.close, bars.c.prev_close,
                       bars.c.high, bars.c.low)
                .where(bars.c.date == day)):
            out[(row.symbol or "").upper()] = {
                "close": row.close, "prev_close": row.prev_close,
                "high": row.high, "low": row.low}
    return out


def main(day=None):
    day = day or datetime.now().strftime("%Y-%m-%d")
    log = DecisionLog()

    _line()
    decision(f"  WERE THE BOT'S PICKS ANY GOOD?   {day}")
    _line()

    if not log.status().get("available"):
        warn("  No decision log. The bot recorded nothing.")
        return 1

    first = log.first_pick_per_symbol(day)
    if not first:
        warn(f"  Nothing recorded for {day}. Days on file: "
             f"{', '.join(log.days()) or 'none'}")
        return 1

    bars = closes_on(day)
    if not bars:
        warn(f"  No daily bars for {day} yet -- run "
             f"py tools/build_daily_history.py first. "
             f"Without them there is nothing to measure against.")
        return 1

    decision(f"  {'STOCK':<13}{'CALL':<6}{'AT':<9}{'ENTRY':>9}"
             f"{'CLOSE':>9}{'RESULT':>9}   WHY IT WAS PICKED")
    decision("-" * 76)

    wins = losses = flat = 0
    total = 0.0
    missing = []
    for symbol, row in sorted(first.items(),
                              key=lambda kv: -(kv[1].get("score") or 0)):
        bar = bars.get(symbol)
        entry = row.get("price")
        if not bar or not bar.get("close") or not entry:
            missing.append(symbol)
            continue
        close = bar["close"]
        move = (close - entry) / entry * 100.0
        # In the direction the bot actually called.
        result = move if row["action"] == "BUY" else -move
        total += result
        if result > 0:
            wins += 1
        elif result < 0:
            losses += 1
        else:
            flat += 1
        decision(f"  {symbol:<13}{row['action']:<6}"
                 f"{str(row['at'])[11:16]:<9}{entry:>9.2f}{close:>9.2f}"
                 f"{result:>8.2f}%   {(row.get('why') or '')[:34]}")

    decision("-" * 76)
    # ---- IT UNDER-REPORTED THE PICKS. 4 August 2026. ----
    #
    # The first real run printed twelve rows and then said
    #
    #     9 pick(s):  3 up, 6 down.
    #
    # wins + losses, and a result of exactly 0.00% is neither. Three
    # rows vanished from the headline while sitting on the screen
    # above it. The count of what the bot chose must not depend on
    # whether the trades worked.
    scored = wins + losses + flat
    if scored:
        decision(f"  {scored} pick(s):  {wins} up, {losses} down"
                 + (f", {flat} unchanged" if flat else "")
                 + f".  Average {total / scored:+.2f}% by the close.")
    if missing:
        decision(f"  no close for: {', '.join(missing[:8])}"
                 f"{' ...' if len(missing) > 8 else ''}")

    refused = log.refusals(day)
    if refused:
        decision("")
        decision("  WHAT IT TURNED AWAY  (a strategy is also its declines)")
        for reason, count in list(refused.items())[:8]:
            decision(f"    {count:>5}  {reason}")

    _line()
    decision("  This measures the PICK, not a trade. Nothing was bought,")
    decision("  there are no charges in these numbers, and an entry at")
    decision("  the moment of the call is not a fill.")
    _line()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
