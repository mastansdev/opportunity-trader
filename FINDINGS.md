# Findings — Replay-Bench Study, 2026-07-24 session

Everything here was **measured** on 2026-07-24's real 1-minute candles
(182,265 bars, 747 symbols) using `backtest/`. Read the caveat at the
bottom before trusting any rupee figure.

---

## 1. The bot was selecting by CLOCK, not by quality

The strategy generated **3,894 fresh-cross breakout signals** that day.
It traded **27** — 0.7%. The 10-position cap filled in the first minutes
and whoever crossed first kept the seat all day.

- **11 of 27 entries fired inside the single 09:34 minute.**
- BHARTIARTL (−1.9%, going nowhere) held a slot until **15:10**; ONGC until 15:15.
- Meanwhile GODIGIT (−6%), MOTILALOFS (−3.5%), ACE (+2.3%), CORONA (+2.2%)
  all broke out to a **full book** and never traded.
- Baseline picks included stocks that moved **±0.1% all day** (BAJAJHLDNG
  +0.0%, WOCKPHARMA +0.1%, IMFA −0.1%, EXIDEIND +0.2%).

**Fix shipped:** trend-rank entry priority + slot rotation.

## 2. ABSOLUTE strength does NOT predict. RELATIVE strength DOES.

Of 985 first-time breakout signals: 298 (30.3%) reached +2R before −1R;
614 (62.3%) stopped out first.

| Feature at entry | Winners | Losers | Verdict |
|---|---|---|---|
| Absolute move | +1.10% | **+1.32%** | no signal (losers stronger!) |
| **Relative strength vs market** | **+0.78%** | **+0.38%** | **SEPARATES (69% apart)** |
| Range compression (coil) | 1.206 | 1.161 | no signal |
| Breakout thrust | 0.567 | 0.549 | no signal |
| Close position in bar | 0.769 | 0.691 | weak |

Win rate by relative-strength quintile:

```
Q1 weakest  −0.25%   14.5%   −0.57R
Q2          +0.21%   21.4%   −0.36R
Q3          +0.47%   26.4%   −0.21R
Q4          +0.93%   39.0%   +0.17R   ← best
Q5 strongest +1.64%  34.0%   +0.02R   ← fades
```

**A stock rising with the tide tells you nothing. A stock pulling away
from the pack has someone acting on it.**

## 3. The relationship is an INVERTED U — never "take the top N"

Q5 underperforms Q4. Taking the top 5% by composite score gave **30.8%**
— *worse* than taking the top 30% (36.4%). Ranking harder concentrates
into **exhausted** names.

**Fix shipped:** BAND selection (`RS_BAND_MIN`..`RS_BAND_MAX`), not top-N.

## 4. Fixed profit targets DESTROY expectancy

| Exit style | Trades | Win rate | NET |
|---|---|---|---|
| ride to stop/bell | 42 | 45.2% | **+₹4,509** |
| target 0.50% | 54 | **53.7%** | −₹10,736 |
| target 1.00% | 52 | 38.5% | −₹6,901 |
| **fixed ₹1,100** | 69 | **53.6%** | **−₹15,714** |

The ₹1,100 target produced the **highest win rate and the worst money**:
avg win ₹1,020 vs avg loss ₹1,420. A ₹1,100 target against a ₹2,000 stop
needs ~65% win rate to break even.

**Win rate without risk:reward is a vanity metric.**

Tightening the stop to fix the geometry didn't save it — win rate simply
collapsed (54%→40%) as the two effects cancelled. Only removing the
target worked:

```
tight stop 0.4% + Rs1100 target   89 trades   NET −11,614
tight stop 0.4% + NO target       82 trades   NET  +1,923   PF 1.37
                                  (avg win 1,487 vs avg loss 596 = 2.5:1)
```

## 5. Conviction weighting ≠ edge

Sizing bigger on stronger names raised NET (+1,364 → +3,101) but **win
rate was identical (35.8%)** and profit factor barely moved (1.35 →
1.38). Average notional rose 20% — that's **leverage, not edge**.

## 6. Data corruption is real and dangerous

Three symbols had impossible bars: **INFY ₹1,037 → ₹111 → back in one
minute**; **JLHL −80.1% in a minute**. The replay "shorted" the INFY
ghost for a fake **+₹145,403** — which would have been mistaken for edge.

**Fix shipped:** `MAX_TICK_JUMP_PCT` sanity filter + clean recorder.

## 7. Time of day matters (unvalidated)

```
09:00 n=434  34.6%   |  10:00 n=201  11.4%  |  11:00 n=112  51.8%
12:00 n=156  32.7%   |  13:00 n= 25  36.0%  |  14:00 n= 50  14.0%
```

Large spread, small buckets, one day. **Not acted on** — flagged for
multi-day validation.

## 8. Capital reality

Best run: 42 trades, avg notional ₹1.96L, **peak ₹19.9L exposure / ₹3.99L
margin**, net **+₹4,509 = +0.45% on ₹10L capital**. One trade
(MOTILALOFS +₹12,228) carried the entire day.

---

## THE CAVEAT THAT GOVERNS ALL OF THE ABOVE

**Every number here is ONE day (2026-07-24), on candles scraped from a
log, with at least three corrupt symbols, and the totals were carried by
a single outlier trade.**

What I'd actually trust: the **structural** findings (clock-order was
broken; relative strength separates; the inverted-U; fixed targets are
mathematically bad). Those appeared repeatedly and have sound mechanisms.

What I would NOT trust: any rupee figure, the exact 4.5%/0.6%/3.0%
thresholds, and the time-of-day buckets. Those need many clean sessions,
which is what `ENABLE_CANDLE_RECORDING` now produces.
