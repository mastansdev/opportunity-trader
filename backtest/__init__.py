"""
Backtest / replay package.

Purpose (operator's own framing, 2026-07-24): don't curve-fit to years
of history that will never recur -- REPLAY the current settings against
RECENT, real market sessions. Markets don't repeat exactly but they
persist in regimes for days/weeks, so the recent window IS the right
test set. This package records real 1-minute candles and replays them,
deterministically, through the same decision logic the live bot uses --
so a change can be measured across the last N real sessions in seconds
instead of one noisy live day at a time.

Modules:
  candle_store    -- SQLite store of 1-min OHLCV candles (the corpus)
  import_from_log -- bootstrap: pull today's candles out of diagnostics.log
  (replay)        -- runs a session's candles through the strategy (WIP)
"""
