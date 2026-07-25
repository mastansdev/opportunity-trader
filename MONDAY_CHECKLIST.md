# Monday Checklist — 2026-07-27

First live session with the full strategy package. **No code changes
today.** The job is to observe, record, and let the bot produce clean
data. Print this or keep it open beside the dashboard.

> **Today's deliverable is DATA, not profit.** Judge the session on
> whether the machinery behaves, not on the number at the bottom.

---

# ☀️ 08:50 — BEFORE ANYTHING

### 1. Start the 24/7 news engine (if not already running)
```
py run_news_engine.py
```
✅ **Normal:** `[NEWS_ENGINE] Starting 24/7 news engine. Store: ... Poll every 45s.`
then a cycle line every 45 seconds.
🚩 **Red flag:** every source failing with network errors → note it, carry on.
News is advisory; it never blocks trading.

### 2. Start the trading bot
```
py main.py
```

### 3. Read the startup block — these six lines matter

| Line | Normal | Red flag |
|---|---|---|
| `[MASTER_LOADER] Loaded 750 symbols` | 750 | anything less |
| `Universe resolved: 750 symbols` | 750 | large drop |
| `[MEMORY] Stock memory refreshed: N new from NSE, M from BSE` | **any N or M > 0** | **both 0** = exchanges blocking; splits/dividends won't be known |
| `[MEMORY] Price-distorting corporate actions ... will NOT be traded` | a short list, or "none today" | a huge list (>30) = suspect bad parsing |
| `[LEARN] Trade memory active — N past trades remembered` | 0 today (first session) | — |
| `[RECORDER] Recording this session's candles` | present | missing = no data collected, **restart** |
| `[NEWS_BOT] External engine mode` | present | if it says it's polling in-process, the news worker isn't running |

### 4. Open both dashboards
- Trading: **http://127.0.0.1:8000** (use the `?token=...` link from the log)
- News: **http://127.0.0.1:8050** (`py news_dashboard.py`)

### 5. Sanity checks
- **Capital** shows ₹10,00,000, margin used ₹0
- If you see `[PAUSED] New entries are STILL PAUSED` → click **Resume** or it won't trade at all
- Port 8000 error? An old `main.py` is still running — close it first

---

# 🕘 09:00 – 09:14:59 — PRE-OPEN

**The bot must place ZERO trades in this window.** If it trades, stop it
and tell me.

| Watch | Normal |
|---|---|
| `[FEED] Connected to Dhan live feed` | present |
| Heartbeat tick count | rising |
| Stale-tick warnings | a burst at connect is normal (60s grace), then quiet |
| Positions | **0** |

Pre-open prices are indicative and often stale. **Ignore any price you
see before 09:15** — this is exactly the data that poisoned our backtest.

---

# 🔔 09:15 – 09:30 — OPENING RANGE (still no normal trades)

The bot is measuring each stock's high and low. It is **not** trading —
except the two early-momentum slots after 09:20.

| Time | What should happen |
|---|---|
| 09:15 | ticks flow, candles start, **no trades** |
| 09:20 | 5-minute early range freezes (`[ORB_EARLY]` in the file log) |
| 09:20–09:30 | **at most 2** `[EARLY_MOMENTUM]` entries |
| 09:30 | full ranges complete |

### ⭐ The line to watch for at ~09:30

```
[ORB_FIX] SYMBOL range widened 1784.20/1765.00 -> 1792.00/1764.50
          (the tick feed is sampled and had missed real trades)
```

**Count roughly how many of these appear.** This is the fix for the bug
you found — a too-narrow range creating false breakouts.

- **Many (50+):** the sampling gap is large and systematic — very
  important, tell me.
- **A few:** working as expected.
- **Zero:** either the REST snapshot isn't arriving, or the feed is
  better than we thought. Worth knowing either way.

---

# 📈 09:30 – 14:00 — TRADING

### The position ladder — verify it holds

| Time | Max open positions |
|---|---|
| 09:30 – 10:00 | **3** |
| 10:00 – 11:00 | **6** |
| 11:00 – 14:00 | **10** |
| after 14:00 | **no new entries** |

🚩 If you ever see **more than 3 positions before 10:00**, staging has
failed — note the time and tell me.

### Log lines and what they mean

| Line | Meaning | Normal? |
|---|---|---|
| `ORB BREAKOUT / BREAKDOWN` | a trade opened | yes |
| `[EARLY_MOMENTUM]` | 5-min range trade | max 2 all day |
| `[ROTATE] X rotated OUT for Y` | laggard swapped for a stronger name | a few |
| `[NO_PROGRESS] X closed after 30 min` | dead money freed | a few |
| `[NO_TRADE] X ... corporate action today` | **stock memory working** | good |
| `[NO_TRADE] X ... contradicting news` | news gate | occasional |
| `[BAD_TICK] X rejected` | corrupt price blocked | rare, but good |
| `[CIRCUIT_PROXIMITY]` | near a circuit limit | occasional |
| `[DAILY HALT]` | **−₹8,000 hit, trading stopped** | investigate |

### What to observe (write these down)

1. **How many trades by 11:00?** Expect ~5–10. If **zero by 10:30**,
   the filters are too tight — tell me and I'll loosen them.
2. **Are the names in sectors that are actually moving?** Open the
   dashboard heatmap and compare. This is the sector gate's whole
   purpose.
3. **Do losers land near ₹800?** That's the risk cap working. A loss far
   bigger than that is a bug.
4. **Do winners run past ₹1,500?** That's the no-target design working.
5. **Does anything look absurd** — a stock you know shouldn't be traded,
   or a price that looks wrong? Check it against your chart, like you did
   with the ORB ranges. **That instinct found two real bugs.**

### Don't intervene unless something is broken

Let it run. Manual clicks contaminate the data — and Friday's biggest
single loss (APAR, −₹53,100) was a manual click.

---

# 🔚 15:15 – 15:30 — SQUARE-OFF

| Watch | Normal |
|---|---|
| `SQUARE OFF: all positions flattened` | at 15:15 |
| Open positions after 15:15 | **0** |
| `[RECORDER] Session candles saved: N bars` | **N in the tens of thousands** |

🚩 Any position still open after 15:16 → tell me immediately. That is
the leak class we fixed and must not return.

---

# 🌙 POST-MARKET — 5 minutes, do not skip

### 1. What did it learn?
```
py tools/learning_report.py
```
Look at: win rate, avg win vs avg loss, which sectors, which hours.
**It will say "only 1 session — not yet evidence." That's correct.**

### 2. Reconstruct the day honestly
```
py tools/diagnose_news.py          # news health
```
And note down: how many trades, biggest winner, biggest loser, anything
that looked wrong.

### 3. Save everything
```
git add -A
git commit -m "Monday 27-Jul paper session"
git push
```

### 4. Confirm the data landed
```
py -c "from backtest.candle_store import CandleStore; s=CandleStore(); print(s.count('2026-07-27'), 'bars'); print(len(s.symbols_for('2026-07-27')), 'symbols')"
```
✅ Expect **tens of thousands of bars across ~700 symbols.** This is the
day's real prize — the first clean corpus we've ever had.

---

# 🚨 WHEN TO STOP THE BOT

Ctrl+C and tell me if:
- positions still open after 15:16
- more than 3 positions before 10:00
- a single loss much larger than ~₹800
- it trades a stock with a known split/dividend today
- 50+ trades (churn has returned)
- the dashboard shows numbers that contradict your chart

**Otherwise: let it run, and let it be wrong.** A losing day with clean
data is a successful Monday.

---

# WHAT SUCCESS LOOKS LIKE

Not profit. These four:

1. It traded **8–20 times**, in sectors that were genuinely moving
2. The new lines appeared — `[ORB_FIX]`, `[ROTATE]`, `[NO_PROGRESS]`
3. Losses clustered near ₹800; winners were allowed to run
4. `backtest_candles.db` filled with a full session of real candles

Hit those and Monday did its job — whatever the P&L says.
