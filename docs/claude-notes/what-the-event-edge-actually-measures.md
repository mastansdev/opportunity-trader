---
name: what-the-event-edge-actually-measures
description: The event is worthless alone; event + already +3% + volume is the whole edge, and capital not opportunity is the binding constraint
metadata:
  type: project
---

Measured 29 Aug 2026 over 18-29 Aug (8 sessions, 444 in-hours events),
per trade, nothing pooled or averaged.

**The event alone is not a signal.** Bucketed by where the stock already
was when the news landed:

| stock was when news landed | n | ran >2% after |
|---|---|---|
| below prev close | 98 | 7 |
| 0 to +1% | 94 | 10 |
| +1 to +3% | 139 | 30 |
| +3 to +5% | 58 | 28 |
| +5% and above | 55 | 26 |

Flat stock + news = nothing. Moving stock + news = ~48%. This is his
rule (move + volume + reason) confirmed, not assumed.

**Volume is a precondition, not a separator.** Of 117 events on stocks
already +3%, only 2 had volume under 1.5x the same stock's own median at
the same clock minute. The move plus the event already implies the crowd.

**The fade exit costs money.** On the 115 qualified trades with a 1.5%
stop and qty = 1500/stop distance: hold-to-close +Rs77,955; best fade
rule (below VWAP) +Rs53,242; `ranker.liveness()` as tuned +Rs29,882.
A breakeven stop after +1% is actively harmful (35W/80L, +Rs28,809) --
it gets shaken out on noise. Giving back a third of peak gain wins far
more often (82W/33L) but caps the big winners: +Rs38,731, best trade
only +Rs3,377 vs +Rs7,721.

**81% of profit came from 10 of 115 trades.** The other 105 made
Rs15,187 between them. Only 23 of 115 cleared his Rs2,500 bar.

**Capital is the binding constraint, not opportunity.** Uncapped needs
Rs17.9 lakh peak. He has Rs431,116, `MAX_OPEN_POSITIONS = 3`.
Seats 3 -> +Rs29,013 (peak capital Rs299,748); 5 -> +Rs35,242
(Rs499,267); 8 -> +Rs56,431; 12 -> +Rs72,936.

**Why:** I proposed a fade exit built on `liveness()` before measuring it
and it was wrong -- `liveness()` is tuned for RANKING (MAX_OFF_EXTREME_PCT
3.0, MIN_RECENT_PCT 0.15) and as an exit it fires within ~11 minutes,
after which the stock made a new high in 98 of 128 cases.

**How to apply:** selection is now a capital problem -- which 3-5 of the
~14 qualified per session -- not a market-wide ranking problem. Before
proposing any exit, measure it against plain hold-with-a-stop on the
qualified set only. See [[operator-work-style]] and
[[verify-the-value-the-live-path-reads]].
