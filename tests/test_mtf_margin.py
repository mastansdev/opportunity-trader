"""
Tests for core/mtf_margin.py -- the operator's own sizing rule.

    "Buy no of shares worth equal to 1 Lakh = mtf power. ex - as of now
     if i want to buy coforge 1686 rs - qty 225 with 99657.31 rs worth."

The first test is that exact trade, because if the module cannot
reproduce the number the operator read off his own order screen, nothing
else about it matters.
"""

import pytest

from core.mtf_margin import (
    MtfMarginBook, parse_margin, shares_for,
    MIN_SANE_MARGIN_PCT, MAX_SANE_MARGIN_PCT,
)
from config import MTF_MARGIN_PER_POSITION_RS, MTF_FALLBACK_MARGIN_PCT

COFORGE_PRICE = 1686.0
COFORGE_MARGIN = 99657.31 / (1686.0 * 225)      # 26.27%


def _book(response=None, raises=False):
    def calc(security_id, price, quantity):
        if raises:
            raise RuntimeError("network down")
        return response
    return MtfMarginBook(calculator=calc)


def test_it_reproduces_the_operators_own_coforge_trade():
    """225 shares for Rs 1 lakh of margin. His screen, his number."""
    qty = shares_for(COFORGE_PRICE, COFORGE_MARGIN)
    assert qty == int(MTF_MARGIN_PER_POSITION_RS // (1686.0 * 0.2627))


def test_the_margin_committed_never_exceeds_one_lakh():
    """Rounds DOWN. 225.7 becomes 225, never 226."""
    qty = shares_for(COFORGE_PRICE, COFORGE_MARGIN)
    assert qty * COFORGE_PRICE * COFORGE_MARGIN <= MTF_MARGIN_PER_POSITION_RS


def test_a_cheaper_margin_buys_a_bigger_position():
    """The operator's point: leverage is not fixed. 25% margin gives a
    Rs 4L position, 50% gives Rs 2L, for the same Rs 1L commitment."""
    at25 = shares_for(1000.0, 0.25) * 1000.0
    at50 = shares_for(1000.0, 0.50) * 1000.0
    assert at25 == pytest.approx(MTF_MARGIN_PER_POSITION_RS / 0.25, abs=1000)
    assert at50 == pytest.approx(MTF_MARGIN_PER_POSITION_RS / 0.50, abs=1000)


def test_no_mtf_means_own_cash_only():
    """100% margin -- Rs 1 lakh buys Rs 1 lakh of stock. 59 shares of
    COFORGE instead of 225."""
    assert shares_for(COFORGE_PRICE, 1.0) == int(MTF_MARGIN_PER_POSITION_RS // 1686.0)


# --------------------------------------------------------------
# Reading Dhan's response
# --------------------------------------------------------------

def test_it_parses_dhans_margin_response():
    resp = {"data": {"totalMargin": 443.0}}
    pct = parse_margin(resp, price=1686.0, quantity=1)
    assert pct == pytest.approx(0.2627, abs=0.001)


def test_it_parses_a_flat_response_without_a_data_wrapper():
    assert parse_margin({"totalMargin": 443.0}, 1686.0, 1) is not None


def test_an_absurd_margin_is_refused_not_believed():
    """2% margin would mean 50x leverage. That does not exist here, so
    the honest reading is "I do not understand this response"."""
    assert parse_margin({"totalMargin": 33.0}, 1686.0, 1) is None
    assert parse_margin({"totalMargin": 5000.0}, 1686.0, 1) is None


def test_a_junk_response_returns_None():
    for junk in (None, "error", {}, {"data": {}}, {"totalMargin": 0}):
        assert parse_margin(junk, 1686.0, 1) is None


# --------------------------------------------------------------
# Failure posture -- every path must lead to LESS leverage
# --------------------------------------------------------------

def test_a_failed_api_call_falls_back_to_own_cash():
    """Under-leveraging costs opportunity. Over-leveraging on a bad
    number can trigger Dhan's own liquidation."""
    book = _book(raises=True)
    qty, pct, value = book.quantity_for("COFORGE", 11543, COFORGE_PRICE)
    assert pct == MTF_FALLBACK_MARGIN_PCT
    assert qty == int(MTF_MARGIN_PER_POSITION_RS // 1686.0)


def test_no_calculator_wired_at_all_still_sizes_safely():
    book = MtfMarginBook(calculator=None)
    qty, pct, _ = book.quantity_for("COFORGE", 11543, COFORGE_PRICE)
    assert pct == MTF_FALLBACK_MARGIN_PCT
    assert qty == int(MTF_MARGIN_PER_POSITION_RS // 1686.0)


def test_an_unparseable_response_falls_back_rather_than_guessing():
    book = _book(response={"status": "failure"})
    _, pct, _ = book.quantity_for("COFORGE", 11543, COFORGE_PRICE)
    assert pct == MTF_FALLBACK_MARGIN_PCT


def test_a_good_response_gives_the_leveraged_quantity():
    book = _book(response={"data": {"totalMargin": 443.0}})
    qty, pct, value = book.quantity_for("COFORGE", 11543, COFORGE_PRICE)
    assert qty == int(MTF_MARGIN_PER_POSITION_RS // (1686.0 * 0.2627))
    assert pct == pytest.approx(0.2627, abs=0.001)
    assert value == pytest.approx(
        int(MTF_MARGIN_PER_POSITION_RS // (1686.0 * 0.2627)) * 1686.0,
        abs=500)


# --------------------------------------------------------------
# Caching
# --------------------------------------------------------------

def test_the_rate_is_asked_once_and_reused():
    """A live call on every click would put ~300ms between BUY and the
    order going out -- the exact latency being removed elsewhere."""
    calls = []

    def calc(security_id, price, quantity):
        calls.append(security_id)
        return {"data": {"totalMargin": 443.0}}

    book = MtfMarginBook(calculator=calc)
    for _ in range(5):
        book.quantity_for("COFORGE", 11543, COFORGE_PRICE)
    assert len(calls) == 1


def test_a_failure_is_cached_too_so_it_does_not_retry_every_tick():
    calls = []

    def calc(security_id, price, quantity):
        calls.append(security_id)
        raise RuntimeError("down")

    book = MtfMarginBook(calculator=calc)
    for _ in range(5):
        book.quantity_for("COFORGE", 11543, COFORGE_PRICE)
    assert len(calls) == 1


def test_clearing_the_cache_asks_again():
    calls = []

    def calc(security_id, price, quantity):
        calls.append(security_id)
        return {"data": {"totalMargin": 443.0}}

    book = MtfMarginBook(calculator=calc)
    book.quantity_for("COFORGE", 11543, COFORGE_PRICE)
    book.clear()
    book.quantity_for("COFORGE", 11543, COFORGE_PRICE)
    assert len(calls) == 2


def test_two_symbols_are_cached_separately():
    calls = []

    def calc(security_id, price, quantity):
        calls.append(security_id)
        return {"data": {"totalMargin": price * 0.25}}

    book = MtfMarginBook(calculator=calc)
    book.quantity_for("COFORGE", 11543, 1686.0)
    book.quantity_for("TVSMOTOR", 8479, 3991.0)
    assert len(calls) == 2


# --------------------------------------------------------------
# Degenerate inputs must never break a buy
# --------------------------------------------------------------

def test_zero_or_missing_price_returns_zero_shares_not_a_crash():
    assert shares_for(0, 0.25) == 0
    assert shares_for(None, 0.25) == 0
    assert shares_for(1686.0, 0) == 0
