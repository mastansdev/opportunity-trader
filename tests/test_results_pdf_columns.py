"""
==========================================================
Reading a filing wrong is worse than not reading it
==========================================================

31 July 2026. APTUS reported, the stock closed -5.77%, and the panel
showed "GOOD: PAT +10% QoQ" -- a grade of the MARCH quarter, because
today's filing had never been read.

    "i'm not aware that we are checking old results till now, as i'm
     checking the earnings pulse only"

WHY IT WAS NOT READ
-------------------
The PDF downloaded fine and had a clean text layer. Its column header
read

    30.06.2026  31.03.2026  30.06.2025  31.03.2026

and _DATE_RE required a THREE-LETTER MONTH NAME, so no period columns
were found and the parser gave up before reading a number. Across 30
stored filings, 6 used only a numeric date and were silently
unreadable.

THE PART THAT MATTERS MORE
--------------------------
Fixing the date alone made it WORSE. pdfplumber reports that filing's
figures with stray spaces inside them:

    VII Profit for the period  26,094.10  2 6,095.49  21,925.15  9 4,294.39

Four columns arriving as six values. Every figure shifted a column and
APTUS parsed as PAT 60.95 against 219.25 -- a 72% collapse -- when the
truth is 261 against 261, flat.

The original "no rows" failure was ugly and SAFE. Half the fix would
have been silent and WRONG, and a wrong grade on a real filing is the
worst thing this program can produce. So these tests pin the NUMBERS,
not just the fact that something parsed.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import date

import pytest

from core.results_pdf import (
    find_period_columns, parse_statement, repair_split_numbers)

# Verbatim from the APTUS Q1 FY27 filing, exactly as pdfplumber reports
# it -- stray spaces included. Cleaning this up would test a document
# we never receive.
APTUS = """Aptus Value Housing Finance India Limited
Statement of unaudited consolidated financial results for the quarter ended June 30, 2026
(INR In lakhs)
Quarter ended Year ended
Particulars
30.06.2026 31.03.2026 30.06.2025 31.03.2026
(Unaudited) (Audited) (Unaudited) (Audited)
I Revenue from operations
Total revenue from operations 60,028.55 5 7,433.70 52,026.04 2,19,223.72
II Other income 1,036.85 1,878.18 9 88.24 5,324.46
III Total Income (I+II) 61,065.40 5 9,311.88 53,014.28 2,24,548.18
V Profit before tax (III-IV) 32,909.43 3 2,756.37 28,554.67 1,21,115.61
VII Profit for the period (V-VI) 26,094.10 2 6,095.49 21,925.15 9 4,294.39
Basic (Amount in INR) 5.21 5 .22 4.39 18.84
"""


# ---------------------------------------------------------------
# 1. THE DATE FORMAT THAT WAS INVISIBLE
# ---------------------------------------------------------------
def test_a_dotted_numeric_header_is_read():
    """30.06.2026 -- the format APTUS actually filed in."""
    got = find_period_columns(
        "Quarter ended Year ended\n30.06.2026 31.03.2026 30.06.2025 31.03.2026")
    assert got == [date(2026, 6, 30), date(2026, 3, 31), date(2025, 6, 30)]


def test_the_named_header_still_works():
    """10 of 30 stored filings use this. It must not regress."""
    got = find_period_columns(
        "Quarter Ended Year Ended\n30-Jun-2026 31-Mar-2026 30-Jun-2025")
    assert got == [date(2026, 6, 30), date(2026, 3, 31), date(2025, 6, 30)]


def test_a_month_first_header_is_read():
    """"June 30, 2026" -- a third layout, and the one AADHARHFC and
    CARTRADE file in."""
    got = find_period_columns(
        "Quarter ended Year ended\n"
        "June 30, 2026 March 31, 2026 June 30, 2025 March 31, 2026")
    assert got == [date(2026, 6, 30), date(2026, 3, 31), date(2025, 6, 30)]


def test_a_date_is_never_read_across_the_boundary_of_two_dates():
    """THE BUG THAT PUT 25 CORRUPT ROWS IN THE STORE.

    An earlier fix allowed "[A-Za-z]{3}[A-Za-z]*" so that "March"
    matched as well as "Mar". On

        June 30, 2026   March 31, 2026   June 30, 2025

    that let the pattern begin on the "26" of "2026", swallow
    " March ", and finish on the "31" of the NEXT date -- yielding
    26 March 2031. AADHARHFC, CARTRADE, COLPAL and fourteen others
    went into quarterly_results.db as Mar-31 and Jun-30.

    Every column here must be a real quarter end in the right year.
    """
    got = find_period_columns(
        "Quarter ended\nJune 30, 2026 March 31, 2026 June 30, 2025")
    assert all(2024 <= d.year <= 2027 for d in got), got
    assert all(d.day >= 28 for d in got), got


@pytest.mark.parametrize("line", [
    "Scrip Code: 543335 Mumbai - 400 051",
    "CIN : L65922TN2009PLC073881",
    "Telephone 2498 8463 4210 6952",
    "GNPA increased to 1.42 from 1.29",
    "05/06/2026 07/06/2026",          # ambiguous MM/DD -- not ours to read
    # "and" is three letters. It is not a month, and the first version
    # of the widened pattern read this as the 33rd of "and", year 52.
    "Regulation 33 and 52 read with Schedule III",
])
def test_things_that_are_not_quarter_ends_are_ignored(line):
    """A quarter end is the LAST day of a month, so the first field is
    28 or more. Anything else is a phone number, a scrip code or a
    ratio, and guessing at it would invent columns."""
    assert find_period_columns("header\n" + line) == []


# ---------------------------------------------------------------
# 2. THE SPACES INSIDE THE FIGURES
# ---------------------------------------------------------------
@pytest.mark.parametrize("raw,fixed", [
    ("26,094.10 2 6,095.49 21,925.15 9 4,294.39",
     "26,094.10 26,095.49 21,925.15 94,294.39"),
    ("1 6,967.51 16,051.21 1 6,043.29", "16,967.51 16,051.21 16,043.29"),
    ("6,815.33 6,660.88 6 ,629.52", "6,815.33 6,660.88 6,629.52"),
    ("Basic (Amount in INR) 5.21 5 .22 4.39",
     "Basic (Amount in INR) 5.21 5.22 4.39"),
])
def test_split_figures_are_closed_up(raw, fixed):
    assert repair_split_numbers(raw) == fixed


@pytest.mark.parametrize("line", [
    "12 345",                      # two separate numbers
    "1,94,380.11",                 # already whole, Indian grouping
    "6,095.49 21,925.15",          # THE ONE THE FIRST FIX BROKE
    "quarter 3 2026",
])
def test_genuinely_separate_numbers_are_left_alone(line):
    """The first version used a lookbehind of (?<=\\d), which the last
    digit of a COMPLETED number satisfies -- so "6,095.49 21,925.15",
    two perfectly good figures, were welded together. Worse than the
    bug it was fixing."""
    assert repair_split_numbers(line) == line


# ---------------------------------------------------------------
# 3. THE NUMBERS THEMSELVES, AGAINST THE PUBLISHED CARD
# ---------------------------------------------------------------
def test_aptus_parses_to_the_figures_in_the_filing():
    rows = parse_statement(APTUS, symbol="APTUS")
    assert len(rows) == 3, f"three quarter columns expected, got {len(rows)}"
    by_period = {r["period_label"]: r for r in rows}

    # Profit for the period, in lakhs, converted to crores.
    assert by_period["Jun-26"]["pat"] == pytest.approx(260.94, abs=0.02)
    assert by_period["Mar-26"]["pat"] == pytest.approx(260.95, abs=0.02)
    assert by_period["Jun-25"]["pat"] == pytest.approx(219.25, abs=0.02)

    assert by_period["Jun-26"]["sales"] == pytest.approx(600.29, abs=0.02)
    assert by_period["Jun-25"]["sales"] == pytest.approx(520.26, abs=0.02)


def test_the_quarter_was_flat_not_up_ten_percent():
    """The whole point. The panel said "PAT +10% QoQ" from a stale
    March row; the filing says 260.94 against 260.95 -- flat."""
    rows = parse_statement(APTUS, symbol="APTUS")
    by_period = {r["period_label"]: r for r in rows}
    change = (by_period["Jun-26"]["pat"] / by_period["Mar-26"]["pat"] - 1) * 100
    assert abs(change) < 1.0, f"PAT moved {change:.1f}% QoQ; it should be flat"


def test_the_year_column_is_never_mistaken_for_a_quarter():
    """31.03.2026 appears TWICE in that header -- once as a quarter and
    once as the full year. The year figure (94,294.39 lakhs = 942 Cr)
    must not land in any quarter's PAT."""
    rows = parse_statement(APTUS, symbol="APTUS")
    for row in rows:
        assert row["pat"] < 500, (
            f"{row['period_label']} got PAT {row['pat']} -- that is the "
            f"full-year column leaking into a quarter")


# ---------------------------------------------------------------
# 4. REFUSING IS STILL ALLOWED
# ---------------------------------------------------------------
def test_a_row_where_profit_dwarfs_revenue_is_refused():
    """1 August 2026. Widening the unit and date patterns made eight
    more filings "readable" and four of those were wrong:

        ASHIKAG  sales=0.86  pat=36.97     profit 43x revenue

    A row that parses is not a row that is right. This is the only
    rule in the parser about BELIEVING a number rather than finding
    one, and it exists because a half-read statement produces a
    confident wrong grade.
    """
    text = APTUS.replace(
        "Total revenue from operations 60,028.55 5 7,433.70 52,026.04 2,19,223.72",
        "Total revenue from operations 86.00 86.00 86.00 86.00")
    rows = parse_statement(text, symbol="ASHIKAG")
    assert rows == [], "profit 30x revenue must not be stored"


def test_a_holding_company_is_still_allowed():
    """Deliberately loose. Holding companies really do earn more from
    investments than operations, and a rule tight enough to catch
    every mis-read would throw away real filings."""
    text = APTUS.replace(
        "Total revenue from operations 60,028.55 5 7,433.70 52,026.04 2,19,223.72",
        "Total revenue from operations 6,000.00 6,000.00 6,000.00 6,000.00")
    rows = parse_statement(text, symbol="HOLDCO")
    assert rows, "profit ~4x revenue is unusual but real"


def test_no_unit_means_no_figures():
    """"Refusing to guess -- figures would be out by 100x." Still
    true, and still the right answer."""
    text = APTUS.replace("(INR In lakhs)", "")
    assert parse_statement(text, symbol="APTUS") == []


def test_no_columns_means_no_figures():
    text = APTUS.replace("30.06.2026 31.03.2026 30.06.2025 31.03.2026", "")
    assert parse_statement(text, symbol="APTUS") == []
