# Friday 31 July 2026 — morning runbook

**The plan:** the bot watches and ranks. It does **not** trade.
You place **one share** of one stock in **MTF**, from the dashboard, and
sell it the same day.

Everything below is a copy-paste line. Run each from `D:\Opportunity Trader`.

---

## Before you start — 2 minutes

**Add funds to Dhan.** Last night the account held **₹47.38**. One share
of a ₹200–320 stock needs roughly **₹50–80 on MTF**, and the exit needs
headroom too. **₹500 is comfortable.**

Nothing else in this runbook works without that. An order rejecting for
insufficient funds at 09:20 looks exactly like a code failure, and you
would spend the session chasing the wrong thing.

---

## 08:00 — the overnight picture

```
py tools/premarket_brief.py
```

Fills the **World markets & commodities** table on the PRE-MARKET tab —
US close, Asia, crude, gold, the dollar. Without this that box reads
*"not collected"* all day.

---

## 08:30 — build today's universe

```
py tools/morning_universe.py
```

Rebuilds `data/master_stocks.csv` with today's `SUBSCRIBE = YES/NO`.
Drops T2T names, ETFs, sub-₹200 stocks, anything going ex-split today.
**Skip this and the bot subscribes to instruments it cannot trade.**

---

## 08:45 — pre-flight

```
py tools/preflight.py
```

Checks everything that can be checked with the market shut. **Read the
output.** If something is wrong you find out now, when a restart is free,
instead of at 09:20 when it costs the session.

Then confirm the broker separately:

```
py tools/dhan_account_check.py --symbol REDINGTON
```

Three things to look at:

- **availabelBalance** — is the money actually there?
- **POSITIONS** — should say *none open at the broker*
- **the quote** — the price Dhan returns for security id 14255 should
  look like REDINGTON's real price

Places nothing. Spends nothing.

---

## 09:00 — start the bot

```
py main.py
```

**Start it before 09:15.** The opening range is built from 09:15 to
09:30 and it cannot be reconstructed afterwards — a bot started at 09:20
has no range for the whole day.

Watch the console for the dashboard line and open it:

```
http://127.0.0.1:8000/?token=...
```

The bot is in **ALERT ONLY** mode. It will find breakouts and put them
in the alert box. It will not buy anything. That is deliberate.

---

## 09:12 — the pre-open book

```
py tools/preopen_gaps.py
```

NSE publishes the auction book 09:00–09:12 and it is **gone by 09:15**.
This is the only window. It fills the **Pre-open gaps** table with who
is gapping and — new since last night — **who is still waiting**:

```
REDINGTON  307.95  +7.13%  BUYERS waiting   640,418 buy / 146,196 sell
```

Unmatched orders after the auction. A gap with a queue behind it is a
different animal from one without.

---

## 09:15 – 09:30 — the opening range

Do nothing. The bot is building ORB ranges for ~666 symbols. No signal
can fire until a range is complete.

---

## 09:30 onward — the session

Watch the **LIVE** tab. Two things matter:

**Bot alerts** — every breakout the bot found, **ranked best-first**, not
in arrival order. The top row is the highest-scoring one, not the one
that happened to fire first.

**Gainers / Losers** — 50 a side with the WHY chips and the ORB attempt
count (`^` = first attempt at the level, `^^` = second).

Click any symbol for the full card: what the company does, live price and
distance to circuit, today's opening range, last results with the grade,
news and Telegram chatter, corporate actions, and **What has happened** —
graded results and order wins with their values.

---

## The one real trade

**When you are ready — not at 09:15.** Let the first ten minutes settle.

1. Pick a stock from the ranked alert box or the Gainers table
2. Click **BUY** on its row
3. `config.MANUAL_TEST_QTY = 1` means it places **exactly one share**,
   not the ~200 that risk sizing would give
4. Check the **Dhan app** — did the order arrive, at what price, product
   **MTF**?
5. Check **broker sync** on the dashboard — does the bot's book match
   Dhan's? This is the first real test of it.
6. Later, click **EXIT** on that position. Confirm in Dhan again.

**Before any of this you must switch to LIVE.** Four lines in
`config.py`, and they are yours to change, not mine:

```python
TRADING_MODE = "LIVE"
I_UNDERSTAND_THIS_PLACES_REAL_ORDERS = True
LIVE_ALLOW_BOT_ENTRIES = False   # keep False — the BOT still cannot enter
ALERT_ONLY_MODE = True           # keep True  — alerts only
```

The last two are what keep this a one-share test rather than a live bot.
Leave them exactly as written. **Restart `main.py` after editing.**

Guard rails already in place: max ₹5,00,000 per order, 30 orders a day,
12 open positions, 0.5% price drift.

---

## 15:15 — square-off time

No new positions after this, manual buys included. If you are still
holding the test share, exit it before now.

---

## 15:30 — close

Trading stops. **The dashboard stays up** — new since last night — so the
POST-MARKET tab is readable: closed trades, performance, and every reason
the bot said no. The header changes from *Updated* to **Closed 15:30**.

Press **Ctrl+C** when you are done. It stops itself at 09:00 tomorrow if
you forget.

---

## After the close — 3 minutes

```
py tools/build_stock_events.py --apply
py tools/telegram_ocr.py --apply
py tools/refused_review.py
```

First two file the day's news and read any new screenshots. The third
compares what the bot took against what it refused — the measurement that
decides, over weeks, whether first-come-first-served is costing you.

---

## If something goes wrong

**The dashboard is blank** → is `main.py` still running? Check the console.

**Search box says "search needs a bot restart"** → the page is newer than
the process. Restart `main.py`.

**An order rejects** → read the message before retrying. Insufficient
funds, wrong product, and market-closed are three different problems and
only one of them is about the code.

**The bot's book and Dhan disagree** → the sync panel says so and changes
nothing by itself. Reconcile in the Dhan app first. Do not let the bot
keep trading against a book you know is wrong.

---

## Afterwards — change this back

```python
MANUAL_TEST_QTY = 1      # -> None once the test is done
```

A test size must never quietly become the size you trade.
