<!-- generated: 2026-08-29 09:24 by tools/bot_doc.py -- do not edit by hand -->
# Opportunity Trader — what the bot is, and what it does

**This file is generated.** Every number below is read out of `config.py` and `core/rules.py` when it is written, so it cannot drift away from the running bot. To change a rule, change the code and run `py tools/bot_doc.py --write`.

---

## 0 · The one hard rule

> **Never assume. Keep it simple. This is a trading bot, not a rocket.**

A number with no `n` behind it is an opinion. Show it, count it, and do not let it change a decision until it has earned that.

## 1 · What it is for

> *"Opportunity Trader Bot = only trades when an event or real opportunity arised in markets, NEVER in to random stocks & only long positions."*

An evidence panel with a BUY button. It reads Telegram pro channels, NSE/BSE filings and live prices, puts the reason next to the stock, and waits.

- Short selling: **OFF** (`ENABLE_SHORT_TRADES`) — long only
- Bot may place its own entries: **OFF** (`LIVE_ALLOW_BOT_ENTRIES`)
- Alert-only mode: **ON** (`ALERT_ONLY_MODE`)

## 2 · The money

| What | Value | Where it lives |
|---|---|---|
| Your own margin per position | ₹30,000 | `config.MTF_MARGIN_PER_POSITION_RS` |
| MTF leverage | 4× | `config.MTF_LEVERAGE` |
| Stock value per position | ≈₹120,000 | derived |
| Risk budget per trade | ₹1,500 | **`core/rules.py`** — the only owner |
| Hard stop from entry | 2.50% | `config.HARD_STOP_FROM_ENTRY_PCT` |
| A stop-out therefore costs | ≈₹3,000 | derived |
| Stop for the day after losing | ₹12,000 (≈4 stop-outs) | `config.DAILY_MAX_LOSS_RS` |
| Stop for the day after making | ₹75,000 | `config.DAILY_PROFIT_TARGET_RS` |
| Positions open at once | 3 | `core/rules.py` (engine sizes from the real balance first) |
| Minimum tradable price | ₹50 | `core/rules.py` |

**`RISK_PER_TRADE_RS` has exactly one owner as of 12 August 2026.** It used to be 2,000 in `config.py` and 1,500 in `core/rules.py`, with both live — the engine sized its breakouts from one and the ranker sized its picks from the other.

## 3 · Overnight

- Force square-off at close: **OFF** (`FORCE_SQUARE_OFF_AT_CLOSE`)
- Resting stop at Dhan: **ON** (`BROKER_STOP_ENABLED`)

A position carried overnight has a **Forever Order (GTT) resting at Dhan** at the hard stop. It fires whether or not this process — or the machine — is running.

## 4 · The two ways a trade can happen

Both lanes end at the same `Engine._enter()`, with the same stops and the same position management.

```
A.  ranker  ->  auto_entry.take()  ->  _enter()
       knows WHY a stock is moving; scores it; sizes it

B.  ORB breakout  ->  _try_structural_entry()  ->  _enter()
       watches a price leave its opening range
```

Since 12 August **both require a reason** — `core/rules.py`'s `is_a_reason()`, one definition imported by both. Lane B had never asked.

- Engine requires a named event: **ON** (`core/rules.ENGINE_REQUIRE_REASON`)

## 5 · What must be true before the bot buys

| # | Gate | Number | Owner |
|---|---|---|---|
| 1 | A named event exists — filing, news or published grade | — | `core/rules.is_a_reason` |
| 2 | Results are OUT, not pending | — | `core/results_gate.py` |
| 3 | Grade is allowed | EXCELLENT/GREAT/GOOD | `core/results_gate.py` |
| 4 | Moving, against yesterday's close | ≥3% | `core/ranker.py` |
| 5 | Moving, against today's open | ≥0.5% | `core/select.py` |
| 6 | Money behind the move | ≥2.5× normal | `core/rules.py` |
| 7 | …or, with no published reason | ≥5× normal | `core/rules.py` |
| 8 | Liquid enough to get out of | ≥₹2 Cr | `core/rules.py` |
| 9 | Still near its high | ≥0.5 of day range | `core/rules.py` |
| 10 | Stop is not too tight | ≥0.75% | `core/rules.py` |
| 11 | Stop is not too wide | ≤6% | `core/rules.py` |
| 12 | Reward is worth the risk | ≥2× the stop | `core/rules.py` |
| 13 | No corporate action distorting the price | — | `core/stock_memory.py` |
| 14 | Book is not full | <3 open | `core/rules.py` |
| 15 | Day's loss is under the cap | ₹12,000 | `config.py` |

**The clock.** Early lane from 09:15, ranker from 09:30, nothing new after 15:15.

## 6 · What the bot knows, and whether it may use it

Run `py tools/knowledge_report.py`, or read the **What the bot knows** panel on the dashboard. Three answers, not one:

| Reach | Meaning |
|---|---|
| `DECIDES` | read on the entry path — it can stop or allow a trade |
| `SHOWS` | drawn on the screen — a human may act on it, the bot never |
| `RECORDS` | written, and read by nothing — measurement only |

| Store | Reach | What it is |
|---|---|---|
| Quarterly results (parsed) | `DECIDES` | core/results_gate.py grade_for() -> block_reason() |
| Who reports, and when | `DECIDES` | core/results_gate.py reports_today() |
| Corporate actions (split/bonus/rights) | `DECIDES` | core/engine.py _memory_block_reason() |
| Channel events (results/orders/news) | `SHOWS` | core/watchlist_builder.py -> Row 1; core/ranker.py |
| News stories, and which stocks they touch | `SHOWS` | core/news_impact.py -> dashboard/state.py build_news_impact() |
| Raw channel messages | `SHOWS` | core/telegram_feed.py -> dashboard/state.py build_telegram() |
| Delivery % (churn vs conviction) | `SHOWS` | core/delivery.py -> the stock card |
| Stored feed rows | `SHOWS` | core/feed_store.py |
| Completed trades, with entry context | `RECORDS` | core/trade_memory.py -- its own docstring says 'IT DOES NOT VOTE' |
| Picks and refusals | `RECORDS` | core/decision_log.py -> tools/refused_review.py |
| Every signal, taken and refused | `RECORDS` | core/signal_journal.py -> dashboard build_journal() |

Row counts and freshness are deliberately **not** printed here — they change hourly and would make this document stale by definition. `py tools/knowledge_report.py` has the live numbers.

### Stored is not understood

- AI master switch: **OFF** (`config.AI_ENABLED`)

> **News is being filed, not understood.** With the master switch off no reasoning call is made, so every story becomes a keyword link with `direction = UNKNOWN`. `core/ranker.py` refuses those by name — *"reason is a lookup, not a mechanism"* — so **the ranked entry lane sees no reasons at all** while the news store looks full and fresh.
>
> Measured on 12 August: 6 of 1,991 stories in the previous seven days were reasoned about. The switch went off on 10 August after calls returned *"credit balance is too low"*. The monthly budget is not the blocker — `data/ai_spend.db` shows about ₹106 of the ₹2,500 cap used.

**The learning loop does not vote.** `core/trade_memory.py`, `core/outcomes.py` and `dashboard/chip_stats.py` each measure what happened after a signal and each is deliberately kept off the decision path. That is a choice, not an oversight — acting on a fortnight of data is how a coincidence becomes a rule. It is also the honest answer to *"does it reuse what it learns"*: **not yet.**

## 7 · Exits

- Bot trailing stop: **OFF** (`ENABLE_BOT_TRAILING_STOP`)
- With the trail off, the stop is a **fixed 2.50% from entry** and does not move (`core/engine.py`, `_atr_entry_sizing`).

> Exits tagged `TRAILING_STOP` since 29 July are therefore **hard stop-outs, not trail exits.** `BOT_SPEC.md` reads all 64 as trail exits and concludes the trail is too wide; split at 29 July they are two different regimes — trail on, n=29, −₹643 average; trail off, n=35, −₹2,627 average. There has been no trail to widen since.
- Force square-off: **OFF** at 15:15

## 8 · What the bot must never do

- place an entry of its own while `LIVE_ALLOW_BOT_ENTRIES` is False
- buy a stock with no named event behind it
- resend an order after a timeout without querying by ID first
- report success when the broker never answered
- claim a stop is resting when the API call failed
- treat a silent source as a negative one
- let an unmeasured flag change a tag
- show a number without its `n`

## 9 · Running it

```bash
py tools/nightly.py          # 22:30, unattended, ~25 min
py tools/morning.py          # 08:30
py main.py                   # terminal 1 — trading
py tools/collector.py        # terminal 2 — Telegram
py tools/preopen_gaps.py     # 09:12, not before
```

Dashboard: `http://localhost:8000/board`

**Never run two things that read Telegram at once.** `core/runlock.py` refuses the second — and holds a stale lock for two hours, because it ages locks out rather than checking whether the process is alive.

---

*Superseded by this file: `RULE_BOOK.md`, `TRADING_POLICY.md`, `RULES_TO_TRADE.md`, `TRADE_SELECTION_RULES.md`, `STRATEGY.md`. `BOT_SPEC.md` is kept for its measured chip-edge tables, which are evidence rather than rules.*

