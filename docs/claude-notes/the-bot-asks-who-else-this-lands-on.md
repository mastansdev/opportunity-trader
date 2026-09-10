---
name: the-bot-asks-who-else-this-lands-on
description: "core/sector_impact.py, built 6 Sep 2026 — the self-upgrading memory he has asked for since the start: an event, who it hits, and what each of them did"
metadata: 
  node_type: memory
  type: project
  originSessionId: 4e2a583c-bc67-420a-94ab-5a19438f1c99
  modified: 2026-09-06T08:19:21.714Z
---

**What he asked for, and why, 6 September 2026:**

> "bot must have self upgrading ability thats the reason i asked since
> starting to create brain memory & linkage to recall whenever
> required. all details must saved in database with their respective
> stocks not in another stock or another info"

> "recent ultratech announced its wire & cables capex. then bot needs
> to check ultratech business (positive to neutral or non event too
> until the real business lands) + wires & cables business companies
> (for this sector its negative update)"

**BUILT: `core/sector_impact.py`, `tools/record_sector_impact.py`.**
One row per stock per event: day, business, entrant, symbol, role,
and THAT STOCK'S own move/high/low. The headline is the LINK, never
filed as that stock's own news.

His example, as recorded:

    2026-09-01  ULTRACEMCO entered WIRES   itself -0.44%  5 of 7 fell

    KEI     -6.83%   POLYCAB -5.82%   RRKABEL   -2.00%
    APARINDS -1.71%  DYCL    +9.98%   KEC       +0.12%   UNIVCABLES -0.22%

DYCL rose on a cable order of its own. The memory records what each
stock DID, not what the theory predicted — that is the point of per
stock rows.

**THE RULE.** A business named in the headline that the announcer is
NOT already in. CEMENT drops out on its own because UltraTech is a
cement company. 11,306 events → 55 entries → 425 company-days.

**THREE FIXES FOUND BY RUNNING IT OVER REAL EVENTS, not the example:**

- *A mention is not an entry.* First cut gave TCS entering METRO,
  PURVA entering MUMBAI. I had said no expansion-word list was needed;
  wrong — his own headline says "COMMENCES COMMERCIAL PRODUCTION".
  `ENTRY_SIGNALS` now requires one.
- *Adjacent tags are one market.* "...WIRES & CABLES PLANT AT BHARUCH
  SUPPORTING INFRASTRUCTURE" pulled in 23 builders and reported 30
  incumbents. Tags now join only while touching in the text.
- *A split is not a fall.* Reported an incumbent at -50.45%; KIRLPNU
  went 1,534.30→760.20 on a 1:2 split, prev_close unadjusted. Past 35%
  is refused and said out loud.

**IT TRADES NOTHING** and a test enforces that no trading file imports
it. Long-only means the side it usually finds cannot be acted on; the
MIRROR case — an event GOOD for a sector — is the tradeable one and
the bot cannot see either today.

**A CLAIM I WITHDREW.** why(symbol="KEI") returns UltraTech's launch
as a reason, direction UNKNOWN, weight 0.6 — a competitor's expansion
read as a reason to be interested in the victim. I claimed it could
reach a buy and could NOT show it: the 3% and volume gates refused KEI
all three days, and two attempts to size the frequency produced
numbers that were my own detectors misfiring (383 counted card
prefixes as company names; 106 were correctly-filed events). He asked
me to justify before building and the justification failed, so no gate
was added. See [[verify-the-value-the-live-path-reads]].

**Next, when there is enough recorded:** the join he described —
event → momentum → volume surge → order flow. Every part exists
separately (payoff_weight, order % of company, liveness, still_buying,
the 10x surge); nothing joins them. See
[[why-the-3-percent-bar-stays-for-now]].
