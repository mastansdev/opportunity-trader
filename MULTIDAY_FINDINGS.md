# Multi-day findings — 61 sessions, 1,957 trades

Measured 2026-07-26 by `backtest/replay_all.py` over
`data/history_candles.db` (2026-04-28 → 2026-07-24, 11.6M 1-minute
bars from Dhan). This supersedes `FINDINGS.md`, which was one session.

```
GROSS     +Rs   67,996
CHARGES   -Rs  228,792     336% of gross
NET       -Rs  160,796     -16.08% on Rs 10L
22/61 green sessions   max drawdown -Rs 163,410
```

Per trade: **gross +Rs 35, charges Rs 117, net −Rs 82.**

The one-day study implied +0.17R ≈ Rs 136 gross per trade. Across 61
sessions it is **Rs 35**. The Q4 relative-strength bucket was one
Friday, not an edge.

---

## 1. Shorts have no edge. This settles POST_MONDAY_TODO §D.

| Direction | n | Win rate | Gross | Gross/trade | Net |
|---|---|---|---|---|---|
| **LONG** | 922 | 38.9% | **+65,546** | **+71** | −41,993 |
| **SHORT** | 1035 | 41.6% | **+2,450** | **+2** | −118,802 |

Shorts are **53% of all trades and 3.6% of all gross profit.** Rs 2,450
across 1,035 trades is indistinguishable from zero — the bot pays about
Rs 121,000 in charges to harvest it.

The question was "does riding strength work or does fading it work".
The answer is neither cleanly: riding strength works **long only**.
Continuation on the short side is noise at this timeframe.

## 2. The profit lives in a tail the exits never let happen

Gross P&L by outcome size:

```
> 3R        87 trades ( 4.4%)   +Rs 324,603
2..3R       50 trades ( 2.6%)   +Rs  98,663
1..2R      145 trades ( 7.4%)   +Rs 169,078
...
-1..-0.5R  797 trades (40.7%)   -Rs 613,925
```

**87 trades — 4.4% of the book — produced Rs 324,603 of gross, nearly
5× the entire net gross of the system.** The edge is real and it is
entirely in the right tail.

Now look at how trades actually end:

| Exit reason | n | Share | Gross/trade | Net |
|---|---|---|---|---|
| STOP | 1464 | 75% | +42 | −110,281 |
| ROTATE_OUT | 293 | 15% | **−29** | −42,734 |
| NO_PROGRESS | 192 | 10% | +29 | −16,922 |
| **SQUARE_OFF** | **8** | **0.4%** | **+1,260** | **+9,142** |

**Only 8 trades out of 1,957 were still open at the bell, and they
averaged 30× the gross of everything else.**

`STRATEGY.md` says "ride the trend, no target". In practice three
separate mechanisms cut the trade early — a 1.2×ATR trail, slot
rotation, and a 30-minute no-progress timer — and 99.6% of positions
are gone before the close. The design intent and the implementation
disagree.

**Rotation is the clearest single defect: its gross is NEGATIVE
(−Rs 8,509) before charges.** It is not evicting laggards for winners,
it is closing positions at a loss and paying Rs 117 for the privilege,
293 times.

## 3. The opening hour trades the most and earns the least

| Entry hour | n | Gross/trade | Net |
|---|---|---|---|
| 09:00 | 834 (43%) | +13 | −86,212 |
| 10:00 | 704 | +49 | −47,851 |
| 11:00 | 201 | −25 | −28,702 |
| 12:00 | 89 | −74 | −17,037 |
| **13:00** | **74** | **+446** | **+24,357** |
| 14:00 | 55 | +20 | −5,352 |

43% of the book is opened in the 09:00 hour at Rs 13 gross per trade —
one ninth of what it costs to place. 13:00 is the only net-positive
hour, and it is the hour with the fewest trades.

This is consistent with the two best trades of 2026-07-24 both being
entered at 13:50/13:51.

## 4. The relative-strength band is wrong at the bottom

| RS at entry | n | Gross/trade |
|---|---|---|
| 1.2–1.8% | 59 | **−162** |
| 1.8–2.5% | 564 | **−32** |
| 2.5–3.5% | 847 | +62 |
| 3.5–5.0% | 487 | **+87** |

Monotonically increasing. The one-day study found an inverted U (Q5
fades, Q4 is best) and the band was built on it. Over 61 sessions
**there is no inverted U in this range — stronger is better**, and the
lower half of the live band (0.4%–2.5%) is a net negative.

---

## What this means

The system does not have a stock-selection problem. It has a
**cost-structure problem**: ~32 trades a session at Rs 35 gross against
Rs 117 of charges. Break-even needs gross/trade above Rs 117 — it is
3.4× short.

No amount of slightly-better picking closes a 3.4× gap. The only
shapes that can are **far fewer trades**, **far larger winners**, or
both. The tail analysis in §2 says the raw material for "far larger
winners" is already there and is being cut off.

## The overfitting warning — read before acting

Stacking the filters above gives:

```
LONG + RS>=2.5% + no rotation + skip 09/11/12h
315 trades   44.4% win   gross +50,618   NET +13,657
```

Positive — but that is **+Rs 224 a session**, and every one of those
four filters was chosen by looking at these same 61 sessions. That is
in-sample fitting, and the honest expectation out-of-sample is worse.

Treat §1–§4 as **hypotheses with a mechanism**, not as a configuration
to ship. The two that have a real mechanism behind them and the largest
samples are:

1. **Shorts don't work** (n=1035, gross ≈ 0) — the strongest result here.
2. **Rotation destroys value** (n=293, gross negative) — and it is a
   rule we invented, not a market fact.

Those two are worth changing. The hour and RS thresholds need
out-of-sample confirmation first — ideally on sessions this analysis
has never seen.
