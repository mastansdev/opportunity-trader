"""
==========================================================
NCC: 8.54x volume, no event, bought twice.
==========================================================

    "Opportunity Trader Bot = only trades when an event or real
     opportunity arised in markets, NEVER in to random stocks & only
     long positions."                    -- standing instruction

    "i gave u my concept & reasons to enter into trade with evidence &
     underlying supports. still u cannot give me the wanted output."
                                        -- operator, 21 August 2026

He was right. 21 August the bot took 3 signals out of 962:

    JSFB     vol 6.03x   news=NEWS      evidence
    URBANCO  vol 5.18x   news=NEWS      evidence
    NCC      vol 8.54x   news=None  filing=None  results=None

NCC came through a lane in core/ranker.py that lets EXCEPTIONAL VOLUME
STAND IN FOR AN EVENT -- UNEXPLAINED_MIN_VOLUME_RATIO. It was bought
at 09:59 and again at 10:31, with nothing published behind it either
time.

THE LANE WAS NOT A MISTAKE, IT WAS A DIFFERENT PREMISE

It was built on measurement: 5-10x normal volume closed up 54.2% of
the time against 44.3% under 2x. That is a real edge and a thin one,
and it answers a different question from the one he asked. Volume is
evidence that money moved. It is not evidence of WHY it moved, and
"why" is his entire premise -- the thing that separates his bot from
buying whatever is green.

AND NOTHING TESTED IT

The lane that contradicted the operator's founding rule had no test of
its own. 278 tests across the ranker passed with it wide open. That is
how it survived from whenever it was written until the morning it
bought NCC twice.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

from core import ranker, rules

ROOT = pathlib.Path(__file__).resolve().parents[1]


LTP = 149.18
VOLUME = 5_000_000

# core/ranker.volume_ratio() derives the multiple from TURNOVER against
# the stock's own average daily value -- it does not read a
# "volume_ratio" key off the row. The first version of this fixture
# supplied one and it was ignored, so a mover meant to be 8.54x
# arrived as 1.49x and every control failed for the wrong reason.
TRADED_CR = VOLUME * LTP / 1e7


def _adv_for(ratio):
    """The average-daily-value that makes today come out at `ratio`."""
    return TRADED_CR / ratio


def _mover(symbol, pct=6.0):
    return {"symbol": symbol, "change_pct": pct, "ltp": LTP,
            "prev_close": 140.0, "volume": VOLUME,
            "turnover_cr": TRADED_CR, "open": 141.0,
            "high": 150.0, "low": 140.5}


def _rank(monkeypatch, mechanism_of, require=True, vol=8.54):
    monkeypatch.setattr(rules, "REQUIRE_A_REASON_ALWAYS", require)
    monkeypatch.setattr(ranker, "REQUIRE_A_REASON_ALWAYS", require)
    got = ranker.rank([_mover("NCC")], mechanism_of=mechanism_of,
                      adv_of=lambda s: _adv_for(vol))
    return got["rows"]


# ---------------------------------------------------------------
# THE NCC CASE
# ---------------------------------------------------------------

def test_a_stock_with_no_event_is_refused_however_heavy(monkeypatch):
    """THE MORNING IT BROKE. 8.54x its normal volume and not one
    published word behind it."""
    got = _rank(monkeypatch, mechanism_of=lambda s: None)
    assert [r["symbol"] for r in got] == [], (
        "a stock with no event is still reaching the board")


def test_even_absurd_volume_is_not_a_reason(monkeypatch):
    """The lane's whole argument was that ENOUGH volume substitutes
    for an event. Under his rule no amount does."""
    monkeypatch.setattr(rules, "REQUIRE_A_REASON_ALWAYS", True)
    monkeypatch.setattr(ranker, "REQUIRE_A_REASON_ALWAYS", True)
    for vol in (5.0, 8.54, 25.0, 100.0):
        got = ranker.rank([_mover("NCC")], mechanism_of=lambda s: None,
                          adv_of=lambda s: _adv_for(vol))
        assert got["rows"] == [], (
            f"{vol}x volume was accepted as a reason")


# ---------------------------------------------------------------
# THE CONTROL: A REAL REASON STILL TRADES
# ---------------------------------------------------------------

def test_a_stock_with_a_written_reason_still_reaches_the_board(monkeypatch):
    """JSFB and URBANCO both carried news and both were correct takes.
    A rule that refuses everything would pass every test above and
    close the bot."""
    got = _rank(monkeypatch, mechanism_of=lambda s: {
        "text": "Q1 order win, Rs 166 crore", "weight": 0.9,
        "direction": "POSITIVE", "source": "PRO channel"})
    assert [r["symbol"] for r in got] == ["NCC"]


def test_the_reason_travels_with_the_row(monkeypatch):
    """He reads the sentence, not the score. A row that qualified on a
    reason must carry it."""
    got = _rank(monkeypatch, mechanism_of=lambda s: {
        "text": "bags Rs 166 crore EPFO work order",
        "weight": 0.9, "direction": "POSITIVE",
        "source": "PRO channel"})
    assert got and "EPFO" in str(got[0])


# ---------------------------------------------------------------
# THE SWITCH IS REAL AND REVERSIBLE
# ---------------------------------------------------------------

def test_turning_it_off_restores_the_measured_lane(monkeypatch):
    """The 5-10x measurement is real evidence and is not being thrown
    away -- UNEXPLAINED_MIN_VOLUME_RATIO keeps its value, so setting
    the flag False brings the old behaviour back intact."""
    got = _rank(monkeypatch, mechanism_of=lambda s: None, require=False)
    assert [r["symbol"] for r in got] == ["NCC"], (
        "the unexplained lane cannot be restored")


def test_the_measured_threshold_was_not_destroyed():
    """Deleting the number would lose the evidence behind it. It is
    left exactly where the journal put it."""
    assert rules.UNEXPLAINED_MIN_VOLUME_RATIO == 5.0


def test_the_rule_lives_in_the_one_rule_file():
    """core/rules.py is the single source of truth for thresholds. A
    second copy anywhere is how two answers start disagreeing."""
    assert hasattr(rules, "REQUIRE_A_REASON_ALWAYS")
    assert rules.REQUIRE_A_REASON_ALWAYS is True


def test_the_refusal_says_why_in_his_words(monkeypatch):
    """Every refusal is journalled and he reads them. "no event behind
    it" is the sentence he has used himself."""
    src = (ROOT / "core" / "ranker.py").read_text(encoding="utf-8")
    assert "no event behind it" in src


def test_the_reason_is_written_down_where_it_broke():
    src = (ROOT / "core" / "rules.py").read_text(encoding="utf-8")
    assert "NCC" in src and "REQUIRE_A_REASON_ALWAYS" in src
