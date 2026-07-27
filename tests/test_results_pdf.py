"""
The numbers are in the PDF, and nowhere else useful.

Three ways to learn what a company just reported, all measured on
2026-07-27:

  1. THE ANNOUNCEMENT TEXT -- no figures at all. Seven real filings that
     evening (BEL, TATAPOWER, SAGCEM, NORTHARC, KANPRPLA, TOKYOPLAST,
     BKMINDST) each carried 109-168 characters of boilerplate: "X Limited
     has submitted to the Exchange, the financial results for the period
     ended Jun 30, 2026." That is the whole payload.

  2. bse.resultsSnapshot() -- lags and is short. TMB reported that day
     and the snapshot still showed Mar-26 while its own period_links
     said Jun-26. Two quarters plus a full year: QoQ, never YoY.

  3. THE PDF -- current quarter, previous quarter AND the year-ago
     quarter, at full precision, the same minute as the filing.

The fixture is the real text layer of MOLD-TEK PACKAGING's Q1 FY27
filing, extracted from the PDF the operator downloaded at 14:09 that
day. Everything below is checked against two independent things: the
operator's own earnings-pulse card, and the company's own prose on page
one of the same document ("Net Sales increased by 26.32%... Net Profit
(PAT) surged by 23.89%... (Q1 on Q4)").
"""

import os
from datetime import date

import pytest

from core.results_pdf import (parse_statement, detect_unit,
                              find_period_columns, _to_float)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                       "moldtkpac_q1fy27.txt")


@pytest.fixture
def statement():
    with open(FIXTURE, encoding="utf-8") as f:
        return f.read()


# ----------------------------------------------------------------
# The real filing
# ----------------------------------------------------------------

def test_all_three_quarters_are_found(statement):
    rows = parse_statement(statement, symbol="MOLDTKPAC")
    assert [r["period_label"] for r in rows] == ["Jun-26", "Mar-26", "Jun-25"]


def test_the_figures_match_the_operators_earnings_pulse_card(statement):
    """Card: Jun-26 300.5 / Mar-26 237.86 / Jun-25 240.56 crore."""
    rows = parse_statement(statement, symbol="MOLDTKPAC")
    assert rows[0]["sales"] == pytest.approx(300.45, abs=0.1)
    assert rows[1]["sales"] == pytest.approx(237.86, abs=0.1)
    assert rows[2]["sales"] == pytest.approx(240.56, abs=0.1)
    assert rows[0]["pat"] == pytest.approx(25.57, abs=0.1)
    assert rows[0]["eps"] == pytest.approx(7.70, abs=0.01)


def test_the_computed_growth_matches_the_companys_own_prose(statement):
    """Page 1 of the same PDF says 26.32% and 23.89% in words. This
    parser reads the TABLE. Two independent parts of one document must
    agree, or the parser is wrong."""
    rows = parse_statement(statement, symbol="MOLDTKPAC")
    q1, q4 = rows[0], rows[1]
    assert (q1["sales"] - q4["sales"]) / q4["sales"] * 100 == \
        pytest.approx(26.32, abs=0.05)
    assert (q1["pat"] - q4["pat"]) / q4["pat"] * 100 == \
        pytest.approx(23.89, abs=0.05)


def test_the_year_ago_quarter_is_present(statement):
    """The whole reason to prefer the PDF. resultsSnapshot cannot give
    this, so YoY is impossible without it until the store has
    accumulated four quarters of its own."""
    rows = parse_statement(statement, symbol="MOLDTKPAC")
    assert rows[2]["period_end"] == date(2025, 6, 30)
    assert rows[2]["sales"] == pytest.approx(240.56, abs=0.1)


def test_the_year_ended_column_is_not_stored_as_a_quarter(statement):
    """'31-Mar-2026' appears TWICE in that header -- once as a quarter,
    once as the year ended, with revenue of 886.61 crore against a
    quarterly 237.86. Storing it as a quarter would make the next
    comparison read as a 73% collapse."""
    rows = parse_statement(statement, symbol="MOLDTKPAC")
    assert len(rows) == 3
    assert all(r["sales"] < 400 for r in rows)


def test_lakhs_are_converted_to_crores(statement):
    """The statement says 'In lakhs'. 30045.20 lakhs is 300.45 crore. Get
    this wrong and every figure is out by 100x."""
    assert detect_unit(statement) == 0.01
    assert parse_statement(statement)[0]["sales"] < 1000


# ----------------------------------------------------------------
# Refusing to guess
# ----------------------------------------------------------------

def test_an_undeclared_unit_is_refused_not_assumed():
    """A statement with no 'in lakhs/crores' header could be either, and
    the two differ by 100x. Silence is the only safe answer."""
    text = ("Quarter Ended\n30-Jun-2026 | 31-Mar-2026\n"
            "Revenue from operations 30045.20 23785.56\n")
    assert parse_statement(text) == []


def test_a_statement_with_no_period_columns_returns_nothing():
    assert parse_statement("Revenue from operations 100 200") == []


@pytest.mark.parametrize("junk", ["", None, "   ", "no numbers here at all"])
def test_junk_input_returns_nothing_rather_than_raising(junk):
    assert parse_statement(junk) == []


# ----------------------------------------------------------------
# The dirty text layer of a real scanned filing
# ----------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("30045.20", 30045.20),
    ("(140.77)", -140.77),        # parentheses mean negative
    ("1,661.59", 1661.59),        # Indian grouping
    ("248,03", 248.03),           # OCR put a comma where the point goes
    ("--", None),                 # not zero -- a different fact
    ("-", None),
    ("", None),
    ("NA", None),
])
def test_number_shapes_seen_in_the_real_file(raw, expected):
    assert _to_float(raw) == expected


def test_indian_grouping_is_not_mistaken_for_a_decimal():
    """'1,661.59' groups thousands; '248,03' is a scan artifact. The
    repair must only fire on the second shape -- two digits after a
    comma at the very end."""
    assert _to_float("1,661.59") == 1661.59
    assert _to_float("58,194.20") == 58194.20


def test_period_columns_stop_at_year_ended():
    header = ("Quarter Ended Year Ended\n"
              "30-Jun-2026 | 31-Mar-2026 | 30-Jun-2025 | 31-Mar-2026")
    assert find_period_columns(header) == [
        date(2026, 6, 30), date(2026, 3, 31), date(2025, 6, 30)]


def test_a_repeated_date_is_not_counted_twice():
    header = "30-Jun-2026 | 31-Mar-2026 | 30-Jun-2025 | 31-Mar-2026"
    assert len(find_period_columns(header)) == 3


# ----------------------------------------------------------------
# Into the store
# ----------------------------------------------------------------

def test_the_parsed_quarters_grade_correctly(tmp_path, statement):
    from core.quarterly_results import QuarterlyResults
    store = QuarterlyResults(url=f"sqlite:///{tmp_path}/q.db")
    for r in parse_statement(statement, symbol="MOLDTKPAC"):
        store.remember("MOLDTKPAC", r["period_end"],
                       period_label=r["period_label"], sales=r.get("sales"),
                       pat=r.get("pat"), eps=r.get("eps"), source="pdf")
    c = store.compare("MOLDTKPAC")
    assert c["grade"] == "STRONG"
    assert c["qoq"]["sales"] == pytest.approx(26.31, abs=0.1)
    assert c["yoy"]["sales"] == pytest.approx(24.90, abs=0.1)
