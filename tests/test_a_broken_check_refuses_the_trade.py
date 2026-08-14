"""
==========================================================
A safety gate that fails OPEN is worse than no gate
==========================================================

    "why these many bugs were un noticied till now?"
    "do not stop until u fixed all items"
                                -- operator, 8 August 2026

WHAT WAS THERE
--------------
core/auto_entry.py asks the Engine's own risk layer for the last word
before an order -- the daily loss cap, entry blocks, the square-off
guard. It did this:

    try:
        why = blocked(symbol, "LONG")
    except Exception:
        why = None          # <- and the trade went THROUGH
    if why:
        return why

So if the risk store was locked, the daily-loss table was missing, or
anything at all raised inside that check, the exception was swallowed,
`why` became None, and auto_entry read that as "nothing is blocking
this" -- and placed the order unprotected.

A broken check and a clean check produced identical behaviour. That is
the exact shape of every bug found on 8 August: something returns
nothing instead of failing loudly, and the bot runs on less protection
than anyone believes.

Worse than the other five, because this one is TRUSTED. The daily loss
cap exists so a bad morning cannot become a bad month; a version of it
that disappears when it breaks is not a cap.

THE RULE
--------
    If the check cannot run, refuse the trade.

Refusing costs one trade. Failing open costs an unbounded number.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import datetime

from core import auto_entry


class _Engine:
    """Bot trading ON, empty book -- everything permits the trade
    except whatever we break in the test."""

    def __init__(self, blocked_raises=False, rotate_raises=False):
        self.alert_only = False
        self.open_positions = {}
        self._blocked_raises = blocked_raises
        self._rotate_raises = rotate_raises

    def entry_blocked_reason(self, symbol, direction, at_time=None):
        # Signature tracks the real Engine's (at_time added 12 August
        # 2026 so one clock answers the whole entry). A double that
        # drifts from the thing it doubles tests nothing.
        if self._blocked_raises:
            raise RuntimeError("risk store is locked")
        return None

    def _maybe_rotate_out(self, challenger, direction, tick_time):
        if self._rotate_raises:
            raise RuntimeError("rotation blew up")
        return False

    def _manual_alert(self, *args):
        return None


def _row(symbol="TESTCO"):
    return {"symbol": symbol, "action": "BUY", "ltp": 100.0,
            "plan": {"ok": True, "qty": 10, "stop": 95.0, "target": 110.0},
            "why": "a reason"}


def _take(engine, rows=None, **kwargs):
    sent = []
    out = auto_entry.take(
        rows or [_row()], engine,
        now=kwargs.pop("now", datetime(2026, 8, 7, 10, 0)),
        security_id_of=lambda s: "1",
        held=kwargs.pop("held", set()),
        max_positions=kwargs.pop("max_positions", 3),
        alert=None,
        enter=lambda *a, **k: sent.append(a[0]))
    return sent, out


# ---------------------------------------------------------------
def test_a_working_risk_check_still_lets_a_good_trade_through():
    """The control. Without this, a test that always refuses would
    pass and prove nothing."""
    sent, _out = _take(_Engine())
    assert sent == ["TESTCO"], "a clean setup was refused"


def test_a_risk_check_that_RAISES_refuses_the_trade():
    """THE test. This used to place the order."""
    sent, out = _take(_Engine(blocked_raises=True))
    assert sent == [], (
        "the risk check raised and the order went out anyway -- this is "
        "the 8 August fail-open bug")
    assert out and out[0]["taken"] is False


def test_the_refusal_says_the_check_itself_failed():
    """He must be able to tell 'the cap blocked me' from 'the cap is
    broken'. Those need different actions from him."""
    _sent, out = _take(_Engine(blocked_raises=True))
    why = str(out[0]["why"]).lower()
    assert "risk check" in why and "failed" in why, why
    assert "refus" in why, why


def test_a_broken_rotation_check_also_refuses():
    """Rotation frees a slot in a full book. If it raises, the safe
    reading is 'no slot was freed', never 'go ahead'."""
    engine = _Engine(rotate_raises=True)
    engine.open_positions = {"A": {}, "B": {}, "C": {}}
    sent, out = _take(engine, held={"A", "B", "C"}, max_positions=3)
    assert sent == []
    assert out and out[0]["taken"] is False


def test_it_is_logged_not_silent(caplog):
    """A refusal nobody can see is a different kind of silence.
    core/logger.py routes through logging, so caplog is the fixture
    that sees it -- capsys returns empty."""
    import logging
    auto_entry._said.clear()
    with caplog.at_level(logging.WARNING):
        _take(_Engine(blocked_raises=True))
    said = caplog.text
    assert "entry_blocked_reason" in said, (
        "the risk check broke and nothing was written down")
    assert "RuntimeError" in said, "the actual error was not named"


def test_it_complains_once_not_per_symbol():
    """This runs over every ranked row on every cycle. A warning per
    symbol is its own kind of blindness."""
    auto_entry._said.clear()
    engine = _Engine(blocked_raises=True)
    rows = [_row(f"SYM{i}") for i in range(20)]
    sent, out = _take(engine, rows=rows)
    assert sent == []
    assert len(out) == 20, "some rows vanished instead of being refused"
    assert len(auto_entry._said) == 1, (
        f"complained {len(auto_entry._said)} times for one fault")


def test_the_source_still_carries_the_fail_closed_reasoning():
    """If someone later 'tidies' this back to `why = None`, this fails
    and the reasoning is right there to read."""
    import inspect
    src = inspect.getsource(auto_entry)
    assert "FAIL CLOSED" in src, (
        "the fail-closed comment is gone -- check the behaviour is too")
