"""Several events across days is not the same as one event today.

    "in this case ather energy got multiple events in multi days & bot
     must relate & show the details highlighting the info next to ather
     energy stock"                 -- operator, 29 August 2026

ATHERENERG, 26-28 August 2026:

    26 Aug 08:56  Hero MotoCorp invests Rs 960cr via convertible warrants
    28 Aug 08:15  To buy additional stake for Rs 1,758cr
    28 Aug 09:01  Hero to acquire additional stake, Rs 1,758cr
    28 Aug 11:07  Ather up 7%, new F&O entrant, largest shareholder...

Four events, two sessions, ONE story -- somebody buying a company in
public, in instalments. The bot read each alone on the day it arrived.
It named the stock at 11:34 on the 26th, by which time that day's move
was spent, and the stock ran +8.9% to Friday's close.

Every row was already in stock_events.db. Nothing ever asked "has this
happened before, recently, to this stock".
"""

from datetime import datetime

import pytest

from core.stock_events import StockEvents

NOW = datetime(2026, 8, 29, 8, 0)


@pytest.fixture(scope="module")
def store():
    return StockEvents()


def test_ather_reads_as_a_run(store):
    got = store.running_story("ATHERENERG", days=7, now=NOW)
    if got is None:
        pytest.skip("no Ather events on this machine")
    assert got["events"] >= 2
    assert got["days"] >= 2, "26 Aug and 28 Aug are different sessions"
    assert got["headlines"], "the run must carry its own evidence"


def test_one_event_is_not_a_story(store):
    """The half that matters as much. Claiming a pattern from a single
    event would be inventing one."""
    assert store.running_story("NOSUCHSTOCK", days=7, now=NOW) is None
    assert store.running_story("", days=7, now=NOW) is None
    assert store.running_story(None, days=7, now=NOW) is None


def test_it_counts_SESSIONS_not_just_rows(store):
    """Four headlines on one afternoon is a busy news day, not a run
    across days. days must come from distinct dates."""
    got = store.running_story("ATHERENERG", days=7, now=NOW)
    if got is None:
        pytest.skip("no Ather events")
    assert got["days"] <= got["events"]


def test_the_window_is_respected(store):
    """A one-day window cannot see the 26 August leg."""
    wide = store.running_story("ATHERENERG", days=7, now=NOW)
    narrow = store.running_story("ATHERENERG", days=1, now=NOW)
    if wide is None:
        pytest.skip("no Ather events")
    if narrow is not None:
        assert narrow["events"] <= wide["events"]


def test_it_never_raises_on_a_broken_store():
    """This runs inside a snapshot build."""
    broken = StockEvents.__new__(StockEvents)
    assert broken.running_story("ATHERENERG", days=7, now=NOW) is None


def test_the_row_and_the_board_both_carry_it():
    import inspect
    from dashboard.state import DashboardState
    assert 'row["story"] = self._story_for(' in inspect.getsource(DashboardState)
    import os
    board = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "dashboard", "static", "board.html")
    with open(board, encoding="utf-8") as handle:
        html = handle.read()
    assert "(r.story.stories || r.story.events) > 1" in html, \
        "only a RUN is drawn -- one event is news, not a situation"


# ==========================================================
#  AND WHAT DID THE STOCK DO
# ==========================================================
#     "i want to see the linkage (memory brain + map = links to stocks
#      + news/events + outcome if the stock movement from that day)"
#                                    -- operator, 29 August 2026

def test_each_story_carries_what_the_stock_did(store):
    got = store.running_story("ATHERENERG", days=7, now=NOW)
    if got is None:
        pytest.skip("no Ather events")
    assert got["told"], "a story with no outcome is trivia"
    for told in got["told"]:
        assert "headline" in told and "at" in told
        outcome = told.get("outcome")
        if outcome is None:
            continue                    # today's own story, not closed
        assert "day_pct" in outcome and "since_pct" in outcome


def test_the_outcome_comes_from_the_settled_record(store):
    """Never live ticks -- an outcome that moves while you read it is
    not an outcome."""
    import inspect
    src = inspect.getsource(type(store)._move_on)
    assert "daily_store" in src or "DailyStore" in src
    assert "market_data" not in src and "latest_price" not in src


def test_a_day_not_on_file_is_None_not_zero(store):
    """Today's own story before today has closed. Zero would read as
    'the news did nothing', which is a different claim."""
    assert store._move_on("ATHERENERG", "2099-01-01") is None
    assert store._move_on("NOSUCHSTOCK", "2026-08-26") is None
    assert store._move_on("", "2026-08-26") is None


def test_the_day_move_is_open_to_close(store):
    """Not previous-close to close. The news arrived in the morning;
    measuring from yesterday would credit the story with an overnight
    gap it had nothing to do with."""
    import inspect
    src = inspect.getsource(type(store)._move_on)
    assert "bars.c.open" in src


def test_the_board_draws_the_outcome():
    import os
    board = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "dashboard", "static", "board.html")
    with open(board, encoding="utf-8") as handle:
        html = handle.read()
    assert "st.told" in html, "the chip must show the outcomes"
    assert "since_pct" in html
    # Green only when the runs actually paid.
    assert "paid ? " in html
