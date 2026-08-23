r"""
==========================================================
VIKRAN's order became POWERGRID's as well.
==========================================================

    "fix the multi symbol attribution bug"  -- operator, 22 Aug 2026

Live rows off data/stock_events.db:

    VIKRAN      2,120.7 cr   |  POWERGRID   2,120.7 cr
    ASTRAMICRO  2,205.2 cr   |  HAL         2,205.2 cr
    WEALTH / LANDMARK / NUVAMA   15,840 cr each, one garbled card

events_from_message() built one `common` dict carrying value_cr and
handed the SAME dict to every symbol the card mentioned. A news-channel
screenshot naming four companies gave all four the same order value.

The counterparty rule above it catches the BUYER when the card names
one -- "Astra Microwave secures Rs 2,205 Cr order from HAL" correctly
drops HAL. It cannot help when a card simply mentions several
companies, which is what an OCR'd TV screenshot does constantly.

THE EVENT STAYS, THE MONEY GOES

The card did mention them, and that is worth recording. But a figure
that cannot be pinned to ONE company is not that company's order
value, and a wrong number is worse than none -- it was feeding the
"is this order big for THIS company" measurement the operator asked
for, which is exactly where a mis-attributed value does most damage.

Same doctrine as symbols_first(): one tag means one subject, several
means none. This applies it to the money.

AND THERE WERE TWO MONEY PARSERS

core/catalysts.value_cr() and core/stock_events.amount_in_crore() both
required a currency marker before the number, and the CHANNELS DO NOT
WRITE ONE. The second is the one that fills the stored value_cr. Both
now accept a bare figure, provided the UNIT is present.

Author : H&M Opportunity Trader
==========================================================
"""

from core.stock_events import amount_in_crore, events_from_message


class _Matcher:
    """Names whatever symbols appear in the text."""

    def __init__(self, symbols):
        self.symbols = symbols

    def symbols_in(self, text):
        return [s for s in self.symbols if s in str(text).upper()]

    def names_in(self, text):
        return []


def _rows(symbols, text):
    return events_from_message(_Matcher(symbols), text=text,
                               at="2026-08-22T05:00:00+00:00") or []


# ---------------------------------------------------------------
# ONE COMPANY KEEPS ITS FIGURE
# ---------------------------------------------------------------

def test_a_single_company_keeps_the_order_value():
    got = _rows(["ASTRAMICRO"], "ASTRAMICRO wins order worth RUPEES 2205 CR")
    assert got, "the order event vanished entirely"
    assert got[0]["value_cr"] == 2205.0


# ---------------------------------------------------------------
# SEVERAL COMPANIES KEEP NOTHING
# ---------------------------------------------------------------

def test_two_companies_on_one_card_get_no_value():
    """THE CASE. VIKRAN's Rs 2,120cr order became POWERGRID's too."""
    got = _rows(["VIKRAN", "POWERGRID"],
                "VIKRAN wins order worth 2120 CR, POWERGRID also in focus")
    assert len(got) == 2
    assert all(r["value_cr"] is None for r in got), (
        "one order is still being credited to several companies")


def test_the_event_itself_is_still_recorded():
    """Dropping the money must not drop the news. The card did mention
    them and that is worth knowing."""
    got = _rows(["VIKRAN", "POWERGRID"],
                "VIKRAN wins order worth 2120 CR, POWERGRID also in focus")
    assert {r["symbol"] for r in got} == {"VIKRAN", "POWERGRID"}
    assert all(r.get("headline") for r in got)


def test_three_companies_are_already_refused_entirely():
    """WEALTH, LANDMARK and NUVAMA all showed Rs 15,840cr from one
    OCR'd screenshot -- but that is a THREE-company card, and

        # A MESSAGE ABOUT THREE COMPANIES IS ABOUT NONE OF THEM.
        if len(symbols) >= 3: return []

    already dropped it. Those rows predate that rule. The gap this file
    fixes is EXACTLY TWO companies with no hashtag to say whose card it
    is -- the VIKRAN/POWERGRID and ASTRAMICRO/HAL shape, which fell
    between the hashtag rule above and the three-company rule below."""
    assert _rows(["WEALTH", "LANDMARK", "NUVAMA"],
                 "WEALTH LANDMARK NUVAMA order 15840 CR") == []


def test_a_hashtag_still_narrows_to_one_and_keeps_the_value():
    """The existing rule: when the caption tags the subject, the card
    belongs to that company alone -- and it keeps its money."""
    got = _rows(["ASTRAMICRO", "HAL"],
                "#ASTRAMICRO secures order worth RUPEES 2205 CR from HAL")
    assert len(got) == 1 and got[0]["symbol"] == "ASTRAMICRO"
    assert got[0]["value_cr"] == 2205.0


# ---------------------------------------------------------------
# THE PARSER THE EVENTS PATH ACTUALLY USES
# ---------------------------------------------------------------

def test_a_bare_figure_is_read():
    """core/stock_events.amount_in_crore -- the one that fills the
    stored value_cr. catalysts.value_cr is a SECOND parser with the
    same bug, and fixing only that one changed nothing on this path."""
    assert amount_in_crore("CO HAS WON LARGE ORDER WORTH 26000 CRS") == 26000.0
    assert amount_in_crore("order worth RUPEES 2205 CR") == 2205.0
    assert amount_in_crore("INVESTOR CALL ON 217,200 CR ORDER") == 217200.0


def test_what_already_worked_still_does():
    assert amount_in_crore("wins Rs 51.54 crore NHAI contract") == 51.54
    assert amount_in_crore("\u20b978.09 crore tender") == 78.09
    assert amount_in_crore("order worth 12.5 lakh") == 0.12


def test_dollars_are_still_converted():
    """A bare figure has no prefix, so `dollars` stays False and it
    reads as rupees. USD must keep its own conversion."""
    assert amount_in_crore("USD 5 mn deal") > 40


def test_a_bare_number_is_still_not_an_amount():
    """Making the marker optional is only safe while the UNIT is
    required."""
    for text in ("Q1 FY27 up 12%", "board meets on 25 August",
                 "Rs 500", "EPS of 12.5", "results for FY 2026"):
        assert amount_in_crore(text) is None, text


def test_the_reason_is_written_down_where_it_broke():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "core" / "stock_events.py").read_text(encoding="utf-8")
    assert "VIKRAN" in src and "26000 CRS" in src
