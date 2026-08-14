"""
==========================================================
Give the stored news a direction
==========================================================
    py tools/ai_backfill.py            look, spend nothing
    py tools/ai_backfill.py --apply    grade them

WHAT IT DOES
------------
Every event that has a company and a kind but no direction gets one
verdict from the cheap model: POSITIVE, NEGATIVE, NEUTRAL or
UNRELATED, with a confidence and a one-line reason, stored next to the
event.

WHY IT IS A SEPARATE TOOL
-------------------------
The live path grades new events as they arrive. This one exists for
the events ALREADY on disk -- 141 of them on 31 July 2026 -- so Monday
morning opens with history behind the chips instead of an empty
column that fills up slowly through the day.

It is also how a re-grade happens. When the model changes, or the
prompt does, the old verdicts were produced by a different reader; run
this with --regrade to replace them, and ai_model on each row records
which reader said what.

WHAT IT COSTS
-------------
About Rs 3 for the whole backfill, and it will tell you the number
before it spends anything. Every call goes through core/ai_budget.py,
which refuses at the monthly cap.

IT NEVER TRADES. It writes five columns on rows that already exist.

Author : H&M Opportunity Trader
==========================================================
"""

import sys

sys.path.insert(0, ".")

from config import AI_MODEL_CHEAP                          # noqa: E402
from core.ai_budget import AiBudget                        # noqa: E402
from core.ai_news import AiNewsGrader                      # noqa: E402
from core.logger import decision, warn                     # noqa: E402
from core.master_loader import MasterLoader                # noqa: E402
from core.stock_events import StockEvents                  # noqa: E402

# MEASURED, not estimated. The first real backfill graded 142 events
# for Rs 9.15 -- Rs 0.064 each. The guess before it ran was Rs 0.025,
# which was 2.6x low, because it assumed every call would read a warm
# cache and ignored that the system prompt is ~450 tokens rather than
# the 260 assumed.
#
# Sending the company profile too makes each call slightly larger
# again, so this is rounded UP. An estimate that flatters the bill is
# worse than no estimate.
EST_RS_PER_EVENT = 0.075


def _line():
    decision("-" * 68)


def main(apply=False, limit=500, regrade=False):
    decision("=" * 68)
    decision("  AI BACKFILL -- a direction for news the bot already has")
    decision("=" * 68)

    store = StockEvents()
    budget = AiBudget()

    if regrade:
        import sqlite3
        with sqlite3.connect(store.db_path) as conn:
            n = conn.execute(
                "UPDATE events SET ai_direction = NULL, ai_confidence = NULL,"
                " ai_reason = NULL, ai_model = NULL, ai_at = NULL"
                " WHERE ai_direction IS NOT NULL").rowcount
        warn(f"  --regrade: cleared {n} existing verdict(s). They will be "
             f"asked again.")

    pending = store.needing_a_verdict(limit=limit)
    _line()
    decision(f"  waiting for a verdict : {len(pending)}")
    decision(f"  model                 : {AI_MODEL_CHEAP}")
    decision(f"  estimated cost        : about Rs "
             f"{len(pending) * EST_RS_PER_EVENT:,.2f}")
    decision(f"  {budget.report()}")

    if not pending:
        _line()
        decision("  Nothing to do. Every stored event already has a "
                 "direction or a grade.")
        return

    _line()
    decision("  a sample of what would be asked:")
    for event in pending[:6]:
        decision(f"    {event['symbol']:12} {event['kind']:6} "
                 f"{event['headline'][:60]}")

    allowed, why = budget.may_call()
    if not allowed:
        _line()
        warn(f"  REFUSED: {why}.")
        return

    if not apply:
        _line()
        decision("  DRY RUN -- nothing was asked and nothing was spent.")
        decision("  To grade them:")
        decision("      py tools/ai_backfill.py --apply")
        return

    _line()
    decision("  asking...")
    decision("")
    # THE COMPANY NAME GOES WITH THE STORY. Without the master file the
    # model sees a bare ticker and has to guess what PPLPHARMA is -- on
    # the first run it guessed wrong and called a Piramal Pharma story
    # UNRELATED to Piramal Pharma.
    loader = MasterLoader()
    loader.load()
    grader = AiNewsGrader(budget=budget, master_loader=loader)
    result = grader.grade_pending(store, limit=limit, log=True)

    _line()
    decision(f"  graded  : {result['graded']} of {result['pending']}")
    decision(f"  calls   : {result['calls']}")
    decision(f"  {budget.report()}")
    decision("")
    decision("  NOTHING WAS TRADED. Five columns were written on rows that")
    decision("  already existed.")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv,
         regrade="--regrade" in sys.argv)
