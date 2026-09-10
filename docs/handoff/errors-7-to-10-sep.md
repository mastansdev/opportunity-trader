# Errors and warnings the bot printed, 7–10 September 2026

Source: the 11 `logs/diagnostics_*.log` files covering those days (not in
the repo). Only `[WARNING]`, `[ERROR]` and `[CRITICAL]` lines, with every
number replaced by N so repeats group together.

    07 Sep    753
    08 Sep  1,213
    09 Sep  1,256
    10 Sep    240   (partial — stopped ~10:50)

**Status key.**
- FIXED TODAY: fixed on 10 Sep, in `main`.
- FIXED IN CODE: the current code no longer does it; confirm on the next run.
- OPEN: not yet investigated.
- NETWORK: the laptop's connection, not the bot.
- NOISE: the same message repeated every cycle; the underlying fact may be fine.

## Fixed

| Count | Message | Status |
|---:|---|---|
| 247 | `[GUARD] Could not check the feed ('Engine' object has no attribute 'alert_only')` | FIXED IN CODE — `main.py` now passes `execution.live` (the switch) to `_live_guard.poll` |
| 191 | `[OCR] Read failed: a bytes-like object is required, not 'coroutine'` | FIXED TODAY (half 1). Transcripts not yet recovered — open-problems §4 |
| 9 | `[BROKER_STOP] DISABLED -- BROKER_STOP_ENABLED is on but TRADING_MODE is PAPER` | FIXED TODAY — the broker stop follows the switch, per position |
| 4 | `[GATE] Refusing to arm: no reading has come from Dhan this session` | FIXED IN CODE — the dashboard reads Dhan funds before asking the gate (7 Sep) |

## Open — worth a look

| Count | Message | Notes |
|---:|---|---|
| 380 + 65 | `[CIRCUIT_MONITOR] THE BOARD IS SHORT: N of N stocks, N missing (N batch(es) failed)` | OPEN. Price board incomplete; stocks aren't refused, they're absent |
| 250 | `[CIRCUIT_MONITOR] Quote request failed. status='failure' remarks={... None}` | OPEN. Dhan quote batches failing with no reason given; likely the cause of the line above |
| 61 / 49 / 48 | `[RESULTS] BAJAJFINSV / KOLTEPATIL / AIIL: no grade -- sales +N% ... misread` | OPEN + NOISE. A results card figure is misread; warned every cycle instead of once |
| 44 | `[SLOTS] No room for a NEW position ... Holding N` | Seat filling — open-problems §1 |
| 25 | `[MTF] N margin calls this session, N unanswered, Ns spent waiting` | Part of the rebuild delay — open-problems §2 |
| 5 | `[FEED] N/N symbols (N%) are stale AT ONCE -- the feed appears to be lagging` | OPEN. Check against the network errors on the same day |
| 3 | `[PREMARKET] N/N collected. Could not fetch: S&P, Nasdaq, Dow ...` | OPEN, minor |

## Noise — one stock warned every cycle

`[CIRCUIT_PROXIMITY] <SYMBOL> within N% of its UPPER/LOWER circuit --
blocking new entries and closing any open position`: ATALREAL 288,
SHANTIGEAR 156, BODALCHEM 115+4, ELLEN 71, DAVANGERE 70, GENESYS 63,
GVT&D 52, GRAPHITE 50, TBZ 46, XTRANET 38, and more. Two questions: say
it once per stock per state, and confirm "closing any open position" is
the intended behaviour.

`[NO_TRADE] <SYMBOL> LONG skipped -- not a fresh breakout` (MOBIKWIK,
STYRENIX, SBCL, KMEW, KEC, ZENTEC, …): these are correct refusals logged
at WARNING level.

## Network / environment

| Count | Message |
|---:|---|
| 222 + 71 + 13 | telethon `Attempt N at connecting failed` (network location unreachable / timeout / server closed) |
| ~21 | `[TELEGRAM] <channel>: urlopen error getaddrinfo failed` (DNS) |
| 34 | `[NEWS] Announcement poll failed: HTTPSConnectionPool(host='www.nseindia.com')` |
| 43 | `[root] Exception in DhanHQConnection.GET/POST` (connection reset, max retries, read timed out) |
| 10 + 10 | `[FUNDS] Dhan REFUSED the balance request` (network), with the token hint beside it |
| 9 | `[LIVE] could not read holdings from Dhan (connection reset)` |
| 11 + 6 | `[FEED] Feed error, retrying: no close frame` / `Feed connection closed` |
| 4 | `[asyncio] Exception in callback _ProactorBasePipeTransport._call_connection_lost()` (Windows asyncio) |

## Expected (config)

`[AI NEWS] OFF` and `[IMPACT] REASONING OFF` (9 each): `config.AI_ENABLED`
is False on purpose.
