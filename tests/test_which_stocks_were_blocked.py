"""Which stocks the bot said no to, not just how often it said no.

    "next the stocks with their parsed sales figures are absurd , when
     they were blocked from trading . why still today i cannot see
     which stocks were blocked & reason"
                                        -- operator, 30 August 2026

Because the name was never written down.

    picks      (date, at, rank, SYMBOL, action, score, ...)
    refusals   (date, at, reason, n)          <- no symbol, ever

259,674 rows summing to 5.7 million refusals, every one anonymous. So
"why was TVSMOTOR skipped" was unanswerable from history, and
/api/why's own docstring says so.

AND THE BOT HAD THE NAME THE WHOLE TIME. core/select.py builds
{symbol: reason} -- "already holding it", "not in the tradeable
universe", "at its circuit" -- and hands it straight to
record_refusals(), which tallied the reason and dropped the symbol on
purpose: "the reason is what is counted". That answered one good
question and threw away another.

ONE ROW PER SYMBOL PER REASON PER DAY. The ranker refuses roughly
1,100 stocks every cycle, all session: per-cycle rows would be
millions a day, which is why the original was a census in the first
place. Upserted instead, with `n` counting the cycles -- about 1,100
rows a day, and "refused since 09:21, 118 cycles" is a stronger
reading than any single timestamp.
"""

import os
import tempfile

import pytest

from core.decision_log import DecisionLog


@pytest.fixture
def log():
    folder = tempfile.mkdtemp()
    return DecisionLog(db_path=os.path.join(folder, "decisions.db"))


# ------------------------------------------------------- the name is kept

def test_the_symbol_survives(log):
    log.record_refusals({"TVSMOTOR": "no volume behind it",
                         "GRSE": "no reason found"})
    got = {r["symbol"]: r["reason"] for r in log.refused_symbols()}
    assert got == {"TVSMOTOR": "no volume behind it",
                   "GRSE": "no reason found"}


def test_the_census_still_works(log):
    """Both questions are worth answering. Keeping the symbol must not
    cost the count of how often each gate fired."""
    log.record_refusals({"TVSMOTOR": "no volume behind it",
                         "GRSE": "no volume behind it"})
    assert log.refusals()["no volume behind it"] == 2


def test_a_plain_census_still_records_and_names_nobody(log):
    """core/ranker.py sends {reason: count} -- no symbols to keep. It
    must not become an error, and must not invent a symbol."""
    log.record_refusals({"not moving enough": 812})
    assert log.refusals()["not moving enough"] == 812
    assert log.refused_symbols() == []


# ------------------------------------------------- one row, many cycles

def test_the_same_refusal_all_day_is_one_row(log):
    """1,100 stocks a cycle, all session, would be millions of rows a
    day -- which is why the original table was a census."""
    for _ in range(50):
        log.record_refusals({"TVSMOTOR": "no volume behind it"})
    rows = log.refused_symbols()
    assert len(rows) == 1
    assert rows[0]["cycles"] == 50


def test_a_stock_refused_two_ways_keeps_both(log):
    """A stock can fail two gates in a session, and which one it was
    at 09:20 is a different fact from which it was at 14:00."""
    log.record_refusals({"BEL": "no volume behind it"})
    log.record_refusals({"BEL": "at its circuit"})
    assert len(log.refused_symbols()) == 2


def test_the_first_time_is_kept_not_the_last(log):
    """"refused since 09:21" is the useful reading. Overwriting it with
    the newest cycle would make every row say "a moment ago"."""
    from datetime import datetime

    early = datetime(2026, 8, 31, 9, 21, 4)
    late = datetime(2026, 8, 31, 14, 55, 0)
    log.record_refusals({"BEL": "no volume behind it"}, when=early)
    log.record_refusals({"BEL": "no volume behind it"}, when=late)
    row = log.refused_symbols(date="2026-08-31")[0]
    assert row["first_at"].endswith("09:21:04")
    assert row["last_at"].endswith("14:55:00")


def test_the_longest_standing_refusal_comes_first(log):
    """A stock refused since the open is a settled decision; one
    refused twice may simply not have ticked yet."""
    for _ in range(9):
        log.record_refusals({"OLD": "no volume behind it"})
    log.record_refusals({"NEW": "no reason found"})
    assert [r["symbol"] for r in log.refused_symbols()][0] == "OLD"


# ------------------------------------------------------------ never fatal

def test_a_broken_store_returns_nothing_rather_than_raising(tmp_path):
    """A diagnostic panel must never be able to take the snapshot
    down -- the rule every panel in dashboard/state.py follows."""
    log = DecisionLog(db_path=str(tmp_path / "nope" / "x.db"))
    assert log.refused_symbols() == []


def test_mixed_shapes_do_not_lose_the_batch(log):
    """---- TWO PRODUCERS, TWO SHAPES. 19 August 2026. ----
    One unreadable entry once threw away a whole cycle's census. The
    named rows must survive the same mixture."""
    log.record_refusals({"not moving enough": 812,
                         "TVSMOTOR": "no volume behind it",
                         "BROKEN": True})
    assert log.refusals()["not moving enough"] == 812
    assert [r["symbol"] for r in log.refused_symbols()] == ["TVSMOTOR"]


# ---------------------------------------------------------- on the screen

def test_the_row_carries_it_to_the_page():
    import inspect

    from dashboard.state import DashboardState

    src = inspect.getsource(DashboardState)
    assert '"refused_today": self._safe_refused_today()' in src
