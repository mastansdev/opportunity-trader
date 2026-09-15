"""
==========================================================
Trailing Stop -- Longs AND Shorts, mirrored
==========================================================

Purely candle-based, no external indicator -- matches how the
rest of this bot decides everything from price structure alone
(see PHASES.md, PHASE3_NEWS_DESIGN.md section 1.3).

Mechanics, confirmed with the operator before the LONG side was
built, mirrored exactly for SHORT:

  LONG:
    - Initial stop, at entry: set by the CALLER (core/engine.py's
      _orb_stop_seed()) and passed in as seed_stop -- see that
      method's docstring. Operator-corrected 2026-07-23: this
      used to be the breakout candle's own low, which on a
      liquid stock can be a few paise wide and gets clipped by
      ordinary tick noise within seconds. It's now the ORB
      range's OPPOSITE boundary (the low) minus a small buffer
      (config.ORB_STOP_BUFFER_PCT) -- the actual structural
      invalidation level for an ORB trade, not an arbitrary
      1-minute bar. This class itself stays agnostic to how
      seed_stop was computed; it just seeds and ratchets.
    - After that, on every new CLOSED candle: take the LOWEST
      low of the last TRAILING_STOP_WINDOW_CANDLES closed
      candles (a small rolling window, not just the latest one).
      If that rolling low is HIGHER than the current stop, raise
      the stop to it. NEVER lowered.
    - Exit when price <= stop.

  SHORT (mirror image):
    - Initial stop, at entry: same as LONG but mirrored -- the
      ORB range's high plus the buffer (see core/engine.py's
      _orb_stop_seed()).
    - After that, on every new CLOSED candle: take the HIGHEST
      high of the last TRAILING_STOP_WINDOW_CANDLES closed
      candles. If that rolling high is LOWER than the current
      stop, lower the stop to it. NEVER raised.
    - Exit when price >= stop.

  Both: no fixed target. The position rides until the trailing
  stop is hit or the 15:15 square-off forces it closed,
  whichever comes first. A stop-out on a STRUCTURAL entry also
  blocks that symbol+direction for the rest of the day (core/
  engine.py's _exit()) -- one attempt per breakout, not repeated
  whipsaws on a signal that already proved wrong once.

Exit trigger is checked by the caller (core/engine.py) on
every TICK, not candle close -- a stop's job is capital
protection, it should fire immediately on breach, not wait for
confirmation the way an entry does.

Author : H&M Opportunity Trader
==========================================================
"""

from config import (
    TRAILING_STOP_WINDOW_CANDLES, MIN_STOP_DISTANCE_PCT,
    ENABLE_PEAK_TRAIL, PEAK_TRAIL_PCT,
    VOLATILITY_SCALED_TRAIL, DAILY_ATR_TRAIL_MULT,
    TRAIL_EVENT_SLACK, TRAIL_MIN_PCT, TRAIL_MAX_PCT,
)

# ==========================================================
# BOOK 1:1 INSTEAD OF GIVING IT ALL BACK  (2026-08-08)
# ==========================================================
#
#     "in 2:1 ration if the stock is falling after reaching nearby rs
#      & started retrace back book at 1:1 profit (something is better
#      than nothing)"
#
# The 2.5% peak trail sits BELOW the halfway mark of its own 3.6%
# target, so an ordinary pullback ends the trade for almost nothing.
# DEEPAKNTR on 7 August ran 1.81 times its risk and booked 0.68%.
#
# Measured on the recorded tape, 12 trades, 09:30 entries:
#
#     2.5% peak trail    +0.42%
#     1:1 lock rule      +4.33%
#
# The lock is BOUNDED, which the trail was not: the trade can only end
# at the target (+2R), the stop (-1R), the lock (+1R) or the close. At
# most 1R is ever handed back from the peak.
#
# LONG only. He does not short, and the measurement is long-only, so
# SHORT keeps the old peak trail untouched.
ENABLE_ONE_TO_ONE_LOCK = True

LONG = "LONG"
SHORT = "SHORT"



# ==========================================================
#  THE TRAIL WAS ALSO ONE WIDTH FOR EVERY STOCK
# ==========================================================
#
#     "why can't bot self adjust the trading based on the stock
#      movement & news/events supporting the stock price movement.
#      trailing in good moving stocks (strong supported events)"
#                                 -- operator, 19 August 2026
#
# The entry stop was fixed on 18 August: it is now this stock's own
# daily range rather than a flat 2.5%. The TRAIL was left behind and
# is the same mistake one step later -- PEAK_TRAIL_PCT is 2.5% from
# the peak for POLYCAB, whose ordinary day is 1.79%, and for ICIL,
# whose ordinary day is 4.99%.
#
# On ICIL a 2.5% trail is HALF a normal day's movement. It is not a
# trail, it is a coin toss that fires on the first ordinary breather,
# which is exactly the complaint that got the trail switched off
# entirely on 29 July after it sold KAYNES before a run to 3,685.
#
# Same source as the entry stop -- core/atr.daily_atr_pct(), read off
# the bhavcopy store, no network, cached per session -- so the trail
# and the stop can never drift onto different definitions of "how
# much this stock moves".
#
# STRONG EVENTS GET MORE ROOM. His second sentence: a stock running on
# a real catalyst deserves a wider leash than one drifting on nothing,
# because the catalyst is a reason to expect continuation and a
# breather is not a failure. That is TRAIL_EVENT_SLACK, applied only
# when the caller says the position carries one -- this file never
# decides what counts as an event.

def _trail_pct_for(symbol, has_event=False):
    """How far below the peak this stock's trail belongs, as a
    FRACTION. Falls back to the flat PEAK_TRAIL_PCT whenever the daily
    range cannot be measured -- a trail derived from a volatility
    nobody measured is worse than an honestly flat one.
    """
    if not VOLATILITY_SCALED_TRAIL:
        return PEAK_TRAIL_PCT
    try:
        from core.atr import daily_atr_pct
        daily = daily_atr_pct(symbol)
    except Exception:                                       # noqa: BLE001
        daily = None
    if not daily or daily <= 0:
        return PEAK_TRAIL_PCT
    wanted = DAILY_ATR_TRAIL_MULT * float(daily)
    if has_event:
        wanted *= TRAIL_EVENT_SLACK
    wanted = max(TRAIL_MIN_PCT, min(TRAIL_MAX_PCT, wanted))
    return wanted / 100.0

def trail_points(symbol, entry, has_event=False):
    """How far below the peak this stock trails, IN RUPEES.

        "TIME  SYMBOL BUY REASON QTY  ENTRY - TARGET -EXIT -
         TRAILING POINTS"          -- operator, 19 August 2026

    The alert quotes every other level in rupees, so the trail is
    quoted in rupees too. A percentage on a card full of prices is one
    unit conversion he should not have to do on a phone.

    None when it cannot be worked out -- an absent number is better on
    that card than a wrong one.
    """
    try:
        entry = float(entry)
    except (TypeError, ValueError):
        return None
    if entry <= 0:
        return None
    try:
        return round(entry * _trail_pct_for(symbol, has_event), 2)
    except Exception:                                       # noqa: BLE001
        return None


class TrailingStopEngine:

    def __init__(self, window=TRAILING_STOP_WINDOW_CANDLES):
        self.window = window
        # symbol -> {"stop": float, "recent": [float, ...], "direction": str}
        self._state = {}

    # --------------------------------------------------

    def start(self, symbol, seed_stop, direction=LONG,
              entry_price=None, has_event=False):
        """
        Called once, right at entry -- seeds the stop at the
        breakout/breakdown candle's own extreme (low for LONG,
        high for SHORT).
        """
        # ---- A LONG'S STOP GOES BELOW ITS ENTRY. 4 September 2026 ----
        # start() took the seed verbatim and never asked whether it was
        # on the right side. On 4 September SBCL was seeded at 1144.80
        # against an entry of 1135.67 and was stopped out one second
        # later for -Rs 481. The cause was upstream -- a plan built on a
        # stale price -- and is fixed there, but a guard that only one
        # caller respects is not a guard.
        #
        # It is CLAMPED, not refused: the position is already open by
        # the time this runs, and leaving it unprotected would be worse
        # than protecting it at the standard distance. Said loudly,
        # because a stop on the wrong side means something upstream is
        # broken and silence would hide it.
        try:
            if entry_price and seed_stop:
                wrong = (direction == LONG and seed_stop >= entry_price) or (
                    direction != LONG and seed_stop <= entry_price)
                if wrong:
                    from config import FIXED_STOP_PCT
                    from core.logger import warn
                    fixed = (entry_price * (1 - FIXED_STOP_PCT / 100.0)
                             if direction == LONG
                             else entry_price * (1 + FIXED_STOP_PCT / 100.0))
                    warn(f"[STOP] {symbol} {direction}: the plan gave a stop of "
                         f"{seed_stop:.2f} on an entry of {entry_price:.2f} -- "
                         f"the wrong side. Using {fixed:.2f}. Something "
                         f"upstream built this on a stale price.")
                    seed_stop = fixed
        except Exception:                                  # noqa: BLE001
            pass

        self._state[symbol] = {
            "stop": seed_stop,
            "recent": [seed_stop],
            "direction": direction,
            # PEAK TRAIL, 2026-07-28. The best price seen since entry.
            # The stop is PEAK_TRAIL_PCT below it and moves ONLY on a
            # new high -- never on a pause, which is precisely what the
            # old 5-candle window did and why AFFLE gave back Rs 2,497
            # of a Rs 3,087 profit in eight minutes.
            "peak": None,
            # The 1:1 lock needs the two numbers the trail never kept:
            # where the trade went on, and where its risk was measured
            # from. Without both, "one times the risk" has no meaning.
            "entry": entry_price,
            "base_stop": seed_stop,
            "locked": False,
            # Set by the caller at entry. This file never decides what
            # counts as an event -- see _trail_pct_for().
            "has_event": bool(has_event),
        }
        # With the peak trail on, the stop starts EXACTLY
        # PEAK_TRAIL_PCT below the entry -- not wherever the breakout
        # candle's low happened to fall. That low was sometimes a
        # rupee away (noise clipped it in seconds) and sometimes 6%
        # away (an unbounded loss). Anchoring on entry makes the
        # initial risk the same known number on every trade, which is
        # what the operator asked for.
        if ENABLE_PEAK_TRAIL and entry_price:
            state = self._state[symbol]
            state["peak"] = entry_price
            # ---- THE PLANNED STOP IS THE STOP. 8 August 2026. ----
            # With the lock on, the seed the caller passed IS the risk
            # the position was sized against -- core/exit_plan.py
            # measured it and core/auto_entry.py bought quantity to
            # match. Overwriting it with a flat 2.5% here made "one
            # times the risk" mean two different numbers in the same
            # trade: sized on 1.8%, stopped on 2.5%.
            if ENABLE_ONE_TO_ONE_LOCK and direction == LONG and seed_stop:
                state["base_stop"] = seed_stop
            elif direction == LONG:
                state["stop"] = entry_price * (
                    1 - _trail_pct_for(symbol, state.get("has_event")))
                state["base_stop"] = state["stop"]
            else:
                state["stop"] = entry_price * (
                    1 + _trail_pct_for(symbol, state.get("has_event")))
                state["base_stop"] = state["stop"]

    def update_on_price(self, symbol, price):
        """Percent trail from the PEAK. Called on every tick.

        LONG : stop = highest price seen since entry x (1 - PEAK_TRAIL_PCT)
        SHORT: stop = lowest  price seen since entry x (1 + PEAK_TRAIL_PCT)

        Moves only when a NEW extreme is made. A flat stretch does
        nothing -- the old rolling-window rule crept the stop up during
        pauses, so an ordinary breather ended the trade.

        Breakeven needs no special case: at +2.6% the trail crosses the
        entry price by itself, and keeps climbing from there.

        Returns the current stop, or None if this symbol has no active
        trailing stop.
        """
        state = self._state.get(symbol)
        if state is None or not ENABLE_PEAK_TRAIL or not price:
            return None if state is None else state["stop"]

        peak = state.get("peak")
        if state["direction"] == LONG:
            if peak is None or price > peak:
                state["peak"] = price
                if ENABLE_ONE_TO_ONE_LOCK:
                    # ---- 1:1 LOCK, NOT A CREEPING TRAIL. ----
                    # Nothing moves until the stock has run 1.5x its
                    # own risk. A stop that creeps from the first tick
                    # is the 2.5% trail under a new name, and it is
                    # what turned +3.26% into +0.68%.
                    moved = self._lock_at_one_to_one(state, price)
                    if moved is not None:
                        state["stop"] = moved
                else:
                    candidate = price * (
                        1 - _trail_pct_for(symbol,
                                           state.get("has_event")))
                    if candidate > state["stop"]:
                        state["stop"] = candidate

            # ---- AND THE PROFIT LOCK, ON TOP. 14 Sep 2026. ----
            #
            # Applied to the peak as it now stands, after whichever
            # branch above ran, so it is a FLOOR under the stop and
            # never a replacement for either. It only ever raises --
            # a lock that could lower a stop is a giveaway.
            #
            # See config.PROFIT_LOCK_ARM_PCT: the 1:1 lock above arms
            # at +3.75% and 94 of his 95 trades never got there.
            locked = self._profit_lock(state)
            if locked is not None and locked > state["stop"]:
                state["stop"] = locked
        else:
            if peak is None or price < peak:
                state["peak"] = price
                candidate = price * (
                    1 + _trail_pct_for(symbol,
                                       state.get("has_event")))
                if candidate < state["stop"]:
                    state["stop"] = candidate
        return state["stop"]

    @staticmethod
    def _profit_lock(state):
        """The floor his slab rule puts under the stop, or None.

            "once mtm profit cross 5K then shift the Trailing stop loss
             to 5K price of that stock then increase for every 1 k
             upside movement"                     -- 14 September 2026

        Once the high-water gain reaches PROFIT_LOCK_ARM_PCT, the stop
        may never sit more than PROFIT_LOCK_GIVEBACK_PCT below the
        highest price seen. Continuous rather than in notches, which is
        the same rule with the steps made infinitely small.

        LONG only -- the short side has no measurement behind it and a
        rule without one does not belong in the exit path.

        Returns None whenever it cannot say, and None never moves a
        stop. Read at call time: he changes these between sessions.
        """
        try:
            from config import (PROFIT_LOCK_ARM_PCT, PROFIT_LOCK_ENABLED,
                                PROFIT_LOCK_GIVEBACK_PCT)
        except Exception:                                      # noqa: BLE001
            return None
        if not PROFIT_LOCK_ENABLED:
            return None
        entry = state.get("entry")
        peak = state.get("peak")
        try:
            entry = float(entry or 0)
            peak = float(peak or 0)
        except (TypeError, ValueError):
            return None
        if entry <= 0 or peak <= 0:
            return None
        if (peak - entry) / entry * 100.0 < float(PROFIT_LOCK_ARM_PCT):
            return None

        # ---- AND IT HANDS OVER. 14 September 2026. ----
        #
        # A flat 0.5% give-back is TIGHTER than the 1.5R trail once the
        # trade is really running: at 4R it would sit at 1066.64 where
        # the R trail sits at 1045.00, so a 10% winner would be closed
        # on an ordinary 0.5% pullback. His 7-10 September book could
        # not show that -- exactly ONE of 95 trades ever passed 6% --
        # and a rule measured only where the big winners are absent
        # must not be the one governing them.
        #
        # So this covers the GAP the 1:1 lock leaves: from the arm up
        # to 1.5R, where nothing held a profit before. The moment that
        # lock engages, the bounded R-relative design takes over and
        # this says nothing.
        if state.get("locked"):
            return None
        return peak * (1 - float(PROFIT_LOCK_GIVEBACK_PCT) / 100.0)

    def _lock_at_one_to_one(self, state, peak):
        """The stop once the stock has run near its target, or None.

        Delegates the arithmetic to core/exit_plan.py so the rule lives
        in exactly one place. A failure here must never widen a stop,
        so it returns None and the existing stop stands.
        """
        entry = state.get("entry")
        base = state.get("base_stop")
        if not entry or not base:
            return None
        try:
            from core import exit_plan
            moved, why = exit_plan.live_stop(entry, base, None, peak)
        except Exception:                                      # noqa: BLE001
            return None
        if moved is None or not why:
            return None
        if moved <= (state.get("stop") or 0):
            return None
        if not state.get("locked"):
            state["locked"] = True
            try:
                from core.logger import decision
                decision(f"[LOCK] {why}")
            except Exception:                                  # noqa: BLE001
                pass
        return moved

    def update_on_candle_close(self, symbol, candle_low, candle_high,
                               reference_price=None):
        """
        Called every time a candle closes for a symbol that
        already has an active trailing stop. Feeds the new
        low/high into the rolling window (whichever side matters
        for this symbol's direction) and ratchets the stop if
        warranted. Returns the (possibly unchanged) current
        stop, or None if this symbol has no active trailing
        stop at all.

        THE MINIMUM-DISTANCE FLOOR (added 2026-07-27)
        ---------------------------------------------
        Operator-found live. Every single position on 2026-07-27 --
        more than twenty of them, manual and structural alike -- exited
        by TRAILING_STOP within two to fifteen minutes, at a price
        within 0.2% of where it went in:

            LAURUSLABS  in 1681.60  out 1681.60   9 min   0.00%
            CARTRADE    in 2893.40  out 2892.90  15 min  -0.02%
            ETERNAL     in  295.20  out  295.40   8 min  +0.07%
            LAURUSLABS  in 1717.50  out 1718.30   8 min  +0.05%

        LAURUSLABS sold for exactly what it cost, and then ran to
        1730.50 without us.

        The cause is right here. The ratchet moved the stop to
        `min(recent candle lows)` with NO minimum distance from price.
        MIN_STOP_DISTANCE_PCT was applied once, when the stop was
        seeded at entry, and then never again. In a quiet minute a
        candle's low sits a rupee or two under the price, so after two
        or three candles the stop had climbed to within paise of the
        market -- and the next ordinary wobble was a "stop hit".

        This is the same disease as the 0.4% seed floor fixed earlier
        that day, one level deeper: widening the SEED changed nothing,
        because the ratchet immediately walked the stop back up to
        touching distance regardless.

        So the floor now applies on EVERY ratchet, not just at entry:
        the stop may rise (LONG) but may never come closer to
        `reference_price` than MIN_STOP_DISTANCE_PCT.

        `reference_price` is optional and defaults to the candle's own
        extreme. Callers that don't pass it keep the old behaviour --
        that is deliberate, so this cannot silently change any test or
        replay that hasn't been looked at.
        """
        state = self._state.get(symbol)
        if state is None:
            return None

        # 2026-07-28: with the peak trail on, the candle-close ratchet is
        # switched off entirely. Running both would let the tighter of
        # the two win, which is the 5-candle window -- the exact rule
        # being replaced. It stays in the file (and under test) so
        # ENABLE_PEAK_TRAIL=False restores the old behaviour intact.
        if ENABLE_PEAK_TRAIL:
            return state["stop"]

        if state["direction"] == SHORT:
            state["recent"].append(candle_high)
            if len(state["recent"]) > self.window:
                state["recent"] = state["recent"][-self.window:]
            candidate = max(state["recent"])
            # never let the stop sit closer than the floor ABOVE price
            ref = reference_price if reference_price is not None else candle_high
            ceiling = ref * (1 + MIN_STOP_DISTANCE_PCT)
            candidate = max(candidate, ceiling)
            if candidate < state["stop"]:
                state["stop"] = candidate
        else:
            state["recent"].append(candle_low)
            if len(state["recent"]) > self.window:
                state["recent"] = state["recent"][-self.window:]
            candidate = min(state["recent"])
            # never let the stop sit closer than the floor BELOW price
            ref = reference_price if reference_price is not None else candle_low
            floor = ref * (1 - MIN_STOP_DISTANCE_PCT)
            candidate = min(candidate, floor)
            if candidate > state["stop"]:
                state["stop"] = candidate

        return state["stop"]

    def get_stop(self, symbol):
        state = self._state.get(symbol)
        return state["stop"] if state else None

    def get_direction(self, symbol):
        state = self._state.get(symbol)
        return state["direction"] if state else None

    def get_peak(self, symbol):
        """The best price this position has seen since entry, or None.

        Already tracked on every tick by update_on_price(); it simply
        had no reader outside this file. core/engine._buying_dried_up()
        needs it to answer one question -- is this stock still at its
        high? -- before it acts on an order-flow reading.
        """
        state = self._state.get(symbol)
        return state.get("peak") if state else None

    def is_hit(self, symbol, price):
        state = self._state.get(symbol)
        if state is None:
            return False
        if state["direction"] == SHORT:
            return price >= state["stop"]
        return price <= state["stop"]

    def clear(self, symbol):
        self._state.pop(symbol, None)

    # --------------------------------------------------
    # Restart persistence (core/state_store.py)
    # --------------------------------------------------

    # ---- A RESTART DROPPED THE PEAK AND THE ENTRY. 15 Sep 2026. ----
    #
    # export_state() kept stop, recent and direction only. peak, entry,
    # base_stop and locked were lost on every restart, so for a position
    # carried through one the 1:1 lock had no entry to measure risk from,
    # and the profit protection had no peak -- it silently never moved
    # the stop again. Found while building his rupee slabs; nothing was
    # open across today's two restarts, so no trade was hit.
    _CARRIED = ("peak", "entry", "base_stop", "locked", "has_event")

    def export_state(self):
        """Plain-dict snapshot, safe to json.dump directly."""
        out = {}
        for symbol, s in self._state.items():
            row = {"stop": s["stop"], "recent": list(s["recent"]),
                   "direction": s["direction"]}
            for key in self._CARRIED:
                if key in s:
                    row[key] = s[key]
            out[symbol] = row
        return out

    def load_state(self, state):
        """Restores from a snapshot produced by export_state().
        Overwrites, never merges -- same reasoning as
        OrbEngine.load_state(). "direction" defaults to LONG for
        snapshots saved before shorts existed."""
        for symbol, s in state.items():
            self._state[symbol] = {
                "stop": s["stop"],
                "recent": list(s.get("recent", s.get("recent_lows", []))),
                "direction": s.get("direction", LONG),
            }
            for key in self._CARRIED:
                if key in s:
                    self._state[symbol][key] = s[key]

    # ---- HIS PROFIT SLABS, EXACTLY AS HE SAID THEM. 15 Sep 2026. ----
    #
    #     "once mtm profit cross 5K then shift the Trailing stop loss to
    #      5K price of that stock then increase for every 1 k upside
    #      movement"                                -- 14 September 2026
    #
    # Built that night as a PERCENTAGE instead (arm at +2.5%, give back
    # 0.5%) -- not his rule. He caught it on 15 Sep. This is his rule:
    #
    #     best MTM reached   stop locks
    #     Rs 5,000           Rs 5,000
    #     Rs 6,000           Rs 6,000   ... up Rs 1,000 at a time, never down
    #
    #     stop price = entry + locked rupees / quantity
    #
    # Rupees need the quantity, which this file does not keep -- the
    # engine passes it in. LONG only. Only ever raises the stop.
    def apply_profit_slab(self, symbol, qty):
        """Raise the stop to his rupee slab. Returns the new stop, or None."""
        try:
            from config import (PROFIT_SLAB_ENABLED, PROFIT_SLAB_FIRST_RS,
                                PROFIT_SLAB_STEP_RS)
        except Exception:                                      # noqa: BLE001
            return None
        if not PROFIT_SLAB_ENABLED:
            return None
        state = self._state.get(symbol)
        if not state or state.get("direction") != LONG:
            return None
        try:
            entry = float(state.get("entry") or 0)
            peak = float(state.get("peak") or 0)
            qty = float(qty or 0)
            first = float(PROFIT_SLAB_FIRST_RS)
            step = float(PROFIT_SLAB_STEP_RS)
        except (TypeError, ValueError):
            return None
        if entry <= 0 or peak <= 0 or qty <= 0 or first <= 0 or step <= 0:
            return None
        # A paisa of float error: exactly Rs 5,000 computes as 4,999.9999.
        best = (peak - entry) * qty + 1e-6
        if best < first:
            return None
        import math
        locked = first + step * math.floor((best - first) / step)
        stop = round(entry + locked / qty, 2)
        if stop <= (state.get("stop") or 0):
            return None
        state["stop"] = stop
        if state.get("slab") != locked:
            state["slab"] = locked
            try:
                from core.logger import decision
                decision(f"[SLAB] {symbol}: best profit Rs {best:,.0f} -- "
                         f"stop moved to {stop:.2f}, locking Rs "
                         f"{locked:,.0f} on {qty:.0f} shares.")
            except Exception:                                  # noqa: BLE001
                pass
        return stop
