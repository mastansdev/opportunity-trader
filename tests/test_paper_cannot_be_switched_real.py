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


def test_the_switch_alone_decides(monkeypatch):
    """---- HE OVERRULED THE OUTER BOUND. 6 September 2026. ----

        "its not correct. as we settled that switch . OFF = paper &
         ON = Real trades thats it & final"
        "by default OFF . after clicking ON then it must trade in real
         mode & do not ask user to change in files or restarts in run"

    This file was written on 4 September to stop a click costing money
    while his static IP was down and Dhan was unreachable. That reason
    is now served properly: core/trading_gate.refuse_to_arm_reason()
    will not let ON happen while the broker is not answering, and says
    why. A refusal with a sentence is a control; a second hidden mode
    is the third state he abolished.

    So TRADING_MODE no longer gates a real order. The switch does.
    """
    ex = _armed_execution(monkeypatch, "PAPER")
    assert ex._live_executor() is not None, (
        "the switch is ON and this handed back paper -- he must not "
        "have to edit a file or restart to trade for real")


def test_a_live_process_still_routes_to_the_live_executor(monkeypatch):
    """The gate must not break real trading when it is genuinely wanted."""
    ex = _armed_execution(monkeypatch, "LIVE")
    assert ex._live_executor() is not None


def test_arming_is_refused_while_the_broker_is_silent(monkeypatch):
    """What replaced the outer bound, and the case it was built for:
    4 September, his static IP not renewed, Dhan unreachable. ON must
    not arm into that -- and must say why rather than go quiet."""
    from core import trading_gate
    monkeypatch.setattr(trading_gate, "broker_is_reachable",
                        lambda *a, **k: (False, "Dhan has not answered"))
    why = trading_gate.refuse_to_arm_reason(object())
    assert why and "answered" in why


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


def test_the_switch_writes_exactly_one_flag():
    """The collapse to two. alert_only and breakout_armed were retired
    on 5 September; apply_switch sets execution.live and nothing else,
    so there is no second flag for the two screens to disagree over."""
    import inspect

    from core.trading_gate import apply_switch
    src = inspect.getsource(apply_switch)
    assert "execution.live = bool(on)" in src
    # The docstring EXPLAINS the retired flags by name, so strip it
    # along with the comments and look only at what executes. (The
    # same trap tests/test_the_guard_stops_a_dead_feed.py fell into
    # tonight: a guard that fires on its own documentation.)
    import ast

    tree = ast.parse(src.lstrip())
    fn = tree.body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]
    body = ast.unparse(fn)
    assert "alert_only" not in body, "the third state is back"
    assert "breakout_armed" not in body, "the second switch is back"


def test_the_gate_itself_still_fails_closed():
    """Unknown must mean paper, everywhere in it."""
    from core.trading_gate import may_place_real_orders
    ok, why = may_place_real_orders(None)
    assert ok is False and why


def test_the_gate_allows_a_real_order_when_the_switch_is_on(monkeypatch):
    """TRADING_MODE is not consulted any more. The switch and a broker
    that answered -- those two, and nothing else."""
    import config
    from core import trading_gate
    monkeypatch.setattr(config, "TRADING_MODE", "PAPER")
    monkeypatch.setattr(trading_gate, "broker_is_reachable",
                        lambda *a, **k: (True, "Dhan answered"))

    class _Execution:
        live = True
    class _Engine:
        execution = _Execution()
    ok, _why = trading_gate.may_place_real_orders(_Engine())
    assert ok is True
