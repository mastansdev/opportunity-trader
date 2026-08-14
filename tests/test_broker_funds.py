"""
==========================================================
The book's capital must be the broker's, not config's
==========================================================

31 July 2026, first live session. The dashboard showed

    capital   Rs 10,00,000

against a Dhan account holding a few hundred rupees. Portfolio()
defaulted to config.PAPER_STARTING_CAPITAL in BOTH modes.

    "BY CHANGING CONFIG TRADING_MODE everything must follow.
     LIVE = CONNECT TO DHAN FOR TRADING. SHOW LIVE MODE. FUNDS
            AVAILABLE IN DHAN & EVERYTHING LINKED"

Portfolio.available_capital gates sizing, so this was never only a
label. A book that believes it holds ten lakh approves positions the
account cannot pay for; the broker refuses them one at a time,
mid-session, and every refusal looks like a different bug.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from config import PAPER_STARTING_CAPITAL
from core.broker_funds import read_balance, starting_capital


class Dhan:
    """Answers the funds call however a test needs it to."""

    def __init__(self, payload=None, raises=None):
        self.payload = payload
        self.raises = raises
        self.calls = 0

    def get_fund_limits(self):
        self.calls += 1
        if self.raises:
            raise self.raises
        return self.payload


# ---------------------------------------------------------------
# 1. LIVE TAKES THE BROKER'S NUMBER
# ---------------------------------------------------------------
def test_live_uses_the_dhan_balance():
    dhan = Dhan({"data": {"availabelBalance": 1047.38}})
    assert starting_capital(dhan, mode="LIVE") == 1047.38


def test_dhans_misspelling_is_the_one_that_ships():
    """Dhan's API returns "availabelBalance". Their typo, not ours.
    Reading only the correct spelling would return None and trip the
    refusal below for entirely the wrong reason."""
    assert read_balance(Dhan({"data": {"availabelBalance": 500.0}})) == 500.0
    assert read_balance(Dhan({"data": {"availableBalance": 500.0}})) == 500.0


def test_a_real_zero_is_not_a_failure():
    """An empty account is a true answer and must be reported as 0.0,
    not confused with "could not read". The operator is warned, and the
    session still starts -- he may be about to add funds."""
    dhan = Dhan({"data": {"availabelBalance": 0}})
    assert starting_capital(dhan, mode="LIVE") == 0.0


def test_strings_from_the_api_are_accepted():
    """Dhan returns several numeric fields as strings."""
    assert read_balance(Dhan({"data": {"availabelBalance": "1047.38"}})) \
        == 1047.38


# ---------------------------------------------------------------
# 2. LIVE REFUSES RATHER THAN INVENTING MONEY
# ---------------------------------------------------------------
def test_live_refuses_when_the_funds_call_fails():
    """The dangerous fallback would be PAPER_STARTING_CAPITAL. Ten lakh
    of imaginary money in a live book is the exact bug this file
    exists for, and an expired token is the usual cause -- two minutes
    to fix at 09:00, a lost trade at 11:00."""
    with pytest.raises(RuntimeError) as raised:
        starting_capital(Dhan(raises=TimeoutError("no reply")), mode="LIVE")
    assert "Refusing to start" in str(raised.value)


def test_live_refuses_when_there_is_no_balance_field():
    with pytest.raises(RuntimeError):
        starting_capital(Dhan({"data": {"someOtherKey": 1}}), mode="LIVE")


def test_live_refuses_without_a_client():
    with pytest.raises(RuntimeError):
        starting_capital(None, mode="LIVE")


def test_the_failure_never_silently_becomes_the_paper_figure():
    """Stated as its own test because it is the whole point. If this
    ever returns instead of raising, a live session runs on a number
    nobody deposited."""
    for broken in (Dhan(raises=ValueError("boom")), Dhan({}), None):
        with pytest.raises(RuntimeError):
            starting_capital(broken, mode="LIVE")


# ---------------------------------------------------------------
# 3. PAPER IS UNCHANGED AND TOUCHES NO BROKER
# ---------------------------------------------------------------
def test_paper_uses_the_config_purse():
    assert starting_capital(None, mode="PAPER") == float(
        PAPER_STARTING_CAPITAL)


def test_paper_never_calls_the_broker():
    """A paper session must work with no token, no network and no
    account. Calling Dhan to seed a simulation would make PAPER depend
    on the very thing it exists to avoid."""
    dhan = Dhan({"data": {"availabelBalance": 999999.0}})
    assert starting_capital(dhan, mode="PAPER") == float(
        PAPER_STARTING_CAPITAL)
    assert dhan.calls == 0


# ---------------------------------------------------------------
# 4. THE PORTFOLIO ACTUALLY RECEIVES IT
# ---------------------------------------------------------------
def test_portfolio_opens_on_the_number_it_is_given():
    from trading.portfolio import Portfolio

    book = Portfolio(starting_capital=1047.38)
    assert book.starting_capital == 1047.38
    assert book.available_capital == 1047.38


def test_main_seeds_the_portfolio_from_the_broker():
    """The function existing is worth nothing if main.py still calls a
    bare Portfolio() -- which is precisely the state it was in this
    morning. Read as text: importing main.py opens sockets."""
    with open("main.py", encoding="utf-8") as handle:
        source = handle.read()
    stripped = "\n".join(line.split("#")[0] for line in source.splitlines())
    assert "Portfolio()" not in stripped, (
        "main.py builds a bare Portfolio, so a LIVE session opens on "
        "config.PAPER_STARTING_CAPITAL -- imaginary money.")
    assert "broker_funds.starting_capital(" in stripped


def test_the_dhan_client_is_built_once():
    """It was constructed twice, in two places, before the portfolio
    needed it. Two constructions is two apparent sources of truth."""
    with open("main.py", encoding="utf-8") as handle:
        source = handle.read()
    stripped = "\n".join(line.split("#")[0] for line in source.splitlines())
    assert stripped.count("dhan_context = DhanContext(") == 1
