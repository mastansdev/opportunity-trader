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

# analyse() needs three bars to name a structure, so this is 45
# minutes of session -- a first reading at about 10:00.
MIN_BLOCKS = 3


def blocks(series, minutes=BLOCK_MINUTES):
    """Group a minute series into blocks carrying high/low/close.

    series: [{"minute": "09:15", "ltp": 598.1}, ...] oldest first.
    Rows without a price are skipped -- a minute nothing traded in is
    not a flat minute, it is an absent one.
    """
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


def today(symbol=None, series=None, date=None, db_path=None):
    """Today's shape for one stock, or None.

        {"structure": "UPTREND",         same words as the 7-day read
         "text": "going up since 11:40", what the board prints
         "since": "11:40",
         "blocks": 9}

    None means not enough of the session has traded yet, and that is
    the honest answer before about 10:00 -- not "sideways", which is a
    claim.

    `series` is accepted so the caller can supply minutes it already
    holds; otherwise today's are read from the order flow store.
    """
    if series is None:
        try:
            from core.order_flow import session_series
            series = session_series(symbol, date=date, db_path=db_path)
        except Exception:                                  # noqa: BLE001
            return None

    bars = blocks(series)
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
            "blocks": len(bars), "broke": broke}
