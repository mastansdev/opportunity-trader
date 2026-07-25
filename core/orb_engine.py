"""
==========================================================
ORB Engine
==========================================================

The ONE structural rule everything else serves: track the
high and low of each symbol between MARKET_OPEN and
ORB_WINDOW_END. Nothing else. No scoring, no filtering,
no opinions.

A tick outside [MARKET_OPEN, ORB_WINDOW_END) is simply not
part of the range -- before it, ignored as pre-market;
after it, the range is already frozen and does not move.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import datetime, time

from config import MARKET_OPEN, ORB_WINDOW_END, EARLY_ORB_END
from core.logger import diagnostic, warn


def _parse_hhmm(value):
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


MARKET_OPEN_T = _parse_hhmm(MARKET_OPEN)
ORB_WINDOW_END_T = _parse_hhmm(ORB_WINDOW_END)

# 2026-07-25: a SECOND, shorter opening range (first ~5 minutes).
# A break of this can trade from ~09:20 instead of waiting for the
# full 09:30 range -- but only for names clearing a much higher
# strength bar (see core/engine.py's early-momentum path).
EARLY_ORB_END_T = _parse_hhmm(EARLY_ORB_END)


class OrbEngine:

    def __init__(self):
        # symbol -> {"high": float, "low": float, "complete": bool}
        self._ranges = {}

        # Same shape, but frozen at EARLY_ORB_END_T -- the short
        # "first 5 minutes" range used by the early-momentum entry.
        self._early_ranges = {}

        # Diagnostic-only bookkeeping -- 2026-07-23, added while
        # chasing a live bug where _ranges stayed empty all session
        # despite ticks visibly flowing (core/candle_engine.py logs
        # proved it). Never affects trading logic, only visibility:
        # logs the very first tick this engine instance ever sees
        # for each symbol (once), so a restart's diagnostics.log can
        # directly answer "did update() even get called, and with
        # what time, for this symbol" instead of having to infer it
        # from candle logs.
        self._seen_symbols = set()

        # Edge-triggered -- without this the "no range was ever
        # built" warning below fires on EVERY tick, forever, for
        # every affected symbol (state stays None forever once
        # missed), which floods the console exactly the way this
        # whole project has tried to avoid. Warn once per symbol.
        self._no_range_warned = set()

    # --------------------------------------------------

    def update(self, symbol, price, tick_time):
        """
        Feed one tick. tick_time must be a datetime (not a
        raw string) so callers can't accidentally pass an
        unparsed timestamp.
        """
        if symbol not in self._seen_symbols:
            self._seen_symbols.add(symbol)
            diagnostic(
                f"[ORB] First tick seen for {symbol}: "
                f"price={price} tick_time={tick_time} "
                f"(parsed .time()={tick_time.time()}) "
                f"MARKET_OPEN_T={MARKET_OPEN_T} ORB_WINDOW_END_T={ORB_WINDOW_END_T}"
            )

        t = tick_time.time()

        if t < MARKET_OPEN_T:
            # Pre-market. Never part of the range.
            return

        # ---- early (first ~5 min) range, 2026-07-25 ----------------
        # Accumulated in parallel with the main range and frozen at
        # EARLY_ORB_END_T. Used only by the high-conviction
        # early-momentum entry path; the main range is untouched.
        early = self._early_ranges.get(symbol)
        if t < EARLY_ORB_END_T:
            if early is None:
                self._early_ranges[symbol] = {
                    "high": price, "low": price, "complete": False}
            else:
                if price > early["high"]:
                    early["high"] = price
                if price < early["low"]:
                    early["low"] = price
        elif early is not None and not early["complete"]:
            early["complete"] = True
            diagnostic(f"[ORB_EARLY] {symbol} early range complete: {early}")

        state = self._ranges.get(symbol)

        if t >= ORB_WINDOW_END_T:
            # Range window closed. Mark complete if not
            # already, but never let a late tick move the
            # range.
            if state is not None and not state["complete"]:
                state["complete"] = True
                diagnostic(f"[ORB] {symbol} range complete: {state}")
            elif state is None and symbol not in self._no_range_warned:
                self._no_range_warned.add(symbol)
                warn(
                    f"[ORB] {symbol}: window-close tick arrived "
                    f"(t={t}) but no range was ever built for it "
                    f"during [{MARKET_OPEN_T}, {ORB_WINDOW_END_T}) -- "
                    f"this symbol got zero ticks inside its own "
                    f"opening-range window."
                )
            return

        # Inside the range window [MARKET_OPEN, ORB_WINDOW_END)
        if state is None:
            state = {
                "high": price,
                "low": price,
                "complete": False,
            }
            self._ranges[symbol] = state
        else:
            if price > state["high"]:
                state["high"] = price
            if price < state["low"]:
                state["low"] = price

    # --------------------------------------------------

    def range_count(self):
        """Diagnostic only -- symbols with a range being tracked."""
        return len(self._ranges)

    def complete_count(self):
        """Diagnostic only -- symbols whose range is locked.
        dict(self._ranges) snapshot for the same cross-thread-
        mutation reason as export_state() above."""
        return sum(1 for s in dict(self._ranges).values() if s["complete"])

    # --------------------------------------------------

    def is_complete(self, symbol):
        state = self._ranges.get(symbol)
        return bool(state and state["complete"])

    # --------------------------------------------------

    def get_range(self, symbol):
        state = self._ranges.get(symbol)
        if state is None:
            return None
        return {"high": state["high"], "low": state["low"]}

    # --------------------------------------------------

    def get_early_range(self, symbol):
        """The frozen first-~5-minute range, or None if it isn't
        complete yet / was never built. Separate from get_range() so
        no existing caller can accidentally trade off it."""
        st = self._early_ranges.get(symbol)
        if st is None or not st["complete"]:
            return None
        return {"high": st["high"], "low": st["low"]}

    def reconcile_early_with_exchange(self, symbol, ex_high, ex_low):
        """
        Same exchange-truth widening as reconcile_with_exchange(), but
        for the EARLY (first ~5 min) range.

        Gap found 2026-07-25, hours after shipping the early-momentum
        entry: the main ORB gets corrected from the exchange's OHLC at
        09:30, but the early range is USED at ~09:21 -- before any
        reconcile has happened. So early entries were still trading off
        a sampled, too-narrow range: exactly the false-breakout problem
        the reconcile exists to kill, on the noisiest range of the day.

        Right after EARLY_ORB_END the exchange's day high/low IS the
        early range (only those minutes have traded), so it is the
        authoritative source here too. Only ever widens.
        """
        state = self._early_ranges.get(symbol)
        if state is None:
            return False
        changed = False
        try:
            if ex_high and float(ex_high) > state["high"]:
                state["high"] = float(ex_high); changed = True
            if ex_low and 0 < float(ex_low) < state["low"]:
                state["low"] = float(ex_low); changed = True
        except (TypeError, ValueError):
            return False
        return changed

    def reconcile_with_exchange(self, symbol, ex_high, ex_low):
        """
        Widen this symbol's opening range to the EXCHANGE's own
        high/low. Returns True if the range actually changed.

        Why this exists (operator-found, 2026-07-25): the WebSocket
        feed sends periodic SNAPSHOTS, not every trade. A liquid stock
        trades many times a second; the bot sees only a few of those.
        So the range we accumulate from ticks is systematically
        NARROWER than the true one -- verified live on 2026-07-24:

            ZENTEC    tick-built 1784.20  vs real 1792.00
            CROMPTON  tick-built  246.85  vs real  249.70

        A too-narrow range is not a cosmetic error: price at 1785 looks
        like a breakout when it is still 7 rupees INSIDE the real
        range, so the bot buys noise and calls it a breakout.

        The exchange's own OHLC (Dhan's REST quote, already polled by
        core/circuit_monitor.py) counts every trade. Immediately after
        the ORB window closes, the day's high/low IS the opening range
        -- only those 15 minutes have traded -- so it is the
        authoritative source. We only ever WIDEN (never narrow): the
        REST snapshot can lag a few seconds, and a tick we genuinely
        saw is real data that must not be discarded.
        """
        state = self._ranges.get(symbol)
        if state is None:
            return False
        changed = False
        try:
            if ex_high and float(ex_high) > state["high"]:
                state["high"] = float(ex_high); changed = True
            if ex_low and 0 < float(ex_low) < state["low"]:
                state["low"] = float(ex_low); changed = True
        except (TypeError, ValueError):
            return False
        return changed

    def force_complete_all(self):
        """
        Called once wall clock passes ORB_WINDOW_END, in
        case a symbol had no ticks exactly at/after the
        boundary (illiquid names).
        """
        for state in self._ranges.values():
            state["complete"] = True

    # --------------------------------------------------
    # Restart persistence (core/state_store.py)
    # --------------------------------------------------

    def export_state(self):
        """Plain-dict snapshot, safe to json.dump directly.

        dict(self._ranges) first: this is read from the dashboard's
        refresh thread while update() (feed thread) can be adding a
        NEW symbol to self._ranges concurrently -- iterating the
        live dict directly here raised "RuntimeError: dictionary
        changed size during iteration" in production (2026-07-23).
        dict(...) copies the whole table in one C-level pass that
        holds the GIL throughout, so it can't be interrupted by the
        other thread -- see dashboard/state.py's _build() docstring
        for the fuller writeup of this pattern.
        """
        return {
            symbol: {
                "high": state["high"],
                "low": state["low"],
                "complete": state["complete"],
            }
            for symbol, state in dict(self._ranges).items()
        }

    def load_state(self, state):
        """
        Restores ranges from a snapshot produced by
        export_state(). Never merges with -- always
        overwrites -- whatever this instance already has,
        so restart order is unambiguous.
        """
        for symbol, s in state.items():
            self._ranges[symbol] = {
                "high": s["high"],
                "low": s["low"],
                "complete": s["complete"],
            }
