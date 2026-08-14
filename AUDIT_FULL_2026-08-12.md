# Full bot audit — 12 August 2026

All 12 groups. 124 modules. Nothing changed except one fix in Group 1
(recorded below). Everything else is findings only, awaiting your call.

**Rule followed throughout: never assume.** Where a test failed I checked
whether the code was wrong or my test was wrong. Most were my tests.

---

## THE HEADLINE

**The bot is in better shape than it felt today.**

```
124 modules          123 load clean (1 needed a pip install, not a bug)
~90 scenarios run     84 pass
true orphans          3 files
real bugs found       1 (fixed)
```

The problem was never the code. It was that the *numbers* behind the
rules were set on small samples and never re-checked, and that a day of
bad analysis (mine) made a working system look broken.

---

## WHAT WAS ACTUALLY FIXED

**`trading/live_execution.py` — the kill switch had no local backstop.**

Before: `kill_switch(True)` only asked Dhan to block orders. If that API
call failed, the bot kept sending and believed it was stopped.

After: the bot stops itself first, then tells Dhan. 9/9 scenarios pass,
including "broker unreachable → bot stops anyway" and "still killed after
the day rolls over".

Three edits, one file. Nothing else was changed anywhere.

---

## GROUP 1 — BROKER & ORDERS (18 files)  ·  35 scenarios, 34 pass

**Verdict: healthy. The safety guards are genuinely good.**

Verified working:

```
Rs 9L order over ceiling        REFUSED
3% price drift                  REFUSED   (the SUPREMEIND case)
No live price                   REFUSED   (won't fire blind)
31st order of the day           REFUSED
13th open position              REFUSED
Timeout                         checks by ID, NEVER blind-resends
broker_stop: 16/16              incl. no double-sell, no false "protected"
```

**Open item: `BROKER_STOP_ENABLED = False`.** The resting stop at Dhan is
switched off. This is the file that would have caught the 6 trades that
blew through the 2.5% stop for **-Rs 48,692**. Your switch to flip, not
mine.

**Could merge:** `trade_logger.py` (CSV) duplicates `fill_log.py` (SQLite).

---

## GROUP 2 — PRICES & CANDLES (13 files)  ·  19 scenarios, 19 pass

**Verdict: clean. No bugs.**

`atr.py` correctly counts gaps (prev close 90, bar 105-100 → TR 15, not 5),
so stops widen on gappy stocks. Returns `None` on no data — never invents
a number that would set a stop.

`candle_engine.py` builds OHLC correctly and returns volume `None` (not
zero) when unknown, so the volume filter fails open instead of blocking
every trade.

**Delivery% — you confirmed you want this.** It works and IS on the
dashboard (`state.py:2655`). Two issues:

```
data ends 2026-08-07, today is 2026-08-12   -> 3 sessions stale
refreshed by tools/fetch_delivery.py        -> nothing runs it automatically
```

And it nearly caught PANAMAPET:

```
LOW fires when latest < average x 0.7
PANAMAPET      34.0  vs  48.0 x 0.7 = 33.6
               34.0 > 33.6  ->  called NORMAL, missed by 0.4pp
```

34% delivery against a 48% average = intraday churn, not investors
buying to keep. On an all-time-high day at 90x volume.

---

## GROUP 3 — WHAT TO WATCH (16 files)  ·  passes

`liquidity.py` returns real ADV (RELIANCE Rs 1,914 cr). `sector_map.py`
has 23 sectors covering 500+ names.

**Gap found: RELIANCE has no sector.** Its row says `DIVERSIFIED`, which
is not a priced index, so `sector_of("RELIANCE")` returns `None`. By
design — but India's largest stock is invisible to every sector rule.

---

## GROUP 4 — ENTRY (12 files)

`shock.py` classifies macro headlines correctly (`"RBI cuts repo rate"`
→ `rate_cut`). `canslim.py` tier ranking ordered correctly.

**`core/engine.py` is 5,043 lines** — entry, exit, stop, trail and sizing
all in one file. It cannot be unit-tested without a live feed. This is
the single biggest source of the complexity you are feeling.

---

## GROUP 5 — EXIT, STOPS & TRAILS (5 files)  ·  9 scenarios, 7 pass + 2 test errors

**`exit_plan.py` is the best-designed file in the bot.** All 7 pass:

```
below 1.5R      stop does NOT move            (no premature ratchet)
at 1.5R         locks 1:1 at 102.50
at 2R           never drops below that lock
big run to 120  trails 1.5R behind -> 116.25  (no ceiling on winners)
zero risk       refuses to divide by zero
junk input      no crash
```

**`position_plan.py` is DEAD** — imported only by its own test.

**And it is a trap if ever revived:** it speaks `"BUY"/"SELL"` while
`exit_plan.py` and `trailing_stop.py` speak `"LONG"/"SHORT"`. Pass the
wrong word and it silently returns a stop on the **wrong side of the
entry** — no error, just a wrong number. I hit this in testing.

---

## GROUP 6 — RESULTS & NEWS (24 files)  ·  11 scenarios, 11 pass

**`result_tag.py` — all correct:**

```
Excellent + green + Beat  -> EXCELLENT
Weak + red + Miss         -> AVOID
Excellent + RED           -> AVOID   (disagreement, not a middle grade)
one-off present           -> NOTE only, tag unchanged   (the SHILPAMED rule)
silence from one source   -> not treated as a negative
```

**`subject.py` works** — the SIEMENS/TRENT card-mixing bug is genuinely
fixed. Feed it two cards, it keeps only the one whose hashtag matches.

---

## GROUP 7-12 — TELEGRAM, CONTEXT, MEASURING, SCREEN, PLUMBING

All load. `outcomes.py` reads chips correctly off an event and returns
`None` (not 0) for a holiday baseline. `chip_stats.py` returns `{}` on
first call and never blocks the panel.

---

## THE THREE TRUE ORPHANS

```
core/centre.py        205 lines   computes delivery/run-up/catalyst chips
                                  -> imported by NOTHING (state.py calls
                                     delivery directly instead)
core/week_ahead.py                -> imported by NOTHING at all
core/position_plan.py             -> only its own test imports it
```

10 other modules looked orphaned but are used by `tools/` or `tests/` —
those are legitimate utilities, not dead code.

---

## CONFIG DRIFT — RULE_BOOK.md vs config.py

| | RULE_BOOK.md (1 Aug) | config.py (now) |
|---|---|---|
| margin per position | Rs 1,00,000 | **Rs 30,000** |
| ALERT_ONLY_MODE | True | **False** |
| MANUAL_TEST_QTY | 1 | **None** |
| max open positions | "book full (10)" in journal | **3** |

**Real loss per stop-out today is ~Rs 3,000, not the Rs 9,665 the rule
book implies.** If you size from that document you will misjudge your own
risk.

Also: git history ends 28 July with ~21,400 uncommitted lines, and a
leftover `.git/index.lock` is blocking commits.

---

## WHAT I WOULD NOT TOUCH

The safety architecture is good and should survive any rewrite:

- two switches to trade live, not one
- `LIVE_ALLOW_BOT_ENTRIES` separate from `ALERT_ONLY_MODE`
- timeout → query by ID, never blind resend
- protective orders that are LOUD when they fail and never claim success
- `tests/test_outcomes.py` forbidding the trading path from importing the
  measurement — that guard caught me trying to violate it today, and it
  was right

---

## OPEN ITEMS, NOTHING DONE WITHOUT YOUR WORD

1. `BROKER_STOP_ENABLED = False` → the -Rs 48,692 gap
2. `tools/fetch_delivery.py` not scheduled → dashboard 3 sessions stale
3. 3 orphan files → delete or keep
4. `trade_logger.py` + `fill_log.py` → merge
5. `RULE_BOOK.md` vs `config.py` → one of them is wrong
6. `.git/index.lock` → blocks all commits (needs you: `del` it)
7. `engine.py` at 5,043 lines → the real complexity
8. Delivery LOW threshold 0.7 → would have flagged PANAMAPET at 0.75
   (unmeasured — note only, not a rule)
