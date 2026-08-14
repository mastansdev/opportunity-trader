"""
==========================================================
Did the market agree? -- the post-earnings sentiment page
==========================================================

    "are we utilizing all what we have from PRO? we get almost every
     details as instant as possible."
                                    -- operator, 1 August 2026

He kept asking. This is the largest single answer, and it is a no.

    52 pages received
   258 stock rows printed on them
     3 events produced

Earnings Pulse publishes "Market Sentiment for <date> Reportings" the
morning after results, in numbered parts. Every row is one company and
carries three things nothing else in the system has:

    1. Adani Enterp. (ADANIENT) Pulse: Weak
       Sentiment: Negative
       Market Reality: During-hours release: Adani Enterprises shares
       slipped 0.44% after reporting a Q1 FY27 consolidated net loss of
       Rs 1,160.23 Cr due to a one-time exceptional settlement charge
       of Rs 2,644 Cr, despite revenue surging 50% YoY to Rs 33,546 Cr.

    PULSE           the publisher's grade of the quarter
    SENTIMENT       whether the MARKET agreed with that grade
    MARKET REALITY  what the price actually did, and why

The PRO page calls this layer "market confirmation and your safety
blanket". It is the only source that says the grade and the tape
DISAGREED -- WAAREEENER above is Pulse Weak, Sentiment Positive, stock
up 79% revenue. A weak grade the market bought is a different trade
from a weak grade the market sold.

WHY 258 ROWS BECAME 3
---------------------
events_from_message() refuses any message naming three or more
companies:

    "A MESSAGE ABOUT THREE COMPANIES IS ABOUT NONE OF THEM."

That rule is right, and it is right for the reason it was written: a
news RECAP pairs the wrong figure with the wrong company. It is wrong
here for exactly the reason the expectations page was -- this is a
TABLE. Every row carries its own symbol, its own grade and its own
sentence, and reading it row by row cannot cross-contaminate.

This is the second time the same rule has eaten a structured page.
The first cost 23 expectations before anyone noticed. This one cost
258.

IT ALSO CARRIES THE TIMING
--------------------------
"During-hours release" or "After-hours release" on every row -- which
is the answer to the 88%-after-12:30 problem, per company, in the
publisher's own words rather than inferred from a timestamp.

Author : H&M Opportunity Trader
==========================================================
"""

import re

PAGE_HEADER = re.compile(
    r"MARKET\s+SENTIMENT\s+FOR\s+.{0,40}?REPORTING", re.I)

# "1. Adani Enterp. (ADANIENT) Pulse: Weak"
#
# The ticker is the LAST bracketed group before "Pulse", because the
# printed name carries its own brackets often enough to matter --
# "Go Fashion (I) (GOCOLORS) Pulse: Weak". Taking the first would file
# that row against "I".
_ROW = re.compile(
    r"^\s*\d{1,3}\s*[.)]\s*(?P<name>.+?)"
    r"\((?P<sym>[A-Z][A-Z0-9_&.\-]{1,19})\)\s*"
    r"Pulse\s*[:;.]?\s*(?P<pulse>[A-Za-z]+)",
    re.M)

# OCR returns the label as "Sentiment:", "Sentiment;", "'Sentiment:"
# and "‘Sentiment :". The colon is the least reliable character on the
# page, so it is optional.
_SENTIMENT = re.compile(r"Sentiment\s*[:;.]?\s*([A-Za-z]+)", re.I)
_REALITY = re.compile(r"Market\s+Realit[yi]\s*[:;.]?\s*(.+)", re.I | re.S)
_WHEN = re.compile(r"(During|After|Before)[\s-]*hours?\s*release", re.I)

_PULSE_WORDS = {"EXCELLENT", "GREAT", "GOOD", "OK", "FAIR", "MIXED",
                "WEAK", "POOR"}
_SENTIMENT_WORDS = {"POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL", "FLAT"}


def is_sentiment_page(text):
    """True when this message is a Market Sentiment page."""
    return bool(text) and bool(PAGE_HEADER.search(str(text)))


def _clean(block):
    """One paragraph of prose from however OCR broke the lines."""
    out = " ".join(part.strip() for part in str(block).splitlines())
    out = re.sub(r"\s{2,}", " ", out)
    # Bullet leaders the reader invented for the diamond glyph.
    out = re.sub(r"^\s*[«+•\-*_>]+\s*", "", out)
    # A hyphen the reader left hanging at a line break: "(-\n0.11%)".
    out = re.sub(r"\(\s*-\s+", "(-", out)
    return out.strip(" .;,")


def rows_from_page(text, known=None):
    """Every company row on the page.

    `known` is an optional set of valid NSE symbols. When given, a row
    whose ticker is not in it is DROPPED rather than stored -- the OCR
    on these pages turns "M&M" into "M_M" and there is no honest way to
    guess which company a ticker that does not exist refers to.
    """
    body = str(text or "")
    if not is_sentiment_page(body):
        return []
    if known is not None:
        known = {str(s).upper() for s in known}

    hits = list(_ROW.finditer(body))
    out = []
    for i, hit in enumerate(hits):
        symbol = hit.group("sym").upper().strip(".")
        pulse = hit.group("pulse").upper()
        if pulse not in _PULSE_WORDS:
            # The word after "Pulse:" was not a grade -- the row is
            # damaged, and a grade guessed off a broken line is the
            # thing this project keeps deleting.
            continue
        if known is not None and symbol not in known:
            continue

        # The row runs to the start of the next numbered row.
        end = hits[i + 1].start() if i + 1 < len(hits) else len(body)
        block = body[hit.end():end]

        stance = None
        found = _SENTIMENT.search(block)
        if found and found.group(1).upper() in _SENTIMENT_WORDS:
            stance = found.group(1).upper()

        reality = None
        told = _REALITY.search(block)
        if told:
            reality = _clean(told.group(1))

        when = None
        timing = _WHEN.search(block)
        if timing:
            when = timing.group(1).title() + "-hours"

        out.append({
            "symbol": symbol,
            "name": _clean(hit.group("name")),
            "pulse": pulse,
            "sentiment": stance,
            "reality": reality,
            "released": when,
        })
    return out


# The price move, out of the Market Reality sentence.
#
# THIS IS THE ONLY PLACE THE TAPE SPEAKS. The row's "Sentiment:" label
# is the publisher reading the RESULT, not the price -- proved by AHCL
# on 30 July:
#
#     Pulse: Weak
#     Sentiment: Positive
#     Market Reality: shares FELL 7.4% in profit booking despite Q1
#                     FY27 net profit rising to Rs 4.8 Cr
#
# Sentiment says Positive and the stock fell 7.4%. The first version of
# disagrees() compared the grade against Sentiment and called the
# result "MARKET DISAGREES", which would have told the operator the
# tape bought a stock it sold. Read the number instead.
_MOVE = re.compile(
    r"shares?\s+(?P<dir1>gained|rose|jumped|surged|climbed|advanced|"
    r"fell|slipped|dropped|declined|sank|tumbled)\s+"
    r"(?P<pct1>\d+(?:\.\d+)?)\s*%"
    r"|(?:traded|closed|held)\s+(?:flat|steady)\s*\(\s*"
    r"(?P<sign>[+-])\s*(?P<pct2>\d+(?:\.\d+)?)\s*%\s*\)",
    re.I)

_DOWN_WORDS = {"fell", "slipped", "dropped", "declined", "sank", "tumbled"}


def price_move(row):
    """The stock's own answer, in percent, or None.

    Positive is up. Taken from the Market Reality sentence because
    that is where the publisher prints what actually happened.
    """
    hit = _MOVE.search(str(row.get("reality") or ""))
    if not hit:
        return None
    if hit.group("pct1"):
        value = float(hit.group("pct1"))
        return -value if hit.group("dir1").lower() in _DOWN_WORDS else value
    value = float(hit.group("pct2"))
    return -value if hit.group("sign") == "-" else value


def disagrees(row):
    """True when the PRICE did not confirm the publisher's grade.

    A Weak quarter the tape bought, or a Great quarter it sold. That
    is the one case where the grade alone puts the operator on the
    wrong side, and it is the reason this page is worth reading.

    Judged on the move, never on the Sentiment word -- see _MOVE above
    for why. A move under 0.5% is not an answer, it is noise, and
    dressing it up as one would manufacture a signal out of a flat day.
    """
    move = price_move(row)
    if move is None or abs(move) < 0.5:
        return False
    pulse = (row.get("pulse") or "").upper()
    good = pulse in ("EXCELLENT", "GREAT", "GOOD")
    bad = pulse in ("WEAK", "POOR")
    return (good and move < 0) or (bad and move > 0)


def headline_for(row):
    """The chip line for one row.

    Leads with the disagreement when there is one, because that is the
    thing the operator cannot get anywhere else. Otherwise it states
    the confirmation plainly -- "the market agreed" is still worth
    knowing, it is just not worth shouting.
    """
    pulse = (row.get("pulse") or "").title()
    if not pulse:
        return None
    move = price_move(row)
    shown = f"{move:+.2f}%" if move is not None else None

    if disagrees(row):
        # The grade and the tape point opposite ways. Says which, with
        # the number, so the operator can weigh it himself rather than
        # take the word "disagrees" on trust.
        head = f"TAPE DISAGREED: {pulse} result, stock {shown}"
    elif move is not None and abs(move) >= 0.5:
        head = f"TAPE AGREED: {pulse} result, stock {shown}"
    elif move is not None:
        # Under half a percent is the market not answering.
        head = f"TAPE FLAT: {pulse} result, stock {shown}"
    else:
        head = f"MARKET REACTION: {pulse} result"
    if row.get("released"):
        head += f" ({row['released']})"
    if row.get("reality"):
        head += f" -- {row['reality']}"
    return head[:200]
