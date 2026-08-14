"""
==========================================================
Running the backfill twice must not double the file
==========================================================

DAILY_ROUTINE.md, after every close:

    py tools/build_stock_events.py --apply

and the tool's own docstring says "Safe to re-run; it only adds what
is new". On 31 July 2026 that was measured for the first time. Two
identical runs, back to back, on an unchanged telegram.db:

    run A   104 new events stored (274 were already there)
    run B   150 new events stored (228 were already there)

WHY
---
NULL IS NOT EQUAL TO NULL. That is the SQL standard, and it means a
UNIQUE index over a nullable column cannot detect a repeat when the
column is NULL.

    CREATE UNIQUE INDEX ux_event ON events (symbol, at, kind, headline)

Market-scope events are stored with symbol=NULL on purpose -- a Fed
decision belongs to no single company. So every market event was
re-inserted on every run, while the log calmly reported how many were
"already there".

The split in the evidence is total:

    duplicated groups where a symbol was present   0
    duplicated groups where symbol was NULL      150

It had been compounding once a day since the tool was written, and
nothing complained, because a table getting bigger is what a table
that collects things is supposed to do.

Author : H&M Opportunity Trader
==========================================================
"""

import sqlite3

import pytest

from core.stock_events import StockEvents


@pytest.fixture
def store(tmp_path):
    return StockEvents(db_path=str(tmp_path / "events.db"))


def _count(store):
    conn = sqlite3.connect(store.db_path)
    n = conn.execute("select count(*) from events").fetchone()[0]
    conn.close()
    return n


MARKET = dict(symbol=None, at="2026-07-28T17:10", kind="MACRO",
              headline="Extended engagement for CODI deposit insurance",
              scope="MARKET")
STOCK = dict(symbol="GAIL", at="2026-07-31T08:54", kind="RESULT",
             headline="PAT +203% vs est -- #GAIL - Strong Beat",
             scope="STOCK", grade="EXCELLENT")


# ---------------------------------------------------------------
# 1. THE BUG
# ---------------------------------------------------------------
def test_a_market_event_stored_twice_is_stored_once(store):
    """The exact failure. symbol=None on both, everything else equal."""
    assert store.remember(**MARKET) is True
    assert store.remember(**MARKET) is False, (
        "a second identical market event was accepted -- NULL symbols "
        "escape the unique index unless it coalesces them")
    assert _count(store) == 1


def test_ten_runs_of_the_same_market_event_leave_one_row(store):
    """A daily tool compounds. One duplicate a day is a table that has
    doubled by the time anybody looks."""
    for _ in range(10):
        store.remember(**MARKET)
    assert _count(store) == 1


# ---------------------------------------------------------------
# 2. THE HALF THAT ALWAYS WORKED MUST KEEP WORKING
# ---------------------------------------------------------------
def test_a_stock_event_is_still_deduplicated(store):
    assert store.remember(**STOCK) is True
    assert store.remember(**STOCK) is False
    assert _count(store) == 1


# ---------------------------------------------------------------
# 3. AND GENUINELY DIFFERENT EVENTS MUST STILL BOTH BE KEPT
# ---------------------------------------------------------------
@pytest.mark.parametrize("field,value", [
    ("at", "2026-07-28T17:11"),
    ("kind", "NEWS"),
    ("headline", "Something else entirely happened"),
])
def test_events_differing_in_any_key_field_are_both_kept(store, field, value):
    """Deduplication that swallows real events is worse than the
    duplication it replaced."""
    store.remember(**MARKET)
    store.remember(**dict(MARKET, **{field: value}))
    assert _count(store) == 2


def test_a_market_event_and_a_stock_event_do_not_collide(store):
    """The same headline can legitimately be filed once against a
    company and once as market context."""
    store.remember(**MARKET)
    store.remember(**dict(MARKET, symbol="GAIL", scope="STOCK"))
    assert _count(store) == 2


# ---------------------------------------------------------------
# 4. AN EXISTING FILE FULL OF DUPLICATES IS REPAIRED ON OPEN
# ---------------------------------------------------------------
def test_opening_a_polluted_database_cleans_it(tmp_path):
    """The operator's own file had 771 rows of which 393 were repeats.

    A UNIQUE index cannot be built over a table that already violates
    it, so the migration has to remove the duplicates first -- keeping
    the OLDEST row of each group, because created_at on the first one
    is when the event was actually first seen.
    """
    path = str(tmp_path / "dirty.db")
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, at TEXT,
        kind TEXT, scope TEXT, grade TEXT, value_cr REAL,
        counterparty TEXT, headline TEXT, source TEXT, url TEXT,
        from_image INTEGER DEFAULT 0, created_at TEXT)""")
    for _ in range(4):
        conn.execute("INSERT INTO events (symbol, at, kind, headline) "
                     "VALUES (NULL, '2026-07-28T17:10', 'MACRO', 'dup')")
    conn.execute("INSERT INTO events (symbol, at, kind, headline) "
                 "VALUES ('GAIL', '2026-07-31T08:54', 'RESULT', 'real')")
    conn.commit()
    conn.close()

    StockEvents(db_path=path)          # _ensure() migrates on open

    conn = sqlite3.connect(path)
    rows = conn.execute("select coalesce(symbol,'~'), headline "
                        "from events order by id").fetchall()
    conn.close()
    assert rows == [("~", "dup"), ("GAIL", "real")], (
        "the migration must collapse the duplicates and keep the "
        "genuine row")
