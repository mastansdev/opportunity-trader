"""
==========================================================
Can this program START in the mode it will be started in?
==========================================================

31 July 2026, 09:00. The operator flipped TRADING_MODE to "LIVE" for
the first real order and main.py died before the market opened:

    RuntimeError: TRADING_MODE is LIVE but no Dhan client was provided.
    Refusing to start.

1,637 tests passed that morning. Not one of them caught it.

WHY THEY ALL MISSED IT
----------------------
The seam was tested from BOTH SIDES and never ACROSS:

    tests/test_live_execution.py   built LiveExecution(FakeDhan())
                                   DIRECTLY -- bypassing Engine
    every other engine test        built Engine() in PAPER, where the
                                   dhan_client argument is unused

So `Execution` was proven to work with a client, and `Engine` was
proven to work without one, and nobody ever asked whether Engine could
GIVE Execution a client. It could not: there was no parameter for it.

That is the shape of this whole class of bug. Two components, each
correct, each tested, joined by a wire nobody drew.

THE RULE THIS FILE ENCODES
--------------------------
A guard rail that has never been executed is not a guard rail, it is a
comment. Every one of these tests actually CONSTRUCTS the object, in
LIVE, the way main.py does.

Author : H&M Opportunity Trader
==========================================================
"""

import inspect

import pytest

import core.engine as engine_module
import trading.execution as execution_module
from core.engine import Engine
from trading.execution import Execution


class FakeDhan:
    """A broker that would record an order if anyone sent one.

    Nothing here reaches a network. If a test in this file ever ends
    with calls non-empty, something constructed an order during
    STARTUP, which would be its own emergency.
    """

    def __init__(self):
        self.calls = []

    def place_order(self, **kwargs):                       # pragma: no cover
        self.calls.append(kwargs)
        return {"data": {"orderId": "NEVER"}}

    def get_order_by_id(self, order_id):                   # pragma: no cover
        return {"data": {"orderStatus": "TRADED"}}


def _live(monkeypatch):
    """Put trading/execution.py into LIVE without touching config.py.

    Both names are read at IMPORT time (`from config import ...`), so
    patching config itself would be too late. Patching the module's own
    globals is what actually changes the behaviour under test.
    """
    monkeypatch.setattr(execution_module, "TRADING_MODE", "LIVE")
    monkeypatch.setattr(execution_module,
                        "I_UNDERSTAND_THIS_PLACES_REAL_ORDERS", True)


# ---------------------------------------------------------------
# 1. THE EXACT FAILURE OF 31 JULY
# ---------------------------------------------------------------
def test_engine_accepts_a_dhan_client():
    """The parameter exists at all.

    This is the entire bug in one assertion. On 31 July this failed:
    Engine.__init__ had eighteen keyword arguments and none of them
    was the broker.
    """
    params = inspect.signature(Engine.__init__).parameters
    assert "dhan_client" in params, (
        "Engine cannot be given a broker. LIVE mode will refuse to "
        "start, as it did on 31 July 2026.")


def test_engine_in_live_mode_starts_when_given_a_client(monkeypatch):
    """The reproduction. Without the fix this raises RuntimeError."""
    _live(monkeypatch)
    engine = Engine(dhan_client=FakeDhan())
    assert engine.execution.mode == "LIVE"


def test_engine_in_live_mode_still_refuses_without_a_client(monkeypatch):
    """The guard must SURVIVE the fix.

    It would be an easy and catastrophic over-correction to make LIVE
    fall back to paper when no client is present. A bot the operator
    believes is live and which is only pretending is the worse failure
    -- he would sit watching fills that never happened.
    """
    _live(monkeypatch)
    with pytest.raises(RuntimeError) as raised:
        Engine()
    assert "no Dhan client" in str(raised.value)


def test_live_still_needs_both_switches(monkeypatch):
    """One switch is one typo away from spending money. Two is a
    decision. A client on its own is not consent."""
    monkeypatch.setattr(execution_module, "TRADING_MODE", "LIVE")
    monkeypatch.setattr(execution_module,
                        "I_UNDERSTAND_THIS_PLACES_REAL_ORDERS", False)
    with pytest.raises(RuntimeError):
        Engine(dhan_client=FakeDhan())


# ---------------------------------------------------------------
# 2. PAPER MUST NOT CHANGE
# ---------------------------------------------------------------
def test_paper_ignores_the_client_completely():
    """Passing a broker must not make a paper session live.

    main.py now passes dhan_client UNCONDITIONALLY -- deliberately, so
    the two modes are not different code paths that get tested
    different amounts. That is only safe if PAPER genuinely ignores it.
    """
    fake = FakeDhan()
    engine = Engine(dhan_client=fake)   # conftest pins tests to PAPER
    assert engine.execution.mode == "PAPER"
    assert fake.calls == []
    assert not hasattr(engine.execution.executor, "dhan")


def test_constructing_an_engine_sends_no_orders(monkeypatch):
    """Startup must be silent at the broker. Nothing about building an
    object should reach an exchange."""
    _live(monkeypatch)
    fake = FakeDhan()
    Engine(dhan_client=fake)
    assert fake.calls == []


# ---------------------------------------------------------------
# 3. THE DRIFT CHECK NEEDS A PRICE, AND REFUSES WITHOUT ONE
# ---------------------------------------------------------------
# Every Engine below is handed a FakeDhan even where the test is not
# about the broker. config.py's TRADING_MODE is real and the operator
# changes it -- a test that only passes while he happens to be in PAPER
# is a test that disappears on exactly the day it is needed.
def test_live_execution_is_given_a_price_lookup(monkeypatch):
    """live_execution.py refuses to send a market order when it cannot
    read a live price -- "no live price feed to check against". Wire it
    without one and every single order is refused, which looks exactly
    like a broken broker."""
    _live(monkeypatch)
    engine = Engine(dhan_client=FakeDhan())
    assert engine.execution.executor._price_lookup is not None
    assert engine.execution.executor._open_count is not None


def test_price_lookup_prefers_the_tick_feed():
    """The tick feed is what the dashboard was showing when the button
    was pressed. The REST snapshot is seconds old; it is the fallback,
    not the source."""

    class Feed:
        def get_latest_price(self, symbol):
            return 307.95

    class Monitor:
        def get_snapshot(self):
            return {"REDINGTON": {"last_price": 999.0}}

    engine = Engine(market_data=Feed(), circuit_monitor=Monitor(),
                    dhan_client=FakeDhan())
    assert engine._live_price_for_order("REDINGTON") == 307.95


def test_price_lookup_falls_back_to_the_snapshot():
    class Monitor:
        def get_snapshot(self):
            return {"REDINGTON": {"last_price": 307.95}}

    engine = Engine(circuit_monitor=Monitor(), dhan_client=FakeDhan())
    assert engine._live_price_for_order("REDINGTON") == 307.95


def test_price_lookup_returns_none_rather_than_a_stale_guess():
    """None means REFUSE downstream. That is the correct answer when
    nothing is known -- it must never become 0.0 or a last-seen value,
    because both would pass the drift check."""
    engine = Engine(dhan_client=FakeDhan())
    assert engine._live_price_for_order("REDINGTON") is None


def test_price_lookup_survives_a_broken_feed():
    """Called from inside the order path. An exception here would
    surface as a failed ORDER, not as a failed price read."""

    class Exploding:
        def get_latest_price(self, symbol):
            raise RuntimeError("feed is down")

    engine = Engine(market_data=Exploding(), dhan_client=FakeDhan())
    assert engine._live_price_for_order("REDINGTON") is None


# ---------------------------------------------------------------
# 4. THE POSITION COUNT MUST BE READ LATE
# ---------------------------------------------------------------
def test_open_position_count_reads_the_current_book(monkeypatch):
    """A number captured at construction is always zero -- Engine
    builds Execution before it builds self.open_positions. The ceiling
    would then never bind."""
    _live(monkeypatch)
    engine = Engine(dhan_client=FakeDhan())
    count = engine.execution.executor._open_count
    assert count() == 0
    engine.open_positions["REDINGTON"] = {"qty": 1}
    assert count() == 1, (
        "the open-position ceiling is reading a stale snapshot")


# ---------------------------------------------------------------
# 5. MAIN.PY MUST ACTUALLY PASS IT
# ---------------------------------------------------------------
def test_main_passes_the_client_to_the_engine():
    """The parameter existing is worth nothing if main.py omits it --
    which is precisely the state the code was in on 31 July.

    Read as text on purpose: importing main.py opens sockets.
    """
    with open("main.py", encoding="utf-8") as handle:
        source = handle.read()
    start = source.index("engine = Engine(")
    call = source[start:source.index("\n    )", start)]
    stripped = "\n".join(line.split("#")[0] for line in call.splitlines())
    assert "dhan_client=" in stripped, (
        "main.py builds a Dhan client and does not give it to the "
        "Engine. LIVE mode will refuse to start.")
    # The NAME changed on 31 July, an hour after this test was written.
    # SEBI requires orders to leave from a registered static IP, but NSE
    # and the news feeds block datacenter addresses -- so main.py now
    # builds TWO clients and the Engine gets the proxied one. Pinning
    # the old variable name failed on a change that was correct, which
    # is the same brittleness that broke test_pending_work.py earlier
    # today. Assert that the Engine gets A client, and that tests/
    # test_order_route.py owns the question of WHICH.
    assert "dhan_client=dhan_" in stripped


def test_engine_module_still_imports_execution_the_same_way():
    """Cheap canary: if Execution is ever swapped for something that
    does not take dhan_client, the tests above go green while the wire
    is gone."""
    assert engine_module.Execution is Execution
    assert "dhan_client" in inspect.signature(Execution.__init__).parameters
