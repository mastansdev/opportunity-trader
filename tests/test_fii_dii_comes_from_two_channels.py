"""---- THE TWO SOURCES HE NAMED. 31 August 2026. ----

    "FII /DII data we will get from day trader telugu (img) & news
     pulse."                                          -- the operator

Both were named. Only one worked. The prose parser needs the words
"buyers" or "sellers" and the Telugu channel posts a picture with
neither, so it had contributed nothing to this figure, ever, while
being one of the two named sources.

The other half of it is worse. When the picture IS read, OCR is not
exact -- the stored card for the 28 August session reads -50,359.8
where the image plainly shows -5,039.8. A digit was inserted. Nothing
downstream could catch that, because -50,359.8 is a perfectly
well-formed number, so the rule is: typed text always wins, a picture
is used only when no typed figure exists, and a disagreement is said
out loud rather than resolved by guessing which looks more plausible.
"""

from core.market_flows import (from_telegram, parse_flow_card,
                               parse_flow_message)

# Copied verbatim out of the operator's data/telegram.db -- OCR junk,
# arrow glyphs and all. Written-out samples would prove nothing; every
# hard part of this is in what the OCR actually does to the card.
TELUGU_28_AUG = """MARKET OVERVIEW
S&P@3SE Ie Gift nitty
SENSEX As on 28 Aug 02:29 AM
~ 76933.59 ~ 24090.85 4«24210.5
-539.35 -0.7% -116.9 -0.48% +10.5 0.04%
FIl & DIT CASH MARKET ACTIVITY
FIl cash market DIl cash market
~ -298.26 a 4977.17
FIIS IN DERIVATIVES
FIl Index Future FIl Stock Future
> -1871.04 y -1714.67
FIl index Option FIl Stock Option
4 6885.99 ¥ -641.97
@DayTraderTelugu"""

TELUGU_BAD_OCR = """4 77264.51 «24175.65 ~24282.5
330.92 0.43% 84.8 0.35% -29.5 -0.12%
FIl & DIT CASH MARKET ACTIVITY
FIl cash market DIl cash market
~ -50359.8 « 5183.93
FIIS IN DERIVATIVES
FIl Index Future FIl Stock Future
> -774.13 A 148.46
@DayTraderTelugu"""

NEWS_PULSE = ("FIIs were net sellers of Rs 5,039.80 Cr while DIIs were "
              "net buyers of Rs 5,183.93 Cr")


class _Feed:
    def __init__(self, rows):
        self._rows = rows

    def recent(self, limit=None, hours=None):
        return self._rows


def _row(channel, at, text="", ocr=""):
    return {"channel": channel, "at": at, "text": text, "ocr_text": ocr}


# --------------------------------------------------------------- card

def test_the_picture_is_read_at_all():
    """It never was. This is the whole gap."""
    got = parse_flow_card(TELUGU_28_AUG)
    assert got == {"fii_cr": -298.26, "dii_cr": 4977.17}


def test_the_card_reaches_the_normal_entry_point():
    """parse_flow_message is what every caller uses. The card must be
    reachable through it, not only through its own function.

    This is where it broke the first time: the OCR contains "FIl" and
    "DIl", so _PARTY finds hits and the early card check never fires.
    Every hit then fails the buyers/sellers test and it returned None
    while looking like it had tried."""
    assert parse_flow_message(TELUGU_28_AUG) == {"fii_cr": -298.26,
                                                 "dii_cr": 4977.17}


def test_cash_is_not_confused_with_derivatives():
    """The same card carries FII Index Future and FII Stock Future
    immediately below. Those are not cash flows and reading one as the
    other would be silent and completely wrong."""
    got = parse_flow_card(TELUGU_28_AUG)
    for wrong in (-1871.04, -1714.67, 6885.99, -641.97):
        assert got["fii_cr"] != wrong
        assert got["dii_cr"] != wrong


def test_the_sign_comes_from_the_minus_not_the_arrow():
    """The coloured arrows OCR as ~ a A y > « 4 ¥ -- unusable. Every
    stored card carries a real minus on every negative figure, and a
    sign error here would make a heavy selling day read as a heavy
    buying one."""
    got = parse_flow_card(TELUGU_28_AUG)
    assert got["fii_cr"] < 0            # "~ -298.26", down arrow
    assert got["dii_cr"] > 0            # "a 4977.17", up arrow


def test_prose_still_parses():
    """The card path must not have cost the typed one."""
    assert parse_flow_message(NEWS_PULSE) == {"fii_cr": -5039.80,
                                              "dii_cr": 5183.93}


# ------------------------------------------------------- which one wins

def test_typed_beats_photographed():
    """Both sources present, and they disagree by a factor of ten. The
    typed one is the answer."""
    got = from_telegram(_Feed([
        _row("Day Trader Telugu", "2026-08-31T02:29:08+00:00",
             ocr=TELUGU_BAD_OCR),
        _row("News Pulse", "2026-08-30T14:12:50+00:00", text=NEWS_PULSE),
    ]))
    assert got["fii_cr"] == -5039.80
    assert got["source"] == "News Pulse"
    assert got["via"] == "text"


def test_the_disagreement_is_not_swallowed():
    """Silently preferring one source would hide a broken OCR for as
    long as it kept happening."""
    got = from_telegram(_Feed([
        _row("Day Trader Telugu", "2026-08-31T02:29:08+00:00",
             ocr=TELUGU_BAD_OCR),
        _row("News Pulse", "2026-08-30T14:12:50+00:00", text=NEWS_PULSE),
    ]))
    assert got.get("disagrees_with_image") is True


def test_the_picture_is_used_when_it_is_all_there_is():
    """It arrives before the market opens, most mornings, and is often
    the only figure for hours. Refusing it would leave the panel blank
    exactly when it is wanted."""
    got = from_telegram(_Feed([
        _row("Day Trader Telugu", "2026-08-28T02:27:21+00:00",
             ocr=TELUGU_28_AUG),
    ]))
    assert got["fii_cr"] == -298.26
    assert got["via"] == "image"


def test_agreement_is_not_reported_as_a_disagreement():
    agreeing = TELUGU_28_AUG
    prose = ("FIIs were net sellers of Rs 298.26 Cr while DIIs were "
             "net buyers of Rs 4,977.17 Cr")
    got = from_telegram(_Feed([
        _row("Day Trader Telugu", "2026-08-28T02:27:21+00:00", ocr=agreeing),
        _row("News Pulse", "2026-08-28T14:12:50+00:00", text=prose),
    ]))
    assert "disagrees_with_image" not in got


def test_nothing_found_is_still_none():
    """None must stay distinct from zero. Nobody has ever seen a
    session with exactly zero FII flow."""
    assert from_telegram(_Feed([_row("News Pulse", "x", text="good morning")])) is None
