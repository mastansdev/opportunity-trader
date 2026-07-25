"""
==========================================================
Dhan Time
==========================================================

Dhan's live feed reports LTT (Last Traded Time) as a bare
"HH:MM:SS" string -- no date. This module used to add a
+5:30 IST_OFFSET here, on the assumption (from the dhanhq
SDK source: utc_time() calls datetime.utcfromtimestamp())
that LTT is UTC and needs shifting into IST.

CORRECTED 2026-07-23, from live evidence, not source
reading: during the first live session, every ORB range came
back empty and orb_engine.py never fired a single breakout
all morning, despite ticks visibly flowing the whole time
(candle logs proved it). Added a diagnostic that logs the
raw parsed tick time -- it showed t=15:40:35 within minutes
of restart, while the operator's own PC clock read 10:14 IST
at that exact moment (confirmed directly, not assumed). The
gap between those two numbers is ~5:26-5:30 -- the IST_OFFSET
being added to a value that was already IST, double-shifting
every tick ~5.5 hours into the future. That mismatch put every
real 09:15-09:30 tick past ORB_WINDOW_END_T (09:30) from the
code's point of view, which is exactly why _ranges stayed
empty all session -- see core/orb_engine.py's own history for
the rest of that investigation.

Whatever the SDK's utc_time() method name implies, the LTT
value actually arriving over this feed/version is already IST
wall-clock time. This function now just anchors it to today's
date -- no shift. If Dhan's feed behavior ever changes back,
the same live symptom (empty ORB ranges, ticks flowing fine)
combined with a direct operator-clock check is what will catch
it again; that's why this docstring records the exact method
used to confirm it, not just the conclusion.

Every other module in this bot (MARKET_OPEN, SQUARE_OFF_TIME,
MAX_TICK_STALENESS_SECONDS) works in IST wall-clock time, so
this is still the one place any LTT conversion should happen --
nothing else should touch LTT directly. Feeding a raw
"HH:MM:SS" string straight into datetime.fromisoformat() would
still crash on every tick (no date component); that part of
the original reasoning stands.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import datetime


def parse_ltt_to_ist(ltt_raw, today=None):
    """
    ltt_raw : "HH:MM:SS" string from Dhan -- already IST
              wall-clock time-of-day (see module docstring
              for how that was confirmed live). None/empty
              returns None -- caller decides the fallback,
              never guess here.
    today   : date to anchor the time to. Defaults to the
              local machine's current date (this bot is run
              from IST, so "today" in local wall-clock terms
              is correct for the trading session).

    Returns a naive datetime, safe to compare directly
    against MARKET_OPEN_T, SQUARE_OFF_T, and datetime.now().
    """
    if not ltt_raw:
        return None

    today = today or datetime.now().date()
    ist_time = datetime.strptime(ltt_raw, "%H:%M:%S").time()
    return datetime.combine(today, ist_time)
