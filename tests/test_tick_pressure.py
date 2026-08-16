"""
==========================================================
The order book was arriving free and read by nothing
==========================================================

main.py has printed this at startup every session since 30 July 2026:

    [FEED] Arriving but UNUSED: ['LTQ', 'avg_price', 'close', 'high',
           'low', 'open', 'total_buy_quantity', 'total_sell_quantity']

OHLC came off that list on 10 August. On 16 August a feed audit found
the rest still on it, and a grep settled it: outside of tests, the only
mention of total_buy_quantity anywhere in the repo was the docstring in
core/tick_ohlc.py quoting that very log line.

WHY THESE THREE AND NOT THE WHOLE PACKET
----------------------------------------
His own definition of an opportunity asks for something price cannot
show:

    "Volume confirms it -- money changing hands above this stock's own
     normal for this time of day"

    "Depth imbalance, total buy vs sell quantity and traded quantity
     per tick describe whether real money is stacked behind a move."

total_buy_quantity / total_sell_quantity are the aggregate size resting
on each side. avg_price is the day's ATP, so LTP above it means the
last trades printed above where the day's money actually changed hands.

Market DEPTH proper -- five levels a side -- never arrives at all:
main.py subscribes equities as MarketFeed.Quote and only the indices as
MarketFeed.Full. That is a subscription change, not a parsing one, and
it is not made here.

IT RECORDS. IT DOES NOT DECIDE.
-------------------------------
Same posture as the OHLC beside it, for the reason he gave himself:

    "i'd rather show you the real size of the drift before rewriting
     the tick path"

and the standing rule that nothing becomes a trading rule until it has
been scored against real outcomes. test_it_never_reaches_the_entry_path
below fails the build the day that changes by accident.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

import pytest

from core import tick_ohlc

ROOT = pathlib.Path(__file__).resolve().parents[1]


# The exact packet shape from the live log, 2026-08-04. Field names and
# the string-vs-number mix are copied, not invented -- a fake built from
# memory is how this repo has confirmed its own errors before.
LIVE_PACKET = {
    "LTP": 167.0, "LTQ": 10, "LTT": "2026-08-04 10:00:00",
    "avg_price": "165.73", "close": "165.43", "high": "167.20",
    "low": "164.51", "open": "166.00", "security_id": "1",
    "total_buy_quantity": 48000, "total_sell_quantity": 12000,
    "type": "Quote", "volume": 100,
}


@pytest.fixture(autouse=True)
def _clean():
    tick_ohlc.reset()
    yield
    tick_ohlc.reset()


# ---------------------------------------------------------------
# IT READS WHAT ACTUALLY ARRIVES
# ---------------------------------------------------------------

def test_the_book_is_kept_off_a_real_packet():
    tick_ohlc.remember("TESTSTK", LIVE_PACKET)
    got = tick_ohlc.pressure("TESTSTK")
    assert got is not None, "the fields arrived and nothing was kept"
    assert got["buy"] == 48000
    assert got["sell"] == 12000
    assert got["ratio"] == 4.0
    assert got["skew_pct"] == 60.0


def test_atp_is_read_from_the_string_dhan_sends():
    """avg_price arrives as '165.73', a STRING. Reading it as a number
    without conversion would silently compare a str to a float."""
    tick_ohlc.remember("TESTSTK", LIVE_PACKET)
    got = tick_ohlc.pressure("TESTSTK")
    assert got["atp"] == pytest.approx(165.73)
    assert got["above_atp"] is True, "LTP 167.00 is above ATP 165.73"


def test_the_ltp_key_is_the_one_dhan_actually_sends():
    """Dhan sends 'LTP', not 'ltp'. The first version of this module
    read the lowercase name, so above_atp was None on every packet --
    a field that looks wired and reports nothing."""
    tick_ohlc.remember("TESTSTK", LIVE_PACKET)
    assert tick_ohlc.of("TESTSTK").get("LTP") == 167.0


def test_a_price_below_the_atp_reads_false_not_none():
    packet = dict(LIVE_PACKET, LTP=160.0)
    tick_ohlc.remember("TESTSTK", packet)
    assert tick_ohlc.pressure("TESTSTK")["above_atp"] is False


# ---------------------------------------------------------------
# MISSING IS NOT ZERO
# ---------------------------------------------------------------

def test_a_packet_without_the_book_reads_None_not_balanced():
    """A missing book and a balanced book are opposite readings, and
    only one of them means anything."""
    packet = {k: v for k, v in LIVE_PACKET.items()
              if k not in ("total_buy_quantity", "total_sell_quantity")}
    tick_ohlc.remember("TESTSTK", packet)
    assert tick_ohlc.pressure("TESTSTK") is None


def test_an_empty_book_on_both_sides_is_not_a_skew():
    """0 and 0 is 'nobody is there', not 'balanced'. Dividing would
    raise; reporting 0% would be a reading that was never taken."""
    packet = dict(LIVE_PACKET, total_buy_quantity=0, total_sell_quantity=0)
    tick_ohlc.remember("TESTSTK", packet)
    assert tick_ohlc.pressure("TESTSTK") is None


def test_nothing_offered_is_a_real_reading():
    """Sell side 0 with size on the bid IS meaningful -- it is the
    upper circuit shape. ratio cannot be computed, skew can."""
    packet = dict(LIVE_PACKET, total_buy_quantity=90000,
                  total_sell_quantity=0)
    tick_ohlc.remember("TESTSTK", packet)
    got = tick_ohlc.pressure("TESTSTK")
    assert got is not None
    assert got["ratio"] is None, "division by an empty offer side"
    assert got["skew_pct"] == 100.0


def test_an_unknown_symbol_reads_None():
    assert tick_ohlc.pressure("NEVER-SEEN") is None
    assert tick_ohlc.pressure(None) is None


def test_it_never_raises_on_junk():
    for packet in ({}, {"LTP": None}, {"total_buy_quantity": "abc"},
                   {"open": "x", "high": None, "total_sell_quantity": []}):
        assert tick_ohlc.remember("JUNK", packet) in (None,) or True
        assert tick_ohlc.pressure("JUNK") is None or True


# ---------------------------------------------------------------
# THE OHLC IT ALREADY HELD MUST STILL WORK
# ---------------------------------------------------------------

def test_the_existing_ohlc_reading_is_unchanged():
    """The book fields were added to remember(). The four prices it
    was written for must behave exactly as before."""
    tick_ohlc.remember("TESTSTK", LIVE_PACKET)
    row = tick_ohlc.of("TESTSTK")
    assert row["open"] == pytest.approx(166.00)
    assert row["high"] == pytest.approx(167.20)
    assert row["low"] == pytest.approx(164.51)
    assert tick_ohlc.prev_close("TESTSTK") == pytest.approx(165.43)


def test_a_pre_open_packet_is_still_silence():
    """All-zero prices are the pre-open shape. It must not be recorded
    as a reading, book fields or not."""
    packet = {"open": 0, "high": 0, "low": 0, "close": 0,
              "total_buy_quantity": 500, "total_sell_quantity": 400}
    assert tick_ohlc.remember("PREOPEN", packet) is None
    assert tick_ohlc.of("PREOPEN") is None


# ---------------------------------------------------------------
# IT MUST NEVER REACH THE ENTRY PATH
# ---------------------------------------------------------------

def test_it_never_reaches_the_entry_path():
    """THE LINE THAT MUST NOT MOVE.

    A depth imbalance is a snapshot of RESTING orders and resting
    orders can be pulled. Turning it into an entry condition is a
    decision to argue about in daylight, not a quiet import.
    """
    for name in ("core/engine.py", "core/auto_entry.py", "core/ranker.py",
                 "core/position_plan.py", "core/exit_plan.py"):
        src = (ROOT / name).read_text(encoding="utf-8", errors="replace")
        assert "tick_ohlc.pressure(" not in src, (
            f"{name} reads the order-book skew. That may be right, but "
            f"it is a deliberate change, not a quiet one.")
        assert "total_buy_quantity" not in src, name


def test_the_module_still_says_it_only_records():
    src = (ROOT / "core" / "tick_ohlc.py").read_text(encoding="utf-8")
    assert "It records and reports" in src or "records and reports" in src


# ---------------------------------------------------------------
# IT HAS TO REACH THE SCREEN
# ---------------------------------------------------------------
#
# Three readings were found computed-and-invisible on 16 August alone:
# the watchlist panel, core/runup.py, and these very fields. A number
# nobody can see is indistinguishable from one never computed, and the
# tests that were supposed to catch it were reading deleted pages.

def test_the_snapshot_attaches_it_to_a_ranked_row():
    src = (ROOT / "dashboard" / "state.py").read_text(encoding="utf-8")
    assert 'row["pressure"]' in src, (
        "the order-book reading is kept and never attached to a row")
    assert "tick_ohlc" in src


def test_the_board_draws_it():
    page = (ROOT / "dashboard" / "static" / "board.html").read_text(
        encoding="utf-8")
    block = page[page.find("function reasonChips(r)"):
                 page.find("function capOf(")]
    assert "r.pressure" in block, (
        "core/tick_ohlc.py keeps the book and /board does not draw it")


def test_a_balanced_book_draws_nothing():
    """A 52:48 book is noise wearing a number. A chip on every row
    teaches him to stop reading chips."""
    page = (ROOT / "dashboard" / "static" / "board.html").read_text(
        encoding="utf-8")
    block = page[page.find("function reasonChips(r)"):
                 page.find("function capOf(")]
    assert ">= 20" in block, (
        "every book draws a chip, however balanced -- the threshold "
        "that keeps the row readable is gone")


def test_the_tooltip_says_resting_orders_can_be_pulled():
    """The single most important caveat on this reading. Size standing
    in the book is not size that traded."""
    page = (ROOT / "dashboard" / "static" / "board.html").read_text(
        encoding="utf-8")
    assert "can be pulled" in page, (
        "the chip presents resting depth as if it were done business")
