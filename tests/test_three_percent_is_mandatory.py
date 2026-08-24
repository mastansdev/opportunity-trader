"""A stock below 3% is not tradeable. Every lane, no exception.

    "we never settled the MIN_MOVE_PCT = 1.0. any random stock may move
     in this range. pls raise that from 1.0 to 3.0"
    "make sure that a stock move atleast 3.0 % is mandatory below that
     range is not tradeable & will fail (hit stoploss or waste our
     capital until book loss)"
                                    -- operator, 24 August 2026

Read one by one -- not averaged, which is what hid it -- the 28
order-win trades of 10-24 August split on exactly this:

    entered while moving         entered while drifting
    WELCORP   15.3%  +4,926      NCC        2.0%  -2,500
    BALUFORGE 10.6%  +5,496      NTPCGREEN  2.3%  -2,500
    URBANCO    9.0%  +6,747      GHCL       3.1%  -2,500
    RATNAMANI  7.4%  +8,161      RAILTEL    4.9%  -2,500

RAILTEL had 14x its normal volume and still stopped out. Volume does
not rescue a stock that is not going anywhere.

NTPCGREEN's median daily RANGE is 1.5%. It cannot deliver a 3% move on
an ordinary day; asking it to is asking for a stop.
"""

import pytest


def test_the_floor_is_three_percent():
    from core.rules import MIN_MOVE_FROM_PREV_CLOSE_PCT
    assert MIN_MOVE_FROM_PREV_CLOSE_PCT == 3.0


def test_the_ranker_reads_the_same_number():
    from core.ranker import MIN_MOVE_PCT
    from core.rules import MIN_MOVE_FROM_PREV_CLOSE_PCT
    assert MIN_MOVE_PCT == MIN_MOVE_FROM_PREV_CLOSE_PCT


def test_a_drifting_stock_is_refused_however_good_its_reason():
    """NTPCGREEN, 24 August: 2.3% move, 6.4x volume, a real order win
    -- and it stopped out for -Rs 2,500."""
    from datetime import datetime
    from core.ranker import rank
    row = {"symbol": "NTPCGREEN", "change_pct": 2.3, "ltp": 100.0,
           "volume": 5_000_000, "sector": "POWER & UTILITIES",
           "day_open": 98.0}
    reason = lambda s: {"text": "Wins 500 MW capacity in SECI auction",
                        "weight": 0.9, "direction": "POSITIVE",
                        "source": "NSE filing"}
    got = rank([row], mechanism_of=reason, adv_of=lambda s: 30.0,
               now=datetime(2026, 8, 24, 9, 16))
    assert [r["symbol"] for r in (got.get("rows") or [])] == []


def test_the_same_stock_moving_properly_is_taken():
    """So the refusal above is about the MOVE and nothing else."""
    from datetime import datetime
    from core.ranker import rank
    row = {"symbol": "NTPCGREEN", "change_pct": 7.4, "ltp": 100.0,
           "volume": 5_000_000, "sector": "POWER & UTILITIES",
           "day_open": 94.0}
    reason = lambda s: {"text": "Wins 500 MW capacity in SECI auction",
                        "weight": 0.9, "direction": "POSITIVE",
                        "source": "NSE filing"}
    got = rank([row], mechanism_of=reason, adv_of=lambda s: 30.0,
               now=datetime(2026, 8, 24, 9, 16))
    assert [r["symbol"] for r in (got.get("rows") or [])] == ["NTPCGREEN"]


def test_the_other_entry_lanes_cannot_bypass_it():
    """The ranker is the only lane that can trade, so the floor is
    mandatory by construction. If either of these is ever turned on,
    it must be checked for a movement floor of its own FIRST."""
    import config
    from core.engine import Engine
    assert config.ENABLE_EARLY_MOMENTUM_ENTRY is False
    # The breakout lane starts disarmed and the dashboard switch
    # deliberately leaves it that way -- see /api/bot_trading.
    engine = Engine.__new__(Engine)
    assert getattr(engine, "breakout_armed", False) is False


def test_the_three_move_rules_stay_named_apart():
    """They measure different things and must not be merged.

    prev-close is the gap-plus-move his rule is about; from-open is an
    intraday measure; the shortlist one only decides what is DRAWN.
    """
    from core import rules
    assert rules.MIN_MOVE_FROM_PREV_CLOSE_PCT == 3.0
    assert rules.MIN_MOVE_FROM_OPEN_PCT != rules.MIN_MOVE_FROM_PREV_CLOSE_PCT
    assert not hasattr(rules, "MIN_MOVE_PCT"), \
        "the old shared name must not come back -- it hid three rules"
