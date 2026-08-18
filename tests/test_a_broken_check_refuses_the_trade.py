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

# ---------------------------------------------------------------
# A SEAT YOU ARE NOT USING CANNOT RUN OUT
# ---------------------------------------------------------------
#
# 18 August 2026. core/broker_funds.py stopped reading the paper purse
# out of config and started asking Dhan. Correct -- and it very nearly
# produced a silent, all-day alert blackout on the morning after he
# asked why alerts never reached his phone.
#
# Engine._position_ceiling() is cash-sized: (capital - Rs 1,00,000) /
# Rs 30,000. On the frozen constant of Rs 4,31,116 that was 5 seats.
# On his REAL free cash of Rs 84,518 -- his own manual trades were
# holding Rs 1.2 lakh of the account -- it is 0. refuse_reason then
# evaluates `len(held) >= max_positions` as `0 >= 0` and refuses every
# pick of the day with a sentence about a book that holds nothing.
#
# In ALERT_ONLY the bot enters nothing, so it occupies no seat.


class _Alerting(_Engine):
    def __init__(self):
        super().__init__()
        self.alert_only = True
        self.alerts = []

    def _manual_alert(self, symbol, kind, message):
        self.alerts.append((symbol, kind, message))


def _alert_run(engine, max_positions, held=None):
    return auto_entry.take(
        [_row()], engine, now=datetime(2026, 8, 18, 11, 0),
        security_id_of=lambda s: "1", held=held or set(),
        max_positions=max_positions,
        alert=engine._manual_alert, enter=lambda *a, **k: None)


def test_a_zero_seat_book_still_alerts():
    """THE BLACKOUT THIS PREVENTS."""
    engine = _Alerting()
    _alert_run(engine, max_positions=0)
    assert engine.alerts, (
        "cash ran low and he stopped being told about opportunities")


def test_a_full_book_still_alerts():
    engine = _Alerting()
    _alert_run(engine, max_positions=1, held={"SOMETHINGELSE"})
    assert engine.alerts


def test_it_still_places_nothing_while_alert_only():
    engine = _Alerting()
    placed = []
    auto_entry.take([_row()], engine, now=datetime(2026, 8, 18, 11, 0),
                    security_id_of=lambda s: "1", held=set(),
                    max_positions=0, alert=engine._manual_alert,
                    enter=lambda *a, **k: placed.append(a[0]))
    assert placed == [], "ALERT_ONLY placed an order"


def test_the_entry_path_still_respects_the_seat_count():
    """The capacity rule is untouched where it actually matters. If
    this ever passes an entry through on a zero ceiling, the change
    stopped being about alerts."""
    engine = _Engine()          # alert_only False -- the entry path
    sent, _ = _take(engine, max_positions=0)
    assert sent == [], "a full book let a real entry through"


def test_a_bad_pick_is_still_silenced_in_alert_only():
    """Only the CAPACITY question is set aside. A refusal about the
    TRADE must still stop the alert, or the phone fills with picks the
    bot itself rejected."""
    engine = _Alerting()
    row = _row()
    row["plan"] = {"ok": False, "why": "no tradeable plan"}
    auto_entry.take([row], engine, now=datetime(2026, 8, 18, 11, 0),
                    security_id_of=lambda s: "1", held=set(),
                    max_positions=5, alert=engine._manual_alert,
                    enter=lambda *a, **k: None)
    assert engine.alerts == []


def test_already_held_is_still_silenced_in_alert_only():
    engine = _Alerting()
    auto_entry.take([_row()], engine, now=datetime(2026, 8, 18, 11, 0),
                    security_id_of=lambda s: "1", held={"TESTCO"},
                    max_positions=5, alert=engine._manual_alert,
                    enter=lambda *a, **k: None)
    assert engine.alerts == []
