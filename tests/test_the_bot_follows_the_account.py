"""
==========================================================
Money added mid-session must be spendable
==========================================================

    "what if i add funds in to dhan after some time like lets say 50 K
     around 07:30 & 1 Lakh around 11:30. i don't want restart main run
     , it must fetch for available funds & thats the right mechanism"
                                -- the operator, 7 September 2026

portfolio.starting_capital used to be written in exactly two places --
startup, and the moment ON arms. A top-up during the day was visible
on the board and invisible to sizing, and the workaround was to toggle
the switch. He asked for the bot to follow the account instead.

THE TRAP, AND WHY IT IS NOT ONE LINE. Read live from his account on
7 September:

    availabelBalance   69,429.68        utilizedAmount   0.00
    sodLimit           69,536.33        withdrawable     69,176.26

`availabelBalance` is ALREADY NET of margin in use, and
trading/portfolio.py then computes

    available_margin = starting_capital - used_margin(open_positions)

so assigning the available figure straight in subtracts the same
margin twice and quietly UNDER-sizes every order. The bot's own used
margin is added back, which makes available_margin come out at exactly
what Dhan says is available.

HIS OWN DHAN POSITIONS STAY HIS. Dhan has already netted them out of
the available figure, so money tied up in his manual trades is money
the bot cannot spend -- arithmetic, not the bot managing his book.

PAPER IS UNTOUCHED. It runs only while real orders are armed, so a
paper week is still measured against constant capital.

Author : H&M Opportunity Trader
==========================================================
"""

import io

import pytest

from trading.portfolio import Portfolio


def _apply(portfolio, available, held):
    """The arithmetic main.py._follow_the_account() performs."""
    used = float(portfolio.used_margin(held) or 0.0)
    whole = float(available) + used
    portfolio.starting_capital = whole
    portfolio.available_capital = whole
    return whole


def test_a_top_up_reaches_the_next_buy():
    """50,000 at 07:30. The bot must be able to spend it."""
    p = Portfolio(starting_capital=69429.68)
    _apply(p, 119429.68, {})
    assert p.available_margin({}) == pytest.approx(119429.68)


def test_the_margin_is_never_counted_twice():
    """THE bug this guards. Dhan's available already excludes the
    margin held against an open position; the portfolio subtracts its
    own again. Add it back or every order is sized short."""
    p = Portfolio(starting_capital=119429.68)
    held = {"ABC": {"entry_price": 100.0, "qty": 500}}
    used = p.used_margin(held)
    assert used > 0, "the fixture must actually block some margin"

    dhan_says_available = 119429.68 - used      # Dhan nets it out
    _apply(p, dhan_says_available, held)

    assert p.available_margin(held) == pytest.approx(dhan_says_available), (
        "the bot's free margin disagrees with Dhan -- the position's "
        "margin has been subtracted twice")


def test_a_second_top_up_while_a_position_is_open():
    """1,00,000 at 11:30, still holding something."""
    p = Portfolio(starting_capital=119429.68)
    held = {"ABC": {"entry_price": 100.0, "qty": 500}}
    used = p.used_margin(held)
    _apply(p, 119429.68 - used + 100000.0, held)
    assert p.available_margin(held) == pytest.approx(219429.68 - used)


def test_a_withdrawal_is_followed_too():
    """It follows the account, not just upwards. Taking money out must
    shrink what the bot may commit."""
    p = Portfolio(starting_capital=119429.68)
    _apply(p, 20000.0, {})
    assert p.available_margin({}) == pytest.approx(20000.0)


# ------------------------------------------------------------------
# and where it is wired
# ------------------------------------------------------------------

def test_the_heartbeat_actually_applies_it():
    """The fault this codebase keeps producing is machinery nothing
    calls. The reading was already being taken every minute while
    armed; nothing did anything with it."""
    src = io.open("main.py", encoding="utf-8").read()
    assert "_follow_the_account(portfolio, engine, _before)" in src, \
        "the balance is refreshed and never applied"
    assert "def _follow_the_account" in src


def test_it_only_follows_a_reading_that_came_from_dhan():
    """A figure from config decides nothing -- that is the whole point
    of core/broker_funds.last_read() carrying its source."""
    src = io.open("main.py", encoding="utf-8").read()
    block = src[src.index("def _follow_the_account"):]
    block = block[:block.index("def _real_orders_armed")]
    assert 'got.get("source") != "dhan"' in block


def test_paper_capital_is_left_alone():
    """It runs inside `if _real_orders_armed()`, so a paper week is
    still measured against a constant purse."""
    src = io.open("main.py", encoding="utf-8").read()
    armed = src.index("if _real_orders_armed():")
    call = src.index("_follow_the_account(portfolio, engine, _before)")
    assert armed < call, \
        "the capital would follow Dhan in paper too, and a paper week " \
        "must be measured against constant capital"
