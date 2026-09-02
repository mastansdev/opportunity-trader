"""---- 89 STOCKS, NO NAMES. 2 September 2026. ----

    "no event -- not evaluated x89"

That line is the largest refusal of most sessions and the only one that
names nobody. A stock reaches the candidate pool through one of a few
doors -- a filing, a news item, a results grade, reporting today, or
trading at SURGE_REASON_MIN_RATIO times its own normal volume. Miss all
of them and it is never scored, so there is no refusal to record and it
leaves no trace at all.

On 1 September the market offered 37 stocks up 3%+ on three times their
normal volume, in the bot's own universe. The bot saw 35 of them. But
SAKAR (+11.9%), IZMO (+10.0%), JAYKAY (+8.3%), YATRA (+7.0%) and TNPL
(+6.0%) had NOTHING recorded before 11:38 -- they were not refused,
they were never looked at, and the record could not say so.

THE NUMBER IS THE POINT.

    "i want your complete understanding & guidance . never average or
     assume"

Not "it had no reason" but how close it came: the volume multiple it
actually reached against the bar it needed. Best movers sitting at 6-9x
against a 10x bar is an argument to move the bar, with evidence. At
1.5x the bar is right and the answer is elsewhere. Those two look
identical today.
"""

import os
import sqlite3
import tempfile
from datetime import datetime

import pytest

from core.decision_log import DecisionLog


@pytest.fixture
def log():
    path = os.path.join(tempfile.mkdtemp(), "d.db")
    try:
        yield DecisionLog(path), path
    finally:
        pass


SAKAR = ("up 11.9% and never in the pool: nothing published, "
         "volume 6.4x (bar 10x)")
IZMO = ("up 10.0% and never in the pool: nothing published, "
        "volume 4.7x (bar 10x)")


def _rows(path, symbol=None):
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    sql = "select symbol, reason, first_at, last_at, n from pool_misses"
    args = ()
    if symbol:
        sql += " where symbol=?"
        args = (symbol,)
    got = c.execute(sql + " order by symbol, first_at", args).fetchall()
    c.close()
    return got


def test_a_moving_stock_outside_the_pool_is_named(log):
    """The whole point. It used to be an anonymous count."""
    lg, path = log
    lg.record_pool_misses({"SAKAR": SAKAR}, when=datetime(2026, 9, 1, 10, 15))
    got = _rows(path, "SAKAR")
    assert len(got) == 1
    assert "6.4x" in got[0][1], got[0][1]


def test_the_same_state_repeated_is_one_row_with_a_count(log):
    lg, path = log
    for minute in (15, 20, 25):
        lg.record_pool_misses({"SAKAR": SAKAR},
                              when=datetime(2026, 9, 1, 10, minute))
    got = _rows(path, "SAKAR")
    assert len(got) == 1
    assert got[0][4] == 3, got
    assert got[0][2][11:16] == "10:15" and got[0][3][11:16] == "10:25"


def test_a_stock_crossing_the_bar_is_its_own_row(log):
    """SAKAR at 6.4x in the morning and 11.2x by 11:05 are two different
    facts. If it is STILL outside the pool at 11.2x against a 10x bar,
    that is a finding -- and collapsing them would hide it."""
    lg, path = log
    lg.record_pool_misses({"SAKAR": SAKAR}, when=datetime(2026, 9, 1, 10, 15))
    lg.record_pool_misses(
        {"SAKAR": "up 11.9% and never in the pool: nothing published, "
                  "volume 11.2x (bar 10x)"},
        when=datetime(2026, 9, 1, 11, 5))
    got = _rows(path, "SAKAR")
    assert len(got) == 2, got
    assert "6.4x" in got[0][1] and "11.2x" in got[1][1]


def test_two_stocks_do_not_share_a_row(log):
    lg, path = log
    lg.record_pool_misses({"SAKAR": SAKAR, "IZMO": IZMO},
                          when=datetime(2026, 9, 1, 10, 15))
    assert len(_rows(path)) == 2


def test_nothing_to_record_is_not_an_error(log):
    lg, path = log
    for empty in ({}, None):
        assert lg.record_pool_misses(empty) == 0


def test_rubbish_does_not_reach_the_table(log):
    lg, path = log
    lg.record_pool_misses({"": "no symbol", "OK": "", None: "x", "GOOD": SAKAR},
                          when=datetime(2026, 9, 1, 10, 15))
    got = _rows(path)
    assert [r[0] for r in got] == ["GOOD"], got


def test_it_never_raises_into_the_build(log):
    """It runs inside build_ranked. A bookkeeping failure must not take
    the snapshot down."""
    lg, path = log
    lg._connect = lambda: (_ for _ in ()).throw(RuntimeError("disk gone"))
    assert lg.record_pool_misses({"SAKAR": SAKAR}) == 0


# ------------------------------------------------- and it is wired in

def test_build_ranked_actually_records_them():
    """A store nothing writes to is the fault this repo keeps finding."""
    import inspect

    import dashboard.state as st

    src = inspect.getsource(st.DashboardState.build_ranked)
    assert "record_pool_misses" in src, (
        "the pool misses are computed and never written")


def test_only_moving_stocks_are_recorded():
    """1,300 quiet stocks outside the pool are not missed opportunities,
    and writing them down would bury the ones that are."""
    import inspect

    import dashboard.state as st

    src = inspect.getsource(st.DashboardState._pool_misses)
    assert "MIN_MOVE_FROM_PREV_CLOSE_PCT" in src, (
        "every quiet stock in the market is being recorded as a miss")


def test_the_reason_carries_the_actual_multiple():
    """"no reason" is not an argument. "6.4x against a 10x bar" is."""
    import inspect

    import dashboard.state as st

    src = inspect.getsource(st.DashboardState._pool_misses)
    assert "SURGE_REASON_MIN_RATIO" in src and "ratio" in src
