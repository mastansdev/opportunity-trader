"""
==========================================================
The same fill, filed under a second date, is not a second trade
==========================================================

    "okay so what should we improve now to make bot profitable?"
                                -- operator, 16 August 2026

The first thing to improve was the number he would have judged it on.

data/trade_memory.db held three adopted positions TWICE -- same entry
price, same exit price, same quantity, same P&L, on consecutive days:

    CORONA     2026-08-05  2266.24 -> 2096.70  q=100  -16,954
    CORONA     2026-08-06  2266.24 -> 2096.70  q=100  -16,954
    DEEPAKNTR  x2  -6,324        DEEPAKFERT x2  -4,030

Rs 27,309 counted twice out of Rs 69,766 of adopted losses, so that
group read 64% worse than it was, and the whole book read -81,530
when it was -54,221.

WHY THE EXISTING GUARD MISSED IT
--------------------------------
UniqueConstraint(symbol, direction, trade_date) -- and its comment is
honest about the limit: "a re-run or a restart can't double-count a
trade". It cannot see a restart on the NEXT DAY. An adopted position
is re-adopted once per process start, so starting again tomorrow files
the same holding under a new trade_date and the constraint is
satisfied.

tools/dry_run_live_path.py junction 15 was written for exactly this
fault -- its docstring says "DEEPAKNTR appeared twice ... adopted once
per process start" -- and it watches data/session_state.json, which is
cleared between sessions. The rows land in trade_memory.db, which had
no guard at all.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.trade_memory import TradeMemory


# NOTE ON trade_date. record() does NOT take it from the caller: it is
# entry_time.date() when entry_time is a datetime, and TODAY otherwise.
# An adopted broker position carries entry_time=None -- the bot never
# saw the fill -- so its trade_date is simply the day it was recorded.
# That is precisely how one holding became 2026-08-05 and 2026-08-06.
# These tests move the CLOCK to reproduce that, rather than passing a
# trade_date that record() would ignore.
def _fill(**over):
    row = {"symbol": "CORONA", "direction": "LONG",
           "entry_time": None, "entry_price": 2266.24,
           "exit_price": 2096.70, "qty": 100, "pnl": -16954.0,
           "exit_reason": "TRAILING_STOP",
           "entry_reason": "ADOPTED_FROM_BROKER"}
    row.update(over)
    return row


def _frozen(day):
    """A datetime SUBCLASS whose now() is fixed.

    It must remain a real datetime: record() does
    isinstance(entry_time, datetime) to decide whether it has a fill
    time, and a plain stub makes that raise TypeError -- which the
    bare `except Exception: return False` swallows, so every record
    silently fails and the test reads as a guard that is working.
    """
    from datetime import datetime as _dt

    class _Frozen(_dt):
        @classmethod
        def now(cls, tz=None):
            return day

    return _Frozen


@pytest.fixture
def mem(tmp_path):
    return TradeMemory(url="sqlite:///" + str(tmp_path / "tm.db").replace(chr(92), "/"))


def _on(monkeypatch, day):
    """Record as if it were `day` -- a restart on the next session."""
    import core.trade_memory as tm
    monkeypatch.setattr(tm, "datetime", _frozen(day))


def test_the_same_fill_on_a_later_date_is_refused(mem, monkeypatch):
    """THE REGRESSION. Restarting tomorrow re-adopts the position and
    records the same fill again under a new trade_date."""
    from datetime import datetime as _d
    _on(monkeypatch, _d(2026, 8, 5, 15, 30))
    assert mem.record(_fill()) is True
    _on(monkeypatch, _d(2026, 8, 6, 15, 30))
    assert mem.record(_fill()) is False, (
        "the same fill was recorded twice under a different date -- "
        "this is the Rs 27,309 double-count")


def test_the_same_day_guard_still_works(mem):
    assert mem.record(_fill()) is True
    assert mem.record(_fill(pnl=-1.0)) is False


def test_a_genuine_second_trade_still_records(mem, monkeypatch):
    """The line that must not over-reach. Buying the same stock again
    at a DIFFERENT price on a later day is a real second trade and
    refusing it would hide live business."""
    from datetime import datetime as _d
    _on(monkeypatch, _d(2026, 8, 5, 15, 30))
    assert mem.record(_fill()) is True
    _on(monkeypatch, _d(2026, 8, 7, 15, 30))
    assert mem.record(_fill(entry_price=2100.0, exit_price=2150.0,
                            pnl=5000.0)) is True


def test_a_different_quantity_is_a_different_trade(mem, monkeypatch):
    from datetime import datetime as _d
    _on(monkeypatch, _d(2026, 8, 5, 15, 30))
    assert mem.record(_fill()) is True
    _on(monkeypatch, _d(2026, 8, 7, 15, 30))
    assert mem.record(_fill(qty=50, pnl=-8477.0)) is True


def test_a_different_symbol_is_never_blocked(mem, monkeypatch):
    from datetime import datetime as _d
    _on(monkeypatch, _d(2026, 8, 5, 15, 30))
    assert mem.record(_fill()) is True
    _on(monkeypatch, _d(2026, 8, 6, 15, 30))
    assert mem.record(_fill(symbol="DEEPAKNTR")) is True


def test_the_live_store_has_no_remaining_duplicates():
    """Guards the real file. The three known pairs are history and
    stay -- deleting his trade record to make a number look better is
    not a fix -- but no NEW pair may appear."""
    import sqlite3
    con = sqlite3.connect("file:data/trade_memory.db?mode=ro", uri=True)
    dupes = list(con.execute(
        "SELECT symbol, entry_price, exit_price, qty, COUNT(*) n "
        "FROM trade_memory GROUP BY symbol, direction, entry_price, "
        "exit_price, qty HAVING COUNT(*) > 1"))
    con.close()
    known = {"CORONA", "DEEPAKNTR", "DEEPAKFERT"}
    fresh = [d for d in dupes if d[0] not in known]
    assert not fresh, f"new duplicate fills recorded: {fresh}"
