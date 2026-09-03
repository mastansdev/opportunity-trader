"""
==========================================================
The stop he did not know he was trading
==========================================================

    "what are we using 1% stoploss? from when this came i'm not
     aware of this logic"
                                    -- operator, 1 August 2026

He was right not to recognise it. He never approved a 1% stop.

WHAT HAPPENED
-------------
MIN_STOP_DISTANCE_PCT is a FLOOR UNDER THE ATR TRAIL. It was raised
0.5% -> 1.0% on 24 July after CAPLIPOINT was trailed out at +0.22%
after six minutes -- its job was to stop the TRAIL clipping winners
on noise.

On 29 July the trail was switched off entirely (the 80-trade replay:
"the finding is not use a wider trail, it is the trail should not be
there") and the surviving stop became HARD_STOP_FROM_ENTRY_PCT, 2.5%,
measured. _atr_entry_sizing() was updated to use it.

The manual dashboard path was not. So from 29 July to 1 August:

    the bot's own entries      2.5% stop
    every dashboard BUY        1.0% stop

Two stops in one account, off a constant whose purpose had been
deleted three days earlier, with nothing anywhere saying why. Nobody
noticed because nothing went red.

WHAT THE 1% WAS DOING
---------------------
50,422 entries, buy at close, hold 3 sessions, liquid NSE stocks
since 1 April:

    stop    avg/trade   stopped out   winners killed
    1.0%      +0.392%      72.9%          51.4%
    2.5%      +0.424%      45.2%          19.7%
    3.5%      +0.489%      30.7%           9.8%
    5.0%      +0.577%      16.5%           3.2%
    none      +0.634%       0.0%              -

It was closing HALF of every winning trade. Of trades that finished
higher after three sessions the median dipped 1.05% below entry on
the way -- the stop sat inside ordinary noise, and on a multi-day MTF
hold that is fatal.

WHY 2.5%, WHEN 3.5% EARNS MORE
------------------------------
Leverage, not returns. At 4X on a Rs 4,00,000 position Dhan's holding
coverage reaches 20% -- their margin-call line -- at a 6.27% fall.
That 6.27% is the whole runway:

    2.5% stop -> Rs -10,000    3.77% of room left
    3.5% stop -> Rs -14,000    2.77% of room left
    5.0% stop -> Rs -20,000    1.27% of room left
    no stop   -> worst single trade in the sample, -90.26%

The extra Rs 261/trade a 3.5% stop earns is what you would pay to sit
2.77% away from a broker margin call on every open position.

If leverage ever drops to 2X the runway doubles and 3.5% becomes the
right number. That is the trigger to revisit this, not a calendar.

Author : H&M Opportunity Trader
==========================================================
"""

import io
import re
import tokenize

import pytest

import config
from config import MTF_MARGIN_PER_POSITION_RS


def _code_only(path):
    """Source with comments and docstrings stripped.

    Four tests in this project have now failed on their own English --
    a docstring saying a thing is NOT done read as the thing being
    done. The block above this file's own change is fifty lines of
    commentary containing the literal text "MIN_STOP_DISTANCE_PCT"
    several times, so matching raw source here would be guaranteed to
    lie.
    """
    src = open(path, encoding="utf-8").read()
    out, prev_end, prev_type = [], (1, 0), tokenize.INDENT
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and prev_type in (
                tokenize.INDENT, tokenize.DEDENT, tokenize.NEWLINE,
                tokenize.NL, tokenize.ENCODING):
            prev_type = tok.type
            continue
        out.append(tok.string)
        prev_end, prev_type = tok.end, tok.type
    return " ".join(out)


ENGINE = "core/engine.py"


# ---------------------------------------------------------------
# 1. THE NUMBER ITSELF
# ---------------------------------------------------------------
def test_the_hard_stop_is_two_and_a_half_percent():
    """His own number, from the 29 July replay. If this ever moves,
    every table in this file's docstring was measured against a stop
    that no longer exists."""
    assert config.HARD_STOP_FROM_ENTRY_PCT == 0.025


def test_one_percent_is_still_the_trail_floor_and_only_that():
    """MIN_STOP_DISTANCE_PCT is not deleted -- it still floors the ATR
    trail distance. It simply must not be an ENTRY stop any more."""
    assert config.MIN_STOP_DISTANCE_PCT == 0.01


def test_the_floor_still_belongs_to_a_trail_that_is_running():
    """The floor keeps the trail from getting razor-thin.

    While the trail was off (29 July - 29 August 2026) this asserted
    the flag was False, because a 1% entry seed was a leftover of a
    mechanism that was not running. The trail is back on, to be
    measured forward in paper against stocks fading into the close --
    so the floor has a job again, and what matters is that it exists,
    not which way the flag points.
    """
    assert config.ENABLE_BOT_TRAILING_STOP is True
    assert config.MIN_STOP_DISTANCE_PCT > 0, (
        "the trail is running with no floor under it")


# ---------------------------------------------------------------
# 2. BOTH DASHBOARD BUTTONS USE IT
# ---------------------------------------------------------------
def test_the_manual_buy_seeds_its_stop_off_the_hard_stop():
    code = _code_only(ENGINE)
    assert "floor_low = price * ( 1 - HARD_STOP_FROM_ENTRY_PCT )" in code


def test_the_manual_short_seeds_its_stop_off_the_hard_stop():
    code = _code_only(ENGINE)
    assert "floor_high = price * ( 1 + HARD_STOP_FROM_ENTRY_PCT )" in code


def test_no_entry_seed_is_left_on_the_trail_floor():
    """THE ONE THAT MATTERS. This is the exact line that was missed on
    29 July and ran live for three sessions."""
    code = _code_only(ENGINE)
    for stale in ("floor_low = price * ( 1 - MIN_STOP_DISTANCE_PCT )",
                  "floor_high = price * ( 1 + MIN_STOP_DISTANCE_PCT )"):
        assert stale not in code, (
            "a dashboard button is seeding its stop off the ATR TRAIL "
            "floor again. That is a 1% stop, and measured on 50,422 "
            "entries it closes 51.4% of all winning trades.")


def test_the_two_buttons_agree_with_each_other():
    """Two different stops on BUY and SHORT would be the same class of
    surprise as the one this file exists to fix."""
    code = _code_only(ENGINE)
    longs = re.findall(r"floor_low = price \* \( 1 - (\w+) \)", code)
    shorts = re.findall(r"floor_high = price \* \( 1 \+ (\w+) \)", code)
    assert longs and shorts
    assert set(longs) == set(shorts) == {"HARD_STOP_FROM_ENTRY_PCT"}


def test_the_manual_stop_agrees_with_the_bots_own_entries():
    """The bot's structural entries set stop_distance from the same
    constant (_atr_entry_sizing, the ENABLE_BOT_TRAILING_STOP=False
    branch). One account, one stop."""
    code = _code_only(ENGINE)
    assert "stop_distance = HARD_STOP_FROM_ENTRY_PCT * entry_price" in code


# ---------------------------------------------------------------
# 3. THE CANDLE LOW STILL WINS WHEN IT IS WIDER
# ---------------------------------------------------------------
#
# Kept deliberately. Across 1,445,619 one-minute candles (27-31 July)
# a candle low sits more than 2.5% under its own close 64 times --
# 0.004%, once every ~22,000 minutes. It is a fire alarm for the one
# violent bar, not a rule that binds. Both of his 31 July SHADOWFAX
# buys had candle lows 0.12% and 0.37% away; the floor won both.

def _seed(price, candle_low, pct):
    """The manual-buy seed rule, restated. Whichever is FURTHER from
    entry wins -- more room, never less."""
    floor = price * (1 - pct)
    if candle_low is not None and candle_low < price:
        return min(candle_low, floor)
    return floor


PCT = 0.025


@pytest.mark.parametrize("price,low,expected,why", [
    # His two real SHADOWFAX fills, 31 July, against the last candle
    # that had actually closed before each one.
    (245.32, 245.03, 245.32 * (1 - PCT), "13:59 low is 0.12% away"),
    (250.94, 250.00, 250.94 * (1 - PCT), "14:26 low is 0.37% away"),
    # A genuinely violent bar -- the rule steps back and gives room.
    (251.00, 243.00, 243.00, "candle fell 3.2% in a minute"),
    # No candle yet (first minute of the session).
    (100.00, None, 97.50, "no closed candle to read"),
    # A stale candle whose low is ABOVE the current price must never
    # seed a stop at or above entry -- it would self-trigger instantly.
    (100.00, 104.00, 97.50, "stale candle, low above price"),
])
def test_whichever_is_further_from_entry_wins(price, low, expected, why):
    assert _seed(price, low, PCT) == pytest.approx(expected), why


def test_the_seed_is_always_strictly_below_entry():
    for price in (10.0, 100.0, 250.94, 5000.0):
        for low in (None, price * 0.5, price * 0.999, price * 1.5):
            assert _seed(price, low, PCT) < price


def test_the_seed_is_never_tighter_than_the_hard_stop():
    """The candle low may only ever WIDEN the stop. If it could narrow
    it, a quiet stock would hand back a 0.02% stop -- the ACUTAAS /
    IGIL / SYRMA failure of 24 July."""
    for price in (10.0, 100.0, 250.94, 5000.0):
        for low in (None, price * 0.9, price * 0.999, price * 1.2):
            assert _seed(price, low, PCT) <= price * (1 - PCT)


# ---------------------------------------------------------------
# 4. WHAT IT COSTS, SO THE NUMBER IS NEVER ABSTRACT AGAIN
# ---------------------------------------------------------------
def test_a_stop_out_stays_inside_the_daily_loss_cap():
    """The hard stop must cost a readable fraction of the day's cap.

    ---- THE SLOT HALVED, THE CAP DID NOT. 3 September 2026. ----

    This asked for 3 to 5 stop-outs, correct while a slot was
    Rs 30,000 and a hard stop cost Rs 3,000. On 3 September the slot
    became Rs 15,000 -- eight seats on his Rs 1,23,491 rather than
    four, because the book was full for 290 of the day's 306 minutes
    and the bot reached every good setup late. A hard stop now costs
    Rs 1,500, so the unchanged Rs 12,000 buys eight of them.

    He was shown the ratio and chose: "keep 12000 as it is". The band
    records his number. It stays a band because a cap worth twenty
    stop-outs is not a brake at all.

    Note this is the HARD stop (2.5%), the broker-side backstop. The
    entry stop is FIXED_STOP_PCT = 3%, costing Rs 1,800, which the cap
    buys 6.7 of -- see test_daily_limits.py for that one.
    """
    position = config.MTF_MARGIN_PER_POSITION_RS * config.MTF_LEVERAGE
    loss = position * config.HARD_STOP_FROM_ENTRY_PCT
    assert loss == pytest.approx(MTF_MARGIN_PER_POSITION_RS * 0.10)
    assert 5 <= config.DAILY_MAX_LOSS_RS / loss <= 9


def test_the_stop_fires_well_before_dhans_margin_call():
    """Dhan liquidates on holding coverage, not on your stop:

        coverage = (combined_ledger + stock_value) / stock_value

    At 4X he owes 3/4 of the position, so coverage reaches 20% at a
    6.25% fall. The stop must sit clearly inside that -- if it did
    not, the broker's RMS would be the exit, on their schedule.
    """
    lev = config.MTF_LEVERAGE
    position = config.MTF_MARGIN_PER_POSITION_RS * lev
    borrowed = position - config.MTF_MARGIN_PER_POSITION_RS

    # value at which (-borrowed + value) / value == 0.20
    call_value = borrowed / 0.80
    call_pct = (position - call_value) / position

    assert call_pct == pytest.approx(0.0625, abs=1e-4)
    assert config.HARD_STOP_FROM_ENTRY_PCT < call_pct / 2, (
        "the stop must leave real room before Dhan's coverage line, "
        "not shave it")
