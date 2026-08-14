"""
==========================================================
The move leads. The card supports. The grade never gates.
==========================================================

    "the chips grade excellent, great , good doesn't promise the
     movement in stock. thats not the real defination . i / bot needs
     to trade in the best moving stock with underlying card that
     supports the movement & if u remember some AVOID/WEAK stocks
     rallied too"
                                -- operator, 8 August 2026

WHAT THE DATA SAID
------------------
2,088 graded RESULT events measured against what the stock did the
next recorded session:

    GRADE        N     AVG NEXT DAY    AVG HIGH    WIN%
    GOOD       427        -0.64%         +2.41%     36%
    WEAK       288        +0.18%         +3.00%     50%
    OK         148        -0.05%         +2.57%     43%
    MIXED      133        +0.19%         +2.93%     49%
    EXCELLENT   83        -1.42%         +1.99%     39%
    GREAT       32        +0.15%         +2.37%     44%
    POOR         6        -1.46%         +1.63%     17%

EXCELLENT is the WORST bucket in the table. WEAK is among the best,
with the highest average intraday high of all.

That is "buy the rumour, sell the news" in his own data. An EXCELLENT
result is the one the market expected and already owns, so the print
is the exit. A WEAK result has nobody positioned in it, so anything
better than feared moves it.

THE TWO EARLIER VERSIONS, AND WHY BOTH WERE WRONG
-------------------------------------------------
    ranker.py   anything up 3% with any reason attached
                -> 15 trades, 0 targets hit, 12 drifted to the close

    select.py   the grade decides, the tape confirms
                (first version, 8 Aug)
                -> picked four EXCELLENTs on 6 August that did +1.35%,
                   +1.16%, +2.07%, +0.47%. The same mediocre drift,
                   from a different list. I built the thing he was
                   complaining about and pointed it at Row 1.

THIS VERSION
------------
    1. MOVEMENT leads -- and movement means the move is ALIVE:
       volume building against the stock's own normal, holding near
       the day's high, still extending. Not "it printed 3% at 09:30",
       which is how a finished move gets bought.

    2. A CARD IS REQUIRED. Results, order win, business update, news.
       The card is what separates a real move from noise. No card, no
       trade -- however pretty the chart.

    3. THE GRADE NEVER GATES. It is displayed, because he wants to see
       it, and it carries almost no weight, because the table above
       says it earns none. A WEAK result on 5x volume with a Rs 990
       crore order behind it is a better setup than an EXCELLENT that
       has already been bought.

WHAT IT STILL DOES NOT DO
-------------------------
Size, stop, or order. core/position_plan.py and core/auto_entry.py
keep those jobs unchanged, with every gate they already apply. This
decides WHO IS CONSIDERED and in what order.

Author : H&M Opportunity Trader
==========================================================
"""

# ---- WHAT MAKES A MOVE WORTH RIDING ----
# Weighted so that no single term can carry a stock on its own. The
# whole failure being corrected is a scorer where one term -- raw
# move % -- decided everything.
# ---- VALUES LIVE IN core/rules.py. 11 August 2026. ----
# Named SELECT_W_* there. They disagreed with core/ranker.py's W_VOLUME
# under the same name for days and read as a bug -- the two score on
# different scales and are supposed to differ.
from core.rules import (
    SELECT_W_VOLUME as W_VOLUME,        # building against its own normal
    SELECT_W_EXTENDING as W_EXTENDING,  # still making highs, not fading
    SELECT_W_MOVE as W_MOVE,            # the move itself, NOT dominant
    SELECT_W_CARD as W_CARD,            # strength of the reason behind it
)

# ---- THE GRADE ----
# Measured to have no predictive value for next-day movement, and
# EXCELLENT measured WORSE than WEAK. So it is carried for display and
# given a weight of zero.
#
# Zero, not negative. Reading -1.42% off 83 observations and betting
# against EXCELLENT would be fitting a constant to a small sample --
# exactly the mistake this file exists to undo.
W_GRADE = 0.0

# A move must be alive, not finished. These describe LIVENESS, not
# size: a stock up 1.5% on 4x volume still making highs is a better
# candidate than one up 6% that peaked an hour ago.
# ---- AN UNEXPLAINED MOVE IS STILL A MOVE. 8 August 2026. ----
# Volume this far above a stock's own normal is evidence in itself:
# somebody is trading it hard for a reason that has not been published
# yet.
#
# MIN_MOVE_PCT here is measured FROM TODAY'S OPEN -- see movement()
# below -- which is NOT what core/ranker.py's threshold of the same
# name measured. They were different rules sharing a name for days.
from core.rules import (
    MIN_VOLUME_RATIO,
    UNEXPLAINED_MIN_VOLUME_RATIO as UNEXPLAINED_VOLUME,
    MIN_MOVE_FROM_OPEN_PCT as MIN_MOVE_PCT,
    FADED_FROM_HIGH,          # below half its day range = the move is over
)

# ---- THE CLOCK HAS STRUCTURE. 8 August 2026. ----
#
#     "you need to understand the markets layer by layers"
#
# Researched 8 August. Two kinds of intraday movement, and they behave
# in opposite ways:
#
#   morning momentum   = overnight news still being priced in
#                        -> CONTINUES
#   afternoon momentum = temporary price pressure, no new information
#                        -> REVERSES
#
# The opening drive 09:15-10:30 is where volume peaks and the day's
# biggest moves happen. 10:30-14:30 is thin: little new information
# arrives, so a move there is usually pressure, not news.
#
# Every trade the bot took was timed 09:50, 10:10, 10:15, 11:35,
# 12:00, 12:05 -- almost entirely in the dead zone, on 1.2-1.9x
# volume. It was systematically buying the REVERTING kind. That
# explains 12 of 15 drifting to the close better than any change I
# made to the scorer.
from datetime import time as _t

DRIVE_OPEN = _t(9, 15)      # overnight news being priced
DRIVE_END = _t(10, 30)
DEAD_END = _t(14, 30)       # institutions adjust after this

# In the thin middle a move needs MORE proof, not the same. It is not
# forbidden -- an event can land at 11:40 -- but drifting on ordinary
# volume there is the reverting kind.
DEAD_ZONE_VOLUME = 3.0

# Nowhere left to run. See core/headroom.py.
MIN_HEADROOM_PCT = 2.0


def _num(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if value != value else value


def movement(tape):
    """Is this move ALIVE, and how strong? {"ok","score","why"}.

    `tape`: ltp, day_open, day_high, day_low, volume_ratio.
    """
    tape = tape or {}
    ltp = _num(tape.get("ltp"))
    day_open = _num(tape.get("day_open"))
    day_high = _num(tape.get("day_high"))
    day_low = _num(tape.get("day_low"))
    ratio = _num(tape.get("volume_ratio")) or 0.0

    if ltp is None or not day_open:
        return {"ok": False, "score": 0.0, "why": "no price"}

    move = (ltp - day_open) / day_open * 100.0

    if move < MIN_MOVE_PCT:
        return {"ok": False, "score": 0.0, "move_pct": round(move, 2),
                "why": f"up only {move:.1f}% -- not moving"}
    if ratio < MIN_VOLUME_RATIO:
        return {"ok": False, "score": 0.0, "move_pct": round(move, 2),
                "why": f"{ratio:.1f}x volume -- the move has no "
                       f"participation"}

    # ---- IS IT STILL GOING, OR IS IT OVER? ----
    # This is the term the old ranker never had, and the reason it kept
    # buying finished moves. A stock that ran and faded has the same
    # change% as one still extending -- and is a completely different
    # trade.
    position = None
    if day_high and day_low and day_high > day_low:
        position = (ltp - day_low) / (day_high - day_low)
        if position < FADED_FROM_HIGH:
            return {"ok": False, "score": 0.0, "move_pct": round(move, 2),
                    "why": f"faded to {position:.0%} of its day range -- "
                           f"the move is over"}

    score = 0.0
    bits = []
    score += W_VOLUME * min((ratio - 1.0) / 3.0, 1.0)
    bits.append(f"{ratio:.1f}x volume")
    if position is not None:
        score += W_EXTENDING * position
        bits.append(f"holding {position:.0%} of its range")
    score += W_MOVE * min(move / 6.0, 1.0)
    bits.append(f"up {move:.1f}%")

    return {"ok": True, "score": round(score, 3), "why": ", ".join(bits),
            "move_pct": round(move, 2), "position": position}


def card_weight(reason):
    """How much the underlying card supports this move, 0..1.

    core/why_moving.py already grades its own sources -- a published
    result carries more than an unexplained volume spike. This reads
    that rather than inventing a second opinion.
    """
    if not isinstance(reason, dict):
        return 0.0
    weight = _num(reason.get("weight"))
    return max(0.0, min(weight if weight is not None else 0.4, 1.0))


def when(clock):
    """Which part of the session is this, and what does it demand?"""
    if clock is None:
        return {"phase": "unknown", "min_volume": MIN_VOLUME_RATIO}
    t = clock.time() if hasattr(clock, "time") else clock
    if DRIVE_OPEN <= t < DRIVE_END:
        return {"phase": "opening drive", "min_volume": MIN_VOLUME_RATIO,
                "why": "overnight news still being priced"}
    if t >= DEAD_END:
        return {"phase": "closing", "min_volume": MIN_VOLUME_RATIO,
                "why": "institutions adjusting"}
    return {"phase": "thin middle", "min_volume": DEAD_ZONE_VOLUME,
            "why": "little new information -- a move here is usually "
                   "pressure, not news"}


def pick(movers, reason_of=None, grade_of=None, held=None, top=6,
         eligible_of=None, now=None, headroom_of=None):
    """The best MOVING stocks that have a card behind them.

    movers      [{"symbol","ltp","day_open","day_high","day_low",
                  "volume_ratio"}] -- every eligible stock, not Row 1
    reason_of   symbol -> {"text","weight"} or None   REQUIRED to pass
    grade_of    symbol -> "EXCELLENT"/"WEAK"/...      display only
    eligible_of symbol -> True/False                  universe gate

    Returns {"rows", "considered", "refusals"}.
    """
    held = {str(s).upper() for s in (held or [])}
    rows, refused = [], {}

    for mover in (movers or []):
        if not isinstance(mover, dict):
            continue
        symbol = str(mover.get("symbol") or "").upper()
        if not symbol:
            continue
        if symbol in held:
            refused[symbol] = "already holding it"
            continue
        if eligible_of is not None:
            try:
                if not eligible_of(symbol):
                    refused[symbol] = "not in the tradeable universe"
                    continue
            except Exception:                              # noqa: BLE001
                refused[symbol] = "eligibility could not be read"
                continue

        alive = movement(mover)
        if not alive["ok"]:
            refused[symbol] = alive["why"]
            continue

        # LAYER: the clock. A move in the thin middle needs more.
        phase = when(now)
        ratio = _num(mover.get("volume_ratio")) or 0.0
        if ratio < phase["min_volume"]:
            refused[symbol] = (f"{phase['phase']} -- {ratio:.1f}x volume is "
                               f"not enough here ({phase.get('why','')})")
            continue

        # LAYER: is there anywhere left to go today?
        if headroom_of is not None:
            try:
                room = headroom_of(symbol)
            except Exception:                              # noqa: BLE001
                room = None
            if room and room.get("ok") and \
                    room.get("headroom_pct", 99) < MIN_HEADROOM_PCT:
                refused[symbol] = room.get("why") or "at its circuit"
                continue

        # ---- THE CARD IS NOT OPTIONAL ----
        #     "trade in the best moving stock with underlying card that
        #      supports the movement"
        reason = None
        if reason_of is not None:
            try:
                reason = reason_of(symbol)
            except Exception:                              # noqa: BLE001
                reason = None
        reason_text = (reason or {}).get("text") \
            if isinstance(reason, dict) else None
        if not reason_text:
            refused[symbol] = "moving, but nothing behind it"
            continue

        grade = None
        if grade_of is not None:
            try:
                grade = (grade_of(symbol) or "").upper() or None
            except Exception:                              # noqa: BLE001
                grade = None

        support = card_weight(reason)
        score = alive["score"] + W_CARD * support + W_GRADE * 0.0

        rows.append({
            "symbol": symbol, "action": "BUY",
            "score": round(score, 3),
            "grade": grade,
            "move_pct": alive.get("move_pct"),
            "moving": alive["why"],
            "why": reason_text,
            "ltp": mover.get("ltp"),
            "day_open": mover.get("day_open"),
            "day_high": mover.get("day_high"),
            "day_low": mover.get("day_low"),
        })

    rows.sort(key=lambda r: (-r["score"], r["symbol"]))
    return {"rows": rows[:top], "considered": len(movers or []),
            "refusals": refused}
