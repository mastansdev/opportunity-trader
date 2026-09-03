"""---- IT SOLD FIRSTCRY BEFORE IT BOUGHT IT. 3 September 2026. ----

    FIRSTCRY   bought 09:35:21 at 177.49, stop 172.08
               "sold" 09:35:05 at 173.01          -Rs 2,164

Sixteen seconds before it was bought, at a price the stock never
printed, on a breach of a stop it never reached. FIRSTCRY's entire
3 September was 176.09 to 180.89 across 335 board rows, and it closed
at 180.48. The recorded holding_seconds was -16.017868.

WHY THE ROW LOOKED LIKE A BREACH. FIRSTCRY's PREVIOUS close was
170.83 -- below the 172.08 stop the bot had just set. So any row
carrying the previous session's low reports a breach the instant it is
read, without anything odd happening today at all. Same shape as the
stale rows this session fixed in core/tick_ohlc.

WHY THE FUNCTION SHOULD HAVE CAUGHT IT. Its own docstring says the
breach is ours "if it extends past our stop AFTER we entered", and it
declares that it "fails OPEN in every uncertain case -- because a
false exit is a real loss". It never tested the AFTER. A tick at or
before the entry cannot evidence a breach that is ours.

This is the largest single loss of the day and none of it was a market
move.
"""

from datetime import datetime, timedelta

from core.engine import EXIT_REASON_MISSED_STOP, Engine

ENTRY = datetime(2026, 9, 3, 9, 35, 21)


def _engine(tick_time, day_low):
    eng = object.__new__(Engine)
    eng.open_positions = {"FIRSTCRY": {
        "entry_price": 177.49, "qty": 483, "direction": "LONG",
        "entry_time": ENTRY.isoformat(),
        "exchange_extreme_at_entry": (176.09, 180.10),
    }}
    eng.circuit_monitor = None
    eng._exchange_extreme = lambda sym: (day_low, 180.10)
    eng._live_stop_price = lambda sym, pos: 172.08
    eng.exits = []
    eng._exit = lambda sym, px, why, t: eng.exits.append((sym, px, why))
    return eng


def test_a_tick_from_before_the_entry_cannot_prove_a_breach():
    """THE BUG, with the day's real numbers. The 170.83 low is
    FIRSTCRY's PREVIOUS close, which is what a stale row reports."""
    eng = _engine(ENTRY - timedelta(seconds=16), day_low=170.83)
    assert eng._check_missed_stop("FIRSTCRY", 173.01, ENTRY -
                                  timedelta(seconds=16)) is False
    assert eng.exits == [], "it sold a position sixteen seconds before buying it"


def test_a_tick_at_the_very_moment_of_entry_is_not_after_it():
    """Equal is not after. The baseline is taken AT entry, so a
    reading from that same instant compares a row with itself."""
    eng = _engine(ENTRY, day_low=170.83)
    assert eng._check_missed_stop("FIRSTCRY", 173.01, ENTRY) is False


def test_a_real_breach_after_entry_still_closes_the_position():
    """The safety net must still catch what it was built for: a stock
    that trades through the stop with no tick in our feed showing it."""
    later = ENTRY + timedelta(minutes=12)
    eng = _engine(later, day_low=171.40)
    assert eng._check_missed_stop("FIRSTCRY", 173.50, later) is True
    assert eng.exits and eng.exits[0][2] == EXIT_REASON_MISSED_STOP


def test_an_unreadable_entry_time_refuses_rather_than_sells():
    """_held_minutes returns None when it cannot work the time out.
    None means do not judge -- and this rule's stated posture is that
    a false exit is a real loss."""
    later = ENTRY + timedelta(minutes=12)
    eng = _engine(later, day_low=171.40)
    eng.open_positions["FIRSTCRY"]["entry_time"] = "not a timestamp"
    assert eng._check_missed_stop("FIRSTCRY", 173.50, later) is False
