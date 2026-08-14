# Rules to Trade — how a stock qualifies

> **SUPERSEDED — read [BOT.md](BOT.md) for the live rules.**
>
> The worked examples from the 24 July session are still the clearest
> explanation of *why* each gate exists. The thresholds have since
> changed and now live in `core/rules.py`, which `BOT.md` reads.

Every rule the bot applies, in the order it applies them, with a real
example from the **2026-07-24** session for each. Read this to know
exactly how narrow the funnel is and where a stock dies.

Legend:
**HARD** = never overridden, no exceptions ·
**SOFT** = fails OPEN (missing data never blocks a trade) ·
**NARROW** = the rule that kills the most candidates

---

## THE FUNNEL — 750 stocks → about 15 trades

Measured on 2026-07-24 (985 first-time breakout signals):

```
750  stocks watched
     ↓  price / liquidity / data-sanity screens
~600 tradeable at all today
     ↓  must form a valid opening range
 746 ranges built
     ↓  must actually break out (fresh cross)
 985 breakout signals fired
     ↓  top-20 gainers / losers only          ← ~2,800 rejected here
     ↓  relative-strength band
     ↓  not exhausted
     ↓  leading sector
     ↓  volume surge, regime, news, earnings…
     ↓  a free slot (staged 3 → 6 → 10)
~15-20 trades actually taken
```

**Roughly 2% of signals become trades.** That is the design.

---

# STAGE 0 — Is this stock touchable at all?

### 0.1 Minimum price — ₹200 · **HARD**
Under ₹200, a 1-tick move is a large % swing; the noise swamps the signal.
> *Friday: 14 signals rejected on price alone.*

### 0.2 Liquidity — ₹2 crore turnover today · **SOFT**
Turnover = price × volume. A breakout in a thin stock can't be traded in
real life — the spread eats the edge.
> *No volume in the quote → rule does nothing (fails open).*

### 0.3 Tick sanity — reject >20% single-tick jumps · **HARD**
> **Real case: INFY printed ₹1,037 → ₹111 → back, inside one minute.**
> **JLHL moved −80.1% in a minute** (a split, not a crash). In backtest
> that manufactured a fake **+₹145,403 "profit."** Live, it would have
> fired every stop in the symbol. Now rejected before it touches anything.

### 0.4 Frozen feed — 3 identical candles · **HARD**
Circuit-locked or dead feed. Both look the same and both are untradeable.
> *Real case: HFCL printed O=H=L=C=207.01 for 4.5 hours, and the bot
> round-tripped it 12 times at the identical price.*

### 0.5 Circuit proximity — within 2% of a limit · **HARD**
No new entries, and any open position is closed — in **either** direction.
> *Real case: STYL round-tripped SHORT 5× in 11 minutes walking into its
> lower circuit.*

### 0.6 Earnings day · **HARD**
A results reaction is news, not momentum.
> **Real case: APARINDS.** Bought manually at ₹14,610 on results day,
> fell ₹531 in 5 minutes → **−₹53,100**, 70% of the day's entire loss.

---

# STAGE 1 — Is there a valid opening range?

### 1.1 The range: 09:15 → 09:30 · **HARD**
Highest and lowest price in the first 15 minutes. No trades before 09:30
(except the early path, §5).

### 1.2 Exchange correction · **HARD (new)**
The tick feed sends **snapshots, not every trade**, so the bot's range is
always slightly too narrow. It is widened to the exchange's true high/low.
> **Real case: ZENTEC.** Bot saw high 1784.20; the real high was 1792.00.
> Without the fix, price at 1785 looks like a breakout while still
> **₹7 inside** the real range — buying noise and calling it a breakout.

### 1.3 Unreliable range → skip the stock all day · **HARD**
> *Real case: SONACOMS. A ~30s feed gap at 09:15 made its range 3.80
> too narrow, producing a "breakout" that was still inside the real range.*

---

# STAGE 2 — Did it genuinely break out?

### 2.1 Fresh cross only · **HARD**
Fires **once**, on the candle that crosses. Not while price merely sits
beyond the range.
> **Why: without this the bot re-fired constantly. On 2026-07-24 the 10
> slots refilled instantly every time a position closed** — 201 trades.

### 2.2 Clear the line by 0.1% · **HARD**
A close that grazes the boundary is range noise.

### 2.3 Volume ≥ 1.5× recent average · **SOFT**
Real breakouts carry volume; drifts don't.
> *KPITTECH broke out on volume and ran +5.3%. MOIL/TATASTEEL drifted
> across the line on nothing and went +0.2%.*

---

# STAGE 3 — Is it worth trading? *(the narrow part)*

### 3.1 Top-20 gainer (long) / top-20 loser (short) · **NARROW**
> **Rejected ~2,800 of 985 signal-checks on Friday — by far the biggest
> filter.** This replaced first-come-first-served selection, which had
> filled all 10 slots at 09:34 with whatever twitched first — including
> stocks that moved **±0.1% all day** (BAJAJHLDNG +0.0%, WOCKPHARMA +0.1%,
> IMFA −0.1%) — while **GODIGIT (−6%), MOTILALOFS (−3.5%), ACE (+2.3%)**
> broke out to a full book and never traded.

### 3.2 Relative strength 0.4% – 5.0% vs the market · **NARROW, SOFT**
Not "how much did it move" but **"how much more than everything else."**

> **This is the one feature that measurably predicts.** Measured Friday:
> | Relative strength quintile | Win rate |
> |---|---|
> | Q1 weakest | 14.5% |
> | Q2 | 21.4% |
> | Q3 | 26.4% |
> | **Q4** | **39.0%** ← best |
> | Q5 strongest | 34.0% ← *fades* |
>
> Absolute strength did **not** predict (winners +1.10% vs losers +1.32%
> — the losers were *stronger*). A stock rising with the tide tells you
> nothing; one pulling away from the pack has someone acting on it.

### 3.3 Not exhausted — absolute move ≤ 5% · **HARD**
Q5 above is the proof: the *most* extended names underperform.
> *A stock already +10% by mid-morning is a sprinter at the 90-metre mark.
> Friday, the strongest quartile averaged **−₹640 per trade at 31% wins.***

### 3.4 Sector must be leading — top 8 of ~90 · **NARROW, SOFT**
Long only in a top-gaining sector; short only in a top-losing one.
> **Why: Friday's replay traded DATAPATTNS, SUDEEPPHRM, AEQUS — orphan
> mid-caps in no theme at all.** Ranked by the *median* move of each
> sector, so one runaway stock can't drag a sector onto the leaderboard.

### 3.5 Market regime — ≥60% one-sided blocks the fighting side · **SOFT**

### 3.6 No contradicting HIGH news · **SOFT**
Free keyword news is display-only; only paid AI news can block.

### 3.7 One attempt per stock per direction per day · **HARD**
> **Real case: CHENNPETRO traded 9×, CORONA 6×, TIPSMUSIC 6× in one
> session** — in, stopped, back in, each round paying charges.

### 3.8 No re-entry after a stop-out (same direction) · **HARD**

---

# STAGE 4 — Is there room, and how big?

### 4.1 Staged slots · **HARD**

| Time | Max open |
|---|---|
| 09:30–10:00 | **3** |
| 10:00–11:00 | **6** |
| 11:00–14:00 | **10** |
| after 14:00 | **no new entries** |

> **Why: 11 of 27 entries fired in the single 09:34 minute** — the whole
> book committed in the noisiest 60 seconds of the day.

### 4.2 Rotation — evict the weakest for a clearly stronger name · **SOFT**
Challenger must lead by >0.4%. A winning runner is never the weakest, so
only laggards get evicted.
> **Real case: BHARTIARTL (−1.9%, going nowhere) held a slot from 09:34
> to 15:10** while better setups queued outside.

### 4.3 Size: ₹800 risk, ₹2 lakh cap · **HARD**
Quantity = risk ÷ stop distance, capped at ₹2L notional.
> **Real case: APARINDS at ₹14,610.** Old bot: flat 100 shares = **₹14.6
> lakh on one click**. Now: 13 shares. That single cap turns a −₹53,100
> loss into −₹6,900.

### 4.4 Margin must exist · **HARD** (20% MIS, ₹10L capital)

---

# STAGE 5 — The early exception (before 09:30)

A **second, 5-minute range** (09:15–09:20) can be traded from ~09:21 —
but the bar is deliberately higher:

- relative strength ≥ **1.0%** (vs 0.4% normally)
- leading sector required
- **maximum 2 such trades per day**
- burns the stock's one daily attempt

> *Why: waiting for 09:30 makes the opening move — often the day's
> cleanest — untradeable.*

---

# STAGE 6 — Getting out

### 6.1 Stop: ~0.4%, trails up, never down · **HARD**
### 6.2 **No profit target** · **HARD**
> **Tested and proven harmful.** A ₹1,100 target produced the *best*
> win rate of anything we tried — **53.6%** — and the *worst* money:
> **−₹15,714**. Avg win ₹1,020 vs avg loss ₹1,420. You need ~65% wins
> just to break even.
> **MOTILALOFS made ₹12,228 on one trade. A target would have clipped it
> at ₹1,100 and killed the day.**

### 6.3 No-progress exit — 30 min without +0.5R · **HARD**
Dead money loses its seat.

### 6.4 Square-off 15:15 · **HARD**

---

# STAGE 7 — Day-level brakes

- **Daily loss halt: −₹8,000 realized** · **HARD** (now survives restarts)
- **"Stop new entries"** persists across restarts · **HARD**
- **Max 10 concurrent** · **HARD**

---

# WORKED EXAMPLE — one stock, all the way through

**MOTILALOFS, 2026-07-24, SHORT, +₹12,228** (the day's best trade):

| Gate | Value | Verdict |
|---|---|---|
| Price ≥ ₹200 | ₹906 | ✅ |
| Liquidity | large cap | ✅ |
| Tick sanity | normal moves | ✅ |
| Not earnings / circuit / frozen | clean | ✅ |
| ORB range | built 09:15–09:30 | ✅ |
| Fresh cross below the low | yes, 09:36 | ✅ |
| Top-20 loser | −3.5% on the day | ✅ |
| Relative strength | ~2% vs market | ✅ in band |
| Not exhausted | −3.5%, under 5% | ✅ |
| Sector leading down | ✅ | |
| Slot free | 09:36, cap 3 | ✅ |
| **ENTERED** | 220 shares @ ₹906, stop ₹910 | |
| Exit | trailing stop, no target | **+₹12,228** |

And a **rejection** for contrast — **SWANCORP**, aligned and liquid, but
Friday it broke out, immediately reversed and hit the stop: **−₹2,000.**
*Passing every gate does not make a trade a winner. The rules control
losses, not outcomes.*

---

# HOW HARD IS THIS, HONESTLY?

| | Count |
|---|---|
| HARD gates (never overridden) | 18 |
| SOFT gates (fail open) | 7 |
| Signals → trades | ~2% |
| Expected win rate | **~35%** |
| Expected win : loss size | **~2.5 : 1** |

**Two-thirds of trades are designed to lose**, each capped near ₹800. The
system makes money only if the winners run — which is exactly why there is
no profit target.

**Still missing (see BACKLOG.md):** the bot cannot see *yesterday*. It has
no daily-trend filter.
> **Real case: SRF had fallen 10% over two days. The bot bought it long.**
> No rule here catches that. It is the biggest known gap.
