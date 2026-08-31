"""One switch, two states, and no third.

    "keep simple ON = REAL TRADES . OFF = PAPER TRADES . all same
     entry, exits, capital allotted & everything same. no need to
     mention any extra parts .... on dashboard just show as this by
     default OFF PAPER TRADE . after i click ON then REAL TRADE .
     thats it no explanation or nothing required"
                                    -- operator, 31 August 2026

He specified this on 5 August. What shipped was ALERT_ONLY_MODE, whose
OFF meant "place nothing at all, not even a simulated fill" -- a third
state he never asked for. On 31 August it produced 65 alerts and 0
trades, and the ten days before it produced no completed trade at all.

THE BOT ALWAYS TRADES NOW. The switch chooses whose money.

AND THEN I ADDED A THIRD STATE ANYWAY. Later the same day, this file
tested LIVE_ALLOW_BOT_ENTRIES: a flag meaning "switch ON, but the
BOT'S trades stay on paper -- only your clicks are real." He had not
asked for it. He said so:

    "i asked you to create two modes paper & real trading . all common
     in both with only distinct is real uses dhan path with real money
     & paper do not use dhan real money. remaining all same."

The tell was that "what happens when I click ON" needed a table to
answer. It also caused a bug: entries filling on paper while exits went
live, which can only happen if entries and exits are allowed to
disagree about whose money they are.

It is gone. Two branches, and the safety is where it always was -- the
switch starts OFF, moves only when he clicks it, and the process still
refuses to go live without a Dhan client and
I_UNDERSTAND_THIS_PLACES_REAL_ORDERS.

AN EXIT FOLLOWS ITS OWN ENTRY. Not a third state -- the same two,
remembered. A stock bought on paper is sold on paper even if he flips
the switch while it is open, because selling it for real would open a
real short in stock he never bought.
"""

import pytest

from trading.execution import Execution


class _Spy:
    def __init__(self, name):
        self.name = name
        self.orders = []

    def buy(self, *a, **k):
        self.orders.append("buy")
        return {"filled": True, "by": self.name}

    def sell(self, *a, **k):
        self.orders.append("sell")
        return {"filled": True, "by": self.name}


def _execution(live_possible=True):
    ex = Execution.__new__(Execution)
    ex.executor = _Spy("paper")
    ex._live = _Spy("live") if live_possible else None
    ex._live_refused = None if live_possible else "no Dhan client"
    ex.mode = "PAPER"
    ex.live = False
    return ex


def _who(result):
    return result["by"]


# ------------------------------------------------------- the two states

def test_off_means_paper_and_the_bot_still_trades():
    """OFF is not "do nothing". It trades fully on paper -- which is
    the whole point: a day that produces a record."""
    ex = _execution()
    assert _who(ex.buy(1, "ASHOKA", 100.0, 10,
                       reason="STRUCTURAL_LONG_BREAKOUT")) == "paper"
    assert ex.executor.orders == ["buy"]


def test_on_sends_his_click_to_the_exchange():
    ex = _execution()
    ex.live = True
    assert _who(ex.buy(1, "ASHOKA", 100.0, 10,
                       reason="MANUAL_BUY_DASHBOARD")) == "live"


def test_it_starts_on_paper_whatever_config_says():
    """"by default OFF PAPER TRADE". A process that comes back while
    he is away from the desk must come back simulated."""
    assert Execution.live is False


# ------------------------------------------- no third state, either way

def test_on_sends_the_bots_own_entry_to_the_exchange():
    """This asserted the OPPOSITE until he read it back to me.

    LIVE_ALLOW_BOT_ENTRIES kept the bot's own trades on paper while the
    switch said REAL. That is a third mode, and it is the one thing he
    has said twice that he does not want:

        "all common in both with only distinct is real uses dhan path
         with real money"

    ON means the bot trades his money. That is what the switch is for.
    It starts OFF and only his click moves it."""
    ex = _execution()
    ex.live = True
    for reason in ("STRUCTURAL_LONG_BREAKOUT", "RANKED_SETUP", "", None):
        assert _who(ex.buy(1, "X", 100.0, 10, reason=reason)) == "live"


def test_the_reason_no_longer_changes_where_an_order_goes():
    """Whose idea a trade was used to decide which money paid for it.
    With two modes that cannot matter, and a router that reads the
    reason is a router that can grow a third mode again."""
    ex = _execution()
    ex.live = True
    where = {_who(ex.buy(1, "X", 100.0, 10, reason=r))
             for r in ("MANUAL_BUY", "RANKED_SETUP", "ADOPTED_FROM_BROKER",
                       "STRUCTURAL_LONG_BREAKOUT", "", None)}
    assert where == {"live"}, "the reason still steers the order"

    ex.live = False
    where = {_who(ex.buy(1, "X", 100.0, 10, reason=r))
             for r in ("MANUAL_BUY", "RANKED_SETUP", "ADOPTED_FROM_BROKER",
                       "STRUCTURAL_LONG_BREAKOUT", "", None)}
    assert where == {"paper"}


def test_the_third_state_cannot_come_back_quietly():
    """It arrived as a flag nobody was watching. If it returns, this
    fails on the day it does, not on the day it costs him money."""
    import inspect

    src = inspect.getsource(Execution._route)
    code = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    assert "LIVE_ALLOW_BOT_ENTRIES" not in code
    assert "_is_the_operators_click" not in code
    assert "OPERATOR_CLICKS" not in code


# --------------------------------------------------- exits are not gated

def test_a_real_position_gets_a_real_exit():
    """A position opened live is real. Sending its stop to paper would
    leave him holding stock the bot believes it has sold."""
    ex = _execution()
    ex.live = True
    assert _who(ex.sell(1, "X", 100.0, 10, reason="TRAILING_STOP")) == "live"
    assert _who(ex.sell(1, "X", 100.0, 10, reason="FIXED_STOP_LOSS")) == "live"


def test_exits_stay_on_paper_while_the_switch_is_off():
    ex = _execution()
    assert _who(ex.sell(1, "X", 100.0, 10, reason="TRAILING_STOP")) == "paper"


# ------------------------------------------- a switch that cannot deliver

def test_on_without_a_live_path_stays_on_paper_and_says_so():
    """21 August: the board answered "placing REAL orders" during a
    PAPER session and he stood down, correctly, on what he was shown.
    ON in a process that cannot place a real order must never look
    real."""
    ex = _execution(live_possible=False)
    ex.live = True
    assert _who(ex.buy(1, "X", 100.0, 10,
                       reason="MANUAL_BUY_DASHBOARD")) == "paper"


def test_the_board_reads_the_truth_not_the_button():
    from dashboard.server import _bot_trading_now

    class _Engine:
        def __init__(self, ex):
            self.execution = ex
            self.open_positions = {}

    class _State:
        def __init__(self, e):
            self.engine = e

    ex = _execution(live_possible=False)
    ex.live = True
    got = _bot_trading_now(_State(_Engine(ex)))
    assert got["on"] is True
    assert got["placing_real_orders"] is False
    assert got["mode"] == "PAPER"


def test_an_unreadable_switch_is_unknown_not_off():
    from dashboard.server import _bot_trading_now

    class _State:
        engine = None

    got = _bot_trading_now(_State())
    assert got["on"] is None and got["known"] is False
