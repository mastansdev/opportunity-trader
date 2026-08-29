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

# ---------------------------------------------------------------------
# EXTRA TELEGRAM CHANNELS -- the private / paid ones
# ---------------------------------------------------------------------
#     "i brought you some more promising pro channels of earnings
#      pulse... those pro channels are not showing link to share"
#                                     -- operator, 1 August 2026
#
# A PUBLIC channel has an @handle printed on its page. A PRIVATE one
# has neither a handle nor a share link, and the only name it has is
# its TITLE inside the account that joined it.
#
# Put those titles here, EXACTLY as `py tools/telegram_channels.py`
# prints them. Nothing else needs editing -- core/telegram_feed.py
# appends whatever is in this list to the four public channels.
#
#     EXTRA_TELEGRAM_CHANNELS = [
#         "Earnings Pulse Pro",
#         "Street Pulse Pro",
#     ]
#
# WHAT THESE DEPEND ON. A private channel is reachable ONLY through the
# Telegram API -- there is no public web page for it. So if the session
# expires or the account is rate-limited, these go quiet while the four
# public channels fall back to the web view and keep arriving. That is
# a real difference in reliability, not a formality, and it is the
# reason the public four are not moved off the web reader entirely.
#
# `kind` is "text" unless the channel is mostly screenshots, in which
# case use a dict: {"handle": "Some Pro Channel", "kind": "image"}.
EXTRA_TELEGRAM_CHANNELS = [
    # ---- THE WATCHLIST BOT, 1 August 2026 ----
    #
    # The richest source in the whole subscription, and it arrives as a
    # direct message rather than a channel. For up to 100 chosen stocks
    # it pushes results, concall summaries, investor presentations,
    # OrderBook filings, other announcements, price movements, broker
    # ratings and watchlist news -- "Only your stocks. No firehose."
    #
    # Named here rather than left to the PRO folder scan because it has
    # a public username, so it resolves directly and does not depend on
    # Telegram listing a bot alongside channels in a folder -- which it
    # did not appear to do when the folder was first read.
    #
    # core/telegram_client._is_readable_source() allows bots on purpose
    # and still refuses human chats. See tests/test_folder_sources.py.
    "WLPulseBot",
]

# ---------------------------------------------------------------------
# ...OR JUST USE A TELEGRAM FOLDER
# ---------------------------------------------------------------------
#     "in my telegram . two folder - ALL CHATS & PRO
#      if we want & feasible i will move our required telegram channels
#      to PRO folder"               -- operator, 1 August 2026
#
# Feasible, and better than the list above. Put a folder name here and
# every channel inside it is watched. Curation happens in the Telegram
# app: drag a channel in and the bot reads it, drag it out and it
# stops. Nothing to type exactly, no file to edit, and no way for a
# list in the code to drift from what is actually being followed.
#
#     TELEGRAM_FOLDER = "PRO"
#
# Folders are an account setting, so this needs the API session -- a
# public web page has no folders. Set it to "" to switch it off.
#
# ONLY CHANNELS AND GROUPS ARE READ. A personal chat dragged into that
# folder is skipped: the bot has no business in one, and quietly
# collecting private messages because somebody tidied their app would
# be indefensible.
TELEGRAM_FOLDER = "PRO"

# ----------------------------------------------------------
# Trading mode
# ----------------------------------------------------------

# PAPER only until Layer 1 has been watched for real, live,
# without placing a single real order, and the operator
# trusts what it's doing.
# ---- PAPER, ON REAL MARKET DATA. His call, 9 August 2026. ----
#
#     "lets bot trade in paper mode but dashboard must show me as
#      we both agreed . i'll trade manually"
#
# This said LIVE, with I_UNDERSTAND_THIS_PLACES_REAL_ORDERS True,
# so trading/execution.py built LiveExecution and dhan.place_order
# was one call away. ALERT_ONLY_MODE and LIVE_ALLOW_BOT_ENTRIES
# stopped the BOT -- but this file says in as many words that
# "Manual dashboard clicks can" place a real order, and he asked
# for paper.
#
# PAPER changes the EXECUTOR only. The WebSocket still carries
# real ticks, the Telegram cards are real, the ranker sees the
# real board and the dashboard shows the real session. Nothing
# about the market data is simulated -- only the fills.
#
# His own manual trading in the Dhan app is completely unaffected;
# this process never touches it.
TRADING_MODE = "PAPER"

# ----------------------------------------------------------
# LIVE TRADING -- real money. 2026-07-28
# ----------------------------------------------------------
# TRADING_MODE = "LIVE" is NOT enough on its own. Both of these must be
# true before a single real order can be placed. One switch is one typo
# away from spending money by accident; two is a decision.
I_UNDERSTAND_THIS_PLACES_REAL_ORDERS = True

# Operator's decisions, 2026-07-28:
#   1. MARKET orders   -- fills instantly, price not guaranteed
#   2. He watches on 2-3 screens
#   3. HIS CLICKS ONLY at first. "initially i'll trade with bot dashboard.
#      once bot gets clarity shifts to bot (not autonomous - i'll be
#      there 100%)"
#
# So the bot's own structural entries CANNOT place live orders until
# this is turned on deliberately. Manual dashboard clicks can.
LIVE_ALLOW_BOT_ENTRIES = False

# ---------------------------------------------------------------
# A STOP THAT SURVIVES THIS PROCESS DYING, 2026-08-02
# ---------------------------------------------------------------
#     "yeah pick that one. - pick the broker-side stop"
#
# Until now every stop lived in RAM, in core/trailing_stop.py, inside
# the running process. Kill the process -- crash, sleep, power cut,
# dead proxy -- and an open MTF position at up to 4X, held overnight,
# had no stop anywhere. Dhan did not know one was intended.
#
# With this ON, every entry also rests a Forever Order (GTT) at Dhan
# at the HARD stop. It sits BELOW the live trailing stop on purpose,
# so the two cannot race for the same fill: in normal running the live
# stop always fires first and this one is cancelled on the exit. It
# only ever does anything when this process is not there to act.
#
# It places REAL resting orders in a real account, and a resting order
# left behind after an exit would SELL STOCK THAT IS NOT HELD -- on MTF,
# that is a short. trading/broker_stop.py cancels on every exit and
# reconciles against Dhan's own list at startup.
#
# ---- TURNED ON, 12 AUGUST 2026. THE OPERATOR'S DECISION. ----
#
# It was OFF, and FORCE_SQUARE_OFF_AT_CLOSE below is also False. Those
# two together meant an open MTF position had NO STOP ANYWHERE between
# 15:30 and 09:15 -- not at Dhan, and not in this process if the machine
# was off. That is not a theoretical gap. Six trades went straight past
# the 2.5% hard stop overnight for -Rs 48,692:
#
#     CORONA     -7.48%    DEEPAKFERT -4.80%    YASHO     -5.19%
#     DEEPAKNTR  -3.51%    DEEPAKFERT -4.81%    JKLAKSHMI -2.82%
#
# Asked which way to close it, he picked the resting stop over forced
# square-off: the overnight hold is the strategy, so protect it rather
# than abolish it.
#
# WATCH THE FIRST SESSION. The dashboard toggle (/api/broker_stop/on|off)
# switches this live without a restart, so it can be turned off mid-
# session if the resting orders look wrong.
BROKER_STOP_ENABLED = True

# How far the live trailing stop must ratchet above the resting trigger
# before the resting order is moved up to follow it. Every move is an
# API call on the order path; following every tick would be thousands
# of calls a day for a protection that only matters when the process is
# already dead. 1% keeps the backstop within one stop-width of the real
# one without hammering the endpoint.
BROKER_STOP_RESYNC_PCT = 0.01

# Written into the resting order's correlationId so reconcile() can
# tell OUR orders from ones the operator placed by hand in the Dhan
# app. An order that is not ours is reported and left alone -- this bot
# does not reach into his account and cancel a protection he set
# himself.
BROKER_STOP_TAG_PREFIX = "OTSTOP"

# ---------------------------------------------------------------
# THE STATIC IP, AND WHY IT IS ONLY ON THE ORDER PATH
# ---------------------------------------------------------------
# 31 July 2026. SEBI requires every API-placed order to leave from a
# registered static IP. Three orders were refused DH-905 Invalid IP
# before the cause was found; reads were never affected, which is
# exactly why it hid for so long.
#
# The obvious fix -- move the whole bot to a cloud machine with a
# static IP -- IS WRONG, and the operator knew it from experience:
#
#     "last time when deployed in railway - some rss not worked"
#
# He was right, and the code says why. This bot fetches from:
#
#     www.nseindia.com          5 places   BLOCKS datacenter IPs
#     nsearchives.nseindia.com  3 places   BLOCKS datacenter IPs
#     moneycontrol / ET / BS    5 places   bot protection
#     api.dhan.co               5 places   needs the STATIC ip
#     t.me, telegram            6 places   fine either way
#
# The two requirements point in OPPOSITE directions. NSE and the news
# sites want a residential address; Dhan wants a registered static one.
# A cloud VM satisfies the second and breaks the first -- which is the
# Railway failure, reproduced at greater expense.
#
# So the proxy is applied to ONE client: the one that places orders.
# Everything else -- the tick feed, circuit-monitor quotes, NSE, the
# pre-open book, RSS, Telegram -- keeps going out over the home
# connection exactly as it does today.
#
# StaticIP.in, bought 31 July 2026. Verified the same afternoon:
#
#     home line arrives as   157.50.99.165      (Jio -- NSE sees this)
#     via the proxy          165.101.251.109    (Dhan sees this)
#
# 165.101.251.109 is the number whitelisted at Dhan. Valid to
# 31 Aug 2026 -- RENEW BEFORE THEN or every order stops.
#
# Both http:// and https:// were tested and both carry traffic;
# http:// is used because it is a plain CONNECT tunnel, which keeps
# the Dhan access token encrypted end to end and unreadable by the
# proxy operator.
ORDER_PROXY = ("http://sip_310709bcebbdfd89:9VURw2Kt5f7qIkJE"
               "@dc-mum-005.staticip.in:443")

# HARD LIMITS. These are not risk management -- they are the guard rail
# against a bug. A loop that fires fifty orders is the nightmare case,
# and it has to be impossible rather than unlikely.
LIVE_MAX_ORDER_VALUE_RS = 500_000.0   # refuse any single order above this
LIVE_MAX_ORDERS_PER_DAY = 30          # refuse everything past this count
LIVE_MAX_OPEN_POSITIONS = 12

# A MARKET order cannot be cancelled once it fills, so the only place to
# protect the fill price is BEFORE sending. If the live price has moved
# more than this from the price the dashboard showed when the operator
# clicked, the order is REFUSED and he is told why.
#
# The case this exists for: 2026-07-28, SUPREMEIND. First click was lost
# (item 26), price ran from ~3,385 to 3,472.70 before the second click
# went through -- Rs 5,000 on 57 shares. With a live market order that
# would have been a real fill at a price he never agreed to.
LIVE_MAX_PRICE_DRIFT_PCT = 0.005      # 0.5%

# Every order carries a correlation ID. On a TIMEOUT the bot must query
# by that ID before it even considers resending -- a blind retry is how
# you end up holding two positions and knowing about one.
LIVE_ORDER_TAG_PREFIX = "OT"
LIVE_CONFIRM_TIMEOUT_SECONDS = 10

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
# MIS/intraday only, and DORMANT while FORCE_SQUARE_OFF_AT_CLOSE is
# False (which it is, for MTF). 31 July 2026: this time also used to
# block every NEW entry after 15:15 -- correct when the bot flattened
# at 15:15, meaningless once it stopped. The block now follows
# FORCE_SQUARE_OFF_AT_CLOSE automatically. See
# core/engine._entry_cutoff_reason().
SQUARE_OFF_TIME = "15:15"

# ----------------------------------------------------------
# HOLD OVERNIGHT -- the MTF switch, 2026-07-28
# ----------------------------------------------------------
# SQUARE_OFF_TIME above is MIS machinery. main.py calls
# engine.flatten_all() at 15:15 and closes EVERY open position, every
# day, no exceptions.
#
# The operator moved to MTF specifically to hold positions for days:
# "shifted to MTF (even more safer than MIS)", and the whole strategy
# is "ride while momentum persists, exit ruthlessly when it dies" --
# neither of which survives a daily forced liquidation. On 2026-07-28
# it closed TVSMOTOR and CUB at 15:15 for exactly that reason.
#
# This is not cleanup. With square-off armed, the MTF strategy cannot
# be run at all.
#
# WHAT STAYS ON when this is False:
#   - No FRESH entries after NO_NEW_ENTRIES_AFTER (unchanged).
#   - Trailing stops keep working, through the close and into the next
#     session. A position is never unmanaged.
#   - The end-of-day sweep still runs, but only REPORTS what is being
#     carried instead of liquidating it.
#
# WHAT THE OPERATOR TAKES ON:
#   - Overnight gap risk. An MTF position gaps against you with no stop
#     able to fire between 15:30 and 09:15.
#   - MTF interest from T+1 (~0.0342%/day on the funded amount).
#   - Dhan's own RMS can still square off if coverage falls below 20%.
#
# Set True to restore the old MIS behaviour on any day you want to be
# flat by the close.
FORCE_SQUARE_OFF_AT_CLOSE = False
MARKET_CLOSE = "15:30"

# ---------------------------------------------------------------------
# KEEP THE DASHBOARD UP AFTER THE CLOSE
# ---------------------------------------------------------------------
# 30 July 2026. The dashboard grew a POST-MARKET tab -- closed trades,
# performance, and the refusal breakdown -- and then the operator asked
# the obvious question nobody had asked:
#
#     "but main.py will auto close after market timings right?"
#
# It does. main.py's loop breaks the moment `now >= MARKET_CLOSE_T`, so
# the review tab could only ever be read DURING the session, which is
# precisely when nobody wants to read it. The tab was built for a screen
# that no longer existed by the time it mattered.
#
# With this True the bot's TRADING day still ends at exactly 15:30 --
# same break, same state save, feed closed, no order path alive -- but
# the process stays up serving the dashboard read-only until Ctrl+C.
# Nothing about the trading behaviour changes; only the process lifetime.
KEEP_DASHBOARD_AFTER_CLOSE = True

# ...and the hazard that creates. A process left running overnight has a
# CLOSED feed and yesterday's opening ranges. If it were still serving at
# 09:15 it would look live and be dead -- the single most dangerous state
# this screen can be in, because every number on it is plausible.
#
# So it stops itself before the next session can start. A banner alone
# was the alternative and it was rejected for the right reason: a banner
# is a thing you have to notice.
DASHBOARD_AFTER_CLOSE_EXIT_AT = "09:00"

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
# Kept in lockstep with STAGED_NO_ENTRY_AFTER -- both moved to
# 15:15 on 8 August when the square-off argument stopped applying.
#
# ---- 15:30. THE WINDOW IS THE SESSION. 23 August 2026 ----
#
#     "for bot from 09 - 15:30 complete trading whenever opportunity
#      saw"                            -- operator, 23 August 2026
#
# The 8 August note above already retired the square-off argument.
# The last 15 minutes were left behind by habit, not by a reason.
# FORCE_SQUARE_OFF_AT_CLOSE is False and entries are MTF held
# overnight, so a 15:20 entry has the whole of the next session.
#
# THIS is the value the live path reads -- core/auto_entry.py imports
# it directly. core/rules.py's LAST_NEW_ENTRY is derived from it, and
# on 23 August I edited that one instead and reported the window as
# widened when nothing had changed. Nothing reads rules' copy.
# ---- CAS. NSE CHANGED THE CLOSE ON 3 AUGUST 2026. ----
#
#     "once normal activity started at 09:15 till 15:15 is regular
#      trading thats it . CAS after 15:16 leave that completely"
#                                    -- operator, 29 August 2026
#
# He is right and my 24 August change was wrong. I moved this from
# 15:15 to 15:30 reasoning that 15:15 was leftover MIS square-off
# machinery. It was -- but 15:15 became correct again for a different
# reason three weeks earlier, and I did not check:
#
#   NSE Closing Auction Session, live since 3 August 2026
#     F&O stocks (Category I)  continuous trading ENDS 15:15,
#                              auction runs 15:15-15:35
#     other cash stocks        close 15:30
#     equity derivatives       close 15:40
#     post-close               15:50-16:00
#
# The bot trades MTF, and MTF-eligible names are largely F&O stocks.
# An entry at 15:20 on one of those does not reach continuous trading
# at all -- it lands in an auction, at a price set by a mechanism the
# bot knows nothing about.
#
# 15:15 for now, deliberately conservative: it is right for Category I
# and merely early for the rest. Revisit when CAS has settled and
# there is a reason to want those fifteen minutes.
LAST_ENTRY_TIME = "15:15"

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

# ----------------------------------------------------------
# PER-SYMBOL STALENESS, 2026-07-28
# ----------------------------------------------------------
# The flat 5-second threshold above was set BELOW the feed's own
# natural rate. Measured live on 2026-07-28:
#
#     ~8,900 ticks/min across 666 symbols
#     = 13.4 ticks per symbol per minute
#     = one tick every 4.63 seconds, on average
#
# So the threshold sat 0.37s above the average gap. Poisson arrivals
# put ~34% of symbols past 5s at any instant even with a PERFECT feed;
# bursty arrivals took the live figure to 50%. The alarm was measuring
# the threshold, not the feed.
#
# What it actually cost, all four from the same constant:
#     "333/666 symbols (50%) are stale AT ONCE" fired all session
#     "stale symbols flagged: 157,069"  (there are 666 symbols)
#     2,446 disk writes a MINUTE into a 369 MB unrotated log
#     607 of 666 symbols locked out of trading -- see below
#
# Dhan sends periodic SNAPSHOTS, not every trade, and tick_time is the
# last TRADE time. So a quiet mid-cap that genuinely hasn't traded for
# 20 seconds reports 20s of "staleness" while the feed is perfectly
# healthy. One number cannot serve a Rs 3,000-crore stock and a Rs
# 30-crore one.
#
# Each symbol now learns its OWN typical gap and is flagged only when
# it exceeds that by a wide multiple. A stock that ticks every 2s is
# flagged at 2s x multiple; one that ticks every 25s is not flagged for
# behaving normally.
STALENESS_ADAPTIVE = True
STALENESS_MULTIPLE = 4.0          # flag at 4x the symbol's own normal gap
STALENESS_MIN_SECONDS = 8.0       # never flag below this, however fast
STALENESS_WARMUP_TICKS = 20       # fall back to the flat rule until then

# ----------------------------------------------------------
# ORB-WINDOW INTEGRITY, retuned 2026-07-28
# ----------------------------------------------------------
# is_orb_window_unreliable() blocks structural entries for the whole
# session for any symbol that went stale inside 09:15-09:30. Correct
# rule -- a range built around a hole in the feed is not a range.
#
# But it inherited the 5-second threshold, so on 2026-07-28 it
# blacklisted 607 of 666 symbols and the bot took ZERO automated
# entries all day. The three restarts inside the opening range made it
# worse, but 5s alone would have flagged most of the universe anyway.
#
# The incident this rule exists for (SONACOMS, 2026-07-24) was a ~30
# SECOND gap. That is the harm level. Anything under it is a quiet
# stock, not a hole.
ORB_WINDOW_MAX_GAP_SECONDS = 30.0

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

# ==========================================================
# THE CIRCUIT RULE IS HALF RIGHT  (2026-07-29)
# ==========================================================
# Until now, a stock within CIRCUIT_PROXIMITY_PCT of EITHER limit got
# no new entries and any open position closed -- "irrespective of
# direction", in the log's own words.
#
# For a LONG the two limits are opposite situations:
#
#   LOWER   real danger. If it locks there are no buyers, the position
#           cannot be exited at any price, and on MTF that is how a
#           2.5% stop becomes a 20% loss. Closing early is correct.
#
#   UPPER   the best thing that can happen. Buyers with no sellers.
#           Selling there means dumping the strongest position of the
#           day, every time.
#
# The rule exists so the bot does not get trapped. Trapped in a RISING
# stock is not a trap.
#
# WHAT IT COST, measured:
#
#   COFORGE 28 Jul   bought 1,648.10, rule sold at 1,648.30 for +Rs 24.
#                    It then ran to 1,692.20 and closed 1,680.10.
#                    Holding was worth Rs 3,872.
#
#   29 Jul           the day's two biggest movers were both structurally
#                    off-limits:
#                        SMLMAH      3,838 -> 4,566   +18.97%
#                        APCOTEXIND    602 ->   709   +17.82%
#                    The operator bought SMLMAH by hand and the bot sold
#                    it within seconds. APCOTEX it never touched at all.
#
# THE KNOWN RISK, stated rather than hidden: a stock locked at its
# upper circuit can open lower the next morning, and a stop does not
# help when there are no buyers. Positions are carried overnight on
# MTF deliberately, so that exposure is real -- it is just not a reason
# to sell every winner the moment it becomes one.
CIRCUIT_RULE_DIRECTION_AWARE = True

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
# REMOVED 2026-07-29, operator's decision: "Remove cap on below 200 &
# above 10,000 rs as we have moved from MIS to MTF we left these two
# unchanged."
#
# The rule was written on 2026-07-24 for MIS intraday, where a sub-Rs
# 200 stock's tick granularity really did behave differently inside a
# same-day round trip. MTF changes the holding period, and the
# operator's own judgement on his own money governs which stocks he
# is willing to own.
#
# 0.0 disables the gate without deleting the plumbing -- the check in
# _enter() still runs, so putting a floor back is a one-number change
# rather than a re-implementation.
#
# NOTE, and this matters: this gate only refuses stocks that are
# ALREADY in the universe. The universe itself is still built with
# its own price bounds (core/universe_builder.py). Until that is
# rebuilt, the tradable list is unchanged.
# ---- THE FLOOR IS BACK, AND IT IS HIS NUMBER. 6 August 2026. ----
#
#     "we need to refine the stocks which are having lower price than
#      50 rs CMP. we/bot never trade in those stocks"
#
# It was 0.0 -- switched off -- and worse, nothing on the DECISION
# path read it at all. core/ranker.py, core/watchlist_builder.py and
# core/auto_entry.py never mentioned it, so only _enter() checked, and
# only against a floor of zero. GTLINFRA at Rs 1.23 was in today's
# result set with nothing to stop it being ranked.
#
# 50.0 now, applied at the WATCHLIST as well as at entry, so a stock
# he will never trade never occupies a row he could have used.
MIN_TRADABLE_PRICE_RS = 50.0

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
TRAILING_STOP_WINDOW_CANDLES = 5   # LEGACY -- see PEAK_TRAIL_PCT below

# ----------------------------------------------------------
# PERCENT TRAIL FROM THE PEAK, 2026-07-28
# ----------------------------------------------------------
# REPLACES the 5-candle rolling-low trail above, which took the lowest
# low of the last five ONE-MINUTE candles. That is a five-minute noise
# window on a system that now holds positions for days, and it ratcheted
# the stop up during flat stretches -- so an ordinary pause pulled the
# stop right under the price and the next dip ended the trade.
#
# WHAT IT COST ON 2026-07-28, all three from the same rule:
#     AFFLE       peaked +Rs 3,087, exited +Rs 590. Gave back Rs 2,497
#                 in eight minutes. Simply holding beat it by Rs 886.
#     NILKAMAL    entered 09:36, out 09:53 for +0.51%. The stock went
#                 on to +7.63%.
#     KALYANKJIL  stopped at 597.50. Closed at 608.85.
#
# WHY 2.5%. Measured on that same session: 51 stocks finished up 2% or
# more, and their worst pullback ALONG THE WAY was --
#
#     median   1.84%      75th pct  2.50%
#     average  2.03%      90th pct  3.45%
#
# A 1% trail was hit in 45 of those 51 winners. 2.5% survives three
# normal pullbacks out of four. Wider catches more (CUB dipped 4.4%
# before delivering 8.9%) but pays for it on every loser.
#
# BREAKEVEN IS AUTOMATIC, no second rule needed. Operator asked whether
# the stop should jump to the buy price once the stock is +2.5% up. It
# already does:
#     peak = entry x 1.025  ->  stop = peak x 0.975 = entry x 0.9994
#     peak = entry x 1.026  ->  stop = entry x 1.0004   ABOVE entry
# So around +2.6% the trail crosses the buy price by itself, and keeps
# climbing: at +5% the stop sits at +2.3%, at +9% it sits at +6.3%.
#
# NEVER TIGHTENS. It only moves on a NEW HIGH -- never on a pause. That
# distinction is the whole fix.
#
# Operator, 2026-07-28: "keep 2.5% for now but my strong feeling is we
# close much before this number touched." Correct use -- it is a
# backstop, not a plan.
ENABLE_PEAK_TRAIL = True
PEAK_TRAIL_PCT = 0.025

# ---- AND THE TRAIL IS ONE WIDTH TOO. 19 August 2026. ----
#
#     "trailing in good moving stocks (strong supported events)"
#
# 2.5% from the peak is half an ordinary day for ICIL (daily range
# 4.99%) and more than a full day for POLYCAB (1.79%). On the first it
# fires on a routine breather; on the second it gives away money it
# never needed to risk. Same source as the entry stop --
# core/atr.daily_atr_pct() -- so the two can never drift onto
# different definitions of how much a stock moves.
VOLATILITY_SCALED_TRAIL = True
DAILY_ATR_TRAIL_MULT = 0.8

# A position standing on a real catalyst gets a wider leash: the
# catalyst is a reason to expect continuation, and a pause inside one
# is not a failure. Applied only when the entry says the position
# carries an event.
TRAIL_EVENT_SLACK = 1.4

# Bounds, in PERCENT. Below the floor a trail is noise; above the
# ceiling it is not protecting anything.
TRAIL_MIN_PCT = 1.5
TRAIL_MAX_PCT = 7.0

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
# REMOVED 2026-07-29 with ONE_TRADE_PER_SYMBOL_PER_DAY, same decision
# and same reasoning (see that flag's note for the MTF assessment and
# the measurement). These two together meant a single stop-out retired
# a stock for the whole day; turning off only one of them would have
# left the other still enforcing the rule, and the operator would have
# been told it was removed while it was not.
BLOCK_REENTRY_AFTER_STOPOUT = False

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
# ==========================================================
# THE NAME IS A LIE  (2026-07-29)
# ==========================================================
# This flag has NOTHING to do with a momentum list any more. The
# eligibility gate that used one was removed weeks ago -- core/engine.py
# says so outright: "momentum_universe is no longer consulted for
# eligibility at all."
#
# What it actually controls today is which SIZING AND STOP path an entry
# takes:
#
#     True   -> ATR-derived stop, 2.5% hard stop from entry, MTF sizing
#     False  -> LAYER1_FIXED_QTY shares and an ORB-boundary stop
#
# So anyone flipping this to False -- reasonably believing they are
# switching off an unused momentum list -- would silently change every
# entry's share count and stop. No error, no warning, just different
# trades. It is read in 26 places across 7 files.
#
# ATR_ENTRY_SIZING below is the honest name. This one stays as an alias
# so nothing breaks, and so a search for the old name still lands here.
#
# It already cost an argument: on 29 July the operator said the 09:30
# momentum lock had been removed. It had. I argued back, because the
# machinery was still running and still printing a tidy line at 09:30.
ATR_ENTRY_SIZING = True
TOP_N_MOMENTUM_MODE = ATR_ENTRY_SIZING     # alias -- see above

# ==========================================================
# THE 09:30 LOCK IS OFF  (2026-07-29, measured over 3 sessions)
# ==========================================================
# core/momentum_universe.py froze a top-25-gainers / top-25-losers list
# at 09:30 every day, logged it, saved it to disk and restored it on
# restart. NOTHING HAS READ IT FOR WEEKS.
#
# The operator asked the right question -- does the market only show its
# strength at that time, or was that one day's test? Three sessions of
# minute candles, counting how many of the day's CLOSING top 20 were
# already top 20 at each hour:
#
#     date             09:30    10:00    11:00    12:00    13:00    14:00
#     2026-07-27        8/20     8/20    10/20    12/20    12/20    13/20
#     2026-07-28        9/20    10/20    11/20    14/20    13/20    15/20
#     2026-07-29        2/20     7/20     7/20     8/20     8/20     9/20
#
# At 09:30 roughly a THIRD of the day's eventual leaders are visible --
# and on 29 July, two of twenty. Even at 14:00 it is only about 60%.
#
# There is no good hour to freeze a list. Early misses most of them;
# late sees more but leaves less time to profit. The earlier evidence
# (TMB at rank 95 at noon, closing 2nd, 98% of its volume after 13:00)
# was one day. This is three, and it says the same thing louder.
#
# The dashboard never needed it: Top 50 Gainers/Losers and the Sector
# Heatmap build from the circuit monitor's live snapshot, and the
# Shortlist rebuilds continuously by design.
ENABLE_MOMENTUM_LOCK = False

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
# ---- NOT THE OWNER ANY MORE. 12 August 2026. ----
#
# core/rules.py owns the live risk budget and says 1,500 -- the number
# he approved on 11 August. This said 2,000, and BOTH were live:
# core/engine.py sized its entries from this one and
# core/position_plan.py sized the ranker's from that one, so the same
# bot risked a different amount depending on which half of itself found
# the trade.
#
# Re-exported from core/rules.py rather than deleted, because
# backtest/replay.py and backtest/monday_replay.py read `cfg.RISK_PER_
# TRADE_RS` and a replay measuring 2,000 while the bot trades 1,500 is
# how twelve days of results came to describe a bot that does not
# exist. One value, every reader.
#
# To change the risk budget, edit core/rules.py. Not here.
from core.rules import RISK_PER_TRADE_RS       # noqa: E402  (= 1500.0)

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

# ---- THE SCALING STOPPED SCALING. 29 August 2026. ----
#
#     "do not fix the 2.5% for every stock"
#                                 -- operator, 18 August 2026
#
# VOLATILITY_SCALED_STOP was built to answer exactly that, and on
# the stocks this bot now trades it does not scale. Measured over
# the 101 qualified event trades of 18-29 August:
#
#     2.0 x daily ATR, bounded [0.75%, 6.0%]
#     -> median 6.0%, and 81 of 101 sit ON the ceiling
#
# These are 3.9%-ATR names by the nature of the setup -- a stock is
# only here because it moved 3%+ on volume with an event behind it
# -- so twice the daily range clears 6% almost every time and the
# cap flattens it. His instruction was already not being honoured;
# the live choice was never scaled-vs-fixed, it was WHICH fixed
# number, and 6% was chosen by a ceiling rather than by measurement.
#
# Same 101 trades, qty = RISK_PER_TRADE_RS / stop distance, held to
# the close, slippage charged on entry AND on the stop fill:
#
#                    no slip     0.2%      0.3%      0.5%   stopped
#     6% (live)     +15,955   +10,655    +8,004    +2,704     2/101
#     3.0% fixed    +32,685   +21,323   +15,642    +4,281    14/101
#     2.5% fixed    +38,559   +24,078   +16,838    +2,357    21/101
#     2.0% fixed    +53,994   +34,986   +25,482    +6,474    27/101
#
# 2.0% wins at every slippage level, and the tighter stop is what
# buys the size: Rs 24,930 a position becomes Rs 74,812, so five
# seats go from Rs 1.25 lakh to Rs 3.74 lakh of Rs 4.31 lakh.
#
# HE CHOSE THIS KNOWING THE COST. 27 stops instead of 2, and the
# bot no longer adapts the width to the stock. Set to None to fall
# straight back to the ATR-scaled rule -- nothing else changes.
#
# Read by core/engine.py _hard_stop_pct() and core/position_plan.py
# plan(). Both, or the alert and the position disagree.
FIXED_STOP_PCT = 2.0

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
# MTF POSITION SIZING, 2026-07-28 -- operator's own rule
# ----------------------------------------------------------
# "Buy no of shares worth equal to 1 Lakh = mtf power. ex - as of now
#  if i want to buy coforge 1686 rs - qty 225 with 99657.31 rs worth."
#
#     COFORGE 1,686 x 225 shares = Rs 3,79,350 position
#     margin Dhan actually blocks =  Rs   99,657   (26.27%)
#
# So the operator commits a FIXED Rs 1 lakh of his own margin per
# position, and the share count falls out of whatever margin that stock
# happens to require. He made the point himself: leverage is not fixed
# -- "some stocks may give more leverage & some none".
#
#     qty = MTF_MARGIN_PER_POSITION_RS / (price x that stock's margin %)
#
# A stock at 25% margin gives a Rs 4L position. One at 50% gives Rs 2L.
# One with no MTF gives Rs 1L, bought with his own cash. The commitment
# is identical either way.
#
# The margin % is NOT estimated. dhanhq exposes /margincalculator with
# product_type="MTF", which returns the same figure the order screen

# ==========================================================
# WHAT A TELEGRAM / DASHBOARD BUY GETS
# ==========================================================
#
#     "BUY SBIN = then bot must buy SBIN MTF with assigned rules
#      (capital, target, stoploss, trailling)"
#                                     -- operator, 23 August 2026
#
# Three of the four already applied: the desk refuses a non-MTF stock
# before it quotes, the quantity is risk-sized from RISK_PER_TRADE_RS,
# and the stop is the volatility-scaled one. TARGET and TRAILING did
# not exist on any entry at all.
#
# These apply to HIS commands only. The bot's own entries keep holding
# to the close, because every target width measured on 22-23 August
# underperformed holding -- seven widths, all worse. He chose that
# split when asked, and it keeps Monday's paper session a clean read
# of the bot's own behaviour.
MANUAL_BUY_TARGET_RS = 2000.0     # book it when the position shows this
MANUAL_BUY_TRAILS = True          # and ratchet the stop until it does

# shows -- so the bot asks Dhan rather than guessing, and self-corrects
# when Dhan changes a stock's rate or drops it from the MTF list.
#
# REPLACES the old sizing entirely. RISK_PER_TRADE_RS / MIN_STOP_
# DISTANCE_PCT produced Rs 2L on every trade regardless of the stock,
# because at a 1% stop both formulas are algebraically identical
# (2000/(0.01*p) == 200000/p). Every one of 2026-07-28's eighteen trades
# landed at Rs 1.90-2.00 lakh -- NILKAMAL, which swings 11% a day, got
# the same size as MANAPPURAM, which swings 2%.
# ==========================================================
# THE TRAIL SOLD THE WINNERS  (2026-07-29, measured)
# ==========================================================
# 80 real trades across 27, 28 and 29 July were replayed against
# their own minute candles. Same entries every time; only the exit
# rule changed. On the bot's own 35 structural entries:
#
#     exit rule                  n    win     total   per trade
#     what actually happened    35    43%    -1,252         -36
#     1.5% trail                35    43%     8,856         253
#     2.5% trail                35    46%    15,496         443
#     3.5% trail                35    51%    21,374         611
#     5.0% trail                35    51%    21,374         611
#     7.5% trail                35    51%    21,374         611
#
# The entries were worth over Rs 21,000. The exit logic gave all of
# it back and more.
#
# 3.5%, 5.0% and 7.5% are IDENTICAL because above 3.5% the trail
# never fires at all -- 33 of 35 trades simply ran to the close. So
# the finding is not "use a wider trail". It is "the trail should
# not be there".
#
# WHAT THE BOT WAS ACTUALLY RUNNING, which is not what was agreed:
# the operator approved 2.5% on 28 July, but structural entries used
# an ATR trail (ATR_TRAIL_MULTIPLIER 1.2). Measured across all 16 of
# its stop-outs, the drop from peak to exit was:
#
#     median 1.06%    min 0.65%    max 1.93%    under 2%: 16 of 16
#
# Not one reached 2.5%. His own words on 28 July -- "my strong
# feeling is we close much before this number touched".
#
# With this False the stop is set once, HARD_STOP_FROM_ENTRY_PCT
# below the entry, and never moves. It still closes a losing trade.
# It just stops selling the winners.
ENABLE_BOT_TRAILING_STOP = False

# The stop that remains. 2.5% from the entry price, fixed for the
# life of the trade -- the operator's own number, and the one every
# variant above was measured with underneath it.
HARD_STOP_FROM_ENTRY_PCT = 0.025

# ==========================================================
# ONE STOP WIDTH FOR 1,312 DIFFERENT STOCKS  (18 Aug 2026)
# ==========================================================
#
#     "do not fix the 2.5% for every stock. as u suggested
#      volatility-scaled stop may be best suited option"
#
# HE IS RIGHT, AND THE JOURNAL AGREES. core/signal_journal.py scored
# 12,036 recorded signals against the candles that followed them. At
# the flat 2.5% above, the stop was hit BEFORE the move on:
#
#     46.3%  of signals carrying evidence (news/results/orders)
#     27.8%  of signals carrying none
#
# Evidence-backed names move further in BOTH directions -- avg best
# +1.73% against +1.25%, avg worst -3.01% against -2.20% -- so the
# single number that is merely tight for a quiet stock is a
# guaranteed exit on a live one. The bigger move was being collected
# as a bigger loss.
#
# THE MACHINERY WAS ALREADY HERE AND POINTED AT THE WRONG CLOCK.
# _atr_entry_sizing() has computed an ATR stop since 24 July, off the
# engine's own ONE-MINUTE candles. Measured on 31 July:
#
#     symbol       1-min ATR   x0.8 stop     daily ATR
#     NAVINFLUOR      0.34%       0.27%         3.46%
#     POLYCAB         0.23%       0.18%         1.79%
#     ICIL            0.23%       0.19%         4.99%
#
# Switching that on would have produced quarter-percent stops -- TEN
# TIMES TIGHTER than the flat number it was meant to improve. A stop
# answers "has this idea failed", and an idea has not failed because
# a stock moved less than it moves on an ordinary day. That is a
# DAILY question and it is now asked on daily bars.
#
# MEASURED BEFORE IT WAS ARMED, on identical signals and candles:
#
#     stop rule          evidence stopped   result    no-evid stopped
#     flat 2.5% (old)          46.3%        -1.07%         27.8%
#     daily ATR x0.8           44.4%        -0.91%         25.4%
#     daily ATR x1.0           27.8%        -0.74%         11.4%
#     daily ATR x1.2           18.5%        -0.36%          6.1%
#
# HONEST LIMITS. n=54 evidence signals at minute resolution, over two
# sessions, because tools/collector.py stopped filling
# data/history_candles.db on 31 July. And every variant is still
# NEGATIVE: a wider stop cuts the loss, it does not manufacture a
# profit. This is a demonstration that 2.5% is the wrong shape, not
# that 1.2x ATR is a winning system.
VOLATILITY_SCALED_STOP = True

# Multiples of the stock's own ordinary daily range. Bounded by
# core/rules.MIN_STOP_DISTANCE_PCT / MAX_STOP_DISTANCE_PCT (0.75% and
# 6.0%), so no reading -- however strange -- can produce a stop that
# is either meaningless or ruinous.
# ---- MEASURED, 22 August 2026 ----
# 16,186 scored signals, identical history, only the multiple changed:
#
#     ATR x 1.2 (was)   avg -0.414%   stopped 15.1%
#     ATR x 2.0         avg -0.256%   stopped  8.0%
#     ATR x 2.5         avg -0.255%   stopped  8.0%   (plateau)
#
# It improves EVERY bucket -- evidence, no-evidence, high volume -- and
# flattens at 2.0, so this is the measured value and not a guess. The
# reason it matters: reason-backed stocks move further in both
# directions (best move 2.04% against 1.25% for unexplained), so the
# stop sized for a calm stock is the wrong stop for the ones his own
# rule selects. It was cutting the winners before the thesis played out.
DAILY_ATR_STOP_MULT = 2.0

# ==========================================================
# YOUR TRADES ARE YOURS  (2026-07-29, operator-found live)
# ==========================================================
# SMLMAH. The operator saw it locked at its UPPER circuit -- no
# sellers left, the strongest thing a stock can do -- and bought it
# deliberately. The bot closed the position within seconds, because
# a housekeeping rule says "near a circuit limit, get out".
#
# That rule protects nothing. It exists so the BOT doesn't get
# trapped in its own inventory. Applying it to a position a human
# opened on purpose means the operator's decision was overruled by
# a tidy-up routine.
#
# Three exits are pure housekeeping and never protect anyone:
#
#   CIRCUIT_PROXIMITY  near either circuit band, close it
#   NO_PROGRESS        flat too long, free the slot
#   ROTATED_OUT        a better breakout wants this seat
#
# None of them fires because you are losing money. With this flag
# on, none of them may touch a position you opened by hand.
MANUAL_POSITIONS_BOT_MAY_NOT_CLOSE = True

# The trailing stop on a MANUAL position warns instead of selling.
#
# 29 July, the operator's own numbers:
#
#     exits he made by hand    18 trades   + Rs  5,947
#     the bot's trailing stop  17 trades   - Rs 14,909
#
# Every rupee lost that day came from the trail. On his own trades
# he is the better exit, so it tells him and he decides.
#
# THE HARD STOP STILL FIRES -- deliberately. The trail sells you out
# of WINNERS; the fixed stop only fires on a real loss. It is the one
# thing standing between a position and a bad afternoon away from the
# desk. Alert-only on both was offered and refused.
MANUAL_POSITIONS_TRAIL_ALERTS_ONLY = True

# How many manual-position alerts to keep for the dashboard.
# RAISED from 50, 30 July 2026. In ALERT_ONLY_MODE the alerts ARE the
# product, not a side note about manual positions. Today's journal held
# 717 signals; the ones that clear every quality gate are what get
# alerted, and 50 would have silently dropped the earliest ones -- the
# 09:31 breakouts, which are the ones worth seeing. Truncation that hides
# the start of the day is worse than a long list.
MANUAL_ALERT_HISTORY = 400

# ---- FIRST REAL DAY, SMALLER SIZE. 5 August 2026. ----
#
#     "yes for tomorrow trade with lower capital . 30 K per position
#      in MTF ."
#
# Was 100,000. The bot has never placed a real order in its life, so
# the first live session runs the identical logic at under a third of
# the size. Nothing else changes: the same gates, the same Rs 1,500
# risk per trade, the same stops. Only the ceiling on how much margin
# any one position may consume.
#
# Raise it back when the join has been watched for a few sessions.
MTF_MARGIN_PER_POSITION_RS = 30_000.0

# Cached per session: margin rates change rarely, and a live API call on
# every click would put ~300ms between the operator pressing BUY and the
# order going out -- the exact latency being removed elsewhere.
# Re-checked on the first buy of each new day.
MTF_MARGIN_CACHE_SECONDS = 21600      # 6 hours

# When the margin call fails, or the stock has no MTF at all: buy with
# the operator's own cash only. Rs 1 lakh buys Rs 1 lakh of stock (59
# shares of COFORGE instead of 225). UNDER-leveraging is the safe error.
MTF_FALLBACK_MARGIN_PCT = 1.0

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

# ----------------------------------------------------------
# MARKET REGIME GATE -- SWITCHED OFF 2026-07-28
# ----------------------------------------------------------
# The gate above refuses a LONG whenever REGIME_BREADTH_THRESHOLD of the
# universe is declining, and a SHORT when it is advancing. "Trade with
# the tape, never against it." Defensible for a two-sided intraday
# system.
#
# It is wrong for THIS one, and it was costing entire sessions.
#
# 2026-07-28: 445 of 665 symbols declining -> SHORT_ONLY all day. The
# operator trades LONG ONLY. So the bot was structurally incapable of
# taking a single entry, silently, for the whole session -- one of the
# three reasons it placed zero automated trades that day. And CUB
# reported results and went +8.47% on that same 67%-red tape; this gate
# would have refused it.
#
# The deeper problem: a rule that switches the bot off on two-thirds of
# days makes it UNMEASURABLE. Nothing can be learned about entries,
# exits or the reason gate on a day the bot cannot trade.
#
# Operator's decision, 2026-07-28, asked directly: "A" -- remove it for
# longs so tomorrow's paper session can actually measure something.
#
# NOT DELETED. The gate is intact and one flag away, because "trade with
# the tape" may well prove right once there is data to judge it on. It
# is off because it is UNPROVEN and expensive, not because it is wrong.
#
# Blocked breakouts are still recorded on the Fresh Breakouts panel
# either way, so the operator can see what the gate WOULD have refused.
ENABLE_MARKET_REGIME_GATE = False
REGIME_REFRESH_SECONDS = 30
REGIME_MIN_SYMBOLS = 100

# --- Risk guardrails (items 4 & 5: cap + explicit daily goal) ---
# Hard cap on CONCURRENT open positions. 131 concurrent positions
# (2026-07-23) is not a strategy, it's spray-and-pray -- and in live
# trading each one ties up real margin. 10 forces the bot to be
# selective: once full, new signals are skipped until a slot frees.
# ---- THREE, FOR THE FIRST LIVE DAY OF THE RANKER. 7 Aug 2026. ----
#
#     "2/3 is enough today . i'll trade cautiously"
#
# Ten was sized for capital, and at Rs 4.31 lakh the capital genuinely
# allows it. But 6 August filled EIGHT positions off the breakout path
# before he noticed, and today is the first live session for the ranker
# path -- which has never taken a single real trade.
#
# The point of three is not risk. Three entries he can read one by one
# and judge whether the reason given was sound; ten he cannot. Raise it
# once the picks have been scored against what those stocks did.
MAX_OPEN_POSITIONS = 3

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
# ----------------------------------------------------------
# ALERT ONLY -- the bot stops trading and starts telling, 30 July 2026
# ----------------------------------------------------------
#     "we will stop completely bot from trade taking as of now. it must
#      show me the stock in alerts only."      -- operator
#
# WHY, in his own words and the journal's numbers. On 30 July the bot
# placed 16 of its 29 trades between 09:31 and 09:35, filling all ten
# slots in four minutes, and then refused 665 signals for the rest of the
# day. It took THYROCARE on 0.03x normal volume because a slot happened
# to be free, and six minutes later refused KSB on 715x volume because
# the book was full. Nothing compared the two.
#
# There are real gates per stock -- relative strength, circuit room,
# results timing, liquidity -- but there is no ranking BETWEEN
# candidates, so the winner is whoever ticks first. engine.py's own
# comment calls a slot refusal "an accident of timing, not a judgement".
#
# Until that is fixed, the bot has no business choosing. So it does not
# choose: every signal that would have been an entry becomes an ALERT
# with the reason attached, and the operator decides.
#
# THIS IS NOT THE PAUSE FLAG. trade_controller's pause is a runtime
# toggle that skips SILENTLY -- "no log line", by design, because it
# fires on every candle close. Silence is exactly wrong here: the whole
# point is to be told. Separate flag, separate behaviour.
#
# Manual BUY / SHORT from the dashboard still work. This gates the
# AUTOMATED entry only.
# ----------------------------------------------------------
# TURNED BACK ON, IN PAPER, 12 August 2026.
# ----------------------------------------------------------
#     "i want a bot which checks for the opportunity in the live
#      markets & do trade" -- operator
#
# The exact problem this flag was raised for on 30 July -- no ranking
# between candidates, first-come-first-buy, THYROCARE taken on 0.03x
# volume while KSB was refused on 715x -- is what core/ranker.py +
# core/auto_entry.py were built to fix: every ranked pick is now scored,
# sorted BEST FIRST (not first-fired-first), and REQUIRED to carry a
# reason (core/why_moving.py) and pass a hard volume-ratio gate
# (core/rules.MIN_VOLUME_RATIO) before it can reach an entry -- see
# core/ranker.py's mandatory gates and core/auto_entry.py's early_rows()
# (the 09:15-09:30 graded lane, wired into main.py the same day this
# flag flipped). Both paths refuse a stock with no story to tell, which
# is the rule this flag existed to enforce by hand.
#
# TRADING_MODE stays "PAPER" (above) -- this arms automated PAPER
# entries only, on real live market data. No real order can result from
# this flag alone; that still needs TRADING_MODE = "LIVE" AND
# LIVE_ALLOW_BOT_ENTRIES = True, both separately, both untouched here.
#
# The legacy structural ORB-breakout path (core/engine.py's
# _try_structural_entry(), reached when NOT coming through the ranker)
# is UNCHANGED by this flag -- it still needs its own separate
# `breakout_armed` switch, off by default, because it has no reason
# requirement at all (see core/engine.py, "ONE SWITCH WAS ARMING TWO
# BUYERS", 6 August 2026). Re-arming the ranked/early-bird paths here
# does not re-arm that one.
#
# ==========================================================
# BACK TO True. HIS INSTRUCTION, 12 August 2026.
# ==========================================================
#
#     "by default bot trading = OFF (Bot Observing) when i start
#      main.py . i can ON when i want bot to trade with the same rules"
#
# This was False, so main.py came up ARMED. The dashboard switch was
# built to be the control -- and the thing it controls was already on
# before he touched it.
#
# The switch's own docstring in dashboard/server.py has claimed the
# opposite since 5 August:
#
#     "It is deliberately NOT written back to config.py. A restart
#      returns to ALERT_ONLY_MODE, which is the safe value: if the bot
#      dies at 11:00 and comes back while he is away from the desk, it
#      must come back watching, not trading."
#
# That safety property was written against a True that had drifted to
# False, so the restart-comes-back-safe guarantee was not true.
# AUDIT_2026-08-12.md caught the drift ("rule book says True -- drifted")
# and nobody moved it back.
#
# WHAT THIS DOES AND DOES NOT CHANGE
#   - main.py starts with engine.alert_only = True  -> BOT OBSERVING
#   - the dashboard ON button sets alert_only False -> BOT TRADING
#   - OFF sets it back. Neither needs a restart.
#   - a restart or a crash returns here: observing.
#   - EXITS ARE UNAFFECTED. Stops, trails and targets run on anything
#     already held whatever this says -- see core/engine.py's
#     "Exits deliberately ignore alert_only so a stop always fires".
# ---- HE ASKED TO ARM IT. THE CONFIG IS THE WRONG SWITCH. ----
#      20 August 2026.
#
#     "yes do both. so basically paper trades will be logged"
#
# He said yes to arming the bot, and I started by flipping this to
# False. That was wrong, and his own words from 12 August say why:
#
#     "by default bot trading = OFF (Bot Observing) when i start
#      main.py . i can ON when i want bot to trade with the same
#      rules"
#
# He set this to True that day HAVING ALREADY TRIED False, for two
# reasons that have not changed:
#
#   1. This is the STARTUP value and the dashboard/Telegram switch is
#      the control. With it False, main.py comes up already armed and
#      the ON switch has nothing left to turn on.
#   2. dashboard/server.py has promised since 5 August that "a
#      restart returns to ALERT_ONLY_MODE, which is the safe value --
#      it must come back watching, not trading". False makes that
#      guarantee a lie, and a crash at 11:00 would restart into a
#      trading bot.
#
# So arming is done the way he built it: start disarmed, send ON when
# he wants the session armed. That is a decision per session rather
# than a decision once, which is the right shape for a switch that
# spends money -- and today it spends paper money, which is the whole
# point of the experiment.
ALERT_ONLY_MODE = True


# =====================================================================
# THE AI LAYER -- budget, scope, and what it is allowed to touch
# =====================================================================
#     "max .2500 per month is cap. & we need to use the best case of AI
#      & trade by using the AI"          -- operator, 30 July 2026
#
# Costed against the bot's OWN measured volumes on 30 July: 82 news
# stories, 133 Telegram messages and 731 ORB signals a day.
#
#     Haiku on news + telegram + events        Rs 1,084 / month
#     Sonnet on ~30 shortlisted decisions      Rs 1,272 / month
#     ------------------------------------------------------
#     total                                    Rs 2,356 / month
#     with prompt caching                      Rs   825 / month
#
# It fits. But it only fits because the model is asked about the ~30
# stocks that survive the arithmetic, not all 731 signals. Sending every
# signal to Sonnet costs Rs 28,369 a month -- twelve times more, for
# worse answers, because most of those 731 are noise the cheap filters
# already reject correctly.
#
# THAT IS THE DESIGN, not an optimisation: cheap deterministic filters
# first, the model only on what survives.
AI_ENABLED = False              # master switch. Nothing calls out while False.

# HARD CEILING. When the month's recorded spend crosses this, every call
# stops until the 1st. Not a warning -- a refusal.
#
# It exists because the failure mode is not "expensive", it is a retry
# loop at 3am turning Rs 2,500 into Rs 25,000 while nobody is watching.
# The bot already refuses to trade past its daily loss limit; this is
# the same idea pointed at the API bill.
AI_MONTHLY_BUDGET_RS = 2500.0
AI_USD_INR = 88.0               # only to convert token cost into rupees

# Below this the bot warns but keeps going; above it, it stops.
AI_BUDGET_WARN_AT_PCT = 0.75

# WHICH MODEL FOR WHAT.
# Haiku classifies and extracts -- high volume, low judgement.
# Sonnet decides -- low volume, high judgement.
AI_MODEL_CHEAP = "claude-haiku-4-5-20251001"
AI_MODEL_SMART = "claude-sonnet-5"

# How many stocks reach the expensive model per day. The shortlist is
# already ranked; this is the top slice of it.
AI_DECISION_CANDIDATES_PER_DAY = 30

# ---------------------------------------------------------------------
# WHAT THE MODEL MAY AND MAY NOT DECIDE
# ---------------------------------------------------------------------
# The operator's goal is "trade by using the AI". These flags are the
# staircase to that, one step at a time, and each one is a separate
# decision he makes -- not a thing that arrives switched on.
#
# ---- WHICH OF THESE ARE ENFORCED, AND WHICH ARE A PLAN ----
#      12 August 2026.
#
# AUDIT_2026-08-12.md listed five of these as dead constants and said
# to delete them. Checked one by one instead, and "dead" is the wrong
# word for two different situations that look identical in a grep:
#
#     AI_MAY_AFFECT_SCORE      READ BY CODE. A real gate.
#     AI_NEWS_DIRECTION        read by nothing
#     AI_SHOW_IN_SHORTLIST     read by nothing
#     AI_MAY_RANK_ENTRIES      read by nothing
#     AI_MAY_SIZE_POSITIONS    read by nothing
#     AI_MAY_MOVE_STOPS        read by nothing
#
# The five unread ones are NOT protecting anything. They are the plan
# written down, and the features they would gate do not exist yet -- so
# "False" here is a statement of intent, not a lock.
#
# They are KEPT, because the staircase is the clearest description of
# where this is going and deleting it would lose that. But the last two
# say "leave False permanently", which reads like an enforced boundary
# and is not one. If somebody builds AI position sizing tomorrow,
# nothing in this file will stop them -- they have to come here and
# read this. That is the honest state, and it is now written down
# rather than implied.
#
# THE RULE FOR WHOEVER WIRES ONE OF THESE UP: add the `if not
# config.AI_MAY_X: return` at the same time as the feature, in the same
# change. A flag that arrives after the capability has already shipped
# has never once been added.
#
# STEP 1  the model reads news and says what it means. Recorded, shown,
#         and worth nothing to the score. This is where it starts.
AI_NEWS_DIRECTION = False
#
# STEP 2  the model's view becomes a why-chip on the shortlist. Visible
#         to the operator, still not scored.
AI_SHOW_IN_SHORTLIST = False
#
# STEP 3  the model's view MOVES THE SCORE. Only after enough recorded
#         calls have been checked against what the stock actually did.
#         There is no honest way to skip this: on 30 July the bot's own
#         arithmetic reported +Rs 9,498 on a day it really lost
#         Rs 11,239, and an unchecked model on top of an unchecked
#         scorer is two things nobody can audit.
AI_MAY_AFFECT_SCORE = False
#
# STEP 4  the model chooses WHICH of several simultaneous breakouts to
#         take. This is the real prize -- it replaces first-come-first-
#         served, which on 30 July took THYROCARE at 0.03x volume and
#         refused KSB at 715x.
AI_MAY_RANK_ENTRIES = False

# NEVER. Not a staircase step -- a boundary.
#
# The model does not size a position and does not move a stop. Those are
# arithmetic on money at risk, they are exact, and a language model is
# strictly worse at them than the code already is. A wrong direction
# costs one trade; a wrong size costs the account.
AI_MAY_SIZE_POSITIONS = False   # leave False permanently
AI_MAY_MOVE_STOPS = False       # leave False permanently

# ---------------------------------------------------------------------
# THE FRIDAY TEST -- one share, by hand, from the dashboard
# ---------------------------------------------------------------------
#     "Friday . we planned 1 manual share buying & selling in MTF from
#      our dashboard"                    -- operator, 30 July 2026
#
# A manual dashboard BUY normally sizes itself by risk (_risk_sized_qty),
# which on a Rs 300 stock is hundreds of shares. That is correct for
# real use and completely wrong for the first order this account has
# ever sent through the bot.
#
# Set to a number and EVERY manual dashboard BUY/SHORT places exactly
# that many shares, whatever the risk maths says. Set to None and normal
# risk sizing applies.
#
# This deliberately does NOT touch automated entries. It cannot: the bot
# is in ALERT_ONLY_MODE and takes none. If that changes, this stays a
# manual-only override -- a test size must never quietly become the
# size the bot trades.
# ---- TURNED OFF 1 August 2026, ON THE OPERATOR'S INSTRUCTION ----
#
#     "i'll trade with 1 lakh not 1 share of qty.. from dashboard"
#
# With this None, a dashboard BUY is sized by _risk_sized_qty(): Rs 1
# lakh of HIS OWN margin per position, share count asked of Dhan.
#
#     COFORGE 1,686 @ 26.3% margin -> 225 shares
#                                  -> Rs 3,79,350 of stock
#                                  -> Rs   99,655 blocked
#                                  -> a 1% stop costs Rs 3,794
#
# Set it back to 1 for a day of testing the order path without size.
MANUAL_TEST_QTY = None

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
# 2026-07-29, operator's call: turned ON for the two remaining paper
# sessions before live on 3 August.
#
# What it is for, in his words: "real movers are ignored by bot. as
# first see = buy & 10 slots filled." Today's book proves the point --
# it sat at 9 or 10 positions from 09:30 until 14:00, so every breakout
# in four and a half hours was refused for no reason except that ten
# other names arrived earlier.
#
# WHO GETS SWAPPED: the weakest position THE BOT ITSELF opened, judged
# on trend strength. Positions the operator opened by hand are skipped
# entirely (see core/engine.py's _can_rotate_out). At 10:19 today that
# meant MOBIKWIK at +0.45%, not CUB at -2.26%, because CUB was his.
#
# HAS NEVER RUN IN PRODUCTION. Thursday is its first live session, on
# paper, with a hard cap below.
#
# ---- THE FRIDAY MEASUREMENT, AND IT SAYS OFF. 21 Aug 2026 ----
#
# The note below asked for exactly this: "read tools/refused_review.py
# on Friday and set it from the data." This is Friday. Every
# ROTATED_OUT trade on record, data/trade_memory.db:
#
#     ROTATED_OUT        n= 15   net -Rs  1,860   won  3 of 15  (20%)
#     every other exit   n=122   net -Rs 80,379   won 48 of 122 (39%)
#
#     median holding time      2.3 minutes
#     closed inside 5 minutes  10 of 12
#
# It is the worst win rate of any exit reason in the book, and the
# holding time says why. A position sold 2.3 minutes after entry was
# not sold on information -- the setup had no time to work or to fail.
# That is not "a stronger breakout needs the slot", it is noise
# crossing a 0.4% edge back and forth.
#
# 21 August, live, in 32 minutes:
#
#     10:14  SELL URBANCO -> BUY JSFB
#     10:18  SELL JSFB    -> BUY URBANCO    (sold 4 minutes earlier)
#     10:22  SELL NCC     -> BUY JSFB       (sold 4 minutes earlier)
#     10:31  SELL JSFB    -> BUY NCC        (sold 9 minutes earlier)
#
#     four legs, four losses, -Rs 873 realised
#
# It bought back what it had just sold, three times. Nothing forbids
# that: ROTATED_OUT deliberately never arms BLOCK_REENTRY_AFTER_
# STOPOUT so a rotated name can return "if it climbs back up the
# leaderboard" -- written for a name that recovers over a session, not
# one oscillating on a four-minute cycle. And ONE_TRADE_PER_SYMBOL_PER
# _DAY, which would have stopped it, was assessed on 29 July against
# RE-ENTRY AFTER A STOP-OUT, where a stock must fall 2.5% and break
# out again. URBANCO was sold at -0.48%. That assessment never covered
# this case.
#
# n=15 is small and this is not a permanent verdict. But the mechanism
# is demonstrably churning rather than upgrading, and every leg pays
# slippage and charges. OFF until a rotation is shown to beat holding.
#
# To put it back: set this True. The cap below is untouched.
# ---- BACK ON, WITH THE CONSTRAINTS THAT WERE MISSING. 23 Aug ----
#
#     "fix the seat timing"          -- operator, 23 August 2026
#
# It was switched OFF on 22 August because it churned: a 0.4% edge and
# NO minimum holding period gave a 2.3-minute median hold, 20% winners
# and -Rs 1,860 over 15 trades. CDSL was bought and sold ELEVEN
# SECONDS apart.
#
# But OFF leaves the real problem unsolved. Seats are spent in the
# first minutes and the good names arrive later: 20 August, the first
# rank-1 was STAR at 09:30 which lost, and SOLARA did not lead the
# board until 10:24 and closed +16.4%. With rotation off, that seat
# could never have been handed over.
#
# The edge is now 2.0% and a position gets 45 minutes to work. Both
# numbers are set so that the SOLARA hand-over passes and the CDSL
# twitch does not. Leaving the switch off would have been shipping a
# fix that never runs.
ENABLE_SLOT_ROTATION = True

# At most this many swaps a day.
#
# The edge required is only 0.4% (ROTATION_MIN_STRENGTH_EDGE), and a
# challenger carrying the operator's confirmations needs as little as
# 0.1%. That is easy to clear. With 666 symbols breaking out all day
# and nothing counting the swaps, the bot could churn the whole book
# repeatedly -- every swap paying slippage and charges, and every one
# selling a position that the new no-trail rule was meant to let run.
#
# Nobody has measured what the right number is. Five is a deliberate
# floor for two paper sessions, not a considered answer -- read
# tools/refused_review.py on Friday and set it from the data.
ROTATION_MAX_PER_DAY = 5
ROTATION_MIN_STRENGTH_EDGE = 0.020   # challenger must lead by >2.0% move

# ---- WHY THE EDGE MOVED, AND WHY A HOLD TIME EXISTS NOW ----
#
#     "fix the seat timing"            -- operator, 23 August 2026
#
# THE PROBLEM IS REAL. 20 August: the bot's first rank-1 was STAR at
# 09:30, which lost. SOLARA did not reach rank 1 until 10:24 and closed
# +16.4%. Seats are spent in the first minutes and the good names
# surface later. Measured over 20 sessions, filling the same three
# seats from the board as it stood at each hour:
#
#     commit at   Rs/trade   win%
#     09:45         -279     31.8
#     10:30         -115     40.0
#     13:00          -64     46.7
#     14:00          -19     51.7
#
# Patience raises the win rate steadily. Nothing is reliably positive,
# so this is a direction, not a discovery.
#
# A TIME LADDER IS NOT THE ANSWER. STAGED_POSITION_LIMITS was exactly
# that and was flattened on 27 July: "a strongly bullish tape produced
# two trades before 10:00 and nothing after, because both early seats
# were spent by 09:26". It throttles the whole day to fix one hour.
#
# Rotation is the right mechanism -- give a seat up when something
# clearly better appears -- and it churned because it was allowed to
# swap on almost nothing:
#
#     0.4% edge, no minimum hold  ->  median hold 2.3 minutes,
#                                     20% win rate, -Rs 1,860 over 15
#     21 Aug: CDSL bought and sold ELEVEN SECONDS apart
#
# So the edge is 2.0% -- five times what it was -- and a position must
# be given ROTATION_MIN_HOLD_MINUTES to work before its seat can be
# taken. SOLARA at 10:24 beat STAR by far more than 2%; the 11-second
# CDSL swap cleared 0.4% and nothing else.
ROTATION_MIN_HOLD_MINUTES = 45

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
# ---- 15:15, NOT 15:00. His decision, 8 August 2026. ----
#
#     "15:15 & results gate open for the chips"
#
# The 15:00 cutoff existed for one reason, stated in its own
# comment above: "a brand-new position opened at 14:50 has ~25
# minutes to work before forced square-off". That reason is gone.
# FORCE_SQUARE_OFF_AT_CLOSE is False and positions are held on MTF
# overnight, so a 15:10 entry is not a coin flip with a deadline --
# it is a position that carries. The gate outlived its argument.
# 23 August 2026: 15:30, in lockstep with LAST_ENTRY_TIME above. This
# one is the harder gate of the two -- _position_ceiling() returns 0
# past it, so the book is shut regardless of what auto_entry allows.
# Back in lockstep with LAST_ENTRY_TIME above: CAS ends continuous
# trading in F&O names at 15:15, so the book must shut with it.
STAGED_NO_ENTRY_AFTER = "15:15"

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
#
# ASSESSED AGAINST MTF AND REMOVED -- 2026-07-29, operator's decision:
# "Remove stocks trading rule of 1 side 1 time."
#
# This is the assessment the note above asked for, not a repeat of the
# old intraday argument. What changed is the stop, not the opinion:
#
#   the churn this rule stopped   CHENNPETRO 9x, CORONA 6x -- under a
#                                 0.4% TRAIL FLOOR, where ordinary
#                                 noise triggered the stop-out
#   the stop today                2.5% HARD, trail off entirely
#                                 (ENABLE_BOT_TRAILING_STOP = False)
#
# A stock must now genuinely fall 2.5% AND then break out again to
# re-enter. That is a different event from being shaken out by 0.4%
# of noise nine times.
#
# MEASURED on 2026-07-29: twelve symbols were refused a second
# attempt. KAYNES was refused at 10:14 from 3,400 and reached
# 3,684.70; EPACKPEB refused at 10:39 and gained 4.2%. But the median
# refused symbol only gained 0.8% at its best and closed +0.3% -- so
# this is NOT a clear win on one session's evidence. It is the tail
# that pays, and the operator wants the tail.
ONE_TRADE_PER_SYMBOL_PER_DAY = False

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

# --- Live announcements (core/announcement_watcher.py) ----
# main.py used to refresh the results calendar exactly ONCE, at startup,
# and never again. On a day when 68 companies report, the bot learned
# about a 12:12 filing the following morning. Canara Bank filed around
# noon on 2026-07-27; at 13:50 the bot still had no idea.
#
# The exchange is not the slow part. tools/watch_results.py measured the
# gap between NSE publishing and us seeing it at about ONE SECOND. The
# entire delay was our own polling.
#
# 60s. NSE's announcements endpoint returns the whole recent window on
# every call, so this is one modest request a minute, on its own daemon
# thread, never on the tick path. Faster buys little -- the operator
# still has to read the row and decide.
ENABLE_ANNOUNCEMENT_WATCHER = True
ANNOUNCEMENT_POLL_SECONDS = 60
# How far back each poll looks. Generous on purpose: a restart at 14:00
# must not lose the morning's filings, and re-seeing a row we already
# know costs nothing (deduped on symbol + timestamp).
ANNOUNCEMENT_LOOKBACK_HOURS = 8
ANNOUNCEMENT_PANEL_COUNT = 25

# ---- WHO WAS IN A HURRY. 29 August 2026. ----
#
#     "by volume , order flow which carries the buyer & seller will
#      give us info"                            -- operator
#
# volume_ratio() measures how MUCH traded. It cannot say whether a
# stock on 5x volume is being accumulated or distributed -- turnover
# reads identically either way. His claim is that the buyer/seller
# split turns before the price does, and the bot cannot answer it
# because total_buy_quantity, total_sell_quantity and LTQ arrive on
# every tick and are discarded.
#
# core/order_flow.py records them per symbol per minute. It feeds NO
# decision and is not wired to one: the cheap version of his idea
# (surge SIZE, not composition) measured -Rs 30,664 over 1,049
# stock-days this morning, so composition gets measured before it
# gets believed. A few weeks of this store is what makes the question
# askable at all.
#
# All ~1,300 subscribed stocks, not the shortlist -- the whole point
# is catching the turn BEFORE a stock qualifies. PRECWIRE at 11:00 on
# 28 August was not a candidate; by the time it was, it was +8%.
# Roughly 490k rows a session, the same order as the candle store.
ENABLE_ORDER_FLOW_RECORDER = True
ORDER_FLOW_FLUSH_SECONDS = 30

# ---- THE CYCLE COULD NOT FINISH IN A SECOND. 29 August 2026. ----
#
# Measured on the real stores: dashboard_state.refresh() is asked to
# run every DASHBOARD_REFRESH_INTERVAL_SECONDS (1), and the reason
# lookup alone took 1,590 ms of it -- why() at a median 15.1 ms x 105
# symbols carrying news. So the loop was running at roughly 1.7-2s a
# cycle: about 13,000 cycles between 09:15 and 15:30 instead of
# 22,500. It missed no event -- the reason set is rebuilt every cycle
# either way -- but every entry landed a second or two late.
#
# Two one-off costs sat on top: 2,071 ms for the first call of the
# session, and one call in 105 taking 8,432 ms when the cache inside
# core/opportunity.evaluate() rebuilds (it walks ~14,000 events and
# fires 227,577 regex searches, roughly twice an hour).
#
# why() was re-deriving the same answer every second for a stock
# whose news had not changed since 09:41. Caching it per symbol takes
# the reason path from 1,590 ms to about 50 ms.
#
# THIRTY SECONDS, NOT LONGER, because of his rule:
#
#     "if 100 stocks were there at morning & by 11 5 stocks got news
#      . then bot must include those stocks too"
#
# A stock that gets news at 11:00:05 is a candidate by 11:00:35. The
# membership question is answered by this lookup, so this TTL IS the
# bot's reaction time to fresh news. Raising it trades entry speed
# for cycle time; 0 disables the cache entirely.
REASON_CACHE_SECONDS = 30

# Read the PDF attached to a results filing (core/results_ingest.py).
# THE ONLY SOURCE WITH THE FIGURES, measured 2026-07-27:
#   - the announcement text has none. Seven real filings that evening
#     averaged 130 characters of boilerplate and nothing else.
#   - bse.resultsSnapshot lags (TMB reported and it still showed Mar-26)
#     and returns two quarters, so YoY is impossible from it.
#   - the PDF has the current quarter, the previous quarter AND the
#     year-ago quarter at full precision. MOLD-TEK's Q1 FY27 table parses
#     to +26.31% QoQ sales; page 1 of the same document says 26.32% in
#     prose. The table and the prose agree.
# Runs on its own thread -- the filings are large (MOLD-TEK's was 7 MB)
# and downloading one inside the news poll would stall the feed exactly
# when news is arriving.
ENABLE_FILING_PDF_READING = True

# --- High-conviction news (core/news_watcher.py) ----------
# The previous news subsystem (~3,200 lines) was deleted 2026-07-26 --
# it ran a thread through every session and nothing read the output.
# This is the operator's tighter brief from the same day: news, but ONLY
# key events that can move a stock.
#
# The gap it fills, measured on 2026-07-27: the filings watcher would
# have missed BOTH of the day's biggest single moves --
#   GANDHAR   -11.6%  flood damage at its Silvassa plant
#   CARTRADE  +10.8%  UBS initiated Buy, target Rs 4,000
# One is a news story, the other a broker note. Neither is a filing.
#
# 180s. RSS is cheap but these are public feeds; polling harder buys
# nothing and risks being throttled.
ENABLE_NEWS_WATCHER = True
NEWS_POLL_SECONDS = 180

# --- Shortlist panel (core/shortlist.py) ------------------
# The dashboard panel that answers "which of these 689 deserve thirty
# seconds of my attention, and WHY". Operator, 2026-07-27: "as a human
# i cannot read all 750/960/1500 stocks daily, i created bot to trade
# beside me not replacing me."
#
# 30s, NOT the 09:30 one-shot lock core/momentum_universe.py uses.
# Measured that day by rebuilding the ranking at nine clock times:
# of the closing top 20, only 12 were already top 20 at 09:30, and TMB
# -- the day's best stock at +12.1% -- sat at rank 95 at noon with 98%
# of its volume still to come after 13:00. A frozen list cannot hold
# it. The rebuild itself is arithmetic over rows the dashboard already
# computed, so the cadence is cheap; the slow part (50-day volume and
# trend normals) is loaded once per day and cached.
SHORTLIST_REFRESH_SECONDS = 30
# 25 rows. Deliberately looser than momentum_universe's top-25 LOCK,
# because this list only costs attention, never a seat: showing eight
# names when three are worth it costs thirty seconds, missing TMB
# costs the trade.
SHORTLIST_COUNT = 25

# Fresh Breakouts panel (core/breakout_feed.py), 2026-07-28. How many
# rows the panel shows. Newest first, so this is "how far back can I
# scroll", not "how many matter" -- a breakout more than ~20 old is
# history, and the panel greys out failed ones rather than dropping
# them so the list is not all live opportunities.
BREAKOUT_PANEL_COUNT = 20

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
# ==========================================================
# RE-CHOSEN 2026-07-29, after leverage started working
# ==========================================================
# Rs 20,000 was set when a position was Rs 1 lakh of STOCK. The MTF
# margin call had been failing silently on a NameError for weeks, so
# every position was unleveraged and a 2.5% stop cost about Rs 2,500 --
# eight losing trades before the day ended.
#
# With leverage working, one position controls ~Rs 3.8 lakh and the same
# 2.5% stop costs about Rs 9,500:
#
#     one failed trade, 2.5% stop
#       no leverage (what was really running)   Rs 2,500  -> 8.0 trades
#       MTF working (from 30 July)              Rs 9,500  -> 2.1 trades
#
# Nobody decided to tighten this to two trades; it happened by
# arithmetic. Rs 40,000 restores the ORIGINAL INTENT -- about four
# failed trades -- rather than preserving a number that now means
# something else. 4% of Rs 10 lakh.
#
# ---- AND THE ARITHMETIC ABOVE WAS WRONG. 11 August 2026. ----
#
# The "Rs 9,500 per failed trade" figure assumes one position controls
# ~Rs 3.8 lakh. It does not. A position is capped at
# MTF_MARGIN_PER_POSITION_RS (Rs 30,000) of margin, and at MTF_LEVERAGE
# 4x that is Rs 1.2 lakh of stock, not Rs 3.8 lakh. The same 2.5% stop
# therefore costs about Rs 3,000:
#
#     30,000 margin x 4 leverage x 2.5% stop  =  Rs 3,000
#
# So Rs 40,000 was never "about four failed trades". It was THIRTEEN --
# and two separate tests have been failing on exactly that since:
#
#     tests/test_daily_limits.py                  14.0 trades, wants 3.5-5
#     tests/test_manual_stop_is_the_hard_stop.py  13.3 trades, wants 3-5
#
# The kill switch is the one control that protects the worst day of the
# year, and it was three times looser than the number written beside it
# claimed. Rs 12,000 is four failed trades at the REAL per-trade loss,
# which is what this was always meant to be:
#
#     12,000 / 3,000  =  4.0 failed trades
#
# If a position's margin or leverage changes, this number has to be
# re-derived -- it is 4 x (MTF_MARGIN_PER_POSITION_RS x MTF_LEVERAGE x
# HARD_STOP_FROM_ENTRY_PCT), not a round figure chosen for its own sake.
#
# It blocks NEW ENTRIES only. It has never closed an open position and
# still does not.
DAILY_MAX_LOSS_RS = 12000.0

# The operator's own item-5 number: once the session's realized P&L
# reaches this, stop taking new entries -- the day's goal is met,
# don't hand it back. Same "existing positions still managed
# normally" semantics as the loss switch above.
# RAISED 2026-07-29. The profit target was biting before the loss limit
# ever did.
#
# All three recorded sessions, scored under the new exit rules and with
# leverage working:
#
#     date          trades   x3.8 leverage
#     2026-07-27        21           8,476
#     2026-07-28        19          49,687   <- would have STOPPED at 30,000
#     2026-07-29        40          24,552
#
# On 28 July the bot would have crossed Rs 30,000 partway through the
# day and switched itself off, leaving Rs 19,687 on the table. That is
# not a safety net firing -- it is the bot quitting in the middle of its
# best day.
#
# Rs 75,000 keeps a ceiling for a genuinely wild session while letting a
# normal good one run. Each position is already protected by its own
# 2.5% stop, and the day is still protected by DAILY_MAX_LOSS_RS above.
DAILY_PROFIT_TARGET_RS = 75_000.0
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
# 2026-07-29, operator's rule: "we need some confirmation before
# entries ... Volume". Measured on his own three sessions, the single
# worst trade of all 35 was the one that broke out on BELOW-average
# volume -- Rs 4,994 lost on its own.
ENABLE_VOLUME_FILTER = True

# How many minutes of volume to add up for the breakout reading.
#
# One minute is not enough. Dhan reports a running day total and a
# candle's volume is the difference between its first and last reading
# inside that minute -- so a minute that received only ONE snapshot
# reports zero. That happened to 11% of every candle recorded across
# 27, 28 and 29 July, and to 7 of the bot's 35 breakouts.
#
# Five minutes cannot miss in the same way, and summing is exactly
# right for a cumulative feed: shares missed by a one-snapshot minute
# are counted in the next minute's difference, so the window total is
# correct even when its individual minutes are not.
VOLUME_WINDOW_CANDLES = 5

# The change the operator asked for on 29 July: a breakout whose
# volume genuinely cannot be measured is now REFUSED rather than
# waved through.
#
# Before this, _breakout_has_volume() failed OPEN on every unknown --
# "volume is a quality bonus, never a hard gate". His answer:
#
#     "without volume how the stock moves upside ?"
#
# A breakout nobody can see the volume behind is exactly the one not
# to buy. Set False to restore the old permissive behaviour -- the
# tests cover both paths.
VOLUME_REQUIRED_FOR_ENTRY = True
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
# 2026-07-29, MEASURED -- turned off. Replayed over the bot's own 35
# structural entries with the trail already removed:
#
#     WITHOUT partial exit      51% win    Rs 21,374    Rs 611/trade
#     WITH partial (2xATR/50%)  66% win    Rs  9,761    Rs 279/trade
#
# It raises the win RATE and halves the MONEY. 23 of the 35 trades
# reached the 2x ATR level; of those:
#
#     16 kept going / ended above entry -> the partial COST  Rs 14,508
#      7 reversed  / ended below entry -> the partial SAVED Rs  2,894
#
# So it is not useless -- it rescued Rs 2,894 on the seven that turned.
# It simply costs more than twice that on the sixteen that ran. Two
# winners keep going for every one that reverses, and booking half at
# that moment bets on the one in three.
#
# WHERE THIS FLIPS: in a choppy market that spikes and fades, those
# counts invert and the partial starts paying. Three sessions in one
# mood is not enough to call it permanently -- hence a flag, not a
# deletion. Re-run tools/trail_sweep.py after another week.
#
# The operator saw this live before the numbers did, on KAYNES (30 of
# 59 booked) and EPACKPED: "booked small portion of them".
ENABLE_PARTIAL_EXIT = False

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
# ---- THE PAPER PURSE MUST MATCH THE REAL ONE. 9 Aug 2026. ----
# Rs 10 lakh of imaginary money sizes positions he could never
# actually take and hands back a P&L he could never actually earn.
# A paper week is only worth reading if the constraints are real.
PAPER_STARTING_CAPITAL = 431_116.0

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
# Roughly where each index actually trades. Used ONLY to catch a wrong
# security id: on 2026-07-28 id 13 was labelled "nifty" and delivered
# 7,330.5 while Nifty 50 was near 24,000, and id 25 ("banknifty")
# delivered 3,038 against a real BankNifty near 52,000. Both were
# sector indices. A tile showing a confident number for the WRONG
# instrument is far more dangerous than a blank one, so anything outside
# its band is shown as suspect rather than as a level.
INDEX_EXPECTED_RANGE = {
    "nifty":     (15000, 40000),
    "banknifty": (35000, 90000),
    "midcap":    (30000, 90000),
    "vix":       (5, 60),
}

# EMPTIED 2026-07-28. Every id in here was wrong, and two of them were
# actively harmful:
#
#     "nifty":     "13"  -> ABB INDIA LIMITED       (a real equity, SUBSCRIBE=YES)
#     "banknifty": "25"  -> ADANI ENTERPRISES LTD   (a real equity, SUBSCRIBE=YES)
#     "midcap":    "26"  -> nothing, never ticked
#     "vix":       "21"  -> nothing, never ticked
#
# The live packets gave it away: they carried volume and a last-traded
# QUANTITY, which no index has, on exchange_segment 1 (NSE_EQ). So the
# Nifty tile was showing ABB's share price (7,234) and BankNifty was
# showing Adani Enterprises (3,007).
#
# The damage was not just cosmetic. main.py's tick router checks index
# ids BEFORE the symbol lookup and returns, so ABB and ADANIENT ticks
# never reached the stock pipeline at all -- no candles, no opening
# range, no gainers/losers row. Two live stocks were silently missing
# from the universe for as long as this feed existed.
#
# Left EMPTY on purpose. A blank tile is honest; a confident number for
# the wrong instrument is not, and guessing these ids has now failed
# twice. To fill it: run a session, watch for the
# "[INDEX] Unmapped IDX id NN: LTP=..." lines, and identify each index
# by its LEVEL -- Nifty near 24,000, BankNifty near 52,000, VIX 8-20.
# Then put the id here and confirm the tile matches your broker screen.
# ---- REFILLED, 3 August 2026. THE IDS WERE NEVER WRONG. ----
#
#     "i want to see NIFTY 50 ; BANK NIFTY ; VIX"
#     "NIFTY 50, BANKNIFTY and VIX show 'no feed' - thats your work to
#      check with dhan & resolve"
#
# He is right, and the answer was already written down in this
# repository. From core/index_monitor.is_index_segment():
#
#     "The Nifty tile meanwhile displayed 7,234, which is ABB's share
#      price, while Nifty 50 was near 24,000. That was diagnosed as
#      'wrong security ids' and INDEX_INSTRUMENTS was emptied. The ids
#      were right. The routing was wrong."
#
# Index ids and equity ids are separate numbering spaces and they
# collide:
#
#     IDX_I 13 = NIFTY 50        NSE_EQ 13 = ABB INDIA
#     IDX_I 25 = NIFTY BANK      NSE_EQ 25 = ADANI ENTERPRISES
#
# On 28 July the router keyed on the id ALONE, so every ABB and
# ADANIENT tick was swallowed by the index monitor. The tile showed
# ABB's price, the diagnosis blamed the ids, and this dict was emptied.
# The routing was repaired on 30 July -- subscribe on MarketFeed.IDX,
# route on (segment, id) -- and nobody ever put the ids back. The tiles
# have read "needs index feed" every session since.
#
# Dhan's own annexure confirms the segment: IDX_I, Index Value, enum 0.
#
# THE SAFETY RAIL IS ALREADY BUILT. core/index_monitor.suspect() takes
# expected levels and reports any tile whose number is nowhere near
# where that index actually trades -- exactly the check that would have
# caught 7,234 on the Nifty tile in one glance. INDEX_EXPECTED_RANGE
# above feeds it, and the dashboard draws the warning. If a tile comes
# up absurd after this change, that is the mechanism saying so; do not
# empty this dict again without reading the segment on the packet.
#     "first you check what dhan gives us & then we decide what we can
#      use & drop . all possible"          -- operator, 3 August 2026
#
# Right again, and I had just done the thing this comment block warns
# against: 13 and 25 are EVIDENCED -- they appear in his own 28 July
# logs as IDX packets -- and I wrote 21 for VIX and 27 for midcap from
# nothing at all. Both removed.
#
# Run  py tools/find_index_ids.py  to list every index Dhan actually
# publishes, with its id, straight from their scrip master. Then choose
# from that list rather than from anyone's memory.
# Every id below was READ from Dhan's scrip master by
# tools/find_index_ids.py on 3 August 2026 -- not remembered, not
# inferred. That run is also what caught the last invented id: 27 is
# FINNIFTY, not midcap, and would have put Finnifty's level on a tile
# labelled MIDCAP.
INDEX_INSTRUMENTS = {
    "13": "nifty",        # Nifty 50    -- expect ~24,000
    "25": "banknifty",    # Nifty Bank  -- expect ~52,000
    "21": "vix",          # India VIX   -- expect 8-20

    # ---- GIFT NIFTY. 4 August 2026. ----
    #
    #     "USE DHAN THEY WILL PROVIDE THE INFO"
    #
    # I looked at Yahoo, found nothing dependable, and said it could
    # not be done -- while the broker the bot is already connected to
    # carried it. tools/find_gift_nifty.py found exactly one match in
    # Dhan's 202,206-row master:
    #
    #     SEM_TRADING_SYMBOL        GIFTNIFTY
    #     SEM_CUSTOM_SYMBOL         Gift Nifty
    #     SEM_SMST_SECURITY_ID      5024
    #     SEM_SEGMENT               I          <- INDEX, same as Nifty
    #     SEM_INSTRUMENT_NAME       INDEX
    #
    # SEGMENT "I" is what matters and is why this belongs HERE rather
    # than beside an equity. The first run printed only "NSE", which is
    # the EXCHANGE -- and id spaces collide across segments: IDX_I 13
    # is Nifty 50 while NSE_EQ 13 is ABB India. Reading the segment off
    # the file instead of inferring it is the whole reason that tool
    # exists.
    #
    # It is the most predictive number for an Indian open -- it trades
    # while NSE is shut -- so it is expected to look "stale" against a
    # cash-market clock. That is correct behaviour, not a dead feed.
    "5024": "giftnifty",  # Gift Nifty  -- expect close to Nifty 50
}

# ---- THE FOURTH TILE IS A DROPDOWN. 3 August 2026. ----
#
#     "Keep NIFTY 50, BANK NIFTY, VIX . these 3 on main board & 4 th =
#      SECTOR INDICES (sector based Indices as a dropdown option =this
#      will be bird view from top section which index=sector is moving)"
#
# Three fixed tiles answer "how is the market". The fourth answers a
# different and more useful question -- WHICH PART of it is moving --
# and that cannot be a fixed tile, because the answer changes through
# the day.
#
# So the fourth slot shows the sector index that has moved furthest
# from yesterday's close, with every other sector one click away. On a
# day when pharma is up 3% and everything else is flat, it says pharma
# without being asked.
#
# It also serves the cause-and-effect idea directly: a story about
# Chinese power imports is a guess until NIFTY ENERGY confirms the
# sector actually moved.
SECTOR_INDICES = {
    "29":  "IT",
    "32":  "Pharma",
    "31":  "Metal",
    "14":  "Auto",
    "42":  "Energy",
    "33":  "PSU Bank",
    "15":  "Private Bank",
    "28":  "FMCG",
    "34":  "Realty",
    "30":  "Media",
    "43":  "Infra",
    "470": "Oil & Gas",
    "447": "Healthcare",
    "466": "Consumer Durables",
}

# Subscribed alongside the three above. Prefixed so the monitor and the
# dashboard can tell a sector apart from a headline index without a
# second lookup.
INDEX_INSTRUMENTS.update(
    {sec_id: f"sector:{name}" for sec_id, name in SECTOR_INDICES.items()})

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
# OVERNIGHT / MTF COSTS, 2026-07-28
# ----------------------------------------------------------
# The rates above are INTRADAY. They apply to a position opened and
# closed in the same session -- which, per the operator's instruction,
# includes a same-day MTF round trip:
#
#   "do not consider mtf charges right away on closed positions too"
#
# He was right: MTF interest is applied FROM T+1, so a trade that lived
# 6 seconds to 37 minutes owes none of it.
#
# These apply only once a position actually CROSSES a session.
# Verified at source (Zerodha STT page + MTF FAQ, 28 Jul 2026):
#
#   Equity intraday   STT 0.025%   SELL side only
#   Equity delivery   STT 0.1%     BOTH buy and sell sides
#   MTF interest      from T+1 until sold
#   MTF pledge        auto-pledged on buy, unpledged on sell,
#                     ~Rs 15 + GST each way, per ISIN, per day
#
# NOTE the delivery STT is BOTH SIDES. My first correction modelled it
# as sell-side only and UNDERSTATED it.
#
# STILL UNVERIFIED: whether a same-day MTF exit is charged intraday or
# delivery STT. Public sources contradict each other and nobody here has
# read a real MTF contract note. The 30 Jul live order test settles it.
STT_DELIVERY_PCT = 0.001          # 0.1% on BOTH legs
STAMP_DUTY_DELIVERY_PCT = 0.00015 # 0.015% on the BUY leg
MTF_INTEREST_DAILY_PCT = 0.000342 # Dhan ~12.49% p.a. = 0.0342%/day
MTF_LEVERAGE = 4.0                # only the FUNDED 75% accrues interest
MTF_PLEDGE_FEE_RS = 15.0          # per stock, each way, + GST

# ----------------------------------------------------------
# PAPER SLIPPAGE, 2026-07-28
# ----------------------------------------------------------
# trading/paper_execution.py filled at the EXACT intent price,
# instantly, always successfully. No spread, no partial fill, no
# rejection. Six months of paper results were all optimistic, and paper
# results are the yardstick every rule on this bot is measured against.
#
# A buy lifts the offer and a sell hits the bid, so BOTH legs cost you.
# The size of it is not guesswork -- it is roughly half the bid-ask
# spread plus impact, and it is worse when:
#   - the stock is thin        (wider spread)
#   - the move is fast         (the quote moves before you arrive)
#   - the order is large       (you eat more than the top of book)
#
# Rs 2L in a liquid large-cap is a few paise. The same Rs 2L in a Rs
# 300-crore small-cap at 09:20 is not.
#
# Set to 0.0 to get the old fantasy back, if a backtest needs to be
# compared like-for-like against an older run.
ENABLE_PAPER_SLIPPAGE = True
SLIPPAGE_BASE_PCT = 0.0005        # 0.05% each leg, liquid and calm
SLIPPAGE_THIN_PCT = 0.0020        # 0.20% each leg below the turnover mark
SLIPPAGE_THIN_TURNOVER_CR = 25.0  # day turnover under this = "thin"
SLIPPAGE_OPENING_MULTIPLE = 2.0   # x2 before SLIPPAGE_CALM_AFTER
SLIPPAGE_CALM_AFTER = "09:45"     # the open is the expensive part

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

# ---- THE PRICE CHANNEL. 4 August 2026. ----
#
#     "even today i got confused no of times & felt that lag on price
#      observations"
#
# The comment above explains why the SNAPSHOT can't ride every tick,
# and it is right. But prices were made to wait for the snapshot, and
# then wait again for a 2-second page poll -- up to three seconds
# behind the Dhan app, on the one field he watches hardest.
#
# dashboard/server.py's /ws/prices reads market_data's price dict and
# nothing else: no snapshot rebuild, no breadth, no sector maths. It
# is cheap enough to run at this cadence without touching the engine.
#
# 250ms, not faster. Below about 200ms the browser cannot repaint
# between frames anyway, so the only thing left to gain is CPU spent
# in the process that has to place his orders.
PRICE_PUSH_SECONDS = 0.25

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
# ----------------------------------------------------------
# LOGGING, rewritten 2026-07-28
# ----------------------------------------------------------
# The old logger was one un-rotated file at DEBUG. By the audit that
# evening: 369 MB, 3.59 million lines, 131,238 of them CORRUPTED by
# several PROCESSES appending to the same path at once --
#
#     2026-02026-07-23 11:29:29,307 [DEBUG] [CANDLE] LICI closed ...
#     7-23 11:29:29,582 [DEBUG] [ORB] TCS range complete ...
#
# That corruption is why three of the audit's own findings turned out
# to be wrong: the file could not be read reliably. Disk space was
# never the issue -- EVIDENCE was.
LOG_MAX_BYTES = 25 * 1024 * 1024      # 25 MB per file
LOG_BACKUP_COUNT = 5                  # keep ~a week

# One file per PROCESS (pid in the name). Python's logging is
# thread-safe, not process-safe, so this is the only way two processes
# can never tear into each other's lines again.
LOG_ONE_FILE_PER_PROCESS = True

# DEBUG to disk. ~84% of the old volume was DEBUG, and 2,446 lines a
# MINUTE were "SYM stale" alarms from a threshold set below the feed's
# own rate (now fixed). Kept ON by default -- a log that cannot answer
# "what happened at 09:47" is a false economy -- but the switch is here
# for a day when it matters. Turning it off is announced at startup.
LOG_DEBUG_TO_FILE = True

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
# MEASURED AND LEFT OFF, 2026-07-29.
#
# The operator's stated rule was "we trade in trending sectors -
# strong/leaders of that sector stocks only". His own 35 bot trades
# from 27-29 July, scored under the current exit rule, with the sector
# leaderboard reconstructed at the exact minute of each entry:
#
#     gate setting                 taken    win      total  per trade
#     top 3 sectors only               7    43%        221         32
#     top 5 sectors only              10    40%        225         22
#     top 8 sectors only              14    50%      5,874        420
#     top 12 sectors only             17    53%      4,692        276
#     NO GATE                         35    51%     21,374        611
#
# No gate wins on both counts -- more trades AND more per trade -- and
# the tighter the filter the worse it gets. The trades it would have
# refused include KAYNES +9,344, M&MFIN +4,611 and DREDGECORP +3,221.
# KAYNES alone beats every top-5-sector trade combined.
#
# The likely reason: a sector average is dominated by its ordinary
# members. A stock breaking out on its OWN reason -- results, an order
# win -- is averaged away by the forty names sitting still beside it.
# The gate then refuses exactly the stock that has something specific
# happening to it.
#
# CAVEATS, so this is not treated as settled: 35 trades over 3 sessions
# in one market mood; the leaderboard was reconstructed from average
# move-from-open rather than by calling _sector_leaderboard itself; and
# some sectors have very few names in the 973-stock master, making
# their averages noisy.
#
# Sector rotation over DAYS may well be real. This measures one
# intraday moment, and there the stock says more than its sector does.
# The operator read these numbers and agreed to leave it off.
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



# ==========================================================
# THE BOOK IS SIZED BY CASH, NOT BY THE NUMBER 3  (2026-08-08)
# ==========================================================
#
#     "we prepared the bot to search for better trading opportunites
#      not to keep the door shut after 3 positions irrespective of pnl"
#                                -- operator, 8 August 2026
#
# He is right about the principle. MAX_OPEN_POSITIONS = 3 was written
# for ONE cautious session on 7 August and never came off, and on every
# replayed day all three seats filled by 09:30 and the bot went blind
# for six hours. STOVEKRAFT made its high at 12:12 with the book full
# since 09:30.
#
# core/capital.py implements his actual rule -- keep Rs 1 lakh free,
# Rs 30,000 of own cash per position, deploy the rest. At Rs 4.31 lakh
# that is 11 seats.
#
# WHY IT IS OFF
# -------------
# Measured before arming it. Replaying 3-5 August through
# core/select.py with the 1:1 lock in place:
#
#     3 slots      9 trades   11% win rate   Rs -10,715
#     11 slots    33 trades   24% win rate   Rs -26,018
#
# Opening the book did not find better opportunities. It found eight
# times as many of the SAME ones. At a 2:1 payoff the break-even hit
# rate is 33%; the selector is at 24%. Every extra seat multiplies a
# losing edge.
#
# Worse, the top-ranked three were the worst of the eleven, which says
# the ranking is not yet sorting by anything predictive.
#
# So: built, wired, tested, and OFF. Turn it on when the selector shows
# an edge -- not because the principle is right, which it is.
# ---- ON, WITH A WORKING CEILING. 10 August 2026. ----
#
#     "Capital rule: hold while it works, never block all funds"
#
# Off since 8 August because the cash rule alone said 11 seats at
# Rs 4.31 lakh, and 11 measured worse than 3 -- more trades through
# a selector with no edge. But 3 was his original complaint: one
# overnight hold leaves two seats and Rs 3.4 lakh idle whatever the
# morning offers.
#
# core/capital.WORKING_MAX_POSITIONS = 5 is the third number. Cash
# still limits below it -- Rs 2 lakh gives 3, Rs 1.5 lakh gives 1 --
# so the rule is CASH, as he asked, with a ceiling that cannot
# reach eleven until the hit rate earns it.
# BACKED OUT THE SAME NIGHT. 10 August 2026.
# Arming it broke two engine tests, and the reason is real, not a
# stale fixture: with the cash rule live, a portfolio holding less
# than the Rs 1 lakh floor plus one position gets ZERO slots and
# the bot refuses everything -- before the margin check is even
# reached. That is arguably CORRECT under his own rule, but it
# changes the order in which two gates fire, and I am not
# reconciling the margin path at 22:40 on the strength of a guess.
#
# core/capital.WORKING_MAX_POSITIONS = 5 is built, tested and
# ready. What is missing is one careful pass over how the cash
# rule and the margin gate order themselves.
ENABLE_CASH_SIZED_BOOK = True
