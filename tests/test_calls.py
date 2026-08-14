"""
==========================================================
The bot decides. He clicks.
==========================================================

    "user(my) worry should be about taking trades which are sorted
     curated by bot. not by searching & calculating to trade. thats can
     be done by anywhere if dashboard is not efficient . today i almost
     lost my temper & loss moved to 20K at one time. but as markets are
     good & recovered today which is not guaranteed on every day & i
     can't take trade on the clumsy dashboards"
                                    -- operator, 3 August 2026

Every ingredient for this already existed and none of it was ever
assembled into an answer:

    core/shortlist.py     scored the stocks
    _mark_movement()      knew which were running, and why
    core/chain.py         knew BUY from WAIT from AVOID
    the results gate      knew what was blocked

He got four panels and had to do the join himself, by eye, while
Rs 20,000 moved against him. He is right that a dashboard which makes
him calculate is a dashboard he can replace with anything.

THE FOUR FILTERS
----------------
    a REASON        at least one chip -- a result, an order, a filing
    MOVING NOW      the market is acting on that reason, last 15 min
    a CLEAR CALL    the chain says BUY or SHORT, never WAIT or AVOID
    TRADEABLE       not vetoed, not already held

Four ANDs is what makes the list short. Seven scored stocks produced
two calls in the first run of this file, and the five that fell out
each failed a different one.

EMPTY IS AN ANSWER
------------------
A screen that always finds six things to trade will find six things on
a day with nothing worth doing. That is a worse failure than showing
none, because it is the one he would act on.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from dashboard.state import DashboardState


def state():
    return DashboardState.__new__(DashboardState)


def scored(symbol, **kw):
    row = {"symbol": symbol, "chain_state": "BUY", "support": 2,
           "against": 0, "score": 8.0, "ltp": 100.0, "change_pct": 3.0,
           "sector": "IT", "why": ["RESULT EXCELLENT"], "veto": []}
    row.update(kw)
    return row


def running(symbol, pct=2.0, **kw):
    row = {"symbol": symbol, "moving": True, "recent_pct": pct}
    row.update(kw)
    return row


def calls(rows, movers, held=None):
    gl = {"gainers": [m for m in movers if (m.get("recent_pct") or 0) >= 0],
          "losers": [m for m in movers if (m.get("recent_pct") or 0) < 0]}
    return state().build_calls({"rows": rows}, gl, held or {})


# ---------------------------------------------------------------
# 1. WHAT EARNS A PLACE
# ---------------------------------------------------------------
def test_a_stock_with_a_reason_that_is_moving_and_called_makes_the_list():
    got = calls([scored("REDINGTON")], [running("REDINGTON", 2.6)])
    assert [r["symbol"] for r in got["rows"]] == ["REDINGTON"]
    assert got["rows"][0]["action"] == "BUY"


def test_a_falling_stock_with_a_reason_is_a_short():
    got = calls([scored("LATENTVIEW", chain_state="SHORT",
                        why=["RESULT WEAK"])],
                [running("LATENTVIEW", -1.9)])
    assert got["rows"][0]["action"] == "SHORT"


def test_the_row_carries_one_reason_not_five_chips():
    """He gets the strongest, already sorted by weight in
    core/shortlist.py. Weighing them is the work being removed."""
    got = calls([scored("X", why=["ORDER WIN Rs 2,205cr",
                                  "PULSE: Excellent results", "up 3.0%"])],
                [running("X")])
    assert got["rows"][0]["why"] == "ORDER WIN Rs 2,205cr"


def test_the_backing_count_travels_with_it():
    got = calls([scored("X", support=3, against=1)], [running("X")])
    row = got["rows"][0]
    assert row["support"] == 3 and row["against"] == 1


def test_the_live_news_is_attached_when_there_is_some():
    got = calls([scored("X")],
                [running("X", why_now={"kind": "ORDER",
                                       "text": "wins Rs 412cr mandate"})])
    assert "412cr" in got["rows"][0]["news"]


# ---------------------------------------------------------------
# 2. WHAT IS KEPT OUT, AND WHY EACH ONE MATTERS
# ---------------------------------------------------------------
def test_a_leader_that_stopped_moving_is_not_a_call():
    """SHADOWFAX at +12% that has not ticked in an hour. It topped the
    gainers table all day and there was nothing to do about it."""
    got = calls([scored("SHADOWFAX", change_pct=12.1)],
                [{"symbol": "SHADOWFAX", "moving": False, "recent_pct": 0.1}])
    assert got["rows"] == []


def test_a_stock_the_chain_is_unsure_about_is_not_a_call():
    """WAIT is not a soft yes. Putting it on this list with a button
    beside it makes it one."""
    got = calls([scored("MAYBE", chain_state="WAIT")], [running("MAYBE")])
    assert got["rows"] == []


def test_a_move_with_no_reason_behind_it_is_not_a_call():
    """     "without any thing stock doesn't move, that something is we
             need to find out"   """
    got = calls([scored("NOREASON", support=0, why=[])],
                [running("NOREASON")])
    assert got["rows"] == []


def test_a_vetoed_stock_is_not_a_call():
    """Ex-dividend, surveillance, no feed. The veto exists precisely so
    it never reaches a button."""
    got = calls([scored("VETOED", veto=["ex-dividend today"])],
                [running("VETOED")])
    assert got["rows"] == []


def test_something_already_held_is_not_offered_again():
    """No pyramiding, and a second BUY on an open position is refused
    downstream anyway -- offering it is inviting a click that fails."""
    got = calls([scored("URBANCO")], [running("URBANCO")],
                held={"URBANCO": {}})
    assert got["rows"] == []


def test_the_four_filters_together_make_it_short():
    """Seven scored, two calls -- each of the five drops out for a
    different reason. This is the whole design in one assertion."""
    rows = [
        scored("GOOD"),
        scored("STALLED"),
        scored("UNSURE", chain_state="WAIT"),
        scored("NOWHY", support=0, why=[]),
        scored("BLOCKED", veto=["no feed"]),
        scored("MINE"),
        scored("FALLING", chain_state="SHORT"),
    ]
    movers = [running("GOOD"), running("UNSURE"), running("NOWHY"),
              running("BLOCKED"), running("MINE"), running("FALLING", -2.0),
              {"symbol": "STALLED", "moving": False, "recent_pct": 0.0}]
    got = calls(rows, movers, held={"MINE": {}})
    assert {r["symbol"] for r in got["rows"]} == {"GOOD", "FALLING"}


# ---------------------------------------------------------------
# 3. EMPTY IS AN ANSWER
# ---------------------------------------------------------------
def test_nothing_worth_doing_says_so():
    got = calls([scored("X", chain_state="AVOID")], [running("X")])
    assert got["rows"] == []
    assert "nothing meets the bar" in got["note"]


def test_no_scored_rows_at_all_says_so_differently():
    got = state().build_calls({"rows": []}, {}, {})
    assert got["note"] == "nothing scored yet"


def test_it_never_pads_the_list_to_look_busy():
    """Twenty perfectly good candidates still yield at most CALLS_MAX.
    A screen that always finds six things will find six on a day with
    nothing worth doing."""
    rows = [scored(f"S{i}") for i in range(20)]
    movers = [running(f"S{i}") for i in range(20)]
    got = calls(rows, movers)
    assert len(got["rows"]) == DashboardState.CALLS_MAX
    assert DashboardState.CALLS_MAX <= 8, (
        "a list he has to scroll is a list he has to search")


# ---------------------------------------------------------------
# 4. IT REACHES THE SCREEN, AND IT IS THE FIRST THING ON IT
# ---------------------------------------------------------------
def test_the_calls_are_in_the_payload():
    src = open("dashboard/state.py", encoding="utf-8").read()
    assert '"calls": self.build_calls(' in src


def test_the_panel_is_drawn_and_comes_first():
    html = open("dashboard/static/index.html", encoding="utf-8").read()
    assert "function renderCalls" in html
    assert "renderCalls(snap.calls)" in html
    assert html.index('id="otCalls"') < html.index('id="otBook"'), (
        "what to do comes before what you already hold")
    assert html.index('id="otCalls"') < html.index('id="tabNav"'), (
        "and before every tab -- it is the answer, not a tab's content")


def test_each_call_has_exactly_one_button():
    """Symbol, reason, button. A row offering both BUY and SHORT is a
    row you can misread in a hurry."""
    html = open("dashboard/static/index.html", encoding="utf-8").read()
    block = html[html.find("function renderCalls"):]
    block = block[:block.find("function otGradeChip")]
    assert 'buy ? "BUY" : "SHORT"' in block


def test_the_size_box_reuses_the_one_that_already_works():
    """QTY_BY_SYMBOL survives the one-second rebuild and restores the
    caret -- the fix for "while i try to keep some number 55 or 48 its
    not working, & got struck". A second mechanism would bring it back."""
    html = open("dashboard/static/index.html", encoding="utf-8").read()
    block = html[html.find("function renderCalls"):]
    block = block[:block.find("function otGradeChip")]
    assert "data-qtyfor" in block
    assert "data-qtyfrom" not in html


# ---------------------------------------------------------------
# 5. EVERY ROW HE CAN ACT ON HAS A BUTTON
# ---------------------------------------------------------------
#     "no buttons provided in TURNED AROUND , FROM SEARCH BAR , &
#      WATCHLIST - JUNGLE OF STOCKS WITH NO DISTINCT. TOP GAINERS ARE
#      BURIED AT LAST & USER NEEDS TO SCROL DOWN"
#
# A row he cannot act on is a row that wasted his time. TURNED AROUND
# existed precisely to surface the stock in neither top-50 list -- and
# then made him go elsewhere to trade it.
def _html():
    return open("dashboard/static/index.html", encoding="utf-8").read()


def test_a_turned_around_stock_can_be_traded_from_its_own_row():
    """The attribute is BUILT -- 'data-' + (up ? "buy" : "short") -- so
    the literal never appears in the source. Asserting on it failed,
    which is the fourth time tonight a test looked for prose instead of
    behaviour. Assert the construction."""
    html = _html()
    block = html[html.find("function renderReversals"):]
    block = block[:block.find("function renderMoving")]
    assert "'data-' + (up ? \"buy\" : \"short\")" in block
    assert "ot-call-btn" in block
    assert "data-qtyfor=" in block


def test_a_turn_up_offers_buy_and_a_turn_down_offers_short():
    """One direction per row. A row offering both is a row you can
    misread in a hurry."""
    html = _html()
    block = html[html.find("function renderReversals"):]
    block = block[:block.find("function renderMoving")]
    assert 'up ? "buy" : "short"' in block
    assert 'up ? "BUY" : "SHORT"' in block


def test_the_watchlist_rows_carry_a_button():
    html = _html()
    block = html[html.find("var addRowButtons"):]
    block = block[:block.find("var refresh =")]
    assert "data-buy=" in block
    assert "data-qtyfor=" in block


def test_the_watchlist_buttons_survive_a_redraw():
    """It redraws on every socket push. Buttons added once at load
    would vanish on the first tick."""
    html = _html()
    assert "MutationObserver(refresh)" in html


def test_a_row_that_is_not_a_symbol_gets_no_button():
    """Section headers and totals live in the same tbody. A BUY on
    'TOTAL' is an order nobody meant to place."""
    html = _html()
    block = html[html.find("var addRowButtons"):]
    assert "/^[A-Z0-9&_-]{2,20}$/" in block


# ---------------------------------------------------------------
# 6. THE JUNGLE IS SHUT UNTIL HE ASKS FOR IT
# ---------------------------------------------------------------
def test_focus_mode_exists_and_is_the_default():
    """Three previous passes ADDED panels to the top of a 39-panel
    page. Adding does not reduce scroll."""
    html = _html()
    assert 'localStorage.getItem("otfocus") !== "off"' in html, (
        "focus must be ON unless he turned it off")


def test_the_movers_stay_open_in_focus_mode():
    """     "TOP GAINERS ARE BURIED AT LAST"   """
    html = _html()
    assert 'var KEEP_OPEN = ["Gainers", "Losers"];' in html


def test_focus_hides_rather_than_deletes():
    """Deleting a panel he might want is how the broker panel went
    missing for a day."""
    html = _html()
    block = html[html.find("function paintFocus"):]
    block = block[:block.find("bar.addEventListener")]
    assert "style.display" in block
    assert "remove()" not in block


def test_the_toggle_says_what_it_does():
    html = _html()
    assert "SHOW EVERYTHING" in html and "one click away" in html


def test_the_choice_survives_a_refresh():
    html = _html()
    assert 'localStorage.setItem("otfocus"' in html
