"""
==========================================================
The best stock of the day, not the first one to trigger
==========================================================

    "it must not follow old logic of first come = first buy"
    "yes 2 positions or even 1 is fine for now. but it must take the
     best stock pick of the day."
    "any specific stock is out winning others; why ? that stock is
     moving ? whats the supporting factor to the rally in stock?"
                                    -- operator, 4 August 2026

WHY THE OLD SHAPE CANNOT WORK ON RS 30,000
------------------------------------------
core/engine.py decides inside process_tick(). A stock crosses its
opening range, the tick arrives, the trade is taken. That is
first-come-first-served, and with a large account it is survivable --
the twelfth-best setup of the day still gets funded.

With Rs 30,000 and one or two slots it is fatal. A 6-out-of-10 setup
that triggers at 09:47 spends the capital that a 9-out-of-10 setup
needed at 09:52. The bot would not be picking well; it would be
picking EARLY, and calling the result a strategy.

So this module does not react to ticks. It is asked, on a clock, one
question:

    of everything moving right now, which is the best, and why?

WHAT "BEST" MEANS HERE
----------------------
Four questions, each answerable from data the bot already holds. No
new feed, no new fetch, nothing invented.

  1. IS IT BEATING ITS OWN SECTOR AND THE MARKET?
     A stock up 3% in a sector up 3% has done nothing. Excess over the
     sector is the first real evidence that something is happening to
     THIS company rather than to everything.

  2. IS MONEY BEHIND IT?
     Today's traded value against its OWN normal day. 5x is a crowd;
     0.4x is a drift on no participation. This is the operator's own
     rule -- "volumes supports the data" -- made arithmetic.

  3. IS THERE A REASON?  (MANDATORY -- NOT A SCORE)
     A named mechanism from news_memory.db (1,408 stock links, each
     with written reasoning) or a graded channel event. No mechanism,
     no candidate. His ideology, unchanged since the first day:

         "without any thing stock doesn't move, that something is we
          need to find out"

     This is the one input that can REJECT rather than merely subtract.

  4. CAN WE ACTUALLY TRADE IT?
     Liquidity known, not pinned to a circuit, not blocked upstream,
     in the tradeable universe. A perfect setup on a stock the bot has
     never seen trade is YASHO, and YASHO cost Rs 11,300.

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not place orders, size positions, set stops, or decide when to
exit. It returns a ranked list with a sentence attached to each row.
core/engine.py remains the only thing that trades.

It also does not pretend the weights are proven. They are named
constants, gathered in one place, and every pick is recorded so
core/outcomes.py can eventually say which of them earned their keep.
Right now they are my judgement, and that is a fact about them, not a
feature.

Author : H&M Opportunity Trader
==========================================================
"""

import math
from datetime import datetime, timedelta, timezone

from core.logger import diagnostic, when_it_changes


def _said_on(at):
    """The IST calendar date a reason was said, or None if it carries no
    readable date. Stored stamps are ISO, usually UTC ("+00:00"); a naive
    one is already the local IST clock. 15 September 2026."""
    if not at:
        return None
    if isinstance(at, datetime):
        got = at
    else:
        try:
            got = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
        except ValueError:
            return None
    if got.tzinfo is not None:
        got = got.astimezone(timezone(timedelta(hours=5, minutes=30)))
    return got.date()

# ---------------------------------------------------------------
# What a candidate has to clear before it is even considered
# ---------------------------------------------------------------
# ---- THE THRESHOLDS LIVE IN core/rules.py NOW. 11 August 2026. ----
#
# MIN_MOVE_PCT existed in FOUR files with three different values, and
# MIN_VOLUME_RATIO in three with two. The name hid the fact that this
# module and core/select.py are not even measuring the same thing: this
# one measures against YESTERDAY'S CLOSE, select measures against
# TODAY'S OPEN. So they are named apart now and neither is redeclared.
from core.rules import (
    MIN_MOVE_FROM_PREV_CLOSE_PCT as MIN_MOVE_PCT,
    MIN_VOLUME_RATIO,
    MIN_LIQUIDITY_CR,
    MIN_TRADABLE_PRICE_RS,
    NOT_A_REASON,
    is_a_reason,
    REQUIRE_A_REASON_ALWAYS,
    UNEXPLAINED_MIN_VOLUME_RATIO,
    UNEXPLAINED_WEIGHT,
    RANKER_W_EXCESS_SECTOR as W_EXCESS_SECTOR,
    RANKER_W_SECTOR_LEAD as W_SECTOR_LEAD,
    RANKER_W_VOLUME as W_VOLUME,
    RANKER_W_MECHANISM as W_MECHANISM,
    RANKER_W_PERSISTENCE as W_PERSISTENCE,
    RANK_BY_COMMODITY_POLARITY,
)

# Beating the sector by less than this is not leadership, it is
# rounding. Measured against the sector's own average move.
MIN_EXCESS_PCT = 0.5

# ---- WHAT AN UNEXPLAINED MOVE HAS TO SHOW INSTEAD ----
#
# A stock with no published reason can still be where the money is
# going -- MAZDOCK moved the whole defence sector on 6 August and no
# channel had written a sentence the bot could read. But price alone
# proves nothing: a drift on no volume is noise wearing a percentage.
#
# So an unexplained mover has to bring MONEY, not just movement --
# meaningfully more volume than that stock normally does. 2.5x is
# deliberately well above MIN_VOLUME_RATIO's 1.2, because a written
# reason from his channels is worth something and a stock without one
# must clear a higher bar to stand beside it.
#
# UNTESTED AT HIS HORIZON. Recorded on every pick so it can be scored
# against what those stocks actually did. (Value: core/rules.py.)

# A sector average built from one stock compares a stock to itself.
MIN_SECTOR_PEERS = 3

# NOT_A_REASON and the 15-character floor moved to core/rules.py on
# 12 August 2026 and are imported at the top of this file. They were
# declared here and nowhere else, so core/engine.py's ORB lane -- the
# other path that can place an order -- had no way to apply them and
# bought on no reason at all. One definition, both lanes.

# ---------------------------------------------------------------
# The weights are imported at the top of this file from core/rules.py,
# where they are named RANKER_W_* so they cannot be confused with
# core/select.py's, which score on a different scale entirely. Those
# two disagreed under the same name for days and looked like a bug.
# ---------------------------------------------------------------

# A challenger must beat what we already hold by THIS much before the
# bot swaps. Without it the ranking churns: two near-equal candidates
# trade places every clock tick and the account pays brokerage for the
# privilege of standing still.
SWAP_MARGIN = 2.0

# ---- IS THE MOVE STILL ON? 4 August 2026. ----
#
#   "some stocks will rally in opening 1/2 mins & sit in top gainers
#    no use of such movement in stock for trader"
#
# RBA closed +18.2%, top of the gainers list all day, high made at
# 09:16. Five hours of nothing. Day-change ranking loves that stock.
#
# More than 3% back from the day's extreme is a stock being sold into,
# not one being bought. And a move that has done less than 0.15% in the
# last window has stopped, whatever the day's number says.
# ---- SIX WAS MINE, NOT THE MARKET'S. 20 August 2026. ----
#
#     "increase top=6 so i don't miss ranker approved setups"
#
# The chain on 19 August at 12:12:
#
#     120 considered -> 15 kept by every gate -> 6 (this number)
#                    -> 2 after the card/liveness filter
#
# NINE setups passed every gate the ranker has -- reason, volume,
# sector lead, liveness, MTF, a sizeable plan -- and were discarded
# purely by list length, before the next filter even saw them. It was
# a default argument, it was never reported, and it is the same shape
# as every other invisible filter found this week.
#
# 25 sits well above the 15 that survived the gates on a busy day, so
# the gates decide what he sees and this number does not. It stays
# bounded only so a runaway upstream cannot hand the board a thousand
# rows -- the same regression-brake reasoning as the alert ceiling in
# core/telegram_desk.py.
RANKED_LIST_SIZE = 25

MAX_OFF_EXTREME_PCT = 3.0
MIN_RECENT_PCT = 0.15

# ---- FLAT AT ITS OWN HIGH IS A COIL, NOT A STALL. 3 Sep 2026. ----
#
#     "why brigade got refused?"                    -- the operator
#
# BRIGADE, 3 September, the best trade of his day:
#
#     bought 12:22:39 at 665.33
#     day high so far  665.25      off the high  0.04%
#     recent window   +0.02%       needed       +0.15%
#     verdict: FADING -- flat
#
# It had spent fifteen minutes in a ONE-RUPEE range at its own day
# high. It then broke to 732.30 and made Rs 3,406. The flat test --
# which predates this session -- cannot tell a stock coiling under its
# high from one that has stopped.
#
# Distance from the high is what separates them, and today's board
# says so plainly. Every trade, measured at its own entry minute:
#
#     BRIGADE     +3,406   at its high   recent +0.02%   FLAT
#     RAYMOND       +412   at its high   recent +0.00%   FLAT
#     BAJAJCON       +64   at its high   recent +0.00%   FLAT
#     ALEMBICLTD  -2,581   at its high   recent -0.40%   FALLING
#     FIRSTCRY    -2,164   at its high   recent -0.34%   FALLING
#     VISHNU        +218   at its high   recent -0.20%   FALLING
#
# "At its high" alone admits the two worst trades of the day. FLAT at
# its high does not: the three flat ones are all winners and every
# loser in that list is FALLING. So falling stays dead everywhere, and
# only the FLAT test is relaxed, and only within this band.
#
# Same number as config.BUYING_DRIED_UP_MIN_OFF_PEAK_PCT on purpose --
# one idea at both ends of the trade. A stock at its own high has not
# stopped being bought, so the bot may enter it, and will not sell it
# on an order-flow blip either.
COILING_AT_HIGH_PCT = 1.0

# A fading move is not deleted -- it is pushed below every live one.
# Deleting it teaches him nothing; showing it decay teaches him what a
# dying move looks like before he buys the next one.
FADING_PENALTY = 8.0

# Within this much of the band there is no meaningful trade: the book
# is one-sided and the fill is a queue, not a price. 0.5% rather than
# 0 because a stock 0.2% from its limit is, in practice, at it.
AT_CIRCUIT_PCT = 0.5

# ---- NOTHING IS NAMED BEFORE THE OPENING RANGE EXISTS ----
#      5 August 2026.
#
#     "some stocks will rally in opening 1/2 mins & sit in top gainers
#      no use of such movement in stock for trader"
#                                 -- operator, 4 August 2026
#
# On 5 August the ranker published DEEPAKNTR at 09:15:28 -- twenty-eight
# seconds after the open, fifteen minutes before the opening range it is
# supposed to trade closes. `volume_x 1.23` on 28 seconds of tape is not
# a volume measurement, and `change_pct` against yesterday's close on a
# gapped stock is not momentum.
#
# That day's five pre-09:30 picks averaged -2.71%. The eighteen from
# 09:30 onwards averaged +1.51%. The two worst losses of the session,
# DEEPAKNTR -6.05% and SFL -5.78%, were both named in the first five
# minutes and both made their high inside the first sixty seconds.
#
# Empty for fifteen minutes is the correct answer, and it is his:
#     "no trade is far more than a bad pick/wrong pick trade"
# Above this the denominator is broken, not the market. See
# volume_ratio(): the field is SORTED ON, so corrupt values are picked
# preferentially rather than diluted.
# ---- 50x MEANT A BROKEN DENOMINATOR. IT NO LONGER DOES. ----
#      27 August 2026.
#
# This was set on 23 August when 276 of 16,581 recorded multiples were
# over 50x and every one of them was a DENOMINATOR fault -- VINATIORGA
# reading 7,799x on a real 7.4x day. The denominator has since been
# fixed (core/liquidity.py: median of 20 sessions, excluding today,
# where it had been the MEAN of five INCLUDING today), and with a
# correct divisor only two or three stocks a DAY now exceed 50x -- and
# they are the biggest genuine movers in the market:
#
#     24 Aug  TVSSCS 106x   QUADFUTURE 104x   LTFOODS 97x
#     25 Aug  FACT   617x   BOROLTD    297x
#
# Checked one by one, not averaged. TVSSCS traded Rs 546cr against a
# Rs 5.1cr normal, and earningspulse.ai independently showed Rs 537cr
# that day. FACT went Rs 4.4cr -> Rs 3,054cr overnight. These are real
# event days on small caps, and 50 would refuse every one of them --
# the cap had turned from catching corruption into rejecting the best
# signal on the board.
#
# The tiny-denominator case it guarded is already covered, and covered
# better, by ABSOLUTE floors that do not depend on a ratio:
# MIN_LIQUIDITY_CR (Rs 2cr), MIN_UNIVERSE_TURNOVER_RS (Rs 5cr) and
# config.MIN_TURNOVER_RS (Rs 2cr traded so far today). A stock cannot
# reach the ranker on a near-zero denominator at all.
#
# 1000 keeps a backstop against arithmetic that has gone truly wrong
# without refusing anything the market actually does.
MAX_SANE_VOLUME_RATIO = 1000.0

# ---- 09:30 IS PART OF TRADING, NOT PERMISSION TO TRADE. 23 Aug ----
#
#     "09:30 is part of trading its not ultimate to trade & this
#      statement ive said enough times ... whenever opportunity
#      arrives bot must identify , analyse & trade not avoid or wait
#      for some time. all rules are set by our understanding which no
#      one knows, follows."          -- operator, 23 August 2026
#
# The opening range is still built, still real, and still feeds the
# structural lane. What it is NOT is a blackout on looking.
#
# The blackout below it justified itself on measurement, not on the
# clock: "volume_x 1.23 on 28 seconds of tape is not a volume
# measurement". That was true, and it is now handled where the defect
# actually was -- core/volume_pace.py returns UNMEASURED until a stock
# has traded enough of its own normal day to divide by, so the early
# minutes disqualify themselves on evidence instead of on time.
#
# The -2.71% measured across five pre-09:30 picks on 5 August was
# taken through the broken instrument: those picks were made with a
# volume field that could not see the morning at all. It cannot be
# used to justify keeping a gate that the fix has made redundant.
#
# What still stops a bad early pick, unchanged: a published reason is
# mandatory (REQUIRE_A_REASON_ALWAYS), a long below its own open is
# refused, and unmeasured volume sorts last everywhere it is read.
OPENING_RANGE_ENDS = "09:30"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class Candidate(dict):
    """A ranked row. A dict so it serialises straight into the payload."""


def sector_moves(gainers_losers, movers=None):
    """{sector: average move}.

    ---- IT WAS SILENTLY EMPTY. 4 August 2026. ----
    Run against the real snapshot, every candidate came back with
    "sector unknown" -- so `excess` was None, and the gate written as

        if excess is not None and excess < MIN_EXCESS_PCT: refuse

    never fired once. The whole point of the ranker -- is this stock
    beating its own sector -- was being skipped, and the list was
    ordered on volume and mechanism alone. It looked like it worked.

    The sector_gainers/losers block is not always in the payload, but
    EVERY mover row carries its own sector. So the averages are
    computed from the movers themselves when the block is missing,
    which is also the more honest number: it is the average of the
    stocks actually moving, not of a precomputed basket.
    """
    out = {}
    # EVERY sector first (15 Sep 2026): the gainers/losers lists are the
    # top 10 each way and left the middle of the table with no move --
    # "sector unknown" and the excess gate skipped. They remain the
    # fallback for a payload that does not carry the full list.
    keys = (("sectors_all",) if (gainers_losers or {}).get("sectors_all")
            else ("sector_gainers", "sector_losers"))
    for key in keys:
        for row in (gainers_losers or {}).get(key) or []:
            name = row.get("sector")
            move = _num(row.get("avg_change_pct"))
            if name and move is not None:
                out[name] = move
    if out:
        return out

    buckets = {}
    for row in (movers or []):
        name = row.get("sector")
        move = _num(row.get("change_pct"))
        if not name or move is None:
            continue
        buckets.setdefault(name, []).append(move)
    for name, moves in buckets.items():
        # One stock is not a sector. With a single name the "excess"
        # would be zero by construction and the gate meaningless.
        if len(moves) >= MIN_SECTOR_PEERS:
            out[name] = _baseline(moves)
    return out


def _baseline(moves):
    """What the sector did, WITHOUT the outliers doing it.

    ==========================================================
        "MOREPEN LAB HIT CIRCUIT , BASF , STYRENIX, ALKYLAMINE ,
         got good results none of them were shown by bot"
                                -- operator, 4 August 2026
    ==========================================================

    BASF, STYRENIX and ALKYLAMINE are all CHEMICALS. On 4 August all
    three rose hard on their own results. The mean of that sector was
    8.5%, so every one of them failed "not beating its sector" -- each
    was measured against a baseline it had itself created. The ranker
    returned an empty list on the best day of the week:

        sector avg  -> {'CHEMICALS': 8.5}
        ranked      -> []

    The gate was not wrong. The baseline was. "What did this sector do
    today" means the DRIFT -- what a chemicals stock with no news of
    its own did. A handful of names moving on their own earnings are
    the signal being looked for; letting them set the bar they must
    clear is circular.

    The median is the fix, and it is the standard one: it is the middle
    stock, so a few big movers cannot drag it. With CHEMICALS at
    6/7/9/12, the mean is 8.5 and the median 8.0 -- and once the real
    sector's untouched names are in the list (most of a sector does
    NOT report on any given day), the median sits near zero where it
    belongs while the mean is still pulled up by the reporters.
    """
    ordered = sorted(moves)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 2)
    return round((ordered[middle - 1] + ordered[middle]) / 2.0, 2)


def market_move(gainers_losers, indices=None, movers=None):
    """One number for 'the market'. NIFTY when the feed has it, the
    average of every sector when it does not.

    Deliberately not breadth: breadth says how MANY are up, and this
    needs to know how FAR the average stock moved, so a stock's excess
    means something.
    """
    nifty = (indices or {}).get("nifty") or {}
    if nifty.get("available") and _num(nifty.get("pct")) is not None:
        return _num(nifty["pct"])
    sectors = sector_moves(gainers_losers, movers)
    if not sectors:
        return 0.0
    return round(sum(sectors.values()) / len(sectors), 2)


def volume_ratio(row, adv_cr, symbol=None, now=None):
    """Today's traded value against this stock's own normal day.

    None when we cannot say -- which is NOT the same as 'quiet', and
    must never be scored as if it were.

    ---- A PART DAY OVER A WHOLE DAY MEASURES THE CLOCK. 23 Aug ----

        "i want bot trade by finding opportunity as they arrives not
         by its own timing limitations"          -- operator

    adv_cr is a WHOLE day. Before the close the numerator is a part
    day, so this answered "what time is it", not "how busy is this
    stock". From each stock's own 1-minute history, the share of a
    normal day already traded:

        SBIN      09:30  7.0%    11:00 28.7%    15:00 85.1%
        RAILTEL   09:30 16.7%    11:00 46.7%    15:00 83.2%

    A stock at FIVE TIMES its normal pace at 09:30 read 0.5x and was
    refused as quiet, while a dull stock at 15:00 read 0.85x and
    outranked it. Seats are filled by SORTING ON THIS FIELD, so the
    hour was outranking the stock every single day -- and that, not
    patience, is most of why committing later measured better.

    With `symbol` and `now` the divisor becomes what THIS stock
    normally has traded BY THIS MINUTE (core/volume_pace.py, one
    curve per symbol -- never a pooled one). Without them the old
    whole-day answer stands, so every existing caller is unchanged.
    """
    volume = _num(row.get("volume"))
    price = _num(row.get("ltp"))
    if volume is None or price is None or not adv_cr:
        return None
    traded_cr = volume * price / 1e7

    # ---- A BAD DENOMINATOR LANDS AT THE TOP OF THE SORT. 23 Aug ----
    #
    #     "first are you sure about the stocks traded are having
    #      underlying reason in move"        -- operator, checking the
    #                                           picks and finding them
    #                                           reasonless
    #
    # 276 of 16,581 recorded multiples were over 50x. VINATIORGA read
    # 7,799x when its real day was 7.4x; MIDHANI 1,782x against a true
    # 14.7x; WAKEFIT 2,736x on a day it traded HALF its normal. The
    # numerator was right every time -- data/liquidity.json's adv_cr
    # was wrong for that symbol on that morning.
    #
    # 1.7% corrupt sounds survivable. It is not, because seats are
    # filled by SORTING ON THIS FIELD and taking the top three: the
    # broken values are picked preferentially, every single day. The
    # measured "+Rs 565/trade for volume ordering" was partly this.
    #
    # No real stock trades 50x its own normal value. Above that the
    # DENOMINATOR is broken, not the market, and the honest answer is
    # UNMEASURED -- which core/finders.TradeBrain already sorts last.
    # Returning a number here would be inventing one.
    # Pace first: today so far against this stock's own normal BY NOW.
    # Falls through to the whole-day answer when the stock has no
    # curve of its own -- inventing one from other stocks' days is
    # exactly the pooling his rule forbids.
    ratio = None
    if symbol is not None and now is not None:
        try:
            from core.volume_pace import pace_ratio
            ratio = pace_ratio(traded_cr, adv_cr, symbol, now)
        except Exception:                                   # noqa: BLE001
            ratio = None
    if ratio is None:
        ratio = traded_cr / adv_cr
    if ratio > MAX_SANE_VOLUME_RATIO:
        diagnostic(f"[VOLUME] {row.get('symbol')}: {ratio:,.0f}x is not a "
                   f"market event -- adv_cr {adv_cr} is wrong. Treating "
                   f"the multiple as unmeasured.")
        return None
    return round(ratio, 2)


def _at_circuit(row, side):
    """Locked, or so close to it that there is no trade left.

    MOREPEN went limit-up on results and stayed there. A BUY button on
    that row is a lie -- there is nothing to buy, only a queue to join.
    """
    room = (row.get("headroom_up_pct") if side == "BUY"
            else row.get("headroom_down_pct"))
    room = _num(room)
    if room is None:
        return None
    return room <= AT_CIRCUIT_PCT


def liveness(row):
    """Is this move STILL HAPPENING, or did it finish hours ago?

    ==========================================================
        "some stocks will rally in opening 1/2 mins & sit in top
         gainers no use of such movement in stock for trader"
                                -- operator, 4 August 2026
    ==========================================================

    The single most important thing this table gets wrong today. RBA
    closed +18.2% and sat at the top of the gainers list all day -- it
    made its high at 09:16 and did nothing for the next five hours.
    Ranking on day-change puts that stock first every time, and there
    was never a trade in it.

    Three readings, all from data already on the row:

        off_high_pct   how far it has given back from the day's high.
                       A stock 4% off its high is being sold.
        recent_pct     what it did in the last window. Near zero means
                       the move is over whatever the day says.
        above_vwap     are buyers still paying up.

    Returns one of:

        "alive"    still at or near its high, still moving
        "fading"   well off the high, or the recent window has died
        None       cannot say -- shown, never guessed at

    "fading" does not hide the stock. It demotes it and labels it, so
    he can see what a dying move looks like instead of being handed it
    as a fresh idea.
    """
    high = _num(row.get("day_high"))
    ltp = _num(row.get("ltp"))
    recent = _num(row.get("recent_pct"))
    vwap = _num(row.get("vwap"))
    up = (_num(row.get("change_pct")) or 0) >= 0

    off_high = None
    if high and ltp:
        # For a SHORT the "high" that matters is the day's low, so the
        # same arithmetic is run against whichever extreme the trade is
        # heading towards. Using the high for a faller would call every
        # short "fading" the moment it bounced a rupee.
        extreme = high if up else (_num(row.get("day_low")) or high)
        if extreme:
            off_high = abs((ltp - extreme) / extreme * 100.0)

    if off_high is None and recent is None:
        return None, None

    dead = False
    if off_high is not None and off_high > MAX_OFF_EXTREME_PCT:
        dead = True

    # ---- MOVING DOWN IS STILL MOVING. 3 September 2026. ----
    #
    #     "i need to see the stocks which are actively moving not
    #      already moved stocks and struck at upper levels"
    #     "my real goal is to get max profits"
    #
    # This was abs(recent) < MIN_RECENT_PCT, so a stock sliding 0.28%
    # in the recent window passed the test -- it was "moving", just
    # the wrong way. Live on his board at 15:20 today, all reading
    # ALIVE while drifting down:
    #
    #     RAYMOND    off_high 0.84   recent -0.28
    #     RBLBANK    off_high 0.60   recent -0.36
    #     JYOTICNC   off_high 1.58   recent -0.65
    #     KIRIINDUS  off_high 2.22   recent -0.45
    #
    # He buys long. A long whose recent window is NEGATIVE is not a
    # move he is joining, it is one he is catching. The direction has
    # to agree with the side.
    #
    # Flat still counts as dead, which is what the old test caught and
    # this keeps: a stock going nowhere is not an opportunity either.
    if recent is not None:
        wrong_way = (up and recent < 0) or ((not up) and recent > 0)
        at_high = off_high is not None and off_high <= COILING_AT_HIGH_PCT
        if wrong_way:
            dead = True                      # going the wrong way
        elif abs(recent) < MIN_RECENT_PCT and not at_high:
            dead = True                      # going nowhere, and not at its high
    if vwap and ltp:
        # Below VWAP on a long means the average buyer today is under
        # water. That is not a stock to be joining.
        if (up and ltp < vwap) or (not up and ltp > vwap):
            dead = True

    return ("fading" if dead else "alive"), (
        round(off_high, 2) if off_high is not None else None)



def _best_of_each_sector(rows):
    """Interleave by sector: every sector's best, then every second.

    ---- WHY NOT SIMPLY CAP AT N PER SECTOR. 19 August 2026. ----
    A cap throws away a real setup on a day when one sector is the
    whole story. This reorders instead, so the leaders come first and
    nothing is lost. The book's own limits then decide how many are
    taken, which is where that decision has always belonged.

    Order WITHIN a sector is preserved exactly as it arrived, so the
    liveness-then-score rule above still holds inside each group.
    A row with no sector is its own group -- an unknown sector must
    not silently become one big bucket that gets rationed hardest.
    """
    groups = {}
    order = []
    for index, row in enumerate(rows or []):
        sector = str((row or {}).get("sector") or "").strip().upper()
        key = sector or f"__unknown_{index}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)

    out = []
    depth = 0
    while True:
        added = False
        for key in order:
            group = groups[key]
            if depth < len(group):
                out.append(group[depth])
                added = True
        if not added:
            return out
        depth += 1

def rank(movers, gainers_losers=None, indices=None, mechanism_of=None,
         adv_of=None, blocked=None, held=None, mtf_of=None,
         top=RANKED_LIST_SIZE,
         now=None, open_of=None):
    """Everything moving right now, best first, with the reason.

    mechanism_of(symbol) -> {"text": ..., "weight": 0..1} or None
    adv_of(symbol)       -> average daily traded value in crore
    blocked              -> symbols the risk layer has already refused
    held                 -> symbols already in the book
    now                  -> the clock. Used to measure volume against
                            this stock's own pace by this minute
                            (core/volume_pace.py). It is not a gate:
                            an opportunity is named whenever it can be
                            evidenced. None skips the pace lookup.
    open_of(symbol)      -> today's opening price. A long below its own
                            open is a falling stock whatever yesterday
                            did. None skips the check.

    Returns {"rows": [...], "market_pct": x, "note": ...}. Never raises.
    """
    rows = list(movers or [])
    if not rows:
        return {"rows": [], "market_pct": 0.0, "note": "nothing is moving"}

    sectors = sector_moves(gainers_losers, rows)
    market = market_move(gainers_losers, indices, rows)
    blocked = {str(s).upper() for s in (blocked or [])}
    held = {str(s).upper() for s in (held or [])}
    adv_of = adv_of or (lambda s: 0.0)
    mechanism_of = mechanism_of or (lambda s: None)

    out, rejected = [], {}
    # ---- WHICH STOCK, NOT JUST HOW MANY. 11 August 2026. ----
    # refuse() counted reasons and threw the SYMBOL away. So the
    # dashboard could say "not moving enough x91" and never say which
    # 91. On 11 August I built the board's refusal rows out of the
    # counts dict, assumed it was {symbol: reason}, and put rows on his
    # screen named "too thin to trade our size" with a volume of 65.
    #
    #     "not even one thing is as i wanted"
    #
    # The count is still useful -- it is the whole shape of a day. But
    # the operator cannot argue with a number. He argues with a stock.
    refused_by_symbol = {}

    def refuse(symbol, why):
        rejected[why] = rejected.get(why, 0) + 1
        name = str(symbol or "").upper()
        if name:
            refused_by_symbol[name] = why

    # ---- NO EVENT, NO EVALUATION. 29 August 2026. ----
    #
    #     "the problem is for non events / no volume stocks are being
    #      processed continously ?"
    #     "if 100 stocks were there at morning & by 11 5 stocks got
    #      news . then bot must include those stocks too"
    #                                    -- operator, 29 August 2026
    #
    # On 24 August the bot recorded 355,089 refusals to reach three
    # decisions. The largest single reason, 164,988 of them, was "no
    # event behind it" -- the same reasonless stocks re-refused on
    # every one of ~1,400 cycles. 31,924 more were "under the Rs 50
    # floor", which is a permanent property of a stock being
    # rediscovered twenty-five times a day.
    #
    # REQUIRE_A_REASON_ALWAYS means a stock without a published reason
    # can never be taken. Walking it through nine gates to arrive
    # there is work whose answer is known before it starts.
    #
    # The market context above is computed from the FULL mover list
    # and is untouched -- sector strength and market breadth need
    # every stock, including the ones that are not candidates.
    #
    # A stock is NOT dropped for the day: mechanism_of() is asked
    # fresh each cycle, so news arriving at 11:00 puts a stock into
    # the evaluated set from 11:00 onward. That is his 100-at-the-open
    # plus 5-at-eleven, and it costs nothing to support because the
    # reason lookup is what decides membership.
    reason_cache = {}

    def _reason_for(symbol):
        if symbol not in reason_cache:
            try:
                reason_cache[symbol] = mechanism_of(symbol)
            except Exception:                              # noqa: BLE001
                reason_cache[symbol] = None
        return reason_cache[symbol]

    if REQUIRE_A_REASON_ALWAYS:
        candidates_before = rows
        before = len(rows)
        rows = [r for r in rows
                if _reason_for(str(r.get("symbol") or "").upper())]
        skipped = before - len(rows)
        if skipped:
            # ONE aggregate line, not one refusal per gate per cycle.
            rejected["no event -- not evaluated"] = skipped
            # But the SYMBOL is still remembered, so "why was X not
            # named?" keeps an answer. tests/test_live_tab_is_not_blank
            # exists for that question -- the ranker used to count
            # reasons and forget the stock. Writing a dict entry is
            # not the cost being avoided here; walking nine gates,
            # computing a volume ratio and sizing a plan is.
            named = {str(r.get("symbol") or "").upper() for r in rows}
            for row in candidates_before:
                name = str(row.get("symbol") or "").upper()
                if name and name not in named:
                    refused_by_symbol[name] = ("no event behind it -- "
                                               "the tape is not a reason")

    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue

        move = _num(row.get("change_pct"))
        if move is None or abs(move) < MIN_MOVE_PCT:
            refuse(symbol, "not moving enough")
            continue

        side = "BUY" if move > 0 else "SELL"

        # ---- gates. these REFUSE, they do not subtract ----
        if symbol in blocked:
            refuse(symbol, "blocked upstream")
            continue

        # ---- THE PRICE FLOOR BELONGS HERE. 11 August 2026. ----
        #
        #     "why MSUMI & SEPC = 30 times bot tried to buy?"
        #
        # It was enforced only in Engine._enter, the very last line of
        # the order path. This module had never heard of it. So on
        # 5 August the ranker scored SEPC at Rs 6.29 nineteen times and
        # MSUMI at Rs 41.07 eleven times, auto_entry cleared all thirty,
        # and the order gate refused every one -- then nothing recorded
        # that it had happened, so five minutes later it did it again.
        #
        # Thirty wasted candidate slots on one day for two stocks that
        # could never be bought. A rule enforced at the bottom of a
        # funnel does not stop work, it only stops orders.
        price_now = _num(row.get("ltp")) or _num(row.get("price"))
        if price_now is not None and price_now < MIN_TRADABLE_PRICE_RS:
            refuse(symbol, f"under the Rs {MIN_TRADABLE_PRICE_RS:.0f} "
                           f"floor -- never tradeable")
            continue

        # ---- A GAP IS NOT MOMENTUM. 5 August 2026. ----
        #
        #     "why it is taking trades in falling stock? DEEPAKNTR even
        #      i took this without looking charts ; ICICIGI SAME STORY"
        #
        # `move` above is measured against YESTERDAY'S CLOSE, and that
        # is the only thing this ranker ever looked at. A stock can gap
        # up 5% at the open and bleed all day, and it reads as "up" the
        # whole way down.
        #
        # ICICIGI, 5 August: previous close 1644.80, opened 1732.20,
        # then fell nine minutes in a row. At 09:23 the bot recorded
        # `change_pct 2.68%, state=alive` and called it a BUY -- while
        # the chart showed an unbroken staircase down. He read it in one
        # glance. The bot had no notion of the open at all.
        #
        # Of that day's nineteen sized entries exactly two were below
        # their own open: DEEPAKNTR and ICICIGI. Both lost. He named
        # both, unprompted, from memory.
        #
        # Against the OPEN, not the previous close, and only for the
        # direction being proposed: a long must be above its open, a
        # short below it.
        if open_of is not None:
            try:
                day_open = _num(open_of(symbol))
            except Exception:                              # noqa: BLE001
                day_open = None
            price = _num(row.get("ltp")) or _num(row.get("price"))
            if day_open and price:
                if side == "BUY" and price < day_open:
                    refuse(symbol, "below its own open -- falling today")
                    continue
                if side == "SELL" and price > day_open:
                    refuse(symbol, "above its own open -- rising today")
                    continue

        adv = _num(adv_of(symbol)) or 0.0
        if adv < MIN_LIQUIDITY_CR:
            # ---- A SIZE FILTER. NOT A "NEVER SEEN IT" FILTER. ----
            #      Corrected 4 August 2026.
            #
            # I first called this "the YASHO gate" and justified it by
            # saying the bot had never seen YASHO trade. That was my
            # broken data source talking, not a fact about the stock:
            # core/liquidity.py was reading a store frozen on 31 July.
            # Against NSE's own bhavcopy YASHO averages Rs 61 crore a
            # day and did Rs 175 crore the session before he traded it.
            # It is perfectly liquid, and 191 of 954 names that looked
            # unknown were all data rot -- the real count is zero.
            #
            # The gate still earns its place, but for the honest
            # reason: at Rs 1.2 lakh of MTF buying power a stock doing
            # Rs 3 crore a day means the operator IS the volume, and
            # getting out costs more than getting in.
            #
            # ---- BUT ADV IS LAST MONTH. THE MOVE IS TODAY. ----
            #      2 September 2026.
            #
            #     "too thin to trade our size is not correct that too
            #      on its best moving day"          -- the operator
            #
            # adv_of() is a 20-session average. On the one day a stock
            # is worth trading it is not trading its average -- SOTL
            # did 75x its normal today against a Rs 17 crore ADV, so
            # the money actually in the book was orders of magnitude
            # past what the average implied. Refusing on the average
            # refuses precisely the days the gate was never aimed at.
            #
            # So the gate now asks the question it always meant to ask
            # -- is there enough money in this stock TODAY to get our
            # size in and back out -- and today's own turnover answers
            # it whenever it is known. The average is the fallback,
            # not the verdict. A stock thin on BOTH counts is still
            # refused, which is the case the gate was built for.
            #
            # ONLY WHEN THE AVERAGE IS KNOWN. adv 0 does not mean a
            # thin stock, it means NO DATA -- the exact symptom of the
            # frozen liquidity store this gate's own comment describes
            # above. A stock we cannot measure stays refused, because
            # a store broken enough to lose the average is not a store
            # to trust the day's volume from either. That refusal is
            # test_a_stock_with_no_measurement_is_never_a_candidate,
            # and letting today's turnover override it was a bug I put
            # in while fixing the surge-day one.
            traded_cr = None
            if adv > 0:
                _v, _p = _num(row.get("volume")), _num(row.get("ltp"))
                if _v and _p:
                    traded_cr = _v * _p / 1e7
            if not traded_cr or traded_cr < MIN_LIQUIDITY_CR:
                refuse(symbol, "too thin to trade our size")
                continue

        # VOLUME IS READ HERE, NOT 60 LINES DOWN. It used to be
        # computed after the mechanism check, which was fine while a
        # missing reason simply refused the stock. Now the tape can
        # qualify a stock on its own, and the tape means volume -- so
        # the number has to exist before the question is asked.
        vratio = volume_ratio(row, adv, symbol=symbol, now=now)

        mech = _reason_for(symbol)
        text = str((mech or {}).get("text") or "").strip()
        if not mech or not text:
            # ---- FOLLOW THE MONEY. THE REASON BACKS IT. ----
            #      6 August 2026.
            #
            #     "my concern is not profit & loss at all. the only
            #      concern is bot must know where the money is moving ?
            #      to find that it must check with top gainers & orb
            #      breakout stocks . details of them will get in
            #      telegram channels"
            #
            # This was a veto, and on 6 August it refused 494 of the
            # 605 stocks that actually moved. Every one of these was
            # thrown away:
            #
            #     INDOMIM     +8.58%   Rs 1,730 Cr   closed ON its high
            #     NAVINFLUOR  +8.58%   Rs   119 Cr   1.7% off its high
            #     GVT&D       +7.11%   Rs   377 Cr
            #     MAZDOCK     +6.32%   Rs   198 Cr   govt defence news
            #
            # The ranker named nothing all day and the operator got no
            # list at all.
            #
            # The order was backwards. Money moves first and the
            # channels explain it afterwards -- sometimes hours later,
            # sometimes never. MAZDOCK moved the whole defence sector
            # on government news the bot has no sentence for.
            #
            # So the tape leads. A stock carrying REAL money -- volume
            # well above its own normal, not just a price that drifted
            # -- qualifies on its own, and is marked as unexplained so
            # it can never be mistaken for a stock with a written
            # reason behind it.
            #
            # This is NOT the old "buy anything that moves". Price
            # alone still proves nothing: without volume confirming
            # that money actually changed hands, the refusal stands.
            # ---- THE TAPE IS NOT A REASON. 21 August 2026 ----
            # rules.REQUIRE_A_REASON_ALWAYS. NCC, 8.54x normal volume
            # and no event of any kind, was bought twice on 21 August
            # through the lane below. His instruction has always been
            # "an event or real opportunity ... NEVER in to random
            # stocks", and volume says money moved, not why.
            if REQUIRE_A_REASON_ALWAYS:
                refuse(symbol, "no event behind it -- the tape is not "
                               "a reason")
                continue
            if vratio is None or vratio < UNEXPLAINED_MIN_VOLUME_RATIO:
                refuse(symbol, "no reason found, and no volume behind it")
                continue
            mech = {
                "text": (f"unexplained -- {vratio:.1f}x its normal volume, "
                         f"no published reason yet"),
                "weight": UNEXPLAINED_WEIGHT,
                "direction": None,
                "source": "the tape",
                "unexplained": True,
            }
            text = mech["text"]

        # ---- A LOOKUP RESULT IS NOT A MECHANISM ----
        # core/news_impact.py writes "matched on: INDGN" when a story
        # named a company and produced no reasoning. That is the
        # matcher reporting its own work, and on the first real run it
        # sailed through this gate and ranked sixth.
        if not is_a_reason(text):
            refuse(symbol, "reason is a lookup, not a mechanism")
            continue

        # ---- THE REASON MUST POINT THE SAME WAY AS THE TRADE ----
        #      4 August 2026.
        #
        # The first real run ranked MUTHOOTFIN as a SELL and attached
        # "Strong Q1 FY27 AUM and PAT growth signals..." to it. A
        # bullish mechanism justifying a short is not a near miss; it
        # is the bot telling the operator a reason that argues against
        # the trade it is proposing.
        #
        # The stock was down 7.3% on the day, so the TAPE said sell and
        # the READER said buy. That disagreement is exactly the MDR
        # situation, and the rule settled then still holds: where the
        # evidence points two ways, the bot has no view and offers no
        # trade.
        direction = str((mech or {}).get("direction") or "").upper()
        if direction in ("POSITIVE", "NEGATIVE"):
            wants = "POSITIVE" if side == "BUY" else "NEGATIVE"
            if direction != wants:
                # ---- AN OLD NOTE DOES NOT OVERRULE TODAY'S PRICE. ----
                #      15 September 2026.
                #
                #     "old negative reason must not block a rising stock."
                #                                         -- the operator
                #
                # TATAINVEST rose from 709.55 to 749.40 on 15 Sep and was
                # refused here 2,017 times. The only reason the bot held
                # was Earnings 360's note of 4 AUGUST -- "profit is just
                # mark-to-market gains", NEGATIVE. OPTIEMUS, 2,005 times,
                # on its own 4 August note. A six-week-old verdict is not
                # what the market is doing today.
                #
                # So only a contradicting reason SAID TODAY refuses. An
                # older one stays on the row as what it is -- an old note,
                # labelled with its date -- and stops pointing a direction.
                # No date at all (the pre-open gapper card is today's by
                # construction) is treated as today, so a down gap still
                # refuses a long.
                said = _said_on(mech.get("at"))
                today = (now.date() if isinstance(now, datetime)
                         else datetime.now().date())
                if said is None or said >= today:
                    refuse(symbol, "reason contradicts the move")
                    continue
                mech = dict(mech)
                mech["direction"] = None
                mech["old_contradiction"] = direction
                mech["text"] = (f"old {direction.lower()} note "
                                f"({said.strftime('%d %b')}), not today's -- "
                                f"{text}")
                text = mech["text"]

        # ---- the four measurements ----
        sector_name = row.get("sector")
        sector_move = sectors.get(sector_name)
        # Excess is signed against the DIRECTION of the trade: a short
        # candidate outperforms by falling faster than its sector.
        if sector_move is None:
            excess = None
        else:
            excess = (move - sector_move) if side == "BUY" \
                else (sector_move - move)

        if excess is not None and excess < MIN_EXCESS_PCT:
            refuse(symbol, "not beating its sector")
            continue

        lead = None
        if sector_move is not None:
            lead = (sector_move - market) if side == "BUY" \
                else (market - sector_move)

        if vratio is not None and vratio < MIN_VOLUME_RATIO:
            refuse(symbol, "no volume behind it")
            continue

        recent = _num(row.get("recent_pct"))

        # ---- CAN HE BUY IT THE WAY HE BUYS? ----
        #      "only trade in best set of stocks in MTF"
        #
        # The whole book runs on MTF. Dhan does not margin every scrip,
        # and until now the ranker never asked -- so it could hand him
        # a perfect-looking name he could only buy with cash, and he
        # would find out at the click.
        #
        # This REFUSES rather than penalises, same as every other gate:
        # a stock he cannot trade his way is not a better or worse
        # candidate, it is not a candidate.
        #
        # No mtf_of supplied -- paper mode, backtests, the preview --
        # means the question was not asked, and an unasked question
        # must never read as a failed one.
        # ---- CASH IS NOT A REFUSAL. 2 September 2026. ----
        #
        #     "no MTF doesn't meaning to be blocked. bot can use the
        #      available capital to buy"            -- the operator
        #
        # This refused, and it cost the best move of the day. TBZ was
        # turned away 1,256 times between 08:57 and the close for
        # "no MTF -- cash only" and closed +20.0% on 23.4x its normal
        # volume -- the largest gain on the whole board. SAKAR, +11.9%,
        # went the same way.
        #
        # The refusal assumed no leverage means no trade. It does not:
        # there was Rs 4,02,064 of his own capital free all day, and
        # core/mtf_margin.py already sizes a non-MTF name on cash
        # (margin_pct 1.0, "Rs 1 lakh buys Rs 1 lakh"). The order was
        # placeable the whole time. The ranker simply never offered it.
        #
        # So leverage is now a PROPERTY of the candidate, not a gate on
        # it. The row carries cash_only so the board can say plainly
        # what buying it will cost, and the sizing layer -- which has
        # always handled this correctly -- does the rest.
        mtf = mtf_of(symbol, row) if mtf_of else None
        cash_only = bool(mtf is not None and not mtf.get("eligible"))

        # ---- IS THE MOVE STILL HAPPENING? ----
        #      "some stocks will rally in opening 1/2 mins & sit in top
        #       gainers no use of such movement in stock for trader"
        state, off_extreme = liveness(row)

        # ---- the score ----
        score = 0.0
        score += W_EXCESS_SECTOR * (excess or 0.0)
        score += W_SECTOR_LEAD * max(lead or 0.0, 0.0)
        if vratio is not None:
            # ---- 71x AND 5x SCORED THE SAME. 7 August 2026. ----
            #
            # The cap at 5.0 was there so a 40x reading could not swamp
            # every other input, and that part was right. But it also
            # made every stock above 5x identical, and on 6 August the
            # whole unexplained row tied at 13.9 and came out in
            # ALPHABETICAL order:
            #
            #     GMMPFAUDLR  71.2x        BLUESTARCO   5.0x
            #     COHANCE     20.5x        ADVANCE      5.9x
            #
            # 71x its own normal volume is not the same event as 5x,
            # and the ranker could not tell them apart -- which is the
            # one job it exists to do.
            #
            # So: unchanged up to 5x, then a LOG bonus above it. 20x
            # earns +0.6 over 5x, 71x earns +1.15. Real separation,
            # and a 40x reading still cannot outweigh sector leadership
            # and a written reason put together.
            score += W_VOLUME * (min(vratio, 5.0)
                                 + (math.log10(vratio / 5.0)
                                    if vratio > 5.0 else 0.0))
        score += W_MECHANISM * float(mech.get("weight") or 0.5) * 2.0
        if recent is not None:
            # Still moving NOW. A stock that gapped at 09:15 and has not
            # ticked since is not a rally, it is a memory.
            score += W_PERSISTENCE * (recent if side == "BUY" else -recent)

        # A finished move ranks below every live one. Not deleted --
        # RBA closing +18.2% with its high at 09:16 is worth SEEING,
        # labelled, so he learns the shape. It is never worth being
        # handed as today's best idea.
        if state == "fading":
            score -= FADING_PENALTY

        # ---- THE SAME EVENT, THE OPPOSITE TRANSMISSION. 19 Aug 2026 ----
        #
        # His own framework: crude rises, airline margins fall and
        # airline stocks sell off, while oil producers' realisation
        # rises and those stocks are bought. One event, two mechanisms,
        # opposite signs -- and this scorer treated a cable maker and a
        # copper miner identically on a copper day.
        #
        # Measured over a year before it was armed. Every session an
        # instrument moved 1.5%+, the NEXT Indian session's move for
        # every name carrying it, minus that session's market median,
        # signed by the commodity's direction:
        #
        #     COPPER      producers +0.210  consumers +0.116
        #     CRUDE OIL   producers +0.115  consumers +0.000
        #     GOLD        producers +1.309  consumers +0.366
        #     SILVER      producers +0.261  consumers +0.085
        #     NATURAL GAS producers +0.006  consumers -0.031
        #
        # Five out of five in the same direction. The magnitude is
        # SMALL -- around a tenth of a percent on the well-sampled
        # series -- so the tilt is small too, bounded [0.90, 1.10] by
        # core/sector_map.py. It reorders a close call. It cannot make
        # a trade out of nothing, and it is off in one line.
        tilt, tilt_why = 1.0, None
        if RANK_BY_COMMODITY_POLARITY:
            try:
                from core import sector_map as _sector_map
                tilt, tilt_why = _sector_map.commodity_tilt(symbol)
            except Exception as exc:                       # noqa: BLE001
                diagnostic(f"[RANK] commodity tilt skipped "
                           f"({type(exc).__name__}).")
                tilt, tilt_why = 1.0, None
        if tilt != 1.0:
            score *= tilt

        out.append(Candidate({
            "symbol": symbol,
            "action": side,
            "score": round(score, 2),
            # Shown so a ranking he disagrees with can be taken apart.
            "commodity_tilt": None if tilt == 1.0 else round(tilt, 3),
            "commodity_tilt_why": tilt_why,
            "change_pct": move,

            # Dhan quotes no MTF margin on this one, so it is bought
            # with his own cash at 1x. A fact about the trade, not a
            # reason to withhold it -- see the note at the mtf check.
            "cash_only": cash_only,

            # ---- THE PRICES HE ASKED FOR. 9 August 2026. ----
            #
            #     "still the CMP, Volume, Open, High, Low. is not
            #      showed ?"
            #
            # They were never missing from the screen -- they were
            # missing from the PAYLOAD. This row carried the score, the
            # sector, the volume MULTIPLE and the reason, but not one
            # actual price, so the dashboard had nothing to print even
            # if it wanted to. It could show him why the bot liked a
            # stock and not what the stock cost.
            #
            # Straight off the same mover row every other field is read
            # from, so they cannot disagree with the tape.
            "ltp": _num(row.get("ltp")),
            "open": _num(row.get("day_open") or row.get("open")),
            "high": _num(row.get("day_high") or row.get("high")),
            "low": _num(row.get("day_low") or row.get("low")),
            "volume": _num(row.get("volume")),
            "turnover_cr": _num(row.get("turnover_cr")),
            "prev_close": _num(row.get("prev_close")),
            "recent_pct": recent,
            "sector": sector_name,
            "sector_pct": sector_move,
            "excess_pct": None if excess is None else round(excess, 2),
            "sector_lead_pct": None if lead is None else round(lead, 2),
            "volume_x": vratio,
            "adv_cr": round(adv, 1),
            # Is the move alive, and can he trade it his way. Both are
            # drawn on the row, so both have to reach the payload.
            "state": state,
            "off_extreme_pct": off_extreme,
            # ROOM LEFT BEFORE THE CIRCUIT. 4 August 2026 --
            #   "why bot or trader needs to wait till Circuit closing"
            # At the circuit there are no sellers and the printed
            # percentage understates the move. Headroom says whether
            # there is still a trade or only a queue.
            "headroom_pct": (row.get("headroom_up_pct") if side == "BUY"
                             else row.get("headroom_down_pct")),
            "at_circuit": _at_circuit(row, side),
            "mtf_eligible": None if mtf is None else bool(mtf.get("eligible")),
            "mtf_leverage": None if mtf is None else mtf.get("leverage"),
            "mechanism": mech.get("text"),
            "mechanism_weight": mech.get("weight"),
            "held": symbol in held,
            "why": explain(symbol, side, move, sector_name, sector_move,
                           excess, vratio, mech.get("text")),
        }))

    # ---- A FINISHED MOVE CAN NEVER LEAD. 4 August 2026. ----
    #
    # FADING_PENALTY alone was not enough and could not be. Tested
    # against the real case -- RBA +18.2%, high made at 09:16, 5% off
    # it -- an eight-point penalty still left it FIRST, because an
    # 18-point day move drives an excess score far larger than any
    # constant I could pick. Raising the number until RBA lost would
    # have been tuning to one example, and the next 25% mover would
    # walk straight past it again.
    #
    # So it is structural, not numeric: liveness sorts BEFORE score.
    # Every stock still moving outranks every stock that has stopped,
    # whatever the day's percentage says. The penalty stays, to order
    # the fading ones sensibly among themselves.
    #
    # Unknown liveness (no high, no recent window) sorts with the live
    # ones. We did not measure it, so we must not demote it -- that is
    # the same "unasked is not failed" rule the MTF gate follows.
    # ---- WHEN DID EACH MOVE BEGIN. 6 September 2026. ----
    #
    # Watches only. core/move_clock.py decides nothing and no gate
    # imports it -- it exists because Friday's book could not answer
    # "how late were we", and reconstructing one day by hand took an
    # afternoon. Wrapped because bookkeeping must never stop a cycle.
    try:
        from core import move_clock
        move_clock.note(out, now=now)
    except Exception:                                      # noqa: BLE001
        pass

    out.sort(key=lambda c: (c.get("state") == "fading", -c["score"]))

    # ---- FIVE CHEMICALS NAMES IS ONE BET, NOT FIVE. 19 Aug 2026 ----
    #
    #     "which events will create opportunity to which sector stocks
    #      & trade in top ranker of that sector"
    #
    # An event does not happen to a stock, it happens to a SECTOR, and
    # the sector then hands the same reason to every name in it. This
    # list had no per-sector limit at all, so a copper headline or a
    # chemicals rally could put four or five correlated names on the
    # board -- and the book, sized for three positions, would fill
    # with one idea wearing four tickers. When that idea is wrong,
    # every seat is wrong together.
    #
    # So: the best name per sector, then the next best, and so on.
    # Nothing is deleted -- the also-rans keep their place BELOW every
    # sector's leader, so a day when one sector genuinely owns the
    # tape still surfaces its second name, just not above another
    # sector's first.
    out = _best_of_each_sector(out)

    if rejected:
        when_it_changes("rank-refused", "[RANK] refused: " + ", ".join(
            f"{k} x{v}" for k, v in sorted(rejected.items())))

    return {"rows": out[:top],
            "market_pct": market,
            "considered": len(rows),
            "kept": len(out),
            # HOW MANY SETUPS EXIST PER DAY, AND WHAT TURNED THE REST
            # AWAY. 4 August 2026 -- the operator's plan is ten
            # positions a day at Rs 2 lakh each. Whether ten A-grade
            # setups exist on an ordinary day is the number that plan
            # lives or dies on, and it was being computed here and
            # thrown away: rejected never left this function.
            "refusals": dict(rejected),
            # {SYMBOL: why}. Named separately from `refusals` on purpose:
            # that key has meant {reason: count} since 4 August and
            # anything already reading it must keep working.
            "refused_by_symbol": dict(refused_by_symbol),
            "note": "" if out else "nothing cleared the gates"}


def explain(symbol, side, move, sector, sector_move, excess, vratio, mech):
    """One sentence a human can act on.

        "up 4.2% while IT is up 0.8% -- 5.1x its normal volume --
         order win announced at 09:22"

    Deliberately plain. The operator's standing rule is that the screen
    shows the stock, the direction and the reason; the arithmetic that
    produced the ranking stays in the background.
    """
    bits = []
    bits.append(("up" if move > 0 else "down") + f" {abs(move):.1f}%")
    if sector and sector_move is not None:
        way = "up" if sector_move >= 0 else "down"
        bits.append(f"while {sector.title()} is {way} {abs(sector_move):.1f}%")
    elif excess is None:
        bits.append("sector unknown")
    if vratio is not None:
        bits.append(f"{vratio:.1f}x its normal volume")
    line = ", ".join(bits)
    return (line + " — " + str(mech)[:110]) if mech else line


def should_swap(current, challenger, margin=SWAP_MARGIN):
    """Is the challenger enough better to be worth the round trip?

    Without a margin the ranking churns: two candidates within a
    rounding error of each other trade places on every clock tick and
    the account pays brokerage to stand still. Charges are real and the
    operator has watched them eat a day before.
    """
    if current is None:
        return True
    if challenger is None:
        return False
    return (challenger.get("score", 0) - current.get("score", 0)) >= margin
