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
from datetime import datetime, time as dtime, timedelta

from config import (
    ENABLE_SHORT_TRADES,
    LAYER1_FIXED_QTY, ORB_STOP_BUFFER_PCT, BLOCK_REENTRY_AFTER_STOPOUT,
    MANUAL_POSITIONS_BOT_MAY_NOT_CLOSE, MANUAL_POSITIONS_TRAIL_ALERTS_ONLY,
    MANUAL_ALERT_HISTORY, ENABLE_BOT_TRAILING_STOP, MANUAL_TEST_QTY,
    ALERT_ONLY_MODE,
    HARD_STOP_FROM_ENTRY_PCT, VOLUME_WINDOW_CANDLES,
    VOLATILITY_SCALED_STOP, DAILY_ATR_STOP_MULT,
    VOLUME_REQUIRED_FOR_ENTRY, ROTATION_MAX_PER_DAY,
    CIRCUIT_RULE_DIRECTION_AWARE,
    TOP_N_MOMENTUM_MODE,
    SQUARE_OFF_TIME, FROZEN_PRICE_STREAK_CANDLES,
    ATR_PERIOD, MIN_ATR_CANDLES,
    ENABLE_MARKET_REGIME_GATE,
    MTF_MARGIN_PER_POSITION_RS,
    ATR_STOP_MULTIPLIER, ATR_TRAIL_MULTIPLIER, ATR_TRAIL_ACTIVATION_MULT,
    MIN_STOP_DISTANCE_PCT, FIXED_STOP_PCT,
    # ---- LOOKS UNUSED. IS NOT. 31 August 2026. ----
    #
    # Nothing in this file reads MAX_NOTIONAL_PER_TRADE_RS -- sizing
    # moved to the MTF margin on 29 July. A sweep for unused imports
    # removed it, and the suite caught it in one run.
    #
    # It is a deliberate anchor. test_engine's
    # test_atr_entry_sizing_notional_cap_binds_independently_of_the_stop_floor
    # monkeypatches it HERE, to an absurd value, to prove the share
    # count does not move when it changes. Until 29 July size came from
    # min(RISK / stop, MAX_NOTIONAL / price), which at the 1% stop floor
    # is the same number -- so the ceiling bound every trade and ATR did
    # nothing. All 29 structural entries that day came out between
    # Rs 197,041 and Rs 200,382, double the size he had specified.
    #
    # Remove this line and that regression stops being watched.
    MAX_NOTIONAL_PER_TRADE_RS,
    STOP_FROM_RISK_AND_SIZE,
    MIN_TRADABLE_PRICE_RS, EARNINGS_CALENDAR,
    ENABLE_PARTIAL_EXIT, PARTIAL_EXIT_ATR_MULTIPLE, PARTIAL_EXIT_FRACTION,
    PARTIAL_EXIT_MIN_PCT,
    LAST_ENTRY_TIME, REGIME_GATE_ENABLED, REGIME_BREADTH_THRESHOLD,
    REGIME_REFRESH_SECONDS, REGIME_MIN_SYMBOLS,
    MAX_OPEN_POSITIONS, DAILY_MAX_LOSS_RS, DAILY_PROFIT_TARGET_RS,
    BREAKOUT_MIN_MARGIN_PCT,
    ENABLE_TREND_RANK_ENTRY, TREND_RANK_TOP_N, TREND_RANK_REFRESH_SECONDS,
    ENABLE_SLOT_ROTATION, ROTATION_MIN_STRENGTH_EDGE,
    ROTATION_MIN_HOLD_MINUTES,
    ENABLE_RS_BAND, RS_BAND_MIN, RS_BAND_MAX, MAX_ABS_MOVE_PCT,
    ENABLE_STILL_TRENDING, STILL_TRENDING_MIN_POSITION,
    ENABLE_STAGED_ENTRY, STAGED_POSITION_LIMITS, STAGED_NO_ENTRY_AFTER,
    ENABLE_CASH_SIZED_BOOK,
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
    MANUAL_BUY_TARGET_RS, MANUAL_BUY_TRAILS, TARGET_REWARD_BY_REGIME,
)
from core.atr import compute_atr, daily_atr_pct
# ---- ONE RISK BUDGET, NOT TWO. 12 August 2026. ----
#
# This was `RISK_PER_TRADE_RS` off config.py, which says 2,000.
# core/position_plan.py -- the sizing on the OTHER lane that can place
# an order -- takes it from core/rules.py, which says 1,500. Both are
# live, so the same bot risked a different amount depending on which
# half of itself found the trade.
#
# AUDIT_2026-08-12.md calls config's 2,000 "legacy, sizes nothing".
# That was true until 7 August and is not true now: _cap_by_risk()
# below reads it on every single entry this engine makes.
#
# 1,500 is the number he approved on 11 August, and the reasoning in
# core/rules.py still holds -- twelve replayed days were measured at
# 1,500 and the selector has no proven edge yet, so raising size before
# there is an edge only loses money faster.
from core import tick_ohlc
from core.rules import (RISK_PER_TRADE_RS, BREAKOUT_MAX_OFF_HIGH_PCT,
                        MIN_STOP_DISTANCE_PCT as STOP_FLOOR_PCT,
                        MAX_STOP_DISTANCE_PCT as STOP_CEILING_PCT)
from core.orb_engine import OrbEngine, EARLY_ORB_END_T, ORB_WINDOW_END_T
from core.candle_engine import CandleEngine
from core.strategy import Strategy
from core.trailing_stop import TrailingStopEngine, LONG, SHORT
from core.logger import (decision, diagnostic, warn,
                         when_it_changes)

# A refusal that is true RIGHT NOW and must be asked again next
# cycle, rather than one that settles the stock for the session.
# entry_blocked is otherwise permanent: nothing clears it, and
# _try_structural_entry() returns on it before any gate runs. So
# a stock refused at 12:34 could never be bought at 14:00 however
# the day turned. The reason is still recorded and still shown on
# the panel -- it just no longer settles the question.
#
#     "new entries only when opportunity showed up. there is no
#      fixed time ,price or fixed limitations to follow."
#                                 -- the operator, 1 Sept 2026
FOR_NOW = "for now -- "


def _is_provisional(reason):
    return str(reason or "").startswith(FOR_NOW)

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


def _entry_cutoff_reason(at_time):
    """Why a NEW position may not be opened right now, or None.

    ---- 31 July 2026: THE 15:15 BLOCK WAS GUARDING NOTHING ----

        "Pls remove this 15:15 Hard rule as we moved from MIS to MTF.
         this hard square off is not ideal to have."

    The block above was written for MIS. Its entire justification, in
    its own words, was "square-off exists specifically to guarantee
    zero new intraday exposure past this time" -- do not open something
    the bot is about to force-close three minutes later.

    That reasoning is sound and it stopped being true on 28 July, when
    FORCE_SQUARE_OFF_AT_CLOSE was set False for MTF. Nothing is
    force-closed at 15:15 any more. The gate stayed, so the bot was
    refusing entries to protect them from a liquidation that no longer
    happens -- and on MTF a 15:20 entry is not stray intraday exposure,
    it is an overnight position, which is the entire point of the
    product.

    So the rule is now tied to the thing that justified it rather than
    to a clock. Turn FORCE_SQUARE_OFF_AT_CLOSE back on for a day you
    want to be flat, and the 15:15 block comes back with it,
    automatically, because it is once again true.

    WHAT DID NOT CHANGE
    -------------------
    - The market close still ends everything. 15:29 is a real entry;
      15:31 is not.
    - STAGED_NO_ENTRY_AFTER (15:00) still gates AUTOMATIC entries, so
      the bot's own behaviour is barely affected -- it had already
      stopped opening by 15:00. This mostly frees the operator's own
      manual buys in the last half hour, which is what he asked for.
    - Trailing stops keep managing everything through the close and
      into the next session. A position is never unmanaged.

    Read from config at CALL time, not import time, so flipping the
    switch does not need a code change to take effect anywhere.
    """
    if at_time is None:
        return None
    from config import (FORCE_SQUARE_OFF_AT_CLOSE, MARKET_CLOSE,
                        SQUARE_OFF_TIME as _SO)
    now = at_time.time()
    if FORCE_SQUARE_OFF_AT_CLOSE and now >= _parse_hhmm(_SO):
        return (f"past square-off ({_SO}) and FORCE_SQUARE_OFF_AT_CLOSE "
                f"is ON -- a new position would be flattened within "
                f"minutes")
    if now >= _parse_hhmm(MARKET_CLOSE):
        return f"the market is closed ({MARKET_CLOSE})"
    return None

# How long after the opening-range window closes the exchange reconcile
# may still run. The quote it reads carries the DAY high/low, which only
# equals the opening range for a few minutes after 09:30. In normal
# running the reconcile fires within seconds of the window closing (TBZ:
# window closed 09:30:16, reconciled 09:30:16). This grace exists only
# for a slow first snapshot, not for restarts. See
# _reconcile_orb_once() for the full incident.
ORB_RECONCILE_GRACE_MINUTES = 5
_ORB_RECONCILE_DEADLINE_T = (
    datetime.combine(datetime.today(), ORB_WINDOW_END_T)
    + timedelta(minutes=ORB_RECONCILE_GRACE_MINUTES)
).time()

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
EXIT_REASON_BUYING_DRIED_UP = "BUYING_DRIED_UP"

# The reading compares now against fifteen minutes ago, so a position
# younger than that is being judged against the noise around its own
# entry. It matches STILL_BUYING_LOOKBACK in the flow module, and is
# not a number anybody chose.
BUYING_CHECK_MIN_MINUTES = 15
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

# A position he opened himself, taken into the bot's book so the stops
# and exits that already work start working on it too. 5 August 2026.
ENTRY_REASON_ADOPTED = "ADOPTED_FROM_BROKER"

# ---- THE MOVE IS OVER. 5 August 2026. ----
#
#   "ride untill the momentum stays - exit once it gone ruthlessly"
#                                 -- operator, core ideology
#
# core/ranker.py's liveness() has known since 4 August when a move has
# died -- it is what demotes a stock that made its high at 09:16 and
# sat there. It was used to RANK and never to EXIT.
#
# The cost, measured on 5 August: of nineteen reconstructed trades,
# SEVENTEEN reached neither their stop nor their target. They were held
# until the bell because nothing was watching whether they still
# worked. HAPPYFORGE was +Rs 786 with a target it never reached and
# nothing asked, at any point, whether the move was still on.
#
# A stop protects against being wrong. This protects against being
# right and then sitting through the giveback.
EXIT_REASON_MOVE_DIED = "MOVE_DIED"

# How far off the day's extreme before the move is called finished.
# Deliberately WIDER than the ranker's 3.0% entry threshold: refusing
# to open a position is cheap, and closing one he is already in costs
# brokerage and a slot. A position gets more rope than a candidate.
MOVE_DIED_OFF_EXTREME_PCT = 4.5

# Only once it has actually made money. A new position that dips below
# its entry is the STOP's business, not this one -- exiting there would
# be a second, tighter, undeclared stop.
MOVE_DIED_MIN_GAIN_R = 0.5

# ATR_TRAILING only, 2026-07-24 -- "dynamic position building"
# extension to item 3 (config.PARTIAL_EXIT_ATR_MULTIPLE's docstring).
# Books PART of the qty as a realized win while the position is
# still open and still running -- distinct from every other
# EXIT_REASON above, which always closes the WHOLE position. Never
# participates in BLOCK_REENTRY_AFTER_STOPOUT (it's a win, not a
# failed signal) and never appears in _exit() at all -- see
# _maybe_partial_exit()'s own bookkeeping.
EXIT_REASON_PARTIAL_PROFIT = "PARTIAL_PROFIT_ATR"

# The operator's own trim, from the dashboard -- "sell half and let the
# rest run". Kept SEPARATE from PARTIAL_PROFIT_ATR on purpose: one is
# the bot's rule firing and the other is his judgement, and the trade
# log has to be able to tell them apart when either is later measured.
# Like the ATR trim, it never closes the whole position and so never
# reaches _exit().
EXIT_REASON_MANUAL_PARTIAL = "MANUAL_PARTIAL"

# 2026-07-27, operator-found live on SWIGGY: the bot's stop is checked
# ONLY against tick prices that actually arrive --
# core/trailing_stop.py's is_hit() is `price <= stop`. But the Dhan
# WebSocket sends periodic SNAPSHOTS, not every trade (already proven
# on this project for the ORB range: ZENTEC seen 1784.20 vs a real
# 1792.00, which is why ENABLE_ORB_EXCHANGE_RECONCILE exists). So a
# dip THROUGH the stop between two snapshots is never seen, and the
# position stays open carrying a loss it was supposed to have cut.
#
# The operator watched exactly this happen: SWIGGY traded below its
# stop on TradingView, no tick in our feed showed it, the bot held on.
#
# This is not a small bug. It means RISK_PER_TRADE_RS is not actually
# enforced -- it is the risk we take IF the feed happens to catch the
# breach, and unbounded if it does not. Every replay in this project
# assumes stops fill at the stop price.
#
# The reconciliation that catches it is in _check_missed_stop(): the
# exchange's own day LOW/HIGH (already polled every ~3s by
# core/circuit_monitor.py for all 693 symbols) can only move one way,
# so if it extends past our stop AFTER we entered, the breach is ours
# and we missed it.
#
# Tagged distinctly from TRAILING_STOP on purpose -- these need to be
# COUNTED. How often the feed skips a stop, and by how much, decides
# whether MTF overnight holding is safe at all: a missed stop squared
# off at 15:15 is a bad day, a missed stop carried overnight is not.
EXIT_REASON_MISSED_STOP = "MISSED_STOP_RECONCILED"


# ---- A REFUSED EXIT IS NOT AN EXIT. 31 August 2026. ----
#
# _enter() has checked this since it was written:
#
#     if not result.get("success"):
#         return
#
# _exit() never did. It took the fill price out of the result and
# carried on -- telling the portfolio, removing the position from the
# book, writing a closed trade -- whether or not the order had actually
# been placed.
#
# In PAPER this cannot bite; the paper executor always succeeds. In
# LIVE it is the worst outcome this bot can produce. Dhan refuses
# orders for real reasons: margin, a frozen scrip, a price band, or a
# market that has moved to the closing auction -- which every F&O stock
# does at 15:15. The bot would then believe it was flat while still
# holding the shares, with no stop watching it, no exit rule watching
# it, and no row anywhere saying it exists.
#
# The same fault this repository forbids in three other places --
# "claim a stop is resting when the API call failed", "report success
# when the broker never answered" -- arriving on the one path nobody
# had checked.
#
# THE CHECK GOES BEFORE THE PORTFOLIO, not after. Booking the P&L and
# then returning would leave the trade counted and the position open,
# which is worse than either.


def _order_went_through(result):
    """A missing "success" key means the executor does not report one,
    and the order stands. Only an explicit False is a refusal -- this
    must never invent a failure out of a shape it does not recognise."""
    if not isinstance(result, dict):
        return True
    return result.get("success", True) is not False


def _refused_exit(symbol, result):
    reason = (result or {}).get("error") if isinstance(result, dict) else None
    warn(f"[EXIT] {symbol} NOT closed -- the broker refused the order "
         f"({reason or 'no reason given'}). The position is STILL OPEN "
         f"and still managed; the next tick will try again. Nothing has "
         f"been booked.")


class Engine:

    def __init__(self, portfolio=None, sector_monitor=None,
                 momentum_universe=None, circuit_monitor=None, market_data=None,
                 signal_journal=None,
                 min_tradable_price=MIN_TRADABLE_PRICE_RS,
                 earnings_calendar=None,
                 candle_recorder=None,
                 enable_rs_band=None, enable_staged_entry=None,
                 one_trade_per_symbol=None, enable_no_progress=None,
                 enable_tick_sanity=None, stock_memory=None,
                 trade_memory=None, breakout_feed=None,
                 mtf_margin=None, results_gate=None,
                 news_feed=None, announcements=None,
                 alert_only=None, dhan_client=None):
        # ALERT ONLY -- config.py's value by default, injectable for the
        # same reason min_tradable_price is: a module-level constant read
        # from inside the tick path cannot be turned off for a test that
        # is about entry MECHANICS rather than about this switch. Reading
        # ALERT_ONLY_MODE directly broke 14 entry tests, which is the
        # signal that it belonged here rather than in the hot path.
        self.alert_only = (ALERT_ONLY_MODE if alert_only is None
                           else bool(alert_only))
        # THE SECOND SWITCH, AND IT IS OFF. The structural breakout
        # path has no ranker gates -- no move threshold, no reason, no
        # sector check, no liquidity check. It must be armed on its own,
        # deliberately, and never as a side effect of turning the bot on.
        # See _try_structural_entry() for what this cost on 6 August.
        self.breakout_armed = False

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
        # Slippage needs to know how liquid each symbol is, and
        # circuit_monitor already polls day turnover for the whole
        # universe -- no new poller, no extra request. Lambda rather
        # than a direct reference so it reads the CURRENT snapshot on
        # every fill, not whatever existed at construction.
        # Returns None (= assume thin, the expensive assumption) when
        # the snapshot is not ready or the monitor is not wired.
        # THE ARGUMENT THAT WAS NEVER PASSED.
        #
        # 31 July 2026, 09:00. TRADING_MODE was flipped to LIVE for the
        # first real order and main.py refused to start:
        #
        #   RuntimeError: TRADING_MODE is LIVE but no Dhan client was
        #   provided. Refusing to start.
        #
        # main.py had built the REST client at line 210 and handed it to
        # the circuit monitor and the MTF margin calculator. It never
        # handed it here, because until this line there was nowhere to
        # put it. In PAPER the argument is unused, so the omission was
        # invisible for months.
        #
        # Both lookups are LAMBDAS, not values: self.market_data and
        # self.open_positions are assigned further down this same
        # __init__, so anything read eagerly here would be None. They
        # also need to read the CURRENT price and the CURRENT book at
        # order time, not whatever existed at construction.
        self.execution = Execution(
            turnover_lookup=self._day_turnover_cr,
            dhan_client=dhan_client,
            price_lookup=self._live_price_for_order,
            open_position_count=lambda: len(self.open_positions),
        )
        self.trade_controller = TradeController()

        # ---- A STOP THAT SURVIVES THIS PROCESS DYING, 2026-08-02 ----
        #
        # self.trailing_stop above lives in RAM. If this process dies
        # with an MTF position open, that stop dies with it and Dhan
        # never knew one was intended. This rests a Forever Order at
        # the broker as a BACKSTOP -- below the live stop, so the two
        # cannot race, and cancelled on every exit.
        #
        # OFF unless BROKER_STOP_ENABLED. See trading/broker_stop.py.
        from config import (BROKER_STOP_ENABLED, BROKER_STOP_RESYNC_PCT,
                            BROKER_STOP_TAG_PREFIX, EXCHANGE_SEGMENT,
                            TRADING_MODE)
        from trading.broker_stop import BrokerStop

        # ---- THE BUY WAS IMAGINARY. THE SELL WAS REAL. ----
        #      19 August 2026, 14:26.
        #
        #     "why dhan pipeline activiated & order placed to SELL
        #      NILKAMAL?"
        #
        # Ten seconds apart in his log:
        #
        #   14:26:33  PAPER BUY NILKAMAL qty=28 @ 2075.64
        #             (MANUAL_BUY_DASHBOARD)
        #   14:26:43  [BROKER_STOP] NILKAMAL: SELL 28 resting at Dhan,
        #             trigger 2023.75 (id 23132608191377)
        #
        # TRADING_MODE was PAPER, so the BUY was simulated and no
        # order left the machine. BROKER_STOP_ENABLED reads its own
        # flag and nothing else, so the protective SELL was placed
        # FOR REAL, against a position that existed only in memory.
        #
        # Dhan rejected it -- he held no NILKAMAL MTF position to sell
        # -- and that rejection is the only reason this cost nothing.
        # The protection was the exchange's, not ours. Had he been
        # holding NILKAMAL from his own trading, a stop derived from a
        # paper entry could have been ACCEPTED against real shares.
        #
        # A resting order at a broker is a LIVE instruction. It cannot
        # be armed by a flag that does not know whether the rest of
        # the system is pretending.
        _stop_live = str(TRADING_MODE).upper() == "LIVE"
        if BROKER_STOP_ENABLED and not _stop_live:
            warn(f"[BROKER_STOP] DISABLED -- BROKER_STOP_ENABLED is on "
                 f"but TRADING_MODE is {TRADING_MODE}. A real resting "
                 f"order must never protect a simulated position. "
                 f"Set TRADING_MODE=LIVE to arm it.")

        self.broker_stop = BrokerStop(
            dhan_client=dhan_client,
            exchange_segment=EXCHANGE_SEGMENT,
            # MTF, matching every order trading/live_execution.py sends.
            # A protective order on the wrong product would be refused
            # by Dhan, or worse, accepted against a different position.
            product_type="MTF",
            enabled=BROKER_STOP_ENABLED and _stop_live,
            resync_pct=BROKER_STOP_RESYNC_PCT,
            tag_prefix=BROKER_STOP_TAG_PREFIX,
        )

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

        # Disk record of every structural signal, taken or refused
        # (core/signal_journal.py, 2026-07-29). Optional: None means
        # nothing is written and nothing else changes.
        self.signal_journal = signal_journal

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

        # Fresh Breakouts panel (core/breakout_feed.py, 2026-07-28).
        # Observation only -- it never gates a trade.
        self.breakout_feed = breakout_feed

        # Operator's Rs 1 lakh-of-margin sizing rule
        # (core/mtf_margin.py, 2026-07-28). None = own cash only.
        self.mtf_margin = mtf_margin

        # Results gate (core/results_gate.py, 2026-07-28).
        # None = fall back to the old blanket results-day block.
        self.results_gate = results_gate

        # The evidence feeds. Read by _capture_reason(), which stamps
        # WHY a trade was taken onto the position for
        # core/trade_memory.py -- and, since 12 August 2026, by
        # _no_reason_refusal(), which requires that there BE a why.
        #
        # That comment used to end "Observation only -- nothing here
        # gates a trade". It was accurate for a fortnight and it was
        # also the bug: BOT_SPEC.md's entry rule 2 existed the whole
        # time and this lane never applied it.
        self.news_feed = news_feed
        self.announcements = announcements

        # Said once, not per symbol per candle. See _no_reason_refusal().
        self._warned_no_reason_sources = False

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
        # Symbols we have sold today and are still watching, purely so
        # the dashboard can answer "what did it do after we got out".
        # See _watch_after_exit() -- observation only, never an input
        # to any decision.
        self.post_exit = {}

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

        # Plain-English notes about positions the OPERATOR opened --
        # every time the bot wanted to close one and was not allowed
        # to, and every trailing-stop breach it reported instead of
        # acting on. 2026-07-29, after SMLMAH. See _manual_alert.
        self.manual_alerts = []
        self._manual_alerts_seen = set()

        # ---- WHERE THOSE NOTES GO NEXT. 18 August 2026. ----
        #
        #     "why i didn't get any alerts to buy stocks in telegram?"
        #
        # Because this list was the end of the road. Between 31 July
        # and this morning the bot wrote 2,652 of these notes -- every
        # one reached a log file and the board, and not one reached
        # him. The alert was never missing; the last mile was.
        #
        # main.py sets this to core/telegram_desk.py's push(). None is
        # the correct default and must stay it: the Engine has to run
        # identically with no phone attached, and no test may need one.
        self.on_alert = None

        # Slot rotation, switched on 2026-07-29 for the two paper
        # sessions before live. Counted and capped -- see config's
        # ROTATION_MAX_PER_DAY.
        self._rotations_today = 0
        self._rotation_cap_logged = False

        # (symbol, source, event stamp) already announced. Keyed on the
        # EVENT so a second, different filing on the same stock is still
        # reported. 2026-07-29.
        self._news_alerted = set()

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

        # Where a stock we already sold has gone since. One dict
        # lookup, before anything can return early -- a symbol we are
        # flat in takes several early exits further down this method,
        # and putting this after any of them is how the panel would
        # quietly stay empty for exactly the stocks it exists for.
        self._update_after_exit(symbol, price, tick_time)

        self.orb_engine.update(symbol, price, tick_time)

        # 2026-07-29: our ticks are snapshots ~4.6s apart, so the true
        # opening-range extreme is often never in one. Dhan's REST
        # quote carries the exchange's own session high and low and is
        # polled every 3 seconds -- inside the ORB window that IS the
        # range. A dict lookup on the tick path; widens only, never
        # narrows. See OrbEngine.merge_official for the measurements.
        if self.circuit_monitor is not None:
            try:
                official = (self.circuit_monitor.get_snapshot()
                            or {}).get(symbol)
                if official:
                    self.orb_engine.merge_official(
                        symbol, official.get("high"), official.get("low"),
                        tick_time)
                    # Same response carries the exchange's real OPEN.
                    # Ours is the first snapshot to arrive, ~2s and a
                    # rupee or two late -- INFY opened at 1,147.00 on
                    # 29 July and the bot's first tick said 1,145.00,
                    # which is the whole "+3.55% vs NSE's +3.74%" gap.
                    if self.market_data is not None:
                        self.market_data.set_official_day_open(
                            symbol, official.get("open"))
            except Exception:                              # noqa: BLE001
                pass

        # Fresh Breakouts panel: mark a breakout FADED the moment price
        # drops back inside the range it broke. A dict lookup and a
        # float compare -- cheap enough for the tick path. The row is
        # kept, greyed: a breakout that silently vanishes teaches
        # nothing, one that visibly fails teaches how often they fail.
        if self.breakout_feed is not None:
            self.breakout_feed.update_price(symbol, price)
            # Count TESTS of the range boundary -- the pressure building
            # BEFORE a break, which the operator can see on a chart and
            # the bot previously could not (RADICO pressed against 4,182
            # for hours on 2026-07-28 before finally going).
            orb = self.orb_engine.get_range(symbol)
            if orb and orb.get("complete"):
                self.breakout_feed.note_touch(
                    symbol, price, orb.get("high"), orb.get("low"))

        closed_candle = self.candle_engine.update(
            symbol, price, tick_time, cum_volume
        )

        if closed_candle is not None:
            # ---- THE STORE ALREADY HAS THIS. 24 August 2026. ----
            #
            #     "too many repeated data prints"   -- operator
            #
            # 49,830 [CANDLE] lines in the 24 August session, 52% of a
            # 95,933-line log -- one per symbol per minute across 1,291
            # symbols. Every one of them is written to the replay
            # bench's store immediately below, so the line restates a
            # database row and nothing here reads it back.
            #
            # Kept for what is HELD, because that is the case where
            # somebody is watching a specific stock minute by minute
            # and wants it beside the exit decisions in the same file.
            # Everything else is in data/backtest_candles.db, complete
            # and queryable, exactly as before -- the recording below
            # is untouched.
            if symbol in getattr(self, "open_positions", {}):
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

                # 2026-07-29: news on something we HOLD. Once per closed
                # candle, open positions only -- roughly ten lookups a
                # minute rather than ten thousand.
                self._check_news_on_holding(symbol, position,
                                            closed_candle.get("close"))

                if not self._is_frozen(symbol):
                    if position.get("stop_mode") == STOP_MODE_ATR_TRAILING:
                        self._update_atr_trailing_on_candle_close(
                            symbol, position, closed_candle
                        )
                    elif position.get("fixed_target") is None:
                        # reference_price = this candle's CLOSE, so the
                        # minimum-distance floor is measured against where
                        # the market actually is, not against the wick.
                        # See trailing_stop.update_on_candle_close's
                        # docstring: without it the stop ratchets up to
                        # touching distance and every position exits at
                        # breakeven within minutes (2026-07-27, LAURUSLABS
                        # bought and sold at 1681.60).
                        new_stop = self.trailing_stop.update_on_candle_close(
                            symbol, closed_candle["low"], closed_candle["high"],
                            reference_price=closed_candle["close"],
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
            # READ THE SIZE BEFORE CLEARING. clear_buy() drops the
            # remembered quantity along with the request, so reading it
            # afterwards would silently give every dashboard buy the
            # default size again -- the exact bug this change exists to
            # fix, reintroduced by the order of two lines.
            asked_qty = self.trade_controller.buy_qty(symbol)
            self.trade_controller.clear_buy(symbol)
            if symbol in self.open_positions:
                warn(
                    f"[MANUAL_BUY] {symbol} already has an open "
                    f"position -- request ignored, no pyramiding."
                )
            elif _entry_cutoff_reason(tick_time):
                # Was a flat "past 15:15" block. See
                # _entry_cutoff_reason() -- that rule existed to stop
                # the bot opening something it was about to force-close,
                # and since 28 July it force-closes nothing. On MTF a
                # 15:20 buy is an overnight position, not stray
                # intraday exposure.
                warn(
                    f"[MANUAL_BUY] {symbol} skipped -- "
                    f"{_entry_cutoff_reason(tick_time)}."
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
                #
                # ---- 2026-08-01: THE FLOOR IS NOW THE HARD STOP ----
                # This line read MIN_STOP_DISTANCE_PCT (1%) until today,
                # and the operator did not know it:
                #
                #     "what are we using 1% stoploss? from when this came
                #      i'm not aware of this logic"
                #
                # He was right not to recognise it. MIN_STOP_DISTANCE_PCT
                # is a FLOOR UNDER THE ATR TRAIL, raised to 1% on 24 July
                # to stop the trail clipping winners on noise. On 29 July
                # the trail was switched off entirely and the stop became
                # HARD_STOP_FROM_ENTRY_PCT, 2.5%, his own number measured
                # across 80 replayed trades. _atr_entry_sizing() was
                # updated. THIS LINE WAS NOT. So the bot's own entries ran
                # a 2.5% stop while every dashboard BUY ran 1% -- two
                # stops in one account, with nothing anywhere saying why.
                #
                # Measured before changing it. 50,422 entries, buy at
                # close, hold 3 sessions, liquid NSE stocks since 1 April:
                #
                #     stop    avg/trade   stopped out   winners killed
                #     1.0%      +0.392%      72.9%          51.4%
                #     2.5%      +0.424%      45.2%          19.7%
                #     3.5%      +0.489%      30.7%           9.8%
                #     5.0%      +0.577%      16.5%           3.2%
                #     none      +0.634%       0.0%              -
                #
                # 1% was killing HALF of all winning trades. Of trades up
                # after three sessions, the median dipped 1.05% below
                # entry first -- the stop sat inside ordinary noise, and
                # on a multi-day MTF hold that is fatal.
                #
                # WHY 2.5% AND NOT 3.5%, WHICH EARNS MORE. Leverage. At
                # 4X on a Rs 4,00,000 position Dhan's holding coverage
                # reaches 20% -- their margin-call line -- at a 6.27%
                # fall. That 6.27% is the entire runway:
                #
                #     2.5% stop  -> Rs -10,000   3.77% of room left
                #     3.5% stop  -> Rs -14,000   2.77% of room left
                #     5.0% stop  -> Rs -20,000   1.27% of room left
                #     no stop    -> tail is -90% on a single trade
                #
                # The extra Rs 261/trade a 3.5% stop earns is the money
                # you would pay to sit 2.77% from a broker margin call on
                # every open position. Reassess if leverage ever drops to
                # 2X -- the runway doubles and 3.5% becomes correct.
                #
                #     "from 1% (too noise) to 2.5% (some may hit stop
                #      losses but thats part of the game)"
                #                             -- operator, 1 August 2026
                #
                # The candle-low rule below is KEPT. Measured across
                # 1,445,619 one-minute candles (27-31 July), a candle low
                # sits more than 2.5% under its close 64 times -- 0.004%.
                # It is a fire alarm for the one violent bar, not a rule
                # that binds. Both of his 31 July SHADOWFAX buys had
                # candle lows 0.12% and 0.37% away; the floor won both.
                floor_low = price * (1 - HARD_STOP_FROM_ENTRY_PCT)
                if last_candle and last_candle["low"] < price:
                    seed_low = min(last_candle["low"], floor_low)
                else:
                    seed_low = floor_low
                # HIS CLICK, HIS SIZE. The risk cap governs what the
                # BOT chooses on its own; a manual buy is a decision he
                # has already made, and silently handing him 47 shares
                # when the margin book says 67 would be the bot
                # overruling him at his own keyboard.
                qty = self._manual_qty(
                    self._risk_sized_qty(price, price - seed_low,
                                         symbol, security_id,
                                         cap_by_risk=False),
                    asked=asked_qty)
                # ---- HIS COMMAND, HIS RULES. 23 August 2026. ----
                #
                #     "BUY SBIN = then bot must buy SBIN MTF with
                #      assigned rules (capital, target, stoploss,
                #      trailling)"                    -- operator
                #
                # Capital and stop were already applied. TARGET and
                # TRAILING were not -- _enter() has accepted both since
                # it was written and this call passed neither, so every
                # dashboard and Telegram buy ran bare.
                #
                # Only HIS entries get them. The bot's own keep holding
                # to the close: seven target widths were measured on
                # 22-23 August and every one underperformed holding. He
                # was asked and chose that split.
                target = None
                if MANUAL_BUY_TARGET_RS and qty:
                    target = price + (MANUAL_BUY_TARGET_RS / abs(int(qty)))
                self._enter(
                    symbol, security_id, price, seed_low, tick_time,
                    ENTRY_REASON_MANUAL_DASHBOARD, LONG, qty=qty,
                    target=target,
                    stop_mode=(STOP_MODE_ATR_TRAILING if MANUAL_BUY_TRAILS
                               else STOP_MODE_SWING_TRAILING),
                )

        # Manual short request (dashboard's per-row SHORT button on
        # the Top 50 Losers table) -- exact mirror of the manual buy
        # block above, direction flipped. Same operator-override
        # reasoning: bypasses news/sector checks, no pyramiding,
        # blocked past square-off.
        if self.trade_controller.is_short_requested(symbol):
            # Read before clearing -- same trap as the BUY block above.
            asked_short_qty = self.trade_controller.short_qty(symbol)
            self.trade_controller.clear_short(symbol)
            if symbol in self.open_positions:
                warn(
                    f"[MANUAL_SHORT] {symbol} already has an open "
                    f"position -- request ignored, no pyramiding."
                )
            elif _entry_cutoff_reason(tick_time):
                # Exact mirror of the manual BUY gate above. A SHORT is
                # NOT an MTF position -- it cannot be carried overnight
                # on delivery -- but the gate is left identical on
                # purpose: whether a short may be opened at 15:20 is a
                # question about the product and the broker's own RMS,
                # not about a square-off the bot no longer performs.
                # Two different rules on the two buttons would be a
                # surprise nobody asked for.
                warn(
                    f"[MANUAL_SHORT] {symbol} skipped -- "
                    f"{_entry_cutoff_reason(tick_time)}."
                )
            else:
                last_candle = self.candle_engine.last_closed(symbol)
                # Mirror of the LONG seed_low logic above -- a SHORT's
                # stop must always sit strictly ABOVE entry price. The
                # last closed candle's high can be stale or missing,
                # same reasoning as the LONG side, just flipped.
                # Mirror of the manual-buy floor above -- the seed
                # sits at least HARD_STOP_FROM_ENTRY_PCT ABOVE entry, so
                # a short can't be handed a 0.02% stop off a barely-wide
                # last candle. Whichever is HIGHER (more room) wins.
                #
                # 2026-08-01: moved from MIN_STOP_DISTANCE_PCT (1%) to
                # HARD_STOP_FROM_ENTRY_PCT (2.5%) with the BUY side. See
                # the measured tables in the manual-buy block above. Kept
                # identical to the BUY deliberately -- two different stops
                # on the two dashboard buttons is exactly the surprise
                # that made the operator ask where 1% came from.
                #
                # NOTE a SHORT is not an MTF hold and cannot be carried
                # overnight, so the 4X coverage-runway argument that
                # settled on 2.5% does not apply to this side. It is
                # matched for predictability, not because the same
                # arithmetic produced it.
                floor_high = price * (1 + HARD_STOP_FROM_ENTRY_PCT)
                if last_candle and last_candle["high"] > price:
                    seed_high = max(last_candle["high"], floor_high)
                else:
                    seed_high = floor_high
                qty = self._manual_qty(
                    self._risk_sized_qty(price, seed_high - price,
                                         symbol, security_id,
                                         cap_by_risk=False),
                    asked=asked_short_qty)
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
        # AFTER no-progress, because a position that never worked is
        # dead money rather than a finished move, and the two would
        # otherwise both claim the same exit. This one only ever fires
        # on a WINNER whose run is over -- see _check_move_died.
        self._check_move_died(symbol, price, tick_time)

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

    def _note_slot_refusal(self, symbol, direction, cap):
        """Record a breakout refused purely because the book was full.

        THE most important row in the journal. Everything else the bot
        refuses, it refuses for a stated reason about the stock. This
        one it refuses because ten other names arrived first, which is
        an accident of timing, not a judgement.
        """
        try:
            confirmations = self._confirmation_count(symbol)
            self._note_breakout_block(
                symbol, direction,
                f"book full ({cap} positions) -- {confirmations} of 3 "
                f"confirmations behind it")
        except Exception:                                  # noqa: BLE001
            pass

    def _confirmation_count(self, symbol, closed_candle=None):
        """How many of the operator's three confirmations this setup
        carries: good results, a volume surge, and news.

            "as we are into long positions only we need some
             confirmation before entries = 1) Results (good) +
             2) Volume + 3) News"          -- operator, 29 July 2026

        USED FOR RANKING ONLY -- never to block. Measured over his own
        three sessions, requiring news or results would have refused 33
        of the 35 trades that made Rs 18,389, to capture 2 worth
        Rs 2,986. Per trade the confirmed ones paid 2.7x more, which is
        why it ranks; two data points is why it does not gate.

        Volume already gates on its own, separately.
        """
        try:
            reason = self._capture_reason(symbol) or {}
            count = 0
            if (reason.get("results_grade") or "") in ("STRONG", "GOOD"):
                count += 1
            if reason.get("news_kind") or reason.get("filing_kind"):
                count += 1
            multiple = self._volume_multiple(symbol, closed_candle) \
                if closed_candle is not None else None
            if multiple and multiple >= VOLUME_SURGE_MULT:
                count += 1
            return count
        except Exception:                                  # noqa: BLE001
            return 0

    def _weakest_holder_for_rotation(self):
        """The open position with the LOWEST trend strength in its own
        direction -- the stalling laggard a stronger breakout should be
        allowed to evict. Returns (symbol, strength) or None if no open
        position has usable ranking data. A winning runner has high
        strength and is never selected here."""
        weakest = None
        for sym, pos in self.open_positions.items():
            # 2026-07-29: skip what the bot is not allowed to close.
            #
            # Found by walking the operator through today's book. At
            # 10:19 the ten open positions ranked like this:
            #
            #     CUB        YOU   -2.26%   <- weakest
            #     INFY       YOU   +0.31%
            #     MOBIKWIK   BOT   +0.45%   <- first the bot may touch
            #     ...
            #     EPACKPEB   BOT   +2.70%
            #
            # The weakest was HIS. This method used to return it anyway,
            # _maybe_rotate_out then hit the manual-position guard and
            # returned False -- so rotation was dead for the ENTIRE book
            # for as long as one of his trades happened to be the
            # laggard. CUB was the weakest from 09:30 onward, so that
            # would have been all day.
            #
            # A protection meant to keep his positions safe was quietly
            # disabling a completely separate feature. Skip and keep
            # looking; MOBIKWIK is the honest answer.
            if not self._can_rotate_out(sym):
                continue
            s = self._symbol_strength(sym, pos.get("direction", LONG))
            if s is None:
                continue
            if weakest is None or s < weakest[1]:
                weakest = (sym, s)
        return weakest

    def _can_rotate_out(self, symbol):
        """True if the bot is allowed to give this position's slot away.

        Quiet check -- unlike _bot_may_close it raises no alert, because
        merely CONSIDERING a position for rotation and rejecting it is
        not an event the operator needs to read about. The alert belongs
        at the point of an actual attempted close.
        """
        if not MANUAL_POSITIONS_BOT_MAY_NOT_CLOSE:
            return True
        return not self._is_manual_position(symbol)

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

    def _capture_reason(self, symbol, on_date=None):
        """What was KNOWN about this stock at the moment of entry.

        The learning loop had four columns -- sector, hour, relative
        strength, regime -- every one of them price context. It could
        answer "do metals breakouts at 10am work", the price-and-volume
        question the operator has already rejected, and could NEVER
        answer the one he cares about:

            "no info why gaining = no entry at all"

        Six months of trades could not tell an ORDER_WIN entry from a
        BROKER upgrade, or a STRONG results grade from a MIXED one,
        because none of it was recorded.

        Returns a dict stamped onto the position. Never raises -- a
        bookkeeping lookup must not be able to block a trade.
        """
        out = {"news_kind": None, "filing_kind": None,
               "results_grade": None, "sector_move": None,
               "days_since_results": None, "had_reason": 0,
               "reason_summary": None}
        parts = []
        # ---- TWO NEWS SOURCES, AND THE JOURNAL SAW THE THIN ONE ----
        #      19 August 2026.
        #
        #     "fix the news_kind gap"
        #
        # 13,174 of 13,272 recorded signals carried no news_kind, so
        # the whole "news predicts" half of his thesis was
        # unmeasurable. The cause was not a missing feed -- it was two
        # of them:
        #
        #   self.news_feed          RSS headlines, symbol-resolved
        #   data/stock_events.db    the PRO Telegram channels,
        #                           15,289 events across 1,727 symbols
        #
        # core/why_moving.py reads the SECOND to build the sentence on
        # his alert. This function read only the FIRST. So on
        # 19 August the RAILTEL alert quoted a Rs 166.80 crore EPFO
        # work order -- straight out of stock_events -- while the row
        # recorded for that same signal said news_kind = NULL.
        #
        # The alert and the record disagreed about whether the stock
        # had news at all, which is the worst possible shape: the
        # thing he reads says yes, and the thing that would prove it
        # says no.
        #
        # RSS FIRST, still: it carries a stance the channels do not.
        # The channel event fills in only when RSS has nothing, so
        # nothing that already worked changes.
        try:
            if self.news_feed is not None:
                item = self.news_feed.for_symbol(symbol)
                if item:
                    out["news_kind"] = item.get("kind")
                    parts.append(f"news:{item.get('kind')}")
        except Exception:                                  # noqa: BLE001
            pass

        # ---- A WHOLE SECTOR MOVING IS ITSELF THE EVENT ----
        #      20 August 2026.
        #
        #     "if complete sector is being rallied then something is
        #      happening underlying right?"
        #
        # On 20 August ten sugar names ran 7-17% together and every
        # one was refused for "no event behind it" -- MAGADSUGAR on
        # FIFTEEN times its normal volume. Each name individually had
        # no filing, and nothing ever asked about the group.
        #
        # Measured before arming: six or more members co-moving gives
        # a next-session excess of +0.925 against a +0.550 control of
        # any lone 5% mover. At FOUR members it is +0.526 -- nothing.
        # See core/sector_map.co_moving() for the table.
        #
        # A REASON, satisfying "no event, no trade". Not a score.
        sector_move = self._sector_co_move_reason(symbol)
        if sector_move:
            out["sector_move"] = sector_move
            parts.append(f"sector:{sector_move}")

        if out["news_kind"] is None and not out.get("sector_move"):
            # on_date is the caller's clock -- a replay of a past
            # morning must not read events that had not happened yet.
            channel = self._channel_event_kind(symbol, on_date)
            if channel:
                out["news_kind"] = channel
                parts.append(f"news:{channel}")
        try:
            if self.announcements is not None:
                filing = self.announcements.for_symbol(symbol)
                if filing:
                    out["filing_kind"] = filing.get("kind")
                    parts.append(f"filed:{filing.get('kind')}")
        except Exception:                                  # noqa: BLE001
            pass
        # ==========================================================
        # THE PUBLISHED CHIP FIRST.  10 August 2026.
        # ==========================================================
        # Monday's session recorded 1,191 signals and NOT ONE carried a
        # grade -- while Row 1 held 24 graded stocks all morning.
        #
        #     KNACK       EXCELLENT   grade_for() -> None
        #     UNIVCABLES  GREAT       grade_for() -> None
        #     SKYGOLD     GOOD        grade_for() -> None
        #
        # grade_for() computes its own grade from parsed QoQ/YoY numbers
        # in core/quarterly_results.py. Those numbers exist for a small
        # minority of stocks, so it answers None for almost everything
        # -- and the whole results strategy never reached the signal
        # path. Every one of Monday's 1,191 signals was a bare ORB
        # breakout with no reason attached.
        #
        # This is the SAME disconnect I fixed in results_gate.block_
        # reason() on 9 August and did not follow through to here: two
        # sources for one question, and the weaker one wired in.
        #
        # The chip is what Earnings Pulse actually published, read from
        # the same place Row 1 reads it. The computed grade is still
        # consulted when there is no chip, so nothing is lost.
        try:
            if self.results_gate is not None:
                grade = None
                published = getattr(self.results_gate, "_published_grade", None)
                if published is not None:
                    grade = published(symbol)
                if not grade:
                    grade = self.results_gate.grade_for(symbol)
                if grade:
                    out["results_grade"] = grade
                    parts.append(f"results:{grade}")
        except Exception:                                  # noqa: BLE001
            pass
        # ---- THE COLUMN THAT WAS NEVER FILLED. 16 August 2026. ----
        #
        #     "measure it against trade_memory first"
        #
        # He asked whether a catalyst should stay valid for more than
        # one session -- the TVSMOTOR question. trade_memory has the
        # exact column for it, days_since_results, and it is NULL on
        # all 134 rows, because this dict has hardcoded None since it
        # was written. So the question could not be answered from the
        # bot's OWN trades and had to be proxied with price moves
        # across 715 stored catalysts instead.
        #
        # A proxy is not the same measurement. The bot buys intraday
        # on a breakout with a 1.8-3% stop and trails; "buy the close,
        # hold five days" is a different trade. Filling this in means
        # the next time the question comes up it can be answered on
        # real fills.
        #
        # core/runup.py's reported_on() already does the lookup and is
        # time-bounded ("results_date <= ?"), so it cannot see a result
        # published after the moment being asked about.
        try:
            from datetime import date as _date

            from core import runup
            when = self.clock().date() if callable(
                getattr(self, "clock", None)) else _date.today()
            # within_days=180, not runup's default 12. That default is
            # the RUN-UP window -- there is no run-up into a result
            # three weeks old -- and it is right for that question and
            # wrong for this one. TVSMOTOR reported 21 July; on 14
            # August "24 days since results" is a real answer and the
            # 12-day default would have written None again.
            reported = runup.reported_on(symbol, on_date=when,
                                         within_days=180)
            if reported:
                got = reported if isinstance(reported, _date) else None
                if got is None:
                    from datetime import datetime as _dt
                    got = _dt.fromisoformat(str(reported)[:10]).date()
                out["days_since_results"] = (when - got).days
        except Exception:                                  # noqa: BLE001
            pass                       # bookkeeping must never block a trade

        out["had_reason"] = 1 if parts else 0
        out["reason_summary"] = ", ".join(parts)[:160] or None
        return out

    def _alert_evidence(self, symbol):
        """The EVIDENCE behind this break, as a readable clause.

            "stocks raising with underlying evidence = news / results /
             orders / anything that supports with volume must have
             added advantage rather than normal breakout stocks"
                                -- operator, 18 August 2026

        Returns "" when there is nothing to add, so the sentence reads
        the same as before for anything this cannot enrich. Never
        raises and never blocks: an alert with no evidence line is
        worse than one with it, and both are far better than an
        exception on the trading loop.

        Nothing is computed here. _capture_reason() has gathered this
        since 28 July -- to STAMP on the position afterwards for
        core/trade_memory.py -- and the alert has been discarding it
        and printing the mechanism name instead.
        """
        try:
            got = self._capture_reason(symbol) or {}
        except Exception:                                  # noqa: BLE001
            return ""
        summary = str(got.get("reason_summary") or "").strip()
        if not summary:
            return "  [PRICE ONLY -- no event behind it]"
        return f"  [EVIDENCE: {summary}]"

    def _sector_co_move_reason(self, symbol):
        """Is this stock's whole group moving today? A sentence or None.

        Reads the circuit poller's snapshot -- the same ~1,300-symbol
        picture the gainers table is drawn from -- so it costs no
        extra network and cannot disagree with the board about what
        moved.

        Never raises: this runs on the reason path and a broken lookup
        must refuse a reason, not stop a tick.
        """
        try:
            from core.rules import SECTOR_CO_MOVE_IS_A_REASON
            if not SECTOR_CO_MOVE_IS_A_REASON:
                return None
            snapshot = ((self.circuit_monitor.get_snapshot() or {})
                        if self.circuit_monitor is not None else {})
            if not snapshot:
                return None
            moves = {}
            for name, row in snapshot.items():
                try:
                    last = float((row or {}).get("last_price") or 0)
                    prev = float((row or {}).get("prev_close") or 0)
                except (TypeError, ValueError):
                    continue
                if last > 0 and prev > 0:
                    moves[str(name).upper()] = (last - prev) / prev * 100.0
            if not moves:
                return None
            from core import sector_map
            return sector_map.co_move_reason(symbol, moves)
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[SECTOR] co-move check failed "
                       f"({type(exc).__name__}).")
            return None

    def _channel_event_kind(self, symbol, when=None):
        """The PRO channel event behind this stock today, or None.

        Reads data/stock_events.db through core/why_moving.py's own
        cached reader -- the SAME path that builds the sentence on his
        alert. One reader, one cache, one answer: a second lookup here
        would drift from the alert within a week and the record would
        contradict the message again.

        ---- THE STORE IS UTC AND THE MARKET IS IST. ----

        stock_events writes "2026-08-18T13:41:11+00:00". That is
        19:11 IST on the 18th -- an EVENING filing, made after the
        close, and it is precisely the kind that drives the next
        morning. RAILTEL's Rs 166.80 crore EPFO order carried that
        exact stamp and the 19 August alert quoted it.

        So a same-calendar-day filter does not merely miss a few
        events, it misses THE ONES THAT MATTER MOST -- everything
        filed between the close and midnight UTC. The first version of
        this method had that filter and returned None for RAILTEL on
        the morning RAILTEL was the pick of the day.

        The window is therefore the trading day PLUS everything from
        the previous session's close onward, read in IST.

        Anything older is excluded: an order win from three weeks ago
        is not why this stock is breaking out this morning, and
        stamping it on the signal would make the column look full
        while meaning nothing.

        Never raises. This runs on the tick path and a journal that
        cannot be written is better than a tick that does not happen.
        """
        try:
            from core.why_moving import _events_for

            rows = _events_for(symbol) or []
        except Exception:                                  # noqa: BLE001
            return None

        now = when or datetime.now()
        if not isinstance(now, datetime):
            try:
                now = datetime.strptime(str(now)[:10], "%Y-%m-%d")
            except Exception:                              # noqa: BLE001
                now = datetime.now()
        # From yesterday's close (15:30 IST) to now.
        cutoff = (now - timedelta(days=1)).replace(
            hour=15, minute=30, second=0, microsecond=0)

        best = None
        for row in rows:
            try:
                raw = str((row or {}).get("at") or "")
                kind = str((row or {}).get("kind") or "").strip().upper()
            except Exception:                              # noqa: BLE001
                continue
            if not kind or len(raw) < 19:
                continue
            try:
                stamped = datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S")
                if raw.endswith("+00:00") or raw.endswith("Z"):
                    stamped += timedelta(hours=5, minutes=30)   # IST
            except Exception:                              # noqa: BLE001
                continue
            if stamped < cutoff or stamped > now + timedelta(minutes=5):
                continue
            # MACRO is market-wide -- it is not this stock's news, and
            # counting it would fill the column with the same word on
            # every symbol that moved.
            if kind in ("MACRO", "MARKET_ANSWER", "AI_VERDICT"):
                continue
            best = kind
            break
        return best

    def _no_reason_refusal(self, symbol):
        """Why this stock has no event behind it today, or None if it
        has one.

        ---- THE RULE THAT WAS ONLY IN THE OTHER LANE. 12 Aug 2026. ----

            "Opportunity Trader Bot = only trades when an event or real
             opportunity arised in markets, NEVER in to random stocks"

        BOT_SPEC.md has said this since it was written -- entry rule 2,
        "a written reason exists: no mechanism, no trade". Two paths in
        this bot can reach _enter(), and only one of them asked:

            ranker -> auto_entry   refused a stock with no mechanism
            engine ORB breakout    never looked

        _capture_reason() below has gathered exactly this evidence since
        28 July -- but only to STAMP it on the position afterwards, for
        core/trade_memory.py to learn from. The engine was recording why
        it bought and never requiring that there be a why. On 5 August
        that lane fired 1,047 signals; on 10 August 1,191 signals
        carried no grade at all.

        So this asks the same question the same way, one moment earlier,
        and refuses instead of noting.

        NARROWER THAN THE RANKER, ON PURPOSE. See rules.ENGINE_REQUIRE_
        REASON. The ranker can see volume and may accept an unexplained
        mover carrying 2.5x its normal turnover. This lane sees a price
        leaving a range, so a named event is the whole of its evidence.

        ---- "NO EQUIPMENT" IS NOT "NO NEWS". ----

        An empty feed and an ABSENT feed are different answers and this
        must not confuse them:

            wired, and silent      nobody published    REFUSE
            not wired at all       cannot answer       allow, and SAY SO

        The second case is tests, backtests and dashboard_preview, none
        of which attach a news reader. Refusing there would not make
        those safer, it would just make every one of them measure this
        gate instead of what it was written to measure.

        But it is also what a broken startup looks like in production --
        main.py builds every one of these inside a try/except -- so it
        is a WARNING, once, not a silence. A bot that cannot read a
        reason should not be quietly trading as if it could.
        """
        from core.rules import ENGINE_REQUIRE_REASON
        if not ENGINE_REQUIRE_REASON:
            return None

        if (self.news_feed is None and self.announcements is None
                and self.results_gate is None):
            if not self._warned_no_reason_sources:
                self._warned_no_reason_sources = True
                warn("[NO_REASON] No news feed, no filings watcher and no "
                     "results gate are wired to this engine, so 'does this "
                     "stock have an event today' cannot be answered and "
                     "the rule is not being applied. Expected in tests and "
                     "replays. IN A LIVE SESSION THIS MEANS THE BOT IS "
                     "BUYING BREAKOUTS WITH NO REASON BEHIND THEM.")
            return None

        reason = self._capture_reason(symbol) or {}
        if reason.get("had_reason"):
            return None
        return ("no event behind it -- no filing, no news and no "
                "published grade for this stock today. The bot only "
                "trades a reason")

    def _record_breakout_signal(self, symbol, direction, closed_candle,
                                tick_time=None):
        """Put a structural signal on the Fresh Breakouts panel.

        Called at the TOP of _try_structural_entry, before any gate, so
        the panel shows what the bot SAW -- not the smaller set it was
        allowed to act on. Fail-silent: a panel must never break a tick.
        """
        try:
            orb_range = self.orb_engine.get_range(symbol) or {}
        except Exception:                                  # noqa: BLE001
            orb_range = {}

        if self.breakout_feed is not None:
            try:
                self.breakout_feed.record(
                    symbol, direction,
                    price=closed_candle.get("close"),
                    orb_high=orb_range.get("high"),
                    orb_low=orb_range.get("low"),
                    tick_time=tick_time,
                )
            except Exception:                              # noqa: BLE001
                pass

        # 2026-07-29: the panel above is memory only and dies at 15:30.
        # This is the same event written to disk, so the question the
        # operator asked -- "real movers are ignored" -- can finally be
        # measured instead of argued. See core/signal_journal.py.
        if self.signal_journal is not None:
            try:
                # The three confirmations the operator named on 29 July
                # -- results, volume, news -- recorded on EVERY signal
                # and gating on none of them here. Only volume gates,
                # further down. The rest earn a vote only once two
                # weeks of these rows say they deserve one.
                reason = self._capture_reason(symbol) or {}
                attempt = None
                if self.breakout_feed is not None:
                    try:
                        attempt = self.breakout_feed.attempt_for(
                            symbol, direction)
                    except Exception:                      # noqa: BLE001
                        attempt = None
                self.signal_journal.record(
                    symbol, direction,
                    break_price=closed_candle.get("close"),
                    orb_high=orb_range.get("high"),
                    orb_low=orb_range.get("low"),
                    open_positions=len(self.open_positions),
                    when=tick_time,
                    volume_mult=self._volume_multiple(symbol, closed_candle),
                    news_kind=reason.get("news_kind"),
                    filing_kind=reason.get("filing_kind"),
                    results_grade=reason.get("results_grade"),
                    attempt=attempt,
                    sector=(self.sector_monitor.sector_of(symbol)
                            if self.sector_monitor is not None else None),
                )
            except Exception:                              # noqa: BLE001
                pass

    def _note_breakout_block(self, symbol, direction, reason):
        """Attach the reason a breakout was refused, so the operator can
        see the disagreement instead of guessing at a silence."""
        if self.breakout_feed is not None:
            try:
                self.breakout_feed.note_block(symbol, direction, reason)
            except Exception:                              # noqa: BLE001
                pass
        if self.signal_journal is not None:
            try:
                self.signal_journal.record(symbol, direction,
                                           refused_why=reason)
            except Exception:                              # noqa: BLE001
                pass

    def _day_turnover_cr(self, symbol):
        """This symbol's traded value TODAY, in crores, or None.

        Feeds trading/slippage.py. Same circuit_monitor REST snapshot
        that _has_liquidity() already reads -- turnover = last price x
        day volume. None means "unknown", which slippage deliberately
        treats as THIN.
        """
        if self.circuit_monitor is None:
            return None
        try:
            info = (self.circuit_monitor.get_snapshot() or {}).get(symbol)
            if not info:
                return None
            price = info.get("last_price") or info.get("ltp")
            volume = info.get("volume")
            if not price or not volume:
                return None
            return (float(price) * float(volume)) / 1e7
        except Exception:                                  # noqa: BLE001
            return None

    def _live_price_for_order(self, symbol):
        """The CURRENT traded price, for the pre-send drift check.

        trading/live_execution.py refuses to send a market order if the
        price has run away from the one the operator saw when he
        clicked. It cannot do that without a live price, and it treats
        None as "refuse", not as "assume fine" -- deliberately, because
        a market order cannot be un-filled.

        The tick feed FIRST: it is the freshest thing on the machine and
        it is what the dashboard was showing when the button was
        pressed. The circuit monitor's REST snapshot is the fallback --
        it is seconds old rather than milliseconds, which is still far
        better than blind.
        """
        if self.market_data is not None:
            try:
                price = self.market_data.get_latest_price(symbol)
                if price:
                    return float(price)
            except Exception:                              # noqa: BLE001
                pass
        if self.circuit_monitor is not None:
            try:
                info = (self.circuit_monitor.get_snapshot() or {}).get(symbol)
                price = (info or {}).get("last_price") or (info or {}).get("ltp")
                if price:
                    return float(price)
            except Exception:                              # noqa: BLE001
                pass
        return None

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

        # TIME GUARD, added 2026-07-27 -- operator-found live on TBZ.
        #
        # The quote we widen from carries the exchange's DAY high/low. At
        # 09:30 that IS the opening range, so the reconcile is correct.
        # One minute later it is not: it is the day's range so far, and
        # widening the "opening range" to it is simply wrong.
        #
        # `self._orb_reconciled` is an in-memory set, so it is EMPTY
        # after a restart -- and the bot then re-reconciled all 689
        # symbols against a day high that had been running for an hour.
        # TBZ, from that day's log:
        #
        #   09:30:16  [ORB_FIX] TBZ 263.80/260.84 -> 263.80/260.39  correct
        #   10:36:10  [ORB_FIX] TBZ 263.80/260.39 -> 270.00/260.39  WRONG
        #
        # 263.80 is what the exchange itself shows for 09:15-09:30. The
        # 10:36 pass -- one minute after a restart -- dragged the range
        # high up by Rs 6.20 to wherever the stock had since traded.
        #
        # The consequence is worse than one bad number: after any
        # restart past 09:30, EVERY symbol's breakout level becomes its
        # running day high, so the bot stops looking for opening-range
        # breaks and starts demanding fresh day highs. That is a much
        # harder bar, and it is why so little fired after the 10:35
        # restart that day. TBZ eventually entered at 274.15 instead of
        # around 264.
        #
        # ORB ranges are restored from core/state_store.py on restart
        # (the startup line reports "689 ORB range(s)"), already
        # reconciled from the first pass -- so skipping here loses
        # nothing and protects what is already correct.
        now_t = datetime.now().time()
        if now_t > _ORB_RECONCILE_DEADLINE_T:
            self._orb_reconciled.add(symbol)     # never try again today
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

        # The range now comes from the exchange, so a feed gap while it
        # was being built no longer matters -- that doubt is exactly
        # what the unreliable flag records, and it has been answered.
        # 2026-07-28: the flag was set on 607 of 666 symbols and the bot
        # took zero automated entries all day, many of them on ranges
        # that had already been reconciled and were known-good.
        if self.market_data is not None and \
                self.market_data.clear_orb_window_unreliable(symbol):
            decision(
                f"[ORB_FIX] {symbol} is tradeable again -- its range was "
                f"rebuilt from the exchange's own high/low, so the feed "
                f"gap that flagged it no longer applies."
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

    def _position_has_event(self, symbol):
        """Is this position standing on a real catalyst?

            "trailing in good moving stocks (strong supported events)"
                                -- operator, 19 August 2026

        core/trailing_stop.py widens the leash when this is True,
        because a catalyst is a reason to expect continuation and a
        pause inside one is not a failure.

        The answer comes from _capture_reason() -- the same evidence
        the alert prints and core/trade_memory.py stores -- so a
        position the board calls evidence-backed is trailed as one.
        A second definition of "event" living here would drift from
        that one within a week.
        """
        try:
            return bool((self._capture_reason(symbol) or {}).get(
                "had_reason"))
        except Exception:                                  # noqa: BLE001
            return False

    def _hard_stop_pct(self, symbol):
        """How far below entry this stock's stop belongs, as a FRACTION.

        core/atr.daily_atr_pct() measures the stock's ordinary daily
        range from the bhavcopy store the nightly chain already fills
        -- no network call, nothing on the tick path.

        Bounded by core/rules.py at both ends. A stock whose daily
        range reads 0.2% must not be given a 0.24% stop, and one
        reading 9% must not be given a 10.8% one.

        ---- TWO CONSTANTS SHARE A NAME AND DISAGREE ON UNITS ----
        config.MIN_STOP_DISTANCE_PCT is 0.01, a FRACTION.
        core/rules.MIN_STOP_DISTANCE_PCT is 0.75, a PERCENT.
        They are imported here under different names on purpose --
        reading rules' 0.75 as a fraction would put the floor at 75%
        of price, which is not a stop, it is a donation.

        Falls back to HARD_STOP_FROM_ENTRY_PCT when the range cannot
        be measured. A stop derived from a volatility nobody measured
        is worse than an honestly flat one.
        """
        # ---- ONE WIDTH, AND HE PICKED IT. 29 August 2026. ----
        # Above the VOLATILITY_SCALED_STOP branch on purpose: on the
        # event setups this bot now trades, 2.0 x daily ATR cleared
        # the 6% ceiling for 81 of 101 names, so the scaling was
        # already flat. See config.FIXED_STOP_PCT for the measurement.
        # None there restores the ATR rule and this returns nothing.
        if FIXED_STOP_PCT:
            return float(FIXED_STOP_PCT) / 100.0
        if not VOLATILITY_SCALED_STOP:
            return HARD_STOP_FROM_ENTRY_PCT
        try:
            daily = daily_atr_pct(symbol)
        except Exception:                                  # noqa: BLE001
            daily = None
        if not daily or daily <= 0:
            return HARD_STOP_FROM_ENTRY_PCT
        wanted = DAILY_ATR_STOP_MULT * float(daily)
        wanted = max(STOP_FLOOR_PCT, min(STOP_CEILING_PCT, wanted))
        return wanted / 100.0

    def _is_at_the_days_extreme(self, symbol, direction, closed_candle):
        """Is this close MAKING today's high, or sitting under one the
        stock already printed and walked back from?

        ==========================================================
            "bot alert system unable to identify the difference of
             fresh breakout or fall backs"
                                -- operator, 18 August 2026
        ==========================================================

        THE DIFFERENCE FROM _is_still_trending(). That one asks where
        price sits inside the day RANGE and is deliberately generous
        (0.65) -- it is a "has it rolled over" check. This asks a
        narrower question that a range position cannot answer: a stock
        can sit in the top third of its range and still be a full
        percent under a high it made an hour ago. NAVINFLUOR was at
        0.60 of its range and 0.72% off its high, and 0.72% off the
        high is what he objected to.

        THE HIGH COMES FROM THE FEED, not from the ORB and not from
        the circuit poller. core/tick_ohlc.py carries Dhan's own
        day OHLC and is updated on every tick, so it cannot lag the
        candle being judged. The ORB range is fixed at 09:30 by
        definition and is exactly what made a stale level look fresh.

        FAILS OPEN. No tick data, no high, a zero high -- allow, and
        let the gates that CAN answer decide. A missing reading is not
        a refusal, the same posture as every other gate on this path.
        """
        if not closed_candle:
            return True
        try:
            close = float(closed_candle.get("close") or 0)
        except (TypeError, ValueError):
            return True
        if close <= 0:
            return True

        row = tick_ohlc.of(symbol) or {}
        extreme_key = "high" if direction == LONG else "low"
        try:
            extreme = float(row.get(extreme_key) or 0)
        except (TypeError, ValueError):
            return True
        if extreme <= 0:
            return True

        off = abs((close - extreme) / extreme) * 100.0
        if off <= BREAKOUT_MAX_OFF_HIGH_PCT:
            self._unblock(symbol, direction)
            return True

        # ---- THE PROXY DEFERS TO THE MEASUREMENT. 1 September 2026. ----
        #
        #     "we created more reliable sources to enter rather than
        #      blank coating some percentages of move"
        #                                          -- the operator
        #
        # He is right, and this gate is the clearest case of it. It was
        # written on 18 August because the reason source of the day --
        # STRUCTURAL_LONG_BREAKOUT -- measured the break against the
        # 09:15-09:30 opening range, a level frozen at 09:30 and never
        # updated, so the third re-cross of a dead level read as fresh.
        # The signal could not tell a live move from an old one, so this
        # demanded the price be glued to the high instead. It is a fence
        # around a broken signal, not a rule about markets.
        #
        # WHAT IT ACTUALLY ASKS. "Is the move still going?" -- inferred
        # from where the price happens to sit. core/order_flow.py's
        # still_buying() answers that same question by measurement:
        # cumulative delta positive (buyers ahead today) AND higher than
        # fifteen minutes ago (still adding), on a real bid and ask. Its
        # own docstring is this same objection, from PRECWIRE on 31
        # August -- refused 518 times on where its price sat while
        # buyers took 63% of every share traded all session.
        #
        # MEASURED ON THE 41 STOCKS THIS GATE REFUSED ON 1 SEPTEMBER:
        #
        #     16   buyers still winning   <- this gate was wrong
        #     25   buyers had stopped     <- this gate was right
        #      0   flow could not answer  <- this gate keeps the word
        #
        # So it is not a rubber stamp: it overturns 16 and BACKS 25.
        # BEML was refused at 13:22 for sitting 1.13% under its high
        # while its cumulative delta was at 100% of the day's peak.
        # SSWL passed the volume surge at 49x and still fails here,
        # because its delta is negative -- sellers have won it all day.
        #
        # IT ONLY REMOVES A VETO. Every other gate is untouched, and
        # long-only is untouched. still_buying() returns None on a thin
        # book -- "a guess must not overrule a gate" -- and None does
        # not overrule anything here either.
        if direction == LONG:
            check = getattr(self, "buying_check", None)
            if check is not None:
                try:
                    reading = check(symbol)
                except Exception:                          # noqa: BLE001
                    reading = None
                if reading and reading.get("still_buying"):
                    self._unblock(symbol, direction)
                    when_it_changes(
                        f"flow-overrules-{symbol}-{direction}",
                        f"[FLOW] {symbol} is {off:.2f}% under today's "
                        f"{extreme_key}, but the buyers are still "
                        f"winning it -- delta {reading.get('delta'):,.0f} "
                        f"against {reading.get('was'):,.0f} fifteen "
                        f"minutes ago, {reading.get('of_peak')}% of the "
                        f"day's peak. The price gate does not get the "
                        f"last word.",
                        how=decision)
                    return True

        # REFUSED FOR NOW, NOT FOR THE DAY. Buyers who have stopped at
        # 12:34 may be back at 14:00, and until today this line settled
        # the stock for the session -- see FOR_NOW.
        already = _is_provisional(
            self.entry_blocked.get(symbol, {}).get(direction))
        self._block_entry(
            symbol, direction,
            FOR_NOW +
            f"not a fresh breakout -- {close:.2f} is {off:.2f}% below "
            f"today's {extreme_key} of {extreme:.2f}, which it has "
            f"already made and come back from (limit "
            f"{BREAKOUT_MAX_OFF_HIGH_PCT}%), and the buyers are not "
            f"still winning it either",
            say=not already)
        return False

    def _unblock(self, symbol, direction):
        """Drop a provisional block once the stock clears the gate that
        set it, so the panel never shows a refusal that has passed."""
        held = self.entry_blocked.get(symbol)
        if held and _is_provisional(held.get(direction)):
            held.pop(direction, None)
            if not held:
                self.entry_blocked.pop(symbol, None)

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

    def _position_ceiling(self):
        """How many positions the CASH allows -- see core/capital.py.

        ==========================================================
        A COUNT WAS THE WRONG CONTROL. 8 August 2026.
        ==========================================================

            "we prepared the bot to search for better trading
             opportunites not to keep the door shut after 3 positions
             irrespective of pnl"

        MAX_OPEN_POSITIONS = 3 was written on 7 August for ONE session
        -- "2/3 is enough today, i'll trade cautiously" -- and never
        came off. Replaying 4, 6 and 7 August, all three seats filled
        by 09:30 every single day and the bot then went blind for six
        hours. STOVEKRAFT made its high at 12:12 with the book full
        since 09:30.

        core/capital.py was written the same week to fix exactly this
        and was imported by nothing. His rule, in his words:

            "keep at least 1 lakh free cash & positions can be build
             on remaining"

        So the ceiling is cash: (capital - Rs 1 lakh) / Rs 30,000.
        At Rs 4.31 lakh that is 11, not 3.

        MAX_OPEN_POSITIONS survives as the FALLBACK for when the
        balance cannot be read. A broker timeout must not silently
        open the book -- it falls back to the cautious number.

        ---- MEASURED BEFORE IT WAS ARMED. 8 August 2026. ----
        Replaying 3-5 August through core/select.py with the 1:1 lock:

            3 slots     9 trades   11% win   Rs -10,715
            11 slots   33 trades   24% win   Rs -26,018

        Opening the book did not find better opportunities. It found
        eight times as many of the same ones. The hit rate is 24% and
        a 2:1 payoff needs 33% to break even, so every extra seat is a
        multiplier on a losing edge -- and the TOP-ranked three were
        the worst of the eleven, which says the ranking is not sorting
        by anything predictive yet.

        So the gate is built, tested and OFF. It turns on the day the
        selector shows an edge, not before. He asked for a bot that
        searches for better opportunities; eleven seats on a 24%
        selector is not that, it is the same bot losing faster.
        """
        if not ENABLE_CASH_SIZED_BOOK:
            return MAX_OPEN_POSITIONS
        # NO PORTFOLIO AT ALL is not a money question -- cash sizing is
        # simply not wired in that configuration, and this falls back to
        # the count exactly as it did before cash sizing existed. In
        # production main.py always passes one; tests often do not, and
        # a test harness with no portfolio must not be read as an empty
        # account.
        if self.portfolio is None:
            return MAX_OPEN_POSITIONS
        capital = getattr(self.portfolio, "starting_capital", None)

        # ---- NO MONEY, NO TRADES. 31 August 2026. ----
        #
        #     "no capital (money) = no trades in real mode right. thats
        #      as simple as that whats so complex in that?"
        #
        # It is that simple, and the code was not. It read
        #
        #     if not capital: return MAX_OPEN_POSITIONS
        #
        # so a balance of zero, a balance of None and a broker timeout
        # all came back as THREE SEATS -- opening the book on money the
        # bot could not confirm exists, silently.
        #
        # I then replaced it with three branches: zero means no seats,
        # unreadable falls back to three, unparseable falls back to
        # three. He read that and said it is one rule.
        #
        # He is right. If the bot cannot see the money, it does not
        # know it has any, and "I could not read the balance" is not a
        # reason to trade. One rule: a positive, readable number or no
        # new positions.
        #
        # OPEN POSITIONS ARE UNTOUCHED. This decides new entries only.
        # Abandoning live positions because a balance read failed would
        # be a far worse failure than not opening another.
        try:
            cash = float(capital)
        except (TypeError, ValueError):
            cash = 0.0
        if cash <= 0:
            held_now = len(getattr(self, "open_positions", {}) or {})
            if getattr(self, "_no_cash_said", False) is not True:
                self._no_cash_said = True
                warn(f"[SLOTS] No new positions: the account reads "
                     f"{capital!r}. Holding {held_now}; those are "
                     f"unaffected.")
            return held_now
        if getattr(self, "_no_cash_said", False):
            self._no_cash_said = False
            decision(f"[SLOTS] The account reads Rs {cash:,.0f} again. "
                     f"Sizing from cash resumes.")

        try:
            from core import capital as capital_rules
            allowed = capital_rules.slots(
                capital, held=len(getattr(self, "open_positions", {}) or {}))
        except Exception as exc:                           # noqa: BLE001
            warn(f"[SLOTS] Could not size the book from cash ({exc}); "
                 f"falling back to MAX_OPEN_POSITIONS={MAX_OPEN_POSITIONS}")
            return MAX_OPEN_POSITIONS
        held = len(getattr(self, "open_positions", {}) or {})

        # ---- THE REASON WAS WRITTEN AND THROWN AWAY. 31 Aug 2026. ----
        #
        # capital.slots() returns a "why" on purpose. Its own docstring
        # says it: "never a bare number, because a refusal he cannot
        # read is a refusal he cannot act on."
        #
        # This line read .get("slots") and discarded it. So when cash
        # closes the book -- the balance dipped, or came back
        # unparseable and became 0.0 in slots() -- the bot quietly stops
        # opening positions and nothing anywhere says why. He sees a day
        # with no trades and no reason, which is the single most
        # frustrating thing this bot has done to him.
        #
        # Edge-triggered: said once when the book closes and once when
        # it reopens, never every cycle.
        seats = max(allowed.get("slots", 0) + held, 0)
        shut = seats <= held
        # Defaults to False, not None: a fresh engine with an open book
        # has nothing to announce. Starting at None made the very first
        # cycle of a normal session log "Room again", which is noise on
        # the one message that has to be worth reading.
        if shut != getattr(self, "_book_shut_by_cash", False):
            self._book_shut_by_cash = shut
            if shut:
                warn(f"[SLOTS] No room for a NEW position: "
                     f"{allowed.get('why') or 'cash sizing returned none'}. "
                     f"Holding {held}. Open positions are unaffected.")
            else:
                decision(f"[SLOTS] Room again -- "
                         f"{allowed.get('why') or f'{seats - held} free'}.")
        return seats

    def _staged_position_cap(self, effective_time):
        """
        Max concurrent positions allowed at this time of day. Never
        fill all ten seats in the opening minute -- on 2026-07-24, 11
        of 27 entries fired inside the single 09:34 minute, committing
        the whole book to whatever twitched first. Returns the cap, or
        0 once past STAGED_NO_ENTRY_AFTER.
        """
        ceiling = self._position_ceiling()
        if not self.enable_staged_entry or effective_time is None:
            return ceiling
        hhmm = effective_time.strftime("%H:%M")
        if hhmm >= STAGED_NO_ENTRY_AFTER:
            return 0
        for cutoff, cap in STAGED_POSITION_LIMITS:
            if hhmm < cutoff:
                return min(cap, ceiling)
        return ceiling

    def _already_attempted(self, symbol, direction):
        """One attempt per (symbol, direction) per day -- kills the
        re-entry whipsaw (CHENNPETRO traded 9x, CORONA 6x in a single
        session)."""
        if not self.one_trade_per_symbol:
            return False
        return direction in self._attempted_today.get(symbol, set())

    def _mark_attempted(self, symbol, direction):
        self._attempted_today.setdefault(symbol, set()).add(direction)

    def adopt_position(self, symbol, qty, direction, entry_price, stop,
                       security_id, entry_time=None):
        """Take a position HE opened into the bot's book, with a stop.

        ==========================================================
            "my goal is to stop manual trading & let the bot trade .
             do not ask me how ? thats your job"
                                    -- operator, 5 August 2026
        ==========================================================

        On the evening of 5 August the bot's own log read:

            BERGEPAINT  100 at Dhan, opened outside the bot.
                        the bot will not stop or exit it.
            DEEPAKNTR   100 ...
            MOREPENLAB 2000 ...

        About Rs 2 lakh on MTF overnight with nothing watching it.
        That came from a rule set on 3 August -- "why bot is concerned
        on user trading - thats his choice" -- which was about NAGGING
        him, not about leaving his money unprotected. He has since
        asked for the opposite.

        Once here, every existing exit applies: the trailing stop, the
        circuit guard, MOVE_DIED and square-off. Nothing new manages
        these; they simply stop being invisible to what already works.

        Deliberately NOT an entry. It places no order and changes
        nothing at the broker -- the position already exists. It only
        makes the bot aware of something he already owns.
        """
        symbol = str(symbol).upper()
        if symbol in self.open_positions:
            return False
        self.open_positions[symbol] = {
            "security_id": security_id,
            "qty": abs(int(qty)),
            "entry_price": float(entry_price),
            "sector": None,
            "rel_strength": None,
            "regime": self._last_logged_regime,
            "entry_reason": ENTRY_REASON_ADOPTED,
            "entry_time": entry_time,
            "direction": direction,
            "initial_stop": float(stop),
            "fixed_target": None,
            "stop_mode": STOP_MODE_SWING_TRAILING,
        }
        self.trailing_stop.start(symbol, float(stop), direction=direction,
                                 entry_price=float(entry_price),
                                 has_event=self._position_has_event(symbol))
        return True

    def _check_move_died(self, symbol, price, tick_time):
        """Exit a WINNING position whose move has stopped working.

        ==========================================================
            "ride untill the momentum stays - exit once it gone
             ruthlessly + repeat the process on only high setups"
                                    -- operator, core ideology
        ==========================================================

        The bot had every other exit -- stop, trail, target, circuit,
        dead money -- and none of them answer "the move is finished".
        On 5 August seventeen of nineteen positions reached neither
        stop nor target and simply sat until 15:30.

        This is the second half of his sentence. The first half, riding
        while momentum stays, is what the trailing stop already does.

        THREE CONDITIONS, ALL REQUIRED:

            1. it is IN PROFIT by at least MOVE_DIED_MIN_GAIN_R of its
               own risk -- below that it is the stop's business
            2. liveness() says "fading" against the day's extreme
            3. it is more than MOVE_DIED_OFF_EXTREME_PCT off that
               extreme

        Deliberately never fires on a losing position. Two exits
        competing for the same trade is how a stop gets quietly
        replaced by something tighter that nobody declared.
        """
        position = self.open_positions.get(symbol)
        if position is None:
            return False
        entry = position.get("entry_price")
        initial_stop = position.get("initial_stop")
        if not entry or not initial_stop:
            return False
        risk = abs(entry - initial_stop)
        if risk <= 0:
            return False

        direction = position.get("direction", LONG)
        gain = (price - entry) if direction == LONG else (entry - price)
        if gain < MOVE_DIED_MIN_GAIN_R * risk:
            return False                     # not yet the stop's peer

        extremes = {}
        if self.market_data is not None:
            try:
                extremes = self.market_data.day_extremes(symbol) or {}
            except Exception:                              # noqa: BLE001
                return False
        day_high = extremes.get("high")
        day_low = extremes.get("low")
        if not day_high or not day_low:
            return False

        from core.ranker import liveness
        state, off_extreme = liveness({
            "ltp": price, "day_high": day_high, "day_low": day_low,
            "change_pct": 1.0 if direction == LONG else -1.0,
        })
        if state != "fading":
            return False
        if off_extreme is None or off_extreme < MOVE_DIED_OFF_EXTREME_PCT:
            return False

        if not self._bot_may_close(symbol, "its move has finished"):
            return False

        extreme = day_high if direction == LONG else day_low
        decision(
            f"[MOVE_DIED] {symbol} {direction} closed at {price:.2f} -- "
            f"{off_extreme:.1f}% off the day's {extreme:.2f} and no "
            f"longer moving. Banked {gain:+.2f} per share "
            f"({gain / risk:.1f}R). Riding it further was giving it back."
        )
        self._exit(symbol, price, EXIT_REASON_MOVE_DIED, tick_time)
        return True

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

        if not self._bot_may_close(symbol, "it has not moved, to free a slot"):
            return False

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
        # ---- ROTATION IS AN ENTRY DECISION. 7 August 2026. ----
        #
        #     "why bot sold? it is not even falling"
        #     "i turn off the trading bot since morning after market
        #      opened . now didn't ON"           -- operator
        #
        # The switch was OFF all day and the bot still sent five real
        # SELL orders. Two were rotations:
        #
        #     10:58  SELL KALYANKJIL  500 @  622.30   ROTATED_OUT
        #     10:58  SELL HEROMOTOCO   50 @ 5792.00   ROTATED_OUT
        #     BUYS that day: 0
        #
        # Exits deliberately ignore alert_only so a stop always
        # protects him whether or not new buying is armed. That is
        # right. But ROTATION IS NOT AN EXIT -- it is "sell the weakest
        # to buy something better", an ENTRY decision with a sell
        # attached. The sell rode out with the exits; the buy was
        # correctly blocked by the switch.
        #
        # With trading OFF, rotation is therefore GUARANTEED to be a
        # one-legged trade. It took him out of two positions for a
        # purchase the bot was never allowed to make.
        #
        # No switch, no rotation. A full book simply refuses.
        if getattr(self, "alert_only", True):
            if not getattr(self, "_rotation_off_logged", False):
                self._rotation_off_logged = True
                decision(
                    "[ROTATE] Bot trading is OFF -- no rotation. A full "
                    "book refuses new signals rather than selling a "
                    "holding for a buy that cannot happen.")
            return False

        # Hard cap on churn. Each swap pays slippage and charges, and
        # sells a position the new no-trail rule was meant to let run.
        if self._rotations_today >= ROTATION_MAX_PER_DAY:
            if not self._rotation_cap_logged:
                self._rotation_cap_logged = True
                decision(
                    f"[ROTATE] Daily swap limit reached "
                    f"({ROTATION_MAX_PER_DAY}). No more slot rotation "
                    f"today -- a full book now simply refuses, and every "
                    f"refusal is journalled.")
            return False

        challenger_strength = self._symbol_strength(challenger, direction)
        if challenger_strength is None:
            return False

        # 2026-07-29: a challenger carrying the operator's confirmations
        # -- good results, news -- needs less of a trend edge to take a
        # laggard's seat. RANKING, not gating: a confirmed setup cannot
        # enter on confirmations alone, it still has to be a stronger
        # breakout. It just does not have to be as MUCH stronger.
        edge = ROTATION_MIN_STRENGTH_EDGE
        confirmations = self._confirmation_count(challenger)
        if confirmations:
            edge = ROTATION_MIN_STRENGTH_EDGE / (1 + confirmations)
        weakest = self._weakest_holder_for_rotation()
        if weakest is None:
            return False
        w_sym, w_strength = weakest

        # ---- A POSITION GETS TIME TO WORK. 23 August 2026. ----
        #
        # Rotation had no minimum holding period at all, which is how
        # 21 August produced this:
        #
        #     12:49:37  PAPER BUY  CDSL 47 @ 1390.80
        #     12:49:48  CDSL rotated OUT for URBANCO
        #
        # Eleven seconds. Median hold across every ROTATED_OUT trade on
        # record was 2.3 minutes, 20% of them won, and they lost
        # Rs 1,860 between them. A swap decided that fast is not an
        # upgrade, it is noise crossing a threshold.
        #
        # The seat-timing problem this mechanism exists for is real and
        # slow: SOLARA reached rank 1 at 10:24 on 20 August and closed
        # +16.4%, an HOUR after the seats were filled. Forty-five
        # minutes is long enough that a genuine hand-over survives it
        # and a twitch does not.
        held_position = self.open_positions.get(w_sym) or {}
        entry_time = held_position.get("entry_time")
        if entry_time is not None and tick_time is not None:
            try:
                held_min = (tick_time - entry_time).total_seconds() / 60.0
            except TypeError:                               # noqa: BLE001
                held_min = None
            if held_min is not None and held_min < ROTATION_MIN_HOLD_MINUTES:
                return False
        if challenger_strength <= w_strength + edge:
            return False

        # Belt and braces. _weakest_holder_for_rotation already skips
        # positions the operator opened, so this should be unreachable
        # -- but if it ever is reached, his trade keeps its seat.
        if not self._bot_may_close(
                w_sym, f"a stronger breakout ({challenger}) wanted the slot"):
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
            f"{challenger} {direction} (trend {challenger_strength:+.2%}, "
            f"{confirmations} of 3 confirmations) "
            f"-- a stronger breakout needs the slot."
        )
        self._exit(w_sym, price, EXIT_REASON_ROTATED_OUT, tick_time)
        self._rotations_today += 1
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

        # ==========================================================
        # 2026-07-29 -- one candle in nine reported ZERO volume
        # ==========================================================
        # The operator, told that seven breakouts had "no volume data":
        #
        #     "what ? but without volume how the stock moves upside ?"
        #
        # He was right and the phrasing was wrong. The volume existed;
        # the bot could not measure it. Counted across all three
        # recorded sessions:
        #
        #     27 Jul   28,123 of 235,348 candles show volume 0  (11.9%)
        #     28 Jul   24,135 of 230,047 candles show volume 0  (10.5%)
        #     29 Jul   25,931 of 229,470 candles show volume 0  (11.3%)
        #
        # Impossible in reality. Dhan sends a RUNNING DAY TOTAL, and a
        # candle's own volume is the difference between its first and
        # last reading. If only ONE snapshot lands inside that minute,
        # first == last and the subtraction gives zero. One photograph
        # instead of two.
        #
        # Seven of the bot's 35 breakouts fired on such a minute -- IKS,
        # NAVINFLUOR, DEEPAKNTR, ENDURANCE, GILLETTE, IFBIND, GANECOS --
        # and the filter waved every one through, because it could not
        # tell "no volume" from "not measured".
        #
        # THE FIX: measure over a WINDOW instead of one minute. A single
        # minute can miss a snapshot; VOLUME_WINDOW_CANDLES of them
        # cannot. Same feed, same data, wider ruler.
        history = self.candle_engine.last_n_closed(
            symbol, VOLUME_AVG_CANDLES + 1)
        prior = [
            c.get("volume") for c in history[:-1]
            if c.get("volume") is not None and c.get("volume") > 0
        ]

        # NO volume history for this symbol AT ALL -> the filter cannot
        # run. That is a feed-mode fact (Ticker mode reports no volume
        # for anything), not a fact about this breakout, and refusing
        # every trade because of it would simply stop the bot. Fails
        # open here, deliberately and narrowly.
        if len(prior) < MIN_VOLUME_CANDLES:
            return True

        avg_vol = sum(prior) / len(prior)
        if avg_vol <= 0:
            return True

        candle_vol = closed_candle.get("volume")
        if candle_vol and candle_vol > 0:
            # The normal path, unchanged since 24 July. A single-minute
            # surge must stay visible AS a single-minute surge -- an
            # early attempt at this fix averaged the breakout across
            # five minutes and turned a real 3x spike into 1.4x, which
            # would have refused exactly the trades worth taking.
            return candle_vol >= VOLUME_SURGE_MULT * avg_vol

        # THE ZERO-VOLUME MINUTE. Only one snapshot landed inside it, so
        # its own delta is 0 -- 11% of all candles, and 7 of the bot's
        # 35 breakouts. Fall back to the window, where the missing
        # shares reappear in a neighbouring minute's difference.
        window = self._window_volume(symbol, closed_candle)
        if window is None:
            # Silent across the whole window while this symbol normally
            # reports volume. Under the operator's rule (29 July) that
            # is a refusal, not a free pass.
            return not VOLUME_REQUIRED_FOR_ENTRY
        return (window / VOLUME_WINDOW_CANDLES) >= VOLUME_SURGE_MULT * avg_vol

    def _volume_multiple(self, symbol, closed_candle):
        """How many times its own recent average this breakout traded.

        The same number the volume gate judges on, exposed so the
        journal can record it for signals the gate never reached --
        including the ones refused for a completely different reason.
        None when it cannot be measured.
        """
        try:
            if closed_candle is None:
                return None
            history = self.candle_engine.last_n_closed(
                symbol, VOLUME_AVG_CANDLES + 1)
            prior = [c.get("volume") for c in history[:-1]
                     if c.get("volume") is not None and c.get("volume") > 0]
            if len(prior) < MIN_VOLUME_CANDLES:
                return None
            avg = sum(prior) / len(prior)
            if avg <= 0:
                return None
            volume = closed_candle.get("volume")
            if not volume or volume <= 0:
                window = self._window_volume(symbol, closed_candle)
                if window is None:
                    return None
                volume = window / VOLUME_WINDOW_CANDLES
            return round(volume / avg, 2)
        except Exception:                                  # noqa: BLE001
            return None

    def _window_volume(self, symbol, closed_candle):
        """Total volume over the last VOLUME_WINDOW_CANDLES minutes,
        the breakout candle included. None when even the window has
        nothing -- which means the feed really is silent, not that one
        snapshot went missing.

        Summing is exactly right for a cumulative-total feed: a minute
        that reads 0 because it saw one snapshot has its shares counted
        in the NEXT minute's difference, so the window total is correct
        even when its individual minutes are not.
        """
        try:
            history = list(self.candle_engine.last_n_closed(
                symbol, VOLUME_WINDOW_CANDLES))
            # The breakout candle has ALREADY been appended to the
            # closed-candle history by the time entry is evaluated, so
            # it is normally the last element here. Adding it again
            # would double-count it -- caught by the window test, which
            # read 500 where 450 was correct.
            if not history or history[-1] is not closed_candle:
                history.append(closed_candle)
                history = history[-VOLUME_WINDOW_CANDLES:]
            total = sum(c.get("volume") or 0 for c in history
                        if (c.get("volume") or 0) > 0)
            return total if total > 0 else None
        except Exception:                                  # noqa: BLE001
            return None

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
        # FRESH BREAKOUTS PANEL (2026-07-28) -- recorded HERE, at the
        # top, BEFORE every gate below. A breakout that gets refused is
        # exactly as worth seeing as one that gets taken: on 2026-07-28
        # the engine fired breakouts on TVSMOTOR, NTPCGREEN, KTKBANK and
        # dozens more, the SHORT_ONLY regime refused every one in
        # silence, and the operator watched TVS run with no idea his own
        # bot had already spotted it. Recording after the gates would
        # reproduce exactly that blindness.
        # Never raises -- see core/breakout_feed.py.
        self._record_breakout_signal(symbol, direction, closed_candle,
                                     tick_time)
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

        # Entry cutoff. 2026-07-24 (evening) #0 FIX: this checks the
        # ACTUAL processing tick_time, not the closing candle's label
        # time. The bug: the final 15:14 candle only CLOSES when the
        # first 15:15 tick arrives, but closed_candle["time"] is
        # ~15:14:59 (the last tick INSIDE it), so it slid past this
        # guard and fired 10 fresh entries at 15:15:00-01 -- racing
        # main.py's one-shot flatten_all(), leaving them open (operator
        # report). tick_time is that first-15:15 tick. Falls back to
        # the candle label only if tick_time wasn't passed (older
        # callers/tests). Silent skip -- fires every candle for the
        # rest of the session and would flood otherwise.
        #
        # 31 July 2026: the CUTOFF ITSELF moved into
        # _entry_cutoff_reason(). It is no longer a bare 15:15 -- that
        # was MIS machinery guarding a forced liquidation the bot
        # stopped performing on 28 July. The race described above is
        # unchanged and still guarded; only the time it guards is now
        # derived from whether square-off is actually armed.
        #
        # Automatic entries are barely affected either way:
        # STAGED_NO_ENTRY_AFTER (15:00) already stops the bot opening
        # anything a quarter of an hour before this ever mattered.
        effective_time = tick_time or (
            closed_candle.get("time") if closed_candle else None
        )
        if _entry_cutoff_reason(effective_time):
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

        # RESULTS GATE, rewritten 2026-07-28 (core/results_gate.py).
        #
        # This used to be a flat "reporting today -> refuse", silently.
        # The comment justifying it was honest: the ATR system could not
        # tell a news reaction from organic momentum. That was true when
        # written; the filing -> PDF -> grade chain now reads the
        # numbers, so the premise expired.
        #
        # It also inverted the operator's entire strategy -- "entry only
        # on real reasons: results genuinely better than previous
        # quarter". CUB reported on 2026-07-28 and went +8.47%; this
        # rule would have refused it. 27 companies reported that day.
        #
        # Now: BEFORE the filing lands it still blocks (unknown outcome
        # is exactly the coin flip the rule was for). AFTER it lands and
        # grades STRONG or GOOD, it allows. Every unknown blocks.
        if self.results_gate is not None:
            if not self.results_gate.allows(symbol, candle_date):
                self._note_breakout_block(
                    symbol, direction,
                    self.results_gate.block_reason(symbol, candle_date))
                return
        elif candle_date is not None \
                and symbol in self.earnings_calendar.get(
                    candle_date.isoformat(), ()):
            # No gate wired (tests, dashboard_preview): fall back to the
            # old blanket block. Safe direction.
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

        # NO EVENT, NO TRADE (12 August 2026). See _no_reason_refusal().
        # This is BOT_SPEC.md's entry rule 2, finally applied to the lane
        # that could always place an order without it.
        #
        # NOTED, not _block_entry()'d: a stock with no news at 10:00 can
        # have a filing at 14:00, and a hard block would keep it out for
        # the rest of the day after the reason arrived. The breakout
        # still appears on the panel with this sentence attached, which
        # is the visibility the panel exists for.
        no_reason = self._no_reason_refusal(symbol)
        if no_reason is not None:
            self._note_breakout_block(symbol, direction, no_reason)
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
        if self.circuit_monitor is not None \
                and self.circuit_monitor.is_flagged(symbol) \
                and self._circuit_blocks(symbol, direction):
            return

        if _is_provisional(self.entry_blocked.get(symbol, {})
                           .get(direction)):
            pass                    # true at the time; ask again now
        elif direction in self.entry_blocked.get(symbol, {}):
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

        # LONG-ONLY MODE (2026-07-27, operator's decision).
        # Measured over 61 replayed sessions: SHORT was 1,035 trades
        # (53% of everything the bot did) for Rs 2,450 of GROSS profit
        # -- statistically indistinguishable from zero -- and about
        # Rs 121,000 of charges paid to collect it. See
        # MULTIDAY_FINDINGS.md section 1. Continuation on the short
        # side is noise at this timeframe, so the whole direction is
        # switched off rather than re-tuned.
        if direction == SHORT and not ENABLE_SHORT_TRADES:
            return

        # Trade WITH the tape, never against it (item 1). A one-sided
        # market blocks the fighting direction entirely.
        #
        # OFF since 2026-07-28 (config.ENABLE_MARKET_REGIME_GATE). On
        # that day 445 of 665 symbols were declining, the regime read
        # SHORT_ONLY, and the operator -- who trades LONG ONLY -- had a
        # bot that was structurally incapable of a single entry, in
        # silence, all session. CUB reported and went +8.47% on that
        # same tape; this gate would have refused it.
        #
        # A rule that switches the bot off on two-thirds of days makes
        # it unmeasurable. Kept intact and one flag away: "trade with
        # the tape" may prove right once there is data to judge it on.
        #
        # The breakout is recorded on the panel EITHER WAY, so what the
        # gate would have refused is still visible.
        regime = self._market_regime()
        if (direction == LONG and regime == "SHORT_ONLY") \
                or (direction == SHORT and regime == "LONG_ONLY"):
            self._note_breakout_block(
                symbol, direction,
                f"against the tape ({regime})"
                + ("" if ENABLE_MARKET_REGIME_GATE else " -- allowed anyway"))
            if ENABLE_MARKET_REGIME_GATE:
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

        # ---- AND IS IT MAKING THE HIGH, OR RETURNING TO IT? ----
        #      18 August 2026. See core/rules.BREAKOUT_MAX_OFF_HIGH_PCT
        #      for NAVINFLUOR, the alert that produced this gate.
        if not self._is_at_the_days_extreme(symbol, direction,
                                            closed_candle):
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
        # CAPACITY GATES DO NOT APPLY IN ALERT-ONLY MODE. 30 July 2026.
        #
        # The slot cap and the staged ramp exist to limit how much money is
        # committed. In alert-only mode the bot commits nothing -- it just
        # tells the operator what it found -- so "the book is full" has no
        # bearing on whether he should be told.
        #
        # This is not a nicety. The operator is carrying 10 positions into
        # tomorrow and MAX_OPEN_POSITIONS is 10, so the book is full at
        # 09:15. Without this bypass every single signal would have died at
        # the check below and alert-only mode would have produced ZERO
        # alerts all day -- a silent bot that looked like a quiet market.
        #
        # The QUALITY gates above and below still run in full: relative
        # strength, circuit room, results timing, liquidity, panic sector,
        # ATR sizing. Only capacity is skipped, and only when not trading.
        position_cap = self._staged_position_cap(effective_time)
        if not self.alert_only and position_cap <= 0:
            return
        if not self.alert_only and len(self.open_positions) >= position_cap:
            if not (ENABLE_SLOT_ROTATION
                    and self._maybe_rotate_out(symbol, direction, effective_time)):
                # 2026-07-29: say WHY, with the confirmations attached.
                # The operator's complaint was "real movers are ignored
                # by bot -- first see = buy & 10 slots filled", and it
                # could not be checked because nothing recorded the
                # refusals. Now the journal holds the name, the time,
                # how many positions were already open, and whether
                # this setup had news, results and volume behind it.
                self._note_slot_refusal(symbol, direction, position_cap)
                return

        # Daily guardrail (item 5): a realized day at/below the LOSS
        # switch takes no further entries. The profit goal is announced
        # and nothing more -- see the note on it below. Edge-triggered
        # log so the moment it trips is loud, once.
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
        # ---- A GOOD DAY IS NOT A REASON TO STOP. 1 Sept 2026. ----
        #
        #     "new entries only when opportunity showed up. there is no
        #      fixed time ,price or fixed limitations to follow. this is
        #      stock market not our own shop to do as we want."
        #                                            -- the operator
        #
        # This used to return here once realized P&L reached
        # DAILY_PROFIT_TARGET_RS, so the bot refused every opportunity
        # for the rest of the session because of a number WE chose. The
        # market does not stop offering at Rs 75,000, and a target that
        # closes the door is our shop's opening hours, not a reading of
        # anything.
        #
        # THE LOSS CAP ABOVE STAYS, and he said so explicitly. It is not
        # the same shape: it is protection against a bad day compounding,
        # and it triggers on money already lost, not money not yet made.
        #
        # Still said out loud when it is passed -- he wants to know the
        # day cleared its goal. It just no longer decides anything.
        if realized >= DAILY_PROFIT_TARGET_RS:
            if self._daily_halt_logged != "GOAL":
                self._daily_halt_logged = "GOAL"
                decision(
                    f"[DAILY GOAL MET] Realized P&L {realized:.0f} >= "
                    f"{DAILY_PROFIT_TARGET_RS:.0f}. Trading continues -- "
                    f"a good day is not a reason to stop taking the next "
                    f"opportunity."
                )

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
            symbol, direction, closed_candle["close"], security_id
        )
        if stop_seed is None:
            # ATR unavailable/insufficient history, or the computed
            # qty came out below 1 share -- see _atr_entry_sizing()'s
            # docstring. Silent skip, same pattern as every other
            # "not a real signal yet" gate in this method.
            return
        # ALERT ONLY -- 30 July 2026. The signal has passed every gate and
        # WOULD have been bought. Instead it is reported, with the price,
        # the size it would have taken and the reason, and the operator
        # decides.
        #
        #     "we will stop completely bot from trade taking as of now.
        #      it must show me the stock in alerts only."
        #
        # Placed HERE, at the last possible moment, on purpose: everything
        # above still runs, so the journal still records the signal and
        # every refusal reason, and the alert carries the same evidence the
        # entry would have. Gating earlier would have made the bot blind
        # as well as idle.
        #
        # Deliberately NOT the trade_controller pause, which skips in
        # silence by design. Silence is the opposite of the requirement.
        # ---- ONE SWITCH WAS ARMING TWO BUYERS. 6 August 2026. ----
        #
        #     "even morning i asked can bot trade ? u replied with all
        #      rules . but again random entries taken"
        #                                       -- operator
        #
        # He turned bot-trading ON having been told the RANKER's rules:
        # up 1% or more, above its own open, a written reason, beating
        # its sector, liquid enough for his size, MTF allowed.
        #
        # This path -- the structural breakout -- applies none of them.
        # It buys a level break. Both paths read the same alert_only
        # flag, so one switch armed both, and every one of the eight
        # fills on 6 August came from THIS one:
        #
        #     EXIDEIND JAMNAAUTO BASF JKLAKSHMI RHIM BELRISE
        #     VGUARD GMDCLTD          all STRUCTURAL_LONG_BREAKOUT
        #
        # while the ranker named nothing all day. He was told the rules
        # of the path that never fired.
        #
        # So the breakout now needs its OWN arming, and it is off by
        # default. Bot-trading ON means the ranker trades. This path
        # alerts and waits for him, exactly as it did before the switch
        # existed.
        if self.alert_only or not getattr(self, "breakout_armed", False):
            why_not = ("the bot is not trading" if self.alert_only else
                       "bot trading is ON for the ranked list only -- "
                       "breakout entries are not armed")
            # ---- SHOW THE EVIDENCE, NOT JUST THE MECHANISM. ----
            #      18 August 2026.
            #
            #     "stocks raising with underlying evidence =
            #      news/results/orders/anything that supports with
            #      volume must have added advantage rather than normal
            #      breakout stocks."
            #
            # He was reading alerts that said only
            # STRUCTURAL_LONG_BREAKOUT -- SHRINGARMS at 229.36 was the
            # one that prompted this -- and could not tell an
            # evidence-backed break from a bare level cross.
            #
            # The evidence was ALREADY GATHERED. _no_reason_refusal()
            # runs on this path and refuses a stock with no event
            # behind it, so anything reaching here HAS one --
            # _capture_reason() knows what it is and the alert threw
            # it away, printing the mechanism instead. The name of the
            # pattern is not the reason to buy.
            # ---- HIS FORMAT. 19 August 2026. ----
            #     "TIME  SYMBOL BUY REASON QTY  ENTRY - TARGET -
            #      EXIT - TRAILING POINTS"
            # Two lanes reached his phone in two different shapes and
            # he had to read each one differently. Same fields, same
            # order, whichever lane found the stock.
            _trail = None
            try:
                from core.trailing_stop import trail_points
                _trail = trail_points(
                    symbol, closed_candle["close"],
                    has_event=self._position_has_event(symbol))
            except Exception:                              # noqa: BLE001
                _trail = None
            self._manual_alert(
                symbol, f"alert-only-{direction}",
                f"{symbol} {direction} -- {entry_reason}"
                f"{self._alert_evidence(symbol)}"
                f"\nqty {qty}"
                f"\nentry {closed_candle['close']:.2f}"
                + (f"\ntarget {target:.2f}" if target else "")
                + f"\nexit {stop_seed:.2f}"
                + (f"\ntrailing {_trail}" if _trail else "")
                # "ALERT ONLY" is the standing phrase across the
                # logs, the board and every earlier alert. It is a
                # safety statement -- the bot did NOT act -- and
                # keeping the exact words costs one line and
                # removes any doubt about which it is.
                + f"\n_ALERT ONLY: {why_not}_"
            )
            if self.signal_journal is not None:
                try:
                    self.signal_journal.record(
                        symbol, direction,
                        break_price=closed_candle["close"],
                        taken=False,
                        refused_why="ALERT ONLY -- bot not trading, "
                                    "operator decides",
                    )
                except Exception:                          # noqa: BLE001
                    pass
            return
        self._enter(
            symbol, security_id, closed_candle["close"], stop_seed,
            closed_candle["time"], entry_reason, direction, target=target,
            qty=qty, stop_mode=stop_mode,
        )
        # The signal made it all the way through. Drop the BUY button on
        # the Fresh Breakouts panel -- the engine refuses pyramiding, so
        # offering one on a position already open would be a lie.
        if self.breakout_feed is not None:
            try:
                self.breakout_feed.mark_taken(symbol, direction)
            except Exception:                              # noqa: BLE001
                pass
        if self.signal_journal is not None:
            try:
                self.signal_journal.record(symbol, direction, taken=True)
            except Exception:                              # noqa: BLE001
                pass

    def _entry_stop_and_target(self, symbol, direction, entry_price,
                               security_id=None):
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
                symbol, direction, entry_price, security_id
            )
            return stop_price, target, qty, STOP_MODE_ATR_TRAILING
        return (
            self._orb_stop_seed(symbol, direction), None,
            LAYER1_FIXED_QTY, STOP_MODE_SWING_TRAILING,
        )

    def _manual_qty(self, sized, asked=None):
        """The size for an order the OPERATOR asked for.

        ---- HE CAN NAME IT NOW. 2 August 2026. ----
        `asked` is a quantity typed on the dashboard. It WINS over the
        risk sizing, because a number he typed is a decision and the
        sizing rule is a default. It does not win over
        MANUAL_TEST_QTY -- that switch exists to make the first real
        orders one share regardless of what anything else believes,
        and a typo in a quantity box must not defeat it.

        Every hard ceiling still applies downstream, in
        trading/live_execution.py: LIVE_MAX_ORDER_VALUE_RS,
        LIVE_MAX_ORDERS_PER_DAY, LIVE_MAX_OPEN_POSITIONS. Those are
        enforced at the order, not here, precisely so that no caller
        -- including this one -- can talk its way past them.


            "Friday . we planned 1 manual share buying & selling in MTF
             from our dashboard"

        config.MANUAL_TEST_QTY overrides risk sizing for manual clicks
        only. The first order this account ever sends through the bot
        should be one share, not the two hundred that risk maths gives
        on a Rs 300 stock.

        Automated entries never reach here. That separation is the whole
        point -- a test size must never quietly become the size the bot
        trades.
        """
        if MANUAL_TEST_QTY:
            try:
                qty = int(MANUAL_TEST_QTY)
            except (TypeError, ValueError):
                return sized
            if qty > 0:
                warn(f"[MANUAL] config.MANUAL_TEST_QTY is set -- placing "
                     f"{qty} share(s), not the risk-sized {sized}.")
                return qty
        if asked:
            try:
                asked = int(asked)
            except (TypeError, ValueError):
                return sized
            if asked > 0:
                decision(f"[MANUAL] {asked} share(s) requested from the "
                         f"dashboard (the sizing rule said {sized}).")
                return asked
        return sized

    def _risk_sized_qty(self, price, stop_distance, symbol=None,
                        security_id=None, cap_by_risk=True):
        """Shares to buy for ONE position.

        OPERATOR'S RULE, 2026-07-28 -- replaces the old risk formula:

            "Buy no of shares worth equal to 1 Lakh = mtf power. ex - as
             of now if i want to buy coforge 1686 rs - qty 225 with
             99657.31 rs worth."

        A fixed Rs 1 lakh of HIS OWN margin goes into every position.
        The share count falls out of whatever margin that stock requires
        -- asked of Dhan, never estimated (core/mtf_margin.py).

            COFORGE 1,686 -> 225 shares -> Rs 3,79,350 of stock
                                        -> Rs   99,655 blocked

        WHAT THIS REPLACED, and why it had to go: the old rule was
        min(RISK_PER_TRADE_RS / stop_distance, MAX_NOTIONAL / price).
        At the 1% stop floor those two are algebraically identical --
        2000/(0.01*p) == 200000/p -- so every one of 2026-07-28's
        eighteen trades came out at Rs 1.90-2.00 lakh. NILKAMAL, which
        swings 11% a day, was given the same size as MANAPPURAM, which
        swings 2%. The rule could not distinguish between any two
        stocks in the universe.

        stop_distance is kept in the signature (unused) so every caller
        and test keeps working; the stop still governs the EXIT, it just
        no longer governs the SIZE.

        Falls back to own-cash sizing whenever the margin book is not
        wired -- Rs 1 lakh buys Rs 1 lakh of stock. Never more.
        """
        try:
            if self.mtf_margin is not None and symbol:
                qty, pct, value = self.mtf_margin.quantity_for(
                    symbol, security_id, price)
                if qty > 0:
                    return (self._cap_by_risk(qty, price, stop_distance,
                                              symbol)
                            if cap_by_risk else qty)
            budget = MTF_MARGIN_PER_POSITION_RS
            qty = max(1, int(budget // float(price))) if price else 1
            return (self._cap_by_risk(qty, price, stop_distance, symbol)
                    if cap_by_risk else qty)
        except Exception:                                  # noqa: BLE001
            return 1

    def _cap_by_risk(self, qty, price, stop_distance, symbol=None):
        """Shrink the position so a stop-out costs RISK_PER_TRADE_RS.

        ---- THE SIZE NEVER LOOKED AT THE STOP. 7 August 2026. ----

            "but with lower the stop loss 1.67% will kick us out
             instantly right?"                        -- operator
            "MADE TO LOOSE SMALL INCASE OF LOSS & WIN BIG ON WINNING
             STOCKS. THATS THE CORE HEIRARCHY YOU MUST FOLLOW"

        Size came from the MARGIN budget alone -- Rs 30,000 of his own
        money, roughly Rs 1.2 lakh of stock -- and nothing asked how
        far away the stop was. So the loss on a stop-out was whatever
        the opening range happened to be that morning.

        Measured on the eight fills of 6 August, entry to the range low:

            JAMNAAUTO 1.26%   BELRISE 1.45%   EXIDEIND 1.72%
            RHIM      2.10%   GMDCLTD 2.41%   VGUARD   3.82%
            BASF      4.16%   JKLAKSHMI 6.42%

        Rs 2,000 of risk on a Rs 1.2 lakh position allows 1.67%. Five
        of the eight were wider. JKLAKSHMI at 6.42% would have cost
        about Rs 6,623 on a stop-out -- three times the budget -- and
        nothing anywhere would have refused it.

        THE STOP IS NOT MOVED. That was his first worry and it is the
        right one: a stop tightened to fit a budget is a guaranteed
        loser, and this bot learned that on 24 July. The stop stays at
        the opening range low, however far that is. The SHARE COUNT
        comes down instead.

            JKLAKSHMI   entry 618.00   stop 578.34
                        was  167 shares -> Rs 6,623 at risk
                        now   50 shares -> Rs 2,000 at risk
                        same stop, same room to breathe

        A tight range therefore gets a BIGGER position than before, not
        a smaller one. That is the "win big" half of his rule, and it
        is where it comes from.
        """
        try:
            qty = int(qty)
            price = float(price)
            stop_distance = abs(float(stop_distance or 0.0))
        except (TypeError, ValueError):
            return qty
        if qty <= 0 or price <= 0 or stop_distance <= 0:
            # No stop distance to size against -- leave it alone rather
            # than invent one. Silently guessing here would be worse
            # than the gap it is closing.
            return qty

        affordable = int(RISK_PER_TRADE_RS / stop_distance)
        if affordable >= qty:
            return qty
        if affordable < 1:
            # Even one share risks more than the budget. That is a
            # refusal, not a rounding -- and it is said out loud.
            self._manual_alert(
                symbol or "?", "stop-too-wide",
                f"{symbol}: the stop is {stop_distance:.2f} away from "
                f"entry, so a single share risks Rs {stop_distance:.0f} "
                f"-- more than the Rs {RISK_PER_TRADE_RS:.0f} budget. "
                f"Not taken.")
            return 0
        diagnostic(
            f"[SIZE] {symbol}: {qty} -> {affordable} shares. The stop "
            f"sits {stop_distance / price * 100:.2f}% away, so {qty} "
            f"would risk Rs {qty * stop_distance:,.0f} against a "
            f"Rs {RISK_PER_TRADE_RS:,.0f} budget. Stop unchanged.")
        return affordable

    def _atr_entry_sizing(self, symbol, direction, entry_price,
                          security_id=None):
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
        of how small ATR reads.

        ---- THIS PARAGRAPH WAS DESCRIBING OLD CODE. 31 Aug 2026. ----

        It used to say qty was "separately capped so notional never
        exceeds MAX_NOTIONAL_PER_TRADE_RS -- a second, independent
        backstop". That stopped being true on 29 July, when sizing
        moved to the MTF margin (see _risk_sized_qty and the long note
        further down this method). MAX_NOTIONAL_PER_TRADE_RS is
        imported by this file and read by no line of it.

        A comment promising a safety that no longer exists is worse
        than no comment: it sent me looking for a bug that was not
        there, and it would send anyone else the same way.

        WHAT ACTUALLY BOUNDS THE SIZE NOW: a fixed
        MTF_MARGIN_PER_POSITION_RS (Rs 30,000) of his own cash per
        position, with the share count asked of Dhan rather than
        estimated. The stop distance above governs the EXIT; it has
        not governed the SIZE since 29 July.
        """
        candles = self.candle_engine.last_n_closed(symbol, ATR_PERIOD + 1)
        if len(candles) < MIN_ATR_CANDLES:
            return None, None, None

        atr = compute_atr(candles, ATR_PERIOD)
        if atr is None or atr <= 0:
            return None, None, None

        # ---- TWO QUESTIONS, ONE FLAG. UNTANGLED 29 August 2026. ----
        #
        # HOW WIDE the entry stop is, and WHETHER it ratchets up, are
        # separate questions. VOLATILITY_SCALED_STOP's own comment
        # below says exactly that -- "ENABLE_BOT_TRAILING_STOP had
        # been answering both since 29 July" -- and the ordering here
        # was what made it true.
        #
        # Turning the trail on for his fading-into-the-close problem
        # silently took this first branch instead, and 0.8 x a
        # ONE-MINUTE ATR is always under the 1% floor. Measured: the
        # entry stop became 1.00% for every stock at every ATR, on
        # names whose DAILY range is around 3.9%. A stop inside the
        # noise, and qty = risk / distance would have tripled every
        # position at the same time.
        #
        # So the width is decided first and on its own terms. The
        # trail flag now governs only the ratchet, which is what its
        # name says and all it was ever meant to do.
        if VOLATILITY_SCALED_STOP:
            # ---- ONE WIDTH FOR 1,312 STOCKS. 18 August 2026. ----
            #
            #     "do not fix the 2.5% for every stock"
            #
            # Still a HARD stop -- it is placed once and never moves,
            # exactly as the trail-free design requires. Only its
            # WIDTH changed, from one number for every stock to this
            # stock's own daily range. Those are two separate
            # questions and ENABLE_BOT_TRAILING_STOP had been
            # answering both since 29 July.
            #
            # Falls back to the flat number, not to a guess, whenever
            # the daily store cannot answer. See _hard_stop_pct().
            stop_distance = self._hard_stop_pct(symbol) * entry_price
        elif ENABLE_BOT_TRAILING_STOP:
            # The pre-18-August width: this stock's INTRADAY ATR, with
            # a percentage floor under it. Demoted below the daily
            # scaling rather than deleted -- it is still the right
            # width if VOLATILITY_SCALED_STOP is ever turned off, and
            # tests/test_engine.py pins that combination to prove it.
            #
            # It is no longer reachable by turning the trail on, which
            # is the whole point: 0.8 x a one-minute ATR sits under the
            # 1% floor on every stock, so this branch WAS the 1.00%
            # stop that turning the trail on silently produced.
            raw_stop_distance = ATR_STOP_MULTIPLIER * atr
            min_stop_distance = MIN_STOP_DISTANCE_PCT * entry_price
            stop_distance = max(raw_stop_distance, min_stop_distance)
        else:
            # 2026-07-29: with the trail gone this stop is the ONLY
            # thing protecting the trade, so it is the operator's own
            # number -- 2.5% from entry -- not an ATR reading that
            # measured 1.06% in practice. Every variant in config's
            # ENABLE_BOT_TRAILING_STOP table was measured with exactly
            # this underneath it.
            stop_distance = HARD_STOP_FROM_ENTRY_PCT * entry_price

        # 2026-07-29, operator-found live. The size now comes from the
        # SAME rule his manual buys already use -- Rs 1 lakh of MTF
        # margin per position, share count asked of Dhan
        # (_risk_sized_qty / core/mtf_margin.py).
        #
        # What this replaced, and why it had to go: this method still
        # carried the OLD formula that _risk_sized_qty was written on
        # 2026-07-28 to abolish --
        #
        #     min(RISK_PER_TRADE_RS / stop_distance,
        #         MAX_NOTIONAL_PER_TRADE_RS / entry_price)
        #
        # At the 1% stop floor those two are algebraically identical
        # (2000 / (0.01 * p) == 200000 / p), so the notional cap bound
        # on EVERY trade and the ATR reading did nothing at all. Proof
        # from 29 July's own log -- 29 structural entries, every one of
        # them pinned to the ceiling:
        #
        #     MANUAL_BUY_DASHBOARD        11   Rs   95,934 - 100,064
        #     STRUCTURAL_LONG_BREAKOUT    29   Rs  197,041 - 200,382
        #
        # The operator's rule was in the code, tested, and simply not
        # on the path the bot used. Manual buys obeyed it; the bot's
        # own entries ran at double the agreed size.
        #
        # The ATR distance above is untouched -- the stop still governs
        # the EXIT. It just no longer governs the SIZE.
        #
        # ---- AND THE RISK CAP IS OFF ON THIS PATH. 7 Aug 2026. ----
        #
        # TOP_N_MOMENTUM_MODE sizes from the ATR itself, a few lines
        # up: a volatile stock already gets a wide stop and a small
        # position through ATR_STOP_MULTIPLIER. Applying the Rs 2,000
        # cap on top would be the same reduction taken twice, and it
        # broke seven tests that pin this path's arithmetic.
        #
        # The cap belongs on the ORB path, where size came from the
        # margin budget alone and nothing ever asked where the stop
        # was -- that is the hole it was built for.
        qty = self._risk_sized_qty(entry_price, stop_distance,
                                   symbol, security_id,
                                   cap_by_risk=False)
        if qty < 1:
            return None, None, None

        # ---- AND THE STOP HAD TO FOLLOW THE SIZE. 29 Aug 2026. ----
        #
        # The share count above comes from the MTF margin. The stop
        # width came from the stock's daily range, and nothing
        # reconciled the two -- so the rupees at stake were whatever
        # the multiplication happened to give.
        #
        # Caught by walking a real trade through: TCS at Rs 3,000, the
        # card said stop 2,937.50 risking Rs 2,500, and this method
        # held 2,859.53 risking Rs 5,619. His phone would have shown
        # less than half the loss the trade carried.
        #
        # core/position_plan.py was changed the same day to derive the
        # distance from the rupee risk: distance = risk / qty. This is
        # the other half of that. Same inputs, same arithmetic, same
        # answer on both paths.
        #
        # Bounded at both ends like everything else -- a size that
        # would put the stop inside the noise, or past the point where
        # the loss stops being small, is refused rather than taken.
        if STOP_FROM_RISK_AND_SIZE and qty > 0:
            wanted = RISK_PER_TRADE_RS / qty
            as_pct = wanted / entry_price * 100.0
            if as_pct < STOP_FLOOR_PCT or as_pct > STOP_CEILING_PCT:
                return None, None, None
            stop_distance = wanted

        if direction == LONG:
            stop_price = entry_price - stop_distance
        else:
            stop_price = entry_price + stop_distance

        # ---- THE CARD PROMISED A TARGET AND THE TRADE IGNORED IT ----
        #      29 August 2026.
        #
        # core/position_plan.py has always put "target 700" on the
        # alert -- stop distance x MIN_REWARD_MULTIPLE. This method
        # returned None here, so the bot held to the close and the
        # card was describing a trade that was never taken.
        #
        # The multiple comes from the day's breadth, which is already
        # computed and cached. See config.TARGET_REWARD_BY_REGIME.
        # The stop is scaled to the stock, so a multiple of the stop
        # is a target scaled to the stock.
        #
        # Never raises and never blocks an entry: if the regime cannot
        # be read, the target is simply absent and the trade behaves
        # exactly as it did before this existed.
        target_price = None
        if TARGET_REWARD_BY_REGIME:
            try:
                reward = TARGET_REWARD_BY_REGIME.get(self._market_regime())
            except Exception:                              # noqa: BLE001
                reward = None
            if reward:
                target_price = (entry_price + reward * stop_distance
                                if direction == LONG
                                else entry_price - reward * stop_distance)

        return stop_price, target_price, qty

    # ==============================================================
    # YOUR TRADES ARE YOURS  (2026-07-29)
    # ==============================================================

    def _is_manual_position(self, symbol):
        """True if the OPERATOR opened this position, not the bot.

        SMLMAH, 29 July: bought by hand at its upper circuit, closed
        by the bot seconds later on a housekeeping rule. See config's
        MANUAL_POSITIONS_BOT_MAY_NOT_CLOSE for the full note.
        """
        position = self.open_positions.get(symbol)
        if not position:
            return False
        return position.get("entry_reason") in (
            ENTRY_REASON_MANUAL_DASHBOARD,
            ENTRY_REASON_MANUAL_SHORT_DASHBOARD,
        )

    def _bot_may_close(self, symbol, what_it_wanted_to_do):
        """False when the bot is about to close a position the operator
        opened for a reason that isn't loss protection.

        Says so in plain English rather than skipping silently -- the
        operator's standing rule is that he must be able to read what
        the bot is doing.
        """
        if not MANUAL_POSITIONS_BOT_MAY_NOT_CLOSE:
            return True
        if not self._is_manual_position(symbol):
            return True
        self._manual_alert(
            symbol, "HELD",
            f"{symbol} -- you bought this one. The bot wanted to close "
            f"it ({what_it_wanted_to_do}) and did NOT. Still open."
        )
        return False

    def _check_news_on_holding(self, symbol, position, price):
        """Tell the operator when a stock he HOLDS files something.

        =====================================================
        2026-07-29 -- information, deliberately not automation
        =====================================================
        PCBL filed results at 14:19 while the position was open. The
        bot logged the filing, exited on the trail minutes later, and
        the stock ran 12%. The obvious fix -- pause or widen the stop
        when news lands -- was MEASURED against all 19 results filings
        that day before being built, and it loses money:

            fell 2.5% or more after filing :  5
            rose 2.5% or more after filing :  8

        The eight that rose never touched a 2.5% stop anyway, so a
        pause does nothing for them. FOUR of the five that fell kept
        falling -- SKMEGGPROD -6.39%, REFEX -6.07%, CARTRADE -5.62%,
        BLACKBUCK -4.63% -- where the stop firing was correct and a
        pause would have doubled the loss. Exactly one (REFEX) fell
        through a stop and then recovered.

        Saves you once in nineteen, hurts you four times in nineteen.
        On results a stop is MORE useful, not less.

        So the bot reports and the operator decides -- which is also
        what the numbers say he is better at: on 29 July his own exits
        beat holding by Rs 5,319 while the bot's trail cost Rs 47,324.

        Fail-silent. A notification must never break a tick.
        """
        try:
            for source, label in ((self.news_feed, "news"),
                                  (self.announcements, "filing")):
                if source is None:
                    continue
                item = source.for_symbol(symbol)
                if not item:
                    continue
                kind = item.get("kind") or label.upper()
                # Dedupe on the EVENT, not the symbol -- a second,
                # different filing on the same stock is worth saying.
                stamp = (item.get("filed_at") or item.get("at")
                         or item.get("time") or kind)
                self._position_news_alert(symbol, position, price,
                                          label, kind, stamp, item)
        except Exception:                                  # noqa: BLE001
            pass

    def _position_news_alert(self, symbol, position, price, label, kind,
                             stamp, item):
        """One plain-English line, once per event."""
        key = (symbol, label, str(stamp))
        if key in self._news_alerted:
            return
        self._news_alerted.add(key)

        entry = position.get("entry_price")
        qty = position.get("qty")
        move = ""
        if entry and price:
            move = f", now {price:,.2f} ({(price - entry) / entry * 100:+.2f}%)"
        headline = (item.get("headline") or item.get("subject")
                    or item.get("title") or "")
        when = item.get("filed_at") or item.get("at") or ""
        self.manual_alerts.append({
            "symbol": symbol,
            "kind": "NEWS",
            "message": (f"{symbol} -- {kind} {label} {when} while you hold "
                        f"{qty} shares from {entry:,.2f}{move}. "
                        f"No action taken."
                        + (f" [{headline[:80]}]" if headline else "")),
            "at": datetime.now().strftime("%H:%M:%S"),
        })
        del self.manual_alerts[:-MANUAL_ALERT_HISTORY]
        decision(f"[HOLDING] {self.manual_alerts[-1]['message']}")

    def _trail_only_warns(self, symbol, price, stop_price):
        """True when this trailing-stop breach should be REPORTED
        rather than acted on -- i.e. the operator opened this position.

        KAYNES, 29 July: in profit, dipped 2.5% off its high, sold by
        the trail, then ran to 3,685. That day his own hand-made exits
        returned +Rs 5,947 while the trail lost Rs 14,909 -- so on HIS
        trades the message is worth more than the sale.

        The HARD stop is untouched and still fires. This only silences
        the trail, which is the one that sells winners.
        """
        if not MANUAL_POSITIONS_TRAIL_ALERTS_ONLY:
            return False
        if not self._is_manual_position(symbol):
            return False
        entry = (self.open_positions.get(symbol) or {}).get("entry_price")
        move = ""
        if entry:
            move = f", {((price - entry) / entry * 100):+.2f}% from your entry"
        self._manual_alert(
            symbol, "TRAIL",
            f"{symbol} has fallen back to {price:.2f} (trail level "
            f"{stop_price:.2f}{move}). NOT sold -- it is your trade. "
            f"Sell it from the dashboard if you want out."
        )
        return True

    def _manual_alert(self, symbol, kind, message):
        """Record a plain-English note about a manual position, once.

        Repeats are suppressed per symbol per kind -- a trailing-stop
        breach is true on every tick after it happens, and the operator
        does not need the same sentence four hundred times.
        """
        key = (symbol, kind)
        if key in self._manual_alerts_seen:
            return
        self._manual_alerts_seen.add(key)
        self.manual_alerts.append({
            "symbol": symbol,
            "kind": kind,
            "message": message,
            "at": datetime.now().strftime("%H:%M:%S"),
        })
        del self.manual_alerts[:-MANUAL_ALERT_HISTORY]
        decision(f"[YOUR TRADE] {message}")
        self._push_alert(self.manual_alerts[-1])

    def _push_alert(self, note):
        """Hand a finished note to whatever is listening.

        Order matters: the note is appended and logged BEFORE this
        runs, so a phone that is off, unconfigured or unreachable
        costs him nothing he had before -- the board and the log are
        already written by the time this is called.

        Wrapped because this runs on the trading loop. A Telegram
        timeout must never delay a tick, and must never turn a
        recorded alert into an exception on the entry path.
        """
        sink = getattr(self, "on_alert", None)
        if sink is None:
            return
        try:
            sink(dict(note))
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[ALERT] {note.get('symbol')} could not be "
                       f"forwarded ({type(exc).__name__}). It is on the "
                       f"board and in the log.")

    def export_session_counters(self):
        """Per-day counters that must survive a mid-session restart.

        2026-07-29: found in the integration check. _rotations_today
        reset to 0 on restart, so the 5-swap cap could be exceeded --
        five before lunch, five more after. _news_alerted reset too,
        so every filing already reported would be announced again.
        """
        return {
            "rotations_today": self._rotations_today,
            "news_alerted": ["|".join(k) for k in self._news_alerted],
            "manual_alerts_seen": ["|".join(k)
                                   for k in self._manual_alerts_seen],
        }

    def load_session_counters(self, saved):
        """Restore them. Never raises -- bad state must not stop a
        restart, it just means a counter starts fresh."""
        try:
            if not saved:
                return
            self._rotations_today = int(saved.get("rotations_today") or 0)
            self._news_alerted = {tuple(k.split("|"))
                                  for k in saved.get("news_alerted") or []}
            self._manual_alerts_seen = {
                tuple(k.split("|"))
                for k in saved.get("manual_alerts_seen") or []}
        except Exception:                                  # noqa: BLE001
            pass

    def get_manual_alerts(self):
        """Public read for the dashboard. Newest first."""
        return list(reversed(self.manual_alerts))

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

        # 2026-07-29: direction-aware. A LONG approaching its UPPER
        # circuit is the day's best position, not a trapped one.
        position = self.open_positions.get(symbol) or {}
        if not self._circuit_blocks(symbol, position.get("direction", LONG)):
            return

        if not self._bot_may_close(symbol, "it is near a circuit limit"):
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

    def _circuit_blocks(self, symbol, direction):
        """True when this circuit approach is genuinely against us.

        LONG  + LOWER circuit  -> True   (no buyers if it locks)
        LONG  + UPPER circuit  -> False  (no sellers -- that is the win)
        SHORT + UPPER circuit  -> True
        SHORT + LOWER circuit  -> False

        Fails CLOSED on unknown data: if the side cannot be read, the
        old blanket behaviour applies. An unreadable flag is not
        evidence that the approach is favourable.
        """
        if not CIRCUIT_RULE_DIRECTION_AWARE:
            return True
        if self.circuit_monitor is None:
            return True
        try:
            flag = self.circuit_monitor.get_flag(symbol) or {}
            side = (flag.get("side") or "").upper()
        except Exception:                                  # noqa: BLE001
            return True
        if side not in ("UPPER", "LOWER"):
            return True
        if direction == LONG:
            return side == "LOWER"
        return side == "UPPER"

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

    # ----------------------------------------------------------
    # What happened AFTER we sold
    # ----------------------------------------------------------
    #
    #     "ltp is not place in closed positions so can't identify the
    #      move after exit in stocks - this requested by me as wanted
    #      but not done"          -- operator, 29 July 2026
    #
    # The bot forgot a stock the instant it sold it. On 29 July it
    # trailed out of KAYNES at 3,398 and KAYNES went to 3,684.70;
    # PCBL, KIRLPNU and EPACKPEB did the same thing. Every one of
    # those was spotted by the operator watching his broker screen,
    # because the bot had no idea and the dashboard had nothing to
    # show.
    #
    # This is DELIBERATELY observation only. It records where a stock
    # went after we left. It must never re-enter, never widen a stop,
    # never influence a decision -- the moment "it went up after we
    # sold" becomes an input, the bot is chasing its own regret.

    def _watch_after_exit(self, symbol, exit_price, exit_time):
        """Start following a symbol we have just sold."""
        try:
            exit_price = float(exit_price)
        except (TypeError, ValueError):
            return
        # Re-exiting the same symbol later in the day restarts the
        # clock -- the question is always "since the LAST exit".
        self.post_exit[symbol] = {
            "exit_price": exit_price,
            "exit_time": exit_time,
            "last": exit_price,
            "peak": exit_price,
            "trough": exit_price,
            "peak_at": exit_time,
        }

    def _update_after_exit(self, symbol, price, tick_time):
        """One dict lookup on the tick path. Nothing else."""
        watch = self.post_exit.get(symbol)
        if watch is None:
            return
        watch["last"] = price
        if price > watch["peak"]:
            watch["peak"] = price
            watch["peak_at"] = tick_time
        elif price < watch["trough"]:
            watch["trough"] = price

    def get_post_exit(self, symbol):
        """Where a symbol went after we sold it, or None."""
        watch = self.post_exit.get(symbol)
        return dict(watch) if watch else None

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

    def _block_entry(self, symbol, direction, reason, say=True):
        self.entry_blocked.setdefault(symbol, {})[direction] = reason
        if not say:
            # A provisional block is re-taken every cycle. Saying it
            # every cycle is how the log became 77% repeats.
            return
        warn(
            f"[NO_TRADE] {symbol} {direction} skipped -- {reason}. "
            f"No {direction.lower()} trade for {symbol} today."
        )

    def entry_blocked_reason(self, symbol, direction, at_time=None):
        """Is a fresh entry into (symbol, direction) blocked right now,
        and why -- or None if the risk layer has no objection.

        `at_time` is the moment being asked about. It defaults to
        datetime.now(), which is what every live caller wants.

        ---- WHY IT IS A PARAMETER. 12 August 2026. ----
        core/auto_entry.py's take() already carries its own `now` and
        gates on it (FIRST_NEW_ENTRY, LAST_NEW_ENTRY). It then called
        this method, which read the wall clock again. Two clocks in one
        decision is the same class of split-brain as two rule files, and
        it also made the two tests below fail after 15:30 every day --
        they asked a real Engine whether TCS was blocked and got "the
        market is closed", which is true and is not what they measure.
        Commit 1691b16 fixed exactly this bug in two other files.

        ---- THE CALL THAT WAS NEVER ANSWERED. 12 August 2026. ----

        core/auto_entry.py's refuse_reason() has asked for this exact
        method since it was written on 5 August ("the engine's own risk
        layer has the last word"), via getattr(engine,
        "entry_blocked_reason", None). Engine never had one, so
        callable(None) was always False and that whole check was a
        silent no-op on every ranked/early-bird entry -- the ranked path
        was never actually asked whether square-off, the daily loss cap,
        or a same-day news/sector block applied to it.

        This does not re-implement those checks; it reads the same state
        _try_structural_entry() already maintains (entry_blocked,
        _daily_realized_pnl(), _entry_cutoff_reason()) so the two entry
        paths can never disagree about whether the risk layer allows a
        trade right now.
        """
        symbol = str(symbol or "").upper()
        direction = str(direction or "").upper()

        # _entry_cutoff_reason() calls .time() on what it's given, so it
        # wants the full datetime, not an already-extracted time -- see
        # its "now = at_time.time()" line. Passing datetime.now().time()
        # here crashed with "'datetime.time' object has no attribute
        # 'time'" on every single call, live, at 09:30 on 12 August --
        # every ranked/early-bird entry that morning was refused by the
        # very check meant to protect them, not by a real risk block.
        cutoff = _entry_cutoff_reason(at_time or datetime.now())
        if cutoff:
            return cutoff

        realized = self._daily_realized_pnl()
        if realized <= -DAILY_MAX_LOSS_RS:
            return (f"daily loss cap hit ({realized:.0f} <= "
                    f"-{DAILY_MAX_LOSS_RS:.0f}) -- no new entries for the "
                    f"rest of the session")

        blocked = self.entry_blocked.get(symbol, {}).get(direction)
        if blocked and not _is_provisional(blocked):
            return blocked

        return None

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
        elif entry_reason == ENTRY_REASON_MANUAL_DASHBOARD:
            decision(
                f"\nMANUAL BUY (dashboard): {symbol}\n"
                f"Price                  : {price:.2f}"
                            )
        else:
            # ---- THE LOG LIED ABOUT WHO TRADED. 1 Sept 2026. ----
            #
            #     "34 qty is bots . mine 50 qty"
            #     "maintain 2 tables in each mode"
            #
            # This was the `else`, so EVERY entry whose reason was
            # not one of the two structural constants printed
            # "MANUAL BUY (dashboard)" -- including every
            # RANKED_SETUP, which is the bot's main lane:
            #
            #     14:38:18  MANUAL BUY (dashboard): VTL
            #     14:59:03  MANUAL BUY (dashboard): CAPLIPOINT
            #
            # Both were the bot deciding on its own, and I twice
            # told him VTL was his own click on the strength of it.
            #
            # He is separating his trades from the bot's across two
            # tables precisely so this cannot be confused. Those
            # tables read entry_reason and were never wrong; the LOG
            # was, and the log is what he reads while it runs.
            decision(
                f"\nBOT BUY: {symbol}\n"
                f"Reason : {entry_reason}\n"
                f"Price  : {price:.2f}"
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

        # What it actually filled at, not what we asked for. Everything
        # downstream -- the stop, the target, the R, the P&L -- is
        # measured from the entry price, so using the intended one puts
        # the error into every number the trade ever produces.
        price = self._filled_at(result, price)

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

        # WHY this trade was taken, captured NOW -- at entry, before
        # anything is known about how it turns out (2026-07-28).
        entry_reason_context = self._capture_reason(symbol)

        self.open_positions[symbol] = {
            "security_id": security_id,
            "qty": qty,
            "entry_price": price,
            "sector": entry_sector,
            "rel_strength": entry_rel,
            "regime": self._last_logged_regime,
            **entry_reason_context,
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
            # Missed-stop reconciliation (EXIT_REASON_MISSED_STOP).
            # The exchange's own day extreme AS IT STOOD at entry. A
            # day low only ever falls and a day high only ever rises,
            # so if this extends past our stop later, that move
            # happened AFTER we bought and the tick feed skipped it.
            # None when circuit_monitor isn't wired in (every existing
            # test, the replay bench) -- the check then fails open and
            # behaves exactly as before.
            "exchange_extreme_at_entry": self._exchange_extreme(symbol),
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
            self.trailing_stop.start(
                symbol, stop_seed, direction=direction, entry_price=price,
                has_event=self._position_has_event(symbol),
            )

        # ---- REST A STOP AT THE BROKER, 2026-08-02 ----
        #
        # Everything above this line keeps the stop in RAM. This is the
        # copy that survives the process dying. Placed at the HARD stop
        # from entry, NOT at stop_seed -- stop_seed is the live level
        # this process will manage and ratchet, and two stops at the
        # same price would race for the same fill.
        #
        # Wrapped, and never allowed to matter: an entry that has
        # already filled cannot be undone because a protective order
        # failed, so the failure is LOUD and the trade stands.
        if self.broker_stop is not None:
            try:
                from trading.broker_stop import hard_stop_price
                resting = hard_stop_price(price, direction,
                                          HARD_STOP_FROM_ENTRY_PCT)
                if resting:
                    self.broker_stop.place(symbol, security_id, qty,
                                           resting, direction=direction)
            except Exception as exc:                       # noqa: BLE001
                warn(f"[BROKER_STOP] {symbol}: entry is filled but no "
                     f"resting stop could be placed ({exc}). This "
                     f"position is protected by THIS PROCESS ONLY.")

        if self.portfolio is not None:
            if direction == LONG:
                self.portfolio.on_buy(price, qty)
            else:
                self.portfolio.on_short(price, qty)

    # --------------------------------------------------

    def _exchange_extreme(self, symbol):
        """The exchange's own day LOW for a long-side view / day HIGH
        for a short-side one, from circuit_monitor's REST snapshot.

        Returns (low, high) or None when there is no monitor wired in
        or no row for this symbol yet. Never raises -- this is a
        safety net, and a safety net that can throw is worse than no
        safety net at all."""
        if self.circuit_monitor is None:
            return None
        try:
            row = self.circuit_monitor.get_snapshot().get(symbol)
        except Exception:                               # noqa: BLE001
            return None
        if not row:
            return None
        low, high = row.get("low"), row.get("high")
        if not low or not high or low <= 0 or high <= 0:
            return None
        return (float(low), float(high))

    def _check_missed_stop(self, symbol, price, tick_time):
        """Did the stock trade through our stop without the tick feed
        ever showing us? See EXIT_REASON_MISSED_STOP at the top of this
        file for why this is necessary.

        Fails OPEN in every uncertain case -- no snapshot, no stop, no
        baseline -- because a false exit is a real loss, while a missed
        catch only leaves us where we already were.
        """
        position = self.open_positions.get(symbol)
        if position is None:
            return False

        baseline = position.get("exchange_extreme_at_entry")
        now = self._exchange_extreme(symbol)
        if baseline is None or now is None:
            return False

        stop = self._live_stop_price(symbol, position)
        if stop is None:
            return False

        direction = position.get("direction", LONG)
        if direction == LONG:
            # day low can only fall; a fall after entry is ours
            if now[0] >= baseline[0] or now[0] > stop:
                return False
            breached, gap = now[0], stop - now[0]
        else:
            if now[1] <= baseline[1] or now[1] < stop:
                return False
            breached, gap = now[1], now[1] - stop

        warn(
            f"[MISSED_STOP] {symbol} {direction} traded to {breached:.2f}, "
            f"through a stop of {stop:.2f} (by {gap:.2f}), and no tick in "
            f"our feed showed it. Exiting now at {price:.2f} -- this fill "
            f"is WORSE than the stop by design; the alternative was "
            f"holding a position we had already decided to cut."
        )
        self._exit(symbol, price, EXIT_REASON_MISSED_STOP, tick_time)
        return True

    def _live_stop_price(self, symbol, position):
        """The stop actually in force right now, whichever of the
        three stop mechanisms owns this position."""
        if position.get("stop_mode") == STOP_MODE_ATR_TRAILING:
            return position.get("atr_stop")
        if position.get("fixed_target") is not None:
            return position.get("initial_stop")
        try:
            return self.trailing_stop.get_stop(symbol)
        except Exception:                               # noqa: BLE001
            return None

    def _check_trailing_stop(self, symbol, price, tick_time):
        position = self.open_positions.get(symbol)
        if position is None:
            return

        # Reconcile against the exchange's own extreme BEFORE the
        # normal tick check. If the feed skipped a breach, this exits
        # and the tick check below has nothing left to do.
        if self._check_missed_stop(symbol, price, tick_time):
            return

        # ---- BOOK IT WHEN THE BUYING DRIES UP. 31 August 2026. ----
        #
        #     "when the buying dries up, book it. no one can book all
        #      the run stock did. its never gonna happen . we are here
        #      to trade as long as stock is in momentum thats it"
        #
        # This is the rule. It is not a target and it is not a trailing
        # stop -- both of those ask the PRICE where to get out, and the
        # price is the last thing to know. The buying stops first.
        #
        # self.buying_check is a function handed in by main.py, never
        # imported here. That keeps this engine free of the flow store
        # (which records; it does not decide) and, more practically,
        # stops a unit test reading the real store and closing a live
        # position, which is what happened the first time this was
        # written.
        if self._buying_dried_up(symbol, price, tick_time):
            return

        # Old fixed-bracket trades (any position opened before the
        # 2026-07-24 ATR redesign, restored from state across a
        # restart) never use the ratcheting trailing stop -- routed
        # by the position's OWN "fixed_target" field, not the global
        # config flag, so an already-open trade keeps behaving
        # exactly as it was opened even if the flag/mode changes
        # mid-session.
        # ---- A MANUAL BUY CARRIES BOTH. 23 August 2026. ----
        #
        #     "BUY SBIN = then bot must buy SBIN MTF with assigned rules
        #      (capital, target, stoploss, trailling)"   -- operator
        #
        # Target and trailing used to be mutually exclusive: setting
        # fixed_target routed here and RETURNED, so the ratchet below
        # never ran. A position that carries both -- which is what a
        # Telegram BUY now creates -- books the target when it is
        # reached, and until then trails like any other.
        #
        # His command, his rules. The bot's OWN entries are untouched
        # and still hold to the close, because every target width
        # measured on 22-23 August underperformed holding. He chose
        # that split deliberately.
        target = position.get("fixed_target")
        if target is not None and                 position.get("stop_mode") == STOP_MODE_ATR_TRAILING:
            direction = position.get("direction", LONG)
            hit = price >= target if direction == LONG else price <= target
            if hit:
                decision(f"[TARGET] {symbol} reached {target:.2f} -- "
                         f"booking it. Your Rs target on a manual buy.")
                self._exit(symbol, price, EXIT_REASON_FIXED_TARGET,
                           tick_time)
                return
            self._check_atr_trailing(symbol, position, price, tick_time)
            return

        if target is not None:
            self._check_fixed_bracket(symbol, position, price, tick_time)
            return

        # ATR trailing (TOP_N_MOMENTUM_MODE, 2026-07-24 onward) --
        # also routed by the position's own field, same reasoning.
        if position.get("stop_mode") == STOP_MODE_ATR_TRAILING:
            self._check_atr_trailing(symbol, position, price, tick_time)
            return

        # PEAK TRAIL, 2026-07-28. Ratchet on EVERY tick, not on candle
        # close -- a new high made mid-minute should lift the stop
        # immediately rather than waiting up to 60 seconds for the bar
        # to finish. Moves only on a new extreme, never on a pause.
        previous = self.trailing_stop.get_stop(symbol)
        moved = self.trailing_stop.update_on_price(symbol, price)
        if moved is not None and previous is not None and moved != previous:
            diagnostic(f"[TRAIL] {symbol} stop -> {moved:.2f} "
                       f"(new high {price:.2f})")
            # Let the resting stop at Dhan follow, but only when the
            # trail has moved far enough to be worth an order-path call
            # -- see BROKER_STOP_RESYNC_PCT. sync() never moves a stop
            # DOWN, so a trail that somehow retreats leaves the broker's
            # copy where it is, which is the safe side.
            if self.broker_stop is not None:
                try:
                    self.broker_stop.sync(symbol, moved)
                except Exception as exc:                   # noqa: BLE001
                    diagnostic(f"[BROKER_STOP] {symbol}: sync failed "
                               f"({exc}); the older trigger stands.")

        if not self.trailing_stop.is_hit(symbol, price):
            return

        stop_price = self.trailing_stop.get_stop(symbol)

        if self._trail_only_warns(symbol, price, stop_price):
            return

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

        if self._trail_only_warns(symbol, price, stop_price):
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
        # 2026-07-29, measured over 80 real trades: ratcheting this stop
        # is what turned +Rs 21,374 of entries into -Rs 1,252. With the
        # trail off the stop stays exactly where _atr_entry_sizing put
        # it -- 2.5% below entry -- and still closes a losing trade. It
        # simply stops selling the winners. See config's
        # ENABLE_BOT_TRAILING_STOP for the full table.
        if not ENABLE_BOT_TRAILING_STOP:
            return

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

        self._trim(symbol, position, trim_qty, close,
                   EXIT_REASON_PARTIAL_PROFIT, closed_candle.get("time"))
        position["partial_exit_done"] = True

    def _trim(self, symbol, position, trim_qty, price, reason, exit_time):
        """Close PART of a position and leave the rest running.

        Extracted from _maybe_partial_exit() on 2 August 2026 so the
        automatic ATR trim and the operator's own "sell half" go down
        the SAME path. Two code paths that both reduce a position and
        both write a closed_positions row is how the two start
        disagreeing about what is still held.

        The stop and the trail are deliberately NOT touched: the
        remaining shares keep the level they had. Re-seeding a stop on
        a trim would move risk on a position he did not re-enter.

        Returns the filled price, or None if nothing was sold.
        """
        direction = position.get("direction", LONG)
        entry_price = position["entry_price"]
        total_qty = int(position.get("qty") or 0)
        try:
            trim_qty = int(trim_qty)
        except (TypeError, ValueError):
            return None
        if trim_qty < 1 or trim_qty >= total_qty:
            return None

        exit_price = price
        pnl = None
        if direction == LONG:
            result = self.execution.sell(
                position["security_id"], symbol, exit_price, trim_qty,
                reason=reason,
            )
            exit_price = self._filled_at(result, exit_price)
            if self.portfolio is not None:
                pnl = self.portfolio.on_sell(entry_price, exit_price, trim_qty)
        else:
            result = self.execution.buy(
                position["security_id"], symbol, exit_price, trim_qty,
                reason=reason,
            )
            exit_price = self._filled_at(result, exit_price)
            if self.portfolio is not None:
                pnl = self.portfolio.on_cover(entry_price, exit_price, trim_qty)

        entry_time = position.get("entry_time")
        holding_seconds = None
        if entry_time is not None and exit_time is not None:
            holding_seconds = (exit_time - entry_time).total_seconds()

        decision(
            f"\n{reason}: {symbol}\n"
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
            "exit_reason": reason,
            "holding_seconds": holding_seconds,
            "pnl": pnl,
        })

        # Reduce the OPEN position's qty in place -- used_margin(),
        # deployed_capital(), and the eventual full exit via _exit()
        # all read position["qty"] fresh every time, so this is the
        # only bookkeeping change needed; the stop/trail state is
        # untouched.
        position["qty"] = total_qty - trim_qty

        # The resting stop at Dhan is for the WHOLE position. After a
        # trim it would sell more than is held -- on MTF the surplus is
        # a short. Re-rest it at the same trigger for what is left.
        if self.broker_stop is not None:
            try:
                resting = self.broker_stop.resting().get(symbol)
                self.broker_stop.cancel(symbol, why=f"trimmed to "
                                                    f"{position['qty']}")
                if resting and position["qty"] > 0:
                    self.broker_stop.place(
                        symbol, position["security_id"], position["qty"],
                        resting.get("trigger"), direction=direction)
            except Exception as exc:                       # noqa: BLE001
                warn(f"[BROKER_STOP] {symbol}: trimmed to "
                     f"{position['qty']} but the resting stop could not "
                     f"be resized ({exc}). CHECK DHAN -- it may still be "
                     f"sized for the OLD quantity.")
        return exit_price

    def _buying_dried_up(self, symbol, price, tick_time):
        """Close a winner whose buyers have stopped. True if it did.

        Three refusals, and each one is there for a reason he has
        already lived through:

        WINNERS ONLY. A losing trade belongs to the stop. Selling a
        loser because the flow looks tired is a stop loss replaced by a
        feeling, which is the thing this bot exists to remove.

        NO READING, NO ACTION. The check returns None when the order
        book is too thin to classify. None means nothing, not "sell".

        NOT IN THE FIRST FIFTEEN MINUTES. The reading compares now with
        fifteen minutes ago; below that it is reading the noise around
        its own entry. CDSL was once bought and closed eleven seconds
        later. Never again.
        """
        check = getattr(self, "buying_check", None)
        if check is None:
            return False
        position = self.open_positions.get(symbol)
        if position is None:
            return False
        entry = position.get("entry_price")
        if entry is None or price is None or price <= entry:
            return False

        held = self._held_minutes(position, tick_time)
        if held is not None and held < BUYING_CHECK_MIN_MINUTES:
            return False

        try:
            reading = check(symbol)
        except Exception:                                  # noqa: BLE001
            return False
        if not reading or reading.get("still_buying") is not False:
            return False

        gain = (price - entry) * (position.get("qty") or 0)
        decision(
            f"[BUYING DRIED UP] {symbol} at {price:.2f} -- the buyers have "
            f"stopped (delta {reading.get('delta')} against "
            f"{reading.get('was')} fifteen minutes ago). Booking "
            f"Rs {gain:+,.0f}.")
        self._exit(symbol, price, EXIT_REASON_BUYING_DRIED_UP, tick_time)
        return True

    @staticmethod
    def _held_minutes(position, tick_time):
        """Minutes since entry, or None when it cannot be worked out.
        None means "do not judge" -- never "zero"."""
        entered = position.get("entry_time")
        if not entered or not tick_time:
            return None
        try:
            start = datetime.fromisoformat(str(entered).replace("T", " ")[:19])
            now = (tick_time if isinstance(tick_time, datetime)
                   else datetime.fromisoformat(
                       str(tick_time).replace("T", " ")[:19]))
        except (ValueError, TypeError):
            return None
        return (now - start).total_seconds() / 60.0

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

            # ---- SELL SOME OF IT, NOT ALL OF IT. 2 August 2026. ----
            #
            #     "ride untill the momentum stays - exit once it gone
            #      ruthlessly"
            #
            # Riding a move usually means trimming into strength, and
            # this button could only ever sell the whole position. A
            # size on the request now trims instead.
            #
            # None -- every caller before today, and the exit-all
            # batch -- still means the whole position, unchanged.
            want = self.trade_controller.exit_qty(pending_symbol)
            position = self.open_positions[pending_symbol]
            held = int(position.get("qty") or 0)
            if want and 0 < want < held:
                self._trim(pending_symbol, position, want, exit_price,
                           EXIT_REASON_MANUAL_PARTIAL, tick_time)
            else:
                # want >= held is not an error -- it is "sell all of
                # it", which is what he means by typing the full size.
                self._exit(pending_symbol, exit_price,
                           EXIT_REASON_MANUAL, tick_time)
            self.trade_controller.clear_exit(pending_symbol)

    @staticmethod
    def _filled_at(result, intended):
        """The price the order ACTUALLY traded at.

        THE 11x BUG, fixed 30 July 2026.
        --------------------------------
        Every execution call returns

            {"success", "order_id", "price", "intent_price", "slippage_rs"}

        where `price` is the FILL and `intent_price` is what the engine
        asked for. The engine discarded the whole dict and carried on
        using its own intended price, so slippage was modelled, printed,
        written to fills.db -- and then thrown away before it reached
        the P&L.

        Measured over one session: gross on the fills was Rs 1,843.94,
        modelled slippage was Rs 19,334.01, and the dashboard reported
        Rs 21,177.95. The reported figure was the gross PLUS the cost
        that should have been subtracted -- roughly 11x the truth, in
        the flattering direction.

        A paper run exists to estimate what live trading would do. A
        paper run that quietly deletes its own costs estimates nothing.
        """
        try:
            filled = float((result or {}).get("price"))
        except (TypeError, ValueError):
            return intended
        # A zero or negative fill is a broken response, not a free trade.
        return filled if filled > 0 else intended

    def _exit(self, symbol, price, reason, exit_time):
        position = self.open_positions[symbol]
        direction = position.get("direction", LONG)

        pnl = None
        if direction == LONG:
            result = self.execution.sell(
                position["security_id"], symbol, price, position["qty"],
                reason=reason,
            )
            if not _order_went_through(result):
                _refused_exit(symbol, result)
                return
            # Rebound to the FILL before anything else uses it -- the
            # P&L, the closed_positions row, and the exit log all read
            # `price` below.
            price = self._filled_at(result, price)
            if self.portfolio is not None:
                pnl = self.portfolio.on_sell(
                    position["entry_price"], price, position["qty"]
                )
        else:
            result = self.execution.buy(
                position["security_id"], symbol, price, position["qty"],
                reason=reason,
            )
            if not _order_went_through(result):
                _refused_exit(symbol, result)
                return
            price = self._filled_at(result, price)
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
            # THE REASON, as it was known AT ENTRY (2026-07-28). Stamped
            # onto the position by _capture_reason() when the trade
            # opened -- never re-read at exit, which would record what
            # turned out to be true rather than what was known when the
            # decision was made.
            "news_kind": position.get("news_kind"),
            "filing_kind": position.get("filing_kind"),
            "results_grade": position.get("results_grade"),
            "days_since_results": position.get("days_since_results"),
            "had_reason": position.get("had_reason"),
            "reason_summary": position.get("reason_summary"),
            "rel_strength": position.get("rel_strength"),
            "regime": position.get("regime"),
        })

        self._watch_after_exit(symbol, price, exit_time)

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

        # ---- PULL THE RESTING STOP. THE ONE THAT MUST NOT BE MISSED.
        #
        # A Forever Order left at Dhan after this exit would SELL STOCK
        # THAT IS NO LONGER HELD -- on MTF that opens a short position
        # nobody asked for. It goes before the local bookkeeping below
        # so that even an exception in the rest of this teardown cannot
        # leave the broker holding a live order.
        if self.broker_stop is not None:
            try:
                self.broker_stop.cancel(symbol, why=reason)
            except Exception as exc:                       # noqa: BLE001
                warn(f"[BROKER_STOP] {symbol}: exit is done but the "
                     f"resting stop could NOT be cancelled ({exc}). "
                     f"CHECK DHAN -- it may still be live with no "
                     f"position behind it.")

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

    BROKER_HELD_SECONDS = 30

    def symbols_at_broker(self):
        """Every symbol he actually holds at Dhan, whoever opened it.

        ---- DHAN AND THE BOT WERE NOT IN LINE. 1 September 2026. ----

            "another thing dhan & bot is not inline. i had caplinpoint
             stock but bot does'nt know that still"

        Measured on the live snapshot as he said it:

            his at Dhan     CAPLIPOINT, SSWL, INTELLECT, MARINE, ...
            ranked to BUY   CAPLIPOINT, SSWL, DYCL, ENGINERSIN, ...

        CAPLIPOINT and SSWL were his own positions AND live buy
        candidates at the same moment. Nothing was bought on top of them
        only because the book happened to be full -- luck, not a guard.

        IT WAS NEVER A DATA PROBLEM. core/broker_sync.py prints "[BOOK]
        CAPLIPOINT: 50 at Dhan, opened outside the bot" every cycle and
        the panel shows it. The reading was there, correct, and
        displayed. It never reached the DECISION.

        IT LIVES HERE, not on the dashboard, because the ENGINE owns
        self.execution -- and because both readers need the same answer.
        main.py builds auto_entry's `held` from engine.open_positions
        and dashboard/state.py builds the ranker's separately, so a
        helper on either one of them would have fixed exactly half the
        problem and left the order path untouched.

        NOT an adoption and NOT a block: the bot still will not stop,
        trail or exit anything he opened. This only stops it BUYING a
        stock he is already in -- what "no pyramiding" has always meant
        for its own positions.

        FAILS OPEN. If Dhan cannot be reached this returns an empty set
        and both paths behave exactly as they did before, rather than
        refusing everything because one REST call timed out.

        IT NEVER BLOCKS THE CALLER. This is a REST call on the live
        account, and BOTH callers are on hot loops -- dashboard
        build_ranked() on the refresh loop and main.py's auto_entry on
        the trading loop, the same loop that checks square-off and the
        feed watchdog. core/engine.py has been bitten by exactly this
        before (the 52-week scan: "a 3.5s scan there is a 3.5s stall in
        the bot's own heartbeat"), and a slow Dhan reply measured 25.6s
        on 1 September. So the answer is always returned from memory and
        refreshed on a worker; a stale reading is worth far more than a
        stalled heartbeat.
        """
        import threading
        import time

        now = time.time()
        cached = getattr(self, "_broker_held_cache", None)
        fresh = cached and (now - cached[0]) < self.BROKER_HELD_SECONDS
        known = cached[1] if cached else set()

        if not fresh and not getattr(self, "_broker_held_running", False):
            self._broker_held_running = True
            threading.Thread(target=self._refresh_broker_held,
                             name="broker-held", daemon=True).start()
        return known

    def _refresh_broker_held(self):
        """The worker. Never raises -- it is a thread, so an exception
        here is silent and would leave the flag stuck on forever."""
        import time

        out = set()
        try:
            executor = getattr(self, "execution", None)
            executor = getattr(executor, "executor", executor)
            reader = getattr(executor, "positions", None)
            rows = reader() if reader else None
            for entry in (rows if isinstance(rows, list) else []):
                if not isinstance(entry, dict):
                    continue
                symbol = str(entry.get("tradingSymbol")
                             or entry.get("symbol") or "").upper()
                try:
                    # The same two keys dashboard/state.py's _book_row()
                    # reads, so the panel and the decision can never
                    # disagree about what he owns.
                    qty = float(entry.get("netQty")
                                or entry.get("quantity") or 0)
                except (TypeError, ValueError):
                    qty = 0.0
                if symbol and qty:
                    out.add(symbol)
            self._broker_held_cache = (time.time(), out)
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[BOOK] Could not read holdings from Dhan: {exc}")
        finally:
            self._broker_held_running = False

    def export_entry_blocks(self):
        """Plain-dict snapshot, safe to json.dump directly."""
        return {
            symbol: dict(directions)
            for symbol, directions in self.entry_blocked.items()
        }

    # A restored block whose RULE is now switched off must not outlive
    # the rule. 2026-07-27: BLOCK_REENTRY_AFTER_STOPOUT was set False
    # mid-session and the bot restarted -- but AUBANK and CAPLIPOINT had
    # already been blocked before the restart, the blocks were in the
    # state snapshot, and the read at _try_structural_entry consults
    # entry_blocked directly without checking the flag. Both of the
    # day's strongest names stayed locked out by a rule that was no
    # longer in force.
    #
    # Matched on the reason TEXT written by _block_entry, because that
    # is what the snapshot actually stores. Only the stop-out and
    # circuit-proximity reasons are droppable: corporate-action, news
    # and sector blocks are facts about the stock, not strategy
    # choices, and they survive regardless.
    _STOPOUT_BLOCK_MARKERS = (
        "stopped out once today",
        "flagged near its circuit limit once today",
    )

    def load_entry_blocks(self, blocks):
        """Restores from a snapshot produced by export_entry_blocks().
        Overwrites, never merges -- same reasoning as every other
        load_state() in this codebase.

        Stop-out blocks are dropped on the way in when
        BLOCK_REENTRY_AFTER_STOPOUT is off, so a disabled rule cannot
        keep enforcing itself through yesterday's saved state."""
        restored, dropped = {}, 0
        for symbol, directions in blocks.items():
            kept = {}
            for direction, reason in directions.items():
                if not BLOCK_REENTRY_AFTER_STOPOUT and any(
                    marker in str(reason)
                    for marker in self._STOPOUT_BLOCK_MARKERS
                ):
                    dropped += 1
                    continue
                kept[direction] = reason
            if kept:
                restored[symbol] = kept
        self.entry_blocked = restored
        if dropped:
            decision(
                f"[STATE] Dropped {dropped} stop-out entry block(s) -- "
                f"BLOCK_REENTRY_AFTER_STOPOUT is off, so they no longer "
                f"apply."
            )

    # --------------------------------------------------

    def flatten_all(self, get_price):
        """
        Called at SQUARE_OFF_TIME when FORCE_SQUARE_OFF_AT_CLOSE is on.
        get_price(symbol) -> latest known price.
        """
        now = datetime.now()
        for symbol in list(self.open_positions.keys()):
            price = get_price(symbol)
            if price is None:
                # 2026-07-28: this used to fall back to the position's
                # own ENTRY price, booking a perfectly flat P&L for a
                # trade that had one -- a silent falsification of the
                # book. Skip instead and say so; the belt-and-suspenders
                # loop in main.py retries on the next pass.
                warn(f"[SQUARE_OFF] {symbol} NOT closed -- no live price "
                     f"available. Will retry. It is still open.")
                continue
            self._exit(symbol, price, EXIT_REASON_SQUARE_OFF, now)

        decision("SQUARE OFF: all positions flattened.")

    def report_carry_forward(self, get_price):
        """MTF, 2026-07-28. What is being HELD overnight, and what it is
        worth right now.

        The operator moved to MTF to hold positions for days. Square-off
        is MIS machinery and would liquidate every one of them daily --
        it closed TVSMOTOR and CUB on 2026-07-28 for exactly that
        reason. So instead of flattening, the bot reports.

        Deliberately loud and itemised. A position carried overnight has
        risk no stop can cover between 15:30 and 09:15, so the operator
        should end every session knowing precisely what he is holding,
        not discover it at the next open.
        """
        if not self.open_positions:
            decision("[CARRY] Flat at the close -- nothing held overnight.")
            return

        total_value = 0.0
        total_open_pnl = 0.0
        decision(f"[CARRY] Holding {len(self.open_positions)} position(s) "
                 f"overnight (MTF -- square-off is OFF):")
        for symbol, position in sorted(self.open_positions.items()):
            price = get_price(symbol)
            entry = position.get("entry_price")
            qty = position.get("qty") or 0
            direction = position.get("direction", LONG)
            # ---- THERE IS NO KEY CALLED "stop". 24 August 2026. ----
            #
            #     "[CARRY]   CDSL LONG qty 47 ... stop None"
            #                                    -- operator, 24 Aug
            #
            # A position stores initial_stop, atr_stop and stop_mode.
            # `position.get("stop")` has therefore returned None for
            # every carried position since this line was written, so
            # the overnight block reported three unprotected holdings
            # while CDSL, JBMA and NCC each had a stop -- 1358.55,
            # 648.90 and 145.55, visible in the dashboard snapshot the
            # whole time.
            #
            # _live_stop_price() is the existing answer and knows all
            # three mechanisms. Reused, not re-derived: a second
            # opinion about where the stop is would be the same bug in
            # a new place.
            stop = self._live_stop_price(symbol, position)
            if price is None:
                decision(f"[CARRY]   {symbol}: qty {qty} @ {entry} -- "
                         f"no live price to value it against.")
                continue
            pnl = ((price - entry) if direction == LONG
                   else (entry - price)) * qty
            value = price * qty
            total_value += value
            total_open_pnl += pnl
            move = ((price - entry) / entry * 100) if entry else 0.0
            decision(
                f"[CARRY]   {symbol:12} {direction:5} qty {qty:6} "
                f"entry {entry:10.2f} now {price:10.2f} "
                f"({move:+.2f}%)  open P&L {pnl:+10.0f}  "
                f"stop {stop if stop is None else round(stop, 2)}"
            )
        decision(
            f"[CARRY] Total carried: Rs {total_value:,.0f} of stock, "
            f"open P&L Rs {total_open_pnl:+,.0f}. Overnight gap risk is "
            f"NOT covered by the trailing stop -- it cannot fire between "
            f"15:30 and 09:15."
        )
