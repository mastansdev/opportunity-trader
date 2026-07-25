"""
IndexMonitor tests (core/index_monitor.py) -- Nifty/BankNifty/Midcap/
VIX feed store. Fail-open: unknown ids ignored, missing data reported
as unavailable, % change only once both LTP and prev close are known.
"""

from core.index_monitor import IndexMonitor


def _mon():
    return IndexMonitor({"13": "nifty", "25": "banknifty", "21": "vix"})


def test_pct_change_computed_once_ltp_and_prev_close_known():
    m = _mon()
    m.on_index_tick("13", prev_close=22000.0)
    m.on_index_tick("13", ltp=22220.0)
    snap = m.snapshot()
    assert snap["nifty"]["available"] is True
    assert snap["nifty"]["ltp"] == 22220.0
    assert snap["nifty"]["pct"] == 1.0


def test_index_with_no_ltp_is_unavailable():
    m = _mon()
    m.on_index_tick("25", prev_close=48000.0)  # prev close only, no LTP
    snap = m.snapshot()
    assert snap["banknifty"]["available"] is False
    assert snap["banknifty"]["pct"] is None


def test_unknown_security_id_is_ignored():
    m = _mon()
    m.on_index_tick("99999", ltp=100.0)  # not an index we track
    snap = m.snapshot()
    assert "99999" not in snap
    # tracked names still present, just empty
    assert snap["nifty"]["available"] is False


def test_index_security_ids_exposes_the_routing_set():
    m = _mon()
    assert m.index_security_ids() == {"13", "25", "21"}


def test_zero_or_negative_values_are_ignored():
    m = _mon()
    m.on_index_tick("13", ltp=0.0, prev_close=-5.0)
    snap = m.snapshot()
    assert snap["nifty"]["available"] is False
