"""
==========================================================
The market prices the future. The grade describes the past.
==========================================================

    "in real markets some stocks earnings with lower business or
     negative reading also considered as positive & stock moves as
     results were not as bad as expected (we know that market prices
     the future right, by expecting the bad results due to any reason
     from regular updates like concalls, company fire accidents, recent
     one company manufacturing facility effected in floods, govt orders
     which will impact the company business.)"
                                    -- operator, 1 August 2026

MEASURED ON THE 151 GRADED RESULTS HELD THAT DAY
------------------------------------------------
    CONFIRMS      57   38%    grade and move agree
    NO REACTION   62   41%    the move was inside the noise
    LESS BAD      16   11%    WEAK result, stock rallied
    PRICED IN     16   11%    GOOD result, stock fell

One in five times the grade pointed the WRONG WAY:

    UEL          Weak result,   stock +7.3%
    GOCOLORS     Weak result,   stock +6.2%
    DHANBANK     Great result,  stock -6.3%
    KABRAEXTRU   Good result,   stock -6.4%

A grade on its own is right about direction fewer than four times in
ten. Everything this bot reads -- filed numbers, channel verdicts,
consensus surprise, metric tallies, AI opinions -- describes what
already happened. The price is a bet on what happens next, placed
before the result landed.

THE ROW THAT MADE THE CASE
--------------------------
    DEEPAKFERT   score 14.5   3 backing
      ALREADY PRICED: Good result, stock -5.8%
      STRONG (Mar-26): sales +18% QoQ, PAT +1028% QoQ
      PULSE: Good results
      AI +: net profit doubled YoY
      AI +: operational profits doubled YoY

Every evidence chip positive, three independent sources backing it,
and the stock fell 5.8%. Without the market's answer that row reads as
a buy.

Author : H&M Opportunity Trader
==========================================================
"""

import sqlite3

import pytest

from core.reaction import Reaction


@pytest.fixture
def bars(tmp_path):
    """A daily-bar store with a handful of known sessions."""
    path = str(tmp_path / "daily.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE daily_bars (date TEXT, symbol TEXT, "
                 "series TEXT, open REAL, high REAL, low REAL, "
                 "close REAL, prev_close REAL)")
    rows = [
        # weak result, stock UP -- less bad than feared
        ("2026-07-30", "GOCOLORS", 106.2, 100.0),
        # good result, stock DOWN -- already priced
        ("2026-07-30", "DEEPAKFERT", 94.2, 100.0),
        # good result, stock up -- confirms
        ("2026-07-30", "SHADOWFAX", 113.9, 100.0),
        # a move inside the noise
        ("2026-07-30", "QUIETCO", 100.4, 100.0),
        # the NEXT session, for after-hours news
        ("2026-07-31", "GOCOLORS", 104.0, 106.2),
    ]
    for date, sym, close, prev in rows:
        conn.execute("INSERT INTO daily_bars VALUES (?,?,?,?,?,?,?,?)",
                     (date, sym, "EQ", prev, close, prev, close, prev))
    conn.commit()
    conn.close()
    return Reaction(db_path=path)


# ---------------------------------------------------------------
# 1. THE TWO CASES THAT MATTER
# ---------------------------------------------------------------
def test_a_weak_result_that_rallies_is_less_bad_than_feared(bars):
    got = bars.verdict("GOCOLORS", "2026-07-30T10:00:00", "WEAK")
    assert got["state"] == "LESS BAD"
    assert "LESS BAD THAN FEARED" in got["note"]
    assert got["move_pct"] == pytest.approx(6.2, abs=0.1)


def test_a_good_result_that_falls_was_already_priced(bars):
    """DEEPAKFERT. Every evidence chip positive, three sources backing
    it, and the stock fell 5.8%."""
    got = bars.verdict("DEEPAKFERT", "2026-07-30T10:00:00", "GOOD")
    assert got["state"] == "PRICED IN"
    assert "ALREADY PRICED" in got["note"]


# ---------------------------------------------------------------
# 2. AND THE ORDINARY CASES
# ---------------------------------------------------------------
def test_agreement_is_reported_but_is_not_the_point(bars):
    got = bars.verdict("SHADOWFAX", "2026-07-30T10:00:00", "EXCELLENT")
    assert got["state"] == "CONFIRMS"


def test_a_move_inside_the_noise_is_not_a_confirmation(bars):
    """A stock that closes +0.4% on results day has not answered the
    question. Calling that confirmation would put a chip on every
    row -- and 41% of the real sample sits here."""
    got = bars.verdict("QUIETCO", "2026-07-30T10:00:00", "GOOD")
    assert got["state"] == "NO REACTION"


# ---------------------------------------------------------------
# 3. NEWS AFTER THE CLOSE IS ANSWERED THE NEXT DAY
# ---------------------------------------------------------------
def test_a_result_filed_after_the_close_reads_the_next_session(bars):
    """Reading the same day's move would credit the news with a move
    that finished before the news existed."""
    got = bars.verdict("GOCOLORS", "2026-07-30T18:40:00", "WEAK")
    assert got["on_date"] == "2026-07-31"
    assert got["move_pct"] == pytest.approx(-2.07, abs=0.1)


def test_a_result_with_no_session_yet_reports_nothing(bars):
    """The normal case for a result that landed minutes ago. It must
    never be confused with "the market ignored it"."""
    assert bars.verdict("GOCOLORS", "2026-07-31T18:40:00", "WEAK") is None


# ---------------------------------------------------------------
# 4. IT NEVER GUESSES
# ---------------------------------------------------------------
@pytest.mark.parametrize("grade", [None, "", "MIXED", "OK", "nonsense"])
def test_only_a_directional_grade_gets_an_answer(grade):
    """"OK" and "MIXED" point nowhere, so nothing can contradict them."""
    assert Reaction().verdict("GOCOLORS", "2026-07-30T10:00", grade) is None


def test_an_unknown_symbol_reports_nothing(bars):
    assert bars.verdict("NOSUCHCO", "2026-07-30T10:00", "GOOD") is None


def test_a_missing_database_does_not_raise():
    """It is read on every dashboard refresh. It must degrade to
    silence, never take the panel down."""
    assert Reaction(db_path="/nonexistent/x.db").verdict(
        "GOCOLORS", "2026-07-30T10:00", "GOOD") is None


# ---------------------------------------------------------------
# 5. ONLY DISAGREEMENTS REACH THE PANEL
# ---------------------------------------------------------------
def test_the_panel_shows_only_the_disagreements():
    """57 of 151 results CONFIRM. Putting those on the panel would
    bury the 32 that carry information."""
    src = open("core/shortlist.py", encoding="utf-8").read()
    body = src[src.index("def _market_answer"):]
    body = body[:body.index("\n    def ")]
    assert '("LESS BAD", "PRICED IN")' in body
