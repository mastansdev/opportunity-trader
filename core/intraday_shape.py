"""What shape is this stock making TODAY?

    "stock displayed on dashboard is not showing its price action
     (uptrend , downtrend, sideways)"   -- operator, 30 August 2026

core/trend_structure.py has classified every stock's SEVEN DAY shape
for weeks, and since 24 August that has been a chip on the board. It
answers a different question from the one he is asking. A stock can be
STRONG_UP on daily bars and have been going sideways since 10:20 this
morning, and it is the second fact that decides whether to hold it
through lunch.

SAME METHOD, DIFFERENT CLOCK. This does not invent a second way of
reading a trend. It groups today's minutes into fifteen-minute blocks
and hands them to trend_structure.analyse() -- the same higher-high /
lower-low test, on blocks instead of days. So "climbing" means the
same thing on both readings, and the two can be compared without a
translation.

Fifteen minutes, not thirty: analyse() needs three bars, so thirty
would say nothing until 10:45. A day trader who cannot get a reading
until the session is a quarter gone has no reading.

NO AVERAGING ANYWHERE.

    "never pool all stocks , never average the stocks data. thats not
     stock working mechanism"                        -- the operator

A block's high is the highest price traded in it and its low is the
lowest. Nothing is meaned, and one stock is never mixed with another.

Author : H&M Opportunity Trader
"""

BLOCK_MINUTES = 15

# analyse() needs three bars to name a structure. Blocks slot on the
# wall clock -- 09:15, 09:30, 09:45 -- so the third completes at 09:45
# and that is when the first reading appears.
MIN_BLOCKS = 3

# ==========================================================
# HOW EARLY IS THIS WORTH READING?  30 August 2026.
# ==========================================================
#
#     "why we need to wait until 10 ? who ordered that & reason"
#                                         -- the operator
#
# Nobody ordered it, and 10:00 was wrong as well: the first reading
# lands at 09:45. But the honest answer to his question turned out to
# be about TRUST, not timing, so it was measured rather than argued.
#
# Six sessions (21-28 August), the 120 most-traded stocks, 5,040
# readings. The test is not "does it predict the close" -- the label
# describes what has happened so far, and a day that changes should
# change it. The test is whether it STAYS PUT long enough to act on:
# does the reading at T still stand at T+30 minutes?
#
#     block     09:30  09:45  10:00  10:30  11:00  12:00  13:30
#      5 min      35%    45%    51%    56%    59%    67%    68%
#     15 min       --    45%    48%    59%    66%    70%    75%
#
# Fifteen wins from 10:30 on, which is why the block size stays. But
# at 09:45 the label is a coin flip, and a screen that shows an
# unsettled reading the same way as a settled one is lying by layout.
#
# Seven blocks is 10:50, the point the measurement crosses 60%.
# Before that the reading is given AND marked.
SETTLED_BLOCKS = 7


def blocks(series, minutes=None):
    """Group a minute series into blocks carrying high/low/close.

    `minutes` defaults to BLOCK_MINUTES, read AT CALL TIME. Binding it
    as a default argument -- which is how this was first written --
    freezes it at import, so setting the module constant to measure a
    different block size silently changed nothing and three sizes
    produced identical results.

    series: [{"minute": "09:15", "ltp": 598.1}, ...] oldest first.
    Rows without a price are skipped -- a minute nothing traded in is
    not a flat minute, it is an absent one.
    """
    minutes = int(minutes or BLOCK_MINUTES)
    held, out = None, []
    for row in (series or []):
        price = row.get("ltp")
        if price is None:
            continue
        try:
            price = float(price)
            hh, mm = str(row.get("minute") or "").split(":")
            slot = (int(hh) * 60 + int(mm)) // minutes
        except (TypeError, ValueError):
            continue
        if held is None or held["slot"] != slot:
            if held is not None:
                out.append(held)
            held = {"slot": slot, "at": row["minute"], "high": price,
                    "low": price, "close": price}
            continue
        held["high"] = max(held["high"], price)
        held["low"] = min(held["low"], price)
        held["close"] = price
    if held is not None:
        out.append(held)
    return out


def _since(bars, legs, direction):
    """When the CURRENT run began -- the start of the last unbroken
    stretch of `direction`, walking back from now.

    None when the run reaches the first block, which is what lets the
    card say "all session" instead of naming the open as if something
    changed there.
    """
    if not legs:
        return None
    i = len(legs) - 1
    while i >= 0 and legs[i] == direction:
        i -= 1
    if i < 0:
        return None                     # unbroken since the open
    return bars[i + 1]["at"]


def describe(structure, since, broke=None):
    """The line the board prints, in day-to-day words.

        "going up all session"
        "going up since 11:40"
        "sideways since 10:20"
        "was going up, turned at 14:05"
    """
    if broke == "UP":
        return f"was going up, turned at {since}" if since else "just turned down"
    if broke == "DOWN":
        return f"was going down, turned at {since}" if since else "just turned up"

    words = {"STRONG_UP": "going up", "UPTREND": "going up",
             "RANGE": "sideways", "DOWNTREND": "drifting down",
             "STRONG_DOWN": "going down"}.get(structure)
    if not words:
        return None
    return f"{words} since {since}" if since else f"{words} all session"


def today(symbol=None, series=None, date=None, db_path=None, minutes=None):
    """Today's shape for one stock, or None.

        {"structure": "UPTREND",         same words as the 7-day read
         "text": "going up since 11:40", what the board prints
         "since": "11:40",
         "blocks": 9}

    None means not enough of the session has traded yet, and that is
    the honest answer before 09:45 -- not "sideways", which is a claim.

    `settled` is False until roughly 10:50. The reading before that is
    real but flips within half an hour about as often as it holds, and
    the caller is expected to say so rather than print it plainly.

    `series` is accepted so the caller can supply minutes it already
    holds; otherwise today's are read from the order flow store.
    """
    if series is None:
        try:
            from core.order_flow import session_series
            series = session_series(symbol, date=date, db_path=db_path)
        except Exception:                                  # noqa: BLE001
            return None

    bars = blocks(series, minutes=minutes)
    if len(bars) < MIN_BLOCKS:
        return None

    try:
        from core.trend_structure import analyse, leg, UP_LEG, DOWN_LEG
    except Exception:                                      # noqa: BLE001
        return None

    got = analyse(bars) or {}
    structure = got.get("structure")
    if not structure or structure == "UNKNOWN":
        return None

    legs = [leg(bars[i - 1], bars[i]) for i in range(1, len(bars))]
    direction = UP_LEG if structure in ("STRONG_UP", "UPTREND") else (
        DOWN_LEG if structure in ("STRONG_DOWN", "DOWNTREND") else None)
    since = _since(bars, legs, direction) if direction else (
        bars[max(0, len(bars) - 3)]["at"])

    broke = got.get("broke_structure")
    text = describe(structure, since, broke)
    if not text:
        return None
    return {"structure": structure, "text": text, "since": since,
            "blocks": len(bars), "broke": broke,
            # False until about 10:50. Measured, not guessed -- see
            # SETTLED_BLOCKS above. The reading is still shown; it is
            # the certainty that is withheld, not the fact.
            "settled": len(bars) >= SETTLED_BLOCKS}
