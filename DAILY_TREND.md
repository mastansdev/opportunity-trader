# Daily trend history & deal flow

Two new sources of context, both free, both from data we were already
downloading or ignoring.

---

## Part 1 — Daily candles and 7-day structure

### Run once

```
py tools/build_daily_history.py 30
```

Downloads the last 30 trading days' bhavcopies and stores a daily
candle for every EQ stock. Slow the first time (one download per day),
then instant — already-stored dates are skipped.

After that, `py tools/morning_universe.py` adds one day per run and the
history stays current by itself.

### Then look at it

```
py tools/trend_report.py                              # everything
py tools/trend_report.py PARAS KALYANKJIL DATAPATTNS  # your three
```

Writes `data/trend_structure.csv` — open it in Excel and sort.

*(Note: the NSE symbol is **DATAPATTNS**, not DATAPATTERNS.)*

### What it reads

Exactly the structure you described. Each day is compared to the day
before it:

| Today vs yesterday | Called | Means |
|---|---|---|
| higher high **+** higher low | **UP leg** | the staircase up |
| lower high **+** lower low | **DOWN leg** | the staircase down |
| higher high **+** lower low | OUTSIDE | expansion, volatility |
| lower high **+** higher low | INSIDE | contraction, coiling |

A run of UP legs is a trend. Then the label:

| Label | Meaning |
|---|---|
| **STRONG_UP** | 3+ higher highs in a row, unbroken |
| **UPTREND** | mostly higher highs and higher lows |
| **RANGE** | no clear structure |
| **DOWNTREND** | mostly lower highs and lower lows |
| **STRONG_DOWN** | 3+ lower lows in a row |

### The break — your actual point

> *"once that formation stopped and forms higher low then lower low
> formation causes the reversal / range boundness"*

This is flagged as **`broke_structure`**, and it needs **both** things:

1. the stock **failed to make a higher high**, and
2. it **took out the previous day's low**

One quiet day on its own is a *pause*, not a reversal — if a single
inside day tripped the flag, every consolidation would fire a false
alarm. There's a test pinning exactly that distinction.

When a break is confirmed, the label is **downgraded to RANGE** even if
the leg counts still say uptrend. That's the whole point of noticing it.

You also get `hh_streak` (how many higher highs in a row, right now),
`days_since_high`, and how far below the 7-day high it closed.

---

## Part 2 — Bulk / block deals and short selling

```
py tools/deals_report.py 5
```

Writes `data/deals.csv`.

| Report | What it is |
|---|---|
| **Bulk deals** | one client trading >0.5% of a company's shares in a day, on the normal market |
| **Block deals** | a negotiated trade ≥ ₹10cr, crossed in the **08:45–09:00 window before the open** |
| **Short selling** | NSE's daily securities-wise short positions |

### The honest read

**For:** a bulk *buy* is an institution committing real money — and
large positions get built over days, not minutes. That's a plausible
reason a stock keeps trending, which is what this bot trades.

**Against:** it lands *after* the close, so it's always a day stale. A
block deal has a buyer **and** a seller, so "net" only really means
something for bulk deals. And plenty of large deals are promoter exits
or pledge unwinds — the opposite of conviction.

### The one genuinely useful piece

The **live block window at 08:45–09:00** is the only part that's
actually pre-market. A large block crossed at a discount very often
precedes a gap, and we can see it before 09:15. `deals_report.py`
prints those separately and loudly.

---

## Neither of these votes on a trade — on purpose

Both are wired to **describe**, not decide. Nothing here gates an entry.

I want to be straight about why. On Friday I shipped the "still
trending" rule because the mechanism was obviously sensible. When I
measured it properly against the market baseline, the stocks it favoured
had **underperformed by 0.55%**. A plausible story is not evidence, and
I'd rather not repeat that.

So the plan is: record the structure label against every trade the bot
takes, and after a few weeks ask the only question that matters —

> did trades taken in **STRONG_UP** structure actually do better than
> trades taken in **RANGE**?

If yes, wiring it as an entry gate is a one-line change. If no, we
deleted nothing and learned something real.

---

## Where each thing lives

| File | Purpose |
|---|---|
| `core/daily_store.py` | daily bars, SQLite, one row per (date, symbol) |
| `core/trend_structure.py` | the HH/HL leg reader |
| `core/deal_flow.py` | NSE bulk/block/short fetch + netting |
| `tools/build_daily_history.py` | one-off backfill |
| `tools/trend_report.py` | the structure table |
| `tools/deals_report.py` | the deals table |
| `data/daily_candles.db` | the history |

The store has an `upto` cutoff on every read, so a backtest replaying
2026-07-24 physically cannot see 07-25. Without that, any result would
be worthless.
