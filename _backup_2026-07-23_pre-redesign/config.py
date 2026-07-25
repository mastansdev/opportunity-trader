"""
==========================================================
Opportunity Trader — Config
==========================================================

Layer 1 build (2026-07-22): raw ORB structural breakout
detection + buy, PAPER mode, NSE equity only. No news, no
sector/conviction scoring, no automated stop loss, no
position sizing logic yet -- those are separate phases,
each proven on its own before being trusted (see
PHASES.md).

Author : H&M Opportunity Trader
==========================================================
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ----------------------------------------------------------
# Broker credentials
# ----------------------------------------------------------

DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "")

# News Bot Stage 3 (AI classification, Claude Haiku). Only
# needed once the news pipeline actually runs -- the rest of
# Layer 1 (ORB PAPER trading) works fine without it.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ----------------------------------------------------------
# Trading mode
# ----------------------------------------------------------

# PAPER only until Layer 1 has been watched for real, live,
# without placing a single real order, and the operator
# trusts what it's doing.
TRADING_MODE = "PAPER"

# Equity only. No F&O in this bot, ever -- not a Layer 1
# limitation, a permanent decision.
EXCHANGE_SEGMENT = "NSE_EQ"

# ----------------------------------------------------------
# Market session (NSE real timeline -- verified against
# actual exchange behaviour, not assumed)
# ----------------------------------------------------------

PRE_OPEN_START = "09:00"   # order collection -- NOT live
PRE_OPEN_MATCH = "09:08"   # order matching -- NOT live
PRE_OPEN_BUFFER = "09:12"  # buffer -- NOT live

MARKET_OPEN = "09:15"      # real continuous trading starts
ORB_WINDOW_END = "09:30"   # opening range closes
SQUARE_OFF_TIME = "15:15"  # flatten everything, intraday only
MARKET_CLOSE = "15:30"

# Any tick timestamped before MARKET_OPEN must never be
# treated as live data for ORB building or entries. This is
# enforced in core/market_data.py, not just documented here.

# ----------------------------------------------------------
# Data integrity
# ----------------------------------------------------------

# If a tick's timestamp is older than wall clock by more
# than this, it's stale -- log it loudly, don't act on it
# silently.
MAX_TICK_STALENESS_SECONDS = 5

# A DIFFERENT integrity problem than the above -- MAX_TICK_
# STALENESS_SECONDS catches a DELAYED feed (old timestamp vs
# wall clock); this catches a FROZEN price (fresh timestamps,
# but the PRICE VALUE itself stops changing), regardless of
# WHY it froze. Found live, 2026-07-23: HFCL printed the exact
# same O=H=L=C=207.01 on every single 1-minute candle from
# 12:45 to 15:21 (see diagnostics.log). Operator-confirmed
# 2026-07-23 (after this fix was already built): the actual
# cause was HFCL hitting its LOWER CIRCUIT (exchange price
# band) at 11:49 -- real, legitimate market data, not a dead
# feed. The recurring "Stale tick" warnings for HFCL earlier
# in the session (~10:22 onward) were a separate, unrelated
# feed hiccup; the flat 12:45-15:21 stretch itself was the
# stock genuinely locked at its circuit limit.
#
# The fix is still correct, and arguably matters MORE for a
# circuit lock than a dead feed: a circuit-locked stock has no
# real counterparty for a NEW order in the losing direction
# (nobody wants to buy a stock stuck at its floor), so a fresh
# SHORT entry there is not a real trade even if this paper
# simulator would happily fill one. And ratcheting the
# trailing stop onto a circuit-locked "candle" is just as
# wrong as ratcheting onto a dead one -- a zero-range candle
# carries no real stop-safe level either way. The bot had no
# way to tell "this stock hit its circuit" from "my data for
# this one symbol died" or "the market genuinely went quiet
# here" -- practically, all three need the exact same response
# (stop treating this price as tradeable), so one detector
# covers all of them rather than trying to specifically
# classify which case it is.
#
# Before this fix: entering SHORT, immediately ratcheting the
# trailing stop flush onto the frozen price once the rolling
# window rolled the safe seed out, self-triggering an exit at
# that same frozen price on the very next tick, and (with
# BLOCK_REENTRY_AFTER_STOPOUT off for that one day) re-entering
# the instant the next identical candle closed -- 12 round
# trips, all at breakeven, over ~4 hours on one symbol.
#
# core/engine.py's frozen-price check (mirrors the momentum-
# eligibility / sector-panic gate pattern) silently blocks new
# structural entries and skips trailing-stop ratcheting for a
# symbol once its last N closed candles are all EXACT
# duplicates (same O=H=L=C) -- a live, actively traded,
# NOT-circuit-locked stock essentially never prints that by
# chance. 3 candles (~3 minutes of zero tick variance) is a
# deliberately low bar -- real consolidation still moves by at
# least a paisa somewhere in 3 minutes; a genuine circuit lock
# or dead feed does not.
FROZEN_PRICE_STREAK_CANDLES = 3

# ----------------------------------------------------------
# Circuit-limit proximity (PROACTIVE -- see core/circuit_monitor.py)
# ----------------------------------------------------------
#
# FROZEN_PRICE_STREAK_CANDLES above is REACTIVE -- it only notices
# a circuit lock after the fact (3 candles of zero movement have
# already printed). Operator instruction, post-HFCL discussion
# 2026-07-23: get out BEFORE the lock, not after. "Bullish is fine
# good but bearish = lower circuits are terrible. Bullish & Bearish
# irrespective we will close the open position before circuits."
#
# So this is deliberately direction-agnostic: an open position gets
# closed the moment its symbol is APPROACHING either circuit limit,
# never mind whether the approaching circuit favours the position
# (upper, for a long) or not (lower, for a long) -- a stock locked
# at its ceiling has no real counterparty for an exit order either,
# same practical problem as being locked at its floor, just a nicer
# mark-to-market number while it lasts. New entries are blocked the
# same way, same as the existing frozen-price gate.
#
# Circuit limits themselves come live from Dhan's REST
# /marketfeed/quote endpoint (upper_circuit_limit /
# lower_circuit_limit per symbol) -- confirmed against Dhan's API
# docs (2026-07) that the WebSocket feed this bot's tick stream
# already runs on (main.py's MarketFeed) does NOT carry circuit
# limits at all, only that separate REST snapshot does. This is
# deliberately NOT a hardcoded SEBI band table (2%/5%/10%/20%,
# category-dependent, can change intraday) -- Dhan already computes
# the live number per symbol, so core/circuit_monitor.py just reads
# it.
#
# A symbol is "approaching" a circuit once price is within this
# fraction of the LTP away from the limit -- e.g. 0.02 means "within
# 2% of hitting either the upper or lower circuit price". Starting
# point, not a proven number -- tune it after watching how fast a
# real circuit approach actually moves once live data exists to
# reason from, same spirit as every other placeholder threshold in
# this file.
CIRCUIT_PROXIMITY_PCT = 0.02

# How often the circuit monitor polls Dhan's REST quote endpoint,
# in seconds. Runs on its own thread (core/circuit_monitor.py),
# entirely separate from the tick-processing hot path -- same
# separation-of-concerns principle already applied to News Bot
# (main.py's _news_loop). Dhan's rate limit is 1 request/second for
# up to 1000 instruments per request -- this bot's whole ~750-symbol
# universe fits in a single call, so this interval is a polling
# cadence choice, not a batching necessity.
CIRCUIT_POLL_INTERVAL_SECONDS = 3

# ----------------------------------------------------------
# Dashboard -- Top Gainers / Top Losers (2026-07-23, replaces the
# old ORB Bullish/Bearish watchlist panel)
# ----------------------------------------------------------
#
# Reuses core/circuit_monitor.py's existing REST poll (see
# CIRCUIT_POLL_INTERVAL_SECONDS above) -- that poll already pulls a
# full quote snapshot (LTP, OHLC, prev close, volume) for the whole
# universe every few seconds; no second poller needed. This constant
# only controls how often dashboard/state.py re-RANKS that cached
# snapshot into the Top N gainers/losers table -- operator's own
# choice, deliberately much slower than the underlying data refresh:
# "for every 5 mins" -- a display table doesn't need to reshuffle
# every few seconds to be useful, and re-sorting the whole universe
# less often is cheaper for a value nobody's watching tick-by-tick.
GAINERS_LOSERS_REFRESH_SECONDS = 300

# How many symbols on each side of the table -- operator's own
# number, matches NSE's own "Top Gainers/Losers" convention.
GAINERS_LOSERS_COUNT = 50

# Sector Heatmap redesign, 2026-07-23 evening: "instead of deleting
# the sector heatmap, make it use like same top 50 gainers &
# losers... top gaining sectors / top loosing sectors." Replaces the
# old DAY-OPEN-based sector heatmap (dashboard/state.py's old
# _build_sectors() "heatmap" list, now removed) with a PREV-CLOSE
# ranking, built from the exact same per-symbol rows
# _build_gainers_losers() already computes off circuit_monitor's
# snapshot -- one throttled pass feeds both tables, not two. Same
# too-few-symbols-is-noise reasoning as the old
# INDUSTRY_HEATMAP_MIN_SYMBOLS (a sector with 1-2 reporting stocks
# isn't a real sector move) -- a dedicated constant, not a reuse of
# that one or of core/sector_monitor.py's SECTOR_PANIC_MIN_SYMBOLS,
# because both of those serve different features and could
# reasonably diverge from this one later.
SECTOR_GAINERS_LOSERS_MIN_SYMBOLS = 3

# ----------------------------------------------------------
# Console health signal
# ----------------------------------------------------------

# At 750 symbols, per-tick console logging is exactly what
# flooded the previous bot into unreadability. Console stays
# silent between real decisions except for this one line --
# proof the bot is alive and roughly how busy it is, not a
# play-by-play.
HEARTBEAT_INTERVAL_SECONDS = 60

# ----------------------------------------------------------
# Universe
# ----------------------------------------------------------

# The 6-symbol hardcoded watchlist has been retired. The
# tradable universe is now the full 750-stock master
# database (data/master_stocks.csv, loaded via
# core/master_loader.py) -- verified once against Dhan's
# live scrip master (tools/verify_master_database.py) and
# treated as the fixed source of truth from here on. Re-run
# that verification tool periodically -- symbols get
# delisted, security IDs occasionally change.

# ----------------------------------------------------------
# Strategy
# ----------------------------------------------------------

# A breakout is a 1-minute candle CLOSE above the ORB high,
# not an intrabar touch/wick. Keeps out fake pokes.
CANDLE_INTERVAL_SECONDS = 60

# ----------------------------------------------------------
# Position sizing (PLACEHOLDER -- Layer 1 only)
# ----------------------------------------------------------

# No capital-based sizing yet. Fixed quantity until the Risk
# Layer is rebuilt and proven. This is intentionally crude
# and is not meant to reflect real position sizing.
#
# Bumped 1 -> 100 on 2026-07-23 at the operator's explicit
# request, for that session only -- NOT a Phase 2 sizing
# upgrade, still the same flat placeholder regardless of
# price or capital. Revisit this number every session until
# real capital-based sizing (Phase 2) replaces it outright.
LAYER1_FIXED_QTY = 100

# ----------------------------------------------------------
# Trailing stop (longs AND shorts -- see core/trailing_stop.py)
# ----------------------------------------------------------

# Rolling window, in closed 1-min candles, used to compute the
# trailing-stop reference (low for longs, high for shorts). A
# 1-candle trail on 1-min bars ratchets too fast and cuts
# winners short -- the same failure mode as the fixed 1:1 R:R
# this replaces. 5 is a starting point, not a proven number --
# tune it after watching real trades, same as everything else
# in this codebase.
TRAILING_STOP_WINDOW_CANDLES = 5

# Operator-approved 2026-07-23, after watching the first live
# session whipsaw repeatedly: the initial stop used to be seeded
# from the BREAKOUT CANDLE's own low/high -- a single 1-minute
# bar, often just a few paise wide on a liquid stock -- instead
# of the actual structural level being traded. Dozens of same-
# second BUY/TRAILING_STOP pairs in logs/trade_log.csv that
# morning were ordinary tick noise clipping a stop that was
# never really "in the market" to begin with.
#
# Corrected: the initial stop is now the OPPOSITE boundary of
# the ORB range itself -- ORB low (minus this buffer) for a
# long, ORB high (plus this buffer) for a short. That gives the
# trade the full range width as room, which is what "the range
# failed" structurally means for an ORB breakout. This buffer is
# just cushion on top of that so the stop doesn't sit exactly on
# the boundary line where a single wick could tag it by a paisa.
# See core/engine.py's _try_structural_entry().
ORB_STOP_BUFFER_PCT = 0.2

# Operator override, 2026-07-23 ONLY: today's stop-outs -- both
# the ~146 losing round-trips already in trade_log.csv and the
# 36 legacy open positions restored with their old too-tight
# stops -- don't reflect a genuine "the breakout failed" signal,
# they reflect the bug above (stop seeded from a paise-wide
# candle instead of the ORB boundary). Blocking those symbols
# from re-entering today would be punishing them for OUR error,
# not theirs. So the "one attempt per direction per day" rule
# (core/engine.py's _exit()) is switched OFF for today only --
# every symbol may re-attempt either direction as many times as
# a genuine signal fires, same as before that rule existed.
#
# SET THIS BACK TO True for the next trading session -- the rule
# itself is sound (it's what stopped BLUESTONE/IDEA/WAKEFIT/
# JYOTHYLAB from whipsawing 3-4x each that morning); today is
# the one-off exception, not a permanent rollback.
#
# Reverted to True on 2026-07-23 evening for the 2026-07-24 (Friday)
# session, per the instruction above -- today's exception is over,
# and it stands independently of TOP_N_MOMENTUM_MODE below (a
# stop-out in the new fixed-bracket mode is just as much "this
# breakout already failed today" as a trailing-stop-out was).
BLOCK_REENTRY_AFTER_STOPOUT = True

# ----------------------------------------------------------
# Top-N momentum mode (operator-designed 2026-07-23 evening, for
# the 2026-07-24 (Friday) session -- see core/momentum_universe.py)
# ----------------------------------------------------------
#
# Operator's own words: "what bot must do is simple. take best 25
# long positions & 25 short positions keep the Stop loss & targets
# as fixed... best in my terms top trending stocks in both cases =
# top 25 gainers & top 25 losers."
#
# This is a deliberate, testable EXPERIMENT, not a claimed final
# answer -- the operator was explicit that fixed rules are not
# expected to be the permanent design ("no fixed rules will work in
# stock market, bot must change/adapt"). The point of this session
# is to establish a real, measured baseline (this exact rule set,
# against this exact day's market) to compare a future adaptive
# design against -- you can't build "adapt when X" without first
# knowing what X actually looks like in real trade data, which is
# what today's all-750-symbols/dynamic-trailing approach hasn't
# given a clean read on (too many symbols, too much dynamic sizing
# noise to isolate a single variable).
#
# Toggle: True routes every new structural entry through the
# narrowed universe + fixed bracket below. False (the previous
# behaviour) leaves the full 750-symbol universe and the ORB-
# boundary-seeded dynamic trailing stop (core/trailing_stop.py)
# completely untouched -- flip back instantly if Friday's read
# says this isn't working, no code changes needed either way.
TOP_N_MOMENTUM_MODE = True

# How many symbols on each side. Locked ONCE, right when the ORB
# window closes (ORB_WINDOW_END above) -- see
# core/momentum_universe.py's lock(). Top N by %-change-vs-day-open
# become the ONLY LONG-eligible symbols; bottom N become the ONLY
# SHORT-eligible symbols, for the rest of the day. Everything
# outside these 2*N symbols is skipped silently (no entry_blocked
# ledger entry -- that ledger is for news/sector REASONS a specific
# signal was refused, not "wasn't in today's shortlist", and 700+
# such skips a day would just be noise there).
TOP_N_MOMENTUM_LIST_SIZE = 25

# Fixed target and stop-loss, in RUPEES of total position P&L (not
# percent, not per-share) -- operator's own numbers: "P:L at 2500 :
# 1000 rs". A LONG's target/stop PRICE levels are derived from
# these at entry (entry_price +/- amount/qty); a SHORT mirrors it.
# Deliberately NOT the trailing stop -- operator's explicit choice,
# "keep the Stop loss & targets as fixed" -- see
# core/engine.py's _check_fixed_bracket(). No ratcheting, no riding
# a winner past the target: closes the instant either level is hit.
FIXED_TARGET_RS = 2500.0
FIXED_STOP_LOSS_RS = 1000.0

# ----------------------------------------------------------
# News contradiction + sector panic (both operator-approved,
# 2026-07-23 -- see core/engine.py's _try_structural_entry() and
# core/sector_monitor.py)
# ----------------------------------------------------------

# A sector is flagged "panic" -- broadly, sentiment-driven
# selling, not one or two names dragging an average down --
# when BOTH of these hold at once. Deliberately blunt, breadth-
# only thresholds (not news-matching-based -- see
# core/sector_monitor.py's own docstring for why): average
# change across the sector's stocks (vs each stock's own day-
# open) is at or below this percentage...
SECTOR_PANIC_AVG_CHANGE_PCT = -1.5

# ...AND at least this fraction of the sector's stocks (with
# data so far today) are individually declining, not just the
# average being dragged down by one or two names.
SECTOR_PANIC_MIN_DECLINE_RATIO = 0.65

# Sectors with fewer than this many stocks reporting data yet
# are never flagged -- too few names for "broad" to mean
# anything, just noise.
SECTOR_PANIC_MIN_SYMBOLS = 3

# ----------------------------------------------------------
# Paper capital (dashboard display/tracking only)
# ----------------------------------------------------------

# Starting paper capital for the session, operator-chosen.
# This is a DISPLAY/TRACKING ledger only -- it does NOT gate
# new entries. There is no capital-based sizing or exposure
# cap yet (that's real Phase 2 scope, PHASES.md). With
# LAYER1_FIXED_QTY=100 and no cap on concurrent positions
# across 750 symbols, deployed notional CAN exceed this number
# on a strong trending day -- the dashboard will show that
# honestly (capital can go negative) rather than silently
# blocking trades to hide it.
PAPER_STARTING_CAPITAL = 1_000_000.0

# ----------------------------------------------------------
# MIS (margin intraday) leverage -- operator-approved 2026-07-23
# ----------------------------------------------------------

# Real MIS margin is broker- AND stock-specific (SEBI peak-margin
# rules, ASM/GSM-restricted names get reduced or zero leverage) --
# modeling every stock's real number would need Dhan's margin API,
# not built yet. This is a deliberate, documented simplification:
# ONE flat multiplier applied to every stock alike, same
# "crude placeholder, not real, revisit later" spirit as
# LAYER1_FIXED_QTY. Operator's own estimate was 3.5x-5x depending
# on broker; 4x is the mid-point.
#
# THIS ONE GATES ENTRIES -- unlike PAPER_STARTING_CAPITAL's
# available_capital/realized_pnl (display-only, trading/
# portfolio.py), buying power actually blocks a new position from
# opening once it's used up (core/engine.py's _enter()). See
# trading/portfolio.py's own docstring for the full split.
MIS_LEVERAGE_MULTIPLIER = 4.0

# ----------------------------------------------------------
# Dashboard -- sector heatmap
# ----------------------------------------------------------

# The broad SECTOR heatmap can dilute a real rally: e.g.
# "AUTOMOBILE" (53 symbols in master_stocks.csv) mixes 13 OEM
# majors (MARUTI, TVSMOTOR, HEROMOTOCO, BAJAJ-AUTO, ...) with 27
# unrelated auto-component makers, 5 tyre makers, 2 battery
# makers, etc. -- an unweighted average across all 53 can mask a
# genuine move in the 13 names an operator actually means by
# "auto sector today". The INDUSTRY column (master_stocks.csv,
# 177 distinct values) is finer-grained and gives a "core sector"
# view alongside the existing broad one. Mirrors the same
# too-few-symbols-is-noise idea as SECTOR_PANIC_MIN_SYMBOLS in
# core/sector_monitor.py -- 82 of the 177 industries have only 1
# stock and would be meaningless to average alone, so those are
# left out of the core heatmap entirely (they still count inside
# their broad SECTOR bucket).
#
# NOTE: because INDUSTRY is a finer split than SECTOR, a handful
# of stocks an operator might expect to see together intuitively
# (e.g. M&M under "TRACTORS / FARM EQUIPMENT - AUTOMOBILE",
# BOSCHLTD under "AUTO COMPONENTS") land in different, smaller
# industry buckets than the OEM majors (MARUTI, TVSMOTOR, ... in
# "AUTOMOBILES - OEM") -- this is the data being genuinely more
# specific, not a bug to route around.
INDUSTRY_HEATMAP_MIN_SYMBOLS = 3

# ----------------------------------------------------------
# Dashboard
# ----------------------------------------------------------

DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 8000

# How often the live snapshot (capital, PnL, watchlists, ...)
# is rebuilt and pushed to connected dashboard clients. Kept
# short for a responsive feel, but never driven off every tick
# directly -- rebuilding a 750-symbol snapshot on every single
# tick would be exactly the kind of thing that could slow the
# trading engine down, which is the one thing this must never
# do.
DASHBOARD_REFRESH_INTERVAL_SECONDS = 1

# ----------------------------------------------------------
# Logging
# ----------------------------------------------------------

LOG_DIR = "logs"
TRADE_LOG_PATH = os.path.join(LOG_DIR, "trade_log.csv")
DIAGNOSTIC_LOG_PATH = os.path.join(LOG_DIR, "diagnostics.log")

# Console stays clean by default -- only real decisions and
# results print live. Full detail always goes to the file.
VERBOSE_CONSOLE = False
