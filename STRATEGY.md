# Opportunity Trader — Strategy (live from 2026-07-27)

The complete decision path, and the evidence behind each rule.
Measurements: `FINDINGS.md`. Bench: `backtest/`.

## The edge claim — stated honestly

We do **not** claim to predict stocks. We claim one measured thing:

> A stock **outperforming the market**, breaking out **fresh** (not
> exhausted), continues more often than chance.
> Measured: 14.5% → 39% hit rate across relative-strength quintiles.

Everything else in this document is risk control so that thin edge can
survive costs, variance, and bad days.

---

## 1. Universe & hygiene

- 750 NSE cash symbols, price ≥ ₹200 (`MIN_TRADABLE_PRICE_RS`)
- Reject ticks jumping > 20% in a minute (`MAX_TICK_JUMP_PCT`) — INFY/JLHL class
- Skip: earnings-day names, circuit-proximity, frozen feeds, unreliable ORB windows

## 1b. What the bot KNOWS before it looks at price (2026-07-25)

Two memories, both consulted before any decision:

- **Stock Memory** (`core/stock_memory.py`) — corporate actions with
  ex-dates, pulled from NSE/BSE at startup. A split / bonus / rights /
  demerger / dividend changes the price SCALE, so every %-move and range
  computed against yesterday's close is a lie. Those symbols are refused
  with a loud reason. *This is the JLHL fix: a 2:10 split read as an
  −80% crash.* Informational facts (board meetings) are remembered but
  never veto.
- **Trade Memory** (`core/trade_memory.py`) — every completed trade with
  the CONDITIONS it was taken in (sector, relative strength, hour,
  regime). **Observation only — it has no vote.** Report:
  `py tools/learning_report.py`.

## 2. Entry — every condition must pass

| # | Gate | Config | Evidence |
|---|---|---|---|
| 1 | Fresh ORB cross (transition, not state) | — | stops standing-signal refills |
| 2 | In top-20 gainers (long) / losers (short) | `TREND_RANK_TOP_N` | clock-order was the original sin |
| 3 | **Relative strength in band 0.4%–5.0%** | `RS_BAND_MIN/MAX` | **the one predictive feature** (widened 2026-07-25 — the old band was fitted to corrupted data) |
| 4 | **Intraday move since 09:15 ≤ 5%** | `MAX_ABS_MOVE_PCT` | inverted-U / exhaustion. **Measured from the DAY'S OPEN, not yesterday's close** (fixed 2026-07-25) — a gap is repricing, not exhaustion, and the old reference blocked every gap-and-go all day |
| 5 | Breakout clears margin | `BREAKOUT_MIN_MARGIN_PCT` | grazes = range noise |
| 6 | Volume ≥ 1.5× average (fail-open) | `VOLUME_SURGE_MULT` | conviction |
| 7 | Regime allows the direction | `REGIME_*` | don't fight the tape |
| 8 | No contradicting HIGH news | news gate | — |
| 9 | **One attempt per symbol per direction per day** | `ONE_TRADE_PER_SYMBOL_PER_DAY` | CHENNPETRO traded 9× |
| 10 | No corporate action distorting today's price | `ENABLE_STOCK_MEMORY` | JLHL split read as −80% |
| 11 | Liquidity ≥ ₹2cr turnover | `MIN_TURNOVER_RS` | spread/impact eat thin names |
| 12 | Tick sanity — no >20% single-tick jump | `MAX_TICK_JUMP_PCT` | INFY 1037→111 |

## 3. Staged deployment — never fill the book at once

| Window | Max concurrent |
|---|---|
| 09:30–10:00 | **3** |
| 10:00–11:00 | **6** |
| 11:00–14:00 | **10** |
| after 14:00 | **no new entries** |

`STAGED_POSITION_LIMITS`. On 2026-07-24, 11 of 27 entries fired in one
minute at 09:34 — the whole book committed at the noisiest moment.

## 4. Sizing

- Risk **₹800/trade** (`RISK_PER_TRADE_RS`), notional cap **₹2L**
- Stop ~**0.4%** (`MIN_STOP_DISTANCE_PCT`), ATR-aware (`ATR_STOP_MULTIPLIER` 0.8)
- Peak book ≈ ₹20L notional ≈ ₹4L margin on ₹10L capital

## 5. Exits

- **Trailing stop** (`ATR_TRAIL_MULTIPLIER` 1.2), activates in profit
- **NO fixed target.** Every target tested lost money; the ₹1,100 target
  gave 53.6% wins and −₹15,714
- **No-progress exit**: not +0.5R within 30 min → close, free the slot
- **Rotation**: weakest laggard evicted for a decisively stronger signal
- **Square-off 15:15**

## 6. Governors

- Daily realized loss halt: **−₹8,000** (`DAILY_MAX_LOSS_RS`)
- Max 10 concurrent, no scale-in (pyramiding declined)
- **No daily profit target.** A ₹50k/day goal = 5%/day = structurally
  unreachable, and chasing it forces the overtrading that kills accounts

## 7. Data recording (always on)

`ENABLE_CANDLE_RECORDING` writes every closed candle to
`data/backtest_candles.db`, building a clean multi-session corpus so
every rule above can be re-validated with `backtest/ranked_replay.py`.

---

## Proven vs. assumed

**Proven (repeatedly, mechanism understood):** clock-order selection was
broken; relative strength separates winners; the inverted-U/exhaustion
effect; fixed targets destroy expectancy; sizing ≠ edge.

**Assumed (one day only — validate before trusting):** the exact 0.6%/
3.0%/5% thresholds, staged limits, 30-min no-progress window, time-of-day
effects.

## The honest bottom line

The best configuration tested returned **+0.45% on capital for one day**,
carried by a single trade, on partly-corrupt data. Expectancy per trade
in the best bucket was **+0.17R ≈ ₹136 gross vs ~₹117 charges.**

**This is a structurally sound system with one real signal — not yet a
proven money-maker.** It goes live in PAPER only. The next milestone is
not profit; it is **20+ clean recorded sessions** so these rules can be
judged on evidence instead of one Friday.

## Next (highest value first)

1. **Higher-timeframe alignment** — the bot is blind to the *daily*
   trend. Biggest known gap.
2. **Entry on retest** rather than the breakout candle — mechanically
   better R:R without needing predictive skill.
3. **Relative strength vs own sector**, not just the market.
4. **Regime adaptation** — see `REGIME_NOTES.md`.
