"""
==========================================================
Make the bot's book agree with Dhan's
==========================================================
    py tools/reconcile.py            look, change nothing
    py tools/reconcile.py --apply    adopt Dhan's truth

DHAN IS ALWAYS RIGHT. This tool only ever edits OUR file.

WHY
---
31 July 2026. The operator closed a bot-opened SHADOWFAX from the Dhan
app to see what would happen. The dashboard caught it within a minute:

    AT THE BROKER                                    MISMATCH
    SHADOWFAX   Dhan: --   Bot's book: 1
    "The bot thinks it holds this and Dhan does not."

Detection worked. Repair did not exist -- the fix was a raw one-liner
typed into a terminal that edited a JSON file by hand. That is not a
tool, and it means every future mismatch needs someone who knows the
file format.

Then he said the thing that made this urgent:

    "on monday mostly i use both for buying & selling - no 100% on
     single i can tell u"

If both the dashboard and the Dhan app are used on the same day, a
divergence is not an incident. It is Tuesday.

WHAT IT WILL NOT DO
-------------------
IT NEVER PLACES AN ORDER. Not to buy back something the bot thinks it
holds, not to flatten something it does not. "Fixing" a book by
trading is how a discrepancy becomes a loss -- the bot would sell
stock that is not there, which on MTF opens a SHORT.

It also refuses to run while main.py is live. The running process
holds the book in memory and writes it out on shutdown, so anything
changed underneath it is silently overwritten -- which would look like
the tool did nothing.

WHAT "ADOPT" MEANS
------------------
    at Dhan, not in the bot     -> ADDED to the bot's book
    in the bot, not at Dhan     -> REMOVED from the bot's book
    quantities differ           -> set to Dhan's number

A position adopted from the broker is marked so the bot will not
manage it -- no stop, no target, no square-off. The bot did not open
it and has no idea what it was for.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, ".")

from config import (                                       # noqa: E402
    DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN, ORDER_PROXY, TRADING_MODE,
)
from core.broker_sync import compare                       # noqa: E402
from core.logger import decision, warn                     # noqa: E402
from core.order_route import route_orders_through          # noqa: E402

STATE = os.path.join("data", "session_state.json")
ADOPTED_REASON = "ADOPTED_FROM_BROKER"


def _line():
    decision("-" * 70)


def _bot_is_running():
    """Is main.py live right now?

    Anything this tool writes while the bot is running gets overwritten
    when the bot shuts down and saves its own in-memory book. The
    operator would see "cleared" and then find it back, which is worse
    than refusing.

    The dashboard's own port is the tell -- it is bound for as long as
    main.py lives.
    """
    import socket

    for port in (8000,):
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(0.4)
        try:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return True
        finally:
            probe.close()
    return False


def _broker_positions():
    """What Dhan says is open -- intraday AND overnight, through the
    static IP, same as orders.

    ---- POSITIONS ALONE IS HALF THE BOOK. Fixed here 12 August 2026. ----

    This used to call client.get_positions() directly and stop there.
    Dhan's /positions is the INTRADAY book; an MTF or delivery position
    bought yesterday moves to /holdings on T+1. So the morning after
    every overnight trade, this function reported "Dhan holds nothing"
    for a real position, and `py tools/reconcile.py --apply` would have
    adopted that as truth and DELETED it from the bot's book -- see
    trading/live_execution.py's LiveExecution.holdings() docstring for
    the 5 August incident this caused live.

    core/broker_sync.py's own BrokerSync (the one main.py runs every
    60s while the bot is live) was fixed the same day by reading
    LiveExecution.broker_book() instead of positions() alone. This
    script builds its own raw client rather than reusing main.py's
    running instance -- deliberately, since it is meant to run AFTER
    the bot has been stopped -- but it was never updated to ask the
    same question. It is now: LiveExecution already carries the
    positions+holdings union, the None-vs-empty discipline that tells
    "could not ask" apart from "asked and got nothing", and the field-
    name handling for both response shapes -- reimplementing any of
    that here would be a second copy that could drift from the first.
    """
    from dhanhq import DhanContext, dhanhq as DhanRestClient
    from trading.live_execution import LiveExecution

    client = DhanRestClient(DhanContext(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN))
    route_orders_through(client, ORDER_PROXY)
    execution = LiveExecution(client)
    rows = execution.broker_book()
    if rows is None:
        raise RuntimeError(
            "could not read Dhan's positions AND holdings -- refusing "
            "to reconcile against a half-read book (see "
            "LiveExecution.broker_book())")
    return rows


def _load_state():
    with open(STATE, encoding="utf-8") as handle:
        return json.load(handle)


def _show(result, state):
    decision(f"  bot's book : {result['bot_count']} position(s)")
    decision(f"  at Dhan    : {result['broker_count']} position(s)")
    decision("")

    if result["in_sync"]:
        decision("  IN SYNC. Nothing to do.")
        return False

    for row in result["only_at_broker"]:
        decision(f"  + {row['symbol']:12} Dhan has {row['broker_qty']:g}, "
                 f"the bot does not know about it")
        decision("      -> would be ADDED to the bot's book, marked as not "
                 "the bot's to manage")

    for row in result["only_in_bot"]:
        held = (state.get("open_positions") or {}).get(row["symbol"], {})
        decision(f"  - {row['symbol']:12} the bot thinks it holds "
                 f"{row['bot_qty']:g}, Dhan has none")
        if held.get("entry_reason"):
            decision(f"      (bot opened it as {held['entry_reason']})")
        decision("      -> would be REMOVED from the bot's book")

    for row in result["quantity_differs"]:
        decision(f"  ~ {row['symbol']:12} bot says {row['bot_qty']:g}, "
                 f"Dhan says {row['broker_qty']:g}")
        decision(f"      -> would be SET to {row['broker_qty']:g}")

    return True


def main(apply=False):
    decision("=" * 70)
    decision("  RECONCILE -- the bot's book against Dhan's")
    decision("=" * 70)

    if str(TRADING_MODE).upper() != "LIVE":
        warn("  TRADING_MODE is not LIVE, so there is no broker book to")
        warn("  compare against. Nothing to reconcile.")
        return

    if _bot_is_running():
        warn("  main.py IS RUNNING.")
        warn("")
        warn("  It holds the book in memory and writes it out when it")
        warn("  stops, so anything changed here would be silently undone.")
        warn("  Press Ctrl+C in the bot's terminal first, then run this.")
        return

    if not os.path.exists(STATE):
        warn(f"  {STATE} not found -- the bot has no saved book.")
        return

    state = _load_state()
    bot = state.get("open_positions") or {}

    try:
        rows = _broker_positions()
    except Exception as exc:                               # noqa: BLE001
        warn(f"  Could not read Dhan's positions: {exc}")
        warn("  Refusing to change anything on a book we could not read.")
        return

    result = compare(bot, rows)
    _line()
    differs = _show(result, state)
    _line()

    if not differs:
        return

    if not apply:
        decision("  DRY RUN -- nothing was changed.")
        decision("  To adopt Dhan's version:")
        decision("      py tools/reconcile.py --apply")
        return

    # ---- write ------------------------------------------------------
    backup = f"{STATE}.{datetime.now():%Y%m%d-%H%M%S}.bak"
    shutil.copy(STATE, backup)

    for row in result["only_in_bot"]:
        bot.pop(row["symbol"], None)

    for row in result["only_at_broker"]:
        qty = row["broker_qty"]
        bot[row["symbol"]] = {
            "qty": abs(qty),
            "direction": "SHORT" if qty < 0 else "LONG",
            "entry_price": row.get("avg_price"),
            "entry_time": datetime.now().isoformat(timespec="seconds"),
            # Marked so the bot leaves it alone. It did not open this and
            # has no stop, no target and no idea what it was for.
            "entry_reason": ADOPTED_REASON,
        }

    for row in result["quantity_differs"]:
        entry = bot.get(row["symbol"])
        if entry is not None:
            qty = row["broker_qty"]
            entry["qty"] = abs(qty)
            entry["direction"] = "SHORT" if qty < 0 else "LONG"

    state["open_positions"] = bot
    with open(STATE, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)

    decision(f"  DONE. The bot's book now matches Dhan.")
    decision(f"  Backup of the old book: {backup}")
    decision("")
    decision(f"  bot holds: {sorted(bot) or 'nothing'}")
    decision("")
    decision("  NOTHING WAS BOUGHT OR SOLD. Only our own file changed.")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
