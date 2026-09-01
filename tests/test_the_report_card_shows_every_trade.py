"""---- THE REPORT CARD SHOWED HALF THE DAY. 1 September 2026. ----

    "i want bot report card after market closed time"
    "for today no issue but from tomorrow it must report"
                                                -- the operator

The bot traded four round trips on 1 September. `py tools/day_report.py`
showed two, and nothing was logged to say the other two had gone:

    MARINE  11:08 -> 11:29   +177   stored
    MARINE  11:30 -> 14:58    +98   DROPPED
    VTL     14:38 -> 15:02    -32   stored
    VTL     15:02 -> 15:17    +24   DROPPED

TWO FAULTS, and the second is why the first bites.

ONE TRADE PER STOCK PER DAY. The duplicate guard in
core/trade_memory.record() was (symbol, direction, trade_date). It was
written so a restart cannot double-count a trade and it does that job
-- but re-entering the same name later the same day is ordinary
business, it happened twice in one session, and every re-entry after
the first was refused as a duplicate. The ENTRY TIME separates them:
two round trips have different ones, the same trade re-recorded after a
restart has the same one.

CARRIED TRADES CAME BACK AS TEXT. data/session_state.json is JSON, so a
position that survives a restart returns its times as ISO strings.
Every `isinstance(x, datetime)` test in record() then failed and the
trade was filed with entry_time None -- which is precisely the
signature this module uses to mean "adopted from the broker, the bot
never saw the fill". On MTF the bot carries overnight BY DESIGN, so
that is the normal path, not an edge case.
"""

from datetime import datetime

import pytest

from sqlalchemy import select

from core.trade_memory import TradeMemory, _as_datetime


@pytest.fixture
def store(tmp_path):
    return TradeMemory(url=f"sqlite:///{tmp_path / 'tm.db'}")


def _trade(symbol, entry_at, exit_at, entry, exit_px, qty, pnl):
    return {
        "symbol": symbol, "direction": "LONG",
        "entry_time": entry_at, "exit_time": exit_at,
        "entry_price": entry, "exit_price": exit_px,
        "qty": qty, "pnl": pnl,
        "entry_reason": "RANKED_SETUP", "exit_reason": "BUYING_DRIED_UP",
        "holding_seconds": 1260,
    }


# The real session, to the rupee.
DAY = [
    _trade("MARINE", datetime(2026, 9, 1, 11, 8, 20),
           datetime(2026, 9, 1, 11, 29, 6), 430.16, 431.78, 109, 176.58),
    _trade("MARINE", datetime(2026, 9, 1, 11, 30, 46),
           datetime(2026, 9, 1, 14, 58, 56), 432.82, 433.73, 108, 98.28),
    _trade("VTL", datetime(2026, 9, 1, 14, 38, 18),
           datetime(2026, 9, 1, 15, 2, 16), 603.85, 603.65, 159, -31.80),
    _trade("VTL", datetime(2026, 9, 1, 15, 2, 18),
           datetime(2026, 9, 1, 15, 17, 0), 603.60, 603.75, 159, 23.85),
]


def test_all_four_round_trips_are_stored(store):
    """The whole point. Two of these were thrown away silently."""
    kept = [store.record(t) for t in DAY]
    assert kept == [True, True, True, True], kept


def test_the_second_trade_in_a_stock_is_not_a_duplicate(store):
    """MARINE, bought again 97 seconds after it was sold. Ordinary
    business, and it was being filed as a re-run of the first."""
    assert store.record(DAY[0]) is True
    assert store.record(DAY[1]) is True, (
        "the second MARINE trade is still being dropped")


def test_the_same_trade_recorded_twice_is_still_refused(store):
    """The guard's real job, which must survive the fix. A restart that
    replays a closed position must not count it again."""
    assert store.record(DAY[0]) is True
    assert store.record(dict(DAY[0])) is False, (
        "a restart can double-count a trade again")


def test_the_pnl_adds_up_to_the_whole_day(store):
    for t in DAY:
        store.record(t)
    total = round(sum(t["pnl"] for t in DAY), 2)
    assert total == 266.91
    # And nothing was lost on the way in.
    assert sum(1 for t in DAY if store.record(t) is False) == 4


# ------------------------------------------- a carried trade keeps its time

def test_a_time_that_came_back_as_text_is_still_a_time():
    """session_state.json returns ISO strings for anything carried
    across a restart -- and the bot carries overnight on MTF by
    design."""
    got = _as_datetime("2026-09-01T11:08:17.164716")
    assert isinstance(got, datetime)
    assert got.hour == 11 and got.minute == 8


def test_rubbish_is_not_a_time():
    for bad in (None, "", "not a date", 12345, [1]):
        assert _as_datetime(bad) is None


def test_a_carried_trade_is_not_filed_as_an_adopted_one(store):
    """entry_time None is this module's signature for a position
    adopted from the broker, which it dedupes by PRICE. A trade the bot
    opened itself and carried across a restart is not that, and being
    filed as one hid it behind a different guard entirely."""
    carried = dict(DAY[1])
    carried["entry_time"] = "2026-09-01T11:30:46.000000"
    carried["exit_time"] = "2026-09-01T14:58:56.000000"
    assert store.record(carried) is True
    with store.engine.begin() as conn:
        got = conn.execute(
            select(store.trades.c.entry_time, store.trades.c.trade_date)
            .where(store.trades.c.symbol == "MARINE")).first()
    assert got is not None and got[0] is not None, (
        "the carried trade was filed with no entry time")
    assert str(got[1]) == "2026-09-01", (
        f"filed under the wrong day: {got[1]}")


def test_two_carried_trades_in_one_stock_both_survive(store):
    """Both halves together: re-entry AND restored-as-text."""
    a = dict(DAY[0]); a["entry_time"] = "2026-09-01T11:08:20"
    b = dict(DAY[1]); b["entry_time"] = "2026-09-01T11:30:46"
    assert store.record(a) is True
    assert store.record(b) is True
