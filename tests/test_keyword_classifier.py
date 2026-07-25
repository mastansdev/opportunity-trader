"""
==========================================================
Tests -- FREE keyword classifier (news_bot/keyword_classifier.py)
==========================================================

Locks in the free classifier's contract so it can stand in for
the paid Haiku classifier without surprising the rest of the
pipeline: same return shape, sane direction/confidence/materiality,
and the "classifier": "keyword" stamp the gate uses to decide
whether keyword news is allowed to block a trade.

Author : H&M Opportunity Trader
==========================================================
"""

from news_bot import keyword_classifier
from news_bot.models import NewsItem


def _item(title, summary=""):
    return NewsItem(
        source="TEST",
        title=title,
        summary=summary,
        link="http://x/" + title.replace(" ", "_"),
        published_raw="",
        guid=title,
    )


# ---------------------------------------------------------------
# Shape / contract
# ---------------------------------------------------------------

def test_return_shape_has_all_keys_and_keyword_stamp():
    r = keyword_classifier.classify(_item("Company wins order worth 500 cr"))
    assert set(r) == {
        "direction", "confidence", "materiality", "reason", "classifier"
    }
    assert r["classifier"] == "keyword"


def test_company_arg_is_accepted_but_optional():
    # Signature parity with classification.classify(item, company)
    r1 = keyword_classifier.classify(_item("ABC bags contract"))
    r2 = keyword_classifier.classify(_item("ABC bags contract"), company={"SYMBOL": "ABC"})
    assert r1["direction"] == r2["direction"] == "bullish"


# ---------------------------------------------------------------
# Direction
# ---------------------------------------------------------------

def test_strong_bullish_headline_is_bullish_material_high_confidence():
    r = keyword_classifier.classify(_item("XYZ wins order worth 1200 crore from railways"))
    assert r["direction"] == "bullish"
    assert r["materiality"] == "material"
    assert r["confidence"] >= 70          # clears the HIGH bar


def test_strong_bearish_headline_is_bearish_material_high_confidence():
    r = keyword_classifier.classify(_item("SEBI bars promoter, launches probe into fraud"))
    assert r["direction"] == "bearish"
    assert r["materiality"] == "material"
    assert r["confidence"] >= 70


def test_no_directional_keywords_is_neutral_routine():
    r = keyword_classifier.classify(_item("Company to hold analyst meet next Tuesday"))
    assert r["direction"] == "neutral"
    assert r["materiality"] == "routine"
    assert r["confidence"] < 70           # never HIGH


def test_conflicting_strong_terms_stay_ambiguous_not_high():
    # Both a strong bull and a strong bear term -> material but NOT
    # confident enough to clear HIGH.
    r = keyword_classifier.classify(
        _item("Profit rises but SEBI opens probe into accounting")
    )
    assert r["materiality"] == "material"
    assert r["confidence"] < 70


def test_soft_only_signal_stays_mid_confidence():
    r = keyword_classifier.classify(_item("Stock rises on positive sentiment"))
    assert r["direction"] == "bullish"
    assert r["materiality"] == "routine"   # no STRONG term
    assert r["confidence"] < 70


def test_reason_names_the_matched_terms():
    r = keyword_classifier.classify(_item("Company bags order worth 300 cr"))
    assert "keyword match" in r["reason"].lower()
    assert "order" in r["reason"].lower()


def test_substring_traps_do_not_fire_word_boundary(tmp_path=None):
    """Regression for the live 2026-07-24 bug: substring matching
    stamped bearish HIGH onto 8 banks off 'UAE Bank Partners' because
    'ban' matched inside 'Bank'. Whole-word matching must NOT fire on
    any of these."""
    # 'ban' must NOT match 'Bank' / 'Banking'
    r = keyword_classifier.classify(
        _item("Deal Win - Leading UAE Bank Partners revolutionise Corporate Banking")
    )
    assert r["direction"] != "bearish"          # the false signal is gone
    # 'cut' must NOT match 'circuit' / 'execute'
    assert keyword_classifier.classify(_item("Plant circuit upgrade to execute plan"))
    r2 = keyword_classifier.classify(_item("Board to execute the circuit maintenance"))
    assert "cut" not in r2["reason"]
    # 'gains' must NOT match 'bargains'
    r3 = keyword_classifier.classify(_item("Investors hunt for bargains"))
    assert r3["direction"] == "neutral"


def test_standalone_words_still_match():
    """The whole-word fix must not break real signals."""
    assert keyword_classifier.classify(_item("Government imposes export ban"))["direction"] == "bearish"
    assert keyword_classifier.classify(_item("Stock gains after results"))["direction"] == "bullish"


def test_title_and_summary_are_both_scanned():
    r = keyword_classifier.classify(
        _item("Board meeting outcome", summary="Company declares record profit and buyback")
    )
    assert r["direction"] == "bullish"
    assert r["materiality"] == "material"
