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
