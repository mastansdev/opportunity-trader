---
name: three-rules-the-code-and-his-notes-disagree-on
description: "Found 6 Sep 2026 auditing the live path against his rules — a short button, the ranking order, and a moved premise. His call, not mine."
metadata: 
  node_type: memory
  type: project
  originSessionId: 4e2a583c-bc67-420a-94ab-5a19438f1c99
  modified: 2026-09-06T02:54:55.043Z
---

He asked "are you sure bot is safe & trade as per our rules". Checked
by EXECUTING each live value, not reading constants. Everything in
[[his-trading-rules]] held except these three. **None is changed** --
each is either his own past decision or a control he built on purpose.

**1. A manual SHORT can bypass long-only.** `ENABLE_SHORT_TRADES` is
False and the bot cannot short -- but that guard sits only inside
`engine._try_structural_entry` (the single occurrence in the file).
`POST /api/short/{symbol}`, the per-row button on the Top 50 Losers
table, never checks it. Operator-authenticated, so nothing shorts
unless he clicks. Offered to gate it; he has not said yes.

**2. Ordering is by score, not volume multiple.** His rules note says
"ordered by volume multiple, not score". Live sort in `core/ranker.py`
is `(state == "fading", -score)`. The volume-ordering finding was
measured 18-27 Aug and did NOT survive the eleven sessions it had not
seen, so it was reverted -- the CODE is probably right and the NOTE is
stale. Do not silently "fix" either to match the other; it is his call
which one is the rule. See
[[what-the-live-stop-and-seats-actually-are]].

**3. `ONE_TRADE_PER_SYMBOL_PER_DAY = False` on a premise that moved.**
His own decision, 29 July: "Remove stocks trading rule of 1 side 1
time." The stated reasoning was "the stop today is 2.5% HARD, trail
off entirely". Today the trail is ON and `FIXED_STOP_PCT` is 3.0. This
flag only governs re-entry after a stop-out in the structural lane --
his one-stock-one-trade-a-day rule IS enforced on the lane that
actually buys (`auto_entry.py`, and a manual sell locks the name too).

**Why:** each is a real gap between what he believes and what runs,
and all three came from executing rather than reading. Two of them are
in the repo's own comments as deliberate operator decisions, so
changing them would be undoing him.

**How to apply:** when he asks whether the bot follows his rules, run
the values and name the disagreements plainly rather than reporting a
clean bill. See [[verify-the-value-the-live-path-reads]].
