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

    ---- NARROWED, NOT LIFTED. 31 August 2026. ----

        "start the work . complete all tasks which we planned"

    He instructed the flow into the entry decision after watching
    PRECWIRE refused 518 times as "fading" while 63% of every share
    traded was bought and cumulative delta rose all session, 100%
    measured against a real bid and ask.

    So core/auto_entry.py is allowed ONE use of it, and the SHAPE of
    that use is the protection: still_buying() may only RESCUE a row
    the price test already condemned. It can never condemn one, never
    open an entry by itself, and a missing or inferred reading leaves
    the old verdict exactly as it was.

    THE ORIGINAL WARNING STANDS AND IS NOT SETTLED. The surge-size
    version of this idea measured -Rs 30,664 over 1,049 stock-days.
    This variant is different and UNMEASURED; it is in because he
    decided it is in, on one session's evidence, and the measurement
    is owed.

    ---- WHAT THE BAN ACTUALLY IS. 1 September 2026. ----

    This asserted the literal string "order_flow" appeared nowhere in
    five files. That is not the contract and it broke on a COMMENT --
    a note in core/engine.py explaining why the flow reading now
    outranks the 0.25%-off-high price gate tripped it, while the code
    it describes obeys the rule completely.

    The contract is IMPORT, and engine.py states it itself:

        "self.buying_check is a function handed in by main.py, never
         imported here. That keeps this engine free of the flow store
         (which records; it does not decide) and, more practically,
         stops a unit test reading the real store and closing a live
         position, which is what happened the first time this was
         written."

    So the engine decides WITH a flow reading and still cannot reach
    the store: main.py injects still_buying after construction, and an
    Engine built by a tool, a replay or a test gets None and behaves
    exactly as it did before any of this existed. Two uses now, both
    his call -- the exit rule on 31 August, and on 1 September the
    entry gate, after 16 of the 41 stocks that gate refused in one
    session turned out to have buyers still winning them.

    THE ORIGINAL WARNING STILL STANDS AND IS STILL NOT SETTLED. The
    surge-size version of this idea measured -Rs 30,664 over 1,049
    stock-days. These variants are different and UNMEASURED beyond one
    session each. The measurement is owed.

    Everywhere else the ban holds -- and now it bans the thing that
    would actually do the damage.
    """
    import ast

    for name in ("core/engine.py", "core/ranker.py",
                 "core/position_plan.py", "core/select.py",
                 "core/why_moving.py"):
        path = ROOT / name
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        for node in ast.walk(tree):
            hit = False
            if isinstance(node, ast.Import):
                hit = any("order_flow" in a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                hit = ("order_flow" in (node.module or "")
                       or any("order_flow" in a.name for a in node.names))
            assert not hit, (
                f"{name}:{getattr(node, 'lineno', '?')} imports the flow "
                f"store. It may DECIDE on a reading handed to it, but it "
                f"must never reach the store itself -- a unit test would "
                f"read the real one and close a live position.")


# ---------------------------------------------- the book, when it is there

CLOCK = datetime(2026, 8, 31, 10, 5)
NEXT_MIN = datetime(2026, 8, 31, 10, 6)


def _full(px, qty, bid, ask):
    """A FULL packet -- LTP and LTQ with the five-level book beside it."""
    return {"LTP": px, "LTQ": qty, "volume": 1000,
            "depth": [{"bid_price": "%.2f" % bid, "ask_price": "%.2f" % ask,
                       "bid_quantity": 500, "ask_quantity": 400}]}


def test_a_trade_at_the_ask_is_a_buy_whatever_the_tick_did():
    """The correction, 29 August 2026: "no thats not the way order
    flow is used".

    Delta is not "did the price tick up". It is "did this trade lift
    the offer or hit the bid". Here the price does not move at all --
    three prints at the same 100.50 -- and every one of them lifted
    the offer. The tick rule would call the last two flat.
    """
    for _ in range(3):
        order_flow.observe("TESTCO", _full(100.5, 100, 100.0, 100.5),
                           now=CLOCK)
    closed = order_flow.observe("TESTCO", _full(100.5, 1, 100.0, 100.5),
                                now=NEXT_MIN)
    assert closed["up_qty"] == 300.0
    assert closed["down_qty"] == 0.0


def test_a_trade_at_the_bid_is_a_sell():
    order_flow.observe("TESTCO", _full(100.0, 80, 100.0, 100.5), now=CLOCK)
    closed = order_flow.observe("TESTCO", _full(100.0, 1, 100.0, 100.5),
                                now=NEXT_MIN)
    assert closed["down_qty"] == 80.0


def test_a_trade_inside_the_spread_is_not_guessed_at():
    """Neither side took it. Counting it as either would invent a
    reading the book does not support."""
    order_flow.observe("TESTCO", _full(100.2, 50, 100.0, 100.5), now=CLOCK)
    closed = order_flow.observe("TESTCO", _full(100.2, 1, 100.0, 100.5),
                                now=NEXT_MIN)
    assert closed["flat_qty"] == 50.0
    assert closed["up_qty"] == 0.0 and closed["down_qty"] == 0.0


def test_it_says_whether_the_delta_came_from_the_book():
    """The honesty column. A delta built from the book and one built
    from the tick rule are not the same number."""
    order_flow.observe("TESTCO", _full(100.5, 100, 100.0, 100.5), now=CLOCK)
    order_flow.observe("TESTCO", _full(100.5, 1, 100.0, 100.5), now=NEXT_MIN)
    assert order_flow.pressure("TESTCO")["from_the_book"] is True

    order_flow.observe("QUOTECO", _tick(100.0, 50), now=CLOCK)
    order_flow.observe("QUOTECO", _tick(100.5, 80), now=CLOCK)
    order_flow.observe("QUOTECO", _tick(100.5, 1), now=NEXT_MIN)
    quote = order_flow.pressure("QUOTECO")
    assert quote["from_the_book"] is False
    assert quote["book_ticks"] == 0


def test_a_quote_packet_still_works_without_the_book():
    """The feed is in Quote mode until a live session proves Full
    arrives. The tick rule must keep answering until then."""
    order_flow.observe("QUOTECO", _tick(100.0, 10), now=CLOCK)
    order_flow.observe("QUOTECO", _tick(101.0, 90), now=CLOCK)
    closed = order_flow.observe("QUOTECO", _tick(101.0, 1), now=NEXT_MIN)
    assert closed["up_qty"] == 90.0


# ------------------------------------------------- the LIVE reading

def test_pressure_is_the_running_total_for_the_session():
    """Same day, live -- his whole point. It must include the minute
    still being filled, not only the ones already closed."""
    order_flow.observe("TESTCO", _full(100.5, 100, 100.0, 100.5), now=CLOCK)
    order_flow.observe("TESTCO", _full(100.0, 40, 100.0, 100.5), now=CLOCK)
    order_flow.observe("TESTCO", _full(100.5, 60, 100.0, 100.5), now=NEXT_MIN)
    got = order_flow.pressure("TESTCO")
    assert got["buy"] == 160.0        # 100 closed + 60 still open
    assert got["sell"] == 40.0
    assert got["delta"] == 120.0


def test_pressure_is_none_before_the_stock_has_traded():
    assert order_flow.pressure("NEVERTRADED") is None
    assert order_flow.pressure("") is None


def test_a_new_day_does_not_inherit_yesterdays_pressure():
    order_flow.observe("TESTCO", _full(100.5, 100, 100.0, 100.5), now=CLOCK)
    order_flow.observe("TESTCO", _full(100.5, 10, 100.0, 100.5),
                       now=datetime(2026, 9, 1, 10, 5))
    assert order_flow.pressure("TESTCO")["buy"] == 10.0


def test_auto_entry_uses_the_flow_only_to_rescue():
    """The one place it is allowed, and the shape that makes it safe.

    still_buying() may overrule a row the PRICE test already called
    faded. It may never call one faded, never open an entry on its
    own, and never act on a missing or inferred reading.
    """
    text = (ROOT / "core/auto_entry.py").read_text(encoding="utf-8",
                                                   errors="ignore")
    # Code only. The comment above the rescue explains it at length,
    # and scanning raw text would count its own explanation.
    code = "\n".join(line for line in text.splitlines()
                     if not line.strip().startswith("#"))
    # Three is the minimum a single rescue costs: the import, the
    # call, and reading the key off the result. A fourth means it has
    # been used somewhere else.
    assert code.count("still_buying") <= 3, (
        "order_flow has spread beyond the single rescue in _faded()")
    body = text.split("def _faded")[1].split("\ndef ")[0]
    assert "still_buying" in body, "the rescue is not in _faded()"
    # The rescue returns False (not faded). Nothing in this block may
    # return True on the strength of the flow.
    after = body.split("still_buying")[-1]
    assert "return False" in after
