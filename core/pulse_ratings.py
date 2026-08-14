"""
==========================================================
The publisher's own rating system, as the publisher defines it
==========================================================

    "GUIDE = how the grading of results are categorized . this is the
     original guide on how to understand & use the results card. first
     u need to understand this guide total -4 pages with complete
     information on how to understand & what details we will get from
     which channel. so u make a rule in bot to understand accurately.."
                                -- operator, 6 August 2026

WHY THIS EXISTS
---------------
core/result_read.py scores results with weights I invented -- W_BEAT
3.0, W_YOY 2.0, and so on. They are my judgement, they are untested,
and on 6 August they produced a chip he had to argue me out of.

EarningsPulse publishes a four-page guide defining exactly what each
of its ratings means, what values each one can take, and -- most
importantly -- how to read them when they DISAGREE. That is not a
heuristic to be approximated. It is the definition of the data, from
the people who produce it, and the operator pays for it.

So the taxonomy below is TRANSCRIBED, not designed. Where the guide
gives a reading, that reading is used verbatim. Nothing here invents a
rule the guide does not state.

THE NINE RATINGS (Guide 02 -- "Each rating answers a different
investment question")

    Pre-Earnings Sentiment   Bullish / Neutral / Bearish
    Pulse                    Excellent / Great / Good / OK / Weak
    Earnings Verdict         Beat / Met / Mixed / Miss
    Consensus Rating         Strong Beat / Beat / Inline / Miss /
                             Strong Miss
    Brief Quality            Excellent / Great / Good / OK / Weak
    Forensic Quality         Clean / Cost-led / One-off / Low Quality
    TechnoFunda              Exceptional / Strong / Mixed / Weak
    Post-Earnings Sentiment  Positive / Mixed / Negative
    Broker Ratings           analyst actions, counts, revised targets

WHY THE DISTINCTION MATTERS (Guide 03)
--------------------------------------
Pulse and Consensus are NOT the same question, and this is exactly
what I got wrong on MOTHERSON:

    Pulse      "How strong was the quarter compared with the company's
                own historical growth and trajectory?"
    Consensus  "How did actual results compare with published analyst
                estimates?"

MOTHERSON printed Pulse: Weak with every consensus line beating. The
bot called it AVOID. The guide has a name for that exact combination
and it is not AVOID -- it is "weak underlying trajectory, but better
than depressed expectations", which is a different statement entirely
and one a trader can act on.

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not trade, score or rank. It reads the ratings out of OCR text
and, where two of them disagree, returns the guide's own words for
what that disagreement means. core/result_read.py consumes it.

Author : H&M Opportunity Trader
Source : EarningsPulse "Pulse Pro Guide" 01-04, supplied 6 Aug 2026
==========================================================
"""

import re

# ---------------------------------------------------------------
# GUIDE 02 -- the ratings, their permitted values, and the question
#             each one answers. Transcribed.
# ---------------------------------------------------------------
RATINGS = {
    "pre_sentiment": {
        "label": "Pre-Earnings Sentiment",
        "values": ("BULLISH", "NEUTRAL", "BEARISH"),
        "question": ("What was the setup and expectation before the "
                     "company reported?"),
    },
    "pulse": {
        "label": "Pulse",
        "values": ("EXCELLENT", "GREAT", "GOOD", "OK", "WEAK"),
        "question": ("How strong was the reported quarter compared with "
                     "the company's historical growth and trajectory?"),
    },
    "verdict": {
        "label": "Earnings Verdict",
        "values": ("BEAT", "MET", "MIXED", "MISS"),
        "question": ("What is the overall conclusion after aggregating "
                     "the important KPI outcomes?"),
    },
    "consensus": {
        "label": "Consensus Rating",
        "values": ("STRONG BEAT", "BEAT", "INLINE", "MISS", "STRONG MISS"),
        "question": ("How did actual results compare with published "
                     "analyst estimates?"),
    },
    "brief_quality": {
        "label": "Brief Quality",
        "values": ("EXCELLENT", "GREAT", "GOOD", "OK", "WEAK"),
        "question": ("How convincing is the underlying earnings "
                     "performance after reviewing the detailed result?"),
    },
    "forensic": {
        "label": "Forensic Quality",
        "values": ("CLEAN", "COST-LED", "ONE-OFF", "LOW QUALITY"),
        "question": ("Are the earnings repeatable, or were they "
                     "influenced by temporary costs, exceptional items "
                     "or accounting effects?"),
    },
    "technofunda": {
        "label": "TechnoFunda",
        "values": ("EXCEPTIONAL", "STRONG", "MIXED", "WEAK"),
        "question": ("Does the fundamental result also present a "
                     "favourable technical or market opportunity?"),
    },
    "post_sentiment": {
        "label": "Post-Earnings Sentiment",
        "values": ("POSITIVE", "MIXED", "NEGATIVE"),
        "question": ("What is the sentiment in news channels and on "
                     "Twitter/X after earnings are declared?"),
    },
}

# ---------------------------------------------------------------
# GUIDE 01 -- which poster carries which rating, and when it lands.
#             This is what lets the bot know a rating is still COMING
#             rather than absent.
# ---------------------------------------------------------------
POSTERS = {
    "pre_sentiment": ("Pro channel, before results", "before"),
    "consensus": ("Pro channel, immediately after results", "at result"),
    "verdict": ("Pro channel at result, presentation and concall stages",
                "at result"),
    "pulse": ("Pro channel, immediately after results", "at result"),
    "brief_quality": ("E360 Pro channel -- Institutional Earnings Brief",
                      "after result"),
    "forensic": ("E360 Pro channel -- Institutional Earnings Brief",
                 "after result"),
    "technofunda": ("Pro channel, generally around the next trading "
                    "session", "next session"),
    "post_sentiment": ("Cockpit web/poster and a separate Pro poster, "
                       "before the next session opens", "next session"),
}

# ---------------------------------------------------------------
# Reading them out of OCR text.
# ---------------------------------------------------------------
# Order matters: the longer name is tried first so "Strong Beat" is
# never read as "Beat", and "Brief Quality" never as "Quality".
_PATTERNS = [
    # "FinAI Rating: Beat" IS the Consensus rating. Guide 01 lists the
    # Premium Result / Consensus poster as "Pro channel, immediately
    # after results -- actual figures versus analyst estimates,
    # including percentage surprises", and that is exactly the card
    # headed "FinAI Rating" with the Est and delta-Est columns.
    # OCR reads the capital I as a lowercase l often enough that both
    # spellings have to be accepted.
    ("consensus", r"(?:Consensus\s*(?:Rating)?|FinA[Il]\s*(?:Rating)?)"
                  r"\s*[:|\-–—]\s*"
                  r"(Strong\s+Beat|Strong\s+Miss|Beat|Inline|In-line|Miss)"),
    ("pre_sentiment", r"Pre-?Earnings\s*Sentiment\s*[:|\-–—]\s*"
                      r"(Bullish|Neutral|Bearish)"
                      r"|expectations?\b[\s\S]{0,60}?"
                      r"\b(Bullish|Bearish|Neutral)\b"),
    ("post_sentiment", r"Post-?Earnings\s*Sentiment\s*[:|\-–—]\s*"
                       r"(Positive|Mixed|Negative)"),
    ("brief_quality", r"Brief\s*Quality\s*[:|\-–—]\s*"
                      r"(Excellent|Great|Good|OK|Weak)"),
    ("forensic", r"(?:Forensic\s*Quality|Earnings\s*Quality)\s*[:|\-–—]?\s*"
                 r"(Clean|Cost-?led|One-?off|Low\s*Quality)"),
    ("technofunda", r"Techno-?Funda\s*[:|\-–—]?\s*"
                    r"(Exceptional|Strong|Mixed|Weak)"),
    ("verdict", r"(?:Earnings\s*)?Verdict\s*[:|\-–—]\s*"
                r"(Strong\s+Beat|Strong\s+Miss|Beat|Met|Mixed|Miss)"),
    ("pulse", r"(?:Algo\s+)?Pulse(?:\s*Rating)?\s*[:|\-–—]\s*"
              r"(Excellent|Great|Good|OK|Weak)"
              r"|\b(Excellent|Great|Good|OK|Weak)\s+Results\b"),
]
_PATTERNS = [(k, re.compile(p, re.I)) for k, p in _PATTERNS]


def _clean(value):
    return re.sub(r"[-\s]+", " ", str(value or "").strip()).upper()


def read_ratings(texts):
    """{rating_key: VALUE} for every rating found in the OCR text.

    `texts` is an iterable of strings -- pass every image and message
    body for one symbol. Only values the guide permits are returned; a
    word the guide does not list is dropped rather than guessed at.
    """
    found = {}
    for text in (texts or []):
        text = str(text or "")
        if not text.strip():
            continue
        for key, pattern in _PATTERNS:
            if key in found:
                continue
            hit = pattern.search(text)
            if not hit:
                continue
            value = next((g for g in hit.groups() if g), None)
            if value is None:
                continue
            value = _clean(value)
            value = {"IN LINE": "INLINE", "COST LED": "COST-LED",
                     "ONE OFF": "ONE-OFF"}.get(value, value)
            if value in RATINGS[key]["values"]:
                found[key] = value
    return found


# ---------------------------------------------------------------
# GUIDE 03 -- "How to read rating divergences". Verbatim.
#
# Each entry is (name, test, the guide's own words). Nothing here is
# my interpretation; the reading column is transcribed from the page.
# ---------------------------------------------------------------
def _is(got, key, *wanted):
    return got.get(key) in wanted


DIVERGENCES = [
    ("Pulse Excellent + Consensus Miss",
     lambda g: _is(g, "pulse", "EXCELLENT")
     and _is(g, "consensus", "MISS", "STRONG MISS"),
     "Strong historical growth, but below elevated market expectations."),

    ("Pulse Weak + Consensus Beat",
     lambda g: _is(g, "pulse", "WEAK")
     and _is(g, "consensus", "BEAT", "STRONG BEAT"),
     "Weak underlying trajectory, but better than depressed "
     "expectations."),

    ("Verdict Beat + Low Quality",
     lambda g: _is(g, "verdict", "BEAT")
     and _is(g, "forensic", "LOW QUALITY", "ONE-OFF"),
     "A headline beat whose earnings may not be repeatable."),

    ("Pre-Earnings Bearish + Verdict Beat + Post Positive",
     lambda g: _is(g, "pre_sentiment", "BEARISH")
     and _is(g, "verdict", "BEAT")
     and _is(g, "post_sentiment", "POSITIVE"),
     "A genuine upside surprise reinforced by positive news and social "
     "sentiment."),

    ("TechnoFunda Strong + Post Negative",
     lambda g: _is(g, "technofunda", "STRONG", "EXCEPTIONAL")
     and _is(g, "post_sentiment", "NEGATIVE"),
     "An attractive setup, but a negative post-result news and social "
     "narrative introduces caution."),

    ("Verdict Miss + Post Positive",
     lambda g: _is(g, "verdict", "MISS")
     and _is(g, "post_sentiment", "POSITIVE"),
     "Despite the miss, post-result coverage may be focusing on "
     "guidance or future recovery."),
]


def divergences(got):
    """[{name, reading}] -- every guide-defined divergence that applies.

    Empty when the ratings agree, or when too few of them have arrived
    for any divergence to be testable. An empty list is NOT a clean
    bill; missing() says what is still outstanding.
    """
    return [{"name": name, "reading": reading}
            for name, test, reading in DIVERGENCES if test(got or {})]


def missing(got):
    """Which ratings have not arrived yet, and where they will come
    from.

    Guide 01 says each poster lands at a different stage -- TechnoFunda
    "generally around the next trading session", Post-Earnings
    Sentiment "before the next session opens". So a rating that is
    absent at 09:30 is usually not missing, it is NOT PUBLISHED YET,
    and treating the two the same is how a bot decides in the dark.
    """
    out = []
    for key, spec in RATINGS.items():
        if key in (got or {}):
            continue
        where, stage = POSTERS.get(key, ("", ""))
        out.append({"rating": spec["label"], "expected_from": where,
                    "stage": stage})
    return out


def read(texts):
    """Everything the guide defines, for one symbol, in one call.

    Returns {"ratings", "divergences", "missing"} -- no score, no
    verdict of its own. What the publisher said, and what the
    publisher's own guide says it means when those sayings conflict.
    """
    got = read_ratings(texts)
    return {"ratings": got,
            "divergences": divergences(got),
            "missing": missing(got)}
