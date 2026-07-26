# Post-Monday To-Do — known gaps we are shipping anyway

Written 2026-07-25, before the first live session with the full package.
Everything here is **known-imperfect and deliberately not fixed before
Monday**, because untested changes stacked on untested changes is how
the last bot died. Work through this after market hours.

Ordered by how much it actually matters.

---

## 🔴 A. Things I got WRONG

### A1. The 14:00 entry cutoff — ✅ FIXED 2026-07-25
`STAGED_NO_ENTRY_AFTER` was `14:00`, stopping new entries 75 minutes
before square-off. **You had explicitly told me to remove the afternoon
cutoff** — "cutting off entries at 2pm was throwing away exactly the
afternoon data we need to study" — and I reintroduced one without
flagging it.

**Evidence it was wrong:** in Friday's replay the two BEST trades of the
day were entered at **13:50 (IPCALAB +₹1,346)** and **13:51
(ZFCVINDIA +₹2,193)**.

**Now: entries run to 15:00, hard square-off stays 15:15.** Both
`STAGED_NO_ENTRY_AFTER` and the dormant `LAST_ENTRY_TIME` set to 15:00.
Open item: *does* late-day entry quality decay? Measure after 5 sessions
by bucketing win rate by entry hour — don't guess a cutoff again.

### A2. T2T stocks in the universe — ✅ FIXED 2026-07-25
Now handled automatically by the morning run (`SUBSCRIBE` column, see
`MORNING_ROUTINE.md`). **7** symbols are genuinely T2T and are marked
NO: DBREALTY, JAIBALAJI, KRN, MTARTECH, QPOWER, **STLTECH**, TRIVENI.

**And I had one of them wrong.** I previously told you SUDEEPPHRM was
T2T as well. It isn't. It appears **twice** in the bhavcopy — once in
series `BL` (the block-deal window) and once in `EQ`. The old tool
judged whichever row it read first. `BL` is a block deal, not
trade-to-trade, and SUDEEPPHRM is perfectly tradeable. The new code
always prefers the EQ row, and there's a regression test pinning this
exact case.

So the real count is **7, not 8** — and STLTECH is the only one of the
two names in the trade log that was actually an invalid trade.

---

## 🟠 B. Rules shipping WITHOUT evidence

Each of these is a guess. None is validated. All are the first things to
test once we have ~5 clean sessions.

| Rule | Value | Status |
|---|---|---|
| **"Still trending"** (top 35% of day range) | 0.65 | **CONTRADICTED** on 2026-07-24 — but that was a reversal day, the worst case for it. See §D. |
| Relative-strength band | 0.4%–5.0% | widened from a band fitted to corrupted data. Guess. |
| Sector gate | top 8 of ~90 | never measured |
| Staged limits | 3 / 6 / 10 | reasoning only |
| No-progress exit | 30 min / +0.5R | reasoning only |
| Early-momentum bar | RS ≥ 1.0%, max 2/day | reasoning only |
| Blow-off guard | 12% intraday | arbitrary |
| Rotation edge | 0.4% | arbitrary |

---

## 🟡 C. Built but not finished

- **Universe not trimmed.** The tool proposes ~206 removals and ~247
  additions. Nothing applied yet. Trimming would cut ~25% of the live
  tick load, most of it at the 09:15 burst.
- **Railway deploy** — news engine still only runs when your PC is on.
- **Gap size is logged (`[GAP]`) but unused.** Should a big gap mean a
  smaller position? Unknown — that's what the logging is for.
- **Charges eat ~78% of gross profit.** Not solved, only mitigated by
  trading less. Needs either fewer/larger trades or a cheaper plan.

---

## 🔵 D. The big open question

**Does riding strength work, or does fading it work?**

2026-07-24, measured against the market baseline (median stock rose
+1.13% after 11:00 — it was a bounce-back day):

```
LONG:  up 2%+ and near the high    n= 9   −0.55% vs market  (underperformed)
SHORT: down 2%+ and near the low   n=53   +0.35% vs market  (rose — bad for shorts)
```

Both sides **mean-reverted**. But that was a single reversal day, which
is exactly when continuation should fail — so it neither proves nor
disproves the rule. The short-side sample (53) is far more trustworthy
than the long side (9).

**This is the single most important thing to settle**, and it needs
5+ clean sessions of mixed character.

---

## ⚪ E. Never built (from the architecture deck)

1. ~~**Daily / higher-timeframe trend**~~ — **data layer BUILT
   2026-07-25** (`core/daily_store.py` + `core/trend_structure.py`,
   see `DAILY_TREND.md`). The bot can now see the last 7 days'
   higher-high / higher-low structure. **Still not wired as a gate** —
   it records only, until we can measure whether STRONG_UP trades beat
   RANGE trades. Backfill with `py tools/build_daily_history.py 30`.
2. **Entry on the retest** instead of the breakout candle.
3. **Relative strength vs its OWN sector** (we have vs market only).
4. **Regime detection** (ADX + ATR percentile) — designed in
   `REGIME_NOTES.md`, zero code.
5. **Position IQ** — a position that re-thinks itself when news breaks
   mid-trade (`MONITOR → NEWS → RECALCULATE` from the deck).
5b. **Narrow the earnings block using the pulse.** Data now exists
   (`CALENDAR_AND_RESULTS.md`): of 107 names with a reliable reporting
   time, **61% report after 15:15** — so the whole-day block costs us
   those sessions for nothing. But 39% report DURING the session, some
   as early as 11:30 (CARTRADE) and 12:09 (DIVISLAB). Change to "trade
   normally, stop 30 min before the usual time" only after watching a
   couple of real reporting days.
6. **News decay / story clustering.**
7. **Per-sector capital cap.**
8. **Trade log:** market-time timestamps + per-exit P&L column.
9. **Telegram alerts.**
10. Wider evidence inputs (Govt, Brokerage, Guidance, Commodities,
    Macro) — mostly aspirational for intraday; low priority.

---

## 🟤 G. Decide the block-deal question with evidence (2026-07-26)

`core/deal_flow.py` + `tools/deals_report.py` were deleted, then
restored on the operator's call. They currently do NOTHING — no
decision, no display. They are on probation.

**The one part worth testing:** NSE's block-deal window runs
**08:45–09:00, before the market opens**. A large block crossed at a
discount to yesterday's close very often precedes a gap down. Unlike
RSS and unlike bulk-deal/short-selling data (both of which land after
the close), this arrives BEFORE you need it.

**The test, Monday 09:05:**

```
py tools/deals_report.py
```

Look at the "TODAY's block window" section, then check what those names
actually did at the open.

**Decide on the evidence:**

- Nothing in the window, or names that went nowhere -> delete both files
  for good. Two sessions of this is enough to tell.
- Real names that gapped -> it earns its place, and the next step is
  wiring it into the morning run rather than a manual command.

Recording this because the same trap caught us three times today: news
fan-out, keyword blocking, and the events strip all *sounded* useful and
all failed on contact with real output. This one gets measured before it
gets defended.

---

## 🟢 H. WHAT WE COULD STILL DO BETTER — the Monday-evening list

Everything above is a known gap. This is the ORDER to work through them
after Monday's close, worst-first, with what settles each one.

### H1. The bot still cannot see YESTERDAY when it decides
The single biggest gap. `core/trend_structure.py` now knows every
stock's 7-day higher-high/higher-low shape -- and it gates NOTHING. This
is why the bot bought SRF long after a 10% two-day fall: the session
starts fresh at 09:15 and the previous week may as well not exist.

**Settles it:** 5 clean sessions, then bucket win rate by the structure
label the stock had that morning. If STRONG_UP longs beat RANGE longs,
wire it as a gate -- one line. If not, delete the module.

**Right now**, for context: 370 of 544 stocks (68%) are in daily
downtrends, only 47 trending up. Monday's long side is thin by
construction.

> **2026-07-26 -- that plan had a hole, and it was mine.**
> `core/trend_structure.py`'s own docstring said the label was
> *"recorded against every trade the bot takes"*. It was not. The only
> file that imported the module was `tools/trend_report.py` -- nothing
> in `core/engine.py`, nothing in `dashboard/`. Five sessions from now
> there would have been **nothing to bucket**, and I would have found
> that out at the moment we sat down to answer the question.
>
> Closed WITHOUT touching `core/engine.py`, because the label never
> needed to be recorded live: it is a pure function of daily bars we
> already store. Given a trade on 07-24 in PARAS, the structure the bot
> saw at 09:15 is exactly
> `analyse(daily_store.history("PARAS", days=8, upto="2026-07-23"))`.
>
> ```
> py tools/structure_performance.py
> ```
>
> The `upto` cutoff is the whole thing: include the trade day's own bar
> and the label "knows" how the day ended. That is lookahead, it always
> flatters the answer, and there is a test pinning it
> (`test_label_uses_only_bars_before_the_trade`).
>
> Also now VISIBLE: a Daily Trend panel on the trading dashboard --
> universe split by structure, every open position against the shape it
> was entered into, and the "just broke" list. **Read-only. It gates
> nothing**, and `test_daily_trend_never_gates_anything` fails if anyone
> wires it in without reading why first.
>
> Live numbers from the 30 days stored, as of 2026-07-24:
> `STRONG_DOWN 237 · DOWNTREND 133 · RANGE 127 · UPTREND 37 ·
> STRONG_UP 10`, and **102 names broke structure on the last bar**.
> Gating longs to STRONG_UP would cut the long side to 10 of 544.

### H1b. The replay bench is not missing logic. It is missing MARKET.
`backtest/monday_replay.py` already runs the real rules -- top-20
movers, top-8 sectors, RS band, staged seats, rotation, ATR stops,
charges -- over **one** recorded session, and that one restart-muddied.
Every question below is unanswerable for that single reason.

Dhan already serves the fix, and we already hold the credentials:
1-minute candles, **five years back**, every active instrument, 90 days
per request, 5 requests/second, 100,000/day.

```
py tools/fetch_history.py            # 62 sessions x 545 symbols, ~545 requests
py backtest/monday_replay.py         # 62 sessions instead of 1
```

| Pull | Requests | Wall clock |
|---|---|---|
| 62 sessions x 545 | 545 | ~2 min |
| 1 year x 545 | 2,725 | ~10 min |
| 5 years x 545 | ~13,600 | ~45 min |

The API is not the constraint. Disk is: 545 x 375 minutes x 62 sessions
is ~12.7 million rows (~1.2 GB). `CandleStore.add_many()` was issuing
one `execute()` per row -- fine for the live recorder, most of a day for
this -- and is now chunked `executemany` at ~97,000 rows/sec.

**Two things to check before believing ANY result from this data:**

1. **Splits.** It is undocumented whether Dhan's history is
   split-adjusted. If not, a 1:10 reads as -90% and invents an ORB gap
   that never happened. Every day-on-day close move over 25% is printed
   at the end of the run and cross-checked against the 141 corporate
   actions in `core/stock_memory.py`. **Anything marked UNEXPLAINED
   means that window is not trustworthy.**
2. **Survivorship.** `master_stocks.csv` is TODAY'S universe. Two years
   of it excludes everything delisted since and includes names that
   only became liquid recently. That biases results upward. State it in
   any conclusion that comes out of this data.

### H2. Is the whole direction backwards?
On 2026-07-24, against a +1.13% market baseline:

```
LONG:  up 2%+ and near the high    n= 9   -0.55% vs market
SHORT: down 2%+ and near the low   n=53   +0.35% vs market
```

Both mean-reverted. One reversal day proves nothing -- but if this holds
over five sessions the bot is trading the wrong way and no amount of
gate-tuning fixes that. **Everything else is decoration until this is
settled.**

### H3. Eight rules running on reasoning, not evidence
RS band 0.4-5%, sector top-8, staged 3/6/10, no-progress 30 min/0.5R,
early-momentum RS>=1.0%, blow-off 12%, rotation edge 0.4%,
still-trending 0.65. Each is my guess. Test one at a time against
recorded sessions -- never two together, or neither result means
anything.

> **2026-07-26 -- you can now SEE which of them is binding.**
> Operator: *"we can judge our bot trading descison on this i guess and
> improve the gates which are used by bot"*.
>
> `core/engine.py` declines candidates at **seventeen** gates and
> recorded **none** of them. A threshold set too tight has exactly one
> symptom -- trades that never happened -- and those were invisible.
>
> `core/gate_log.py` + the **Why No Trade** panel now show the funnel:
> candidates seen, which gate each one died at, survivors, and the
> near-misses that passed every selection rule and died on mechanics.
>
> **The counting rule is the design.** These gates re-fire on every
> candle close while their condition holds -- a name failing the RS
> band from 09:31 to 15:15 would log ~350 rejections. So it counts
> CANDIDATES, at the **deepest** gate each one ever reached, not
> events. Raw firings are kept in a separate column for context.
>
> **Two things not to misread:**
> 1. A *candidate* is a fresh ORB cross, not every stock. 40 candidates
>    out of 545 names does not mean 505 were rejected -- they never
>    broke out to be judged.
> 2. The gate killing the most is the first place to LOOK, not
>    automatically the one to loosen. The top gate is usually doing its
>    job.
>
> It has no vote. `test_logging_does_not_change_a_single_decision` runs
> an identical session with the log on and off and asserts every trade
> matches; `ENABLE_GATE_LOG = False` makes every call a no-op.

### H4. Charges eat ~78% of gross profit
Not solved, only mitigated by trading less. ~Rs 117 a round trip against
a best-bucket expectancy of ~Rs 136. **The edge is currently thinner
than the fee.** Either the per-trade edge grows or the trade count falls
further -- there is no third option.

### H5. Two things on probation
- **Block-deal window** -- see section G. Test at 09:05 Monday.
- **Earnings pulse timing** -- 61% of names report AFTER 15:15, so the
  whole-day block costs those sessions for nothing. Narrow it only after
  watching real reporting days.

### H6. Never built, in the order they are worth building
1. Entry on the RETEST rather than the breakout candle -- better R:R
   with no predictive skill needed.
2. Relative strength vs its OWN sector, not just the market.
3. Regime detection (`REGIME_NOTES.md` -- designed, zero code).
4. Per-sector capital cap.
5. Trade log: market-time timestamps + per-exit P&L column.

### H7. Housekeeping that keeps biting
- Universe still untrimmed: ~206 removals / ~247 additions proposed,
  none applied. Would cut ~25% of the 09:15 tick load.
- `NEW_STOCKS.md` classification queue -- new listings sit at
  SUBSCRIBE=NO until their sector is filled in.
- `git push` -- commits are ahead of origin.

### H8. The process lesson, worth more than any item above
Three things today looked useful and failed on contact with real output:
news fan-out, keyword blocking, the events strip. A fourth (the earnings
parser) took four attempts. Every one of them was caught by the operator
reading actual output, not by me reasoning about it.

**So: measure before defending, and inspect real rows before writing the
parser.** Nothing on this list gets wired as a gate on the strength of a
clean-looking table.

---

## 🟣 F. Does the bot use the FULL session? (asked 2026-07-25)

Short answer: **now yes on time, but no on trade count.**

**Time coverage — fixed.** Entries now run 09:20 → 15:00 (was 14:00).
That is 5h40m of a 6h session, with the last 15 minutes reserved so a
new position isn't opened straight into the square-off.

**Trade count — 8 to 20 is a real constraint, and it is deliberate:**

| What limits it | Effect |
|---|---|
| Top-20 movers only | ~750 → ~40 candidates |
| Top-8 sectors only | ~40 → ~15 |
| RS band 0.4–5% | drops the extended ones |
| One attempt per symbol/direction | no CHENNPETRO ×9 |
| 3 / 6 / 10 staged seats | no 09:34 book dump |

At ~₹117 charges per round trip, **8–20 trades costs ₹936–₹2,340/day**.
The old 27-trade day cost ₹3,159 and most of it was the same few names
re-entered. Fewer, better-selected trades is the point.

**Does 8–20 cover all the findings?** Yes — every finding is a *filter*,
and filters reduce count by design. The findings we CANNOT yet judge at
this volume:

- **Rotation** needs a full book to trigger. If we only reach 6–8
  positions, rotation never fires and stays untested.
- **The no-progress exit** needs enough trades to show whether 30 min
  is the right window.
- **Late-session entries** — now unblocked, so Monday gives us the first
  real 14:00–15:00 sample we've ever had.

**What to check Monday evening:** entries per hour, peak concurrent
positions, and whether rotation fired at all. If peak concurrency never
hits 10, the staged caps aren't binding and the gates upstream are.

---

## Suggested order after Monday

1. **A2** (T2T removal — cheap, no risk; A1 already done)
2. Apply the universe trim
3. Collect 5 clean sessions
4. **Settle §D** with real data
5. Bucket win rate by **entry hour** — settle the late-entry question
   with numbers instead of another guessed cutoff
6. Then **E1 (daily trend)** and **E2 (retest entry)** — the two with
   the best reasoning behind them
