# WHAT THE BOT ACTUALLY DOES, END TO END

**5 August 2026, after the close. Phase 1, day 1.**

Every line below was checked against the running code and today's own
data. Nothing here is from memory.

---

## THE ONE-LINE ANSWER

**There are two brains inside this bot and they are not connected to
each other.**

- The **Engine** watches candles for breakouts. It is the only thing
  that can place an order. It has never placed one.
- The **Ranker** — "WHAT TO TRADE NOW", the results, the reasons, the
  sector comparison, the sizing — is a **screen**. Nothing downstream
  reads it. It cannot order, and switching the bot to live tomorrow
  would not change that.

Everything else in this document is detail underneath that fact.

---

## STAGE 1 — SOURCES COMING IN

| Source | Working? | Evidence from today |
|---|---|---|
| PRO Telegram channels | **YES** | 522 messages, 8 channels |
| Dhan tick feed | **YES** | 949 symbols, 328,599 minute candles, 09:15–15:27 |
| NSE announcements | **YES** | 5,601 result events stored |
| NSE bhavcopy | **YES** (late) | Publishes ~18:00; today's not in yet |
| Master / universe | **YES** | 1,383 stocks, security ids verified against Dhan |
| Liquidity | **YES** | 2,423 stocks with an average daily value |

Channels today: News Pulse 171, Day Trader Telugu 148, Earnings Pro 70,
Earnings 360 67, Earnings Pulse 51, Breakouts 47, OrderBook Pulse 13,
Business Pulse 1.

**Nothing is missing at the front door.** The sources are arriving.

---

## STAGE 2 — TURNING MESSAGES INTO FACTS

Two separate stores get written, and this is where it starts to go
wrong.

### `stock_events.db` — the PRO channel grades
- 239 symbols got an event today
- Grades (`GOOD`, etc.) **are** being written
- **Only 9 of 239 got an `ai_reason` written**

### `news_memory.db` — the reasons the Ranker reads
- 470 symbols got a reason today
- Many of those reasons are **useless text**

SHILPAMED, the best-performing name of the day, had exactly one entry
the Ranker could see:

```
reason:    "matched on: SHILPAMED"
direction: UNKNOWN
```

That is a symbol match, not an explanation of why the stock is moving.

**Timestamps are stored correctly** as UTC with `+00:00` attached.
`results_calendar` is fed from NSE announcements in IST and is not
affected.

---

## STAGE 3 — THE TWO BRAINS

### Brain A: the Engine — the only one that can trade

Watches one-minute candles. Fires on:
- opening-range breakout
- structural breakout
- early momentum (**switched OFF** — `ENABLE_EARLY_MOMENTUM_ENTRY = False`)

Consults results **only as a veto** (`results_gate` blocks a stock whose
numbers are due or unread). It never uses results to *find* a stock.

**Today: 1,047 signals fired. 0 taken.**

```
309  refused: "ALERT ONLY -- bot not trading, operator decides"
699  no reason recorded at all      <-- a hole in the record
 34  reports today, numbers not out yet
  5  filed today, numbers not read yet
```

Two thirds of the day's signals have **no recorded outcome**. That is
its own defect: it means the journal cannot answer why a signal died.

### Brain B: the Ranker — the screen

`core/ranker.py` is called from **one place in the entire codebase**:
`dashboard/state.py`, line 2148.

`core/position_plan.py` — same file, line 2175.

`core/result_tag.py` — **called from nowhere.** It was finished today
and is not wired to anything.

So the reason gates, the sector comparison, the liveness check, the
risk-based sizing, the EXCELLENT/GOOD/AVOID tag — all of it produces a
table on a web page and stops there.

**The two brains share no code path.** The Engine has never heard of
the Ranker.

---

## STAGE 4 — PLACING AN ORDER

The live path **is armed**:

```
TRADING_MODE                        = "LIVE"
I_UNDERSTAND_THIS_PLACES_REAL_ORDERS = True
ALERT_ONLY_MODE                      = True   <-- this is what stops it
```

With `ALERT_ONLY_MODE` on, the Engine reaches the point of entry,
computes the quantity and the stop, writes an alert saying what it
*would* have done, and returns without ordering. That is Phase 1
working as agreed.

Orders route through the SEBI static IP (`dc-mum-005.staticip.in:443`).

**Dhan Super Orders — broker-side target, stop and trailing jump — are
referenced nowhere in the codebase.** The feature exists at the broker
and the bot does not know about it.

---

## STAGE 5 — MANAGING AN OPEN POSITION

| Mechanism | Wired? |
|---|---|
| Hard stop from entry | YES |
| Trailing stop | YES |
| ATR trailing | YES |
| Fixed bracket target | YES |
| Missed-stop recovery | YES |
| Circuit proximity check | YES |
| No-progress exit | YES |
| Square-off at close | **OFF on purpose** — MTF positions are held overnight |

**A BUY from the dashboard does get a stop.** It seeds from the last
candle's low or a hard floor from entry, whichever is further, then
sizes on that. That path is sound.

**What has no stop is a position adopted from Dhan** — one bought on the
Dhan app directly. The bot sees it in the book and manages nothing.

**`liveness()` — the function that knows when a move has died — is used
to rank and never to exit.** Of 19 reconstructed trades today, 17 never
touched a stop or a target and simply sat until the bell. The bot has
no working intraday exit.

---

## STAGE 6 — CLOSING AND RECONCILING

**This is the dangerous one.**

`trading/live_execution.py`, `positions()` calls `dhan.get_positions()`
and nothing else. It never calls holdings.

Dhan moves an MTF/delivery position **out of positions and into
holdings on T+1**. So the morning after a trade, the bot asks Dhan
"what do I hold?", Dhan answers with an empty intraday book, and
`broker_sync` concludes the bot's book is wrong.

At 07:06 this morning that produced the warning you saw. **`py
tools/reconcile.py --apply` would have adopted that answer and deleted
your real positions.** It will do the same at 07:00 tomorrow.

---

## STAGE 7 — WHAT REACHES YOUR SCREEN

Working: one link, live prices at 250ms, watchlist with search,
circuit and MTF tags, GIFT Nifty, closed book merged from Dhan,
refusal breakdown.

Not on the screen: the EXCELLENT/GOOD/AVOID tag (built today, unwired),
`results_grade`, sector drill-down.

---

## THE HONEST SUMMARY

**Data in: healthy.** Sources arrive, ticks arrive, results arrive.

**Understanding: half-built.** The grades land in one store and the
Ranker reads a different one. Reasons like "matched on: SHILPAMED"
pass for explanations, and stocks are refused because of them.

**Decisions: split in two, neither complete.** The brain that can trade
doesn't read results. The brain that reads results can't trade.

**Orders: armed and deliberately idle.** Correct for Phase 1.

**Exits: the weakest link.** Stops exist. Nothing decides that a move
is over.

**Reconcile: actively unsafe.** One command from deleting the book.

---

## WHAT HAS TO BE FIXED, IN ORDER

1. **`broker_sync` must read holdings.** It can destroy real data
   tomorrow morning. Nothing else on this list can.
2. **Join the two reason stores** so the PRO grades reach the Ranker.
   This is what lost SHILPAMED.
3. **Connect the Ranker to the Engine**, or accept in writing that the
   Ranker is a screen only and the Engine is what will trade. Right now
   the bot behaves as if both are true.
4. **Wire `liveness()` as an exit rule.**
5. **Record why every signal died** — 699 blanks today.
6. Entry rules: no pick before 09:30, never below today's open,
   `fading` cannot be sized.

Nothing above is a new feature. Every item is a wire that was never
connected.
