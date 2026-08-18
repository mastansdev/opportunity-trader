"""
==========================================================
What happened after the signal
==========================================================

    "do it - build the signal outcome scoring"
                                -- operator, 18 August 2026

WHY THIS EXISTS
---------------
core/signal_journal.py has recorded every structural signal since
29 July: 13,333 of them, with `taken` and `refused_why` on each, and
NO column for what the price then did. Nothing had ever read it back.

51 of those 13,333 were taken. So the journal is almost entirely a
record of what the bot REFUSED -- the one population a P&L statement
can never show him, and the only way to tell a gate that saves money
from a gate that merely says no.

Every rule this bot has gained was reasoning: a breakout should be at
the day's high, evidence should beat no evidence, a full book should
not silence an alert. All arguable. None ever checked. This is the
machinery that checks them, so the next rule can be argued with
numbers instead of with confidence.

WHAT THE TESTS BELOW ARE ACTUALLY GUARDING
------------------------------------------
A scorer that flatters itself is worse than no scorer, because it
turns a losing rule into a justified one. Four ways this could lie,
and a test for each:

  1. Counting a stopped-out trade as a winner, by reading a day's
     high and low without their ORDER.
  2. Scoring the signal's OWN candle -- crediting the bot with a move
     it had already seen when it decided.
  3. Averaging daily-resolution rows in with minute ones, so a
     "result" appears for a signal whose result is unknowable.
  4. Getting the sign wrong on a SHORT, which would make every
     falling stock look like a loss.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

import pytest

from core import signal_journal as sj

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _sig(**kw):
    row = {"trade_date": "2026-07-30", "symbol": "TESTCO",
           "direction": "LONG", "first_seen": "2026-07-30 09:31:00",
           "break_price": 100.0, "taken": 0, "refused_why": None}
    row.update(kw)
    return row


def _candles(*bars):
    """(minute, o, h, l, c) tuples, the shape score_row() is handed."""
    return [(f"2026-07-30T{9 + i // 60:02d}:{31 + i:02d}:00",
             o, h, l, c) for i, (o, h, l, c) in enumerate(bars)]


# ---------------------------------------------------------------
# 1. THE STOP HAS TO COME FIRST TO COUNT
# ---------------------------------------------------------------

def test_a_stop_hit_before_the_high_is_a_loss():
    """THE LIE THIS PREVENTS. Down to 97 first, then up to 106. A
    daily bar shows +6% high and reads like a winner. The trade was
    already stopped out at 97.5."""
    got = sj.score_row(_sig(), minutes=_candles(
        (100, 100, 96.0, 97.0),      # -4% -- the stop
        (97, 106.0, 97.0, 106.0)))   # the run that never happened
    assert got["hit_first"] == "stop"
    assert got["result_pct"] == -sj.SCORE_STOP_PCT
    assert got["mfe_pct"] > 5, "the high is still REPORTED, just not paid"


def test_a_target_hit_before_the_stop_is_a_win():
    got = sj.score_row(_sig(), minutes=_candles(
        (100, 106.0, 100.0, 105.5),
        (105, 105.5, 90.0, 91.0)))
    assert got["hit_first"] == "target"
    assert got["result_pct"] == sj.SCORE_TARGET_PCT


def test_one_candle_spanning_both_counts_as_the_stop():
    """Within a single candle the order is unknowable. Assuming the
    good half came first is exactly how a backtest flatters itself."""
    got = sj.score_row(_sig(), minutes=_candles((100, 106.0, 96.0, 101.0)))
    assert got["hit_first"] == "stop"


def test_neither_hit_pays_what_the_close_paid():
    got = sj.score_row(_sig(), minutes=_candles(
        (100, 101.5, 99.0, 101.0),
        (101, 102.0, 99.5, 101.8)))
    assert got["hit_first"] is None
    assert got["result_pct"] == pytest.approx(1.8, abs=0.01)


# ---------------------------------------------------------------
# 2. THE SIGNAL'S OWN CANDLE IS NOT A PREDICTION
# ---------------------------------------------------------------

def test_only_candles_after_the_signal_are_scored():
    """Scoring the bar the signal fired on credits the bot with a move
    it had already seen when it decided."""
    import sqlite3
    rows = sj.score(db_path="does-not-exist.db")
    assert rows == [], "a missing journal must answer empty, not raise"
    del sqlite3

    src = (ROOT / "core" / "signal_journal.py").read_text(encoding="utf-8")
    body = src[src.find("def score("):src.find("def _mean(")]
    code = "\n".join(ln for ln in body.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert 'str(c[0]) > seen' in code, (
        "the walk no longer excludes the signal's own candle")


# ---------------------------------------------------------------
# 3. DAILY RESOLUTION MUST NOT PRETEND TO BE MINUTE RESOLUTION
# ---------------------------------------------------------------

def test_a_daily_row_refuses_to_state_a_result():
    """It has the high and the low and not their order, so it cannot
    say whether the trade made money. Saying nothing is the correct
    answer; saying +4% is the lie."""
    got = sj.score_row(_sig(), daily=(104.0, 97.0, 103.0))
    assert got["resolution"] == "daily"
    assert got["result_pct"] is None
    assert got["hit_first"] is None
    assert got["mfe_pct"] == pytest.approx(4.0)
    assert got["mae_pct"] == pytest.approx(-3.0)


def test_the_averages_keep_the_two_apart():
    rows = [sj.score_row(_sig(), minutes=_candles((100, 101, 99.5, 100.9))),
            sj.score_row(_sig(), daily=(104.0, 97.0, 103.0))]
    got = sj._summary(rows)
    assert got["n"] == 2
    assert got["n_minute"] == 1, "he cannot see how much of this is guessed"
    assert got["stopped_first_pct"] is not None


def test_minute_data_wins_when_both_are_offered():
    got = sj.score_row(_sig(), minutes=_candles((100, 101, 99.5, 100.9)),
                       daily=(999.0, 1.0, 500.0))
    assert got["resolution"] == "minute"


# ---------------------------------------------------------------
# 4. A SHORT THAT FALLS HAS MADE MONEY
# ---------------------------------------------------------------

def test_a_short_that_falls_is_a_win_not_a_loss():
    got = sj.score_row(_sig(direction="SHORT"),
                       minutes=_candles((100, 100.2, 94.0, 94.5)))
    assert got["mfe_pct"] > 0, "a short that fell 6% was scored as a loss"
    assert got["close_pct"] == pytest.approx(5.5, abs=0.01)


def test_a_short_that_rises_is_stopped():
    got = sj.score_row(_sig(direction="SHORT"),
                       minutes=_candles((100, 103.5, 100.0, 103.0)))
    assert got["hit_first"] == "stop"


def test_the_short_side_daily_row_is_mirrored_too():
    got = sj.score_row(_sig(direction="SHORT"), daily=(104.0, 97.0, 98.0))
    assert got["mfe_pct"] == pytest.approx(3.0)
    assert got["mae_pct"] == pytest.approx(-4.0)
    assert got["close_pct"] == pytest.approx(2.0)


# ---------------------------------------------------------------
# IT MUST NEVER RAISE, AND NEVER WRITE
# ---------------------------------------------------------------

def test_junk_scores_to_None_rather_than_exploding():
    for row in ({}, _sig(break_price=0), _sig(break_price=None),
                _sig(break_price="abc")):
        assert sj.score_row(row) is None
    assert sj.score_row(_sig()) is None, "no data at all -> no score"


def test_a_broken_candle_does_not_break_the_walk():
    got = sj.score_row(_sig(), minutes=[
        ("t1", None, None, None, None),
        ("t2", 100, 101.0, 99.5, 100.8)])
    assert got is not None
    assert got["mfe_pct"] == pytest.approx(1.0)


def test_the_scorer_opens_every_store_read_only():
    """It reads three databases the LIVE BOT WRITES. A scorer that can
    hold a write lock on data/signal_journal.db can stall the tick
    loop that is trying to append to it."""
    src = (ROOT / "core" / "signal_journal.py").read_text(encoding="utf-8")
    body = src[src.find("def _ro("):src.find("def _pct(")]
    assert "mode=ro" in body
    code = src[src.find("def score("):]
    for call in ("_ro(db_path)", "_ro(candles_db)", "_ro(daily_db)"):
        assert call in code, f"{call} is not going through the read-only path"


def test_report_says_so_when_it_cannot_measure():
    got = sj.report(scored=[])
    assert got["available"] is False
    assert got["why"]


def test_a_thin_bucket_is_never_reported_as_a_finding():
    """Three signals with a good average is not a rule. min_cases is
    the difference between a measurement and an anecdote."""
    rows = [sj.score_row(_sig(refused_why="rare thing"),
                         daily=(110.0, 99.0, 109.0)) for _ in range(3)]
    rows += [sj.score_row(_sig(refused_why="common thing"),
                          daily=(101.0, 99.0, 100.0)) for _ in range(25)]
    got = sj.report(scored=rows, min_cases=20)
    assert "rare thing" not in got["by_refusal"]
    assert "common thing" in got["by_refusal"]


# ---------------------------------------------------------------
# IT MEASURES. IT DOES NOT DECIDE.
# ---------------------------------------------------------------

def test_no_gate_imports_the_scorer():
    """THE LINE THAT MUST NOT MOVE.

    A number measured this morning becoming an entry condition this
    afternoon is how a bot starts trading its own backtest. If a
    finding here earns a rule, that rule gets written, argued and
    tested on its own -- it does not arrive by import.
    """
    for name in ("auto_entry.py", "ranker.py", "engine.py"):
        src = (ROOT / "core" / name).read_text(encoding="utf-8")
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith("#"))
        for banned in ("signal_journal.score", "signal_journal.report",
                       "from core.signal_journal import score"):
            assert banned not in code, (
                f"core/{name} is deciding with a measurement")


def test_the_hypothesis_he_asked_about_is_actually_measured():
    """18 August: "stocks raising with underlying evidence must have
    added advantage rather than normal breakout stocks". That is a
    claim about outcomes, so the report has to answer it."""
    rows = [sj.score_row(_sig(results_grade="STRONG"),
                         daily=(105.0, 99.0, 104.0)) for _ in range(5)]
    rows += [sj.score_row(_sig(), daily=(101.0, 99.0, 100.0))
             for _ in range(5)]
    got = sj.report(scored=rows)
    assert got["evidence"]["with"]["n"] == 5
    assert got["evidence"]["without"]["n"] == 5
    assert (got["evidence"]["with"]["avg_close_pct"]
            > got["evidence"]["without"]["avg_close_pct"])


def test_he_can_read_it_from_the_phone_and_the_board():
    desk = (ROOT / "core" / "telegram_desk.py").read_text(encoding="utf-8")
    assert "def _score" in desk, "no way to ask for it from Telegram"
    server = (ROOT / "dashboard" / "server.py").read_text(encoding="utf-8")
    assert "/api/score" in server
