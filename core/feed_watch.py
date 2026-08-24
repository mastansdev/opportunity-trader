"""
==========================================================
Which subscriptions actually delivered anything
==========================================================

    "yes pls complete"
                                -- operator, 8 August 2026

THE QUESTION NOTHING OFFLINE CAN ANSWER
---------------------------------------
19 stocks are marked SUBSCRIBE = YES, carry a security id that Dhan's
own API confirmed, and traded on NSE with real volume -- MOTHERSON did
115 million shares on 7 August -- and our tape has not one bar for any
of them.

    tools/silent_subscriptions.py:
        "Nothing offline can tell the difference between 'Dhan never
         sent it' and 'we dropped it'. Do not guess -- measure it."

That is right, and it has been the answer for days, which is why the
question is still open. #38 was closed on an earlier day with
MOTHERSON still silent -- closed because the code ran, not because the
result was checked.

WHAT THIS DOES
--------------
Records the security id of every tick that arrives, and at 09:45 says
plainly which subscriptions have delivered NOTHING in the first half
hour. One line per silent name, once, then it stops talking.

That turns a week of guessing into one morning of fact:

    a name here    -> Dhan is not sending it. The id, the segment or
                      the entitlement is wrong, and it belongs out of
                      the universe until it is fixed.

    NOT here, yet no bars in the store
                   -> Dhan sent it and WE dropped it, somewhere between
                      on_message and core/candle_recorder.py. Our bug.

Either answer ends the question. Neither can be reached from a file.

WHY IT CANNOT BREAK THE FEED
----------------------------
One set.add() per tick and one comparison per session. Every entry
point swallows its own exceptions and returns, because a diagnostic
that can stop the tick loop is worth less than the diagnosis.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import time as dtime

# Half an hour of the busiest session there is. A liquid stock that has
# not printed once by here is not quiet, it is absent.
REPORT_AT = dtime(9, 45)

# Never more than this many names in one message. If 900 are silent the
# problem is the connection, not the instruments, and 900 lines of log
# would bury that.
MAX_NAMED = 40

# ---- HOW LONG HAVE WE BEEN LISTENING? 24 August 2026. ----
#
# The wall-clock gate above answers "is it late enough in the session",
# and the 10% gate answers "has enough of the book spoken". Neither
# answers the one that matters after a RESTART: has THIS process been
# subscribed long enough for silence to mean anything?
#
# 24 August, main.py restarted at 14:45. One minute later:
#
#     [FEED] 1162 of 1291 subscriptions have delivered NOTHING by
#            09:45 (129 are live). Dhan is not sending these
#
# Every one of those 1,291 symbols went on to tick in that same
# process -- the log shows a closed candle for all of them. The feed
# was perfectly healthy and the message named ATGL, ADANIENT,
# ADANIGREEN, ADANIPOWER and 20MICRONS among 1,162 others as dead. He
# read the terminal and asked why those stocks were not tradeable.
#
# 129 live was not a coincidence: it is exactly len(resolved) // 10,
# the 10% threshold, cleared sixty seconds after subscribing.
#
# This module's own docstring already says why that matters: "a
# diagnostic that cries wolf is worse than none". It had been taught
# not to trust the tick's clock; it had not been taught that its own
# uptime is part of the question.
MIN_LISTEN_MINUTES = 30.0

_seen = set()
_said = False
_first_tick_at = None


def saw(security_id):
    """Call on every stock tick. Never raises."""
    global _first_tick_at
    try:
        if security_id is not None:
            _seen.add(str(security_id))
            if _first_tick_at is None:
                from core.feed_clock import now_ist
                _first_tick_at = now_ist()
    except Exception:                                          # noqa: BLE001
        pass


def heard_from(security_id):
    """Has this instrument delivered anything this session?"""
    return str(security_id) in _seen


def report(resolved, now=None, log=None):
    """Name the subscriptions that have delivered nothing. Once.

    `resolved` is main.py's {symbol: security_id}. Returns the list of
    silent symbols, or [] when it is too early or already said.

    ==========================================================
    IT CRIED WOLF ON ITS FIRST MORNING.  10 August 2026.
    ==========================================================
    07:15, pre-open. The heartbeat said:

        ticks: 1223 (+1223 in last 60s)

    and this said:

        1222 of 1223 subscriptions have delivered NOTHING by 09:45

    Both from the same process, one line apart. Two faults, and the
    same root: I trusted a timestamp I had not checked.

    1. `now` came from the TICK, and a pre-open Dhan packet carries
       the LAST TRADED time -- Friday 15:30 -- which sails past the
       09:45 gate on the first tick of Monday.

    2. It then ran on the FIRST tick, when exactly one symbol had been
       seen, and _said = True meant it never corrected itself.

    So it named 1,222 healthy instruments as dead. A diagnostic that
    cries wolf is worse than none: he goes hunting a feed that is
    working, on the one morning he has no time.

    Now: the WALL clock, never the tick's. And the market must have
    been open long enough for a quiet instrument to be genuinely quiet.
    """
    global _said
    try:
        if _said or not resolved:
            return []
        # The wall clock in IST. NOT the tick's timestamp -- see above.
        from core.feed_clock import now_ist
        clock = now_ist().time()
        if clock < REPORT_AT:
            return []
        # After the open, and after enough of the book has spoken that
        # silence means something. On a live morning the great majority
        # of 1,223 subscriptions tick within the first minutes; if
        # almost nothing has, the connection is the story, not the
        # instruments, and that is a different message.
        if len(_seen) < max(20, len(resolved) // 10):
            return []
        # And we must have been listening long enough that a quiet
        # instrument is genuinely quiet -- not merely subscribed a
        # minute ago. See MIN_LISTEN_MINUTES.
        if _first_tick_at is None:
            return []
        listened = (now_ist() - _first_tick_at).total_seconds() / 60.0
        if listened < MIN_LISTEN_MINUTES:
            return []
        silent = sorted(symbol for symbol, sid in resolved.items()
                        if str(sid) not in _seen)
        _said = True
        if log is None:
            from core.logger import decision, warn
        else:
            decision = warn = log
        live = len(resolved) - len(silent)
        if not silent:
            decision(f"[FEED] All {len(resolved)} subscriptions are "
                     f"delivering.")
            return []
        warn(f"[FEED] {len(silent)} of {len(resolved)} subscriptions have "
             f"delivered NOTHING by {REPORT_AT:%H:%M} ({live} are live). "
             f"Dhan is not sending these -- the id, segment or "
             f"entitlement is wrong, and they cannot be traded today.")
        for symbol in silent[:MAX_NAMED]:
            warn(f"[FEED]   {symbol} (id {resolved[symbol]}) silent")
        if len(silent) > MAX_NAMED:
            warn(f"[FEED]   ... and {len(silent) - MAX_NAMED} more. That "
                 f"many silent names is a CONNECTION problem, not an "
                 f"instrument problem.")
        return silent
    except Exception:                                          # noqa: BLE001
        return []


def reset():
    """New session."""
    global _said
    _seen.clear()
    _said = False
