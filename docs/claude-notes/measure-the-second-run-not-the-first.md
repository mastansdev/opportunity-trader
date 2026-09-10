---
name: measure-the-second-run-not-the-first
description: "A benchmark that runs A then B charges every one-time load to A; warm first, then alternate A/B/A/B"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9fd6931f-938d-4539-ad73-4191c031054a
  modified: 2026-09-06T01:49:46.545Z
---

Timing the new code first and the old code second makes the new code
look slow by however much the process had left to load — imports,
pandas, the master list, every lazy cache.

6 Sep 2026, measuring the standing-order gate on the entry path:

    gate ON first, gate OFF second      18.76 ms a symbol   WRONG
    warmed, then A/B/A/B                 0.22 ms a symbol   real

I reported the first number to him as a lag problem. The problem was
real — 1,642 ms on the FIRST standing lookup, which would have landed
inside the 09:15 entry loop — but the per-symbol figure was my
measurement, not his bot. Two different faults, and I named the wrong
one.

**Why:** a cold process has hundreds of milliseconds of first-touch
cost with nobody's name on it, and whichever arm runs first collects
all of it. The shape of the answer changes too: "every call is slow"
and "one call is slow" need completely different fixes.

**How to apply:** warm every path to be timed until a repeat run is
flat, then alternate the arms and compare the averages. If the two
arms differ by more than a few percent, run them again — a difference
that moves between runs is the loader, not the code. And say which
number is the one-time cost and which is per call; they are different
questions and he asks about both.

Same family as [[verify-the-value-the-live-path-reads]]: measure the
thing that actually runs, in the state it actually runs in.
