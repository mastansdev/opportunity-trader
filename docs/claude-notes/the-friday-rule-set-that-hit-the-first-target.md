---
name: the-friday-rule-set-that-hit-the-first-target
description: 4 Sep 2026 hit his first target — commit 6efe7ff and its exact constants. The baseline every later rule set is judged against.
metadata: 
  node_type: memory
  type: project
  originSessionId: 4e2a583c-bc67-420a-94ab-5a19438f1c99
  modified: 2026-09-06T03:05:02.063Z
---

**His words, 6 September 2026:**

> "our first target acheived on Friday rule set 04/09/2026"

So Friday 4 September is the BASELINE. Not a good day among many — the
first time the thing worked. Everything after it is judged against it.

**What Friday was**, from his book:

    2 Sep     6 trades    1 up   5 down    Rs  -6,845
    3 Sep    21 trades    8 up  13 down    Rs     235
    4 Sep    27 trades   14 up  13 down    Rs   9,247   <- the target

**THOSE ARE NET, CORRECTED 6 SEPTEMBER.** trade_memory stores pnl
GROSS -- (exit - entry) x qty -- and I reported gross all day. Friday
was 11,794 gross, 2,547 in charges, **9,247 kept**. Worse, 3 September
read +1,870 gross and 13 up / 8 down; net it is **+235 and 8 up / 13
down** -- charges turned five apparent winners into losers. September
to date is **-3,838**, not +1,197. The Month tab and every per-trade
table now show net with charges beside it.

Won 14, lost 13 — near enough a coin flip, and it paid because the
winners were bigger: NIACL +14,577 and PURVA +10,099 against the worst
losses of -4,833 (RESPONIND) and -4,517 (DIFFNKG). **The size of the
right ones, not the count.** All paper.

**The exact rule set** — commit `6efe7ff`, "Paper is five lakh and asks
the broker for nothing but margin", 4 Sep 09:00, fifteen minutes before
the open:

    TRADING_MODE                    PAPER
    MTF_MARGIN_PER_POSITION_RS      50,000  (paper)  <- changed THAT morning
    PAPER_STARTING_CAPITAL          5,00,000         <- changed THAT morning
    MAX_OPEN_POSITIONS              3
    FIXED_STOP_PCT                  3.0
    PEAK_TRAIL_PCT                  0.025    trail ON
    SQUARE_OFF_TIME                 15:15
    ENABLE_SHORT_TRADES             False
    ONE_TRADE_PER_SYMBOL_PER_DAY    False
    DAILY_LOSS_CAP_APPLIES_IN_PAPER False
    MIN_MOVE_FROM_PREV_CLOSE_PCT    3.0
    MIN_VOLUME_RATIO                2.5
    SURGE_REASON_MIN_RATIO          10.0
    REQUIRE_A_REASON_ALWAYS         True
    ranker sort   (fading last, then -score)   NOT by volume multiple

**Positions were ~1.5x Wednesday's** because the slot changed that
morning: Friday ran Rs 82k-191k, Wednesday Rs 47k-120k. Rupee results
from 3 Sep and earlier are NOT comparable with 4 Sep.

**Monday 7 Sep is already a different set.** Seven commits touched the
entry path after Friday's open — the seat rework ("the seat goes to
whoever is alive now", 5 Sep 07:45), MOVE_DIED, the takeover veto, and
the standing-order gate. When comparing Monday to Friday, say which
rule set produced each; do not present them as one record.

**How to apply:** before quoting "the rules", check the session's
commit. `git log --format=%h --until="<date> 09:15" -1` gives what
actually ran. See [[rules-are-provisional-not-permanent]] and
[[never-mix-old-data-with-new-rules]].
