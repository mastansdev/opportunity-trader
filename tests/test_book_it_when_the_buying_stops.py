"""---- BOOK WHEN MOMENTUM EXHAUSTED. 31 August 2026. ----

    "book when momentum exhausted"                    -- the operator
    "trades without booking profit & keep on holding until close or in
     falling stocks is not what i expect bot to do"   -- 30 August

The bot had three ways out -- stop, target, trailing stop -- and not
one of them says "the move is over". A stock that runs, stalls and
drifts back sits between its stop and its target for as long as it
likes.

Which is exactly what happened. NCC and CDSL were bought on 21 August
and were still open on the 31st. Ten days. CDSL was +3.84% on the 26th
and came within Rs 8 of its target, then finished the period at +1.18%.
Neither level was ever touched. Nothing was broken and nothing
complained; there was simply no rule for it.

The reading was already there and already ignored: still_buying() was
wired to ENTRIES only. On ASHOKA, live, on 31 August it turned false at
12:10 while the price was still near +12%, and the stock finished that
window at +7.45%.

The four refusals below are the whole design. A rule that closes
winners early is a bad rule; a rule that closes LOSERS on a feeling is
a stop loss replaced by a feeling, which is worse.
"""

from datetime import datetime, timedelta

import pytest

from core import engine as eng


class _Engine:
    """The two methods under test, on a stand-in with nothing else."""
    _momentum_is_gone = eng.Engine._momentum_is_gone
    # staticmethod() on the way in, or copying it onto this class turns
    # it back into an instance method and `self` lands in `position`.
    _held_minutes = staticmethod(eng.Engine._held_minutes)

    def __init__(self):
        self.exits = []

    def _exit(self, symbol, price, reason, tick_time):
        self.exits.append((symbol, price, reason))


ENTRY = datetime(2026, 8, 31, 11, 0, 0)
NOW = ENTRY + timedelta(minutes=40)


def _position(entry_price=100.0, qty=50):
    return {"entry_price": entry_price, "qty": qty,
            "entry_time": ENTRY.isoformat(), "direction": "LONG"}


def _flow(monkeypatch, value):
    """value: dict, or None for 'no reading available'."""
    import core.order_flow as of
    monkeypatch.setattr(of, "still_buying", lambda *a, **k: value)


# ------------------------------------------------------------ it fires

def test_a_winner_whose_buying_stopped_is_booked(monkeypatch):
    _flow(monkeypatch, {"still_buying": False, "cum": 3_04_021,
                        "then": 3_28_122})
    e = _Engine()
    assert e._momentum_is_gone("ASHOKA", _position(), 112.0, NOW) is True
    assert e.exits == [("ASHOKA", 112.0, "MOMENTUM_EXHAUSTED")]


def test_a_winner_still_being_bought_is_left_alone(monkeypatch):
    """The rule must not clip a move that is still running. This is the
    common case and the one it would be easiest to get wrong."""
    _flow(monkeypatch, {"still_buying": True, "cum": 5, "then": 1})
    e = _Engine()
    assert e._momentum_is_gone("ASHOKA", _position(), 112.0, NOW) is False
    assert e.exits == []


# -------------------------------------------------- the four refusals

def test_it_never_closes_a_losing_trade(monkeypatch):
    """(1) Flow turning against a position already under water tells us
    nothing the stop does not, and the stop owns that decision. Booking
    a loss because the flow looks tired is a stop loss replaced by a
    feeling."""
    _flow(monkeypatch, {"still_buying": False, "cum": 1, "then": 9})
    e = _Engine()
    assert e._momentum_is_gone("X", _position(), 97.0, NOW) is False
    assert e._momentum_is_gone("X", _position(), 100.0, NOW) is False, (
        "flat is not a winner either")
    assert e.exits == []


def test_no_reading_means_no_exit(monkeypatch):
    """(2) still_buying() returns None when book coverage is too thin to
    classify. A guess must never overrule a gate -- the target and
    trailing checks carry on as normal."""
    _flow(monkeypatch, None)
    e = _Engine()
    assert e._momentum_is_gone("X", _position(), 112.0, NOW) is False
    assert e.exits == []


def test_a_position_younger_than_the_lookback_is_not_judged(monkeypatch):
    """(3) The reading compares now against fifteen minutes ago. A
    position younger than that is being judged against its own entry
    noise. Fifteen is core/order_flow.STILL_BUYING_LOOKBACK, not a
    number anybody picked.

    CDSL on 21 August was rotated out ELEVEN SECONDS after entry. No
    exit rule should ever be able to do that again."""
    _flow(monkeypatch, {"still_buying": False, "cum": 1, "then": 9})
    e = _Engine()
    young = ENTRY + timedelta(seconds=11)
    assert e._momentum_is_gone("CDSL", _position(), 112.0, young) is False
    fourteen = ENTRY + timedelta(minutes=14)
    assert e._momentum_is_gone("CDSL", _position(), 112.0, fourteen) is False
    assert e.exits == []


def test_the_operator_can_turn_it_off(monkeypatch):
    """(4) His switch, not mine."""
    monkeypatch.setattr("config.EXIT_ON_MOMENTUM_EXHAUSTED", False)
    _flow(monkeypatch, {"still_buying": False, "cum": 1, "then": 9})
    e = _Engine()
    assert e._momentum_is_gone("X", _position(), 112.0, NOW) is False
    assert e.exits == []


# ------------------------------------------------------- it never raises

def test_a_broken_flow_read_leaves_the_stop_in_charge(monkeypatch):
    """An exit path that can raise is an exit path that can leave a
    position unmanaged. It falls through to the stop and target."""
    import core.order_flow as of

    def _boom(*a, **k):
        raise sqlite_error()

    def sqlite_error():
        return RuntimeError("order_flow.db is locked")

    monkeypatch.setattr(of, "still_buying", _boom)
    e = _Engine()
    assert e._momentum_is_gone("X", _position(), 112.0, NOW) is False
    assert e.exits == []


def test_an_unreadable_entry_time_does_not_mean_zero_minutes():
    """None means "do not judge", never "zero". Treating an unparseable
    timestamp as a zero-minute hold would let the rule fire on a
    position it knows nothing about."""
    assert _Engine._held_minutes({"entry_time": "not a time"}, NOW) is None
    assert _Engine._held_minutes({}, NOW) is None
    assert _Engine._held_minutes({"entry_time": ENTRY.isoformat()},
                                 None) is None


def test_held_minutes_is_measured_from_the_entry():
    got = _Engine._held_minutes({"entry_time": ENTRY.isoformat()}, NOW)
    assert got == pytest.approx(40.0)


# ------------------------------------------------- it is actually wired

def test_it_runs_before_the_target_and_the_trailing_stop():
    """A position whose buying has stopped must not sit waiting for a
    level it is now drifting away from. Order matters, so it is
    asserted rather than assumed."""
    import inspect

    src = inspect.getsource(eng.Engine._check_trailing_stop)
    where_flow = src.find("_momentum_is_gone")
    where_target = src.find("fixed_target")
    assert where_flow != -1, "the exit is not wired into the tick path"
    assert 0 < where_flow < where_target, (
        "the target is checked before the flow -- a stalled position "
        "will wait for a level it is drifting away from")


def test_the_reason_says_what_happened():
    """Anyone reading this trade back must see WHY it was closed. Every
    other exit reason in this bot names its own rule."""
    assert eng.EXIT_REASON_MOMENTUM_GONE == "MOMENTUM_EXHAUSTED"
