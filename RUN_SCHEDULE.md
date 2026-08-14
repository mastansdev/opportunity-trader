# Runs, in order, with timings

All times IST. Corrected 3 August 2026 against the real tool names.

**One rule above all others:** never run two things that read Telegram at
the same time. `core/runlock.py` refuses the second one. The order below
never asks you to.

---

## A. The night before — 22:30, ~25 min, unattended

```
py tools/nightly.py
```

Ten steps in sequence, each waits for the last. Two were added on
12 August 2026 — `delivery` (the fetch existed and was never scheduled, so the
store sat three sessions stale while the dashboard printed it beside live
prices) and `health` (a read-only census that exits non-zero on a silent data
outage; it reports and the night moves on, it can never halt the run):

| # | Step | Tool | What it does |
|---|---|---|---|
| 1 | telegram | `telegram_catchup.py --apply` | reads channels, OCRs images |
| 2 | history | `build_daily_history.py` | today's bars from the bhavcopy |
| 3 | discover | `discover_stocks.py --apply` | stocks the channels named that we don't carry |
| 4 | classify | `classify_stocks.py` | fills sector on new rows |
| 5 | verify | `verify_master_database.py` | every security id against Dhan's own master |
| 6 | universe | `morning_universe.py` | tradeable list + liquidity gate |

Re-run one step only:

```
py tools/nightly.py --only classify,universe
```

**Step 5 exits non-zero when the master is dirty. That is correct** — a
security-id mismatch means the bot would buy a different company. Fix
the rows, re-run, and it must print `clean`.

Weekends: still run it. Step 1 is what gets Monday's calendar card in.

---

## B. Morning — 08:30. One command, then two terminals.

```
py tools/morning.py
```

That runs, in order: token → telegram catch-up → universe → verify →
brief. It refuses a step rather than colliding with a running reader,
carries on when one fails, and prints how long each took. It does
**not** start `main.py` or the collector — those keep running, so they
stay yours.

Then, one terminal each:

```
Terminal 1   py main.py                trading
Terminal 2   py tools/collector.py     Telegram + news
```

And at **09:12**, not before:

```
py tools/preopen_gaps.py
```

Re-run one step only:

```
py tools/morning.py --only verify
```

---

## B2. The long way, if you ever need a step by hand

### 08:30 · Terminal 1 — token (CHECK only, nothing to do)
```
py tools/dhan_token_check.py
```

**You no longer log in.** `core/dhan_auth.py` (11 Aug 2026) mints a fresh
24-hour token over TOTP when `main.py` starts — `main.py:194`. `DHAN_TOTP_SECRET`,
`DHAN_CLIENT_ID` and `DHAN_PIN` are in `.env`, and if any of that fails it falls
back to the `DHAN_ACCESS_TOKEN` already there and says why.

This command only *confirms* it, which is worth doing before the open because a
dead token is the one failure that stops the whole session.

> The old instruction here was `py tools/dhan_login.py`. **That file does not
> exist** and had not for some time — it was also step 1 of `tools/morning.py`,
> so the first step of every morning failed silently and the run carried on.
> Fixed 12 August 2026.

### 08:35 · Terminal 1 — overnight catch-up
```
py tools/telegram_catchup.py --apply
```
Must finish before anything else.

> **This paragraph was wrong from 10 August to 12 August 2026.** It said
> *"Slow: it re-walks 96 hours across every channel even when nothing is new —
> 45 min on 3 August for 16 messages. A `--new-only` flag is queued to fix
> this."* That was true on 3 August. It was **fixed on 10 August** and the
> document was never updated, so the operator went on believing the bot had no
> memory of where it stopped.

**The bot resumes from where it stopped.** `data/telegram.db`'s
`feed_watermark` table holds, per channel, the last message time *and* the last
message id:

```
Earnings Pulse     2026-08-12T11:49:09Z   id 13763   400 messages
Earnings 360       2026-08-12T05:15:54Z   id  6171   338 messages
Day Trader Telugu  2026-08-12T04:54:41Z   id 204661  516 messages
```

`core/feed_clock.py` turns that into how far behind each channel is, and
`catch_up()` sizes the walk to **that channel's own gap** rather than a flat 40
pages — `max(2, min(40, behind_hours * 0.6 + 2))`:

```
WLPulseBot        30.6h behind  ->  20 pages
Business Pulse    20.8h behind  ->  14 pages
Earnings Pulse     4.2h behind  ->   4 pages
```

And it stops the moment a page contains a post id already held — that is the
correct signal, because it means the two ranges overlap and there is no hole
between them. Page count is only a safety rail for a first run on an empty
database.

Three channels (Breakouts, News Pulse, WLPulseBot) skip the **backward walk**
by operator decision on 10 August; they are still polled forward normally.

Signs it is alive, not hung: `data/telegram_reader.lock` exists, and the
`.db` timestamps keep moving. Ctrl+C is safe — every page is committed
as it is read.

### 08:40 · Terminal 1 — overnight picture
```
py tools/premarket_brief.py
```
Standalone. Touches no position.

### 08:45 · Terminal 2 — the bot
```
py main.py
```
Stays up all session. Holds the Telegram reader lock — **do not run
anything Telegram-related from Terminal 1 while it is up.**

Check on startup:
- subscribes ~946 symbols
- ticks arriving
- no repeating error lines

### 08:47 · Browser
```
http://localhost:8000
```
**Ctrl+Shift+R.** A cached panel shows yesterday's chips.

---

## C. In session

| Time | What | You |
|---|---|---|
| 09:12 | `py tools/preopen_gaps.py` (Terminal 1) | **not earlier** — NSE fixes opening prices 09:08–09:12 |
| 09:15 | open, ORB window starts | watch |
| 09:30 | ORB range set, entries can fire | watch |
| 09:30–15:00 | bot manages entries, trails, exits | supervise |
| 15:00 | no new entries | — |
| 15:20 | intraday square-off (MTF **not** forced out) | — |
| 15:30 | close | — |

Manual BUY / SHORT / EXIT with a quantity box are on the dashboard.
Empty box = full size: **₹30,000 of your margin × 4 = about ₹1,20,000 of stock**
(`MTF_MARGIN_PER_POSITION_RS` × `MTF_LEVERAGE`). This line said "₹1 lakh" until
12 August 2026; it was never that number.

**Broker stop is now ON** (`BROKER_STOP_ENABLED = True`, 12 Aug). Every entry
also rests a Forever Order at Dhan at the hard stop, so a position carried
overnight is protected even with this process stopped. It toggles live from the
dashboard — `/api/broker_stop/off` — with no restart, and the `broker_stop`
panel shows `resting`, `open` and `unprotected` counts. **Watch the first
session.**

---

## D. After the close — 16:00, optional

```
py tools/outcome_report.py
```

What happened after each chip fired. Needs days of samples before it
says anything. Run it; don't act on it yet.

---

## E. Weekly — Sunday

Covered by nightly step 5, but worth running alone after any master edit:

```
py tools/verify_master_database.py
```

---

## F. When something looks wrong

| Symptom | Run |
|---|---|
| A stock's chips look like another company's | `py tools/audit_event_tags.py` |
| "Are we using everything from PRO?" | `py tools/audit_pro_channels.py` |
| A stock won't take a manual BUY | check the blocked list on the dashboard |
| Panel empty or stale | Ctrl+Shift+R, then check main.py is up |

Both audits are report-only unless you add `--apply`, and
`audit_event_tags.py` prints every row it would touch first.

---

## Authorisation

**DDPI active since 3 August 2026.** No eDIS, no TPIN, no daily OTP. The
bot can complete a sell unattended, including an overnight MTF position
exited the next morning.

Before DDPI this needed a CDSL authorisation every morning before 08:00.
If DDPI is ever revoked, that step comes back — and until it is redone,
an automatic exit will place the order and the pay-in will not complete,
which the engine cannot see.

---

## Two warnings that cost real damage

**1. Never let two processes write the event store at once.**
`data/stock_events.db` lives on a Windows drive. SQLite there does not
survive two writers — it was corrupted this way on 2 August and rebuilt
from a backup. If a tool is writing, let it finish.

**2. Back up before any `--apply`.**
```
copy "data\stock_events.db" "data\stock_events.backup.db"
copy "data\master_stocks.csv" "data\master_stocks.backup.csv"
```

---

## The whole day

**TWO terminals stay up all session. A third is for one-off commands.**

```
22:30 (night before)  py tools/nightly.py               ~25 min, walk away
                        10 steps, ending with `health`

08:30  Terminal 3     py tools/morning.py               token check, telegram,
                                                        universe, verify, brief

08:45  Terminal 1     py main.py                        STAYS UP -- trading
08:45  Terminal 2     py tools/collector.py             STAYS UP -- Telegram
08:47  Browser        localhost:8000 + Ctrl+Shift+R

09:12  Terminal 3     py tools/preopen_gaps.py          not before 09:12
09:15  open — supervise
15:30  close

16:00  Terminal 3     py tools/knowledge_report.py      is every store fresh
                                                        AND understood?
16:00  Terminal 3     py tools/learning_report.py       what the book says
```

**Terminal 1 and Terminal 2 must both be running.** `main.py` reads Telegram
and never collects it; `tools/collector.py` does the collecting. Without
Terminal 2 the channels go quiet and the ranker runs out of reasons — which is
exactly the state `main.py`'s startup `[IMPACT]` line now warns about.

**Never run anything Telegram-related in Terminal 3 while the collector is up.**
`core/runlock.py` refuses the second reader, and it ages a lock out over two
hours rather than checking whether the process is alive — so a killed run
blocks the next one for a long time.
