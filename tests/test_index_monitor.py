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


# ---------------------------------------------------------------
# ROUTING -- segment first, then id
# ---------------------------------------------------------------
# The worst data bug this project has had. Index ids and equity ids are
# separate numbering spaces and they collide:
#
#     IDX_I 13 = NIFTY 50       NSE_EQ 13 = ABB INDIA
#     IDX_I 25 = NIFTY BANK     NSE_EQ 25 = ADANI ENTERPRISES
#
# main.py's router keyed on the id ALONE, before the symbol lookup, so on
# 2026-07-28 every ABB and ADANIENT tick was captured by the index
# monitor and returned early. Both stocks were subscribed, both were in
# the universe, and neither produced a single candle, opening range or
# gainers row for the whole session. Nothing logged an error.
#
# The Nifty tile showed 7,234 -- ABB's share price -- while Nifty 50 was
# near 24,000. That was diagnosed as "wrong security ids" and
# INDEX_INSTRUMENTS was emptied. The ids were right; the routing was not.

from core.index_monitor import is_index_segment          # noqa: E402

IDX, NSE_EQ = 0, 1


def _packet(security_id, segment, ltp="24000.00", **extra):
    p = {"security_id": security_id, "exchange_segment": segment,
         "LTP": ltp, "close": ltp}
    p.update(extra)
    return p


def test_an_equity_packet_is_not_an_index_packet():
    """ABB's real 2026-07-28 tick. It carries volume and a last-traded
    quantity, which no index has -- but the router never looked."""
    abb = _packet(13, NSE_EQ, ltp="7234.00", volume=16838, LTQ=6)
    assert is_index_segment(abb) is False


def test_an_index_packet_is_recognised():
    assert is_index_segment(_packet(13, IDX)) is True
    assert is_index_segment(_packet(13, "IDX_I")) is True


def test_owns_requires_both_segment_and_id():
    m = _mon()
    assert m.owns("13", _packet(13, IDX)) is True
    # Same id, equity segment -- this is ABB and must NOT be claimed.
    assert m.owns("13", _packet(13, NSE_EQ)) is False
    # Index segment, unconfigured id.
    assert m.owns("99", _packet(99, IDX)) is False


def test_abb_ticks_are_not_swallowed_by_the_index_monitor():
    """The regression that cost two live stocks a whole session."""
    m = _mon()
    abb = _packet(13, NSE_EQ, ltp="7234.00", volume=16838)
    assert m.owns("13", abb) is False, \
        "ABB's tick was claimed by the index monitor -- the 2026-07-28 bug"
    m.on_index_tick("13", ltp=7234.0) if m.owns("13", abb) else None
    assert m.snapshot()["nifty"]["available"] is False, \
        "an equity price reached the Nifty tile"


def test_adanient_ticks_are_not_swallowed_either():
    m = _mon()
    adanient = _packet(25, NSE_EQ, ltp="3007.70", volume=50246)
    assert m.owns("25", adanient) is False


def test_a_junk_packet_is_not_an_index_packet():
    assert is_index_segment(None) is False
    assert is_index_segment({}) is False
    assert is_index_segment({"exchange_segment": 2}) is False   # NSE_FNO
