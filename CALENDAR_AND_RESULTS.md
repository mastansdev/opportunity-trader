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

So every filing's broadcast timestamp gets recorded. After a few
quarters:

```
TCS            ~16:05   (6 past results, +/-40min)
```

Median, not mean — one result that slipped to 22:00 shouldn't drag the
estimate. The spread is shown so you can see how consistent a company
actually is; a name with a 6-hour spread has no habit worth trusting.

The first run reaches back **400 days**, so you get roughly four
quarters immediately rather than waiting a year for it to become useful.

### Why the time matters more than it sounds

Right now the earnings gate is blunt: a reporting stock is refused for
the **whole session**. But if the numbers land at 16:20, the entire
09:15–15:15 session was ordinary trading and we sat out for nothing.

Knowing the habitual time turns that into *"trade it normally, stop 30
minutes before it usually reports."*

**That change is not made yet.** This only supplies the data. Once
there's real timing history, we can measure whether reporting-day
mornings actually behave like ordinary mornings — and change the rule on
evidence rather than on the idea sounding good.

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
