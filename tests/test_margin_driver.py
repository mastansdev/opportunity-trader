"""
Pins core/margin_driver.py against the day that produced it.

PANAMAPET Q1 FY27, 12 August 2026. PULSE EXCELLENT + CLEAN, all-time
high 599.60, closed 518.75 -- one stop-out. GANDHAR printed the same
shape on 23 July, SAVITA the same week.

The rule this module must obey, from core/result_tag.py and SHILPAMED
on 5 August: it may add a chip and a note, it may NEVER change the tag.
"""

import pytest

from core import margin_driver


def _fields(sales_now, sales_year, op_now, op_year):
    """The grid core/result_read.py returns, only the keys we consume."""
    return {"quarters": {
        "sales": {"now": sales_now, "prev": None, "year": sales_year},
        "op": {"now": op_now, "prev": None, "year": op_year},
        "opm": {"now": round(op_now / sales_now * 100, 2),
                "prev": None,
                "year": round(op_year / sales_year * 100, 2)},
    }}


# Rs crore, off the real filings.
PANAMA = _fields(1735.15, 693.22, 391.76, 58.90)     # 22.58% vs 8.50%
GANDHAR = _fields(1731.93, 907.00, 281.26, 46.17)    # 16.24% vs  5.09%
SAVITA = _fields(1479.76, 989.14, 364.00, 60.67)     # 24.60% vs  6.13%
STEADY = _fields(760.00, 693.22, 68.40, 58.90)       #  9.00% vs  8.50%


def _peers(*pairs):
    return [{"symbol": s, "delta_pp": margin_driver.margin_delta_pp(f),
             "sector": None, "at": "2026-07-23"} for s, f in pairs]


# ---------------------------------------------------------------- maths

def test_margin_delta_reads_the_grid():
    assert margin_driver.margin_delta_pp(PANAMA) == pytest.approx(14.08, abs=0.1)


def test_incremental_margin_is_the_new_revenue_only():
    # (391.76 - 58.90) / (1735.15 - 693.22) = 31.9%
    assert margin_driver.incremental_margin(PANAMA) == pytest.approx(0.319, abs=0.005)


def test_leverage_ceiling_is_smaller_than_the_move():
    # A converter's fixed base is ~5% of revenue. It cannot lift margin
    # 14pp no matter how much revenue arrives. This is arithmetic.
    # 15% fixed opex is generous for any manufacturer and very
    # generous for a converter. Even so it caps the gain at ~9pp
    # against 14.1pp observed, so leverage cannot be the explanation.
    ceiling = margin_driver.leverage_ceiling_pp(PANAMA, "PANAMAPET")
    assert ceiling == pytest.approx(9.0, abs=0.2)
    assert margin_driver.margin_delta_pp(PANAMA) > ceiling


def test_unreadable_grid_says_nothing():
    assert margin_driver.margin_delta_pp({}) is None
    assert margin_driver.assess("X", {}, peers=[]) is None
    assert margin_driver.assess("X", None, peers=None) is None


# ------------------------------------------------------------ the case

def test_panamapet_fires_sector_wide():
    got = margin_driver.assess(
        "PANAMAPET", PANAMA,
        peers=_peers(("GANDHAR", GANDHAR), ("SAVITA", SAVITA)))
    assert got is not None
    assert got["driver"] == "SECTOR_WIDE"
    assert got["chip"] == "SECTOR-WIDE MARGIN"
    assert set(got["peers"]) == {"GANDHAR", "SAVITA"}
    assert any("not new information" in w for w in got["why"])


def test_alone_it_is_price_not_sector():
    # Same filing, no peer reported. The peer claim must not be made.
    got = margin_driver.assess("PANAMAPET", PANAMA, peers=[])
    assert got is not None
    assert got["driver"] == "PRICE"
    assert got["chip"] == "MARGIN = PRICE"
    assert got["peers"] == []


def test_one_peer_is_not_enough():
    got = margin_driver.assess("PANAMAPET", PANAMA,
                               peers=_peers(("GANDHAR", GANDHAR)))
    assert got["driver"] == "PRICE"          # not SECTOR_WIDE on n=1


def test_an_ordinary_quarter_is_silent():
    # +0.5pp on a business growing 10%. Nothing to say.
    assert margin_driver.assess("STEADY", STEADY, peers=[]) is None


def test_peers_moving_the_other_way_do_not_count():
    down = _fields(700.0, 693.22, 21.0, 58.90)        # margin collapsed
    got = margin_driver.assess("PANAMAPET", PANAMA,
                               peers=_peers(("A", down), ("B", down)))
    assert got["driver"] == "PRICE"          # opposite sign, not correlated


# ------------------------------------------------- the standing rule

def test_it_can_never_change_the_tag():
    """SHILPAMED, 5 August: a forensic flag said SKIP and the stock
    closed +11.96%. Nothing here is allowed to do that again."""
    got = margin_driver.assess(
        "PANAMAPET", PANAMA,
        peers=_peers(("GANDHAR", GANDHAR), ("SAVITA", SAVITA)))
    assert "tag" not in got
    assert got["chip"] not in ("EXCELLENT", "GOOD", "AVOID")
    assert set(got) == {"driver", "chip", "note", "why", "delta_pp", "peers"}
