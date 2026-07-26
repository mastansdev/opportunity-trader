"""
==========================================================
Tests -- universe builder (bhavcopy-driven maintenance)
==========================================================

The classification is a pure function, so these pin the rules exactly:
T2T is refused, the price band is enforced at both ends, illiquid names
are dropped, and new listings are proposed as additions.

The T2T case is the one that matters most -- intraday is not permitted
on those at all, and in LIVE trading it becomes compulsory delivery.

Author : H&M Opportunity Trader
==========================================================
"""

from core.universe_builder import (
    MAX_PRICE, MIN_PRICE, MIN_TURNOVER_RS, classify,
)

CR = 10_000_000


def _row(symbol, series="EQ", close=500.0, turnover=10 * CR, volume=None,
         udiff=False):
    """A bhavcopy row in either the legacy or UDIFF column naming."""
    if udiff:
        return {"TckrSymb": symbol, "SctySrs": series, "ClsPric": str(close),
                "TtlTradgVol": str(volume or 1000), "TtlTrfVal": str(turnover)}
    return {"SYMBOL": symbol, "SERIES": series, "CLOSE": str(close),
            "TOTTRDQTY": str(volume or 1000), "TOTTRDVAL": str(turnover)}


def _reasons(result):
    return {r["symbol"]: r["reason"] for r in result["rejected"]}


# ---------------------------------------------------------------
# THE ONE THAT COSTS REAL MONEY
# ---------------------------------------------------------------

def test_trade_to_trade_series_is_refused():
    """BE/BZ = trade-to-trade. Intraday is NOT allowed; in live trading
    this becomes compulsory delivery and shorting is impossible."""
    res = classify([_row("SOMET2T", series="BE")], {"SOMET2T"})
    assert not res["keep"]
    assert "NO INTRADAY" in _reasons(res)["SOMET2T"]
    # ...and because we hold it, it's proposed for removal
    assert [r["symbol"] for r in res["to_remove"]] == ["SOMET2T"]


def test_only_eq_series_survives():
    rows = [_row("A", series="EQ"), _row("B", series="BE"),
            _row("C", series="BZ"), _row("D", series="SM")]
    res = classify(rows, set())
    assert [r["symbol"] for r in res["keep"]] == ["A"]


# ---------------------------------------------------------------
# Price band -- both ends, for different reasons
# ---------------------------------------------------------------

def test_cheap_stocks_are_dropped_for_tick_noise():
    res = classify([_row("PENNY", close=MIN_PRICE - 1)], set())
    assert not res["keep"]
    assert "tick noise" in _reasons(res)["PENNY"]


def test_very_expensive_stocks_are_dropped_because_sizing_breaks():
    """A Rs 2L position buys 1 share of a Rs 1,30,850 stock -- whole-share
    rounding destroys the Rs 800 risk model."""
    res = classify([_row("MRF", close=130850.0)], set())
    assert not res["keep"]
    assert "sizing breaks" in _reasons(res)["MRF"]


def test_the_band_edges_are_inclusive():
    res = classify([_row("LOW", close=MIN_PRICE),
                    _row("HIGH", close=MAX_PRICE)], set())
    assert {r["symbol"] for r in res["keep"]} == {"LOW", "HIGH"}


def test_midrange_stocks_are_kept():
    """Rs 2k-10k still gives 28-69 shares and real movement -- cutting at
    Rs 2,000 would drop good stocks for no measured benefit."""
    res = classify([_row("MIDPRICE", close=5000.0)], set())
    assert [r["symbol"] for r in res["keep"]] == ["MIDPRICE"]


# ---------------------------------------------------------------
# Liquidity
# ---------------------------------------------------------------

def test_illiquid_names_are_dropped():
    res = classify([_row("THIN", turnover=MIN_TURNOVER_RS - 1)], set())
    assert not res["keep"]
    assert "illiquid" in _reasons(res)["THIN"]


def test_turnover_is_derived_when_absent():
    """Some bhavcopy variants omit turnover -- close x volume stands in."""
    row = _row("X", close=1000.0, volume=100000)
    row.pop("TOTTRDVAL")
    res = classify([row], set())
    assert [r["symbol"] for r in res["keep"]] == ["X"]      # 10cr derived


# ---------------------------------------------------------------
# Universe maintenance
# ---------------------------------------------------------------

def test_new_listings_are_proposed_as_additions():
    res = classify([_row("NEWIPO", turnover=50 * CR)], {"OLD"})
    assert [r["symbol"] for r in res["to_add"]] == ["NEWIPO"]


def test_additions_are_ranked_by_turnover():
    rows = [_row("SMALL", turnover=6 * CR), _row("BIG", turnover=90 * CR)]
    res = classify(rows, set())
    assert [r["symbol"] for r in res["to_add"]] == ["BIG", "SMALL"]


def test_symbols_absent_from_the_bhavcopy_are_flagged():
    """Delisted / suspended / renamed -- worth a human look, not an
    automatic delete."""
    res = classify([_row("STILLHERE")], {"STILLHERE", "VANISHED"})
    assert res["missing_from_bhavcopy"] == ["VANISHED"]


def test_a_held_symbol_that_still_qualifies_is_left_alone():
    res = classify([_row("GOOD")], {"GOOD"})
    assert [r["symbol"] for r in res["unchanged"]] == ["GOOD"]
    assert res["to_add"] == [] and res["to_remove"] == []


def test_udiff_column_names_are_handled():
    """NSE changed the bhavcopy format in July 2024."""
    res = classify([_row("UDIFFSTK", udiff=True)], set())
    assert [r["symbol"] for r in res["keep"]] == ["UDIFFSTK"]


def test_junk_rows_never_crash_it():
    rows = [{}, {"SYMBOL": ""}, _row("OK"), {"SYMBOL": "NOPRICE",
            "SERIES": "EQ", "CLOSE": "abc", "TOTTRDVAL": "x"}]
    res = classify(rows, set())
    assert [r["symbol"] for r in res["keep"]] == ["OK"]
