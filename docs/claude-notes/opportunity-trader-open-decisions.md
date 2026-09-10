---
name: opportunity-trader-open-decisions
description: "Opportunity Trader — decisions the operator made on 12 Aug 2026, and the ones still open"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9fd6931f-938d-4539-ad73-4191c031054a
  modified: 2026-08-12T12:21:37.141Z
---

**Decided 12 August 2026** (operator chose, in chat):

- Overnight protection: **resting stop at Dhan**, not forced square-off.
  `BROKER_STOP_ENABLED = True`. The overnight hold is the strategy, so
  protect it rather than abolish it.
- Entry lanes: **keep both**, but the ORB lane must also require a
  reason. Implemented as `core/rules.is_a_reason()` +
  `Engine._no_reason_refusal()`, switch `rules.ENGINE_REQUIRE_REASON`.

**Decided 18 August 2026** (operator, in chat):

- **Non-MTF = no buy.** "BY SEEING THAT ALERT I'LL GIVE COMMAND BUY X
  SHARES IN MTF (INCASE NON-MTF - NO BUY)". Enforced in
  `core/telegram_desk._mtf_check` before the quote is offered. Three
  answers, not two: eligible / not eligible / **could not be asked** --
  the third is reported in those words and never read as a pass.
- **Alerts go to Telegram; execution only after his YES.** Wired
  18 Aug: `engine.on_alert = telegram_desk.push` in `main.py`. Capped at
  `PUSH_MAX_PER_DAY = 25` because the engine wrote 200-360 alerts a day
  through 12 August.

- **AI stays OFF.** "AI will be OFF as of Now. once bot starts trading &
  earns. AI will be started." Do not propose turning it on again until
  the bot has traded profitably. `AI_ENABLED = False`.
- **He trades the SAME Dhan account manually, during the session.**
  18 Aug: 2 open MTF positions of his own (PARAS 50, NEOGEN 50) plus 7
  delivery holdings, `utilizedAmount` Rs 1.2 lakh. So `availabelBalance`
  is what is left AFTER his trades, not the size of the account.
  `sodLimit` (Rs 2,14,747 on 18 Aug) is the day's limit;
  `collateralAmount` Rs 8.49 lakh sits behind it.

**His stated roadmap (NOT built, do not assume any of it exists):**

- **F&O buying, 1 lot.** The whole repo is NSE cash: `NSE_EQ` segment,
  `data/master_stocks.csv` holds equities only, no lot sizes, no expiry,
  no option chain, no F&O margin model. This is a new segment, not a
  setting.
- **Zero manual input, bot self-learns and sizes from "stock underlying
  strength".** Today every learning store is deliberately severed from
  the decision path (see the open question below) and sizing comes from
  `RISK_PER_TRADE_RS` + `core/mtf_margin.py`.

**Still open:**

- **Does the learning loop get a vote?** `core/trade_memory.py`,
  `core/outcomes.py` and `dashboard/chip_stats.py` each measure what
  happened after a signal and are all deliberately severed from the
  decision path. This was the operator's original question. Answer today
  is "no, by design". Visible via `py tools/knowledge_report.py` or the
  "What the bot knows" panel (POST tab).
- **Retire the `ONE-OFF` warning** — it was set on n=25 at −1.61% and is
  now n=109 at +0.54%. Still open from BOT_SPEC's list.
- **`ENGINE_REQUIRE_REASON` needs re-measuring at n=20.** On the 134
  recorded trades the gate would have refused the 49 breakeven ORB
  entries and kept the 7 losers. Kept ON because n=7 proves nothing and
  the results_grade column was NULL on all 134 rows. If it still says
  that at n=20, turn it off.

**The real problem, measured from `data/trade_memory.db` (134 trades,
10 sessions, −₹81,530 total):** the bot's own ORB entries were roughly
break-even (n=62, +₹2,982). The losses came from `ADOPTED_FROM_BROKER`
(n=19, −₹69,766) and manual dashboard buys (n=52, −₹15,786). Since the
trail was disabled on 29 July the stop is a fixed 2.5% and only 20% of
stopped trades were ever in profit — an **entry quality** problem, not
an exit one.

See [[operator-work-style]] and [[opportunity-trader-architecture]].
