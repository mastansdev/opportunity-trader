# Post-market discussion agenda -- 2026-07-23 (starts ~16:00 IST)

Captured live during market hours, to work through in full once the
session closes and today's trades are complete. Nothing here has been
acted on yet -- pure notes for the post-close discussion.

## 1. Direction selection needs a market-regime brain

Bot is taking both LONG and SHORT structural entries even on a day
where the tape is broadly falling (654/750 stocks red at one point).
It doesn't currently "know" the broader market is bearish and should
be leaning away from longs (or requiring a higher bar for them).
Needs a full discussion: should overall breadth/regime gate or bias
which side the bot is willing to trade, and how.

## 2. Separate the News Engine from the trading terminal

`news_bot/` currently runs in-process with the trading loop
(`main.py`), adding load to the one process that must never be slowed
down. Needs to become an independent process/service that the engine
reads from (already read-only via `core/news_gate.py`), not something
sharing the same runtime loop.

## 3. Full redesign discussion: qty, stop loss, target, trailing

Current state: flat 100-qty placeholder, ORB-boundary-seeded stop +
0.2% buffer, no fixed target (trailing-stop-only, dynamic). All of
this needs a ground-up discussion now that real trading data exists
to reason from, not just first-principles guesses.

## 4. Max number of open positions

Currently uncapped (131 open positions were sitting concurrently
today). Fine to observe in PAPER mode, but in live trading each open
position ties up real margin -- needs an actual cap tied to capital,
not just the MIS buying-power gate that already exists.

## 5. Give the bot an explicit goal, not "trade every opportunity"

Proposed: a defined daily objective -- e.g. a fixed profit target
(₹50,000/day mentioned as an example) that, once hit, stops the bot
from taking further trades for the day. Right now the bot has no
concept of "enough" -- it just keeps trading every qualifying signal.

## 6. Document/clarify how the bot picks LONG vs SHORT

Operator wants a clear, plain explanation of the actual decision path
that determines whether a given symbol's breakout gets traded as a
long or a short (this is the existing ORB rule -- close above range
high = long, close below range low = short -- but needs to be laid
out clearly, not just implied by the code).

## 7. Dashboard: Long/Short open-position counts + Exit All placement

Next to the Open Positions panel, add: count of open LONGs, count of
open SHORTs, and an Exit All button in that same area. Currently only
each row's own direction is visible -- no aggregate long vs short
split at a glance.

## 8. Stock prioritization -- bot treats every stock as equal

Confirmed wrong per today's data. Needs a real, meaningful way to
prioritize which stocks the bot should weight/prefer among all
qualifying ORB signals, based on the stock's own available data
(sector, liquidity, volatility, news, etc.) -- explicitly NOT a
copy of whatever the previous (failed) bot did. Needs fresh design.

## 9. Core unresolved question: why no profit even with 654/750 falling

If the vast majority of the universe is falling and the bot has
short capability, it should be finding an edge -- but it isn't.
Something in the trade-selection engine is fundamentally off. This
needs a complete, guided refinement session -- operator is open to
researching proven/best-practice approaches (not just patching the
current logic) if that turns out to be the right path.

## 10. CONFIRMED: market movement exhausts by ~10:30, most stocks go range-bound

Operator's own observation, verified against today's actual candle
data (not just taken on faith) -- log-line timestamps 09:16-14:45,
744 real symbols (TCS/INFY excluded from this specific check only,
since both are hardcoded fixtures in `tests/test_engine.py` and
would otherwise pollute the read via the still-open
`core/logger.py` diagnostics.log test-pollution bug).

Average per-candle high-low range: 0.104% of price before 10:30,
0.053% after -- roughly half. Share of symbols essentially flat
(near-zero movement): 19% before 10:30, 72% after -- three out of
four stocks in the whole universe go quiet after 10:30. The movers
that keep going aren't a tiny elite either: the top 25 post-10:30
movers account for ~21% of all remaining movement (today's leaders:
ROUTE, OFSS, CHENNPETRO, WAKEFIT, BLUESTONE, UJJIVANSFB, PVRINOX,
DIACABS, VMM, TANLA) -- a real skew, but moderate, not extreme.

Relevant to the post-close session: the new TOP_N_MOMENTUM_MODE
(locks the top-25-gainers/top-25-losers shortlist at 09:30 -- see
PHASES.md) is already timed right at this regime shift, which is
a point in its favour. But the bot still treats 10:35 identically
to 09:35 in every other respect (entry eligibility, position
management) -- this observation is a real, data-backed case for
giving the bot some time-of-day awareness, not just symbol
selection. Caveat: this read is PARTIAL DAY (through ~14:45, not
full close) and uses log-line timestamps as a proxy for market time
(same ~1-minute-lag caveat documented elsewhere for candle log
lines) -- worth re-confirming on the full close.

---

Since this file was written, `TOP_N_MOMENTUM_MODE` (top-25-gainers/
top-25-losers shortlist + fixed ₹1,000 stop / ₹2,500 target,
replacing the dynamic trailing stop for these trades) was designed,
built, and fully tested for the 2026-07-24 (Friday) session -- see
PHASES.md's own section on it for the full writeup. That's now live
by default; Friday's results become part of what this post-close
session should also review, alongside everything below.

*No other code changes have been made based on this list. This is
the agenda for the after-close working session.*
