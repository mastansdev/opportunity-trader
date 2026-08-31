"""---- THE EXIT RULE, IN HIS WORDS. 31 August 2026. ----

    "when the buying dries up, book it. no one can book all the run
     stock did. its never gonna happen . we are here to trade as long
     as stock is in momentum thats it"

Not a target and not a trailing stop. Both of those ask the PRICE where
to get out, and the price is the last thing to know -- the buying stops
first, and the price follows.

WHAT IT REPLACES
----------------
Nothing, and that is the point. The bot's own entries had no way out
except a stop or the 15:15 square-off, because _atr_entry_sizing()
returns a target of None by design. So every winner rode to the close.
On 31 August its nine picks showed ASHOKA +7.27% at 10:17 and
PRECWIRE +3.46%, and eight of the nine finished below where it would
have bought.

INTRADAY, WHICH IS THE POINT
----------------------------
The reading is computed from this session's own ticks and resets every
morning. It is the same shape as the bot: flat by 15:15, nothing
carried.

THE ENGINE IS HANDED THE CHECK, IT DOES NOT GO LOOKING
------------------------------------------------------
The flow store records; it does not decide. When an earlier version
imported it directly inside core/engine.py, a unit test read the real
data/order_flow.db and closed a working position that was up twice its
risk. main.py wires the function in; an engine built anywhere else has
no buying check at all and every other exit behaves exactly as before.
"""

from datetime import datetime, timedelta

import pytest

from core import engine as eng


class _Engine:
    _buying_dried_up = eng.Engine._buying_dried_up
    # staticmethod() on the way in, or copying it onto this class turns
    # it back into an instance method and `self` lands in `position`.
    _held_minutes = staticmethod(eng.Engine._held_minutes)

    def __init__(self, position=None, check=None):
        self.open_positions = {"ASHOKA": position} if position else {}
        if check is not None:
            self.buying_check = check
        self.exits = []

    def _exit(self, symbol, price, reason, tick_time):
        self.exits.append((symbol, price, reason))
        self.open_positions.pop(symbol, None)


ENTRY = datetime(2026, 8, 31, 9, 16, 0)
LATER = ENTRY + timedelta(minutes=61)          # 10:17, ASHOKA's high


def _position(entry_price=120.26, qty=443):
    return {"entry_price": entry_price, "qty": qty,
            "entry_time": ENTRY.isoformat(), "direction": "LONG"}


def _stopped(**over):
    """A reading that says the buyers have stopped."""
    out = {"still_buying": False, "delta": 3_04_021, "was": 3_28_122}
    out.update(over)
    return out


# ------------------------------------------------------------ it books

def test_a_winner_whose_buyers_stopped_is_booked():
    e = _Engine(_position(), lambda s: _stopped())
    assert e._buying_dried_up("ASHOKA", 129.00, LATER) is True
    assert e.exits == [("ASHOKA", 129.00, "BUYING_DRIED_UP")]


def test_a_winner_still_being_bought_is_left_to_run():
    """"we are here to trade as long as stock is in momentum". While
    the buying holds, the position holds."""
    e = _Engine(_position(), lambda s: {"still_buying": True})
    assert e._buying_dried_up("ASHOKA", 129.00, LATER) is False
    assert e.exits == []


# --------------------------------------------------------- three refusals

def test_it_never_touches_a_losing_trade():
    """A loser belongs to the stop. Selling one because the flow looks
    tired is a stop loss replaced by a feeling -- the exact thing this
    bot exists to remove from his trading."""
    e = _Engine(_position(), lambda s: _stopped())
    assert e._buying_dried_up("ASHOKA", 118.00, LATER) is False
    assert e._buying_dried_up("ASHOKA", 120.26, LATER) is False, "flat is not a win"
    assert e.exits == []


def test_no_reading_means_no_action():
    """still_buying() returns None when the book is too thin to
    classify. None means nothing, not "sell"."""
    for answer in (None, {}, {"still_buying": None}):
        e = _Engine(_position(), lambda s, a=answer: a)
        assert e._buying_dried_up("ASHOKA", 129.00, LATER) is False
        assert e.exits == []


def test_not_within_the_first_fifteen_minutes():
    """The reading compares now with fifteen minutes ago; below that it
    is the noise around its own entry. CDSL was once bought and closed
    eleven seconds later."""
    e = _Engine(_position(), lambda s: _stopped())
    assert e._buying_dried_up("ASHOKA", 129.00,
                              ENTRY + timedelta(seconds=11)) is False
    assert e._buying_dried_up("ASHOKA", 129.00,
                              ENTRY + timedelta(minutes=14)) is False
    assert e.exits == []


# ------------------------------------------------------ it cannot misfire

def test_an_engine_with_no_check_wired_does_nothing():
    """Every other exit must behave exactly as it did before. An engine
    built without the check is not a broken engine."""
    e = _Engine(_position())
    assert e._buying_dried_up("ASHOKA", 129.00, LATER) is False


def test_a_check_that_raises_leaves_the_stop_in_charge():
    """An exit path that can raise is an exit path that can leave a
    position unmanaged."""
    def _boom(symbol):
        raise RuntimeError("order flow store is locked")

    e = _Engine(_position(), _boom)
    assert e._buying_dried_up("ASHOKA", 129.00, LATER) is False
    assert e.exits == []


def test_a_symbol_that_is_not_held_is_ignored():
    e = _Engine(_position(), lambda s: _stopped())
    assert e._buying_dried_up("NOTHELD", 129.00, LATER) is False


def test_an_unreadable_entry_time_is_not_treated_as_zero_minutes():
    """None means "do not judge", never "zero". Treating an unparseable
    timestamp as a zero-minute hold would let the rule fire on a
    position it knows nothing about."""
    assert _Engine._held_minutes({"entry_time": "rubbish"}, LATER) is None
    assert _Engine._held_minutes({}, LATER) is None
    assert _Engine._held_minutes({"entry_time": ENTRY.isoformat()}, None) is None
    assert _Engine._held_minutes({"entry_time": ENTRY.isoformat()},
                                 LATER) == pytest.approx(61.0)


# --------------------------------------------------------- it is wired

def test_the_engine_does_not_import_the_flow_store():
    """The store records; it does not decide. When engine.py imported it
    directly, a unit test read the real data/order_flow.db and closed a
    position that was up twice its risk."""
    from pathlib import Path

    src = Path(eng.__file__).read_text(encoding="utf-8", errors="ignore")
    assert "from core.order_flow" not in src
    assert "import order_flow" not in src


def test_main_hands_the_check_to_the_engine():
    """A rule nothing wires is a rule that never runs. This is the
    junction; without it the bot holds every winner to 15:15 again and
    nothing anywhere reports a problem."""
    from pathlib import Path

    src = Path("main.py").read_text(encoding="utf-8", errors="ignore")
    assert "engine.buying_check = still_buying" in src, (
        "main.py no longer wires the buying check -- winners will ride "
        "to the close again")


def test_it_runs_before_the_target_and_the_trailing_stop():
    """A position whose buyers have gone must not sit waiting for a
    level it is drifting away from."""
    import inspect

    src = inspect.getsource(eng.Engine._check_trailing_stop)
    where_flow = src.find("_buying_dried_up")
    where_target = src.find("fixed_target")
    assert where_flow != -1, "the exit is not in the tick path"
    assert 0 < where_flow < where_target
