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

AND THE GUARD THAT WAS ONLY A COMMENT. config.LIVE_ALLOW_BOT_ENTRIES
is described in three files -- "the bot's own structural entries
cannot place a live order until LIVE_ALLOW_BOT_ENTRIES is turned on
deliberately" -- and was implemented in none of them. Searched the
whole repository: config defines it, preflight reports it, two
docstrings promise it, a test quotes it, and no line of the order path
ever read it. With the mode on LIVE and the switch ON, that day's 40+
structural entries would have reached the exchange with no click.

EXITS ARE NEVER GATED. A position opened live is real, and a real
position needs a real stop. Sending its exit to paper would leave him
holding stock the bot believes it has sold.
"""

import pytest

from trading.execution import Execution, _is_the_operators_click


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


# ---------------------------------- the guard that was only a comment

def test_on_leaves_the_bots_own_entry_on_paper():
    """LIVE_ALLOW_BOT_ENTRIES is off, so his clicks are real and the
    bot's own signals are not."""
    ex = _execution()
    ex.live = True
    for reason in ("STRUCTURAL_LONG_BREAKOUT", "RANKED_SETUP", "", None):
        assert _who(ex.buy(1, "X", 100.0, 10, reason=reason)) == "paper"


def test_a_click_is_recognised_and_a_bot_reason_is_not():
    for click in ("MANUAL_BUY_DASHBOARD", "MANUAL_SELL", "MANUAL_EXIT",
                  "manual_short_dashboard"):
        assert _is_the_operators_click(click) is True, click
    for bot in ("STRUCTURAL_LONG_BREAKOUT", "RANKED_SETUP", "TRAILING_STOP",
                "ADOPTED_FROM_BROKER", "", None):
        assert _is_the_operators_click(bot) is False, bot


def test_the_guard_is_real_code_not_a_docstring():
    """The whole finding. Three files promised this behaviour and none
    implemented it."""
    import inspect

    src = inspect.getsource(Execution._route)
    code = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    assert "LIVE_ALLOW_BOT_ENTRIES" in code


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
