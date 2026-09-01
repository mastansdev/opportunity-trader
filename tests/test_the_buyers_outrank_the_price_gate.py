"""---- A FENCE AROUND A BROKEN SIGNAL. 1 September 2026. ----

    "we had enough discussions & made out loudly that bot is
     constantly moving towards better trade methods ... today we
     created more reliable sources to enter rather than blank coating
     some percentages of move right?"

    "new entries only when opportunity showed up. there is no fixed
     time ,price or fixed limitations to follow. this is stock market
     not our own shop to do as we want."
                                                -- the operator

BREAKOUT_MAX_OFF_HIGH_PCT = 0.25 was not a rule about markets. It was
written on 18 August because the reason source of the day --
STRUCTURAL_LONG_BREAKOUT -- measured the break against the 09:15-09:30
opening range, a level FROZEN at 09:30 and never updated again, so the
third re-cross of a dead level read as fresh. The signal could not tell
a live move from an old one, so the gate demanded the price be glued to
the high instead.

WHAT IT COST ON 1 SEPTEMBER. It refused 41 stocks. Not 41 refusals --
41 DISTINCT STOCKS, and every other reason combined refused none:

    [NO_TRADE] ZFCVINDIA LONG skipped -- not a fresh breakout --
    2558.40 is 1.29% below today's high of 2591.80 ... (limit 0.25%)

Measured against core/order_flow.py's still_buying() on those same 41:

    16   buyers still winning   <- the gate was wrong
    25   buyers had stopped     <- the gate was right, flow agrees
     0   flow could not answer  <- the gate keeps the last word

BEML was refused at 13:22 for sitting 1.13% under its high while its
cumulative delta stood at 100% of the day's peak -- buying at its
strongest point of the whole session. DABUR the same at 0.44%.

THE SECOND HALF, AND THE BIGGER ONE. self.entry_blocked is PERMANENT:
nothing clears it, and _try_structural_entry() returns on it before any
gate runs. So HIRECT, refused at 12:34:27, could not be bought at 14:00
however the afternoon went. That is a fixed limitation of exactly the
kind he ruled out, and it would have made the fix above nearly useless
-- a stock whose buyers pause for one minute would be dead for the day.
"""

import pytest

from core import tick_ohlc as _tick_ohlc
from core.engine import FOR_NOW, _is_provisional
from tests.test_engine import _engine


BUYING = {"symbol": "X", "delta": 9076.0, "was": 6942.0, "growing": True,
          "positive": True, "still_buying": True, "of_peak": 100.0,
          "book_pct": 100.0, "minutes": 15}
STOPPED = dict(BUYING, delta=32641.0, was=33186.0, growing=False,
               still_buying=False, of_peak=96.4)


@pytest.fixture
def engine():
    got = _engine()
    _tick_ohlc.reset()
    yield got
    _tick_ohlc.reset()


def _beml(symbol="BEML"):
    """His real numbers: refused at 13:22, 1.13% under the high."""
    _tick_ohlc.remember(symbol, {"open": 1900.0, "high": 1974.80,
                                 "low": 1890.0, "close": 1900.0,
                                 "LTP": 1952.40})
    return {"close": 1952.40}


# ------------------------------------------- the measurement overrules

def test_the_buyers_overrule_the_price_gate(engine):
    """BEML, 1.13% under its high, delta at 100% of the day's peak."""
    engine.buying_check = lambda symbol: BUYING
    assert engine._is_at_the_days_extreme("BEML", "LONG", _beml()) is True


def test_it_is_not_a_rubber_stamp(engine):
    """QUESS: buyers ahead 32,641 but DOWN from 33,186 -- they stopped
    adding. 25 of the 41 read like this and the gate stands on them. A
    check that let everything through would be worse than the fence."""
    engine.buying_check = lambda symbol: STOPPED
    assert engine._is_at_the_days_extreme("QUESS", "LONG",
                                          _beml("QUESS")) is False


def test_a_thin_book_does_not_overrule_anything(engine):
    """still_buying() returns None when under FLOW_MIN_BOOK_PCT of
    prints were classified against a real bid and ask -- its own words,
    "a guess must not overrule a gate". None must not overrule this one
    either."""
    engine.buying_check = lambda symbol: None
    assert engine._is_at_the_days_extreme("THIN", "LONG",
                                          _beml("THIN")) is False


def test_a_broken_flow_lookup_leaves_the_gate_standing(engine):
    """It runs on the entry path. A raising check may not open the gate
    and may not take the loop down."""
    def boom(symbol):
        raise RuntimeError("order flow store is gone")

    engine.buying_check = boom
    assert engine._is_at_the_days_extreme("BOOM", "LONG",
                                          _beml("BOOM")) is False


def test_an_engine_with_no_flow_check_behaves_exactly_as_before(engine):
    """main.py wires buying_check after construction. Anything that
    builds an Engine without it -- a tool, a test, a replay -- must get
    the old behaviour, not an open gate."""
    engine.buying_check = None
    assert engine._is_at_the_days_extreme("NAVINFLUOR", "LONG",
                                          _beml("NAVINFLUOR")) is False


def test_the_short_side_is_not_touched(engine):
    """still_buying() answers a LONG question. There is no "still
    selling" reading, so SHORT must not consult it -- and the bot is
    long-only regardless."""
    engine.buying_check = lambda symbol: BUYING
    _tick_ohlc.remember("DOWN", {"open": 100.0, "high": 101.0, "low": 92.0,
                                 "close": 100.0, "LTP": 95.0})
    assert engine._is_at_the_days_extreme("DOWN", "SHORT",
                                          {"close": 95.0}) is False


# ------------------------------------ refused for now, not for the day

def test_the_refusal_does_not_settle_the_stock_for_the_session(engine):
    """HIRECT was refused at 12:34:27 and could not be bought at 14:00.
    entry_blocked is permanent and _try_structural_entry() returns on it
    before any gate runs."""
    engine.buying_check = lambda symbol: STOPPED
    engine._is_at_the_days_extreme("HIRECT", "LONG", _beml("HIRECT"))
    written = engine.entry_blocked.get("HIRECT", {}).get("LONG")
    assert written, "the reason was not recorded at all -- info lost"
    assert _is_provisional(written), (
        "the stock is settled for the day on one momentary reading")


def test_the_reason_is_still_recorded_for_the_panel(engine):
    """"i do not want to miss / loose any info even by mistake". The
    block stops being BINDING; it does not stop being VISIBLE.
    dashboard/state.py reads engine.entry_blocked directly."""
    engine.buying_check = lambda symbol: STOPPED
    engine._is_at_the_days_extreme("SHOWN", "LONG", _beml("SHOWN"))
    reason = engine.entry_blocked["SHOWN"]["LONG"]
    assert "not a fresh breakout" in reason
    assert "1.13% below" in reason
    assert "1974.80" in reason


def test_a_stock_that_later_clears_the_gate_is_unblocked(engine):
    """The panel must not show a refusal that has since passed."""
    engine.buying_check = lambda symbol: STOPPED
    engine._is_at_the_days_extreme("TURN", "LONG", _beml("TURN"))
    assert engine.entry_blocked.get("TURN", {}).get("LONG")

    engine.buying_check = lambda symbol: BUYING
    assert engine._is_at_the_days_extreme("TURN", "LONG",
                                          _beml("TURN")) is True
    assert not engine.entry_blocked.get("TURN", {}).get("LONG"), (
        "a stale refusal is still on the panel")


def test_making_the_high_also_clears_it(engine):
    """The other way through the gate must clear it too."""
    engine.buying_check = lambda symbol: STOPPED
    engine._is_at_the_days_extreme("BACK", "LONG", _beml("BACK"))
    assert engine.entry_blocked.get("BACK", {}).get("LONG")

    _tick_ohlc.remember("BACK", {"open": 1900.0, "high": 1974.80,
                                 "low": 1890.0, "close": 1900.0,
                                 "LTP": 1974.80})
    assert engine._is_at_the_days_extreme("BACK", "LONG",
                                          {"close": 1974.80}) is True
    assert not engine.entry_blocked.get("BACK", {}).get("LONG")


def test_a_real_block_is_still_permanent(engine):
    """Only THIS gate's refusal becomes re-askable. A stop-out block, a
    news block, a sector block still settle the stock for the day --
    loosening those was never asked for and is not what this changes."""
    engine._block_entry("HARD", "LONG", "stopped out this morning")
    assert not _is_provisional(engine.entry_blocked["HARD"]["LONG"])
    assert engine.entry_blocked_reason("HARD", "LONG")


def test_a_provisional_block_is_not_returned_as_a_refusal(engine):
    """core/auto_entry.py asks entry_blocked_reason() before every
    ranked entry. A provisional block must not answer it -- otherwise
    the permanence comes straight back through the other door."""
    engine.buying_check = lambda symbol: STOPPED
    engine._is_at_the_days_extreme("SOFT", "LONG", _beml("SOFT"))
    assert engine.entry_blocked["SOFT"]["LONG"]
    got = engine.entry_blocked_reason("SOFT", "LONG")
    assert not (got and "fresh breakout" in got), (
        "the ranked lane is still refusing on a provisional block")


# ----------------------------------------------------- and it stays quiet

def test_it_does_not_shout_the_same_refusal_every_cycle(engine):
    """The gate now runs every cycle instead of once, because the stock
    is no longer settled. 77% of the log was repeats once already."""
    said = []
    import core.engine as eng
    real, eng.warn = eng.warn, said.append
    try:
        engine.buying_check = lambda symbol: STOPPED
        for _ in range(50):
            engine._is_at_the_days_extreme("LOUD", "LONG", _beml("LOUD"))
    finally:
        eng.warn = real
    assert len(said) == 1, f"said it {len(said)} times"
