"""
==========================================================
The recap card -- who reported, and when
==========================================================

    "sorted list of results which will get impacted on monday market"
                                    -- operator, 1 August 2026

He is describing the one thing this card knows that nothing else does.
A result released AFTER 15:30 on Friday has not been priced. The market
was shut. It moves on Monday morning -- which is the early-bird window
he has been asking for since the morning:

    "before the movement i need to trust as early bird not in a over
     crowded place after rally done"

Earnings Pulse posts "EARNINGS PULSE RECAP" every evening at 18:00: a
grid of every company that reported that day, rated EXCELLENT / GREAT /
GOOD / OK / WEAK down the side, and split DURING MARKET / AFTER MARKET
across the top.

    5 cards stored
  193 companies named on them
    0 events produced

Third structured page eaten by the three-company rule, after the
expectations page (23 lost) and the market sentiment pages (258 lost).

WHAT THIS DELIBERATELY REFUSES TO READ
--------------------------------------
THE GRADE. It is on the card and it is not recoverable.

The card is a table, and OCR reads the rating column as a detached
stack at the very top, before the title:

    EXCELLENT
    GREAT
    GOOD
    EARNINGS PULSE RECAP
    29 Jul, 2026
    During Market
    @ APCOTEXIND @ PCBL
    @ VIOHING  DHANBANK
    ...

Three rating words for five rating rows, sitting above the title, with
nothing tying any of them to any company. On one of the five cards only
three of the five ratings survived at all.

Guessing which band a company sits in would put a WEAK company under
EXCELLENT on the panel he clicks BUY from. That is the mismatch rule,
and the grade is already stored properly from the individual brief
cards anyway -- this card would add nothing but risk.

WHAT IT DOES READ, AND WHY THAT IS THE VALUABLE HALF
----------------------------------------------------
The DURING / AFTER split survives cleanly on all five cards, in order,
every time. Everything between "During Market" and "After Market"
reported inside the session. Everything after "After Market" did not.

That is not available anywhere else per company, and it answers the
question the whole 88%-after-12:30 finding raised: which of today's
results has the market NOT yet had a chance to price?

Author : H&M Opportunity Trader
==========================================================
"""

import re
from datetime import date, datetime

# ---- THREE CARDS, ONE SPLIT, 2 August 2026 ----
#
#     "shortly today they will send list of stocks which have results
#      on 03-Aug with same During Markets & After Market (this will get
#      sort out to focus on which stocks we needed = early bird)"
#
# The first version of this module read only the 18:00 recap, which
# looks BACKWARD -- who reported today. Earnings Pulse sends the same
# During / After split on two FORWARD-looking cards as well, and those
# are the ones that answer "what should I be watching tomorrow":
#
#     02:30  TODAY EARNINGS        who reports TODAY
#     14:30  TOMORROW'S CALENDAR   who reports TOMORROW
#     18:00  EARNINGS PULSE RECAP  who reported today
#
# Eight of the two forward cards were already sitting in the store,
# carrying the split, unread. They differ from the recap in the one
# way that matters: a company on the AFTER side has not reported yet,
# so it moves the session AFTER the one the card names.
RECAP, TODAY, TOMORROW = "RECAP", "TODAY", "TOMORROW"

_CARD_KINDS = (
    (RECAP, re.compile(r"EARNINGS\s+PULSE\s+RECAP", re.I)),
    (TOMORROW, re.compile(r"TOMORROW'?S?\s+CALENDAR", re.I)),
    (TODAY, re.compile(r"TODAY\s*'?S?\s*EARNINGS|EARNINGS\s+TODAY", re.I)),
)
# Kept for callers that only ever cared about the recap.
RECAP_HEADER = _CARD_KINDS[0][1]

# "AFTER MARKET HOURS" and "AFTER MARKET" are the same heading; the
# recap drops the word HOURS and the other two keep it.
_DURING = re.compile(r"During\s*Market", re.I)
_AFTER = re.compile(r"After\s*Market", re.I)

# "29 Jul, 2026" on the card, "31 Jul, 2026" in the caption.
_DATE = re.compile(
    r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"[a-z]*\.?,?\s*(\d{4})\b", re.I)
_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}

# A ticker chip. The reader puts "@", "©", "=" and "§" in front of them
# where the company logo was.
_TOKEN = re.compile(r"\b[A-Z][A-Z0-9_&\-]{2,19}\b")

# Words printed ON the card that look like tickers.
_FURNITURE = frozenset({
    "EARNINGS", "PULSE", "RECAP", "DURING", "AFTER", "MARKET", "RATING",
    "EXCELLENT", "GREAT", "GOOD", "WEAK", "MARKETPULSE", "AI",
})

DURING, AFTER = "DURING", "AFTER"
# ---- THE CARD DOES NOT ALWAYS CARRY THE SPLIT. 2 August 2026. ----
#
#     "why this Reports today is not showing stocks?"
#
# The module docstring above claimed all three cards carry the During /
# After split. Counted on every such card in the store, that is false:
#
#     RECAP      6 cards    6 with the split
#     TODAY     12 cards    3 with the split
#     TOMORROW   7 cards    2 with the split
#
# On a busy day the card is a two-column table. On a light one -- and
# 2 August named exactly two companies, PERSISTENT and BIRLACABLE --
# it is a plain list with no columns at all. Ten of the nineteen
# forward cards ever posted were being dropped whole.
#
# Refusing the row was right for the RECAP, where the split decides
# whether the market has already priced the result. It was wrong for
# the forward cards, where the company reporting is a fact on its own
# and the time of day is a detail we simply do not have.
#
#     "do not throw away any information we are receiving"
UNKNOWN = "UNKNOWN"


def card_kind(text):
    """RECAP, TODAY, TOMORROW -- or None if this is not one of them.

    Checked in that order on purpose: the recap card prints the word
    "Market" in both column heads and nothing else, so it cannot be
    confused, while a TOMORROW'S CALENDAR card often carries the words
    "today" elsewhere in its caption.
    """
    body = str(text or "")
    if not body:
        return None
    for kind, pattern in _CARD_KINDS:
        if pattern.search(body):
            return kind
    return None


def is_recap_card(text):
    """True when this message is any of the three During/After cards."""
    return card_kind(text) is not None


def recap_date(text, fallback=None):
    """The session the card is describing."""
    hit = _DATE.search(str(text or ""))
    if hit:
        try:
            return date(int(hit.group(3)),
                        _MONTHS[hit.group(2).lower()[:3]],
                        int(hit.group(1)))
        except (ValueError, KeyError):
            pass
    if isinstance(fallback, datetime):
        return fallback.date()
    # ---- THE STRING THAT IS NOT A DATE. 2 August 2026. ----
    #
    # tools/build_stock_events.py reads `at` straight out of SQLite, so
    # the fallback arrives as "2026-08-02T02:30:10+00:00" and not as a
    # datetime. It went unnoticed while the split-less cards returned
    # no rows at all -- the moment they started returning rows the
    # backfill died on .strftime, which is the third time in this
    # project that a datetime has come back from storage as a string.
    if isinstance(fallback, str):
        try:
            return datetime.fromisoformat(fallback).date()
        except ValueError:
            try:
                return date.fromisoformat(fallback[:10])
            except ValueError:
                return None
    return fallback


def rows_from_card(text, known=None):
    """[{symbol, when}] for every company on the card.

    `when` is DURING or AFTER. The grade is NOT returned -- see the
    module docstring for why it cannot be recovered honestly.

    `known` gates every ticker against the NSE master. Without it this
    returns nothing: the OCR on this card is poor enough that an
    ungated read fills the store with fragments, and a fragment is
    indistinguishable from a real symbol once it is stored.
    """
    body = str(text or "")
    if not is_recap_card(body) or known is None:
        return []
    known = {str(s).upper() for s in known}
    if not known:
        return []

    during = _DURING.search(body)
    after = _AFTER.search(body)
    if not during or not after or after.start() <= during.start():
        # ---- NO COLUMNS ON THE CARD ----
        #
        # For the RECAP this is still a refusal. The split is what says
        # whether the market has already priced the result, and calling
        # a DURING company "not yet priced" would put the operator into
        # a move that finished hours ago.
        #
        # For the two FORWARD cards it is not. "PERSISTENT reports on
        # 02 Aug" is true whether or not the card says what time of
        # day, and dropping it loses the only thing the panel is for.
        if card_kind(body) == RECAP:
            return []
        return _tokens(body, known, UNKNOWN)

    blocks = ((DURING, body[during.end():after.start()]),
              (AFTER, body[after.end():]))
    out, seen = [], set()
    for when, block in blocks:
        for row in _tokens(block, known, when, seen=seen):
            out.append(row)
    return out


def _tokens(block, known, when, seen=None):
    """Every real NSE ticker in one block of card text, once.

    Gated on `known` throughout. The OCR on these cards produces
    BAJAJFINSY for BAJAJFINSV and GMOCTTO for GMDCLTD, and a fragment
    is indistinguishable from a real symbol once it is stored --
    which is the mismatch rule:

        "pls make sure these chips & related stocks are never mis
         matched as they are the one we trust"
    """
    seen = seen if seen is not None else set()
    out = []
    for hit in _TOKEN.finditer(str(block or "").upper()):
        token = hit.group(0)
        if token in _FURNITURE or token in seen or token not in known:
            continue
        seen.add(token)
        out.append({"symbol": token, "when": when})
    return out


# "03 Aug, 2026 - 60 Companies". The card states its own size, and
# that number is the only thing standing between a half-read grid and
# a watchlist that looks complete.
_HOW_MANY = re.compile(r"(\d{1,3})\s+Compan(?:y|ies)", re.I)


def stated_count(text):
    """How many companies the card says it lists, or None.

    ---- THE SILENT FAILURE. 2 August 2026. ----

        "what if i didn't asked you to tell me what our bot will do
         this image? we never know right"

    The 03 August card said 60 Companies. We filed 34, and nine of the
    nineteen DURING names went into the AFTER bucket. Nothing anywhere
    said so -- the panel showed 34 names as though that were the list.

    The card counts itself. Reading that number costs nothing and
    turns "here is your watchlist" into "here is 34 of 60".
    """
    hit = _HOW_MANY.search(str(text or ""))
    if not hit:
        return None
    try:
        value = int(hit.group(1))
    except ValueError:
        return None
    return value if 0 < value < 500 else None


def rows_from_grid(words, known=None):
    """[{symbol, when}] from WORD POSITIONS, for a card that is a grid.

    ---- WHY THE FLAT TRANSCRIPT CANNOT DO THIS ----

    TOMORROW'S CALENDAR is a wall of logos with the ticker printed
    under each. Tesseract walks it column by column, so the DURING
    names end up scattered through the transcript -- some before the
    AFTER heading, some after the FOOTER. Splitting the text on the two
    headings put ESCORTS, CAMS, PARKHOSPS, JAINREC, BLUEJET, ETHOSLTD,
    HUBTOWN, STOVEKRAFT and MOBIKWIK into "after the close" when all
    nine report while the market is open.

    A y-coordinate does not care what order anything was read in. Each
    ticker is bucketed by whether it sits above or below the AFTER
    heading ON THE PAGE.

    Returns [] when there are no positions, when the headings cannot be
    found, or when `known` is missing -- every one of those falls back
    to the old text path rather than guessing.
    """
    if not words or known is None:
        return []
    known = {str(s).upper() for s in known}
    if not known:
        return []

    # The two headings, found BY POSITION -- a word "DURING"/"AFTER"
    # with a word starting "MARKET" on the same line and to its right.
    #
    # The first version of this walked words[i+1:i+4], i.e. it assumed
    # the list was in reading order. That is the exact assumption this
    # whole function exists to escape, and the test caught it: with the
    # word list shuffled it found no headings at all and returned
    # nothing. Adjacency ON THE PAGE, not in the list.
    def heading_y(first):
        best = None
        for w in words:
            if w["text"].strip().upper() != first:
                continue
            line = max(14, w["height"]) * 1.2
            for other in words:
                if other is w:
                    continue
                if not other["text"].strip().upper().startswith("MARKET"):
                    continue
                if abs(other["top"] - w["top"]) > line:
                    continue
                if other["left"] < w["left"]:
                    continue
                if best is None or w["top"] < best:
                    best = w["top"]
                break
        return best

    during_y = heading_y(DURING)
    after_y = heading_y(AFTER)
    if during_y is None or after_y is None or after_y <= during_y:
        return []

    # The footer is not a company list. Everything below it -- the
    # "During/After forecast is based on past behavior" line and the
    # handle underneath -- is dropped by position too.
    footer_y = None
    for i, w in enumerate(words):
        if w["text"].strip().lower().startswith("during/after"):
            footer_y = w["top"]
            break

    out, seen = [], set()
    for w in words:
        token = w["text"].strip().upper().strip(".,:;|")
        if token in _FURNITURE or token in seen or token not in known:
            continue
        if w["top"] < during_y:
            continue                      # title block, above both
        if footer_y is not None and w["top"] > footer_y + 5:
            continue                      # below the small print
        seen.add(token)
        out.append({"symbol": token,
                    "when": AFTER if w["top"] >= after_y else DURING})
    return out


def coverage(text, known=None):
    """How much of the card the reader actually got.

    MEASURED, AND IT IS ABOUT HALF. The 31 July card shows roughly a
    hundred companies and its OCR is 845 characters long. DIVISLAB,
    GAEL and SPORTKING -- all three printed under EXCELLENT / After
    Market -- are not in the text at all. The reader simply missed
    them.

    So this list is a SAMPLE of the day, never the whole day, and the
    panel has to say so. A screen showing 27 after-close names as
    though that were all of them would have the operator plan a
    morning around a list missing half its entries -- the same
    dishonesty the "+N more" note on the Week Ahead card exists to
    prevent.

    Returns (matched, unmatched). `unmatched` counts ticker-shaped
    tokens the reader produced that are not real symbols -- BAJAJFINSY
    for BAJAJFINSV, GMOCTTO for GMDCLTD, GBBROSLTD for LGBBROSLTD.
    Each one is a company on the card that has been lost, so it is a
    floor under how much is missing, not a measure of it.
    """
    body = str(text or "")
    if not is_recap_card(body) or known is None:
        return (0, 0)
    known = {str(s).upper() for s in known}
    matched = unmatched = 0
    for hit in _TOKEN.finditer(body.upper()):
        token = hit.group(0)
        if token in _FURNITURE:
            continue
        if token in known:
            matched += 1
        else:
            unmatched += 1
    return (matched, unmatched)


def headline_for(row, on=None, kind=RECAP):
    """The chip line for one company.

    THE TENSE IS THE WHOLE POINT. The same During/After split means
    three different things depending on which card it came from, and
    getting it wrong would tell the operator a stock is unpriced when
    it has not even reported:

        RECAP     + AFTER   reported last night, market never saw it
                            -> moves at THIS open.  Early bird.
        TODAY     + AFTER   reports after today's close
                            -> moves TOMORROW. Nothing to do today.
        TODAY     + DURING  reports inside today's session
                            -> the one to have on screen now.
        TOMORROW  + *       same as TODAY, one day later.
    """
    when = row.get("when")
    day = on.strftime("%d %b") if on else None
    stamp = f" ({day})" if day else ""

    if kind == RECAP:
        if when == AFTER:
            return f"REPORTED AFTER CLOSE{stamp} -- not yet priced " \
                   f"by the market"[:200]
        return f"REPORTED DURING THE SESSION{stamp}"[:200]

    # Forward-looking cards. These have NOT reported yet.
    if when == AFTER:
        return f"REPORTS AFTER CLOSE{stamp} -- moves the next session"[:200]
    if when == UNKNOWN:
        # The card named the company but printed no columns. Saying
        # DURING here would be inventing the one detail we do not have,
        # and DURING is the side that puts a stock on screen at 09:15.
        return f"REPORTS{stamp} -- the card did not say during or " \
               f"after the close"[:200]
    return f"REPORTS DURING THE SESSION{stamp} -- live today"[:200]
