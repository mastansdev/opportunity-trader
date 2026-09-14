---
name: the-seat-goes-back-when-it-never-worked
description: "DRIFTED_NO_MOVE, added 14 Sep 2026 -- 45 min, never +1.0%, below entry. The measurement behind it, and the cost it knowingly pays"
metadata:
  node_type: memory
  type: project
---

**Added 14 September 2026**, the first new exit rule since
BUYING_DRIED_UP.

## Why it exists

Over 7-10 Sep, **32 positions were flattened BY HAND at 15:11-15:22 for
-30,444 gross**. They drifted at -1 to -2% all session: never far enough
for the -3% stop, never up enough for `_buying_dried_up()`, which takes
winners only and says why -- *"A losing trade belongs to the stop."*

That principle is right and is kept. What it missed is that a position
drifting sideways-down for six hours does not belong to the stop either
-- **the stop never comes**. It belongs to nothing, and the seat it
holds is the seat the next opportunity needed: the book was full for 290
of the session's 306 minutes.

**Only 7 of those 32 ever reached +1.0%** at any point, and the ones
that did their best did it in the first ten minutes.

## The rule

    held >= 45 min  AND  high-water gain never >= +1.0%  AND  below entry
    -> exit, tagged DRIFTED_NO_MOVE

Asked AFTER the buying check, and refuses anything at or above entry, so
it can never book a winner early. No peak reading from the trail means
no action.

## What it costs, knowingly

Replayed against the minute candles on those 95 trades: **+16,432 gross**
(-12,768 -> +3,664).

    MANUAL_EXIT     +16,091   trades that had no rule at all
    TRAILING_STOP    +9,052   left before the -3% stop arrived
    BUYING_DRIED_UP -10,669   <- positions it closes that would have
                                 recovered and been booked later

That last line is real and is written into config.py beside the
constants. It is accepted because the net is positive and because the
seat turnover is itself part of the late-entry problem.

## It is PROVISIONAL

Measured on the same four sessions it was chosen on, which is the one
thing [[never-mix-old-data-with-new-rules]] says never to trust. It runs
in PAPER and is judged on sessions it has not seen.
`DRIFT_EXIT_ENABLED = False` removes it in one line.

Related: [[what-the-live-stop-and-seats-actually-are]],
[[late-entries-measured]], [[rules-are-provisional-not-permanent]].
