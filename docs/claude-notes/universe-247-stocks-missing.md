---
name: universe-247-stocks-missing
description: 247 stocks qualify for the tradeable universe and were never added — the review file has sat unactioned since 26 July
metadata:
  type: project
---

**FIRST job after the 1 September 2026 close.** Ahead of
[[telegram-catchup-should-walk-forward]] and
[[first-task-after-close-1-sep-2026]].

He asked why DYCL (Dynamic Cables) was not traded on 1 September. It
rose **+11.84%** (493 -> 551), the bot recorded **121 minutes of its
order flow** from 09:15, and it appeared on the live gainers board at
+11.21%. It has a volume curve (84 days) and a liquidity number
(Rs 18.17 cr).

And it produced **zero pick rows and zero refusal rows.** It was never
ranked and never refused, because it never reached the ranker.

**The cause.** `data/universe_review.csv`:

    action ADD   symbol DYCL   turnover_cr 47.25
    reason: "qualifies but missing from our universe"

That file holds **247 ADD rows** — stocks that qualify and are not in
the universe. The biggest by turnover:

    SHADOWFAX   Rs 3,272.7 cr        CNL         Rs   549.1 cr
    CMLL        Rs 1,157.2 cr        INDOBORAX   Rs   434.7 cr
    GANDHAR     Rs 1,036.5 cr        E2E         Rs   366.6 cr

It also holds 206 REMOVE rows and 2 CHECK.

**Written 26 July 2026 and never actioned.** Five weeks. The universe
resolved to 1,282 subscribed on 1 September; it should be nearer 1,529.

**Why it LOOKED like the bot was watching:** the tick feed subscribes
more broadly than the universe, so order flow and candles are recorded
for stocks the ranker will never consider. The dashboard shows them as
gainers. Nothing says they are ineligible.

**The same shape as every other fault found 31 Aug - 1 Sep:** the work
was done, the answer was written to a file, and the last step to where
it is used never happened.

**Care needed:** the ADD list includes ETFs (LIQUIDBEES, SILVERBEES,
NIFTYBEES, SBIFUNDS). `core/universe_builder.py` has `_looks_like_an_etf`
and `fetch_excluded_symbols` for exactly this. Do not bulk-add without
running them, and check the 206 REMOVE rows separately rather than
applying both at once.
