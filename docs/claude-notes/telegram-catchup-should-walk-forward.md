---
name: telegram-catchup-should-walk-forward
description: "Settled 5 Sep 2026 — forward walk, gap fill by post id, and Telegram pushing instead of the bot asking. The results-calendar nag is still open."
metadata:
  node_type: memory
  type: project
  originSessionId: 9fd6931f-938d-4539-ad73-4191c031054a
  modified: 2026-09-05T10:43:04.246Z
---

**Settled 5 September 2026** (commits `bf74f3e`, `2bc8471`). He had
asked at least four times; the last was *"if bot received last data at
22:05 then this morning will start fetching from last night after
22:05:01"*.

**Three separate things had to be true, and only the first was:**

1. **Forward walk** — already done 1 Sep: `since_id` → `min_id` plus
   `reverse=True`, so each pass takes the OLDEST unread posts and the
   watermark advances in order.
2. **Holes in the MIDDLE** — a backward page walk cannot close one,
   because the pages either side of a weekend gap are ground already
   held, so it stops and reports success. Measured: **183 posts
   published and never collected**, every long run of them a weekend
   (RedboxGlobal India lost 76 between Sat 29 and Mon 31 August).
   Fixed by `TelegramFeed.fill_gaps()` / `missing_ids()`, which ask
   Telegram for the missing posts **by id** rather than by page. An id
   that never arrives is asked for three times then dropped (Telegram
   numbers service posts in the same sequence). A hole bigger than the
   channel's own posting rate could produce is not asked for at all —
   that is what keeps @WLPulseBot's shared-conversation id space out.
3. **Push** — Telegram now tells the bot (`NewMessage`). `start()`'s
   two polling threads became ONE, because both drove the same telethon
   client and a held event loop breaks that. Polling stays behind push
   as the floor: Telegram queues nothing for a laptop that is off.

**The web-reader complication was resolved by refusing, not
approximating:** `t.me/s/` serves pages and cannot answer "give me post
3741", so `telegram_web.fetch(ids=...)` returns `[]` and the hole stays
open until the API path can fill it. Never a page nobody asked for.

See also [[never-mix-old-data-with-new-rules]] and
[[verify-the-value-the-live-path-reads]] — every number above was
measured on the live store, not reasoned about.

---

**STILL OPEN, from 1 September:** `morning_ready`'s results-calendar
check BLOCKS on a date stamp alone — *"last refreshed 2026-08-31 -- the
bot will not know which stocks report"* — without asking whether
anything is actually due. Note the original entry claimed results season
was over until late October; that was **wrong** and he corrected it —
Earnings Pulse shows companies reporting most days. The nag is still a
real problem (it teaches him to ignore the one that matters), but the
fix is "ask whether anything is due today", not "assume the season is
closed".
