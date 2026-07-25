"""
==========================================================
Engine -- Layer 1
==========================================================

Ties the pieces together. Per tick:

    1. Update ORB range (if inside the window).
    2. Update the 1-min candle. If a candle just closed:
       - existing position: feed the candle's low/high into the
         trailing stop (core/trailing_stop.py), ratcheting it in
         the protective direction if warranted.
       - no position yet: ask the strategy for a signal (LONG on
         a close above the ORB high, SHORT on a close below the
         ORB low -- core/strategy.py), then run it past
         _try_structural_entry()'s two checks before actually
         entering.
    3. Every tick: check for a pending manual buy request
       (dashboard BUY button -- deliberate, scoped addition;
       see trading/trade_controller.py's docstring), check the
       trailing stop (tick-touch, not candle-close -- a stop's
       job is capital protection, it fires immediately on
       breach), and manual exit requests. Act on whichever
       fires.

Structural price action alone still decides every AUTOMATIC
entry -- news and sector data never manufacture a signal, they
only ever SUBTRACT from what price action already produced, and
only in the two narrow, operator-approved ways below. Manual buy
stays an explicit operator override, bypassing both checks
entirely (see _enter()'s manual branch).

_try_structural_entry() is where a valid structural signal can
still be turned away, in exactly two cases -- both because
taking the trade would mean fighting a market that's already
telling you something, not because "no confirmation exists":

  1. NEWS CONTRADICTION (single stock): the exact symbol has a
     same-day HIGH-priority news item (core/news_gate.py) whose
     direction is the OPPOSITE of this signal. Blocks only that
     one direction, for that one symbol, for the rest of the
     day -- a genuine bearish breakdown on that SAME symbol
     later (which would agree with the bad news) is still fully
     tradeable. Operator-approved 2026-07-23: "NO TRADE" rather
     than "flag only, still trade" -- no fighting the market on
     a name with real, material, contradicting news against it.

  2. SECTOR PANIC (breadth-wide): core/sector_monitor.py flags a
     whole sector as broadly, sharply declining -- not one bad
     stock. Blocks new LONG entries anywhere in that sector for
     the rest of the day. NEVER blocks a SHORT -- shorting a
     real sector breakdown is going WITH the market, not against
     it, so it stays fully available, ORB rule unchanged.

Both blocks are recorded in self.entry_blocked (persisted -- see
core/state_store.py) and logged ONCE per (symbol, direction),
not every candle -- the same edge-triggered-logging discipline
used everywhere else in this codebase, so a stock stuck at a
blocked breakout for hours doesn't flood the console.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import datetime, time as dtime

from config import (
    LAYER1_FIXED_QTY, ORB_STOP_BUFFER_PCT, BLOCK_REENTRY_AFTER_STOPOUT,
    TOP_N_MOMENTUM_MODE, FIXED_TARGET_RS, FIXED_STOP_LOSS_RS,
    SQUARE_OFF_TIME, FROZEN_PRICE_STREAK_CANDLES,
)
from core.orb_engine import OrbEngine
from core.candle_engine import CandleEngine
from core.strategy import Strategy
from core.trailing_stop import TrailingStopEngine, LONG, SHORT
from core.logger import decision, diagnostic, warn
from trading.execution import Execution
from trading.trade_controller import TradeController


def _parse_hhmm(value):
    hour, minute = value.split(":")
    return dtime(int(hour), int(minute))


# Same parsing pattern as core/orb_engine.py's MARKET_OPEN_T/
# ORB_WINDOW_END_T. Real bug found live, 2026-07-23 15:18: main.py's
# flatten_all() at SQUARE_OFF_TIME is a ONE-SHOT close of whatever
# was open at that exact moment -- nothing ever stopped brand new
# entries from opening immediately after (or even during the same
# tick batch), and once opened they just sat there ungoverned,
# never getting squared off since flatten_all() only runs once
# (main.py's own squared_off guard). 74 open positions were still
# live and the bot was still trying to buy MORE at 15:18, three
# minutes past square-off -- blocked only by margin exhaustion, not
# by time. Checked against tick_time (market time), not wall clock,
# for the same reason every other time-window check in this
# codebase does (core/orb_engine.py's own MARKET_OPEN_T/
# ORB_WINDOW_END_T) -- ties the block to the market's own timeline,
# not system clock drift.
SQUARE_OFF_T = _parse_hhmm(SQUARE_OFF_TIME)

ENTRY_REASON_STRUCTURAL_LONG = "STRUCTURAL_LONG_BREAKOUT"
ENTRY_REASON_STRUCTURAL_SHORT = "STRUCTURAL_SHORT_BREAKDOWN"
ENTRY_REASON_MANUAL_DASHBOARD = "MANUAL_BUY_DASHBOARD"
EXIT_REASON_TRAILING_STOP = "TRAILING_STOP"
EXIT_REASON_MANUAL = "MANUAL_EXIT"
EXIT_REASON_SQUARE_OFF = "SQUARE_OFF"
# TOP_N_MOMENTUM_MODE only (config.py) -- fixed bracket exits,
# never the ratcheting trailing stop. See _check_fixed_bracket().
EXIT_REASON_FIXED_TARGET = "FIXED_TARGET"
EXIT_REASON_FIXED_STOP = "FIXED_STOP_LOSS"
# core/circuit_monitor.py -- proactive, direction-agnostic close
# ahead of either circuit limit (see config.py's
# CIRCUIT_PROXIMITY_PCT docstring, post-HFCL operator instruction
# 2026-07-23). Distinct from EXIT_REASON_TRAILING_STOP/FIXED_STOP --
# this isn't a losing-trade stop-out, so BLOCK_REENTRY_AFTER_STOPOUT
# (_exit()'s own re-entry-block check below) deliberately does NOT
# treat it as one.
EXIT_REASON_CIRCUIT_PROXIMITY = "CIRCUIT_PROXIMITY"

# Structural direction -> the news direction that would AGREE
# with it. Anything else in the HIGH-priority item is a
# contradiction (HIGH tier already excludes "neutral" by
# construction -- see news_bot/priority.py).
_AGREEING_NEWS_DIRECTION = {LONG: "bullish", SHORT: "bearish"}


class Engine:

    def __init__(self, news_gate=None, portfolio=None, sector_monitor=None,
                 momentum_universe=None, circuit_monitor=None):
        self.orb_engine = OrbEngine()
        self.candle_engine = CandleEngine()
        self.strategy = Strategy(self.orb_engine)
        self.trailing_stop = TrailingStopEngine()
        self.execution = Execution()
        self.trade_controller = TradeController()

        # Advisory reader only -- see module docstring above and
        # core/news_gate.py. None is the default and fully
        # supported: every existing decision path works
        # identically with no news_gate at all.
        self.news_gate = news_gate

        # Display/tracking ledger only -- see
        # trading/portfolio.py's own docstring. None is fully
        # supported: every existing decision path works
        # identically with no portfolio at all.
        self.portfolio = portfolio

        # Breadth-based sector panic reader -- see
        # core/sector_monitor.py. None is fully supported: no
        # sector check ever runs, structural signals decide
        # everything exactly as before it existed.
        self.sector_monitor = sector_monitor

        # TOP_N_MOMENTUM_MODE's locked top-25-gainers/top-25-losers
        # shortlist -- see core/momentum_universe.py. None is fully
        # supported (mirrors every other optional reader here): if
        # TOP_N_MOMENTUM_MODE is False, this is never consulted at
        # all, regardless of whether an instance was wired in.
        self.momentum_universe = momentum_universe

        # Proactive circuit-limit approach detector -- see
        # core/circuit_monitor.py and config.py's
        # CIRCUIT_PROXIMITY_PCT docstring. None is fully supported,
        # same pattern as every other optional reader here: no
        # circuit check ever runs, structural entries/exits behave
        # exactly as before it existed.
        self.circuit_monitor = circuit_monitor

        # symbol -> {"security_id":, "qty":, "entry_price":,
        #            "entry_reason":, "entry_time":, "direction":}
        self.open_positions = {}

        # Newest last. In-memory only -- trade_log.csv is the
        # durable record; this is what the dashboard's Closed
        # Positions table reads for a fast, structured view.
        self.closed_positions = []

        # symbol -> {direction: reason} -- see module docstring's
        # _try_structural_entry() section. Persisted (see
        # core/state_store.py) so a block survives a restart.
        self.entry_blocked = {}

        # "exitall" snapshot -- see _maybe_snapshot_exit_all() and
        # _exit()'s draining logic. None whenever no exit-all batch
        # is in flight; a set() (possibly empty) once one is. NOT
        # persisted, same as trade_controller's own request flags --
        # a manual exit-all is a live, in-session action, never
        # expected to span a restart.
        self._exit_all_snapshot = None

        # Frozen-price feed detection -- see config.py's
        # FROZEN_PRICE_STREAK_CANDLES docstring (HFCL, 2026-07-23).
        # symbol -> (repeated_close_value, consecutive_candle_count).
        # NOT persisted -- a freeze is a live feed condition, not
        # state worth carrying across a restart; a fresh streak just
        # rebuilds from the next few candles either way.
        self._frozen_streak = {}
        # Edge-triggered warning tracker, mirrors core/market_data.py's
        # own _stale_symbols pattern -- warn once per freeze episode,
        # not every candle for the rest of the day.
        self._frozen_warned = set()

    # --------------------------------------------------

    def process_tick(self, symbol, security_id, price, tick_time):
        self._maybe_snapshot_exit_all()

        self.orb_engine.update(symbol, price, tick_time)

        closed_candle = self.candle_engine.update(
            symbol, price, tick_time
        )

        if closed_candle is not None:
            diagnostic(
                f"[CANDLE] {symbol} closed "
                f"O={closed_candle['open']:.2f} "
                f"H={closed_candle['high']:.2f} "
                f"L={closed_candle['low']:.2f} "
                f"C={closed_candle['close']:.2f}"
            )

            self._update_frozen_streak(symbol, closed_candle)

            already_open = symbol in self.open_positions

            if already_open:
                # Fixed-bracket trades (TOP_N_MOMENTUM_MODE) have no
                # trailing to ratchet -- stop and target are both
                # fixed at entry, see _check_fixed_bracket().
                #
                # A frozen candle (see FROZEN_PRICE_STREAK_CANDLES)
                # carries no real information about a safe stop level
                # -- ratcheting onto it would drag the stop flush
                # against the current (phantom) price and self-
                # trigger on the very next tick. Skip the ratchet
                # entirely while frozen; the position just sits,
                # protected by whatever stop it already had, until
                # the feed recovers or square-off closes it normally.
                if self.open_positions[symbol].get("fixed_target") is None \
                        and not self._is_frozen(symbol):
                    new_stop = self.trailing_stop.update_on_candle_close(
                        symbol, closed_candle["low"], closed_candle["high"]
                    )
                    if new_stop is not None:
                        diagnostic(f"[TRAIL] {symbol} stop -> {new_stop:.2f}")

            elif self.strategy.is_buy_signal(
                symbol, closed_candle, already_open
            ):
                self._try_structural_entry(
                    symbol, security_id, closed_candle, LONG,
                    ENTRY_REASON_STRUCTURAL_LONG,
                )

            elif self.strategy.is_short_signal(
                symbol, closed_candle, already_open
            ):
                self._try_structural_entry(
                    symbol, security_id, closed_candle, SHORT,
                    ENTRY_REASON_STRUCTURAL_SHORT,
                )

        # Manual buy request (dashboard BUY button) -- checked every
        # tick, not just on candle close, so it fires on the very
        # next available price, same immediacy as manual exit. This
        # is an explicit operator override: it bypasses the news/
        # sector checks below entirely, same as it already bypasses
        # the ORB signal itself -- an operator clicking BUY has
        # already made an informed choice, the automation doesn't
        # second-guess it.
        if self.trade_controller.is_buy_requested(symbol):
            self.trade_controller.clear_buy(symbol)
            if symbol in self.open_positions:
                warn(
                    f"[MANUAL_BUY] {symbol} already has an open "
                    f"position -- request ignored, no pyramiding."
                )
            elif tick_time is not None and tick_time.time() >= SQUARE_OFF_T:
                # Real bug found live, 2026-07-23 15:18 -- see
                # SQUARE_OFF_T's own module-level comment. Manual
                # buy is normally an unconditional operator override,
                # but square-off exists specifically to guarantee
                # zero new intraday exposure past this time -- an
                # override that could reopen that exposure would
                # defeat the one thing square-off is for.
                warn(
                    f"[MANUAL_BUY] {symbol} skipped -- past square-off "
                    f"time ({SQUARE_OFF_T}), no new positions today."
                )
            else:
                last_candle = self.candle_engine.last_closed(symbol)
                # A stop must always sit strictly below entry price --
                # the last closed candle's low can be STALE (price may
                # have fallen since that candle closed) or simply not
                # exist yet. Either way, using it blindly risks seeding
                # a stop AT or ABOVE the entry price, which would
                # self-trigger the trailing stop on this exact same
                # tick. Fall back to a small buffer below entry
                # whenever the candle low isn't safely below price.
                if last_candle and last_candle["low"] < price:
                    seed_low = last_candle["low"]
                else:
                    seed_low = price * 0.995
                self._enter(
                    symbol, security_id, price, seed_low, tick_time,
                    ENTRY_REASON_MANUAL_DASHBOARD, LONG,
                )

        # Circuit-proximity exit takes priority over the trailing
        # stop/manual checks below -- see _check_circuit_proximity()'s
        # own docstring. Checked every tick, same immediacy as the
        # trailing stop, not gated on candle close.
        self._check_circuit_proximity(symbol, price, tick_time)

        # Trailing stop is capital protection -- checked on every
        # tick, intrabar, not just on candle close.
        self._check_trailing_stop(symbol, price, tick_time)
        self._check_manual_exit(symbol, price, tick_time)

    # --------------------------------------------------

    def _try_structural_entry(self, symbol, security_id, closed_candle,
                               direction, entry_reason):
        """
        The gate a valid structural signal passes through before
        becoming a real entry. See module docstring for the two
        checks and why each exists. Already-blocked directions
        short-circuit immediately -- no repeat news/sector lookup,
        no repeat log line, every candle the breakout keeps firing.
        """
        # Cheapest, most fundamental check, first -- see SQUARE_OFF_T's
        # module-level comment for the real bug this fixes (74 open
        # positions and still buying at 15:18, three minutes past
        # square-off). Checked against the candle's own tick_time
        # (market time), not wall clock, same convention as
        # core/orb_engine.py's MARKET_OPEN_T/ORB_WINDOW_END_T. Silent
        # skip, no log line -- this fires on every candle close for
        # the rest of the session once past square-off, every symbol,
        # and would flood the console otherwise.
        candle_time = closed_candle.get("time") if closed_candle else None
        if candle_time is not None and candle_time.time() >= SQUARE_OFF_T:
            return

        # Frozen price (see FROZEN_PRICE_STREAK_CANDLES) -- a circuit
        # lock or a dead feed shouldn't be allowed to manufacture
        # "breakouts" out of a price that structurally never moved.
        # Silent skip, same
        # as the square-off check above -- this fires on every candle
        # close for as long as the freeze lasts and would flood the
        # console otherwise; _is_frozen() itself already logs once
        # per freeze episode.
        if self._is_frozen(symbol):
            return

        # Proactive circuit-limit approach (see core/circuit_monitor.py) --
        # direction-agnostic, same as the frozen check above: a symbol
        # approaching EITHER circuit gets no new entries, not just the
        # direction that would be walking into the unfavourable one.
        # Silent skip, same reasoning as the frozen check -- this fires
        # on every candle close for as long as the approach lasts and
        # circuit_monitor itself already warns once per episode.
        if self.circuit_monitor is not None and self.circuit_monitor.is_flagged(symbol):
            return

        if direction in self.entry_blocked.get(symbol, {}):
            return

        # TOP_N_MOMENTUM_MODE (config.py, 2026-07-24 experiment):
        # cheapest, most restrictive check first -- only today's
        # locked top-25-gainers (LONG) / top-25-losers (SHORT) are
        # eligible at all. Silent skip, no entry_blocked entry and
        # no log line -- entry_blocked is for a specific news/
        # sector REASON a signal was refused; "not on today's
        # shortlist" applies to 700+ symbols constantly and would
        # just be noise there. False before the universe is even
        # locked (fail-closed -- see MomentumUniverse.is_eligible()),
        # which is fine: no structural signal can fire before
        # ORB_WINDOW_END anyway.
        if TOP_N_MOMENTUM_MODE and self.momentum_universe is not None \
                and not self.momentum_universe.is_eligible(symbol, direction):
            return

        contradiction = self._news_contradiction(symbol, direction)
        if contradiction is not None:
            self._block_entry(
                symbol, direction,
                f"contradicting news -- {contradiction}",
            )
            return

        if direction == LONG and self.sector_monitor is not None \
                and self.sector_monitor.is_symbol_in_panicking_sector(symbol):
            sector = self.sector_monitor.sector_of(symbol)
            self._block_entry(
                symbol, direction,
                f"sector '{sector}' is panic-flagged today -- broad, "
                f"sentiment-driven decline, not this stock's own "
                f"fundamentals",
            )
            return

        stop_seed, target = self._entry_stop_and_target(
            symbol, direction, closed_candle["close"]
        )
        self._enter(
            symbol, security_id, closed_candle["close"], stop_seed,
            closed_candle["time"], entry_reason, direction, target=target,
        )

    def _entry_stop_and_target(self, symbol, direction, entry_price):
        """
        Returns (stop_price, target_price) for a new STRUCTURAL
        entry. target_price is None outside TOP_N_MOMENTUM_MODE --
        this bot's default design has never had a fixed target
        (core/trailing_stop.py's own docstring: ride the trend,
        dynamic, no cap) and stays that way unless the mode is on.
        Manual buys never call this -- they keep the old dynamic-
        trailing, no-target behaviour unconditionally (see
        process_tick()'s manual-buy branch).

        Requires self.momentum_universe to actually be wired in, not
        just the config flag -- same guard as the eligibility check
        in _try_structural_entry(). A bare Engine() with no
        momentum_universe (every existing test, anything that
        doesn't explicitly opt in) gets the original ORB-boundary
        dynamic-trailing behaviour regardless of the flag's default,
        exactly as if the feature didn't exist for it.
        """
        if TOP_N_MOMENTUM_MODE and self.momentum_universe is not None:
            return self._fixed_bracket_prices(direction, entry_price)
        return self._orb_stop_seed(symbol, direction), None

    def _fixed_bracket_prices(self, direction, entry_price):
        """
        TOP_N_MOMENTUM_MODE only -- FIXED_STOP_LOSS_RS /
        FIXED_TARGET_RS (config.py) are total position P&L in
        rupees, converted to per-share price levels using the
        flat LAYER1_FIXED_QTY every structural entry actually
        uses. Mirrored for SHORT (stop above entry, target below).
        """
        qty = LAYER1_FIXED_QTY
        stop_per_share = FIXED_STOP_LOSS_RS / qty
        target_per_share = FIXED_TARGET_RS / qty
        if direction == LONG:
            return entry_price - stop_per_share, entry_price + target_per_share
        return entry_price + stop_per_share, entry_price - target_per_share

    def _orb_stop_seed(self, symbol, direction):
        """
        Initial stop = the OPPOSITE boundary of the ORB range itself
        (plus a small buffer), not the breakout candle's own low/
        high. Operator-corrected 2026-07-23 -- see config.py's
        ORB_STOP_BUFFER_PCT docstring for why: a 1-minute candle can
        be a few paise wide, which isn't a real invalidation level
        for an ORB trade. "The range failed" is the actual
        structural stop; this gives the trade the full range width
        as room, same as the boundary the breakout itself was
        measured against.
        """
        orb_range = self.orb_engine.get_range(symbol)
        buffer_mult = ORB_STOP_BUFFER_PCT / 100
        if direction == LONG:
            return orb_range["low"] * (1 - buffer_mult)
        return orb_range["high"] * (1 + buffer_mult)

    def _update_frozen_streak(self, symbol, closed_candle):
        """
        See config.py's FROZEN_PRICE_STREAK_CANDLES docstring for
        the real bug this catches (HFCL, 2026-07-23: 12 phantom
        round trips over ~4 hours after its price stopped moving --
        operator-confirmed root cause was HFCL hitting its LOWER
        CIRCUIT at 11:49, not a dead feed; the fix applies equally
        either way). Tracks how many CONSECUTIVE closed candles for
        this symbol have printed the exact same O=H=L=C value -- a
        live, actively-traded, non-circuit-locked stock essentially
        never does this by chance. Resets the instant a genuinely
        different price prints.
        """
        is_flat_candle = closed_candle["high"] == closed_candle["low"]
        close = closed_candle["close"]
        streak = self._frozen_streak.get(symbol)

        if is_flat_candle and streak is not None and streak[0] == close:
            self._frozen_streak[symbol] = (close, streak[1] + 1)
        elif is_flat_candle:
            self._frozen_streak[symbol] = (close, 1)
        else:
            self._frozen_streak.pop(symbol, None)
            self._frozen_warned.discard(symbol)

    def _is_frozen(self, symbol):
        """
        True once a symbol has strung together
        FROZEN_PRICE_STREAK_CANDLES consecutive identical closes.
        Warns once per freeze episode (edge-triggered, mirrors
        core/market_data.py's own stale-tick warning pattern) --
        callers should still short-circuit silently on every
        subsequent candle for as long as the freeze lasts.
        """
        streak = self._frozen_streak.get(symbol)
        if streak is None or streak[1] < FROZEN_PRICE_STREAK_CANDLES:
            return False

        if symbol not in self._frozen_warned:
            self._frozen_warned.add(symbol)
            warn(
                f"[FROZEN_FEED] {symbol} price hasn't moved in "
                f"{streak[1]} consecutive candles (stuck at "
                f"{streak[0]:.2f}) -- likely a circuit lock or a dead "
                f"feed. No new entries and no trailing-stop ratchet "
                f"for {symbol} until the price actually moves again."
            )
        return True

    def _check_circuit_proximity(self, symbol, price, tick_time):
        """
        Operator instruction, post-HFCL discussion 2026-07-23:
        "Bullish & Bearish irrespective we will close the open
        position before circuits." Direction-agnostic by design --
        this does NOT check whether the approaching circuit favours
        the open position (upper for a long, lower for a short) or
        not; either way there's no real counterparty for an exit
        order once the lock actually happens, so the position closes
        pre-emptively regardless. Runs ahead of the trailing
        stop/manual-exit checks in process_tick() -- a circuit
        approach is a market-structure exit, not a normal risk-
        management one, and takes priority.
        """
        if self.circuit_monitor is None:
            return
        if symbol not in self.open_positions:
            return
        if not self.circuit_monitor.is_flagged(symbol):
            return

        flag = self.circuit_monitor.get_flag(symbol)
        detail = (
            f" ({flag['side']}, gap={flag['gap_pct'] * 100:.2f}%)"
            if flag else ""
        )
        decision(
            f"CIRCUIT PROXIMITY EXIT: {symbol} price={price:.2f}{detail} -- "
            f"closing ahead of the circuit lock, irrespective of direction."
        )
        self._exit(symbol, price, EXIT_REASON_CIRCUIT_PROXIMITY, tick_time)

    def get_circuit_flagged_symbols(self):
        """
        Public read for the dashboard (see dashboard/state.py's
        risk-filters panel), same pattern as get_frozen_symbols()
        just below. Returns [] whenever no circuit_monitor is wired
        in, same fail-safe default as every other optional reader.
        """
        if self.circuit_monitor is None:
            return []
        return self.circuit_monitor.get_flagged_symbols()

    def get_circuit_snapshot(self):
        """
        Public read for the dashboard's gainers/losers table (see
        dashboard/state.py's _build_gainers_losers()) -- the raw
        per-symbol OHLC/prev-close/volume/LTP data circuit_monitor's
        poll cycle already fetches for proximity checking. Returns
        {} whenever no circuit_monitor is wired in, same fail-safe
        default as get_circuit_flagged_symbols() above.
        """
        if self.circuit_monitor is None:
            return {}
        return self.circuit_monitor.get_snapshot()

    def get_frozen_symbols(self):
        """
        Public read for the dashboard (see dashboard/state.py's
        risk-filters panel) -- symbols currently past
        FROZEN_PRICE_STREAK_CANDLES consecutive identical closes.
        A plain list snapshot, safe to call from another thread the
        same way entry_blocked/open_positions already are (dict
        comprehension over a dict copy, single GIL-holding pass).
        """
        return sorted(
            symbol for symbol, streak in dict(self._frozen_streak).items()
            if streak[1] >= FROZEN_PRICE_STREAK_CANDLES
        )

    def _news_contradiction(self, symbol, direction):
        """
        Returns a short description if today's latest HIGH-priority
        news for `symbol` points the OPPOSITE way from `direction`,
        else None. HIGH tier already guarantees confidence >= the
        configured threshold, materiality == "material", and a
        real direction (never neutral) -- see
        news_bot/priority.py's tier_for().
        """
        if self.news_gate is None:
            return None

        item = self.news_gate.latest_high_priority(symbol)
        if item is None:
            return None

        if item["direction"] == _AGREEING_NEWS_DIRECTION[direction]:
            return None

        return f"{item['direction']} ({item['confidence']}%) -- {item['reason']}"

    def _block_entry(self, symbol, direction, reason):
        self.entry_blocked.setdefault(symbol, {})[direction] = reason
        warn(
            f"[NO_TRADE] {symbol} {direction} skipped -- {reason}. "
            f"No {direction.lower()} trade for {symbol} today."
        )

    # --------------------------------------------------

    def _enter(self, symbol, security_id, price, stop_seed,
               entry_time, entry_reason, direction, target=None):
        qty = LAYER1_FIXED_QTY

        # MIS buying-power gate -- operator-approved 2026-07-23,
        # applies to EVERY new position, structural or manual
        # (unlike the news/sector checks, which are strategy
        # judgment calls a manual override is allowed to
        # supersede, margin is a hard capital constraint -- you
        # don't get to override not having the money). Deliberately
        # NOT persisted or "for the rest of the day" like
        # entry_blocked -- buying power frees up the moment another
        # position closes, so this is re-checked fresh on every
        # single entry attempt, never cached.
        if self.portfolio is not None and not self.portfolio.has_buying_power_for(
                self.open_positions, price, qty):
            available = self.portfolio.available_buying_power(self.open_positions)
            warn(
                f"[MARGIN] {symbol} {direction} skipped -- insufficient "
                f"buying power for {qty} qty @ {price:.2f} "
                f"(needs {price * qty:,.0f}, {available:,.0f} available)."
            )
            return

        news_line = ""
        if self.news_gate is not None:
            note = self.news_gate.describe(symbol)
            if note is not None:
                news_line = f"\nHIGH news today: {note}"

        bracket_line = (
            f"\nFixed stop     : {stop_seed:.2f}\nFixed target   : {target:.2f}"
            if target is not None else ""
        )

        if entry_reason == ENTRY_REASON_STRUCTURAL_LONG:
            orb_range = self.orb_engine.get_range(symbol)
            decision(
                f"\nORB BREAKOUT   : {symbol}\n"
                f"ORB High       : {orb_range['high']:.2f}\n"
                f"ORB Low        : {orb_range['low']:.2f}\n"
                f"Breakout Close : {price:.2f}"
                f"{bracket_line}"
                f"{news_line}"
            )
        elif entry_reason == ENTRY_REASON_STRUCTURAL_SHORT:
            orb_range = self.orb_engine.get_range(symbol)
            decision(
                f"\nORB BREAKDOWN  : {symbol}\n"
                f"ORB High       : {orb_range['high']:.2f}\n"
                f"ORB Low        : {orb_range['low']:.2f}\n"
                f"Breakdown Close: {price:.2f}"
                f"{bracket_line}"
                f"{news_line}"
            )
        else:
            decision(
                f"\nMANUAL BUY (dashboard): {symbol}\n"
                f"Price                  : {price:.2f}"
                f"{news_line}"
            )

        if direction == LONG:
            result = self.execution.buy(
                security_id, symbol, price, qty, reason=entry_reason
            )
        else:
            result = self.execution.sell(
                security_id, symbol, price, qty, reason=entry_reason
            )

        if not result.get("success"):
            return

        self.open_positions[symbol] = {
            "security_id": security_id,
            "qty": qty,
            "entry_price": price,
            "entry_reason": entry_reason,
            "entry_time": entry_time,
            "direction": direction,
            # The stop AS SEEDED at entry -- never updated after this,
            # even as trailing_stop.py ratchets the LIVE stop forward.
            # This is what real risk (R) was accepted for THIS trade,
            # needed to compute an honest RR (risk:reward) on the
            # dashboard even after the position closes and
            # trailing_stop.clear() wipes the live ratcheted state.
            "initial_stop": stop_seed,
            # TOP_N_MOMENTUM_MODE only -- fixed target price, checked
            # by _check_fixed_bracket() instead of the ratcheting
            # trailing stop. None for every other entry (manual buys,
            # or any structural entry when the mode is off), which is
            # exactly how the dashboard/exit logic tells "fixed
            # bracket trade" from "normal dynamic-trailing trade".
            "fixed_target": target,
        }
        # Fixed-bracket trade (target is not None): stop_seed is
        # already the fixed stop PRICE (see _fixed_bracket_prices())
        # and lives on "initial_stop" above -- _check_fixed_bracket()
        # reads it directly, no trailing_stop.start() call, this
        # trade is deliberately NOT ratcheted (operator's explicit
        # choice: "keep the Stop loss & targets as fixed").
        if target is None:
            self.trailing_stop.start(symbol, stop_seed, direction=direction)

        if self.portfolio is not None:
            if direction == LONG:
                self.portfolio.on_buy(price, qty)
            else:
                self.portfolio.on_short(price, qty)

    # --------------------------------------------------

    def _check_trailing_stop(self, symbol, price, tick_time):
        position = self.open_positions.get(symbol)
        if position is None:
            return

        # Fixed-bracket trades (TOP_N_MOMENTUM_MODE) never use the
        # ratcheting trailing stop -- routed by the position's OWN
        # "fixed_target" field, not the global config flag, so an
        # already-open trade keeps behaving exactly as it was opened
        # even if the flag gets toggled mid-session.
        if position.get("fixed_target") is not None:
            self._check_fixed_bracket(symbol, position, price, tick_time)
            return

        if not self.trailing_stop.is_hit(symbol, price):
            return

        stop_price = self.trailing_stop.get_stop(symbol)
        decision(
            f"TRAILING STOP HIT: {symbol} stop={stop_price:.2f} "
            f"price={price:.2f}"
        )
        self._exit(symbol, price, EXIT_REASON_TRAILING_STOP, tick_time)

    def _check_fixed_bracket(self, symbol, position, price, tick_time):
        """
        TOP_N_MOMENTUM_MODE only. Both levels fixed at entry --
        "initial_stop" (never changes, same field every other
        position uses for the RR calc) and "fixed_target". Stop is
        checked before target on a tick that crosses both at once
        (e.g. a gap) -- same capital-protection-first precedence as
        the trailing stop.
        """
        direction = position.get("direction", LONG)
        stop_price = position.get("initial_stop")
        target_price = position.get("fixed_target")
        if stop_price is None or target_price is None:
            return

        hit_stop = price <= stop_price if direction == LONG else price >= stop_price
        hit_target = price >= target_price if direction == LONG else price <= target_price

        if hit_stop:
            decision(
                f"FIXED STOP HIT: {symbol} stop={stop_price:.2f} "
                f"price={price:.2f}"
            )
            self._exit(symbol, price, EXIT_REASON_FIXED_STOP, tick_time)
        elif hit_target:
            decision(
                f"FIXED TARGET HIT: {symbol} target={target_price:.2f} "
                f"price={price:.2f}"
            )
            self._exit(symbol, price, EXIT_REASON_FIXED_TARGET, tick_time)

    def _maybe_snapshot_exit_all(self):
        """
        Real bug, live, 2026-07-23: the old code just checked
        "is trade_controller.is_exit_all_requested() True", with no
        memory of WHICH positions the operator actually meant. With
        re-entry unblocked the book went 74+ minutes without ever
        being fully empty, so EVERY new position opened during that
        window got force-sold as MANUAL_EXIT within 0-1 seconds --
        2039 phantom trades, ~Rs 7,707 in paper-mode churn (real
        slippage/brokerage cost in live).

        "exitall" is a one-shot request against whatever was open at
        the exact moment it was issued (see _exit()'s docstring) --
        never a standing order that also claims anything opened
        afterward. Fixed by capturing that moment explicitly: the
        first tick (any symbol) that observes the flag freshly set
        snapshots the currently-open symbols into
        self._exit_all_snapshot. Only THOSE symbols are exited by
        _check_manual_exit() below; anything opened later is a fresh
        position, untouched by this batch, and just follows its own
        normal exit logic (trailing stop / fixed bracket / square
        off) like any other trade.

        If nothing was open at that moment, the snapshot is the
        empty set and the flag is cleared immediately right here --
        an exit-all issued against a flat book has nothing to do and
        must not linger, or the next position opened (possibly hours
        later) would be phantom-exited the instant it opens, which
        is the exact same bug in a different shape.
        """
        if not self.trade_controller.is_exit_all_requested():
            return
        if self._exit_all_snapshot is not None:
            return  # already snapshotted, batch in flight

        self._exit_all_snapshot = set(self.open_positions.keys())
        if not self._exit_all_snapshot:
            self.trade_controller.clear_exit_all()
            self._exit_all_snapshot = None

    def _check_manual_exit(self, symbol, price, tick_time):
        if symbol not in self.open_positions:
            return

        should_exit = (
            (self._exit_all_snapshot is not None
             and symbol in self._exit_all_snapshot)
            or self.trade_controller.is_exit_requested(symbol)
        )

        if not should_exit:
            return

        self._exit(symbol, price, EXIT_REASON_MANUAL, tick_time)
        self.trade_controller.clear_exit(symbol)

    def _exit(self, symbol, price, reason, exit_time):
        position = self.open_positions[symbol]
        direction = position.get("direction", LONG)

        pnl = None
        if direction == LONG:
            self.execution.sell(
                position["security_id"], symbol, price, position["qty"],
                reason=reason,
            )
            if self.portfolio is not None:
                pnl = self.portfolio.on_sell(
                    position["entry_price"], price, position["qty"]
                )
        else:
            self.execution.buy(
                position["security_id"], symbol, price, position["qty"],
                reason=reason,
            )
            if self.portfolio is not None:
                pnl = self.portfolio.on_cover(
                    position["entry_price"], price, position["qty"]
                )

        holding_seconds = None
        entry_time = position.get("entry_time")
        if entry_time is not None and exit_time is not None:
            holding_seconds = (exit_time - entry_time).total_seconds()

        self.closed_positions.append({
            "symbol": symbol,
            "security_id": position["security_id"],
            "qty": position["qty"],
            "entry_price": position["entry_price"],
            "entry_time": entry_time,
            "entry_reason": position.get("entry_reason"),
            "direction": direction,
            "initial_stop": position.get("initial_stop"),
            "exit_price": price,
            "exit_time": exit_time,
            "exit_reason": reason,
            "holding_seconds": holding_seconds,
            "pnl": pnl,
        })

        del self.open_positions[symbol]
        self.trailing_stop.clear(symbol)

        # Operator-approved 2026-07-23, after the first live session
        # showed the same symbol re-triggering the same direction
        # 3-4 times in a row, each one a fresh small loss (BLUESTONE,
        # IDEA, WAKEFIT, JYOTHYLAB in that morning's trade_log.csv).
        # A stop-out on a STRUCTURAL entry means the breakout already
        # failed once today -- re-attempting the identical direction
        # on the same symbol is fighting the same signal that already
        # proved wrong, not a fresh opportunity. One attempt per
        # symbol per direction per day, same "NO TRADE today" ledger
        # already used for news/sector blocks. The OPPOSITE direction
        # stays fully available -- a failed long says nothing about
        # whether a later short setup is valid. Manual exits and
        # square-off never block -- only a genuine stop-out does.
        #
        # Re-enabled by default from 2026-07-24 onward (config.py's
        # docstring). EXIT_REASON_FIXED_STOP counts here too, same
        # as EXIT_REASON_TRAILING_STOP -- a fixed-bracket stop-out
        # is just as much "this breakout already failed today" as a
        # trailing one was. EXIT_REASON_FIXED_TARGET does NOT --
        # that's a win, not a failed signal, and must never block.
        if BLOCK_REENTRY_AFTER_STOPOUT \
                and reason in (EXIT_REASON_TRAILING_STOP, EXIT_REASON_FIXED_STOP) \
                and position.get("entry_reason") in (
                    ENTRY_REASON_STRUCTURAL_LONG, ENTRY_REASON_STRUCTURAL_SHORT):
            self._block_entry(
                symbol, direction,
                "stopped out once today -- no repeat attempts in the "
                "same direction",
            )

        # Drain this symbol out of the exit-all snapshot regardless
        # of WHY it closed -- a snapshotted symbol that stops out on
        # its trailing stop, hits its fixed target, or gets squared
        # off is just as "done" for exit-all purposes as one that
        # closed via the exit-all path itself. Once the snapshot is
        # fully drained, clear the controller flag and reset the
        # snapshot so the next exit-all request starts fresh. See
        # _maybe_snapshot_exit_all() for the full reasoning -- this
        # replaces the old "wait for open_positions to be fully
        # empty" check, which never fired while re-entries kept the
        # book non-empty for 74+ minutes straight.
        if self._exit_all_snapshot is not None:
            self._exit_all_snapshot.discard(symbol)
            if not self._exit_all_snapshot:
                self.trade_controller.clear_exit_all()
                self._exit_all_snapshot = None

    # --------------------------------------------------

    def export_positions(self):
        """Plain-dict snapshot, safe to json.dump directly.
        entry_time (a datetime) is converted to isoformat since
        JSON has no native datetime type."""
        return {
            symbol: {
                **position,
                "entry_time": (
                    position["entry_time"].isoformat()
                    if position.get("entry_time") else None
                ),
            }
            for symbol, position in self.open_positions.items()
        }

    def load_positions(self, positions):
        """
        Restores open positions from a snapshot produced by
        export_positions(). Overwrites, never merges -- same
        reasoning as OrbEngine.load_state(). entry_time is
        parsed back from isoformat if present. "direction"
        defaults to LONG if missing (snapshots saved before
        shorts existed). "initial_stop" defaults to None if
        missing (snapshots saved before RR tracking existed) --
        the dashboard's RR calc must treat None as "unknown",
        never guess a risk figure that was never actually set."""
        restored = {}
        for symbol, position in positions.items():
            position = dict(position)
            if position.get("entry_time"):
                position["entry_time"] = datetime.fromisoformat(
                    position["entry_time"]
                )
            position.setdefault("direction", LONG)
            position.setdefault("initial_stop", None)
            # None default for snapshots saved before fixed-bracket
            # mode existed -- treated as a normal dynamic-trailing
            # position, same as it always was.
            position.setdefault("fixed_target", None)
            restored[symbol] = position
        self.open_positions = restored

    def export_entry_blocks(self):
        """Plain-dict snapshot, safe to json.dump directly."""
        return {
            symbol: dict(directions)
            for symbol, directions in self.entry_blocked.items()
        }

    def load_entry_blocks(self, blocks):
        """Restores from a snapshot produced by export_entry_blocks().
        Overwrites, never merges -- same reasoning as every other
        load_state() in this codebase."""
        self.entry_blocked = {
            symbol: dict(directions) for symbol, directions in blocks.items()
        }

    # --------------------------------------------------

    def flatten_all(self, get_price):
        """
        Called at SQUARE_OFF_TIME. get_price(symbol) ->
        latest known price.
        """
        now = datetime.now()
        for symbol in list(self.open_positions.keys()):
            price = get_price(symbol) or self.open_positions[symbol][
                "entry_price"
            ]
            self._exit(symbol, price, EXIT_REASON_SQUARE_OFF, now)

        decision("SQUARE OFF: all positions flattened.")
