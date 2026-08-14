# Thursday 30 July 2026 — what to run

Live money starts **Monday 3 August**. Tomorrow and Friday are the last
two paper sessions. Two things must be proven before Monday, and both
are marked **MUST** below.

---

## Tonight — the one that gates Monday

```
py tools/verify_master_database.py
```

Checks every security ID in `data/master_stocks.csv` against Dhan's live
scrip master. **Orders are sent by ID, not by symbol.** If an ID is
wrong the bot decides on one company and buys another — sized on the
wrong stock's ATR, stopped at the wrong stock's price — and every
screen still shows the symbol it chose.

It writes `data/scrip_verified.json`. Preflight reads that every
morning and **FAILS in LIVE mode** if it is missing, older than 7 days,
or records a mismatch. Nothing goes live Monday without it.

Also one-off:

```
py tools/index_members.py
```

Fetches NIFTY 50 and F&O membership from NSE and caches it to disk.
Without it the pre-open **NIFTY 50 and F&O buttons do not appear at
all** — deliberately, because a group whose membership is unknown must
be hidden, not shown filled with the wrong stocks.

Optional, whenever you like:

```
pip install telethon
py tools/telegram_setup.py
```

Needs `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` in `.env` first — free
from https://my.telegram.org → API development tools. Until then the
Telegram panel says "not connected" and nothing else is affected.

---

## Morning

```
08:45   py tools/premarket_brief.py     the overnight world, 18 markets
08:45   py tools/preflight.py           auto-fills any missing bhavcopy
09:12   py tools/preopen_gaps.py        NSE's pre-open book, 09:00-09:12 only
09:14   py main.py
```

### MUST see at startup

```
[MTF] ... about 3.8x leverage
```

**If the `[MTF]` lines do not appear, stop and report it.** Leverage
has never once worked in a live session — `name 'dhan' is not defined`
was found today only because you ran main.py after I said we could not
compare. Nothing goes live Monday until leverage is proven.

You should also see:

```
[INDEX] Membership: {'nifty50': 50, 'fno': ...}
```

### MUST run, funded with about ₹25,000

```
py tools/live_order_test.py --symbol COFORGE
```

Five steps, real money, smallest possible size. The live order path has
never placed a real order.

---

## During the session

Dashboard: `http://127.0.0.1:8000/v2?token=...` — the link prints at
startup.

**What changed tonight, so you know where to look:**

| where | what is new |
|---|---|
| top strip | FOMC / RBI / CPI countdown. **RBI 5 Aug, ~10:00 IST, during the session** |
| Pre-market | Telegram panel, and the pre-open group buttons now actually filter |
| Live | holdings show room left to the upper circuit, and an **AT UC** tag |
| Review | closed trades show **since** and **best** — where the stock went after you sold |

**Two trading rules changed tonight:**

1. **A stock can be re-entered after a stop-out.** KAYNES was refused a
   second attempt at 10:14 today and ran to 3,684.70. Expect more
   trades, and expect some of them to be the same stock twice. Watch
   whether the old churn comes back — that is the thing to judge this
   change on.
2. **No price floor or ceiling at entry.** The universe is still the
   same 668 symbols until Friday's rebuild, so this changes little in
   practice tomorrow.

---

## After the close

```
15:35   py tools/fills_report.py         what your REAL fills cost
15:35   py tools/refused_review.py
15:35   py tools/dashboard_preview.py    replays the whole day off disk
```

**`fills_report.py` is new and today is the first day it has anything
to say.** Every fill — paper and live, never mixed — is now stored in
`data/fills.db` with the price the bot wanted next to the price it got.

Both executors have computed that difference on every single fill and
thrown it away. Yesterday that was 84 fills.

It matters because `config.SLIPPAGE_BASE_PCT` (0.05%) and
`SLIPPAGE_THIN_PCT` (0.20%) are **conventional retail figures, not your
data** — `trading/slippage.py` says so itself. Yesterday's "₹20,303 of
slippage" is those guesses multiplied out, not money that left your
account.

After ~30 real fills the report prints the measured number that should
replace them. **Only then is the limit-order question answerable**: a
market order costs a few basis points every time, a limit order costs
the whole move on the days it doesn't fill. That trade-off needs a real
number on one side of it.

If you see `[FILLS] CANNOT WRITE data/fills.db`, stop and fix it before
the live order test — those fills happen once.

The preview reads a finished session back from disk — trades, filings,
refusals, breakouts, orders, and where every stock went after you sold
it. No broker, no token, no network.

---

## Friday, after 15:30

**Rebuild the universe.** See `FRIDAY_UNIVERSE_REBUILD.md` — your own
instruction. It admits ~214 untested symbols, so it is a deliberate job
and not a quick one.
