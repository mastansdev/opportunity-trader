---
name: open-work-31-aug-2026
description: "What is still unfinished after the 30 Aug 2026 session, and the Monday start order"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9fd6931f-938d-4539-ad73-4191c031054a
  modified: 2026-08-30T17:54:22.166Z
---

Left open at the end of 30 August 2026 (a Sunday). Tree clean, 5,182
passed / 6 skipped, last commit 45a488b.

**Monday start order** (he asked; his own list had it reversed):
1. `py tools/collector.py` — early, own terminal, leave running all day.
   Catch-up is the DEFAULT (`--no-catchup` disables; there is no
   `--fetchup`). This is the ONLY Telegram writer — `main.py` builds
   `TelegramFeed(client=None)` and logs "This process does NOT collect".
2. `py tools/preflight.py` — ~08:45.
3. `py main.py` — before 09:15. One start, zero restarts.

**AFTER MONDAY'S CLOSE — he approved both, 31 Aug 09:05:**
1. Wire the order-flow divergence exit into the real exit path. It is
   computed and displayed and votes on nothing.
2. Drop ATR_TRAIL_ACTIVATION_MULT from 1.0. Proof it is too high: CDSL
   held since 27 Aug at +Rs 23.90/share, trail arms at 1.0 x ATR =
   Rs 29.16 — Rs 5.26 short, never armed in four days. With
   TARGET_REWARD_BY_REGIME empty and square-off off (MTF), the only
   exit either carried position has is a stop BELOW entry, so as built
   they can only close at a loss. This is the hole behind his "trades
   without booking profit & keep on holding" complaint.

Also after close: `py tools/nightly.py` (it had not been run since
24 Aug — that is why delivery was stale), and the FII/DII fetch is
broken (`no FII/DII method on the nse package`), showing a stale
figure.

Static IP dc-mum-005.staticip.in:443 expired 31 Aug. Harmless while
ALERT_ONLY/PAPER; must be renewed before going LIVE.

**Still unfinished:**
- 4 of the 8 misparsed-results stocks still do not grade. AIIL (+440%)
  and BAJAJFINSV (+3,182%) are implausible WITHIN one basis — cause not
  found. BAJAJHLDNG and COROMANDEL have no comparable pair at all.
  Fixing needs a correct series, not more logic. See [[what-the-basis-column-decides]].
- `feed_watermark` disagrees with the messages table on Day Trader
  Telugu (101 behind) and RedboxGlobal (105). Collection is correct
  (reads MAX(message_id)); the bookmark is what tools read. Cause not
  traced.
- 18 of 1,284 stocks have no volume curve and are refused as
  "unmeasured" — MVELECTRO traded 8.6x its normal day and was refused.
- Delivery store stale 6 days; `AI_ENABLED` stays False by his decision,
  so news carries no direction and `core/ranker.py` refuses it.
- Two candle stores still disagree on volume (median 10.4%); he said
  "leave it until we see monday's report".

**Do not "fix" by inventing numbers.** He has paid for that twice.
Related: [[operator-work-style]], [[verify-the-value-the-live-path-reads]].
