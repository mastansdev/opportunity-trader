"""
==========================================================
Major events -- the only news worth a line on the trading screen
==========================================================

Operator, 2026-07-26:

    "it must display intraday news, announcements, results, any other
     major events/news not all other mid news. that too on top of this
     display only recent one with stockname news direction time"

So this module answers one question: **is this headline a MAJOR event,
and which kind?** Everything that is not gets no row.

WHY A SEPARATE LIST FROM THE ROUTINE FILTER
news_bot/matching.py's is_routine_filing() already drops obvious
housekeeping -- trading windows, director appointments, newspaper
copies. What survives that is still a mixed bag: a credit-rating
reaffirmation and a factory fire both get through, and only one of them
belongs on a trading screen.

This is the positive list. Rather than "not obviously junk", a headline
must actively look like one of the things that moves a share price:

    RESULTS      quarterly / annual numbers
    ORDER        contract wins, LOIs, order-book additions
    M&A          acquisitions, mergers, stake sales, demergers
    FUNDRAISE    QIP, preferential issue, NCDs, rights
    CAPITAL      split, bonus, buyback
    APPROVAL     USFDA, regulatory clearance, patents, licences
    RATING       credit-rating changes
    LEGAL        SEBI action, penalties, investigations, tax demands
    DISRUPTION   fire, strike, lockout, accident, plant shutdown
    DISTRESS     default, insolvency, NCLT, resolution plan
    GUIDANCE     outlook and forecast changes

Order matters: the list is checked top-down and the first hit wins, so
"Board approves acquisition funded by QIP" reads as M&A, not FUNDRAISE.

NO DIRECTION IS DECIDED HERE. This says WHAT happened, never whether it
is good or bad -- that is exactly the judgement the keyword classifier
proved unable to make ("Tax Deduction on Dividend" -> bullish 80%).
Direction comes from whatever classifier ran, and while that is the free
lexicon the screen shows it for information only.

Author : H&M Opportunity Trader
==========================================================
"""

# (event type, markers). First match wins -- see the note above.
_EVENT_RULES = (
    ("RESULTS", (
        "FINANCIAL RESULT", "QUARTERLY RESULT", "AUDITED RESULT",
        "UNAUDITED RESULT", "Q1 RESULT", "Q2 RESULT", "Q3 RESULT",
        "Q4 RESULT", "FINANCIAL STATEMENT", "EARNINGS",
    )),
    ("M&A", (
        "ACQUISITION", "ACQUIRE", "MERGER", "AMALGAMATION", "DEMERGER",
        "SCHEME OF ARRANGEMENT", "STAKE SALE", "DIVESTMENT", "DIVEST",
        "SLUMP SALE", "JOINT VENTURE", "OPEN OFFER", "TAKEOVER",
    )),
    ("ORDER", (
        "BAGGING", "BAGGED", "ORDER WIN", "WINS ORDER", "NEW ORDER",
        "WORK ORDER", "LETTER OF INTENT", "LETTER OF AWARD", "CONTRACT",
        "ORDER BOOK", "AWARDED",
    )),
    ("FUNDRAISE", (
        "FUND RAISING", "FUND RAISE", "QIP", "QUALIFIED INSTITUTIONAL",
        "PREFERENTIAL ISSUE", "PREFERENTIAL ALLOTMENT",
        "NON-CONVERTIBLE DEBENTURE", "RIGHTS ISSUE", "DEBENTURE",
        "RAISING OF FUNDS",
    )),
    ("CAPITAL", (
        "STOCK SPLIT", "SUB-DIVISION", "SUBDIVISION", "BONUS ISSUE",
        "BONUS SHARE", "BUYBACK", "BUY BACK", "FACE VALUE SPLIT",
    )),
    ("APPROVAL", (
        "USFDA", "US FDA", "FDA APPROVAL", "DRUG APPROVAL", "APPROVAL FOR",
        "RECEIVES APPROVAL", "PATENT", "LICENCE", "LICENSE GRANTED",
        "CDSCO", "EU GMP", "CERTIFICATION",
    )),
    ("RATING", (
        "CREDIT RATING", "RATING UPGRADE", "RATING DOWNGRADE",
        "REVISION IN RATING", "ICRA", "CRISIL RATING", "CARE RATINGS",
    )),
    ("LEGAL", (
        "SEBI", "PENALTY", "SHOW CAUSE", "INVESTIGATION", "FRAUD",
        "TAX DEMAND", "GST DEMAND", "INCOME TAX", "SEARCH AND SEIZURE",
        "LITIGATION", "COURT ORDER", "TRIBUNAL", "FRONT-RUNNING",
    )),
    ("DISRUPTION", (
        "FIRE", "STRIKE", "LOCKOUT", "LOCK-OUT", "SHUTDOWN", "SHUT DOWN",
        "ACCIDENT", "FORCE MAJEURE", "DISRUPTION", "PLANT CLOSURE",
        "SUSPENSION OF OPERATIONS", "BLAST", "EXPLOSION",
    )),
    ("DISTRESS", (
        "DEFAULT", "INSOLVENCY", "NCLT", "RESOLUTION PLAN",
        "BANKRUPTCY", "WINDING UP", "ONE-TIME SETTLEMENT",
    )),
    ("GUIDANCE", (
        "GUIDANCE", "OUTLOOK REVISED", "PROFIT WARNING",
        "REVISES FORECAST",
    )),
)

# Every type this module can return, in the order it checks them.
EVENT_TYPES = tuple(name for name, _ in _EVENT_RULES)


def classify_event(text):
    """
    Returns the event type ("RESULTS", "ORDER", ...) or None when the
    headline is not a major event.

    Deliberately says nothing about direction -- see the module note.
    """
    upper = str(text or "").upper()
    if not upper.strip():
        return None
    for name, markers in _EVENT_RULES:
        if any(marker in upper for marker in markers):
            return name
    return None


def is_major_event(text):
    return classify_event(text) is not None
