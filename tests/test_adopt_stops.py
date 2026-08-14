"""
==========================================================
Adoption must not become liquidation
==========================================================

    "so the three positions will be protected? if yes morning all
     will exit as all are under the prices u mentioned. which i
     don't want ."
                                -- operator, 5 August 2026

He read three log lines and caught it before it cost money.

The first version measured the stop 2.5% below what he PAID. Against
the real 5 August closes:

    BERGEPAINT   paid  546.26  stop  532.60  closed  540.65   ok
    MOREPENLAB   paid   77.77  stop   75.82  closed   76.77   ok
    DEEPAKNTR    paid 1799.94  stop 1754.94  closed 1723.50   BREACHED

DEEPAKNTR would have been market-sold on the first tick of the next
session for about Rs 7,644 -- not because he decided to cut it, not
because anything moved, but because the bot adopted it with a stop it
had already passed.

THE RULE
--------
The stop is measured from WHERE IT IS as well as from what he paid,
and the wider one wins. For a long, the lower. A position that is
already under water gets room to work; it is never sold merely for
being down at the moment the bot noticed it.

Author : H&M Opportunity Trader
==========================================================
"""

from core.adopt_positions import LONG, SHORT, plan_adoptions, stop_for

REAL = [
    {"symbol": "BERGEPAINT", "broker_qty": 100,
     "avg_price": 546.26, "cmp": 540.65},
    {"symbol": "DEEPAKNTR", "broker_qty": 100,
     "avg_price": 1799.94, "cmp": 1723.50},
    {"symbol": "MOREPENLAB", "broker_qty": 2000,
     "avg_price": 77.77, "cmp": 76.77},
]


def test_no_adopted_long_is_stopped_out_on_the_first_tick():
    """THE BUG HE CAUGHT. Every stop must sit BELOW the last price."""
    plan, _ = plan_adoptions(REAL)
    assert len(plan) == 3
    for row in plan:
        assert row["stop"] < row["last_price"], (
            f"{row['symbol']} would be sold at the open: stop "
            f"{row['stop']} vs price {row['last_price']}")


def test_the_underwater_one_is_measured_from_the_price_not_the_cost():
    """DEEPAKNTR: paid 1799.94, trading 1723.50. The stop belongs
    below 1723.50, not below 1799.94."""
    plan, _ = plan_adoptions(REAL)
    deepak = next(r for r in plan if r["symbol"] == "DEEPAKNTR")
    assert deepak["stop"] < 1723.50
    assert deepak["underwater"] is True


def test_the_old_behaviour_would_still_breach():
    """Proof this test tests the fix. Without the last price, the
    entry-based stop sits above where the stock actually is."""
    assert stop_for(1799.94, LONG) > 1723.50


def test_a_position_in_profit_keeps_the_entry_based_stop():
    """Up from 100 to 130: the stop stays near cost rather than being
    dragged up to 126.75. The trailing stop is what ratchets a winner
    -- adoption must not do it in one jump."""
    assert stop_for(100.0, LONG, last_price=130.0) == 97.5


def test_a_short_is_mirrored():
    """Sold at 100, now 130. The stop must sit ABOVE 130, not above
    100, or it buys back instantly."""
    stop = stop_for(100.0, SHORT, last_price=130.0)
    assert stop > 130.0


def test_no_last_price_still_produces_a_stop():
    """A stock that has not ticked yet. Entry-based is the only
    reference there is, and some protection beats none."""
    assert stop_for(100.0, LONG) == 97.5


def test_a_junk_last_price_is_ignored_not_trusted():
    for junk in (0, -5, "", "n/a", None):
        assert stop_for(100.0, LONG, last_price=junk) == 97.5


def test_no_cost_means_no_stop_and_it_is_reported():
    plan, skip = plan_adoptions(
        [{"symbol": "X", "broker_qty": 10, "avg_price": None, "cmp": 50.0}])
    assert plan == []
    assert skip and "NOT protected" in skip[0]["why"]
