"""
==========================================================
Circuit Monitor
==========================================================

Proactive, direction-agnostic circuit-limit protection --
see config.py's CIRCUIT_PROXIMITY_PCT docstring for the full
rationale (HFCL, 2026-07-23: hit its LOWER CIRCUIT and froze
for ~4 hours; core/engine.py's FROZEN_PRICE_STREAK_CANDLES
only detects that AFTER the fact, once 3 candles have already
printed an identical O=H=L=C). This module detects the
APPROACH to either circuit limit before the freeze happens,
so the engine can close out ahead of it instead of getting
stuck.

Runs on its own poll thread (see start()), entirely separate
from the tick-processing hot path -- same separation-of-
concerns principle already applied to News Bot (main.py's
_news_loop). Talks to Dhan's REST /marketfeed/quote endpoint,
NOT the WebSocket feed this bot's ticks already come from --
confirmed against Dhan's own API docs (2026-07) that the
WebSocket Ticker/Quote/Full packets carry LTP/OHLC/depth but
never circuit limits; only the REST quote snapshot does (up
to 1000 instruments per request, 1 request/second -- this
bot's whole ~750-symbol universe fits in a single call).

Circuit limits are the exchange's own live-computed band
(2%/5%/10%/20%, category-dependent, and can change intraday)
-- Dhan hands back the actual number per symbol in that same
quote response, so this deliberately does NOT hardcode SEBI's
band tables anywhere.

Decoupled from the actual Dhan client, same testability
pattern as core/market_data.py's own docstring ("never talks
to the network itself, so it can be unit tested with fake
ticks") -- the caller hands in a plain `quote_fn(securities)`
callable (main.py wires this to a real
dhanhq.dhanhq(...).quote_data), so this class can be driven
with a fake in tests with no network, no thread, no dhanhq
import at all.

Dashboard reuse (2026-07-23 evening, replacing the old ORB
Bullish/Bearish watchlist panel with Top Gainers/Losers): each
poll cycle already pulls OHLC/prev-close/volume for the whole
universe alongside the circuit limits used for proximity
checking -- get_snapshot() exposes that same per-symbol data
so dashboard/state.py's gainers/losers table can be built from
it directly, with NO second REST poller. Circuit-safety still
drives the poll cadence (CIRCUIT_POLL_INTERVAL_SECONDS, a few
seconds); the dashboard re-ranks that cached snapshot into a
Top N table on its own, much slower cadence
(GAINERS_LOSERS_REFRESH_SECONDS) -- two different consumers of
one poll, not two polls.

Author : H&M Opportunity Trader
==========================================================
"""

import threading

from config import CIRCUIT_PROXIMITY_PCT, CIRCUIT_POLL_INTERVAL_SECONDS
from core.logger import diagnostic, warn

UPPER = "UPPER"
LOWER = "LOWER"


class CircuitMonitor:
    """
    quote_fn: callable(securities: dict[str, list[int]]) -> raw
    dhanhq response dict, i.e. exactly what
    dhanhq.dhanhq(dhan_context).quote_data(securities) returns --
    {"status": "success"/"failure", "remarks": ..., "data": {
        "data": {exchange_segment: {security_id_str: {...,
        "last_price":, "upper_circuit_limit":,
        "lower_circuit_limit":, ...}}}, "status": "success"}}
    (Dhan's HTTP wrapper nests the raw API body itself under
    "data" -- see dhanhq's own dhan_http.py -- so the actual
    per-symbol quotes are two "data" keys deep. Handled once,
    here, so nothing else in this codebase has to know that.)
    """

    def __init__(self, quote_fn, exchange_segment,
                 proximity_pct=CIRCUIT_PROXIMITY_PCT,
                 poll_interval_seconds=CIRCUIT_POLL_INTERVAL_SECONDS):
        self._quote_fn = quote_fn
        self._exchange_segment = exchange_segment
        self._proximity_pct = proximity_pct
        self._poll_interval = poll_interval_seconds

        self._lock = threading.Lock()
        # symbol -> {"side": UPPER/LOWER, "gap_pct":, "ltp":,
        #            "upper":, "lower":}. NOT persisted -- a live
        #            price's distance from a live circuit limit is
        #            re-derived fresh every poll, same "no point
        #            carrying this across a restart" reasoning as
        #            core/engine.py's own _frozen_streak.
        self._flagged = {}
        # Edge-triggered warning tracker, mirrors core/engine.py's
        # own _frozen_warned -- warn once per approach episode, not
        # every poll cycle for as long as it lasts.
        self._warned = set()

        # symbol -> {"last_price":, "open":, "high":, "low":,
        #            "prev_close":, "volume":}, EVERY successfully
        #            quoted symbol, not just flagged ones -- see
        #            class docstring's "Dashboard reuse" section.
        #            Replaced atomically alongside self._flagged each
        #            poll cycle, same not-persisted reasoning.
        self._snapshot = {}

        self._security_id_to_symbol = {}
        self._stop_event = threading.Event()
        self._thread = None

    # --------------------------------------------------

    def set_universe(self, security_id_to_symbol):
        """
        security_id_to_symbol: dict of security_id (str) -> symbol,
        the same mapping main.py already builds for the tick feed.
        Split out from start() specifically so tests can drive
        poll_once() directly against a fake quote_fn with no thread
        involved at all -- same testability goal as this class's own
        docstring.
        """
        self._security_id_to_symbol = dict(security_id_to_symbol)

    def start(self, security_id_to_symbol):
        """
        Sets the universe (see set_universe()) and starts the poll
        loop on a daemon thread, returning it -- same pattern as
        main.py's own start_feed().
        """
        self.set_universe(security_id_to_symbol)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self._thread

    def stop(self):
        self._stop_event.set()

    def _run(self):
        while not self._stop_event.is_set():
            try:
                self.poll_once()
            except Exception as e:
                # A failed poll cycle must never take the circuit
                # monitor thread down -- same resilience pattern as
                # main.py's _news_loop. Worst case, one cycle's worth
                # of proximity data goes stale; the next cycle tries
                # again CIRCUIT_POLL_INTERVAL_SECONDS later.
                warn(f"[CIRCUIT_MONITOR] Poll cycle failed, will retry: {e}")
            self._stop_event.wait(self._poll_interval)

    # --------------------------------------------------

    def poll_once(self):
        """
        One full poll cycle: request quotes for every tracked
        security ID in a single batched call, recompute proximity
        for each, and replace the flagged set atomically. Public
        (not prefixed) so tests and a manual/administrative trigger
        can call it directly without spinning up the poll thread.
        """
        security_ids = list(self._security_id_to_symbol.keys())
        if not security_ids:
            return

        response = self._quote_fn(
            {self._exchange_segment: [int(sid) for sid in security_ids]}
        )

        if not isinstance(response, dict) or response.get("status") != "success":
            warn(
                f"[CIRCUIT_MONITOR] Quote request failed: "
                f"{response.get('remarks') if isinstance(response, dict) else response}"
            )
            return

        # See class docstring -- Dhan's HTTP wrapper nests the raw
        # API body under this same "data" key a second time.
        body = response.get("data", {})
        if isinstance(body, dict) and "data" in body:
            body = body["data"]
        segment_quotes = body.get(self._exchange_segment, {}) if isinstance(body, dict) else {}

        new_flagged = {}
        new_snapshot = {}
        for security_id, symbol in self._security_id_to_symbol.items():
            info = segment_quotes.get(str(security_id)) or segment_quotes.get(security_id)
            if not info:
                continue

            flag = self._evaluate(info)
            if flag is not None:
                new_flagged[symbol] = flag

            row = self._snapshot_row(info)
            if row is not None:
                new_snapshot[symbol] = row

        with self._lock:
            # Edge-triggered warning: only symbols newly entering
            # the flagged set this cycle get a log line, same
            # discipline as core/engine.py's _is_frozen().
            for symbol, flag in new_flagged.items():
                if symbol not in self._warned:
                    self._warned.add(symbol)
                    warn(
                        f"[CIRCUIT_PROXIMITY] {symbol} within "
                        f"{self._proximity_pct * 100:.1f}% of its "
                        f"{flag['side']} circuit (LTP={flag['ltp']:.2f}, "
                        f"limit={flag['limit']:.2f}) -- blocking new "
                        f"entries and closing any open position, "
                        f"irrespective of direction."
                    )
            # Anything that dropped out of new_flagged has moved
            # back away from its circuit -- clear its warned flag so
            # a later re-approach warns again, same reset pattern as
            # _frozen_warned.discard() on a genuinely moved price.
            for symbol in list(self._warned):
                if symbol not in new_flagged:
                    self._warned.discard(symbol)

            self._flagged = new_flagged
            self._snapshot = new_snapshot

        diagnostic(
            f"[CIRCUIT_MONITOR] Poll cycle: {len(security_ids)} symbols "
            f"checked, {len(new_flagged)} within "
            f"{self._proximity_pct * 100:.1f}% of a circuit limit, "
            f"{len(new_snapshot)} snapshot rows cached for the "
            f"gainers/losers table."
        )

    def _snapshot_row(self, info):
        """
        Returns the plain OHLC/prev-close/volume/LTP row dashboard/
        state.py's gainers/losers builder needs, or None if this
        symbol's quote is missing the fields required to compute a
        %-change (mirrors _evaluate()'s own fail-quiet-on-bad-data
        posture -- a symbol with no usable prev_close just doesn't
        appear in the table, rather than showing a wrong number).
        """
        try:
            last_price = float(info.get("last_price") or 0)
        except (TypeError, ValueError):
            return None
        if last_price <= 0:
            return None

        ohlc = info.get("ohlc") or {}
        try:
            prev_close = float(ohlc.get("close") or 0)
            open_price = float(ohlc.get("open") or 0)
            high = float(ohlc.get("high") or 0)
            low = float(ohlc.get("low") or 0)
        except (TypeError, ValueError):
            return None
        if prev_close <= 0:
            # "close" here is Dhan's PREVIOUS trading day's close (the
            # standard %-change reference -- during live market hours
            # today's own close obviously isn't known yet), needed to
            # compute CHANGE/CHANGE%. Without it there's nothing
            # honest to rank this symbol by -- skip it rather than
            # fabricate a base.
            return None

        try:
            volume = int(info.get("volume") or 0)
        except (TypeError, ValueError):
            volume = None

        return {
            "last_price": last_price,
            "open": open_price,
            "high": high,
            "low": low,
            "prev_close": prev_close,
            "volume": volume,
        }

    def get_snapshot(self):
        """
        Public read for the dashboard's gainers/losers table (see
        class docstring's "Dashboard reuse" section) -- a plain dict
        copy, symbol -> OHLC/prev-close/volume/LTP, safe to call from
        another thread, same pattern as get_flagged_symbols().
        """
        with self._lock:
            return dict(self._snapshot)

    def _evaluate(self, info):
        """
        Returns a flag dict if this symbol's LTP is within
        self._proximity_pct of either circuit limit, else None.
        Proximity is measured as a fraction of LTP itself (not the
        band width) -- "within 2% of hitting the limit" is the
        intuitive, directly-configurable read, and matches how a
        circuit band's remaining room is normally talked about.
        """
        try:
            ltp = float(info.get("last_price") or 0)
            upper = float(info.get("upper_circuit_limit") or 0)
            lower = float(info.get("lower_circuit_limit") or 0)
        except (TypeError, ValueError):
            return None

        if ltp <= 0 or upper <= 0 or lower <= 0 or upper <= lower:
            # Missing/malformed circuit data for this symbol (e.g. a
            # segment that doesn't carry circuit limits at all) --
            # silently skip rather than false-flag off garbage
            # numbers. This mirrors the fail-open posture already
            # used for optional readers elsewhere in this codebase
            # (e.g. core/engine.py's momentum_universe is None ->
            # no check at all).
            return None

        upper_gap_pct = (upper - ltp) / ltp
        lower_gap_pct = (ltp - lower) / ltp

        if upper_gap_pct <= self._proximity_pct:
            return {"side": UPPER, "gap_pct": upper_gap_pct, "ltp": ltp, "limit": upper}
        if lower_gap_pct <= self._proximity_pct:
            return {"side": LOWER, "gap_pct": lower_gap_pct, "ltp": ltp, "limit": lower}
        return None

    # --------------------------------------------------

    def is_flagged(self, symbol):
        """
        True if `symbol` is currently within CIRCUIT_PROXIMITY_PCT
        of either circuit limit, as of the last completed poll
        cycle. Cheap dict lookup -- safe to call on every tick from
        the engine's hot path, same as core/engine.py's own
        _is_frozen().
        """
        with self._lock:
            return symbol in self._flagged

    def get_flag(self, symbol):
        """Full flag detail (side/gap_pct/ltp/limit) for `symbol`, or None."""
        with self._lock:
            return self._flagged.get(symbol)

    def get_flagged_symbols(self):
        """
        Public read for the dashboard (see dashboard/state.py's
        risk-filters panel), same pattern as
        core/engine.py's get_frozen_symbols() -- a plain, sorted
        list snapshot, safe to call from another thread.
        """
        with self._lock:
            rows = [
                {
                    "symbol": symbol,
                    "side": flag["side"],
                    "gap_pct": round(flag["gap_pct"] * 100, 2),
                }
                for symbol, flag in self._flagged.items()
            ]
        rows.sort(key=lambda r: r["symbol"])
        return rows
