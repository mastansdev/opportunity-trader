# Tuesday 2026-07-28 — what to run

Three terminals. Two commands before the open, one optional.

---

## Tonight (or now) — one job, twelve minutes

```
py tools/fetch_quarterly.py --resume
```

Fills the quarterly store for all 693 symbols. Right now it holds **2 rows
for 1 symbol** (TMB, from a test), so until this runs the STRONG / GOOD /
WEAK grades stay blank on the dashboard.

Safe to Ctrl+C. `--resume` picks up where it stopped.

Check it worked:

```
py tools/fetch_quarterly.py --report
```

---

## To see the dashboard right now, with the market shut

```
py tools/dashboard_preview.py
```

Then open **http://127.0.0.1:8000**. It runs the REST snapshot only — no
tick feed, no trading, no orders possible — so it shows yesterday's
closing data in the real panels. Safe to leave running.

The two new panels are at the top: **Filed Today** and **Shortlist**.

---

## Morning

### Terminal 1 — 08:30, before the open

```
py tools/morning_universe.py
```

Builds today's tradeable list. Wait for it to finish.

### Terminal 2 — the bot

```
py main.py
```

Dashboard link with token prints in the log. Open it.

**Six startup lines worth reading:**

| Line | Normal |
|---|---|
| `[MASTER_LOADER] Loaded ... symbols` | ~935 |
| `[MEMORY] Stock memory refreshed: NSE X fetched / N new` | any **fetched** > 0 |
| `[FINANCIALS] N quarters on record across M symbols` | M ≈ 690 after the fetch above |
| `[NEWS] Watching announcements every 60s` | present |
| `[FILING] Reading results PDFs as they arrive` | present |
| `[RECORDER] Recording this session's candles` | present — **restart if missing** |

### Terminal 3 — optional, the news engine

```
py run_news_engine.py
```

Advisory only. Never blocks trading.

---

## The one thing to watch today

When a company files, the log prints one of two lines:

```
[FILING] SYMBOL: read 3 quarters (3 new) -- STRONG: sales +26% QoQ    <- working
[FILING] SYMBOL: download failed (...)                                <- wrong URL field
```

If it is the second, run this and send the output:

```
py tools/inspect_results_feed.py
```

The PDF link field name was written without a live announcement row to
check against. It is a one-line fix, but it needs the real field name.

---

## What is new since yesterday

- **Shortlist panel** — all 689 ranked by reason, with the WHY beside each
  name. Yesterday's ranking surfaced SWIGGY (−₹2,128) and never showed TMB
  (+12.1%). This one puts TMB at 2 and SWIGGY at 250.
- **Filed Today panel** — announcements as they land, every 60 seconds,
  instead of one read at 08:30.
- **Automatic PDF reading** — a filing at 16:03 becomes
  `STRONG: sales +26% QoQ` by 16:04, with no manual step.
- **Two bugs fixed** — the trailing stop was leaving ₹1.40 of room instead
  of ₹17, and the recorder was inventing prices that never traded.

---

## What is NOT fixed, and should stay in mind

**The grade does not predict price.** On the only three real cases we could
check it got one right. KFINTECH's profit fell 7% and the stock rose 9.2%
because it beat forecasts — the market prices surprise, and nothing here
can see surprise. MOLDTKPAC graded STRONG and fell 6.5% the same day.

What exists now is a much better **screener**. It puts the right names in
front of you with the reasons attached. That is not the same as evidence
that it makes money.

**Survivorship bias is still unresolved.** Every forward-return figure from
last night came from 510 stocks that all survived to today. That check
decides whether the measured edge is real.
