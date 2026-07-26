# Morning Routine — 08:30, before the market opens

```
py tools/morning_universe.py
```

That's the whole thing. It takes a minute or two and prints what
changed. Then start the bot as usual.

---

## What it does

It reads yesterday's official NSE data and writes **one column** into
`data/master_stocks.csv`:

| SUBSCRIBE | Meaning |
|---|---|
| **YES** | Tradeable today. The bot subscribes to its live feed. |
| **NO** | Not tradeable intraday today. Never reaches the feed at all. |

A second column, **SUBSCRIBE_REASON**, says *why* in plain words, so you
can open the file in Excel, filter on `NO`, and read down the list.

**Nothing is ever deleted.** A stock that falls under ₹200 this month
may be back over it next month, and deleting the row would throw away
its SECTOR / INDUSTRY / KEYWORDS / THEMES — data that took real work to
build and that the sector gate and news matcher both depend on. So it
just flips to NO, and flips back to YES on its own the morning it
qualifies again.

---

## What makes a stock NO

| Reason | Why it can't be traded |
|---|---|
| **Series is BE / BZ (T2T)** | Trade-to-trade. **No intraday at all.** In LIVE this becomes compulsory delivery and a short is impossible. |
| **ETF / SGB / SME** | Not company equity. Sector strength, relative strength, corporate actions and news keywords are all meaningless for a fund. *"we will trade only in Equity series"* |
| **Price below ₹200** | One tick is a large fraction of the price, so a 0.4% stop can't survive the granularity. |
| **Price above ₹10,000** | A ₹2L position buys 11 shares; whole-share rounding throws the ₹800 risk model off by 30–50%. |
| **Turnover below ₹5 crore** | Too illiquid to get in and out without moving the price yourself. |
| **Price band 2% or 5%** | Surveillance / ASM / GSM. A stock that can only move 2% cannot produce a tradeable breakout — it locks. |
| **Corporate action today** | Split / bonus / rights / demerger / dividend ex-date. The price *scale* changes overnight, so every %-move vs yesterday is a lie. |
| **No SECTOR filled in** | New listing. See NEW_STOCKS.md below. |

**Earnings day is deliberately NOT a reason.** The engine already
refuses entries in a reporting stock, but its move is *real*, so it
should still count toward sector strength and market breadth. Dropping
it from the feed would distort the market read to fix something that's
already fixed.

### About "turnover"

**It's the previous day's**, from NSE's end-of-day bhavcopy: the total
rupee value traded in that stock across the whole day. Not intraday —
at 08:30 the market hasn't opened, so yesterday is the freshest number
available. It answers one question: *did enough money change hands
yesterday that I can get in and out today without moving the price?*

---

## NEW_STOCKS.md — your daily classification queue

New listings that pass every market test get **added to the master file**
(with their Dhan SECURITY ID resolved automatically, since that's the one
field you can't look up by hand) but land at **SUBSCRIBE = NO** with the
reason *"new listing — awaiting sector classification"*.

They're also written to **`NEW_STOCKS.md`** as a table.

Fill in SECTOR / INDUSTRY / KEYWORDS / THEMES for a row in
`master_stocks.csv`, and **the next morning's run flips it to YES on its
own.** Nothing unclassified ever reaches the sector gate.

---

## What you'll see on Friday's data

```
YES : 545
NO  : 205
```

| Why NO | Count |
|---|---|
| price below ₹200 | 130 |
| illiquid (< ₹5cr turnover) | 47 |
| price above ₹10,000 | 21 |
| T2T / BE series | 7 |

The 7 T2T names: DBREALTY, JAIBALAJI, KRN, MTARTECH, QPOWER, STLTECH,
TRIVENI.

That's **205 fewer live subscriptions**, most of the saving landing
exactly where it hurts — the 09:15 tick burst.

---

## If something goes wrong

**Everything fails open.** A stock is never marked NO because a website
was slow:

- ETF list unreachable → falls back to name patterns (`*BEES`, `*ETF`)
- Price-band report unreachable → that check is skipped entirely
- Corporate-action fetch fails → that check is skipped
- Dhan scrip master unreachable → new listings written without an ID and
  clearly flagged
- **Bhavcopy itself unreachable → the run aborts and does not touch the
  file.** Yesterday's YES/NO list stays in force, which is far better
  than a list built on nothing.

The file is rewritten **atomically** (temp file, then swap), so a
Ctrl-C at 08:45 can't leave you with a corrupt universe the bot
refuses to start on.

**Safe to run twice.** It's idempotent — same data in, same file out.

**If you forget to run it**, the bot still starts and subscribes to
everything, but prints a loud warning telling you T2T names are in the
feed.

---

## Want it automatic?

It can be scheduled to run itself every weekday at 08:30 — just ask.
