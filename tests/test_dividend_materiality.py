"""
Dividends do NOT block trading -- 2026-07-26.

Operator: "when did i say to block trading for any dividend stocks?
dividend is very minimal effect."

They were right, and DIVIDEND was in PRICE_ADJUSTING on my initiative,
never asked for. Real output from the first live refresh, all of which
were being blocked:

    CRISIL      Rs 10.00 on Rs 4,347  = 0.23%
    TATACAP     Rs  0.57 on Rs   342  = 0.17%
    PERSISTENT  Rs 18.00 on Rs 5,200  = 0.35%
    DEEPAKNTR   Rs  7.50 on Rs 1,650  = 0.45%
    ARE&M       Rs  5.20 on Rs   873  = 0.60%
    DLF         Rs  8.00 on Rs   645  = 1.24%
    WIPRO       Rs  2.00 on Rs   177  = 1.13%

Against a normal 2-3% daily range every one of those is noise.

The single exception kept is a SPECIAL dividend big enough to rescale
the price like a split (DIVIDEND_BLOCK_PCT, 5%). Splits, bonuses, rights
and demergers still block unconditionally -- that is the JLHL case.
"""

from datetime import date

import pytest

from core.stock_memory import (
    DIVIDEND_BLOCK_PCT, INFORMATIONAL, PRICE_ADJUSTING, StockMemory,
    parse_amount,
)

# The real closes, from the daily store on 2026-07-24.
PRICES = {"CRISIL": 4347.20, "TATACAP": 341.90, "PERSISTENT": 5200.50,
          "DEEPAKNTR": 1649.60, "ARE&M": 872.90, "DLF": 645.20,
          "WIPRO": 177.12}

EX = date(2026, 7, 26)


def price_of(symbol):
    return PRICES.get(symbol)


@pytest.fixture
def memory(tmp_path):
    m = StockMemory(url=f"sqlite:///{tmp_path}/mem.db")
    for symbol, detail in [
        ("CRISIL", "Interim Dividend - Rs 10  Per Share"),
        ("TATACAP", "Dividend - Re 0.57 Per Share"),
        ("PERSISTENT", "Dividend - Rs 18 Per Share"),
        ("DEEPAKNTR", "Dividend - Rs 7.50 Per Share"),
        ("ARE&M", "Dividend - Rs 5.20 Per Share"),
        ("DLF", "Dividend - Rs 8 Per Share"),
        ("WIPRO", "Interim Dividend - Rs 2 Per Share"),
    ]:
        m.remember(symbol, "DIVIDEND", EX, detail, source="NSE")
    return m


# ---------------------------------------------------------------
# The classification itself
# ---------------------------------------------------------------

def test_dividend_is_informational_not_price_adjusting():
    assert "DIVIDEND" not in PRICE_ADJUSTING
    assert "DIVIDEND" in INFORMATIONAL


def test_splits_and_friends_are_still_price_adjusting():
    assert PRICE_ADJUSTING == {"SPLIT", "BONUS", "RIGHTS", "DEMERGER"}


# ---------------------------------------------------------------
# No ordinary dividend blocks anything
# ---------------------------------------------------------------

def test_no_ordinary_dividend_blocks_even_without_a_price(memory):
    """The plain call the engine makes. Nothing should come back."""
    assert memory.price_distorting_symbols(EX) == {}


def test_no_ordinary_dividend_blocks_with_a_price_either(memory):
    assert memory.price_distorting_symbols(EX, price_lookup=price_of) == {}


def test_dlf_and_wipro_are_no_longer_blocked(memory):
    """These two were the 'material' ones under the previous 1% rule.
    At 1.24% and 1.13% they are still just dividends."""
    blocked = memory.price_distorting_symbols(EX, price_lookup=price_of)
    assert "DLF" not in blocked
    assert "WIPRO" not in blocked


def test_dividends_are_still_REMEMBERED(memory):
    """Not blocking is not the same as not knowing. The fact stays on
    record and shows up in the reports."""
    assert memory.counts_for("CRISIL") == {"DIVIDEND": 1}
    assert len(memory.facts_for("CRISIL", EX)) == 1


# ---------------------------------------------------------------
# The one exception: a special dividend that rescales the price
# ---------------------------------------------------------------

def test_a_huge_special_dividend_still_blocks(tmp_path):
    """20% of the share price is a rescaling, not a dividend in any
    meaningful sense -- identical in effect to a split."""
    m = StockMemory(url=f"sqlite:///{tmp_path}/m.db")
    m.remember("SPECIAL", "DIVIDEND", EX, "Special Dividend - Rs 200 Per Share")
    blocked = m.price_distorting_symbols(EX, price_lookup=lambda s: 1000.0)
    assert "SPECIAL" in blocked
    assert "special dividend" in blocked["SPECIAL"][0]


def test_just_under_the_threshold_does_not_block(tmp_path):
    m = StockMemory(url=f"sqlite:///{tmp_path}/m.db")
    m.remember("NEARLY", "DIVIDEND", EX, "Dividend - Rs 49 Per Share")
    assert m.price_distorting_symbols(
        EX, price_lookup=lambda s: 1000.0) == {}      # 4.9%


def test_an_unparseable_dividend_does_NOT_block(tmp_path):
    """Reversed from the old rule. 'Dividend' now means 'almost certainly
    noise', so the burden of proof is on blocking, not on trading."""
    m = StockMemory(url=f"sqlite:///{tmp_path}/m.db")
    m.remember("VAGUE", "DIVIDEND", EX, "Dividend declared")
    assert m.price_distorting_symbols(
        EX, price_lookup=lambda s: 1000.0) == {}


def test_an_unknown_price_does_NOT_block(tmp_path):
    m = StockMemory(url=f"sqlite:///{tmp_path}/m.db")
    m.remember("NOPRICE", "DIVIDEND", EX, "Dividend - Rs 500 Per Share")
    assert m.price_distorting_symbols(
        EX, price_lookup=lambda s: None) == {}


def test_the_safety_net_can_be_switched_off(memory):
    m = memory
    m.remember("BIG", "DIVIDEND", EX, "Special Dividend - Rs 300 Per Share")
    assert "BIG" in m.price_distorting_symbols(
        EX, price_lookup=lambda s: 1000.0)
    assert m.price_distorting_symbols(
        EX, price_lookup=lambda s: 1000.0, min_pct=None) == {}


def test_default_threshold_is_documented_and_sane():
    assert DIVIDEND_BLOCK_PCT == 5.0


# ---------------------------------------------------------------
# Splits still behave exactly as before -- the JLHL case
# ---------------------------------------------------------------

def test_a_split_always_blocks_however_it_is_worded(tmp_path):
    """Ratios are not parseable as rupees, and splits are never trivial."""
    m = StockMemory(url=f"sqlite:///{tmp_path}/m.db")
    m.remember("JLHL", "SPLIT", EX, "Face Value Split From Rs 10 To Rs 2")
    m.remember("OTHER", "BONUS", EX, "Bonus 1:1")
    m.remember("THIRD", "DEMERGER", EX, "Scheme of Arrangement")
    blocked = m.price_distorting_symbols(EX, price_lookup=lambda s: 1000.0)
    assert set(blocked) == {"JLHL", "OTHER", "THIRD"}


def test_a_split_blocks_with_no_price_lookup_at_all(tmp_path):
    m = StockMemory(url=f"sqlite:///{tmp_path}/m.db")
    m.remember("JLHL", "SPLIT", EX, "2:10")
    assert "JLHL" in m.price_distorting_symbols(EX)


# ---------------------------------------------------------------
# parse_amount -- still used by the special-dividend net
# ---------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Dividend - Rs 5.20 Per Share", 5.20),
    ("Interim Dividend - Rs 10  Per Share", 10.0),
    ("Dividend - Re 0.57 Per Share", 0.57),            # "Re", not "Rs"
    ("Dividend - Rs. 12 Per Share", 12.0),             # trailing full stop
    ("Special Dividend INR 1,250 Per Share", 1250.0),  # digit grouping
])
def test_parse_amount_handles_the_real_formats(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["", None, "Stock Split 2:10", "Bonus 1:1"])
def test_parse_amount_returns_None_when_there_is_no_amount(text):
    assert parse_amount(text) is None
