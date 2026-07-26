# Trade Selection — every rule, in the order the bot applies them

Live config as of 2026-07-25. This is the complete list: if a stock is
rejected, it was rejected by exactly one of the numbered rules below.

Two things to understand before the list:

- **Order matters.** The cheap checks run first so the bot isn't doing
  ATR maths on a ₹40 stock 375 times a minute.
- **Silent vs loud.** Most rejections are silent (they'd fire on every
  candle and flood the log). Only the ones marked 🔊 write a visible
  reason to the dashboard's "blocked" panel.

---

## STAGE 0 — Can this stock be traded at all today?

These run before the bot even looks at a breakout.

| # | Rule | Setting | Why |
|---|---|---|---|
| 0.1 | Operator pause is off | dashboard flag | "Stop New Entries" must stick across restarts |
| 0.2 | Price ≥ **₹200** | `MIN_TRADABLE_PRICE_RS` | penny moves are noise, and % stops are meaningless |
| 0.3 | Turnover ≥ **₹2 crore** | `MIN_TURNOVER_RS` | fail-open. Spread + impact eat the edge in thin names |
| 0.4 | Before **15:15** | `SQUARE_OFF_TIME` | checked on the *tick* clock, not the candle label |
| 0.5 | Not an earnings day | `EARNINGS_CALENDAR` | a results reaction isn't organic momentum |
| 0.6 🔊 | **No corporate action today** | `ENABLE_STOCK_MEMORY` | split/bonus/rights/demerger/dividend rescales the price — every %-move vs yesterday becomes a lie. *This is the JLHL fix: a 2:10 split read as −80%.* |
| 0.7 | Price not frozen | `FROZEN_PRICE_STREAK_CANDLES` | a dead feed or circuit lock manufactures fake breakouts |
| 0.8 | ORB window feed was reliable | — | the SONACOMS case: a 30-second gap at 09:15 built a range ₹3.80 too narrow |
| 0.9 | Not near a circuit limit | `CIRCUIT_PROXIMITY_PCT` 2% | direction-agnostic — near *either* limit disqualifies |
| 0.10 | No tick jumped > **20%** | `MAX_TICK_JUMP_PCT` | corrupt data. *INFY printed ₹1,037 → ₹111.* |
| 0.11 🔊 | No blocking news on this symbol | news store | — |

---

## STAGE 1 — Is there a breakout, and is it real?

### 1a. The early-momentum path (**09:20**, the one you asked about)

The full opening range doesn't close until **09:30**. But the strongest
stocks of the day are often already running by 09:20 — a gap-and-go
doesn't wait for us. So there is a **second, shorter range: 09:15–09:20**.

Breaking *that* range can enter from ~09:20, but only for stocks that
clear a **deliberately higher bar**:

| Condition | Early path | Normal path |
|---|---|---|
| Range used | 09:15–**09:20** | 09:15–**09:30** |
| Relative strength needed | **≥ +1.0%** vs market | ≥ +0.4% |
| Must be in a leading sector | **yes** | yes |
| Max such trades per day | **2** | — |

`ENABLE_EARLY_MOMENTUM_ENTRY`, `EARLY_ORB_END`, `EARLY_ENTRY_MIN_RS`,
`EARLY_ENTRY_MAX_POSITIONS`.

Everything that doesn't clear +1.0% still waits for 09:30. This is
capped at 2 on purpose — 09:15–09:20 is the noisiest five minutes of
the day, and this rule is unvalidated.

### 1b. The normal path (from 09:30)

| # | Rule | Setting |
|---|---|---|
| 1.1 | **Fresh** cross of the range — the transition, not the state | — |
| 1.2 | Close clears the boundary by ≥ **0.1%** | `BREAKOUT_MIN_MARGIN_PCT` |
| 1.3 | Breakout candle volume ≥ **1.5×** average | `VOLUME_SURGE_MULT` (fail-open) |

The range itself is **reconciled against the exchange's own OHLC** once
(`ENABLE_ORB_EXCHANGE_RECONCILE`) — the WebSocket feed samples, so our
locally-built high can be below the true high. *ZENTEC: we had 1784.20,
the exchange had 1792.*

---

## STAGE 2 — Is this one of the day's *strongest* stocks?

**This is the stage that fixes "first come = first buy."** Everything
here is about ranking, not timing.

| # | Rule | Setting | Why |
|---|---|---|---|
| 2.1 | **Market regime allows this direction** | `REGIME_BREADTH_THRESHOLD` 0.6 | if 60%+ of the market is falling, no new longs. Don't fight the tape |
| 2.2 | **In the top 20 gainers** (long) / **top 20 losers** (short) | `TREND_RANK_TOP_N` | a breakout outside the leaderboard is range noise, not a trend |
| 2.3 | **Relative strength in the band 0.4% – 5.0%** | `RS_BAND_MIN/MAX` | **the one measured predictive feature** — 14.5% → 39% win rate across quintiles. A *band*, not a top-N: outperforming is what wins, being the *most* extended is what kills |
| 2.4 | **Still trending** — price in the top 35% of today's range (long) / bottom 35% (short) | `STILL_TRENDING_MIN_POSITION` 0.65 | asks *"is it still moving?"* not *"how far has it moved?"*. Replaced a flat 5% ceiling that blocked the day's best trend by construction. **⚠ Unvalidated — see POST_MONDAY_TODO.md §D** |
| 2.5 | Intraday move ≤ **12%** from the day's **open** | `MAX_ABS_MOVE_PCT` | blow-off guard only (APAR-class parabolic). Measured from the open, **not** yesterday's close — **a gap is repricing, not exhaustion** |
| 2.6 | **In a top-8 sector** (long) / bottom-8 (short) | `SECTOR_STRENGTH_TOP_N` | ride what money is rotating *into*, not an orphan mid-cap nobody is bidding for |
| 2.7 🔊 | Sector not panic-flagged (longs) | `SECTOR_PANIC_*` | broad sentiment decline ≠ this stock's problem |
| 2.8 | **First attempt in this symbol + direction today** | `ONE_TRADE_PER_SYMBOL_PER_DAY` | *CHENNPETRO was traded 9× in one session, CORONA 6× — each round trip paying ~₹117* |

---

## STAGE 3 — Is there room, and should something be evicted?

### Staged deployment — the book fills gradually

| Time | Max concurrent positions |
|---|---|
| 09:20 – 10:00 | **3** |
| 10:00 – 11:00 | **6** |
| 11:00 – **15:00** | **10** |
| after **15:00** | no new entries |
| **15:15** | hard square-off, everything flat |

`STAGED_POSITION_LIMITS`, `STAGED_NO_ENTRY_AFTER`.

*Why: on 2026-07-24, **11 of 27 entries fired inside the single 09:34
minute** — the whole book committed to whatever twitched first.*

**Changed 2026-07-25:** the cutoff was 14:00, now **15:00**. The bot
trades the full session and stops opening 15 minutes before square-off.

### Slot rotation — a full book is no longer a closed book

If all seats are taken and a **decisively stronger** signal appears
(`ROTATION_MIN_STRENGTH_EDGE` = 0.4% better relative strength), the
**weakest current holder is closed** to make room.

*Why: on 2026-07-24 GODIGIT −6%, ACE +2.3% and MOTILALOFS −3.5% all
broke out to a full book and were simply dropped.*

### Daily guardrails

- Realized loss ≤ **−₹8,000** → no more entries (`DAILY_MAX_LOSS_RS`)
- Open positions are still managed normally after a halt
- Realized profit ≥ **+₹30,000** → no more entries
  (`DAILY_PROFIT_TARGET_RS`, set 2026-07-26). A **ceiling, not a
  target**: it can only make the bot trade less, never harder. Open
  positions are still managed normally.
  *(This list previously said no such switch existed — it did, at
  ₹50,000.)*

---

## STAGE 4 — Sizing

| Item | Value |
|---|---|
| Risk per trade | **₹800** (`RISK_PER_TRADE_RS`) |
| Quantity | `₹800 ÷ stop distance` |
| Notional cap | **₹2,00,000** (`MAX_NOTIONAL_PER_TRADE_RS`) |
| Stop | max(**0.4%**, 0.8 × ATR) |

*The cap is what turns a manual APAR click from 100 shares / ₹14.6L
notional (the ₹53k loss) into ~13 shares / ₹1.9L.*

---

## STAGE 5 — Exits

| Rule | Setting |
|---|---|
| **Trailing stop**, 1.2 × ATR, activates in profit | `ATR_TRAIL_MULTIPLIER` |
| **No fixed target** | every target tested lost money — the ₹1,100 target gave 53.6% wins and **−₹15,714** |
| **No-progress exit**: not +0.5R within 30 min → close, free the slot | `NO_PROGRESS_MINUTES/R` |
| **Rotation-out**: evicted for a stronger signal | `ROTATION_MIN_STRENGTH_EDGE` |
| **Hard square-off 15:15** | `SQUARE_OFF_TIME` |

---

## Summary — the one-paragraph version

A stock is traded if it is **liquid, over ₹200, clean of corporate
actions and earnings**, makes a **fresh, volume-backed break** of its
opening range (09:20 for the strongest two, 09:30 for everyone else),
is **among the day's top 20 movers in a top-8 sector**, is
**outperforming the market by 0.4%–5%**, is **still holding near the
day's extreme**, hasn't already been tried today, and there is a **free
seat** — or a weaker holding worth evicting for it. It is sized to risk
**₹800**, trailed with no target, cut if it goes nowhere in 30 minutes,
and flat by **15:15**.
