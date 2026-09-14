---
name: telegram-push-breaks-ocr
description: "Telegram push delivers photos inside a running event loop, so download_media returns an un-awaited coroutine and every pushed picture loses its transcript"
metadata: 
  node_type: memory
  type: project
  originSessionId: 16056bf4-7288-47a5-b025-94575658f3a9
  modified: 2026-09-10T10:33:33.242Z
---

**Found 10 September 2026.** He reported "Telegram OCR Failed". In the
collector log, 119 times in one morning:

    WARNING: [OCR] Read failed: a bytes-like object is required, not 'coroutine'

Tesseract is fine -- 5.5.3.20260724, found at
`C:\Program Files\Tesseract-OCR\tesseract.exe`. The bytes never arrive.

## Root cause

`core/telegram_client.py:116`, in `_photo_bytes()`:

    loop = getattr(client, "loop", None)
    if loop is None or loop.is_running():
        return client.download_media(message, file=bytes)   # a coroutine

`pump()` runs `client.loop.run_until_complete(sleep(90))` so Telegram
can PUSH posts (the 5 Sep change he asked for: "if telegram tells bot
to check then it will be easy"). A post arriving during that sleep is
dispatched **inside the running loop**, so `loop.is_running()` is True
and this hands an un-awaited coroutine back to a SYNCHRONOUS caller.

`_shape()` puts it in `record["photo_data"]`, `_store()` passes it as
`blobs[0]` to `_read_photo(..., data=...)`, and `image_text.read()`
dies on it. The docstring's claim -- that telethon "hands back the
coroutine untouched ... which is what lets asyncio.wait_for put a bound
on it" -- is true only for a caller that can await. None of these can.

Telethon is 1.44.0, so `client.loop` exists; the `loop is None` arm is
not the one firing.

## Damage

Every picture that arrives by PUSH loses its transcript. Ones that
arrive by ordinary poll are fine. Push now delivers nearly everything,
so it got worse each day:

    07 Sep   299 pictures    44 unread   (14.7%)
    08 Sep   249 pictures    47 unread   (18.9%)
    09 Sep   243 pictures   194 unread   (79.8%)
    10 Sep   125 pictures   125 unread  (100.0%)

10 Sep, Day Trader Telugu: **85 messages, 84 pictures, 84 unread, and
84 carry no text at all** -- the whole day's content from the channel
that posts market-hours news as screenshots.

**It does not recover on its own.** `poll()` uses `skip_known=True` and
a floor of `_newest_stored_id()`, so a message stored with an empty
`ocr_text` raises the floor and is never revisited. Only `catch_up()`
(`skip_known=False`) walks back over it.

## Status 10 Sep 2026

**Half 1 DONE** (commit "A pushed picture no longer crashes the reader"):
`_photo_bytes()` closes the coroutine and returns None inside a running
loop. 100 Telegram tests pass. **Half 2 OPEN** — handed to the phone
session in `docs/handoff/open-problems-10-sep.md` §4, with the facts:
`_store` is `INSERT OR IGNORE` (re-fetch never updates ocr_text);
`fetch(handle, ids=[...])` returns photo_data and works on the poller
thread; wire after `self.poll` in `start()._loop`; `_read_photo` caches
the failed `""` by URL — evict it first; remember tried ids so textless
pictures aren't re-downloaded every 90s; bound it (daily channels);
`tools/telegram_ocr.py` exists — check it before writing a second path.

## The fix, both halves

1. Never let a coroutine escape `_photo_bytes()`. Inside a running loop
   the download cannot be driven -- close the coroutine and give up
   cleanly rather than returning it.
2. A re-read pass on the poller thread (outside the loop) that finds
   stored messages with a picture and no transcript and fills them in.
   This is also what recovers the ~410 already lost. His rule: "i do
   not want to miss / loose any info even by mistake".

Related: [[telegram-catchup-should-walk-forward]],
[[telegram-channel-roles]], [[day-trader-telugu-weekends-and-links]].

## BOTH HALVES DONE -- 14 September 2026

Half 2 shipped: `core/telegram_feed.reread_missing_photos()`, called
from the poller loop after `poll()`. It selects rows with a photo and
an empty `ocr_text`, asks Telegram for those exact ids
(`fetch(ids=...)`, one request for up to a hundred), re-reads the
picture and writes with **UPDATE** -- which was the missing piece:
`_store()` uses INSERT OR IGNORE on (channel, message_id), so even
`catch_up()` re-reading the image had its write dropped. Bounded at
`REREAD_MAX_PER_PASS = 25`, newest hole first.
