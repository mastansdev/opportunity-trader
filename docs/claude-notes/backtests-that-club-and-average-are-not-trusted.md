---
name: backtests-that-club-and-average-are-not-trusted
description: "His standing objection, 14 Sep 2026 -- pooled/averaged backtests misdescribe an opportunity strategy, and every counterfactual I ran that day shared a worse flaw"
metadata:
  node_type: feedback
  type: feedback
---

**14 September 2026**, after I handed him three measured-sounding
numbers for three new rules:

> "i never trusted on your illogical back results. u were clubbing,
> averaging, static calculating like mean, median while calculating the
> back data which is not good for stocks. we will never be able to
> trade in all stocks at all time. we are just opportunity traders that
> too ride until momentum lasts"

**Why he is right.** A mean or a sum across a pool of trades assumes
every one of them could have been taken. He has 2-10 seats. He is
picking specific situations and riding them, so the payoff lives in the
individual case; averaging is exactly the operation that destroys what
he selects for.

**And the error was worse than averaging.** Every counterfactual I ran
that day assumed the SAME TRADES WOULD STILL HAVE BEEN TAKEN. The
freshness gate refuses 61 of 95 entries, so the drift exit's +16,432
and the profit lock's +7,110 -- both computed across all 95 -- describe
a book those rules would have destroyed: seats free at different times,
different stocks get bought. Three rules measured in isolation against
a history each one would have changed, then added together.

Those numbers were retracted. They were not predictions.

**How to apply.**

- Do not present a pooled backtest number as a prediction. If it is
  offline and in-sample, say both words.
- A rule that changes WHICH trades are taken cannot be scored against
  the trades that were actually taken. The counterfactual changes the
  state.
- Rules are judged FORWARD, one case at a time, on sessions nobody
  tuned anything on -- which is why the bot now records
  extension_pct, drift_since_rank_pct, peak_mtm and the full entry
  fingerprint, and why refusals carry their reason into
  core/signal_journal.py.
- Read a session by its individual refusals and holds, not by the
  day's total. One day's P&L is noise about a rule.

Related: [[never-mix-old-data-with-new-rules]],
[[verify-the-value-the-live-path-reads]], [[operator-work-style]],
[[measure-the-second-run-not-the-first]].
