r"""
==========================================================
Half the order wins arrived with no rupee figure attached.
==========================================================

    "small company getting a big order is far different to big company
     getting the same order types. bot must distinguish that."
                                -- operator, 22 August 2026

He is right, and the bot could not distinguish them because it was
reading the figure off only 330 of 619 order events. The pattern
REQUIRED a currency marker before the number:

    (?:Rs\.?|Rs|INR)\s*([\d][\d,]*)\s*(crore|cr\b|lakh)

What the channels actually publish:

    POWERGRID  "CO HAS WON LARGE ORDER WORTH 26000 CRS"
    CEIGALL    "CO WINS ORDER WORTH RUPEES 225 CR"
    WELCORP    "INVESTOR CALL ON 217,200 CR ORDER"

No symbol at all, RUPEES spelled out, CRS as the unit. The currency
marker is optional now -- the UNIT is what identifies a money figure,
and "225 CR" is not ambiguous in an order headline.

Coverage went 53% -> 64% of order events.

WHAT THIS DOES NOT FIX

A headline naming several companies still attaches its figure to every
one of them -- VIKRAN's order became POWERGRID's too, and one garbled
card gave WEALTH, LANDMARK and NUVAMA the same Rs 15,840cr. And OCR'd
image cards produce absurd values (ACMESOLAR at Rs 73,404cr). Callers
must sanity-check against the company's own size; the parser only
promises to read what is printed.

Author : H&M Opportunity Trader
==========================================================
"""

from core.catalysts import value_cr


# ---------------------------------------------------------------
# THE HEADLINES IT WAS MISSING
# ---------------------------------------------------------------

def test_no_currency_marker_at_all():
    """THE POWERGRID CASE. 'WORTH 26000 CRS' -- no Rs, and CRS."""
    assert value_cr("CO HAS WON LARGE ORDER WORTH 26000 CRS") == 26000.0


def test_rupees_spelled_out():
    """THE CEIGALL CASE."""
    assert value_cr("CO WINS ORDER WORTH RUPEES 225 CR") == 225.0


def test_a_bare_figure_before_the_unit():
    """THE WELCORP CASE, commas and all."""
    assert value_cr("INVESTOR CALL ON 217,200 CR ORDER") == 217200.0


def test_crores_plural():
    assert value_cr("bags order worth 1,750 crores") == 1750.0


# ---------------------------------------------------------------
# EVERYTHING THAT ALREADY WORKED STILL DOES
# ---------------------------------------------------------------

def test_the_rupee_symbol_still_reads():
    assert value_cr("\u20b978.09 crore hydro-power tender awarded") == 78.09


def test_rs_prefix_still_reads():
    assert value_cr("wins Rs 51.54 crore NHAI contract") == 51.54


def test_mixed_case_cr_still_reads():
    assert value_cr("New \u20b9183.18 Cr residential building order") == 183.18


def test_lakh_is_still_converted_to_crore():
    """A lakh is a hundredth of a crore. Reading it as a crore would
    inflate a small order 100-fold."""
    assert value_cr("order worth 12.5 lakh") == 0.125
    assert value_cr("Rs 250 lakhs contract") == 2.5


# ---------------------------------------------------------------
# AND IT DOES NOT INVENT MONEY
# ---------------------------------------------------------------

def test_a_percentage_is_not_an_order():
    """Making the currency marker optional is only safe because the
    UNIT is still required. These must all stay silent."""
    for text in ("Q1 FY27 revenue up 12%", "FY27 guidance 15% growth",
                 "stock up 4.5 percent today", "board meeting on 25 August",
                 "no money here at all", "EPS of 12.5 for the quarter"):
        assert value_cr(text) is None, text


def test_a_year_is_not_a_figure():
    assert value_cr("results for FY 2026 announced") is None


def test_junk_is_None_not_an_exception():
    for bad in (None, "", 0, [], {}, 12345):
        assert value_cr(bad) is None


def test_the_first_figure_wins_when_a_range_is_printed():
    """'potential 100-110 crore' -- either is defensible; what matters
    is that it returns ONE number and does not raise."""
    got = value_cr("5-year supply order, potential 100-110 crore")
    assert got in (100.0, 110.0)


def test_the_reason_is_written_down_where_it_broke():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "core" / "catalysts.py").read_text(encoding="utf-8")
    assert "26000 CRS" in src and "RUPEES 225 CR" in src
