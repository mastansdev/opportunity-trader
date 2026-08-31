"""The flow reading only ever reached the rows that cleared the gates.

    "Buying pressure / order flow / delta for all stocks on dashboard
     except 1/2 stocks"                 -- operator, 31 August 2026
    "not trading yet"                   -- what his screen said instead

build_ranked() attached flow, shape and trend to the rows that PASSED
the gates. That afternoon there were three of them. The board draws
the gainers and the refused rows as well:

    ranked.rows              3 rows    flow on 2
    ranked.refused_rows     96 rows    flow on 0
    gainers_losers.gainers  50 rows    flow on 0

So 146 of 149 rows carried no reading, and flowCell() printed "not
trading yet" over BALRAMCHIN while it was up 11.30%.

BOUNDED ON PURPOSE. One symbol costs about 51 ms of SQLite and the
whole cost lands in the first cycle of each minute, because _flow_for
caches per minute. Widening it to all 149 rows would put three
seconds into a one-second refresh. It is bounded by the same mover
threshold the board itself filters on, and capped.
"""

import pytest

from dashboard.state import DashboardState


class _State(DashboardState):
    """Only the three lookups, stubbed. Nothing else is exercised."""

    def __init__(self):
        self.asked = []

    def _flow_for(self, symbol):
        self.asked.append(symbol)
        return {"delta": 1.0, "symbol": symbol}

    def _shape_for(self, symbol):
        return {"text": "going up all session"}

    def _trend_for(self, symbol):
        return {"structure": "UPTREND"}


def _rows(*pairs):
    return [{"symbol": s, "change_pct": c} for s, c in pairs]


def test_a_gainer_the_board_draws_gets_a_reading():
    state = _State()
    gainers = _rows(("BALRAMCHIN", 11.30), ("NORTHARC", 10.22))
    state._widen_flow_to_the_board(None, gainers, None)
    assert [r["flow"]["symbol"] for r in gainers] == ["BALRAMCHIN", "NORTHARC"]
    assert all(r["shape"] and r["trend"] for r in gainers)


def test_a_refused_row_gets_one_too():
    """He can see them on the Blocked tab; a blank column there is the
    same lie."""
    state = _State()
    refused = _rows(("PRECWIRE", 5.10))
    state._widen_flow_to_the_board(None, None, refused)
    assert refused[0]["flow"]["symbol"] == "PRECWIRE"


def test_a_row_that_already_has_one_is_not_asked_again():
    """build_ranked() got there first. Asking again costs 51 ms for an
    answer already on the row."""
    state = _State()
    rows = [{"symbol": "ASHOKA", "change_pct": 9.1, "flow": {"delta": 5.0}}]
    state._widen_flow_to_the_board(rows, None, None)
    assert state.asked == []
    assert rows[0]["flow"]["delta"] == 5.0


def test_the_same_stock_in_two_lists_is_read_once():
    """ASHOKA appears in ranked AND in gainers. It is one database
    read, not two."""
    state = _State()
    a = _rows(("ASHOKA", 9.1))
    b = _rows(("ASHOKA", 9.1))
    state._widen_flow_to_the_board(a, b, None)
    assert state.asked == ["ASHOKA"]


def test_a_stock_the_board_cannot_draw_is_skipped():
    """The board filters on the mover threshold. A row it will never
    show does not need 51 ms spent on it."""
    state = _State()
    rows = _rows(("QUIETCO", 0.4), ("STILLQUIET", -1.2))
    state._widen_flow_to_the_board(rows, None, None)
    assert state.asked == []


def test_a_faller_is_still_read():
    """He trades long only, but a stock down 8% is drawn and its
    buying pressure is exactly what explains it."""
    state = _State()
    rows = _rows(("SLIDER", -8.0))
    state._widen_flow_to_the_board(rows, None, None)
    assert state.asked == ["SLIDER"]


def test_the_work_is_capped():
    """A 400-stock day must not put twenty seconds into one cycle."""
    state = _State()
    rows = _rows(*[("S%03d" % i, 9.0) for i in range(200)])
    state._widen_flow_to_the_board(rows, None, None)
    assert len(state.asked) == state.FLOW_ROWS_MAX


def test_a_broken_lookup_leaves_the_row_alone():
    """A panel must never take the snapshot down."""
    class Broken(_State):
        def _flow_for(self, symbol):
            raise RuntimeError("store gone")

    rows = _rows(("ASHOKA", 9.1))
    Broken()._widen_flow_to_the_board(rows, None, None)
    assert "flow" not in rows[0] or rows[0].get("flow") is None


def test_the_snapshot_actually_calls_it():
    import inspect

    src = inspect.getsource(DashboardState)
    assert "self._widen_flow_to_the_board(" in src
    assert "return snapshot" in src, (
        "_build must name the payload so the widening can reach it")
