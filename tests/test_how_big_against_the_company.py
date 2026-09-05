"""
==========================================================
Rs 100 crore is 50% of one company and 1% of another
==========================================================

    "see the order is compared to Market price of the company &
     pricing the stock. check the % of that order to their market
     cap. this reveal the significance of the order book.
     ex simple = 100 cr order for 200 MCAP & 10000 MCAP company
     1st is 50% & the other is 1%"
                                -- the operator, 5 September 2026

He is right, and this bot's own store proves it. Ranked by RUPEES the
top of the order list was JNPR's investor presentation, where the
figure was a megawatt capacity target. Ranked by SHARE OF THE COMPANY:

    date        stock         order    free float   share      3d     10d
    2026-08-21  NUVAMA     15,840cr     14,099cr    112%   +2.0%       -
    2026-08-26  ADANIENSOL 24,700cr     46,996cr     53%   -9.7%       -
    2026-08-20  WELCORP    15,840cr     33,636cr     47%  +17.0%  +31.7%
    2026-08-27  TEJASNET    1,537cr      5,043cr     30%   +6.0%       -
    2026-08-13  RAILTEL       630cr      2,370cr     27%   -2.8%   -2.2%
    2026-08-03  KEC         1,063cr      5,281cr     20%   -0.2%   -8.9%

Three things that ordering does and rupees does not:

  L&T's Rs 15,000 cr order is THREE PERCENT of L&T. On the rupee list
  it sat near the top; it is a rounding error for that company.

  RAILTEL's Rs 630 cr is a QUARTER of Railtel. On the rupee list it was
  invisible.

  NUVAMA reads 112% -- an order larger than the whole company. That row
  is an acquisition APPROACH, and this measure catches it without a
  rule being written for it. So the share is never clipped to 100:
  hiding it would hide the most useful thing the measure does.

WHAT IT IS NOT. Not a signal, and this is measured, not assumed. Of the
eleven orders above 20% of their company, WELCORP and TEJASNET rose
meaningfully by three sessions and AFCONS, NBCC, RAILTEL and KEC fell.
A better ordering is not a prediction, and nothing here votes on a
trade -- see tests/test_what_is_still_standing.py, which enforces that
no gate reads any of it.

TWO LIMITS, both carried on the reading rather than buried.

  FREE FLOAT, not full market cap. It is what NSE publishes in bulk;
  the full figure is per-symbol only. Free float excludes promoter
  holding, so a promoter-heavy company reads smaller and its orders
  read as more significant. The share is an UPPER bound.

  PARTIAL COVERAGE. About 500 of the 1,976 symbols on file. A stock
  whose size is unknown shows the rupees alone -- never a guess, never
  a default, because implying a company is tiny is worse than saying
  nothing.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import tempfile

import pytest

from core import market_cap


@pytest.fixture()
def store():
    """His own example: a Rs 200 cr company and a Rs 10,000 cr one."""
    path = os.path.join(tempfile.mkdtemp(), "market_cap.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"at": "2026-09-05T22:00:00",
                   "unit": "crore rupees",
                   "caps": {"SMALLCO": 200.0, "BIGCO": 10000.0,
                            "WELCORP": 33636.0, "LT": 528000.0}}, fh)
    return path


# ------------------------------------------------------------------
# his example, exactly
# ------------------------------------------------------------------

def test_the_same_order_is_half_of_one_company_and_a_hundredth_of_another(
        store):
    assert market_cap.share_of_company("SMALLCO", 100.0, store) == 50.0
    assert market_cap.share_of_company("BIGCO", 100.0, store) == 1.0


def test_welspun_reads_as_transformative(store):
    assert market_cap.share_of_company("WELCORP", 15840.0, store) == 47.1


def test_a_huge_order_to_a_huge_company_reads_as_small(store):
    """L&T's Rs 15,000 cr sat near the top of the rupee list."""
    got = market_cap.share_of_company("LT", 15000.0, store)
    assert got is not None and got < 5.0


def test_an_order_bigger_than_the_company_is_shown_as_it_is(store):
    """NUVAMA reads 112%. That row is an acquisition approach, and the
    number saying so is the point -- clipping it to 100 would hide the
    most useful thing this measure does."""
    assert market_cap.share_of_company("SMALLCO", 400.0, store) == 200.0


# ------------------------------------------------------------------
# never guess a size
# ------------------------------------------------------------------

def test_an_unknown_company_gets_no_share(store):
    """Implying a company is tiny is worse than saying nothing."""
    assert market_cap.of("NOSUCH", store) is None
    assert market_cap.share_of_company("NOSUCH", 100.0, store) is None


def test_a_missing_store_is_not_an_error():
    missing = os.path.join(tempfile.mkdtemp(), "nothing.json")
    assert market_cap.of("WELCORP", missing) is None
    assert market_cap.share_of_company("WELCORP", 100.0, missing) is None
    assert market_cap.status(missing)["available"] is False


def test_an_unreadable_store_is_not_an_error(tmp_path):
    bad = tmp_path / "market_cap.json"
    bad.write_text("{not json at all", encoding="utf-8")
    assert market_cap.of("WELCORP", str(bad)) is None


def test_no_value_means_no_share(store):
    assert market_cap.share_of_company("WELCORP", None, store) is None
    assert market_cap.share_of_company("WELCORP", 0, store) is None


# ------------------------------------------------------------------
# the reading says what it is
# ------------------------------------------------------------------

def test_the_reading_says_it_is_free_float(store):
    got = market_cap.status(store)
    assert got["available"] is True
    assert got["symbols"] == 4
    assert got["basis"] == "free float"


def test_a_stale_reading_says_so(tmp_path):
    """A week-old size is fine; believing it silently is not."""
    old = tmp_path / "market_cap.json"
    old.write_text(json.dumps({"at": "2026-01-01T10:00:00",
                               "caps": {"X": 100.0}}), encoding="utf-8")
    got = market_cap.status(str(old))
    assert got["stale"] is True
    assert got["age_days"] > market_cap.STALE_AFTER_DAYS


# ------------------------------------------------------------------
# and it reaches the sentence
# ------------------------------------------------------------------

def test_the_sentence_carries_the_share(monkeypatch, store):
    from core import cause_effect as ce
    monkeypatch.setattr(market_cap, "STORE", store)
    got = ce._sentence("WELCORP", "2026-08-21", 15840.0,
                       "WELSPUN CORP: SECURES LARGEST-EVER ORDER", 10)
    assert got["pct_of_company"] == 47.1
    assert got["cap_basis"] == "free float"
    assert "47% of the company" in got["text"]
    assert "10 sessions ago" in got["text"]


def test_the_sentence_is_still_readable_without_a_size(monkeypatch,
                                                       store):
    from core import cause_effect as ce
    monkeypatch.setattr(market_cap, "STORE", store)
    got = ce._sentence("NOSUCH", "2026-08-21", 900.0,
                       "NOSUCH LTD: RECEIVES ORDER", 3)
    assert got["pct_of_company"] is None
    assert got["text"] == "Rs 900 cr order, 3 sessions ago"


def test_one_session_is_not_pluralised(monkeypatch, store):
    from core import cause_effect as ce
    monkeypatch.setattr(market_cap, "STORE", store)
    got = ce._sentence("NOSUCH", "2026-09-04", 900.0, "X LTD: ORDER", 1)
    assert "1 session ago" in got["text"]


# ------------------------------------------------------------------
# the refresher exists and is not on the trading path
# ------------------------------------------------------------------

def test_the_refresher_is_a_tool_not_a_gate():
    import io
    assert os.path.exists("tools/refresh_market_cap.py")
    for path in ("core/ranker.py", "core/auto_entry.py",
                 "core/engine.py", "core/why_moving.py"):
        src = io.open(path, encoding="utf-8").read()
        assert "market_cap" not in src, \
            f"{path} reads company size -- that was never decided"
