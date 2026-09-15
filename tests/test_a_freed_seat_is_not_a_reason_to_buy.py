"""
==========================================================
A freed seat is not new information about the stock
==========================================================

    "do not keep instant buy when ever seat gets free. fill after
     complete scanning , freshness of the stock ranked, price action
     followed after the rank , what stock did after ranked stage
     incase the time between the rank & entry"
                                    -- the operator, 14 September 2026

WHAT WAS HAPPENING. 39 of 95 entries (41%) landed in the first three
minutes -- 8 positions at 09:16:34 on 7 Sep, 9 at 09:16:38 on 8 Sep.
After that the book was full for 290 of the session's 306 minutes and
"[SLOTS] No room for a NEW position" was logged 44 times. So the only
way in was when something exited, and whatever sat at the top of the
last board got bought the instant a seat opened -- however long ago
that board had ranked it.

    move age when bought   trades      net
    over 60 min old            27   -21,896      the whole week's loss

HOW FAR INTO THE MOVE IT ALREADY WAS, on the same 95 trades, against
the minute candles (extension = entry price vs the day's OPEN):

    already +4% or more    40   -16,568   avg  -414
    +2% to +4%             21    -8,458   avg  -403
    +0.5% to +2%           15    +4,023   avg  +268
    under +0.5%             8    +7,513   avg  +939

Monotonic across four buckets. 61 trades at 2% or more extended lost
25,026; the 23 below it made 11,536.

NOT THE 3% BAR. That asks whether a move QUALIFIES, from the previous
close, and is untouched. This asks how much of TODAY'S move is already
spent, from the open -- so a stock that gaps and then sits still is
fresh, and one that has ground up 5% since the open is not.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import datetime, timedelta

import pytest

from core.auto_entry import price_now, refuse_reason

NOW = datetime(2026, 9, 14, 11, 0, 0)


class _Engine:
    pass


def _row(**kw):
    row = {
        "symbol": "ABC",
        "action": "BUY",
        "plan": {"ok": True, "qty": 10, "stop": 90.0},
        "state": "live",
        "ranked_at": NOW - timedelta(seconds=10),
    }
    row.update(kw)
    return row


def _why(row, **kw):
    return refuse_reason(row, _Engine(), now=NOW, held=set(), **kw)


# ---------------------------------------------------------------
# FRESHNESS OF THE MOVE
# ---------------------------------------------------------------

def test_a_stock_that_has_already_run_is_no_longer_refused_for_it():
    """15 Sep 2026: the fixed 2% gate was removed by him -- "not a fixed
    % to check the freshness. who asked u to do so?". It refused
    ZENSARTECH (430 -> 479). Buyers and price-following decide now; see
    tests/test_buyers_and_price_at_entry.py."""
    assert _why(_row(extension_pct=10.7)) is None


def test_a_fresh_move_is_allowed():
    """The control. A guard that refuses everything would pass every
    test above and stop the bot trading."""
    assert _why(_row(extension_pct=0.8)) is None


def test_there_is_no_percentage_boundary_any_more():
    assert _why(_row(extension_pct=2.0)) is None
    assert _why(_row(extension_pct=1.99)) is None


def test_a_stock_below_its_open_is_not_refused_for_extension():
    """Extension asks what has already been spent, not direction."""
    assert _why(_row(extension_pct=-1.5)) is None


def test_no_reading_is_not_a_refusal():
    """A missing reading means nothing -- the rule this file already
    follows for the tick and the flow."""
    assert _why(_row()) is None
    assert _why(_row(extension_pct=None)) is None
    assert _why(_row(extension_pct="nonsense")) is None


def test_it_can_be_turned_off(monkeypatch):
    monkeypatch.setattr("config.ENTRY_MAX_EXTENSION_PCT", None)
    assert _why(_row(extension_pct=9.0)) is None


def test_the_threshold_is_read_at_call_time(monkeypatch):
    monkeypatch.setattr("config.ENTRY_MAX_EXTENSION_PCT", 5.0)
    assert _why(_row(extension_pct=4.2)) is None
    monkeypatch.setattr("config.ENTRY_MAX_EXTENSION_PCT", 1.0)
    assert _why(_row(extension_pct=4.2)) is not None


# ---------------------------------------------------------------
# FRESHNESS OF THE RANK
# ---------------------------------------------------------------

def test_a_stale_board_is_not_bought_from():
    """The seat opening is not news about the stock. If the board that
    ranked it has not been re-checked, wait for the next one."""
    why = _why(_row(ranked_at=NOW - timedelta(minutes=9)))
    assert why and "board that ranked it" in why


def test_a_rank_from_this_board_is_fine():
    """A slow rebuild is 98s, so an ordinary session refuses nothing
    here -- this is a guard against a board that has STOPPED."""
    assert _why(_row(ranked_at=NOW - timedelta(seconds=95))) is None


def test_an_unstamped_row_is_not_refused():
    """Rows from paths that do not stamp it must still trade."""
    row = _row()
    row.pop("ranked_at")
    assert _why(row) is None


def test_a_broken_stamp_is_not_a_refusal():
    assert _why(_row(ranked_at="not a time")) is None


# ---------------------------------------------------------------
# WHAT THE STOCK DID BETWEEN THE RANK AND THE FILL
# ---------------------------------------------------------------

def test_the_board_price_is_kept_when_the_tick_overwrites_it():
    """It could not be asked at all before: price_now() overwrote
    row["ltp"] and nothing kept what the board had said."""
    row = {"symbol": "ABC", "ltp": 100.0}
    price_now(row, lambda s: {"LTP": 103.0, "open": 100.0, "close": 99.0})
    assert row["ranked_ltp"] == 100.0
    assert row["ltp"] == 103.0
    assert row["drift_since_rank_pct"] == pytest.approx(3.0)


def test_the_ranked_price_is_not_overwritten_on_later_ticks():
    """The row survives until the next board publishes, so only the
    FIRST re-pricing still holds the board's own number."""
    row = {"symbol": "ABC", "ltp": 100.0}
    price_now(row, lambda s: {"LTP": 103.0, "open": 100.0})
    price_now(row, lambda s: {"LTP": 107.0, "open": 100.0})
    assert row["ranked_ltp"] == 100.0
    assert row["drift_since_rank_pct"] == pytest.approx(7.0)


def test_extension_is_measured_from_the_open_not_the_previous_close():
    """A gap is not something the bot missed. 3% from yesterday with
    nothing since the open is FRESH."""
    row = {"symbol": "ABC", "ltp": 100.0}
    price_now(row, lambda s: {"LTP": 103.0, "open": 103.0, "close": 100.0})
    assert row["extension_pct"] == pytest.approx(0.0)
    assert _why(_row(extension_pct=row["extension_pct"])) is None


def test_the_stamp_is_applied_where_the_board_is_published():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "main.py").read_text(encoding="utf-8")
    assert '_row["ranked_at"] = _ranked_at' in src
    assert src.index('_row["ranked_at"] = _ranked_at') < \
        src.index('_candidates["rows"] = _rows')
