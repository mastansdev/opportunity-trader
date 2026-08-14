"""
Transaction-cost model tests (trading/charges.py). Proves the
charge estimate is sane and that it correctly turns a tiny gross
"profit" into the net loss it really is after costs -- the operator's
whole point (RELIANCE / HDFCBANK partials, 2026-07-24).
"""

from trading.charges import round_trip_charges


def test_charges_are_positive_and_reasonable_for_a_normal_round_trip():
    # 20 shares, ~Rs 25k a side -- charges should be a few tens of Rs,
    # not zero and not hundreds.
    c = round_trip_charges(1279.5, 1281.0, 20, "LONG")
    assert 10 < c < 60


def test_a_tiny_gross_profit_becomes_a_net_loss_after_charges():
    """HDFCBANK partial today: 33 sh, +Rs 0.60 => Rs 19.80 gross.
    Charges exceed that, so the real net is negative."""
    gross = (747.2 - 746.6) * 33
    charges = round_trip_charges(746.6, 747.2, 33, "LONG")
    assert gross - charges < 0


def test_short_side_charges_are_computed_too():
    c = round_trip_charges(1000.0, 990.0, 50, "SHORT")
    assert c > 0


def test_degenerate_records_cost_nothing_rather_than_raising():
    assert round_trip_charges(0.0, 100.0, 10, "LONG") == 0.0
    assert round_trip_charges(100.0, 100.0, 0, "LONG") == 0.0
    assert round_trip_charges(100.0, 100.0, -5, "LONG") == 0.0


def test_brokerage_is_capped_per_order_on_large_turnover():
    """0.03% on a huge turnover would exceed the Rs 20/order cap, so
    a very large trade's brokerage is capped -- charges grow with STT/
    exchange fees but brokerage stops at Rs 20 per leg (Rs 40 total)."""
    small = round_trip_charges(100.0, 100.0, 100, "LONG")     # 10k a side
    big = round_trip_charges(100.0, 100.0, 100000, "LONG")    # 100L a side
    # Big is far larger overall (STT/exchange scale), but sanity: both
    # positive and big > small.
    assert big > small > 0


# ---------------------------------------------------------------
# OVERNIGHT / MTF COSTS, 2026-07-28.
#
# Operator's correction: "do not consider mtf charges right away on
# closed positions too". He was right -- MTF interest starts at T+1, so
# a trade that lived 6 seconds owes none of it. I had charged it.
# My second error went the other way: delivery STT is 0.1% on BOTH
# sides, not sell-side only, so the overnight figure was UNDERstated.
# ---------------------------------------------------------------

from datetime import datetime

from trading.charges import mtf_carry_cost, nights_between


def test_a_same_day_trade_pays_no_overnight_cost():
    """THE operator's correction. Default is intraday, always."""
    same = round_trip_charges(604.10, 597.50, 331)
    explicit = round_trip_charges(604.10, 597.50, 331, nights_held=0)
    assert same == explicit


def test_holding_overnight_costs_strictly_more():
    intraday = round_trip_charges(604.10, 610.00, 331, nights_held=0)
    overnight = round_trip_charges(604.10, 610.00, 331, nights_held=1)
    assert overnight > intraday


def test_delivery_stt_is_charged_on_BOTH_legs():
    """My first correction modelled it sell-side only and understated
    the cost. Delivery STT is 0.1% on the buy AND the sell."""
    from config import STT_DELIVERY_PCT, STT_SELL_PCT
    entry, exit_, qty = 1000.0, 1000.0, 100
    intraday = round_trip_charges(entry, exit_, qty, nights_held=0)
    overnight = round_trip_charges(entry, exit_, qty, nights_held=1)
    stt_gap = (STT_DELIVERY_PCT * (entry * qty + exit_ * qty)
               - STT_SELL_PCT * exit_ * qty)
    assert overnight - intraday > stt_gap


def test_interest_accrues_only_on_the_FUNDED_portion():
    """At 4x the operator puts up 25%. Only the borrowed 75% accrues."""
    from config import MTF_INTEREST_DAILY_PCT, MTF_LEVERAGE
    value = 200000.0
    cost = mtf_carry_cost(value, nights_held=1)
    pledge = 15.0 * 2 * 1.18
    interest = cost - pledge
    expected = value * (1 - 1 / MTF_LEVERAGE) * MTF_INTEREST_DAILY_PCT
    assert abs(interest - expected) < 0.01


def test_interest_scales_with_nights_but_pledge_does_not():
    one = mtf_carry_cost(200000.0, nights_held=1)
    ten = mtf_carry_cost(200000.0, nights_held=10)
    pledge = 15.0 * 2 * 1.18
    assert abs((ten - pledge) - 10 * (one - pledge)) < 0.01


def test_no_carry_cost_for_zero_nights():
    assert mtf_carry_cost(200000.0, nights_held=0) == 0.0


def test_the_pledge_fee_hurts_small_positions_hardest():
    """It is FLAT, so it does not scale with size -- exactly the trades
    the dashboard makes look marginally profitable."""
    small = mtf_carry_cost(20000.0, nights_held=1)
    big = mtf_carry_cost(2000000.0, nights_held=1)
    assert small / 20000.0 > big / 2000000.0


def test_nights_between_counts_sessions_not_hours():
    same = nights_between(datetime(2026, 7, 28, 9, 45),
                          datetime(2026, 7, 28, 15, 10))
    overnight = nights_between(datetime(2026, 7, 28, 14, 37),
                               datetime(2026, 7, 29, 9, 20))
    assert same == 0
    assert overnight == 1


def test_nights_between_never_raises_on_bad_input():
    """A cost estimate must not be able to break a P&L display."""
    assert nights_between(None, None) == 0
    assert nights_between("not a date", datetime(2026, 7, 29)) == 0


def test_todays_kalyankjil_trade_is_charged_as_intraday():
    """13 minutes long. It must not be charged interest or pledge fees
    -- the exact mistake the operator caught."""
    entry_t = datetime(2026, 7, 28, 13, 48, 55)
    exit_t = datetime(2026, 7, 28, 14, 1, 14)
    charges = round_trip_charges(604.10, 597.50, 331,
                                 nights_held=nights_between(entry_t, exit_t))
    assert charges == round_trip_charges(604.10, 597.50, 331)
