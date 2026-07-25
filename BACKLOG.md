# Opportunity Trader — Backlog (leftover work)

---
## ⚠️ AUDIT 2026-07-25 — discussed but NOT in the code

Verified by scanning every config flag against real usage. Everything
below was talked about; only the first item has since been fixed.

**FIXED during the audit:**
- ~~`ENABLE_TICK_SANITY` / `MAX_TICK_JUMP_PCT` were in config but never
  wired~~ → now enforced in `Engine.process_tick()` with 4 tests. This
  was the guard for the INFY/JLHL corrupt-tick class; it would have been
  dead config on Monday.

**BUILT LATER THE SAME DAY (2026-07-25, after the audit):**
- ORB now reconciled against the exchange's own high/low (the sampled
  feed ran too narrow -> false breakouts). Early 5-min range too.
- Daily P&L carries across a restart; "entries paused" persists.
- Liquidity floor; corrupt-tick guard wired.
- RS band widened 0.6-3.0% -> 0.4-5.0%.
- Sector/theme strength gate (operator's core thesis).
- Early-momentum entry (5-min range, max 2/day).
- **Stock Memory** -- corporate actions from NSE/BSE, consulted before
  every trade (the JLHL split fix).
- **Trade Memory** -- the learning loop, OBSERVATION ONLY.

**STILL NOT BUILT (agreed as valuable, never coded):**

1. **Higher-timeframe / daily trend alignment.** The single biggest gap.
   The bot cannot see yesterday. It bought SRF long after the stock fell
   10% over two days. Needs 20-day daily OHLC at startup + a rule that
   longs only trade above daily structure. *Blocked on: nothing, just
   not built.*
2. **Entry on the retest, not the breakout candle.** Mechanically better
   R:R with no new prediction required. Discussed twice, never built.
3. **Relative strength vs OWN SECTOR** (we built RS vs *market*, and a
   separate sector gate — but not the stock-vs-its-own-sector measure).
4. **Regime detection** (ADX + ATR percentile + persistence). Fully
   designed in `REGIME_NOTES.md`; zero code.
5. ~~Loosening the RS band~~ — **DONE 2026-07-25.** Widened to 0.4–5.0%;
   the old 0.6–3.0% had been fitted to the corrupted ORB ranges.
6. **Story clustering / news decay** (item 13, open since 2026-07-23).
7. **Per-sector CAPITAL cap** (Phase-2 leftover; the panic filter is not
   an exposure cap).
8. ~~Daily loss/goal counters reset on restart~~ — **DONE.** The daily
   guardrails now cover the whole session, not just the current process.
9. ~~Persist "entries paused"~~ **DONE.**
10. **Trade log: market-time + per-exit realized P&L column.**
11. ~~Liquidity floor~~ — **DONE.** ₹2cr turnover minimum, fail-open.
12. **Telegram alerts** — never started.
13. **Railway deploy** — code + guide ready, never deployed (your action).

**Known live issue, mitigated but not solved:**
- The tick feed is *sampled*, so the bot's ORB is narrower than reality.
  `ENABLE_ORB_EXCHANGE_RECONCILE` now widens it from the exchange OHLC
  at 09:30 — but any range used BEFORE that reconcile (i.e. the early
  5-minute momentum range) is still built from sampled ticks only.

---


Consolidated from PHASES.md, PHASE3_NEWS_DESIGN.md, TRADING_POLICY.md and
ISSUES_LOG.md on 2026-07-24. Only items NOT yet done are listed. Grouped by
theme; each has a rough size and whether it needs an operator working-session
(thresholds/design) vs. can be built straight away.

Status key: **[design]** needs a working session on real examples first ·
**[build]** can be implemented directly · **[verify]** needs a live session
to confirm · **[you]** needs an action from the operator.

---

## A. Trading logic & risk

1. **Stops/targets off real structure, not 1-minute ATR.** [design] The big
   one — the "ATR is not the holy bible" redesign. Replace noise-based ATR
   distances with structure / percentage / cost-aware levels. Highest impact,
   needs real examples to set the rules.

2. **Earnings filter "violence" refinement (ISSUES_LOG 0c).** [design] Blanket
   "block every earnings-day stock" wrongly skipped clean orderly trends
   (ATUL +4.9%, LALPATHLAB +5.8%, both tradeable) while it should only skip
   violent spike-and-die moves (APAR). Design a filter on the *character* of
   the move (opening gap %, single-candle range %).

3. **Full weekly earnings list (#12).** [you] Paste the complete results
   calendar into `config.EARNINGS_CALENDAR`; current dict is partial (one
   screenshot only).

4. **Per-sector capital exposure cap.** [build] Phase-2 leftover. A sector
   *panic* filter exists (breadth-based), but a real per-sector CAPITAL cap
   does not.

5. **Signal prioritization when more signals fire than the position cap.**
   [design] Currently first-come-first-served; rank by liquidity / volatility
   / news instead (POST_MARKET item 8).

## B. Restart robustness (smaller / mechanical)

6. **Daily loss/goal counters reset on restart (Audit #2).** [build] Read
   realized P&L from the persisted portfolio (or trade_log) so a mid-session
   restart doesn't re-arm the loss switch / re-open the goal.

7. **Persist the "entries paused" flag across restart.** [build] Optional,
   quick — so a deliberate pause survives a restart instead of resuming.

8. **Trade log: market-time timestamps + per-exit realized P&L column
   (Audit #4).** [build] Timestamps are wall-clock and there's no per-exit
   P&L column — makes daily review harder.

## C. News engine (continuing)

9. **Story clustering / priority decay (item 13).** [build] Collapse the
   same-story fan-out (one headline → one card listing the stocks it hit),
   and age out stale HIGH news over time. Directly finishes the "all items
   same with different headings" cleanup.

10. **Results-calendar integration + first-15-minute momentum setup.**
    [design] Deferred in Phase 3 / PHASE3_NEWS_DESIGN.

11. **Market-sentiment routing (Concern #4).** [design] Index / VIX-driven
    regime bias into the news→trade path.

## D. Interfaces & infra

12. **Deploy the news engine to Railway.** [you] Built and tested; follow
    RAILWAY_DEPLOY.md (create project, add Postgres, set env, point the bot at
    the cloud DB).

13. **Verify Monday live-test items.** [verify] Index security IDs, Quote-mode
    volume (already in the ISSUES_LOG Monday checklist).

14. **Telegram control / alerts.** [build] Phase 4, not started.

15. **Per-trade AI "Brain Verdict" / reasoning.** [design] Deliberately not
    built (no per-trade AI reasoning call exists). Large, separate piece.

## E. Validation (gates real money)

16. **Phase 5 — shadow-mode validation.** [verify] At least one full clean
    session validated against live data before the bot touches real capital.

17. **Monitoring Engine (India VIX / crude / gold / silver).** [build/verify]
    Partially started (index + VIX feed built); needs live verification and
    the commodities wired in.

---

### Suggested first picks (morning)
- **#9 story clustering** — finishes the news cleanup you just saw.
- **#6 / #7 / #8 restart-counter & log fixes** — quick, and matter for live safety.
- **#1 ATR→structure redesign** — highest impact, but book a working session
  on real examples first.
