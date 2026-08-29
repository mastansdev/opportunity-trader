"""The buy/sell split is kept now, and it still decides nothing.

    "by volume , order flow which carries the buyer & seller will
     give us info"              -- operator, 29 August 2026

core/order_flow.py exists because that question could not be asked:
total_buy_quantity, total_sell_quantity and LTQ arrive on every Quote
packet and were discarded. On 28 August PRECWIRE went from 1.4x to
19x volume between 11:45 and 12:29 and locked at +20%, with the only
stored reason arriving at 12:24 -- after. Whatever the book was doing
at 11:50 is gone, and this file is what stops that being true again.

Two things are guarded here. That the tick rule does what it claims,
and that NOTHING reads the store into a decision. The second matters
more: the cheap version of this idea measured -Rs 30,664 over 1,049
stock-days, and a recorder that quietly grows into a signal is how
that gets forgotten.
"""

import pathlib
import sqlite3
from datetime import datetime

import pytest

from core import order_flow

ROOT = pathlib.Path(__file__).resolve().parents[1]
AT = datetime(2026, 8, 28, 11, 50)
NEXT = datetime(2026, 8, 28, 11, 51)


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setattr(order_flow, "DB_PATH", str(tmp_path / "flow.db"))
    order_flow.reset()
    yield
    order_flow.reset()


def _tick(px, qty, **extra):
    row = {"LTP": px, "LTQ": qty}
    row.update(extra)
    return row


# ----------------------------------------------------------- tick rule

def test_a_rising_tape_reads_as_buying():
    for px, qty in ((100.0, 50), (100.5, 80), (101.0, 120)):
        order_flow.observe("TESTCO", _tick(px, qty), now=AT)
    closed = order_flow.observe("TESTCO", _tick(101.5, 10), now=NEXT)
    assert closed["up_qty"] == 200.0        # 80 + 120
    assert closed["down_qty"] == 0.0


def test_a_falling_tape_reads_as_selling():
    for px, qty in ((100.0, 50), (99.5, 80), (99.0, 120)):
        order_flow.observe("TESTCO", _tick(px, qty), now=AT)
    closed = order_flow.observe("TESTCO", _tick(98.5, 10), now=NEXT)
    assert closed["down_qty"] == 200.0
    assert closed["up_qty"] == 0.0


def test_an_unchanged_print_inherits_the_last_direction():
    """Dropping them would bias the delta.

    A trade at the same price as the last one is still a trade, and
    at the offer it is still a buy. Counting only price-moving prints
    would credit whichever side happened to tick the price.
    """
    order_flow.observe("TESTCO", _tick(100.0, 10), now=AT)
    order_flow.observe("TESTCO", _tick(101.0, 20), now=AT)   # up
    order_flow.observe("TESTCO", _tick(101.0, 70), now=AT)   # unchanged
    closed = order_flow.observe("TESTCO", _tick(101.0, 1), now=NEXT)
    assert closed["up_qty"] == 90.0         # 20 + 70
    assert closed["flat_qty"] == 10.0       # only the very first print


def test_the_very_first_print_is_not_guessed_at():
    """No previous price means no direction. It is not a buy."""
    order_flow.observe("TESTCO", _tick(100.0, 40), now=AT)
    closed = order_flow.observe("TESTCO", _tick(100.0, 1), now=NEXT)
    assert closed["flat_qty"] == 40.0
    assert closed["up_qty"] == 0.0
    assert closed["down_qty"] == 0.0


def test_delta_is_up_minus_down():
    order_flow.observe("TESTCO", _tick(100.0, 10), now=AT)
    order_flow.observe("TESTCO", _tick(101.0, 100), now=AT)
    order_flow.observe("TESTCO", _tick(100.0, 30), now=AT)
    order_flow.observe("TESTCO", _tick(100.0, 5), now=NEXT)
    order_flow.flush(force=True)
    with sqlite3.connect(order_flow.DB_PATH) as db:
        got = db.execute("select up_qty, down_qty, delta from flow_minutes "
                         "where minute='11:50'").fetchone()
    assert got == (100.0, 30.0, 70.0)


# ------------------------------------------------- the honesty columns

def test_it_records_what_it_saw_against_what_actually_traded():
    """ltq_sum vs vol_delta is how a later reader catches throttling.

    If the feed coalesces prints, the classified quantity is a sample
    of the flow and not the flow. Hiding that would let someone
    measure the feed's throttling and call it order flow.
    """
    order_flow.observe("TESTCO", _tick(100.0, 10, volume=5000), now=AT)
    order_flow.observe("TESTCO", _tick(101.0, 20, volume=9000), now=AT)
    closed = order_flow.observe("TESTCO", _tick(101.0, 1, volume=9100),
                                now=NEXT)
    assert closed["ltq_sum"] == 30.0
    order_flow.flush(force=True)
    with sqlite3.connect(order_flow.DB_PATH) as db:
        ltq, vol = db.execute("select ltq_sum, vol_delta from flow_minutes "
                              "where minute='11:50'").fetchone()
    assert ltq == 30.0
    assert vol == 4000.0                    # 9000 - 5000, the exchange's own


def test_the_resting_book_is_kept_separately_from_traded_flow():
    order_flow.observe("TESTCO", _tick(100.0, 10, total_buy_quantity=48000,
                                       total_sell_quantity=12000,
                                       avg_price=99.5), now=AT)
    order_flow.observe("TESTCO", _tick(100.0, 1), now=NEXT)
    order_flow.flush(force=True)
    with sqlite3.connect(order_flow.DB_PATH) as db:
        buy, sell, skew, atp = db.execute(
            "select book_buy, book_sell, skew_pct, atp from flow_minutes "
            "where minute='11:50'").fetchone()
    assert (buy, sell) == (48000.0, 12000.0)
    assert skew == 60.0                     # (48000-12000)/60000 * 100
    assert atp == 99.5


# ------------------------------------------------------------ plumbing

def test_a_new_minute_closes_the_old_one():
    order_flow.observe("TESTCO", _tick(100.0, 10), now=AT)
    assert order_flow.observe("TESTCO", _tick(100.0, 10), now=AT) is None
    closed = order_flow.observe("TESTCO", _tick(100.0, 10), now=NEXT)
    assert closed is not None and closed["minute"] == "11:50"


def test_two_stocks_do_not_share_a_bucket():
    order_flow.observe("AAA", _tick(100.0, 10), now=AT)
    order_flow.observe("AAA", _tick(101.0, 90), now=AT)
    order_flow.observe("BBB", _tick(50.0, 10), now=AT)
    order_flow.observe("BBB", _tick(49.0, 40), now=AT)
    order_flow.flush(force=True)
    with sqlite3.connect(order_flow.DB_PATH) as db:
        rows = dict(db.execute("select symbol, delta from flow_minutes"))
    assert rows == {"AAA": 90.0, "BBB": -40.0}


def test_writing_the_same_minute_twice_does_not_double_it():
    """A restart mid-session must not double a minute already written."""
    order_flow.observe("TESTCO", _tick(100.0, 10), now=AT)
    order_flow.flush(force=True)
    order_flow.observe("TESTCO", _tick(100.0, 10), now=AT)
    order_flow.flush(force=True)
    with sqlite3.connect(order_flow.DB_PATH) as db:
        n = db.execute("select count(*) from flow_minutes").fetchone()[0]
    assert n == 1


def test_nothing_traded_yet_is_not_a_reading():
    """Pre-open packets carry no LTP. None is not zero."""
    assert order_flow.observe("TESTCO", {"LTQ": 10}, now=AT) is None
    assert order_flow.observe("TESTCO", {"LTP": 0}, now=AT) is None
    assert order_flow.stats()["open"] == 0


def test_junk_is_ignored_rather_than_counted():
    """Never raises -- and never invents a reading either.

    Only the last packet here is real, so exactly one bucket may
    exist and it must hold that packet's quantity and nothing else.
    A recorder that swallows an error and books a zero is worse than
    one that crashes, because the zero gets measured later.
    """
    for junk in ({}, {"LTP": "abc"}, {"LTP": None}, {"LTP": float("nan")},
                 {"LTP": -5.0}):
        assert order_flow.observe("TESTCO", junk, now=AT) is None
    order_flow.observe(None, {"LTP": 100.0, "LTQ": 99}, now=AT)
    assert order_flow.stats()["open"] == 0, "junk created a bucket"

    order_flow.observe("TESTCO", _tick(100.0, 42), now=AT)
    order_flow.observe("TESTCO", _tick(100.0, 1), now=NEXT)
    order_flow.flush(force=True)
    with sqlite3.connect(order_flow.DB_PATH) as db:
        rows = db.execute("select symbol, ticks, ltq_sum from flow_minutes "
                          "where minute='11:50'").fetchall()
    assert rows == [("TESTCO", 1, 42.0)]


def test_an_unreadable_quantity_does_not_become_a_zero_trade():
    """LTQ that will not parse is size we did not see.

    The tick still counts -- a print happened -- but no quantity is
    invented for it, and ltq_sum stays honest about what was actually
    classified.
    """
    order_flow.observe("TESTCO", {"LTP": 100.0, "LTQ": "x"}, now=AT)
    order_flow.observe("TESTCO", {"LTP": 101.0, "LTQ": 25}, now=AT)
    closed = order_flow.observe("TESTCO", _tick(101.0, 1), now=NEXT)
    assert closed["ticks"] == 2
    assert closed["ltq_sum"] == 25.0


def test_a_stock_that_stops_ticking_still_gets_written():
    """An open bucket nothing touches again would never be written."""
    order_flow.observe("TESTCO", _tick(100.0, 10), now=AT)
    order_flow.flush(now=datetime(2026, 8, 28, 11, 55))
    with sqlite3.connect(order_flow.DB_PATH) as db:
        n = db.execute("select count(*) from flow_minutes").fetchone()[0]
    assert n == 1


def test_the_current_minute_is_left_alone_by_a_routine_flush():
    """Writing a minute still being filled would store a half-minute."""
    order_flow.observe("TESTCO", _tick(100.0, 10), now=AT)
    assert order_flow.flush(now=AT) == 0
    assert order_flow.stats()["open"] == 1


# ------------------------------------------------- and it decides NOTHING

def test_it_never_reaches_a_decision():
    """The guard that matters.

    core/tick_ohlc.py carries the same rule for pressure(). This store
    is younger and less proven than that one: the surge-size version
    of the idea measured -Rs 30,664 over 1,049 stock-days. It gets
    wired in after it is measured, or not at all.
    """
    for name in ("core/engine.py", "core/auto_entry.py", "core/ranker.py",
                 "core/position_plan.py", "core/select.py",
                 "core/why_moving.py"):
        path = ROOT / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "order_flow" not in text, (
            f"{name} references order_flow. It records; it must not "
            f"decide until the question has been measured.")
