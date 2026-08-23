# The plan, 22 August 2026

Written after a full day of measurement. Every number here was
measured on this bot's own data; anything unmeasured is marked as
such. Regenerate the rule list with `py tools/bot_doc.py --write`.

---

## The principle

> "these scores, grades were self assigned & neither stocks nor NSE
>  works as per our scoring right?"          -- operator, 22 Aug 2026

He is right, and the measurements agree with him. Sort the day's list
by the bot's OWN SCORE and it returns -Rs 68 a trade, worse than a
random draw at -Rs 226 being beaten by nothing at all. Sort the same
list by VOLUME AGAINST THE STOCK'S OWN NORMAL and it returns +Rs 565.

The difference is not cleverness. It is that volume is a FACT the
exchange counts, and the score is an opinion this repository invents.

**Rule: a decision may be built on what the exchange publishes.
Anything we assign ourselves may inform, rank ties, or explain -- it
may not decide.**

Observable, in order of how much they have earned:

| fact | source | measured |
|---|---|---|
| volume vs the stock's own normal | exchange | +Rs 565/trade sorting the list |
| price | exchange | decides what a fixed quantity can pay |
| the filing itself | NSE | 602 a day, 78% were being discarded |
| turnover / ADV | exchange | sets what size can get out |

Self-assigned, and none has earned a decision:

| ours | measured |
|---|---|
| ranker score | -Rs 68/trade ordering its own list |
| channel grade EXCELLENT/GOOD | vanished once entry came after the news |
| AI verdict / market answer | -Rs 407 and -Rs 636 a trade |

---

## What is settled

1. **The bot narrows well.** 1,299 signals -> ~23 alerts. Those 23
   averaged +Rs 73 against -Rs 122 for a random stock the same day.
2. **It could not order them.** 23 names spanning +4.78% to -3.05%,
   seats filled by arrival. Fixed 22 Aug: heaviest volume first.
3. **No exit rule helps.** Targets at 7 widths, breakeven stops at 5
   triggers, profit-locking trails at 9 combinations -- every one lost.
   Stop widened to ATR x 2.0 on measurement; nothing else added.
4. **Public news is priced.** Entering AFTER an event is public:
   -Rs 268 a trade. The edge is in the volume behind the move, not in
   the sentence explaining it.

## What is not settled

- The volume ordering rests on **n=45**, and 7 August was 40% of the
  profit. Direction is solid; size is not.
- Rank 1 is WEAKER than the top 3. It is a coarse sort.
- The bot's own lifetime record is **66 trades**. Too few to judge.

---

## Monday 24 August

PAPER. Armed. Configuration as committed:

- entry from 09:30, ranked lane, reason required, volume >= 2.5x
- seats to the heaviest volume, score breaks ties
- 3 seats, Rs 1.2 lakh each, fixed rupees
- stop ATR x 2.0 (floor 0.75%, ceiling 6%)
- no target, no trailing, no breakeven, no rotation
- holdings watch reporting on the nine Dhan positions

**Record, do not change.** One clean session on a bot that is not
78% blind is the first honest data point this project has had.

## The test that decides the next step

After 5 sessions (~15 trades), compare:

- the bot's picks vs the market's own drift that day
- the top-volume seat vs the others
- charges paid vs edge captured

**Go wider** if the picks beat drift and the volume sort holds.
**Go narrower** -- alert only, operator picks -- if the ordering
collapses on live data.

## What would make it feasible

At +Rs 565 a trade the arithmetic works; at +Rs 12 it does not.
The gap is entirely in ordering, not in finding. So the work is:

1. more observable features to sort by -- delivery percentage, order
   book imbalance, the first 15 minutes' turnover shape
2. **never** a self-assigned score deciding a seat again
3. fewer, larger positions -- charges are Rs 38 against an edge that
   has to clear them

---

## Honesty log, 22 August

Four measurements were wrong before they were caught, all the same
fault -- the test seeing what the bot cannot:

1. a flat 2.5% stop the bot does not run
2. a rule paid for a 2% move that happened before entry
3. seats given to the day's best performers, chosen after the close
4. buying on news that had not yet arrived

Every one looked like a discovery. Any future finding gets a
look-ahead check before it reaches this file.
