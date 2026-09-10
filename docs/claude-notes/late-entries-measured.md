---
name: late-entries-measured
description: "Measured 10 Sep 2026 on 95 real trades: entries into moves over an hour old lost 21,896 — the whole week's loss"
metadata:
  node_type: memory
  type: project
---

**The answer to "right stock at right time", finally measured.** His
standing question since 6 September. Rebuilt on 10 Sep 2026 from the
candles (`data/backtest_candles.db`, `data/history_candles.db`,
`data/daily_candles.db`) per trade, because the fingerprint columns
were NULL -- see fault 5 in [[bot-review-7-to-10-sep-2026]].

A move "began" at the first minute its high crossed +3.0% from the
previous close (`config.MIN_MOVE_FROM_PREV_CLOSE_PCT`). 95 trades,
7-10 September 2026, net of charges.

## How old the move was when the bot bought

    move never reached 3%     17 trades    9 up    +6,056
    0-15 min old              34 trades   17 up    -1,974
    15-30 min old             11 trades    5 up    -8,369
    30-60 min old              6 trades    4 up    +4,472
    over 60 min old           27 trades   10 up   -21,896

**27 trades bought into a move already more than an hour old lost
21,896 -- the entire week's loss.** Everything else together is +185.

## How far it had already run at entry

    under 3% up               18 trades    9 up    +7,140
    3-6% up                   47 trades   22 up   -13,566
    6-10% up                  17 trades    8 up    -7,413
    over 10% up               12 trades    5 up    -8,717

Worst cases, one line each: XTRANET 07 Sep bought 14:29 already
+18.69%, move 315 min old. GENESYS 08 Sep bought 12:39 already +19.14%,
201 min old. INDORAMA 09 Sep bought 15:04 already +15.86%, 307 min old.

## The shape underneath it

The bot opens most of its book in ONE instant at the open, from the
pre-open shortlist:

    07 Sep  09:16:34.938865   8 positions at once
    08 Sep  09:16:38.915703   9 positions at once
    09 Sep  09:16:49.818895   5   and 09:18:07.285352   5 more
    10 Sep  09:17:45.979617   (4 of these still open when he stopped it)

**39 of 95 entries (41%) landed in the first three minutes.** After
that every seat is full, so the only way in is when something exits --
and that is precisely when it buys the hour-old movers. This is the
"instant fill on free seat by 1 hour old sort list stock" he described
on 6 September, now measured.

Seat count is NOT `MAX_OPEN_POSITIONS = 3`. `engine._position_ceiling()`
divides capital by margin per position: Rs 5,00,000 paper purse /
Rs 50,000 = **10 seats**. With his real Rs 1,00,000 it would be 2.

Related: [[what-the-live-stop-and-seats-actually-are]],
[[no-fixed-limits-trade-when-opportunity-shows]],
[[why-the-3-percent-bar-stays-for-now]].
