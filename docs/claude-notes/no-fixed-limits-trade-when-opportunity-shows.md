---
name: no-fixed-limits-trade-when-opportunity-shows
description: "The bot does not trade all day every day — enter only when opportunity shows, exit on the exit rule, and no fixed time/price/limit decides either"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9fd6931f-938d-4539-ad73-4191c031054a
  modified: 2026-09-01T08:28:09.638Z
---

Stated 1 September 2026, in his words:

> "we will not trade whole day on each & every day. bot needs to book
> profits when the exit rule triggers thats it & new entries only when
> opportunity showed up. there is no fixed time ,price or fixed
> limitations to follow. this is stock market not our own shop to do as
> we want."

So a quiet day with no trades is a CORRECT day, not a failure — and a
day with several is fine too. Neither number is a target.

**Why:** he keeps finding gates that impose our schedule on the market
instead of reading it. `BREAKOUT_MAX_OFF_HIGH_PCT = 0.25` demanded the
price sit within 0.25% of the day's high and refused 41 distinct stocks
on 1 Sep. Worse, `engine.entry_blocked` was PERMANENT — nothing cleared
it, and `_try_structural_entry()` returned on it before any gate ran —
so a stock refused at 12:34 could not be bought at 14:00 however the
afternoon went.

**How to apply:** before adding or defending any gate, ask whether it
reads the market or imposes a schedule on it. Prefer a live measurement
(`still_buying()`, `pace_ratio()`) over a fixed threshold. A refusal
should say "not now" and be re-asked next cycle unless there is a real
reason it settles the stock for the session (a stop-out, a news block).
Do not report "no trades yet today" as a fault by itself — check first
whether anything was actually an opportunity.

**BOTH GATES NAMED HERE ARE NOW FIXED** -- verified 6 Sep 2026 by
executing the live code, not by reading it. `DAILY_PROFIT_TARGET_RS`
is still 75,000 but no longer returns: it logs "a good day is not a
reason to stop taking the next opportunity" and decides nothing.
`FIRST_NEW_ENTRY`/`LAST_NEW_ENTRY` are gone from config entirely.
`DAILY_MAX_LOSS_RS` = 12,000 DOES still stop the day and he approved
that one out loud -- it triggers on money already lost, not money not
yet made, which is the different shape he allowed for.
See [[rules-are-provisional-not-permanent]] and [[the-one-switch]].
