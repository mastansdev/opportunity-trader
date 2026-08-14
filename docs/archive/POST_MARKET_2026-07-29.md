# POST MARKET — 29 July 2026

---

## SCOREBOARD — final, end of the 29 July evening

**35 findings. 17 closed. 18 open.** 1,107 tests pass.

### CLOSED THIS EVENING

| # | Finding | What changed |
|---|---------|--------------|
| N1 | Bot sized every entry at Rs 2 lakh, double the rule | Routed through `_risk_sized_qty` |
| N2 | **MTF leverage never worked at all** | `dhan` -> `dhan_rest_client`; a NameError swallowed every run |
| N3 | Opening range systematically too narrow | Widened from the exchange's own high/low |
| N4 | Opening print missed by ~2 seconds | Exchange's official open now preferred |
| N5 | Last three minutes of every session discarded | Open candles finalised at shutdown |
| A5 | Bot closed positions the operator opened | Housekeeping exits blocked; trail warns |
| A1 | **The trail sold every winner** | Removed. Stop fixed at entry −2.5%, never moves |
| A2 | Partial exit booked too small a slice | Off. Cost Rs 11,614 over 35 trades |
| B1a | Refused breakouts were deleted daily | `core/signal_journal.py` writes every one |
| B1b | First come = first buy, no escape valve | Slot rotation ON, capped at 5 swaps/day |
| E1 | Bot vs NSE percentages unproven | `tools/nse_check.py` — **verdict 09:20 Thursday** |
| E2 | Blind 09:00–09:15 | `core/preopen.py` + `tools/preopen_gaps.py` |
| Vol | Volume filter failed OPEN and leaked | Hard gate; 5-min window fixes the 11% zero-volume artefact |
| N9 | Manual protection silently killed rotation | `_can_rotate_out` skips and keeps looking |
| N10 | Rotation had no churn limit | `ROTATION_MAX_PER_DAY = 5` |
| — | News/results as a GATE would block 33 of 35 trades | Made a ranking input instead |
| — | Exit measurement had no tooling | `exit_review.py`, `trail_sweep.py`, `refused_review.py` |

### STILL OPEN — 18

**A. Exits (2)** — A3 circuit rule still direction-agnostic for the
bot's own positions; A4 exits ignore the news the entries read.

**B. Selection (2)** — B2 sector used only to block, never to prefer;
B3 results grading wrong for 116 banks and NBFCs.

**C + D. Dashboard (12)** — structure and defects, untouched.

**E. Data (1)** — E3 Nifty-50 vs 666-stock universe mismatch.

**F. Execution (1)** — F1 marketable limit orders.

**Plus, found tonight and not yet done:**

- **N6** — `TOP_N_MOMENTUM_MODE` still locks a 25/25 list at 09:30 that
  nothing reads. Dead machinery that misled me twice.
- **N7** — `daily_candles.db` and the bhavcopy folder stop at 27 July.
  Two sessions stale, and nothing downloads automatically.
- **N8** — `DAILY_MAX_LOSS_RS = 20,000` was set for unleveraged
  positions. With MTF working it now trips after roughly two failed
  trades instead of four. Nobody decided that.

---

## PREVIOUS SCOREBOARD (kept for the record)

**32 findings. 8 closed. 24 open.**

Seven of the eight closed were found tonight, chasing the operator's
own observations rather than auditing code.

### CLOSED

| # | Finding | Fix |
|---|---------|-----|
| A5 | Bot closed positions the operator opened | Housekeeping exits blocked, trail warns instead of selling, hard stop kept |
| N1 | Bot sized every entry at Rs 2 lakh, double the rule | `_atr_entry_sizing` routed through `_risk_sized_qty` |
| N2 | **MTF leverage never worked at all** | `dhan` -> `dhan_rest_client`; a NameError swallowed every run for days |
| N3 | Opening range systematically too narrow | Widened from the exchange's own high/low, inside the window only |
| N4 | Opening print missed by ~2 seconds | Exchange's official open preferred over our first tick |
| N5 | Last three minutes of every session discarded | Open candles finalised at shutdown |
| E2 | Blind 09:00-09:15 | `core/preopen.py` + `tools/preopen_gaps.py` |
| E1 | Bot vs NSE percentages unproven | `tools/nse_check.py` built — **verdict due 09:20 tomorrow** |

### NEW FINDINGS FROM TONIGHT, STILL OPEN

| # | Finding |
|---|---------|
| N6 | `TOP_N_MOMENTUM_MODE = True` no longer means what its name says. The 09:30 lock still runs, still logs a 25/25 list, still persists it — and nothing reads it. Dead machinery that misled me twice tonight |
| N7 | `daily_candles.db` and the bhavcopy folder both stop at **27 July**. Two sessions stale, so MA50, median volume and turnover normals are all computed on old data. Nothing downloads the bhavcopy automatically |

### STILL OPEN — the rest

**A. Exits (4 of 5)** — A1 the 2.5% trail, A2 the partial too small,
A3 circuit rule still direction-agnostic for the bot's own positions,
A4 exits ignore the news the entries read.

**B. Selection (4 of 4)** — B1 first come first buy, B2 sector used
only to block, B3 results grading wrong for 116 banks and NBFCs,
B4 equal capital regardless of quality.

**C. Dashboard structure (4 of 4)** — six screens tall, half of it
history and debug, no search, light mode as the base.

**D. Dashboard defects (8 of 8)** — sector overlapping LTP, no LTP in
closed positions, blank QTY, partials shown as two entries, LONG and
SHORT clubbed, circuit bands invisible, company business invisible,
results shown for shortlisted stocks only.

**E. Data (1 of 3)** — E3, the Nifty-50 versus 666-stock universe
mismatch.

**F. Execution (1 of 1)** — F1, marketable limit orders.

---


**The session ran 09:15 to 15:30 with zero restarts. First time.**

That was the entire goal of the day. Everything below is a bonus, and
almost all of it was found by the operator watching the screen — not by
any audit of the code.

Trading mode: PAPER. Nothing below cost real money. It cost information,
which is what the day was for.

---

## A. EXIT RULES — the money leak

Five stocks in two sessions, all the same shape: profit on screen, exit
fires, stock carries on without us.

| # | Finding | Evidence |
|---|---------|----------|
| A1 | **2.5% trailing stop gives back the move** | AFFLE (28 Jul, +3,087 → +590), KRIPLON, KAYNES, EPACKPED, PCBL |
| A2 | **Partial exit books too small a slice** | KAYNES 30 of 59; EPACKPED "small portion" — not enough banked, bulk still trailed out |
| A3 | **Circuit proximity is direction-agnostic** | `CIRCUIT_PROXIMITY_PCT = 0.02` closes within 2% of *either* limit |
| A4 | **Exit path never reads the news the entry path reads** | PCBL filed results 14:19, bot logged it, trail stopped us out, stock +3% |
| A5 | **Manual positions are auto-exited without asking** | SMLMAH bought at upper circuit, closed by the bot within seconds |

### A3 in detail

For a LONG position the two circuit limits are opposite risks:

- **Lower circuit** — real danger. If it locks there are no buyers and
  the position cannot be exited at any price. Closing early is correct.
- **Upper circuit** — the best case. Bid up with no sellers. Exiting
  there means the bot systematically dumps its strongest names.

Seen from both sides on the same day: it sold SMLMAH at UC, and APCOTEX
went to UC without ever being considered.

Proposed: lower circuit → exit unchanged. Upper circuit while long →
hold. Upper circuit and not held → candidate, not exclusion.

### A5 in detail

This is the old pending task *"position watcher that alerts, never
auto-exits"*, never built. A deliberate manual entry was overridden by
the bot inside seconds. Manual positions should raise an alert, not be
closed.

---

## B. ENTRY AND SELECTION

| # | Finding | Detail |
|---|---------|--------|
| B1 | **First come = first buy** | Ten slots filled by whichever breakout fired earliest; later, better movers locked out |
| B2 | **Sector is only used negatively** | `sector_monitor` blocks longs in a collapsing sector. Nothing anywhere *prefers* a leading sector, and there is no concept of a leader within one |
| B3 | **Results grading fits manufacturers only** | `grade()` reads **sales and PAT only**. 34 Banking + 82 Financial Services = **116 stocks** graded on metrics that don't describe them |
| B4 | **Equal capital regardless of quality** | Carried from 28 Jul. Rank 1 and rank 50 get the same allocation |

### B1 — the design tension

Strict ranking cannot work in real time: at 10:15 the bot doesn't know a
better setup fires at 11:40. Two candidate fixes, to be decided on data:

- **Quality floor** — refuse anything below a threshold, take everything
  above it in arrival order
- **Reserved slots** — cap the morning at N, keep the rest for later

Measurable tonight: what the ten taken positions did versus what the
refused breakouts did. Every refusal is already in the breakout feed
with a timestamp.

### B3 — the two examples

**APCOTEX** (manufacturer) — sales +32% QoQ, PAT +127% QoQ, OPM 13.8% →
22.3%. Our grader handles this correctly.

**MASFIN** (NBFC) — NII +44% YoY, but **provisions +44% YoY**, PAT only
+5% QoQ. There is no "sales" line. The number that decides quality is
provisions relative to NII, and the grader cannot see it.

| Sector | What actually decides quality |
|--------|-------------------------------|
| Manufacturing | sales, OPM expansion, PAT |
| Banks / NBFC | NII, provisions vs NII, NPA trend, AUM growth |
| IT services | constant-currency revenue, margin, deal wins |
| Pharma | US vs domestic mix, USFDA status |

---

## C. DASHBOARD — structure

| # | Finding |
|---|---------|
| C1 | **Six to seven screens tall, single column, fourteen stacked panels** |
| C2 | **More than half the page height is Action Log + Closed Trades** — history and debug output, neither useful at 10:40 |
| C3 | **No search** — a single stock cannot be looked up at all |
| C4 | **Light mode is the better base** — dense numeric tables read faster, and the coloured badges carrying the best information disappear into the dark background |

### C5 — the principle the operator set

> "dashboard must contain all info from bot. recall the memory of any
> stock on demand"

Anything the bot knows and acts on must be visible. If the bot holds a
fact and hides it, that is a bug by definition.

Merged with C3 into a single stock card:

```
KAYNES
  price      LTP, % vs prev close, day high/low, turnover
  sector     sector, industry, sector move today, rank within it
  results    last quarter, QoQ, grade, next reporting date
  news       announcements and filings today, with times
  corporate  splits, bonuses, ex-dates, circuit band
  memory     every past trade, entry reason, outcome
  now        breakout state, why blocked or allowed, position if open
```

### C6 — proposed layout

Four tabs, one visible at a time. Same data, same backend, no new
libraries.

```
[ NOW ]   [ MARKET ]   [ POSITIONS ]   [ REVIEW ]
```

- **NOW** — shortlist, fresh breakouts, results due today, anything
  needing a decision. 90% of the day; should fill the screen alone.
- **MARKET** — gainers, losers, sectors, breadth, overnight picture.
- **POSITIONS** — open positions, risk, margin, book exposure.
- **REVIEW** — closed trades, action log, system health.

Open question for the operator: does the day actually divide that way,
and does the Action Log earn a place at all or was it only ever a
debugging aid?

---

## D. DASHBOARD — specific defects

| # | Finding |
|---|---------|
| D1 | Sector text **overlaps LTP** in the Shortlist box |
| D2 | **No LTP in Closed Positions** — impossible to see what a stock did after exit. Requested before and filed as cosmetic. It is not cosmetic: it is the number that measures the exit rule |
| D3 | **QTY blank** in Closed Trades (open since 28 Jul) |
| D4 | **Partial exits render as two entries**, with no plain-English note saying what happened |
| D5 | **LONG and SHORT clubbed in one table** — raised before, still not split |
| D6 | **Circuit bands (UC / LC) shown nowhere**, though the bot polls them for every symbol and closes positions on them |
| D7 | **Company business not shown** — `master_stocks.csv` already carries CORE BUSINESS, KEYWORDS, THEMES, COMMODITY_EXPOSURE, ECONOMIC_SENSITIVITY for all 973 stocks |
| D8 | **Results shown only for shortlisted stocks**, not the 52 reporting today |

### D2 — what the column should carry

```
exit price  |  LTP now  |  what holding would have paid  |  peak since exit
```

That answers the AFFLE / KAYNES / PCBL question automatically, every
day, instead of either of us reconstructing it from charts.

### D5 — a question first

The operator is longs only. So a SHORT table is not a trading list — it
is a warning list. Either keep it as SHORT candidates, or relabel it
**WEAK / AVOID**: stocks breaking down, useful for knowing what not to
touch and which sectors are bleeding. Same data, but the second earns
its space.

### D8 — correction

An earlier claim today that the results calendar was **absent** from the
dashboard was wrong, and was made from reading code instead of looking
at the screen. The Shortlist badges clearly show `FILED RESULTS today`,
`STRONG: sales +x% QoQ, PAT +y% QoQ` and `REPORTING TODAY`. The real gap
is coverage, not absence.

---

## E. DATA AND ACCURACY

| # | Finding |
|---|---------|
| E1 | **Bot % vs NSE % — unresolved.** Formula is already NSE's: `(last − prev_close) / prev_close`. If wrong, the inputs are wrong, not the arithmetic |
| E2 | **No pre-open data at all.** The bot is blind 09:00–09:15 — no equilibrium price, no gap %, no pre-open volume. Item 16 on the operator's own preparation chart |
| E3 | **Universe mismatch.** NSE's headline "top gainers" is usually Nifty 50. Ours is 666 mid and small caps. INFY +3.74% and ACUTAAS on top can both be true |

---

## F. EXECUTION

| # | Finding |
|---|---------|
| F1 | **Slippage — move to marketable limit orders** |

Plain limits are the wrong fix. On entry, a breakout that runs away
never fills: avoiding ₹200 of slippage to miss a ₹3,000 move. On exit
it is worse — a stop-loss limit in a falling stock simply doesn't fill.

**Marketable limit**: a BUY limit placed slightly *above* the current
price. Fills immediately like a market order, cannot fill worse than the
cap. Only real decision is how wide the cap is — to be set from today's
actual fills, not a guess.

Measured slippage 28 Jul across all trades: **₹4,166**.

---

## G. CHECKED AND FINE

- **NSE announcement timeouts** — 2 failures against 55 successful news
  events. NSE is occasionally slow; the poller retries and loses
  nothing.
- **News latency is good** — announcements reaching the bot 1–2 minutes
  after NSE's own filing time:

```
14:19  PCBL       RESULTS  filed 14:19:01 (1 min ago)
14:19  BLACKBUCK  RESULTS  filed 14:18:03 (2 min ago)
14:24  PCBL       PAYOUT   filed 14:23:02   Dividend
14:26  PCBL       PAYOUT   filed 14:25:04   Record Date
```

- **Pre-market module** — all 18 Yahoo symbols resolve. A % change bug
  was found and fixed *before* the open: `chartPreviousClose` measures
  from the start of the requested range, not the prior session, and was
  reporting crude at −10.65% and the Nikkei at −7.13% overnight. Neither
  happened. Now uses `previousClose`, with a test pinning it.

---

## H. STILL OPEN FROM BEFORE

- 61-session sweep of the 2.5% trail
- Purge `X` / `NEW` / `OLD` test symbols from the live path
- Verify every SECURITY ID against Dhan's scrip master; drop JBCHEPHARM
- Survivorship bias in `daily_candles.db`
- Strip the MIS-era machinery
- Live order test on one stock with real money (planned 30 July)

---

## THE ONE NUMBER THAT MATTERS

**09:15 to 15:30. Zero restarts.** Never achieved before today.

Every finding above exists because the session was allowed to run.
