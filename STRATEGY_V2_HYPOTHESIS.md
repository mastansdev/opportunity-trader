# Strategy v2 — a prediction, written BEFORE the five-year test

Written 2026-07-26, after `MULTIDAY_FINDINGS.md` (61 sessions, 1,957
trades) and **before** any data older than 2026-04-28 has been pulled.

## Why this document exists

Everything in `MULTIDAY_FINDINGS.md` was found by slicing the same 61
sessions it was then measured on — by direction, exit reason, entry
hour, relative-strength band, and daily structure. That is five looks
at one dataset. Search a dataset hard enough and it will always hand
you a rule that works on it.

The only way to know whether any of it is real is to **state the rules
now, in advance, and then test them on years nobody has looked at.**
A rule written after seeing the answer is a description. A rule written
before is a prediction, and a prediction can be wrong — which is what
makes it worth anything.

So this file is locked before the 2023–2025 pull. Whatever it gets
wrong stays on the record.

---

## The thesis, in one sentence

**Buy intraday strength in stocks that have been weak for several days;
never chase a stock already extended in the direction it is already
going.**

Daily-timeframe mean reversion, intraday-timeframe momentum. This is
close to the opposite of the current "still trending" rule.

## The rules

Three changes to entry, all with a mechanism, none of them a tuned
number:

1. **LONG only.** Shorts were 1,035 trades for Rs 2,450 of gross —
   indistinguishable from zero, and Rs 121,253 of charges to collect it.
2. **Reject both daily extremes.** No entry if the stock's 7-day
   structure is STRONG_UP or STRONG_DOWN. Those two buckets lost
   Rs 32 and Rs 150 per trade respectively. Everything between them
   (UPTREND / RANGE / DOWNTREND) was positive.
3. **No rotation.** `ROTATE_OUT` produced NEGATIVE gross before charges
   across 293 trades. It is a rule we invented, not a market fact.

And one change to exits, which is an experiment rather than a setting:

4. **Let winners run.** 87 trades above +3R produced Rs 324,603 of
   gross — five times the system's entire gross — but only 8 trades of
   1,957 ever reached the closing bell. Widen `ATR_TRAIL_MULTIPLIER`
   and lengthen or remove the no-progress timer. The sweep decides the
   values; this document only predicts the DIRECTION: looser exits
   should raise net, because the profit is in a tail the current exits
   truncate.

Deliberately NOT included, because they are fitted thresholds with no
independent mechanism: the 13:00 hour effect, the RS >= 2.5% floor, and
the DOWNTREND-only variant. They may well be real. They are not in the
prediction.

## What it produced in-sample

Applying rules 1–3 to the 61 sessions already measured (exits
unchanged, so no credit taken for rule 4):

| | Trades | Per day | Win rate | Gross | NET | Net/day |
|---|---|---|---|---|---|---|
| Current live rules | 1,957 | 32.1 | 40.4% | +67,996 | **−160,796** | −2,636 |
| **v2 (rules 1–3)** | **639** | **10.5** | **41.2%** | **+88,460** | **+13,958** | **+229** |

Trade count falls by two thirds, gross *rises* by 30%, and the system
crosses into profit. That combination — fewer trades AND more gross —
is the signature of removing trades that were never edge to begin with.

## Expected scale — stated plainly

**+Rs 229 a session. About Rs 4,600 a month on Rs 10L. Roughly 5.5% a
year, in-sample, before it meets a single day it has not seen.**

That is the honest size of what has been found. It is not Rs 30,000 a
day and no arrangement of these rules produces Rs 30,000 a day. Rule 4
is the only component with genuine upside left in it, because the tail
it targets is worth several times everything else on this page.

## How this gets falsified

The 2023–2025 test is run once, on data untouched until then. Grade it
against these, decided now:

- **PASS** — v2 is net positive across the out-of-sample years, AND
  beats the current rules by a clear margin in each of 2023, 2024 and
  2025 separately.
- **PARTIAL** — v2 beats current rules overall but flips negative in at
  least one full year. Means the direction is right and the thresholds
  are not. Do not go live.
- **FAIL** — v2 is net negative out-of-sample, or does not beat the
  current rules. Then the 61-session result was noise, this document
  was wrong, and the answer is that this strategy family does not have
  an exploitable edge after costs. That is a legitimate outcome and it
  should be accepted rather than re-fitted.

**No re-tuning between seeing the out-of-sample result and grading it.**
If rules get changed after looking, the test is spent and the next one
needs fresh data again.

## The prior worth holding

Retail intraday equity strategies fail far more often than they work,
mostly on exactly the arithmetic that beat this one: a thin edge minus
a fixed cost per round trip. The base rate says FAIL is the most likely
outcome here. This document exists so that if it does fail, we find out
in an afternoon instead of over a year of live trading.
