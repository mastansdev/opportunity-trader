# Every runnable file — what it does and what you get back

All commands run from `D:\Opportunity Trader`.

**Daily routine is only two lines:**

```
py tools/morning_universe.py      # ~08:30, before the open
py main.py                        # start trading
```

Everything else on this page is either a one-off, a read-only report, or
a diagnostic for when something looks wrong.

---

## 1. Daily — the only two you must run

### `py main.py`
**The bot.** Connects to Dhan, subscribes to the YES stocks, builds
opening ranges, takes and manages trades in PAPER mode, serves the
trading dashboard, and squares off at 15:15.

| Gives you | |
|---|---|
| Live dashboard | http://127.0.0.1:8000 |
| Trades | logged to `data/trade_log.txt` |
| Candles | recorded to `data/backtest_candles.db` |
| Learning | every closed trade into the trade memory |

Type while it runs: `positions`, `exit SYMBOL`, `exitall`, `Ctrl+C`.

**Exits immediately on a holiday or weekend** — that's intended.

---

### `py tools/morning_universe.py`
**The pre-market run.** One command, six jobs:

| # | Does | Writes |
|---|---|---|
| 1 | Marks every stock **SUBSCRIBE YES/NO** (T2T, ETF, <₹200, illiquid, ASM band, corporate action) | `data/master_stocks.csv` |
| 2 | Stores yesterday's **daily candle** for all EQ stocks | `data/daily_candles.db` |
| 3 | **Trading holidays** — skipped if this year is already loaded | `data/market_calendar.db` |
| 4 | **Results dates + earnings pulse** — daily in season, weekly out | `data/results_calendar.db` |
| 5 | **Corporate actions** — splits, bonus, dividends | stock memory |
| 6 | **New listings** queued for you to classify | `NEW_STOCKS.md` |

**On screen:** YES/NO counts, which stocks newly blocked or newly
tradeable, holidays ahead, who reports today.

**Safe to run twice.** Aborts without touching anything if the bhavcopy
can't be downloaded — yesterday's list stays in force.

---

## 2. One-offs — already done, don't need again

### `py tools/build_daily_history.py 30`
Backfills 30 days of daily candles. Slow the first time (one download
per day), instant after. **Already run — 30 days, 71,922 bars.**
Only needed again if you want a longer history (`60`, `90`).

### `py tools/refresh_calendars.py`
Same three knowledge stores as the morning run, but **forced** and
without touching `master_stocks.csv`. Use it if you want the calendars
refreshed right now, out of cycle. **Already run.**

---

## 3. Reports — read-only, run whenever

### `py tools/calendar_report.py`
Holidays ahead, who reports in the next 14 days, which stocks have a
**reliable** reporting time vs no usable pattern, and what the stock
memory holds.

```
py tools/calendar_report.py TCS INFY      # one stock's full record
```

### `py tools/trend_report.py`
7-day higher-high/higher-low structure for every tradeable stock —
STRONG_UP / UPTREND / RANGE / DOWNTREND / STRONG_DOWN, plus which
uptrends have just **broken**.

Writes `data/trend_structure.csv` (open in Excel).

```
py tools/trend_report.py PARAS KALYANKJIL DATAPATTNS
```

### `py tools/learning_report.py`
What the bot has learned from its own trades — grouped by sector, entry
hour, direction, exit reason. **The memory has no vote**; this is
observation only.

```
py tools/learning_report.py 3     # only buckets with 3+ trades
```

### `py tools/deals_report.py`
NSE bulk deals, block deals and short selling. Writes `data/deals.csv`.
Prints today's **08:45–09:00 block window** separately — the one
genuinely pre-market read, since a big block at a discount often
precedes a gap.

```
py tools/deals_report.py 15       # last 15 days
```

### `py tools/refresh_universe.py`
Proposes ADD / REMOVE against `master_stocks.csv` and writes
`data/universe_review.csv`. **Proposal only — changes nothing.**
Largely superseded by the SUBSCRIBE column.

---

## 4. Diagnostics — only when something looks wrong

| Command | Use it when |
|---|---|
| `py tools/inspect_results_feed.py` | earnings pulse is empty — shows NSE's raw fields |
| `py tools/verify_master_database.py` | check every security ID against the live broker |
| `py tools/dashboard_preview.py` | open the dashboard outside market hours (weekends, after 15:30) |

---

## 5. Backtest — replay a recorded session

| Command | Does |
|---|---|
| `py backtest/monday_replay.py` | replays a session through **today's exact live rules** |
| `py backtest/ranked_replay.py` | strength-ranked selection (top gainers long / losers short) |
| `py backtest/replay.py` | plain ORB baseline |
| `py backtest/import_from_log.py` | rebuild candles from `diagnostics.log` (bootstrap only) |

Needs recorded candles. `main.py` records them every session
automatically.

---

## 6. Tests

```
py -m pytest -q
```

548 tests. Run after any code change — if this isn't green, don't trade.

---

## Quick answers

**"What do I run on a normal morning?"**
`py tools/morning_universe.py` then `py main.py`. Nothing else.

**"What if I skip the morning run?"**
The bot still starts, but subscribes to everything including T2T names
it cannot legally trade intraday. It warns you loudly.

**"What if I run something twice?"**
Everything here is safe to re-run. Nothing double-counts.
