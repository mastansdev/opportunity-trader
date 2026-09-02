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
    "to be realistic i'll trade based on qty in my real trading. not
     based on risk per trade & i'll book profits once orderflow shows
     the momentum exhuasted"       -- operator, 2 September 2026

SIZE comes from the MTF margin -- the shares a Rs 30,000 slot actually
buys. The STOP is a flat 3% below entry (config.FIXED_STOP_PCT, set
2 September on his instruction and tested on both halves of the record
before it went in). The rupee loss is whatever those two produce --
about Rs 3,600 -- and it is reported honestly rather than pinned.

With FIXED_STOP_PCT set back to None the width comes from the stock own
daily range instead, and every branch below that reads day_low, the ATR
and the widening belongs to that rule.

This file used to do the opposite: risk a fixed number of rupees and
let the quantity fall out of the stop. That is still in the code,
behind config.STOP_FROM_RISK_AND_SIZE, with the full argument for it
written where the flag is set. He turned it off on 2 September, and
the note there says plainly what it costs -- the loss per trade is no
longer fixed and is usually larger.

The cost of the version he left behind was that a Rs 3,000 stock with
a wide stop got ten shares and had to move +9.4% in a day to be worth
taking. It never did, and the position drifted to the close.

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
The margin decides the share count outright. Where no margin figure is
available -- paper, backtests, the preview -- this falls back to the
risk formula rather than guessing at a size, and says so.

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
from config import (FIXED_STOP_PCT, TARGET_REWARD_BY_REGIME,
                    # Read by core/engine.py at its own sizing site
                    # too. One dial, both halves -- see the note
                    # where it is used below.
                    STOP_FROM_RISK_AND_SIZE)
import math

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
        # Round TOWARD entry and re-derive, for the same reason the
        # ATR branch below does: rounding to nearest moves the stop
        # away from entry as often as toward it, which widens the real
        # distance past the width just set, and risk_rs computed off
        # the pre-rounding distance then reports rupees the trade
        # cannot lose. ASHOKA at 126.46 read Rs 2,697.39 against a
        # true Rs 2,694.69.
        cents = distance * 100.0
        if side == "BUY":
            stop = round(math.ceil(entry * 100.0 - cents) / 100.0, 2)
        else:
            stop = round(math.floor(entry * 100.0 + cents) / 100.0, 2)
        distance = abs(entry - stop)
        stop_pct = distance / entry * 100.0
    else:
        stop = stop_for(entry, side, day_low, day_high, atr)

        if stop is None and symbol:
            # ---- IT REFUSED WITH THE ANSWER IN ITS HAND. 1 Sep 2026 ----
            #
            #     "first settle this one as it occured today might
            #      return tomorrow right with same set of rules. how do
            #      u expect different outcome while using same inputs?"
            #                                        -- the operator
            #
            # stop_for() has exactly two ways to find a level for a
            # long: today's low if it is BELOW the entry, or entry
            # minus the ATR. dashboard/state.py's ranked path calls
            # plan() WITHOUT atr -- it passes day_low, day_high,
            # margin_pct and symbol and nothing else -- so on the live
            # path the ATR branch is dead and the day low is the only
            # candidate. Missing day low, or a stock sitting at its own
            # low, and the whole trade was refused.
            #
            # On 1 September that cost NORTHARC at 49.2x its normal
            # volume, ATHERENERG, TBZ and PTC. None of them was
            # evaluated on its merits.
            #
            # THIS IS NOT AN INVENTED STOP. It is the same
            # core/atr.scaled_stop_pct() the widening below already
            # uses, the same one core/engine.py sizes every live stop
            # from -- the stock's own daily range, bounded by the same
            # floor and ceiling. The refusal below still stands for a
            # stock with no daily range at all, which is the case the
            # original comment was really about.
            try:
                from core.atr import scaled_stop_pct
                from config import DAILY_ATR_STOP_MULT
                # fallback_pct=None ON PURPOSE. The widening call
                # below passes MIN_STOP_DISTANCE_PCT because it already
                # HAS a stop and is only stretching it. Here there is no
                # stop at all, so accepting a fallback would invent one
                # for a stock with no daily range -- caught in test:
                # an unknown symbol was handed a 0.75% stop and 3,333
                # shares. None means "no range", and no range still
                # refuses.
                from_range = scaled_stop_pct(
                    symbol, DAILY_ATR_STOP_MULT, MIN_STOP_DISTANCE_PCT,
                    MAX_STOP_DISTANCE_PCT, None)
            except Exception:                              # noqa: BLE001
                from_range = None
            if from_range:
                gap = entry * float(from_range) / 100.0
                stop = round(entry - gap if side == "BUY"
                             else entry + gap, 2)

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
    # ---- AND THE SAME FAULT IN MIRROR. 31 August 2026. ----
    #
    # The note above fixed TOO CLOSE and left TOO FAR refusing, on the
    # grounds that it "is a real statement about the trade: the loss
    # would not be small". Watched live, it is the same fault wearing
    # the other face.
    #
    # ASHOKA, 31 August: +13% on a Rs 602 crore RVNL order, 231x its
    # own normal volume, delta +2.9 lakh with 100% of it measured
    # against a real book. Refused 847 times. Its day low sat 10.5%
    # below the price -- because the stock had RUN, which is the whole
    # reason it was interesting.
    #
    #     the harder a stock runs, the further its low,
    #     the more certain the refusal
    #
    # So this filter, like the last one, was strongest against exactly
    # the setups it should have been weakest against. And it refused on
    # a number that was about to be thrown away: with a margin figure
    # present the stop is RE-DERIVED below from risk and size, and for
    # ASHOKA that gives 2.78% -- well inside the ceiling. The trade
    # died on a stop it was never going to use.
    #
    # Same answer as too-close, same tool, same bounds: a stop that
    # fits the stock. core/atr.scaled_stop_pct() is what core/engine.py
    # and core/trailing_stop.py already trade on. ASHOKA's is 4.19%.
    #
    # It still refuses when there is no daily range to size against.
    # "The loss would not be small" remains true when nothing can be
    # said about the stock's own volatility -- it is only untrue when
    # the day's low happened to be far away.
    if stop_pct > MAX_STOP_DISTANCE_PCT:
        tightened = None
        if symbol:
            try:
                from core.atr import scaled_stop_pct
                from config import DAILY_ATR_STOP_MULT
                # fallback_pct is None ON PURPOSE, and this is the
                # one place it differs from the widen path above.
                # There, an unmeasurable stock falls back to the floor
                # and that is benign -- the stop was too tight and the
                # floor loosens it. Here the floor would hand a 0.75%
                # stop to a stock whose volatility nobody has measured,
                # which is the tightest possible stop on the least
                # known name. No measurement, no tightening, refuse.
                tightened = scaled_stop_pct(
                    symbol, DAILY_ATR_STOP_MULT, MIN_STOP_DISTANCE_PCT,
                    MAX_STOP_DISTANCE_PCT, None)
            except Exception:                              # noqa: BLE001
                tightened = None
        if not tightened or tightened > MAX_STOP_DISTANCE_PCT:
            return {"ok": False,
                    "why": "stop too far -- the loss would not be small"}
        stop_pct = tightened
        distance = entry * stop_pct / 100.0
        stop = round(entry - distance if side == "BUY"
                     else entry + distance, 2)

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
        # ---- THE STOP STOPS FOLLOWING THE SIZE. 2 September 2026. ----
        #
        #     "to be realistic i'll trade based on qty in my real
        #      trading. not based on risk per trade & i'll book
        #      profits once orderflow shows the momentum exhuasted"
        #
        # The share count still comes from the MTF margin. The stop no
        # longer does: it stays the width already computed above from
        # the stock's own daily range, and the rupee risk becomes
        # whatever that costs at this size -- reported honestly as
        # risk_rs below, which has always been qty x distance.
        #
        # BOTH HALVES MOVED TOGETHER. core/engine.py reads the same
        # config flag at its own sizing site. If only one of them
        # changed, the card would print one stop and the trade would
        # take another -- the exact fault of 29 August, TCS at 2,937.50
        # on his phone and 2,859.53 in the book.
        if STOP_FROM_RISK_AND_SIZE:
            # The stop is whatever puts risk_rs at stake over this many
            # shares. Recomputed here, then re-checked against the
            # bounds below -- a width this produces is not exempt.
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
        elif symbol and not FIXED_STOP_PCT:
            # THE TRADE'S OWN WIDTH, not this file's. core/engine.py
            # sizes every live stop from core.atr.entry_stop_pct(); the
            # card printed the tighter of the day's low and a passed-in
            # ATR instead, and while the flag above was on nobody could
            # see the two disagree because it overwrote both.
            #
            # On a Rs 3,000 share they give 2,940 and 2,925. A card
            # that prints a stop the trade will not take is the TCS
            # fault of 29 August. One owner now -- see the note there.
            try:
                from core.atr import entry_stop_pct
                width = entry_stop_pct(symbol)
            except Exception:                              # noqa: BLE001
                width = None
            if width:
                stop_pct = float(width)
                distance = entry * stop_pct / 100.0
                # ---- ROUND TOWARD ENTRY, NOT TO NEAREST. ----
                #
                # round() moves the stop AWAY from entry as often as
                # toward it, and away means a wider distance than the
                # width just computed. At the ceiling that breaches it:
                # ASHOKA at 126.46 on a 6.00% width rounded to 118.87,
                # which is 6.0019% -- over a bound the whole function
                # exists to respect. A hair, but a ceiling that can be
                # crossed is decorative, and this one gates real money.
                #
                # Ceiling up for a long, floor down for a short: both
                # move the stop TOWARD entry, so the realised width is
                # never more than the intended one.
                cents = distance * 100.0
                if side == "BUY":
                    stop = math.ceil(entry * 100.0 - cents) / 100.0
                else:
                    stop = math.floor(entry * 100.0 + cents) / 100.0
                stop = round(stop, 2)
                # Re-derive BOTH from the rounded stop. risk_rs is
                # qty x distance, and a distance left at its
                # pre-rounding value would report rupees the trade
                # cannot actually lose -- Rs 5.40 out on ASHOKA, which
                # is small and is still a number on his card that the
                # book would never produce.
                distance = abs(entry - stop)
                stop_pct = distance / entry * 100.0
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
