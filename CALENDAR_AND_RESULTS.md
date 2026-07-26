# Holidays, results, and the earnings pulse

Both refresh automatically inside `py tools/morning_universe.py`. To
look at what's stored:

```
py tools/calendar_report.py              # everything
py tools/calendar_report.py TCS INFY     # one stock's full record
```

---

## 1. Trading holidays

Only ~12–15 days a year, but the bot was getting three separate things
wrong without them:

| Without a calendar | With one |
|---|---|
| downloads a bhavcopy that doesn't exist, warns, trains you to ignore warnings | knows there was no session |
| after a long weekend, "yesterday's close" is silently 3 days old — every gap and %-move measured against the wrong bar | `previous_trading_day()` returns the real one |
| starts on a holiday, subscribes 545 symbols, waits forever for ticks | warns you at startup |

**Fetched once a year, not every morning.** NSE publishes the whole
year's list in December, so re-downloading it on the other 250 sessions
is pointless traffic and one more thing that can fail at 08:45. The
download is skipped once the current year is held, with a December
look-ahead for the next year. Unplanned closures are still caught — a
weekday with no bhavcopy gets inferred automatically.

**Holiday = no trading.** The bot now exits on a holiday rather than
starting a feed that will never tick.

**Two independent sources**, so this doesn't depend on a website being
up on the morning it matters:

1. **NSE's holiday master** — authoritative, fetched and stored.
2. **Inferred from your own bhavcopy history** — a weekday NSE never
   published a file for, with trading days either side, was a holiday.
   You already have those recorded. The calendar can rebuild itself
   from local data with no network at all.

**Deliberate design note — this one is fail-*safe*, not fail-open.**
Everywhere else in the bot, missing data must never block trading. Here,
an unknown weekday defaults to **open**. Worst case if that's wrong: the
bot waits for ticks that never come, which costs nothing. The opposite
default — refusing to trade on a day it wasn't sure about — would cost
real sessions.

---

## 2. Results calendar

Replaces `config.EARNINGS_CALENDAR`, the hand-typed dict that goes stale
the moment nobody updates it. NSE publishes board meetings in advance
with their purpose, so the bot now pulls the real thing.

It's a **union, not a replacement** — anything you typed in by hand
survives even if NSE's feed misses it.

**Refreshed seasonally, not daily.** Results cluster into four windows —
Q1 lands in Jul–Aug, Q2 in Oct–Nov, Q3 in Jan–Feb, Q4 plus the annual
audit in Apr–May. So the refresh runs **daily in season, weekly out of
season**. Not *never*: a company can move its date, and a straggler
filing still carries a timestamp worth having.

Still a plain dictionary lookup on the tick path. No database is touched
while trading.

---

## 3. The earnings pulse

> *"as of now time cannot predict but later from our own stored data,
> bot can predict the time too"*

Exactly the right framing, because the two halves are different problems:

- **The DATE is published.** A company announces it will report on the
  28th. Free, available in advance.
- **The TIME is not published anywhere.** Whether the numbers hit the
  wire at 11:40 or 16:20 is announced nowhere — but it *is* observable
  after the fact, and companies are creatures of habit.

Every results filing's broadcast timestamp gets recorded. Real output
after four rounds of cleaning the input:

```
RELIABLE reporting times (97 of 227 with history):
    EMCURE       ~13:34   (3 past, spread   4min)
    NEULANDLAB   ~16:12   (4 past, spread   7min)
    ZYDUSWELL    ~12:47   (4 past, spread  13min)
    TCS          ~15:52   (5 past, spread   7min)
No usable pattern (130): COFORGE, NESCO, ACI, IOC, CHOLAFIN...
```

**Reliable = 3+ results within a 2-hour spread.** Below that bar, the
pulse says *"NO reliable pattern — do not rely on it"* instead of
quoting a median. COFORGE genuinely filed at 21:54, 16:10, 23:35 and
16:58 — a median of 17:06 for it is arithmetically true and useless.
That's not a data problem to fix; it's a real property of the company.

Median, not mean — one result that slipped to 22:00 shouldn't drag the
estimate.

### Getting this right took four passes

Worth writing down, because the mistake was the same each time: I
filtered on text that *looked* right instead of checking what the field
actually contained.

| Attempt | Result | What was wrong |
|---|---|---|
| `financial_results` endpoint | 91 rows/year | wrong endpoint — only late filings by delisted names |
| match "result" in body | 15 per company | swept in AGM minutes filed at 23:56 |
| filter follow-up documents | 6 per company | still counting "Updates" and "Shareholders meeting" |
| **match the `desc` CATEGORY** | **~4 per company** | correct — plus drop exchange clarifications |

**Lesson for next time: inspect real rows before writing the parser.**

### What the data says about the earnings block

Of the 107 names with a reliable pulse:

- **61% report after 15:15** — the whole session was ordinary trading
  and the current whole-day block cost us the day for nothing
- **39% report during the session**, some as early as **CARTRADE 11:30**
  and **DIVISLAB 12:09**

So the blunt block is wrong in both directions: too cautious for the
majority, and for the earliest reporters it's the only thing protecting
you from holding into the numbers.

Narrowing it to *"trade normally, stop 30 minutes before the usual
time"* is now supportable — **but it is not done yet.** It should be
changed after watching a couple of reporting days, not on the strength
of a table that looks clean.

---

## 3b. Dividends do not block trading

Worth recording, because I got this wrong. I had put DIVIDEND in the
price-adjusting set — the same bucket as a stock split — so seven liquid
large-caps were being refused for a whole session over this:

| Stock | Dividend | % of price |
|---|---|---|
| TATACAP | ₹0.57 | **0.17%** |
| CRISIL | ₹10.00 | **0.23%** |
| PERSISTENT | ₹18.00 | 0.35% |
| DLF | ₹8.00 | 1.24% |

Against a normal 2–3% daily range, all of that is noise. A split is a
different animal — JLHL's 2:10 read as −80%.

So dividends are now **informational**: remembered, shown in the
reports, never a veto. Splits, bonuses, rights and demergers still block
unconditionally.

The one exception kept is `DIVIDEND_BLOCK_PCT` (5%) — a *special*
dividend can be 20% of the share price, which genuinely rescales it like
a split. Nothing you'll see in practice comes close. Set it to `None` to
turn even that off.

---

## 4. What memory holds

> *"how many times stocks are releasing their results & dividend /
> buyback / splits announcing, or any other announcements in memory"*

The memory was only ever asked about **today**. Everything it had
already stored about the past was invisible. Now:

```
py tools/calendar_report.py
```

shows totals per action type across the universe, the date range
covered, and which names carry the most activity. And per stock:

```
py tools/calendar_report.py KALYANKJIL
```

gives its result history (with times where known), its earnings pulse,
and every dividend / split / bonus / buyback on record.

One thing to watch on that report: a symbol with **far more entries than
its peers** usually means a duplicate feed, not an unusually busy
company. Worth a look when you see it.

---

## Files

| File | Purpose |
|---|---|
| `core/market_calendar.py` | trading holidays, `is_trading_day`, `previous_trading_day` |
| `core/results_calendar.py` | who reports when + the earnings pulse |
| `core/stock_memory.py` | corporate actions (now with history/count views) |
| `tools/calendar_report.py` | read it all |
| `data/market_calendar.db`, `data/results_calendar.db` | the stores |
