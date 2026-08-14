# Honest readiness assessment — 30 July 2026

You asked for 100% honest. Here it is.

## Overall: **4 / 10**

Scored against **your** stated goal — *"trade through bot ... give
authorisation to bot automation trading using our claude AI api decision
+ evidence + ranking factors"*. Not against "does the code run".

The code is large, careful and well tested. That is not the same as
ready. The gap is not craftsmanship — it is **evidence**.

---

## The one number that decides everything

**The bot has ONE day of recorded trading. And that day's P&L was wrong
until tonight.**

```
paper sessions with fills recorded    1     (30 July 2026)
live sessions                          0
signals journalled                   731    all from that one day
```

Today it reported **+₹9,498**. The real figure was **−₹11,239**. The
sign was wrong, not just the size.

So the honest count of sessions where the bot's performance was measured
correctly is **zero**. Everything anyone believes about whether this
strategy works rests on numbers that were wrong.

That single fact is why the score is 4 and not 7.

---

## Section by section

| Area | Score | Why |
|---|---|---|
| Data collection | **8/10** | 1.08m daily bars, 399 Telegram messages, 247 news stories, results calendar, corporate actions. Genuinely strong. |
| Observability | **7/10** | Dashboard shows what the bot knows. Was 3/10 this morning. |
| Paper execution | **7/10** | Works, models slippage, logs every fill. Fixed tonight. |
| Strategy logic | **5/10** | ORB works. 18 features are switched OFF. |
| Risk management | **5/10** | Stops and caps exist. Position sizing is crude. |
| Live execution | **2/10** | Written, guarded, **never once executed**. |
| Evidence base | **1/10** | One session, and it was mis-measured. |
| AI decision layer | **0/10** | Not started. |

---

## COMPLETE — you can rely on these

**Market data and the universe.** 973 stocks, daily SUBSCRIBE list, T2T
and illiquid names excluded before they reach the feed. 1.08m daily bars
for the 50-day average and volume baselines.

**The ORB engine.** Opening ranges for ~666 symbols, built 09:15–09:30,
saved across restarts. Today it built 666 ranges and survived four
restarts. This is the most proven thing in the codebase.

**Paper execution and the fill log.** Every order records what it wanted
and what it got. 65 fills today with ₹26,806 of modelled slippage. As of
tonight that slippage actually reaches the P&L.

**State that survives a restart.** Open positions, ORB ranges, trailing
stops, entry blocks, and — new tonight — today's closed trades.

**News and Telegram collection.** Four channels polled, images read by
OCR, 224 typed events filed against the right stocks. Order values and
results grades extracted and scored.

**The dashboard.** Three tabs, ranked alerts, 50-a-side movers with the
reasons attached, search across all 973 stocks, a card per stock, and it
now survives the 15:30 close.

**Test suite.** 1,637 tests. Most encode a specific bug that actually
happened.

---

## NEEDS UPGRADE — works, but not enough

**First-come-first-served entries.** *The biggest known defect.* The bot
fills its 10 slots in the order signals arrive. Today it took THYROCARE
at 0.03× volume and refused KSB at 715× because the book was full. 154
"book full" refusals. Measured, understood, **not fixed**. It only
matters once real money is involved — which is Friday.

**Position sizing.** Risk-sized off the stop distance, but no portfolio
view — no sector concentration limit, no correlation check. Ten positions
could all be one theme.

**The live order path.** Written with real guard rails (₹5 lakh per
order, 30 orders/day, 12 positions, 0.5% drift, kill switch). **It has
never sent a single order.** Code that has never run is a hypothesis.

**Broker reconciliation.** Written tonight. Compares the bot's book with
Dhan's and reports mismatches without correcting them. Correct design.
Has never run against a real broker book.

**Index tiles.** `INDEX_INSTRUMENTS = {}` — NIFTY, BANKNIFTY, MIDCAP and
INDIA VIX still have no resolved security IDs. This was your **first
question of the session** and it is still open.

**News→stock quality.** 47% are direct ticker hits and reliable. The rest
are word matches, and every link says direction UNKNOWN.

**Eighteen strategy features are switched off**, including short trades,
bot trailing stops, partial exits, the market regime gate, trend ranking,
sector strength and early momentum. Most were disabled deliberately after
measurement — but it means the running strategy is far simpler than the
codebase implies. Anyone reading the repo would overestimate it.

---

## NOT STARTED

**The AI decision layer — 0%.** This is the centre of your plan and none
of it exists.

```
news stories held        247
stories reasoned about     0
stock links               396
links with a direction      0     every one says UNKNOWN
```

`ANTHROPIC_API_KEY` appears in exactly two places: the morning brief
(optional, never runs) and as an OCR fallback. **No decision, ranking or
evidence-weighing uses a model.** Every score in this bot is hand-written
arithmetic.

Between where you are and *"claude AI api decision + evidence + ranking
factors"* there is: the key, a trust policy, a cost budget, latency
limits, a way to record what the model said so it can be judged later,
and a rule for what happens when it is wrong. None of that is designed,
let alone built.

**After-market orders.** No AMO field in the executor. Manual orders are
tick-driven, so nothing works outside 09:15–15:30.

**Multi-day learning.** `trade_memory` has a schema and almost no data.
Every "learning" claim needs weeks of correctly-measured sessions.

**Digest splitting.** Messages with several stories are skipped whole —
64 today. Safe, but real events are being dropped.

**`core/deal_flow.py`** is imported by nothing. Dead code.

---

## What would move the score

| To | Needs |
|---|---|
| 5/10 | Two weeks of paper sessions with the corrected P&L |
| 6/10 | Ranked entries instead of first-come-first-served |
| 7/10 | The live path exercised — one share, then ten sessions |
| 8/10 | Index IDs resolved, sector concentration limits, AMO |
| 9/10 | The AI layer built, with recorded decisions judged after the fact |

Realistically **6–8 weeks of disciplined sessions**, not days. The
blocker is not code — it is that you need trading days to accumulate, and
they only arrive one per day.

---

## One more honest thing

I was wrong repeatedly today. I told you not to restart when restarting
was safe and cost you four hours. I claimed NSE endpoints were dead;
you disproved it by running the tool. I twice diagnosed a blank page
without checking whether the process was running. I wrote a test that
passed vacuously for hours.

Weigh this assessment accordingly. The measured numbers in it — 65 fills,
₹26,806 slippage, 731 signals, 1 session, 0 reasoned links — are pulled
from your databases tonight and you can re-run every one. **The judgement
around them is mine, and my judgement has been wrong today.**
