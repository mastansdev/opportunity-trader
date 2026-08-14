"""
==========================================================
Start tomorrow with an empty book
==========================================================

    py tools/fresh_book.py

    "first thing is opened positions till now . bot do not track them .
     next from morning onwards track everything not older trades, only
     fresh from tomorrow . saregama i sold today, whats the rocket
     science in that"
                                -- operator, 5 August 2026

WHY
---
The bot's book had drifted into a state nobody chose:

    CORONA      100  ADOPTED_FROM_BROKER   no stop
    DEEPAKFERT   50  ADOPTED_FROM_BROKER   no stop
    PIDILITIND  100  ADOPTED_FROM_BROKER   no stop
    SAREGAMA    100  ADOPTED_FROM_BROKER   no stop -- and SOLD, days ago
    BERGEPAINT  100                        stopped
    MOREPENLAB 2000                        stopped

Four with no stop, and one he had already closed. Adoption skips a
symbol that is already in the book, so none of them would ever have
been repaired -- they would have sat there, unprotected and invisible,
for as long as the file survived.

Rather than patch six rows into a shape nobody designed, this empties
the book. He keeps every share; only the bot's RECORD of them is
cleared. From the next session the bot tracks what it opens itself,
and adopts anything at Dhan freshly -- with a stop, priced from where
the stock actually is.

WHAT IT TOUCHES
---------------
data/session_state.json ONLY, and it writes a timestamped backup
first. It places no order, cancels nothing, and cannot change a single
share at Dhan. Your holdings are untouched.

RUN IT WITH main.py STOPPED. A running session holds this state in
memory and rewrites the file on shutdown, which would put every row
straight back.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import decision, warn                     # noqa: E402

STATE = os.path.join("data", "session_state.json")
# The keys that describe POSITIONS. Everything else in the file --
# ORB ranges, the momentum universe, counters -- is session data the
# next run rebuilds anyway and is left alone.
BOOK_KEYS = ("open_positions", "trailing_stops", "entry_blocks",
             # ---- THE PHANTOM CLOSES. 5 August 2026. ----
             #
             # The POST screen reported Rs 34,048 of losses on CORONA,
             # DEEPAKFERT and DEEPAKNTR with not one order sent. They
             # were adopted with stops measured from his ENTRY price,
             # so the stops were already breached when they were set;
             # the next tick closed them in memory and wrote a P&L on
             # prices that were never traded. He still owns the shares.
             #
             # The first version of this tool cleared the OPEN book and
             # left these behind, so the fictional losses survived
             # every restart.
             "closed_positions")


def _bot_is_running(port=8000):
    """A live main.py holds this state in memory and would undo us."""
    import socket
    with socket.socket() as probe:
        probe.settimeout(0.4)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def main(force=False):
    decision("=" * 70)
    decision("  EMPTY THE BOT'S BOOK -- your shares are not touched")
    decision("=" * 70)

    if not os.path.exists(STATE):
        warn(f"  {STATE} does not exist. Nothing to clear.")
        return 0

    if _bot_is_running() and not force:
        warn("  main.py is RUNNING. It holds the book in memory and would")
        warn("  write every row back when it stops.")
        warn("")
        warn("  Press Ctrl+C in that terminal first, then run this again.")
        warn("  (py tools/fresh_book.py --force to override.)")
        return 1

    backup = f"{STATE}.bak-{datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy(STATE, backup)
    decision(f"  backup written: {backup}")

    with open(STATE, encoding="utf-8") as handle:
        state = json.load(handle)

    for key in BOOK_KEYS:
        rows = state.get(key) or ({} if key != "closed_positions" else [])
        if rows:
            # closed_positions is a LIST OF DICTS; the other three are
            # dicts keyed by symbol. Joining the list gave
            # "expected str instance, dict found" and killed the tool
            # AFTER printing two lines, which reads like it worked.
            names = [r.get("symbol") if isinstance(r, dict) else str(r)
                     for r in rows]
            decision(f"  {key}: clearing {len(rows)} -- "
                     f"{', '.join(str(n) for n in names[:8] if n)}")
        # Same shape back, so nothing downstream has to special-case it.
        state[key] = [] if isinstance(rows, list) else {}

    # Written to a temp file and replaced, so a crash mid-write cannot
    # leave him with half a state file and no book at all.
    temporary = STATE + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)
    os.replace(temporary, STATE)

    decision("-" * 70)
    decision("  The book is empty. Every share you hold is still yours --")
    decision("  only the bot's record of them was cleared.")
    decision("")
    decision("  On the next start the bot adopts whatever Dhan reports,")
    decision("  fresh, each with a stop priced from where the stock IS.")
    decision("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main(force="--force" in sys.argv))
