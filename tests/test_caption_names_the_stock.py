r"""
==========================================================
The caption names the stock. All of it, or none of it.
==========================================================

    "Earnings Pulse & Pro both uses same format #Company name.
     recheck & i'm 100% sure"
    "make sure every results, our chips, news, orders any other things
     each are tagged/linked to their own stocks & no lapse or swapping
     of results, investor presentations or mainly in order pulse."
                                    -- operator, 2 August 2026

He was right and the measurement was wrong, three times over. Each
was a silent hole in the rule that is supposed to make the publisher's
caption final:

    1. THE TAG PATTERN COULD NOT SEE HALF THE TAGS
       r"#([A-Z][A-Z0-9&\-]{2,19})"  -- a letter first, no underscore.

           #20MICRONS  #63MOONS  #360ONE     start with a digit
           #M_M  #J_KBANK  #M_MFIN           & written as _
           #VHLTD_RE  #HCG_RE                rights entitlement

       On every one the caption named the company outright and the
       caption rule never fired, so the card fell through to guessing
       from the prose.

    2. THE MATCHER COULD NOT TOKENISE A DIGIT-LED TICKER
       Same assumption one layer down, in telegram_feed.symbols_in().
       360ONE, 3MINDIA and 63MOONS are real NSE symbols and could
       never be matched at all.

    3. THE FIRST TAG WON, EVEN WHEN THERE WERE SIXTY
       "Tomorrow's Calendar - Key companies: #BHARTIARTL #MARUTI
       #SUNPHARMA ..." answered BHARTIARTL. Because that answer is
       used to NARROW a card to one company, a sixty-name calendar
       was one refactor away from filing every REPORTED row against
       Bharti Airtel. The store-wide audit surfaced it as 386 rows
       "disagreeing with their caption" -- and the caption was right
       to name many.

AND THE ONE THAT COSTS A TRADE
------------------------------
When the tag resolves to nothing, the old code went looking in the
prose. The prose of an order card names the CUSTOMER:

    "#TAKYON  Takyon Networks wins Rs 14.32 crore HAL IT network
              upgrade order"                     -> filed against HAL
    "#S_SPOWER New order over Rs 8 crore from Siemens for isolator
              supply"                        -> filed against SIEMENS

Measured over the store: 25 messages took that path and 19 of them
were wrong, including both order cards above. The six real losses are
all a tag that ABBREVIATES the same company (#DRL for DRREDDY). An
abbreviation can be aliased on purpose later; a counterparty filed as
the subject cannot be detected by anything downstream.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.stock_events import resolve_tag, symbols_first


class Matcher:
    """The master, as core/telegram_feed.py exposes it."""

    def __init__(self, known):
        self.known = {s.upper() for s in known}

    def _known_symbols(self):
        return set(self.known)

    def symbols_in(self, text):
        import re
        up = str(text or "").upper()
        found = []
        for token in re.findall(r"#?[A-Za-z0-9][A-Za-z0-9&_\-]{2,}", up):
            bare = token.lstrip("#")
            if bare in self.known and bare not in found:
                found.append(bare)
        return found

    def names_in(self, text):
        return []


KNOWN = ["M&M", "M&MFIN", "J&KBANK", "VHLTD", "HCG", "STARHEALTH",
         "LOTUSDEV", "INDOBORAX", "360ONE", "3MINDIA", "63MOONS",
         "BIRLACABLE", "DEEPINDS", "BHARTIARTL", "MARUTI", "SUNPHARMA",
         "SIEMENS", "HAL", "IRFC", "DOLLAR", "BSE"]
M = Matcher(KNOWN)


# ---------------------------------------------------------------
# 1. THE TAGS THE PATTERN COULD NOT SEE
# ---------------------------------------------------------------
@pytest.mark.parametrize("tag,expected", [
    ("M_M", "M&M"),
    ("M_MFIN", "M&MFIN"),
    ("J_KBANK", "J&KBANK"),
])
def test_the_publisher_writes_an_ampersand_as_an_underscore(tag, expected):
    """Telegram will not carry an & inside a hashtag, so the publisher
    has to write something. This is reversible and cannot reach a
    company other than the one the tag already spells."""
    assert resolve_tag(M, tag) == expected


@pytest.mark.parametrize("tag,expected", [
    ("VHLTD_RE", "VHLTD"),
    ("HCG_RE", "HCG"),
])
def test_a_rights_entitlement_is_the_same_company(tag, expected):
    assert resolve_tag(M, tag) == expected


@pytest.mark.parametrize("caption,expected", [
    ("#63MOONS.NS", "63MOONS"),
    ("#360ONE.NS", "360ONE"),
    ("🟢 #M_M — Q1 FY27 Strong on Automotive & Farm", "M&M"),
    ("🔴 #J_KBANK — Q1 FY27 Profitability declined", "J&KBANK"),
])
def test_the_caption_is_read_end_to_end(caption, expected):
    assert symbols_first(M, caption) == expected


# ---------------------------------------------------------------
# 2. THE NEAR-MISSES THAT MUST STAY REFUSED
# ---------------------------------------------------------------
@pytest.mark.parametrize("tag,nearly", [
    ("STARHF_RE", "STARHEALTH"),
    ("LOTUSCHO", "LOTUSDEV"),
    ("INDOBELL", "INDOBORAX"),
])
def test_a_near_miss_is_not_evidence(tag, nearly):
    """Star HOUSING Finance is not Star Health. Lotus Chocolate is not
    Lotus Developers. Indobell Insulations is not Indo Borax. A
    prefix-matching rule mapped all three and would have put a
    micro-cap's rights entitlement on a Nifty insurer's row."""
    assert resolve_tag(M, tag) != nearly
    assert resolve_tag(M, tag) is None


def test_a_bse_scrip_code_resolves_to_nothing():
    """#BSE_543980 is another company's card entirely. Splitting it
    filed two GREAT quarters against BSE Ltd."""
    assert resolve_tag(M, "BSE_543980") is None
    assert symbols_first(M, "🟢 #BSE_543980 — Q1 FY27 Solid quarter") is None


# ---------------------------------------------------------------
# 3. SEVERAL COMPANIES NAMED IS NOT ONE SUBJECT
# ---------------------------------------------------------------
def test_a_calendar_caption_naming_many_identifies_none():
    """This answered BHARTIARTL, and that answer NARROWS a card to one
    company. A sixty-name calendar would have filed every row against
    the first tag on it."""
    caption = ("📅 Tomorrow's Calendar - 30 Jul, 2026\n"
               "Key companies reporting: #BHARTIARTL #MARUTI #SUNPHARMA")
    assert symbols_first(M, caption) is None


def test_the_same_tag_repeated_is_still_one_company():
    """Earnings 360 prints the tag twice -- once in the headline and
    once at the foot. That is one company, not two."""
    caption = "🟢 #BIRLACABLE — Q1 FY27 Skyrocketing profit\n\n#BIRLACABLE"
    assert symbols_first(M, caption) == "BIRLACABLE"


# ---------------------------------------------------------------
# 4. THE COUNTERPARTY MUST NEVER WIN THE ORDER
# ---------------------------------------------------------------
def test_the_customer_does_not_get_the_order():
    """     "no lapse or swapping of results ... mainly in order pulse"

    Takyon Networks won this. HAL bought it. Filing it against HAL
    puts a real order win on a company that won nothing -- and puts
    the value_cr chip beside it on the panel."""
    caption = ("⭐ Takyon Networks wins ₹14.32 crore HAL IT network "
               "upgrade order. #TAKYON")
    assert symbols_first(M, caption) is None, "HAL must not win it"


def test_the_supplier_does_not_get_the_order_either():
    caption = ("⭐ New order over ₹8 crore from Siemens for isolator "
               "supply. #S_SPOWER")
    assert symbols_first(M, caption) is None, "SIEMENS must not win it"


def test_a_currency_story_does_not_become_a_textile_company():
    """DOLLAR is Dollar Industries, a real ticker. A story about the
    US dollar is not about it."""
    caption = ("💱 The U.S. Dollar traded near a one-month high on safe "
               "haven demand. #MODRNSH")
    assert symbols_first(M, caption) is None


def test_an_unresolvable_tag_is_logged_not_swallowed():
    """The six genuine losses are tags that ABBREVIATE the same company
    (#DRL for DRREDDY). They can be aliased on purpose -- but only if
    the refusal is visible."""
    src = open("core/stock_events.py", encoding="utf-8").read()
    block = src[src.find("A TAG WE CANNOT RESOLVE IS STILL AN ANSWER"):]
    block = block[:block.find("DB_PATH")]
    assert "diagnostic(" in block
    assert "refusing to name a company from the prose" in block


# ---------------------------------------------------------------
# 5. WHAT MUST NOT CHANGE
# ---------------------------------------------------------------
def test_a_message_with_no_tag_falls_back_exactly_as_before():
    """The rule narrows; it does not widen. A single unambiguous name
    with no hashtag anywhere is still that company."""
    assert symbols_first(M, "Siemens reported a strong quarter") == "SIEMENS"


def test_two_names_and_no_tag_is_still_a_refusal():
    assert symbols_first(M, "SIEMENS and HAL both rose today") is None


def test_the_tag_pattern_accepts_every_shape_the_channels_send():
    from core.stock_events import _TAGS
    for tag in ("BIRLACABLE", "M_M", "63MOONS", "360ONE", "20MICRONS",
                "VHLTD_RE", "BSE_543980", "ARE&M"):
        assert _TAGS.findall(f"#{tag} ") == [tag], tag


def test_a_bare_number_is_not_a_ticker():
    """Business Pulse tables are full of them: 5,33,416 / 22,10,729.
    Allowing a digit to LEAD must not make those candidates."""
    assert M.symbols_in("Total 2Ws 5,33,416 4,49,755 22,10,729") == []
    assert symbols_first(M, "Period: 2026-06-30 Q1 FY27") is None
