"""---- THE REASON WAS WRITTEN AND THROWN AWAY. 31 Aug 2026 ----

core/capital.slots() returns a "why" on purpose. Its own docstring
says so:

    "Returns {"slots", "deployable", "free_after", "why"} -- never a
     bare number, because a refusal he cannot read is a refusal he
     cannot act on."

Engine._position_ceiling() read .get("slots") and discarded the rest.

So when cash closed the book -- the balance dipped below one position,
or came back unparseable and became 0.0 inside slots() -- the bot
quietly stopped opening positions and nothing anywhere said why. He
would see a day with no trades and no explanation.

That is the third time tonight the same shape has turned up: the
ranker's per-stock refusals computed and dropped, the flow reading
computed and unused, and now this. The work is done and the last step
to where he can see it is missing.

EDGE-TRIGGERED. Said once when the book closes and once when it opens
again -- never every cycle. A warning that repeats every few seconds
is one he learns to scroll past, which is the same as not saying it.
"""

import pytest

from core import capital
from core.engine import Engine


class _Portfolio:
    def __init__(self, starting_capital):
        self.starting_capital = starting_capital


def _engine(capital_rs, held=0):
    e = Engine.__new__(Engine)
    e.portfolio = _Portfolio(capital_rs)
    e.open_positions = {str(i): {} for i in range(held)}
    return e


def _ceiling(engine, said):
    import core.engine as mod

    real_warn, real_decision = mod.warn, mod.decision
    mod.warn = said.append
    mod.decision = said.append
    try:
        return engine._position_ceiling()
    finally:
        mod.warn, mod.decision = real_warn, real_decision


# ------------------------------------------------ slots() itself is fine

def test_slots_always_explains_a_zero():
    """The half that was already right."""
    got = capital.slots(0, held=0)
    assert got["slots"] == 0
    assert got["why"], "a zero with no reason is unactionable"


def test_an_unreadable_balance_becomes_zero_and_says_so():
    """float("not a number") is caught and capital becomes 0.0. That is
    the correct choice -- guessing a balance would size real orders --
    but it must not be silent."""
    got = capital.slots("not a number", held=0)
    assert got["slots"] == 0
    assert got["why"]


# ------------------------------------------- the engine now passes it on

def test_no_money_means_no_new_trades(monkeypatch):
    """---- ONE RULE. 31 August 2026. ----

        "no capital (money) = no trades in real mode right. thats as
         simple as that whats so complex in that?"

    It read `if not capital: return MAX_OPEN_POSITIONS`, so zero, None
    and a broker timeout all came back as THREE SEATS -- opening the
    book on money the bot could not confirm exists.

    Zero, None, and unparseable are one case: the bot cannot see the
    money, so it does not know it has any. "I could not read the
    balance" is not a reason to trade."""
    monkeypatch.setattr("core.engine.ENABLE_CASH_SIZED_BOOK", True)
    for balance in (0, None, "not a number", -5000):
        said = []
        engine = _engine(431000)
        engine.portfolio.starting_capital = balance
        seats = _ceiling(engine, said)
        assert seats == 0, f"{balance!r} opened {seats} seats"
        assert "No new positions" in " ".join(said), balance


def test_open_positions_are_never_abandoned(monkeypatch):
    """Losing sight of the balance must not close what is already held.
    Abandoning live positions over a failed balance read is far worse
    than not opening another."""
    monkeypatch.setattr("core.engine.ENABLE_CASH_SIZED_BOOK", True)
    engine = _engine(431000, held=3)
    engine.portfolio.starting_capital = None
    assert _ceiling(engine, []) == 3, (
        "the seat count fell below what is already open, which asks the "
        "bot to close positions because it could not read a number")


def test_an_open_book_says_nothing(monkeypatch):
    """Normal running must stay quiet, or the message above stops being
    read."""
    monkeypatch.setattr("core.engine.ENABLE_CASH_SIZED_BOOK", True)
    said = []
    seats = _ceiling(_engine(431000), said)
    assert seats > 0
    assert said == [], f"noise on a normal cycle: {said}"


def test_it_is_said_once_not_every_cycle(monkeypatch):
    """Edge-triggered. A warning every few seconds is one he scrolls
    past, which is the same as not saying it."""
    monkeypatch.setattr("core.engine.ENABLE_CASH_SIZED_BOOK", True)
    engine = _engine(0)
    said = []
    for _ in range(5):
        _ceiling(engine, said)
    assert len(said) == 1, f"said {len(said)} times: {said}"


def test_it_speaks_again_when_the_book_reopens(monkeypatch):
    """He needs to know it came back too, or he is left assuming it is
    still shut."""
    monkeypatch.setattr("core.engine.ENABLE_CASH_SIZED_BOOK", True)
    engine = _engine(0)
    said = []
    _ceiling(engine, said)
    engine.portfolio.starting_capital = 431000
    _ceiling(engine, said)
    assert len(said) == 2, said
    assert "again" in said[1], said


def test_the_seat_count_itself_is_unchanged(monkeypatch):
    """This must only add a message. If it changes how many positions
    the bot may open, it is a different change and a dangerous one."""
    monkeypatch.setattr("core.engine.ENABLE_CASH_SIZED_BOOK", True)
    for capital_rs, held in ((431000, 0), (431000, 3), (105000, 1)):
        engine = _engine(capital_rs, held=held)
        expected = max(
            capital.slots(capital_rs, held=held)["slots"] + held, 0)
        assert _ceiling(engine, []) == expected, (capital_rs, held)
    # A zero balance is its own branch above: no NEW seats, and the
    # ones already held are left alone rather than force-closed.
    assert _ceiling(_engine(0, held=2), []) == 2
