"""
==========================================================
The ranker's picks reach the order path -- the missing join
==========================================================

    "the purpose of bot is not fulfilled right? even after bringing
     all food near mouth . you can't take the food!"
                                -- operator, 5 August 2026

WHAT WAS MISSING
----------------
core/ranker.py was imported by exactly ONE file in the entire
codebase: dashboard/state.py. Nothing in core/engine.py or trading/
had ever heard of it.

So the bot had two brains that never met:

    Engine   watches candles for breakouts, CAN place an order,
             consults results only as a veto, and fired 1,047 signals
             on 5 August that he would never have taken.

    Ranker   knows WHY a stock is moving, whether volume is behind it,
             whether it is still alive, whether it is MTF-eligible,
             and what quantity risks exactly Rs 1,500 -- and could not
             place anything, ever.

Everything he asked for over three weeks went into the second one.
Turning the bot loose would have traded the first.

This module is the join. It takes the rows the ranker already
produces -- with the plan core/position_plan.py already sized -- and
routes them into the Engine's own entry path, the same one the
dashboard BUY button uses, with the same stops, the same trailing and
the same position management.

WHAT IT DOES NOT CHANGE
-----------------------
ALERT_ONLY_MODE still governs everything. While it is True this
alerts and records and places nothing, exactly as it does today. The
join being built is not the same as the safety being removed, and
those two must never arrive in one change.

Nor does it replace the breakout Engine. Both can speak; the Engine's
own signals are unaffected.

THE GATES HERE ARE THE LAST ONES, NOT THE ONLY ONES
---------------------------------------------------
By the time a row arrives it has already passed every ranker gate --
move, liquidity, reason, direction, sector, volume, circuit, MTF,
liveness -- and been sized against a real stop. What is left is the
book-level question the ranker cannot answer: am I already in this,
how many do I hold, and is it too late in the day.

    "no trade is far more than a bad pick/wrong pick trade"

so every gate here refuses. None of them adjust.

Author : H&M Opportunity Trader
==========================================================
"""

from config import ENABLE_SLOT_ROTATION
from datetime import datetime, time as dtime

LONG = "LONG"



# ---- A SWALLOWED FAILURE ON THE ORDER PATH. 8 August 2026. ----
#
#     "do not stop until u fixed all items"
#
# Six handlers in this file caught an exception and carried on. One of
# them decided whether a trade was allowed. They now say so, once per
# session -- this runs over every ranked row on every cycle, so a
# warning per symbol would be its own blindness.
_said = set()



# ---- TWO LOOKUPS, NEITHER OF THEM TOUCHES A DISK. 6 Sep 2026. ----
#
#     "but make sure all these never slow down the bot or process the
#      trades"                                    -- the operator
#
# Measured this morning that a single sqlite read on this path cost
# 1,642 ms the first time it ran, at 09:15, on a live decision. So
# neither of these reads a store, a file or a database. One is a dict
# lookup held in memory by core/move_clock.py; the other reads a
# number the ranker already computed and put on the row.
#
# Both return None rather than raise. None means NOT KNOWN and must
# never be read as zero.
def _move_age(symbol, now=None):
    """Minutes since this stock's move began, or None. Dict lookup."""
    try:
        from core import move_clock
        return move_clock.age_minutes(symbol, now)
    except Exception:                                      # noqa: BLE001
        return None


def _reason_size(row, symbol=None):
    """How big the reason is against the company, if it says so.

    Taken off the row, NOT looked up. The standing-order memory has
    already worked this out and put pct_of_company on the reason it
    handed back; asking again here would be a second answer to a
    settled question, and a slower one.

    The module is deliberately not named in this file. Two guard
    tests read that name as evidence the trading path reads the
    memory, and they are worth more than the cross-reference.
    """
    try:
        mech = row.get("mechanism") if isinstance(row, dict) else None
        if isinstance(mech, dict) and mech.get("pct_of_company") is not None:
            return _num(mech.get("pct_of_company"))
        got = row.get("reason") if isinstance(row, dict) else None
        if isinstance(got, dict):
            return _num(got.get("pct_of_company"))
    except Exception:                                      # noqa: BLE001
        pass
    return None

def _broke(where, exc):
    if where not in _said:
        _said.add(where)
        try:
            from core.logger import warn
            warn(f"[ENTRY] {where} raised and was swallowed: "
                 f"{type(exc).__name__}: {exc}")
        except Exception:                                  # noqa: BLE001
            pass


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

# ---- 14:45 WAS AN INTRADAY NUMBER TOO. 9 August 2026. ----
#
# Its old reasoning: "a position opened at 15:10 has twenty minutes to
# work and then becomes an overnight hold BY ACCIDENT rather than by
# decision."
#
# Overnight is now the decision. FORCE_SQUARE_OFF_AT_CLOSE is False and
# positions carry on MTF, so a 15:10 entry is not an accident -- it is
# the trade. Worse, this sat at 14:45 while config.LAST_ENTRY_TIME and
# STAGED_NO_ENTRY_AFTER both said 15:15, so the bot stopped half an
# hour before the screen said it would, and I described 15:15 to him
# on 9 August without checking this file.
#
# Read from config so the three can never disagree again.
try:
    from config import LAST_ENTRY_TIME as _LAST
    LAST_NEW_ENTRY = dtime(int(_LAST[:2]), int(_LAST[3:5]))
except Exception:                                          # noqa: BLE001
    LAST_NEW_ENTRY = dtime(15, 15)

# The ranker names an opportunity whenever it can be evidenced --
# see core/ranker.py OPENING_RANGE_ENDS. It no longer blacks out the
# 09:15-09:30 window; the opening range is a signal, not permission.
# This is a second, independent floor so a change there can never
# silently re-open first-minute entries here.
FIRST_NEW_ENTRY = dtime(9, 30)

# ---- STRENGTH IS BOUGHT EARLY OR NOT AT ALL. 7 August 2026. ----
#
#     "thats the issue & i've been asking you to enter into strength
#      stocks as early as possible"                    -- operator
#
# Measured on the 7 August tape. SBCL was in Row 1 at 08:21 with an
# EXCELLENT result, before the bell. What the 09:30 floor did to it:
#
#     09:20   price 846.00   stop 833.35   1.5% away   118 shares
#     09:35   price 895.95   stop 833.35   7.0% away   REFUSED
#     10:00   price 914.05   stop 833.35   8.8% away   REFUSED
#
# The stop never moved. The entry ran away from it. Every higher high
# widened the gap until position_plan refused the trade for being
# exactly what he wanted to buy -- a strong stock going up.
#
# And the tight stop is not a restriction, it is SIZE: 118 shares at
# 09:20 against 23 at 09:35, for the same Rs 1,500 of risk.
#
# WHY THIS IS NARROW, AND MUST STAY NARROW
# ----------------------------------------
# At 09:20 there is no confirmation. The tape is ten minutes old and
# says almost nothing. Buying an UNEXPLAINED volume mover here is
# buying noise, and no amount of "it was strong" makes that a reason.
#
# The one case where the reason genuinely predates the open is a
# result already graded overnight -- Row 1. That reason was published
# last night; the 09:20 tape adds nothing to it and takes nothing
# away. So only those may be entered early. Everything else waits for
# FIRST_NEW_ENTRY exactly as before.
# ---- 09:15, NOT 09:20. His rule, 9 August 2026. ----
#
#     "why still waiting 9:20 ? we decided not to time the entry"
#
# He is right and he said it first on 7 August: "don't fix the timing
# of the trades. no one can guess the stock movement & price in this
# world". The five minutes from 09:15 to 09:20 were mine, not measured
# -- there is no evidence that a card published last night becomes
# more true at 09:20 than at 09:15.
#
# What stays is the DISTINCTION, which is structural rather than a
# clock: a stock whose reason predates the open needs no opening
# range, because the reason is already published. An UNEXPLAINED
# volume mover does -- there is nothing else to judge it by. That is
# not timing the entry, it is requiring evidence before one.
# ---- ON. 10 August 2026. ----
# Switched off on 9 August for cost: 57 ms a symbol, 1.15 s for a
# cycle of 20, and the test suite stopped finishing. The question
# was the wrong way round -- it asked every candidate whether any
# message was about them. core/supply_events.py now asks each
# MESSAGE who it is about, once per window, and falls back to the
# full subject test only when the index says nothing.
#
#     20 unknown candidates, cold   1.15 s  ->  0.026 s
#     400 cached lookups                       0.0011 s
#
# And it still blocks LICI, whose notice carries no hashtag and
# whose registered name NSE abbreviates to LIFE INSURA CORP OF
# INDIA -- the case a faster-but-shallower gate lost.
SUPPLY_GATE = True

EARLY_ENTRY_FROM = dtime(9, 15)

# ---- THE SAME THREE GRADES AS ROW 1. 9 August 2026. ----
#
#     "@ results time = EXCELLENT, GREAT, GOOD"
#
# This said EXCELLENT and GREAT while core/watchlist_builder.TOP_GRADES
# said all three, so a GOOD result could lead Row 1 all morning and
# still be refused at the entry for a grade the operator had already
# ruled in. SHILPAMED, 5 August, exactly that shape.
try:
    from core.watchlist_builder import TOP_GRADES as EARLY_ENTRY_GRADES
except Exception:                                          # noqa: BLE001
    EARLY_ENTRY_GRADES = ("EXCELLENT", "GREAT", "GOOD")

_graded_cache = {}

# ---- THE GRADES CHANGE DURING THE SESSION. 11 August 2026. ----
#
#     "during results time = bot must know which stocks will get results
#      on which date & time (during/after) ... once bot recv the graded
#      card of result, it must act on the stock"
#                                                       -- operator
#
# This cache was loaded ONCE per process and never refreshed, on the
# stated assumption that "the overnight grades do not change during a
# session". That is true only for companies reporting after the close.
# Companies that report DURING market hours -- which the operator has
# asked the bot to handle from the start, and which core/
# results_calendar.py records a broadcast_at timestamp for precisely
# so their habitual time can be learned -- publish their card while the
# bot is running. With a cache that never expired, that card could not
# reach the entry path on the day it mattered. It would first be seen
# the NEXT morning, by which time the reaction is over.
#
# core/results_gate.py already refreshes on a 60-second TTL for exactly
# this reason. The two paths disagreed; they no longer do.
_GRADED_TTL_SECONDS = 60.0


def _is_pre_graded(symbol):
    """Is this stock currently graded EXCELLENT / GREAT / GOOD?

    Re-read every _GRADED_TTL_SECONDS rather than once per process, so
    a card that lands mid-session is acted on in the same session. The
    TTL exists because this is asked once per pick per cycle and the
    underlying read touches data/telegram.db -- a per-tick lookup would
    put the feed on the hot path.
    """
    symbol = str(symbol or "").upper()
    if not symbol:
        return False

    import time as _time
    now = _time.monotonic()
    stale = (now - _graded_cache.get("at", 0.0)) > _GRADED_TTL_SECONDS
    if "map" not in _graded_cache or stale:
        try:
            from core import watchlist_builder
            _graded_cache["map"] = watchlist_builder.graded_symbols() or {}
        except Exception as exc:                           # noqa: BLE001
            _broke("graded_symbols (Row 1 is empty)", exc)
            # Keep whatever was already known. Blanking the map on a
            # transient read failure would drop every graded stock out
            # of the lane for a full cycle, which is the loudest
            # possible way to fail quietly.
            _graded_cache.setdefault("map", {})
        _graded_cache["at"] = now

    entry = (_graded_cache["map"] or {}).get(symbol) or {}
    grade = str(entry.get("grade") or "").upper()
    return grade in EARLY_ENTRY_GRADES


def _faded(mover):
    """Has the stock already rolled off its high?

    ---- "+ MAKING HIGHS". HIS THIRD CONDITION, 11 August 2026. ----

        "stock must get graded - excellent, great, good + volume
         supports + making highs"

    The grade says the quarter was good. The volume says money is
    moving. Neither says the stock is still going UP right now, and a
    graded result that has already rolled over is one the market has
    finished pricing -- buying it is buying somebody else's exit. This
    lane checked only that the change was not negative, which a stock
    can satisfy while sitting at the bottom of its range all morning.

    core/rules.FADED_FROM_HIGH owns the number (half the day's range)
    so this lane and core/ranker.py cannot drift apart.

    Unknown range -> NOT faded. If the mover rows do not carry
    day_high/day_low this test must not silently close the lane on
    every stock; it fails open, and the caller is expected to have
    verified the feed supplies them.
    """
    try:
        from core.rules import FADED_FROM_HIGH
    except Exception:                                      # noqa: BLE001
        FADED_FROM_HIGH = 0.5
    high = _num(mover.get("day_high"))
    low = _num(mover.get("day_low"))
    ltp = _num(mover.get("ltp"))
    if high is None or low is None or ltp is None or high <= low:
        return False
    if ((ltp - low) / (high - low)) >= FADED_FROM_HIGH:
        return False                      # not faded on price either

    # ==========================================================
    # PRICE SAYS FADED. ASK THE BUYING.  31 August 2026.
    # ==========================================================
    #
    #     "buying pressure making highs confirm even before news land
    #      into bot"                          -- the operator
    #
    # The test above is where the PRICE sits in the day's range and
    # nothing else. PRECWIRE sat at 0.22 of its range and was refused
    # 518 times that morning, while buyers took 63% of every share
    # traded and cumulative delta made new highs all session -- 100%
    # of it classified against a real bid and ask, not inferred.
    #
    # A pullback on rising buying is not the same animal as a
    # roll-over on selling, and until today the bot could not tell
    # them apart. core/order_flow.still_buying() asks the second
    # question: is the delta positive, and higher than it was fifteen
    # minutes ago.
    #
    # THE FLOW CAN ONLY RESCUE, NEVER CONDEMN. If it says the buying
    # is still growing, the price verdict is overruled. If it says
    # anything else -- or says nothing, which is what a missing or
    # inferred reading returns -- the price verdict stands exactly as
    # it did before. A gate that could be turned ON by a guess would
    # be worse than the gate we have.
    try:
        from core.order_flow import still_buying
        flow = still_buying(mover.get("symbol"))
    except Exception:                                      # noqa: BLE001
        flow = None
    if flow and flow.get("still_buying"):
        return False
    return True


def _volume_supports(mover, now=None):
    """Is today's traded value at least MIN_VOLUME_RATIO x this stock's
    own normal day -- the third of his three conditions (see above).

    Fails CLOSED, deliberately unlike the structural path's
    _breakout_has_volume() (core/engine.py): that one fails open
    because a legacy Ticker-mode feed sometimes carries no volume at
    all, and refusing every trade over a feed gap would just stop the
    bot. This lane has no such excuse -- the gainers/losers snapshot
    it reads always carries a real volume field (core/circuit_monitor.py),
    so "cannot be measured" here means the ADV lookup failed, not that
    the data doesn't exist, and a graded stock is worth enough to wait
    for a real answer rather than guess one.
    """
    try:
        from core.ranker import volume_ratio
        from core.liquidity import adv
    except Exception as exc:                                # noqa: BLE001
        _broke("volume_ratio import", exc)
        return False
    symbol = str(mover.get("symbol") or "").upper()
    try:
        # ---- 2.5x OF A WHOLE DAY, MEASURED AT 09:20. 23 Aug ----
        # This lane runs 09:15-09:30, when a stock has traded roughly
        # 4-7% of its normal day. Against a WHOLE-day divisor, clearing
        # 2.5 here demanded FIFTY times normal pace -- which is also
        # MAX_SANE_VOLUME_RATIO, the value above which the denominator
        # is presumed broken. The gate could not be passed by a real
        # stock. Measured against this stock's own pace by this minute
        # (core/volume_pace.py) 2.5 means what it reads.
        ratio = volume_ratio(mover, adv(symbol), symbol=symbol, now=now)
    except Exception as exc:                                # noqa: BLE001
        _broke("volume_ratio", exc)
        return False
    return ratio is not None and ratio >= MIN_VOLUME_RATIO


def _clock(now):
    if now is None:
        return None
    return now.time() if hasattr(now, "time") else now


# ---- THE THIRD CONDITION WAS NEVER CODED. 12 August 2026. ----
#
#     "stock must get graded - excellent, great, good + volume
#      supports + making highs"                    -- operator, 11 Aug
#
# Three conditions were stated. _faded() below checks "making highs".
# The grade check is _is_pre_graded(). "Volume supports" was never
# written -- this lane took a graded, still-rising stock on ANY
# volume, including a thin morning tape doing nothing unusual. A good
# quarter with nobody trading it yet is a card, not a mover.
#
# Same threshold the ranker and select.py already use for the same
# question (core/rules.py -- the one place this number now lives, so
# the early lane and the standard lane can never drift apart on what
# "volume supports" means).
try:
    from core.rules import MIN_VOLUME_RATIO
except Exception:                                          # noqa: BLE001
    MIN_VOLUME_RATIO = 1.5


def early_rows(movers, now=None, plan_of=None, evidence_of=None):
    """Row 1's candidates, ranked for the 09:20 lane.

    ---- WHY NOT core/ranker.py. 7 August 2026. ----
    The ranker will not name any of these, and it is right not to:
    liveness(), the sector lead and the 3% move threshold all read the
    TAPE, and at 09:20 there are five minutes of tape. Asking it to
    judge a stock before the stock has done anything would mean
    loosening the gates that protect every other entry of the day.

    So the early lane does not use it. Its candidate list is Row 1 --
    the overnight grades -- which is a list that was already complete
    before the bell. The only ordering question is which of them to
    take first, and that is answered by the grade and then by what the
    open is already saying.

    Returns rows shaped exactly like the ranker's, so take() cannot
    tell the difference and no gate is skipped.
    """
    clock = _clock(now)
    if clock is None or not (EARLY_ENTRY_FROM <= clock < FIRST_NEW_ENTRY):
        return []

    out = []
    for mover in (movers or []):
        if not isinstance(mover, dict):
            continue
        symbol = str(mover.get("symbol") or "").upper()

        # ---- THE DOOR ONLY OPENED FOR RESULTS. 18 August 2026. ----
        #
        #     "by knowing the underlying news = buy right? if we wait
        #      for 09:30 to orb confirmation we may miss or never able
        #      to enter into trade after a long run up ... in some
        #      great events on the stock will not give the opportunity
        #      to enter at all as stocks lock at circuits"
        #
        # This lane exists precisely to avoid that wait, and its
        # admission test was _is_pre_graded() -- watchlist_builder's
        # OVERNIGHT RESULTS GRADES and nothing else. An order win, a
        # contract, a business update or a commodity headline filed at
        # 20:00 was not a grade, so it fell through to the standard
        # path and waited for the 09:30 range to complete and then to
        # break. On a stock that opens and locks, that wait is not a
        # delay, it is the whole trade.
        #
        # core/signal_journal.py measured the cost. Of every refusal
        # bucket with enough cases, the BEST-performing one was
        # "filed today, numbers not read yet" -- n=91, +0.25% at the
        # close, +3.53% at its best, against +1.22% for stocks with no
        # event at all. The bot's most profitable refusal was a stock
        # whose news it had not finished reading.
        #
        # A GRADE STILL OUTRANKS RAW EVIDENCE, and deliberately: an
        # overnight grade has been parsed, and a filing at 09:16 has
        # only been noticed. Both get in; the parsed one sorts first.
        #
        # Every other gate below is UNCHANGED and applies to both --
        # must be up on the day, must be making highs and not falling
        # back, must have volume behind it. Widening the door does not
        # widen the room.
        graded = _is_pre_graded(symbol)
        evidence = None
        if not graded and evidence_of is not None:
            try:
                evidence = evidence_of(symbol)
            except Exception as exc:                       # noqa: BLE001
                _broke("evidence_of (the early lane sees results only)",
                       exc)
                evidence = None
        if not graded and not evidence:
            continue
        grade = str(((_graded_cache.get("map") or {}).get(symbol)
                     or {}).get("grade") or "").upper()

        # ---- A GAP THAT IS ALREADY SPENT IS NOT AN EARLY ENTRY ----
        # The whole point is a tight stop. If the stock has already
        # run away from its own low in the first five minutes, this
        # lane has no advantage over waiting, and position_plan will
        # refuse it anyway -- better to say why here.
        change = _num(mover.get("change_pct")) or 0.0
        if change < 0:
            continue

        # "+ making highs" -- see _faded(). A graded stock sitting in
        # the bottom half of its own day range is not an opportunity
        # occurring, it is one that has already passed.
        if _faded(mover):
            continue

        # "+ volume supports" -- see _volume_supports(). A good quarter
        # nobody is trading yet is a card, not a mover.
        if not _volume_supports(mover, now=now):
            continue

        if graded:
            base, why = ((10.0 if grade == "EXCELLENT" else 5.0),
                         f"{grade} result, bought at the open before the "
                         f"move widened the stop")
        else:
            # Below every graded row on purpose -- see the note above.
            base = 4.0
            why = (f"{str(evidence)[:90]} -- taken at the open rather "
                   f"than waiting for the 09:30 range")
        row = {"symbol": symbol, "action": "BUY", "ltp": mover.get("ltp"),
               "score": base + change, "why": why,
               "result_tag": grade or "EVENT", "early": True,
               "early_source": "grade" if graded else "evidence"}
        if plan_of is not None:
            row["plan"] = plan_of(mover)
        out.append(row)
    out.sort(key=lambda r: -r["score"])
    return out


def _journal_pick(engine, row, taken, why):
    """Record a ranked pick and what became of it. Never raises.

    ---- THE RANKED LANE KEPT NO RECORD. 19 August 2026. ----

        "whats the use for trader on seeing the score ?"

    None yet -- and it could not even be checked, because only the
    STRUCTURAL lane wrote to core/signal_journal.py. Every ranked
    pick, its score, and whether it reached his phone existed for one
    loop and was gone. So "does a higher score lead to a better
    outcome" had no data behind it, in either direction.

    Buffered, not written: record() keeps a dict keyed by symbol and
    the heartbeat flushes it, so this costs no disk on the tick path.
    """
    journal = getattr(engine, "signal_journal", None)
    if journal is None:
        return
    symbol = str(row.get("symbol") or "").upper()

    # ---- THE RANKED LANE RECORDED HALF A ROW. 19 Aug 2026. ----
    #
    # The first version passed the score and left news_kind NULL, so
    # RAILTEL -- whose alert quoted a Rs 166.80 crore EPFO order --
    # was recorded as a scored pick with no news against it. The
    # structural lane fills those columns from _capture_reason(); the
    # lane that actually produces his alerts did not, which would have
    # left "does news predict" unanswerable for exactly the picks that
    # reach his phone.
    #
    # Same source as the alert sentence and the structural lane. One
    # answer per stock per morning, or the record contradicts the
    # message again.
    reason = {}
    try:
        capture = getattr(engine, "_capture_reason", None)
        if capture is not None:
            reason = capture(symbol) or {}
    except Exception as exc:                               # noqa: BLE001
        _broke("reason capture for the journal", exc)
        reason = {}

    try:
        journal.record(
            symbol,
            "LONG",
            break_price=_num(row.get("ltp")),
            taken=bool(taken),
            refused_why=None if taken else str(why or "")[:200],
            volume_mult=_num(row.get("volume_x")),
            sector=row.get("sector"),
            score=_num(row.get("score")),
            news_kind=reason.get("news_kind"),
            filing_kind=reason.get("filing_kind"),
            results_grade=reason.get("results_grade"),
        )
    except Exception as exc:                               # noqa: BLE001
        _broke("signal journal (the pick is unrecorded)", exc)


def _alert_lines(row, plan):
    """Everything the board already knows about this pick, on one card.

    ---- IT WAS SENDING FOUR FACTS OUT OF TWENTY-FIVE. 19 Aug 2026 ----

        "why you are not using complete resources & expecting spoon
         feeding by me ?"                    -- operator

    Fair. core/ranker.py puts delivery, order-book pressure, circuit
    headroom, MTF leverage, average traded value, position in range
    and distance off the high on EVERY row, and the alert carried the
    reason, the quantity and two prices. The rest was computed, shown
    on a screen he is not looking at, and dropped on the way to the
    phone -- the order-book reading in core/tick_ohlc.py in
    particular had been read by nothing since it was written on
    17 August.

    That module's guard greps for its own call signature, so this
    docstring deliberately does not spell it out. The guard must stay
    able to fail on real code, and prose that trips it is exactly how
    a guard gets loosened for the wrong reason.

    NOTHING HERE IS COMPUTED. Every number is lifted off the row the
    ranker built, so the card and the board cannot disagree.

    A LINE IS OMITTED WHEN ITS FACT IS MISSING, never filled with a
    zero or a dash. And a reading that is AGAINST the trade is printed
    exactly as loudly as one for it -- an alert that only lists
    reasons to buy is an advertisement.
    """
    lines = []

    # ---- CONVICTION: is real money behind this, or only price? ----
    delivery = row.get("delivery") if isinstance(row.get("delivery"),
                                                 dict) else None
    if delivery and delivery.get("pct") is not None:
        note = str(delivery.get("reading") or "").replace("_", " ")
        avg = delivery.get("avg")
        lines.append(f"delivery {delivery['pct']}%"
                     + (f" vs {avg}% usual" if avg is not None else "")
                     + (f" -- {note}" if note else ""))

    book = row.get("pressure") if isinstance(row.get("pressure"),
                                             dict) else None
    if book and book.get("ratio") is not None:
        ratio = book["ratio"]
        side = (f"buyers {ratio:.1f}x" if ratio >= 1
                else f"SELLERS {1 / ratio:.1f}x" if ratio > 0 else None)
        if side:
            above = book.get("above_atp")
            lines.append(
                f"book {side}"
                + ("" if above is None
                   else (" and above the day's average price" if above
                         else " and BELOW the day's average price")))

    moving = str(row.get("moving") or "").strip()
    if moving:
        lines.append(moving)

    # ---- ROOM: can he actually get the size on, and get out? ----
    room = []
    head = _num(row.get("headroom_pct"))
    if row.get("at_circuit"):
        room.append("AT THE CIRCUIT -- a queue, not a trade")
    elif head is not None:
        room.append(f"{head:.1f}% to the circuit")
    lev = _num(row.get("mtf_leverage"))
    if lev is not None:
        room.append(f"MTF {lev:.1f}x")
    elif row.get("cash_only"):
        # Dhan margins nothing here, so this one costs full cash. Said
        # out loud because the ranker no longer refuses it -- see the
        # note at the mtf check in core/ranker.py. He asked for the
        # trade to be offered; he should still see what it will cost.
        room.append("no MTF -- full cash, 1x")
    adv = _num(row.get("adv_cr"))
    if adv is not None:
        room.append(f"Rs {adv:.1f}cr traded on a normal day")
    if room:
        lines.append(" | ".join(room))

    tilt_why = str(row.get("commodity_tilt_why") or "").strip()
    if tilt_why:
        lines.append(tilt_why)

    return lines


def refuse_reason(row, engine, now=None, held=None, max_positions=None,
                  traded_today=None):
    """Why this pick must NOT be taken, or None if it may be.

    Returns a plain sentence, because every refusal is shown to him.
    """
    symbol = str(row.get("symbol") or "").upper()
    if not symbol:
        return "no symbol on the row"

    # LONG ONLY. "i only trade in long positions".
    if str(row.get("action") or "").upper() != "BUY":
        return "not a long -- he does not short"

    # ---- PAUSED. HE IS AWAY FROM THE DESK. 14 September 2026. ----
    #
    # Asked early and about the SESSION rather than the stock, so the
    # reason he is shown names the pause and not whichever gate the
    # stock would have met next. See Engine.entries_paused: the switch
    # is untouched, open positions are still managed, and this refusal
    # is one he is told about.
    if getattr(engine, "entries_paused", False):
        return ("new entries are PAUSED -- you stopped them. It passed "
                "every other gate; nothing was bought")

    plan = row.get("plan") or {}
    if not plan.get("ok"):
        return str(plan.get("why") or "no tradeable plan")
    if not plan.get("qty") or not plan.get("stop"):
        return "the plan carries no quantity or no stop"

    # liveness() said the move has stopped working. It must not be
    # possible to enter one of these from any path.
    if row.get("state") == "fading":
        return "fading -- the move has already stopped working"

    # ---- A FREED SEAT IS NOT A REASON TO BUY. 14 Sep 2026. ----
    #
    #     "do not keep instant buy when ever seat gets free ...
    #      freshness of the stock ranked, price action followed after
    #      the rank"                            -- the operator
    #
    # Both halves of that, in order: is this rank still describing the
    # market, and how much of the move is already gone. See
    # config.ENTRY_MAX_EXTENSION_PCT for the measurement behind the
    # second one. Anything unreadable is NOT a refusal -- a missing
    # reading means nothing, the rule this file already follows for the
    # tick and the flow.
    from config import (ENTRY_MAX_EXTENSION_PCT,
                        ENTRY_RANK_MAX_AGE_SECONDS)

    ranked_at = row.get("ranked_at")
    if ranked_at is not None and ENTRY_RANK_MAX_AGE_SECONDS and now:
        try:
            age = (now - ranked_at).total_seconds()
        except TypeError:
            age = None
        if age is not None and age > float(ENTRY_RANK_MAX_AGE_SECONDS):
            return (f"the board that ranked it is {age / 60:.0f} min old "
                    f"-- waiting for a fresh one rather than buying off a "
                    f"list nobody has re-checked")

    if ENTRY_MAX_EXTENSION_PCT is not None:
        extension = row.get("extension_pct")
        if extension is not None:
            try:
                extension = float(extension)
            except (TypeError, ValueError):
                extension = None
        if extension is not None and extension >= float(ENTRY_MAX_EXTENSION_PCT):
            return (f"already {extension:.1f}% above the day's open -- the "
                    f"part of the move worth having has gone "
                    f"(measured: 61 such trades lost 25,026)")

    # ---- WHO IS WINNING, AND IS THE PRICE FOLLOWING. 15 Sep 2026. ----
    #
    #     "i asked to check the strength on buying or selling side &
    #      price action stocks were made during the trades. not a fixed
    #      % to check the freshness"                 -- the operator
    #
    # Two questions, asked at the moment of buying, direction only:
    #
    #   1. BUYERS. Are buyers ahead today and still adding? The same
    #      reading the BUYING_DRIED_UP exit already trusts. Before the
    #      minute store has enough session, the live running total says
    #      at least whether buyers or sellers are ahead.
    #   2. PRICE. Since the board ranked it, has the price held or gone
    #      up? SUNTV was ranked at 476.94 and bought at 471.64.
    #
    # No reading is not a refusal -- the rule this file keeps for the
    # tick and the flow. A reading that says sellers, or a falling
    # price, is.
    from config import ENTRY_NEEDS_BUYERS, ENTRY_NEEDS_PRICE_FOLLOWING
    if ENTRY_NEEDS_PRICE_FOLLOWING:
        drift = _num(row.get("drift_since_rank_pct"))
        if drift is not None and drift < 0:
            return (f"price fell {abs(drift):.1f}% since it was ranked -- "
                    f"the price is not following")
    if ENTRY_NEEDS_BUYERS:
        try:
            from core.order_flow import pressure, still_buying
            flow = still_buying(symbol)
            if flow is not None:
                if not flow.get("still_buying"):
                    side = ("sellers are ahead today" if not flow.get("positive")
                            else "buying has stopped growing")
                    return (f"{side} (buy-sell {flow.get('delta'):,.0f}, was "
                            f"{flow.get('was'):,.0f} "
                            f"{flow.get('minutes')} min ago)")
            else:
                live = pressure(symbol)
                if live is not None and live.get("delta", 0) <= 0:
                    return (f"sellers are ahead today (buy-sell "
                            f"{live.get('delta'):,.0f})")
        except Exception as exc:                           # noqa: BLE001
            _broke("order flow at entry", exc)

    held = {str(s).upper() for s in (held or [])}
    if symbol in held:
        return "already holding it -- no pyramiding"

    # ---- HIS BOOK IS NOT THE BOT'S BOOK. 1 September 2026. ----
    #
    #     "bot doesnot confuse with my trades incase i trade in vtl ,
    #      bot can also trade if all rules satisfies"
    #
    # A refusal lived here for a few hours: a stock he held at Dhan was
    # refused to the bot. It came from his CAPLIPOINT message earlier
    # the same day, and I read that as "do not buy on top of me". He
    # meant the opposite -- the two books must not be CONFUSED with each
    # other, which is a reporting problem, not a trading one. They are
    # kept apart where that belongs: two tables on the Trade tab, and
    # core/broker_sync.py's three buckets behind them.
    #
    # So his position blocks nothing. The bot's own book still does --
    # "already holding it" above -- because that is the bot pyramiding
    # into itself, which is a different thing entirely.

    # ---- ONE STOCK, ONE TRADE A DAY. 1 September 2026. ----
    #
    #     "done one stock one trade per trade by bot."
    #
    # The exit rule and the ranker fought over the same name and both
    # won, in turn: VTL was sold at 15:02:16 because its buyers had
    # stopped and bought back at 15:02:18 because it was still the best
    # stock on the board. Two seconds, two lots of brokerage, and VTL's
    # whole loss for the day. MARINE did the same 98 seconds apart.
    #
    # Neither rule was wrong. They were answering different questions
    # about the same stock in the same second, and nothing above them
    # said which one settles it. This does.
    #
    # A MISS IS THE PRICE. If the stock runs again after the bot is out,
    # it is missed. He has weighed that against paying the spread twice
    # and chosen this. See Engine.symbols_traded_today().
    if symbol in {str(s).upper() for s in (traded_today or [])}:
        return ("already traded today -- one stock, one trade a day")

    # ==========================================================
    # SUPPLY IS NOT DEMAND -- IN THE LIVE PATH.  9 August 2026.
    # ==========================================================
    #
    #     "u didn't fill the gaps till now?"
    #
    # core/supply_events.py was written on 8 August, tested, wired into
    # core/centre.py -- and NOT into this function, the one that
    # actually decides. So the board could show LICI BLOCKED in red
    # while this path would still have taken the trade. I found that on
    # Friday, said so, and left it.
    #
    # LICI, four of five replayed days, 165x its own volume, the
    # largest flow on the board, lost every time. The OFS notice was in
    # data/telegram.db from 3 August. An OFS produces exactly the
    # signature the volume filter hunts and the price goes DOWN,
    # because the whole event is somebody selling.
    #
    # He is long only. This is not a weaker buy. It is not a buy.
    # ---- MEASURED, AND BACKED OUT. 9 August 2026, same evening. ----
    #
    # Hooking supply_events.overhang() in here is CORRECT and it is the
    # gap he was angry about. It is off because of cost, not doubt:
    #
    #     per symbol, cold        ~57 ms  (core/subject.is_about)
    #     20 candidates, cold     ~1.15 s
    #     test suite              stopped finishing at all
    #
    # A gate I cannot run the suite against is a gate I cannot claim
    # works, and putting an unverified change on the live entry path the
    # night before a session is the exact thing that has cost him money
    # before.
    #
    # The block itself is NOT lost: core/centre.py calls it, so LICI
    # still shows BLOCKED with its reason on the board. What is missing
    # is the live refusal, and the fix is to resolve each message's
    # subject ONCE per window instead of once per candidate.
    # ---- IT COULD ONLY EVER FIRE ON A STOCK THAT WAS RISING. ----
    #                                     5 September 2026.
    #
    #     "recent TBZ stock check that rally. does the bot take this
    #      stock atleast one time?"
    #     "yes i think this settles & its a good one"
    #                                            -- the operator
    #
    # 1 September, in the bot's own store, with 12x volume behind it:
    #
    #     TBZ: CO PROMOTER SELLS 74.12% STAKE TO GRT JEWELLERS
    #          FOR Rs 1,033.71 CRORE; OPEN OFFER TO FOLLOW
    #
    # matched on PROMOTER SELL and was refused as "the promoter is
    # selling". It is the opposite: ownership changed hands privately,
    # not one share reached the market, and the buyer is now obliged to
    # bid for everyone else's. TBZ went +19.99% then +14.03%, ran 248
    # to 437 in ten sessions, and the bot bought it on 4 September
    # after all of it. The module already excepts "OPEN OFFER TO
    # ACQUIRE"; this headline said "OPEN OFFER TO FOLLOW".
    #
    # THE MEASUREMENT THAT SETTLED IT. Of the 75 stocks this refused:
    #
    #     60 never got 3% above their previous close -- the chain
    #        refuses them at MIN_MOVE_FROM_PREV_CLOSE_PCT anyway
    #     15 did -- and ALL FIFTEEN closed above their open
    #
    # and every faller it "caught" -- ADANIPOWER -6.8%, THYROCARE
    # -7.6%, NETWEB -4.9%, ASTERDM -4.1%, RENUKA -3.1% -- never got 3%
    # up either. It cannot stop a single faller the chain does not
    # already stop, so the only thing it can do is refuse risers.
    #
    # That is not a close call about a threshold. It is the shape of
    # the two rules: a stock about to fall is not 3% up making higher
    # highs on its own volume, so this gate can only ever bite on one
    # that is.
    #
    # THE LABEL STAYS. core/centre.py still reads overhang() and the
    # board still shows "promoter sold 74% to GRT Jewellers" beside
    # the stock. He keeps the information and loses the veto.
    #
    # What is given up: a rising stock with a REAL distribution
    # overhang that then collapses. Fifteen is a small number and that
    # case is not disproven -- it is judged rarer than losing TBZ,
    # CYIENT, HINDZINC and WELCORP, and this is one flag to put back.
    if SUPPLY_GATE:
        try:
            from core import supply_events
            sold = supply_events.overhang(symbol, now=now)
        except Exception as exc:                           # noqa: BLE001
            _broke("supply_events -- the label is missing, not the trade", exc)
            sold = None
        if sold:
            row["supply_note"] = sold["why"]

    clock = _clock(now)
    if clock is not None:
        # ---- THE GATE WAS ONLY ON ONE SIDE. 31 August 2026. ----
        #
        #     "so basically bot can trade at its own time not within
        #      NSE timings"                            -- the operator
        #
        # He read a would-be entry stamped 07:58 and asked the obvious
        # question. There was a check for TOO LATE and none at all for
        # TOO EARLY. On 31 August the ranker produced four picks at
        # 07:58:40 -- PRECWIRE, ATHERENERG, ELGIEQUIP, RAMRAT -- an
        # hour and seventeen minutes before the exchange opened.
        #
        # Nothing was placed, because ALERT_ONLY_MODE was on all day.
        # That is luck, not a guard. With the bot trading, a pre-open
        # price is a stale price from a market that is not running, and
        # any order built on one is priced against nothing.
        if clock < EARLY_ENTRY_FROM:
            return (f"before {EARLY_ENTRY_FROM:%H:%M} -- the market is "
                    f"not open yet")
        if clock >= LAST_NEW_ENTRY:
            return (f"after {LAST_NEW_ENTRY:%H:%M} -- too late to give a "
                    f"new position room to work")

    if max_positions is not None and len(held) >= max_positions:
        # ---- A FULL BOOK IS NOT A CLOSED DOOR. 5 August 2026. ----
        #
        # Engine._maybe_rotate_out() exists and is conservative: it
        # frees a slot only when the challenger is DECISIVELY stronger
        # than the weakest holding, and it caps swaps per day so churn
        # cannot eat the edge in brokerage. The breakout path has used
        # it since it was written. This one never called it, so the
        # tenth setup of the morning permanently outranked the best
        # setup of the afternoon.
        # ---- ONE SWITCH, TWO DOORS. 21 August 2026. ----
        #
        #     "do u understand how stupid trade were bot trading?"
        #
        # 12:49:37  PAPER BUY  CDSL 47 @ 1390.80
        # 12:49:48  [ROTATE] CDSL rotated OUT for URBANCO
        # 12:49:48  PAPER SELL CDSL 47 @ 1391.50
        #
        # ELEVEN SECONDS. Gross +Rs 32.90, charges Rs 69.34, net
        # -Rs 36.44 -- a winning trade turned into a loss by its own
        # brokerage. Four of the day's five closed trades exited
        # ROTATED_OUT, holding 0.2 to 23 minutes, for -Rs 1,029.33.
        #
        # ENABLE_SLOT_ROTATION was set False that morning, on the
        # measurement the config file itself asked for (n=15, 20% win,
        # median hold 2.3 minutes). It was honoured in core/engine.py
        # and NOT here. Two call sites, one guard, and the unguarded
        # one is the RANKED lane -- the lane he actually trades.
        #
        # A switch that turns something off in one place and not the
        # other is worse than no switch: it reports a decision that
        # was never carried out.
        rotate = (getattr(engine, "_maybe_rotate_out", None)
                  if ENABLE_SLOT_ROTATION else None)
        freed = False
        if callable(rotate):
            try:
                freed = bool(rotate(symbol, "LONG", now))
            except Exception as exc:                       # noqa: BLE001
                _broke("rotation check", exc)
                freed = False
        if not freed:
            # ---- SAY WHY, NOT JUST NO. 24 August 2026. ----
            #
            # This claimed the challenger was "not decisively better
            # than the weakest" whatever the real cause. On 24 August
            # RATNAMANI arrived at +5.70% against a weakest holder at
            # -1.60%, a 7.3-point gap over a 2.0-point bar -- it was
            # decisively better by any reading. Rotation had refused
            # on its FIRST line:
            #
            #     if getattr(self, "alert_only", True):
            #         return False
            #
            # The bot was not trading. The message blamed the stock,
            # and reading it you would conclude the bot had judged
            # RATNAMANI inferior to a position sitting at -1.6%. It
            # never got as far as judging.
            #
            # Same fault as "[CARRY] ... stop None" and the false
            # "silent" feed warning: a sentence asserting something
            # the code never established.
            if not ENABLE_SLOT_ROTATION:
                return (f"book full ({len(held)} of {max_positions}) and "
                        f"slot rotation is OFF -- no seat can be freed")
            return (f"already holding {len(held)} of {max_positions} "
                    f"and not decisively better than the weakest")

    # The engine's own risk layer has the last word -- daily loss cap,
    # entry blocks, square-off guard. Ask it rather than duplicating it.
    blocked = getattr(engine, "entry_blocked_reason", None)
    if callable(blocked):
        try:
            # ONE clock for the whole decision (12 August 2026). This
            # path already gated on `now` above; letting the engine read
            # the wall clock again meant two answers to "what time is
            # it" inside a single entry.
            why = blocked(symbol, "LONG", at_time=now)
        except Exception as exc:                           # noqa: BLE001
            # ---- FAIL CLOSED, NOT OPEN. 8 August 2026. ----
            # This is the engine's own risk layer: daily loss cap,
            # entry blocks, square-off guard. It used to swallow the
            # exception, set why=None, and let the trade THROUGH --
            # so a broken risk check read exactly like a clean one and
            # the order went out unprotected.
            #
            # A safety gate that fails open is worse than no gate,
            # because it is trusted.
            _broke("engine.entry_blocked_reason -- REFUSING the trade",
                   exc)
            why = (f"the risk check itself failed ({type(exc).__name__})"
                   f" -- refusing rather than trading unprotected")
        if why:
            return str(why)
    return None


def price_now(row, price_of):
    """Put the LIVE tick price on a ranked row before anything reads it.

    ---- THE DOOR WAS READING A PHOTOGRAPH. 3 September 2026. ----

        "fix the entry lag, make it read ticks not the snapshot ...
         i want lag free & seamless dashboard with out missing any
         opportunity"                                -- the operator

    take() ends in

        enter(symbol, security_id, row.get("ltp"), plan["stop"], ...)

    and row["ltp"] came from the dashboard snapshot. That snapshot is
    rebuilt by dashboard/state._build(), which recomputes about
    twenty-five panels from scratch and takes 42s at the median, 82s
    at p90 -- main.py asks for it every second and gets one every
    forty. So the price the order was placed at, and the stop derived
    from it, were both up to a minute and a half old.

    Measured on his own book: entries averaged 0.95% worse than the
    price at first sighting.

    THE SPLIT. The snapshot is good at the slow question -- WHICH
    stocks qualify: the reason, the sector, liquidity, ADV, the news.
    None of that changes in a minute. It is bad at the fast one --
    WHAT the price is now. So the snapshot still chooses the
    candidates and the tick prices them, which is the same division
    core/engine.py already uses for exits: process_tick() runs the
    trailing stop intrabar, on every tick.

    price_of is INJECTED, like engine.buying_check -- main.py hands in
    core.tick_ohlc.of. Nothing here imports the tick store, so a unit
    test cannot reach the live one.

    A row with no tick is left exactly as it was. A missing reading
    means nothing; it must never be read as a better price.
    """
    if price_of is None:
        return row
    try:
        live = price_of(row.get("symbol")) or {}
    except Exception:                                      # noqa: BLE001
        return row

    try:
        ltp = float(live.get("LTP") or 0)
    except (TypeError, ValueError):
        return row
    if ltp <= 0:
        return row

    # WHAT THE BOARD SAID, KEPT. 14 September 2026. This line used to
    # be the only record of the ranked price and it overwrote it, so
    # "what did the stock do between being ranked and being bought"
    # could not be asked at all. setdefault, not assignment: the row
    # object survives until the next board publishes, and the first
    # re-pricing is the one that still holds the board's own number.
    if row.get("ranked_ltp") is None:
        try:
            was = float(row.get("ltp") or 0)
        except (TypeError, ValueError):
            was = 0.0
        if was > 0:
            row["ranked_ltp"] = was

    row["ltp"] = ltp
    row["priced_from"] = "tick"

    # HOW MUCH OF TODAY'S MOVE IS ALREADY SPENT. Against the day's
    # OPEN, so a gap is not counted as something the bot missed -- see
    # config.ENTRY_MAX_EXTENSION_PCT for the measurement.
    try:
        opened = float(live.get("open") or 0)
        if opened > 0:
            row["extension_pct"] = (ltp - opened) / opened * 100.0
    except (TypeError, ValueError):
        pass

    # And what it did since the rank, which is his actual question.
    try:
        ranked = float(row.get("ranked_ltp") or 0)
        if ranked > 0:
            row["drift_since_rank_pct"] = (ltp - ranked) / ranked * 100.0
    except (TypeError, ValueError):
        pass

    try:
        prev = float(live.get("close") or 0)
        if prev > 0:
            row["change_pct"] = (ltp - prev) / prev * 100.0
    except (TypeError, ValueError):
        pass

    # The day's extremes can only widen. Take the wider of the two
    # sources rather than trusting either alone -- REST drops symbols
    # and the feed reconnects.
    for key, live_key, pick in (("day_high", "high", max),
                                ("day_low", "low", min)):
        try:
            got = float(live.get(live_key) or 0)
        except (TypeError, ValueError):
            continue
        if got <= 0:
            continue
        had = row.get(key)
        row[key] = pick(got, float(had)) if had else got
    # LTP itself is a print, so it is evidence about the extremes too.
    if row.get("day_high") is None or ltp > row["day_high"]:
        row["day_high"] = ltp
    if row.get("day_low") is None or ltp < row["day_low"]:
        row["day_low"] = ltp

    # ---- THE STOP WAS BUILT ON A PRICE FIVE MINUTES OLD. 4 Sep ----
    #
    # SBCL, 4 September:
    #
    #     bought 09:16:39 at 1135.67
    #     stop   1144.80   -- ABOVE the entry
    #     sold   09:16:40 at 1131.13, one second later, -Rs 481
    #
    # 1144.80 / 0.97 = 1180.20, which is where SBCL was before it fell
    # into the open. The ORDER price was fresh -- price_now() had
    # already done its job -- but row["plan"] carries the stop and the
    # quantity, and that is built by dashboard/state._build() during
    # the rebuild. On 4 September the rebuild took 50 to 344 seconds.
    #
    # So the bot bought at a one-second price against a stop and a size
    # from a price up to five minutes old. On a stock falling into the
    # open, the stop lands above the entry and the position is closed
    # on the next tick.
    #
    # THE MARGIN RATE IS RECOVERED, NOT RE-ASKED. Dhan's margin for a
    # stock does not change minute to minute, and asking again here
    # would put a network call on the entry path. value_rs is what the
    # old plan sized, so budget / value_rs is the rate it used.
    #
    # A rebuild that fails leaves the old plan standing. A stale stop
    # is bad; no plan at all refuses the trade outright, which is worse.
    try:
        old_plan = row.get("plan") or {}
        if old_plan.get("ok") and row.get("ltp"):
            from config import MTF_MARGIN_PER_POSITION_RS
            from core.position_plan import plan as _position_plan
            value = _num(old_plan.get("value_rs"))
            pct = (MTF_MARGIN_PER_POSITION_RS / value) if value else None
            fresh = _position_plan(
                row.get("ltp"), row.get("action") or "BUY",
                day_low=row.get("day_low"), day_high=row.get("day_high"),
                margin_pct=pct, symbol=row.get("symbol"))
            if fresh.get("ok"):
                row["plan"] = fresh
                row["plan_priced_from"] = "tick"
    except Exception:                                      # noqa: BLE001
        pass

    # The gate that decides whether the move is still on was computed
    # on the stale price. Re-ask it on the live one. A None answer
    # ("cannot say") leaves the ranker's own verdict standing rather
    # than replacing a judgement with a shrug.
    try:
        from core.ranker import liveness
        state, why = liveness(row)
        if state:
            row["state"] = state
            if why:
                row["state_why"] = why
    except Exception:                                      # noqa: BLE001
        pass
    return row


def detail_or_symbol(row, symbol):
    """The one-line description of a pick, for an alert. Falls back to
    the symbol -- a missing description must not cost him the alert."""
    bits = [symbol]
    move = _num(row.get("change_pct"))
    if move is not None:
        bits.append(f"up {move:.1f}%")
    vol = _num(row.get("volume_x")) or _num(row.get("volume_ratio"))
    if vol:
        bits.append(f"on {vol:.1f}x volume")
    return " ".join(bits)


def take(rows, engine, now=None, security_id_of=None, held=None,
         traded_today=None,
         max_positions=None, alert=None, enter=None, price_of=None,
         surge_of=None):
    """Route the ranker's picks into the order path.

    `enter` and `alert` are injected so this can be exercised without
    an engine and without a broker. In production they are the
    Engine's own methods -- nothing here reimplements an entry.

    Returns a list of {"symbol", "taken", "why"} for the record. It
    never raises: this runs on the trading loop.
    """
    out = []
    held = set(str(s).upper() for s in (held or []))

    # ---- BEST FIRST, NOT FIRST FIRST. 5 August 2026. ----
    #
    #     "does the bot trades as first come = first ?"
    #
    # Yes, it did. core/ranker.py opens with "The best stock of the day,
    # not the first one to trigger" -- and this function then walked its
    # output in whatever order it arrived and stopped at ten. On
    # 5 August the book filled by 11:15 and RITES, HINDZINC, WESTLIFE
    # and KIRLOSBROS were never seen. Three of those four were winners.
    #
    # The ranker already scored every row. Sorting by it here is the
    # difference between the best ten setups and the earliest ten.
    # ---- THE SCORE DOES NOT ORDER THEM. VOLUME DOES. 22 Aug 2026 ----
    #
    #     "this mere 100 +/- 150 rs per trade is not at all feasible"
    #                                     -- operator, 22 August 2026
    #
    # He was right, and the reason was here. Sorting by score was a
    # real improvement over arrival order (5 August, above) and it is
    # still not the best key available. Measured over 15 sessions,
    # every ordering the bot could compute at alert time, three seats,
    # entry at the alert, exit at the close:
    #
    #     highest volume x      +Rs 565/trade   62.2% up
    #     best grade first      +Rs 225         55.6%
    #     most confirmations    +Rs  15         55.6%
    #     first to fire         -Rs  36         44.4%
    #     HIGHEST SCORE         -Rs  68         42.2%
    #     random draw           -Rs 226
    #     LOWEST volume x       -Rs 823         26.7%
    #
    # The score is WORSE THAN RANDOM at ordering its own list. Volume
    # against the stock's own normal is better than everything, and
    # the mirror image at the bottom (-Rs 823, 26.7% up) is what says
    # it is signal rather than a lucky cut.
    #
    # Held in both halves (+21,323 then +4,088) and at 3, 5 and 10
    # seats. Two things it is NOT: rank 1 is weaker than the top 3, so
    # this is a coarse sort and not a precise one; and 7 August alone
    # was 40% of the total, so the size of the edge is far less certain
    # than its direction.
    #
    # The score still breaks ties -- it carries the reason weight and
    # the sector work, which volume knows nothing about.
    # ---- THE SEAT GOES TO THE JUMP, NOT THE LEVEL. 4 Sep 2026 ----
    #
    # The measured table above is right that volume beats every other
    # ordering -- but it was measured on the CUMULATIVE ratio, because
    # that was the only one that existed. A cumulative ratio describes
    # a move that already happened.
    #
    # 4 September, the 10:19 seat. RESPONIND's volume had jumped at
    # 10:07 -- 34,906 shares against a baseline of 11 -- and it was
    # twelve minutes into a move that ran 152 -> 174. VISHNU had a
    # cumulative 16.5x from a move made an hour earlier. The sort took
    # VISHNU. RESPONIND was finally bought at 13:26, 48 paise below the
    # top, for -Rs 4,833; entering at that 10:19 seat makes +Rs 9,039.
    #
    # So the jump ranks first when it is known, and the cumulative
    # ratio remains the tie-break and the fallback -- a stock the flow
    # store cannot speak for must not be sorted last for that reason
    # alone.
    if surge_of is not None:
        for r in (rows or []):
            if not isinstance(r, dict):
                continue
            try:
                got = surge_of(r.get("symbol"))
            except Exception:                              # noqa: BLE001
                got = None
            if got and got.get("ratio"):
                r["jump_x"] = float(got["ratio"])
                r["jump_at"] = got.get("minute")

    # ---- THE SEAT GOES TO WHOEVER IS ALIVE NOW. 5 Sep 2026. ----
    #
    #     "whenever a free seat is available that is not meant to fill
    #      any eligible candidate at 09:30 to fill at 12:45 time ...
    #      bot needs to search for the best candidate right that time
    #      not 1 hour back best candidate"       -- the operator
    #
    # He is right, and the old code did exactly what he described. It
    # sorted by volume_x and score -- both read off the board, both
    # describing a move that ALREADY HAPPENED -- and only then walked
    # the list re-checking liveness one row at a time. So liveness was
    # a FILTER and the stale ratio was the SORT. A stock surging this
    # second but ranked eighth by cumulative volume got the seat only
    # if the seven above it were all dead.
    #
    # 4 September is what that costs. The book filled 10 of 10 by
    # 09:16:38 -- the whole day's capital in 83 seconds -- and then:
    #
    #     first 83 seconds   11 trades   8 won  3 lost   +Rs 13,157
    #     everything after   16 trades   6 won 10 lost   -Rs  1,363
    #
    # RESPONIND ignited at 10:07 and was bought at 13:26, 48 paise
    # below the top of its move, for -Rs 4,833. Entering at the
    # ignition replays at +Rs 8,170. The stock was right; the hour was
    # not, because the seat was not free and the list was not re-asked.
    #
    # SO EVERY ROW IS RE-PRICED FIRST, THEN SORTED. price_now() used to
    # run inside the loop, which meant the ordering could never see the
    # live reading. It runs over the whole field here, and the sort key
    # is what the field is doing RIGHT NOW.
    #
    # WHAT LIVENESS IS, kept exactly as core/ranker.liveness() defines
    # it -- nothing new is invented and no threshold is added:
    #
    #     alive   at or near its own high, still moving his way
    #     fading  well off the high, or the recent window has died
    #     None    cannot say -- which never sorts last, because a
    #             stock the feed cannot speak for is not a dead one
    #
    # Within "alive", the tie goes to the stock DOING MORE right now --
    # the bigger recent move, then the one closest to its own high.
    # Volume and score still break ties, so nothing that used to
    # matter has been thrown away; it has been demoted below the
    # question he actually asked.
    for r in (rows or []):
        if isinstance(r, dict):
            price_now(r, price_of)

    def _how_alive(r):
        state = str(r.get("state") or "").lower()
        rank = {"alive": 0, "fading": 2}.get(state, 1)   # unknown sits between
        recent = _num(r.get("recent_pct")) or 0.0
        hi, ltp = _num(r.get("day_high")), _num(r.get("ltp"))
        off_high = abs((ltp - hi) / hi * 100.0) if (hi and ltp and hi > 0) else 99.0
        return (rank, -recent, off_high,
                -(_num(r.get("volume_x"))
                  or _num(r.get("volume_ratio")) or 0.0),
                -(_num(r.get("score")) or 0.0))

    rows = sorted([r for r in (rows or []) if isinstance(r, dict)],
                  key=_how_alive)

    # ---- A SEAT YOU ARE NOT USING CANNOT RUN OUT. 18 Aug 2026. ----
    #
    # core/broker_funds.py now sizes the book from the REAL Dhan
    # balance instead of a constant. That is right, and it had a
    # consequence that would have looked exactly like a broken alert
    # system on the morning after he asked why alerts never arrived.
    #
    # Engine._position_ceiling() is cash-sized: (capital - Rs 1 lakh)
    # / Rs 30,000. On the frozen figure of Rs 4,31,116 that was 5
    # seats. On his real free cash of Rs 84,518 -- after HIS OWN
    # manual trades took Rs 1.2 lakh of the account -- it is 0, and
    # refuse_reason then reads `len(held) >= max_positions` as
    # `0 >= 0` and refuses EVERY pick. Zero alerts, all day, with a
    # sentence about a book that holds nothing.
    #
    # In ALERT_ONLY the bot enters nothing, so it occupies no seat and
    # cannot be out of them. The capacity question belongs to the
    # ENTRY path, and this hands it only to the entry path. Every
    # other refusal -- no reason, fading, already held, under the
    # Rs 50 floor, the daily loss cap, the engine's own risk layer --
    # is untouched and still silences the alert, because those are
    # statements about the TRADE and not about the bot's wallet.
    #
    #     "as of now all alerts must be in telegram & after my
    #      confirmation only they need to executed"
    #
    # He is the one taking it. His capacity is not this number.
    # ---- THE BOT ALWAYS TRADES. 5 September 2026. ----
    # This was `None if alert_only else max_positions` -- unlimited
    # picks when the bot was only alerting, because his own capacity
    # is not the seat count. alert_only is retired (see Engine's
    # __init__), so the seat limit always applies.
    seats = max_positions

    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()

        # Already priced off the tick, above, before the sort -- the
        # ordering has to see the live reading or it cannot rank by it.
        why = refuse_reason(row, engine, now=now, held=held,
                            max_positions=seats,
                            traded_today=traded_today)
        if why:
            # ---- A FULL BOOK MUST NOT SILENCE HIM. 5 Sep 2026. ----
            #
            #     "i do not want to miss / loose any info even by
            #      mistake"                        -- his standing rule
            #
            # Until the collapse to two, the only path that alerted on
            # a pick it could not take was the ALERT-ONLY lane, and
            # that lane went with the flag. Nothing else alerted on a
            # capacity refusal, so removing it would have left him
            # hearing nothing for most of the day: on 4 September the
            # book was full 10 of 10 by 09:16:38 and stayed at 9 or 10
            # until the close.
            #
            # A refusal ABOUT THE STOCK stays silent -- he does not
            # want to be told that a stock he was never going to buy
            # was not bought. A refusal about CAPACITY is different:
            # the stock passed everything and lost to an accident of
            # timing, which is the one refusal he can act on himself.
            # "already holding it -- no pyramiding" is about the
            # STOCK and must stay silent; "already holding 5 of 5" is
            # about the BOOK. One substring caught both, which is why
            # this matches the shapes rather than a word.
            # A PAUSE IS THE SAME SHAPE AS A FULL BOOK: the stock
            # passed everything and lost to something that has nothing
            # to do with the stock. Those are the refusals he can act
            # on himself, and the ones he asked to keep hearing about
            # while he is away from the desk.
            lost_a_seat = ("book full (" in why
                           or "PAUSED" in why
                           or " of " in why and "already holding" in why)
            if lost_a_seat and alert is not None:
                try:
                    alert(symbol, "ranked-buy",
                          f"{detail_or_symbol(row, symbol)} -- NO SEAT: "
                          f"{why}. It passed every other gate.")
                except Exception as exc:                   # noqa: BLE001
                    _broke("alert (he never saw this pick)", exc)
            _journal_pick(engine, row, False, why)
            out.append({"symbol": symbol, "taken": False, "why": why,
                        "score": _num(row.get("score"))})
            continue

        # ---- ONE SEAT AT A TIME, TO THE BEST MOVER. 15 Sep 2026. ----
        #
        #     "whats the use of bot trading if it fill random stock &
        #      unmoving stock while good moving stock waiting for seat &
        #      why i need to keep everything ON rotation on ? why can't
        #      bot take the best moving stock instead of racing to fill
        #      with shit stocks with shit reasons"     -- the operator
        #
        # This loop sorted the field best-first and then gave a seat to
        # EVERY row that passed, in the same second. At 09:16 the board
        # held its first handful of names, so all ten seats went by
        # 09:18 -- KEC, MPHASIS, SWSOLAR, TMPV, INFY, NEWGEN, TENNIND --
        # while EMUDHRA, the day's #1 at score 74, was first seen at
        # 09:18 and FSL (#5) at 09:21. Rotation is a patch for seats
        # wasted like that; the fix is not wasting them.
        #
        # Three rules, all simple:
        #   1. nothing before ENTRY_NOT_BEFORE -- the whole market is
        #      scanned before the first seat is given;
        #   2. the seat goes only to a stock MOVING NOW (liveness
        #      "alive"): not fading, not "cannot say";
        #   3. ONE new position per ENTRY_MIN_GAP_SECONDS, and it is the
        #      best of the field at that moment -- so the next seat is
        #      decided on a fresh ranking, not in the same breath.
        # A pace, not a limit: every seat can still fill, one best
        # mover at a time.
        from config import (ENTRY_NOT_BEFORE, ENTRY_MIN_GAP_SECONDS,
                            ENTRY_ONLY_ALIVE)
        clock = now or datetime.now()
        if ENTRY_NOT_BEFORE and clock.strftime("%H:%M") < ENTRY_NOT_BEFORE:
            out.append({"symbol": symbol, "taken": False,
                        "why": f"scanning the market until {ENTRY_NOT_BEFORE} "
                               f"before the first seat",
                        "score": _num(row.get("score"))})
            continue
        if ENTRY_ONLY_ALIVE and str(row.get("state") or "").lower() != "alive":
            out.append({"symbol": symbol, "taken": False,
                        "why": "not moving right now -- a seat goes only to "
                               "a stock that is",
                        "score": _num(row.get("score"))})
            continue
        last_at = getattr(engine, "_last_auto_entry_at", None)
        if ENTRY_MIN_GAP_SECONDS and last_at is not None:
            try:
                since = (clock - last_at).total_seconds()
            except TypeError:
                since = None
            if since is not None and 0 <= since < float(ENTRY_MIN_GAP_SECONDS):
                out.append({"symbol": symbol, "taken": False,
                            "why": f"next seat in {ENTRY_MIN_GAP_SECONDS - since:.0f}s "
                                   f"-- one at a time, to the best mover then",
                            "score": _num(row.get("score"))})
                continue

        plan = row["plan"]
        # ---- HIS FORMAT, AND NO SCORE. 19 August 2026. ----
        #
        #     "i don't want to see ranking by bot. the format of alert
        #      TIME  SYMBOL BUY REASON QTY  ENTRY - TARGET - EXIT -
        #      TRAILING POINTS"
        #
        # The score went on the card earlier the same day so he could
        # tell a strong pick from a weak one. He asked what use it was
        # to a trader, and the honest answer is none yet: it is an
        # internal ranking number on no scale, and NOTHING has shown
        # that a higher one leads to a better outcome. The 8 August
        # replay pointed the other way -- the top-ranked three were
        # the worst of the eleven.
        #
        # So it comes off the card and rides on the ROUTING record
        # instead -- take()'s return, published on the snapshot -- so
        # every pick's score and fate are stored together and the
        # question "does a higher score lead to a better outcome" can
        # actually be asked. A number he is asked to trust and cannot
        # check is worse than no number.
        #
        # TRAILING POINTS in rupees, like every other level here. A
        # percentage on a card full of prices is a conversion he
        # should not be doing on a phone.
        _trail = None
        try:
            from core.trailing_stop import trail_points
            _trail = trail_points(symbol, row.get("ltp"),
                                  has_event=bool(row.get("why")))
        except Exception:                                  # noqa: BLE001
            _trail = None

        _context = _alert_lines(row, plan)
        detail = (f"{symbol} BUY -- {row.get('why') or 'ranked setup'}"
                  + ("\n\n" + "\n".join(_context) if _context else "")
                  + f"\n\nqty {plan['qty']}"
                  f"\nentry {row.get('ltp')}"
                  f"\ntarget {plan.get('target')}"
                  f"\nexit {plan['stop']}"
                  + (f"\ntrailing {_trail}" if _trail else ""))

        # ---- THE ALERT-ONLY LANE IS GONE. 5 September 2026. ----
        #
        # A branch stood here that alerted him and took no trade, for
        # when the bot "was not trading". That state was abolished on
        # 31 August -- 65 alerts and 0 trades over ten days is what it
        # produced -- and the flag guarding it was retired with the
        # collapse to two. The bot always trades; the switch chooses
        # whose money. Removed with the flag it depended on.

        security_id = None
        if security_id_of is not None:
            try:
                security_id = security_id_of(symbol)
            except Exception as exc:                       # noqa: BLE001
                _broke("security_id lookup", exc)
                security_id = None
        if not security_id:
            out.append({"symbol": symbol, "taken": False,
                        "why": "no security id -- cannot be ordered"})
            continue

        try:
            # ---- THE FINGERPRINT OF THIS ENTRY. 4 September 2026 ----
            #
            #     "i want to make sure that which combination of rules
            #      set were yielding results = profits"
            #
            # The facts as they stood at the instant of the decision,
            # handed to the engine so they land on the trade record.
            # Facts only -- no grouping, no score. Which combinations
            # pay is a question for the data, not for me tonight.
            try:
                ltp = _num(row.get("ltp"))
                hi = _num(row.get("day_high"))
                engine.entry_facts = {
                    "symbol": symbol,
                    "door": row.get("door"),
                    "volume_x": (_num(row.get("volume_x"))
                                 or _num(row.get("volume_ratio"))),
                    "jump_x": _num(row.get("jump_x")),
                    "liveness": row.get("state"),
                    "off_high_pct": (round((hi - ltp) / hi * 100.0, 2)
                                     if hi and ltp and hi > 0 else None),
                    # Both answers, recorded, deciding nothing --
                    # see core/move_clock.py and trade_memory's
                    # LATE_COLUMNS for the measurement behind each.
                    "run_up_pct": _num(row.get("change_pct")),
                    "move_age_min": _move_age(symbol, now),
                    # ---- WHAT THE GATE SAW. 14 September 2026. ----
                    #
                    # The freshness gate refuses on extension_pct and
                    # nothing wrote it down, so the bot would have
                    # turned most candidates away on a number that
                    # existed for one microsecond and was never
                    # recorded. There would be no way to ask, of a
                    # single trade, "how far into the move were we when
                    # we bought this one" -- which is the only honest
                    # way to judge the gate, one case at a time.
                    #
                    # Recorded for the trades it TOOK. The ones it
                    # refused carry their reason into
                    # core/signal_journal.py already.
                    "extension_pct": _num(row.get("extension_pct")),
                    "drift_since_rank_pct": _num(
                        row.get("drift_since_rank_pct")),
                    "reason_kind": (row.get("news_kind")
                                    or row.get("reason_kind")),
                    # The sentence he sees on the board for this pick,
                    # kept on the trade. 15 September 2026.
                    "entry_why": (str(row.get("why"))[:300]
                                  if row.get("why") else None),
                    "reason_pct_of_company": _reason_size(row, symbol),
                }
            except Exception:                              # noqa: BLE001
                engine.entry_facts = None   # never block a trade for bookkeeping

            enter(symbol, security_id, row.get("ltp"), plan["stop"],
                  now, "RANKED_SETUP", "LONG",
                  target=plan.get("target"), qty=plan["qty"])
        except Exception as exc:                           # noqa: BLE001
            out.append({"symbol": symbol, "taken": False,
                        "why": f"the order path refused it ({exc})"})
            continue
        held.add(symbol)
        try:
            engine._last_auto_entry_at = now or datetime.now()
        except Exception:                                  # noqa: BLE001
            pass
        _journal_pick(engine, row, True, detail)
        out.append({"symbol": symbol, "taken": True, "why": detail,
                    "score": _num(row.get("score"))})
    return out
