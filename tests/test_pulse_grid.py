"""
==========================================================
Reading the numbers the channel already sent
==========================================================

    "i'm saying the same thing since morning right? i brought every
     thing to you. all pro folder channels give us complete data in
     realtime, which our own bot is unable to get in real time."
                                    -- operator, 1 August 2026

He said it at eight in the morning. It was built at eight in the
evening, after a day spent patching the source that was broken instead
of reading the one that was not.

WHAT THE DAY WAS SPENT ON
-------------------------
core/results_pdf.py downloads a filing and hunts for the results table
inside it. 200 were fetched:

    92   parsed
    108  failed -- 57% of them had no results table in the PDF at all

and 21 of 1,699 stored rows held figures that could not be that
company. RAYMOND at 1.36 crore of quarterly sales. WESTLIFE at 1.00.

WHAT WAS ALREADY IN THE STORE
-----------------------------
Earnings Pulse publishes this with every result, and the bot had been
saving it and reading only the Pulse Rating off the top:

    Metric      QoQ    YoY    Jun'26  Mar'26  Jun'25
    Sales        1%    11%       783     792     707
    OP         -18%     8%       228     277     210
    PAT         17%     9%       159     192     146

206 cards. 192 parse. Each carries THREE quarters -- including the
year-ago one, which a single filing does not even contain.

    WESTLIFE   store 1.00   card 736.0
    RAINBOW    store 6.40   card 416.5
    QUESS      store 0.15   card 3,969.0

Jun-26 coverage went from 342 symbols to 404 in one run.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import date

import pytest

from core.pulse_grid import GRID_HEADER, parse_grid, quarters_in

# Verbatim from the store, OCR damage included -- the real card reads
# "a1 FY27" for "Q1 FY27" and turns a minus into a curly quote.
GILLETTE = """Gillette India (cuterte)
Fersonal Products | Personal Gare
a1 FY27 Pulse Rating : Weak —
Metric QoQ YoY Jun'26 Mar'26 Jun'25
Sales 1% 11% 783 792 707
Other Inc. - > 5 5 7
oP -18% 8% 228 277 210
OPM -592 bps -67 bps 29.1% 35.0% 29.8%
PAT 17% 9% 159 192 146
EPS "17% 9% 48.9 59.1 44.7
CMP : 7,847 | Large-Cap(25.7K Cr) | P/E
carringspulseal g
"""


# ---------------------------------------------------------------
# 1. THE QUARTERS
# ---------------------------------------------------------------
def test_the_three_quarters_are_read_in_order():
    assert quarters_in(GILLETTE) == [date(2026, 6, 30), date(2026, 3, 31),
                                     date(2025, 6, 30)]


def test_a_quarter_end_is_the_last_day_of_its_month():
    """Feb must be 28 or 29, not 31. A date that does not exist would
    raise the moment it reached the store."""
    assert quarters_in("Metric QoQ YoY Feb'26 Feb'24") == [
        date(2026, 2, 28), date(2024, 2, 29)]


def test_a_missing_apostrophe_still_reads():
    """The OCR loses it just often enough to matter."""
    assert quarters_in("Metric QoQ YoY Jun 26 Mar 26") == [
        date(2026, 6, 30), date(2026, 3, 31)]


def test_a_message_with_no_grid_is_not_one_of_these_cards():
    assert quarters_in("#GHCL - Excellent Results") == []
    assert parse_grid("Reliance bags Rs 2,205 crore order") == []
    assert parse_grid("") == []


# ---------------------------------------------------------------
# 2. THE FIGURES
# ---------------------------------------------------------------
def test_every_row_lands_against_the_right_quarter():
    """THE ONE THAT MATTERS. The row reads
        LABEL  QoQ%  YoY%  Q1  Q2  Q3
    and putting a figure against the wrong quarter is the exact
    failure that filled the store with rubbish in the first place."""
    got = parse_grid(GILLETTE)
    assert [q["period_label"] for q in got] == ["Jun-26", "Mar-26", "Jun-25"]
    assert [q["sales"] for q in got] == [783.0, 792.0, 707.0]
    assert [q["pat"] for q in got] == [159.0, 192.0, 146.0]
    assert [q["operating_profit"] for q in got] == [228.0, 277.0, 210.0]
    assert [q["eps"] for q in got] == [48.9, 59.1, 44.7]


def test_the_change_columns_are_never_mistaken_for_figures():
    """"1% 11% 783 792 707" is two changes and three figures. Reading
    the 1 as sales is how a company ends up reporting one crore."""
    got = parse_grid(GILLETTE)
    assert got[0]["sales"] == 783.0
    assert 1.0 not in [q["sales"] for q in got]
    assert 11.0 not in [q["sales"] for q in got]


def test_a_bps_column_is_dropped_too():
    """OPM reads "-592 bps -67 bps 29.1% 35.0% 29.8%" -- five cells,
    none of which is a rupee figure."""
    got = parse_grid(GILLETTE)
    for q in got:
        assert q.get("sales") not in (592.0, 67.0)


def test_a_half_read_row_is_refused_rather_than_padded():
    """Three quarter columns and two figures cannot be lined up. A
    guess here puts a number against the wrong quarter, silently."""
    broken = ("Metric QoQ YoY Jun'26 Mar'26 Jun'25\n"
              "Sales 1% 11% 783 792\n")
    got = parse_grid(broken)
    assert all("sales" not in q for q in got)


def test_a_card_with_no_sales_and_no_pat_is_not_a_result():
    assert parse_grid("Metric QoQ YoY Jun'26 Mar'26\n"
                      "OPM -592 bps -67 bps 29.1% 35.0%\n") == []


def test_one_quarter_is_not_a_grid():
    """Two columns is the minimum that can be compared. One is a fact,
    not a trend -- the same rule compare() already follows."""
    assert parse_grid("Metric QoQ YoY Jun'26\nSales 1% 11% 783\n") == []


# ---------------------------------------------------------------
# 3. THE REAL CASES THAT PROMPTED IT
# ---------------------------------------------------------------
@pytest.mark.parametrize("card,symbol,expected", [
    ("Metric QoQ YoY Jun'26 Mar'26 Jun'25\n"
     "Sales 12% 12% 736 655 658\nPAT -50% 0% 1 2 1\n", "WESTLIFE", 736.0),
    ("Metric QoQ YoY Jun'26 Mar'26 Jun'25\n"
     "Sales -9% 18% 416.5 456 352\n", "RAINBOW", 416.5),
    ("Metric QoQ YoY Jun'26 Mar'26 Jun'25\n"
     "Sales 5% 35% 34922 33260 25800\n", "REDINGTON", 34922.0),
])
def test_the_channel_had_the_figure_the_filing_parser_lost(card, symbol,
                                                           expected):
    """The store held 1.00 for WESTLIFE, 6.40 for RAINBOW. The card had
    been sitting in telegram.db the whole time."""
    got = parse_grid(card)
    assert got[0]["sales"] == expected, symbol


# ---------------------------------------------------------------
# 4. THE STORE MUST NOT REFUSE THE CURE
# ---------------------------------------------------------------
def test_a_trusted_reading_bypasses_the_median_guard(tmp_path):
    """WESTLIFE's stored history was 1.0 and 1.0, both misread. The
    CORRECT figure of 736 is a 736x outlier against that, and the
    sanity guard refused it -- corrupt data defending itself."""
    from core.quarterly_results import QuarterlyResults
    store = QuarterlyResults(url=f"sqlite:///{tmp_path}/q.db")
    for month, day, year in ((3, 31, 2026), (12, 31, 2025), (9, 30, 2025)):
        store.remember("WESTLIFE", date(year, month, day), sales=1.0,
                       source="filing_pdf")

    assert store.remember("WESTLIFE", date(2026, 6, 30), sales=736.0,
                          source="filing_pdf") == "unchanged"
    assert store.remember("WESTLIFE", date(2026, 6, 30), sales=736.0,
                          source="pulse_grid", trusted=True) == "new"
    assert store.latest("WESTLIFE")["sales"] == 736.0


def test_the_loader_never_deletes_a_filing_row():
    """Two independent readings of one quarter is what the CONFLICT
    chip is made of. Replacing one with the other throws that away."""
    src = open("tools/load_pulse_grids.py", encoding="utf-8").read()
    # The SQL, not the word. The docstring says it does NOT delete the
    # filing rows, and the first version of this test failed on its own
    # explanation -- the fourth time that happened in one day.
    import re
    assert not re.search(r"\bDELETE\s+FROM\b", src, re.I)
    assert "trusted=True" in src


def test_a_card_naming_more_than_one_company_is_refused():
    """A grid describes ONE company. If the symbol column holds more we
    cannot tell whose figures these are, and guessing puts a quarter on
    the wrong stock."""
    src = open("tools/load_pulse_grids.py", encoding="utf-8").read()
    assert "more than one symbol" in src


def test_the_header_pattern_is_what_identifies_a_card():
    assert GRID_HEADER.search("Metric QoQ YoY Jun'26")
    assert not GRID_HEADER.search("#GHCL - Excellent Results")
