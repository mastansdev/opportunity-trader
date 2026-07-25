"""
==========================================================
State Store
==========================================================

Persists just enough state to survive a restart without
silently losing what the bot already knew:

    1. Today's ORB ranges -- without this, a restart after
       09:30 permanently disables entries for every symbol
       for the rest of the session (core/orb_engine.py
       refuses to build a range once the window has closed
       on a symbol it has no memory of).
    2. Open positions -- without this, a restart forgets any
       PAPER position it already holds (long OR short), even
       though trade_log.csv still shows it as bought/sold.
    3. Trailing stop state -- without this, a restart on an
       open position forgets how far the stop had already
       ratcheted, silently giving back the protection that
       position had already earned (core/trailing_stop.py has
       no memory of a symbol until start() is called again).
    4. Paper capital ledger -- without this, a restart resets
       available capital back to the full starting amount,
       silently erasing the notional/P&L effect of every trade
       that already happened today (trading/portfolio.py).
    5. Entry blocks (news-contradiction / sector-panic "NO
       TRADE today" ledger) -- without this, a restart would
       silently re-open a direction that had been correctly
       blocked earlier in the day for a real, operator-approved
       reason (core/engine.py's entry_blocked). This is the one
       piece where losing it on restart isn't just cosmetic --
       it would let the bot fight the market again after
       already having been told not to.
    6. Momentum universe lock (TOP_N_MOMENTUM_MODE, config.py) --
       without this, a restart after ORB_WINDOW_END would
       recompute the top-25-gainers/top-25-losers shortlist from
       whatever prices happen to be current at restart time,
       possibly a DIFFERENT 50 symbols than the ones actually
       locked at 09:30 (core/momentum_universe.py). The whole
       point of "locked once" is a stable daily list -- silently
       swapping it mid-day on a restart would defeat that.

Written as a single JSON snapshot, tagged with the trading
date. A file from any other date is never loaded -- there is
no cross-day carryover, ever. A missing or corrupt file is
treated as "nothing to recover", never guessed at.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
from datetime import datetime

from core.logger import diagnostic, warn

STATE_PATH = os.path.join("data", "session_state.json")


def save(orb_ranges, open_positions, trailing_stops=None, portfolio=None,
         entry_blocks=None, momentum_universe=None, path=STATE_PATH):
    """
    orb_ranges     : dict symbol -> {"high":, "low":, "complete":}
    open_positions : dict symbol -> {"security_id":, "qty":, "entry_price":,
                      "entry_reason":, "direction":}
    trailing_stops : dict symbol -> {"stop":, "recent":, "direction":} (optional)
    portfolio      : dict {"available_capital":, "realized_pnl":} (optional --
                      trading.portfolio.Portfolio.export_state())
    entry_blocks   : dict symbol -> {direction: reason} (optional --
                      core.engine.Engine.export_entry_blocks())
    momentum_universe : dict {"long": [...], "short": [...]} (optional --
                      core.momentum_universe.MomentumUniverse.export_state())

    Optional params default to {} so existing callers keep
    working. Written atomically (write to a temp file, then
    replace) so a crash mid-write never leaves a half-written,
    corrupt state file behind.
    """
    payload = {
        "date": datetime.now().date().isoformat(),
        "orb_ranges": orb_ranges,
        "open_positions": open_positions,
        "trailing_stops": trailing_stops or {},
        "portfolio": portfolio or {},
        "entry_blocks": entry_blocks or {},
        "momentum_universe": momentum_universe or {},
    }

    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp_path, path)


def load(path=STATE_PATH, today=None):
    """
    Returns (orb_ranges, open_positions, trailing_stops,
    portfolio, entry_blocks, momentum_universe) from a saved state
    file dated today, or a 6-tuple of Nones if there's nothing
    usable -- no file, an unreadable/corrupt file, or a file
    saved on a different day.
    """
    if not os.path.exists(path):
        return None, None, None, None, None, None

    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        warn(f"[STATE] Saved state file unreadable, starting clean: {e}")
        return None, None, None, None, None, None

    today = today or datetime.now().date().isoformat()
    saved_date = payload.get("date")

    if saved_date != today:
        diagnostic(
            f"[STATE] Saved state is from {saved_date}, not today "
            f"({today}) -- ignored, no cross-day carryover."
        )
        return None, None, None, None, None, None

    return (
        payload.get("orb_ranges") or {},
        payload.get("open_positions") or {},
        payload.get("trailing_stops") or {},
        payload.get("portfolio") or {},
        payload.get("entry_blocks") or {},
        payload.get("momentum_universe") or {},
    )
