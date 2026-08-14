"""
==========================================================
Layer 06 -- a tier, never an instruction
==========================================================

    "Have you forgot SEBI mandates about no stock buy / sell
     recommendations? no one gives that signals. these channels
     provide data with vedict. after connecting all points (we used to
     do this - hectic work gone by outsourcing them) now your only
     work is to show me as instant as possible"
                                    -- operator, 2 August 2026

That ended an hour-long design argument. A chip reading "BUY" would be
a RECOMMENDATION. Nobody in this chain issues one, and Earnings Pulse
says so on their own page:

    "We don't tell you whether to buy, hold, or skip a name."
    "Earnings Pulse is not registered with SEBI as an Investment
     Adviser or Research Analyst."

So layer 06 stores a TIER. This file fails if the words buy, sell,
hold or skip ever reach a headline.

WHAT IT ADDS THAT NOTHING ELSE HAD
----------------------------------
CANSLIM (TechnoFunda) is the sixth read in their chain and the only
one carrying the CHART -- "EXCEPTIONAL: exceptional fit on multiple
lenses, clean earnings quality, TECHNICALLY PRIMED."

Checked against the store the day it arrived. Twelve of thirteen names
disagreed with the Pulse grade:

    SHADOWFAX   CANSLIM EXCEPTIONAL   Pulse GOOD
    AETHER      CANSLIM EXCEPTIONAL   Pulse GOOD
    DIVISLAB    CANSLIM EXCEPTIONAL   Pulse GOOD
    CORONA      CANSLIM STRONG        Pulse OK

Neither is wrong. The Pulse grade is the QUARTER -- their own guide
says "Good: positive, can go either way", and outcome tracking put
PULSE GOOD at +0.02% on 149 samples. CANSLIM adds the lenses the grade
does not have.

NO OCR IN THE PATH
------------------
The tiers live on a webpage, but the page exports a TradingView
watchlist -- plain text. After a weekend of fighting damaged
screenshots this is the only source in the system that cannot be
misread. 1 August: 92 rows, EXCEPTIONAL 4 / STRONG 15 / MIXED 42 /
WEAK 31.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import date

import pytest

from core.canslim import (TIERS, counts, headline_for, parse_watchlist,
                          with_rarity)

# Verbatim shape from the real export, including the exporter's commas
# and the two BSE codes wearing an NSE prefix.
EXPORT = """### EXCEPTIONAL,
NSE:DIVISLAB,
NSE:AETHER,
NSE:SHADOWFAX,
NSE:YASHO,

### STRONG,
NSE:MUTHOOTFIN,
NSE:CORONA,
NSE:BSE-526935,

### MIXED,
NSE:SUNPHARMA,
NSE:20MICRONS,

### WEAK,
NSE:BSE-543980,
NSE:GARGI,
"""


@pytest.fixture(scope="module")
def rows():
    return parse_watchlist(EXPORT)


def _tier(rows, symbol):
    return next(r["tier"] for r in rows if r["symbol"] == symbol)


# ---------------------------------------------------------------
# 1. THE FILE IS READ
# ---------------------------------------------------------------
def test_every_tier_heading_is_recognised(rows):
    assert {r["tier"] for r in rows} == set(TIERS)


def test_each_name_lands_under_its_own_heading(rows):
    """THE ONE THAT MATTERS. Four tiers on one page. A name under the
    wrong heading is the mismatch rule -- and unlike the OCR sources,
    there is no excuse for it here: the text is clean."""
    assert _tier(rows, "DIVISLAB") == "EXCEPTIONAL"
    assert _tier(rows, "SHADOWFAX") == "EXCEPTIONAL"
    assert _tier(rows, "MUTHOOTFIN") == "STRONG"
    assert _tier(rows, "SUNPHARMA") == "MIXED"
    assert _tier(rows, "GARGI") == "WEAK"


def test_a_symbol_starting_with_a_digit_still_reads(rows):
    """20MICRONS is a real NSE symbol. A rule that required a leading
    letter would drop it."""
    assert _tier(rows, "20MICRONS") == "MIXED"


def test_the_counts_match_the_page(rows):
    assert counts(rows) == {"EXCEPTIONAL": 4, "STRONG": 2,
                            "MIXED": 2, "WEAK": 1}


def test_a_name_before_any_heading_is_refused():
    """Without a heading above it there is no tier, and inventing one
    would put a WEAK company in the EXCEPTIONAL list."""
    assert parse_watchlist("NSE:DIVISLAB,\n### STRONG,\nNSE:CORONA,\n") == [
        {"symbol": "CORONA", "tier": "STRONG"}]


def test_an_unknown_heading_stops_the_tier_rather_than_guessing():
    got = parse_watchlist("### SOMETHING ELSE,\nNSE:DIVISLAB,\n")
    assert got == []


# ---------------------------------------------------------------
# 2. NSE ONLY
# ---------------------------------------------------------------
def test_bse_codes_wearing_an_nse_prefix_are_dropped(rows):
    """"NSE:BSE-526935" is a BSE scrip the exporter labelled NSE. Two
    of them were in the 1 August file.

        "pls make sure we will trade only NSE listed stocks"
    """
    names = {r["symbol"] for r in rows}
    assert not any(n.startswith("BSE") for n in names)
    assert "BSE-526935" not in names
    assert "BSE-543980" not in names


def test_the_universe_gate_is_available(rows):
    got = parse_watchlist(EXPORT, known={"DIVISLAB", "CORONA"})
    assert {r["symbol"] for r in got} == {"DIVISLAB", "CORONA"}


# ---------------------------------------------------------------
# 3. THE CHIP SAYS NOTHING IT MUST NOT SAY
# ---------------------------------------------------------------
@pytest.mark.parametrize("tier", TIERS)
def test_no_headline_ever_gives_an_instruction(tier):
    """SEBI, and their own disclaimer. This is the guard the operator
    asked for by name."""
    head = headline_for({"symbol": "X", "tier": tier}) or ""
    lowered = head.lower()
    for word in ("buy", "sell", "hold", "skip", "target", "recommend"):
        assert word not in lowered, f"{tier} headline says '{word}'"


def test_the_source_module_contains_no_instruction_words():
    src = open("core/canslim.py", encoding="utf-8").read()
    body = "\n".join(ln for ln in src.splitlines()
                     if not ln.strip().startswith(("#", '"', "'")))
    for word in ('"BUY"', '"SELL"', "'BUY'", "'SELL'"):
        assert word not in body


def test_an_unknown_tier_has_no_chip():
    assert headline_for({"symbol": "X", "tier": "SUPERB"}) is None
    assert headline_for({"symbol": "X"}) is None


# ---------------------------------------------------------------
# 4. RARITY TRAVELS WITH THE TIER
# ---------------------------------------------------------------
def test_the_chip_carries_how_rare_the_tier_is(rows):
    """Their page says EXCEPTIONAL is "typically 0-3 names per day" out
    of around 92. The word alone reads like a grade; with the count it
    reads like a shortlist, which is what it is."""
    tagged = with_rarity(rows)
    top = next(r for r in tagged if r["symbol"] == "DIVISLAB")
    head = headline_for(top, on=date(2026, 8, 1))
    assert "EXCEPTIONAL" in head
    assert "4 of 9" in head
    assert "01 Aug" in head


def test_rarity_does_not_change_the_tier(rows):
    before = {r["symbol"]: r["tier"] for r in rows}
    after = {r["symbol"]: r["tier"] for r in with_rarity(rows)}
    assert before == after


# ---------------------------------------------------------------
# 5. HOW IT REACHES THE PANEL
# ---------------------------------------------------------------
def test_setup_is_a_kind_the_store_accepts():
    from core.stock_events import USEFUL_KINDS
    assert "SETUP" in USEFUL_KINDS


def test_the_chip_scores_nothing():
    """A tier is not evidence the stock will rise. Nobody has measured
    whether EXCEPTIONAL outperforms -- their page says they do not
    track it either. outcomes.py can answer it after a month."""
    src = open("core/shortlist.py", encoding="utf-8").read()
    block = src[src.find('elif kind == "SETUP"'):]
    block = block[:block.find('elif kind == "REPORTED"')]
    assert "0.0" in block


def test_the_loader_defaults_to_a_dry_run():
    src = open("tools/load_canslim.py", encoding="utf-8").read()
    assert '"--apply"' in src and "DRY RUN" in src


def test_the_loader_gates_on_the_nse_master():
    src = open("tools/load_canslim.py", encoding="utf-8").read()
    assert "MasterLoader" in src
    assert "include_blocked=True" in src
