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

import time as time_module
from datetime import datetime, time as dtime

from config import (
    LAYER1_FIXED_QTY, ORB_STOP_BUFFER_PCT, BLOCK_REENTRY_AFTER_STOPOUT,
    TOP_N_MOMENTUM_MODE, FIXED_TARGET_RS, FIXED_STOP_LOSS_RS,
    SQUARE_OFF_TIME, FROZEN_PRICE_STREAK_CANDLES,
    ATR_PERIOD, MIN_ATR_CANDLES, RISK_PER_TRADE_RS,
    ATR_STOP_MULTIPLIER, ATR_TRAIL_MULTIPLIER, ATR_TRAIL_ACTIVATION_MULT,
    MIN_STOP_DISTANCE_PCT, MAX_NOTIONAL_PER_TRADE_RS,
    MIN_TRADABLE_PRICE_RS, EARNINGS_CALENDAR,
    ENABLE_PARTIAL_EXIT, PARTIAL_EXIT_ATR_MULTIPLE, PARTIAL_EXIT_FRACTION,
    PARTIAL_EXIT_MIN_PCT,
    LAST_ENTRY_TIME, REGIME_GATE_ENABLED, REGIME_BREADTH_THRESHOLD,
    REGIME_REFRESH_SECONDS, REGIME_MIN_SYMBOLS,
    MAX_OPEN_POSITIONS, DAILY_MAX_LOSS_RS, DAILY_PROFIT_TARGET_RS,
    BREAKOUT_MIN_MARGIN_PCT,
    ENABLE_TREND_RANK_ENTRY, TREND_RANK_TOP_N, TREND_RANK_REFRESH_SECONDS,
    ENABLE_SLOT_ROTATION, ROTATION_MIN_STRENGTH_EDGE,
    ENABLE_RS_BAND, RS_BAND_MIN, RS_BAND_MAX, MAX_ABS_MOVE_PCT,
    ENABLE_STILL_TRENDING, STILL_TRENDING_MIN_POSITION,
    ENABLE_STAGED_ENTRY, STAGED_POSITION_LIMITS, STAGED_NO_ENTRY_AFTER,
    ONE_TRADE_PER_SYMBOL_PER_DAY,
    ENABLE_NO_PROGRESS_EXIT, NO_PROGRESS_MINUTES, NO_PROGRESS_R,
    ENABLE_ORB_EXCHANGE_RECONCILE,
    ENABLE_TICK_SANITY, MAX_TICK_JUMP_PCT,
    ENABLE_LIQUIDITY_FLOOR, MIN_TURNOVER_RS,
    ENABLE_STOCK_MEMORY, MEMORY_ACTION_WINDOW_DAYS,
    ENABLE_SECTOR_STRENGTH_GATE, SECTOR_STRENGTH_TOP_N,
    SECTOR_STRENGTH_MIN_SYMBOLS, SECTOR_STRENGTH_REFRESH_SECONDS,
    ENABLE_EARLY_MOMENTUM_ENTRY, EARLY_ENTRY_MIN_RS,
    EARLY_ENTRY_MAX_POSITIONS,
    ENABLE_VOLUME_FILTER, VOLUME_SURGE_MULT, VOLUME_AVG_CANDLES,
    MIN_VOLUME_CANDLES,
)
from core.atr import compute_atr
from core.orb_engine import OrbEngine, EARLY_ORB_END_T, ORB_WINDOW_END_T
from core.candle_engine import CandleEngine
from core.strategy import Strategy
from core.trailing_stop import TrailingStopEngine, LONG, SHORT
from core.logger import decision, diagnostic, warn

# Position "stop_mode" values -- decides HOW an open position's
# stop is managed after entry (core/engine.py's _check_trailing_stop()
# routing). SWING_TRAILING is the original, default behaviour
# (core/trailing_stop.py's rolling swing-high/low ratchet); it's
# the default on every _enter() call so manual buy/short and any
# non-momentum structural entry are completely unaffected by the
# 2026-07-24 ATR redesign. ATR_TRAILING is momentum-mode only, see
# _check_atr_trailing().
STOP_MODE_SWING_TRAILING = "SWING_TRAILING"
STOP_MODE_ATR_TRAILING = "ATR_TRAILING"
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

# 2026-07-24 revamp -- no FRESH structural entries after this time
# (existing positions still fully managed). See config.LAST_ENTRY_TIME's
# docstring for the data-backed rationale (POST_MARKET item 10).
LAST_ENTRY_T = _parse_hhmm(LAST_ENTRY_TIME)

ENTRY_REASON_STRUCTURAL_LONG = "STRUCTURAL_LONG_BREAKOUT"
ENTRY_REASON_STRUCTURAL_SHORT = "STRUCTURAL_SHORT_BREAKDOWN"
ENTRY_REASON_MANUAL_DASHBOARD = "MANUAL_BUY_DASHBOARD"
# Mirrors ENTRY_REASON_MANUAL_DASHBOARD for the SHORT side -- added
# 2026-07-23 evening, dashboard's per-row SHORT button on the Top 50
# Losers table (see trading/trade_controller.py's docstring). Same
# operator-override reasoning as the LONG version, just direction-
# mirrored.
ENTRY_REASON_MANUAL_SHORT_DASHBOARD = "MANUAL_SHORT_DASHBOARD"
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

# Slot rotation (2026-07-24): this position was closed NOT because its
# own stop/target hit, but because a decisively stronger-trending
# breakout needed its seat (see _try_structural_entry's rotation
# block). Like CIRCUIT_PROXIMITY, it is NOT a losing-signal stop-out,
# so it must never arm BLOCK_REENTRY_AFTER_STOPOUT -- the rotated-out
# name can be re-entered later if it climbs back up the leaderboard.
EXIT_REASON_ROTATED_OUT = "ROTATED_OUT"

# 2026-07-25: the position never got going. Not a stop-out (price
# never hit the stop) and not a win -- just dead money holding a
# slot. Freed deliberately so a live signal can use the seat. Like
# ROTATED_OUT, never arms BLOCK_REENTRY_AFTER_STOPOUT.
EXIT_REASON_NO_PROGRESS = "NO_PROGRESS"

# ATR_TRAILING only, 2026-07-24 -- "dynamic position building"
# extension to item 3 (config.PARTIAL_EXIT_ATR_MULTIPLE's docstring).
# Books PART of the qty as a realized win while the position is
# still open and still running -- distinct from every other
# EXIT_REASON above, which always closes the WHOLE position. Never
# participates in BLOCK_REENTRY_AFTER_STOPOUT (it's a win, not a
# failed signal) and never appears in _exit() at all -- see
# _maybe_partial_exit()'s own bookkeeping.
EXIT_REASON_PARTIAL_PROFIT = "PARTIAL_PROFIT_ATR"


class Engine:

    def __init__(self, portfolio=None, sector_monitor=None,
                 momentum_universe=None, circuit_monitor=None, market_data=None,
                 min_tradable_price=MIN_TRADABLE_PRICE_RS,
                 earnings_calendar=None,
                 candle_recorder=None,
                 enable_rs_band=None, enable_staged_entry=None,
                 one_trade_per_symbol=None, enable_no_progress=None,
                 enable_tick_sanity=None, stock_memory=None,
                 trade_memory=None):
        # config.py's real value by default -- injectable purely so
        # tests can construct an Engine without it (this whole
        # suite's pre-existing price convention uses toy values like
        # 100-130 that predate the 2026-07-24 price-floor rule and
        # have nothing to do with testing it), same pattern already
        # used by TrailingStopEngine(window=...) and
        # CircuitMonitor(proximity_pct=...) in this codebase. Real
        # callers (main.py, tools/dashboard_preview.py) never pass
        # this, so production always gets the real config value.
        self.min_tradable_price = min_tradable_price
        # {"YYYY-MM-DD": {SYMBOL, ...}}. Defaults to config's static dict
        # so an offline run and every existing test behave exactly as
        # before; main.py passes a merged live+static calendar.
        self.earnings_calendar = (EARNINGS_CALENDAR if earnings_calendar
                                  is None else earnings_calendar)

        self.orb_engine = OrbEngine()
        self.candle_engine = CandleEngine()
        self.strategy = Strategy(self.orb_engine)
        self.trailing_stop = TrailingStopEngine()
        self.execution = Execution()
        self.trade_controller = TradeController()

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

        # Optional clean-corpus recorder (core/candle_recorder.py).
        # None in tests and any setup that doesn't want recording --
        # the candle-close path simply skips it.
        self.candle_recorder = candle_recorder

        # Per-stock facts (core/stock_memory.py) -- corporate actions
        # that change the PRICE SCALE. Consulted before every entry so
        # the bot never mistakes a split for a crash (the JLHL case).
        # None = no memory wired; every check then passes, i.e. today's
        # behaviour.
        self.stock_memory = stock_memory
        self._memory_cache = None

        # The LEARNING loop (core/trade_memory.py). Records completed
        # trades WITH the context they were taken in. Deliberately
        # OBSERVATION-ONLY: nothing in this engine reads it back to
        # make a decision -- see that module's docstring.
        self.trade_memory = trade_memory

        # Cached last-known-price reader -- see core/market_data.py.
        # None is fully supported (mirrors every other optional
        # reader here): _process_pending_manual_exits() just falls
        # back to only resolving the current tick's own symbol,
        # same as this codebase's behaviour before that fix existed.
        self.market_data = market_data

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

        # Market-regime gate cache, 2026-07-24 revamp (config.py's
        # REGIME_GATE_ENABLED block). (regime, computed_at_monotonic)
        # -- recomputed lazily at most every REGIME_REFRESH_SECONDS,
        # NEVER in the hot tick path more often than that; the
        # underlying read is circuit_monitor's already-cached REST
        # snapshot, so a refresh is pure dict iteration, no network.
        # NOT persisted -- regime is a live market condition.
        self._regime_cache = None

        # Trend-rank leaderboard cache (2026-07-24) -- the top-N gainers/
        # losers sets + the %change map, rebuilt at most every
        # TREND_RANK_REFRESH_SECONDS from circuit_monitor's snapshot.
        # (pct_map, long_set, short_set, usable_count, computed_at).
        self._trend_cache = None

        # 2026-07-25 -- one attempt per (symbol, direction) per day.
        # {symbol: {"LONG", "SHORT"}} of directions already ATTEMPTED
        # today (entered at least once), regardless of how they ended.
        self._attempted_today = {}

        # Symbols whose ORB range has already been reconciled against
        # the exchange's own high/low (see _reconcile_orb_once).
        self._orb_reconciled = set()

        # Last price ACCEPTED per symbol + one-shot warn set, for
        # the corrupt-tick guard (_is_insane_tick).
        self._last_good_price = {}
        self._insane_tick_warned = set()

        # Realized P&L already booked earlier today (seeded at startup
        # from the persisted portfolio) so the daily guardrails survive a
        # restart -- see _daily_realized_pnl()/seed_daily_pnl().
        self._carried_pnl = 0.0

        # Symbols whose EARLY range has been exchange-reconciled.
        self._early_orb_reconciled = set()

        # Symbols whose overnight gap has been logged once
        # (observation only -- see _note_gap).
        self._gap_noted = set()

        # Sector leaderboard cache (strong, weak, ranked, computed_at)
        self._sector_cache = None

        # How many EARLY-momentum entries were taken today (capped by
        # config.EARLY_ENTRY_MAX_POSITIONS -- these skip the full ORB
        # window so they are deliberately rare).
        self._early_entries_taken = 0

        # 2026-07-25 strategy-package gates. Default to config, but
        # injectable per-Engine -- same pattern (and same reasoning) as
        # min_tradable_price above: this suite's older tests exercise
        # DIFFERENT mechanics (ATR sizing, trailing, partial exits) on
        # toy fixtures that predate these gates, so they construct an
        # Engine with them off. Production never passes these, so the
        # real bot always gets the config values.
        self.enable_rs_band = (
            ENABLE_RS_BAND if enable_rs_band is None else enable_rs_band)
        self.enable_staged_entry = (
            ENABLE_STAGED_ENTRY if enable_staged_entry is None
            else enable_staged_entry)
        self.one_trade_per_symbol = (
            ONE_TRADE_PER_SYMBOL_PER_DAY if one_trade_per_symbol is None
            else one_trade_per_symbol)
        self.enable_no_progress = (
            ENABLE_NO_PROGRESS_EXIT if enable_no_progress is None
            else enable_no_progress)
        self.enable_tick_sanity = (
            ENABLE_TICK_SANITY if enable_tick_sanity is None
            else enable_tick_sanity)

        # Edge-triggered logging for regime changes -- log the
        # regime ONCE when it changes, not on every skipped entry.
        self._last_logged_regime = None

        # Edge-triggered logging for the daily loss/profit guardrails
        # (config.DAILY_MAX_LOSS_RS / DAILY_PROFIT_TARGET_RS) -- the
        # gate fires on every candle close for the rest of the day
        # once tripped; log the moment it trips, once, loudly.
        self._daily_halt_logged = None

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

    def process_tick(self, symbol, security_id, price, tick_time, cum_volume=None):
        # TICK SANITY (2026-07-25). Reject an impossible price before it
        # can touch the ORB range, a candle, a stop, or an entry.
        #
        # Real corrupt data found in one session's feed: INFY printed
        # 1037 -> 111 -> back within a minute; JLHL moved -80% in a
        # minute. In a backtest that manufactured a fake +Rs145,000
        # "profit". LIVE, the same glitch would fire every stop in that
        # symbol and could trigger a phantom breakout entry -- with real
        # money. A >20% single-tick move is not a market move, it is bad
        # data (genuine limit moves are capped far below this, and a
        # halted/circuit stock simply stops ticking).
        if self._is_insane_tick(symbol, price):
            return

        self._maybe_snapshot_exit_all()

        self.orb_engine.update(symbol, price, tick_time)

        closed_candle = self.candle_engine.update(
            symbol, price, tick_time, cum_volume
        )

        if closed_candle is not None:
            diagnostic(
                f"[CANDLE] {symbol} closed "
                f"O={closed_candle['open']:.2f} "
                f"H={closed_candle['high']:.2f} "
                f"L={closed_candle['low']:.2f} "
                f"C={closed_candle['close']:.2f}"
            )

            # Clean-corpus recording (2026-07-25) -- every real closed
            # candle goes to the replay bench's store so the strategy
            # can be validated across MANY real sessions instead of one
            # scraped, partly-corrupt log. Buffered + fail-safe: it can
            # never break tick processing (core/candle_recorder.py).
            if self.candle_recorder is not None:
                self.candle_recorder.record(symbol, closed_candle)

            # Exchange-truth ORB reconciliation (2026-07-25) -- runs
            # once per symbol as soon as the range is complete.
            self._reconcile_orb_once(symbol)

            self._update_frozen_streak(symbol, closed_candle)

            already_open = symbol in self.open_positions

            if already_open:
                # Old fixed-bracket trades (any TOP_N_MOMENTUM_MODE
                # position opened before the 2026-07-24 ATR redesign,
                # restored from core/state_store.py across a restart)
                # have no trailing to ratchet -- stop and target are
                # both fixed at entry, see _check_fixed_bracket(). ATR
                # trailing positions ratchet via their OWN dedicated
                # path just below, not the swing-based engine.
                #
                # A frozen candle (see FROZEN_PRICE_STREAK_CANDLES)
                # carries no real information about a safe stop level
                # -- ratcheting onto it would drag the stop flush
                # against the current (phantom) price and self-
                # trigger on the very next tick. Skip the ratchet
                # entirely while frozen; the position just sits,
                # protected by whatever stop it already had, until
                # the feed recovers or square-off closes it normally.
                position = self.open_positions[symbol]
                if not self._is_frozen(symbol):
                    if position.get("stop_mode") == STOP_MODE_ATR_TRAILING:
                        self._update_atr_trailing_on_candle_close(
                            symbol, position, closed_candle
                        )
                    elif position.get("fixed_target") is None:
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
                    ENTRY_REASON_STRUCTURAL_LONG, tick_time,
                )

            elif self.strategy.is_short_signal(
                symbol, closed_candle, already_open
            ):
                self._try_structural_entry(
                    symbol, security_id, closed_candle, SHORT,
                    ENTRY_REASON_STRUCTURAL_SHORT, tick_time,
                )

            else:
                # EARLY MOMENTUM (2026-07-25). Between the early range
                # closing (~09:20) and the full ORB completing (09:30)
                # the normal path can't trade at all -- the range isn't
                # ready -- so the first, often cleanest, move of the day
                # is unusable. This path lets a stock break its SHORT
                # first-5-minute range instead, but only if it clears a
                # deliberately higher bar (leading sector + stronger
                # relative strength) and only a couple of times a day.
                self._try_early_momentum_entry(
                    symbol, security_id, closed_candle, tick_time
                )

            # #0b, 2026-07-24 (evening): update the strategy's
            # beyond-range memory on EVERY closed candle (even the
            # already_open branch above, where no signal was checked),
            # so a breakout only fires on a fresh cross and can't
            # instantly re-fire the moment a position closes while
            # price is still beyond the range. Must run AFTER the
            # signal evaluation, which reads the PRIOR state.
            self.strategy.note_candle_close(symbol, closed_candle)

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
                # 2026-07-24 (evening): floor the seed at least
                # MIN_STOP_DISTANCE_PCT below entry. The last candle's
                # low can sit a rupee or two under price in a quiet
                # stock, giving a 0.02%-0.1% stop that noise clips in
                # seconds (ACUTAAS/IGIL/SYRMA, this session). Whichever
                # is LOWER (further from entry = more room) wins, so a
                # genuinely wide candle low is still respected.
                floor_low = price * (1 - MIN_STOP_DISTANCE_PCT)
                if last_candle and last_candle["low"] < price:
                    seed_low = min(last_candle["low"], floor_low)
                else:
                    seed_low = floor_low
                qty = self._risk_sized_qty(price, price - seed_low)
                self._enter(
                    symbol, security_id, price, seed_low, tick_time,
                    ENTRY_REASON_MANUAL_DASHBOARD, LONG, qty=qty,
                )

        # Manual short request (dashboard's per-row SHORT button on
        # the Top 50 Losers table) -- exact mirror of the manual buy
        # block above, direction flipped. Same operator-override
        # reasoning: bypasses news/sector checks, no pyramiding,
        # blocked past square-off.
        if self.trade_controller.is_short_requested(symbol):
            self.trade_controller.clear_short(symbol)
            if symbol in self.open_positions:
                warn(
                    f"[MANUAL_SHORT] {symbol} already has an open "
                    f"position -- request ignored, no pyramiding."
                )
            elif tick_time is not None and tick_time.time() >= SQUARE_OFF_T:
                warn(
                    f"[MANUAL_SHORT] {symbol} skipped -- past square-off "
                    f"time ({SQUARE_OFF_T}), no new positions today."
                )
            else:
                last_candle = self.candle_engine.last_closed(symbol)
                # Mirror of the LONG seed_low logic above -- a SHORT's
                # stop must always sit strictly ABOVE entry price. The
                # last closed candle's high can be stale or missing,
                # same reasoning as the LONG side, just flipped.
                # Mirror of the manual-buy floor above -- the seed
                # sits at least MIN_STOP_DISTANCE_PCT ABOVE entry, so a
                # short can't be handed a 0.02% stop off a barely-wide
                # last candle. Whichever is HIGHER (more room) wins.
                floor_high = price * (1 + MIN_STOP_DISTANCE_PCT)
                if last_candle and last_candle["high"] > price:
                    seed_high = max(last_candle["high"], floor_high)
                else:
                    seed_high = floor_high
                qty = self._risk_sized_qty(price, seed_high - price)
                self._enter(
                    symbol, security_id, price, seed_high, tick_time,
                    ENTRY_REASON_MANUAL_SHORT_DASHBOARD, SHORT, qty=qty,
                )

        # Circuit-proximity exit takes priority over the trailing
        # stop/manual checks below -- see _check_circuit_proximity()'s
        # own docstring. Checked every tick, same immediacy as the
        # trailing stop, not gated on candle close.
        self._check_circuit_proximity(symbol, price, tick_time)

        # Trailing stop is capital protection -- checked on every
        # tick, intrabar, not just on candle close.
        self._check_trailing_stop(symbol, price, tick_time)

        # Dead-money / no-progress exit (2026-07-25). Runs AFTER the
        # stop (a real stop-out must win the race and be recorded as
        # such) and only closes a position that never got going.
        self._check_no_progress(symbol, price, tick_time)

        self._process_pending_manual_exits(symbol, price, tick_time)

    # --------------------------------------------------

    def _market_regime(self):
        """
        2026-07-24 revamp (POST_MARKET item 1, "market-regime
        brain") -- returns "SHORT_ONLY", "LONG_ONLY", or "BOTH"
        from universe breadth on a prev_close basis, using
        circuit_monitor's already-cached REST snapshot (the same
        source the dashboard breadth panel reads -- no new network
        calls, ever, and cached here for REGIME_REFRESH_SECONDS on
        top so the tick path never pays even the dict iteration
        more than ~twice a minute).

        Fail-open on every unavailable input: gate disabled, no
        circuit_monitor wired (most tests), thin snapshot (<
        REGIME_MIN_SYMBOLS usable rows) all mean "BOTH" -- a
        missing opinion must never lock the bot one-sided.
        """
        if not REGIME_GATE_ENABLED or self.circuit_monitor is None:
            return "BOTH"

        now = time_module.monotonic()
        if self._regime_cache is not None \
                and now - self._regime_cache[1] < REGIME_REFRESH_SECONDS:
            return self._regime_cache[0]

        advancing = declining = 0
        for info in (self.circuit_monitor.get_snapshot() or {}).values():
            try:
                last = float(info.get("last_price") or 0)
                prev = float(info.get("prev_close") or 0)
            except (TypeError, ValueError):
                continue
            if last <= 0 or prev <= 0:
                continue
            if last > prev:
                advancing += 1
            elif last < prev:
                declining += 1

        total = advancing + declining
        if total < REGIME_MIN_SYMBOLS:
            regime = "BOTH"
        elif declining / total >= REGIME_BREADTH_THRESHOLD:
            regime = "SHORT_ONLY"
        elif advancing / total >= REGIME_BREADTH_THRESHOLD:
            regime = "LONG_ONLY"
        else:
            regime = "BOTH"

        self._regime_cache = (regime, now)
        if regime != self._last_logged_regime:
            self._last_logged_regime = regime
            decision(
                f"[REGIME] Market regime -> {regime} "
                f"(advancing={advancing} declining={declining})"
            )
        return regime

    def _trend_snapshot(self):
        """
        The live trend leaderboard, cached. Ranks every symbol in
        circuit_monitor's snapshot by %change vs previous close (the
        same data the dashboard gainers/losers use -- no new network
        calls), and returns (pct_map, long_eligible_set,
        short_eligible_set, usable_count).

        long_eligible  = the TREND_RANK_TOP_N biggest gainers.
        short_eligible = the TREND_RANK_TOP_N biggest losers.

        Cached for TREND_RANK_REFRESH_SECONDS so the tick path never
        pays the full sort more than ~once every few seconds. Returns
        empty sets + usable_count 0 when there's no circuit_monitor or
        the snapshot is empty -- callers fail OPEN on that.
        """
        if self.circuit_monitor is None:
            return {}, set(), set(), 0

        now = time_module.monotonic()
        if self._trend_cache is not None \
                and now - self._trend_cache[4] < TREND_RANK_REFRESH_SECONDS:
            return self._trend_cache[:4]

        pct_map = {}
        for sym, info in (self.circuit_monitor.get_snapshot() or {}).items():
            try:
                last = float(info.get("last_price") or 0)
                prev = float(info.get("prev_close") or 0)
            except (TypeError, ValueError):
                continue
            if last <= 0 or prev <= 0:
                continue
            pct_map[sym] = (last - prev) / prev

        ranked = sorted(pct_map, key=lambda s: pct_map[s])
        short_set = set(ranked[:TREND_RANK_TOP_N])            # weakest
        long_set = set(ranked[-TREND_RANK_TOP_N:]) if ranked else set()
        usable = len(pct_map)

        self._trend_cache = (pct_map, long_set, short_set, usable, now)
        return pct_map, long_set, short_set, usable

    def _is_trend_eligible(self, symbol, direction):
        """True if `symbol` may be entered in `direction` under the
        trend-rank rule: a LONG only in a top-N gainer, a SHORT only in
        a top-N loser. Fail-OPEN (returns True) when the feature is off,
        there's no circuit_monitor, or the snapshot is too thin to rank
        (usable < 2xN) -- a missing leaderboard must never freeze the
        bot, it just falls back to the prior all-symbols behaviour."""
        if not ENABLE_TREND_RANK_ENTRY or self.circuit_monitor is None:
            return True
        _, long_set, short_set, usable = self._trend_snapshot()
        if usable < TREND_RANK_TOP_N * 2:
            return True
        return symbol in (long_set if direction == LONG else short_set)

    def _symbol_strength(self, symbol, direction):
        """The symbol's trend strength in the trade's OWN favour: its
        %gain for a LONG, its %fall for a SHORT. Higher = a stronger
        trend behind the trade. None if unavailable (no ranking data)."""
        pct_map, _, _, _ = self._trend_snapshot()
        p = pct_map.get(symbol)
        if p is None:
            return None
        return p if direction == LONG else -p

    def _weakest_holder_for_rotation(self):
        """The open position with the LOWEST trend strength in its own
        direction -- the stalling laggard a stronger breakout should be
        allowed to evict. Returns (symbol, strength) or None if no open
        position has usable ranking data. A winning runner has high
        strength and is never selected here."""
        weakest = None
        for sym, pos in self.open_positions.items():
            s = self._symbol_strength(sym, pos.get("direction", LONG))
            if s is None:
                continue
            if weakest is None or s < weakest[1]:
                weakest = (sym, s)
        return weakest

    def _reconcile_early_orb_once(self, symbol):
        """Exchange-truth correction for the EARLY range, once per
        symbol. Same reasoning as _reconcile_orb_once; see
        OrbEngine.reconcile_early_with_exchange()."""
        if not ENABLE_ORB_EXCHANGE_RECONCILE:
            return
        if symbol in self._early_orb_reconciled or self.circuit_monitor is None:
            return
        info = (self.circuit_monitor.get_snapshot() or {}).get(symbol)
        if not info:
            return                       # snapshot not ready -- retry next tick
        self._early_orb_reconciled.add(symbol)
        before = self.orb_engine.get_early_range(symbol)
        if before and self.orb_engine.reconcile_early_with_exchange(
                symbol, info.get("high"), info.get("low")):
            after = self.orb_engine.get_early_range(symbol)
            diagnostic(
                f"[ORB_FIX_EARLY] {symbol} early range widened "
                f"{before['high']:.2f}/{before['low']:.2f} -> "
                f"{after['high']:.2f}/{after['low']:.2f}"
            )

    def _memory_block_reason(self, symbol, on_date):
        """
        The Stock Memory check (operator's proposal, 2026-07-25): does
        the bot KNOW something about this stock that makes today's price
        misleading? Returns a reason string to block, or None to allow.

        This is the JLHL fix. On 2026-07-24 that stock did a 2:10 split;
        the exchange halved the reference price, our previous close was
        the unadjusted one, and the bot read a routine corporate action
        as an **-80% crash** -- ranking it the day's biggest loser. Same
        class: a stock going ex-dividend opens lower by the dividend
        amount; that is not weakness, and shorting it is a mistake.

        Only PRICE-SCALE-CHANGING actions block (split / bonus / rights
        / demerger / dividend). Informational facts are memory, not a
        veto. Cached per day, so the tick path never hits the database.
        Fail-OPEN: no memory wired, or a read failure, allows the trade.
        """
        if not ENABLE_STOCK_MEMORY or self.stock_memory is None or on_date is None:
            return None
        try:
            if self._memory_cache is None or self._memory_cache[0] != on_date:
                self._memory_cache = (
                    on_date,
                    self.stock_memory.price_distorting_symbols(
                        on_date, window_days=MEMORY_ACTION_WINDOW_DAYS
                    ),
                )
        except Exception:
            return None                  # a broken memory never blocks trading
        reasons = self._memory_cache[1].get(symbol)
        return "; ".join(reasons) if reasons else None

    def _has_liquidity(self, symbol, price):
        """
        True if the symbol has traded enough value today to be worth
        touching. A breakout in a thin name is untradeable in real life
        -- the spread and impact eat the edge before it exists, and
        charges already take ~78% of gross profit here.

        Turnover = last price x day volume, from circuit_monitor's
        existing REST quote. Fail-OPEN when the feature is off, there's
        no monitor, or the quote carries no usable volume -- a missing
        number must never block a trade.
        """
        if not ENABLE_LIQUIDITY_FLOOR or self.circuit_monitor is None:
            return True
        info = (self.circuit_monitor.get_snapshot() or {}).get(symbol)
        if not info:
            return True
        try:
            volume = float(info.get("volume") or 0)
        except (TypeError, ValueError):
            return True
        if volume <= 0:
            return True                  # no volume data -> don't judge
        return volume * price >= MIN_TURNOVER_RS

    def _is_insane_tick(self, symbol, price):
        """
        True if this price is impossible relative to the last one we
        accepted for the symbol, so process_tick() can drop it.

        Guards against corrupt feed data reaching ANY trading decision.
        Verified real (2026-07-24 session): INFY printed 1037 -> 111 ->
        back inside one minute; JLHL -80.1% in a minute. Live, that one
        bad print would fire every stop in the symbol and could open a
        phantom breakout with real money.

        A >MAX_TICK_JUMP_PCT single-tick move is bad data, not a market
        move: NSE price bands cap genuine moves well below this, and a
        circuit-locked stock stops ticking rather than teleporting. The
        LAST GOOD price per symbol is kept, so a run of garbage can't
        drag the reference along with it. Non-positive prices are always
        rejected. Fail-open: disabled by config, or no prior price yet,
        means the tick passes.
        """
        if price is None or price <= 0:
            return True
        if not self.enable_tick_sanity:
            return False
        last = self._last_good_price.get(symbol)
        if last is None or last <= 0:
            self._last_good_price[symbol] = price
            return False
        if abs(price - last) / last > MAX_TICK_JUMP_PCT:
            if symbol not in self._insane_tick_warned:
                self._insane_tick_warned.add(symbol)
                warn(
                    f"[BAD_TICK] {symbol} rejected {price:.2f} -- a "
                    f"{abs(price - last) / last:.1%} jump from {last:.2f} "
                    f"in one tick is corrupt feed data, not a real move. "
                    f"Ignoring these for {symbol} (warned once)."
                )
            return True
        self._last_good_price[symbol] = price
        return False

    def _reconcile_orb_once(self, symbol):
        """
        Replace this symbol's tick-built opening range with the
        EXCHANGE's own high/low, once, as soon as the ORB window has
        closed. See OrbEngine.reconcile_with_exchange() for the full
        reasoning -- short version: the WebSocket feed is sampled, so
        our tick-built range is too NARROW and manufactures false
        breakouts (ZENTEC 1784.20 seen vs 1792.00 real, 2026-07-24).
        circuit_monitor's REST quote carries the exchange's true OHLC
        and is already being polled, so this costs no new network call.
        Fail-open: no monitor / no usable quote simply leaves the
        tick-built range exactly as it was.
        """
        if not ENABLE_ORB_EXCHANGE_RECONCILE:
            return
        if symbol in self._orb_reconciled or self.circuit_monitor is None:
            return
        if not self.orb_engine.is_complete(symbol):
            return

        info = (self.circuit_monitor.get_snapshot() or {}).get(symbol)
        if not info:
            return                       # snapshot not ready -- retry next tick
        self._orb_reconciled.add(symbol)

        before = self.orb_engine.get_range(symbol)
        if self.orb_engine.reconcile_with_exchange(
                symbol, info.get("high"), info.get("low")):
            after = self.orb_engine.get_range(symbol)
            diagnostic(
                f"[ORB_FIX] {symbol} range widened to the exchange's own "
                f"high/low: {before['high']:.2f}/{before['low']:.2f} -> "
                f"{after['high']:.2f}/{after['low']:.2f} "
                f"(the tick feed is sampled and had missed real trades)."
            )

    def _try_early_momentum_entry(self, symbol, security_id, closed_candle,
                                  tick_time):
        """
        Trade the FIRST-5-MINUTE range break, before the full 09:30 ORB
        exists.

        Operator, 2026-07-25: "is there anything we can do to enter if a
        stock is showing good strength rather than waiting till the ORB
        range forms?" Waiting for 09:30 makes the opening move -- often
        the cleanest of the day -- untradeable.

        Deliberately rare and hard to qualify for, because a 5-minute
        range is far noisier than a 15-minute one:
          - only between EARLY_ORB_END and ORB_WINDOW_END,
          - needs EARLY_ENTRY_MIN_RS relative strength (higher bar than
            the normal band's floor),
          - must be in a leading sector,
          - capped at EARLY_ENTRY_MAX_POSITIONS per day,
          - and it burns the symbol's ONE attempt for that direction,
            exactly like a normal entry.
        Everything else still waits for the full range.
        """
        if not ENABLE_EARLY_MOMENTUM_ENTRY or closed_candle is None:
            return
        if self._early_entries_taken >= EARLY_ENTRY_MAX_POSITIONS:
            return
        if tick_time is None:
            return
        t = tick_time.time()
        # Only in the window between the early range closing and the
        # real ORB completing -- after that the normal path takes over.
        if not (EARLY_ORB_END_T <= t < ORB_WINDOW_END_T):
            return

        # Correct the EARLY range from the exchange first (2026-07-25).
        # The main ORB is reconciled at 09:30, but this range is used at
        # ~09:21 -- so without this, early entries trade a sampled,
        # too-narrow range and fire on false breakouts.
        self._reconcile_early_orb_once(symbol)

        early = self.orb_engine.get_early_range(symbol)
        if early is None:
            return

        close = closed_candle["close"]
        if close > early["high"] * (1 + BREAKOUT_MIN_MARGIN_PCT):
            direction, reason = LONG, ENTRY_REASON_STRUCTURAL_LONG
        elif close < early["low"] * (1 - BREAKOUT_MIN_MARGIN_PCT):
            direction, reason = SHORT, ENTRY_REASON_STRUCTURAL_SHORT
        else:
            return

        if self._already_attempted(symbol, direction):
            return
        rel = self._relative_strength(symbol, direction)
        if rel is None or rel < EARLY_ENTRY_MIN_RS:
            return
        if not self._passes_sector_gate(symbol, direction):
            return

        before = len(self.open_positions)
        decision(
            f"[EARLY_MOMENTUM] {symbol} {direction} on the 5-min range "
            f"break ({close:.2f} vs {early['high']:.2f}/{early['low']:.2f}), "
            f"relative strength {rel:+.2%} -- not waiting for 09:30."
        )
        self._try_structural_entry(
            symbol, security_id, closed_candle, direction, reason, tick_time
        )
        if len(self.open_positions) > before:
            self._early_entries_taken += 1

    def _sector_leaderboard(self):
        """
        Which SECTORS the market is rotating into / out of right now.

        Operator's thesis (2026-07-25): "intraday is completely
        dependent on momentum, which usually lies in the top gaining
        sector stocks." A lone name breaking out is an orphan; the same
        break inside the day's leading sector is money actually
        rotating in.

        Sector strength = MEDIAN %change of that sector's priced
        symbols (median, not mean, so one runaway stock can't drag a
        whole sector onto the leaderboard). Built from circuit_monitor's
        existing REST snapshot -- no new network calls -- and cached.
        Returns (strong_sectors, weak_sectors, ranked_pairs).
        """
        if self.circuit_monitor is None or self.sector_monitor is None:
            return set(), set(), []

        now = time_module.monotonic()
        if self._sector_cache is not None \
                and now - self._sector_cache[3] < SECTOR_STRENGTH_REFRESH_SECONDS:
            return self._sector_cache[:3]

        buckets = {}
        for sym, info in (self.circuit_monitor.get_snapshot() or {}).items():
            try:
                last = float(info.get("last_price") or 0)
                prev = float(info.get("prev_close") or 0)
            except (TypeError, ValueError):
                continue
            if last <= 0 or prev <= 0:
                continue
            sector = self.sector_monitor.sector_of(sym)
            if not sector:
                continue
            buckets.setdefault(sector, []).append((last - prev) / prev)

        ranked = []
        for sector, moves in buckets.items():
            if len(moves) < SECTOR_STRENGTH_MIN_SYMBOLS:
                continue                     # too thin to mean anything
            moves.sort()
            mid = len(moves) // 2
            med = (moves[mid] if len(moves) % 2
                   else (moves[mid - 1] + moves[mid]) / 2.0)
            ranked.append((sector, med))
        ranked.sort(key=lambda kv: -kv[1])

        strong = {s for s, _ in ranked[:SECTOR_STRENGTH_TOP_N]}
        weak = {s for s, _ in ranked[-SECTOR_STRENGTH_TOP_N:]} if ranked else set()
        self._sector_cache = (strong, weak, ranked, now)
        return strong, weak, ranked

    def _passes_sector_gate(self, symbol, direction):
        """A LONG must sit in a top-gaining sector, a SHORT in a
        top-losing one. Fail-OPEN when there's no snapshot, no
        sector_monitor, or too few sectors ranked -- a missing opinion
        never blocks a trade."""
        if not ENABLE_SECTOR_STRENGTH_GATE:
            return True
        strong, weak, ranked = self._sector_leaderboard()
        if len(ranked) < SECTOR_STRENGTH_TOP_N:
            return True                      # not enough data to judge
        sector = self.sector_monitor.sector_of(symbol) if self.sector_monitor else None
        if not sector:
            return True
        return sector in (strong if direction == LONG else weak)

    def _relative_strength(self, symbol, direction):
        """
        The symbol's move MINUS the market's own median move, in this
        trade's favour. This is the one feature that measurably
        separated winners from losers on 2026-07-24 (39% vs 14.5% hit
        rate) -- ABSOLUTE strength did not. A stock rising with the
        tide tells us nothing; a stock pulling away from the pack has
        someone specific acting on it. Returns None if unavailable.
        """
        pct_map, _, _, usable = self._trend_snapshot()
        if usable < TREND_RANK_TOP_N * 2:
            return None
        own = pct_map.get(symbol)
        if own is None:
            return None
        values = sorted(pct_map.values())
        mid = len(values) // 2
        market = (values[mid] if len(values) % 2
                  else (values[mid - 1] + values[mid]) / 2.0)
        rel = own - market
        return rel if direction == LONG else -rel

    def _passes_rs_band(self, symbol, direction):
        """
        BAND selection, not top-N ranking. The 2026-07-24 study found
        an INVERTED-U: moderate outperformers hit 39%, but the very
        strongest names dropped to 34% (and the top 5% to 28%) --
        they're exhausted. So we require relative strength inside
        [RS_BAND_MIN, RS_BAND_MAX] and cap the raw move at
        MAX_ABS_MOVE_PCT. Fail-OPEN when the ranking data isn't
        usable, same convention as every other gate here.
        """
        if not self.enable_rs_band:
            return True
        rel = self._relative_strength(symbol, direction)
        if rel is None:
            return True                      # no data -> don't block
        if not (RS_BAND_MIN <= rel <= RS_BAND_MAX):
            return False
        return not self._is_exhausted(symbol)

    def _is_still_trending(self, symbol, direction):
        """
        Is this stock STILL making progress, or has it rolled over?

        Replaces the flat "% moved today" ceiling (2026-07-25, operator
        challenge). That ceiling blocked the day's BEST trending stock,
        because the best trend is by definition the one that moved most.

        The right question is not how far it has moved but whether it is
        still moving. Two stocks both up 7%:
            A trades at 428 and 428 IS the day's high  -> still trending
            B peaked at 432 and is back at 428         -> fading
        The old rule blocked both identically.

        So we ask where price sits inside TODAY'S range. 1.0 = at the
        day's high, 0.0 = at the day's low. A long needs to be in the
        upper part; a short in the lower part. Deliberately generous
        (0.65) -- this is a "not rolling over" check, not "must be at
        the exact high".

        Fail-OPEN: no usable day range (no ticks yet, flat range,
        market_data not wired) means we cannot judge, so allow.
        """
        if not ENABLE_STILL_TRENDING or self.market_data is None:
            return True
        info = (self.circuit_monitor.get_snapshot() or {}).get(symbol) \
            if self.circuit_monitor is not None else None
        if not info:
            return True
        try:
            high = float(info.get("high") or 0)
            low = float(info.get("low") or 0)
            last = float(info.get("last_price") or 0)
        except (TypeError, ValueError):
            return True
        if high <= low or last <= 0:
            return True                       # no usable range -> allow

        position = (last - low) / (high - low)      # 1.0 = at the high
        if direction == LONG:
            return position >= STILL_TRENDING_MIN_POSITION
        return position <= (1.0 - STILL_TRENDING_MIN_POSITION)

    def _is_exhausted(self, symbol):
        """
        Has TODAY'S move already been spent?

        CORRECTED 2026-07-25 (operator-found). This used to measure the
        move against YESTERDAY'S CLOSE -- which silently included the
        overnight gap, a move that happened while the market was shut.

        The failure that exposed it: a stock closes at 100, gaps to 106
        on real news, and by 10am trades 109. Measured from yesterday's
        close that is +9% -> over the ceiling -> BLOCKED ALL DAY. But
        during actual trading hours it has moved (109-106)/106 = +2.8%
        and has barely started. The bot was refusing exactly the
        gap-and-go names it most wants -- and the ORIGINAL research
        (the inverted-U quintile study) measured from the DAY'S OPEN,
        so the code had drifted from its own evidence.

        A gap is REPRICING, not exhaustion. The day's story starts at
        09:15. So exhaustion is measured from the open; the gap itself
        is a separate question (volatility/violence -- the APAR spike
        case), logged below for study but deliberately NOT gating yet.

        Fail-OPEN: no day-open known (market_data not wired, or no tick
        yet) means we cannot judge, so the trade is allowed.
        """
        day_open = None
        if self.market_data is not None:
            try:
                day_open = self.market_data.get_day_open(symbol)
            except Exception:
                day_open = None
        if not day_open or day_open <= 0:
            return False                     # can't judge -> don't block

        last = None
        if self.market_data is not None:
            last = self.market_data.get_latest_price(symbol)
        if not last or last <= 0:
            return False

        intraday_move = (last - day_open) / day_open
        if abs(intraday_move) <= MAX_ABS_MOVE_PCT:
            # Not spent. Note a large overnight gap once per symbol --
            # observation only, so we can study whether gap size should
            # eventually influence SIZE (it is not a gate today).
            self._note_gap(symbol, day_open)
            return False
        return True

    def _note_gap(self, symbol, day_open):
        """Log a large overnight gap once per symbol. Observation only --
        gap size does not gate or size anything yet. Recorded so Monday's
        data can answer whether it should."""
        if symbol in self._gap_noted:
            return
        pct_map, _, _, _ = self._trend_snapshot()
        total = pct_map.get(symbol)
        if total is None:
            return
        last = self.market_data.get_latest_price(symbol) if self.market_data else None
        if not last or last <= 0:
            return
        intraday = (last - day_open) / day_open
        gap = total - intraday               # the overnight portion
        if abs(gap) >= 0.03:
            self._gap_noted.add(symbol)
            diagnostic(
                f"[GAP] {symbol} opened {gap:+.1%} vs yesterday's close; "
                f"intraday move since 09:15 is {intraday:+.1%}. Exhaustion "
                f"is judged on the intraday part only."
            )

    def _staged_position_cap(self, effective_time):
        """
        Max concurrent positions allowed at this time of day. Never
        fill all ten seats in the opening minute -- on 2026-07-24, 11
        of 27 entries fired inside the single 09:34 minute, committing
        the whole book to whatever twitched first. Returns the cap, or
        0 once past STAGED_NO_ENTRY_AFTER.
        """
        if not self.enable_staged_entry or effective_time is None:
            return MAX_OPEN_POSITIONS
        hhmm = effective_time.strftime("%H:%M")
        if hhmm >= STAGED_NO_ENTRY_AFTER:
            return 0
        for cutoff, cap in STAGED_POSITION_LIMITS:
            if hhmm < cutoff:
                return min(cap, MAX_OPEN_POSITIONS)
        return MAX_OPEN_POSITIONS

    def _already_attempted(self, symbol, direction):
        """One attempt per (symbol, direction) per day -- kills the
        re-entry whipsaw (CHENNPETRO traded 9x, CORONA 6x in a single
        session)."""
        if not self.one_trade_per_symbol:
            return False
        return direction in self._attempted_today.get(symbol, set())

    def _mark_attempted(self, symbol, direction):
        self._attempted_today.setdefault(symbol, set()).add(direction)

    def _check_no_progress(self, symbol, price, tick_time):
        """
        Dead-money exit: a position that hasn't reached +NO_PROGRESS_R
        of its own risk within NO_PROGRESS_MINUTES isn't working.
        Close it and free the slot rather than let it squat all day
        (BHARTIARTL held a seat until 15:10 going nowhere). Never a
        stop-out, so it never blocks a later re-entry.
        """
        if not self.enable_no_progress or tick_time is None:
            return False
        position = self.open_positions.get(symbol)
        if position is None:
            return False
        entry_time = position.get("entry_time")
        if entry_time is None:
            return False
        held_min = (tick_time - entry_time).total_seconds() / 60.0
        if held_min < NO_PROGRESS_MINUTES:
            return False

        entry = position["entry_price"]
        initial_stop = position.get("initial_stop")
        if not initial_stop:
            return False
        risk = abs(entry - initial_stop)
        if risk <= 0:
            return False
        direction = position.get("direction", LONG)
        gain = (price - entry) if direction == LONG else (entry - price)
        if gain >= NO_PROGRESS_R * risk:
            return False                     # it IS working, leave it

        decision(
            f"[NO_PROGRESS] {symbol} {direction} closed after "
            f"{held_min:.0f} min at {price:.2f} -- never reached "
            f"+{NO_PROGRESS_R}R ({gain:+.2f} vs risk {risk:.2f}). "
            f"Freeing the slot."
        )
        self._exit(symbol, price, EXIT_REASON_NO_PROGRESS, tick_time)
        return True

    def _maybe_rotate_out(self, challenger, direction, tick_time):
        """When the book is full, try to free a slot by closing the
        weakest holder for a decisively stronger challenger. Returns
        True only if it actually closed a laggard (slot now free). Safe/
        conservative: needs usable strength on BOTH the challenger and
        the weakest holder, a clear edge (ROTATION_MIN_STRENGTH_EDGE),
        and a real price to close the laggard at -- any missing input
        means no rotation (fall back to the plain full-book skip)."""
        challenger_strength = self._symbol_strength(challenger, direction)
        if challenger_strength is None:
            return False
        weakest = self._weakest_holder_for_rotation()
        if weakest is None:
            return False
        w_sym, w_strength = weakest
        if challenger_strength <= w_strength + ROTATION_MIN_STRENGTH_EDGE:
            return False

        price = None
        if self.market_data is not None:
            price = self.market_data.get_latest_price(w_sym)
        if not price and self.circuit_monitor is not None:
            info = (self.circuit_monitor.get_snapshot() or {}).get(w_sym) or {}
            try:
                price = float(info.get("last_price") or 0) or None
            except (TypeError, ValueError):
                price = None
        if not price:
            return False

        decision(
            f"[ROTATE] {w_sym} (trend {w_strength:+.2%}) rotated OUT for "
            f"{challenger} {direction} (trend {challenger_strength:+.2%}) "
            f"-- a stronger breakout needs the slot."
        )
        self._exit(w_sym, price, EXIT_REASON_ROTATED_OUT, tick_time)
        return True

    def _daily_realized_pnl(self):
        """
        Sum of realized P&L over today's closed trades, partial
        exits included -- read fresh from closed_positions on every
        call, same "derive, don't book-keep" pattern used for
        used_margin.

        RESTART FIX, 2026-07-25: closed_positions is in-memory, so a
        mid-session restart used to reset this to 0 and RE-ARM the daily
        loss switch. Real risk: lose the full DAILY_MAX_LOSS_RS, restart
        for any reason (crash, feed drop, code change -- all of which
        happened on 2026-07-24), and the bot would happily lose it again
        because as far as it knew the day had just begun. `_carried_pnl`
        is seeded once at startup from the persisted portfolio, so the
        guardrail now governs the WHOLE day, not just the current
        process's slice of it.
        """
        return self._carried_pnl + sum(
            (record.get("pnl") or 0) for record in self.closed_positions
        )

    def seed_daily_pnl(self, realized_pnl):
        """Called once at startup with the realized P&L already booked
        earlier today (from the persisted portfolio), so the daily
        loss/goal guardrails survive a restart. Safe to call with None
        or 0."""
        try:
            self._carried_pnl = float(realized_pnl or 0.0)
        except (TypeError, ValueError):
            self._carried_pnl = 0.0
        if self._carried_pnl:
            decision(
                f"[DAILY_PNL] Carrying forward {self._carried_pnl:,.0f} "
                f"realized from earlier today -- the daily loss/goal "
                f"guardrails cover the full session, not just this run."
            )

    def _breakout_has_volume(self, symbol, closed_candle):
        """
        Change 2, 2026-07-24 (evening) -- True if the breakout candle
        carried a genuine volume surge (>= VOLUME_SURGE_MULT x the
        average volume of the last VOLUME_AVG_CANDLES closed candles),
        which separates a real breakout (KPITTECH) from a thin drift
        across the line (MOIL/TATASTEEL/ICICIBANK, all today).

        FAILS OPEN -- returns True (allow the trade) whenever the
        volume can't be judged: no breakout-candle volume (Ticker
        mode / feed didn't supply it), or fewer than MIN_VOLUME_CANDLES
        of prior candles that HAVE volume. Volume is a quality bonus,
        never a hard gate that trading depends on.
        """
        if closed_candle is None:
            return True
        breakout_vol = closed_candle.get("volume")
        if not breakout_vol or breakout_vol <= 0:
            return True  # unknown volume -> don't block

        # Recent closed candles BEFORE this one (exclude the breakout
        # candle itself, which is the last element).
        history = self.candle_engine.last_n_closed(symbol, VOLUME_AVG_CANDLES + 1)
        prior = [
            c.get("volume") for c in history[:-1]
            if c.get("volume") and c.get("volume") > 0
        ]
        if len(prior) < MIN_VOLUME_CANDLES:
            return True  # not enough volume history to judge -> allow

        avg_vol = sum(prior) / len(prior)
        if avg_vol <= 0:
            return True
        return breakout_vol >= VOLUME_SURGE_MULT * avg_vol

    def _try_structural_entry(self, symbol, security_id, closed_candle,
                               direction, entry_reason, tick_time=None):
        """
        The gate a valid structural signal passes through before
        becoming a real entry. See module docstring for the two
        checks and why each exists. Already-blocked directions
        short-circuit immediately -- no repeat news/sector lookup,
        no repeat log line, every candle the breakout keeps firing.

        tick_time is the ACTUAL tick being processed (the one that
        just closed this candle) -- distinct from closed_candle's own
        "time" (the last tick INSIDE the closing candle, ~:59 of the
        prior minute). The square-off guard below uses tick_time so a
        breakout confirmed by the very first tick of the 15:15 minute
        can't sneak an entry in past square-off (see #0 fix below).
        """
        # 2026-07-24 -- EXIT ALL dashboard popup's "Stop New Entries
        # + Exit All" option (trading/trade_controller.py's
        # request_pause_new_entries()). Cheapest possible check,
        # first: a single flag read, no time comparison, no lookup.
        # Manual buy/short are NOT gated by this -- same "explicit
        # operator override" reasoning already applied to the news/
        # sector blocks (process_tick()'s manual-buy/short branches
        # are a deliberate, separate code path from this method).
        # Silent skip, no log line -- fires on every candle close for
        # as long as the pause lasts, same convention as the frozen/
        # circuit-flagged checks below.
        if self.trade_controller.is_new_entries_paused():
            return

        # Minimum tradable price -- operator-approved 2026-07-24,
        # hard floor, "no matter what" (config.MIN_TRADABLE_PRICE_RS's
        # docstring). The REAL enforcement (covers manual buy/short
        # too) is in _enter() below -- this is purely an efficiency/
        # noise short-circuit so a cheap stock that keeps triggering
        # ORB breakouts all day doesn't repeatedly run ATR sizing and
        # log a warning on every single candle close. Silent skip, no
        # entry_blocked entry -- same "not eligible today" convention
        # as the momentum-universe shortlist check below, not a news/
        # sector REASON.
        if closed_candle is not None and closed_candle["close"] < self.min_tradable_price:
            return

        # Liquidity floor (2026-07-25) -- a breakout in a thin stock is
        # untradeable in real life; spread and impact eat the edge before
        # it exists. Fail-open when volume data is missing.
        if closed_candle is not None and not self._has_liquidity(
                symbol, closed_candle["close"]):
            return

        # Square-off entry block. 2026-07-24 (evening) #0 FIX: this now
        # checks the ACTUAL processing tick_time, not the closing
        # candle's label time. The bug: the final 15:14 candle only
        # CLOSES when the first 15:15 tick arrives, but closed_candle
        # ["time"] is ~15:14:59 (the last tick INSIDE it), so it slid
        # past this guard and fired 10 fresh entries at 15:15:00-01 --
        # racing main.py's one-shot flatten_all(), leaving them open
        # (operator report). tick_time is that first-15:15 tick, so
        # >= SQUARE_OFF_T correctly blocks it. Falls back to the
        # candle label only if tick_time wasn't passed (older callers/
        # tests). Silent skip -- fires every candle for the rest of
        # the session once past square-off and would flood otherwise.
        effective_time = tick_time or (
            closed_candle.get("time") if closed_candle else None
        )
        if effective_time is not None and effective_time.time() >= SQUARE_OFF_T:
            return

        # 2026-07-24 (evening) -- the 14:30 fresh-entry cutoff was
        # REMOVED (operator: "that's not what I said -- we need more
        # data to correct ourselves before live trading"). Cutting
        # off entries at 2pm was throwing away exactly the afternoon
        # data we need to study. Entries now run right up to the 15:15
        # square-off; only that hard flatten stops new positions.
        # (LAST_ENTRY_T is kept in config as a dormant dial in case a
        # cutoff is wanted later, but it no longer gates anything.)
        #
        # 2026-07-25 (operator decision): the ONE cutoff that does bite
        # is STAGED_NO_ENTRY_AFTER, applied via _staged_position_cap()
        # below. It was briefly set to 14:00 and is now 15:00 -- trade
        # the full session, stop opening 15 minutes before the 15:15
        # hard square-off. Rationale: on 2026-07-24 the two best entries
        # of the day were 13:50 and 13:51, and nothing in the data marks
        # 14:35 as different from 13:55.

        # Earnings-day entry exclusion, 2026-07-24 (config.py's
        # EARNINGS_CALENDAR docstring has the full sun/moon date-
        # mapping rationale). A reporting stock's move is a news
        # reaction, not organic momentum -- the ATR system can't
        # tell the difference. Checked against the candle's own
        # market-time date, same convention as the square-off check
        # above. Structural entries only -- manual buy/short are a
        # deliberate human override, untouched here. Silent skip,
        # same "not eligible today" convention as the other checks
        # in this method.
        # 2026-07-26: the calendar is now INJECTED. config's hand-typed
        # EARNINGS_CALENDAR remains the default so nothing changes for
        # tests or an offline run, but main.py overlays the live NSE
        # board-meeting calendar (core/results_calendar.py) on top of it
        # -- a hand-maintained dict goes stale the moment nobody updates
        # it. Still a plain dict lookup here; the tick path never touches
        # a database.
        candle_date = effective_time.date() if effective_time is not None else None
        if candle_date is not None \
                and symbol in self.earnings_calendar.get(
                    candle_date.isoformat(), ()):
            return

        # STOCK MEMORY (2026-07-25) -- the bot's own knowledge of what is
        # happening to this share TODAY. A split/bonus/rights/demerger/
        # dividend changes the price SCALE, so every %-move, ORB range
        # and breakout computed against yesterday's close is a lie.
        # Blocked with a loud, once-per-symbol reason -- unlike the
        # silent skips above, this one the operator wants to SEE.
        memory_reason = self._memory_block_reason(symbol, candle_date)
        if memory_reason is not None:
            if direction not in self.entry_blocked.get(symbol, {}):
                self._block_entry(
                    symbol, direction,
                    f"corporate action today -- {memory_reason}. Price is "
                    f"not comparable to yesterday's close"
                )
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

        # ORB-window feed staleness, 2026-07-24 -- the SONACOMS
        # incident (see core/market_data.py's is_orb_window_unreliable()
        # docstring for the full writeup): a ~30s stale-feed gap right
        # at 09:15 open meant the true intraday high never reached
        # orb_engine.update(), producing an ORB range 3.80 narrower
        # than reality and a false "breakout" that was actually still
        # inside the real range. market_data is optional (same as the
        # exit-pricing reader below) -- skipped entirely if not wired
        # up (e.g. most tests). Silent skip, same convention as the
        # frozen-price check above.
        if self.market_data is not None and self.market_data.is_orb_window_unreliable(symbol):
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

        # 2026-07-24 (evening) -- the frozen 9:30 top-25-gainers/
        # top-25-losers shortlist is REMOVED (operator: "that frozen
        # list was part of today's fixed-100-qty test, not a fixed
        # one -- remove it instantly"). It threw away almost every
        # real move of the day: a stock quiet at 9:30 (TATA ELXSI,
        # MOTILAL OSWAL, 2026-07-24) that woke up and broke out at
        # 11-12-1 o'clock was permanently locked out because it
        # wasn't a top mover in the first 15 minutes. Now ALL 750
        # symbols are eligible all day long -- any of them can trade
        # the moment it makes a real, quality breakout (the gates
        # below -- regime, breakout margin, wider ATR stops, caps,
        # earnings, daily limits -- are what enforce QUALITY now,
        # not an arbitrary 9:30 snapshot). ATR-based dynamic sizing
        # (see _entry_stop_and_target) still applies to every one of
        # them; momentum_universe is no longer consulted for
        # eligibility at all.

        # ==========================================================
        # 2026-07-24 revamp gates (config.py's trading-policy block,
        # TRADING_POLICY.md for the full plain-language decision
        # path). All silent skips -- they fire repeatedly on every
        # candle close while their condition holds, and none of them
        # is a symbol-specific news/sector REASON (entry_blocked is
        # reserved for those).
        # ==========================================================

        # Trade WITH the tape, never against it (item 1). A one-sided
        # market blocks the fighting direction entirely.
        regime = self._market_regime()
        if (direction == LONG and regime == "SHORT_ONLY") \
                or (direction == SHORT and regime == "LONG_ONLY"):
            return

        # Trend-rank entry priority (2026-07-24, operator's thesis):
        # trade WITH the leaderboard -- a LONG only in a current top-N
        # gainer, a SHORT only in a top-N loser. A breakout OUTSIDE the
        # leaderboard is range noise, not a trend to sail with. Fail-open
        # (see _is_trend_eligible). Silent skip, same convention as the
        # other quality gates in this method.
        if not self._is_trend_eligible(symbol, direction):
            return

        # One attempt per (symbol, direction) per day, 2026-07-25 --
        # kills the re-entry whipsaw (CHENNPETRO 9x, CORONA 6x in one
        # session, each round trip paying charges).
        if self._already_attempted(symbol, direction):
            return

        # RELATIVE-STRENGTH BAND, 2026-07-25 (the study's main result).
        # Outperforming the market is what separated winners; being
        # the MOST extended is what killed them. Band, not top-N.
        if not self._passes_rs_band(symbol, direction):
            return

        # STILL TRENDING (2026-07-25) -- is it holding near today's high
        # (long) / low (short), or has it rolled over? Replaces the flat
        # "% moved" ceiling, which blocked the day's best trend by
        # construction. See _is_still_trending().
        if not self._is_still_trending(symbol, direction):
            return

        # SECTOR / THEME STRENGTH (2026-07-25). Ride what the market is
        # actually rotating into -- a breakout inside a leading sector,
        # not an orphan mid-cap nobody is bidding for.
        if not self._passes_sector_gate(symbol, direction):
            return

        # Concurrency cap (item 4) + SLOT ROTATION (2026-07-24). Once
        # MAX_OPEN_POSITIONS are on, the bot is FULL. The OLD behaviour
        # just dropped every new signal until a slot freed -- so the
        # first 10 names to cross at 09:34 squatted all day and the real
        # movers were locked out (proven on 2026-07-24: GODIGIT -6%,
        # ACE +2.3%, MOTILALOFS -3.5% all broke out to a full book). Now,
        # if this breakout is decisively stronger than the weakest
        # current holder, that laggard is rotated OUT to make room
        # (_maybe_rotate_out). If rotation is off or can't free a slot,
        # it falls back to the plain "full -> skip".
        # Staged deployment (2026-07-25): the cap RAMPS with the day
        # (3 before 10:00, 6 before 11:00, 10 after) so the book is
        # never committed in the opening minute, and closes entirely
        # after STAGED_NO_ENTRY_AFTER.
        position_cap = self._staged_position_cap(effective_time)
        if position_cap <= 0:
            return
        if len(self.open_positions) >= position_cap:
            if not (ENABLE_SLOT_ROTATION
                    and self._maybe_rotate_out(symbol, direction, effective_time)):
                return

        # Daily guardrails (item 5): a realized day at/below the loss
        # switch, or at/above the goal, takes no further entries.
        # Edge-triggered log so the moment it trips is loud, once.
        realized = self._daily_realized_pnl()
        if realized <= -DAILY_MAX_LOSS_RS:
            if self._daily_halt_logged != "LOSS":
                self._daily_halt_logged = "LOSS"
                warn(
                    f"[DAILY HALT] Realized P&L {realized:.0f} <= "
                    f"-{DAILY_MAX_LOSS_RS:.0f} -- no new entries for "
                    f"the rest of the session. Open positions still "
                    f"managed normally."
                )
            return
        if realized >= DAILY_PROFIT_TARGET_RS:
            if self._daily_halt_logged != "GOAL":
                self._daily_halt_logged = "GOAL"
                decision(
                    f"[DAILY GOAL MET] Realized P&L {realized:.0f} >= "
                    f"{DAILY_PROFIT_TARGET_RS:.0f} -- day's goal met, "
                    f"no new entries. Open positions still managed "
                    f"normally."
                )
            return

        # Breakout-quality margin (items 8/9): the close must clear
        # the ORB boundary by a real, conviction-sized margin --
        # closes that graze the line by a few paise are range noise
        # (the entire SONACOMS class of entry), not breakouts.
        # Only meaningful once the range is FINAL. During the opening
        # window the range is still accumulating and already contains
        # the current price, so "close vs range high" is always ~equal
        # and would block every early-momentum entry (which breaks the
        # separate 5-minute range, not this one). 2026-07-25.
        orb_range = (self.orb_engine.get_range(symbol)
                     if self.orb_engine.is_complete(symbol) else None)
        if orb_range is not None and closed_candle is not None:
            close = closed_candle["close"]
            if direction == LONG and \
                    close < orb_range["high"] * (1 + BREAKOUT_MIN_MARGIN_PCT):
                return
            if direction == SHORT and \
                    close > orb_range["low"] * (1 - BREAKOUT_MIN_MARGIN_PCT):
                return

        # Volume-surge filter (Change 2, 2026-07-24) -- a real breakout
        # carries a surge of volume; a MOIL/TATASTEEL-style drift across
        # the line doesn't. Silent skip if the breakout candle's volume
        # is below VOLUME_SURGE_MULT x the recent average. FAILS OPEN:
        # returns True (allow) whenever volume data is missing or too
        # thin, so it can never block a trade just because the feed
        # isn't delivering volume (see _breakout_has_volume()).
        if ENABLE_VOLUME_FILTER and not self._breakout_has_volume(symbol, closed_candle):
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

        stop_seed, target, qty, stop_mode = self._entry_stop_and_target(
            symbol, direction, closed_candle["close"]
        )
        if stop_seed is None:
            # ATR unavailable/insufficient history, or the computed
            # qty came out below 1 share -- see _atr_entry_sizing()'s
            # docstring. Silent skip, same pattern as every other
            # "not a real signal yet" gate in this method.
            return
        self._enter(
            symbol, security_id, closed_candle["close"], stop_seed,
            closed_candle["time"], entry_reason, direction, target=target,
            qty=qty, stop_mode=stop_mode,
        )

    def _entry_stop_and_target(self, symbol, direction, entry_price):
        """
        Returns (stop_price, target_price, qty, stop_mode) for a new
        STRUCTURAL entry. target_price is always None -- this bot's
        default design has never had a fixed target
        (core/trailing_stop.py's own docstring: ride the trend,
        dynamic, no cap), and the 2026-07-24 ATR redesign brought
        TOP_N_MOMENTUM_MODE in line with that too (see
        config.py's ATR_TRAIL_MULTIPLIER comment). Manual buys never
        call this -- they keep the old dynamic-trailing, no-target,
        flat-qty behaviour unconditionally (see process_tick()'s
        manual-buy branch).

        stop_price (and therefore the whole tuple) can be None if
        TOP_N_MOMENTUM_MODE's ATR sizing couldn't produce a safe
        reading yet -- caller (_try_structural_entry) must check for
        this and skip the entry, not pass None through to _enter().

        Requires self.momentum_universe to actually be wired in, not
        just the config flag -- same guard as the eligibility check
        in _try_structural_entry(). A bare Engine() with no
        momentum_universe (every existing test, anything that
        doesn't explicitly opt in) gets the original ORB-boundary
        dynamic-trailing behaviour regardless of the flag's default,
        exactly as if the feature didn't exist for it.
        """
        if TOP_N_MOMENTUM_MODE and self.momentum_universe is not None:
            stop_price, target, qty = self._atr_entry_sizing(
                symbol, direction, entry_price
            )
            return stop_price, target, qty, STOP_MODE_ATR_TRAILING
        return (
            self._orb_stop_seed(symbol, direction), None,
            LAYER1_FIXED_QTY, STOP_MODE_SWING_TRAILING,
        )

    def _risk_sized_qty(self, price, stop_distance):
        """
        2026-07-24 (evening) -- shared risk-based sizing, now used by
        MANUAL buy/short too (Audit #1 fix). qty risks about
        RISK_PER_TRADE_RS given the stop distance, capped so notional
        never exceeds MAX_NOTIONAL_PER_TRADE_RS. This is what stops a
        manual APAR click from being 100 shares (Rs 14.6L notional /
        Rs 2.92L margin, the Rs 53k loss) -- it becomes ~13 shares
        (~Rs 1.9L notional / ~Rs 38k margin) instead. Returns at least
        1 share (a manual override should still place *a* trade even
        if sizing math rounds tiny), but never more than the notional
        cap allows.
        """
        if stop_distance <= 0:
            stop_distance = price * MIN_STOP_DISTANCE_PCT
        by_risk = int(RISK_PER_TRADE_RS / stop_distance) if stop_distance > 0 else 1
        by_notional = int(MAX_NOTIONAL_PER_TRADE_RS / price) if price > 0 else 1
        return max(1, min(by_risk, by_notional))

    def _atr_entry_sizing(self, symbol, direction, entry_price):
        """
        TOP_N_MOMENTUM_MODE only -- ATR-based initial stop and qty,
        2026-07-24, replacing the old flat qty / fixed rupee bracket
        (see config.py's ATR block for the full rationale). Returns
        (stop_price, target, qty) with target always None -- the
        position is managed post-entry by _check_atr_trailing(), not
        a fixed bracket.

        Returns (None, None, None) if there isn't enough real candle
        history yet to trust an ATR reading (config.MIN_ATR_CANDLES),
        or if the computed qty would be below 1 share (stop distance
        alone already costs more than the risk budget at any
        quantity above zero -- an extremely volatile stock right
        now, not a safe size). Caller treats either case as "skip
        this entry", same silent-skip pattern as the frozen-price/
        circuit-proximity checks in _try_structural_entry().

        Safety floor/ceiling added 2026-07-24 after SWIGGY sized to
        qty=2522 on a 46-paise stop (ATR read Rs 0.264 -- a thin,
        quiet candle window). The stop distance actually used is
        max(ATR_STOP_MULTIPLIER * ATR, MIN_STOP_DISTANCE_PCT * price)
        -- never tighter than that percentage of price, regardless
        of how small ATR reads. qty is derived from THAT distance,
        then separately capped so notional (qty * entry_price) never
        exceeds MAX_NOTIONAL_PER_TRADE_RS -- a second, independent
        backstop in case a cheap stock still sizes up large even
        with the floored distance. See config.py's own comment block
        for the full incident writeup.
        """
        candles = self.candle_engine.last_n_closed(symbol, ATR_PERIOD + 1)
        if len(candles) < MIN_ATR_CANDLES:
            return None, None, None

        atr = compute_atr(candles, ATR_PERIOD)
        if atr is None or atr <= 0:
            return None, None, None

        raw_stop_distance = ATR_STOP_MULTIPLIER * atr
        min_stop_distance = MIN_STOP_DISTANCE_PCT * entry_price
        stop_distance = max(raw_stop_distance, min_stop_distance)

        qty = int(RISK_PER_TRADE_RS / stop_distance)
        if qty < 1:
            return None, None, None

        max_qty_by_notional = int(MAX_NOTIONAL_PER_TRADE_RS / entry_price)
        if max_qty_by_notional < 1:
            return None, None, None
        qty = min(qty, max_qty_by_notional)

        if direction == LONG:
            stop_price = entry_price - stop_distance
        else:
            stop_price = entry_price + stop_distance

        return stop_price, None, qty

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

    def _block_entry(self, symbol, direction, reason):
        self.entry_blocked.setdefault(symbol, {})[direction] = reason
        warn(
            f"[NO_TRADE] {symbol} {direction} skipped -- {reason}. "
            f"No {direction.lower()} trade for {symbol} today."
        )

    # --------------------------------------------------

    def _enter(self, symbol, security_id, price, stop_seed,
               entry_time, entry_reason, direction, target=None,
               qty=None, stop_mode=STOP_MODE_SWING_TRAILING):
        # qty defaults to the flat placeholder unless the caller
        # computed its own (TOP_N_MOMENTUM_MODE's ATR sizing, see
        # _atr_entry_sizing()) -- manual buy/short and any
        # non-momentum structural entry never pass qty, so they're
        # completely unaffected by the 2026-07-24 ATR redesign.
        if qty is None:
            qty = LAYER1_FIXED_QTY

        # Minimum tradable price -- operator-approved 2026-07-24,
        # hard floor, "no matter what" (config.MIN_TRADABLE_PRICE_RS's
        # docstring). Checked here, in the one funnel every entry
        # path goes through, so structural LONG/SHORT and manual
        # buy/short are ALL covered by one change -- same non-
        # overridable treatment as the margin gate just below, not
        # the news/sector checks a manual override is allowed to
        # bypass. Cheapest possible check, first: a single float
        # comparison, no lookups.
        if price < self.min_tradable_price:
            warn(
                f"[PRICE_FLOOR] {symbol} {direction} skipped -- "
                f"{price:.2f} is below the Rs {self.min_tradable_price:.0f} "
                f"minimum tradable price, no exceptions."
            )
            return

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
                self.open_positions, symbol, price, qty):
            available = self.portfolio.available_margin(self.open_positions)
            needed = self.portfolio.margin_required(symbol, price, qty)
            warn(
                f"[MARGIN] {symbol} {direction} skipped -- insufficient "
                f"margin for {qty} qty @ {price:.2f} "
                f"(needs {needed:,.0f} margin, {available:,.0f} free)."
            )
            return

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
                            )
        elif entry_reason == ENTRY_REASON_STRUCTURAL_SHORT:
            orb_range = self.orb_engine.get_range(symbol)
            decision(
                f"\nORB BREAKDOWN  : {symbol}\n"
                f"ORB High       : {orb_range['high']:.2f}\n"
                f"ORB Low        : {orb_range['low']:.2f}\n"
                f"Breakdown Close: {price:.2f}"
                f"{bracket_line}"
                            )
        elif entry_reason == ENTRY_REASON_MANUAL_SHORT_DASHBOARD:
            decision(
                f"\nMANUAL SHORT (dashboard): {symbol}\n"
                f"Price                    : {price:.2f}"
                            )
        else:
            decision(
                f"\nMANUAL BUY (dashboard): {symbol}\n"
                f"Price                  : {price:.2f}"
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

        # One attempt per (symbol, direction) per day -- recorded the
        # moment a position is actually OPENED (not when a signal
        # merely fires), so a blocked/skipped signal never burns the
        # symbol's single daily attempt. See _already_attempted().
        self._mark_attempted(symbol, direction)

        # Entry CONTEXT for the learning loop -- the conditions this
        # trade was taken in, which is the part worth learning from
        # later (the P&L alone is already in trade_log.csv). Captured
        # here, at entry, because none of it can be reconstructed after
        # the fact. Best-effort: never let it break an entry.
        try:
            entry_sector = (self.sector_monitor.sector_of(symbol)
                            if self.sector_monitor is not None else None)
        except Exception:
            entry_sector = None
        try:
            entry_rel = self._relative_strength(symbol, direction)
        except Exception:
            entry_rel = None

        self.open_positions[symbol] = {
            "security_id": security_id,
            "qty": qty,
            "entry_price": price,
            "sector": entry_sector,
            "rel_strength": entry_rel,
            "regime": self._last_logged_regime,
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
            # Legacy fixed-bracket field -- always None for any
            # position opened after the 2026-07-24 ATR redesign
            # (target is no longer a thing this bot sets on a new
            # entry). Kept alive purely so _check_trailing_stop()
            # can still correctly manage an OLD fixed-bracket
            # position restored from core/state_store.py across a
            # restart that happened to land mid-trade -- see
            # _check_fixed_bracket()'s docstring.
            "fixed_target": target,
            # HOW this position's stop is managed post-entry -- see
            # STOP_MODE_SWING_TRAILING/STOP_MODE_ATR_TRAILING at the
            # top of this file and _check_trailing_stop()'s routing.
            "stop_mode": stop_mode,
            # ATR_TRAILING only -- running extreme (highest high for
            # LONG / lowest low for SHORT) since entry, and the ATR
            # reading last used to place the stop. None for
            # SWING_TRAILING positions, which don't use these.
            "atr_extreme": price if stop_mode == STOP_MODE_ATR_TRAILING else None,
            "atr_stop": stop_seed if stop_mode == STOP_MODE_ATR_TRAILING else None,
            "atr_value": None,
            # "Dynamic position building" scale-out, config.py's
            # ENABLE_PARTIAL_EXIT block (test rig, off by default) --
            # guards _maybe_partial_exit() from re-firing on a
            # position it's already trimmed once.
            "partial_exit_done": False,
        }
        # Fixed-bracket trade (target is not None): stop_seed is
        # already the fixed stop PRICE and lives on "initial_stop"
        # above -- _check_fixed_bracket() reads it directly, no
        # trailing_stop.start() call, this trade is deliberately NOT
        # ratcheted (operator's explicit original choice). ATR
        # trailing positions manage their own stop directly on the
        # position dict (atr_stop/atr_extreme above), also skipping
        # the swing-based engine. Only genuine SWING_TRAILING
        # positions (manual buy/short, or structural entries outside
        # momentum mode) use core/trailing_stop.py at all.
        if target is None and stop_mode == STOP_MODE_SWING_TRAILING:
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

        # Old fixed-bracket trades (any position opened before the
        # 2026-07-24 ATR redesign, restored from state across a
        # restart) never use the ratcheting trailing stop -- routed
        # by the position's OWN "fixed_target" field, not the global
        # config flag, so an already-open trade keeps behaving
        # exactly as it was opened even if the flag/mode changes
        # mid-session.
        if position.get("fixed_target") is not None:
            self._check_fixed_bracket(symbol, position, price, tick_time)
            return

        # ATR trailing (TOP_N_MOMENTUM_MODE, 2026-07-24 onward) --
        # also routed by the position's own field, same reasoning.
        if position.get("stop_mode") == STOP_MODE_ATR_TRAILING:
            self._check_atr_trailing(symbol, position, price, tick_time)
            return

        if not self.trailing_stop.is_hit(symbol, price):
            return

        stop_price = self.trailing_stop.get_stop(symbol)
        decision(
            f"TRAILING STOP HIT: {symbol} stop={stop_price:.2f} "
            f"price={price:.2f}"
        )
        self._exit(symbol, price, EXIT_REASON_TRAILING_STOP, tick_time)

    def _check_atr_trailing(self, symbol, position, price, tick_time):
        """
        TOP_N_MOMENTUM_MODE only, 2026-07-24 redesign -- chandelier-
        style trail: stop = highest high since entry (LONG) / lowest
        low since entry (SHORT), minus/plus
        config.ATR_TRAIL_MULTIPLIER times the latest ATR reading.
        The actual RATCHET (moving atr_stop, updating atr_extreme)
        happens once per closed candle in
        _update_atr_trailing_on_candle_close() -- this method only
        checks whether the CURRENT stop (whatever it was last set
        to) has been breached, on every tick, same capital-
        protection-first-not-just-on-candle-close convention as the
        swing-based trailing stop.
        """
        direction = position.get("direction", LONG)
        stop_price = position.get("atr_stop")
        if stop_price is None:
            return

        hit = price <= stop_price if direction == LONG else price >= stop_price
        if not hit:
            return

        decision(
            f"ATR TRAILING STOP HIT: {symbol} stop={stop_price:.2f} "
            f"price={price:.2f}"
        )
        self._exit(symbol, price, EXIT_REASON_TRAILING_STOP, tick_time)

    def _update_atr_trailing_on_candle_close(self, symbol, position, closed_candle):
        """
        Called once per closed candle for an ATR_TRAILING position
        (see process_tick()'s already-open branch). Recomputes ATR
        fresh from the latest candles, extends the running extreme
        (highest high for LONG / lowest low for SHORT) with this
        candle, and ratchets atr_stop toward price -- NEVER loosened,
        same rule core/trailing_stop.py already uses for the swing-
        based trail. If ATR can't be computed right now (should be
        rare -- the position already passed this same check to
        enter), the existing stop is left exactly where it was
        rather than guessed at.
        """
        candles = self.candle_engine.last_n_closed(symbol, ATR_PERIOD + 1)
        atr = compute_atr(candles, ATR_PERIOD) if candles else None
        if atr is None or atr <= 0:
            return

        direction = position.get("direction", LONG)
        entry_price = position["entry_price"]

        # Trail-activation, 2026-07-24 (evening) -- the fix for
        # "stopped out at breakeven right after entry" (operator's
        # own words: "it moves, we stay; it reverses, we exit"). The
        # stop does NOT start following price up until the trade has
        # run at least ATR_TRAIL_ACTIVATION_MULT ATRs in PROFIT. Until
        # then the wide initial stop just sits, giving the trade real
        # room -- a small favourable wiggle can no longer drag the
        # stop up to where the next small unfavourable wiggle exits
        # it. The activation distance uses the SAME max(ATR, %-floor)
        # basis as the trail itself, so it's never a razor-thin bar.
        # Same MIN_STOP_DISTANCE_PCT floor applied at entry, measured
        # off the extreme (the ratchet's own reference point).
        if direction == LONG:
            extreme = max(
                position.get("atr_extreme") or closed_candle["high"],
                closed_candle["high"],
            )
            trail_distance = max(ATR_TRAIL_MULTIPLIER * atr, MIN_STOP_DISTANCE_PCT * extreme)
            activation = max(
                ATR_TRAIL_ACTIVATION_MULT * atr, MIN_STOP_DISTANCE_PCT * entry_price
            )
            if extreme >= entry_price + activation:
                candidate = extreme - trail_distance
                current_stop = position.get("atr_stop")
                if current_stop is None or candidate > current_stop:
                    position["atr_stop"] = candidate
        else:
            extreme = min(
                position.get("atr_extreme") or closed_candle["low"],
                closed_candle["low"],
            )
            trail_distance = max(ATR_TRAIL_MULTIPLIER * atr, MIN_STOP_DISTANCE_PCT * extreme)
            activation = max(
                ATR_TRAIL_ACTIVATION_MULT * atr, MIN_STOP_DISTANCE_PCT * entry_price
            )
            if extreme <= entry_price - activation:
                candidate = extreme + trail_distance
                current_stop = position.get("atr_stop")
                if current_stop is None or candidate < current_stop:
                    position["atr_stop"] = candidate

        position["atr_extreme"] = extreme
        position["atr_value"] = atr
        diagnostic(f"[ATR TRAIL] {symbol} stop -> {position['atr_stop']:.2f}")

        # "Dynamic position building" scale-out extension, 2026-07-24
        # -- see config.ENABLE_PARTIAL_EXIT's docstring (currently a
        # test rig, off by default). Checked AFTER the trail update
        # above so it always sees this candle's freshly-computed ATR.
        if ENABLE_PARTIAL_EXIT and not position.get("partial_exit_done", False):
            self._maybe_partial_exit(symbol, position, closed_candle)

    def _maybe_partial_exit(self, symbol, position, closed_candle):
        """
        ATR_TRAILING only, gated by config.ENABLE_PARTIAL_EXIT (a
        test rig -- see its docstring). Once a position has moved
        config.PARTIAL_EXIT_ATR_MULTIPLE ATRs in its favor from
        entry (measured off this candle's CLOSE, same "confirmed
        candle close, not an intrabar wick" convention structural
        entries already use -- not the high/low, which may already
        have reverted by the time this runs), trims
        config.PARTIAL_EXIT_FRACTION of the qty at that close price,
        booking a real partial realized P&L via a dedicated
        closed_positions record (EXIT_REASON_PARTIAL_PROFIT) while
        the position stays open with its REDUCED qty -- the ATR
        trail (atr_stop/atr_extreme) is completely untouched, the
        remainder keeps riding exactly as it would have anyway.
        Sets partial_exit_done=True regardless of outcome so this
        never re-evaluates for the same position, win or skip.
        """
        direction = position.get("direction", LONG)
        entry_price = position["entry_price"]
        atr = position.get("atr_value")
        if not atr or atr <= 0:
            return

        # 2026-07-24 (evening): the trigger is the WIDER of the ATR
        # multiple or a real % of price, so a thin 1-minute ATR can no
        # longer fire a partial on a move too small to clear charges
        # (RELIANCE Rs 30 / HDFCBANK Rs 19.80 -- both net losses after
        # costs). See config.PARTIAL_EXIT_MIN_PCT.
        trigger_distance = max(
            PARTIAL_EXIT_ATR_MULTIPLE * atr,
            PARTIAL_EXIT_MIN_PCT * entry_price,
        )
        close = closed_candle["close"]
        if direction == LONG:
            triggered = close >= entry_price + trigger_distance
        else:
            triggered = close <= entry_price - trigger_distance

        if not triggered:
            return

        total_qty = position["qty"]
        trim_qty = int(round(total_qty * PARTIAL_EXIT_FRACTION))
        if trim_qty < 1 or trim_qty >= total_qty:
            # Too small a position to meaningfully split (or the
            # fraction rounds away to nothing/everything) -- skip,
            # the whole thing just rides the trail as before.
            position["partial_exit_done"] = True
            return

        exit_price = close
        pnl = None
        if direction == LONG:
            self.execution.sell(
                position["security_id"], symbol, exit_price, trim_qty,
                reason=EXIT_REASON_PARTIAL_PROFIT,
            )
            if self.portfolio is not None:
                pnl = self.portfolio.on_sell(entry_price, exit_price, trim_qty)
        else:
            self.execution.buy(
                position["security_id"], symbol, exit_price, trim_qty,
                reason=EXIT_REASON_PARTIAL_PROFIT,
            )
            if self.portfolio is not None:
                pnl = self.portfolio.on_cover(entry_price, exit_price, trim_qty)

        exit_time = closed_candle.get("time")
        entry_time = position.get("entry_time")
        holding_seconds = None
        if entry_time is not None and exit_time is not None:
            holding_seconds = (exit_time - entry_time).total_seconds()

        decision(
            f"\nPARTIAL PROFIT: {symbol}\n"
            f"Trimmed        : {trim_qty}/{total_qty} @ {exit_price:.2f}\n"
            f"Remaining qty  : {total_qty - trim_qty}"
        )

        self.closed_positions.append({
            "symbol": symbol,
            "security_id": position["security_id"],
            "qty": trim_qty,
            "entry_price": entry_price,
            "entry_time": entry_time,
            "entry_reason": position.get("entry_reason"),
            "direction": direction,
            "initial_stop": position.get("initial_stop"),
            "exit_price": exit_price,
            "exit_time": exit_time,
            "exit_reason": EXIT_REASON_PARTIAL_PROFIT,
            "holding_seconds": holding_seconds,
            "pnl": pnl,
        })

        # Reduce the OPEN position's qty in place -- used_margin(),
        # deployed_capital(), and the eventual full exit via _exit()
        # all read position["qty"] fresh every time, so this is the
        # only bookkeeping change needed; the stop/trail state is
        # untouched.
        position["qty"] = total_qty - trim_qty
        position["partial_exit_done"] = True

    def _check_fixed_bracket(self, symbol, position, price, tick_time):
        """
        LEGACY -- only reachable for a position that was already
        open with a real "fixed_target" BEFORE the 2026-07-24 ATR
        redesign, restored via core/state_store.py across a restart
        that happened to land mid-trade. No new entry sets
        fixed_target any more (see _atr_entry_sizing()). Both levels
        fixed at entry -- "initial_stop" (never changes, same field
        every other position uses for the RR calc) and
        "fixed_target". Stop is checked before target on a tick that
        crosses both at once (e.g. a gap) -- same capital-
        protection-first precedence as the trailing stop.
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

    def _process_pending_manual_exits(self, symbol, price, tick_time):
        """
        Operator report, 2026-07-23 night, live testing: "some
        stocks exited, then silently stopped exiting" after EXIT
        ALL. Root cause -- the previous version of this check
        (_check_manual_exit(), symbol-scoped) only ever acted on
        the ONE symbol the current tick happened to be for. A
        liquid, frequently-ticking stock got exited almost
        instantly; a quiet one just sat in the pending batch
        waiting for ITS OWN next tick, which could be minutes away
        -- indistinguishable from "broken" to the operator, even
        though the mechanism was technically still working.

        Fixed by decoupling "which symbol needs to exit" from
        "which symbol this tick happens to be for": this runs on
        EVERY process_tick() call regardless of symbol (call site
        is right after _check_trailing_stop(), same as before), and
        scans the FULL pending set -- the exit-all snapshot (see
        _maybe_snapshot_exit_all()) plus every individually-
        requested symbol (trade_controller.get_exit_requested_symbols()).
        The CURRENT tick's own (symbol, price) is used directly if
        it's one of the pending symbols (exactly the old behaviour,
        needs no market_data); every OTHER pending symbol is exited
        using market_data's cached last known price (thread-safe,
        same source the dashboard already reads) -- never waiting
        for that specific symbol's own next tick. With any real
        universe (even the ~50-symbol gainers/losers scope) ticking
        constantly, this drains the whole batch within a fraction
        of a second of the click, matching "clicked exit, it exits,
        right now, at market price."

        market_data is optional, same pattern as every other reader
        here -- None (a bare Engine(), most tests) just means only
        the current tick's own symbol can be resolved; other pending
        symbols wait for their own next tick, same as the pre-fix
        behaviour, never a crash, never a guessed price. A symbol
        with genuinely no known price yet (get_latest_price returns
        None) is left pending too, same fail-safe principle used
        everywhere else in this codebase.
        """
        self._maybe_snapshot_exit_all()

        pending = set(self.trade_controller.get_exit_requested_symbols())
        if self._exit_all_snapshot is not None:
            pending |= self._exit_all_snapshot

        if not pending:
            return

        for pending_symbol in pending:
            if pending_symbol not in self.open_positions:
                continue

            if pending_symbol == symbol:
                exit_price = price
            elif self.market_data is not None:
                exit_price = self.market_data.get_latest_price(pending_symbol)
                if exit_price is None:
                    continue
            else:
                continue

            self._exit(pending_symbol, exit_price, EXIT_REASON_MANUAL, tick_time)
            self.trade_controller.clear_exit(pending_symbol)

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
            # Entry context, carried through so the learning loop can
            # ask "which CONDITIONS worked", not just "what was the P&L".
            "sector": position.get("sector"),
            "rel_strength": position.get("rel_strength"),
            "regime": position.get("regime"),
        })

        # LEARN -> MEMORY (the operator's architecture, slide 5). Purely
        # observational: this records the completed trade with the
        # conditions it was taken in. NOTHING reads it back to make a
        # trading decision -- see core/trade_memory.py's docstring for
        # why that vote is deliberately withheld for now. Wrapped so a
        # bookkeeping failure can never affect an exit.
        if self.trade_memory is not None:
            try:
                self.trade_memory.record(self.closed_positions[-1])
            except Exception as exc:
                diagnostic(f"[LEARN] Could not record {symbol}: {exc}")

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
        #
        # EXIT_REASON_CIRCUIT_PROXIMITY added 2026-07-24, live bug:
        # STYL round-tripped SHORT 5x in 11 minutes (09:34-09:45),
        # every exit tagged CIRCUIT_PROXIMITY, each one immediately
        # followed by a fresh STRUCTURAL_SHORT_BREAKDOWN re-entry --
        # the breakdown signal kept re-firing as the stock kept
        # sliding toward its lower circuit, so the bot kept walking
        # right back into the same proximity flag seconds later.
        # Circuit proximity isn't a "failed signal" in the stopout
        # sense, but repeatedly re-entering a stock that's already
        # been flagged as approaching its circuit band today is the
        # same "stop fighting this stock" logic as a stopout -- one
        # attempt per symbol per direction per day here too. Opposite
        # direction still stays open, same as the stopout block.
        if BLOCK_REENTRY_AFTER_STOPOUT \
                and reason in (
                    EXIT_REASON_TRAILING_STOP, EXIT_REASON_FIXED_STOP,
                    EXIT_REASON_CIRCUIT_PROXIMITY) \
                and position.get("entry_reason") in (
                    ENTRY_REASON_STRUCTURAL_LONG, ENTRY_REASON_STRUCTURAL_SHORT):
            reason_text = (
                "flagged near its circuit limit once today -- no repeat "
                "attempts in the same direction"
                if reason == EXIT_REASON_CIRCUIT_PROXIMITY else
                "stopped out once today -- no repeat attempts in the "
                "same direction"
            )
            self._block_entry(symbol, direction, reason_text)

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

        # 2026-07-24 (evening) -- AUTO-RESUME REMOVED. The original
        # design un-paused the moment the book went flat ("new entries
        # will resume after all open positions exit"), but that made
        # "Stop New Entries + Exit All" useless: the instant Exit All
        # cleared the last position the book was empty, the pause
        # lifted, and the bot instantly re-opened 10 fresh positions
        # -- the exact opposite of what the button is for (operator
        # report, 2026-07-24). The pause now STAYS ON until the
        # operator explicitly turns it back on (dashboard "Resume New
        # Entries" button -> trade_controller.resume_new_entries()).
        # "Stop New Entries" now means what it says: stopped, until
        # you say otherwise.

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
            # SWING_TRAILING default for snapshots saved before the
            # 2026-07-24 ATR redesign -- _check_trailing_stop() falls
            # through to the swing-based engine exactly as it always
            # did for these, since core/trailing_stop.py's own state
            # (loaded separately, see main.py) already has them.
            position.setdefault("stop_mode", STOP_MODE_SWING_TRAILING)
            position.setdefault("atr_extreme", None)
            position.setdefault("atr_stop", None)
            position.setdefault("atr_value", None)
            # False default for snapshots saved before the
            # partial-exit test rig existed -- treated as "hasn't
            # partially exited yet", so a restart never re-triggers
            # a double partial on an old position, but also never
            # skips a legitimate first partial for it.
            position.setdefault("partial_exit_done", False)
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
