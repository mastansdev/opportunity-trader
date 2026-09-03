"""---- WHAT DHAN ACTUALLY BILLS. 3 September 2026. ----

    "dhan charges us 20 rs for buying & 20rs for selling == 40rs only
     for broker irrespective of qty; next STT, other charges added up
     will become around 100 rs"                     -- the operator

_brokerage() was min(Rs 20, 0.03% of turnover) -- the published
"whichever is lower" wording. It is not what his account is billed.
The min() only bit below Rs 66,667 of turnover, and a slot is now
Rs 15,000 at 4x = Rs 60,000, so it bit on EVERY trade the bot places.

Why this is worth a test rather than a one-line change: the charge
number decides whether a trade is worth placing at all. His breakeven
is 0.116% of the position. Understating the cost understates the
breakeven, and the bot then takes trades that cannot pay for
themselves. Ten of today's twenty did exactly that.
"""

import config
from trading.charges import _brokerage, round_trip_charges


def test_a_small_order_still_pays_twenty():
    """THE BUG. Rs 60,000 is what a slot buys at 4x, and 0.03% of it
    is Rs 18 -- so every live trade was costed Rs 2 light on each leg
    while the account was billed Rs 20."""
    assert _brokerage(60_000) == 20.0


def test_it_does_not_scale_with_size():
    """'irrespective of qty' -- his words. One order, one price."""
    assert _brokerage(5_000) == _brokerage(50_00_000) == 20.0


def test_a_round_trip_pays_forty_to_the_broker():
    """Two orders, Rs 20 each. The rest of the round trip is STT,
    exchange, SEBI, stamp and GST on top."""
    total = round_trip_charges(600.0, 606.0, 100, "LONG")
    assert total > 40.0
    assert total < 120.0, "a Rs 60,000 round trip near his ~Rs 100"


def test_the_pct_is_not_read_here_any_more():
    """BROKERAGE_PCT stays in config for the other plans that quote
    it, but no longer decides an intraday bill."""
    assert config.BROKERAGE_PCT == 0.0003          # still declared
    assert _brokerage(1_000) == 20.0               # and not used
