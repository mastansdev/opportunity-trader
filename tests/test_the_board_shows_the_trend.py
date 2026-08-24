"""The 7-day structure reaches a screen.

    "as bot knows about stock trend, delivery % why can't it show in
     dashboard in why it is moving ? section or new column as trend =
     Strong_up / Uptrend/range/downtrend/strongdown"
                                    -- operator, 24 August 2026

core/trend_structure.py has classified every stock for weeks;
tools/trend_report.py printed it to a CSV he had to run by hand. The
same fault as delivery in August: measured, stored, fresh, and on no
screen at all.
"""

import os

import pytest

from dashboard.state import DashboardState

BOARD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "dashboard", "static", "board.html")


def _state():
    return DashboardState.__new__(DashboardState)


def test_a_real_stock_gets_a_structure():
    got = _state()._trend_for("NCC")
    if got is None:
        pytest.skip("no daily bars for NCC on this machine")
    assert got["structure"] in ("STRONG_UP", "UPTREND", "RANGE",
                               "DOWNTREND", "STRONG_DOWN")


def test_an_unknown_symbol_is_silent_not_wrong():
    # Saying nothing beats inventing a shape.
    assert _state()._trend_for("NOSUCHSTOCK") is None
    assert _state()._trend_for("") is None
    assert _state()._trend_for(None) is None


def test_it_never_raises_on_a_broken_store(monkeypatch):
    """This runs inside a snapshot build -- a panel must not take the
    board down."""
    import dashboard.state as mod

    class Boom:
        def history(self, *a, **k):
            raise RuntimeError("store gone")

    # The store is a PROCESS singleton, not an instance attribute --
    # one SQLAlchemy pool per DashboardState leaked handles on
    # data/daily_candles.db and failed three unrelated tests, but only
    # when the whole suite ran.
    monkeypatch.setattr(mod, "_daily_store", lambda: Boom())
    state = _state()
    state._trend_cache = None
    assert state._trend_for("NCC") is None


def test_the_answer_is_cached_for_the_day():
    """A daily-bar structure cannot change until tomorrow's close."""
    state = _state()
    first = state._trend_for("NCC")
    calls = []

    class Counting:
        def history(self, symbol, days=8):
            calls.append(symbol)
            return []

    state._daily_store = Counting()
    second = state._trend_for("NCC")
    assert second == first
    assert not calls, "second lookup hit the store again"


def test_the_board_draws_it():
    with open(BOARD, encoding="utf-8") as handle:
        html = handle.read()
    assert "r.trend && r.trend.structure" in html
    # Direction must be readable without stopping to think.
    assert '/UP$/.test(t) ? "earn"' in html
    assert '/DOWN$/.test(t) ? "stop"' in html


def test_the_row_carries_it():
    import inspect
    src = inspect.getsource(DashboardState)
    assert 'row["trend"] = self._trend_for(' in src, \
        "the ranked rows must carry trend or the chip has nothing to draw"
