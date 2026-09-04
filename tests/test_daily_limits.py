"""
The daily guardrails, re-chosen 29 July 2026.

Both numbers were set when a position was Rs 1 lakh of STOCK. The MTF
margin call had been failing silently on a NameError for weeks, so every
position was unleveraged. When that was fixed, one position began
controlling ~Rs 3.8 lakh -- and both limits silently came to mean
something quite different from what was chosen.

    one failed trade, 2.5% stop
      no leverage (what was really running)   Rs 2,500  -> 8.0 trades
      MTF working (from 30 July)              Rs 9,500  -> 2.1 trades

And the profit target was biting before the loss limit ever did. All
three recorded sessions, scored under the new exit rules with leverage:

    date          trades   x3.8 leverage
    2026-07-27        21           8,476
    2026-07-28        19          49,687   <- would have STOPPED at 30,000
    2026-07-29        40          24,552

On 28 July the bot would have crossed Rs 30,000 partway through and
switched itself off, leaving Rs 19,687 on the table.

The operator chose Rs 40,000 and Rs 75,000 from these numbers.

---- AND Rs 40,000 WAS THREE TIMES WHAT IT CLAIMED. 11 August 2026. ----

The Rs 9,500-per-failed-trade figure above assumes a position controls
Rs 3.8 lakh. It cannot. A position is capped at
MTF_MARGIN_PER_POSITION_RS = Rs 30,000 of margin, so at 3.8x it
controls Rs 1.14 lakh and a 2.5% stop costs about Rs 2,850 -- not
Rs 9,500. Rs 40,000 was therefore never "about four failed trades",
it was fourteen, and this file said so for two weeks while both its
loss tests sat red.

    daily loss  Rs 12,000, chosen by the operator 11 August 2026
                12,000 / 2,850 = 4.2 failed trades

Four is the number he wants to be wrong before the bot stops him.
"""

import pytest

from config import (
    DAILY_MAX_LOSS_RS, DAILY_PROFIT_TARGET_RS,
    HARD_STOP_FROM_ENTRY_PCT, MTF_MARGIN_PER_POSITION_RS,
)
from core.rules import MAX_OPEN_POSITIONS

# What one position controls once MTF margin works. COFORGE measured
# 26.27%, about 3.8x -- see core/mtf_margin.py.
TYPICAL_LEVERAGE = 3.8



# ---- THE CAP IS A LIVE GUARDRAIL, SO MEASURE IT LIVE. 4 Sep 2026 ----
# MTF_MARGIN_PER_POSITION_RS is per mode from 4 September: Rs 50,000
# in PAPER (a fixed Rs 5 lakh purse, for testing behaviour freely) and
# Rs 15,000 in LIVE. DAILY_MAX_LOSS_RS governs REAL money only -- it
# is not applied in paper at all, see
# config.DAILY_LOSS_CAP_APPLIES_IN_PAPER -- so its ratio must be
# measured against the LIVE slot whatever mode the test runs in.
LIVE_SLOT_RS = 15_000.0


def _loss_per_failed_trade():
    return LIVE_SLOT_RS * TYPICAL_LEVERAGE * HARD_STOP_FROM_ENTRY_PCT


def test_the_loss_limit_allows_about_seven_failed_trades():
    """---- HE HALVED THE SLOT AND KEPT THE CAP. 3 Sep 2026. ----

    This asked for 3.5 to 5 failed trades, which was right while a
    slot was Rs 30,000. On 3 September the slot became Rs 15,000 --
    eight seats on his Rs 1,23,491 instead of four -- because the book
    was full 290 of the day's 306 minutes and the bot was arriving late
    to every setup that mattered.

    Halving the slot halves what a failed trade costs. The same
    Rs 12,000 now buys about seven of them, not four. He was told the
    ratio moved and answered:

        "keep 12000 as it is"

    So the cap is deliberate and this band records HIS number rather
    than continuing to assert the old slot's arithmetic. The band is
    still a band: a cap worth twenty stop-outs would not be a brake,
    and one worth two would end most days by 10am.
    """
    trades = DAILY_MAX_LOSS_RS / _loss_per_failed_trade()
    assert 5.0 <= trades <= 9.0


def test_the_loss_limit_is_a_sane_share_of_capital():
    """A daily stop should be a few percent of what is actually at risk.

    ---- THE DENOMINATOR WAS NEVER TRUE. 11 August 2026. ----

    This measured against a flat Rs 10,00,000 "deployed". The bot has
    never deployed Rs 10 lakh and cannot: MAX_OPEN_POSITIONS is 3 and
    each one is capped at MTF_MARGIN_PER_POSITION_RS, so the most
    margin that can ever be out is Rs 90,000, controlling about
    Rs 3.42 lakh of stock at 3.8x.

    Measured against a number two-and-a-half times larger than the
    real one, this test demanded a daily stop of at least Rs 20,000 --
    while test_the_loss_limit_allows_about_four_failed_trades demanded
    at most Rs 14,250. No value could satisfy both, and the pair sat
    red rather than either being wrong out loud.

    The BAND is unchanged -- a few percent, 2% to 5%, exactly as
    chosen. Only the denominator is now the real one.

    ---- THE SEAT COUNT IS NOT MAX_OPEN_POSITIONS. 3 Sep 2026. ----

    This multiplied by core.rules.MAX_OPEN_POSITIONS, which is 3. The
    live book has not been sized by that constant since cash sizing
    went in: core.capital.slots() divides real capital by the slot, and
    engine._position_cap() only falls back to MAX_OPEN_POSITIONS when
    cash sizing is off or no portfolio is wired. On his Rs 1,23,491
    the real book is EIGHT seats, so this was measuring the cap
    against three-eighths of the money actually at risk.
    """
    from core.capital import slots

    # His Dhan balance on 3 September 2026, read live by the bot and
    # confirmed by him ("capital is correctly read with dhan"). Written
    # here as a number because there is no config constant for it --
    # capital is a fact about the account, not a setting.
    HIS_CAPITAL_RS = 123_491.0

    seats = int(HIS_CAPITAL_RS // LIVE_SLOT_RS)
    at_risk = seats * LIVE_SLOT_RS * TYPICAL_LEVERAGE
    assert 0.02 <= DAILY_MAX_LOSS_RS / at_risk <= 0.05


def test_the_profit_target_clears_a_normal_good_day():
    """28 July was Rs 49,687 under the new rules. The target must not
    stop the bot in the middle of a day like that."""
    assert DAILY_PROFIT_TARGET_RS > 49_687


def test_the_profit_target_still_exists():
    """Not removed. A genuinely wild session should still be able to
    end early rather than run unbounded."""
    assert DAILY_PROFIT_TARGET_RS > 0


def test_the_target_is_further_away_than_the_loss_limit():
    """A bot that stops itself on good days sooner than on bad ones has
    the asymmetry backwards."""
    assert DAILY_PROFIT_TARGET_RS > DAILY_MAX_LOSS_RS
