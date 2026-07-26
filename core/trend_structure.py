"""
==========================================================
Trend Structure -- what shape has this stock been making?
==========================================================

The operator's description, which is exactly classical price-action
market structure:

    "some stocks make higher highs on day to day basis. once that
     formation stopped and forms higher low then lower low formation
     causes the reversal / range boundness in stocks."
     -- reference names: PARAS, KALYANKJIL, DATAPATTERNS

So: compare each day's HIGH and LOW to the previous day's, and read the
sequence.

    higher high + higher low   -> UP leg      (the staircase up)
    lower high  + lower low    -> DOWN leg    (the staircase down)
    higher high + lower low    -> OUTSIDE day (expansion, volatility)
    lower high  + higher low   -> INSIDE day  (contraction, coiling)

A run of UP legs is a trend. A trend that stops making higher highs and
then breaks the previous day's low is a BREAK OF STRUCTURE -- the moment
the operator is pointing at, where continuation stops being the base
case.

WHY THIS IS NOT WIRED AS AN ENTRY GATE (yet)
--------------------------------------------
Because I have been wrong before by shipping a rule that "obviously"
made sense. On 2026-07-24 I claimed the data supported the "still
trending" rule; measured properly against the market baseline, those
stocks had UNDERPERFORMED by 0.55%. A plausible mechanism is not
evidence.

So this module DESCRIBES, it does not vote. The label is computed
before the open, recorded against every trade the bot takes, and after
a few weeks we can ask the only question that matters: did trades taken
in UPTREND structure actually do better than trades taken in RANGE?

If they did, wiring it as a gate is a one-line change. If they didn't,
we deleted nothing and learned something. Same discipline as
core/trade_memory.py, which also deliberately has no vote.

Author : H&M Opportunity Trader
==========================================================
"""

UP_LEG = "UP"            # higher high AND higher low
DOWN_LEG = "DOWN"        # lower high AND lower low
OUTSIDE = "OUTSIDE"      # higher high AND lower low -- expansion
INSIDE = "INSIDE"        # lower high AND higher low -- contraction

STRONG_UP = "STRONG_UP"
UPTREND = "UPTREND"
RANGE = "RANGE"
DOWNTREND = "DOWNTREND"
STRONG_DOWN = "STRONG_DOWN"
UNKNOWN = "UNKNOWN"      # not enough history

# A run this long, unbroken, is what "makes higher highs day on day"
# means in the operator's description.
STRONG_RUN = 3


def leg(prev, cur):
    """Classify one day against the day before it."""
    hh = cur["high"] > prev["high"]
    hl = cur["low"] > prev["low"]
    if hh and hl:
        return UP_LEG
    if not hh and not hl:
        return DOWN_LEG
    if hh and not hl:
        return OUTSIDE
    return INSIDE


def analyse(bars):
    """
    bars: daily candles OLDEST FIRST, each with high/low/close.

    Returns a dict describing the shape. Never raises, never predicts.

        structure          STRONG_UP / UPTREND / RANGE / DOWNTREND /
                           STRONG_DOWN / UNKNOWN
        legs               per-day labels, oldest first
        up_legs/down_legs  counts
        hh_streak          consecutive higher highs ending today
        ll_streak          consecutive lower lows ending today
        broke_structure    "UP" if an up-run just broke its last low,
                           "DOWN" if a down-run just broke its last
                           high, else None. THE reversal signal the
                           operator described.
        pct_from_high      how far below the window's high we closed
        pct_from_low       how far above the window's low we closed
        days_since_high    0 = the window high was made today
    """
    bars = [b for b in (bars or [])
            if b.get("high") is not None and b.get("low") is not None
            and b.get("close") is not None]

    if len(bars) < 3:
        return dict(structure=UNKNOWN, legs=[], up_legs=0, down_legs=0,
                    hh_streak=0, ll_streak=0, broke_structure=None,
                    pct_from_high=None, pct_from_low=None,
                    days_since_high=None, bars=len(bars))

    legs = [leg(bars[i - 1], bars[i]) for i in range(1, len(bars))]
    up_legs = legs.count(UP_LEG)
    down_legs = legs.count(DOWN_LEG)

    # Streaks of higher highs / lower lows ending on the latest bar.
    hh_streak = 0
    for i in range(len(bars) - 1, 0, -1):
        if bars[i]["high"] > bars[i - 1]["high"]:
            hh_streak += 1
        else:
            break
    ll_streak = 0
    for i in range(len(bars) - 1, 0, -1):
        if bars[i]["low"] < bars[i - 1]["low"]:
            ll_streak += 1
        else:
            break

    # -- BREAK OF STRUCTURE -------------------------------------------
    # The operator's exact case: it was stepping up (higher highs), then
    # the steps stopped AND it took out the prior day's low. One bar
    # failing to make a new high is just a pause; a failed high plus a
    # broken low is the character change.
    broke = None
    if len(legs) >= 3:
        earlier = legs[:-1]
        last = bars[-1]
        prior = bars[-2]
        earlier_up = earlier.count(UP_LEG)
        earlier_down = earlier.count(DOWN_LEG)
        # STRICT MAJORITY, not just "enough". The first version used
        # >= max(2, len//2), which called a 3-UP / 3-DOWN window an
        # uptrend -- so PARAS (legs DOWN DOWN UP UP UP DOWN DOWN, real
        # data 2026-07-24) was reported as "making lower highs and lower
        # lows (UPTREND JUST BROKE)". Both at once, which is nonsense.
        # A tie is not a trend, so there is nothing to break.
        was_up = earlier_up > earlier_down and earlier_up >= 2
        was_down = earlier_down > earlier_up and earlier_down >= 2
        failed_high = last["high"] <= prior["high"]
        failed_low = last["low"] >= prior["low"]
        if was_up and failed_high and last["low"] < prior["low"]:
            broke = "UP"          # an uptrend just broke down
        elif was_down and failed_low and last["high"] > prior["high"]:
            broke = "DOWN"        # a downtrend just broke up

    # -- overall label -------------------------------------------------
    if hh_streak >= STRONG_RUN and up_legs > down_legs and broke is None:
        structure = STRONG_UP
    elif ll_streak >= STRONG_RUN and down_legs > up_legs and broke is None:
        structure = STRONG_DOWN
    elif up_legs >= 2 and up_legs > down_legs:
        structure = UPTREND
    elif down_legs >= 2 and down_legs > up_legs:
        structure = DOWNTREND
    else:
        structure = RANGE

    # A confirmed break of an uptrend is no longer an uptrend, whatever
    # the leg counts say -- that is the whole point of noticing it.
    if broke == "UP" and structure in (STRONG_UP, UPTREND):
        structure = RANGE
    if broke == "DOWN" and structure in (STRONG_DOWN, DOWNTREND):
        structure = RANGE

    window_high = max(b["high"] for b in bars)
    window_low = min(b["low"] for b in bars)
    close = bars[-1]["close"]
    high_index = max(range(len(bars)), key=lambda i: bars[i]["high"])

    return dict(
        structure=structure,
        legs=legs,
        up_legs=up_legs,
        down_legs=down_legs,
        hh_streak=hh_streak,
        ll_streak=ll_streak,
        broke_structure=broke,
        pct_from_high=(close - window_high) / window_high * 100
        if window_high else None,
        pct_from_low=(close - window_low) / window_low * 100
        if window_low else None,
        days_since_high=len(bars) - 1 - high_index,
        bars=len(bars),
    )


def describe(result):
    """One plain-English line, for logs and the dashboard."""
    s = result.get("structure")
    if s == UNKNOWN:
        return "not enough daily history yet"
    parts = {
        STRONG_UP: f"stepping UP -- {result['hh_streak']} higher highs in a row",
        UPTREND: "making higher highs and higher lows",
        RANGE: "range-bound / no clear structure",
        DOWNTREND: "making lower highs and lower lows",
        STRONG_DOWN: f"stepping DOWN -- {result['ll_streak']} lower lows in a row",
    }
    line = parts.get(s, s)
    if result.get("broke_structure") == "UP":
        line += " (UPTREND JUST BROKE -- failed high, then took out the prior low)"
    elif result.get("broke_structure") == "DOWN":
        line += " (DOWNTREND JUST BROKE -- failed low, then took out the prior high)"
    return line
