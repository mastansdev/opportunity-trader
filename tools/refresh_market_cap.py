"""
==========================================================
Refresh how big each company is
==========================================================
    py tools/refresh_market_cap.py

Reads only. Places no orders, touches no positions, changes nothing
the bot may buy.

WHY IT EXISTS

    "check the % of that order to their market cap. this reveal the
     significance of the order book."      -- the operator, 5 Sep 2026

A Rs 630 crore order to RAILTEL is a quarter of the company. The same
figure to Reliance is a rounding error. Without the company's size the
board can only show the rupees, which is the half that misleads.

Free float, from NSE's own index lists -- see core/market_cap.py for
what that means and what it costs. A handful of calls covers about 500
of the 1,976 symbols on file: the liquid ones. Anything not covered is
stored as nothing and shown as nothing.

WHEN TO RUN IT. Weekly is plenty. A company's size moves with its
price, and a week of drift does not change whether an order is 2% or
40% of it. The board reports the age of the reading, so a stale one is
visible rather than quietly believed.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from core.logger import decision                           # noqa: E402
from core import market_cap                                # noqa: E402


def main():
    before = market_cap.status()
    decision("")
    decision("  Refreshing company sizes from NSE (free float).")
    if before["available"]:
        decision(f"  {before['symbols']} already on file, "
                 f"{before['age_days']} day(s) old.")
    n = market_cap.refresh()
    after = market_cap.status()
    decision("")
    if not n:
        decision("  Nothing refreshed. Whatever was on file is "
                 "untouched.")
        return 1
    decision(f"  {after['symbols']} companies on file.")
    decision("")
    # Something to read, not just a count. The point of the number is
    # the comparison, so show one.
    for sym in ("RELIANCE", "WELCORP", "RAILTEL", "TEJASNET"):
        cap = market_cap.of(sym)
        if cap:
            decision(f"    {sym:<12}Rs {cap:>12,.0f} cr free float")
    decision("")
    decision("  This changes nothing the bot may buy. It lets the "
             "board say how big an order is RELATIVE to the company.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
