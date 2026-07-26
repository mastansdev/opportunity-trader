"""
Which headlines earn a row on the trading screen.

Operator, 2026-07-26: "it must display intraday news, announcements,
results, any other major events/news not all other mid news."

So this is a POSITIVE list, not a junk filter. "Not obviously routine"
is not enough -- a headline has to actively look like one of the things
that moves a share price.
"""

import pytest

from news_bot.major_events import EVENT_TYPES, classify_event, is_major_event


@pytest.mark.parametrize("text,expected", [
    ("Financial Results for the quarter ended June 2026", "RESULTS"),
    ("Unaudited Financial Results", "RESULTS"),
    ("Bagging of order worth Rs 500 crore from NHAI", "ORDER"),
    ("Company receives Letter of Award for a metro project", "ORDER"),
    ("Board approves acquisition of a 51% stake", "M&A"),
    ("Scheme of Arrangement between the company and its subsidiary", "M&A"),
    ("Raising of funds through QIP", "FUNDRAISE"),
    ("Allotment of Non-Convertible Debentures", "FUNDRAISE"),
    ("Board recommends Bonus Issue in the ratio 1:1", "CAPITAL"),
    ("Stock Split - face value split from Rs 10 to Rs 2", "CAPITAL"),
    ("Company receives USFDA approval for its Gujarat plant", "APPROVAL"),
    ("Credit Rating upgraded by ICRA", "RATING"),
    ("SEBI imposes penalty on the company", "LEGAL"),
    ("Fire at the manufacturing unit", "DISRUPTION"),
    ("Strike declared at the Pune plant", "DISRUPTION"),
    ("Company defaults on interest payment", "DISTRESS"),
    ("NCLT admits insolvency petition", "DISTRESS"),
    ("Company revises guidance for FY27", "GUIDANCE"),
])
def test_major_events_are_recognised(text, expected):
    assert classify_event(text) == expected


@pytest.mark.parametrize("text", [
    "Management commentary on demand trends",
    "Company participates in an industry conference",
    "General update on operations",
    "Change in registered office address",
    "",
    None,
])
def test_everything_else_gets_no_row(text):
    assert classify_event(text) is None
    assert is_major_event(text) is False


def test_first_rule_wins_when_a_headline_spans_two():
    """"Board approves acquisition funded by QIP" is an acquisition
    story. M&A is checked before FUNDRAISE for exactly this."""
    assert classify_event(
        "Board approves acquisition of XYZ funded through QIP") == "M&A"


def test_it_never_decides_direction():
    """The module returns WHAT happened, never good/bad. Deciding
    direction from words is what produced 'Tax Deduction on Dividend'
    -> bullish 80%."""
    out = classify_event("Fire at the manufacturing unit")
    assert out in EVENT_TYPES
    assert out == "DISRUPTION"          # a type, not a sentiment


def test_case_does_not_matter():
    assert classify_event("financial results for q1") == "RESULTS"
    assert classify_event("FINANCIAL RESULTS FOR Q1") == "RESULTS"
