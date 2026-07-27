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
         entry_blocks=None, momentum_universe=None,
         orb_unreliable=None, path=STATE_PATH):
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
    orb_unreliable : list of symbols whose feed went dark INSIDE their own
                      opening-range window (optional -- core.market_data
                      .MarketData.export_orb_unreliable())

    Optional params default to {} so existing callers keep
    working. Written atomically (write to a temp file, then
    replace) so a crash mid-write never leaves a half-written,
    corrupt state file behind.

    WHY orb_unreliable IS SAVED (added 2026-07-27, operator-found)
    -------------------------------------------------------------
    A symbol whose feed goes quiet during 09:15-09:30 has an opening
    range built from incomplete data -- it may have missed the real
    high or low entirely (the SONACOMS incident). MarketData flags it
    and the engine then refuses STRUCTURAL entries in it for the rest
    of the session. Correct behaviour.

    But the flag lived only in memory. On 2026-07-27:

        09:16  TBZ went stale INSIDE its own ORB window -- range
               flagged unreliable; structural entries skipped for it
               today.
        14:59  PAPER BUY TBZ qty=729 @ 274.15 (STRUCTURAL_LONG_BREAKOUT)

    Two restarts in between wiped the flag, and the bot took the exact
    trade it had already ruled out that morning -- on a range built
    around a gap in the feed. It happened to make money, which is
    worse than losing: a rule that silently stops applying is not a
    rule, and a profit from one is not evidence of anything.
    """
    payload = {
        "date": datetime.now().date().isoformat(),
        "orb_ranges": orb_ranges,
        "open_positions": open_positions,
        "trailing_stops": trailing_stops or {},
        "portfolio": portfolio or {},
        "entry_blocks": entry_blocks or {},
        "momentum_universe": momentum_universe or {},
        "orb_unreliable": sorted(orb_unreliable or []),
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


def load_orb_unreliable(path=STATE_PATH, today=None):
    """Symbols whose feed went dark inside their own opening-range
    window earlier today. Empty list if there's no usable state.

    A SEPARATE function rather than a seventh element of load()'s
    tuple, deliberately: eight call sites unpack that tuple by
    position, one of them being main.py's restart path. Widening it
    would mean touching every one of them to add a flag, and the
    restart path is the last thing that should be broken while fixing
    a restart bug. Additive is safer than elegant here.

    Same day-check as load(): a flag from yesterday means nothing."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    today = today or datetime.now().date().isoformat()
    if payload.get("date") != today:
        return []
    return list(payload.get("orb_unreliable") or [])
