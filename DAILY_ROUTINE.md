# Daily routine — Opportunity Trader

Save this. Do it the same way every trading day.

---

## ⚠️ FIRST, EVERY MORNING — the two that stop the day dead

**1 · Regenerate the access token.** Dhan tokens last **24 hours**.
Yesterday's dies part-way through today's session, and when it does the
tick feed keeps running on its own socket while every broker call
starts failing — so it looks like an outage, not an expiry.

    web.dhan.co -> My Profile -> Access DhanHQ APIs -> Generate
    paste into .env after DHAN_ACCESS_TOKEN=

**2 · Check the order route.**

    py tools/proxy_check.py

Orders must leave via **165.101.251.109** (the static IP), everything
else via your home line. If that number changes, or the proxy does not
answer, **do not trade** — every order would be refused DH-905.

> Static IP expires **31 Aug 2026**. Renew at staticip.in before then
> or order placement stops.

**You need 2 terminals.** Both opened at `D:\Opportunity Trader`.

- **Terminal 1** — the bot. Started once at 09:00, never touched again.
- **Terminal 2** — everything else. Tools run here, before and after.

---

## BEFORE THE MARKET — all in Terminal 2

### 07:00 · close the overnight gap — **START HERE AFTER A WEEKEND**

```
py tools/telegram_catchup.py --apply
```

The channels do not stop when your laptop does. **34% of everything they
send arrives outside market hours.** Friday 15:30 to Monday 09:00 is
about 42 hours and roughly 250–400 posts, most of them result cards that
have to be read by OCR.

Measured on the real store: **about 7 messages a minute.** So a weekend
backlog is **40–60 minutes of work**, not seconds.

`main.py` does this automatically at startup — but if you start it at
09:10 it will still be reading Friday while the market opens. The bot
trades fine either way; your chips just fill in while you are looking at
them.

- **Monday, or after any day off** → run this at 07:00, or start
  `main.py` at 07:00 instead of 09:00.
- **Ordinary weekday** → skip it. Overnight is one page and `main.py`
  handles it in seconds.

Safe to run twice. The second run costs nothing and grades nothing new.

**Day Trader Telugu posts videos at the weekend.** Those are filtered —
`NOISE` in `core/stock_events.py` drops anything carrying `youtu.be`,
`youtube.com` or `/shorts/`. Measured: 23 such posts stored, **0 events
created from them.** The message is kept, it just never becomes a chip.
Nothing else from that channel is dropped.

**What this run now picks up that it did not before (1 August 2026):**

| Card | Was | Now |
|---|---|---|
| Evening recap grid | 0 events | **`REPORTED` — during / after close** |
| Market Sentiment pages | 3 events | **`MARKET_ANSWER` — 225** |
| Concall summaries | filed as plain news | **`CONCALL` — tone + guidance** |

All three were being eaten by the same rule — the one that refuses a
message naming three or more companies. Correct for a news recap, wrong
for a table where every row carries its own symbol.

---

### 08:00 · the overnight picture

```
py tools/premarket_brief.py
```

Fetches what happened while you slept — US close, Asia, crude, gold,
the dollar, US yields. **18 numbers.**

*Skip it and:* the "World markets & commodities" box on the PRE-MARKET
tab reads *"not collected"* all day.

---

### 08:30 · today's tradeable list

```
py tools/morning_universe.py
```

Rebuilds which stocks the bot is allowed to touch. Reads yesterday's
bhavcopy and marks each stock YES or NO — dropping anything under ₹5
crore of daily turnover, T2T names, ETFs, and anything going ex-split or
ex-demerger today. Also refreshes the results calendar and tells you how
many companies report today.

*Skip it and:* the bot uses a stale list. It may subscribe to a stock
that cannot be traded intraday, or one whose price scale changed
overnight — which poisons the sector and breadth numbers.

---

### 08:35 · check every security ID against Dhan

```
py tools/verify_master_database.py
```

**Run this straight after morning_universe, every day.** It downloads
Dhan's live scrip master (~205,000 rows) and checks that our ID for each
symbol is the one Dhan actually uses.

*Why it matters:* on 31 July it found **six wrong IDs**. Two were not
near-misses — our file said CHOLAFIN was 685, Dhan says 19257. An order
would have bought a completely different company, and the contract note
would have been the first you heard of it.

**If it reports mismatches, fix them before starting the bot.** If it
reports a symbol "not found on NSE", that stock should be set
`SUBSCRIBE = NO` — we cannot identify it, so we must not trade it.

---

### 08:40 · yesterday's bars

```
py tools/build_daily_history.py
```

Downloads any trading day missing from `daily_candles.db`. Instant when
there is nothing to fetch.

*Why it is on the list:* on 1 August the store stopped at **30 July** —
Friday the 31st was simply absent. Two things break quietly when that
happens. The panel ranks on two-day-old prices, and the **market-answer
chip cannot fire at all**, because it needs the session *after* a result.
Two rows that day showed `PULSE: Excellent results` on stocks that had
fallen 10%, and the panel said nothing about it.

---

### 08:45 · pre-flight

```
py tools/preflight.py
```

Everything checkable with the market shut: which switches are on, are
the databases present, is the price history current, do all the modules
import, are the security IDs verified.

**Read the output. Do not skim it.** Warnings are fine; a refusal is
not. If something is wrong you find out now, when a restart is free.

---

### 08:50 · the broker

```
py tools/dhan_account_check.py --symbol REDINGTON
```

Read-only. Places nothing, spends nothing. Three things to look at:

- **availabelBalance** — is there money?
- **POSITIONS** — does Dhan hold what you think it holds?
- **the quote** — does the price for that security ID look right?

*If the funds call fails,* the token has expired. Regenerate it in the
Dhan app before anything else — everything downstream will fail the same
way.

---

## THE SESSION

### 09:00 · start the bot — TERMINAL 1

```
py main.py
```

**Before 09:15, always.** The opening range is built between 09:15 and
09:30 and it cannot be reconstructed afterwards. A bot started at 09:20
has no range for the whole day.

Open the dashboard from the link it prints.

> **ONE start. ZERO restarts.**
> If something looks wrong between 09:15 and 15:30, write it down.
> Do not restart. A restart costs the opening range for every stock.

---

### 09:12 · the pre-open book — TERMINAL 2

```
py tools/preopen_gaps.py
```

NSE publishes the auction book between 09:00 and 09:12 and it is **gone
at 09:15**. This is the only window there is.

It gives you where each stock opens, the gap, and — the part worth
having — **who is still waiting**: the buy and sell orders left unmatched
when the auction settled. A gap with a queue of unfilled buyers behind it
is a different animal from one without.

Safe to run while the bot is going. It writes a file the bot re-reads.

---

### 09:12 – 09:15 · read the PRE-MARKET tab

Rebuilt 1 August 2026. The gaps table **is** the tab now; everything
else sits under it, because between 09:00 and 09:15 the pre-open book is
the only thing on the screen that is changing.

```
Symbol │ IEP │ Gap% │ Who is waiting │ Matched │ Why │ Action
─────────────────────────────────────────────────────────────
  Gapping up (n)
  Gapping down (n)
  Flat, or no gap % published (n)
```

Three things to know:

- **The third group is not padding.** NSE omits its `pChange` exactly
  when it is most interesting — on a stock with no prior close. Those
  rows show `—` in the gap column and a real IEP and book beside it.
  Nothing in your universe is ever dropped from this table.
- **Matched quantity is fillability.** A 6% gap on 94 shares is not a
  trade.
- **`BUY 09:15` means what it says.** Dhan does accept orders in the
  pre-open window, but the bot cannot send one — a manual request is
  consumed inside `process_tick()` and the first tick of the day arrives
  at 09:15. Clicking here **queues** the order for the open. If you want
  to be in the auction itself, place it by hand in the Dhan app.

Below the gaps: **World markets**, **Commodities**, **Rates & currency**
as three separate tables; **Events ±7 days**; **Results & corporate
actions** in three columns (*Results today │ Ex-dates │ Reporting within
7 days*); and **News collected**.

---

### The chips, as they now look — 1 August 2026

Three chips are measured. Everything else is greyed context.

| Chip | n | Beat the market by | Beat it how often |
|---|---|---|---|
| `DOUBLE ✦` (both positives) | 22 | **+3.04%** | 77% |
| `PULSE: Excellent` | 25 | +2.17% | 80% |
| `CLEAN \|` | 54 | +0.81% | 59% |
| `ONE-OFF` | 25 | **−1.61%** | 28% |

- **They sort first now.** PSPPROJECT on 30 July had eight chips with
  `CLEAN |` fourth — hidden inside the `+N`. Arrival order was deciding
  what reached your eye.
- **`DOUBLE ✦`** = Earnings Pulse said EXCELLENT *and* Earnings 360 said
  CLEAN. Two different publishers, same quarter. Best thing on the screen.
- **`SKIP — sources disagree`** = a positive chip next to a `ONE-OFF`.
  Happened 3 times ever, so there is no measurement. Treat it as a pass.
- **`CLEAN |` alone is weaker than it feels** — it means *nothing is
  wrong*, not *this is excellent*.

### Four new chips, from cards that used to be thrown away

```
REPORTED AFTER CLOSE (31 Jul) -- not yet priced by the market
TAPE DISAGREED: Weak result, stock +6.79% (During-hours) -- ...
TAPE AGREED: Weak result, stock -7.40% (During-hours) -- ...
CONCALL POSITIVE/CONFIDENT: growth rising, margins expanding
```

- **`REPORTED AFTER CLOSE`** — released after 15:30, so the market was
  shut and has not answered it. **This is the early-bird list.** Read it
  first on a Monday.
- **`TAPE DISAGREED`** — the publisher's grade and the actual price move
  point opposite ways. The one case where the grade alone puts you on the
  wrong side.
- **`CONCALL`** — the tone management struck, and which way they guided
  on growth and margins.

**All four score zero.** They describe what already happened or what
somebody said — not evidence the stock is worth buying.

---

### 09:15 – 09:30 · do nothing

Ranges are building for ~770 stocks. No signal can fire yet. This is not
a moment to look for something to do.

---

### 09:30 onward · watch

The **LIVE** tab:

- **Bot alerts** — every breakout found, **best first**, not first-fired
- **Gainers / Losers** — 50 a side with the reasons and the ORB attempt
  count (`^` first attempt at the level, `^^` second)

Click any symbol for its full card.

#### The chips, and what each one is telling you

The channels send two things per stock — a **verdict** (Weak / Great)
and a **card full of detail**. Until 1 August the bot read the verdict
and threw the detail away. These are the chips that came out of fixing
that.

| Chip | What it means |
|---|---|
| `ONE-OFF: <item> Rs <n> Cr` | The card flagged a one-off. **The number is the point** — subtract it from the printed profit yourself. |
| `CONFLICT: Pulse says Weak, 360 says Great` | Two channels read the same quarter opposite ways, on the same day. Scored **zero**. It says *look*, not buy or sell. |
| `ALREADY PRICED: Good result, stock −5.8%` | Good news, price fell. The market had it before you did. |
| `LESS BAD THAN FEARED: Weak result, stock +6.2%` | Weak news, price rose. Worse than expected is not the same as bad. |
| `CROWDED 30x — likely already priced` | Volume 30× its own normal. The crowd is already here. |
| `WATCH: margins Compressing` | The card's own gauge, and it is a direction, not a number. |
| `EXPECTED BULLISH: …` | What the market wanted *before* the result. Scored **zero** — a bullish expectation that then misses is a sell. |

**The one to take seriously.** CDSL, 1 August: PAT printed **+15% YoY**,
and ₹39.5 Cr of it was a one-off dividend from the subsidiary. Strip it
and the quarter earned roughly **78 Cr against 102 Cr** a year before —
a fall, not a rise. The +15% is the number that puts a stock in your
gainers list. The one-off is the reason it is there.

The bot does **not** decide which side is right. It shows you both and
scores the disagreement at zero.

#### What a BUY actually places — 1 August 2026

```
your margin       Rs 1,00,000     MTF_MARGIN_PER_POSITION_RS
leverage (max)          4X        Dhan's maximum
position          Rs 4,00,000
stop                  2.5%   ->   Rs 10,000 if it hits
daily loss cap    Rs   40,000  =  4 stop-outs and the bot stops
```

**The stop moved from 1% to 2.5% on 1 August.** It was 1% on your
dashboard button and 2.5% on the bot's own entries — two stops in one
account, and the 1% was left over from a trailing stop switched off on
29 July.

Measured on 50,422 entries, buy at close, hold 3 sessions:

```
stop    avg/trade   stopped out   winners killed
1.0%      +0.392%      72.9%          51.4%   <- was killing half
2.5%      +0.424%      45.2%          19.7%
3.5%      +0.489%      30.7%           9.8%
```

**2.5% is a leverage decision, not a returns decision.** 3.5% earns
more. But at 4X, Dhan's margin call comes at a **6.27%** fall, and 3.5%
leaves only 2.77% of runway. Revisit if you ever drop to 2X.

**Optional, Terminal 2, any time:**

```
py tools/dhan_account_check.py --symbol <SYMBOL>
```

---

### 15:15 · square-off time

No new positions after this, manual ones included. If you are holding
something intraday, exit it before now.

### 15:30 · close

Trading stops. **The dashboard stays up** so the POST-MARKET tab is
readable. The header changes from *Updated* to **Closed 15:30**.

Press **Ctrl+C** in Terminal 1 when you are done reviewing. It stops
itself at 09:00 tomorrow if you forget.

---

## AFTER THE CLOSE — Terminal 2, about 3 minutes

### 1 · file the day's news

```
py tools/build_stock_events.py --apply
```

Turns the day's messages into typed events against the right stocks —
RESULT with its grade, ORDER with its value and customer. Safe to
re-run; it only adds what is new.

> **This is now a safety net, not the main path.** From 31 July 2026
> the bot files these events *as the messages arrive* — roughly 90
> seconds, instead of the 91 minutes it used to average. You will see
> them in Terminal 1 while the market is open:
>
> ```
> [EVENTS] YASHO -- RESULT EXCELLENT: #YASHO - Excellent Results
> [EVENTS] ASTRAMICRO -- ORDER: secures Rs 2,205.23 crore order from HAL
> ```
>
> Still worth running after the close: it re-reads **every** message
> with the current rules, including any picture whose text arrived late.

### 2 · read any new screenshots

```
py tools/telegram_ocr.py --apply
```

Reads the pictures the channels posted, so tomorrow they are searchable
text instead of images nobody can use.

### 3 · what the bot took vs what it refused

```
py tools/refused_review.py
```

The measurement that decides, over weeks, whether the entry rules are
costing you. **Do not change a rule on one day of this.** Most buckets
need a fortnight before they mean anything.

### 4 · take the figures the channel sent

```
py tools/load_pulse_grids.py --apply
```

Earnings Pulse posts a FinAI grid with every result, and it carries
**three quarters** of real figures — including the year-ago quarter,
which a single filing does not even contain.

```
Metric      QoQ    YoY    Jun'26  Mar'26  Jun'25
Sales        1%    11%       783     792     707
OP         -18%     8%       228     277     210
PAT         17%     9%       159     192     146
```

**This is the better source, not a fallback.** The filing parser reads
a table out of a 14 MB PDF and gets it wrong often enough to matter —
it stored WESTLIFE's quarterly sales as **₹1.00 crore** when the card
said **₹736 crore**. First run: 429 quarters, Jun-26 coverage 342 → 404
symbols.

It leaves the filing rows alone. Two independent readings of one
quarter is what the CONFLICT chip is made of.

### 5 · which chips were worth reading

```
py tools/outcome_report.py
```

For every chip the panel shows, the move on the session AFTER it,
against the market's median that day. **Read the N column first.**

First run, on four days:

```
PULSE EXCELLENT     74   +1.72%   85.1% up
CLEAN brief         89   +1.56%   66.3%
PULSE GOOD         341   +0.45%   60.4%
BEAT/MISS tally    115   +0.01%   50.4%    <- nothing
AI NEGATIVE         36   +0.14%   55.6%    <- WRONG WAY
ONE-OFF             27   -0.47%   33.3%    <- the warning works
```

It also prints the number that puts the rest in context: stocks with
**any** chip did **+0.19%**, stocks with none **-0.07%**. So **0.26
points of every edge above is "being in the news"**, not the panel.
Subtract it before believing any row.

Nothing here changes a score, and nothing in the trading path imports
it. Give a bucket a fortnight before acting on it.

### 5 · what the AI cost today

```
py tools/ai_check.py
```

Costs about ₹0.003 to run. The budget meter **fails closed** — if the
spend ledger cannot be read, or the month is at its cap, the AI stops
calling rather than guessing. Measured to date: 339 calls, **₹22.32**.

---

## OCCASIONAL — not every day

### After the channel format changes, or a parser is fixed

```
py tools/telegram_resymbol.py --apply
```

Re-links stored messages to their stocks with the current rules. It
**adds** symbols it finds and removes only one thing: a symbol that
disappears once the card's own labels are stripped.

*Why that rule is so narrow:* `CLEAN` is Clean Science's real ticker
**and** the word every Earnings Brief prints when a quarter is honest —
`EARNINGS QUALITY | CLEAN`. On 1 August **140 stored messages** carried
a chemicals company's ticker, including D-Link's and NEUEON's Q1 cards.
Removing CLEAN wherever the label appears would also have deleted
*"Clean Science inks 5-year supply deal. #CLEAN"*, which is real. A true
mention survives the strip; a label does not.

Last run: **129 removed, 11 kept**, every one of the 11 genuine.

---

## THE WHOLE DAY ON ONE PAGE

| Time | Terminal | Command |
|---|---|---|
| **before all** | 2 | **regenerate token -> .env** |
| **before all** | 2 | **`py tools/proxy_check.py`** |
| 07:00 *(Mon / after a break)* | 2 | `py tools/telegram_catchup.py --apply` |
| 08:00 | 2 | `py tools/premarket_brief.py` |
| 08:30 | 2 | `py tools/morning_universe.py` |
| 08:35 | 2 | `py tools/verify_master_database.py` |
| 08:40 | 2 | `py tools/build_daily_history.py` |
| 08:45 | 2 | `py tools/preflight.py` |
| 08:50 | 2 | `py tools/dhan_account_check.py --symbol REDINGTON` |
| **09:00** | **1** | **`py main.py`** ← before 09:15 |
| 09:12 | 2 | `py tools/preopen_gaps.py` |
| 09:12–09:15 | — | read the PRE-MARKET tab |
| 15:30 | 1 | `Ctrl+C` when done reviewing |
| after | 2 | `py tools/build_stock_events.py --apply` |
| after | 2 | `py tools/telegram_ocr.py --apply` |
| after | 2 | `py tools/refused_review.py` |
| after | 2 | `py tools/outcome_report.py` |
| after | 2 | `py tools/ai_check.py` |
| if books disagree | 2 | `py tools/reconcile.py` (bot stopped) |
| checking layout, market shut | 2 | `py tools/dashboard_preview.py` |

---

## SAFE / NOT SAFE while the bot is running

**Safe** — reads only, or writes a file the bot expects:

- `dhan_account_check.py`
- `preopen_gaps.py`
- `refused_review.py`

**NOT safe** — these rewrite files the bot has already loaded:

- `morning_universe.py`
- `verify_master_database.py`
- anything with `--apply`

Run those before 09:00 or after 15:30. Never in between.

### One writer at a time on `stock_events.db`

Two tools write it: **`telegram_catchup.py`** and
**`build_stock_events.py`**. `main.py` writes it too, all session.

Running two of them together means two writers on one SQLite file —
you get `database is locked`, and worse, a **half-applied** run. Let one
finish before starting the next.

`build_daily_history.py` writes a *different* database and is safe
alongside a catch-up.

---

## LOOKING AT THE DASHBOARD WITH THE MARKET SHUT

```
py tools/dashboard_preview.py
```

`main.py` shuts itself down after 15:30, so it would flash and die. This
runs until Ctrl+C and **cannot place an order** — it forces
`TRADING_MODE` to PAPER for its own process only. You will see it say so:

```
[PREVIEW] TRADING_MODE forced LIVE -> PAPER for this process.
          config.py is unchanged; main.py is unaffected.
```

> **If a panel is empty that should not be, restart the preview.**
> `index.html` is re-read from disk on every page load, but the Python
> is loaded once at startup. New page + old process = panels that ask
> for data the server does not know about yet. This is the single most
> likely reason a panel reads *"nothing collected yet"* when the data is
> demonstrably there.

---

## IF SOMETHING GOES WRONG

**Dashboard blank** → is Terminal 1 still running? Check it.

**Search box says "needs a bot restart"** → the page is newer than the
process. Note it; deal with it after the close.

**An order rejects** → read the message before retrying. *Insufficient
funds*, *wrong product* and *market closed* are three different
problems and only one is about the code.

**Bot's book ≠ Dhan's book** → the **AT THE BROKER** panel names the
symbol and says which side to trust. This happens whenever you close a
bot-opened position from the Dhan app, which is normal if you use both.

To fix it — **stop the bot first**, or your change is overwritten when
it shuts down:

```
Ctrl+C                          in the bot's terminal
py tools/reconcile.py           look at both books, changes nothing
py tools/reconcile.py --apply   adopt Dhan's version
py main.py                      start again
```

It **never places an order**. Selling a position the bot imagines it
holds would open a real short. It only edits our own file, backs it up
first, and leaves the ORB ranges alone.

**Anything else, between 09:15 and 15:30** → write it down. Do not
restart.

---

## THE FOUR RULES

1. **Start before 09:15.** The opening range cannot be rebuilt.
2. **One start, zero restarts.**
3. **Verify the security IDs every single day.** It has already caught
   six wrong ones. It costs a minute.
4. **After a weekend, start at 07:00.** The catch-up is 40–60 minutes
   of OCR and it will not be finished by 09:15 if you start at 09:10.

---

*Last updated 1 August 2026 — pre-open gaps table, grouped news table,
earnings-quality chips, weekend catch-up timing.*
