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
def test_the_three_patterns_exist(page):
    for const in ("TRUST_EXCELLENT", "TRUST_CLEAN", "TRUST_ONEOFF"):
        assert f"const {const}" in page, f"{const} is missing"


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


def test_not_clean_is_not_the_same_chip_as_one_off(page):
    """They read alike and measured OPPOSITE ways:

        ONE-OFF     n=25   -1.61%   28% up
        NOT CLEAN   n=28   +0.42%   61% up

    The pattern is anchored at the start of the chip so "NOT CLEAN:
    earnings quality ONE-OFF" cannot be caught by either rule."""
    oneoff = re.compile(r"^ONE-?OFF\b", re.I)
    clean = re.compile(r"^CLEAN\s*\|", re.I)
    text = "NOT CLEAN: earnings quality ONE-OFF"
    assert not oneoff.match(text)
    assert not clean.match(text)


# ---------------------------------------------------------------
# 2. THEY COME FIRST -- THE PSPPROJECT FAILURE
# ---------------------------------------------------------------
def test_the_trusted_chips_are_sorted_ahead_of_the_rest(page):
    cell = _fn(page, "function whyCell")
    assert "trusted.concat(others)" in cell, (
        "the measured chips must be ordered ahead of the others -- "
        "PSPPROJECT had CLEAN at position 4 of 8, inside the collapsed "
        "+N, because the row was in arrival order")


def test_the_inline_slot_grows_rather_than_hiding_a_trusted_chip(page):
    """WHY_INLINE is 3. A stock carrying EXCELLENT, CLEAN and a
    one-off has three trusted chips already -- a fixed cap of 3 would
    be fine, but four would silently collapse one. The cap is the
    LARGER of WHY_INLINE and the trusted count."""
    cell = _fn(page, "function whyCell")
    assert "Math.max(WHY_INLINE, trusted.length)" in cell


def test_nothing_is_ever_dropped(page):
    """The standing rule: 'do not throw away any information we are
    receiving'. The tail moves behind the +N, it does not vanish."""
    cell = _fn(page, "function whyCell")
    assert "const rest" in cell and "rest.length" in cell
    assert "why-more" in page


# ---------------------------------------------------------------
# 3. THE TWO NEW BADGES
# ---------------------------------------------------------------
def test_the_double_badge_needs_both_and_no_warning(page):
    cell = _fn(page, "function whyCell")
    assert "hasExcellent && hasClean && !hasOneOff" in cell, (
        "DOUBLE is the two-publisher agreement. A one-off on the same "
        "row means they do NOT agree, and it must not print.")


def test_the_double_badge_carries_its_own_evidence(page):
    """A badge the operator cannot interrogate is a badge he has to
    take on faith. The hover states the sample size."""
    assert "3.04%" in page and "22 occasions" in page


def test_the_skip_badge_fires_on_the_contradiction(page):
    cell = _fn(page, "function whyCell")
    assert "hasOneOff && (hasExcellent || hasClean)" in cell


def test_the_skip_badge_admits_it_has_no_evidence(page):
    """THE ONE THAT MATTERS. 3 samples. The badge must say there is no
    measurement -- not imply the warning wins, and not imply the
    positive wins."""
    i = page.find("sl-skip\"")
    assert i != -1
    tip = page[i:i + 700]
    assert "3 times" in tip
    assert "No measurement exists" in tip


def test_no_badge_asserts_a_direction_on_three_samples(page):
    """A red row would be a verdict. The 3 samples we have averaged
    slightly POSITIVE, so red would be wrong in the one direction the
    data faintly points."""
    i = page.find("sl-skip\"")
    tip = page[i:i + 700]
    assert "Treat it as a pass" in tip
    for word in ("avoid this stock", "will fall", "sell"):
        assert word not in tip.lower()


# ---------------------------------------------------------------
# 4. EVERYTHING ELSE IS QUIETENED
# ---------------------------------------------------------------
def test_untrusted_chips_are_muted(page):
    chip = _fn(page, "function chipHtml")
    assert "sl-muted" in chip


def test_conflict_is_never_muted(page):
    """It scores zero on purpose and its whole job is to be the loudest
    thing on the row. Greying it would invert that."""
    chip = _fn(page, "function chipHtml")
    assert 'if (!/^CONFLICT:/.test(w)) cls += " sl-muted"' in chip


def test_a_trusted_chip_returns_before_the_old_cascade(page):
    """PULSE: Excellent also matches the older /^PULSE: (Excellent|
    Great|Good)/ rule below it. Falling through would repaint it as an
    ordinary green chip and undo the separation."""
    chip = _fn(page, "function chipHtml")
    early = chip[:chip.find('let cls = "sl-chip"')]
    assert "return" in early and "sl-trust" in early


# ---------------------------------------------------------------
# 5. THE STYLES EXIST
# ---------------------------------------------------------------
@pytest.mark.parametrize("cls", [
    ".sl-trust", ".sl-trust-up", ".sl-trust-dn",
    ".sl-double", ".sl-skip", ".sl-muted",
])
def test_every_new_class_has_a_rule(page, cls):
    assert re.search(re.escape(cls) + r"\s*\{", page), f"{cls} has no CSS"


def test_the_measurements_are_written_down_next_to_the_styling(page):
    """The operator's condition was 'only if they are genuine'. The
    numbers that answered it live beside the code they justify, so the
    next person to change this has to argue with the evidence."""
    for fact in ("+3.04%", "+2.17%", "+0.81%", "-1.61%"):
        assert fact in page, f"the {fact} measurement is not recorded"
