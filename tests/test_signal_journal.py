"""
Tests for core/signal_journal.py -- the refused signals, kept.

    "real movers are ignored by bot. as first see = buy & 10 slots
     filled."                            -- operator, 29 July 2026

He was probably right and it could not be checked. core/breakout_feed
holds every signal in memory; the process exits at 15:30. Six months of
refused setups were deleted daily, so the most important entry question
in the project --

    did the setups we REFUSED do better than the ones we TOOK?

-- had no answer and no way to get one.

The other thing this carries is the operator's three confirmations:
good results, volume, news. Recorded on every signal, gating on none of
them. Requiring news or results would have refused 33 of the 35 trades
that made Rs 18,389 to capture 2 worth Rs 2,986 -- so they rank, and
they wait for evidence before they gate.
"""

import os
import sqlite3

import pytest

from core.signal_journal import SignalJournal


@pytest.fixture
def journal(tmp_path):
    return SignalJournal(str(tmp_path / "j.db"))


def _rows(journal):
    conn = sqlite3.connect(journal.db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("select * from signals")]
    conn.close()
    return rows


# ---------------------------------------------------------------
# Refused signals survive the day -- the whole point
# ---------------------------------------------------------------

def test_a_refused_signal_is_written_not_forgotten(journal):
    journal.record("GODIGIT", "LONG", break_price=310.0,
                   refused_why="book full (10 positions)")
    journal.flush()
    row = _rows(journal)[0]
    assert row["symbol"] == "GODIGIT"
    assert row["taken"] == 0
    assert "book full" in row["refused_why"]


def test_taken_and_refused_both_land_in_the_same_table(journal):
    journal.record("AAA", "LONG", taken=True)
    journal.record("BBB", "LONG", refused_why="sector panic")
    journal.flush()
    assert {r["symbol"]: r["taken"] for r in _rows(journal)} == {
        "AAA": 1, "BBB": 0}


def test_a_signal_that_refires_all_afternoon_is_one_row(journal):
    """A breakout holding above its level triggers on every candle. It
    is ONE event, not forty."""
    for _ in range(40):
        journal.record("KAYNES", "LONG", break_price=3400.0)
    journal.flush()
    rows = _rows(journal)
    assert len(rows) == 1
    assert rows[0]["fired_count"] == 40


def test_taken_wins_permanently_over_a_later_refusal(journal):
    """A signal refused at 10:00 and taken at 10:30 is TAKEN. Without
    this, a later refusal would overwrite the truth and the journal
    would under-count its own entries."""
    journal.record("AAA", "LONG", refused_why="book full")
    journal.record("AAA", "LONG", taken=True)
    journal.record("AAA", "LONG", refused_why="book full")
    journal.flush()
    row = _rows(journal)[0]
    assert row["taken"] == 1
    assert row["refused_why"] is None


# ---------------------------------------------------------------
# The three confirmations
# ---------------------------------------------------------------

def test_all_three_confirmations_are_counted(journal):
    journal.record("INFY", "LONG", volume_mult=3.2, news_kind="RESULTS",
                   results_grade="STRONG")
    journal.flush()
    assert _rows(journal)[0]["confirmations"] == 3


def test_a_weak_results_grade_does_not_count_as_confirmation(journal):
    """Only STRONG and GOOD. MIXED and WEAK are not confirmations --
    they are the opposite."""
    journal.record("AAA", "LONG", volume_mult=3.0, results_grade="WEAK")
    journal.flush()
    assert _rows(journal)[0]["confirmations"] == 1


def test_thin_volume_does_not_count_as_confirmation(journal):
    journal.record("AAA", "LONG", volume_mult=1.1)
    journal.flush()
    assert _rows(journal)[0]["confirmations"] == 0


def test_confirmations_arriving_separately_are_all_kept(journal):
    """Volume is known at the breakout; results may land minutes later.
    A second call must fill in, never blank out."""
    journal.record("AAA", "LONG", volume_mult=3.0)
    journal.record("AAA", "LONG", results_grade="GOOD")
    journal.record("AAA", "LONG", news_kind="ORDER_WIN")
    journal.flush()
    row = _rows(journal)[0]
    assert row["volume_mult"] == 3.0
    assert row["results_grade"] == "GOOD"
    assert row["confirmations"] == 3


def test_the_attempt_number_is_recorded_but_nothing_scores_it(journal):
    """The lore says 'third time breaks'. An equally plausible story
    says each failed attempt burns buying pressure. Recorded, unjudged."""
    journal.record("AAA", "LONG", attempt=3)
    journal.flush()
    assert _rows(journal)[0]["attempt"] == 3


def test_how_full_the_book_was_is_recorded(journal):
    """Without this, 'the slots were full' is an assertion. With it,
    it is a number next to the outcome."""
    journal.record("AAA", "LONG", open_positions=10)
    journal.flush()
    assert _rows(journal)[0]["open_positions_at_signal"] == 10


# ---------------------------------------------------------------
# It can never break the tick loop
# ---------------------------------------------------------------

def test_an_unwritable_path_does_not_raise(tmp_path):
    journal = SignalJournal(str(tmp_path / "nope" / "x" / "j.db"))
    journal.record("AAA", "LONG")
    # A journal that could stop price processing would be worse than
    # no journal at all.
    assert journal.flush() in (0, 1)


def test_junk_arguments_are_survivable(journal):
    journal.record(None, None, break_price="not a number")
    journal.record("AAA", "LONG", volume_mult="junk")
    journal.flush()


def test_flushing_an_empty_journal_writes_nothing(journal):
    assert journal.flush() == 0


def test_counts_are_available_before_any_write(journal):
    journal.record("AAA", "LONG", taken=True)
    journal.record("BBB", "LONG", refused_why="full")
    assert journal.counts() == (1, 1)
