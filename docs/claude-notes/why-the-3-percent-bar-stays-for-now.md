---
name: why-the-3-percent-bar-stays-for-now
description: "His 3% entry bar is deliberate and measured-correct; the plan is to lower it only after the bot can link event to momentum, volume and order flow"
metadata: 
  node_type: memory
  type: project
  originSessionId: 4e2a583c-bc67-420a-94ab-5a19438f1c99
  modified: 2026-09-06T07:33:07.194Z
---

**Settled 6 September 2026, in his words:**

> "3% rule is mine & it may avoid the extra burden on bot ... but if we
> keep bar as >1% to last closing price = prev.close ... morning
> immature participants will be active at the very first minute &
> places market orders which will trigger most of the stocks to move
> upside which may fall or trade side ways throughout the day. that
> will spoil our bots ability & trade selection ... but we may reduce
> the bar in future once bot self upgardes how to treat the event &
> link them to momentum, volume surge, orderflow. thats our plan to
> settle"

**HIS NUMBERS WERE RIGHT.** He flagged them "assumed by me"; measured
across eight sessions, per day, nothing pooled:

    up 1%+   50-80% of stocks   (he said ~50%)
    up 2%+   28-49%             (he said ~30%)
    up 3%+   15-28%
    up 5%+    5-10%

So a 1% bar hands the bot roughly 1,500 candidates a day against ~500
at 3%.

**AND THE OPENING-NOISE CLAIM HOLDS.** Stocks up 1%+ in the first five
minutes:

                              2 Sep      3 Sep
    how many                    210        902
    closed still up 1%+         42%        44%
    faded to flat               18%        25%
    ended BELOW yesterday       39%        30%
    ever reached 3%             44%        37%

56-58% did not hold. The 3% bar is therefore not only load control --
it discards about 60% of the opening pool as unproven.

**THE COST OF THE BAR, also true:** the bot can only ever see a move
that is already 3% old, and 3% means different things per stock. SUNTV's
normal day is 1.7%, so 3% is most of it; TBZ's is 5.5%, so 3% is barely
a start. That is the known trade-off, accepted for now, not a bug.

**WHAT "SELF UPGRADES" NEEDS — the parts already exist, the JOIN does
not.**

    event -> payoff     core/opportunity.payoff_weight(), measured per
                        kind (COMMODITY_CYCLE +0.67 ... FDA_APPROVAL
                        -0.80, BUSINESS_UPDATE -0.32 across 123 cases)
    event -> potential  order as % of company, core/cause_effect.py +
                        core/market_cap.py -- the WELCORP shape, the
                        only place "potential to move" is measured
    momentum            ranker.liveness(), alive / fading
    volume surge        SURGE_REASON_MIN_RATIO = 10.0, a reason alone
    order flow          order_flow.still_buying(), already on the ENTRY
                        path -- it can RESCUE a refusal, never condemn

Each is a separate gate ANDed with the others, or a separate weight.
Nothing joins them into "this event, at this volume, with this flow, is
worth X". That join is what lowering the bar waits on, and it needs
data that only started being recorded on 6 Sep -- see
[[what-the-event-edge-actually-measures]] and
[[the-friday-rule-set-that-hit-the-first-target]].

**How to apply:** do not propose lowering the 3% bar as an
optimisation. It is his rule, it is measured correct, and the sequence
is agreed: the join first, the bar second.
