"""
==========================================================
What the bot actually knows about a stock
==========================================================

    "never assume-give clarity on every item residing in bot =
     dashboard"                     -- operator, 3 August 2026

THE YASHO QUESTION
------------------
    "yasho alone caused - 11.3K loss"

Measured after the fact: YASHO has ZERO minute candles in
data/history_candles.db and no traded value at all. The bot scored it,
ranked it, and put a BUY button on it while knowing nothing whatever
about how it trades. 191 of the 946 tradeable names in the master are
in the same state.

WHAT THIS IS NOT
----------------
Not a risk score, not a size rule, not a refusal. The first thing I
reached for was a liquidity limit, and the numbers killed it: at his
Rs 1 lakh cap even the THINNEST measured stock is 0.22% of a day's
turnover. Size is not his exit problem, and a limit would have been
solving a fear rather than a fact.

The real problem is smaller and worth saying plainly: on those 191
names, every number the bot shows is an extrapolation from nothing,
and silence read as confidence.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core import liquidity
from dashboard.state import _coverage


@pytest.fixture(autouse=True)
def clean():
    liquidity.reset()
    yield
    liquidity.reset()


# ---------------------------------------------------------------
# 1. THE FACT
# ---------------------------------------------------------------
def test_a_stock_with_no_traded_value_is_flagged_unknown():
    got = _coverage("DEFINITELYNOTREAL")
    assert got["known"] is False
    assert "no price history" in got["note"]
    assert got["adv_cr"] is None


def test_a_measured_stock_says_how_much_it_trades():
    if not liquidity.available():
        pytest.skip("run py tools/measure_liquidity.py")
    got = _coverage("INFY")
    assert got["known"] is True
    assert got["adv_cr"] > 0
    assert "Cr a day" in got["note"]


def test_yasho_was_never_actually_unknown():
    """---- I WAS WRONG ABOUT THIS. Corrected 4 August 2026. ----

    This test asserted YASHO had no price history, and I told the
    operator so, and built a gate on it and called it "the YASHO gate".

    It was my data source, not his stock. core/liquidity.py was reading
    data/history_candles.db, which nothing updates. Against NSE's own
    bhavcopy YASHO averages Rs 61 crore a day and traded Rs 175 crore
    the session before he bought it:

        31 Jul   Rs 3,858   273,048 shares   Rs 102.5 cr
        03 Aug   Rs 3,884   438,114 shares   Rs 175.0 cr

    191 of 954 tradeable names looked unknown for the same reason. The
    real number is ZERO. The Rs 11,300 came from the dual entry, which
    is a real defect and already fixed -- not from an illiquid stock.

    ---- AND THEN THE NUMBER ROTTED. 12 August 2026. ----

    This asserted `adv("YASHO") > 20`, a figure true on 4 August and
    hardcoded. tools/measure_liquidity.py re-ran on 12 August and the
    rolling average had fallen to Rs 16.09 crore -- the 102-175 crore
    sessions above had aged out of the window. Nothing was wrong; the
    stock simply traded less.

    The claim this test defends is "YASHO was never unknown, and it is
    liquid enough to trade". It now asserts exactly that, against the
    gate the bot actually applies (core/rules.MIN_LIQUIDITY_CR) instead
    of a number frozen at one moment. A test pinned to live rolling
    data with a magic constant is a test with an expiry date on it.
    """
    from core.rules import MIN_LIQUIDITY_CR

    if not liquidity.available():
        pytest.skip("run py tools/measure_liquidity.py")
    assert liquidity.known("YASHO") is True, (
        "YASHO reads as unknown again -- check which database "
        "core/liquidity.py is reading")
    adv = liquidity.adv("YASHO")
    assert adv > MIN_LIQUIDITY_CR, (
        f"YASHO averages Rs {adv} crore against a Rs {MIN_LIQUIDITY_CR} "
        f"crore floor. If it has genuinely gone thin, that is a real "
        f"finding and not a broken test.")


def test_unknown_count_answers_how_many():
    assert liquidity.unknown_count(["NOTREAL1", "NOTREAL2"]) == 2
    assert liquidity.unknown_count([]) == 0


# ---------------------------------------------------------------
# 2. IT IS A FACT, NOT A JUDGEMENT
# ---------------------------------------------------------------
def test_it_never_refuses_or_resizes_anything():
    """     "bot must inform the situation like a caution not block" """
    src = open("core/liquidity.py", encoding="utf-8").read()
    block = src[src.index("def known("):src.index("def by_size(")]
    # Executable lines only. The docstrings above explain WHY there is
    # no size cap, and asserting against prose inside a docstring is a
    # mistake this project has now made four times.
    code, in_doc = [], False
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.count('"""') == 1:
            in_doc = not in_doc
            continue
        if in_doc or stripped.startswith("#") or stripped.startswith('"""'):
            continue
        code.append(line)
    code = "\n".join(code)
    for banned in ("raise", "max_qty", "cap =", "limit ="):
        assert banned not in code, banned


def test_the_share_of_a_day_is_reported_not_capped():
    """At Rs 1 lakh even a 5cr/day stock is a fifth of one percent. The
    number is available if he wants it; nothing acts on it."""
    assert liquidity.share_of_day(100000, "X", "data/nope.json") is None


def test_a_share_of_day_is_computed_when_the_value_is_known():
    if not liquidity.available():
        pytest.skip("run py tools/measure_liquidity.py")
    got = liquidity.share_of_day(100000, "INFY")
    # 1 lakh against 2,581 Cr a day is 0.0004% -- vanishing, and that
    # IS the answer. Two decimals would have printed 0.00 and read as
    # missing data.
    assert got is not None and 0 < got < 0.01


# ---------------------------------------------------------------
# 3. IT REACHES EVERY BUTTON
# ---------------------------------------------------------------
def test_the_calls_panel_carries_it():
    src = open("dashboard/state.py", encoding="utf-8").read()
    block = src[src.index("def build_calls"):]
    block = block[:block.index("def build_causes")] \
        if "def build_causes" in block else block
    assert '"coverage": _coverage(symbol),' in block


def test_the_screen_says_it_in_plain_words():
    html = open("dashboard/static/index.html", encoding="utf-8").read()
    assert "no price history" in html
    assert ".ot-nohist" in html


def test_the_badge_is_a_caution_colour_not_an_error_colour():
    """It is a fact about the BOT's knowledge, not a judgement on the
    stock. Red would read as 'this stock is bad'."""
    html = open("dashboard/static/index.html", encoding="utf-8").read()
    block = html[html.index(".ot-nohist {"):]
    block = block[:block.index("}")]
    assert "--amber" in block
    assert "--red" not in block


def test_a_known_stock_gets_no_badge_at_all():
    """Clutter on every row would make the exception invisible, which
    is the whole problem this is fixing."""
    html = open("dashboard/static/index.html", encoding="utf-8").read()
    block = html[html.index("WHAT THE BOT ACTUALLY KNOWS"):]
    block = block[:block.index("'</div>'")]
    assert "r.coverage.known === false" in block
