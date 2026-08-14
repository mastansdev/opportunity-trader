"""
==========================================================
The switch OFF must not reach into his Dhan account
==========================================================

    "i stopped trading button of the bot since morning ... today bot
     did Sending SELL KALYANKJIL qty=500 MARKET (MTF) ... why bot
     sold? it is not even falling"

    "if button is OFF it must not participate along with me, it only
     book keep my manual trades for learning purpose"
                                -- operator, 7 August 2026

WHAT HAPPENED
-------------
He turned bot trading OFF at the open. During the session he bought
KALYANKJIL, AUROPHARMA and HEROMOTOCO himself in the Dhan app. The
bot adopted all three -- because core/broker_sync.py adopts any
position that APPEARS mid-session -- armed a trailing stop on each,
and sold them.

Two separate guards both missed it:

  * skip_symbols only protected what was open at STARTUP
  * alert_only was never read in the adoption path at all

The rotation bug found the same morning was a different path with the
same shape: exits deliberately ignore the switch so a stop always
works, and that reasoning had quietly spread to decisions that are
not stops.

WHY A TEST AND NOT JUST THE FIX
-------------------------------
Because this is the second time. tests/test_nothing_sells_while_
trading_is_off.py covers rotation. Nothing covered adoption, so the
same class of bug survived in a second place for a day and cost him
three positions he had chosen to hold.

Author : H&M Opportunity Trader
==========================================================
"""

import inspect

import core.broker_sync as broker_sync


def _adoption_block():
    """The source of the adoption decision, up to the adopt() call."""
    src = inspect.getsource(broker_sync)
    assert "adopt_positions.adopt(" in src, (
        "the adoption call has moved -- this test is now blind")
    return src.split("adopt_positions.adopt(")[0]


def test_the_adoption_path_reads_the_switch():
    """alert_only must be consulted BEFORE anything is adopted."""
    block = _adoption_block()
    tail = block[-2000:]
    assert "alert_only" in tail, (
        "core/broker_sync.py adopts broker positions without ever "
        "checking whether bot trading is ON. This is what sold "
        "KALYANKJIL, AUROPHARMA and HEROMOTOCO on 7 August.")


def test_the_guard_actually_gates_the_call():
    """Reading the switch is not enough -- it has to change the flow."""
    block = _adoption_block()
    tail = block[-1200:]
    gated = ("not _off" in tail or "_off is False" in tail
             or "not off" in tail)
    assert gated, (
        "alert_only is mentioned near the adoption call but does not "
        "gate it. A guard that is read and ignored is not a guard.")


def test_it_says_so_out_loud():
    """A silent refusal is a different kind of surprise.

    He must be able to see on the log that his manual positions are
    deliberately unmanaged, otherwise 'the bot is watching them' and
    'the bot is ignoring them' look identical.
    """
    block = _adoption_block()
    assert "[ADOPT]" in block[-2000:], (
        "the bot declines to adopt without telling him")


def test_rotation_is_still_guarded_too():
    """The sibling bug, so neither can regress alone."""
    import core.engine as engine_module
    src = inspect.getsource(engine_module)
    assert "def _maybe_rotate_out" in src
    body = src.split("def _maybe_rotate_out")[1].split("\n    def ")[0]
    assert "alert_only" in body, (
        "rotation no longer checks the switch -- 7 August, five SELLs "
        "with bot trading OFF all day")


def test_exits_are_deliberately_not_gated():
    """The line that must NOT move.

    A stop on a position the BOT opened has to fire whatever the
    switch says, or turning the switch off mid-trade would abandon
    live risk. This test exists so a future fix for adoption does not
    'tidy up' the exit path and remove protection he depends on.
    """
    import core.engine as engine_module
    src = inspect.getsource(engine_module)
    assert "Exits deliberately ignore alert_only" in src, (
        "the reasoning that exits must always fire has been removed "
        "or reworded -- confirm this is intended before changing it")
