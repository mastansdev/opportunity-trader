"""
==========================================================
Reading a FORWARDED card without tagging the wrong stock
==========================================================

    "ALL PULSE CHANNEL FOLLOWS THE #STOCKNAME , BUT DAY TRADER TELUGU
     = THEY WILL FORWARD IMAGES FROM DIFFERENT SOURCES . THEY ARE NOT
     OWNERS/CREATOR . WE WILL GET ALL DATA . FII/DII. GOLD, SILVER ,
     STOCKS IN NEWS, EVENTS, REUSLTS CARDS IN THIS CHANNEL. ITS WORTH
     TO CHECK & USE IN BOT . BUT STRICTLY AVOID THIER URL'S"
                                -- operator, 7 August 2026

WHY THIS EXISTS
---------------
Measured on the real store, 7 August. Of seventeen symbol tags on
recent Day Trader Telugu images, eight were wrong, and all eight came
off a single card:

    OCR:    "MARKET INDEXES ... NIFTY SENSEX BANK ~ 78491.26"
    tagged: BAJFINANCE, BAJAJFINSV, ICICIBANK

A market-index summary. No company is the subject of it. The tags
came from scanning the whole image for any recognisable name and
taking every hit -- and an index card naturally lists bank names.

    "pls make sure these chips & related stocks are never mis matched
     as they are the one we trust"

A wrong reason is worse than no reason. No reason makes the ranker
refuse; a wrong one makes it score, and puts a sentence on his screen
that he has no way to know is false.

THE TWO RULES THIS ENFORCES
---------------------------
1. CLASSIFY THE CARD FIRST. An index board, an FII/DII table and a
   gold/silver card have no company subject. They are useful -- they
   say what the market is doing -- but they must never tag a stock.

2. THE SUBJECT SITS IN THE HEADLINE. These forwards are screenshots
   of posts, and the source writes the company FIRST:

       "@REDBOXINDIA  ELECTROSTEEL CASTINGS: Q1 CONS NET PROFIT..."
       "@REDBOXINDIA  HINDALCO INDUSTRIES: CO'S..."
       "@CNBCTV18News #BlueStar wanted a 13% price..."

   A name in the headline is the subject. A name in the body is
   context -- a peer, a customer, an index constituent -- and tagging
   it is how ICICIBANK ended up on an index board.

URLS
----
Stripped, on his instruction and without exception. These are
forwards; the links point at the original poster's site, not at
anything the bot should follow.

Author : H&M Opportunity Trader
==========================================================
"""

import re

# ---------------------------------------------------------------
# 1. WHAT KIND OF CARD IS THIS
# ---------------------------------------------------------------
# Ordered: the first match wins, so the most specific comes first.
# Every pattern was written against a real card in data/telegram.db.
_KINDS = (
    # A board of index levels. The 8 wrong tags on 7 August came from
    # exactly this shape.
    ("INDEX", re.compile(
        r"MARKET\s+INDEX|INDEXES|\bNIFTY\b.{0,40}\bSENSEX\b|"
        r"\bSENSEX\b.{0,40}\bNIFTY\b|BANK\s*NIFTY.{0,30}\d{4,}", re.I | re.S)),

    # Institutional flows -- market-wide, never one stock.
    ("FIIDII", re.compile(
        r"\bFII\b|\bDII\b|FOREIGN\s+INSTITUTIONAL|DOMESTIC\s+INSTITUTIONAL|"
        r"PROVISIONAL\s+CASH", re.I)),

    # Metals and energy.
    ("COMMODITY", re.compile(
        r"\bGOLD\b|\bSILVER\b|\bCRUDE\b|\bBRENT\b|\bMCX\b|BULLION", re.I)),

    # Rates, inflation, policy -- moves sectors, not a single name.
    ("MACRO", re.compile(
        r"\bRBI\b|\bGDP\b|\bCPI\b|\bWPI\b|INFLATION|REPO\s+RATE|"
        r"MONETARY\s+POLICY|POLICY\s+FORUM|ECONOMIC\s+SEC", re.I)),
)

# A company headline: NAME followed by a colon, or a #HashTag near the
# front. Both are how these sources actually write.
#
# ---- A DASH IS A HEADLINE TOO. 7 August 2026. ----
# The colon-only version left 52 of 120 real cards UNKNOWN, and the
# subject was sitting in plain sight on most of them:
#
#     "@blitzkreigm  GODREJ CONSUMER - Good Results; Largely..."
#     "@yatinmota    SBI RESULTS - SOLID INTERNALS Domestic..."
#
# The analysts who write these use a dash where the wire services use
# a colon. Same position, same meaning, and dropping them threw away
# the commentary cards -- which is the half of this channel that
# carries a view rather than a number.
_HEADLINE_COLON = re.compile(
    r"(?:^|[|>–—]|@\w{3,20}\s)\s*"
    r"([A-Z][A-Z&'. ]{1,42}?)\s*[:\-–—]\s", re.M)
_HASHTAG = re.compile(r"#([A-Za-z][A-Za-z0-9&]{2,24})")

# Words that look like a company in caps but are not.
_NOT_A_COMPANY = {
    "MARKET", "MARKETS", "INDEX", "INDEXES", "NIFTY", "SENSEX", "BANK NIFTY",
    "BREAKING", "ALERT", "NEWS", "UPDATE", "EXCLUSIVE", "LIVE", "WATCH",
    "RESULTS", "RESULT", "EARNINGS", "Q1", "Q2", "Q3", "Q4", "FY", "CO SAYS",
    "CO", "SAYS", "MANAGEMENT", "GUIDANCE", "OUTLOOK", "SOURCES", "EDIT",
    "TODAY", "STOCKS IN NEWS", "STOCKS TO WATCH", "TOP NEWS", "BUZZING",
    "INDIA", "GLOBAL", "ECONOMY", "GOVT", "GOVERNMENT", "SEBI", "RBI",
    "DAY TRADER", "TRADER", "TV", "NSE", "BSE",
}

# Their links, stripped on instruction.
_URL = re.compile(r"https?://\S+|www\.\S+|\b[a-z0-9-]+\.(?:com|in|co|net)\b",
                  re.I)


def strip_urls(text):
    """Remove every link. Operator instruction, no exceptions."""
    return _URL.sub(" ", str(text or "")).strip()


def classify(text):
    """What kind of card is this -- INDEX, FIIDII, COMMODITY, MACRO,
    COMPANY or UNKNOWN.

    Only COMPANY may ever carry a stock tag.
    """
    body = strip_urls(text)
    if not body:
        return "UNKNOWN"
    # A card can mention gold AND a company. The company headline is
    # the stronger signal, so it is tested first -- but only when the
    # headline is a real name, not a market word.
    if _subjects(body):
        return "COMPANY"
    for kind, pattern in _KINDS:
        if pattern.search(body):
            return kind
    return "UNKNOWN"


def _clean(name):
    name = re.sub(r"\s+", " ", str(name or "")).strip(" -:|").upper()
    return name


def _subjects(text):
    """The company names in HEADLINE position. Body mentions ignored.

    This is the whole defence against the 7 August mis-tag: a name has
    to be the subject of the card, not merely present on it.
    """
    body = strip_urls(text)
    # Only the front of the card. A screenshot's headline is short and
    # first; a name 600 characters in is commentary.
    head = body[:220]
    found = []

    for match in _HEADLINE_COLON.finditer(head):
        name = _clean(match.group(1))
        # ---- SHORT NAMES ARE REAL NAMES. 7 August 2026. ----
        # A 4-character floor dropped "L&T: CO WINS MAJOR CONTRACT" --
        # one of the largest companies on the exchange. The floor was
        # guarding against OCR noise, but resolve() already does that
        # properly: a name that is not a real NSE symbol produces no
        # symbol at all. Length was the wrong filter.
        if len(name) < 2 or name in _NOT_A_COMPANY:
            continue
        # "NIFTY SENSEX BANK" and friends -- any market word makes it
        # a board, not a subject.
        if any(word in name.split() for word in ("NIFTY", "SENSEX", "INDEX")):
            continue
        found.append(name)

    for match in _HASHTAG.finditer(head):
        name = _clean(match.group(1))
        if len(name) >= 3 and name not in _NOT_A_COMPANY:
            found.append(name)

    # Preserve order, drop repeats.
    out = []
    for name in found:
        if name not in out:
            out.append(name)
    return out


def read(text, resolve=None):
    """{"kind", "subjects", "symbols", "text"} for one forwarded card.

    `resolve` maps a company name to an NSE symbol. Without it the
    names come back unresolved rather than guessed -- a wrong symbol
    is the failure this module exists to prevent.
    """
    body = strip_urls(text)
    kind = classify(body)
    subjects = _subjects(body) if kind == "COMPANY" else []

    symbols = []
    if kind == "COMPANY" and resolve is not None:
        for name in subjects:
            try:
                symbol = resolve(name)
            except Exception:                              # noqa: BLE001
                symbol = None
            if symbol and symbol not in symbols:
                symbols.append(str(symbol).upper())

    return {"kind": kind, "subjects": subjects, "symbols": symbols,
            "text": body}


def may_tag(text):
    """True only when this card is about a specific company.

    The one-line guard for any caller that currently scans a forwarded
    image for names.
    """
    return classify(text) == "COMPANY"
