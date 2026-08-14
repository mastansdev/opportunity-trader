"""
==========================================================
What management said, not what the numbers did
==========================================================

    "conviction on business + confidence on management"
                                    -- operator, 1 August 2026

He described the signal. Earnings 360 had been sending it in full
after every concall, and the bot filed it like this:

    kind = NEWS      grade = None      ai_direction = None
    headline = "ADANIENSOL - Concall Summary Period: 2026-06-30
                SENTIMENT TONE = Positive Confid"

Cut off mid-word. Everything below discarded.

    79 concall cards received
    78 carrying SENTIMENT TONE
     0 with the tone, guidance or red flags extracted

The same failure as the Pulse grid on 31 July, in a second place:
somebody had already listened to the call and written down what was
said, and the bot read the top line.

WHAT THE CARD HOLDS
-------------------
    SENTIMENT TONE      Positive, Confident
    GUIDE - GROWTH      Rising
    GUIDE - MARGINS     Expanding
    TONE SIGNAL         "Unwavering conviction; management avoided
                         hedging future performance expectations"
    GUIDANCE            growth / margins / capex, in words and figures
    RED FLAGS           LANGUAGE and BEHAVIOUR, not numbers
    WHAT CHANGED VS LAST QUARTER

A filing tells you profit fell. Only this tells you guidance was
"hedged FY28 capex on Solapur success" -- a sentence about
confidence, which is what he asked for.

AFTER: 78 cards -> 70 tones, 75 guidance blocks, 60 stored events.

THREE THINGS THIS DELIBERATELY REFUSES
--------------------------------------
1. IT DOES NOT SCORE. A result is arithmetic; a concall is a person
   choosing words, and nothing has measured whether a confident tone
   is worth paying for. The chip shows at 0.0 points until
   core/outcomes.py has samples.

2. IT DOES NOT SPLIT THE COLLIDING COLUMNS. RED FLAGS and TRACK NEXT
   SIGNALS print side by side, and on 68 of 78 cards the reader puts
   both headings on one line so their bullets interleave with no
   marker. "rCB facility commissioning by Oct" is a date to watch, not
   a warning -- labelling it a red flag would invent a concern the
   publisher never raised. Those cards return mixed_observations()
   instead, kept and honestly named.

3. IT DOES NOT GUESS THE COMPANY. The card names its company once at
   the top and then discusses customers, plants and rivals. The
   publisher's own hashtag decides; with no usable hashtag and more
   than one name in the body, it returns nothing.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.concall import (columns_collide, gauges, guidance, is_concall_card,
                          mixed_observations, read_card, red_flags, sections,
                          summary)

# Verbatim from telegram.db, OCR damage included. The icons in front of
# the three gauge values came back as "=", "t" and "+".
DODLA = """@ Earnings Pulse DODLA =
SENTIMENT TONE GUIDE - GROWTH GUIDE - MARGINS
= Mixed Cautious t Rising + Expanding
WHY Record topline offset by margin TONE SIGNAL Reiterated margin targets while
squeeze and rising procurement costs. justifying price hikes via gradual implementation.
& GUIDANCE: INTERPRETED
GROWTH T sustained volume growth across segments
MARGINS T recovery to 7-8% range gradually
CAPEX > funded internally via 2590 Cr plan
KEY TAKEAWAYS WHAT CHANGED VS LAST QUARTER
= Record procurement and revenue = Higher procurement cost volatility
growth achieved = Strategic D2C stake in Sids Farm
High input costs compressed EBITDA
gm RED FLAGSANGUAGE - BEHAVIOR TRACK NEXT SIGNALS - NOT METRICS
Margins significantly below historical targets
Realization of planned price hikes
"""

# A card where the two right-hand columns did NOT collide.
CLEAN_COLUMNS = """SENTIMENT TONE GUIDE - GROWTH GUIDE - MARGINS
= Positive Confident t Rising > Stable
& GUIDANCE: INTERPRETED
GROWTH T Mid-teens revenue target
MARGINS ~ Maintain 27-28% EBITDA range
CAPEX 2150 Cr for M&A, radiology labs
&& RED FLAGSANGUAGE - BEHAVIOR
= International markets remain long-term bets
Vague on long-term margin reinvestment impact
TONE SIGNAL Unapologetic focus on execution
"""


# ---------------------------------------------------------------
# 1. RECOGNISING THE CARD
# ---------------------------------------------------------------
def test_a_concall_card_is_recognised():
    assert is_concall_card(DODLA)
    assert is_concall_card("#ADANIENSOL - Concall Summary Period: 2026-06-30")


def test_ordinary_news_is_not_a_concall_card():
    for text in ("Reliance bags Rs 2,205 crore order",
                 "#GHCL - Excellent Results", ""):
        assert not is_concall_card(text)


# ---------------------------------------------------------------
# 2. THE THREE GAUGES
# ---------------------------------------------------------------
def test_the_tone_is_read_with_its_manner():
    got = gauges(DODLA)
    assert got["mood"] == "Mixed"
    assert got["manner"] == "Cautious"


def test_growth_and_margins_land_on_the_right_gauge():
    """THE ONE THAT MATTERS. The values print on one line --
    "= Mixed Cautious t Rising + Expanding" -- and the leading
    characters are icons the reader turned into letters. Position
    shifts whenever OCR drops or invents a character, so the values
    are found by vocabulary. A guidance direction on the wrong gauge
    is the same class of error as a quarter on the wrong company."""
    got = gauges(DODLA)
    assert got["growth"] == "Rising"
    assert got["margins"] == "Expanding"


def test_stable_is_not_claimed_by_both_gauges():
    """STABLE and FLAT are legal on either gauge. The card prints
    growth first, so the later word is the margin one."""
    got = gauges(CLEAN_COLUMNS)
    assert got["growth"] == "Rising"
    assert got["margins"] == "Stable"


def test_no_header_means_no_gauges_at_all():
    """A half-filled gauge dict would put a direction against a metric
    nobody stated."""
    assert gauges("Concall Summary for ABC. Management sounded upbeat.") == {}
    assert gauges("") == {}


# ---------------------------------------------------------------
# 3. THE GUIDANCE, WITH ITS FIGURES
# ---------------------------------------------------------------
def test_guidance_keeps_the_sentence_and_the_number():
    got = guidance(DODLA)
    assert "volume growth" in got["growth"]
    assert "7-8%" in got["margin"]
    assert "2590 Cr" in got["capex"]


def test_the_ocr_arrow_is_stripped_from_the_value():
    """The card prints an arrow before each guidance sentence and OCR
    returns it as T, Tt, Tf, ~, > or a dash. It duplicates a gauge that
    has already been read properly, and a stray letter in front of a
    figure is how a number gets misread later."""
    got = guidance(DODLA)
    for value in got.values():
        assert not value.startswith(("T ", "~ ", "> ", "- "))
    assert got["growth"].startswith("sustained")


def test_a_real_word_starting_with_t_survives():
    """The arrow strip must not eat "Target stable returns"."""
    card = ("SENTIMENT TONE GUIDE - GROWTH GUIDE - MARGINS\n"
            "= Positive Confident t Rising + Expanding\n"
            "GUIDANCE: INTERPRETED\n"
            "MARGINS Target stable returns through scale efficiency\n")
    assert guidance(card)["margin"].startswith("Target stable")


# ---------------------------------------------------------------
# 4. THE COLLIDING COLUMNS
# ---------------------------------------------------------------
def test_a_collision_is_detected():
    assert columns_collide(DODLA)
    assert not columns_collide(CLEAN_COLUMNS)


def test_red_flags_are_empty_when_the_columns_collide():
    """68 of 78 cards. "rCB facility commissioning by Oct" is a date to
    watch. Calling it a red flag would put a warning on a company for
    scheduling a commissioning."""
    assert red_flags(DODLA) == []


def test_the_colliding_block_is_kept_under_an_honest_name():
    """The standing rule is not to throw away information we are
    receiving. It is kept -- just not called a warning."""
    got = mixed_observations(DODLA)
    assert got
    assert any("price hikes" in line for line in got)


def test_red_flags_are_read_when_the_columns_separate():
    got = red_flags(CLEAN_COLUMNS)
    assert got
    assert any("International markets" in line for line in got)
    assert mixed_observations(CLEAN_COLUMNS) == []


def test_a_heading_fragment_is_never_reported_as_a_finding():
    """The heading is "RED FLAGS / LANGUAGE - BEHAVIOR" and OCR eats
    the slash. The first version stopped at "ANGUAGE" and every card
    came back with BEHAVIOR as its first red flag."""
    for card in (DODLA, CLEAN_COLUMNS):
        for line in red_flags(card) + mixed_observations(card):
            assert line.strip().upper() not in (
                "BEHAVIOR", "BEHAVIOUR", "NOT METRICS",
                "TRACK NEXT SIGNALS", "LANGUAGE")


# ---------------------------------------------------------------
# 5. THE CHIP
# ---------------------------------------------------------------
def test_the_summary_leads_with_the_tone():
    got = summary(DODLA)
    assert got.startswith("CONCALL MIXED/CAUTIOUS")
    assert "growth rising" in got
    assert "margins expanding" in got


def test_a_card_with_no_tone_has_no_chip():
    """Rather than a chip that says CONCALL and nothing else."""
    assert summary("Concall Summary. Nothing legible.") is None


def test_the_chip_is_shown_but_never_scored():
    """A result is arithmetic. A concall is a person choosing words,
    and nothing here has measured whether a confident tone is worth
    paying for. Scoring it would be inventing an edge."""
    src = open("core/shortlist.py", encoding="utf-8").read()
    block = src[src.find('elif kind == "CONCALL"'):]
    block = block[:block.find('elif kind == "ORDER"')]
    assert "0.0" in block, "the concall chip must contribute zero points"


def test_the_chip_is_not_printed_twice():
    """_lead_fact() promotes a parser's own label out of a headline.
    The concall headline IS the parsed reading, so running it through
    would print half the chip a second time on the same row."""
    src = open("core/shortlist.py", encoding="utf-8").read()
    assert '"CONCALL")' in src or '"CONCALL",' in src


# ---------------------------------------------------------------
# 6. THE WHOLE CARD
# ---------------------------------------------------------------
def test_read_card_refuses_a_message_that_is_not_one():
    assert read_card("Reliance bags Rs 2,205 crore order") is None


def test_read_card_returns_every_part():
    got = read_card(DODLA)
    assert got["gauges"]["mood"] == "Mixed"
    assert got["guidance"]["capex"]
    assert got["summary"].startswith("CONCALL")
    assert got["mixed"]
    assert got["sections"]


def test_the_left_and_right_prose_columns_collide_too():
    """KEY TAKEAWAYS and WHAT CHANGED VS LAST QUARTER are also side by
    side, and on this card the reader put both headings on one line:

        KEY TAKEAWAYS WHAT CHANGED VS LAST QUARTER
        = Record procurement and revenue = Higher procurement cost...

    So "takeaways" comes back empty and the bullets -- from BOTH
    columns, concatenated on each line -- land under "changed".

    This test exists so that is a KNOWN fact rather than a surprise.
    Nothing is lost and nothing is mislabelled as a warning, which is
    the part that matters; neither block feeds the chip or the score.
    Splitting them would need a column boundary the text does not
    carry, and guessing one is what red_flags() already refuses to do.
    """
    got = sections(DODLA)
    assert "takeaways" not in got
    assert any("procurement" in line for line in got["changed"])


def test_concall_is_a_kind_the_store_accepts():
    from core.stock_events import USEFUL_KINDS
    assert "CONCALL" in USEFUL_KINDS


def test_the_card_is_read_before_the_digest_rule_drops_it():
    """A concall card names its company once and then discusses
    customers, plants and rivals in the takeaways. The three-name rule
    exists for news RECAPS, where the wrong figure gets paired with the
    wrong company -- it was silently dropping every concall card."""
    src = open("core/stock_events.py", encoding="utf-8").read()
    concall_at = src.find("if is_concall_card(body):")
    digest_at = src.find("if is_digest(body):")
    assert 0 < concall_at < digest_at
