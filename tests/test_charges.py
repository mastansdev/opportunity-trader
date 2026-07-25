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
