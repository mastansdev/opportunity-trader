"""
Tests for core/nse_quotes.py and the bot-vs-NSE verdict.

    "NSE & BOT are not synchronised ... do not deviate from NSE"
                                        -- operator, 2026-07-29

The rule this is held to: NSE's OWN percentage is read, never
recomputed, and a symbol NSE doesn't return is MISSING rather than
guessed. A comparison built on a filled-in blank is worse than no
comparison, because it looks like agreement.
"""

import json

import pytest

from core.nse_quotes import NseQuotes, parse_index_payload

# The real shape of NSE's /api/equity-stockIndices response, trimmed.
PAYLOAD = json.dumps({"data": [
    {"symbol": "INFY", "lastPrice": 1151.38, "previousClose": 1109.95,
     "pChange": 3.73, "open": 1140.0, "dayHigh": 1160.0, "dayLow": 1138.0},
    {"symbol": "COFORGE", "lastPrice": 1739.07, "previousClose": 1720.0,
     "pChange": 1.11, "open": 1725.0, "dayHigh": 1745.0, "dayLow": 1718.0},
]})


def test_it_reads_nses_own_numbers():
    quotes = parse_index_payload(PAYLOAD)
    assert quotes["INFY"]["last"] == 1151.38
    assert quotes["INFY"]["prev_close"] == 1109.95


def test_the_percentage_is_NSEs_not_ours():
    """3.73 is what NSE published. Recomputing it here would defeat
    the entire purpose of the comparison."""
    assert parse_index_payload(PAYLOAD)["INFY"]["pct"] == 3.73


def test_junk_never_becomes_a_quote():
    for junk in (None, "", "garbage", "{}", "[]", '{"data": null}'):
        assert parse_index_payload(junk) == {}


def test_a_row_with_no_usable_price_is_dropped_not_zeroed():
    payload = json.dumps({"data": [
        {"symbol": "DEAD", "lastPrice": 0},
        {"symbol": "ALSODEAD", "lastPrice": None},
        {"symbol": "", "lastPrice": 100},
    ]})
    assert parse_index_payload(payload) == {}


def test_one_dead_index_list_does_not_lose_the_others():
    def fetcher(url):
        if "NIFTY%20500" in url:
            raise RuntimeError("NSE timed out")
        return PAYLOAD

    nse = NseQuotes(fetcher=fetcher,
                    index_lists=("NIFTY%20TOTAL%20MARKET", "NIFTY%20500"))
    assert nse.refresh() == 2
    assert nse.get("INFY") is not None
    assert nse.sources_failed == ["NIFTY%20500"]


def test_a_missing_symbol_reads_as_MISSING():
    nse = NseQuotes(fetcher=lambda url: PAYLOAD,
                    index_lists=("NIFTY%20TOTAL%20MARKET",))
    nse.refresh()
    assert nse.get("NOTLISTED") is None


def test_symbols_are_matched_case_and_space_insensitively():
    nse = NseQuotes(fetcher=lambda url: PAYLOAD,
                    index_lists=("NIFTY%20TOTAL%20MARKET",))
    nse.refresh()
    assert nse.get(" infy ") is not None


def test_no_fetcher_collects_nothing_rather_than_crashing():
    assert NseQuotes(fetcher=None).refresh() == 0


def test_a_fetcher_that_always_raises_is_survivable():
    def explode(url):
        raise RuntimeError("no network")
    nse = NseQuotes(fetcher=explode)
    assert nse.refresh() == 0
    assert nse.get("INFY") is None


# ---------------------------------------------------------------
# The verdict -- three faults must look different
# ---------------------------------------------------------------

from tools.nse_check import classify                        # noqa: E402


def test_agreement_reads_as_OK():
    bot = {"last": 1151.38, "change_pct": 3.73, "prev_close": 1109.95}
    nse = {"last": 1151.40, "pct": 3.73, "prev_close": 1109.95}
    assert classify(bot, nse)[0] == "OK"


def test_same_price_but_a_different_percent_names_the_prev_close():
    """THE case the operator is chasing. The price is right, so the
    feed is fine -- the number the bot divides by is not NSE's. A
    split or bonus NSE adjusted for and the bot did not."""
    bot = {"last": 1151.38, "change_pct": 8.20, "prev_close": 1064.00}
    nse = {"last": 1151.38, "pct": 3.73, "prev_close": 1109.95}
    verdict, detail = classify(bot, nse)
    assert verdict == "PREV CLOSE"
    assert "1,064.00" in detail and "1,109.95" in detail


def test_a_lagging_feed_is_called_PRICE_not_prev_close():
    bot = {"last": 1120.00, "change_pct": 0.90, "prev_close": 1109.95}
    nse = {"last": 1151.38, "pct": 3.73, "prev_close": 1109.95}
    assert classify(bot, nse)[0] in ("PRICE", "BOTH")


def test_a_hairs_difference_is_not_reported_as_a_fault():
    """Two screens read a second apart. Calling that a bug would bury
    the real ones."""
    bot = {"last": 1151.38, "change_pct": 3.73, "prev_close": 1109.95}
    nse = {"last": 1151.50, "pct": 3.74, "prev_close": 1109.95}
    assert classify(bot, nse)[0] == "OK"


def test_a_missing_price_is_never_scored_as_agreement():
    assert classify({"last": None, "change_pct": None},
                    {"last": 100.0, "pct": 1.0})[0] == "NO PRICE"
