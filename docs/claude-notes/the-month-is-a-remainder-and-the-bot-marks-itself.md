---
name: the-month-is-a-remainder-and-the-bot-marks-itself
description: "Built 6 Sep 2026 — MONTHLY_TARGET_RS as a running remainder (never a daily quota), and core/self_review.py asking its own book every night"
metadata: 
  node_type: memory
  type: project
  originSessionId: 4e2a583c-bc67-420a-94ab-5a19438f1c99
  modified: 2026-09-06T08:37:26.402Z
---

Two things he asked for on 6 September, both built, **both decide
nothing** and tests enforce that no gate imports either.

## The target: a remainder, never a quota

> "on monthly 5L target & in case day -1 bot booked 70 K then remaining
> 4.3L on remaining days & so on. not like averaging each day targets.
> as market may give more opportunites in some days & less in other
> days"

`config.MONTHLY_TARGET_RS = 5_00_000`, `core/monthly_target.py`.
**It divides by nothing** — there is deliberately no "needed per day"
field and a test fails if one appears. 5L over 21 sessions is 23,810 a
day, which lies twice: it makes a quiet Tuesday read as failure and
calls a day finished at noon. His own book proves it — 2 Sep lost
6,376, 4 Sep made 11,794.

Printed once at the close. When the goal is met it says so and adds
"a good month is not a reason to stop taking the next opportunity" —
the same treatment `DAILY_PROFIT_TARGET_RS` already got. The only
figure that still halts anything is `DAILY_MAX_LOSS_RS`, and that does
not apply in paper.

## The self review: it marks its own homework

> "yes - self performance upgrade, self improving"

`core/self_review.py`, run from main.py at the close. A fixed set of
questions put to its own book, printed, and **kept each night** so
`trend()` shows whether an answer holds. One night is a fact; ten
nights of the same answer is a finding; an answer that flips was never
real.

**FOUND ON ITS FIRST RUN:**

    12 of 16 days lost money on everything except their best two trades

    BUYING_DRIED_UP          37 trades  28 up   9 down   +47,481
    MANUAL_EXIT              61 trades  31 up  30 down   +31,754
    ROTATED_OUT              16 trades   4 up  12 down    -1,827
    MISSED_STOP_RECONCILED    7 trades   2 up   5 down   -22,296

- `MISSED_STOP_RECONCILED` lost nearly twice Friday's whole profit on
  7 trades. Mostly late July (DEEPAKFERT -13,498 on 30 July) but **one
  on 3 September** — not dead, worth watching.
- `ROTATED_OUT` last fired 21 August; rotation is off and stayed off.
- `BUYING_DRIED_UP` is the best exit by a distance. His order-flow
  exit earns its place.

**THE BLEED IS THE YARDSTICK.** Every day so far, the best two trades
ARE the profit: 1 Sep -6,235, 2 Sep -6,500, 3 Sep -3,123, 4 Sep
-12,882 without them. A day's P&L measures whether a big mover turned
up; the rest column can only be moved by getting better. Judge changes
on that, not on day totals.

**Three disciplines are written into the asking**, not left to memory:
a question under `MIN_CASES` (20, same bar as
`opportunity.PAYOFF_MIN_CASES`) says so and names the stocks instead
of pretending a handful is a rate; nothing is averaged across stocks,
only counts and rupee totals; and fields that began recording on 6 Sep
say "nothing recorded yet" rather than reading as zero.

See [[why-the-3-percent-bar-stays-for-now]] and
[[the-bot-asks-who-else-this-lands-on]] for the rest of that day.
