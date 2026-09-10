---
name: what-the-live-stop-and-seats-actually-are
description: How sizing, stop, target and exit actually work after 29 Aug 2026 — and which of that day's findings did not survive out-of-sample
metadata:
  type: project
---

State after 29 Aug 2026. Verified by walking a real trade through the
engine, not by reading constants.

**Sizing.** Share count comes from the MTF margin (Dhan asked per
stock). The STOP DISTANCE then follows: `distance = RISK_PER_TRADE_RS
/ qty`, so the rupee loss is fixed and the width is a consequence
(~2.08%, the same on every stock). `config.STOP_FROM_RISK_AND_SIZE`
turns it off and restores `_cap_by_risk` plus the volatility-scaled
width, both still tested.

RISK_PER_TRADE_RS is 2500 (was 1500) because it now sets the WIDTH,
not the share count.

**Two sizing rules used to be live at once** and nobody had compared
them: on TCS at Rs 3,000 the alert card said 21 shares risking
Rs 2,500 while the engine took 40 risking Rs 5,619. Both paths now
share one rule; `tests/test_the_card_and_the_trade_agree.py` compares
them directly and is the only thing preventing a third recurrence.

**Exit is the trail.** `TARGET_REWARD_BY_REGIME = {}` -- no hard
target, and `core/position_plan.py` reads the SAME dict so the card
cannot print one either. A hard target went on and off the same day:
at 1x risk it capped a Rs 10,800 runner at Rs 2,500, and below it the
trail was booking anyway. `ENABLE_BOT_TRAILING_STOP` is True again,
to be measured forward in paper.

**Turning the trail on also moved the entry WIDTH** until this was
untangled -- that branch sized from a one-minute ATR under a 1% floor,
collapsing every stop to 1.00% and tripling every position.
`_atr_entry_sizing` decides the width first now.

**WHAT DID NOT SURVIVE.** Every parameter measured on 18-27 August --
seats, exits, ordering, a Rs 400 price floor, the reason gate's edge --
was fitted AND validated on the same eight sessions. On 3-17 August,
eleven sessions it had never seen, all of it loses. The 2% fixed stop
was reverted for exactly this (commit e55cc78). Event history begins
3 August, so there are ~19 sessions total: NOT enough to fit anything.
Do not backtest parameters on it; judge forward on the paper record.

**Why:** he pays for this and I spent a day producing tables that
evaporated. The out-of-sample split costs two minutes and should be
the first thing run, not the last.

**How to apply:** before quoting any threshold, execute the live
function and print what it returns. See
[[verify-the-value-the-live-path-reads]] and
[[what-the-event-edge-actually-measures]] (whose per-trade figures are
in-sample and should not be relied on).
