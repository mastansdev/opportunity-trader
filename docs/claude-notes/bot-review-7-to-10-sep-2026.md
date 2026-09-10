---
name: bot-review-7-to-10-sep-2026
description: "What the bot actually did 7-10 Sep 2026 (all PAPER, net -21,710), the seven faults found, and the fix order he agreed to"
metadata: 
  node_type: memory
  type: project
  originSessionId: 16056bf4-7288-47a5-b025-94575658f3a9
  modified: 2026-09-10T10:33:41.630Z
---

**Reviewed 10 September 2026** from the live logs, `data/trade_memory.db`
and the candle stores. He asked: *"our bot is working but not in way
what we expected. Telegram OCR Failed, Bot is showing delayed time. &
entries, exits all are worrking but not as we wanted."*

## What it did, net of charges

    Mon 07 Sep   28 trades   gross -7,263.56   charges 2,659.19   net  -9,922.75
    Tue 08 Sep   32 trades   gross -2,680.68   charges 2,936.20   net  -5,616.88
    Wed 09 Sep   24 trades   gross -3,545.22   charges 2,332.65   net  -5,877.87
    Thu 10 Sep   11 trades   gross   +721.49   charges 1,013.95   net    -292.46
                 95 trades   gross -12,767.97  charges 8,941.99   net -21,709.96

**All four sessions ran PAPER** -- every banner reads `Layer 1 (PAPER,
equity only)` and `[FUNDS] PAPER -- fixed Rs 500,000.00`. His money
never moved. He stopped both runs on 10 Sep at ~10:50.

**Progress, 10 Sep evening:** #1 switch FIXED. #2 OCR half 1 fixed, half 2
open. Everything else open and handed to the phone session in
`docs/handoff/open-problems-10-sep.md` — see [[phone-work-via-cloud-sessions]].
He also named the execution delay and clock lag; both measured to the
board rebuild blocking the main loop — see [[board-rebuild-is-too-slow]].

## The seven faults, in the fix order agreed

1. **The switch is not the whole answer** -- see
   [[the-one-switch]]. Highest priority: it can cost real money the
   moment he clicks ON.
2. **Pushed Telegram pictures lose their transcript** -- see
   [[telegram-push-breaks-ocr]].
3. **Late entries** -- see [[late-entries-measured]].
4. **Nothing exits a position that just sits there.** BUYING_DRIED_UP
   books winners (+68,770 gross on 46 trades); TRAILING_STOP fires
   correctly at -3.06% to -3.43% (the stop is NOT broken). A position
   drifting down 1-2% has no rule, is held all day, and is flattened by
   hand at 15:11-15:22: **32 MANUAL_EXIT trades, -30,444 gross**. GNFC
   07 Sep 09:16->15:10 -1,952; EIEL 09 Sep 09:16->15:17 -3,387.
   `FORCE_SQUARE_OFF_AT_CLOSE` is False on purpose, so the bot itself
   never closes them.
5. **The trade fingerprint is dropped at exit.** `core/auto_entry.py`
   stamps `door`, `volume_x`, `jump_x`, `liveness`, `off_high_pct`,
   `run_up_pct`, `move_age_min`, `reason_kind`,
   `reason_pct_of_company` onto the position (verified present on live
   open positions). `core/engine.py:6244` builds the closed row from a
   fixed key list and **none of those keys are in it**, so
   `trade_memory.record()` reads None every time. All 95 trades since
   Monday recorded `door = NULL`, `move_age_min = NULL`. The partial-
   exit row at `core/engine.py:5882` drops even more (no sector, no
   reason). Same fault shape as always: built, wired at both ends,
   dropped in the middle hop.
6. **The Telegram tab is 5h30m behind.** `at` is stored UTC-with-offset
   (`2026-09-10T05:11:03+00:00`), `seen_at` naive IST
   (`2026-09-10T10:41:30`). `dashboard/static/desk.html:1493` prints
   `r.last_post` raw. Real arrival lag is 0.2 min median -- the feed is
   fast, the clock is lying. `telegram_feed._late_by()` already
   converts both correctly via `core.feed_clock.to_ist`; the displayed
   field never was. Fix at `core/telegram_feed.py:1748`.
7. **The log rotation PermissionError he reported 7 Sep.**
   `core/logger.py:241` -- the docstring says "the SAME file handler is
   attached to root" but the code builds a SECOND `FileHandler` on the
   same path. Two open handles on one file, so `os.rename` at the 25 MB
   rollover fails with `[WinError 32]`. Monday's log is 26 MB, which is
   exactly when he saw it. Fix: attach the existing handler object, and
   keep libraries at WARNING with a `logging.Filter` on the handler.

## Also true, and not a fault

- The board rebuild ran 20.0s to 98.5s on 10 Sep. Known -- see
  [[board-rebuild-is-too-slow]]. It does not affect prices (entries
  re-read the tick); it delays a stock APPEARING.
- Position value runs Rs 1.2-2.1 lakh per seat, not Rs 50,000 -- that
  figure is MTF *margin*, and leverage varies 2x to 4.3x by stock. So
  one 3% stop costs Rs 4,000-4,700, not Rs 1,500. With his real
  Rs 1,00,000 that is ~4.5% of the account per stop and
  `DAILY_MAX_LOSS_RS = 12,000` trips after three.
- 6 `MISSED_STOP_RECONCILED` trades, -4,211. IFCI and NIACL both on
  07 Sep entered 09:16:01 and exited 09:16:47 at -1.74%. Not diagnosed
  yet.
- `NO_NEW_ENTRIES_AFTER` appears only in a config.py *comment* -- the
  constant does not exist. `LAST_ENTRY_TIME = "15:15"` is the only
  cutoff, which is why SPLPETRO was bought 08 Sep at 15:00:23 and
  flattened 19 minutes later for -426 net.
