"""---- ONE REASON PER STOCK PER DAY WAS NOT ENOUGH. 2 Sep 2026. ----

    "yes fix the journal to keep every reason with timestamp"
                                                -- the operator

`signals.refused_why` kept the LAST reason of the day. So a stock
refused all morning for one thing and at 15:20 for another read as
though only the second had ever happened. On 1 September SSWL, DYCL,
GODREJAGRO and VTL all showed

    "after 15:15 -- too late to give a new position room to work"

which is what the record said at 15:30 and says nothing about why they
were refused at 10:00, while they were actually moving.

WHY IT MATTERED THAT DAY. The market offered 37 stocks up 3%+ on three
times their normal volume. The bot SAW 35 of them -- the candidate pool
was never the problem -- and the record could not say what stopped each
one at the moment it mattered. The only question worth asking was
unanswerable:

    "since the last recent we shifted to whats opportunity in market &
     what bot did instead of grabbing those opportunity"

core/decision_log.py already does this correctly for the RANKER's
refusals: UNIQUE(date, symbol, reason), first_at, last_at, count. This
is the same shape for the ROUTING side, which is where "book full",
"already traded today" and the time cutoff live.
"""

import os
import sqlite3
import tempfile
from datetime import datetime

import pytest

from core.signal_journal import SignalJournal


@pytest.fixture
def journal():
    path = os.path.join(tempfile.mkdtemp(), "j.db")
    yield SignalJournal(path), path


DAY = [
    ("no event behind it", datetime(2026, 9, 1, 10, 0)),
    ("no event behind it", datetime(2026, 9, 1, 10, 5)),
    ("no event behind it", datetime(2026, 9, 1, 11, 30)),
    ("book full (4 of 4) and slot rotation is OFF",
     datetime(2026, 9, 1, 13, 0)),
    ("after 15:15 -- too late to give a new position room to work",
     datetime(2026, 9, 1, 15, 20)),
]


def _run(j, symbol="SSWL"):
    for why, when in DAY:
        j.record(symbol, "LONG", taken=False, refused_why=why, when=when)
    j.flush()


def _rows(path, symbol="SSWL"):
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    got = c.execute("select reason, first_at, last_at, n from pick_reasons "
                    "where symbol=? order by first_at", (symbol,)).fetchall()
    c.close()
    return got


def test_every_distinct_reason_is_kept(journal):
    j, path = journal
    _run(j)
    reasons = [r[0] for r in _rows(path)]
    assert len(reasons) == 3, reasons
    assert "no event behind it" in reasons
    assert any("book full" in r for r in reasons)
    assert any("after 15:15" in r for r in reasons)


def test_the_same_reason_repeated_is_one_row_with_a_count(journal):
    """Three refusals for the same thing is one fact, not three."""
    j, path = journal
    _run(j)
    row = [r for r in _rows(path) if r[0] == "no event behind it"][0]
    assert row[3] == 3, row


def test_each_reason_carries_its_own_clock(journal):
    """The whole point: WHEN was it refused for this, not for the day's
    last thing."""
    j, path = journal
    _run(j)
    first = {r[0]: (r[1], r[2]) for r in _rows(path)}
    assert first["no event behind it"] == ("2026-09-01 10:00:00",
                                           "2026-09-01 11:30:00")
    late = [v for k, v in first.items() if "after 15:15" in k][0]
    assert late[0] == "2026-09-01 15:20:00"


def test_the_morning_reason_is_not_hidden_by_the_evening_one(journal):
    """The exact 1 September failure. SSWL read "after 15:15" all the
    way back to 10:00, which is when it was actually moving."""
    j, path = journal
    _run(j)
    at_ten = [r for r in _rows(path) if r[1] <= "2026-09-01 10:00:00"]
    assert at_ten and at_ten[0][0] == "no event behind it", (
        "what stopped it in the morning is still invisible")


def test_the_old_field_still_holds_the_last_reason(journal):
    """Anything already reading signals.refused_why keeps working."""
    j, path = journal
    _run(j)
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    got = c.execute("select refused_why from signals").fetchone()[0]
    c.close()
    assert "after 15:15" in got


def test_a_taken_signal_records_no_refusal(journal):
    j, path = journal
    j.record("WINNER", "LONG", taken=True, when=datetime(2026, 9, 1, 10, 0))
    j.flush()
    assert _rows(path, "WINNER") == []


def test_two_stocks_do_not_share_rows(journal):
    j, path = journal
    _run(j, "SSWL")
    j.record("DYCL", "LONG", taken=False, refused_why="book full (4 of 4)",
             when=datetime(2026, 9, 1, 12, 0))
    j.flush()
    assert len(_rows(path, "SSWL")) == 3
    assert len(_rows(path, "DYCL")) == 1


def test_flushing_twice_does_not_double_the_count(journal):
    """flush() is called from the heartbeat. It must be idempotent."""
    j, path = journal
    _run(j)
    j.flush()
    j.flush()
    row = [r for r in _rows(path) if r[0] == "no event behind it"][0]
    assert row[3] == 3, f"count inflated by a second flush: {row}"
