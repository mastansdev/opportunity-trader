---
name: never-mix-old-data-with-new-rules
description: "Do not tune a rule using trades taken under a different rule set, and never average across stocks or lanes"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9fd6931f-938d-4539-ad73-4191c031054a
  modified: 2026-08-31T07:07:45.105Z
---

Two bans, and he has had to state them repeatedly:

**No averaging or pooling.** Never a median or mean across stocks or
across trades. Measure each stock against ITSELF (its own ATR, its own
normal volume, its own history) and report COUNTS, not distributions.
"22 of 52 trades reached a quarter of their own ATR" is allowed.
"median winner travelled 0.19 x ATR" is not.

**No mixing regimes.** The bot's rules, lanes and trading style change
as it evolves toward the goal. Data produced under the OLD rules does
not describe the NEW ones, and tuning a new parameter on old trades is
worse than having no number at all.

**Why:** on 31 August 2026 I set ATR_TRAIL_ACTIVATION_MULT from 51
winning trades. He checked: 28 were ORB/STRUCTURAL_LONG_BREAKOUT, 20
were his own dashboard clicks, 2 adopted -- and exactly ONE came from
RANKED_SETUP, the opportunity lane the bot now trades. "these stocks u
told on atr is utter flopped trades which were traded purely on orb
trades ... do not mix or confuse things ... do not mixup & make me
frustate."

**How to apply:** before quoting any measurement, state which lane and
which rule set produced it, and check that it is the lane under
discussion. When the right population has too few trades -- the
opportunity lane had FIVE in its whole history -- say so and mark the
number PROVISIONAL in the code. Do not borrow a population.

Related: [[operator-work-style]], [[the-one-switch]],
[[verify-the-value-the-live-path-reads]].
