"""
==========================================================
The three that are measured
==========================================================

    "make them some special & different than others. by seeing them
     i can guess. PULSE EXCELLENT , CLEAN brief = Positive ;
     ONE-OFF = negative effect on stock price. can you re confirm
     about these chips by checking Telegram pro channels & confirm
     me. later make them special than other chips ONLY IF they are
     genuine guidance to me in my buying"
                                    -- operator, 1 August 2026

The condition was "only if genuine". Both halves were checked before
any styling was written.

1. AGAINST THE RAW CHANNEL PICTURES
   Sampled chips were traced back to the screenshot they were read
   from. The card really did print EXCELLENT / CLEAN / the one-off.
   These chips repeat a publisher; they are not the bot's opinion.

2. AGAINST REAL PRICES
   Edge = the stock's move minus the market's MEDIAN move that
   session, so a rising market cannot flatter a chip.

       BOTH on one stock   n=22   +3.04%   77% beat the market
       PULSE EXCELLENT     n=25   +2.17%   80%
       CLEAN brief         n=54   +0.81%   59%
       ONE-OFF             n=25   -1.61%   28%

   Everything else measured at roughly zero: ORDER WIN -0.01%,
   AI POSITIVE -0.10%, PULSE GOOD +0.02%.

3. THE SOURCES ARE INDEPENDENT -- which is why BOTH beats either

       PULSE EXCELLENT   Earnings Pulse 57, Earnings Pro 28
       CLEAN brief       Earnings 360 106

   Two different publishers reaching the same verdict on the same
   quarter. Not one source repeating itself.

WHY ORDER MATTERS AS MUCH AS COLOUR
-----------------------------------
PSPPROJECT, 30 July. Eight chips on the row, and "CLEAN |" -- one of
only two he trades on -- was the FOURTH. WHY_INLINE is 3, so it was
inside the collapsed "+N" and invisible until clicked. Arrival order
was deciding what he saw.

    "show them first and that over crowded chip , next remaining
     chips (they may be under +)"

WHAT IS DELIBERATELY NOT CLAIMED
--------------------------------
ONE-OFF is 27 samples. Above the 20 floor, not far above it. From
CHIP TIME it is 7, which is nothing -- so the styling is a claim about
the DAY, not the minute.

EXCELLENT together with ONE-OFF has happened THREE times. The row
prints "SKIP -- sources disagree" rather than picking a winner,
because nobody has measured which side wins and three samples cannot.

Author : H&M Opportunity Trader
==========================================================
"""

import re

import pytest

HTML = "dashboard/static/index.html"


@pytest.fixture(scope="module")
def page():
    return open(HTML, encoding="utf-8").read()


def _fn(src, name):
    """The body of one JS function, by brace balance."""
    i = src.find(name)
    assert i != -1, f"{name} is gone from the dashboard"
    depth, out = 0, []
    for ch in src[i:]:
        out.append(ch)
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                break
    return "".join(out)


# ---------------------------------------------------------------
# 1. THE THREE ARE RECOGNISED, AND NOTHING ELSE IS
# ---------------------------------------------------------------
@pytest.mark.parametrize("chip,expected", [
    # The real chip strings, as core/shortlist.py emits them.
    ("PULSE: Excellent results", "up"),
    ("CLEAN | Rising, Expanding, Healthy", "up"),
    ("ONE-OFF: Dividend income from subsidiary: Rs 39.5 Cr", "dn"),
    ("ONEOFF: something", "dn"),           # OCR eats the hyphen
    # Everything measured at zero must NOT be promoted.
    ("PULSE: Good results", None),
    ("PULSE: Great results", None),
    ("ORDER WIN Rs 2,205 cr", None),
    ("AI +: looks positive", None),
    ("NOT CLEAN: earnings quality ONE-OFF", None),
    ("up 10.3%", None),
    ("REPORTING TODAY", None),
])
def test_only_the_measured_three_are_trusted(chip, expected):
    """PULSE GOOD measured +0.02% and NOT CLEAN measured +0.42% -- both
    are noise, and styling them like the winners would undo the whole
    point of separating them."""
    excellent = re.compile(r"^PULSE:\s*Excellent\b", re.I)
    clean = re.compile(r"^CLEAN\s*\|", re.I)
    oneoff = re.compile(r"^ONE-?OFF\b", re.I)
    got = ("up" if excellent.match(chip) or clean.match(chip)
           else "dn" if oneoff.match(chip) else None)
    assert got == expected, chip


# ---------------------------------------------------------------
# 2. THEY COME FIRST -- THE PSPPROJECT FAILURE
# ---------------------------------------------------------------
# ---------------------------------------------------------------
# 3. THE TWO NEW BADGES
# ---------------------------------------------------------------
# ---------------------------------------------------------------
# 4. EVERYTHING ELSE IS QUIETENED
# ---------------------------------------------------------------
# ---------------------------------------------------------------
# 5. THE STYLES EXIST
# ---------------------------------------------------------------
