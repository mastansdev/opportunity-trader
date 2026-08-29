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
# The one width, when he has set one. config, not rules: it is a dial
# he changes, not a rule the book is built on. core/engine.py reads
# the same name for the position it manages -- if these two disagree,
# the alert and the trade disagree.
from config import FIXED_STOP_PCT


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
         margin_pct=None, risk_rs=None, budget_rs=None,
         symbol=None):
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

    # ---- ONE WIDTH, AND HE PICKED IT. 29 August 2026. ----
    #
    # A fixed width has no level to sit too close to, so the
    # structural stop, the widening below and the "no level to stop
    # behind yet" refusal all belong to the ATR-scaled rule and are
    # skipped whole. That refusal was the RAILTEL filter of 19
    # August; a fixed width cannot reproduce it.
    #
    # The MIN/MAX bounds below still run and still apply -- 2.0%
    # passes both -- so a badly chosen FIXED_STOP_PCT is caught by
    # the same guards as everything else. See config.FIXED_STOP_PCT.
    if FIXED_STOP_PCT:
        stop_pct = float(FIXED_STOP_PCT)
        distance = entry * stop_pct / 100.0
        stop = round(entry - distance if side == "BUY"
                     else entry + distance, 2)
    else:
        stop = stop_for(entry, side, day_low, day_high, atr)
        if stop is None:
            # SAY SO. An invented stop is worse than none, because it
            # will be believed and it will be wrong at the worst moment.
            return {"ok": False, "why": "no level to stop behind yet"}

        distance = abs(entry - stop)
        stop_pct = distance / entry * 100.0

    # ---- A BAD STOP LEVEL IS NOT A BAD TRADE. 19 August 2026. ----
    #
    #     "alerts are recving but random alerts i'm getting"
    #
    # This refused outright, and it was the single biggest filter on
    # what reached his phone. The two best setups of 19 August:
    #
    #     RAILTEL     score 30.68   struct stop 0.10%   daily ATR 2.08%
    #     KIRLOSBROS  score 17.95   struct stop 0.14%   daily ATR 3.72%
    #
    # RAILTEL was up 4.0% while its sector fell 0.7%, on 28.4x its
    # normal volume, on a Rs 166.80 crore EPFO work order -- the
    # highest score of the day by a distance. It never alerted, and
    # KTKBANK at 5.5 did, because KTKBANK's day low happened to sit
    # far enough below its price.
    #
    # So what reached his phone was filtered by WHERE THE DAY'S LOW
    # HAPPENED TO BE, not by the quality of the opportunity -- and a
    # stock making highs on a real event is exactly the shape whose
    # day low ends up too close. The filter was strongest against the
    # setups it should have been weakest against.
    #
    # A stop a tenth of a percent below entry is not a stop, it is
    # noise. The answer is a stop that fits the stock, which is what
    # core/engine.py and core/trailing_stop.py already use. Same
    # source, same bounds -- see core/atr.scaled_stop_pct().
    #
    # TOO FAR still refuses, below. That one is a real statement about
    # the trade: the loss would not be small.
    if stop_pct < MIN_STOP_DISTANCE_PCT:
        widened = None
        if symbol:
            try:
                from core.atr import scaled_stop_pct
                from config import DAILY_ATR_STOP_MULT
                widened = scaled_stop_pct(
                    symbol, DAILY_ATR_STOP_MULT, MIN_STOP_DISTANCE_PCT,
                    MAX_STOP_DISTANCE_PCT, MIN_STOP_DISTANCE_PCT)
            except Exception:                              # noqa: BLE001
                widened = None
        if not widened:
            return {"ok": False,
                    "why": "stop too close and no daily range to widen it"}
        stop_pct = widened
        distance = entry * stop_pct / 100.0
        stop = round(entry - distance if side == "BUY"
                     else entry + distance, 2)
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
