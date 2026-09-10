---
name: board-rebuild-is-too-slow
description: The dashboard snapshot rebuilds every 42s median (82s p90) and entries read it — so every entry decides on stale prices. Measured 3 Sep 2026; got 50% worse that day.
metadata: 
  node_type: memory
  type: project
  originSessionId: 9fd6931f-938d-4539-ad73-4191c031054a
  modified: 2026-09-10T10:33:38.207Z
---

**Fix this before the exit rules.** His instruction, 3 September 2026:

> "fix the ranker slowness first after market close, why can't we
> follow the same method in getting data & use only the stocks which
> were sort listed as per our requirement. thats easy i believe."

## What is measured

Board rebuild intervals, 10:00–14:00, from `[GL] N rows from N symbols`:

```
2 Sep   n=545   median 28s   p90  41s
3 Sep   n=324   median 42s   p90  82s   max 192s
```

**It doubled at p90 in one day.** What changed between those sessions:
universe 1,332 → 1,343; the pool now seeds from
`watchlist_builder.filed_symbols()` (my change, 2 Sep); 11 stocks
added to the master.

`build_morning_watchlist` is **0.02s** — measured, not the cause.
The cause is **not yet known** and must be measured, not guessed.

## Why it costs money

**Entries read the snapshot** — `main.py` hands
`snapshot["ranked"]["rows"]` to `auto_entry.take()`. So every entry
decides on prices up to 82 seconds old, then sends a market order at
the current price. That gap is the slippage he asked about, and he
was right.

**Exits do not** — the trailing stop and BUYING_DRIED_UP run on the
tick feed and fire in milliseconds. The cost is entirely on entry.

## What the ranker actually sees

Not the whole universe. Roughly 400 a cycle: the top-50 movers plus
~350 "added by reason". Refusals per cycle run ~370, output ~23 rows.
So his "only rank the shortlisted" is close to what already happens —
the ranker is probably NOT the slow part despite its name.

Bigger candidates, unmeasured: the GL build over 1,338 symbols, the
shortlist reference over 2,446, and ~30 other panels all rebuilt from
scratch every cycle.

## Measured again 10 Sep 2026 — the guess above was wrong

From `[SLOW]` lines, 8-10 Sep: medians 32.6s / 70.7s / 23.7s, p90 42.0 /
103.7 / 54.1, max 160.2s. Worst panel: **`ranked` 723 times, `shortlist`
326** — so the ranker IS the slow part. And it blocks: `main.py:2104` calls
`dashboard_state.refresh()` inline (interval 1s) and `state.py:825` runs
`_build()` synchronously, so heartbeats (60s) landed 65-91s apart median,
196s max — his "bot is late, recovers, never in sync". Candidates
(`_candidates["rows"]`, main.py:2203) are published only after a rebuild,
so seats go to stale picks. First step: rebuild on its own thread.

## The shape of the fix

The architecture rebuilds the whole world each cycle instead of
updating what changed. `/ws/prices` already proves the alternative:
it pushes ticks four times a second, independent of the rebuild, and
the desk now reads it (3 Sep). The same treatment applies elsewhere —
slow panels stay slow, fast-moving parts stream.

**First step is instrumentation**: time every panel in one refresh and
find the real cost. Do not optimise a guess.

See [[verify-the-value-the-live-path-reads]] and
[[his-trading-rules]].
