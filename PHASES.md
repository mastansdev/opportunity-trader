# Phase-wise build plan

Each phase is built, tested with real decision-correctness
tests, and watched running before the next one starts. No
phase gets added on top of an unproven one.

## Phase 1 -- DONE, then extended

Raw ORB structural breakout, BOTH directions (long on a close
above the range high, short on a close below the range low --
shorts added 2026-07-23, previously long-only). Manual exit +
manual buy (dashboard). NSE equity only, no F&O anywhere in the
codebase. Candle-based trailing stop, mirrored for both
directions. Clean console / full file logging. Clean Ctrl+C
shutdown, including the dashboard server. Square off at 15:15.
Restart-safe: ORB ranges, open positions, trailing stops,
portfolio, and entry blocks all persist (`core/state_store.py`).

## Phase 2 -- PARTIALLY DONE (2026-07-23)

Real stop loss: DONE (trailing stop, mirrored long/short, see
Phase 1). Position sizing from actual capital: PARTIALLY DONE --
`trading/portfolio.py`'s MIS buying-power gate (flat 4x leverage
on ₹10L, operator-approved placeholder, real per-stock margin not
modeled) now BLOCKS a new position once buying power runs out,
but per-trade QUANTITY is still the flat 100-share placeholder,
not sized off capital -- that was a deliberate, smaller first
step (operator's choice: "keep fixed 100 qty, just cap total
exposure" over risk-based or equal-slice sizing). Daily loss
limit / hard kill switch: NOT STARTED. Portfolio heat cap /
per-sector cap: PARTIALLY DONE from an unplanned angle --
`core/sector_monitor.py` blocks new LONG entries in a sector the
market is already broadly rejecting (breadth-based panic
detection), which is closer to a market-behavior filter than a
capital-exposure cap, so the actual per-sector CAPITAL cap this
phase originally meant is still not built.

## Phase 3 -- DONE (2026-07-23)

News & intelligence: `news_bot/` -- RSS + exchange-announcement
ingestion, rule-based matching, AI classification (Claude Haiku,
budget-capped), HIGH/MID/DUMMY tiering. `core/news_gate.py` is
the thin, read-only bridge into the engine. As of 2026-07-23,
News Bot input is no longer purely advisory: `core/engine.py`'s
`_try_structural_entry()` blocks a structural signal when that
exact symbol has same-day HIGH-confidence news pointing the
opposite way -- scoped to just that direction, for that symbol,
for the day. See PHASE3_NEWS_DESIGN.md for full detail. Results-
calendar integration and a first-15-minute momentum setup remain
deferred, separate builds.

## Phase 4 -- DONE (dashboard V2); Telegram not started

Operator interfaces: FastAPI + WebSocket live dashboard
(`dashboard/`) -- capital/margin, breadth, sector colour, News/
ORB watchlists, Risk Filters (panic sectors + blocked symbols),
open/closed positions (direction-aware), manual BUY (long only)
+ EXIT/EXIT ALL. Starts and stops cleanly with the rest of the
bot.

V2 (2026-07-23, from Institutional_Dashboard_V2_Blueprint.pdf):
real RR (risk:reward, from core/engine.py's "initial_stop" --
the stop AS SEEDED at entry, never the live ratcheted one),
Performance panel (win rate, profit factor, avg win/loss, max
drawdown, net P&L), Sector Heatmap (per-sector avg % change),
News Feed (today's HIGH-priority items, formatted for display),
Opportunity Queue (symbols close to their ORB boundary, ranked
by proximity), and System Health (CPU/RAM via psutil, tick
count, stale-tick count, feed-alive, universe size). Explicitly
NOT built, per an operator decision the same session: AI
Verdict / Confidence / Holding Reason / Brain Verdict (no
per-trade AI reasoning call exists anywhere in this bot --
building this for real is a separate, larger piece of work;
faking it would be exactly the kind of silent, misleading UI
this project has avoided everywhere else), a fixed Target (the
strategy has no fixed target by design), a Knowledge Graph (no
such subsystem exists), and BSE (config.py's EXCHANGE_SEGMENT
is NSE_EQ only, a permanent decision).

Telegram control/alerts: NOT STARTED.

Operator-flagged 2026-07-23, dashboard layout revised same session
per direct feedback (wide Open Positions with Opportunity Queue
alongside; Sector Heatmap/Risk Alerts/Sectors grouped together;
Closed Trades restored to full Entry Time/Exit Time/Sector columns
-- see dashboard/static/index.html). Two known-inaccurate pieces, one fixed same session, one still open:
  - ORB Watchlist FIXED (2026-07-23): now drops a symbol per
    DIRECTION once today already covers it (open position, closed
    trade, or an entry_blocked entry for that direction) -- it's a
    watchlist of untouched opportunities, not a running log of
    every symbol beyond range. Does NOT fully solve late-session
    list growth on its own -- a symbol the bot simply hasn't
    reached yet still qualifies no matter how long it's been beyond
    range, which is expected ORB behavior, not a bug.
  - Sector Heatmap's per-symbol change is vs "day open" which
    resets on every restart (core/market_data.py), so a session
    with multiple restarts (like 2026-07-23's) can show change-
    since-last-restart rather than change-since-market-open for
    part of the universe. STILL OPEN -- needs re-verification on a
    clean, restart-free session.

Core sector (industry) heatmap added same day, operator-requested:
the broad SECTOR heatmap can dilute a genuine move -- e.g.
"AUTOMOBILE" (53 symbols) mixes 13 OEM majors (MARUTI, TVSMOTOR,
HEROMOTOCO, BAJAJ-AUTO, ...) with 27 unrelated auto-component
makers, 5 tyre makers, 2 battery makers, etc., so an unweighted
average across all 53 can mask a real rally in the OEM names.
Investigated first and confirmed this is dilution, not
fragmentation -- all named stocks already shared SECTOR=
"AUTOMOBILE". Fix: a second heatmap (`dashboard/state.py`'s
`_build_industry_heatmap()`, shown under the existing Sector
Heatmap panel as "Core Sector") grouped by the finer INDUSTRY
column (177 distinct values universe-wide) instead, dropping any
industry with fewer than `config.INDUSTRY_HEATMAP_MIN_SYMBOLS`
(3) reporting stocks as too sparse to average meaningfully (82 of
177 industries have exactly 1 stock). Those symbols still count
fully in the broad SECTOR heatmap -- they just don't get their
own core-sector line. NOTE: because INDUSTRY is more specific
than SECTOR, a couple of names an operator might expect together
land in different, smaller buckets than the OEM majors -- M&M is
alone under "TRACTORS / FARM EQUIPMENT - AUTOMOBILE", BOSCHLTD is
under the 27-stock "AUTO COMPONENTS" bucket, neither under
"AUTOMOBILES - OEM" -- this is the data being genuinely more
specific about different sub-businesses, not a bug to route
around.

## Crash fix, 2026-07-23 (mid-session, live)

Bot crashed with `RuntimeError: dictionary changed size during
iteration` in `dashboard/state.py`'s `_build_open_positions()`.
Root cause: `dashboard/state.py`'s refresh runs on `main.py`'s own
loop thread, while `core/engine.py`'s `_enter()`/`_exit()` (called
from the feed thread, on every tick) mutate `engine.open_positions`
/ `closed_positions` / `entry_blocked` concurrently -- no lock ever
guarded these structures against a second thread iterating them
mid-mutation. `core/orb_engine.py`'s `export_state()` and
`complete_count()` had the same latent flaw against `self._ranges`.

Fix: `dashboard/state.py`'s `_build()` now takes ONE snapshot copy
(`dict(...)`/`list(...)`) of each engine-owned mutable structure up
front, and every `_build_X` method receives that snapshot as a
parameter instead of reaching into `self.engine.open_positions` (etc)
directly. `dict(...)`/`list(...)` copy the whole structure in a
single C-level pass that holds the GIL throughout, so the copy can't
be interrupted by the other thread -- the standard safe pattern for
reading a structure another thread is concurrently mutating, without
adding a lock to the engine's own hot path (which must never slow
down). Same fix applied to `core/orb_engine.py`'s `export_state()`
and `complete_count()`. Verified: full test suite green (246 tests),
plus a dedicated concurrency stress test (one thread mutating
open/closed/blocked positions every ~1ms while another thread calls
`refresh()` 30x) with zero errors.

## TOP_N_MOMENTUM_MODE experiment, built 2026-07-23 evening for 2026-07-24 (Friday)

Operator's own words, after a losing session that traded both long
and short in a broadly falling market: "what bot must do is simple.
take best 25 long positions & 25 short positions keep the Stop loss
& targets as fixed... best in my terms top trending stocks in both
cases = top 25 gainers & top 25 losers." Explicitly framed as a
controlled EXPERIMENT, not a claimed final design -- operator was
direct that "no fixed rules will work in stock market, bot must
change/adapt" -- the point is to get a real, measured baseline (this
exact rule set, against this exact day) to compare a future adaptive
design against.

Built:
- `core/momentum_universe.py` (new) -- `MomentumUniverse.lock()`
  ranks every symbol by %-change vs day open, locks the top 25
  gainers as LONG-eligible and the top 25 losers as SHORT-eligible,
  ONCE, at ORB_WINDOW_END (09:30) -- not a periodic reshuffle, a
  stable daily shortlist, so an open trade never loses its own
  eligibility mid-day. Persisted (`core/state_store.py`, 6th field)
  so an intraday restart restores the exact same 50 symbols instead
  of recomputing a possibly-different list.
- `core/engine.py`'s `_try_structural_entry()` gates on
  `momentum_universe.is_eligible(symbol, direction)` first (cheapest
  check) when `config.TOP_N_MOMENTUM_MODE` is on -- silent skip for
  the other 700+ symbols, no entry_blocked entry (that ledger is for
  a specific news/sector REASON, not "wasn't on today's shortlist").
- Fixed bracket exits (`_check_fixed_bracket()`) replace the dynamic
  trailing stop entirely for these trades -- `config.FIXED_STOP_LOSS_RS`
  (1000) / `FIXED_TARGET_RS` (2500) are converted to per-share price
  levels at entry using the flat qty, stored on the position
  (`initial_stop`, `fixed_target`), checked every tick, no ratcheting.
  Routed per-POSITION (via the position's own `fixed_target` field),
  not the global flag, so an already-open trade keeps behaving
  consistently even if the flag is toggled mid-session. Manual buys
  are untouched -- still dynamic trailing, no momentum-eligibility
  gate, same as always (operator override, informed choice already
  made).
- A fixed-bracket stop-out blocks same-direction re-entry same as a
  trailing stop-out always has (`BLOCK_REENTRY_AFTER_STOPOUT`,
  reverted to its default `True` for this session -- the 2026-07-23-
  only override for the too-tight-stop bug is over).
- Dashboard: new "Momentum Universe" panel (locked long/short lists,
  enabled/locked status badge) above Open Positions; Open/Closed
  Positions tables gained a Target column (em-dash for trades opened
  outside the mode, which have no fixed target by design).
- Toggle: `config.TOP_N_MOMENTUM_MODE`, default `True` for
  2026-07-24 onward. Flip to `False` to fall back instantly to the
  original full-750-symbol/dynamic-trailing-stop behaviour, no other
  code changes needed either way.

Deliberately NOT built this session (operator-deferred): a
"Monitoring Engine" watching India VIX / crude oil / gold / silver
before and during market hours -- none of that data is wired into
the bot at all yet, real new integration work, separate session.

NOTE for whoever reads this later: the operator flagged, correctly,
that treating M&M/BOSCHLTD-style "everyone treated equally" is
exactly the failure mode this experiment is trying to get real data
on -- see the "core sector" heatmap section above for the parallel
insight on the sector side.

Verified: 267 tests passing (added `tests/test_momentum_universe.py`
plus engine/dashboard test coverage for the gating and bracket exit
paths), `main.py` imports cleanly, and a standalone integration
script exercising the full non-Dhan wiring path (MasterLoader ->
MomentumUniverse.lock() -> state_store round trip -> DashboardState
refresh) end to end with zero errors.

## Square-off gate fix, 2026-07-23 15:18 (live, mid-session)

Real bug reported live by the operator: 74 open positions and the
bot was still trying to BUY MORE at 15:18, three minutes past
SQUARE_OFF_TIME (15:15) -- only blocked by margin exhaustion, not
by time. Root cause: `main.py`'s `flatten_all()` at square-off is a
ONE-SHOT close of whatever was open at that exact moment (guarded
by a `squared_off` bool that only fires once) -- nothing ever
stopped a brand-new entry from opening immediately after, and once
opened it just sat there ungoverned, since flatten_all() never runs
a second time in the same session.

Fix: `core/engine.py` now blocks both structural entries
(`_try_structural_entry()`) and manual buys (`process_tick()`'s
manual-buy branch) once the tick's own market time (`closed_candle
["time"]` / `tick_time`) passes `SQUARE_OFF_T` -- same parsing
pattern and same "trust market time, not wall clock" convention as
`core/orb_engine.py`'s `MARKET_OPEN_T`/`ORB_WINDOW_END_T`. Manual
buy is normally an unconditional operator override, but square-off
exists specifically to guarantee zero new intraday exposure past
this time -- an override that could reopen that exposure would
defeat the one thing square-off is for, so it's blocked here too.

Verified: 5 new regression tests (structural + manual entry blocked
after 15:15, both still work normally before 15:15, and a scenario
reproducing the live shape -- several pre-existing open positions,
a fresh breakout signal on an unrelated symbol past square-off,
must be refused). Full suite green (272 tests), `main.py` imports
cleanly. Operator instructed to restart the live process immediately
-- the running instance still has the old code and the 74 stragglers
need both the fix (no more new entries) and a fresh flatten_all()
run (which restarting also triggers, since `squared_off` resets on
a new process) before real market close (15:30) leaves them
permanently ungoverned for the day.

## Two more live bugs fixed, 2026-07-23 evening (post-close refinement pass, before 2026-07-24)

Found while backtesting today's trade log against the hypothetical
top-25/25 momentum universe (operator's own request: "check what
the PnL would have been"). Both are root-caused and fixed with
regression tests, ahead of TOP_N_MOMENTUM_MODE's first live session
tomorrow, so that session's data isn't muddied by either.

### 1. Exit-all flag never scoped to what was actually open at request time

The earlier "exit-all flag never resets" fix (Phase 1, item 2) only
covered a single-position, empty-book case correctly by accident --
`_exit()` cleared the flag once `not self.open_positions`, which
happened to be true whenever the one position it applied to closed.
With multiple positions and re-entry unblocked, the book can go
minutes to hours without ever being fully empty: today it took 74
minutes (10:32:44-11:46:28) for a single `exitall`, during which
EVERY new position opened -- 2039 of them -- got force-sold as
MANUAL_EXIT within 0-1 seconds of opening, ~Rs 7,707 in phantom
paper-mode churn (real slippage/brokerage cost in live).

Root cause: the flag was a bare boolean with no memory of WHICH
positions the operator actually meant. Fix: `core/engine.py` now
snapshots the currently-open symbols into `self._exit_all_snapshot`
the first tick after the flag is freshly observed
(`_maybe_snapshot_exit_all()`, called at the top of every
`process_tick()`), and `_check_manual_exit()` only exits symbols in
that snapshot. Each snapshotted symbol is discarded from it in
`_exit()` regardless of WHY it closed (trailing stop, fixed
bracket, square-off, or the exit-all path itself); once the
snapshot fully drains, the controller flag clears and the snapshot
resets to `None`. A position opened AFTER the request -- even while
an older batch is still mid-drain -- is never touched. An exit-all
issued against a flat book clears its own snapshot immediately
(empty set), so it can't linger and phantom-exit some unrelated
position hours later. Not persisted across a restart, same as
`TradeController`'s own request flags -- a manual exit-all is a
live, in-session action.

Verified: 2 new regression tests -- one multi-symbol scenario
matching the live shape (two pre-existing positions, one still
mid-drain when a brand-new unrelated breakout opens, which must
stay open through the rest of the batch's drain), one flat-book
edge case (exit-all with nothing open must clear on the very next
tick, not wait for a position that may never come).

### 2. Frozen/dead price feed traded as if it were real price action (HFCL)

Found investigating an odd cluster in today's trade log: HFCL
cycled SHORT entry -> immediate TRAILING_STOP exit -> re-entry 12
times between 11:37 and 15:21, every single round trip at the
identical price. `diagnostics.log`'s own `[CANDLE]` lines confirmed
it: `O=H=L=C=207.01` on every 1-minute candle from 12:45 to 15:21,
~4.5 hours of zero tick variance -- not plausible real market data.
HFCL had recurring "Stale tick" warnings all session
(`core/market_data.py`'s existing DELAYED-timestamp detector,
intermittent from ~10:22 onward) but that detector only catches a
LATE feed, not a FROZEN one -- fresh timestamps that keep repeating
the same price slip through it entirely.

Mechanism: the trailing stop's rolling window
(`TRAILING_STOP_WINDOW_CANDLES = 5`) keeps the safely-seeded initial
stop in its window until 5 more candles have closed. Once 5
consecutive frozen candles pushed the seed out of the window, the
stop ratcheted down to the frozen price itself -- and the very next
(still-frozen) tick self-triggered an exit at that same price,
breakeven, for no real reason. With `BLOCK_REENTRY_AFTER_STOPOUT`
off for 2026-07-23 only (operator's own one-day override, reverted
from 2026-07-24 in the TOP_N_MOMENTUM_MODE change), the very next
identical candle just re-triggered the whole cycle.

Fix: new `FROZEN_PRICE_STREAK_CANDLES = 3` (config.py) -- a symbol
whose last 3 consecutive closed candles are exact duplicates
(same O=H=L=C) is treated as frozen -- circuit lock or dead feed,
practically indistinguishable and handled identically.
`core/engine.py` tracks
this per symbol (`_update_frozen_streak()`/`_is_frozen()`, edge-
triggered `[FROZEN_FEED]` warning once per freeze episode, same
pattern as `core/market_data.py`'s own stale-tick warnings) and,
while frozen: (a) blocks brand-new structural entries
(`_try_structural_entry()`, silent skip alongside the momentum-
eligibility/square-off checks), and (b) skips the trailing-stop
ratchet entirely for an already-open position, so the safe seed
never gets rolled out of the window in the first place -- the
position just sits, protected by whatever stop it already had,
until the feed recovers or square-off closes it normally. 3
candles is a deliberately low bar; real consolidation still moves
by at least a paisa somewhere in 3 minutes. Surfaced on the
dashboard's existing Risk Alerts panel (new "Frozen-Feed Symbols"
chip list, `Engine.get_frozen_symbols()`), same visibility pattern
as panic-flagged sectors and blocked symbols.

**Correction, later the same evening**: operator confirmed the
actual root cause was HFCL hitting its LOWER CIRCUIT (exchange
price band) at 11:49 -- real, legitimate market data, not a dead
feed. The earlier "Stale tick" warnings (~10:22 onward) were a
separate, unrelated feed hiccup; the flat 12:45-15:21 stretch was
the stock genuinely locked at its floor. The fix and all code/
config comments below have been updated to say "frozen price --
circuit lock or dead feed" rather than assuming dead feed. The fix
itself needed no changes: a circuit-locked stock has no real
counterparty for a fresh order in the losing direction either, so
blocking new entries and refusing to ratchet the stop onto a
circuit-locked candle is correct behaviour regardless of which of
the two actually caused it -- one detector deliberately covers both
rather than trying to specifically diagnose which case it is.

Verified: 2 new regression tests -- one proving the stop never
ratchets onto a frozen streak even 8 candles past the old 5-candle
danger window (and the position never self-exits), one proving a
fresh structural entry attempt is refused once the streak crosses
the threshold (isolated from `BLOCK_REENTRY_AFTER_STOPOUT` by using
a manual exit, not a stop-out, between attempts).

Both: full suite green (277 tests), `main.py` imports cleanly.
Today's actual backtest result (for context, not a preview of
tomorrow): filtering today's real trades to the top-25/25 momentum
universe would have cut the day's loss from Rs -25,281 to
Rs -1,676 using the OLD dynamic-trailing exits -- tomorrow is the
first session with fixed-bracket exits AND both of these bugs
fixed, so it should be a clean read.

### 3. Proactive circuit-limit exit (PROACTIVE follow-up to #2, same evening)

Item #2 above (`FROZEN_PRICE_STREAK_CANDLES`) is REACTIVE -- it only
notices a circuit lock after 3 candles of zero movement have
already printed. Operator instruction, post-HFCL discussion: get
out BEFORE the lock, not after -- "Bullish is fine good but bearish
= lower circuits are terrible. Bullish & Bearish irrespective we
will close the open position before circuits."

New `core/circuit_monitor.py`: an independent poll thread (own
thread, separate from the tick-processing hot path, same
separation-of-concerns principle as the News Bot pipeline) that
calls Dhan's REST `/marketfeed/quote` endpoint every
`CIRCUIT_POLL_INTERVAL_SECONDS` (config.py, default 3s) for the
whole resolved universe in one batched call (Dhan allows up to 1000
instruments/request at 1 request/sec; this bot's ~750 symbols fit
in a single call). Confirmed against Dhan's own API docs that the
WebSocket feed this bot's ticks already run on does NOT carry
circuit limits at all -- only that separate REST snapshot
(`upper_circuit_limit`/`lower_circuit_limit` per symbol) does, so
this genuinely needed its own transport, not just a new field read
off the existing tick stream. Deliberately does not hardcode SEBI's
2%/5%/10%/20% band tables -- Dhan already computes the live number
per symbol.

A symbol is "flagged" once its LTP sits within `CIRCUIT_PROXIMITY_PCT`
(config.py, default 2%) of either circuit limit. Direction-agnostic
by explicit operator instruction: `core/engine.py`'s
`_try_structural_entry()` blocks a brand new entry into a flagged
symbol regardless of direction (same silent-skip pattern as the
existing frozen-price gate), and the new `_check_circuit_proximity()`
force-closes any open position in a flagged symbol -- irrespective
of whether the approaching circuit favours that position (e.g. UPPER
for an open LONG) or not. Runs ahead of the trailing-stop/manual-exit
checks in `process_tick()` -- a circuit approach is a market-
structure exit, takes priority over normal risk management. New
`EXIT_REASON_CIRCUIT_PROXIMITY` is deliberately NOT included in
`BLOCK_REENTRY_AFTER_STOPOUT`'s reason set (`_exit()`) -- this isn't
a losing-trade stop-out, so it must never block a later, fresh
attempt at the same symbol/direction once price moves back to
safety.

Surfaced on the dashboard's existing Risk Alerts panel (new
"Circuit-Proximity Symbols" chip list, `Engine.get_circuit_flagged_symbols()`),
same visibility pattern as the Frozen-Feed chip list right above it.

Verified: 7 new `core/circuit_monitor.py` unit tests (proximity math
both directions, mid-range non-flag, flag-clears-on-recovery, failed/
malformed quote response handled without crashing or false-flagging,
multi-symbol batching) + 4 new `core/engine.py` integration tests
(blocks a fresh entry, force-exits an open LONG even on the
favourable UPPER side, force-exits an open SHORT, and confirms the
stop-out re-entry block does NOT trigger from a circuit-proximity
exit) + 2 new dashboard tests. Full suite green (289 tests),
`main.py` imports cleanly.

### 4. Dashboard: Top 50 Gainers/Losers replaces the ORB Watchlist panel

Operator instruction, 2026-07-23 evening, screenshots of NSE's own
site as the reference: "remove watchlist... TOP 50 GAINERS & TOP 50
LOOSERS in the place of watchlist," columns S.No/Symbol/Sector/Open/
High/Low/Prev Close/LTP/Change/Change%/Volume. The old ORB Bullish/
Bearish watchlist (`dashboard/state.py`'s `_build_watchlists()`,
`orb_bullish`/`orb_bearish`/`news_stocks`/`results_watchlist`) is
fully removed -- `news_stocks`/`results_watchlist` were already dead
in the frontend (nothing rendered them), so nothing else depended on
this method.

Confirmed with the operator before building: (1) refresh cadence --
"for every 5 mins," (2) universe scope -- the bot's own ~750-symbol
master list, not all of NSE's ~2000 (that's all the bot has live
data for), (3) layout -- two tables side by side in the same panel
slot the old Bullish/Bearish columns used.

No second REST poller needed: `core/circuit_monitor.py`'s poll cycle
(item #3 above) already pulls a full quote snapshot -- LTP, OHLC,
previous-day close, volume -- for the whole universe every few
seconds, alongside the circuit limits it was originally built for.
New `CircuitMonitor.get_snapshot()` exposes that same cached data;
new `Engine.get_circuit_snapshot()` forwards it. `dashboard/state.py`'s
new `_build_gainers_losers()` ranks the whole universe by %-change
vs each symbol's PREVIOUS DAY close (a real reference this dashboard
never had before -- advances/declines/sector-colour still use day-
open only, unchanged, that's a separate, larger piece not in scope
here), takes the top/bottom `GAINERS_LOSERS_COUNT` (50), and is
deliberately throttled to rebuild only every
`GAINERS_LOSERS_REFRESH_SECONDS` (300s) regardless of how often the
dashboard's own 1s refresh cycle runs -- cached and reused in
between, per the operator's 5-minute cadence choice.

`dashboard/static/index.html`: new side-by-side Top 50 Gainers/Top
50 Losers tables (scrollable, sticky header) in the old watchlist
panel's slot, colour-coded change/change% cells (new `td.pos`/
`td.neg` CSS -- also fixes a latent styling gap where Closed Trades'
PnL cells already used these classes but no rule existed for them).

Verified: 4 new `core/circuit_monitor.py` snapshot tests (OHLC/
prev-close/volume captured correctly, snapshot includes every quoted
symbol not just flagged ones, a symbol with no usable prev_close is
skipped rather than fabricated, snapshot is replaced fresh each
poll, not accumulated) + 5 new `dashboard/state.py` tests (correct
ranking and field mapping, capped at `GAINERS_LOSERS_COUNT`, skips
symbols missing prev_close, empty when no circuit_monitor wired in,
throttled -- a second refresh() immediately after the first reuses
the cached result even though the underlying data changed). Caught
and fixed a real bug during testing: gainers/losers initially shared
the same dict objects for symbols appearing in both slices (possible
on a small universe), so stamping S.No for one table silently
overwrote the other's -- fixed by copying each row per table.
8 obsolete ORB-watchlist tests removed (tested a feature that no
longer exists). Full suite green (290 tests).

### 5. Dashboard cleanup: layout reorder, Manual Buy removed, Opportunity
   Queue deleted, Sector Heatmap redesigned, holding time on closed trades

Operator instruction, 2026-07-23 evening, after seeing the Top 50
Gainers/Losers panel in place: it needed to sit directly below Open
Positions, not below Sector Heatmap/Risk Alerts/Sectors as first
built. `dashboard/static/index.html` main layout reordered to: Market
Breadth -> Momentum Universe -> Open Positions (now full-width, the
`.layout-open-oq` two-column wrapper it shared with Opportunity Queue
is gone) -> Top 50 Gainers/Losers -> Sector Heatmap -> Risk Alerts |
Sectors (`.layout-2col`, was `.layout-3across`) -> News Feed | System
Health -> Closed Trades | Performance.

Manual Buy (Long only) panel removed outright -- the operator never
uses it (PAPER mode entries come from the strategy, not manual
clicks), and View-Only dashboard links already hid it for anyone but
the operator, so it was pure clutter. HTML block, `#buyForm` submit
listener, and its now-unneeded `viewOnlyBadge` toggle line all
removed.

Opportunity Queue ("approaching ORB boundary") deleted per explicit
instruction -- frontend panel, `dashboard/state.py`'s
`_build_opportunity_queue()`, and its `"opportunity_queue"` key in
`_build()` all removed, plus the 2 tests that covered it (no
replacements needed -- the feature is gone, not replaced).

Sector Heatmap: operator's first instruction was "delete for now,"
then corrected mid-implementation to "make it use like same top 50
gainers & losers... top gaining sectors / top losing sectors" --
redesign, not delete. The old heatmap (`_build_industry_heatmap()`,
INDUSTRY-column based, day-open reference) is fully removed and
replaced with a new implementation that reuses the exact same
already-throttled snapshot rows `_build_gainers_losers()` builds
from `engine.get_circuit_snapshot()` (previous-day close reference,
same 5-minute cadence, no new REST polling). Sectors are grouped,
averaged by %-change vs prev close, and split into gainers (>=0%)
and losers (<0%), dropping any sector with fewer than
`SECTOR_GAINERS_LOSERS_MIN_SYMBOLS` (3) reporting stocks as too
sparse to average meaningfully -- same reasoning as the pre-existing
`SECTOR_PANIC_MIN_SYMBOLS` threshold used elsewhere, kept as a
separate constant since the two features can be tuned independently.
New frontend table pair (Top Gaining Sectors / Top Losing Sectors)
matches the Top 50 Gainers/Losers table style per the operator's
explicit ask. Caught and fixed a JS temporal-dead-zone bug before
running: the new render block initially referenced `gl.sector_gainers`
before `const gl = snap.gainers_losers || {...}` was declared further
down the same function -- relocated the block to right after the
existing gainers/losers render code.

Closed Trades table: added a "Holding (min)" column between Exit
Reason and PnL, per "IN CLOSED POSITION MAINTAIN THE HOLDING TIME
(IN MINUTES) OF STOCK FROM ENTRY TO EXIT." Backend already exposed
`holding_seconds` per row (`_build_closed_positions()`, unchanged);
only the frontend needed a new `fmtHoldingMinutes()` helper
(seconds -> minutes, one decimal place) and a table cell.

CSS cleanup: `.layout-open-oq`, `.layout-3across`, `.oq-row`,
`.heat-row`/`.heat-bar`/`.heat-bar-fill`, `.buy-form`, and `.btn-buy`
were all left orphaned by the above removals (grep-verified zero
remaining references anywhere in `index.html` before deleting each
rule) and removed. `.btn-sell` was checked and kept -- still used by
the per-position EXIT button in Open Positions.

Verified: extracted inline `<script>` block passes `node --check`
(no syntax errors from the reordering/removals). Full suite green
(286 tests -- down from 290: net of 8 obsolete ORB-watchlist tests
removed earlier, 4 obsolete Sector/Industry-heatmap tests replaced
with 2 new prev-close-based ones, 2 Opportunity Queue tests removed
with no replacement).

### 6. Market Breadth and Sectors switched to previous-close basis

Flagged to the operator right after item #5 above: Market Breadth
and the Sectors green/red panel were still day-open based
(`market_data.get_day_open()`, resets to "first tick since the
bot's LAST RESTART," not the true 09:15 open -- an inaccuracy
already documented in this file the evening before), while Top 50
Gainers/Losers and the redesigned Sector Heatmap were both already
previous-close based. Operator chose to switch Market Breadth/
Sectors to match, for one consistent reference across the whole
dashboard, aligned with NSE's own advances/declines convention.

`dashboard/state.py`'s `_build_breadth()` now reads `prev_close`
from `engine.get_circuit_snapshot()` -- the same already-running
`circuit_monitor.py` REST snapshot `_build_gainers_losers()` reads,
no new polling added. `last_price` still prefers `market_data`'s own
tick feed (updates every tick, not throttled to the REST poll's
few-second cadence), falling back to the snapshot's own LTP only
for a symbol that hasn't ticked yet this session. A symbol the
snapshot hasn't captured (REST poll hasn't reached it yet, or its
prev_close was unusable -- see `circuit_monitor.py`'s
`_snapshot_row()`) is counted "unchanged" rather than guessed, same
convention the day-open version used. `_build_sectors()` needed no
logic change -- it only averages whatever `_build_breadth()` already
computed, so switching the one method's reference switched both
panels together, keeping them consistent with each other by
construction.

`core/momentum_universe.py`'s own day-open-based ranking
(TOP_N_MOMENTUM_MODE's locked top-25/top-25 shortlist) is
deliberately UNCHANGED -- that's a separate, intentional design
choice (rewards intraday momentum specifically, locked once at
ORB_WINDOW_END, not meant to track NSE's own convention), not part
of this ask.

Verified: 2 tests updated (`test_advances_declines_unchanged_counts_vs_day_open`
renamed to `..._vs_prev_close`, rebuilt around `circuit_snapshot`
instead of `day_opens`; `test_sector_colour_from_average_change_within_sector`
likewise) plus 1 new test added
(`test_advances_declines_unchanged_when_snapshot_missing_a_symbol` --
a symbol circuit_monitor hasn't captured yet stays "unchanged," not
guessed). Also caught and fixed a leftover duplicate `_quote()` test
helper (two definitions in the same test file -- the second, with no
default arguments, was silently shadowing the first at call time and
would have broken the new tests). Full suite green (287 tests).

## Phase 5 -- NOT STARTED

Shadow-mode validation against live market data (no orders
placed) for at least one full session before this bot ever
touches real capital.
