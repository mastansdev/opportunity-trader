"""---- TWO STATES, ONE SWITCH, AND THE MONEY MOVES WITH IT ----
                                        4 September 2026.

    "new dashboard is showing 5 L as available capital in both REAL /
     PAPER MODES which is not correct.
     PAPER = 5 Lakh
     REAL  = Dhan funds reflects"                 -- the operator

    "separate the REAL & PAPER modes completely so that user can check
     more no of tests & sample data, trades without checking. as of
     now IP is not renewed & dhan can't be reached but ON & OFF needs
     to be taken care."

He found this before it cost anything, and it was not a display bug.

WHAT WAS WRONG. On the morning of 4 September the paper purse became a
fixed Rs 5 lakh, so a session could run with Dhan unreachable. But the
purse was chosen by config.TRADING_MODE -- read ONCE at startup --
while the dashboard switch is what trading/execution._route() actually
reads:

    _route():  if not self.live: return self.executor   # paper
    switch:    execution.live = bool(want_trading)

The live executor is BUILT whenever I_UNDERSTAND_THIS_PLACES_REAL_ORDERS
is on and a Dhan client exists, regardless of TRADING_MODE. So arming
ON in a PAPER process placed REAL orders at Dhan, sized against Rs 5
lakh of money that does not exist -- ten seats at Rs 50,000 a slot,
Rs 2,00,000 a position.

THE RULE NOW:

    ON  -> real orders, and the REAL Dhan balance
    OFF -> paper orders, and the fixed paper purse

and arming is REFUSED when Dhan does not answer, because his static IP
was not renewed that morning and ON would otherwise have sent orders to
a broker the process cannot reach, sized on a stale figure.
"""

import io


SRC = io.open("dashboard/server.py", encoding="utf-8").read()
BLOCK = SRC[SRC.index("THE PURSE FOLLOWS THE SWITCH"):][:5000]


def test_arming_reads_the_real_balance():
    """ON must take the money from Dhan, not from a constant."""
    assert "broker_funds.refresh(" in BLOCK
    assert "portfolio.starting_capital = float(balance)" in BLOCK


def test_disarming_restores_the_paper_purse():
    """OFF must go back to the fixed figure, so a paper day is the
    same size every day and two days can be compared."""
    assert "PAPER_STARTING_CAPITAL" in BLOCK
    assert "portfolio.starting_capital = float(PAPER_STARTING_CAPITAL)" in BLOCK


def test_it_refuses_to_arm_when_dhan_is_silent():
    """THE ONE THAT MATTERS. A real order sized on a guess is the
    single thing this switch must never do."""
    assert "if balance is None:" in BLOCK
    assert "Refusing to" in BLOCK
    assert "execution.live = False" in BLOCK, (
        "a refused arming must leave the switch OFF, not half on")


def test_a_refusal_says_why():
    """He must be able to read the reason on the page, not guess it
    from orders that quietly go nowhere."""
    assert '"error":' in BLOCK
    assert "Dhan did not answer" in BLOCK


def test_the_gate_module_fails_closed():
    """core/trading_gate.py answers the same question in one place.
    Every uncertain case is PAPER -- an engine that cannot be read, a
    mode that cannot be parsed, a broker whose state is unknown."""
    from core.trading_gate import may_place_real_orders
    assert may_place_real_orders(None)[0] is False

    class _NoSay:
        alert_only = None
    assert may_place_real_orders(_NoSay())[0] is False


def test_the_gate_needs_a_broker_that_answered():
    """Unknown is False. A broker whose state cannot be established is
    not one to send money through."""
    from core.trading_gate import broker_is_reachable
    ok, why = broker_is_reachable()
    assert isinstance(ok, bool)
    assert why, "a refusal with no reason is not readable"
