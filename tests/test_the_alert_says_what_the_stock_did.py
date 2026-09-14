"""
==========================================================
"ORB breakout" is true of two completely different trades
==========================================================

    "the alerts i'm receiving is not useful as they are purely orb
     breakout stocks which didn't had idea about price action it made.
     old alerts must be replaced as per my request of freshness of the
     stock rank, price action things"
                                    -- the operator, 14 September 2026

An alert named the stock, the mechanism that fired and the levels, and
said nothing about the thing he actually decides on:

    ABC LONG -- ORB breakout   qty 96   entry 104.00 ...

That sentence is equally true of a stock making a new high with buyers
behind it and of one that ran 6% at 09:20 and has been sliding since.
He cannot tell those apart, so the alerts became noise and he stopped
being able to use them.

THREE FACTS, the ones he named, on every alert that carries evidence:

    FRESHNESS       how much of today's move is already spent, from the
                    OPEN so a gap is not counted as something he
                    missed. Same reading the entry gate uses -- 61
                    trades bought 2%+ extended lost 25,026.
    DIRECTION       where it sits against its own high.
    WHO IS WINNING  buyers or sellers, from the order flow -- the same
                    reading BUYING_DRIED_UP books winners on.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

from core.engine import Engine

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _engine(snapshot=None, flow=None, raises=False):
    engine = Engine.__new__(Engine)
    if raises:
        def _boom():
            raise RuntimeError("snapshot is down")
        engine.get_circuit_snapshot = _boom
    else:
        engine.get_circuit_snapshot = lambda: dict(snapshot or {})
    engine.buying_check = (lambda symbol: flow) if flow is not None else None
    return engine


FADED = {"ABC": {"open": 100.0, "high": 106.0, "ltp": 104.0}}
FRESH = {"ABC": {"open": 100.0, "high": 101.5, "ltp": 101.5}}


# ---------------------------------------------------------------
# THE TWO TRADES THAT USED TO READ THE SAME
# ---------------------------------------------------------------

def test_a_spent_move_says_so():
    said = _engine(FADED, {"still_buying": False})._price_action_clause("ABC")
    assert "+4.0% from the open" in said
    assert "1.9% off its high" in said
    assert "BUYING HAS DRIED UP" in said


def test_a_fresh_move_says_so():
    said = _engine(FRESH, {"still_buying": True})._price_action_clause("ABC")
    assert "+1.5% from the open" in said
    assert "at its high" in said
    assert "BUYERS STILL IN" in said


def test_the_two_do_not_read_the_same():
    """The whole complaint in one assertion."""
    a = _engine(FADED, {"still_buying": False})._price_action_clause("ABC")
    b = _engine(FRESH, {"still_buying": True})._price_action_clause("ABC")
    assert a != b


# ---------------------------------------------------------------
# FRESHNESS IS MEASURED FROM THE OPEN
# ---------------------------------------------------------------

def test_a_gap_is_not_counted_as_a_missed_move():
    """A stock that gapped and then sat still is FRESH. The 3% bar asks
    whether a move qualifies, from the previous close; this asks how
    much of today's move is already spent."""
    snap = {"ABC": {"open": 103.0, "high": 103.2, "ltp": 103.0,
                    "close": 100.0}}
    said = _engine(snap, {"still_buying": True})._price_action_clause("ABC")
    assert "+0.0% from the open" in said


def test_a_stock_below_its_open_reads_negative():
    snap = {"ABC": {"open": 100.0, "high": 100.5, "ltp": 98.0}}
    assert "-2.0% from the open" in _engine(snap)._price_action_clause("ABC")


# ---------------------------------------------------------------
# IT NEVER GUESSES AND NEVER RAISES
# ---------------------------------------------------------------

def test_an_unreadable_flow_is_not_dressed_up_as_an_answer():
    """None means the book was too thin to classify. Neither 'buyers'
    nor 'sellers' may be printed from it."""
    said = _engine(FADED, {"still_buying": None})._price_action_clause("ABC")
    assert "BUYERS" not in said and "DRIED UP" not in said
    assert "from the open" in said


def test_no_data_at_all_says_nothing():
    assert _engine({})._price_action_clause("ABC") == ""


def test_a_broken_snapshot_never_raises():
    """This runs on the trading loop."""
    assert _engine(raises=True)._price_action_clause("ABC") == ""


def test_a_broken_flow_check_never_raises():
    def _boom(symbol):
        raise RuntimeError("order flow is down")
    engine = _engine(FADED)
    engine.buying_check = _boom
    said = engine._price_action_clause("ABC")
    assert "from the open" in said


def test_a_missing_open_still_reports_what_it_can():
    snap = {"ABC": {"high": 106.0, "ltp": 104.0}}
    said = _engine(snap, {"still_buying": True})._price_action_clause("ABC")
    assert "off its high" in said
    assert "from the open" not in said


# ---------------------------------------------------------------
# EVERY ALERT GETS IT
# ---------------------------------------------------------------

def test_it_hangs_off_the_clause_every_alert_already_carries():
    """One place, so the ORB alert, the manual-hold alert and the
    ranked alerts all gain it at once rather than three call sites
    drifting apart."""
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    body = src[src.index("def _alert_evidence"):]
    body = body[:body.index("def _price_action_clause")]
    assert "self._price_action_clause(symbol)" in body


def test_the_orb_alert_carries_the_evidence_clause():
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    block = src[src.index('f"{symbol} {direction} -- {entry_reason}"'):]
    assert "_alert_evidence(symbol)" in block[:200]
