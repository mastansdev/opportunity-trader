---
name: telegram-channel-roles
description: Which PRO channels post daily (delay costs money) vs only in results season vs episodically
metadata: 
  node_type: memory
  type: project
  originSessionId: 9fd6931f-938d-4539-ad73-4191c031054a
  modified: 2026-08-24T09:51:43.957Z
---

The nine PRO channels are not interchangeable. He has had to say this
more than once, so treat it as settled:

**Daily — silence IS a fault, and lateness costs money.** These carry the
order wins and news the bot trades on:
`OrderBook Pulse`, `Day Trader Telugu`, `RedboxGlobal India`

**Results season only** — quiet or promotional between seasons, which is
correct: `Earnings Pulse`, `Earnings 360`, `Earnings Pro`.
Earnings Pulse also posts promotional content daily; that is not data.

**Episodic by design** — never owed a post on a schedule:
`WLPulseBot` (premium tracker, capped at 100 stocks),
`Business Pulse` (fires only when a company publishes a business update).

Encoded in `core/feed_clock.py` as `DAILY_CHANNELS` / `RESULTS_CHANNELS`
/ `EPISODIC_CHANNELS` with `channel_kind()` and `expected_today()`;
`gaps()` now separates `quiet` from `stale` so an episodic channel that
has been silent for days is not reported as a broken feed.

**Why:** on 24 Aug 2026 I read a 4-day-old watermark on Business Pulse
and reported it to him as an outage, having been told before. Noise
beside a real outage is how a real one gets ignored.

**How to apply:** before calling any feed broken, check
`feed_clock.expected_today(channel)`. Measure lag (posted `at` vs stored
`seen_at`) for the daily three specifically — median was ~4.8 min on
24 Aug with `POLL_SECONDS = 90`, so most of the delay is the cycle
walking all ten channels plus OCR, not the interval.
See [[opportunity-trader-architecture]] and [[operator-work-style]].
