# Issues Log — Opportunity Trader

Running record of every real bug or data-quality problem found during live
paper trading, starting 2026-07-23. Each entry: what we saw, why it
happened, what was done, and current status. Update this file whenever a
new issue is found or an open item gets resolved — don't start a new file
per day.

Status key: **Fixed** = root cause addressed. **Mitigated** = a safety net
stops the bad outcome, but the underlying cause is still there. **Open** =
known, not yet acted on.

---

## ⭐ MONDAY (2026-07-27) LIVE-TEST CHECKLIST — do these at the open

Three things were built but CANNOT be validated offline (they touch the
live Dhan feed or need real market data). Verify each on Monday's first
live run:

1. **Quote-mode volume (Change 2).** The feed was switched Ticker→QUOTE to
   carry per-candle volume for the breakout volume-surge filter.
   - CHECK: heartbeat "ticks" count keeps rising and the dashboard looks
     normal (ticks still flowing after the mode change).
   - CHECK: Top-50 tables show a Volume column with real numbers.
   - Fail-safe: if volume is empty, the filter just does nothing — trading
     is never blocked. Config: `ENABLE_VOLUME_FILTER`.

2. **Index + India VIX feed (Nifty / BankNifty / Midcap / VIX).** Subscribed
   on Dhan's IDX segment; the Market Intelligence tiles should fill with
   REAL live numbers.
   - CHECK: the four tiles (Nifty / BankNifty / Midcap / India VIX) show
     live values, not "needs feed".
   - IF a tile stays "needs feed" → its security id is wrong. The ids I
     used are best-guess (Nifty 13, BankNifty 25, VIX 21, Midcap 26) and
     MUST be verified against Dhan's live scrip master. Fix the wrong one
     in `config.py` → `INDEX_INSTRUMENTS` and restart.
   - Fail-safe: indices are routed entirely OUTSIDE the trading pipeline,
     so a wrong id can't affect trading. Config: `ENABLE_INDEX_FEED`.

3. **Earnings list for the week.** Paste the FULL earnings calendar into
   `config.EARNINGS_CALENDAR` before the open (current data is partial —
   only what a screenshot showed). A stock reporting today must be on the
   list or the bot won't know to skip it (APAR-class risk).

Also worth a glance on Monday (already tested in code, first live look):
- Wider stops (1% floor / 2.5× ATR / trail-activation) — confirm stops sit
  a real distance away, not clipping on noise.
- Manual buy/short sizing — confirm a manual click is risk-sized (~₹2L
  notional cap), not 100 flat shares.
- Margin dashboard — confirm Margin Used / Free Margin look right vs the
  ₹10L capital and 5× leverage.
- FII/DII tile — optional: set `FII_NET_CR` / `DII_NET_CR` in config with
  the day's published figures (EOD data, manual by design).
- **News Impact panel (FREE mode, live 2026-07-24).** The news engine now
  runs with NO paid API: a free keyword classifier reads the RSS/exchange
  feeds and fills the "News Impact" panel with today's HIGH & MID items.
  - CHECK: the panel lists real headlines with High/Mid + Keyword badges as
    news comes in through the day (empty early, fills up — RSS is slow).
  - SAFETY: free "Keyword" news is DISPLAY-ONLY — it will NOT block a trade
    (`NEWS_KEYWORD_CAN_BLOCK = False`). Only the paid Haiku classifier gets
    veto power. A "Blocks" badge should therefore appear only once the API
    is on. This is intentional — the keyword reader is too crude to veto a
    real-money trade.
  - WHEN THE API IS ADDED (month-start): set `ANTHROPIC_API_KEY`; mode is
    already `"auto"`, so it switches to Haiku automatically — no code change.
    Haiku news then blocks contradicting trades again as designed.

---

## 2026-07-23

### 1. Market Breadth panel disagreed with an external reference
Bot showed 383 Adv / 347 Decl / 20 Unch; an external source showed
448 / 1367 / 165 at the same moment.
**Cause:** `market_data.get_latest_price()` has no read-time recency
check — a symbol's displayed price can be from any point earlier in the
session, while `circuit_monitor`'s snapshot is uniformly refreshed. The
two panels were quietly comparing data of different ages.
**Status:** Explained, not restructured — breadth was later moved onto
`circuit_monitor`'s prev-close-based snapshot (see #21 below), which
sidesteps the staleness gap.

### 2. JLHL 2:10 stock split showed as an 80% loss
A routine split was read as a real price crash and counted against
"top losers."
**Fix:** Added a sanity check using the exchange's own circuit-band width
— a move too large to be legitimate is treated as a split/bonus artifact
and excluded from gainers/losers instead of shown as a crash.
**Status:** Fixed. (`dashboard/state.py::_is_plausible_move`)

### 3. CEMPRO stayed in Top Losers while locked at 5% lower circuit
A circuit-locked (untradeable) stock has nowhere to go — showing it in a
ranked losers list is misleading, since no exit or entry is actually
possible.
**Fix:** Circuit-locked stocks are now excluded from gainers/losers
ranking entirely.
**Status:** Fixed. (`dashboard/state.py::_is_circuit_locked`)

### 4. Flat 100-qty / fixed ₹2,500 target / ₹1,000 stop for every stock
Same quantity and same rupee stop/target regardless of price or
volatility — unfavorable for low-price stocks, arbitrary for everything
else.
**Fix:** Full redesign — qty now derived from a fixed rupee-risk budget
divided by the stock's own ATR-based stop distance; no fixed target,
ATR-based trailing stop instead (chandelier-style, ratchets up, never
loosens).
**Status:** Fixed (core/atr.py, core/engine.py `_atr_entry_sizing` /
`_check_atr_trailing`). Later found to need additional safety limits —
see #10 and #11 below.

### 5. STYL re-entered 4 times via circuit-proximity whipsaw
Same stock kept stopping out and re-entering near a circuit limit,
whipsawing repeatedly the same session.
**Fix:** Added `CIRCUIT_PROXIMITY` to the set of exit reasons that block
same-direction re-entry for the rest of the day (same rule already
applied to a normal stop-out).
**Status:** Fixed. (`core/engine.py::_exit`)

### 6. Exit All gave no way to pause new entries
Clicking Exit All closed everything but the bot could immediately open
new positions again with no pause.
**Fix:** Exit All now opens a confirm popup with two distinct choices —
"Stop New Entries + Exit All" (pauses until the book is flat again, then
auto-resumes) or "Exit All Only." Both wired end-to-end (backend +
dashboard).
**Status:** Fixed. (`trading/trade_controller.py`,
`dashboard/server.py::/api/exit_all`)

### 7. No minimum price floor — bot traded sub-₹200 stocks
Very low-price stocks are structurally unfavorable for this strategy
(tick-size noise dominates the move).
**Fix:** Hard floor, `MIN_TRADABLE_PRICE_RS = 200`, enforced for every
entry path (structural and manual), non-overridable.
**Status:** Fixed. (`core/engine.py`, `config.MIN_TRADABLE_PRICE_RS`)

---

## 2026-07-24

### 8. Qty column missing from the dashboard entirely
Open Positions and Closed Trades tables never showed quantity, even
though the backend always had it — made it impossible to visually
confirm the #4 dynamic-sizing redesign was actually active after a
restart.
**Fix:** Added a Qty column to both tables.
**Status:** Fixed. (`dashboard/static/index.html`)

### 9. Dashboard panels all refreshed on one shared clock
Market Breadth, Top Gainers/Losers, and Sector Heatmap all shared one
cache/refresh cadence, no matter how differently each needed to update.
**Fix:** Decoupled into three independent throttles — Market Breadth 5s,
Top 50 Gainers/Losers 60s, Sector Heatmap 5s.
**Status:** Fixed. (`dashboard/state.py`)

### 10. ATR stop distances too tight — 7 straight stop-outs, 0 wins
Every trade this session (GODIGIT, IGIL, SRF, HEG, ICICIGI, TIPSMUSIC,
PVRINOX) was stopped out within seconds to a few minutes, each on a
price move of only 0.12%–0.24% — smaller than ordinary 1-minute noise.
**Cause:** ATR computed from a thin, freshly-opened candle window can
read near-zero. `qty = RISK_PER_TRADE_RS / (ATR_STOP_MULTIPLIER × ATR)`
has no floor, so a tiny ATR produces a razor-thin stop with no room to
survive a normal post-breakout retest.
**Fix:** Added `MIN_STOP_DISTANCE_PCT` (0.5% of price) — the stop/trail
distance actually used is now `max(ATR-based distance, 0.5% of price)`,
applied to both the initial stop and the ongoing trailing ratchet.
**Status:** Fixed. (`config.py`, `core/engine.py::_atr_entry_sizing`,
`_update_atr_trailing_on_candle_close`)

### 11. SWIGGY sized to 2,522 shares on a 46-paise stop
Back-solved ATR at entry was ₹0.264 — the sizing formula inflated qty to
compensate, producing ~₹6.2 lakh of notional exposure for what the
system still thought was a ₹1,000-risk trade.
**Cause:** Same root cause as #10, plus no ceiling existed on qty or
notional exposure at all.
**Fix:** Added `MAX_NOTIONAL_PER_TRADE_RS` (₹50,000) — qty is capped down
to this notional regardless of what the risk formula computes, as a
second, independent backstop alongside the stop floor in #10.
**Status:** Fixed. (`config.py`, `core/engine.py::_atr_entry_sizing`)

### 12. No earnings-day awareness
The bot has no way to tell an earnings-reaction gap apart from a real
technical breakout — a stock reporting results can gap several percent
on news, which an ATR read off a handful of post-open candles will
misread as organic momentum.
**Fix:** Added `EARNINGS_CALENDAR` (date → symbols) and a check that
silently skips new *structural* entries (manual override still works)
for any symbol reporting that day. Sun/moon source rows mapped correctly
— a same-day (pre/during market) report blocks that day; an after-close
report blocks the next trading day, since that's when the gap actually
shows up.
**Status:** Mitigated, not complete — this week's list was sourced from
a screenshot that truncated ~100 of 351 names behind "+more." Operator to
paste the full text list weekly going forward; the dict gets regenerated
each time. (`config.EARNINGS_CALENDAR`)

### 13. SONACOMS bought on a false breakout — ORB range 3.80 too narrow
Bot bought at 734.80 believing it broke its saved ORB high of 733.30.
Dhan's own ORB indicator showed the true high at 737.10 — the "breakout"
was actually still inside the real opening range.
**Cause:** Traced in `logs/diagnostics.log`: the live feed went stale
for ~30 seconds right at 09:15:10–09:15:42 (the single most volatile
minute of the day). Whatever the real price did during that gap was
never delivered as individual ticks, so `orb_engine.update()` never saw
the true peak.
**Root cause of the gap itself:** confirmed system-wide, not
SONACOMS-specific — 646 different symbols logged the same staleness
warning in that one minute. `main.py`'s WebSocket `on_message` callback
calls `engine.process_tick()` synchronously on the same thread that
reads the socket — when ~750 symbols post their opening trade within a
second or two, that single thread falls behind, and ticks get processed
15–30 seconds late (or, under the worst of the backlog, possibly dropped
by the feed client's internal buffer rather than merely delayed — can't
fully distinguish the two from our own logs).
**Fix applied today:** `market_data.is_orb_window_unreliable(symbol)` —
any symbol that goes stale while its own ORB window (09:15–09:30) is
still open is flagged for the rest of the session; structural entries
are silently skipped for it, same pattern as the frozen-price/circuit
checks. (`core/market_data.py`, `core/engine.py::_try_structural_entry`)
**Status:** Fixed at the root (same day, during the trading-policy
revamp). `main.py` now decouples tick receiving from processing: the
WebSocket callback only parses and enqueues (microseconds per tick), and
a dedicated worker thread drains the queue in strict arrival order — the
socket reader can never again be blocked by engine work during the
opening burst. Staleness is now measured at delivery (enqueue) time, so
queued-but-delivered ticks aren't falsely flagged. The
`is_orb_window_unreliable` safety net stays in place as a second layer.
Heartbeat log now reports tick-queue backlog + worker liveness so the
09:15 burst can be watched directly.

---

---

## 2026-07-24 (afternoon) — trading-policy revamp

Operator authorized a full revamp of the bot's trading style. Built in
one batch (see TRADING_POLICY.md for the complete decision path):

- **Tick queue + worker thread** — root fix for #13, see its updated
  status above.
- **Market-regime gate** — when ≥60% of the universe is declining, LONG
  entries are blocked (shorts only), and mirrored. The bot no longer
  fights the tape (answer to POST_MARKET items 1 and 9).
- **Max 10 concurrent positions** — no more 131-position spray
  (POST_MARKET item 4).
- **Daily loss switch (−₹10,000 realized)** and **daily goal (+₹50,000
  realized)** — the bot now has a concept of "enough," both directions
  (POST_MARKET item 5).
- **Breakout margin (0.1%)** — a close must clear the ORB boundary with
  conviction, not by 5 paise (kills the SONACOMS class of noise entry).
- **Fresh-entry cutoff 14:30** — no new positions into the dead
  afternoon (backed by POST_MARKET item 10's own data).
- **Partial profit-taking ON (Day-1 baseline: 2.0 ATR / 50% trim)** —
  the "trailing target" half of dynamic targets+stops; the ATR
  chandelier trail is the stop half.

All are config-switchable and structural-entry-only (manual override
always available). 370 tests passing after the batch.

## Open items (not yet acted on)

- **#12 earnings list is incomplete.** Needs the operator to paste the
  full weekly text list; current dict only has what was visible in one
  screenshot.
- **Discuss item 13 (news priority decay / story clustering)** — raised
  earlier, not yet discussed.
- **Scale-in (pyramiding)** — explicitly declined for now by operator;
  only scale-out (partial profit-taking) was built.
- **Stock prioritization (POST_MARKET item 8)** — which signal to prefer
  when more signals fire than the 10-position cap allows is currently
  first-come-first-served; a real ranking (liquidity/volatility/news) is
  a future design pass.
- **Transaction-cost modeling (POST_MARKET item 11)** — paper P&L still
  ignores brokerage/STT/slippage; real-money readiness requires it.

---

## AFTER-MARKET SESSION 2026-07-24 — critical bugs batch (DONE)

Worked through the critical-bugs group after close. All fixed with tests,
full suite green at 377:

- **#0 square-off entry leak — FIXED.** Entry guard now checks the actual
  processing tick_time (the first 15:15 tick), not the 15:14 candle label,
  so nothing opens at/after square-off. Plus main.py re-flattens on any
  post-square-off loop where the book isn't empty (belt-and-suspenders).
- **#0b breakout-fires-every-candle / instant refill — FIXED.** Strategy
  now fires ONCE on the fresh cross (transition), tracked every candle via
  note_candle_close() so a stopout with price still beyond the range can't
  re-fire. Margin folded into the strategy so the memory uses the same
  line the signal does.
- **#1 Momentum Universe removed from dashboard — DONE.** Gone from
  state.py, index.html, and tests. (Engine still uses momentum_universe
  internally as the ATR-mode signal — not the dashboard.)
- **#2 feed staleness warnings — DONE.** Warm-up grace (60s) silences the
  connect/open burst; per-symbol stale events now go to the file log only;
  a single systemic console alarm fires only when >=50% of seen symbols
  are stale at once (real feed lag), and clears on recovery.
- **#3 torn trade-log line — FIXED.** log_trade builds the full row in
  memory then writes it in one flush+fsync, so a kill mid-write can't
  leave a partial line.

## SIGNAL-QUALITY CHANGES 2026-07-24 (evening) — DONE

- **Change 1 — restart-seeding.** A mid-day restart no longer manufactures
  stale entries. The fresh-cross memory now PRIMES on the first candle it
  sees per symbol (records state, never fires), so a stock already beyond
  its ORB range at restart (KPITTECH ~₹583 vs ₹556.70 high) is treated as
  "already crossed" and only a genuine later cross can fire.
- **Change 2 — volume-surge breakout filter.** A fresh breakout only
  enters if the breakout candle's volume is ≥1.5× the recent average
  (config VOLUME_SURGE_MULT). Separates real breakouts (KPITTECH, ran
  +5.3%) from thin drifts (MOIL/TATASTEEL/ICICIBANK, went +0.2–0.4%).
  Feed switched Ticker→QUOTE mode to carry volume. **Fail-open**: missing/
  thin volume never blocks a trade; config-gated (ENABLE_VOLUME_FILTER).
  ⚠️ **LIVE SMOKE-TEST NEEDED**: the Ticker→Quote feed-mode change can't be
  validated offline. On the next live run, confirm (a) ticks still flow
  (heartbeat tick count rising), and (b) the dashboard/candles look normal.
  Worst case is fail-open (volume empty, filter does nothing) — trading is
  never blocked by it.

Still OPEN (design-heavy, need operator input) — original list below:

## NEXT SESSION — do all at once after market (operator's instruction, 2026-07-24 close)

The #0/#0b/#1/#2/#3 items above are DONE. The design-heavy items below
still remain.

0. **CRITICAL — new entries fire AT/AFTER the 15:15 square-off.** Confirmed
   in today's log: at 15:15:00–15:15:01, ten fresh STRUCTURAL_LONG/SHORT
   entries opened at the SAME second as the SQUARE_OFF sells. Positions
   opened in that race are never flattened (main.py's `flatten_all()` is
   one-shot) — in LIVE mode that's unwanted overnight exposure. This is
   the same class as the old "still buying at 15:18" bug, resurfacing at
   the boundary. **Root cause:** the entry guard in
   `_try_structural_entry()` checks the candle's LABEL time (the 15:14
   minute), but the final 15:14 candle only CLOSES at 15:15:00+, so it
   slips past the `>= SQUARE_OFF_T` check and fires. **Fix options:** (a)
   gate entries on the closing tick's actual time, not the candle label;
   and/or (b) make square-off flatten repeatedly / block ALL entries once
   past 15:15, not one-shot; and/or (c) stop new entries a minute early
   (14:xx buffer). Highest priority of the batch.

0b. **Breakout fires on STATE, not the EVENT — slots refill instantly on
   close.** Operator: "why are 10 positions filled instantly every time I
   close open positions?" Root cause: `core/strategy.py`'s signal is
   `close > ORB_high` (or `< ORB_low`) checked EVERY candle close — so a
   stock that broke out at 11am and is still beyond its range at 2pm is a
   STANDING signal that re-fires every minute. By afternoon dozens of
   stocks sit beyond their ranges, so the 10-slot cap refills the instant
   it frees. Compounded by: (a) manual/Exit-All closes DON'T block
   re-entry (only stop-outs do), so it re-buys the very names just closed;
   (b) all 750 now eligible = larger standing-signal pool. **Fix:** fire a
   breakout ONCE on the fresh cross (transition: prior candle inside range
   / at-or-not-beyond, this candle closes beyond) — not on the persistent
   state. Optionally add a cooldown / re-entry block after a manual close
   too. (Workaround for now: use "Exit All + Stop New Entries", not "Exit
   All only".)

0c. **Earnings filter is too blunt — allow ORDERLY results-day trends,
   skip only violent spikes.** Verified today: ATUL (opened 6130, ORB
   6136–6188, ran to 6491 = +4.9% above the breakout line, closed near
   highs) and LALPATHLAB (opened 1698, ORB 1655–1677, ran to 1774 = +5.8%,
   closed near highs) were BOTH clean, sustained, tradeable long breakouts
   on their results day — real moves, not APAR-style spike-and-die. The
   current blanket "block every earnings-day stock" misses these. The
   distinguishing factor is the CHARACTER of the move: APAR = violent
   ~₹900 spike in seconds (untradeable); ATUL/LALPATHLAB = orderly trends
   with normal candles. **Design a filter that measures "violence"** —
   e.g. skip if the opening gap exceeds X% or any single candle's range
   exceeds Y% (a spike), but ALLOW a normal-sized breakout with follow-
   through. Then results-day stocks trade on their real moves and only the
   blowoffs are excluded. (Operator wants to design the exact thresholds
   in the after-market session, from real examples.)

1. **Remove Momentum Universe completely from the dashboard.** The frozen
   9:30 top-25/25 shortlist was removed from the trading engine today, but
   the DASHBOARD still shows it — leftover from the fixed-100-qty test.
   Strip it out of `dashboard/state.py` (`_build`/momentum panel) and
   `dashboard/static/index.html` (the panel + any CSS/JS), and drop the
   now-dead `MomentumUniverse` wiring in `main.py` if nothing else needs
   it. Operator: "our dashboard is still carrying today's test — remove
   this completely."

2. **Feed staleness warnings — two fixes:**
   a. **Warm-up grace period.** Suppress stale-tick warnings for the first
      ~30–60s after startup / feed reconnect. Confirmed harmless: at 09:15
      open (and on every restart) the feed dumps all ~750 symbols at once,
      646 briefly cross the 5s line all clustered at 5.2–7s, then clear
      completely by the next minute (09:16 = 0 stale). This is why the
      prints appear at 09:15 AND on every main.py restart. A grace period
      makes restarts come up clean without hiding a real mid-session
      problem.
   b. **Distinguish "not trading" from "feed behind."** The 5s threshold
      cries wolf every afternoon lull — at 14:53, 340 symbols showed
      "stale" while the tick-queue backlog was 0 and the worker was alive
      (i.e. OUR side was fine; the stocks simply weren't trading every 5s
      at ~46 ticks/sec). Only raise a real alarm when LIQUID names or a
      large share of the universe go stale *at once*, not when thin
      mid-caps quietly don't trade.

3. **Torn trade-log line guard.** A malformed partial line (`_BREAKDOWN`)
   appeared in `trade_log.csv` from a write interrupted by a restart. Make
   the trade-logger write atomically (or append-and-flush safely) so a
   kill mid-write can't leave a half-row.

### Also still open from today's audit (fold into the same session)
- **Manual-entry SIZE is still unguarded (Audit #1).** Manual buy/short
  still use flat 100 shares — NOT ATR sizing or the ₹2L notional cap. The
  manual STOP got the 1% floor today, but SIZE didn't. Route manual
  entries through the same sizing as structural (keep override on *whether*
  to trade, not *how big*).
- **Daily loss/goal reset on restart (Audit #2).** Read realized P&L from
  the persisted portfolio (or trade_log) so a mid-session restart doesn't
  re-arm the loss switch.
- **Trade log lacks market-time + P&L (Audit #4).** Timestamps are
  wall-clock, no per-exit realized-P&L column — makes daily review harder.
- **Charges on the dashboard.** Show estimated brokerage/STT/slippage per
  trade and net-of-cost P&L (started discussing, not built).
- **The big one — anchor stops/targets to real levels, not 1-minute ATR.**
  The "ATR is not the holy bible" redesign: replace noise-based ATR
  distances with structure/percentage/cost-aware levels.
- **Optional:** persist the "entries paused" flag across a restart, so a
  deliberate pause survives a restart instead of quietly resuming.
