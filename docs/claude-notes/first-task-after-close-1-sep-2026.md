---
name: first-task-after-close-1-sep-2026
description: "Delete provably-unreachable branches — his first task after the 1 Sep 2026 close, agreed before the open"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9fd6931f-938d-4539-ad73-4191c031054a
  modified: 2026-09-01T02:04:07.172Z
---

**First task after the close on 1 September 2026**, agreed that morning:
find and delete the code branches that are provably unreachable under
the current settings. He said "even i forgot to ask" — so it is mine to
remember, not his.

**Why it matters, and why NOT for the reason it looks like.** Dead code
is not a runtime burden — an unreachable `elif` costs nothing, Python
never evaluates it. The cost is that it misleads whoever reads it. On
1 September I told him the stop was `0.8 x ATR`, twice, having read
`ATR_STOP_MULTIPLIER` straight out of config. That branch sits under
`elif` beneath `VOLATILITY_SCALED_STOP`, which is True, so it cannot
run. The live stop is `2.0 x the stock's own DAILY ATR` (floored 0.75%,
capped 6%) — which he remembered and I did not.

**The method, and it is not last night's.** On 31 August I swept for
imports that *looked* unused and deleted whole lines that were
load-bearing, breaking four files. Pattern-matching is the wrong tool.
The right one is proving a branch cannot execute given a setting's
current value — checkable, not guessed.

**The rules for doing it:**
- after the close, never before a session
- one at a time, full suite green between each
- prove unreachable first, then delete
- `py tools/dry_run_live_path.py` before and after

Known first candidate: the `elif ENABLE_BOT_TRAILING_STOP` stop-width
branch in `core/engine.py` (`ATR_STOP_MULTIPLIER * atr`), unreachable
while `VOLATILITY_SCALED_STOP` is True.

See [[never-mix-old-data-with-new-rules]] and
[[verify-the-value-the-live-path-reads]] — this is the same lesson a
third time: read what the live path executes, not what config declares.
