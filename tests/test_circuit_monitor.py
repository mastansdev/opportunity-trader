"""
core/circuit_monitor.py -- proactive circuit-limit proximity
detection. See config.py's CIRCUIT_PROXIMITY_PCT docstring for
the operator instruction this implements (post-HFCL discussion,
2026-07-23): close ahead of a circuit lock, direction-agnostic,
not just detect one after the fact (that's the separate, existing
FROZEN_PRICE_STREAK_CANDLES mechanism in core/engine.py).

Decoupled from the real Dhan REST client -- these tests drive
CircuitMonitor with a fake `quote_fn`, exactly the shape
core/circuit_monitor.py's own docstring says dhanhq's
quote_data() returns, no network and no thread involved (poll_once()
is called directly, never start()).
"""

from core.circuit_monitor import CircuitMonitor, UPPER, LOWER


def _quote_response(security_id, last_price, upper, lower, segment="NSE_EQ"):
    """Builds a response shaped exactly like dhanhq's quote_data()
    return value -- see core/circuit_monitor.py's class docstring
    for why the real payload is nested under "data" twice."""
    return {
        "status": "success",
        "remarks": "",
        "data": {
            "status": "success",
            "data": {
                segment: {
                    str(security_id): {
                        "last_price": last_price,
                        "upper_circuit_limit": upper,
                        "lower_circuit_limit": lower,
                    }
                }
            },
        },
    }


def _fake_quote_fn(responses):
    """responses: dict security_id (str) -> (last_price, upper, lower).
    Returns a quote_fn that answers for whichever security_ids are
    actually requested, merging all of them into one response,
    same shape as a real batched /marketfeed/quote call."""
    def quote_fn(securities):
        segment = next(iter(securities))
        quotes = {}
        for sid in securities[segment]:
            sid_str = str(sid)
            if sid_str in responses:
                last_price, upper, lower = responses[sid_str]
                quotes[sid_str] = {
                    "last_price": last_price,
                    "upper_circuit_limit": upper,
                    "lower_circuit_limit": lower,
                }
        return {
            "status": "success",
            "remarks": "",
            "data": {"status": "success", "data": {segment: quotes}},
        }
    return quote_fn


def test_symbol_near_upper_circuit_is_flagged_upper():
    # LTP=99, upper=100 -> gap = (100-99)/99 = 1.01%, within the
    # default 2% CIRCUIT_PROXIMITY_PCT threshold.
    quote_fn = _fake_quote_fn({"1": (99.0, 100.0, 80.0)})
    monitor = CircuitMonitor(quote_fn, "NSE_EQ", proximity_pct=0.02)
    monitor.set_universe({"1": "TESTCO"})
    monitor.poll_once()

    assert monitor.is_flagged("TESTCO")
    flag = monitor.get_flag("TESTCO")
    assert flag["side"] == UPPER


def test_symbol_near_lower_circuit_is_flagged_lower():
    # LTP=81, lower=80 -> gap = (81-80)/81 = 1.23%, within threshold.
    quote_fn = _fake_quote_fn({"1": (81.0, 120.0, 80.0)})
    monitor = CircuitMonitor(quote_fn, "NSE_EQ", proximity_pct=0.02)
    monitor.set_universe({"1": "TESTCO"})
    monitor.poll_once()

    assert monitor.is_flagged("TESTCO")
    assert monitor.get_flag("TESTCO")["side"] == LOWER


def test_symbol_mid_range_is_not_flagged():
    # LTP sits comfortably between both limits -- neither gap is
    # anywhere near the 2% threshold.
    quote_fn = _fake_quote_fn({"1": (100.0, 120.0, 80.0)})
    monitor = CircuitMonitor(quote_fn, "NSE_EQ", proximity_pct=0.02)
    monitor.set_universe({"1": "TESTCO"})
    monitor.poll_once()

    assert not monitor.is_flagged("TESTCO")
    assert monitor.get_flagged_symbols() == []


def test_symbol_moving_back_away_from_circuit_gets_cleared_next_poll():
    """Direction-agnostic, but must also un-flag once price genuinely
    moves back to safety -- a flag isn't a permanent "no trade
    today" ledger entry like entry_blocked, it's a live read."""
    responses = {"1": (99.0, 100.0, 80.0)}
    quote_fn = _fake_quote_fn(responses)
    monitor = CircuitMonitor(quote_fn, "NSE_EQ", proximity_pct=0.02)
    monitor.set_universe({"1": "TESTCO"})
    monitor.poll_once()
    assert monitor.is_flagged("TESTCO")

    responses["1"] = (100.0, 120.0, 80.0)
    monitor.poll_once()
    assert not monitor.is_flagged("TESTCO")


def test_failed_quote_response_does_not_crash_or_flag_anything():
    def failing_quote_fn(_securities):
        return {"status": "failure", "remarks": "rate limited", "data": ""}

    monitor = CircuitMonitor(failing_quote_fn, "NSE_EQ", proximity_pct=0.02)
    monitor.set_universe({"1": "TESTCO"})
    monitor.poll_once()  # must not raise

    assert not monitor.is_flagged("TESTCO")
    assert monitor.get_flagged_symbols() == []


def test_missing_or_zero_circuit_data_is_skipped_not_false_flagged():
    """A symbol with no circuit-limit fields at all (or zeros) must
    never be treated as flagged -- that would be worse than not
    checking at all (every new entry silently refused, every open
    position force-exited, for a segment that just doesn't carry
    this data)."""
    quote_fn = _fake_quote_fn({"1": (100.0, 0.0, 0.0)})
    monitor = CircuitMonitor(quote_fn, "NSE_EQ", proximity_pct=0.02)
    monitor.set_universe({"1": "TESTCO"})
    monitor.poll_once()

    assert not monitor.is_flagged("TESTCO")


def test_multiple_symbols_batched_in_one_poll_cycle():
    quote_fn = _fake_quote_fn({
        "1": (99.0, 100.0, 80.0),   # near upper -> flagged
        "2": (100.0, 120.0, 80.0),  # mid-range -> not flagged
        "3": (81.0, 120.0, 80.0),   # near lower -> flagged
    })
    monitor = CircuitMonitor(quote_fn, "NSE_EQ", proximity_pct=0.02)
    monitor.set_universe({"1": "UP_CO", "2": "SAFE_CO", "3": "DOWN_CO"})
    monitor.poll_once()

    flagged = {row["symbol"]: row["side"] for row in monitor.get_flagged_symbols()}
    assert flagged == {"UP_CO": UPPER, "DOWN_CO": LOWER}
    assert not monitor.is_flagged("SAFE_CO")


# --------------------------------------------------------------
# get_snapshot() -- dashboard reuse (2026-07-23 evening): the same
# poll cycle that already fetches circuit limits also carries OHLC/
# prev-close/volume, which dashboard/state.py's Top Gainers/Losers
# table (replacing the old ORB watchlist) reads directly, with no
# second REST poller. See class docstring's "Dashboard reuse"
# section.
# --------------------------------------------------------------

def _fake_quote_fn_with_ohlc(responses):
    """responses: dict security_id (str) -> dict of quote fields
    (last_price, ohlc, volume, and optionally upper/lower circuit
    limits) -- same batched-response shape as _fake_quote_fn, just
    carrying the extra OHLC/volume fields get_snapshot() needs."""
    def quote_fn(securities):
        segment = next(iter(securities))
        quotes = {}
        for sid in securities[segment]:
            sid_str = str(sid)
            if sid_str in responses:
                quotes[sid_str] = dict(responses[sid_str])
        return {
            "status": "success",
            "remarks": "",
            "data": {"status": "success", "data": {segment: quotes}},
        }
    return quote_fn


def test_snapshot_captures_ohlc_prev_close_and_volume():
    quote_fn = _fake_quote_fn_with_ohlc({
        "1": {
            "last_price": 105.0,
            "ohlc": {"open": 101.0, "high": 108.0, "low": 100.0, "close": 100.0},
            "volume": 123456,
            "upper_circuit_limit": 120.0,
            "lower_circuit_limit": 80.0,
        },
    })
    monitor = CircuitMonitor(quote_fn, "NSE_EQ")
    monitor.set_universe({"1": "TESTCO"})
    monitor.poll_once()

    snapshot = monitor.get_snapshot()
    assert snapshot["TESTCO"] == {
        "last_price": 105.0, "open": 101.0, "high": 108.0, "low": 100.0,
        "prev_close": 100.0, "volume": 123456,
        "upper_circuit_limit": 120.0, "lower_circuit_limit": 80.0,
    }


def test_snapshot_includes_every_quoted_symbol_not_just_flagged_ones():
    """Circuit flagging and the gainers/losers snapshot are two
    independent reads off the same poll -- a symbol nowhere near its
    circuit must still show up in the snapshot."""
    quote_fn = _fake_quote_fn_with_ohlc({
        "1": {
            "last_price": 100.0,
            "ohlc": {"open": 99.0, "high": 101.0, "low": 98.0, "close": 95.0},
            "volume": 500,
            "upper_circuit_limit": 200.0,
            "lower_circuit_limit": 50.0,
        },
    })
    monitor = CircuitMonitor(quote_fn, "NSE_EQ", proximity_pct=0.02)
    monitor.set_universe({"1": "SAFE_CO"})
    monitor.poll_once()

    assert not monitor.is_flagged("SAFE_CO")
    assert "SAFE_CO" in monitor.get_snapshot()


def test_snapshot_skips_a_symbol_with_no_usable_prev_close():
    """A symbol whose quote is missing/zero on "close" (Dhan's
    previous-day-close field) has no honest %-change reference --
    must not appear in the snapshot at all, not show up with a
    fabricated 0."""
    quote_fn = _fake_quote_fn_with_ohlc({
        "1": {
            "last_price": 100.0,
            "ohlc": {"open": 99.0, "high": 101.0, "low": 98.0, "close": 0},
            "volume": 500,
        },
    })
    monitor = CircuitMonitor(quote_fn, "NSE_EQ")
    monitor.set_universe({"1": "NEWCO"})
    monitor.poll_once()

    assert monitor.get_snapshot() == {}


def test_snapshot_replaced_fresh_each_poll_not_accumulated():
    quote_fn_responses = {
        "1": {
            "last_price": 100.0,
            "ohlc": {"open": 99.0, "high": 101.0, "low": 98.0, "close": 95.0},
            "volume": 500,
        },
        "2": {
            "last_price": 200.0,
            "ohlc": {"open": 199.0, "high": 201.0, "low": 198.0, "close": 195.0},
            "volume": 700,
        },
    }
    quote_fn = _fake_quote_fn_with_ohlc(quote_fn_responses)
    monitor = CircuitMonitor(quote_fn, "NSE_EQ")
    monitor.set_universe({"1": "ONLY_CO"})
    monitor.poll_once()
    assert list(monitor.get_snapshot().keys()) == ["ONLY_CO"]

    # Second poll cycle with a DIFFERENT universe (ONLY_CO no longer
    # tracked, OTHER_CO now is) -- the snapshot must reflect only
    # what was actually polled THIS cycle, no stale carry-over from
    # the previous one.
    monitor.set_universe({"2": "OTHER_CO"})
    monitor.poll_once()
    assert list(monitor.get_snapshot().keys()) == ["OTHER_CO"]
