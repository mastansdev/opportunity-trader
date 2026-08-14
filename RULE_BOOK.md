# The rule book — Opportunity Trader

> **SUPERSEDED — read [BOT.md](BOT.md) for the live rules.**
>
> This document says **Rs 1,00,000 per position** and **ALERT_ONLY = True**.
> The running values are **Rs 30,000** and **False**. It was accurate when
> written and has not been true for weeks. `BOT.md` is generated from
> `config.py` and `core/rules.py`, so it cannot drift the same way.
>
> Kept because the reasoning behind each rule is still worth reading.
> **Do not size a position from this file.**

*What the bot does, what it refuses to do, and what is yours to decide.*

Written 1 August 2026, after the first day the bot was measured instead
of argued about.

---

## 1 · WHAT THIS BOT IS

**It is an evidence panel with a BUY button.** It is not an autonomous
trader, and on 1 August 2026 it had never been shown to predict
anything.

It reads eight Telegram channels, RSS, NSE announcements and BSE
filings, and puts what it finds next to the stock, so that the question
*"why is this moving?"* has an answer before you spend money.

**`ALERT_ONLY_MODE = True`.** The bot finds breakouts and announces
them. **It does not buy on its own.** Every order is a click you make.

---

## 2 · THE ONLY TWO CHIPS TO TRADE ON

Measured on 665 graded results and 11 sessions. Everything else on the
panel is context.

| Chip | From the open | From the chip | Fell |
|---|---|---|---|
| **PULSE EXCELLENT** | +1.32% | **+0.66%** | 23% |
| **CLEAN brief** | +1.02% | **+0.52%** | 36% |

### Re-verified 1 August 2026, and one thing is better than we knew

> *"can you re confirm about these chips by checking Telegram pro
> channels & confirm me. later make them special than other chips
> **only if they are genuine guidance to me in my buying**"*

Checked twice. Sampled chips were traced back to the original channel
screenshot — the card really did print `EXCELLENT` / `CLEAN` / the
one-off. **The chips repeat a publisher; they are not the bot's
opinion.**

Then against price. *Edge* = the stock's move **minus the market's
median that session**, so a rising market cannot flatter a chip:

| What you see | n | Beat the market by | Beat it how often |
|---|---|---|---|
| **BOTH chips, one stock** | 22 | **+3.04%** | **77%** |
| **PULSE EXCELLENT** alone | 25 | +2.17% | 80% |
| **CLEAN brief** alone | 54 | +0.81% | 59% |
| **ONE-OFF** alone | 25 | **−1.61%** | **28%** |

**The sources are independent, which is why BOTH beats either:**

```
PULSE EXCELLENT   Earnings Pulse 57, Earnings Pro 28
CLEAN brief       Earnings 360 106
ONE-OFF           Earnings 360 35
```

Two different publishers reaching the same verdict on the same quarter —
not one source repeating itself.

**CLEAN brief alone is weaker than it feels.** +0.81% and it beats the
market only 59% of the time. It is a *"nothing is wrong here"* signal,
not a *"this is excellent"* signal. Nothing-wrong is worth less than
actively-excellent.

### What the panel now does about it

- The three are **loud, and sorted first**. Every other chip is greyed.
  PSPPROJECT on 30 July had eight chips with `CLEAN |` **fourth** —
  inside the collapsed `+N`, invisible. Arrival order was deciding what
  reached the eye.
- **`DOUBLE ✦`** when both positives land on one stock.
- **`SKIP — sources disagree`** when a one-off sits next to a positive.
- Nothing is dropped. The tail is still one click away.

### What is deliberately NOT claimed

**ONE-OFF is 27 samples.** Above the 20 floor, not far above it. From
*chip time* it is **7**, which is nothing — so this is a claim about the
**day**, not the minute.

**EXCELLENT with ONE-OFF has happened 3 times.** The badge says there is
no measurement rather than picking a side. The three we have averaged
faintly *positive*, so a red row would be wrong in the one direction the
data leans.

**`NOT CLEAN` is a different chip from `ONE-OFF`** and measured the
opposite way: +0.42%, up 61%. Do not read them as the same warning.

Pinned by `tests/test_trusted_chips.py` (31 tests).

Best-to-worst on both is roughly **1.5 : 1** — about ₹1.50 of run for
every ₹1 of heat.

**Everything below is context, not a reason.**

| Chip | Measured | Read it as |
|---|---|---|
| `AI POSITIVE` | −0.10% on n=196 | nothing |
| `ORDER WIN` | −0.01% on n=134 | nothing |
| `BEAT/MISS tally` | −0.29% on n=65 | mildly negative |
| `PULSE GOOD` | +0.02% on n=149 | nothing |
| `AI NEGATIVE` | went **up** 70% of the time | backwards |
| `ONE-OFF` | −0.90%, fell 67% | a real warning |

### Do not short on this evidence

`PULSE POOR` has **one** sample. `EXPECTED BEARISH` has **five**.
`PULSE WEAK` went **up** 61% of the time from chip time — "less bad
than feared" is real and it kills a short.

The best measured negative is `ONE-OFF` at −0.90% on 27 samples. That
is thin. **The short side is not ready.**

---

## 2A · EVERY RUPEE — SIZE, STOP, CHARGES, CARRY

*The section that was missing. Read it before Monday.*

### The switch that decides everything

```python
config.py:1475    MANUAL_TEST_QTY = 1
```

**Right now every dashboard BUY places exactly ONE share** — whatever
the stock, whatever the risk maths says. You will see this in Terminal 1
each time:

```
[MANUAL] config.MANUAL_TEST_QTY is set -- placing 1 share(s),
         not the risk-sized 225.
```

It is manual-only. It cannot leak into automated entries.

### What happens if you set it to `None`

Sizing is **not ₹2,000 of risk.** That rule was replaced on 28 July. The
live rule is:

```python
MTF_MARGIN_PER_POSITION_RS = 100_000    # YOUR money, per position
```

**₹1 lakh of your own margin goes into every position.** The share count
falls out of whatever margin Dhan requires for that stock — asked of
Dhan, never estimated.

Worked example, COFORGE at ₹1,686 (26.3% margin):

| | |
|---|---|
| shares | **225** |
| stock value | **₹3,79,350** |
| your margin blocked | **₹99,655** |
| funded by Dhan | **₹2,79,350** |

### What one position can lose

| | |
|---|---|
| Stop distance | **2.5% from entry** (`HARD_STOP_FROM_ENTRY_PCT`) |
| So a stop-out costs | **≈ ₹9,484** on that COFORGE position |
| Round-trip charges | **≈ ₹181** |
| **Worst case per position** | **≈ ₹9,665** |
| Daily loss cap | **₹40,000** — about **4 stop-outs** |

**Not ₹2,000.** `RISK_PER_TRADE_RS = 2000` is legacy and no longer sizes
anything. If I told you ₹2,000 earlier, that was wrong.

### The stop, and where it lives

**One stop, both paths: 2.5% below entry, fixed, it does not move.**

Until 1 August this was not true. The bot's own entries used 2.5%; every
dashboard BUY used **1%**, seeded off `MIN_STOP_DISTANCE_PCT` — a floor
under the ATR *trail*, whose job ended on 29 July when the trail was
switched off. The manual path was never updated. The operator found it:

> *"what are we using 1% stoploss? from when this came i'm not aware of
> this logic"* — 1 August 2026

He was right. He had never approved it. Measured before changing it —
50,422 entries, buy at close, hold 3 sessions, liquid NSE stocks since
1 April:

| stop | avg/trade | stopped out | winners killed |
|---|---|---|---|
| 1.0% | +0.392% | 72.9% | **51.4%** |
| **2.5%** | **+0.424%** | **45.2%** | **19.7%** |
| 3.5% | +0.489% | 30.7% | 9.8% |
| 5.0% | +0.577% | 16.5% | 3.2% |
| none | +0.634% | 0.0% | — |

**1% was closing half of every winning trade.** Of trades that finished
higher after three sessions, the median dipped 1.05% below entry first.
The stop sat inside ordinary noise.

**Why 2.5% and not 3.5%, which earns more.** Leverage, not returns. At
4X on a ₹4,00,000 position, Dhan's holding coverage hits 20% — their
margin-call line — at a **6.27%** fall. That is the entire runway:

| your stop | loss | room left before Dhan |
|---|---|---|
| **2.5%** | ₹10,000 | **3.77%** |
| 3.5% | ₹14,000 | 2.77% |
| 5.0% | ₹20,000 | 1.27% |
| none | worst in sample −90% | breached |

The extra ₹261/trade a 3.5% stop earns is what you would pay to sit
2.77% from a broker margin call on every open position.

**Revisit this if leverage ever drops to 2X** — the runway doubles and
3.5% becomes the right number. That is the trigger, not a date.

**The candle-low rule is kept.** The stop is whichever is *further* from
entry: 2.5%, or the last closed candle's low. Across 1,445,619 one-minute
candles (27–31 July) a candle low sits more than 2.5% under its close
**64 times — 0.004%**. It is a fire alarm for one violent bar, not a rule
that binds.

- The trail is **off** (`ENABLE_BOT_TRAILING_STOP = False`). It sold the
  winners: 16 of 16 stop-outs dropped under 2% from peak, median 1.06%.
- On a **manual** position the trail only *warns*
  (`MANUAL_POSITIONS_TRAIL_ALERTS_ONLY`). The hard stop still fires.
- **It lives only in the running engine.** There is no stop at Dhan.
  Close the laptop and the position is unprotected. See §4.

Pinned by `tests/test_manual_stop_is_the_hard_stop.py` (17 tests), which
fails if the two dashboard buttons ever disagree with each other or with
the bot again.

### Charges (Dhan, NSE equity)

| Item | Rate |
|---|---|
| Brokerage | ₹20/order or 0.03%, whichever is lower |
| STT (intraday sell) | 0.025% |
| STT (delivery/MTF, both legs) | 0.1% |
| Exchange txn | 0.00297% both legs |
| Stamp duty (buy) | 0.003% intraday / 0.015% delivery |
| SEBI | ₹10 per crore |
| GST | 18% on brokerage + exchange + SEBI |

**Break-even move:**

| Position | Round trip | Move needed |
|---|---|---|
| 1 share @ ₹1,000 | ₹1.07 | **0.11%** |
| 225 shares @ ₹1,686 | ₹181 | **0.05%** |

### MTF carry — your position does NOT close at 15:15

```python
FORCE_SQUARE_OFF_AT_CLOSE = False
```

**Nothing is force-closed.** This changed on 28 July when you moved to
MTF. A position opened Monday is still open Tuesday morning, exposed to
the overnight gap, and accruing:

| | |
|---|---|
| Interest | 0.0342%/day on the **funded** portion (~12.49% p.a.) |
| On the COFORGE example | **≈ ₹96 per night** |
| Pledge fee | ₹15 per stock **each way**, plus GST |

`SQUARE_OFF_TIME = 15:15` now only blocks new entries **when
`FORCE_SQUARE_OFF_AT_CLOSE` is True.** Set it True on any day you want
to be flat by the bell.

### The ceilings

| Limit | Value | Applies to |
|---|---|---|
| `DAILY_MAX_LOSS_RS` | ₹40,000 | the bot's own book |
| `MAX_OPEN_POSITIONS` | 10 | the engine |
| `LIVE_MAX_OPEN_POSITIONS` | 12 | the broker guard |
| `LIVE_MAX_ORDER_VALUE_RS` | ₹5,00,000 | **bot-sent orders only** |
| `LIVE_MAX_ORDERS_PER_DAY` | 30 | **bot-sent orders only** |

### Dashboard vs Dhan app — the differences that cost money

| | Dashboard BUY | Dhan app / website |
|---|---|---|
| Order type | **MARKET** only | your choice |
| Quantity | **1** (`MANUAL_TEST_QTY`) | yours — your ₹1L |
| Entry price | **cannot choose** | limit if you want |
| Modify / cancel | **not possible** | yes |
| Refused if price moved | **>0.5%** and it is blocked | never blocked |
| Stop-loss | engine only, laptop must stay on | **none unless you place one** |
| Value ceiling | ₹5,00,000 | **none** |
| Appears in bot's book | yes — trailing stop manages it | **no** — you manage it |
| Appears in AT THE BROKER panel | yes | yes |

**The one that matters:** a position you open in the Dhan app is
**invisible to the bot's stop management.** The panel will show it, the
bot will not protect it.

---

## 3 · WHAT THE BOT REFUSES TO DO

These are hard refusals. Each one exists because of a specific day.

**It will not start LIVE without a broker.** `TRADING_MODE=LIVE` plus no
Dhan client is a refusal, not a fallback to paper. *A bot you believe is
live and which is only pretending is the worse failure.*

**It will not send an order if the price ran away.** More than **0.5%**
between the panel showing a price and your click, and the order is
refused. You will miss the fastest movers. That is the trade.

**It will not order above ₹5,00,000, past 30 orders a day, or beyond 12
open positions.** These are bug guards, not risk rules — and they apply
**only to orders the bot sends.** Nothing limits what you place by hand.

**It will not resend after a timeout.** A missing reply is not a
rejection. It checks whether the order reached Dhan by correlation ID
first, and if the state is unknown it stops and tells you.

**It will not trade anything but NSE equity.** `EXCHANGE_SEGMENT` is
`NSE_EQ`; a symbol that is not NSE EQUITY gets no security ID, so it
cannot be subscribed to or ordered. Verified every morning.

**It will not invent a number.** An unreadable filing is skipped and the
older quarter is kept — labelled with that quarter's name, so a stale
grade is visible as stale.

**It will not spend AI money it cannot account for.** If the spend
ledger cannot be read, the AI stops calling. The only place in the
codebase that fails closed.

---

## 4 · WHAT THE BOT CANNOT DO — know these before Monday

**There is no stop-loss at the broker.** Confirmed: no `STOP_LOSS`, no
`boStopLossValue`, no bracket order anywhere in the order path. Your
stop lives **only inside the running engine**. If `main.py` stops, or
the laptop closes, **an open position is unprotected.**

**You cannot choose your entry price.** Every dashboard BUY is a
**MARKET** order in MTF. There is no limit price, and no modify — Dhan
exposes `PUT /orders/{id}` but this bot does not call it.

**Clicking BUY twice is safe before the fill, not after.** The request
is a set, so two clicks before the engine acts are one order. After it
fills and clears, a fresh click is a **second real position**.

**A hand-placed order is invisible to the bot's book.** The AT THE
BROKER panel will show it, because that reads Dhan. But the bot's
trailing stop will not manage it. You manage it yourself.

**It cannot order in the pre-open auction.** Dhan accepts orders
09:00–09:08, but a manual request is consumed inside
`process_tick()` and the first tick arrives at 09:15. The pre-open BUY
button is labelled `BUY 09:15` for that reason. For the auction itself,
use the Dhan app.

---

## 5 · THE TIMING TRUTH

**88% of results arrive after 12:30 IST.**

```
before 09:15    5.9%
09:15-11:00     0.6%
11:00-12:30     5.4%
12:30-15:30    39.2%
after 15:30    48.9%
```

**You are not an early bird on results, and nobody is.** The channels
publish after the company files; the market has the filing at the same
moment.

Your only pre-open signal is the Earnings Pro expectation page —
`EXPECTED BULLISH` / `EXPECTED NEUTRAL`, 100% before 09:15, and worth
about +0.14%.

**Roughly 40% of the good chips arrive after the close.** Those you can
trade at the next open with a whole session ahead of you. That is the
one entry with real room, and it is the least measured — the sample was
5 when this was written.

---

## 6 · WHAT IS YOURS TO DECIDE

The bot will not make these choices, and should not.

- **Whether to turn off `ALERT_ONLY_MODE`.** Four live fills is not a
  proven order path.
- **Whether to add a broker-side stop.** It closes the largest hole in
  section 4, and it is a change to live order code.
- **Position size.** Nothing in the bot sizes a manual trade.
- **When to take profit.** `PULSE EXCELLENT` ran to +3.30% above the
  open and closed at +1.32% — it gives back two points from the high.
- **Which of two disagreeing sources to believe.** The CONFLICT chip
  says *look*. It never says who is right, because nobody has measured
  that yet.

---

## 6A · MAINTENANCE — WHAT KEEPS THE MONEY HONEST

*Every item here exists because something went wrong once. Skipping one
costs money, not tidiness.*

### Every trading day, before the bell

| Check | Command | What it costs to skip |
|---|---|---|
| **Access token** | regenerate in Dhan app | Token dies mid-session. Feed keeps running, every broker call fails. Looks like an outage, isn't. |
| **Order route** | `py tools/proxy_check.py` | Orders must leave via the static IP. Wrong IP = every order refused **DH-905**. |
| **Security IDs** | `py tools/verify_master_database.py` | Has already caught **six** wrong IDs. CHOLAFIN was 685 in our file, 19257 at Dhan — an order would have bought a **different company**. |
| **Pre-flight** | `py tools/preflight.py` | Reads the ID proof file and **refuses LIVE** if it is missing, stale, or dirty. |
| **Funds** | `py tools/dhan_account_check.py` | If the funds call fails the token has expired. Everything downstream fails the same way. |

> **Static IP expires 31 Aug 2026.** Renew at staticip.in before then or
> order placement stops dead.

### Every trading day, after the close

| Check | Command | Why |
|---|---|---|
| **Books agree** | `py tools/reconcile.py` | Bot's book vs Dhan's. **Dhan is right.** Diverges whenever you close a bot-opened position by hand. |
| **Slippage** | read `data/fills.db` | `slip_rs` and `slip_pct` per fill. Four LIVE fills so far, 0.00–0.13%. Watch it as size grows. |
| **What the bot refused** | `py tools/refused_review.py` | Whether the entry rules are costing you. Needs a fortnight. |
| **Chip performance** | `py tools/outcome_report.py` | Whether the evidence is worth anything. |
| **AI spend** | `py tools/ai_check.py` | Budget fails closed. ₹22.32 to date. |

### Weekly

- `py tools/build_daily_history.py` — missing bars break ORB levels and
  silence the market-answer chip.
- `py tools/fetch_history.py --days 62 --intraday-only` — minute bars,
  needed for the chip-time measurement.
- `py tools/load_pulse_grids.py --apply` — if you have not run it daily.

### What the bot costs to run

*USD/INR taken from the bot's own pre-market feed: **95.67**.*

| Item | Paid | Expires | Per month |
|---|---|---|---|
| **Static IP** (staticip.in) | ₹200 | **31 Aug 2026** | ₹203 |
| **Earnings Pulse PRO** (8 channels) | ₹1,799 | **27 Jan 2027** | ₹306 |
| **Claude subscription** | $23 ≈ ₹2,200 | monthly | ₹2,200 |
| **Claude API credit** | $5 ≈ ₹478 | one-off, tops up | — |
| | | **TOTAL** | **≈ ₹2,709 / month** |

**≈ ₹129 per trading day.**

AI actually consumed to date: **₹66.05** — the $5 credit lasts a long
time at this volume. It is metered in `data/ai_spend.db` and the budget
**fails closed**.

### What that means the bot must earn

| Position size | Must gain, per month, to break even |
|---|---|
| **1 share @ ₹1,000** (today's setting) | **271%** — impossible |
| **₹1 lakh margin → ~₹3.8L stock** | **0.71%** — one decent day |

At `MANUAL_TEST_QTY = 1` **the bot cannot pay for itself.** That is fine
while you are proving the path works, and it is worth knowing that is
what this month is: **₹2,709 spent to learn whether the panel is
trustworthy**, not to make money.

At full size, ₹2,709/month is **0.71% of a single position** — roughly
half of one `PULSE EXCELLENT` chip's measured edge.

### Renewals — put these in your calendar

| Date | What | If you miss it |
|---|---|---|
| **31 Aug 2026** | Static IP, ₹200 | **Every order refused DH-905.** Trading stops dead. |
| **27 Jan 2027** | Earnings Pulse PRO, ₹1,799 | The 8 channels stop. **Both trusted chips come from them** — the panel goes blind. |
| monthly | Claude subscription | No further development, bot keeps running |
| when exhausted | Claude API credit | AI chips stop; budget fails closed, nothing breaks |

**The first two are single points of failure.** The static IP stops
orders; the PRO channels stop the evidence.

### The four money settings to check before changing anything

```python
MANUAL_TEST_QTY            = 1          # 1 share per dashboard click
MTF_MARGIN_PER_POSITION_RS = 100_000    # if MANUAL_TEST_QTY is None
FORCE_SQUARE_OFF_AT_CLOSE  = False      # positions carry overnight
DAILY_MAX_LOSS_RS          = 40_000     # bot's own book only
```

**Changing any of these changes how much money moves.** Nothing in the
bot will stop you, and nothing will warn you the next morning.

### What has never been tested with real money

- **4 LIVE fills, ever.** All on 31 July. Slippage, partial fills,
  rejections and MTF margin behaviour have not been seen at size.
- **No overnight MTF position has been carried** since
  `FORCE_SQUARE_OFF_AT_CLOSE` was set False.
- **No stop has ever fired at the broker**, because there isn't one.

---

## 7 · THE STANDING RULES

1. **Start before 09:15.** The opening range cannot be rebuilt.
2. **One start, zero restarts.** A restart costs the opening range for
   every stock.
3. **Verify the security IDs every day.** It has already caught six
   wrong ones, including CHOLAFIN listed as 685 against Dhan's 19257 —
   an order would have bought a different company.
4. **After a weekend, start at 07:00.** The catch-up is 40–60 minutes
   of OCR.
5. **Give a measurement a fortnight before acting on it.** Three
   separate rules were built and reverted on 1 August because the data
   said no — an all-caps ticker guard, a hashtag-only rule, and a
   duplicate-event collapse.
6. **Never let a fix that loses a true link ship to fix a false one.**
   *"Losing a true link to fix a missing one is a bad trade."*

---

## 8 · WHEN SOMETHING LOOKS WRONG

**A panel is empty that should not be** → restart the process.
`index.html` reloads from disk every page load; the Python does not.
New page + old process = panels asking for data the server has never
heard of.

**The bot's book disagrees with Dhan** → **Dhan is right.** Stop the
bot first, then `py tools/reconcile.py --apply`. It never places an
order; selling a position the bot imagines it holds would open a real
short.

**An order rejects** → read the message. *Insufficient funds*, *wrong
product* and *market closed* are three different problems and only one
of them is about the code.

**Anything else between 09:15 and 15:30** → write it down. Do not
restart.

---

*This book records what was measured, not what was hoped. Every number
in it can be reproduced with `py tools/outcome_report.py`.*
