"""
==========================================================
Layer 04 -- the audit that overrules the algorithm
==========================================================

    "AI Verdict is what we get on the one page of stock = after
     assessing all AI will create a page & we will get them from
     EARNINGS PRO"
                                    -- operator, 2 August 2026

363 of these pages were already in the store. The bot had been saving
them for a week and reading the headline only.

THE TOP LINE CARRIES TWO RATINGS

    Algo Pulse: Weak | Verdict: MET

    Algo Pulse   the algorithm's grade of the quarter
    Verdict      what the audit concluded after reading the filing,
                 the presentation and the concall

Measured on 281 readable pairs:

    WEAK -> MISS    41    the audit agrees
    WEAK -> MET     35    the audit OVERRULES
    WEAK -> BEAT    22    the audit OVERRULES
    GOOD -> MISS    11    the audit OVERRULES

    70 of 281. ONE IN FOUR.

SYRMA is the case. Algo said Weak. The audit said BEAT -- "blowout
quarter with revenue surging 67% YoY". Under the old chip the operator
saw "PULSE: Weak" and moved on.

WHY THE FIGURES ARE NOT READ FROM THE PICTURE
---------------------------------------------
OCR destroys the rupee sign on every amount. From a real stored card:

    picture   75,455 Cr        caption   Rs 5,455 Cr
    picture   74,423 Cr        caption   Rs 4,423 Cr

Reading the picture files SHYAMMETL's revenue at seventy-five thousand
crore instead of five thousand -- 13x, silently, into the store. That
is the RAYMOND failure exactly, and it is why the summary line is taken
from the CAPTION, which Telegram delivers as real text.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.ai_verdict import (benchmarked, is_verdict_card, overruled, ratings,
                             summary, tally, themes)

CARD = """IPL
Q1 FY27
Algo Pulse: Weak | Verdict: MISS
Revenue and profits declined both sequentially and year-over-year
The True Growth Story
METRIC CURRENT VALUE PREVIOUS YOY YOY GROWTH CONTEXT / NOTES
Revenue 7251.8 Cr 7275.2 Cr -8.5% Decline amid sector headwinds.
Tally Against Expectations
THEME STATUS DETAILS
Revenue from Operations CONCERN Down 8.5% YoY to 7251.8 Cr
EBITDA Margin CONCERN Down 400 bps YoY to 15.7%
Net Profit (PAT) CONCERN Down 34.8% YoY to 722.7 Cr
The Verdict
The algo's 'Weak' rating is accurate.
Est x Exp v
"""

UPGRADE = """VISHNU
Q1 FY27
Algo Pulse: Weak | Verdict: MET
Strong year-on-year growth in revenue and profits
Tally Against Expectations
THEME STATUS DETAILS
Consolidated Revenue IMPROVING Revenue grew 24.9% YoY
Consolidated EBITDA IMPROVING EBITDA grew 29.8% YoY
Sequential Performance CONCERN Revenue, EBITDA and PAT all declined QoQ.
The Verdict
my audit finds the performance solid and upgrades the rating to MET.
Est x Exp v
"""

CAPTION = ("\U0001F504 #VISHNU — Earnings · Q1 FY27\n"
           "Revenue ₹433.4 Cr, up 24.9% YoY with EBITDA ₹78.3 Cr.\n"
           "#VISHNU")


# ---------------------------------------------------------------
# 1. THE PAIR
# ---------------------------------------------------------------
def test_a_verdict_card_is_recognised():
    assert is_verdict_card(CARD)
    assert not is_verdict_card("#GHCL - Excellent Results")
    assert not is_verdict_card("")


def test_both_ratings_are_read():
    got = ratings(CARD)
    assert got == {"algo": "WEAK", "verdict": "MISS"}


@pytest.mark.parametrize("pipe", ["|", "I", "l", "!", "/", ""])
def test_the_ocr_mangled_pipe_does_not_break_it(pipe):
    """The bar between the two ratings comes back as I, l or ! about a
    third of the time."""
    line = f"Algo Pulse: Good {pipe} Verdict: BEAT"
    assert ratings(line) == {"algo": "GOOD", "verdict": "BEAT"}


def test_a_verdict_without_its_algo_rating_is_refused():
    """A verdict alone cannot be told apart from an agreement, and the
    disagreement is the only reason to read this layer."""
    assert ratings("Verdict: BEAT") == {}


def test_a_word_that_is_not_a_verdict_is_refused():
    assert ratings("Algo Pulse: Good | Verdict: Ouring") == {}


# ---------------------------------------------------------------
# 2. THE DISAGREEMENT
# ---------------------------------------------------------------
@pytest.mark.parametrize("algo,verdict,expected", [
    ("WEAK", "BEAT", True),      # SYRMA
    ("WEAK", "MET", True),       # VISHNU
    ("GOOD", "MISS", True),      # KIRLOSBROS
    ("WEAK", "MISS", False),     # the audit agrees
    ("GOOD", "BEAT", False),
    ("EXCELLENT", "MET", False),
    ("OK", "BEAT", False),       # OK is not a position
    ("MIXED", "MISS", False),
])
def test_only_a_real_contradiction_counts(algo, verdict, expected):
    """An OK or MIXED algo rating takes no position, so nothing can
    contradict it. Forcing those into a verdict would manufacture
    disagreements that the publisher never expressed."""
    assert overruled({"algo": algo, "verdict": verdict}) is expected


def test_the_upgrade_case_leads_the_chip():
    got = summary(UPGRADE)
    assert got.startswith("AI AUDIT OVERRULES: algo said Weak, audit says MET")


def test_an_agreeing_card_does_not_shout():
    got = summary(CARD)
    assert got.startswith("AI AUDIT MISS: algo said Weak")
    assert "OVERRULES" not in got


# ---------------------------------------------------------------
# 3. THE THEMES
# ---------------------------------------------------------------
def test_the_theme_statuses_are_counted():
    assert tally(themes(CARD)) == {"CONCERN": 3}
    assert tally(themes(UPGRADE)) == {"IMPROVING": 2, "CONCERN": 1}


def test_the_column_heading_is_not_a_theme():
    """"THEME STATUS DETAILS" matches the row shape exactly."""
    names = {t["theme"].upper() for t in themes(CARD)}
    assert "THEME" not in names and "METRIC" not in names


def test_the_chip_carries_the_concern_count():
    got = summary(CARD)
    assert "3 concerns" in got


# ---------------------------------------------------------------
# 4. A BEAT AGAINST NOTHING
# ---------------------------------------------------------------
def test_missing_estimates_are_flagged():
    """Their own verdict text: "This is an un-benchmarked result with
    no consensus estimates". A BEAT nobody set a bar for is a different
    fact from a BEAT against consensus."""
    assert benchmarked(CARD) is False
    assert "no consensus estimates" in summary(CARD)


def test_an_unreadable_footer_claims_nothing():
    assert benchmarked("Algo Pulse: Good | Verdict: BEAT") is None
    assert "consensus" not in (summary("Algo Pulse: Good | Verdict: BEAT") or "")


# ---------------------------------------------------------------
# 5. THE FIGURES COME FROM THE CAPTION, NEVER THE PICTURE
# ---------------------------------------------------------------
def test_the_summary_line_is_taken_from_the_caption():
    """THE ONE THAT MATTERS. OCR turns Rs 5,455 Cr into 75,455 Cr --
    a 13x error. The caption is real text with real rupee signs."""
    got = summary(UPGRADE, caption=CAPTION)
    assert "₹433.4 Cr" in got
    assert "24.9% YoY" in got


def test_the_hashtag_header_line_is_skipped():
    got = summary(UPGRADE, caption=CAPTION)
    assert "Earnings · Q1 FY27" not in got


def test_no_caption_still_gives_a_chip():
    got = summary(UPGRADE)
    assert got and got.startswith("AI AUDIT OVERRULES")


def test_the_module_never_reads_a_rupee_amount_out_of_the_picture():
    """A regex for an amount in this file would be reading the one
    thing OCR reliably destroys."""
    src = open("core/ai_verdict.py", encoding="utf-8").read()
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.strip().startswith("#"))
    for pattern in ("Cr\\b", "crore", "[\\d,]+\\.\\d"):
        assert f're.compile(r"{pattern}' not in code


# ---------------------------------------------------------------
# 6. HOW IT REACHES THE PANEL
# ---------------------------------------------------------------
def test_ai_verdict_is_a_kind_the_store_accepts():
    from core.stock_events import USEFUL_KINDS
    assert "AI_VERDICT" in USEFUL_KINDS


def test_the_card_is_read_before_the_three_company_rule():
    """The page cites customers, segments and rivals in its tables."""
    src = open("core/stock_events.py", encoding="utf-8").read()
    card_at = src.find("if is_verdict_card(body):")
    rule_at = src.find("if len(symbols) >= 3:")
    assert 0 < card_at < rule_at


def test_the_algo_grade_is_not_stored_a_second_time():
    """The result card already filed it. Storing it again would count
    one opinion as two sources."""
    src = open("core/stock_events.py", encoding="utf-8").read()
    block = src[src.find("if is_verdict_card(body):"):]
    block = block[:block.find("if is_digest(body, companies=")]
    assert '"grade": None' in block


def test_the_chip_scores_nothing():
    src = open("core/shortlist.py", encoding="utf-8").read()
    block = src[src.find('elif (kind == "AI_VERDICT"'):]
    block = block[:block.find('elif kind == "SETUP"')]
    assert "0.0" in block
