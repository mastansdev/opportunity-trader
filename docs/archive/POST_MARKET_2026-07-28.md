# Post-market list — Tuesday 2026-07-28

**No code changes until after the close.** Operator instruction. This
file is the running list; keep adding to it during the session and I'll
work through it once the market shuts.

---

## From the operator, during the session

### 1. Dashboard blank for the first ten minutes of the session

**What happened.** Everything from News downward rendered empty —
News, Filed Today, Shortlist, Top 50 Gainers & Losers, Sector Heatmap,
Risk Alerts. Market Intelligence, Breadth and Capital were fine.

**Cause — mine, two separate faults stacked.**

1. The render function's parameter is `snap`. My three inserted blocks
   used `s.news`, `s.announcements`, `s.shortlist` — a variable that does
   not exist there. `ReferenceError` on the first line of the news block
   killed every panel after it.
2. `dashboard/server.py` read `index.html` **once at startup** into
   memory. So the fix could not reach the browser no matter how many
   times F5 or Ctrl+Shift+R was pressed, and I told the operator to
   refresh when a restart was required.

**Already fixed** (during the session, with permission implied by the
outage): variable names corrected, HTML now read per request, and every
panel's render wrapped so one throw can never blank the others again.

**Still to do:** a test that renders the real snapshot shape and fails if
any panel throws. This was caught by a human staring at a screen for an
hour; it should have been caught by a test in a second.

**Process note, worth more than the fix.** I diagnosed this by guessing
from screenshots — browser cache, restart timing, `_compute_gl_rows` —
four confident wrong answers before checking `/api/snapshot`, which
settled it in ten seconds. That endpoint should be the FIRST thing
consulted whenever the dashboard looks wrong.

---

### 2. Some rows have no BUY button — why?

**Answered, and it is a deliberate rule of mine that should be reviewed.**

`dashboard/static/index.html`, the shortlist row:

```js
IS_OPERATOR && r.change_pct >= 0 ? BUY button : nothing
```

**A stock that is DOWN on the day gets no BUY button on the Shortlist.**
My reasoning was that this is a longs-only book, so offering BUY on a
faller invites buying a falling knife.

That reasoning is thin. GANDHAR was ranked #1 yesterday at −11.6% and the
operator might well want to buy a quality name that has been sold off.
The panel already prints the reason beside every name; it should not also
decide what the operator is allowed to click.

**Proposal:** show BUY on every row. Keep the reason chips as they are —
"DOWN −11.6%" and "NEWS DISASTER" are already the warning.

The News and Filed Today panels do NOT have this restriction — every row
there has a BUY button. So the behaviour is inconsistent between panels,
which is its own reason to change it.

---

### 3. Colour palette — headline unreadable, whole dashboard needs a rethink

**Immediate bug:** in the News panel the headline is a link, and the
default link blue on the dark panel background is close to unreadable.

**The larger ask:** a proper, professional palette for the whole
dashboard, working in BOTH light and dark, switchable by the existing
toggle.

Constraints that matter for THIS dashboard specifically:

- **Red/green must survive colour-blindness.** Roughly 8% of men have
  red-green deficiency. P&L, advances/declines and the heatmap all lean
  on it. Pair colour with shape or position, or shift to a
  blue-orange/teal-amber divergent scale, which stays distinguishable.
- **Dark mode should not be pure black on pure white text.** High
  contrast at maximum causes halation over long sessions. Off-black
  surfaces with slightly dimmed text is the standard for terminals people
  stare at for six hours.
- **Colour must carry ONE meaning.** Currently blue means both "a link"
  and "a news event" in different panels. Pick one.
- **Accent colours need a fixed vocabulary:** positive, negative,
  warning, neutral, informational. Five, not twelve.

To be researched properly after the close — real palettes with contrast
ratios checked, not invented on the spot.

---

### 4. Filed Today shows one company on many lines

**Observed:**

```
09:37:02   TORNTPHARM  GOVERNANCE  Appointment
01:07:01   COFORGE     RESULTS     Press Release
00:26:02   COFORGE     PAYOUT      Record Date
00:21:05   COFORGE     PAYOUT      Dividend
00:21:04   COFORGE     PAYOUT      Outcome of Board Meeting
```

Four rows for COFORGE. The operator's instruction:

> "company name - Results, Payout, ... in one line is fine enough."

**Fix:** group by symbol. One row per company, with its kinds collapsed
into a single cell, newest filing time shown, and the subjects available
on hover or expand rather than as four separate rows.

**A second problem visible in that same output, not yet raised by the
operator but real:** COFORGE's filings are timestamped 00:21 to 01:07 —
after midnight. Those are almost certainly yesterday-evening filings that
NSE stamps into the early hours. "543m ago" is technically true and
practically useless. Worth deciding whether a filing from before, say,
06:00 should be labelled "overnight" rather than given a minutes-ago
count.

---

## Open items I already know about, carried into the same session

### 5. CIRCUIT_PROXIMITY closes a winning long — raised, not yet fixed

```
COFORGE   bought 1,648.10 at 09:31:00
          exited 1,648.30 at 09:31:06   CIRCUIT_PROXIMITY
          LTP 1,650.00, upper circuit 1,681.20, gap 1.86% < 2%
```

The rule fires **"irrespective of direction"** — its own log line says so.
It was built that way on the operator's own instruction after the HFCL
incident on 2026-07-23.

But the danger is one-sided:

| position | near UPPER circuit | near LOWER circuit |
|---|---|---|
| LONG | winning; a lock traps you in PROFIT | crashing; a lock traps you in a LOSS |
| SHORT | crashing; trapped in a LOSS | winning |

**Proposal (needs operator approval):** exit only when the flagged side
is ADVERSE to the position. Keep blocking new entries on either side.
Keep the old behaviour behind a config flag.

**Interim option if the change feels too big:** set
`CIRCUIT_PROXIMITY_PCT = 0.005` — COFORGE at 1.86% would not have fired.

---

### 6. A restart inside 09:15–09:30 poisons the whole universe

```
[STATE] Restored 510 symbol(s) whose opening range is unreliable
```

**510 of 668.** Restarting during the opening-range window makes every
symbol's first tick look stale, so it gets flagged unreliable, and the
flag persists to disk for the rest of the day.

Harmless while entries are paused. **Must be fixed before ever running
unpaused**, because a single mid-morning restart would block structural
entries in three-quarters of the universe.

---

### 7. Index tiles — all four security ids were wrong, two dangerously

```
"nifty":     "13"  ->  ABB INDIA LIMITED      (a real equity, SUBSCRIBE=YES)
"banknifty": "25"  ->  ADANI ENTERPRISES LTD  (a real equity, SUBSCRIBE=YES)
"midcap":    "26"  ->  never ticked
"vix":       "21"  ->  never ticked
```

The Nifty tile was showing ABB's share price. Worse: the tick router
checks index ids BEFORE the symbol lookup and returns, so **ABB and
ADANIENT never reached the stock pipeline at all** — no candles, no
opening range, invisible to the bot for as long as the index feed
existed.

`INDEX_INSTRUMENTS` is now **empty**, and a guard refuses any index id
that collides with an equity.

**To finish:** run a session, read the `[INDEX] Unmapped IDX id NN:
LTP=...` lines, and identify each index BY ITS LEVEL — Nifty near 24,000,
BankNifty near 52,000, VIX 8–20. Then set the ids and confirm each tile
against the broker screen before trusting it.

---

### 8. FII/DII — no working method on the `nse` package

Four guessed names all missing. The error now lists the package's real
callables; read that line from the next session's log and wire the right
one. If the package genuinely has none, fetch NSE's published EOD figure
directly instead.

---

### 9. Quarterly grades are measuring the CALENDAR, not the company

- Every stored comparison is QoQ, and **zero of 677 symbols have YoY**
  (`resultsSnapshot` only ever returns two quarters).
- Q4 is India's seasonally strongest quarter, so **71% of companies
  "grew"**. A Mar-26 filer looks great; a Jun-26 filer looks terrible.
- **BEL graded WEAK** on sales −46% QoQ. BEL is a defence PSU whose Q4 is
  routinely double its Q1. That is the calendar, not the business.
- **COALINDIA's stored row is corrupt** — Mar-26 PAT of 5,533 on sales of
  490. Profit cannot exceed revenue elevenfold. Needs a sanity check on
  ingest.

**Until YoY exists, use WEAK as a "look closer" flag and ignore STRONG.**
YoY fills in as today's filings are read from their PDFs.

---

### 10. The shortlist has never been proven to make money

It is a good SCREENER — 7 of the 10 biggest movers yesterday, with
SWIGGY (the day's worst trade) at rank 250. That is not the same as
"buying these names profits."

Yesterday's number-one ranked name was **GANDHAR at −11.6%.**

The 61-session backtest was started three times this morning and killed
by the sandbox each time. **It must complete before the shortlist is ever
wired into automated entries.**

---

### 11. Survivorship bias — still unresolved

Every forward-return figure from Monday night came from 510 symbols that
all survived to today. Delisted losers are absent. This decides whether
the measured edge is real, and it has not been done.

---

### 12. The heartbeat line reads like an emergency when nothing is wrong

```
[HEARTBEAT] 10:29:27 | ticks: 620282 (+9425 in last 60s) | open positions: 0
| ORB ranges: 666 (666 complete) | stale symbols flagged: 58960
| circuit-proximity flagged: 1 | feed alive: True | tick queue backlog: 0
| tick worker alive: True
```

**"stale symbols flagged: 58,960" against a universe of 668.** It reads as
a count of symbols. It is a cumulative COUNT OF EVENTS since startup --
every time a symbol's last tick passes MAX_TICK_STALENESS_SECONDS (5s) it
increments, and a quiet mid-cap genuinely does go five seconds without a
trade dozens of times an hour. Roughly 88 transitions per symbol over an
hour is normal breathing, not a fault.

**Fixes:**
- Rename to `stale events` and add the number stale RIGHT NOW, which is
  the only actionable version: `stale events: 58,960 (0 stale now)`.
- The genuinely important signal already exists and is separate -- the
  systemic alarm at FEED_SYSTEMIC_STALE_FRACTION (50% of the universe
  stale at once). It has not fired. That is the one to watch.
- Group the line so a large harmless counter does not sit beside small
  meaningful ones with no units. Suggested: FEED (ticks, rate, backlog,
  alive) / RANGES / RISK (circuit, stale-now) / BOOK (positions).

---

### 13. Closed Positions — QTY missing, and add "what happened after I left"

**Bug:** the QTY column is empty in the Closed Positions box.

**New columns requested — the most useful idea raised today:**

| add | meaning |
|---|---|
| **LTP** | where the stock is trading NOW |
| **Since exit** | LTP minus exit price, in Rs and % |

Operator's own words: *"this will get how much we missed rally after exit
/ saved from fall of the stock."*

Why this matters more than it looks. Every exit argument this week --
LAURUSLABS thrown out twice on Rs 1.40 of movement, COFORGE closed on a
circuit rule while it was still climbing, Monday's three-lower-lows test
-- has been fought with numbers dug out of logs after the fact. This
column measures the exit rule **live, on every trade, automatically**:

- Consistently large POSITIVE "since exit" on longs = exits are too
  early, leaving rallies on the table.
- Consistently NEGATIVE = exits are working, they are saving losses.

That is the exit quality feedback loop, on screen, with no analysis
needed. It also feeds core/trade_memory.py, which is how the bot
eventually learns which exit reasons pay.

**Design notes for the build:**
- Colour must reflect BENEFIT, not direction. For a LONG, +Rs after exit
  is a MISSED gain (bad for the decision); for a SHORT it is a SAVED
  loss (good). Colouring raw price change would teach the wrong lesson.
- Freeze it at the close, or it keeps drifting overnight and yesterday's
  exits look worse or better than they were.
- Show it per trade AND as a day total: "exits left Rs X on the table" /
  "exits saved Rs Y".

---

### 14. EVIDENCE — CMLL, the cleanest case yet for the reason gate

Kept because it is the first time the operator's entry rule and the
current one can be compared on a live stock with no ambiguity.

```
What the bot knows about CMLL:
  results calendar entries : 0
  corporate actions        : 0
  quarters of financials   : 0
  daily price history      : 2 bars (listed 24 July)
```

**Nothing.** And it was the 3rd biggest mover in the first five minutes.

```
09:16  +2.31%     09:45  +0.44%
09:20  +3.41%     10:15  -0.15%
09:30  +1.92%     now    -1.31%
```

- **Current rule** (did price cross a line?) — CMLL qualifies.
- **Operator's rule** (is there a real reason?) — CMLL is rejected at
  the first gate. No results, no order win, no approval, no broker note,
  no history to compare anything against.

Same pattern in the other faders of that window, INDOTHAI and MANYAVAR,
versus the three that kept going: HEXT, COFORGE, NEWGEN. COFORGE
reported yesterday and grades STRONG.

**What this does and does not prove.** It shows the CURRENT entry test
measures the wrong thing. It does NOT yet show the reason gate makes
money — one stock on one morning. That is what the 61-session backtest
is for, and it must run before any of this is wired to entries.

Also on today's book: the two winners were HELD (LODHA 12 min +Rs 3,807,
HEXT 31 min +Rs 3,667) and every loser was cut by the trailing stop
inside twenty minutes -- ZENSARTECH in 2 minutes, NILKAMAL in 8,
RRKABEL in 20. Same signature as LAURUSLABS yesterday: the stop is
measuring whether the stock breathed, not whether the trade was wrong.

Net Rs 1,609 on gross Rs 2,429 -- **Rs 820, a third of the gross, went
to charges** across 7 round trips.

---

### 15. PRE-OPEN PANEL — everything ready by 09:10, not scrambling at 09:15

Operator's own words:

> "i need to see everything in dashboard updated by 09:10 (after
>  pre-market session completed -- there itself we can see how stocks
>  reacted with volumes and give enough confidence to buy by opening
>  time). rather than being rushed at 09:15 to check where money is
>  being moving"

**The argument is today's session.** Thirty stocks moved 2%+ in the first
five minutes. Six decisions a minute. Nobody reads thirty names and
places ten orders in that window.

**NSE's pre-open session already answers the question:**

```
09:00-09:08   order entry
09:08-09:12   matching and PRICE DISCOVERY
09:12-09:15   buffer
09:15         normal trading
```

By ~09:12 the exchange has published an **equilibrium price and
indicative quantity for every stock** -- real, order-backed, fifteen
minutes before the bell.

**THE BLOCKER IS ONE RULE IN core/market_data.py:**

```python
if tick_time.time() < MARKET_OPEN_T:
    "Dropped pre-market tick"
    return False
```

5,634 pre-open ticks were thrown away this morning. The rule is CORRECT
for what it protects -- pre-open prices must never contaminate the
opening range, the candle engine or the trailing stop. It must stay.

**Design: a SEPARATE pre-open path, not a relaxed filter.**

- Pre-open ticks accepted into their own store. Never into candles,
  never into ORB, never into any stop.
- A **Pre-Open panel** per stock: equilibrium price, % vs previous
  close, indicative quantity, gapping up or down -- ranked by move,
  with the existing reason chips (results, news, grade) already beside
  each name.
- Result: at 09:12 the operator is reading a ranked list he has already
  decided on, and 09:15 is for execution rather than discovery.

**Two things to verify before building:**
1. Does Dhan's WebSocket actually deliver pre-open packets? Today's
   5,634 drops were REPLAYED 22-July data, not live pre-open ticks.
2. Is NSE's own pre-open market API the more reliable source?

This is the largest item on the list. It changes the shape of the
morning rather than fixing a display.

---

### 16. Remove the re-entry block — we are on MTF now

```
config.py:441   BLOCK_REENTRY_AFTER_STOPOUT = True
config.py:888   ONE_TRADE_PER_SYMBOL_PER_DAY = True
```

Both were MIS-era rules: one intraday attempt per name, and once stopped
out, done for the day. They made sense when every position had to be
flat by 15:15 and a re-entry was just churning the same day's noise.

**Under MTF neither holds.** A position can run for days, so "already
traded today" stops meaning anything. And the operator's own rule is
re-entry: *"we can enter the same trade right?"* -- a stock whose reason
is still valid should be re-enterable after an exit.

Today's COFORGE is the case: closed at 09:31:06 by CIRCUIT_PROXIMITY,
then blocked. It went on to +5.28%.

**Note:** CIRCUIT_PROXIMITY deliberately does NOT arm the re-entry block
(engine.py's own comment says so, it is not a losing-trade stop-out), so
COFORGE was blocked by the LIVE circuit flag rather than by this rule.
Both need clearing for that trade to have been re-enterable -- item 5
covers the other half.

Set both to False, and check what else reads them before flipping --
BLOCK_REENTRY_AFTER_STOPOUT is referenced in five places in engine.py
with careful exceptions already carved out for rotation and
circuit exits.

---

### 17-19. AGREED — connect the memory to the reason

Operator, 2026-07-28: *"agreed no use if we don't connect the gap
between them."*

17. Add reason columns to trade_memory (news category, results grade,
    days since results, filing type) — captured AT ENTRY. Record only,
    still no vote.
18. Backfill the 28 existing trades from stored news + filings.
19. Nightly plain-English review: "entries WITH a reason vs WITHOUT."

---

### 20. THE WIRING AUDIT — what is built but not connected

Every module in core/ checked against the DECISION path (engine,
strategy, orb_engine, trailing_stop) versus dashboard-only versus dead.

```
MODULE                  IN DECISIONS   WHERE IT ACTUALLY GOES
-------------------------------------------------------------
results_calendar        YES            but BACKWARDS -- see 20a
stock_memory            partly         splits/bonus only -- see 20e
shortlist               NO             dashboard only  -- 3 "hits" in
                                       engine.py are all COMMENTS
news_watcher            NO             dashboard only
announcement_watcher    NO             dashboard only
quarterly_results       NO             dashboard only
results_pdf             NO             feeds results_ingest, ends there
deal_flow               NO             tools/deals_report.py only
trend_structure         NO             tools/trend_report.py only
index_monitor           NO             dashboard only (acceptable)
market_flows            NO             dashboard only (acceptable)
```

**20a. THE RESULTS CALENDAR IS WIRED BACKWARDS. Highest priority.**

engine.py:1584 —

```python
if symbol in self.earnings_calendar.get(candle_date.isoformat(), ()):
    return          # no entry, silently
```

A stock reporting results today is **BLOCKED from entry.** The comment
above it explains the original reasoning honestly:

> "A reporting stock's move is a news reaction, not organic momentum --
>  the ATR system can't tell the difference."

That was TRUE when written on 2026-07-24. The bot had no way to read a
result. **It now does** — the filing → PDF → grade chain works live
(MOLDTKPAC: STRONG, sales +26% QoQ, PAT +24% QoQ). The premise of the
rule has expired.

The rule is still half right, and this distinction is the fix:

```
BEFORE the announcement   outcome unknown, a coin flip   BLOCK  (keep)
AFTER  it, graded STRONG  the reason the operator wants  ALLOW  (new)
```

It blocks by DATE. It needs to block by TIME-AND-GRADE.

Scale of what is being silently thrown away:

```
27 Jul   33 symbols reporting
28 Jul   27
29 Jul   52
30 Jul   43
```

And the block is **silent** — a bare `return`, no log line. Against the
operator's standing rule that the bot must say what it is doing.

**20b. Shortlist is not in the engine at all.** Ranks 689 stocks by
reason, prints why, and reaches only a screen. Do NOT wire until the
61-session backtest completes (item 10) — started three times, killed
three times.

**20c. deal_flow is dead in the live path.** Bulk and block deals — the
operator named these as real reasons — are only visible by running a
report by hand. Never seen during a session.

**20d. trend_structure is dead in the live path.** Only tools/. Decide:
wire it or delete it, per "NO PLACE FOR ANY ITEM/FILE WHICH DOESN'T
PROVIDE ENOUGH TOWARDS GOAL REACHING BY BOT."

**20e. stock_memory only votes on price scale.** 168 corporate actions
stored; only splits/bonus/rights/demerger/dividend block a trade
(_memory_block_reason). Everything else is stored and never read. That
is defensible — but it means "bot memory" today = "did the price scale
change."

---

### 21. Charges model -- CORRECTED after operator pushback

Operator, 2026-07-28: *"do not consider mtf charges right away on closed
positions too .... pls check with dhan / resources for intraday closing
even in trading mtf segment first."*

He was right and I was wrong twice in the same estimate.

**Wrong #1 -- I charged MTF interest on same-day exits.** Confirmed at
source: interest applies **from T+1 until the stock is sold**. A
position opened and closed the same session pays **zero** interest.
Today's trades lived 6 seconds to 37 minutes. All of them got charged.

**Wrong #2 -- and this went the other way.** I modelled delivery STT as
0.1% on the SELL side. It is **0.1% on BOTH buy and sell**. So the
"MTF" figure was too LOW, not too high.

```
                                            charges     net
A  intraday STT  (what config does today)   Rs 1,054   -979
B  intraday STT + pledge/unpledge           Rs 1,369  -1,294
C  delivery STT both sides + pledge         Rs 4,709  -4,633
```

**UNRESOLVED: is a same-day MTF exit charged intraday or delivery STT?**
Public sources contradict each other. Zerodha says MTF trades are
"treated like any other delivery trade (CNC)" -- but that line is about
P&L and capital-gains reporting, not STT. Dhan's own page says MTF is
not for intraday at all.

**Settle it with a contract note, not more reading.** One real MTF buy
and sell in the same session, then read the STT line. One day, definite.

**MISSED ENTIRELY: pledge / unpledge fees.** MTF stock is auto-pledged
on buy and unpledged on sell -- roughly Rs 15 + GST each way, per stock,
per day. A FIXED cost, so it hurts small positions hardest. Nothing in
the bot knows it exists.

**Build:** charges default to INTRADAY. A separate overnight path adds
delivery STT + interest + pledge fees only when a position actually
crosses a session. Not the other way round.

---

### 22. Today's P&L is NOT evidence about the strategy

Operator, 2026-07-28: *"today dashboard lagged and made our entry as
late as stocks were moved and u judging the pnl?"*

Correct, and the record should say so. The dashboard was blank for the
first ten minutes; the bot restarted three times inside the opening
range. Entries were forced to 09:30-09:45 on stocks that had already
moved at 09:20.

**Every entry today was late because of the system, not the operator's
judgement.** Today's trades are usable as ARITHMETIC -- real prices and
quantities for testing the cost model -- and for nothing else. No win
rate, no verdict on method.

---

### 23. BUY IS NOT INSTANT -- measured. Worst case 39 seconds.

Operator, 2026-07-28: *"Buy is not happening as instant as in broker
platform - this cause slippages more. in opening even 1 sec delay may
slip +/- 1% slippage."*

He is right, and it is worse than a second. **Measured from today's own
log** -- every real click, timestamped at the dashboard, matched to its
fill:

```
symbol            clicked        filled     DELAY
COFORGE       09:30:39.317  09:31:00.682   21.36s
LODHA         09:30:57.171  09:30:57.732    0.56s
RRKABEL       09:36:38.973  09:36:39.132    0.16s
HEXT          09:44:46.432  09:44:47.378    0.95s
ZENSARTECH    09:45:02.600  09:45:02.875    0.28s
NILKAMAL      09:45:07.087  09:45:11.199    4.11s
CUPID         09:45:14.768  09:45:16.906    2.14s
MANAPPURAM    10:36:05.066  10:36:05.130    0.06s
MPHASIS       10:50:11.778  10:50:12.111    0.33s
BSOFT         10:50:30.064  10:50:30.815    0.75s
CONCOR        11:26:32.041  11:27:10.981   38.94s

median 0.75s      mean 6.33s      worst 38.94s
```

**ROOT CAUSE.** `engine.py:569` -- the buy request is checked inside
`process_tick(symbol)`. The code comment is honest and correct:

> "checked every tick, not just on candle close, so it fires on the
>  very next available price"

The problem is what "the very next tick" means. **Dhan sends periodic
SNAPSHOTS, not every trade.** Measured today: ~8,900 ticks/min across
666 symbols = one tick per symbol every ~4.5 seconds *on average*, with
a long tail. CONCOR's whole 11:26 candle was O=H=L=C=523.95 -- a single
tick in the minute. So the click sat in a `set()` for 39 seconds waiting
for a snapshot that had no reason to hurry.

**The click does not queue an order. It arms a flag and waits.**

**WHAT IT COST TODAY -- COFORGE, the 21-second one:**

```
click at 09:30:39, price that minute   1641.70 - 1643.00
actually filled at                     1648.10
slipped                                +5.75  = +0.35%
on 121 shares                          Rs 696
```

Roughly a third of one percent, on the single most time-sensitive trade
of the day, at the open, on the stock the operator wanted most.

**THE FIX -- decouple the click from the tick loop.**

The order must be placed the moment the click lands, not on the next
snapshot. Three price sources exist and none of them require waiting:

1. `market_data.get_latest_price()` -- already in memory, instant, but
   may be a few seconds old.
2. **A one-symbol REST quote.** `core/circuit_monitor.py` ALREADY polls
   `/marketfeed/quote` every few seconds for all 693 symbols. Fetching
   one symbol on demand is the same call and returns in ~100-300ms with
   a true current price. **This is the right answer for PAPER** -- it
   gives an honest fill price instead of a stale one.
3. In LIVE, price is irrelevant to the decision: send a market order
   immediately and take the broker's fill price back.

**THIS MUST BE FIXED BEFORE LIVE.** In paper a 39-second delay only
mis-records a price. In live it is 39 seconds of the market moving
before the order is even sent -- and the operator's own instinct about
the open is right: that is where the whole edge lives.

**Related, same root:** the automated STRUCTURAL entry has exactly the
same dependency. It is evaluated on candle close, which arrives on a
tick, which arrives on Dhan's schedule. Every entry in this bot is
gated on a snapshot cadence nobody controls.

---

### 24. Position sizing -- equal RUPEES, and by accident

Operator, 2026-07-28: *"every trade is being given equal capital
allocation which is not ideal. for a rank 1 & rank 50 gets same capital
allocation. will u give in this way if you trade?"*

**The complaint is correct. The cause is not what it looks like.**

The bot has TWO sizing rules and they returned the identical number on
all eleven trades today:

```
symbol          price   qty   notional   by_risk  by_notional
COFORGE       1648.10   121    199,420       121          121
LODHA         1266.00   157    198,762       157          157
ZENSARTECH     535.85   373    199,872       373          373
CUPID          228.11   876    199,824       876          876
MPHASIS       2429.90    82    199,252        82           82
   ...all eleven the same
```

`RISK_PER_TRADE_RS / stop_distance` vs `MAX_NOTIONAL_PER_TRADE_RS /
price`. **`MIN_STOP_DISTANCE_PCT = 0.01` was binding on every trade**,
and at a 1% stop the two formulas are algebraically identical:

```
2000 / (0.01 x price)  ==  200000 / price
```

One-minute ATR is never wider than 1% of price, so the floor overrides
ATR every single time. **The ATR sizing is dead code in practice.** The
bot is not choosing equal allocation -- it arrives there by accident,
from two different directions.

**AGAINST sizing by rank (my position):** the shortlist has never been
validated. Its 61-session backtest was started three times and killed
three times. Sizing by an unproven rank does not add return, it adds
variance -- concentrating on a signal with no measured edge is strictly
worse than equal weight. (Same reason naive 1/N beat fourteen
"optimal" allocation models out of sample in DeMiguel/Garlappi/Uppal
2009: estimation error swamps the theoretical gain.) MTF sharpens it --
coverage below 20% forces liquidation, roughly a 6.2% portfolio fall.

**FOR the operator's underlying point:** equal RUPEES is not equal
RISK. A 4%-range stock and a 1%-range stock both get Rs 2L; the first
can lose four times as much on the same "size." That is the genuine
mis-allocation, and unlike rank it needs no proof, because volatility
is MEASURED, not predicted.

**WHEN -- the dependency chain, in plain English**

```
STEP 1  Equal RISK instead of equal RUPEES          TONIGHT
        Stop the 1% floor overriding ATR so a volatile stock gets
        FEWER shares for the same Rs 2,000 of risk. Needs no new
        data and no proof. Must be done BEFORE any backtest, or
        every result gets measured against the wrong baseline.

STEP 2  Hard concentration cap                      TONIGHT
        No single position above a set share of equity, because of
        the MTF liquidation maths above. Independent of everything.

STEP 3  Conviction sizing                           NOT YET
        Blocked by items 17-19 (reason columns, backfill, nightly
        review) AND by sample size.
```

**How long STEP 3 really takes.** Two-proportion test, 80% power, 5%
significance, assuming a 45% baseline win rate and ~7 trades per group
per day at the current rate:

```
if "with reason" wins at    gap    trades needed    sessions
                     70%   25pp        63/group           9
                     65%   20pp        99/group          14
                     60%   15pp       176/group          25
                     55%   10pp       396/group          57
```

**So: a large effect is provable in about two weeks. A small one takes
three months.** If the reason gate is worth what the operator believes,
the data will say so by roughly mid-August. If it needs 57 sessions to
show up, it is too small to bet size on anyway -- which is itself a
useful answer.

**Size by PROVEN REASON, never by rank position.** Rank is a sort
order. Reason is a hypothesis that can be tested.

---

### 25. "Is main.py overloaded?" -- No. But it is doing 2,446 pointless disk writes a minute.

Operator, 2026-07-28: *"I DOUBT THAT MAIN.PY IS OVERLOADED. IF YES -
FIND A BETTER/SMARTER APPROACH TO REDUCE BURDEN."*

Prompted by:

```
WARNING: [FEED] 333/666 symbols (50%) are stale AT ONCE -- the feed
         appears to be lagging systemically...
         [FEED] Systemic staleness cleared -- back to 50% stale.
[HEARTBEAT] 12:19:52 | ticks: 1607472 (+8637 in last 60s) |
            stale symbols flagged: 157069 | tick queue backlog: 0 |
            tick worker alive: True
```

**THE TICK PATH IS NOT BEHIND.** The operator's own heartbeat settles
it: `tick queue backlog: 0`, worker alive, 8,637 ticks/min sustained.
An overloaded consumer grows a queue. This one is empty.

**THE 50% IS ARITHMETIC, NOT A FAULT.**

```
8,637 ticks/min / 666 symbols = one tick per symbol every 4.63s
MAX_TICK_STALENESS_SECONDS    = 5
```

With a PERFECT feed at that rate, Poisson arrivals put ~34% of symbols
more than 5 seconds past their last tick at any instant. Bursty
arrivals take it to 50%. **The alarm is measuring the threshold, not
the feed.** Same root cause as item 1b and as the 607 ORB-unreliable
symbols -- one badly-set constant, three symptoms.

**THE MESSAGE ITSELF IS A BUG.** `FEED_SYSTEMIC_STALE_FRACTION = 0.5`
and the real fraction sits exactly on it, so market_data.py:255 flaps
between "50% stale AT ONCE" and "cleared -- back to 50% stale", both
printing the same number. No hysteresis.

**WHERE THE REAL BURDEN IS -- measured, live session:**

```
log lines written per minute        ~4,000
  of which DEBUG                     3,965   99.97%
  of which [MARKET_DATA]             3,326   84%
  of which "SYM stale: 24.0s old"    2,446
```

Into a 369 MB file with no rotation. **The load is not computing ticks.
It is writing about them.**

**THE SMARTER APPROACH**

1. **Per-symbol staleness baseline.** Learn each symbol's own typical
   gap over the first 15 minutes; flag only when it exceeds ITS OWN
   normal by a wide multiple. A Rs 3,000-cr stock and a Rs 30-cr stock
   cannot share one number. **Removes ~84% of logging AND fixes the
   ORB-unreliable blacklist -- one change, both problems.**
2. **Stop writing DEBUG to disk during the session.** Console level
   only, or a ring buffer flushed only on a real error.
3. **Hysteresis on the systemic alarm.** Fire at 65%, clear at 45%.
4. **Fix the heartbeat label** (item 1c) -- 157,069 is a WARNING count,
   not a symbol count. There are 666 symbols.

**WHAT NOT TO DO:** do not split main.py, do not add processes. 902
lines, 7 daemon threads, tick path already isolated on its own worker,
backlog 0. The architecture is sound. Restructuring it would be work
with no payoff.

---

### 26. DEAD CLICK -- the button is destroyed mid-press. HIGHEST PRIORITY.

Happened twice, confirmed both times in the log:

```
SUPREMEIND   1st click: no trace anywhere.  2nd: filled 13:10:42 @ 3,472.70
KALYANKJIL   1st click: no trace anywhere.  2nd: filled 13:48:55 @ 604.10
```

Operator's first SUPREMEIND click was at ~Rs 3,385. Filled at 3,472.70.
**Rs 5,000 lost on 57 shares to a click that silently did nothing.**

**CAUSE.** `DASHBOARD_REFRESH_INTERVAL_SECONDS = 1`, and every panel is
rebuilt with `innerHTML =` (28 wholesale replacements). A browser only
fires `click` when mousedown and mouseup land on the SAME element. A
refresh in that ~100ms gap deletes the button and builds a new one --
the handler never runs. No request, no log, no error, no toast.

At 1 refresh/sec, roughly **1 in 10 clicks dies.** Eleven clicks today,
ten worked, one didn't. Twice.

**EXIT/SELL IS EQUALLY EXPOSED** (`openRows` innerHTML, line 1116). It
has not failed yet only because Open Positions has 2-3 rows while Top 50
Gainers has fifty -- a bigger table is mid-rebuild for longer.

**FIX: event delegation.** One listener on the container, which is never
replaced; read `data-symbol` off the clicked element. ~20 lines across
four panels. Plus: log EVERY attempt server-side (three silent failure
paths exist today), and a persistent action log panel instead of a
fading toast.

**On 3 August a dead SELL click means you hit exit on a falling position
and nothing happens.** This goes first, ahead of everything.

---

### 27. TRADE BIAS "SHORT ONLY" blocks every long. Third reason the bot did nothing today.

Dashboard header read **SHORT ONLY** all session. It is not a label:

```python
if (direction == LONG and regime == "SHORT_ONLY"):
    return                      # silent, no log
```

```
REGIME_BREADTH_THRESHOLD = 0.60
today: 445 declining / 665 = 66.9%   ->   SHORT_ONLY
```

**The operator trades longs only. On any day where 60% of the market is
red, the bot is structurally forbidden from taking a single long.**
Silently. That is why all 17 trades today are MANUAL_BUY_DASHBOARD --
manual clicks bypass the regime check.

"Trade with the tape" is defensible for a two-sided intraday system. It
is wrong for a long-only MTF trader entering on results and order wins:
**CUB reported today and went +8.47% on a 67%-red tape.** The regime
filter would have refused it.

Three independent blocks stopped the bot today -- ORB blacklist (607
symbols), the pause flag, and this.

---

### 28. Fresh ORB breakouts are computed, then thrown away

Operator: *"by this dashboard new/fresh orb breakouts cannot be
identified at all. today i missed some of the best movers - TVS."*

**TVS was not missed by the bot. It was seen and never shown.**
Breakouts fired today on:

```
TVSMOTOR  NTPCGREEN  PINELABS  MSUMI     MOTHERSON  LOTUSDEV
ALOKINDS  PPLPHARMA  OLAELEC   LEMONTREE RAIN       KTKBANK
OIL       CRIZAC     VGUARD    HEG       MARKSANS   RVNL
PNB       IRFC       KOTAKBANK ...and more
```

Every one computed, every one logged, every one refused by item 27 --
and **there is no panel anywhere on the dashboard that shows a
breakout.**

**BUILD: "Fresh breakouts" panel.** Newest first with a seconds-ago
clock (a breakout is worth something only while fresh), volume multiple
beside it (the 7.5-year study says QUIET volume beats 6x), and a row
that greys out and loses its button when price fades back inside the
range -- so a failed breakout is visible rather than silently gone.

Small build: the signal already exists. It needs a store and a window.

**Item 27 and 28 are one story.** The panel shows the breakouts; the
regime fix lets the bot act on them. Fix only the panel and the operator
watches signals the bot still refuses.

---

### 29. BUY button pushed off-screen by too many reasons

Visible in the operator's screenshot: VBL's row carries six why-chips,
`CROWDED 8...` is cut off at the right edge, and the BUY button is
beyond the viewport. **More evidence = less chance of buying.** Exactly
backwards.

The WHY column has no width constraint, so it pushes the action column
out of view.

**FIX, CSS only:** `table-layout: fixed`, WHY cell wraps chips onto
multiple lines inside a bounded width, action column fixed-width and
pinned right. More reasons makes the row TALLER, never the button
harder to reach. ~30 minutes, no logic touched.

---

### 30. Shortlist mixes longs and shorts in one ranked list

Rank #1 today was VBL at **-8.16%** -- the hardest-falling stock at the
top of the list, for an operator who trades long only. Ranking is by
ABSOLUTE move (deliberate, item 12) which is right for a two-sided
system and wrong for this one.

**FIX:** Long / Short toggle, ranked separately.

---

### 31. Dashboard: smaller fixes visible in the 28 Jul screenshots

- **5 of 8 Market Intelligence tiles are dead** -- Nifty, BankNifty,
  Midcap, VIX all read "needs index feed"; FII/DII reads "feed error".
  A permanently blank tile trains the eye to ignore the whole panel.
- **News headlines unreadable** -- dark blue underlined links on a dark
  background. Plain text plus a muted external-link icon.
- **News feed error**: business-standard.com returns HTTP 403.
- **Closed Trades QTY empty on all 17 rows** (also item 13).
- **"Stale Flagged: 2,77,086"** in Feed & System Health, sitting next to
  "Universe: 668" (also item 1c).

**What NOT to redesign:** the Shortlist chips are genuinely good work --
`STRONG: sales +28% QoQ, PAT +549% QoQ`, `CROWDED 8x -- likely already
priced`, `quiet 1.4x -- may not be noticed yet`. Keep as is.

**Charges observation from the Performance box:** Rs 117 per trade,
FLAT, regardless of size. 17 trades = Rs 1,991.48. CONCOR made Rs 133
gross and kept Rs 15.79. And these are the INTRADAY rates we know
understate the real figure. The strongest argument yet for fewer,
larger, longer-held trades.

---

## Keep adding below

_Operator: anything you did not understand, did not use, or that looked
wrong. No item is too small._

-
-
-
