# Trading Policy — Opportunity Trader

*Written 2026-07-24, after the full trading-style revamp. This is the
one document that states, in plain language, exactly how the bot
decides. If the code and this document ever disagree, that's a bug —
fix one of them.*

---

## The goal

Hunt for real opportunity all session, take only high-conviction trades
WITH the market's direction, risk a fixed small amount per trade, bank
profit on winners while letting the remainder run, and know when to stop
— both when the day is lost and when the day is won.

## What it trades

NSE equity only, intraday only, PAPER mode. Universe: ALL ~750 stocks
from `master_database.xlsx`, watched the entire session. (The old
"lock the top 25 gainers + 25 losers at 09:30" shortlist was removed
2026-07-24 — it was part of the fixed-100-qty experiment and threw away
almost every real move of the day, since the biggest movers were usually
quiet at 09:30 and only broke out at 11–12–1 o'clock. Any stock can now
trade the moment it makes a genuine breakout, whenever that happens.)
Quality is enforced by the entry gates below, not by an arbitrary 09:30
snapshot.

## The signal

Opening Range Breakout: the 09:15–09:30 high/low per stock. A 1-minute
candle CLOSE (never a wick) above the range high is a LONG signal; below
the range low, a SHORT signal.

## Every gate a signal must pass, in order

1. **Not paused** by the operator (Exit-All popup's "Stop New Entries").
2. **Price ≥ ₹200** — no low-price stocks, no matter what.
3. **Before 15:15** (square-off) — entries run the full day now; the
   old 14:30 cutoff was removed 2026-07-24 to collect afternoon data.
4. **Not reporting earnings today** (`EARNINGS_CALENDAR`) — an earnings
   gap is news reaction, not momentum; the bot can't tell the
   difference, so it doesn't try.
5. **Feed integrity**: price not frozen, ORB range not corrupted by an
   opening-bell stale gap, not near a circuit limit.
6. **Not already failed today**: a stock stopped out (or circuit-exited)
   in a direction is blocked in that direction for the day. One attempt
   per direction per stock.
7. *(No shortlist gate — removed 2026-07-24. Any of the 750 stocks is
   eligible; quality is enforced by the other gates, not by membership.)*
8. **Market regime agrees**: if ≥60% of the universe is declining, no
   longs (shorts only); if ≥60% advancing, no shorts. The bot never
   fights a one-sided tape.
9. **A slot is free**: max 10 concurrent positions. Full book = no new
   trades until something closes.
10. **The day isn't over**: realized P&L worse than −₹10,000 → done for
    the day (loss switch). Realized P&L past +₹50,000 → done for the
    day (goal met — don't hand it back).
11. **The breakout has conviction**: the close must clear the ORB
    boundary by ≥0.1% of price, not by a few paise.
12. **No contradicting HIGH-priority news** for that direction, and (for
    longs) the stock's **sector isn't in breadth panic**.

Manual buy/short from the dashboard bypasses gates 4, 7–12 — the human
override is deliberate and stays available. Gates 2, 3 and margin are
absolute.

## Position sizing (dynamic, per stock, per moment)

Every trade risks the same rupees, not the same shares:

    stop_distance = max(2.5 × ATR, 1% of price)
    qty           = ₹1,000 / stop_distance     (risk budget)
    qty           = min(qty, ₹50,000 / price)  (notional ceiling)

Volatile stock → wider stop → fewer shares. Quiet stock → tighter stop →
more shares — but **never tighter than 1% of price** (noise floor,
widened from 0.5% on 2026-07-24 after thin stops kept getting clipped)
and never more than ₹50,000 of exposure. If ATR can't be trusted yet
(<5 candles) or qty would be 0, no trade. The 1-minute ATR is used only
as a *widener* for genuinely volatile names; the 1% floor is what
governs a normal stock — thin ATR no longer drives the stop.

## Exits (all dynamic)

- **Trailing stop (chandelier)**: stop = best price since entry ∓
  max(2.5 × ATR, 1% of that best price), recomputed every candle close,
  ratchets only toward profit, never loosens. Does NOT start tightening
  until the trade is at least 1 ATR / 1% in profit (so a fresh trade
  can't be stopped at breakeven). Tick-level check.
- **Trailing target (partial exit)**: once price has moved the WIDER of
  2 × ATR or 1.5% of price in the trade's favor, HALF the position is
  booked and the rest keeps riding the trail. The 1.5% floor (added
  2026-07-24) stops it banking charge-eaten crumbs like the RELIANCE
  ₹30 / HDFCBANK ₹19.80 partials. Fires once per position.
- **Circuit proximity**: position force-closed before a stock locks at
  a circuit limit (untradeable = unacceptable).
- **Square-off 15:15**: everything flattens, no overnight risk, ever.
- **Manual**: per-row EXIT and EXIT ALL (with optional new-entry pause)
  always available.

## What the bot deliberately does NOT do

- No averaging down. No re-entry after a stop-out (per direction/day).
- No pyramiding into winners (operator declined — future test rig).
- No trades under ₹200, over ₹50k notional, after 14:30, on earnings
  day, against the regime, past 10 open positions, past the daily loss
  switch or daily goal.
- No F&O, no overnight, no real orders (PAPER until proven).

## Honest limitations (known, accepted, tracked)

- Daily P&L guardrails read the in-memory session — a mid-session
  restart resets them (trade_log.csv remains the durable record).
- Earnings calendar is only as complete as the operator's weekly paste.
- Paper P&L ignores brokerage/STT/slippage — live results will be worse
  than paper by roughly ₹40–60 per round trip plus slippage.
- When more valid signals fire than free slots, selection is
  first-come-first-served — real prioritization (item 8) not built yet.
- Profitability is NOT proven. This policy is a hypothesis to be
  validated in paper mode over multiple clean sessions before any real
  money is discussed.
