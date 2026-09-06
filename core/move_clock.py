"""
==========================================================
When did THIS stock's move begin
==========================================================

    "not even min or time is answer ; volume settles this & reason
     behind that volumes ; any news, events, or any other reason or
     purely price action"       -- the operator, 6 September 2026

    "no rupee will go into trade unless there is potential to move"

He is right that a clock is not the answer, and this does not pretend
to be one. It RECORDS, it decides nothing, and no gate imports it.

WHY IT IS WORTH RECORDING ANYWAY. Friday 4 September, every trade
measured against the minute its own volume first jumped:

    bot arrived within 30 min of the move starting
        17 trades   11 up   6 down     Rs  21,052
    bot arrived MORE than 30 minutes late
         7 trades    0 up   7 down     Rs -15,083

Seven trades, not one winner. RESPONIND's move began 09:42 at 151.8;
the bot bought at 13:26 at 172.1, after 13.4% of it had already gone.
That is his own complaint stated as a number --

    "instant fill on free seat by 1 hour old sort list stock"

-- and it cannot be answered forward, because nothing writes it down.
Friday's 27 trades carry a blank here. It took minute-by-minute
history and an afternoon to reconstruct one day by hand.

SEVEN TRADES IS NOT A RULE, and this deliberately is not one. Every
parameter fitted on 18-27 August died on the eleven sessions it had
not seen. So: record now, decide later, out of his own book.

WHAT COUNTS AS THE START. The bot's own definition of moving, not a
new one -- the first cycle today where the stock's recent window is
positive by at least ranker.MIN_RECENT_PCT AND it is carrying more
than its normal volume. Reusing those numbers is the point: a second
definition of "moving" would drift from the one the gate uses.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import datetime

from core.logger import diagnostic

# The bot's own bar for "the recent window is alive". Imported, never
# redeclared -- see the module docstring.
try:
    from core.ranker import MIN_RECENT_PCT
except Exception:                                          # noqa: BLE001
    MIN_RECENT_PCT = 0.15

# More than its own normal volume. Well below MIN_VOLUME_RATIO's bar
# for a TRADE, because this is asking when the move BEGAN, not whether
# it is worth buying -- by the time it clears the trading bar the
# beginning has already passed, which is the whole complaint.
MOVE_START_VOLUME_X = 1.5

#: {day: {symbol: first datetime seen moving}}
_FIRST = {}


def reset():
    """Forget everything. Tests, and a process crossing midnight."""
    _FIRST.clear()


def _today(now):
    return (now or datetime.now()).date().isoformat()


def note(rows, now=None):
    """Watch a cycle's rows and remember who started moving, and when.

    Called once per rebuild with whatever the board is holding. Cheap
    by construction: one dict lookup a row, and a symbol is written
    once a day.

    Never raises. Bookkeeping must not be able to stop a cycle.
    """
    stamp = now or datetime.now()
    try:
        day = _FIRST.setdefault(_today(stamp), {})
        for row in rows or ():
            try:
                symbol = str(row.get("symbol") or "").strip().upper()
                if not symbol or symbol in day:
                    continue
                recent = row.get("recent_pct")
                volume = row.get("volume_x")
                if recent is None or volume is None:
                    continue
                if float(recent) >= MIN_RECENT_PCT and \
                        float(volume) >= MOVE_START_VOLUME_X:
                    day[symbol] = stamp
            except (TypeError, ValueError, AttributeError):
                continue
    except Exception as exc:                               # noqa: BLE001
        diagnostic(f"[MOVECLOCK] could not read a cycle ({exc})")
    return len(_FIRST.get(_today(stamp), {}))


def began(symbol, now=None):
    """When this stock was first seen moving today, or None."""
    day = _FIRST.get(_today(now)) or {}
    return day.get(str(symbol or "").strip().upper())


def age_minutes(symbol, now=None):
    """How long ago this stock's move began, in minutes, or None.

    None means NOT KNOWN -- the bot was not watching when it started,
    or it has not started. It never means zero, and a caller must not
    read it as "fresh".
    """
    stamp = now or datetime.now()
    first = began(symbol, stamp)
    if first is None:
        return None
    try:
        return max(0.0, round((stamp - first).total_seconds() / 60.0, 1))
    except Exception:                                      # noqa: BLE001
        return None


def watching(now=None):
    """How many symbols are on today's clock. For the board."""
    return len(_FIRST.get(_today(now)) or {})
