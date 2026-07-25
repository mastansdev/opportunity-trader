"""
==========================================================
Index Monitor -- Nifty / BankNifty / Midcap / India VIX
==========================================================

Holds the latest LTP + previous close for the market indices the
dashboard's Market Intelligence panel shows, fed straight off the
Dhan MarketFeed IDX segment (config.INDEX_INSTRUMENTS). Kept
completely separate from the stock pipeline -- indices are NOT
tradable here and must never flow into ORB/candle/entry logic.

Everything is fail-open: an index with no data yet (wrong security
id, feed not delivering) simply reports available=False, and the
dashboard shows "needs feed" for it. Nothing about trading depends
on this.

Author : H&M Opportunity Trader
==========================================================
"""

import threading


class IndexMonitor:

    def __init__(self, id_to_name):
        """id_to_name: {security_id (str) -> dashboard name}, built
        from config.INDEX_INSTRUMENTS by main.py."""
        self._id_to_name = {str(k): v for k, v in id_to_name.items()}
        self._data = {}   # name -> {"ltp": float|None, "prev_close": float|None}
        self._lock = threading.Lock()

    def index_security_ids(self):
        """The set of security ids that belong to indices, so the
        feed callback can route them here instead of the stock
        pipeline."""
        return set(self._id_to_name.keys())

    def on_index_tick(self, security_id, ltp=None, prev_close=None):
        name = self._id_to_name.get(str(security_id))
        if name is None:
            return
        with self._lock:
            d = self._data.setdefault(name, {"ltp": None, "prev_close": None})
            if ltp is not None and ltp > 0:
                d["ltp"] = ltp
            if prev_close is not None and prev_close > 0:
                d["prev_close"] = prev_close

    def snapshot(self):
        """name -> {ltp, prev_close, pct, available}. pct is the %
        change vs prev close (None until both are known)."""
        out = {}
        with self._lock:
            items = {k: dict(v) for k, v in self._data.items()}
        for name in self._id_to_name.values():
            d = items.get(name, {"ltp": None, "prev_close": None})
            ltp, pc = d["ltp"], d["prev_close"]
            pct = round((ltp - pc) / pc * 100, 2) if (ltp and pc) else None
            out[name] = {
                "ltp": ltp, "prev_close": pc, "pct": pct,
                "available": ltp is not None,
            }
        return out
