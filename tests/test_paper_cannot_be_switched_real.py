"""A gate written to be asked, and never asked.

    "fix the gate now"          -- the operator, 4 September 2026, 23:00

core/trading_gate.py was written that morning to answer "may a REAL
order be placed?" in ONE place, and committed at 09:00. The dead-code
audit he asked for the same evening found that NOTHING CALLED IT --
may_place_real_orders() appeared exactly twice in the repository: its
own definition, and a comment citing it.

What was actually true of the session he ran that night:

    TRADING_MODE = PAPER
    I_UNDERSTAND_THIS_PLACES_REAL_ORDERS = True
    main.py passes the Dhan client in BOTH modes, so holdings can be read
    -> the LIVE executor was built (proven: the REAL ORDERS banner fired,
       and "the live executor exists" is its exact condition)

and dashboard/server.py set `execution.live = bool(want_trading)` with
no mode check. Pressing ON would have sent real orders to Dhan. The
only thing stopping it was a static IP returning 403 -- a broken
network, not a safety mechanism.

TWO LAYERS, ON PURPOSE:

    the switch    refuses to arm when the gate says no, so a refusal
                  reaches him as a sentence
    the router    refuses on the MODE at the point every order passes
                  through, so a future caller that sets .live by some
                  other path is still refused

The second is the one that matters. The first is courtesy.
"""

import pytest

import trading.execution as execution_mod
from trading.execution import Execution


class _Live:
    """Stands in for the live executor -- if a test ever reaches this,
    a real order would have left."""

    def __init__(self):
        self.orders = []

    def buy(self, *a, **k):
        self.orders.append(a)
        return {"success": True}


def _armed_execution(monkeypatch, mode):
    ex = object.__new__(Execution)
    ex.executor = object()
    ex._live = _Live()
    ex.live = True                    # the switch is ON
    ex._said = set()
    monkeypatch.setattr(execution_mod, "TRADING_MODE", mode, raising=False)
    import config
    monkeypatch.setattr(config, "TRADING_MODE", mode)
    return ex


def test_a_paper_process_never_routes_to_the_live_executor(monkeypatch):
    """THE fix. Switch ON, live executor present, mode PAPER -> paper."""
    ex = _armed_execution(monkeypatch, "PAPER")
    assert ex._live_executor() is None, (
        "a PAPER process handed back the LIVE executor -- pressing ON "
        "would place real orders at Dhan")


def test_a_live_process_still_routes_to_the_live_executor(monkeypatch):
    """The gate must not break real trading when it is genuinely wanted."""
    ex = _armed_execution(monkeypatch, "LIVE")
    assert ex._live_executor() is not None


def test_the_refusal_is_said_once_not_per_order(monkeypatch):
    """It runs on every routed order. A line per order would bury the log."""
    ex = _armed_execution(monkeypatch, "PAPER")
    for _ in range(5):
        ex._live_executor()
    assert len(ex._said) == 1


def test_no_live_executor_at_all_is_still_none(monkeypatch):
    ex = _armed_execution(monkeypatch, "LIVE")
    ex._live = None
    assert ex._live_executor() is None


# ---------------------------------------------- the switch, and the gate

def test_both_screens_move_the_switch_through_one_function():
    """The desk and the phone must not each write their own flag.

    Until 4 September they did, and the same OFF meant two different
    things: on the desk the bot kept trading on paper, from Telegram it
    stopped trading altogether and only alerted -- the third state he
    abolished on 31 August. Asserted on the source because the audit's
    whole lesson is that a function nobody calls looks exactly like a
    function that works."""
    import inspect

    import dashboard.server as server
    import core.telegram_desk as desk

    assert "apply_switch" in inspect.getsource(server), (
        "the dashboard no longer moves the switch through the gate")
    assert "apply_switch" in inspect.getsource(desk.TelegramDesk._arm), (
        "Telegram is writing its own flag again -- the same OFF now "
        "means two different things depending on which screen he uses")


def test_arming_asks_the_gate_before_the_switch_moves():
    """A refusal must reach him before anything is armed, not after."""
    import inspect

    from core.trading_gate import apply_switch
    src = inspect.getsource(apply_switch)
    i = src.index("refuse_to_arm_reason")
    j = src.index("execution.live = bool(on)")
    assert i < j, "the gate is asked AFTER the switch is already set"


def test_neither_position_of_the_switch_raises_alert_only():
    """The third state stays dead. ON and OFF both leave it False."""
    import inspect

    from core.trading_gate import apply_switch
    src = inspect.getsource(apply_switch)
    assert "engine.alert_only = False" in src
    assert "alert_only = True" not in src


def test_the_gate_itself_still_fails_closed():
    """Unknown must mean paper, everywhere in it."""
    from core.trading_gate import may_place_real_orders
    ok, why = may_place_real_orders(None)
    assert ok is False and why


def test_a_paper_process_is_never_allowed_by_the_gate(monkeypatch):
    import config
    from core.trading_gate import may_place_real_orders
    monkeypatch.setattr(config, "TRADING_MODE", "PAPER")

    class _Engine:
        alert_only = False            # the switch is ON
    ok, why = may_place_real_orders(_Engine())
    assert ok is False
    assert "paper" in why.lower()
