# Opportunity Trader — Backlog (leftover work)

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
