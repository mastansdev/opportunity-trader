"""
==========================================================
What would today's picks be worth right now?
==========================================================

    py tools/paper_pnl.py
    py tools/paper_pnl.py 100000     # rupees per position

    "not real trades. i'm asking about based on these entries what
     could be the bot's pnl"        -- operator, 5 August 2026

WHY THIS EXISTS
---------------
The bot's own P&L is zero and will stay zero through Phase 1 -- it
places no orders. That is the agreement, and it is also a useless
answer to the question he is actually asking, which is: ARE THE PICKS
ANY GOOD, right now, mid-session.

tools/verify_picks.py answers that against the CLOSE, and cannot run
until NSE publishes the bhavcopy. This answers it against the LIVE
price, at any moment of the day.

WHAT IT ASSUMES, AND SAYS SO
----------------------------
An equal rupee notional per position, because mid-session there is no
stop recorded for every pick and therefore no risk-based size to use.
That is NOT the sizing the bot would trade (see BACKLOG R1 -- equal
RISK, not equal capital), so this is an indicative number, not a
forecast of what Phase 2 would have made.

Everything else is real: the entry is the price at the moment the bot
named the stock, the direction is the one it called, and the current
price comes from the live session.

WHAT IT IS NOT
--------------
Not a fill. Not net of brokerage, STT or MTF interest. A pick is not a
trade and this number is not money.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import sys
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DASHBOARD_HOST, DASHBOARD_PORT        # noqa: E402
from core.decision_log import DecisionLog                # noqa: E402
from core.logger import decision, warn                   # noqa: E402
from dashboard.access_token import get_or_create_token   # noqa: E402

# His own ceiling per position (config.MTF_MARGIN_PER_POSITION_RS is
# the MARGIN; this is the stock value). Stated, not hidden.
DEFAULT_NOTIONAL = 100_000.0


def live_prices():
    """Every price the running session currently holds.

    Read from the dashboard this bot is already serving -- no second
    Dhan connection, no extra REST call, nothing that could interfere
    with the session placing orders.
    """
    url = (f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}/api/snapshot"
           f"?token={get_or_create_token()}")
    with urllib.request.urlopen(url, timeout=10) as response:
        snapshot = json.load(response)

    prices = {}
    # The movers carry ltp for everything that has ticked today.
    block = snapshot.get("gainers_losers") or {}
    for side in ("gainers", "losers"):
        for row in block.get(side) or []:
            symbol = str(row.get("symbol") or "").upper()
            if symbol and row.get("ltp"):
                prices[symbol] = float(row["ltp"])
    for row in (snapshot.get("ranked") or {}).get("rows") or []:
        symbol = str(row.get("symbol") or "").upper()
        if symbol and row.get("ltp"):
            prices.setdefault(symbol, float(row["ltp"]))
    for row in snapshot.get("open_positions") or []:
        symbol = str(row.get("symbol") or "").upper()
        if symbol and row.get("last_price"):
            prices.setdefault(symbol, float(row["last_price"]))
    return prices


def main(notional=DEFAULT_NOTIONAL, day=None):
    day = day or datetime.now().strftime("%Y-%m-%d")

    decision("=" * 78)
    decision(f"  IF THE BOT HAD TAKEN ITS OWN PICKS -- {day}")
    decision(f"  Rs {notional:,.0f} per position. Nothing was bought.")
    decision("=" * 78)

    picks = DecisionLog().first_pick_per_symbol(day)
    if not picks:
        warn(f"  No picks recorded for {day}.")
        return 1

    try:
        prices = live_prices()
    except Exception as exc:                               # noqa: BLE001
        warn(f"  Could not read live prices ({exc}).")
        warn("  Is main.py running? This reads its dashboard.")
        return 1

    decision(f"  {'STOCK':<13}{'CALL':<6}{'AT':<7}{'ENTRY':>9}{'NOW':>9}"
             f"{'MOVE':>8}{'P&L':>11}   WHY")
    decision("-" * 78)

    total = 0.0
    up = down = 0
    unpriced = []
    rows = sorted(picks.items(), key=lambda kv: -(kv[1].get("score") or 0))

    for symbol, pick in rows:
        entry = pick.get("price")
        now = prices.get(symbol)
        if not entry or not now:
            unpriced.append(symbol)
            continue
        move = (now - entry) / entry * 100.0
        # In the direction the bot actually called.
        move = move if pick["action"] == "BUY" else -move
        rupees = notional * move / 100.0
        total += rupees
        if rupees > 0:
            up += 1
        elif rupees < 0:
            down += 1
        decision(f"  {symbol:<13}{pick['action']:<6}"
                 f"{str(pick['at'])[11:16]:<7}{entry:>9.2f}{now:>9.2f}"
                 f"{move:>7.2f}%{rupees:>11,.0f}   "
                 f"{(pick.get('why') or '')[:28]}")

    decision("-" * 78)
    scored = up + down
    if scored:
        decision(f"  {scored} pick(s):  {up} up, {down} down."
                 f"   TOTAL {total:>+,.0f}"
                 f"   average {total / scored:>+,.0f} per pick")
    if unpriced:
        decision(f"  no live price for: {', '.join(unpriced[:10])}"
                 f"{' ...' if len(unpriced) > 10 else ''}")

    decision("=" * 78)
    decision("  INDICATIVE ONLY. Equal rupees per position is NOT how the")
    decision("  bot would size -- it sizes off the stop so every trade")
    decision("  risks the same amount (BACKLOG R1). No brokerage, no STT,")
    decision("  no MTF interest, and an entry at the moment of the call")
    decision("  is not a fill.")
    decision("=" * 78)
    return 0


if __name__ == "__main__":
    amount = DEFAULT_NOTIONAL
    if len(sys.argv) > 1:
        try:
            amount = float(sys.argv[1])
        except ValueError:
            warn(f"Ignoring '{sys.argv[1]}' -- expected rupees per position.")
    sys.exit(main(amount))
