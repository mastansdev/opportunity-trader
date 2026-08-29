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
from config import FIXED_STOP_PCT, TARGET_REWARD_BY_REGIME
from core.logger import diagnostic


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

    # ---- THE CARD SAID 21 AND THE BOT BOUGHT 40. 29 Aug 2026. ----
    #
    #     "even it disagree (that also made by us right). we need to
    #      make bot understand & book profits not wait until close
    #      every day & loose the money"          -- operator
    #
    # Two sizing rules were live at once. This one took
    # min(risk / stop distance, what the margin affords). core/engine.py
    # _risk_sized_qty() takes the margin figure ALONE -- it dropped the
    # risk formula on 28 July, on his own instruction ("Buy no of shares
    # worth equal to 1 Lakh = mtf power"). Nobody reconciled the two.
    #
    # Measured on TCS at Rs 3,000: this card said 21 shares, the engine
    # bought 40. The stop and target printed on his phone were computed
    # for a position half the size of the one that actually opened.
    #
    # And the risk formula is what made an expensive stock untradeable.
    # A Rs 3,000 stock with a 4.68% stop got 10 shares, so it had to
    # move +9.4% to reach its target -- which does not happen in a day,
    # so the trade drifted to the close every time.
    #
    # The margin figure now decides the size, alone, exactly as the
    # engine does it. The stop then keeps the RUPEE loss fixed at
    # risk_rs by adjusting its distance, instead of the size adjusting
    # to a fixed distance. Same money at risk, a reachable target.
    if margin_pct:
        # ---- A FRACTION, NOT A PERCENT. 29 August 2026. ----
        #
        # core/mtf_margin.margin_pct() returns 0.25 for a stock on 25%
        # margin, and dashboard/state.py passes that straight through.
        # tools/dry_run_live_path.py passed 33.0 instead, and for
        # months it did not matter: the stop came from the day's low
        # whatever the share count was, so a 100x-too-small position
        # simply sized small and passed.
        #
        # The moment the stop started following the size, it became
        # "stop too far -- the loss would not be small" and check 6 of
        # the live-path dry run went BROKEN. That is the whole class of
        # fault this repo already has twice over -- config's
        # MIN_STOP_DISTANCE_PCT is 0.01 while core/rules' is 0.75.
        #
        # Real MTF margins run from about 15% to 100%. Anything above
        # 1.0 is therefore a percent that someone forgot to divide, and
        # is worth saying out loud rather than silently sizing wrong.
        margin_pct = float(margin_pct)
        if margin_pct > 1.0:
            diagnostic(f"[PLAN] margin_pct came in as {margin_pct:g} -- "
                       f"reading it as a percent. It should be a "
                       f"fraction (0.25 for 25%).")
            margin_pct /= 100.0
        per_share = entry * margin_pct
        qty = int(budget_rs // per_share) if per_share > 0 else 0
        if qty < 1:
            return {"ok": False, "why": "one share costs more than the budget"}
        # The stop is whatever puts risk_rs at stake over this many
        # shares. Recomputed here, then re-checked against the bounds
        # below -- a width this produces is not exempt from them.
        distance = risk_rs / qty
        stop_pct = distance / entry * 100.0
        stop = round(entry - distance if side == "BUY"
                     else entry + distance, 2)
        if stop_pct < MIN_STOP_DISTANCE_PCT:
            return {"ok": False,
                    "why": "this size would put the stop inside the noise"}
        if stop_pct > MAX_STOP_DISTANCE_PCT:
            return {"ok": False,
                    "why": "stop too far -- the loss would not be small"}
    else:
        # No margin figure -- paper, backtests, the preview. Falls back
        # to the risk formula rather than guessing at a size.
        qty = int(risk_rs // distance)
        if qty < 1:
            return {"ok": False, "why": "one share risks more than the budget"}

    # The target is where the reward is worth the risk. Deliberately
    # not a price prediction -- it is the level below which this trade
    # is not worth taking, which is a different and answerable question.
    # ---- ONE DIAL, SO THE CARD CANNOT LIE. 29 August 2026. ----
    # config.TARGET_REWARD_BY_REGIME is what core/engine.py books at.
    # Empty means the exit is the trail, and then this must print no
    # target either -- a card promising a level the trade will not
    # take is the same fault as the card promising 21 shares while
    # the engine bought 40.
    multiple = MIN_REWARD_MULTIPLE if TARGET_REWARD_BY_REGIME else None
    if multiple:
        reach = distance * multiple
        target = round(entry + reach if side == "BUY" else entry - reach, 2)
    else:
        target = None

    return {
        "ok": True,
        "stop": stop,
        "stop_pct": round(stop_pct, 2),
        "qty": qty,
        # What it ACTUALLY costs at the size we can take, which is not
        # the budget once the MTF cap has bitten.
        "risk_rs": round(qty * distance, 2),
        "target": target,
        "reward_multiple": multiple,
        "value_rs": round(qty * entry, 2),
    }
