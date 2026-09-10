---
name: open-work-5-sep-2026
description: "What went live 5 Sep 2026, what to watch on Monday 7 Sep, and the four tasks still open"
metadata:
  node_type: memory
  type: project
  originSessionId: 9fd6931f-938d-4539-ad73-4191c031054a
  modified: 2026-09-05T17:35:19.996Z
---

Five commits, `bf74f3e` → `fcd72e0`, suite 5,788 passed / 9 skipped.
All of it is the path between a Telegram message and a reason.

**LIVE NOW — the collector must be restarted to pick any of it up.**

- **Collection is three steps**: everything after the last stored post
  (forward, `min_id` + `reverse`), then holes filled BY POST NUMBER,
  then 90s polling. The old backward page-walk no longer runs at
  startup — it cost 25 minutes and 83 seconds a page to store nothing.
  Startup is now ~25 seconds. See
  [[telegram-catchup-should-walk-forward]].
- **Telegram PUSHES** (`NewMessage`, 10 channels). The two poller
  threads became one, because a held event loop breaks both.
- **The results gate has a list.** `core/results_calendar` reads the
  Earnings Pulse calendar posts. It had 0 companies due; it now knows
  MOLBIO (5 Sep), BLEL + SHIPROCKET (Mon 7), GAJA (Thu 10), LALITHAA
  (Fri 11).
- Duplicate events, the digest/card trap, "Tamil Nadu" naming TNPL, the
  subject rules, and the FII/DII flows card — see the commit messages,
  which carry the measurements.

**FIXED 6 SEPTEMBER, before the open.** He asked one question --
*"can you confirm all changes are not breaking our plan on monday? i
want 0 lag & 0 errors"* -- and the honest answer was no. The standing
gate reads the event store from inside why(), which the ranker calls
for every candidate, which _route_entries() runs every second. The
FIRST such call cost 1,642 ms and would have been made at 09:15 on a
live decision. Three causes: it asked per symbol instead of reading
the batch the board already builds; it re-asked _headline_names()
every cycle (86 ms, because names_in compares against every company);
and _matcher() loaded a SECOND MasterLoader when main.py has had one
since line 307. Now: main.py calls cause_effect.warm(master_loader) at
startup (692 ms, before the feed connects) and the entry loop pays
0.03 ms. See [[measure-the-second-run-not-the-first]] -- the first
number I reported him, 18.76 ms a symbol, was my benchmark order, not
his bot.

**WATCH ON MONDAY 7 SEPTEMBER**

1. `[PUSH] Telegram will push new posts from N channel(s)` — if N is 0,
   the listener did not register and polling is carrying the feed.
2. **BLEL and SHIPROCKET will be blocked** until their numbers land,
   then allowed if GOOD or STRONG. That is the results gate working for
   the first time with a real list.
3. The **liveness ordering** change (alive before cannot-say before
   fading) gets its first real trades. `door`, `volume_x`, `jump_x` and
   `liveness` are being recorded per trade now.

4. **The standing gate opens for exactly four stocks on Monday** --
   ADANIENSOL 53%, WELCORP 47%, TEJASNET 30%, NBCC 24%. Each still has
   to clear 3%, 2.5x volume, liveness and a seat. Sixteen more are on
   the board but refused for "company size not on file", which is the
   500-of-1,976 free-float coverage, not a fault.
5. **The results gate blocks BLEL and SHIPROCKET and nothing else.**
   Verified against the live calendar: released on GOOD or STRONG,
   still blocked on MIXED, WEAK or an unread grade, and clear on
   Tuesday. tools/dry_run_live_path.py reports all 19 junctions
   connected, ALERT_ONLY_MODE off, TRADING_MODE PAPER.

**STILL OPEN, in the order agreed**

1. **The seat — right stock at right time.** The only one about money.
   Settle after Monday's trades, with real data. See
   [[what-the-event-edge-actually-measures]].
~~2~~ **DONE, commits `00049cd` and `843c925`.** The board shows a
standing cause beside any symbol, and a large one now opens the door.
**The lesson: I measured by RUPEES, found nothing, and recommended
display-only — after he had already said rupees is the wrong yardstick.
Re-measured by SHARE OF THE COMPANY: of 117 stock-days where an order
was worth 20%+ of the company, 15 moved 3%+ on 2x volume and all 15 ran
3% from the open — four times the rate of the 0-5% band.** A rupee bar
would admit L&T's Rs 15,000 cr (3% of L&T) and refuse RailTel's Rs 630
cr (27% of RailTel). Free-float market cap now comes from NSE index
lists via `core/market_cap.py` (~500 of 1,976 symbols); an unknown size
opens nothing. See [[what-the-event-edge-actually-measures]].
~~3 and 4~~ **DONE, commit `6ae6952`.** They were one bug: 29 ETFs and
mutual funds sat in the news matcher and eleven have ordinary-word
tickers (HEALTHCARE, HEALTHY, SILVER, DEFENCE, SMALLCAP...). A fund
cannot have news, so the CATEGORY is excluded rather than the words —
22 messages → 0. He caught the false positive the moment it shipped:
*"ABSLAMC = ADITYA BIRLA SUN LIFE AMC LIMITED"* — an AMC is a listed
company, and GAJA (reporting 10 Sep) had been silenced by an
"ASSET MANAGEMENT" pattern. **When a company name is available it
decides; the symbol heuristic is the fallback only** — that also fixed
`"SDL" in "SSDL"` reading Saraswati Saree Depot as a fund.

**A LESSON FROM THIS SESSION, worth not repeating.** Three times I
reported a fault that was my own measurement rather than the bot: a
regex that read "NOT CLEAN:" as a company, a count of HISTORICAL rows
already fixed on 6 August, and a `select.py` in my scratchpad shadowing
the stdlib. Each was caught by one of his questions. **Replay through
the live path before reporting a number** — counting rows in the store
measures old code. See [[verify-the-value-the-live-path-reads]].
