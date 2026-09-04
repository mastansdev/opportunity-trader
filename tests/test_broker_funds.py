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

import pathlib

import pytest

from config import PAPER_STARTING_CAPITAL
from core.broker_funds import read_balance, starting_capital

ROOT = pathlib.Path(__file__).resolve().parents[1]


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


def test_paper_still_starts_with_no_broker_at_all():
    """---- THIS TEST CHANGED ON 18 AUGUST 2026. READ WHY. ----

    It used to assert `dhan.calls == 0` -- that PAPER never calls the
    broker -- with this reasoning, which was sound:

        "A paper session must work with no token, no network and no
         account. Calling Dhan to seed a simulation would make PAPER
         depend on the very thing it exists to avoid."

    The operator asked for the opposite, in these words:

        "BOT IS NOT CHECKING THE DHAN ACCOUNT. WHY? IT IS STILL
         SHOWING FUNDS OF LAST CONNECTION TIME AS 431116 RS."

    And the cost of the old rule was real: with no way to ask, the
    paper purse was a constant someone had pasted into config on
    9 August, and it read 431,116 while Dhan held 67,648.

    THE GUARANTEE THAT MATTERED SURVIVES INTACT, and this test now
    pins that instead: a paper session still starts with no token, no
    network and no account -- it just starts on a figure that is
    LABELLED config rather than one pretending to be a balance.
    """
    from core import broker_funds

    assert starting_capital(None, mode="PAPER") == float(
        PAPER_STARTING_CAPITAL), "PAPER could not start without a broker"
    assert broker_funds.last_read()["source"] == "config"


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

# ---------------------------------------------------------------
# 431,116 WAS A CONSTANT
# ---------------------------------------------------------------
#
#     "BOT IS NOT CHECKING THE DHAN ACCOUNT. WHY? IT IS STILL SHOWING
#      FUNDS OF LAST CONNECTION TIME AS 431116 RS."
#                                 -- operator, 18 August 2026
#
# He was right twice.
#
#   1. PAPER never called the broker. Documented, deliberate, and it
#      meant the answer could not change.
#   2. config.PAPER_STARTING_CAPITAL had been set to 431,116.0 on
#      9 August under the comment "THE PAPER PURSE MUST MATCH THE REAL
#      ONE". It matched on 9 August. On 18 August Dhan said 67,648.21
#      and the board still said 431,116.
#
# A frozen number that LOOKS live is worse than an obviously fake one.
# 10,00,000 announces itself as imaginary. 4,31,116 does not.
#
# So PAPER now ASKS, and config is the fallback -- which is what that
# 9 August comment already said, implemented by asking rather than by
# pasting. And every reading carries the time it was taken.


class _Dhan:
    def __init__(self, balance=67648.21, sod=214746.88, fail=False):
        self.balance, self.sod, self.fail = balance, sod, fail
        self.calls = 0

    def get_fund_limits(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("DH-901 Invalid_Authentication")
        return {"status": "success",
                "data": {"availabelBalance": self.balance,
                         "sodLimit": self.sod}}


def test_paper_never_asks_dhan_at_all():
    """---- PAPER IS RS 5 LAKH, EVERY DAY. 4 September 2026. ----

        "in paper mode bot must trade with 5 Lakh capital each day &
         trade with all same rules completely. paper mode do not want
         to see dhan & its related parts at all."

    On 18 August PAPER started sizing off the real Dhan balance, on
    the reasoning that a paper week is only worth reading if the
    constraints are real. Sound, but it made the paper session hostage
    to the broker's own state -- and 4 September proved it. Dhan's
    overnight cleanup was still running and three reads inside one
    hour gave Rs 1,28,096 (8 seats), Rs 35,648 (2 seats) and
    Rs 4,578 (ZERO seats, no trade all day). The purse is read once at
    startup and never again, so a session begun in that window is dead
    for the day through no fault of the strategy.

    The read is NOT MADE -- not made and ignored. No token, no
    network, nothing for a settling broker to break."""
    from core import broker_funds
    client = _Dhan()
    got = broker_funds.starting_capital(client, mode="PAPER")
    assert client.calls == 0, "PAPER asked the broker"
    from config import PAPER_STARTING_CAPITAL
    assert got == pytest.approx(float(PAPER_STARTING_CAPITAL))


def test_the_paper_purse_is_the_same_every_session():
    """Two days can only be compared to each other if the capital was
    the same on both. Repeatability is the point."""
    from core import broker_funds
    a = broker_funds.starting_capital(_Dhan(), mode="PAPER")
    b = broker_funds.starting_capital(_Dhan(fail=True), mode="PAPER")
    assert a == b


def test_paper_capital_is_five_lakh():
    """His figure, 4 September 2026."""
    from config import PAPER_STARTING_CAPITAL
    assert PAPER_STARTING_CAPITAL == 5_00_000.0


def test_live_still_asks_and_still_refuses_without_an_answer():
    """Nothing about LIVE changed. It reads the real balance and
    raises rather than trading on a constant."""
    from core import broker_funds
    client = _Dhan()
    broker_funds.starting_capital(client, mode="LIVE")
    assert client.calls == 1, "LIVE stopped asking the broker"


def test_the_config_figure_is_now_the_source_in_paper():
    """It was the FALLBACK from 18 August; from 4 September it is the
    source, and a broken broker changes nothing."""
    from config import PAPER_STARTING_CAPITAL
    from core import broker_funds
    got = broker_funds.starting_capital(_Dhan(fail=True), mode="PAPER")
    assert got == pytest.approx(float(PAPER_STARTING_CAPITAL))


def test_a_config_fallback_is_labelled_as_config_not_as_a_balance():
    """The whole failure was a constant that looked like a reading."""
    from core import broker_funds
    broker_funds.starting_capital(_Dhan(fail=True), mode="PAPER")
    assert broker_funds.last_read()["source"] == "config"
    assert broker_funds.last_read()["at"] is None, (
        "a config constant was stamped with a read-time it never had")


def test_a_real_reading_carries_the_time_it_was_taken():
    """Unchanged for LIVE, which is where a real reading now happens.
    PAPER no longer takes one at all -- see
    test_paper_never_asks_dhan_at_all."""
    from core import broker_funds
    broker_funds.starting_capital(_Dhan(), mode="LIVE")
    got = broker_funds.last_read()
    assert got["source"] == "dhan"
    assert got["at"], "a balance with no read-time is how this happened"
    assert got["balance"] == pytest.approx(67648.21)


def test_refresh_can_be_called_again_and_moves_the_number():
    """Reading once at startup is still 'not checking' by 14:00."""
    from core import broker_funds
    client = _Dhan()
    broker_funds.refresh(client)
    client.balance = 51000.0
    assert broker_funds.refresh(client) == pytest.approx(51000.0)
    assert broker_funds.last_read()["balance"] == pytest.approx(51000.0)


def test_a_failed_refresh_never_overwrites_a_good_reading():
    """Losing the token must not silently blank the last real answer."""
    from core import broker_funds
    broker_funds.refresh(_Dhan())
    good = broker_funds.last_read()
    assert broker_funds.refresh(_Dhan(fail=True)) is None
    assert broker_funds.last_read() == good


def test_live_still_refuses_rather_than_falling_back():
    """Unchanged, and it must stay unchanged: a LIVE book sized on
    imaginary money approves positions the account cannot pay for."""
    from core import broker_funds
    with pytest.raises(RuntimeError):
        broker_funds.starting_capital(_Dhan(fail=True), mode="LIVE")


def test_last_read_hands_back_a_copy():
    from core import broker_funds
    broker_funds.refresh(_Dhan())
    got = broker_funds.last_read()
    got["balance"] = 1
    assert broker_funds.last_read()["balance"] != 1


def test_the_bot_keeps_asking_during_the_session():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    code = chr(10).join(ln for ln in src.splitlines()
                        if not ln.lstrip().startswith("#"))
    assert "broker_funds.refresh(" in code, (
        "the balance is read once at startup and never again")


def test_the_screen_gets_the_reading_and_its_timestamp():
    src = (ROOT / "dashboard" / "state.py").read_text(encoding="utf-8")
    assert '"broker_funds"' in src
    page = (ROOT / "dashboard" / "static" / "board.html").read_text(
        encoding="utf-8")
    assert 'id="funds"' in page
    assert "s.broker_funds" in page
    assert "bf.at" in page, "the chip shows a balance with no read-time"


def test_the_diagnostics_use_the_token_main_actually_uses():
    """Both probes built their client from DHAN_ACCESS_TOKEN in .env
    while main.py mints over TOTP, so they reported DH-901 about a bot
    that was talking to Dhan perfectly well."""
    for name in ("dhan_funds_probe.py", "dhan_account_check.py"):
        src = (ROOT / "tools" / name).read_text(encoding="utf-8")
        code = chr(10).join(ln for ln in src.splitlines()
                            if not ln.lstrip().startswith("#"))
        assert "_live_token()" in code, f"{name} still trusts only .env"
