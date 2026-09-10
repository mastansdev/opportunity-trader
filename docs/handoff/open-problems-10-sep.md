# Open problems — handoff, 10 September 2026

What the bot did 7–10 Sep: **95 trades, all PAPER, gross −12,768,
charges 8,942, net −21,710.** His money never moved. Detail per trade:
`trades-7-to-10-sep.csv`. Errors: `errors-7-to-10-sep.md`.

Line numbers below were checked on 10 Sep unless marked *(from review)*.
Re-check before editing.

---

## Done on 10 Sep (on `main`)

- **"The switch decides the slot, the loss cap, the broker stop and the
  reconcile."** `TRADING_MODE` (frozen at PAPER) no longer decides
  anything about real vs paper. New orders read the switch
  (`engine._switch_is_live`); existing positions read who opened them
  (`execution._who_opened`). Full suite 5,961 passed.
- **"A pushed picture no longer crashes the reader."** OCR half 1 only —
  see problem 4.

---

## 1. Seat filling — right stock at the right time

His words: seats "filled as instant as possible but not right stocks".
The only problem here that is directly about money.

**Measured (95 trades, from candles, net of charges):**

    move age when bought     trades   net
    move never reached 3%      17    +6,056
    0-15 min old               34    -1,974
    15-30 min old              11    -8,369
    30-60 min old               6    +4,472
    over 60 min old            27   -21,896   <- the whole week's loss

- **39 of 95 entries (41%) landed in the first three minutes**, most of
  the book in one instant (07 Sep 09:16:34 — 8 positions; 08 Sep 09:16:38
  — 9). After that every seat is full, and the only way in is when
  something exits — which is exactly when the bot buys hour-old movers.
- `[SLOTS] No room for a NEW position` logged 44 times (18 / 15 / 11 on
  8 / 9 / 10 Sep).
- Seat count = capital ÷ slot (`engine._position_ceiling` →
  `core/capital.slots`). Paper: 5,00,000 ÷ 50,000 = 10. Live after today's
  fix: Dhan balance ÷ 15,000.
- **Nothing frees a seat from a position that just drifts.**
  BUYING_DRIED_UP booked +68,770 gross on 46 trades; TRAILING_STOP fires
  correctly (−3.06% to −3.43%). But **32 MANUAL_EXIT trades lost 30,444
  gross** — positions drifting down 1–2% with no rule, held all day,
  flattened by hand 15:11–15:22. `FORCE_SQUARE_OFF_AT_CLOSE` is False on
  purpose.
- **The candidate list is stale** — see problem 2. Pricing is live; the
  choice of *which* stock is up to a rebuild old.
- **Why the fingerprint can't answer it directly:** all 95 trades have
  `door`, `move_age_min` etc. = NULL (problem 6a).

**His call, not yours** (`docs/claude-notes/three-rules-the-code-and-his-notes-disagree-on.md`):
ranking is by score in `core/ranker.py`, while his note says volume
multiple. The volume finding did not survive out-of-sample. Don't
"fix" either to match the other without asking.

---

## 2. Execution delay — the board rebuild blocks the main loop

- `main.py:2103-2105` calls `dashboard_state.refresh()` inline in the
  main loop every `DASHBOARD_REFRESH_INTERVAL_SECONDS = 1`
  (`config.py:4050`).
- `dashboard/state.py:820` `refresh()` runs `_build()` (27 panels)
  **synchronously** at line 825.
- Entries are priced from ticks on the tick worker (`_route_entries`,
  `main.py:1558`, called at `main.py:1696`) — but they choose only from
  `_candidates["rows"]`, published at `main.py:2203` **after** a rebuild.

**Measured, `[SLOW] The board took` lines:**

    day      slow rebuilds   median    p90     max
    08 Sep       606          32.6s   42.0s   86.8s
    09 Sep       329          70.7s  103.7s  160.2s
    10 Sep       109          23.7s   54.1s  139.6s

The slowest panel was `ranked` 723 times and `shortlist` 326 times.
Everything else is under ~4s. (An older note guessed the ranker was not the slow part. Measured, it is.)

**Shape of the fix:** move the rebuild off the main loop onto its own
thread first (stops the stall and the lag), then make `ranked` and
`shortlist` cheaper. Measure per panel before optimising
(`snapshot["panel_ms"]` already records it).

---

## 3. Time difference — two separate faults

**a) The loop runs behind real time** (same cause as problem 2).
`HEARTBEAT_INTERVAL_SECONDS = 60` (`config.py:886`), but during market
hours heartbeats landed:

    day      gaps   median   max
    08 Sep    318    69s    123s
    09 Sep    248    91s    196s
    10 Sep     94    65s    141s

That is his "late by ~5 min at times, recovers, never in sync".

**b) The Telegram tab shows posts 5h30m behind** *(from review)*. `at` is
stored UTC-with-offset, `seen_at` naive IST, and
`dashboard/static/desk.html` (~line 1493) prints `r.last_post` raw.
Arrival lag is actually ~0.2 min median — the feed is fast, the clock is
wrong. `telegram_feed._late_by()` already converts correctly via
`core.feed_clock.to_ist`; the displayed field does not (~`core/telegram_feed.py:1748`).

---

## 4. Telegram OCR — pushed pictures lost their text

**Cause:** a pushed photo arrives inside `pump()`'s running event loop,
so `download_media` returned an un-awaited coroutine and
`image_text.read()` failed ("a bytes-like object is required, not
'coroutine'" — 191 times in the logs).

    07 Sep  299 pictures   44 unread
    08 Sep  249 pictures   47 unread
    09 Sep  243 pictures  194 unread
    10 Sep  125 pictures  125 unread   (Day Trader Telugu: 84 of 84)

**Half 1 — DONE:** `core/telegram_client.py` `_photo_bytes()` closes the
coroutine and returns None inside a running loop.

**Half 2 — OPEN: recover the transcripts.** Facts found:
- `core/telegram_feed.py:3185` stores with `INSERT OR IGNORE`, so
  re-fetching never updates an empty `ocr_text`; and `poll()`'s since-id
  floor moves past them. A dedicated re-read + `UPDATE` is needed.
- `TelegramClient.fetch(handle, ids=[...])` fetches named posts and
  returns `photo_data` bytes. Run on the poller thread (loop not running)
  it downloads correctly.
- Wire it into `TelegramFeed.start()`'s `_loop`, after `self.poll(...)`
  (`core/telegram_feed.py:2269`), wrapped so it can never break polling.
- **Trap:** `_read_photo()` (line 1395) caches by URL, and the failed read
  already cached `""` for that URL. Evict the URL before re-reading.
- **Trap:** some pictures genuinely have no text. Remember what was tried
  this process so they are not re-downloaded every 90 seconds.
- **Bound it** (a small batch per pass, recent days only). Three channels
  post daily and delay there costs money
  (`docs/claude-notes/telegram-channel-roles.md`).
- `tools/telegram_ocr.py` already re-reads stored pictures via CDN URLs.
  Check whether it can serve API photos before writing a second path.
- Re-file recovered text through `_file_events()` so the news reaches the
  event store (it is idempotent).

---

## 5. The errors the bot printed

See `errors-7-to-10-sep.md` — each message with count and status (fixed
today / fixed earlier / open / network).

---

## 6. Other open faults (from the 7–10 Sep review)

a. **Trade fingerprint dropped at exit.** `core/auto_entry.py` stamps
   `door`, `volume_x`, `jump_x`, `liveness`, `off_high_pct`, `run_up_pct`,
   `move_age_min`, `reason_kind`, `reason_pct_of_company` on the position.
   The closed-trade row in `core/engine.py` is built from a fixed key list
   that contains none of them, so `trade_memory.record()` stores NULL —
   0 of 95 trades have them. The partial-exit row drops even more.
b. **Log rotation PermissionError** *(from review)*: `core/logger.py`
   (~241) builds a second `FileHandler` on the same file, so the 25 MB
   rollover rename fails with WinError 32.
c. **6 MISSED_STOP_RECONCILED trades, −4,211.** IFCI and NIACL (07 Sep)
   entered 09:16:01 and exited 09:16:47 at −1.74%. Not diagnosed.
d. **`NO_NEW_ENTRIES_AFTER` doesn't exist** — only a config comment.
   `LAST_ENTRY_TIME = "15:15"` is the only cutoff (SPLPETRO bought
   15:00:23, flattened 19 min later).
e. **Stale data files** behind the 4 known test failures (F&O list,
   sector membership) — refreshed by the nightly chain on the laptop.

---

## Agreed order

1. Switch — **done**
2. Telegram OCR — half 1 done, **half 2 next**
3. Board rebuild off the main loop (fixes delay + clock lag + stale
   candidates)
4. Seats: late entries and a rule for drifting positions
5. Fingerprint at exit (so problem 1 can be measured from the store)
6. Telegram clock display, log rotation
