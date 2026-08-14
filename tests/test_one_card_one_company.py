"""
==========================================================
The caption says whose card this is
==========================================================

    "this channel provide 3 documents = CONCALL, INVESTOR PRESENTATION,
     EARNINGS BREIF. with stock name. so pls do not miss or club one
     data to other stock."
                                    -- operator, 2 August 2026

He was right, and it was already happening. Measured on the 432
Earnings 360 cards in the store:

    415 name exactly one company in the CAPTION
     23 of those were ALSO filed against a second stock

because the card's own body mentions another company:

    #BIRLACABLE  "Proposed amalgamation with Vindhya"  -> VINDHYATEL
    #SAGCEM      a cement peer named in the text       -> ACL
    #BAJAJFINSV  its own subsidiary                    -> BAJFINANCE
    #MGL         a gas peer                            -> GAIL
    #DIAMONDYD   a name deep in the OCR                -> SOUTHBANK

Every one of those put BIRLACABLE's EXCELLENT result on Vindhya
Telelinks' row -- on the panel he clicks BUY from. It is the POWERGRID
bug in a different costume: a company MENTIONED is not the company the
card is ABOUT.

THE PUBLISHERS SETTLE IT THEMSELVES
-----------------------------------
Every one of these cards carries a caption hashtag. That is what THEY
say the card is about, and no amount of prose underneath changes it.
symbols_first() has read it that way for concall and verdict cards
since 1 August; this applies the same rule to the path everything else
falls down.

WHAT WAS ALSO WRONG, AND HOW IT WAS AVOIDED
-------------------------------------------
The first cleanup swept 184 stored rows whose headline named a
different company. 65 of them were NOT mis-tags -- the tag was a
variant spelling of the SAME company:

    M&M / #M_M        COFORGE / #COF        HCG / #HCG_RE

Deleting those would have destroyed real events. The rule was
tightened to "the tag resolves to a DIFFERENT REAL master symbol",
which left the variants alone and removed 119.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.stock_events import events_from_message, symbols_first


class Matcher:
    """The master, as core/telegram_feed.py exposes it."""

    def __init__(self, known):
        self.known = {s.upper() for s in known}

    def _known_symbols(self):
        return set(self.known)

    def symbols_in(self, text):
        up = str(text or "").upper()
        import re
        found = []
        for s in self.known:
            if re.search(rf"[#\b]?{re.escape(s)}\b", up):
                found.append(s)
        return found

    def names_in(self, text):
        return []


KNOWN = ["BIRLACABLE", "VINDHYATEL", "DIAMONDYD", "SOUTHBANK",
         "BAJAJFINSV", "BAJFINANCE", "SAGCEM", "ACL", "MGL", "GAIL"]


def run(caption, ocr="", **kw):
    return events_from_message(Matcher(KNOWN), text=caption, ocr_text=ocr,
                               at="2026-08-02T12:44:00",
                               channel="Earnings 360", **kw) or []


# ---------------------------------------------------------------
# 1. THE REAL CARDS THAT WENT WRONG
# ---------------------------------------------------------------
def test_a_merger_mentioned_in_the_body_does_not_get_the_card():
    """The one from his screenshot's channel. BIRLACABLE's EXCELLENT
    result was filed against Vindhya Telelinks because the card said
    "Proposed amalgamation with Vindhya"."""
    got = run("🟢 #BIRLACABLE — Q1 FY27 Skyrocketing profit on strong "
              "revenue growth. #BIRLACABLE",
              "EXCELLENT GROWTH MARGINS Proposed amalgamation with "
              "VINDHYATEL Lower finance costs")
    assert [e["symbol"] for e in got] == ["BIRLACABLE"]


def test_a_subsidiary_named_in_the_card_does_not_get_the_card():
    got = run("🟢 #BAJAJFINSV — Q1 FY27 Strong consolidated top-line",
              "consolidated includes BAJFINANCE contribution")
    assert [e["symbol"] for e in got] == ["BAJAJFINSV"]


def test_a_peer_named_in_the_card_does_not_get_the_card():
    got = run("🔴 #MGL — Q1 FY27 Quarterly profits collapse",
              "city gas peers GAIL also under margin pressure")
    assert [e["symbol"] for e in got] == ["MGL"]


def test_an_investor_presentation_files_against_its_own_stock_only():
    got = run("📝 #DIAMONDYD — Investor Presentation Period: 2026-06-30 "
              "#DIAMONDYD",
              "DIAMONDYD STRATEGY quick commerce SOUTHBANK regional")
    assert [e["symbol"] for e in got] == ["DIAMONDYD"]


# ---------------------------------------------------------------
# 2. WHAT MUST NOT CHANGE
# ---------------------------------------------------------------
def test_a_card_naming_one_company_is_untouched():
    got = run("🟢 #SAGCEM — Q1 FY27 volumes up", "SAGCEM cement volumes")
    assert [e["symbol"] for e in got] == ["SAGCEM"]


def test_a_plain_news_line_with_no_hashtag_is_untouched():
    """The rule keys on the CAPTION hashtag. A news line naming two
    companies and tagging neither is left exactly as it was -- this is
    not a general "pick the first symbol" rule."""
    got = run("", "MGL and GAIL both raised city gas tariffs today")
    assert {e["symbol"] for e in got} <= {"MGL", "GAIL"}
    assert len(got) == 2, "no caption tag means the old behaviour"


def test_the_three_company_rule_still_applies():
    """A message about three companies is about none of them, and that
    survives -- the hashtag rule narrows, it does not widen."""
    got = run("", "MGL GAIL SAGCEM ACL all rose today")
    assert got == []


def test_the_hashtag_must_be_a_real_symbol():
    """#COF, #M_M, #HCG_RE are variant spellings, not master symbols.
    A tag that resolves to nothing must not silence the body."""
    assert symbols_first(Matcher(KNOWN), "#NOTASTOCK — something") is None


# ---------------------------------------------------------------
# 3. THE CLEANUP RULE THAT ALMOST DESTROYED REAL EVENTS
# ---------------------------------------------------------------
@pytest.mark.parametrize("symbol,tag", [
    ("M&M", "M_M"), ("COFORGE", "COF"), ("HCG", "HCG_RE"),
])
def test_a_variant_spelling_is_not_a_mismatch(symbol, tag):
    """The first sweep would have deleted 65 rows where the tag was the
    SAME company written differently. The tag has to resolve to a
    DIFFERENT REAL master symbol before anything is removed."""
    from core.master_loader import MasterLoader
    loader = MasterLoader()
    loader.load()
    assert loader.get_by_symbol(tag) is None, (
        f"{tag} is not a master symbol, so a row tagged {tag} on "
        f"{symbol} is the same company and must be left alone")


# ---------------------------------------------------------------
# 4. IT IS RECORDED, NOT SILENT
# ---------------------------------------------------------------
def test_the_dropped_company_is_logged():
    """Silently narrowing is how the opposite mistake would hide. If a
    card really is about two companies, the line in the log is the only
    way anyone finds out."""
    src = open("core/stock_events.py", encoding="utf-8").read()
    block = src[src.find("subject = symbols_first(matcher, typed)"):]
    block = block[:block.find("# A MESSAGE ABOUT THREE COMPANIES")]
    assert "diagnostic(" in block
    assert "not filed against them" in block


def test_the_rule_only_fires_on_the_caption():
    """typed, not body. The OCR of the picture is prose about the
    company; the caption is the publisher naming it."""
    src = open("core/stock_events.py", encoding="utf-8").read()
    assert "subject = symbols_first(matcher, typed) if typed else None" in src
