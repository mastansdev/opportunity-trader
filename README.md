# Opportunity Trader

NSE equity ORB (Opening Range Breakout) auto-trader. PAPER
mode. Equity only -- no F&O, ever.

## Setup

```
py -m pip install -r requirements.txt
cp .env.example .env      # fill in DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN / ANTHROPIC_API_KEY
```

`ANTHROPIC_API_KEY` is only needed for News Bot's Stage 3 (AI
classification). Everything else -- ORB trading, News Bot
Stages 1/2/4, the interface -- works without it; Stage 3 just
logs a clear error per item and moves on if the key is
missing.

## Run tests

```
py -m pytest tests/ -v
```

## Run the bot

```
py main.py
```

While it's running, type in the terminal:
- `positions` -- show open positions
- `exit SYMBOL` -- exit one position
- `exitall` -- exit everything
- `Ctrl+C` -- clean shutdown

## What Phase 1 does

Watches the full 750-stock universe (`data/master_stocks.csv`,
loaded via `core/master_loader.py`), builds the 09:15-
09:30 opening range per symbol, and trades BOTH directions on
a 1-minute candle CLOSE (never a wick): LONG on a close above
the range high, SHORT on a close below the range low
(`core/strategy.py`). Auto-flattens everything at 15:15.

Exit is a candle-based trailing stop (`core/trailing_stop.py`),
mirrored for both directions: a LONG's stop is seeded at the
breakout candle's own low and ratchets UP (never down) to the
lowest low of the last `TRAILING_STOP_WINDOW_CANDLES` closed
candles; a SHORT's stop is seeded at the breakdown candle's own
high and ratchets DOWN (never up) to the highest high of the
same window. No fixed target -- the trade rides until the
trailing stop is hit (checked every tick, intrabar) or the
15:15 square-off forces it closed. You can still exit manually
any time too.

Two operator-approved "don't fight the market" checks run
before any STRUCTURAL entry (manual dashboard buys bypass both
-- an explicit operator override) -- see `core/engine.py`'s
`_try_structural_entry()`:
- **News contradiction**: same-day, HIGH-confidence News Bot
  item on that exact symbol, pointing the opposite way from the
  signal -- blocks only that direction, for that symbol, for
  the rest of the day. A later signal in the OTHER direction
  (agreeing with the news) is still fully tradeable.
- **Sector panic**: `core/sector_monitor.py` flags a sector as
  broadly, sharply declining (breadth-based, not one bad stock)
  -- blocks new LONG entries anywhere in that sector for the
  rest of the day. Never blocks a SHORT; shorting a real sector
  breakdown is going WITH the market.

Both blocks are visible on the dashboard's Risk Filters panel
and persist across a restart (`core/engine.py`'s
`entry_blocked`, via `core/state_store.py`).

Per-trade quantity is still a flat placeholder (`config.py`,
`LAYER1_FIXED_QTY` = 100) -- but capital now DOES gate whether a
new position can open at all: `trading/portfolio.py` models MIS
buying power as a flat leverage multiple of starting capital
(`config.MIS_LEVERAGE_MULTIPLIER`, 4x on ₹10L = ₹40L, operator-
approved 2026-07-23 -- real per-stock broker margin isn't
modeled, this is one documented flat number). Once open
positions' entry-notional uses up that buying power, `core/
engine.py`'s `_enter()` skips ANY new position -- structural or
manual -- until one closes and frees it up again. Unlike the
news/sector blocks above, this is never a permanent "for today"
block; it's re-checked fresh on every entry attempt. See
`PHASES.md` for what gets built next, and in what order.

## Dashboard

`py main.py` also starts a local dashboard at
`http://127.0.0.1:8000` (FastAPI + WebSocket, `dashboard/`) --
available capital, advances/declines, sector colour, News/ORB
watchlists, the Risk Filters panel above, open/closed positions
(direction-aware PnL), and a manual BUY (long only) plus
per-position EXIT / EXIT ALL. Starts and stops cleanly with the
rest of the bot, including on Ctrl+C.

## Surviving a restart

The console prints a `[HEARTBEAT]` line every 60s (tick
count, open positions, feed health) so it's never flooded
and never silently dead. If the feed thread ever dies
outright it's detected and restarted within 5s automatically.

Today's ORB ranges, open positions, AND trailing-stop levels
are snapshotted to `data/session_state.json` every heartbeat
and on shutdown, and reloaded on the next startup -- so a
restart mid-session doesn't lose track of what it already
bought, how far its stop had already ratcheted up, or
permanently disable entries for symbols whose 09:15-09:30
window already closed. A restart still can't see ticks it
missed while it was down, so any breakout that happened purely
during the downtime is not retroactively caught.

## Files

| File | What it does |
|---|---|
| `config.py` | All settings: session times, mode, qty, trailing-stop window |
| `core/master_loader.py` | Single source of truth for the 750-stock universe: symbol -> security_id, sector, tags |
| `core/instrument_master.py` | Offline reconciliation only (`tools/verify_master_database.py`) -- resolves symbol -> security_id from Dhan's live scrip master to catch drift |
| `core/dhan_time.py` | Converts Dhan's UTC "HH:MM:SS" tick time to IST |
| `core/state_store.py` | Saves/loads today's ORB ranges + open positions + trailing stops so a restart can recover |
| `core/market_data.py` | Tick entry point: drops pre-market ticks, flags stale ones |
| `core/orb_engine.py` | Tracks the 09:15-09:30 high/low per symbol |
| `core/candle_engine.py` | Builds 1-min candles from ticks |
| `core/strategy.py` | The two rules: candle close above ORB high (LONG) / below ORB low (SHORT) |
| `core/trailing_stop.py` | Candle-based trailing stop, mirrored for LONG (ratchets up) and SHORT (ratchets down) |
| `core/sector_monitor.py` | Breadth-based sector panic detection -- blocks new LONG entries in a broadly declining sector |
| `core/news_gate.py` | Thin reader over News Bot's HIGH-priority queue; `core/engine.py` decides what to do with it |
| `core/engine.py` | Ties it together, per tick -- structural signal, news/sector checks, entry, trailing stop, exit |
| `trading/execution.py` | Single buy/sell gateway (PAPER only right now) |
| `trading/trade_controller.py` | Manual buy/exit request flags (dashboard + console) |
| `trading/trade_logger.py` | Writes `logs/trade_log.csv`, now with an entry/exit `reason` column |
| `trading/portfolio.py` | Paper capital ledger (display/tracking only) -- on_buy/on_sell and on_short/on_cover |
| `dashboard/` | FastAPI + WebSocket live dashboard (`server.py`, `state.py`, `static/index.html`) |
| `main.py` | Live wiring: Dhan feed (with auto-reconnect + watchdog), News Bot thread, dashboard, console commands, clean shutdown, square-off |
