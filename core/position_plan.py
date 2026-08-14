"""
==========================================================
Where you get out, and what it costs if you are wrong
==========================================================

    "MAKE THE END USER OF DASHBOARD WORK EASY TO LOOK ... MADE TO
     LOOSE SMALL INCASE OF LOSS & WIN BIG ON WINNING STOCKS. THATS
     THE CORE HEIRARCHY YOU MUST FOLLOW"
    "ride untill the momentum stays - exit once it gone ruthlessly"
                                    -- operator

WHAT WAS MISSING
----------------
core/ranker.py names a stock, explains why it is moving, and stops
talking. That is half a decision, and it skips the half that loses
money. "Lose small, win big" was an intention with nothing enforcing
it anywhere in the code.

THE ONE IDEA HERE
-----------------
Risk a FIXED NUMBER OF RUPEES per trade, and let the quantity fall out
of where the stop has to be.

    qty = risk budget / (entry - stop)

The usual way round -- pick a rupee value, then find a stop -- makes
the loss whatever the chart happens to give you. A stock with a stop
3% away and one with a stop 9% away lose wildly different amounts on
the same position size, and the 9% one will be the one that hurts.
Sizing off the stop makes every loss the same size, which is the only
version where "lose small" is a rule rather than a hope.

WHERE THE STOP GOES
-------------------
Not a fixed percentage. The stop belongs at the price that says the
reason was wrong:

    LONG   below the session low, or ATR below entry -- whichever is
           TIGHTER, so a wide day does not licence a wide stop
    SHORT  the mirror image, above the session high

If neither is available, this returns None rather than inventing a
level. A made-up stop is worse than no stop, because it will be
believed.

MTF
---
The share count is then capped by what the margin actually allows.
Risk-based sizing can ask for more shares than the account can carry;
the smaller of the two always wins.

Author : H&M Opportunity Trader
==========================================================
"""

# ---- THE NUMBERS LIVE IN core/rules.py NOW. 11 August 2026. ----
#
#     "why you created this bot as a mess of files?"
#
# This file used to declare RISK_PER_TRADE_RS = 1500.0 itself while
# config.py said 2000.0, and nothing ever passed the config value in.
# So the Rs 2,000 he had configured was never once used -- every trade
# the bot has ever sized risked Rs 1,500, silently, and neither number
# was wrong in a way anything could detect.
#
# One owner. Imported, never redeclared.
from core.rules import (
    MTF_MARGIN_PER_POSITION_RS,
    RISK_PER_TRADE_RS,          # what one losing trade costs
    MIN_STOP_DISTANCE_PCT,      # closer than this is noise, not a level
    MAX_STOP_DISTANCE_PCT,      # further than this and the loss is not small
    MIN_REWARD_MULTIPLE,        # target must be worth twice the risk
)


def _num(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if value != value else value          # NaN


def stop_for(entry, side, day_low=None, day_high=None, atr=None):
    """Where the trade is wrong. None when we cannot say.

    TIGHTER of the structural level and the ATR level. A stock that has
    ranged 8% today would otherwise licence an 8% stop, which is not a
    small loss by any reading.
    """
    entry = _num(entry)
    if not entry or entry <= 0:
        return None

    levels = []
    if side == "BUY":
        low = _num(day_low)
        if low is not None and low < entry:
            levels.append(low)
        if _num(atr):
            levels.append(entry - _num(atr))
        if not levels:
            return None
        # Tighter = the HIGHEST of the candidate stops for a long.
        return round(max(levels), 2)

    high = _num(day_high)
    if high is not None and high > entry:
        levels.append(high)
    if _num(atr):
        levels.append(entry + _num(atr))
    if not levels:
        return None
    return round(min(levels), 2)


def plan(entry, side, day_low=None, day_high=None, atr=None,
         margin_pct=None, risk_rs=None, budget_rs=None):
    """The whole trade, or an honest refusal.

    Returns:
        {"ok": True, "stop", "stop_pct", "qty", "risk_rs",
         "target", "reward_multiple", "value_rs"}
        {"ok": False, "why": "..."}

    Never raises. A tab that cannot draw must not stop the snapshot.
    """
    entry = _num(entry)
    if not entry or entry <= 0:
        return {"ok": False, "why": "no price"}

    risk_rs = RISK_PER_TRADE_RS if risk_rs is None else float(risk_rs)
    budget_rs = (MTF_MARGIN_PER_POSITION_RS if budget_rs is None
                 else float(budget_rs))

    stop = stop_for(entry, side, day_low, day_high, atr)
    if stop is None:
        # SAY SO. An invented stop is worse than none, because it will
        # be believed and it will be wrong at the worst moment.
        return {"ok": False, "why": "no level to stop behind yet"}

    distance = abs(entry - stop)
    stop_pct = distance / entry * 100.0
    if stop_pct < MIN_STOP_DISTANCE_PCT:
        return {"ok": False, "why": "stop too close -- noise would take it"}
    if stop_pct > MAX_STOP_DISTANCE_PCT:
        return {"ok": False, "why": "stop too far -- the loss would not be small"}

    # THE SIZING. Always rounds DOWN, so the risk can never exceed the
    # budget -- 4.7 shares is 4, never 5.
    qty = int(risk_rs // distance)
    if qty < 1:
        return {"ok": False, "why": "one share risks more than the budget"}

    # MTF cap. Risk-based sizing does not know what the account can
    # carry; the smaller number always wins.
    if margin_pct:
        per_share = entry * float(margin_pct)
        affordable = int(budget_rs // per_share) if per_share > 0 else 0
        if affordable < 1:
            return {"ok": False, "why": "one share costs more than the budget"}
        qty = min(qty, affordable)

    # The target is where the reward is worth the risk. Deliberately
    # not a price prediction -- it is the level below which this trade
    # is not worth taking, which is a different and answerable question.
    reach = distance * MIN_REWARD_MULTIPLE
    target = round(entry + reach if side == "BUY" else entry - reach, 2)

    return {
        "ok": True,
        "stop": stop,
        "stop_pct": round(stop_pct, 2),
        "qty": qty,
        # What it ACTUALLY costs at the size we can take, which is not
        # the budget once the MTF cap has bitten.
        "risk_rs": round(qty * distance, 2),
        "target": target,
        "reward_multiple": MIN_REWARD_MULTIPLE,
        "value_rs": round(qty * entry, 2),
    }
