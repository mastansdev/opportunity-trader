"""
==========================================================
News Bot -- FREE keyword classifier (no API)
==========================================================

A zero-cost stand-in for Stage 3's Claude Haiku classifier
(news_bot/classification.py), 2026-07-24. Returns the exact
same shape -- {direction, confidence, materiality, reason} --
so the rest of the pipeline (tier, queue, dashboard) is
identical whether the classification came from Haiku or from
here.

It reads direction from a hand-built lexicon of bullish /
bearish market phrases. Honest about what it is: cruder than
Haiku (no context understanding -- "profit falls less than
feared" would still read bearish on "profit falls"), so by
default (config.NEWS_KEYWORD_CAN_BLOCK) keyword-classified
news is DISPLAY-ONLY and does NOT block trades. It exists so
the news engine works and is VISIBLE for free until the paid
Haiku classifier is switched on.

Author : H&M Opportunity Trader
==========================================================
"""

# Strong, material phrases -- these can push an item to HIGH
# (confidence >= 70). Lower-case, matched as substrings on the
# headline+summary.
_BULLISH_STRONG = [
    "wins order", "bags order", "bags contract", "wins contract",
    "order worth", "order win", "secures order", "new order",
    "profit rises", "profit jumps", "profit surges", "profit up",
    "net profit up", "record profit", "beats estimate", "beats estimates",
    "upgrade", "upgraded to buy", "raised to buy", "rating raised",
    "acquisition", "acquires", "to acquire", "buyback", "bonus issue",
    "record date", "stake buy", "fund raising", "qip", "capex",
    "new plant", "expansion", "wins approval", "usfda approval",
    "approval granted", "dividend", "strong results", "revenue jumps",
    "multi-year high", "record high", "life high", "block deal buy",
]
_BEARISH_STRONG = [
    "fraud", "scam", "probe", "investigation", "raid", "searches",
    "penalty", "fine imposed", "downgrade", "downgraded", "cut to sell",
    "rating cut", "profit falls", "profit drops", "profit declines",
    "net loss", "posts loss", "widens loss", "misses estimate",
    "misses estimates", "resigns", "resignation", "steps down",
    "default", "insolvency", "nclt", "bankruptcy", "sebi bars",
    "sebi order", "ed summons", "cbi", "income tax", "gst notice",
    "recall", "ban", "banned", "guidance cut", "stake sale",
    "block deal sell", "pledge", "auditor resigns", "qualified opinion",
    "downgrades", "weak results", "revenue falls",
]

# Softer terms -- contribute to direction but keep it MID (never
# strong enough on their own to block a trade even if that were on).
_BULLISH_SOFT = [
    "gains", "rises", "jumps", "surges", "rallies", "outperform",
    "positive", "growth", "higher", "expands", "partnership", "deal",
]
_BEARISH_SOFT = [
    "falls", "slips", "declines", "drops", "underperform", "negative",
    "concern", "concerns", "lower", "warning", "weak", "cut", "slump",
]


import re


def _compile(terms):
    """Precompile each lexicon term as a WHOLE-WORD / whole-phrase
    pattern. This is the fix for the substring bug found live
    2026-07-24: plain `term in text` matched 'ban' inside 'Bank'
    (and 'cut' inside 'circuit', 'gains' inside 'bargains'), which
    stamped bearish HIGH signals onto 8 unrelated banks off one
    "UAE Bank Partners" headline. The lookarounds require an
    alphanumeric boundary on both sides, so 'ban' only matches the
    standalone word 'ban' (e.g. 'export ban'), never 'Bank'."""
    return [
        (t, re.compile(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])"))
        for t in terms
    ]


_BULLISH_STRONG_C = _compile(_BULLISH_STRONG)
_BEARISH_STRONG_C = _compile(_BEARISH_STRONG)
_BULLISH_SOFT_C = _compile(_BULLISH_SOFT)
_BEARISH_SOFT_C = _compile(_BEARISH_SOFT)


def _count_hits(text, compiled_terms):
    return [term for term, pattern in compiled_terms if pattern.search(text)]


def classify(item, company=None):
    """
    Free lexicon classifier. `company` is accepted for signature
    parity with classification.classify() but not used. Returns
    {direction, confidence, materiality, reason, classifier}.
    """
    text = f"{item.title} {item.summary}".lower()

    bull_strong = _count_hits(text, _BULLISH_STRONG_C)
    bear_strong = _count_hits(text, _BEARISH_STRONG_C)
    bull_soft = _count_hits(text, _BULLISH_SOFT_C)
    bear_soft = _count_hits(text, _BEARISH_SOFT_C)

    bull_score = 2 * len(bull_strong) + len(bull_soft)
    bear_score = 2 * len(bear_strong) + len(bear_soft)

    if bull_score == bear_score:
        direction = "neutral"
    elif bull_score > bear_score:
        direction = "bullish"
    else:
        direction = "bearish"

    has_strong = bool(bull_strong or bear_strong)
    materiality = "material" if has_strong else "routine"

    # Confidence: only a STRONG, one-sided signal earns >= 70 (the
    # HIGH bar). A mixed or soft-only signal stays MID.
    if direction == "neutral":
        confidence = 40
    elif has_strong and not (bull_strong and bear_strong):
        confidence = 80
    elif has_strong:
        confidence = 60   # strong terms on BOTH sides -> ambiguous
    else:
        confidence = 55

    hits = (bull_strong + bear_strong) or (bull_soft + bear_soft)
    reason = (
        f"keyword match: {', '.join(hits[:3])}" if hits
        else "no directional keywords"
    )

    return {
        "direction": direction,
        "confidence": confidence,
        "materiality": materiality,
        "reason": reason,
        "classifier": "keyword",
    }
