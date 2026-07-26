"""
Dividend materiality -- 2026-07-26.

The stock memory was built for the JLHL case: a 2:10 split that the bot
read as an 80% crash. Correct. But the same rule was then blocking
liquid large-caps for trivial dividends. Real output from the first live
refresh:

    CRISIL      Rs 10.00 on Rs 4,347  = 0.23%   <- blocked
    TATACAP     Rs  0.57 on Rs   342  = 0.17%   <- blocked
    PERSISTENT  Rs 18.00 on Rs 5,200  = 0.35%   <- blocked
    DEEPAKNTR   Rs  7.50 on Rs 1,650  = 0.45%   <- blocked
    ARE&M       Rs  5.20 on Rs   873  = 0.60%   <- blocked
    DLF         Rs  8.00 on Rs   645  = 1.24%   <- correctly blocked
    WIPRO       Rs  2.00 on Rs   177  = 1.13%   <- correctly blocked

Five of seven were lost for nothing -- 0.23% is inside the noise of any
normal 2-3% daily range.
"""

from datetime import date

import pytest

from core.stock_memory import (
    MIN_DIVIDEND_DISTORTION_PCT, StockMemory, parse_amount,
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
# parse_amount
# ---------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Dividend - Rs 5.20 Per Share", 5.20),
    ("Interim Dividend - Rs 10  Per Share", 10.0),
    ("Dividend - Re 0.57 Per Share", 0.57),       # "Re", not "Rs"
    ("Dividend - Rs. 12 Per Share", 12.0),        # trailing full stop
    ("Special Dividend INR 1,250 Per Share", 1250.0),   # digit grouping
])
def test_parse_amount_handles_the_real_formats(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["", None, "Stock Split 2:10", "Bonus 1:1"])
def test_parse_amount_returns_None_when_there_is_no_amount(text):
    assert parse_amount(text) is None


# ---------------------------------------------------------------
# The gate
# ---------------------------------------------------------------

def test_without_a_price_lookup_everything_still_blocks(memory):
    """Backward compatibility: the conservative path stays the default,
    so no existing caller changes behaviour."""
    blocked = memory.price_distorting_symbols(EX)
    assert set(blocked) == set(PRICES)


def test_only_material_dividends_block(memory):
    blocked = memory.price_distorting_symbols(EX, price_lookup=price_of)
    assert set(blocked) == {"DLF", "WIPRO"}


def test_the_five_trivial_ones_are_released(memory):
    blocked = memory.price_distorting_symbols(EX, price_lookup=price_of)
    for symbol in ("CRISIL", "TATACAP", "PERSISTENT", "DEEPAKNTR", "ARE&M"):
        assert symbol not in blocked, f"{symbol} should be tradeable"


def test_the_reason_now_carries_the_percentage(memory):
    blocked = memory.price_distorting_symbols(EX, price_lookup=price_of)
    assert "1.24% of price" in blocked["DLF"][0]


def test_immaterial_symbols_makes_the_decision_auditable(memory):
    """A stock quietly NOT being blocked must still be visible."""
    ignored = memory.immaterial_symbols(EX, price_lookup=price_of)
    assert set(ignored) == {"CRISIL", "TATACAP", "PERSISTENT",
                            "DEEPAKNTR", "ARE&M"}
    assert ignored == {} or "DLF" not in ignored


def test_a_split_always_blocks_however_it_is_worded(tmp_path):
    """The JLHL case. Ratios are not parseable as rupees, and splits are
    never trivial -- they must block unconditionally."""
    m = StockMemory(url=f"sqlite:///{tmp_path}/m.db")
    m.remember("JLHL", "SPLIT", EX, "Face Value Split From Rs 10 To Rs 2")
    m.remember("OTHER", "BONUS", EX, "Bonus 1:1")
    blocked = m.price_distorting_symbols(EX, price_lookup=lambda s: 1000.0)
    assert set(blocked) == {"JLHL", "OTHER"}


def test_an_unparseable_dividend_blocks_FAIL_CLOSED(tmp_path):
    """An unmeasurable distortion must never be assumed to be small."""
    m = StockMemory(url=f"sqlite:///{tmp_path}/m.db")
    m.remember("VAGUE", "DIVIDEND", EX, "Dividend declared")
    blocked = m.price_distorting_symbols(EX, price_lookup=lambda s: 1000.0)
    assert "VAGUE" in blocked


def test_an_unknown_price_blocks_FAIL_CLOSED(tmp_path):
    m = StockMemory(url=f"sqlite:///{tmp_path}/m.db")
    m.remember("NOPRICE", "DIVIDEND", EX, "Dividend - Rs 1 Per Share")
    blocked = m.price_distorting_symbols(EX, price_lookup=lambda s: None)
    assert "NOPRICE" in blocked


def test_a_raising_price_lookup_blocks_FAIL_CLOSED(tmp_path):
    def boom(symbol):
        raise RuntimeError("store unavailable")
    m = StockMemory(url=f"sqlite:///{tmp_path}/m.db")
    m.remember("X", "DIVIDEND", EX, "Dividend - Rs 1 Per Share")
    assert "X" in m.price_distorting_symbols(EX, price_lookup=boom)


def test_the_threshold_is_adjustable(memory):
    # At 0.5%, ARE&M (0.60%) joins the blocked set.
    blocked = memory.price_distorting_symbols(EX, price_lookup=price_of,
                                              min_pct=0.5)
    assert set(blocked) == {"DLF", "WIPRO", "ARE&M"}
    # At 2%, nothing is material enough.
    assert memory.price_distorting_symbols(
        EX, price_lookup=price_of, min_pct=2.0) == {}


def test_a_big_special_dividend_still_blocks(tmp_path):
    """The threshold must not become a hole. A 12% special dividend is
    exactly the distortion this whole module exists for."""
    m = StockMemory(url=f"sqlite:///{tmp_path}/m.db")
    m.remember("SPECIAL", "DIVIDEND", EX, "Special Dividend - Rs 120 Per Share")
    blocked = m.price_distorting_symbols(EX, price_lookup=lambda s: 1000.0)
    assert "SPECIAL" in blocked


def test_default_threshold_is_documented_and_sane():
    assert MIN_DIVIDEND_DISTORTION_PCT == 1.0
