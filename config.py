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

# No FRESH structural entries after this time -- existing positions
# are still managed (trail/partial/square-off) normally. 2026-07-24
# revamp: the operator's own verified observation (POST_MARKET item
# 10 -- 72% of the universe goes essentially flat after ~10:30, avg
# candle range halves) says late-day breakouts are mostly noise; a
# brand-new position opened at 14:50 has ~25 minutes to work before
# forced square-off, which isn't a trade, it's a coin flip with a
# deadline. Conservative first cut -- tighten toward midday later if
# the data keeps supporting it.
# Revised 2026-07-25 (operator decision): trade the FULL session. The
# 14:30 cutoff was a reasoned guess that cost us real trades -- on
# 2026-07-24 the two best entries of the day were 13:50 and 13:51, and
# nothing in the data says 14:35 is different from 13:55. Entries now
# close at 15:00, leaving 15 minutes before the 15:15 hard square-off.
# Kept in lockstep with STAGED_NO_ENTRY_AFTER.
LAST_ENTRY_TIME = "15:00"

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

# --- Feed staleness console-noise controls, 2026-07-24 (evening) #2 ---
# The 5s threshold above trips constantly for two totally harmless
# reasons: (1) at 09:15 open and on EVERY restart, the feed dumps all
# ~750 symbols at once and a big batch briefly crosses 5s (all
# clustered at 5-7s, cleared within a minute); (2) in the afternoon
# lull, thin mid-caps genuinely don't trade every 5s (340 "stale" at
# 14:53 while our processing backlog was 0). Neither is a real feed
# problem, but both spammed the console.
#
# Warm-up grace: for this many seconds after startup / first tick,
# staleness goes to the FILE log only -- no console warnings -- so a
# normal connect/open burst comes up clean.
FEED_WARMUP_GRACE_SECONDS = 60

# Systemic alarm: instead of one console line per stale symbol
# (afternoon-lull spam), the console only warns when a LARGE share of
# the symbols we've actually seen are stale AT ONCE -- the signature
# of the feed genuinely lagging, not a few quiet stocks. Individual
# stale events always go to the file log. 0.5 = warn once if >=50% of
# seen symbols are stale together; today's normal 45% afternoon lull
# stays quiet, a real stall (85%+ like the 09:15 processing backlog)
# would trip it.
FEED_SYSTEMIC_STALE_FRACTION = 0.5

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
# snapshot into the Top N gainers/losers table. Originally 300s
# ("for every 5 mins"), changed to 60s on 2026-07-24 (operator's own
# instruction, dashboard timing sync pass) -- Top 50 Gainers/Losers
# is deliberately still much slower than the Sector Heatmap below
# (a display table doesn't need to reshuffle every few seconds to be
# useful), just less deliberately slow than the original 5 minutes.
GAINERS_LOSERS_REFRESH_SECONDS = 30  # operator: "refreshes every 30 secs"

# Sector Heatmap (Top Gaining/Losing Sectors) -- decoupled from the
# stock-level table above, 2026-07-24, operator's own instruction:
# "Market Breadth - 5secs, Top 50 Gainers & Losers - 1 min, Sector
# Heatmap - 5 secs." Both tables are built from the SAME underlying
# per-symbol pass (core/circuit_monitor.py's snapshot, re-read and
# re-aggregated independently by each -- see dashboard/state.py's
# _build_stock_gainers_losers() / _build_sector_gainers_losers()),
# just cached and re-ranked on two different clocks now instead of
# one shared one.
SECTOR_GAINERS_LOSERS_REFRESH_SECONDS = 5

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

# Dashboard sector heatmap shows only the TOP N gaining + TOP N
# losing sectors (2026-07-24 operator request) -- we trade only the
# day's momentum sectors, so listing all ~29 is noise (and a small
# per-refresh burden). 10 each = the 20 that matter.
SECTOR_HEATMAP_TOP_N = 10

# ----------------------------------------------------------
# Data-sanity filters for breadth / gainers-losers, 2026-07-24 --
# two real, distinct problems the operator caught live:
#   1. JLHL did a 2:10 stock split; our stored prev_close wasn't
#      adjusted for it, so Market Breadth/Top Losers showed a fake
#      ~-80% "decline" that never actually happened.
#   2. CEMPRO was locked at its 5% lower circuit -- zero real order
#      flow -- but still ranked in Top Losers next to genuinely
#      liquid, tradeable movers.
# ----------------------------------------------------------

# A split/bonus/rights issue our prev_close isn't adjusted for
# produces an impossibly large %-change. The exchange's OWN circuit
# band for today (upper/lower_circuit_limit, computed off the
# correct, adjusted reference) caps how far a GENUINE move can go --
# category-dependent, 2/5/10/20%. If the observed |change_pct|
# exceeds the widest edge of that band by more than this multiple,
# it's mathematically impossible as real intraday price action --
# our prev_close must be stale, not the stock (see
# dashboard/state.py's _is_plausible_move()). 1.5x gives comfortable
# margin above a genuine gap day while still catching every
# realistic split/bonus ratio -- even the smallest common one (1:2)
# is a ~50% "move", well past even the widest 20% band x1.5=30%.
SANITY_BAND_MULTIPLE = 1.5

# A stock trading AT (not just near) its circuit limit is treated as
# "locked" -- last_price within this fraction of the limit (a small
# float-rounding tolerance, NOT a proximity warning zone --
# CIRCUIT_PROXIMITY_PCT above already owns that, separate concern).
# See dashboard/state.py's _is_circuit_locked().
CIRCUIT_LOCK_TOLERANCE_PCT = 0.001

# ----------------------------------------------------------
# Minimum tradable price -- hard floor, 2026-07-24, operator's own
# real-trading rule: "never trade in stocks which are lower than 200
# rs price range (if ltp<=199 no trade in that, no matter what)."
# Distinct from (and stricter than) the ATR sizing above -- ATR
# already sizes a cheap stock differently, but this is a flat
# EXCLUSION, not just a different size: a sub-Rs 200 stock's price
# movement behaves differently enough (operator's earlier words:
# "the movement of the stock under 200 rs is very different to
# above 2000 rs") that it's not traded AT ALL, no exception. "No
# matter what" -- checked in core/engine.py's _enter(), the one
# funnel every entry path goes through (structural LONG/SHORT,
# manual buy, manual short alike), same non-overridable treatment as
# the margin/buying-power gate, NOT the news/sector checks a manual
# override is allowed to bypass.
# ----------------------------------------------------------
MIN_TRADABLE_PRICE_RS = 200.0

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
# DISABLED 2026-07-27, same reasoning as ONE_TRADE_PER_SYMBOL_PER_DAY
# above: this rule and that one together meant a single stop-out
# permanently retired a stock for the day. CAPLIPOINT was refused at
# 09:32:42 ("stopped out once today -- no repeat attempts") in the
# strongest tape of the month, four minutes after being trailed out
# at +0.22%. The stop-out was caused by a 0.4% trail floor, not by
# the setup failing. Punishing the stock for our exit is backwards.
#
# REVERTED to True 2026-07-27, operator's decision, same session, and
# for the same reason as ONE_TRADE_PER_SYMBOL_PER_DAY above: the case
# for removing it was intraday reasoning, and the system is moving to
# multi-day MTF holds where a stop-out means something different.
# Re-assess against MTF, do not remove on the old argument.
#
# NOTE: the load_entry_blocks() filter added today still stands and is
# still correct -- it only drops restored blocks when this flag is
# OFF, so with the flag back ON nothing is dropped. It exists so that
# turning the rule off in future actually turns it off, instead of
# leaving yesterday's saved blocks silently enforcing a dead rule.
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

# Fixed target and stop-loss, in RUPEES of total position P&L --
# operator's original numbers from the first live session ("P:L at
# 2500 : 1000 rs"). SUPERSEDED 2026-07-24 by the ATR-based sizing
# block below, after two real problems surfaced watching that first
# session: a flat qty=100 treats a sub-Rs 200 stock and a Rs 2000+
# stock identically even though their real price MOVEMENT is
# completely different ("not ideal for all market days" -- the
# operator's own words), and a flat Rs 2500/1000 bracket is the same
# distance for every stock regardless of how much it typically
# actually moves. Left here, unused by the current entry path,
# purely as a record of what the very first test day actually ran
# with -- do not delete, do not repurpose these two names.
FIXED_TARGET_RS = 2500.0
FIXED_STOP_LOSS_RS = 1000.0

# ----------------------------------------------------------
# ATR-based sizing, stop, and trail (TOP_N_MOMENTUM_MODE only)
# -- 2026-07-24, replaces the flat qty / fixed rupee bracket
# above (see its comment for why).
# ----------------------------------------------------------

# ATR (Average True Range) measures a stock's own typical
# candle-to-candle range -- how far it usually moves, not how far
# it moved on any one candle. Computed from THIS SESSION's own
# 1-minute candles (core/candle_engine.py), not a separate
# historical-data feed -- see core/atr.py's module docstring for
# why a plain rolling average is used instead of Wilder smoothing.
# By the earliest a structural signal can ever fire (right after
# ORB_WINDOW_END, 09:30), a normally-ticking symbol already has
# ~15 one-minute candles, comfortably enough for a 14-period ATR.
ATR_PERIOD = 14

# Thin/illiquid symbols with fewer real closed candles by the time
# they'd otherwise enter fall back to whatever's available down to
# this floor; below it, the entry is skipped outright (silent skip,
# same pattern as the frozen-price/circuit-proximity checks) rather
# than sized off an ATR reading built from 1-2 candles, which is
# closer to noise than a real volatility read.
MIN_ATR_CANDLES = 5

# Fixed rupee RISK per trade, not target/stop rupees -- qty is now
# DERIVED so every trade risks roughly the same amount regardless of
# the stock's own price or volatility: qty = RISK_PER_TRADE_RS /
# (ATR_STOP_MULTIPLIER * ATR). A cheap, choppy stock gets fewer
# shares (wide ATR in rupee terms); a quiet, steady stock gets more.
# Kept at the same Rs 1000 the old fixed stop used, so today's
# risk-per-trade budget doesn't silently change alongside the
# sizing method -- tune independently once there's real data.
# 2026-07-24 (evening) LEVER 2 -- scaled up from Rs 1,000 to Rs
# 2,000 per trade. At the tiny Rs 500-effective size, hitting a
# Rs 50k day would take hundreds of trades (charges make that
# impossible); the path to a real day is bigger winners AND bigger
# size, not more trades. Still PAPER -- this is the safe place to
# test whether the bigger size behaves. Paired with the Rs 200,000
# notional cap below so the full Rs 2,000 risk actually gets used
# (at a 1% stop, qty wants 100 x risk = Rs 200k of notional).
# APPLIED 2026-07-27. The comment block above has said Rs 2,000 since
# 2026-07-24; the value said 800.0 and nobody moved it. Rs 800 on
# Rs 10L of capital is 0.08% risk per trade -- roughly 15x smaller
# than standard position sizing (0.5-2%), which is how a flat Rs 117
# of charges came to eat 14.7% of everything risked. Paired with the
# 1.0% stop floor below, Rs 2,000 / 1% = exactly the Rs 200,000
# notional cap, which is what that cap was sized for.
RISK_PER_TRADE_RS = 2000.0

# Initial stop distance, in ATR multiples, from entry.
# 2026-07-24 (evening) WIDENED from 1.5x to 2.5x after the operator's
# core observation, proven by the day's own trades: a stop tighter
# than the stock's normal noise is a GUARANTEED loser -- it gets
# clipped by ordinary bid-ask jiggle before the trade can ever work
# (HEG stopped out on a 0.08% move, ACUTAAS on 0.02%). In a quiet
# market the raw ATR is tiny anyway, so MIN_STOP_DISTANCE_PCT below
# (now 1% of price) is what actually does the work most of the time;
# this wider multiple only matters for genuinely volatile names.
ATR_STOP_MULTIPLIER = 0.8

# Trailing distance, in ATR multiples, from the highest high (LONG)
# / lowest low (SHORT) SINCE ENTRY -- recomputed on every closed
# candle, never loosened (see core/engine.py's _check_atr_trailing()).
# No fixed target: the position rides until this trail is hit or
# square-off. 2026-07-24 (evening): widened to 2.5x alongside the
# initial stop AND paired with the trail-activation rule below, so a
# trade "stays in while it moves and only exits on a real reversal"
# (operator's own words) instead of being trailed to death at
# breakeven seconds after entry.
ATR_TRAIL_MULTIPLIER = 1.2

# The trail does NOT start tightening the stop until the trade is at
# least this many ATRs in PROFIT from entry. Before that milestone,
# the wide initial stop just sits there giving the trade room to
# breathe -- this is the fix for "stopped out at breakeven right
# after entry": a small favourable wiggle can no longer drag the
# stop up to where the next small unfavourable wiggle exits it. Only
# once the trade has genuinely run in your favour does the stop begin
# to follow it up (locking in profit), trailing this same distance
# behind the best price seen. 1.0 = "prove one full stop-distance of
# profit first, THEN start protecting it."
ATR_TRAIL_ACTIVATION_MULT = 1.0

# ----------------------------------------------------------
# ATR sizing safety floor/ceiling, 2026-07-24 -- operator's live
# report: SWIGGY entered SHORT 11:37:07 with qty=2522 and a 46-paise
# stop. Back-solved: ATR read Rs 0.264 at that instant (a thin/quiet
# candle window), so ATR_STOP_MULTIPLIER * ATR came out smaller than
# ordinary bid-ask noise -- and RISK_PER_TRADE_RS / that tiny
# distance inflated qty to compensate, producing ~Rs 6.2 lakh of
# notional on what the system still thought was a Rs 1,000-risk
# trade. Same root cause hit 7/7 trades this session (GODIGIT, IGIL,
# SRF, HEG, ICICIGI, TIPSMUSIC, PVRINOX) -- every stop distance was
# 0.12%-0.24% of price, inside normal 1-minute chop, so the trade
# was statistically close to pre-doomed regardless of direction.
# These two constants are a hard backstop UNDERNEATH the ATR
# formula, not a replacement for it -- see _atr_entry_sizing() and
# _update_atr_trailing_on_candle_close() in core/engine.py for
# exactly where each is applied.
# ----------------------------------------------------------

# Floor under the ATR-based stop distance, as a PERCENT OF PRICE --
# never a raw rupee number, so it scales with the stock. Actual
# stop/trail distance used is
# max(ATR_multiplier * ATR, MIN_STOP_DISTANCE_PCT * price) -- i.e.
# whichever is WIDER wins. Applied to both the initial entry stop
# and the ongoing trailing ratchet, so a stock that goes quiet mid-
# trade can't develop a razor-thin trail either. 0.5% is a starting
# point (tune once there's real data on how often it binds vs the
# raw ATR distance) -- roughly Rs 1.25 on a Rs 250 stock like
# SWIGGY, Rs 13+ on a Rs 2,680 stock like SRF, both comfortably
# outside single-tick noise.
#
# 2026-07-24 (evening): RAISED from 0.5% to 1.0%. The day's trades
# showed 0.5% was still too tight for the chandelier trail -- a
# normal intraday pullback exited trades at breakeven. 1% gives a
# real cushion: a Rs 600 stock now has Rs 6 of room, not 50 paise,
# and the trade only exits on a genuine ~1% reversal from its peak,
# not on noise. This floor applies to BOTH the initial stop and the
# trailing distance, so neither can ever be razor-thin regardless of
# how small the raw ATR reads.
# APPLIED 2026-07-27. The comment above has said 1.0% since
# 2026-07-24 ("a Rs 600 stock now has Rs 6 of room, not 50 paise");
# the value said 0.004 and nobody moved it. Live proof on 2026-07-27:
# CAPLIPOINT entered 09:26:10, trailed out 09:32:42 at +0.22% in an
# 88/100 bullish tape -- a winner closed by the trail floor after six
# minutes. Across 61 sessions the 0.4% floor put 75% of all exits on
# the stop and left 8 trades out of 1,957 still open at the bell.
MIN_STOP_DISTANCE_PCT = 0.01

# Hard ceiling on notional exposure (qty * entry_price) for any ONE
# trade, regardless of what the risk/ATR formula computes. Backstop
# for the SAME failure mode from the other side -- even with the
# stop floor above, a very cheap stock could still size up large
# before RISK_PER_TRADE_RS / stop_distance runs out of budget. If
# the risk-sized qty would exceed this, qty is capped down to
# MAX_NOTIONAL_PER_TRADE_RS / entry_price instead (see
# _atr_entry_sizing()). 2026-07-24 (evening) LEVER 2: raised
# Rs 50,000 -> Rs 200,000 so the bigger Rs 2,000 risk budget
# actually gets deployed instead of being halved by the cap. 10
# concurrent x Rs 200k = Rs 20L of margin, inside the Rs 40L MIS
# buying power (Rs 10L x 4). Still a placeholder -- tune with a real
# capital-allocation policy (Phase 2, PHASES.md).
MAX_NOTIONAL_PER_TRADE_RS = 200_000.0

# ----------------------------------------------------------
# 2026-07-24 REVAMP -- trading-policy gates (see TRADING_POLICY.md
# for the complete decision path in plain language). These four
# blocks together are the answer to POST_MARKET items 1, 4, 5 and
# 10, and to the operator's core question (item 9): "why no profit
# even with 654/750 falling" -- because the bot was fighting the
# tape (longs into a falling market), trading noise-thin breakouts,
# taking fresh entries into the dead afternoon, and had no concept
# of 'enough' in either direction (no daily loss stop, no daily
# goal). Every gate below applies to STRUCTURAL entries only --
# manual buy/short remain a deliberate human override throughout.
# ----------------------------------------------------------

# --- Market-regime gate (item 1: "market-regime brain") ---
# When the broad tape is one-sided, only trade WITH it: if >=
# REGIME_BREADTH_THRESHOLD of the universe (with usable prev_close
# data, via circuit_monitor's REST snapshot -- same source the
# dashboard breadth panel uses) is DECLINING, LONG entries are
# blocked (shorts only). Mirrored for advancing/SHORT. In between,
# both directions stay open. Recomputed at most every
# REGIME_REFRESH_SECONDS (cached -- this must never add a REST-
# lookup to the tick path). Fewer than REGIME_MIN_SYMBOLS usable
# rows = no opinion, both directions allowed (fail-open: a thin
# snapshot right at 09:15 shouldn't lock the bot one-sided).
REGIME_GATE_ENABLED = True
REGIME_BREADTH_THRESHOLD = 0.60
REGIME_REFRESH_SECONDS = 30
REGIME_MIN_SYMBOLS = 100

# --- Risk guardrails (items 4 & 5: cap + explicit daily goal) ---
# Hard cap on CONCURRENT open positions. 131 concurrent positions
# (2026-07-23) is not a strategy, it's spray-and-pray -- and in live
# trading each one ties up real margin. 10 forces the bot to be
# selective: once full, new signals are skipped until a slot frees.
MAX_OPEN_POSITIONS = 10

# ==========================================================
# TREND-RANK ENTRY PRIORITY + SLOT ROTATION  (2026-07-24)
# ==========================================================
# The operator's core thesis, proven in backtest/ against the live
# session: "sail with the trend -- trade the top gainers LONG and the
# top losers SHORT, not the first names to twitch past their range."
# The old 10-slot cap filled first-come at 09:34 and squatted all day,
# locking out the real movers (GODIGIT -6%, ACE +2.3%, MOTILALOFS -3.5%
# all broke out to a FULL book on 2026-07-24). These two dials fix that.
#
# Ranking source: circuit_monitor's REST snapshot (%change vs previous
# close -- the same data the dashboard gainers/losers use). Cached, no
# new network calls. Fail-open everywhere: no snapshot / thin snapshot
# -> gate disabled, behaves exactly as before.

# Only take a LONG breakout in a symbol currently ranked in the top
# TREND_RANK_TOP_N gainers, and a SHORT only in the top N losers. A
# breakout OUTSIDE the leaderboard is range noise, not a trend.
# DISABLED 2026-07-27, measured against that day's own tape.
#
# This rule refuses a breakout unless the stock is ALREADY in the day's
# top 20 movers. But a breakout is, by definition, the moment BEFORE the
# move. Requiring the stock to have already run is requiring it to be
# late.
#
# 2026-07-27 was strongly bullish (regime LONG_ONLY, 518 advancing vs
# 171 declining). Twelve stocks finished between +6.65% and +11.24%.
# The bot traded NONE of them and closed the day flat with two dead
# scalps. Every one of the twelve was subscribed and recorded tick by
# tick all day -- so this was not a universe, data or liquidity problem.
#
# Their rank AT THE MINUTE THEY BROKE THEIR OPENING RANGE:
#
#     REDINGTON  09:33  +0.88%  rank 173 of 670  -> closed +7.20%
#     CONCOR     09:54  +2.69%  rank  32 of 658  -> closed +6.65%
#     LAURUSLABS 10:01  +2.65%  rank  39 of 653  -> closed +7.92%
#     TMB        13:44  +3.32%  rank  37 of 618  -> closed +8.42%
#
# All four refused for not yet being in a top 20 they went on to lead.
#
# What still enforces quality without the look-back problem:
# RS_BAND_MIN below already requires the stock to be OUTPERFORMING the
# market at entry (>= +0.4%), which is the real signal; the rank filter
# was a cruder proxy for the same idea, applied to the wrong instant.
ENABLE_TREND_RANK_ENTRY = False
TREND_RANK_TOP_N = 20
TREND_RANK_REFRESH_SECONDS = 5   # recompute the leaderboard at most this often

# Slot rotation: when the book is FULL and a new breakout is decisively
# stronger (by ROTATION_MIN_STRENGTH_EDGE of %-move) than the weakest
# current holder, close the laggard and take the stronger name. A seat
# is no longer taken for the whole day by whoever grabbed it first.
# Strength = %change in the trade's own favour (gainers for longs,
# losers for shorts), so a winning runner is never the weakest and is
# never rotated out -- only stalling laggards are.
# DISABLED 2026-07-27. The clearest single defect in the system.
# Across 61 sessions rotation fired 293 times for GROSS -Rs 8,509 --
# negative BEFORE charges -- and -Rs 42,734 after. It was not evicting
# laggards for winners; it was closing positions at a loss and paying
# Rs 117 for the privilege, 293 times. MULTIDAY_FINDINGS.md section 2.
# It is also a rule we invented, not a market fact.
ENABLE_SLOT_ROTATION = False
ROTATION_MIN_STRENGTH_EDGE = 0.004   # challenger must lead by >0.4% move

# ==========================================================
# 2026-07-25 STRATEGY PACKAGE (from the replay-bench study)
# ==========================================================
# Measured on 2026-07-24's 985 real breakout signals (see
# FINDINGS.md). Four results drove this block:
#   1. RELATIVE strength (vs the market) separates winners from
#      losers (39% vs 14.5% hit rate). ABSOLUTE strength does not
#      (losers were slightly stronger).
#   2. The relationship is an INVERTED U -- the very strongest
#      names are EXHAUSTED and underperform. So we select a BAND,
#      never "the top N".
#   3. Fixed profit targets destroy expectancy (a Rs1100 target
#      gave a 53.6% win rate and -Rs15,714). No targets.
#   4. 30% base hit rate at 2:1 payoff = -0.1R. Selection has to
#      do the work; volume of trades only adds cost.

# --- LONG ONLY --------------------------------------------
# 2026-07-27, operator's decision, and the best-evidenced change
# in the whole file.
#
# Across 61 replayed sessions (MULTIDAY_FINDINGS.md section 1):
#
#     LONG    922 trades   gross +Rs 65,546   (+Rs 71/trade)
#     SHORT  1035 trades   gross  +Rs 2,450   (+Rs  2/trade)
#
# Shorts were 53% of everything the bot did and 3.6% of the gross.
# Rs 2,450 across 1,035 trades is indistinguishable from zero, and
# roughly Rs 121,000 of charges were paid to collect it. This is not
# a threshold to re-tune -- continuation on the short side is noise
# at this timeframe, so the direction is switched off entirely.
#
# Enforced in core/engine.py's _try_structural_entry, before any
# other gate, so a short signal costs nothing to refuse.
ENABLE_SHORT_TRADES = False

# --- Relative-strength BAND selection ---------------------
# Trade only breakouts whose move-vs-market sits inside this band:
# strong enough to be real, not so extended it's spent.
ENABLE_RS_BAND = True
RS_BAND_MIN = 0.004      # >= +0.4% vs the market median move
# CEILING LIFTED 2026-07-27, from 5.0%.
#
# The "exhaustion" idea behind this ceiling came from ONE Friday of
# partly-corrupt data. POST_MONDAY_TODO.md section B already listed it
# as "fitted to corrupted data. Guess."
#
# What it actually did, measured on 2026-07-27: CARTRADE broke its
# opening range at 09:33 as the SINGLE STRONGEST STOCK ON THE BOARD --
# rank 1 of 670 -- with a relative strength of 5.41%. Refused for being
# 0.41 of a percentage point too strong. It closed the day +11.24%.
#
# A rule that rejects the best stock of the day for being too good is
# not a risk control. Note also that it worked in direct opposition to
# the top-20 rank filter above: that one demanded the stock had already
# moved, this one refused it once it had. Between them they left a
# narrow window that the day's actual winners passed straight through.
#
# The genuine protection against a parabolic blow-off is
# MAX_ABS_MOVE_PCT (12% from the day's OPEN) further down -- that is a
# real guard with a mechanism, and it stays. This band keeps its FLOOR,
# which is the part carrying the signal: the stock must be outperforming
# the market to qualify at all.
RS_BAND_MAX = 0.50       # effectively no ceiling; blow-off guard does that job
# Absolute-move ceiling regardless of RS (the APAR/parabolic guard).
# REPLACED 2026-07-25 (operator challenge). A flat "% moved today"
# ceiling is the wrong test: it blocks the day's BEST trending stock,
# because the best trend is by definition the one that moved most.
#
# The right question is not "how far has it moved" but "is it STILL
# moving, or has it rolled over?" Two stocks both up 7%:
#   A is at 428 and 428 IS the day's high -> still making highs, this
#     is the trend of the day.
#   B peaked at 432 and is back to 428 -> fading, the move is spent.
# The old rule blocked both identically.
#
# So: a long must be trading in the TOP part of today's range, a short
# in the BOTTOM part. Position 1.0 = at the day's high, 0.0 = at the low.
# Generous by design (0.65) -- this is a "not rolling over" check, not a
# "must be at the exact high" check.
# DISABLED 2026-07-27. POST_MONDAY_TODO.md section B lists this rule's
# status as "CONTRADICTED on 2026-07-24" and it has never been
# validated since. It is one of twelve entry gates, none of which the
# 61-session corpus supports, and together they produced 2 trades on a
# day the operator correctly read as strongly bullish. Off until it
# earns its place in a replay, not before.
ENABLE_STILL_TRENDING = False
STILL_TRENDING_MIN_POSITION = 0.65

# The flat ceiling stays ONLY as a blow-off guard, raised well clear of
# normal trending (APAR-class parabolic moves). It no longer does the
# day-to-day filtering.
MAX_ABS_MOVE_PCT = 0.12

# --- Staged deployment ------------------------------------
# Never fill all 10 seats in the opening minute (2026-07-24: 11 of
# 27 entries fired in the single 09:34 minute). Ramp with the day.
ENABLE_STAGED_ENTRY = True
# REMOVED 2026-07-27 (operator): "does the market work as per your
# rule and give 2 opportunities before 10, 5 after 10, 10 before 12?"
# It does not. The ladder was listed in POST_MONDAY_TODO.md section B
# as "reasoning only" -- never measured, never validated -- and on
# 2026-07-27 it meant a strongly bullish tape (88/100) produced two
# trades before 10:00 and nothing after, because both early seats
# were spent by 09:26 and the ladder capped the rest.
#
# The ladder was built for ONE real problem: on 2026-07-24, 11 of 27
# entries fired inside the single 09:34 minute. That problem is real,
# but a time ladder is the wrong tool -- it throttles the whole day to
# fix one minute. MAX_OPEN_POSITIONS still caps total exposure, which
# is what actually protects margin.
#
# Now a single flat limit for the whole session. Opportunity decides
# the timing, not the clock.
STAGED_POSITION_LIMITS = [
    ("15:29", 10),   # one limit, all day
]
# No fresh entries after this. Set to 15:00 (2026-07-25): the earlier
# 14:00 cutoff threw away the afternoon, and on 2026-07-24 the two BEST
# trades of the day were entered at 13:50 and 13:51. Positions still
# flatten at SQUARE_OFF_TIME (15:15) regardless.
STAGED_NO_ENTRY_AFTER = "15:00"

# --- One trade per stock per day --------------------------
# A symbol gets ONE attempt per direction per day. Kills the
# whipsaw churn (CHENNPETRO traded 9x, CORONA 6x on 2026-07-24).
#
# RELAXED 2026-07-27. The churn it was built to stop was a symptom of
# a 0.4% stop inside normal noise -- CHENNPETRO was re-entered 9 times
# because it was stopped out 9 times, not because re-entry is wrong.
# With the stop at 1.0% and the no-progress timer off, the churn cause
# is treated directly, and a permanent same-day ban on the day's
# strongest stock is a bigger cost than the churn ever was: on
# 2026-07-27 it locked out CAPLIPOINT at 09:32 in an 88/100 bullish
# tape, for the rest of the session.
#
# REVERTED to True 2026-07-27, operator's decision, same session.
# The churn this stops is real (CHENNPETRO 9x, CORONA 6x) and the
# argument for removing it was built on INTRADAY behaviour. The system
# is moving to MTF multi-day holds, where the whole premise changes: a
# position held for days is not re-entered anyway, and a stop-out on a
# multi-day trade is a far stronger signal than a stop-out on a
# six-minute one. Stays ON until it is assessed against MTF holding,
# not removed on intraday reasoning that no longer applies.
ONE_TRADE_PER_SYMBOL_PER_DAY = True

# --- No-progress exit -------------------------------------
# Dead money: a position that hasn't reached +NO_PROGRESS_R of its
# risk within the window isn't working -- close it and free the
# slot (BHARTIARTL squatted a seat until 15:10 doing nothing).
#
# DISABLED 2026-07-27. This rule is expressed as a fraction of R, so
# raising RISK_PER_TRADE_RS silently raises the bar it demands: at
# Rs 800 risk it asked for Rs 400 of profit in 30 minutes, at Rs 2,000
# it asks for Rs 1,000. Replayed over the 61 sessions with risk at
# Rs 2,000 it went from closing 10% of all trades to closing 41% of
# them -- it became the single largest exit reason in the system,
# killing trades before they could work. On the first 3 sessions,
# turning it off moved the result from -Rs 15,706 to +Rs 10,376.
#
# Three sessions is not proof. But a rule that changes its own
# strictness when an unrelated setting moves is broken by design: if
# it comes back, it comes back as an absolute rupee number or an ATR
# multiple, never as a fraction of R.
ENABLE_NO_PROGRESS_EXIT = False
NO_PROGRESS_MINUTES = 30
NO_PROGRESS_R = 0.5

# --- Data sanity ------------------------------------------
# Reject absurd ticks. Three symbols on 2026-07-24 had corrupt
# bars (INFY 1037->111, JLHL -80% in a minute) which a backtest
# happily "traded" for a fake +Rs145k. A live feed glitch could do
# the same with real money.
ENABLE_TICK_SANITY = True
MAX_TICK_JUMP_PCT = 0.20     # >20% in one tick/minute = reject

# --- Candle recording (clean corpus for the replay bench) ---
# Every session writes its real 1-minute OHLCV to
# data/backtest_candles.db so the strategy can be replayed and
# validated across many REAL days instead of one scraped log.
ENABLE_CANDLE_RECORDING = True

# Last minute-bucket the recorder will accept, 2026-07-27.
#
# EVIDENCE, from that day's own recording (data/backtest_candles.db):
#
#   minute   bars  o=h=l=c
#   15:28     688        2      <- normal
#   15:29     134      134      <- ALL flat, single-price artifacts
#   15:40..    32       32      <- post-market, every one flat
#
# Sixty-seven one-minute "moves" bigger than 4% exist in that file and
# every single one is at or after 15:29. CARTRADE "fell" 11% at 15:50.
# TBZ "fell" 7.7% at 15:52 on ZERO volume. MARKSANS shows one bar at
# 15:29 of 246.95 after trading 263-265 all afternoon -- it never
# happened, and it was reported to the operator as a real price move
# before anyone looked at the bar.
#
# Cause is two-fold and neither is fixable downstream:
#   1. core/candle_engine.py only closes a candle when a tick lands in
#      the NEXT bucket. After 15:30 there are no more real ticks, so
#      the final minutes get closed -- much later -- by post-market
#      snapshot prices from a different session.
#   2. The post-close/auction window prints at prices that have no
#      relationship to continuous trading.
#
# Anything recorded from 15:29 onward is therefore not a candle, and a
# backtest that reads to end-of-day will trade these ghosts. The cost
# of the cutoff is one minute of real data; the cost of not having it
# is silently wrong numbers, which already happened once.
RECORDER_LAST_MINUTE = "15:28"

# Daily REALIZED-loss kill switch: once the session's realized P&L
# (sum over closed trades, partial exits included) is at or below
# -DAILY_MAX_LOSS_RS, no new structural entries for the rest of the
# day. Open positions still managed/exited normally -- this stops
# the bleeding, it doesn't panic-flatten. 10k = 10 full risk-budget
# stops (RISK_PER_TRADE_RS) -- a day that's hit 10 stops has said
# everything it needs to about today's conditions.
# 2026-07-24 (evening) LEVER 2: raised Rs 10,000 -> Rs 20,000 to
# keep the same "10 full stops = done for the day" logic now that
# each stop risks Rs 2,000 instead of Rs 1,000.
# RAISED 2026-07-27 alongside RISK_PER_TRADE_RS. This halt was sized
# as "a day that has hit 10 stops has said enough" -- 10 x Rs 800.
# At Rs 2,000 risk the same Rs 8,000 is only FOUR stops, which on a
# 40% win rate would halt the bot before 10:30 on most mornings.
# Kept at 10 stops: 10 x Rs 2,000.
DAILY_MAX_LOSS_RS = 20000.0

# The operator's own item-5 number: once the session's realized P&L
# reaches this, stop taking new entries -- the day's goal is met,
# don't hand it back. Same "existing positions still managed
# normally" semantics as the loss switch above.
DAILY_PROFIT_TARGET_RS = 30_000.0
# 2026-07-26: operator set this to Rs 30,000 (was 50,000).
#
# READ THIS BEFORE CHANGING IT AGAIN. This is a CEILING, not a target.
# It can only ever make the bot trade LESS: once realized P&L reaches
# the number, no new entries open and existing positions are managed to
# their normal exits. Nothing anywhere makes the bot trade harder,
# size up, or lower its standards to REACH it. That distinction is the
# whole reason this is safe -- FINDINGS.md 4 measured what a real
# target does: a Rs 1,100 per-trade target produced the highest win
# rate (53.6%) and the worst money (-Rs 15,714), because it capped the
# winners and left the losers running.
#
# What it CANNOT do is produce Rs 30,000. On Rs 10L capital, at the
# measured +0.17R expectancy and Rs 800 risk, net is about Rs 19 a
# trade; even at the largest size the margin allows the ceiling is
# roughly Rs 5,000 on a 50-trade day. Reaching Rs 30,000 needs the
# EDGE to improve about 5.5x, not the size. See STRATEGY.md 6.

# --- Breakout-quality margin (part of items 8/9: signal quality) ---
# A structural close must clear the ORB boundary by at least this
# fraction of the boundary price -- not by one paise. SONACOMS
# (2026-07-24) "broke out" by Rs 1.50 over a (wrong) high on a Rs
# 734 stock: ~0.2%. Genuine breakouts clear with conviction; closes
# that barely graze the line are overwhelmingly range noise. 0.1%
# starting value -- Rs 0.73 on SONACOMS, Rs 2.68 on SRF.
BREAKOUT_MIN_MARGIN_PCT = 0.001

# --- Volume-surge breakout filter, 2026-07-24 (evening) Change 2 ---
# The core signal-quality fix. Today's data: MOIL/TATASTEEL/ICICIBANK
# each CROSSED their ORB high and went nowhere (+0.2-0.4%), while
# KPITTECH crossed and ran +5.3%. From PRICE alone at the cross the
# fades and the runner look identical for the first few candles --
# the one thing that separates them is VOLUME (real breakouts carry a
# surge of participation; drifts don't). Requires the feed in QUOTE
# mode (main.py) so candles carry volume.
#
# A fresh breakout only enters if the breakout candle's own volume is
# at least VOLUME_SURGE_MULT times the average volume of the last
# VOLUME_AVG_CANDLES closed candles. FAIL-OPEN: if volume data is
# missing (feed still in Ticker mode, or Quote didn't deliver it) or
# there are fewer than MIN_VOLUME_CANDLES of history, the filter is
# SKIPPED and the trade proceeds -- it can never block trading just
# because volume is absent. Flip ENABLE_VOLUME_FILTER False to turn
# the whole thing off instantly.
ENABLE_VOLUME_FILTER = True
VOLUME_SURGE_MULT = 1.5
VOLUME_AVG_CANDLES = 20
MIN_VOLUME_CANDLES = 5
# "trading style is nowhere professional... substandard." A stock
# reporting quarterly results routinely gaps several percent on the
# news -- the ORB/ATR system has no way to tell that move apart from
# a genuine technical breakout, and an ATR read off a handful of
# post-open candles is actively misleading right after an earnings
# gap, not just noisy. This blocks NEW STRUCTURAL entries only (see
# core/engine.py's _try_structural_entry()) -- manual buy/short is
# untouched, same "auto skips, human overrides" pattern already used
# for the new-entries-pause feature.
#
# Sourced from the operator's weekly earnings calendar (pasted in by
# hand each week -- no reliable free API found for this, operator's
# own choice 2026-07-24). Keys are ISO dates (the date NEW ENTRIES
# are blocked for a symbol), values are the set of symbols blocked
# that date. Two source rows map to one exclusion date each:
#   - "sun" (reports DURING market hours) on day D -> blocks day D
#     itself, since the reaction can hit at any point that session.
#   - "moon" (reports AFTER close / AMC) on day D -> blocks day D+1
#     (the NEXT trading day), since the gap shows up at that day's
#     open, not on day D.
#
# THIS WEEK'S DATA IS PARTIAL -- the source (a Market Pulse "Week
# Ahead" screenshot) truncated each day's list behind "+N more"
# (roughly 100 of 351 names across the week never rendered in the
# image). Treat every date below as "at least these names" until a
# complete text list is pasted in and this dict is regenerated.
EARNINGS_CALENDAR = {
    "2026-07-27": {  # Mon sun (reports same day)
        "BEL", "BHAGYANGR", "CANBK", "EMKAY", "EPIGRAL", "HUDCO",
        "MANBA", "MOLDTKPAC", "SHIVACEM", "SUMICHEM", "USHAMART",
    },
    "2026-07-28": {  # Tue sun
        "A1L", "AMBUJACEM", "CENTENKA", "CHOLAFIN", "DEEPINDS",
        "DWARKESH", "EQUITASBNK", "HINDUNILVR", "HLVLTD", "INDOCO",
        "NAVNETEDUL", "RADICO", "ROSSTECH", "SUNCLAY", "SUPREMEIND",
        "TTKPRESTIG", "VBL", "VSTIND",
    } | {  # Mon moon -> gap hits Tue open
        "AEROFLEX", "ANTELOPUS", "AURIONPRO", "BALAMINES", "CCL",
        "CGCL", "COALINDIA", "COFORGE", "DIGITIDE", "GALLANTT",
        "GODFRYPHLP", "GRAVITA", "HAPPSTMNDS", "HMT", "HOMEFIRST",
        "INDUSTOWER", "JKPAPER", "NELCAST", "NESCO", "NORTHARC",
        "PNGJL", "RRKABEL", "SAGCEM", "SENORES", "SPLPETRO",
        "TATACHEM", "TATAPOWER", "TEJASNET", "TI", "TMB",
    },
    "2026-07-29": {  # Wed sun
        "ADANIENT", "ADANIPORTS", "APCOTEXIND", "ASAHISONG",
        "ASIANPAINT", "BLACKBUCK", "CARTRADE", "CRAFTSMAN", "DABUR",
        "DEVYANI", "DHANBANK", "ERIS", "HEIDELBERG", "J_KBANK",
        "KPITTECH", "MAHSCOOTER", "MASFIN", "MOIL", "PCBL", "PGHH",
        "REFEX", "SHANTIGEAR", "SHARDACROP", "SKMEGGPROD", "SUKHJITS",
        "THANGAMAYL", "VGUARD", "VIDHIING", "VINATIORGA", "VINCOFE",
    } | {  # Tue moon -> gap hits Wed open
        "AGI", "BSOFT", "CCCL", "CEMPRO", "CUB", "DCMSHRIRAM",
        "GINNIFILA", "INDTONER", "JTLDEFENCE", "LT", "MANORG",
        "NETWEB", "PARADEEP", "PFIZER", "PFS", "PHOENIXLTD",
        "PINELABS", "REMIEDEL", "RPGLIFE", "SANOFICONR", "SCANSTL",
        "SEDEMAC", "SHILINDORE", "SHK", "SIRCA", "STLNETWORK",
        "SUZLON", "TATACAP", "UFO", "ZENOTECH",
    },
    "2026-07-30": {  # Thu sun
        "ALIVUS", "APOLLOPIPE", "AWL", "DEEPAKFERT", "EXIDEIND",
        "GHCLTEXTIL", "GILLETTE", "GOCOLORS", "HESTERBIO", "HYUNDAI",
        "IRFC", "M_M", "NUCLEUS", "PRABHA", "PRIVISCL", "PSPPROJECT",
        "VINYLINDIA", "WESTLIFE",
    } | {  # Wed moon -> gap hits Thu open
        "ACMESOLAR", "ADFFOODS", "AEQUS", "BAJAJHFL", "COLPAL",
        "EICHERMOT", "EMUDHRA", "FORCEMOT", "GOKULAGRO", "GRSE",
        "HAWKINCOOK", "HONAUT", "INDOSTAR", "JKLAKSHMI", "KISSHT",
        "KTKBANK", "LXCHEM", "MTARTECH", "PPLPHARMA", "PRESTIGE",
        "QUESS", "STARHEALTH", "STEELCAS", "SYNGENE", "SYRMA",
        "TBOTEK", "TIMEX", "TRIVENI", "WAAREEENER", "ZENSARTECH",
    },
    "2026-07-31": {  # Fri sun
        "ABCAPITAL", "AETHER", "APTUS", "BAJAJFINSV", "CENTURYPLY",
        "GARGI", "HYBRIDFIN", "IOC", "KAJARIACER", "KELENRG",
        "MARUTI", "NATIONALUM", "PUNJABCHEM", "SMARTLINK",
        "SUNPHARMA", "TAJGVK", "VHLTD",
    } | {  # Thu moon -> gap hits Fri open
        "AARTIIND", "ACI", "AJANTPHARM", "BAJFINANCE", "BESTAGRO",
        "CHAMBLFERT", "HONDAPOWER", "ICRA", "INDGN", "KABRAEXTRU",
        "LICHSGFIN", "LTFOODS", "MANKIND", "MEDANTA", "NIVABUPA",
        "NSDL", "NUVAMA", "OAL", "OCCLLTD", "PAUSHAKLTD",
        "PRICOLLTD", "RAINBOW", "SEKURITIND", "SILVERTUC", "SWIGGY",
        "TATASTEEL", "TCI", "THERMAX", "TORNTPHARM", "UEL",
    },
    "2026-08-03": {  # Mon (following week) -- Fri moon -> gap hits next trading day
        "20MICRONS", "AADHARHFC", "ABB", "ASTEC", "BAJAJHLDNG",
        "BINNY", "BINNYMILLS", "BLUEDART", "CORONA", "ESAFSFB",
        "GAIL", "GLENMARK", "GMDCLTD", "IL_FSENGG", "INTELLECT",
        "ITC", "JAGRAN", "JINDWORLD", "LATITMETAL", "LGBBROSLTD",
        "MUKESHB", "NITTAGELA", "RAMRAT", "RPPINFRA", "SEJALLTD",
        "SHREECEM", "TAMBOLIIN", "VOLTAMP", "XPROINDIA", "ZUARI",
    },
}

# ----------------------------------------------------------
# Partial profit-taking (ATR_TRAILING only), 2026-07-24 -- operator's
# "dynamic position building" extension to item 3: "no fixed thing
# will have an edge... dynamic qty on dynamic profits." Also,
# operator's own words: "i didn't face these till now, so best thing
# is to create a test run for everything... plug & play in config.py
# with a to do list, so each day we can test one case and decide
# best suited case before live trading." This whole block is that
# test rig -- change ONE line (ENABLE_PARTIAL_EXIT, or the two dial
# values) per test day, run, note the result in trade_log.csv /
# dashboard performance, move to the next preset. Nothing here is
# "the final answer" yet -- it's the harness for finding one.
#
# Scale-IN (pyramiding/adding to a winner) was explicitly declined
# for now ("No scaling in") and is NOT built -- only scale-OUT
# (partial profit-taking) exists below. Revisit pyramiding as its
# own future test rig once partial-exit has actually been run for a
# few sessions.
# ----------------------------------------------------------

# Master switch -- False disables partial profit-taking entirely,
# every ATR_TRAILING position behaves exactly as the plain item-3
# redesign (single exit, whenever the ATR trail is eventually hit).
# Independent of everything else in this block -- turn it off
# instantly if a test day goes badly, no other values need to
# change.
#
# 2026-07-24 revamp: flipped ON with the Day-1 baseline preset
# (2.0 ATR trigger / 50% trim, the two values below). This is the
# "trailing TARGET" half of the operator's dynamic-targets-and-
# stops requirement -- profit gets banked at a volatility-scaled
# milestone while the remaining half keeps riding the ATR trail
# (the "trailing STOP" half). The 5-day one-variable-per-session
# test plan below still stands -- Day 1 starts now.
ENABLE_PARTIAL_EXIT = True

# TODO -- daily test plan (operator's own request, "test one case
# per day, decide best suited case before live trading"). Suggested
# order, but run in whatever order the market cooperates with; the
# only rule is ONE changed variable per session so a result can
# actually be attributed to it:
#
#   Day 1: PARTIAL_EXIT_ATR_MULTIPLE=2.0, PARTIAL_EXIT_FRACTION=0.5
#          (the defaults below) -- baseline: bank half at a
#          moderate, already-proven extension.
#   Day 2: PARTIAL_EXIT_ATR_MULTIPLE=1.5, PARTIAL_EXIT_FRACTION=0.5
#          -- same split, but trims EARLIER (matches the stop
#          distance itself) -- more trades bank something, each
#          banks less runway.
#   Day 3: PARTIAL_EXIT_ATR_MULTIPLE=2.5, PARTIAL_EXIT_FRACTION=0.5
#          -- trims LATER -- fewer positions reach it, but each is a
#          more convincingly "working" trade before anything is
#          banked.
#   Day 4: PARTIAL_EXIT_ATR_MULTIPLE=2.0, PARTIAL_EXIT_FRACTION=0.33
#          -- same trigger as Day 1, but only a THIRD is trimmed --
#          less locked in, more left to compound if the trend
#          continues.
#   Day 5: PARTIAL_EXIT_ATR_MULTIPLE=3.0, PARTIAL_EXIT_FRACTION=0.5
#          -- the most patient trigger tested -- closest to "let it
#          run" while still banking something.
#   After Day 5: compare win-rate / average realized P&L per trade /
#          how often each preset even got a chance to fire (a trigger
#          set too far out may rarely trigger at all in a choppy
#          session) across the 5 days, pick one, come back and set
#          ENABLE_PARTIAL_EXIT + the two values below to the winner
#          as the new default (delete this TODO once decided).

# The partial-profit milestone: once a position has moved this far
# in its favor from entry, trim PARTIAL_EXIT_FRACTION of the qty at
# the candle's close, banking real profit while the rest keeps
# riding the trail. Fires once per position (core/engine.py's
# _maybe_partial_exit()).
#
# 2026-07-24 (evening): the trigger is now the WIDER of an ATR
# multiple OR a real PERCENTAGE of price (PARTIAL_EXIT_MIN_PCT
# below) -- same "don't trust a thin 1-minute ATR" fix already
# applied to the stops. The old pure-ATR trigger booked garbage:
# RELIANCE banked a Rs 30 "profit" and HDFCBANK Rs 19.80 -- both
# smaller than the brokerage+STT charges on the trade, i.e. banking
# a guaranteed net loss. A percentage floor guarantees the partial
# only fires on a move big enough to actually clear costs with room
# to spare.
PARTIAL_EXIT_ATR_MULTIPLE = 2.0

# The percentage-of-price floor under the partial-profit trigger
# (see above). 1.5% on a Rs 1,000 stock = Rs 15/share of profit
# before any trim -- comfortably past the ~Rs 30-60 round-trip
# charge on a Rs 50k position. Whichever is LARGER, this or
# 2*ATR, is what the milestone actually uses -- so a genuinely
# volatile stock can still demand more, but a quiet one can never
# trim on a 60-paise wiggle again. Tune with real data.
PARTIAL_EXIT_MIN_PCT = 0.015

# Fraction of the CURRENT qty trimmed when the milestone above is
# hit -- 0.5 splits the position roughly in half: half the profit
# locked in now, half still riding uncapped. Rounded to the nearest
# whole share; if that rounds to 0 or to the full qty (a position
# too small to meaningfully split), the partial is skipped
# entirely and the whole thing rides the trail as before.
PARTIAL_EXIT_FRACTION = 0.5

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
# MIS (margin intraday) MARGIN MODEL -- rebuilt 2026-07-24 (evening)
# as a realistic replica of how Zerodha/Dhan actually block margin.
# ----------------------------------------------------------
#
# Verified against Zerodha/Dhan margin docs (July 2026): intraday
# equity MIS leverage is ~5x for most liquid stocks -- i.e. the
# broker blocks ~20% of trade value as margin (the exchange's
# VaR + ELM). Volatile / ASM-GSM names get less leverage (higher
# margin %), some get none. So on Rs 10L capital you can deploy
# ~Rs 50L of NOTIONAL, but each position only BLOCKS notional x its
# margin% of real cash. APAR 100sh @ 14,610 = Rs 14.61L notional ->
# Rs 2.92L margin blocked (20%); the dashboard now shows that real
# margin, not the raw notional.
#
# Default margin fraction (20% = 5x leverage), used for any stock
# not in the overrides table below.
MIS_DEFAULT_MARGIN_PCT = 0.20

# Per-stock margin overrides for names that don't get the default
# 5x -- higher fraction = less leverage (volatile / ASM / GSM
# stocks). Empty for now; populate from Dhan's margin list as real
# per-stock numbers are gathered. A stock set to 1.0 here is
# effectively "no MIS / cash only". Example shape:
#   MIS_MARGIN_OVERRIDES = {"YESBANK": 0.40, "SUZLON": 0.50}
MIS_MARGIN_OVERRIDES = {}

# Real cash available for margin (the paper account's actual money,
# NOT the leveraged notional). Kept equal to PAPER_STARTING_CAPITAL.
# Buying power in NOTIONAL terms is then capital / margin% -- e.g.
# Rs 10L / 0.20 = Rs 50L of deployable notional at the default rate.
MIS_CAPITAL_RS = PAPER_STARTING_CAPITAL

# Back-compat alias -- some older code/tests referenced a single
# leverage multiplier. Derived from the default margin % (1/0.20 = 5).
MIS_LEVERAGE_MULTIPLIER = round(1.0 / MIS_DEFAULT_MARGIN_PCT, 4)

# ----------------------------------------------------------
# Transaction cost model (POST_MARKET item 11), 2026-07-24 (evening).
# Intraday equity (MIS) charges, Dhan/discount-broker rates. Used to
# show real NET-of-cost P&L on the dashboard (Closed Trades + the
# Performance panel) -- the operator's whole point that a Rs 30
# "profit" is a net LOSS once charges are paid. See trading/charges.py.
# ----------------------------------------------------------
# ----------------------------------------------------------
# Index + India VIX feed (Market Intelligence panel), 2026-07-24.
# Dhan MarketFeed IDX segment (exchange code 0). These security IDs
# are Dhan's commonly-published IDX ids but MUST BE VERIFIED against
# the live scrip master on the first run -- if one is wrong that
# index simply won't populate (the dashboard shows "needs feed"),
# nothing else breaks. Fail-open + config-gated end to end.
ENABLE_INDEX_FEED = True
INDEX_INSTRUMENTS = {
    # dashboard name : Dhan IDX security_id (VERIFY on the live feed)
    "nifty": "13",         # NIFTY 50
    "banknifty": "25",     # NIFTY BANK
    "midcap": "26",        # NIFTY MIDCAP (verify -- may be a variant id)
    "vix": "21",           # INDIA VIX
}

# FII/DII institutional flows are EOD-only (NSE publishes after
# close), so they can't be shown live intraday from the tick feed.
# The dashboard shows whatever the operator MANUALLY sets here (net
# Rs crore, +ve = net buy) -- honest and dependable, vs an unreliable
# intraday scrape. Leave None to show "not set".
FII_NET_CR = None          # e.g. 1250.5  (FII net, Rs crore)
DII_NET_CR = None          # e.g. -430.2  (DII net, Rs crore)

BROKERAGE_PER_ORDER_RS = 20.0     # Dhan intraday: Rs 20 or 0.03%, lower
BROKERAGE_PCT = 0.0003            # 0.03%
STT_SELL_PCT = 0.00025            # 0.025% on the SELL leg (intraday)
EXCHANGE_TXN_PCT = 0.0000297      # NSE ~0.00297% both legs
SEBI_CHARGES_PCT = 0.000001       # Rs 10 / crore both legs
STAMP_DUTY_BUY_PCT = 0.00003      # 0.003% on the BUY leg
GST_PCT = 0.18                    # 18% on brokerage + exchange + SEBI

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

# Market Breadth (advances/declines/unchanged, and the green/red
# Sectors list derived from it) -- previously unthrottled, silently
# rebuilt on every single DASHBOARD_REFRESH_INTERVAL_SECONDS cycle
# (every 1s). Given its own explicit cadence 2026-07-24, operator's
# own instruction ("Market Breadth - 5secs"), same throttled-cache
# pattern as GAINERS_LOSERS_REFRESH_SECONDS -- see
# dashboard/state.py's _build_breadth().
MARKET_BREADTH_REFRESH_SECONDS = 5

# ----------------------------------------------------------
# Logging
# ----------------------------------------------------------

LOG_DIR = "logs"
TRADE_LOG_PATH = os.path.join(LOG_DIR, "trade_log.csv")
DIAGNOSTIC_LOG_PATH = os.path.join(LOG_DIR, "diagnostics.log")

# Console stays clean by default -- only real decisions and
# results print live. Full detail always goes to the file.
VERBOSE_CONSOLE = False

# 2026-07-25 (operator-found, live): the WebSocket feed sends periodic
# SNAPSHOTS, not every trade, so the ORB range the bot accumulates from
# ticks is systematically NARROWER than the real one (ZENTEC seen
# 1784.20 vs real 1792.00; CROMPTON 246.85 vs 249.70). A too-narrow
# range manufactures false breakouts -- price still INSIDE the true
# range reads as a break. Once the ORB window closes, the day's
# high/low from Dhan's REST quote (already polled by circuit_monitor)
# IS the true opening range, so we widen to it. Only ever widens.
ENABLE_ORB_EXCHANGE_RECONCILE = True

# ==========================================================
# SECTOR / THEME STRENGTH GATE  (2026-07-25)
# ==========================================================
# Operator's core thesis: "intraday is completely dependent on momentum,
# which usually lies in the top gaining sector stocks." A lone mid-cap
# breaking out is an orphan; the same breakout inside the day's leading
# sector is the market rotating money IN. Friday's replay traded
# DATAPATTNS / SUDEEPPHRM / AEQUS -- names in no particular theme --
# exactly the failure mode this gate targets.
#
# Sector strength = median %change (vs prev close) of all symbols in
# that sector, from circuit_monitor's existing REST snapshot. A LONG
# needs its sector among the top N gainers; a SHORT among the top N
# losers. Fail-open: no snapshot / too few symbols priced -> no gate.
# DISABLED 2026-07-27. POST_MONDAY_TODO.md section B: "never
# measured." A top-8-of-90 sector cut removes roughly 90% of the
# universe on a rule with no evidence behind it at all.
ENABLE_SECTOR_STRENGTH_GATE = False
SECTOR_STRENGTH_TOP_N = 8        # how many leading sectors qualify each side
SECTOR_STRENGTH_MIN_SYMBOLS = 3  # a sector needs this many priced names to rank
SECTOR_STRENGTH_REFRESH_SECONDS = 10

# ==========================================================
# EARLY MOMENTUM ENTRY  (2026-07-25)
# ==========================================================
# Operator: "is there anything we can do to enter if a stock is showing
# good strength rather than waiting till the ORB range forms?" Waiting
# for 09:30 means the first 15 minutes -- often the day's cleanest move
# -- is unusable. A stock that gaps and runs is already telling you.
#
# So a SECOND, shorter range closes at EARLY_ORB_END. A break of THAT
# range can trade from ~09:20 instead of ~09:31, but ONLY for names
# that clear a deliberately higher bar: leading sector + strong relative
# strength. Everything else still waits for the full 09:30 range.
# DISABLED 2026-07-27, on two independent findings from the same day.
#
# 1. It is FIRST-COME, NOT RANKED. Two seats, no comparison between
#    candidates. On 2026-07-27 AUBANK (09:23:09) and CAPLIPOINT
#    (09:26:10) took both seats simply by triggering first; CMLL's
#    early range had only finished forming at 09:20. Both trades were
#    closed inside seven minutes. This is the "clock-order was the
#    original sin" problem that was fixed for the main entry path and
#    never fixed here.
#
# 2. It buys straight into the opening burst. Bucketing all 1,957
#    replayed trades by how far the stock moved in its first five
#    minutes: a 3-4% burst averaged -Rs 78/trade, 4-5% averaged
#    -Rs 176 at a 24.5% win rate, against +Rs 105 for the 2-3% band.
#    279 trades in stocks that ripped 3%+ at the open lost Rs 26,972.
#    Operator's own observation, 2026-07-27, confirmed in the data.
ENABLE_EARLY_MOMENTUM_ENTRY = False
EARLY_ORB_END = "09:20"           # first 5 minutes forms the early range
EARLY_ENTRY_MIN_RS = 0.010        # needs >= +1.0% vs market (vs 0.6% normally)
EARLY_ENTRY_MAX_POSITIONS = 2     # at most this many early trades per day

# ==========================================================
# LIQUIDITY FLOOR  (2026-07-25)
# ==========================================================
# A breakout in a thin stock is untradeable in real life: the spread and
# market impact eat the edge before it exists. Charges already consume
# ~78% of gross profit; slippage on illiquid names would finish it.
# Turnover = last_price x day volume, from circuit_monitor's existing
# REST quote. Fail-open: no volume data -> no gate (the WebSocket feed
# doesn't always carry volume, and a missing number must never block).
ENABLE_LIQUIDITY_FLOOR = True
MIN_TURNOVER_RS = 20_000_000      # Rs 2 crore traded so far today

# ==========================================================
# STOCK MEMORY  (2026-07-25, operator's proposal)
# ==========================================================
# "A memory bot for every 750 stocks, so Brain Bot understands the stock
# situation BEFORE selecting any trade." Stores corporate actions
# (split / bonus / dividend / rights / demerger) with their ex-dates,
# fetched from NSE+BSE, and refuses to trade a symbol whose PRICE SCALE
# is being changed around today.
#
# The failure it fixes: JLHL's 2:10 split on 2026-07-24 read as an -80%
# crash, because our previous close was the unadjusted one. The bot
# ranked a routine corporate action as the day's biggest loser.
# A stock going ex-dividend opens lower by the dividend too -- that is
# not weakness, and shorting it is a mistake.
#
# Fail-open: an empty memory blocks nothing.
ENABLE_STOCK_MEMORY = True
MEMORY_ACTION_WINDOW_DAYS = 1     # +/- days around the ex-date to avoid

# ==========================================================
# TRADE MEMORY / LEARNING LOOP  (2026-07-25)
# ==========================================================
# From the operator's architecture: "Every completed trade becomes new
# memory, improving future decisions." Records each closed trade WITH
# the conditions it was taken in (sector, relative strength, hour,
# regime), so the bot can eventually answer "which conditions work?"
#
# OBSERVATION ONLY, operator-approved. Nothing reads this back to block
# or size a trade. A handful of samples looks like a pattern long before
# it is one -- it earns a vote after enough real sessions, not before.
ENABLE_TRADE_MEMORY = True

