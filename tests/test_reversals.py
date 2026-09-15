"""
==========================================================
Went hard one way, came back the other
==========================================================

    "very rare events trigger stocks moving extreme negative to
     positive & viceversa . those stocks too follow the same rule."
    "today in this clumsy ness i never saw atleast one loser stocks.
     today 71/100 market breadth is positive . still i can't check
     gainers."
                                    -- operator, 3 August 2026

A top-50 list cannot show these. A stock down 6% at 10:00 and flat by
14:00 has done something violent and appears in NEITHER table -- not a
top gainer, not a top loser, just a middling number on a screen full of
them. It is also, on the day it happens, usually the most interesting
row on the board.

BOTH CONDITIONS, ALWAYS
-----------------------
    it went     the day's low was at least 3% below yesterday's close
    it came     it has since climbed at least 3% off that low

Travel alone catches a volatile stock that never went anywhere. Extreme
alone catches one that fell and stayed fallen -- which is not a
reversal, it is a loser, and it already has a table.

WHICH SIDE OF THE SCREEN
------------------------
The side it is heading TOWARDS, not the sign of change_pct. A stock
down 6% and climbing belongs on the GAINERS screen while it is still
negative, because what it is DOING is going up. Filing it under losers
because of its sign would hide the move at the moment it matters.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from dashboard.state import DashboardState


def state():
    return DashboardState.__new__(DashboardState)


def row(symbol, prev, low, high, now):
    return {"symbol": symbol, "prev_close": prev, "low": low,
            "high": high, "change_pct": now}


# ---------------------------------------------------------------
# 1. THE TURN
# ---------------------------------------------------------------
def test_a_stock_that_fell_hard_and_recovered_is_a_turn_up():
    got = state()._find_reversals([row("TURNUP", 100.0, 93.8, 100.5, -1.0)])
    assert [r["symbol"] for r in got["up"]] == ["TURNUP"]
    assert got["up"][0]["from_pct"] == -6.2
    assert got["up"][0]["travelled"] == 5.2


def test_a_stock_that_ran_and_gave_it_back_is_a_turn_down():
    got = state()._find_reversals([row("TURNDN", 100.0, 99.0, 107.0, 1.5)])
    assert [r["symbol"] for r in got["down"]] == ["TURNDN"]
    assert got["down"][0]["travelled"] == 5.5


def test_it_is_filed_on_the_side_it_is_HEADING_towards():
    """Down 6% and climbing is a GAINERS-screen row while still
    negative. The sign says where it has been; the turn says where it
    is going."""
    got = state()._find_reversals([row("TURNUP", 100.0, 93.8, 100.5, -1.0)])
    assert got["up"][0]["side"] == "gainers"
    assert got["up"][0]["change_pct"] < 0


# ---------------------------------------------------------------
# 2. WHAT IS NOT A REVERSAL
# ---------------------------------------------------------------
def test_a_stock_that_fell_and_stayed_down_is_just_a_loser():
    """It has a table already. Calling this a reversal would fill the
    panel with every falling stock on the board."""
    got = state()._find_reversals([row("STAYDOWN", 100.0, 94.0, 100.1, -5.9)])
    assert got["up"] == [] and got["down"] == []


def test_a_stock_that_ran_and_held_is_just_a_gainer():
    got = state()._find_reversals([row("STAYUP", 100.0, 99.9, 108.0, 7.9)])
    assert got["up"] == [] and got["down"] == []


def test_a_small_dip_and_bounce_is_not_a_reversal():
    """Travel without an extreme is a stock trading, not turning."""
    got = state()._find_reversals([row("NOISE", 100.0, 99.6, 100.8, 0.3)])
    assert got["up"] == [] and got["down"] == []


def test_an_extreme_with_no_travel_is_not_a_reversal():
    """-6% low, still -5.8%. It went and it has not come back."""
    got = state()._find_reversals([row("STILLDOWN", 100.0, 94.0, 100.0, -5.8)])
    assert got["up"] == []


@pytest.mark.parametrize("bad", [
    {"symbol": "X", "prev_close": None, "low": 90, "high": 110, "change_pct": 1},
    {"symbol": "X", "prev_close": 0, "low": 90, "high": 110, "change_pct": 1},
    {"symbol": "X", "prev_close": 100, "low": None, "high": None, "change_pct": 1},
    {"symbol": "X", "prev_close": 100, "low": 90, "high": 110, "change_pct": None},
])
def test_a_row_with_missing_numbers_is_skipped_not_guessed(bad):
    assert state()._find_reversals([bad]) == {"up": [], "down": []}


def test_no_rows_at_all():
    assert state()._find_reversals([]) == {"up": [], "down": []}
    assert state()._find_reversals(None) == {"up": [], "down": []}


# ---------------------------------------------------------------
# 3. ORDER AND REACH
# ---------------------------------------------------------------
def test_the_biggest_journey_leads():
    """The violence is the point, so the most violent is first."""
    got = state()._find_reversals([
        row("SMALL", 100.0, 96.0, 100.2, -0.5),   # travelled 3.5
        row("BIG", 100.0, 90.0, 100.5, -1.0),     # travelled 9.0
    ])
    assert [r["symbol"] for r in got["up"]] == ["BIG", "SMALL"]


def test_both_thresholds_are_stated_not_buried():
    assert DashboardState.REVERSAL_TRAVEL_PCT >= 1.0
    assert DashboardState.REVERSAL_EXTREME_PCT >= 1.0


# ---------------------------------------------------------------
# 4. THE TWO SCREENS
# ---------------------------------------------------------------
# ---------------------------------------------------------------
# 5. WHAT IS MOVING NOW, NOT WHAT MOVED THIS MORNING
# ---------------------------------------------------------------
#     "MOST top gainers were sitting at top and not moving in either
#      direction & occupying most favored place on dashboard & making
#      the next gainers invisible to user."
#
# The flaw in every gainers table ever built: it ranks by distance
# travelled since YESTERDAY. A stock that gapped 12% at 09:15 and has
# not ticked since outranks one moving 3% in the last ten minutes, and
# takes the space that decides where he looks.
import time as _time


def _movement_state():
    st = DashboardState.__new__(DashboardState)
    st.news_watcher = None
    st.news_impact = None
    return st


def test_a_leader_parked_on_its_gap_is_not_moving():
    st = _movement_state()
    rows = [{"symbol": "STALLED", "change_pct": 12.0}]
    st._mark_movement(rows)
    st._move_history["STALLED"].insert(
        0, (_time.time() - 16 * 60, 11.9))
    st._mark_movement(rows)
    assert rows[0]["moving"] is False
    assert rows[0]["recent_pct"] == 0.1


def test_a_smaller_stock_actually_running_is_moving():
    st = _movement_state()
    rows = [{"symbol": "RUNNER", "change_pct": 3.0}]
    st._mark_movement(rows)
    st._move_history["RUNNER"].insert(0, (_time.time() - 16 * 60, 0.4))
    st._mark_movement(rows)
    assert rows[0]["moving"] is True
    assert rows[0]["moving_dir"] == "UP"


def test_a_stock_falling_now_is_moving_too():
    """Either direction. A loser accelerating is as tradeable as a
    gainer accelerating, and he asked for both sides."""
    st = _movement_state()
    rows = [{"symbol": "SLIDER", "change_pct": -6.0}]
    st._mark_movement(rows)
    st._move_history["SLIDER"].insert(0, (_time.time() - 16 * 60, -1.0))
    st._mark_movement(rows)
    assert rows[0]["moving"] is True
    assert rows[0]["moving_dir"] == "DOWN"


def test_too_little_history_says_so_rather_than_calling_it_stalled():
    """"we have not watched it long enough" and "it is not moving" are
    different sentences, and only one of them is an answer."""
    st = _movement_state()
    rows = [{"symbol": "NEW", "change_pct": 4.0}]
    st._mark_movement(rows)
    assert rows[0]["moving"] is None
    assert rows[0]["recent_pct"] is None


def test_a_row_with_no_price_is_left_alone():
    st = _movement_state()
    rows = [{"symbol": "NOPRICE", "change_pct": None}]
    st._mark_movement(rows)
    assert "moving" not in rows[0]


def test_the_history_does_not_grow_without_bound():
    """This runs once a second for 946 symbols, all session."""
    st = _movement_state()
    rows = [{"symbol": "X", "change_pct": 1.0}]
    for _ in range(50):
        st._mark_movement(rows)
    st._move_history["X"].insert(0, (_time.time() - 3 * 60 * 60, 0.0))
    st._mark_movement(rows)
    oldest = st._move_history["X"][0][0]
    assert _time.time() - oldest <= st.MOVING_WINDOW_SECONDS * 1.6


