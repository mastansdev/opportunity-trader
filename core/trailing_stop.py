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

from config import TRAILING_STOP_WINDOW_CANDLES, MIN_STOP_DISTANCE_PCT

LONG = "LONG"
SHORT = "SHORT"


class TrailingStopEngine:

    def __init__(self, window=TRAILING_STOP_WINDOW_CANDLES):
        self.window = window
        # symbol -> {"stop": float, "recent": [float, ...], "direction": str}
        self._state = {}

    # --------------------------------------------------

    def start(self, symbol, seed_stop, direction=LONG):
        """
        Called once, right at entry -- seeds the stop at the
        breakout/breakdown candle's own extreme (low for LONG,
        high for SHORT).
        """
        self._state[symbol] = {
            "stop": seed_stop,
            "recent": [seed_stop],
            "direction": direction,
        }

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

    def export_state(self):
        """Plain-dict snapshot, safe to json.dump directly."""
        return {
            symbol: {
                "stop": s["stop"],
                "recent": list(s["recent"]),
                "direction": s["direction"],
            }
            for symbol, s in self._state.items()
        }

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
