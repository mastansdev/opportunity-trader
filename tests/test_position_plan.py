"""
==========================================================
Lose small -- as a rule, not an intention
==========================================================

    "MADE TO LOOSE SMALL INCASE OF LOSS & WIN BIG ON WINNING STOCKS.
     THATS THE CORE HEIRARCHY YOU MUST FOLLOW"
                                    -- operator

core/ranker.py named a stock, explained why it was moving, and stopped
talking. That is half a decision and it skips the half that loses
money.

THE IDEA
--------
Risk a fixed number of rupees and let the QUANTITY fall out of where
the stop has to be:

    qty = risk budget / (entry - stop)

Sizing the other way round -- pick a rupee value, then find a stop --
makes the loss whatever the chart happens to give. Two stocks at the
same position size lose wildly different amounts if one stops 3% away
and the other 9%, and the 9% one is always the one that hurts.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core import position_plan
from core.position_plan import (MAX_STOP_DISTANCE_PCT, MIN_STOP_DISTANCE_PCT,
                                RISK_PER_TRADE_RS, plan, stop_for)


# ---- THIS FILE TESTS THE STRUCTURAL STOP. 29 August 2026. ----
#
# config.FIXED_STOP_PCT was set to 2.0 that morning and reverted the
# same day -- chosen and measured on one window, worse than the rule
# it replaced on eleven sessions it had never seen. It is None again.
#
# Pinned off here anyway: the dial is one line from being set, and
# these guarantees are what the structural rule must still give.
@pytest.fixture(autouse=True)
def _structural_stop(monkeypatch):
    monkeypatch.setattr(position_plan, "FIXED_STOP_PCT", None)


# ---------------------------------------------------------------
# 1. THE LOSS IS THE SAME SIZE EVERY TIME. THAT IS THE POINT.
# ---------------------------------------------------------------
def test_a_tight_stop_and_a_wide_stop_risk_the_same_rupees():
    """The whole reason for sizing off the stop."""
    tight = plan(432.0, "BUY", day_low=427.0)     # ~1.2% away
    wide = plan(432.0, "BUY", day_low=411.0)      # ~4.9% away
    assert tight["ok"] and wide["ok"]
    assert abs(tight["risk_rs"] - wide["risk_rs"]) < 30
    # And the quantity is what absorbed the difference.
    assert tight["qty"] > wide["qty"] * 3


def test_the_risk_never_exceeds_the_budget():
    """Rounds DOWN. 4.7 shares is 4, never 5."""
    for low in (400.0, 415.0, 420.0, 425.0, 428.0):
        got = plan(432.0, "BUY", day_low=low)
        if got["ok"]:
            assert got["risk_rs"] <= RISK_PER_TRADE_RS


def test_the_quantity_is_derived_not_guessed():
    got = plan(100.0, "BUY", day_low=95.0)
    assert got["stop"] == 95.0
    assert got["qty"] == int(RISK_PER_TRADE_RS // 5.0)


# ---------------------------------------------------------------
# 2. THE STOP GOES WHERE THE TRADE IS WRONG
# ---------------------------------------------------------------
def test_a_long_stops_below_the_session_low():
    assert stop_for(432.0, "BUY", day_low=418.0) == 418.0


def test_a_short_stops_above_the_session_high():
    assert stop_for(298.0, "SELL", day_high=306.0) == 306.0


def test_the_tighter_of_structure_and_atr_wins():
    """A stock that ranged 8% today would otherwise licence an 8%
    stop, which is not a small loss by any reading."""
    assert stop_for(432.0, "BUY", day_low=390.0, atr=9.0) == 423.0
    assert stop_for(298.0, "SELL", day_high=340.0, atr=6.0) == 304.0


def test_no_level_means_no_stop_and_no_invented_one():
    """A made-up stop is worse than none -- it will be believed."""
    assert stop_for(432.0, "BUY") is None
    got = plan(432.0, "BUY")
    assert got["ok"] is False
    assert "no level" in got["why"]


def test_a_low_above_the_entry_is_not_a_stop():
    """Bad data, or a price that has already broken down. Either way
    it is not a level below the entry."""
    assert stop_for(100.0, "BUY", day_low=105.0) is None


# ---------------------------------------------------------------
# 3. TWO STOPS THAT ARE NOT WORTH TAKING
# ---------------------------------------------------------------
def test_a_stop_inside_the_noise_is_refused():
    """A 0.3% stop on Rs 1,500 of risk asks for Rs 5 lakh of stock,
    and the stock takes it out on a normal wobble."""
    got = plan(432.0, "BUY", day_low=431.0)
    assert got["ok"] is False
    assert "too close" in got["why"]
    assert MIN_STOP_DISTANCE_PCT >= 0.5


def test_a_stop_so_far_away_the_loss_is_not_small():
    got = plan(432.0, "BUY", day_low=380.0)
    assert got["ok"] is False
    assert "too far" in got["why"]
    assert MAX_STOP_DISTANCE_PCT <= 8.0


# ---------------------------------------------------------------
# 4. MTF CAPS IT. THE SMALLER NUMBER ALWAYS WINS.
# ---------------------------------------------------------------
def test_the_margin_cap_can_only_reduce_the_size():
    free = plan(432.0, "BUY", day_low=427.0)
    capped = plan(432.0, "BUY", day_low=427.0, margin_pct=0.25)
    assert capped["qty"] <= free["qty"]


def test_a_margin_percent_is_read_as_a_percent_not_a_fraction():
    """The unit fault this repo keeps having, caught live.

    core/mtf_margin.margin_pct() returns 0.33 for a stock on 33%
    margin, and dashboard/state.py passes that through. But
    tools/dry_run_live_path.py passed 33.0, and it did not matter for
    months: the stop came from the day's low whatever the share count
    was, so a 100x-too-small position simply sized small and passed.

    The moment the stop started following the size (29 August 2026) it
    became "stop too far -- the loss would not be small", and check 6
    of the bot's own live-path dry run went BROKEN on startup.

    Real MTF margins run 15% to 100%, so anything above 1.0 is a
    percent somebody forgot to divide.
    """
    fraction = plan(104.0, "BUY", day_low=99.0, day_high=105.0,
                    margin_pct=0.33)
    percent = plan(104.0, "BUY", day_low=99.0, day_high=105.0,
                   margin_pct=33.0)
    assert fraction["ok"] and percent["ok"]
    assert fraction["qty"] == percent["qty"]
    assert fraction["stop"] == percent["stop"]


def test_a_full_margin_stock_is_still_read_as_a_fraction():
    """1.0 is 100% margin -- no leverage, and a real answer. The guard
    must not treat the boundary as a percent and turn it into 1%."""
    got = plan(100.0, "BUY", day_low=95.0, margin_pct=1.0,
               budget_rs=50000.0)
    assert got["ok"], got
    assert got["qty"] == 500, got          # 50,000 / (100 x 1.0)


def test_a_share_costing_more_than_the_whole_budget_is_refused():
    got = plan(60000.0, "BUY", day_low=57000.0, margin_pct=1.0,
               budget_rs=10000.0)
    assert got["ok"] is False


def test_the_reported_risk_is_what_it_actually_costs():
    """The row must show what it costs, not what was asked for.

    ---- WHICH SIDE ADJUSTS, CHANGED 29 August 2026. ----
    This used to assert the risk came out BELOW the budget once the
    MTF cap bit: the stop distance was fixed by the day's low and the
    share count was cut to fit, so a capped position risked less.

    The margin figure now decides the size alone -- the same rule
    core/engine.py always used, which this file's rule disagreed with
    (TCS: card 21 shares, engine 40). The stop distance is what
    adjusts now, so the rupees at stake are exactly the budget by
    construction.

    The guarantee is unchanged in substance and stronger in form: the
    number on the card is the number the trade actually risks.
    """
    got = plan(432.0, "BUY", day_low=427.0, margin_pct=0.25,
               budget_rs=20000.0)
    assert got["ok"]
    distance = 432.0 - got["stop"]
    assert got["risk_rs"] == pytest.approx(got["qty"] * distance, abs=1.0)
    assert got["risk_rs"] == pytest.approx(RISK_PER_TRADE_RS, abs=1.0)


# ---------------------------------------------------------------
# 5. WIN BIG -- THE OTHER HALF OF THE RULE
# ---------------------------------------------------------------
def test_the_target_is_a_move_the_stock_actually_makes():
    """Was "worth at least twice the risk" until 29 August 2026.

    Twice the risk put the target 4.17% above entry on a Rs 1.2 lakh
    position, against a 2.34% daily range on TCS. A target beyond the
    day's range never fires, which is the hold-to-the-close behaviour
    it was meant to replace.

    The upside is not capped by this: ENABLE_BOT_TRAILING_STOP arms
    around +1% and follows every higher high, so a stock that keeps
    running is booked by the trail, not here.
    """
    import config

    got = plan(100.0, "BUY", day_low=95.0)
    if config.TARGET_REWARD_BY_REGIME:
        from core.rules import MIN_REWARD_MULTIPLE
        distance = 100.0 - got["stop"]
        assert got["target"] == pytest.approx(
            100.0 + distance * MIN_REWARD_MULTIPLE)
    else:
        # The exit is the trail. A card printing a target the trade
        # will not take is the fault this whole day removed.
        assert got["target"] is None
        assert got["reward_multiple"] is None


def test_a_short_targets_downwards():
    import config

    got = plan(100.0, "SELL", day_high=105.0)
    if not config.TARGET_REWARD_BY_REGIME:
        assert got["target"] is None
        return
    from core.rules import MIN_REWARD_MULTIPLE
    distance = got["stop"] - 100.0
    assert got["target"] == pytest.approx(
        100.0 - distance * MIN_REWARD_MULTIPLE)
    assert got["target"] < 100.0


# ---------------------------------------------------------------
# 6. IT NEVER BREAKS THE SESSION
# ---------------------------------------------------------------
def test_junk_in_is_a_refusal_not_an_exception():
    for bad in (None, 0, -5, "abc", float("nan")):
        got = plan(bad, "BUY", day_low=95.0)
        assert got["ok"] is False


def test_it_is_on_the_row():
    """---- AND IT IS ON NO SCREEN. 13 August 2026. ----

    This asserted the plan was computed AND drawn, and it checked
    dashboard/static/screen.html for `function planLine(`. That page
    was deleted on 13 August when four dashboards were collapsed to
    two, and board.html -- the screen he actually trades from -- has
    never drawn the plan.

    So the sizing is real and reaches core/auto_entry.py, and the
    number he would be risking is not on the row he clicks BUY from.
    That is a gap, and pointing this assertion at a surviving page
    would only hide it.

    ---- AND IT IS BACK, later the same day. ----

    The gap marker written that morning did its job. It failed the
    moment the plan reached /board, with the message "remove this test
    and restore the display assertion". Done.

    The plan now sits under the BUY button on the trading screen --
    qty, stop, target, risk -- because that is the moment it answers a
    question: how many, where is the stop, and what does this cost me
    if I am wrong.
    """
    src = open("dashboard/state.py", encoding="utf-8").read()
    code = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    assert 'row["plan"] = position_plan(' in code

    board = open("dashboard/static/board.html", encoding="utf-8").read()
    assert "r.plan" in board, (
        "the sized plan is computed and no screen shows it -- he cannot "
        "see the number he is about to risk on the row he clicks BUY "
        "from")
    assert "planline" in board, "the plan is read but never rendered"


