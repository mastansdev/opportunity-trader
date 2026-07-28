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
        self._first_packet = {}
        self._unknown = {}

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

    def note_packet(self, security_id, message):
        """Record the FIRST packet seen for each known index, so its
        real field names are visible in the log rather than guessed.
        config.INDEX_INSTRUMENTS carried "VERIFY on the live feed" in
        its own comment and nobody ever did."""
        name = self._id_to_name.get(str(security_id))
        if name is None:
            return
        with self._lock:
            if name in self._first_packet:
                return
            self._first_packet[name] = dict(message)
        from core.logger import decision
        decision(f"[INDEX] {name} (id {security_id}) first packet: "
                 f"{ {k: message.get(k) for k in list(message)[:14]} }")

    def note_unknown(self, security_id, message):
        """An IDX packet whose id is not in INDEX_INSTRUMENTS.

        The VALUE is what identifies it. Live on 2026-07-28, id 13 was
        mapped to "nifty" and delivered 7327.50 while Nifty 50 had closed
        at 23,996 the day before, and id 25 ("banknifty") delivered
        3036.60 against a real BankNifty near 52,000. Both ids were
        wrong, and a tile showing a plausible-looking number for the
        wrong index is far more dangerous than a blank one. Printing the
        level lets the right id be identified by eye in one session."""
        sid = str(security_id)
        with self._lock:
            if sid in self._unknown or len(self._unknown) >= 40:
                return
            self._unknown[sid] = True
        from core.logger import decision
        decision(f"[INDEX] Unmapped IDX id {sid}: LTP={message.get('LTP')} "
                 f"close={message.get('close')} -- identify it by the level "
                 f"and add it to config.INDEX_INSTRUMENTS.")

    def suspect(self, expected_levels):
        """Configured indices whose level is nowhere near what that index
        actually trades at -- i.e. the security id maps to something
        else. expected_levels: {name: (low, high)}."""
        out = []
        with self._lock:
            data = {k: dict(v) for k, v in self._data.items()}
        for name, (lo, hi) in expected_levels.items():
            ltp = (data.get(name) or {}).get("ltp")
            if ltp and not (lo <= ltp <= hi):
                out.append((name, ltp))
        return out

    def missing(self):
        """Names configured but never seen -- surfaced on the panel so
        a wrong id looks like a wrong id, not like a dead market."""
        with self._lock:
            return sorted(n for n in self._id_to_name.values()
                          if not self._data.get(n, {}).get("ltp"))

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
