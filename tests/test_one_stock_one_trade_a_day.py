"""---- ONE STOCK, ONE TRADE A DAY. 1 September 2026. ----

    "done one stock one trade per trade by bot."
                                            -- the operator

On 1 September the exit rule and the ranker fought over the same two
names, and both won in turn:

    VTL     out 15:02:16  ->  back in 15:02:18   (2 seconds)
    MARINE  out 11:29:08  ->  back in 11:30:46   (98 seconds)

One continuous process each time, no restart involved. Neither rule was
wrong: the exit sold because the buyers had stopped, and the ranker
bought because VTL was still the highest-scoring stock on the board
(52.15, on 170.8x its normal volume). They were answering different
questions about the same stock in the same second, and nothing above
them said which one settles it.

VTL's entire loss for the day was that round trip: -Rs 32, of which the
whole amount was the spread crossed twice.

WHAT IT COSTS. If a stock runs again after the bot is out, the bot
misses it. He weighed that against paying the spread twice and chose
this.

WHAT IT IS NOT. Not a block on stocks HE sells by hand, and not a block
on a stock the bot never closed. Only the bot's own completed trades
count.
"""

from datetime import datetime, timedelta

import pytest

from core import auto_entry


ROW = {"symbol": "VTL", "action": "BUY", "state": "ok",
       "plan": {"ok": True, "qty": 159, "stop": 587.58, "entry": 603.60},
       "score": 52.15}


class _Engine:
    """Only what refuse_reason() reaches for."""

    def __init__(self, closed=None):
        self.closed_positions = list(closed or [])
        self.open_positions = {}
        self.alert_only = False

    symbols_traded_today = None      # filled in per test below


def _closed(symbol, exit_time):
    return {"symbol": symbol, "direction": "LONG",
            "entry_price": 603.85, "exit_price": 603.65,
            "exit_time": exit_time, "entry_time": exit_time}


# ------------------------------------------------------------ the gate

def test_a_stock_already_traded_today_is_refused():
    got = auto_entry.refuse_reason(
        ROW, _Engine(), held=set(), max_positions=3,
        traded_today={"VTL"})
    assert got, "VTL was bought back after being sold"
    assert "one stock, one trade a day" in got, got


def test_a_stock_not_yet_traded_is_untouched():
    """The control. A rule that refused everything would pass the test
    above and stop the bot trading at all."""
    got = auto_entry.refuse_reason(
        ROW, _Engine(), held=set(), max_positions=3,
        traded_today={"SOMETHINGELSE"})
    assert not (got and "one trade a day" in str(got)), got


def test_an_empty_list_changes_nothing():
    for empty in (None, set(), []):
        got = auto_entry.refuse_reason(
            ROW, _Engine(), held=set(), max_positions=3,
            traded_today=empty)
        assert not (got and "one trade a day" in str(got)), got


def test_it_is_case_insensitive():
    got = auto_entry.refuse_reason(
        ROW, _Engine(), held=set(), max_positions=3, traded_today={"vtl"})
    assert got and "one trade a day" in got


def test_take_hands_it_to_the_gate():
    """A parameter refuse_reason() accepts and take() never passes is
    the fault this repo keeps finding. Asserted on the source because
    the failure is silent."""
    import inspect

    src = inspect.getsource(auto_entry.take)
    assert "traded_today=traded_today" in src, (
        "take() drops it before refuse_reason() sees it")


def test_main_reads_it_from_the_engine():
    """And the order path has to supply it, or none of this runs."""
    from pathlib import Path

    src = Path("main.py").read_text(encoding="utf-8")
    assert "traded_today=engine.symbols_traded_today()" in src, (
        "main.py never tells auto_entry what the bot already traded")


# ----------------------------------------------- what the engine reports

def _engine_with(closed):
    from core.engine import Engine

    class _Stub:
        closed_positions = closed
        symbols_traded_today = Engine.symbols_traded_today
    return _Stub()


def test_the_engine_names_what_it_closed_today():
    now = datetime.now()
    got = _engine_with([_closed("VTL", now),
                        _closed("MARINE", now)]).symbols_traded_today()
    assert got == {"VTL", "MARINE"}, got


def test_yesterdays_trade_does_not_block_today():
    """The rule is per DAY. A stock traded yesterday is fair game."""
    old = datetime.now() - timedelta(days=1)
    assert _engine_with([_closed("VTL", old)]).symbols_traded_today() == set()


def test_a_time_stored_as_text_still_counts():
    """Positions restored from session_state.json come back as ISO
    strings -- the same fault that hid trades from the report card."""
    now = datetime.now().isoformat()
    assert "VTL" in _engine_with([_closed("VTL", now)]).symbols_traded_today()


def test_a_row_with_no_time_still_counts():
    """It is in THIS session's closed list, so it closed in this
    session. Ignoring it would let the churn straight back in."""
    row = {"symbol": "VTL", "direction": "LONG"}
    assert "VTL" in _engine_with([row]).symbols_traded_today()


def test_rubbish_does_not_take_the_loop_down():
    got = _engine_with([None, 7, {"no": "symbol"},
                        _closed("VTL", datetime.now())]).symbols_traded_today()
    assert got == {"VTL"}, got


# --------------------------------------------------- the churn, replayed

def test_the_vtl_round_trip_cannot_happen_again():
    """The actual sequence, with its real timestamps."""
    sold_at = datetime(2026, 9, 1, 15, 2, 16)
    engine = _engine_with([_closed("VTL", sold_at)])
    # ...and two seconds later the ranker offers it back.
    assert "VTL" in engine.symbols_traded_today()
    got = auto_entry.refuse_reason(
        ROW, _Engine(), held=set(), max_positions=3,
        traded_today={"VTL"})
    assert got and "one trade a day" in got
