---
name: every-change-needs-its-effect-on-trading-stated
description: "His standing benchmark from 6 Sep 2026 — state the effect on the bot and the whole trading mechanism BEFORE making any change, every time"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 4e2a583c-bc67-420a-94ab-5a19438f1c99
  modified: 2026-09-06T09:37:42.643Z
---

**His instruction, 6 September 2026:**

> "does this Tab building will delay bot trading? this is the benchmark
> question from me everytime. from now on what ever change we are doing
> u need to explain me its effect on bot & its complete trading
> mechanism. got it?"

**Before any change, say plainly:**

1. Does the TRADING PATH read it — `core/rules.py`, `core/ranker.py`,
   `core/auto_entry.py`, `core/engine.py`, `core/why_moving.py`,
   `core/results_gate.py`? Name the files checked.
2. Does the BOARD REBUILD compute it? That is the slow lane (600 ms
   warm in replay; the code's note says 42s median live) and the entry
   path waits on it, so anything added there is paid every cycle.
3. What does it COST, measured, not asserted.
4. What BEHAVIOUR changes — what the bot will do differently, and what
   it can no longer do.
5. What it CANNOT break.

**Why:** he pays for this and the bot trades his money. He has asked
some version of this question at every step, and it is faster to
answer it unprompted than to be asked.

**The pattern that satisfies it** — a panel gets its own endpoint and
is fetched when the tab is opened, never added to the payload. Month,
Speed and Brain tabs are all built that way: zero rebuild cost. The
only thing added inside the rebuild all day was the size-band stamp,
0.060 ms per 1,000 rows.

**And measure warm.** A first reading after startup is cold: the
rebuild read 2,381 ms on its first pass and 606-685 ms settled. I
quoted the cold number to him once before checking. See
[[measure-the-second-run-not-the-first]].
