"""
==========================================================
Where the stop goes, and how far the target can be
==========================================================

    "how to resolve that & whats the target we aimed for?"
                                -- operator, 8 August 2026

THE PROBLEM, IN TWO DISGUISES
-----------------------------
core/position_plan.py puts the stop at THE DAY'S LOW, and the target
at twice that distance. The day's low is meaningless at both ends of
the morning, so the same rule fails in opposite directions:

    enter 09:30   the day's low sits below a move that already
                  happened -> stop 5.3% away, target 10.6% away,
                  tiny position, target never reachable

    enter 09:16   the day's low is one candle old -> SHILPAMED's stop
                  was 5 PAISE below the entry, which sized the
                  position at 30,000 shares before the rule refused it

Measured across 36 replayed trades and three different selectors:
ZERO targets ever reached. Not one.

WHAT THE STOCKS ACTUALLY DO
---------------------------
7,709 liquid stock-days from his own tape:

    dip below the open before running     median 1.01%
                                          75th   1.84%
                                          90th   2.98%

    daily range, high to low              median 2.55%
                                          75th   3.74%
                                          90th   5.40%
                                          mean   3.10%

So a stop must survive about 1.8% of ordinary noise, and a target has
to sit inside about 2.5-3.5% or it is aiming past what the stock does
on a normal day.

THE RULE HERE
-------------
    stop     entry x (1 - 1.8%)      survives 3 of 4 normal dips
    target   entry x (1 + 3.0%)      inside the normal daily range

Both derived from behaviour that exists BEFORE the open, so they work
identically at 09:16 and at 14:00 -- which the day's low never could.

    risk 1.8%  ->  reward 3.0%  ->  1.67 : 1

VARROC on 7 August is the shape this is copying: stop 2.7%, target
5.4%, hit in nine minutes for Rs 3,000. The only target ever reached
in any replay.

WHAT IS STILL RESPECTED
-----------------------
The circuit. A target above the upper band is arithmetic that cannot
happen -- see core/headroom.py -- so it is capped there and the trade
is refused if the capped target no longer pays for the risk.

    "MADE TO LOOSE SMALL INCASE OF LOSS & WIN BIG ON WINNING STOCKS"

Losing small is the stop. Winning big is holding to a target that can
actually be reached, instead of one that cannot.

Author : H&M Opportunity Trader
==========================================================
"""

# ---- FROM 7,709 STOCK-DAYS OF HIS OWN TAPE ----
# The 75th percentile dip. A stop here survives three ordinary
# mornings in four; tighter and normal noise takes the trade out
# before the move starts.
STOP_PCT = 1.8

# Inside the median daily range of 2.55% and below the 75th at 3.74%.
# Deliberately NOT a multiple of the stop -- that is the arithmetic
# that produced 10.6% targets on a stock that moves 2%.
# ---- 2:1, AGREED WITH THE OPERATOR. 8 August 2026. ----
#     "i too agree with 2:1 ratio"
# So the target is exactly twice the stop, not an independent number.
# At the 1.8% stop that lands on 3.6% -- inside the 75th-percentile
# daily range of 3.74%, so it is reachable on an ordinary day.
TARGET_PCT = 3.6
REWARD_RATIO = 2.0

# Below this the reward does not pay for the risk. 1.2 is deliberately
# lower than the 1.67 the defaults give, so a circuit cap can shave
# the target a little without killing an otherwise good trade.
MIN_REWARD = 1.5

# A stock's own range can justify a wider stop, but only so far. Past
# this it is not a stop, it is hope.
MAX_STOP_PCT = 3.0

# ==========================================================
# BOOK 1:1 WHEN IT COMES BACK FROM NEAR THE TARGET
# ==========================================================
#
#     "in 2:1 ration if the stock is falling after reaching nearby rs
#      & started retrace back book at 1:1 profit (something is better
#      than nothing)"
#                                -- operator, 8 August 2026
#
# WHAT THE BLANKET TRAIL DOES INSTEAD
# -----------------------------------
# config.PEAK_TRAIL_PCT is 2.5% and the target is 3.6%. The trail sits
# BELOW the halfway mark of its own target, so any ordinary pullback
# ends the trade for almost nothing. DEEPAKNTR, 7 August:
#
#     entry 1774.90   peak 1832.70 (+3.26%, that is 1.81R)
#     2.5% trail      1786.88 (+0.68%)   <- what it actually booked
#     1:1 lock        1806.85 (+1.80%)   <- what this rule books
#
# It ran 1.81 times its risk and handed back 79% of it.
#
# THE RULE
# --------
# R is the stop distance. Target is 2R -- agreed 8 August.
#
#     price reaches NEAR_TARGET_R x R    -> the stop moves to entry + 1R
#     price then retraces                -> booked at 1:1, not at zero
#
# Nothing moves before 1.5R. A stop that creeps up from the first tick
# is the 2.5% trail again under a new name, and it is what turns a
# winner into a scratch.
NEAR_TARGET_R = 1.5
LOCK_AT_R = 1.0

# ==========================================================
# THE TARGET IS NOT A CEILING.  8 August 2026.
# ==========================================================
#
#     "we want money in either money thats it"
#
# A stop at -1R and a hard exit at +2R means your best trade of the
# month and an ordinary one pay exactly the same. That is the opposite
# of "WIN BIG ON WINNING STOCKS", and it was measured:
#
#   8,230 setups, 10 days, same entry and same stop, only the exit
#   changes --
#
#       close at 2R      -0.095R per trade      -780R total
#       trail 1.5R       +0.006R per trade       +53R total
#
# The whole difference is the trades that ALMOST worked. A hard target
# pays exactly 2R or nothing; a trail lets a stock that ran to 1.8R
# and rolled over still book something instead of riding back to the
# stop.
#
# And the tail is real. Of 574 trades that reached +2R:
#
#       95% kept going      35% past 3R      14% past 4R      5% past 6R
#       best trade capped at 2.0R  ->  11.1R with the trail
#
# THE PART THAT COSTS
# -------------------
# On the trades that DO reach the target, trailing is slightly worse:
# 1.88R against 2.00R, and it gives something back 62% of the time.
# That is the price of the 38% that run, and it is worth paying --
# but it will feel wrong six times out of ten, so it is written here.
TRAIL_FROM_R = 2.0     # arm the trail once the old target is reached
TRAIL_WIDTH_R = 1.5    # then follow this far below the peak


def live_stop(entry, stop, target, peak):
    """Where the stop sits now, given how far the stock has run.

    `peak` is the highest price seen since entry. Returns the stop to
    use from here, and a word for why it moved.

    Below 1.5R nothing changes -- the original stop stands. At or above
    it the trade is protected at 1:1, so a retrace books a profit
    instead of a scratch.
    """
    entry = _num(entry)
    stop = _num(stop)
    peak = _num(peak)
    if entry is None or stop is None or peak is None:
        return stop, None
    risk = entry - stop
    if risk <= 0:
        return stop, None
    run = (peak - entry) / risk
    if run < NEAR_TARGET_R:
        return stop, None

    # ---- PAST THE OLD TARGET: FOLLOW, DO NOT CLOSE. ----
    # This is where "win big" lives. Nothing caps the trade from here;
    # the stop simply walks up 1.5R behind the highest price seen.
    if run >= TRAIL_FROM_R:
        # ---- NEVER BELOW THE 1:1 LOCK. ----
        # At exactly 2R a 1.5R trail sits at +0.5R, BELOW the lock the
        # trade already earned at 1.5R. A stop that steps backwards is
        # not a trail, it is a giveaway. The lock is the floor and the
        # trail only ever climbs above it.
        trailed = max(peak - risk * TRAIL_WIDTH_R, entry + risk * LOCK_AT_R)
        if trailed > stop:
            return round(trailed, 2), (
                f"ran {run:.1f}R -- trailing {TRAIL_WIDTH_R:.1f}R behind the "
                f"high at {trailed:.2f}, no ceiling on this one")
        return stop, None

    locked = entry + risk * LOCK_AT_R
    if locked <= stop:
        return stop, None
    return round(locked, 2), (f"ran {run:.1f}R -- stop moved to 1:1 at "
                              f"{locked:.2f}, so a retrace books a profit")


def _num(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if value != value else value


def plan(entry, risk_rs=1500.0, typical_range_pct=None, symbol=None,
         prev_close=None, headroom_of=None):
    """{"ok", "stop", "target", "qty", "risk_rs", "reward", "why"}.

    `typical_range_pct` lets a stock speak for itself -- a name that
    ranges 6% a day needs more room than one that ranges 1.5%. Without
    it the measured defaults apply.
    """
    entry = _num(entry)
    if not entry or entry <= 0:
        return {"ok": False, "why": "no price"}

    # A stock's own volatility widens the stop, within reason. Half its
    # typical range is close to the 75th-percentile dip for most names.
    stop_pct = STOP_PCT
    span = _num(typical_range_pct)
    if span:
        stop_pct = max(STOP_PCT, min(span * 0.7, MAX_STOP_PCT))

    target_pct = stop_pct * REWARD_RATIO

    stop = round(entry * (1 - stop_pct / 100.0), 2)
    target = round(entry * (1 + target_pct / 100.0), 2)
    capped_why = None

    # ---- THE CIRCUIT HAS THE LAST WORD ----
    if headroom_of is not None and symbol:
        try:
            room = headroom_of(symbol)
        except Exception:                                  # noqa: BLE001
            room = None
        if room and room.get("ok"):
            ceiling = room.get("ceiling")
            if ceiling and target > ceiling:
                target = round(ceiling, 2)
                capped_why = (f"target capped at the "
                              f"{room.get('band_pct'):.0f}% circuit")

    distance = entry - stop
    if distance <= 0:
        return {"ok": False, "why": "stop is not below the entry"}

    reward = (target - entry) / distance
    if reward < MIN_REWARD:
        return {"ok": False,
                "why": (f"only {reward:.1f}x reward for the risk"
                        + (f" -- {capped_why}" if capped_why else "")
                        + " -- not worth taking")}

    qty = int(_num(risk_rs) // distance)
    if qty < 1:
        return {"ok": False, "why": "one share risks more than the budget"}

    return {
        "ok": True,
        "stop": stop, "target": target, "qty": qty,
        "stop_pct": round(stop_pct, 2),
        "target_pct": round((target - entry) / entry * 100.0, 2),
        "risk_rs": round(qty * distance, 2),
        "reward": round(reward, 2),
        "value_rs": round(qty * entry, 2),
        "why": (f"stop {stop_pct:.1f}% below, target "
                f"{(target - entry) / entry * 100.0:.1f}% above, "
                f"{reward:.1f}x"
                + (f" ({capped_why})" if capped_why else "")),
    }
