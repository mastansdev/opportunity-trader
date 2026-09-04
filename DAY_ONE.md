# Day One — the first destination reached

**4 September 2026.** The first session where the bot traded to a rule
set the operator recognised as his own, and made money doing it.

    "u must save todays bot rules & working mechanism as this day -1
     which worked in our favour with all rules we applied. make sure
     this as 1st destination reached point. later we will keep on
     moving in bot journey & refining more simpler bot with more
     accurate entry & exits."

This file is the marker. It records what the bot WAS on the day it
first worked, so that every later change can be measured against a
known point rather than against memory. Nothing here is aspirational —
every number was read out of the running code on the afternoon of
4 September.

---

## What the day did

    PAPER, Rs 5,00,000 purse, 10 seats

    closed          16 trades      12 won, 4 lost
    gross          +Rs 32,272
    charges          Rs 1,391      at Rs 93 a round trip
    NET            +Rs 30,881

Hold times ran 15 to 129 minutes. **One** trade closed at exactly
fifteen minutes, against five the day before — the exit fix landing.
The two largest were NIACL held 124 minutes for +Rs 14,577 and PURVA
held 23 minutes for +Rs 10,099. Both would have been cut at minute
fifteen under 3 September's rules.

---

## The rules, as they stood

### Candidacy — how a stock reaches the board

    MIN_MOVE_FROM_PREV_CLOSE_PCT      3.0     from its OWN previous close
    MIN_VOLUME_RATIO                  2.5     against its OWN normal pace
    MIN_LIQUIDITY_CR                  2.0     it must be exitable at his size
    SURGE_IS_A_REASON                 True
    SURGE_REASON_MIN_RATIO           10.0     a surge stands in for a card
    UNEXPLAINED_MIN_VOLUME_RATIO      5.0

A stock needs a REASON — news, a filing, results, an order, a concall
— or a volume surge large enough to be one. Nothing enters off a
gainers list.

### Liveness — is the move still happening

    MAX_OFF_EXTREME_PCT               3.0     more than 3% off its high is dead
    MIN_RECENT_PCT                    0.15    less than this in ten minutes is dead
    COILING_AT_HIGH_PCT               1.0     ...unless it is at its own high,
                                              which is a coil, not a stall

Falling is dead everywhere. Flat is dead only away from the high.
None means "cannot say" and never refuses a trade.

### Size

    MTF_MARGIN_PER_POSITION_RS   50,000       his own money, per trade
    MTF_LEVERAGE                      4.0
    MTF_FALLBACK_MARGIN_PCT           1.0     no MTF -> Rs 50,000 of stock, no more
    PAPER_STARTING_CAPITAL      5,00,000      fixed; Dhan is not asked in paper

Leverage is asked of Dhan per stock at the moment of buying. On
4 September that ran from 26.1% margin (SWIGGY, 3.8x) to 60.7%
(BALAMINES, 1.7x), so positions ranged Rs 82,417 to Rs 1,91,547 while
his own money committed was Rs 50,000 on every single one.

### Exit

    FIXED_STOP_PCT                    3.0
    PEAK_TRAIL_PCT                    0.025   2.5% from the peak since entry
    BUYING_DRIED_UP_MIN_OFF_PEAK_PCT  1.0     flow may not close a winner
                                              sitting at its own high
    BUYING_CHECK_MIN_MINUTES           15     a floor on the reading, NOT a timer
    ENABLE_PEAK_TRAIL                True
    ENABLE_NO_PROGRESS_EXIT          False    measured off: it cut BRIGADE at
                                              +0.12% and lost ~Rs 7,255

### Guardrails

    DAILY_MAX_LOSS_RS              12,000     LIVE only
    DAILY_LOSS_CAP_APPLIES_IN_PAPER  False    a paper day runs whole
    STAGED_NO_ENTRY_AFTER           15:15
    STAGED_POSITION_LIMITS   [('15:29', 10)]
    ENTRY_DECISION_INTERVAL_SECONDS   1.0

### The two lanes

The rebuild answers WHO — news, filings, results, surges. Slow is
acceptable; a company does not win an order twice in a minute.

The tick worker answers WHEN — every second, on prices straight off
the feed, re-pricing each candidate and re-asking liveness before the
gates read it. Exits run on every tick with no beat at all.

### The switch

    ON  -> real orders, and the REAL Dhan balance
    OFF -> paper orders, and the fixed paper purse

Two states, no third. ON refuses to arm when the broker cannot be
reached, and drops to PAPER rather than to watching.

---

## What was still wrong on this day

Recorded so the next milestone can be measured honestly against it.

**Volume unmeasured.** 54 of 100 board rows carried no volume figure,
including every one of the day's biggest movers. Both the 2.5% gate
and the 10x surge rule were blind to them. DOLPHIN ran to its upper
circuit and was never once a candidate — 116 pool misses, all saying
"volume unmeasured".

**The surge is read as a level, not a jump.** RESPONIND's volume went
from 161 shares a minute to 34,906 at 10:07 and the price stepped
152 -> 157. The bot bought at 13:26 at 172.11, three hours and
nineteen minutes later, 48 paise below the top of the whole move, and
lost Rs 4,833. Replayed on the same rules: entering at 10:07 makes
+Rs 8,170; at 10:49, -Rs 2,054; at 11:24, -Rs 2,657. Only the ignition
candle pays.

**The plan is stale.** Stop and quantity are built during the rebuild
and can be five minutes old when the order goes in at a one-second
price. SBCL got a stop ABOVE its entry and was closed one second after
being opened, for -Rs 481.

**The paper fill can invent a price.** INOXWIND filled at 76.57 when
the day's high was 76.50. The slippage model applies a percentage
rather than moving to a price that exists, and treats "turnover
unknown at 09:16" as "thin stock".

**The board is 50 to 344 seconds behind.** `ranked` costs 26-94s and
`shortlist` 15-21s; everything else together is under 5s. Entries no
longer read it, but the screen does.

**No minimum quality.** Only the 2.5x floor. MANYAVAR got a seat at
2.9x and INTELLECT at 3.4x. Every candidate below 6x on 4 September
was flat or losing; every one above 26x was positive but for DIFFNKG.

**Divergence is measured and gates nothing.** DOLPHIN made twenty new
highs after 09:19 with the buying not following and delta -27,242.

---

*Next: surge detection off `order_flow.flow_minutes` — the per-minute
volume the bot already records for all 1,455 symbols — so the jump is
caught when it happens rather than described hours later.*
