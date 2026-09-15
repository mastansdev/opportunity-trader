"""---- IT SOLD AFCONS ON A LOW FROM BEFORE THE STOP. 15 September 2026. ----

    AFCONS  bought 09:16 at 275.99, first stop 267.58
            day low 268.70 printed during the 09:19-09:30 freeze
            09:32:35 trail RAISED the stop to 282.28
            09:32:35 MISSED_STOP "traded to 268.70, through 282.28"
                     -- sold at 284.56 while the real price was ~299

The low did not breach the stop that was in force when it printed
(267.58). It only "breached" a stop set minutes later. A low already on
the board when a stop is set cannot be evidence that stop was missed.
"""

from datetime import datetime, timedelta

from core.engine import EXIT_REASON_MISSED_STOP, Engine

ENTRY = datetime(2026, 9, 15, 9, 16, 35)
LATER = ENTRY + timedelta(minutes=16)


def _engine():
    eng = object.__new__(Engine)
    eng.open_positions = {"AFCONS": {
        "entry_price": 275.99, "qty": 591, "direction": "LONG",
        "entry_time": ENTRY.isoformat(),
        "exchange_extreme_at_entry": (274.20, 276.45),
    }}
    eng.circuit_monitor = None
    eng.state = {"low": 274.20, "stop": 267.58}
    eng._exchange_extreme = lambda sym: (eng.state["low"], 304.55)
    eng._live_stop_price = lambda sym, pos: eng.state["stop"]
    eng.exits = []
    eng._exit = lambda sym, px, why, t: eng.exits.append((sym, px, why))
    return eng


def test_afcons_the_real_sequence_does_not_sell():
    eng = _engine()
    # 09:25 -- the low prints, ABOVE the stop in force (267.58)
    eng.state["low"] = 268.70
    assert eng._check_missed_stop("AFCONS", 280.0, LATER) is False
    # 09:32:35 -- the trail raises the stop past that old low
    eng.state["stop"] = 282.28
    assert eng._check_missed_stop("AFCONS", 284.70, LATER) is False
    assert eng.exits == [], "sold on a low that happened before the stop existed"


def test_a_new_low_through_the_raised_stop_still_sells():
    """The net must still catch a real miss after the stop moved."""
    eng = _engine()
    eng.state["low"] = 268.70
    eng._check_missed_stop("AFCONS", 280.0, LATER)
    eng.state["stop"] = 282.28
    eng._check_missed_stop("AFCONS", 284.70, LATER)
    # a genuinely new low, below the new stop, after it was raised
    eng.state["low"] = 266.00
    assert eng._check_missed_stop("AFCONS", 281.0, LATER) is True
    assert eng.exits[0][2] == EXIT_REASON_MISSED_STOP


def test_a_breach_of_the_first_stop_still_sells():
    """No stop change: the entry baseline applies exactly as before."""
    eng = _engine()
    eng.state["low"] = 265.00
    assert eng._check_missed_stop("AFCONS", 270.0, LATER) is True
