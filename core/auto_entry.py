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
from datetime import time as dtime

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
    adv = _num(row.get("adv_cr"))
    if adv is not None:
        room.append(f"Rs {adv:.1f}cr traded on a normal day")
    if room:
        lines.append(" | ".join(room))

    tilt_why = str(row.get("commodity_tilt_why") or "").strip()
    if tilt_why:
        lines.append(tilt_why)

    return lines


def refuse_reason(row, engine, now=None, held=None, max_positions=None):
    """Why this pick must NOT be taken, or None if it may be.

    Returns a plain sentence, because every refusal is shown to him.
    """
    symbol = str(row.get("symbol") or "").upper()
    if not symbol:
        return "no symbol on the row"

    # LONG ONLY. "i only trade in long positions".
    if str(row.get("action") or "").upper() != "BUY":
        return "not a long -- he does not short"

    plan = row.get("plan") or {}
    if not plan.get("ok"):
        return str(plan.get("why") or "no tradeable plan")
    if not plan.get("qty") or not plan.get("stop"):
        return "the plan carries no quantity or no stop"

    # liveness() said the move has stopped working. It must not be
    # possible to enter one of these from any path.
    if row.get("state") == "fading":
        return "fading -- the move has already stopped working"

    held = {str(s).upper() for s in (held or [])}
    if symbol in held:
        return "already holding it -- no pyramiding"

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
    if SUPPLY_GATE:
        try:
            from core import supply_events
            sold = supply_events.overhang(symbol, now=now)
        except Exception as exc:                           # noqa: BLE001
            _broke("supply_events -- refusing rather than trading blind", exc)
            return ("could not check for an offer for sale -- refusing "
                    "rather than buying into somebody's exit")
        if sold:
            return sold["why"]

    clock = _clock(now)
    if clock is not None:
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
            if getattr(engine, "alert_only", True):
                return (f"book full ({len(held)} of {max_positions}) and "
                        f"the bot is not trading -- no seat can be freed "
                        f"while trading is OFF")
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


def take(rows, engine, now=None, security_id_of=None, held=None,
         max_positions=None, alert=None, enter=None):
    """Route the ranker's picks into the order path.

    `enter` and `alert` are injected so this can be exercised without
    an engine and without a broker. In production they are the
    Engine's own methods -- nothing here reimplements an entry.

    Returns a list of {"symbol", "taken", "why"} for the record. It
    never raises: this runs on the trading loop.
    """
    out = []
    held = set(str(s).upper() for s in (held or []))
    alert_only = bool(getattr(engine, "alert_only", True))

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
    rows = sorted(
        [r for r in (rows or []) if isinstance(r, dict)],
        key=lambda r: (-(_num(r.get("volume_x"))
                         or _num(r.get("volume_ratio")) or 0.0),
                       -(_num(r.get("score")) or 0.0)))

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
    seats = None if alert_only else max_positions

    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        why = refuse_reason(row, engine, now=now, held=held,
                            max_positions=seats)
        if why:
            _journal_pick(engine, row, False, why)
            out.append({"symbol": symbol, "taken": False, "why": why,
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

        # ---- ALERT_ONLY_MODE IS UNTOUCHED BY THIS CHANGE ----
        # Connecting the two halves and switching the safety off are
        # separate decisions and must never ride in together.
        if alert_only:
            if alert is not None:
                try:
                    alert(symbol, "ranked-buy",
                          detail + " -- ALERT ONLY: the bot is not "
                                   "trading. Use the dashboard BUY.")
                except Exception as exc:                   # noqa: BLE001
                    _broke("alert (he never saw this pick)", exc)
            _journal_pick(engine, row, False,
                          "ALERT ONLY -- alerted, operator decides")
            out.append({"symbol": symbol, "taken": False,
                        "score": _num(row.get("score")),
                        "why": "ALERT ONLY -- bot not trading, "
                               "operator decides"})
            continue

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
            enter(symbol, security_id, row.get("ltp"), plan["stop"],
                  now, "RANKED_SETUP", "LONG",
                  target=plan.get("target"), qty=plan["qty"])
        except Exception as exc:                           # noqa: BLE001
            out.append({"symbol": symbol, "taken": False,
                        "why": f"the order path refused it ({exc})"})
            continue
        held.add(symbol)
        _journal_pick(engine, row, True, detail)
        out.append({"symbol": symbol, "taken": True, "why": detail,
                    "score": _num(row.get("score"))})
    return out
