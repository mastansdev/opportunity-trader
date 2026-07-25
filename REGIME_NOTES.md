# Regime Adaptation — evaluation & plan (2026-07-25)

An external suggestion (Grok) proposed a regime-detection layer above the
entry logic. Evaluated below against what we actually measured. Kept the
parts that survive scrutiny; deferred the parts that would add untested
complexity.

## What we're ADOPTING

**1. Measure performance PER REGIME before gating on it.**
This is the single best idea in the suggestion and it matches the
walk-forward discipline we already chose. A strategy that loses in chop
and wins in trend is *fine* — you just switch it off in chop. But you
can only know that if the bench reports results split by regime.
→ **Action: regime tagging in `backtest/`, as OBSERVABILITY first.**

**2. Cheap, robust detectors — ADX + ATR percentile.**
Simple, well-understood, no training data required, hard to overfit.
Correctly ranked ahead of ML by the suggestion itself.
→ **Action: compute and log them; do not gate on them yet.**

**3. Regime persistence / no-flip-flopping.**
Requiring N bars in a regime before switching, and a no-trade zone during
transitions, is a genuinely good practical detail we had not considered.
→ **Action: build into the detector from day one.**

**4. Reduced size in high volatility.**
Consistent with our own risk model.

## What we're DEFERRING (and why)

**HMM / clustering / ML regime classification.**
We have **one** clean-ish day of data. Fitting a Hidden Markov Model to
that would produce a beautiful, meaningless classifier. This is exactly
the "overfit the number of regimes" trap the suggestion itself warns
about. Revisit after 40+ recorded sessions, if simple detectors prove
insufficient.

**A mean-reversion module for ranging markets.**
This is an entire second strategy — new entries, new exits, new
parameters, its own validation burden. **We have not yet validated the
first one.** Building strategy #2 before strategy #1 is proven is how the
previous bot died.

**The generic regime→style table.**
Reasonable textbook mapping, but not derived from our data. Our own
measurements must decide what each regime deserves.

## The honest limitation of regime adaptation

Regime detection **cannot create edge**. It can only tell us *when not to
deploy* the edge we have. Our measured problem is that expectancy per
trade is thin (+0.17R in the best bucket vs ~₹117 charges). Standing
aside in bad regimes improves the average by removing bad trades — real
value — but it does not raise the ceiling.

**Ranked against the other known gaps, I'd put regime adaptation 4th:**
1. Higher-timeframe (daily) trend alignment — total blind spot
2. Entry on retest rather than the breakout candle — mechanical R:R gain
3. Relative strength vs own sector
4. Regime adaptation

## What our own data already says about regimes

We didn't call it "regime", but we measured it. Win rate by hour on
2026-07-24:

```
09:00  34.6%  (n=434)     10:00  11.4%  (n=201)     11:00  51.8%  (n=112)
12:00  32.7%  (n=156)     13:00  36.0%  (n= 25)     14:00  14.0%  (n= 50)
```

A 11.4% hour and a 51.8% hour in the same session **is** a regime shift —
the market changed character mid-morning. That's direct evidence the
concept is real here, and the best argument for building the detector.

It's also, on one day with small buckets, exactly the kind of pattern
that is most dangerous to hard-code. Hence: **measure first, gate later.**

## Plan

1. `core/regime_detector.py` — ADX(14), ATR percentile vs trailing 50
   bars, breadth (already have), with N-bar persistence + transition
   no-trade flag. **Logged and dashboard-displayed, not gating.**
2. Bench reports expectancy/win-rate **split by regime**.
3. After ~20 clean sessions: if a regime shows persistently negative
   expectancy, gate it off (or halve size) — decided by data, not by
   the table above.
