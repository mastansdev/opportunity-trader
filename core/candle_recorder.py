"""
==========================================================
Candle Recorder -- clean OHLCV corpus for the replay bench
==========================================================

Writes every CLOSED 1-minute candle of a live/paper session into
backtest/candle_store.py's database, so the strategy can be replayed
against MANY real sessions instead of one scraped log.

Why this exists (2026-07-25): the first replay corpus was parsed out
of diagnostics.log. It worked, but it carried no volume, no true
market timestamp, and at least three CORRUPT symbols -- INFY printed
Rs1,037 -> Rs111 -> back in one minute, JLHL -80% in a minute. A
backtest happily "shorted" the INFY ghost for a fake +Rs145,403,
which would have been mistaken for edge. Recording clean data at the
source removes that entire class of error.

Design rules, same as every other side-system in this bot:
  - NEVER on the hot path's critical route: a failure here is caught
    and logged, it can never break tick processing or trading.
  - Buffered: candles accumulate in memory and flush in batches, so
    the tick thread doesn't pay a database write per candle.
  - Config-gated (config.ENABLE_CANDLE_RECORDING) and fully optional.

Author : H&M Opportunity Trader
==========================================================
"""

import threading

from core.logger import decision, warn


class CandleRecorder:

    def __init__(self, store=None, flush_every=200):
        self._rows = []
        self._lock = threading.Lock()
        self._flush_every = flush_every
        self._store = store
        self._broken = False
        self._written = 0

    def _get_store(self):
        if self._store is None:
            from backtest.candle_store import CandleStore
            self._store = CandleStore()
        return self._store

    def record(self, symbol, closed_candle):
        """
        Buffer one CLOSED candle. `closed_candle` is the dict
        core/candle_engine.py produces (time/open/high/low/close and,
        when the feed supplies it, volume). Never raises.
        """
        if self._broken or closed_candle is None:
            return
        try:
            t = closed_candle.get("time")
            if t is None:
                return
            minute = t.strftime("%Y-%m-%dT%H:%M")
            row = dict(
                date=t.strftime("%Y-%m-%d"),
                symbol=symbol,
                minute=minute,
                o=float(closed_candle["open"]),
                h=float(closed_candle["high"]),
                l=float(closed_candle["low"]),
                c=float(closed_candle["close"]),
                v=(float(closed_candle["volume"])
                   if closed_candle.get("volume") is not None else None),
            )
            with self._lock:
                self._rows.append(row)
                due = len(self._rows) >= self._flush_every
            if due:
                self.flush()
        except Exception as exc:            # never break the tick path
            warn(f"[RECORDER] Skipped a candle for {symbol}: {exc}")

    def flush(self):
        """Write buffered candles to the store. Safe to call any time
        (shutdown, end of session). Never raises."""
        with self._lock:
            batch, self._rows = self._rows, []
        if not batch:
            return 0
        try:
            store = self._get_store()
            with store.engine.begin() as conn:
                conn.execute(store.candles.insert().prefix_with("OR REPLACE"), batch)
            self._written += len(batch)
            return len(batch)
        except Exception as exc:
            # One failure disables recording for the rest of the
            # session rather than warning on every candle.
            self._broken = True
            warn(
                f"[RECORDER] Disabled for this session -- write failed: "
                f"{exc}"
            )
            return 0

    def close(self):
        n = self.flush()
        if self._written:
            decision(
                f"[RECORDER] Session candles saved: {self._written} bars "
                f"(last flush {n})."
            )
