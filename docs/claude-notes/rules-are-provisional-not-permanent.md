---
name: rules-are-provisional-not-permanent
description: Trade rules change whenever he decides — always read the live code for the current values; quoting an older month's rule is an error
metadata:
  node_type: memory
  type: feedback
  originSessionId: 9fd6931f-938d-4539-ad73-4191c031054a
  modified: 2026-09-04T02:18:47.749Z
---

The bot is moving towards an opportunity-based system, and the rules
change until it works to his ideology. A rule written in August is not
evidence about September.

**AND THE CHURN IS SETTLED, NOT A PROBLEM. 6 September 2026:**

    "until we get our result (profits) we will be changing rules set =
     we settled this already"

So do NOT raise rule churn as instability, do not ask whether a change
is wise because the last one was recent, and do not propose freezing
the set to "get a clean measurement". Changing until it pays IS the
plan. What is owed instead is bookkeeping: say which rule set produced
which day, and never present two sets as one record. The first target
was hit under [[the-friday-rule-set-that-hit-the-first-target]].

**His instruction, 4 September 2026, verbatim:**

    "we may change, modify, delete entry, exit, trailing = trade
     decision part as & when ever required; make sure this statement &
     follow the contemporary rules. if bot/claude opus use aug month
     rules is error when user asked about rules of current Sep-04"

**Why:** entry, exit, trailing and sizing are all under active
revision. On 3-4 September alone the slot halved to Rs 15,000,
`liveness()` gained a direction test and then a coiling-at-its-high
exemption, `BUYING_DRIED_UP` got a peak gate, brokerage became flat
Rs 20, and the entry decision moved onto the tick worker. Any of these
can change again this week.

**How to apply:** when he asks what a rule is, READ THE LIVE CODE and
answer from that — `config.py`, `core/rules.py`, `core/ranker.py`,
`core/auto_entry.refuse_reason()`, `core/engine.py`. Never answer from
memory, from a commit message, or from anything in this memory
directory. Quote the constant and the file it came from so he can
check. If a value here disagrees with the code, the code is right and
this file is stale.

Many gates exist only to fence in a signal that could not be trusted,
and they must retire when the signal improves rather than be defended
on their original grounds. `BREAKOUT_MAX_OFF_HIGH_PCT = 0.25` was the
clearest case: added 18 Aug 2026 because `STRUCTURAL_LONG_BREAKOUT`
measured the break against a 09:30 opening range frozen at 09:30, so
the third re-cross of a dead level read as fresh. The reason source
was broken; the percentage was a fence around it.

Related: [[his-trading-rules]], [[no-fixed-limits-trade-when-opportunity-shows]],
[[verify-the-value-the-live-path-reads]]
