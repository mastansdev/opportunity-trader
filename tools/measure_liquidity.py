"""
==========================================================
Measure how much money trades in each stock
==========================================================

    py tools/measure_liquidity.py

Reads data/history_candles.db -- nineteen million minute candles, each
with a volume -- and writes data/liquidity.json: average daily traded
value per symbol, in crore, over the last five sessions.

WHAT IT IS FOR
--------------
When a market-wide event fires, core/sector_map.py has to put three
names per sector in front of the operator. Anything already moving goes
first. But in the FIRST SECONDS nothing has moved yet, and the fallback
used to be alphabetical:

    IT     ->  63MOONS, AFFLE, AMAGI
    Pharma ->  AARTIDRUGS, AARTIPHARM, ABBOTINDIA

Nobody trades a war headline through 63MOONS. With this file:

    IT     ->  INFY, TCS, COFORGE
    Pharma ->  SUNPHARMA, LAURUSLABS, CUPID

Runs after the close, in the nightly batch, because the aggregate takes
a few seconds over the whole store and cannot go anywhere near a
one-second dashboard refresh.

A failure here is not fatal to anything. Without the file the fan-out
falls back to alphabetical, which is what it did before.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.liquidity import (SESSIONS, STORE_PATH, adv, measured_at,  # noqa: E402
                            refresh, reset)
from core.logger import decision, warn                    # noqa: E402


def main():
    count = refresh(sessions=SESSIONS)
    if not count:
        warn("Nothing measured. The fan-out will order by name until "
             "this succeeds, which is how it behaved before.")
        return 1

    reset()
    decision(f"Written to {STORE_PATH}, measured {measured_at()}.")

    # Show the top of the list so a wrong answer is visible here rather
    # than at 09:15 on a shock.
    from core import sector_map
    sector_map.reset()
    for sector in ("IT", "Auto", "Pharma", "Private Bank"):
        names = sector_map.members(sector)
        if not names:
            continue
        top = sorted(names, key=lambda s: (-adv(s), s))[:3]
        decision("  %-14s %s" % (sector, ", ".join(
            f"{s} {adv(s):,.0f}cr" for s in top)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
