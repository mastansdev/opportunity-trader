"""The harder it runs, the further its low, the more certain the refusal.

    "10- stop not too far = if bot takes as early as possible then why
     this needs?"                      -- operator, 31 August 2026

ASHOKA, that morning: +13% on a Rs 602 crore RVNL order, 231x its own
normal volume, cumulative delta +2.9 lakh with 100% of it classified
against a real bid and ask. The single best setup of the session.

Refused 847 times: "stop too far -- the loss would not be small".

Its day low sat 10.5% below the price, and the ceiling is 6%. The low
was that far away BECAUSE THE STOCK HAD RUN, which is the entire
reason it was interesting.

THIS IS THE 19 AUGUST FAULT IN MIRROR. That day the note in
core/position_plan.py said of the too-CLOSE refusal:

    "what reached his phone was filtered by WHERE THE DAY'S LOW
     HAPPENED TO BE, not by the quality of the opportunity -- and a
     stock making highs on a real event is exactly the shape whose day
     low ends up too close. The filter was strongest against the setups
     it should have been weakest against."

Word for word, with "close" swapped for "far". It was fixed in one
direction and left standing in the other.

AND IT REFUSED ON A DISCARDED NUMBER. With a margin figure present the
stop is re-derived below from risk and size. ASHOKA's MTF margin was
33.36%, which gives 711 shares and a 2.78% stop -- well inside the
ceiling. The trade died on a stop it was never going to use.

Same answer as too-close: a stop that fits the stock, from
core/atr.scaled_stop_pct(), which core/engine.py and
core/trailing_stop.py already trade on. ASHOKA's is 4.19%.
"""

import pytest

from core.position_plan import (MAX_STOP_DISTANCE_PCT, MIN_STOP_DISTANCE_PCT,
                                plan)


def test_ashoka_is_planned_not_refused():
    """Its real numbers from 31 August."""
    got = plan(entry=126.46, side="BUY", day_low=112.92, day_high=129.0,
               symbol="ASHOKA", margin_pct=0.3336)
    assert got["ok"] is True, got.get("why")
    assert got["qty"] == 711
    # ---- THE RUPEES ARE NO LONGER PINNED. 2 September 2026. ----
    #
    #     "to be realistic i'll trade based on qty in my real trading.
    #      not based on risk per trade"          -- the operator
    #
    # This asserted risk == Rs 2,500 and a 2.78% stop, both of which
    # were true only because the width was back-solved from the risk
    # budget. With config.STOP_FROM_RISK_AND_SIZE off the width comes
    # from ASHOKA's own daily range and the rupees follow.
    #
    # WHAT THIS TEST IS ACTUALLY FOR is unchanged and still asserted:
    # the trade is PLANNED, not refused for a 10.5% day low, and the
    # stop comes off the stock's volatility rather than off wherever
    # the session low happened to land.
    assert got["risk_rs"] == pytest.approx(
        got["qty"] * (126.46 - got["stop"]), abs=1.0)
    pct = (126.46 - got["stop"]) / 126.46 * 100.0
    assert pct <= MAX_STOP_DISTANCE_PCT, "the ceiling was breached"
    assert pct < 10.5, (
        "the stop fell back to the day low -- the whole point of this "
        "file is that a stock which RAN is not refused for having run")


def test_the_far_low_is_replaced_not_obeyed():
    """The stop must come off the stock's own volatility, never off
    wherever the session low happened to land."""
    near = plan(entry=126.46, side="BUY", day_low=124.0, day_high=129.0,
                symbol="ASHOKA", margin_pct=0.3336)
    far = plan(entry=126.46, side="BUY", day_low=100.0, day_high=129.0,
               symbol="ASHOKA", margin_pct=0.3336)
    assert near["ok"] and far["ok"]
    assert near["stop"] == far["stop"], (
        "the plan still moves with the day low; it should not")


def test_a_stock_with_no_daily_range_still_refuses():
    """"The loss would not be small" stays true when nothing can be
    said about the stock's own volatility. Only the day-low accident
    was untrue."""
    got = plan(entry=100.0, side="BUY", day_low=50.0, day_high=101.0,
               symbol="NOSUCHSYMBOLANYWHERE", margin_pct=None,
               risk_rs=2500.0)
    assert got["ok"] is False
    assert "too far" in str(got.get("why"))


def test_the_tightened_stop_respects_the_ceiling():
    """A widened-then-tightened value must still land inside the
    bounds, or the ceiling would be decorative."""
    got = plan(entry=126.46, side="BUY", day_low=90.0, day_high=129.0,
               symbol="ASHOKA", margin_pct=0.3336)
    assert got["ok"]
    pct = (126.46 - got["stop"]) / 126.46 * 100.0
    assert MIN_STOP_DISTANCE_PCT <= pct <= MAX_STOP_DISTANCE_PCT


def test_too_close_still_widens():
    """The 19 August fix is untouched."""
    got = plan(entry=126.46, side="BUY", day_low=126.40, day_high=129.0,
               symbol="ASHOKA", margin_pct=0.3336)
    assert got["ok"] is True
    pct = (126.46 - got["stop"]) / 126.46 * 100.0
    assert pct >= MIN_STOP_DISTANCE_PCT


def test_the_risk_per_trade_is_unchanged():
    """Widening the gate must not widen the loss.

    ---- WHAT "UNCHANGED" MEANS NOW. 2 September 2026. ----

    It used to mean a fixed Rs 2,500. He turned that off: size comes
    from the margin, the stop from the stock. So the loss is no longer
    a constant -- but it must still be the SAME for this stock however
    far away the day's low happens to be, which is the thing this test
    was really guarding. A session low at 112.92 and one at 124.0 must
    plan the identical trade.
    """
    seen = set()
    for low in (112.92, 100.0, 124.0):
        got = plan(entry=126.46, side="BUY", day_low=low, day_high=129.0,
                   symbol="ASHOKA", margin_pct=0.3336)
        assert got["ok"]
        seen.add((got["qty"], got["stop"]))
    assert len(seen) == 1, (
        f"the day low still moves the trade: {seen}")
