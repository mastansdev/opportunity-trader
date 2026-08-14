# Opportunity Trader — how the bot must work

Written 12 August 2026, from measured data only. Every number here has an
`n` behind it or comes straight from `config.py`. Nothing is invented.

Hand this to any developer or AI. It is the whole brief.

---

## 0 · THE ONE HARD RULE

**Never assume. Keep it simple. This is a trading bot, not a rocket.**

If a number has no `n`, it is an opinion. Say so, draw it, and count it —
but do not let it change a decision until it has earned that.

---

## 1 · WHAT THE BOT IS

**An evidence panel with a BUY button.**

It reads Telegram pro channels, NSE/BSE filings and live prices, puts the
reason next to the stock, and waits. It does not decide for you.

```
LIVE_ALLOW_BOT_ENTRIES = False    <- the bot places NO entries of its own
                                     every order is a click you make
```

It is not autonomous and should not be until its rules have an `n`.

---

## 2 · MONEY — THE NUMBERS THAT ARE ACTUALLY LIVE

```
MTF_MARGIN_PER_POSITION_RS   30,000     your own money per position
MTF_LEVERAGE                 4.0        -> ~Rs 1,20,000 of stock
HARD_STOP_FROM_ENTRY_PCT     0.025      2.5% from entry
  a stop-out therefore costs ~Rs 3,000
FIXED_TARGET_RS              2,500
DAILY_MAX_LOSS_RS            12,000     = 4 stop-outs, then stop for the day
DAILY_PROFIT_TARGET_RS       75,000
MAX_OPEN_POSITIONS           3
```

**`RULE_BOOK.md` says Rs 1,00,000 per position. It is out of date.**
The live number is Rs 30,000. Do not size from that document.

---

## 3 · THE OVERNIGHT HOLE — FIX THIS FIRST

```
FORCE_SQUARE_OFF_AT_CLOSE = False    the bot HOLDS overnight on MTF
BROKER_STOP_ENABLED       = False    no resting stop sits at Dhan
```

Together those mean: **between 15:30 and 09:15 an open position has no
stop anywhere.** Not at Dhan, not in the bot if the process is not
running. config.py says this itself:

> "An MTF position gaps against you with no stop able to fire between
> 15:30 and 09:15."

This is not theory. Six trades blew past the 2.5% stop for **-Rs 48,692**:

```
CORONA      -7.48%     DEEPAKFERT  -4.80%     YASHO  -5.19%
DEEPAKNTR   -3.51%     DEEPAKFERT  -4.81%     JKLAKSHMI -2.82%
```

**Required: either turn `BROKER_STOP_ENABLED = True`, or set
`FORCE_SQUARE_OFF_AT_CLOSE = True`. Holding overnight with neither is the
single largest risk in the system.**

---

## 4 · READING THE TELEGRAM CHIPS

Four channels publish nine ratings per company. The bot collapses them to
**one word**: EXCELLENT, GOOD or AVOID.

### Step 1 — only cards about THIS stock

`core/subject.py` believes the card's own `#HASHTAG`. A message that
merely mentions a symbol is not a card about it.

> Measured: SIEMENS's chip was built from 22 messages, four of them about
> ENRIN, quoting TRENT's numbers inside an engineering company's verdict.

**Rule: no hashtag match, no card. A blank chip beats a wrong one.**

### Step 2 — the four things read off the card

```
Pulse      Excellent / Great / Good / OK / Weak
Dot        green / amber / red        (Earnings 360)
Verdict    Beat / Met / Mixed / Miss
One-off    "one-off", "exceptional item", "tax credit"
```

### Step 3 — the word

```
AVOID      anything weak, anything red, anything missed
AVOID      two sources DISAGREE          <- not a middle grade
EXCELLENT  strongest reading AND nothing contradicting it
GOOD       clearly positive, or positive with one source silent
```

**A silent source is not a negative one.**

### Step 4 — the one-off is a NOTE, never the word

> SHILPAMED, 5 August: marked SKIP on a one-off flag. It closed +11.96%.

The publisher's forensic rating answers *"will this profit repeat next
quarter?"* — an investor's question. You hold 1–3 days. It goes on the
row as a caution about holding overnight. **It never changes the tag.**

---

## 5 · WHAT EACH CHIP IS WORTH — MEASURED

Edge = the stock's move minus the market's median that session.
"w/stop" applies the real 2.5% stop, which is how the book actually pays.

```
chip                     n      median    w/stop    Rs/trade   tail%
PULSE EXCELLENT        143      +2.29     +3.84      +4,611      41
CLEAN brief            239      +0.71     +1.51      +1,812      50
AI POSITIVE            662      +0.30     +1.45      +1,738      60
PULSE GOOD             734      +0.32     +1.24      +1,483      52
ONE-OFF                109      -0.02     +0.54        +650      59
PULSE WEAK             593      -0.26     +0.15        +176      61
WATCH gauge            175      -0.54     -0.13        -159      60
```

**Three things this table says:**

1. **`PULSE EXCELLENT` is the one real signal.** Best edge, 79.7% hit
   rate, and the *lowest* tail dependence (41%) — it is not one lucky
   outlier.
2. **`ONE-OFF` is no longer a warning.** It was -1.61% on n=25 in July.
   On n=109 it is a coin flip. Any rule resting on it must be retired.
3. **`WATCH gauge` is the only genuinely negative chip in the system**,
   and nothing currently treats it as one.

**`DOUBLE`** — both EXCELLENT and CLEAN on one stock, from two different
publishers: **n=22, +3.04%, up 77%.** The strongest thing on the screen.

---

## 6 · WHEN TO ENTER

All of these must be true:

```
1. tag is EXCELLENT or GOOD          (from section 4)
2. a written reason exists           no mechanism, no trade
3. price is breaking out             the tape agrees with the card
4. fewer than 3 positions open
5. day's loss is under Rs 12,000
6. the stock is liquid               core/liquidity.py
7. results are already OUT           never buy into a pending print
```

**Rule 7 is what saved you on PANAMAPET.** The bot refused at Rs 585.95
with `"reports today, numbers not out yet"`. You bought manually anyway.

### The staleness check — the PANAMAPET lesson

Before paying up, ask: **have peers already printed this same quarter?**

```
GANDHAR reported 23 July   margin  5.09% -> 16.24%
SAVITA  reported same week margin  6.13% -> 24.60%
PANAMA  reported 12 Aug    margin  8.50% -> 22.58%
```

Three companies buying the same input, same quarter, same tripling. By
the time the third card arrived the news was **twenty days old**.

**Show it as a chip. Do not let it block a trade** — measured, warned
names still made +0.87% on n=38. It is a *sizing* note, not a skip.

---

## 7 · WHEN TO EXIT

`core/exit_plan.py` — the best-designed rule in the bot. 7/7 tests pass.
R = the stop distance = 2.5%.

```
below 1.5R      nothing moves. the original stop stands.
at 1.5R         stop jumps to 1:1  -> a retrace now books a PROFIT
at 2R and above trail 1.5R behind the high, never below the 1:1 lock
                NO CEILING -- let a winner run
```

**Why no fixed target:** measured on 8,230 setups over 10 days, same
entry, same stop, only the exit changed —

```
close at 2R    -0.095R per trade    -780R total
trail 1.5R     +0.006R per trade     +53R total
```

Of 574 trades that reached +2R, **95% kept going**, 35% past 3R, 14% past
4R. The best trade capped at 2.0R became **11.1R** with the trail.

**The price:** on trades that DO reach target, trailing books 1.88R
instead of 2.00R and gives something back 62% of the time. That is the
cost of the 38% that run. It will feel wrong six times in ten.

### ~~The trail width bug~~ — WITHDRAWN, 12 August 2026

This section said:

> `PEAK_TRAIL_PCT = 0.025` but the average winner runs +1.9%. A trail
> wider than the typical move can never lock a profit. Measured on 64
> trail exits: **-Rs 1,728 per trade.** Replayed with a 1% trail:
> **-Rs 441.**

**The 64 are not one population.** `ENABLE_BOT_TRAILING_STOP` went
`False` on 29 July. Split on that date, from `data/trade_memory.db`:

```
trail ON   (<= 28 Jul)   n=29   avg   -643   win 24%
trail OFF  (>= 29 Jul)   n=35   avg -2,627   win 20%
```

The 35 later ones are **fixed 2.5% hard stop-outs**, not trail exits.
With the trail off, `core/engine.py`'s `_atr_entry_sizing()` sets
`stop_distance = HARD_STOP_FROM_ENTRY_PCT * entry_price` and it never
moves. They carry the `TRAILING_STOP` label because `_check_trailing_
stop()` is the method that fires the hard stop too.

So averaging them together produced -Rs 1,728 for a mechanism that has
not run for a fortnight, and **there is no trail width to fix.**

What the number actually says: since 29 July the stop is doing exactly
its job at about Rs 2,600 a time, and only 20% of stopped trades were
ever in profit. That is an **entry quality** problem, and no exit rule
can fix it.

**Item 4 in section 11's order of work is therefore void.**

---

## 8 · THE HORIZON — WHY PANAMAPET COST Rs 10,000

**The chip edge is measured from the open, or from chip time, to the
CLOSE OF THAT DAY.**

`PULSE EXCELLENT` at +2.29% is a *same-day* number. It is not a reason to
hold overnight, and it is not a thesis about the company.

You held. The bot's own rule refused the entry. Both facts are in the
logs.

---

## 9 · WHAT THE BOT MUST NEVER DO

```
- place an entry of its own while LIVE_ALLOW_BOT_ENTRIES is False
- resend an order after a timeout without querying by ID first
- report success when the broker never answered
- claim a stop is resting when the API call failed
- treat a silent source as a negative one
- let an unmeasured flag change a tag
- annualise a quarter whose margin came from price, not operations
- show a number without its n
```

---

## 10 · WHAT MUST BE ON THE DASHBOARD

```
tag                EXCELLENT / GOOD / AVOID, loud, sorted first
why                the evidence lines, in the publisher's own words
DOUBLE             when two publishers agree      n=22, +3.04%
one-off note       overnight caution, never a tag change
delivery %         "34% delivered, usual 48%"     <- churn vs conviction
                   NOTE: data is 3 sessions stale.
                   tools/fetch_delivery.py is not scheduled.
chip edge          live n and edge from /api/chip_stats
                   NOT hardcoded -- the typed-in numbers went stale in 11 days
stop + target      in RUPEES, not percent
open risk          how many stop-outs remain before Rs 12,000
```

---

## 11 · ORDER OF WORK

1. ~~**Close the overnight hole**~~ — **DONE 12 Aug.** `BROKER_STOP_ENABLED`
   is now `True`; a Forever Order rests at Dhan at the hard stop.
   `tests/test_broker_stop.py` fails the build if both overnight
   switches are ever off together again.
2. ~~Schedule `tools/fetch_delivery.py`~~ — **DONE 12 Aug.** Added as a
   `delivery` step in `tools/nightly.py`; six missed sessions backfilled.
3. Retire the `ONE-OFF` warning; it stopped earning (n=109). **Still open.**
4. ~~Re-measure the trail, then fix the width~~ — **VOID.** See section 7:
   there has been no trail since 29 July. The 64 exits were two regimes
   averaged together.
5. ~~Reconcile `RULE_BOOK.md` with `config.py`~~ — **DONE 12 Aug.**
   [BOT.md](BOT.md) is generated from `config.py` and `core/rules.py` by
   `tools/bot_doc.py`, and `tests/test_bot_doc_is_current.py` fails the
   build when a rule changes without regenerating it. The five stale
   rule documents now carry a SUPERSEDED banner.
6. Only then touch entry rules.

### Added 12 August, not in the original list

7. **The two entry lanes had two rule sets.** `core/engine.py` sized
   every breakout from `config.RISK_PER_TRADE_RS` (Rs 2,000) while
   `core/position_plan.py` sized every ranked pick from
   `core/rules.py` (Rs 1,500). Both live. This audit called the 2,000
   "legacy, sizes nothing" — it sized every engine entry from 7 August.
   Now one owner, guarded by `tests/test_rules_are_not_duplicated.py`.
8. **"No event, no trade" reached only one lane.** BOT_SPEC's own entry
   rule 2 was enforced by the ranker and never by the ORB breakout.
   Both now import `core/rules.is_a_reason()`.
   **Warning: this has no evidence behind it** — on the 134 recorded
   trades the gate would have refused the 49 that broke even and kept
   the 7 that lost. Kept on because n=7 is a coincidence and it is what
   the operator asked for. Re-measure at n=20.
9. **The learning loop still does not vote.** Three modules measure what
   happened after a signal and all three are severed from the decision.
   Now visible: `py tools/knowledge_report.py`, or the **What the bot
   knows** panel.

**Do not add a rule. Fix or retire the ones that stopped being true.**
