"""
==========================================================
Layer 04 -- the audit that overrules the algorithm
==========================================================

    "AI Verdict is what we get on the one page of stock = after
     assessing all AI will create a page & we will get them from
     EARNINGS PRO"
                                    -- operator, 2 August 2026

363 of these were already in the store. The bot had been saving them
for a week and reading only the headline.

WHAT THE CARD IS
----------------
Earnings Pro posts a one-page audit per stock. Its top line carries
TWO ratings, not one:

    Algo Pulse: Weak | Verdict: MET

    Algo Pulse   the algorithm's grade of the quarter -- the same
                 grade the Earnings Pulse card gives
    Verdict      what the AI audit concluded after reading the
                 filing, presentation and concall: MISS, MET or BEAT

THE PAIR IS THE POINT
---------------------
Measured on 281 readable pairs in the store:

    algo    verdict     n
    WEAK    MISS       41    the audit agrees
    WEAK    MET        35    the audit OVERRULES
    WEAK    BEAT       22    the audit OVERRULES
    GOOD    MISS       11    the audit OVERRULES

    70 of 281 -- ONE IN FOUR -- disagree.

VISHNU, Q1 FY27, says it out loud:

    "The algo's 'Weak' rating likely stems from the sequential dip.
     However, given the strong YoY growth across all key metrics
     (Revenue +25%, PAT +23%, EBITDA +30%), my audit finds the
     performance solid and UPGRADES the rating to MET."

57 companies were graded WEAK and cleared by the audit. Under the old
chip the operator saw "PULSE: Weak" and moved on.

WHY THE FIGURES ARE NOT TAKEN FROM THE PICTURE
----------------------------------------------
The card's growth table is full of rupee amounts and OCR destroys the
rupee sign on every one of them. From a real stored card:

    picture says   75,455 Cr    caption says   Rs 5,455 Cr
    picture says   74,423 Cr    caption says   Rs 4,423 Cr

Reading the picture would have filed SHYAMMETL's revenue at seventy-five
thousand crore instead of five thousand -- a 13x error, silently, into
the store. That is the RAYMOND failure exactly.

So the figures come from the CAPTION, which Telegram delivers as real
text with real rupee signs, and the picture is used only for the two
ratings and the theme statuses -- which are words, and survive.

Author : H&M Opportunity Trader
==========================================================
"""

import re

# "Algo Pulse: Weak | Verdict: MET". The pipe comes back as I, l or !
# about a third of the time, so it is optional.
_PAIR = re.compile(
    r"Algo\s*Pulse\s*[:;.]?\s*(?P<algo>[A-Za-z]+)\s*[|!Il\/]*\s*"
    r"Verdict\s*[:;.]?\s*(?P<verdict>[A-Za-z]+)", re.I)

VERDICTS = ("BEAT", "MET", "MISS")
ALGO_GOOD = ("EXCELLENT", "GREAT", "GOOD")
ALGO_BAD = ("WEAK", "POOR")

# "Revenue from Operations   CONCERN   Down 8.5% YoY to Rs 251.8 Cr"
#
# Only the STATUS word is taken. The detail beside it carries rupee
# amounts and is left alone for the reason in the docstring.
_THEME = re.compile(
    r"^\s*(?P<theme>[A-Za-z][A-Za-z ()/&'-]{3,40}?)\s+"
    r"(?P<status>CONCERN|IMPROVING|STABLE|WATCH|NEUTRAL)\b", re.I | re.M)

# The footer marker: whether consensus estimates existed at all.
# "Est X Exp v" -- a BEAT with no estimates is a beat against nothing.
_EST = re.compile(r"\bEst\s*([x×✗v✓√])", re.I)
_EXP = re.compile(r"\bExp\s*([x×✗v✓√])", re.I)
_YES = "v✓√"


def is_verdict_card(text):
    """True when this message is an AI Verdict page."""
    return bool(text) and bool(_PAIR.search(str(text)))


def ratings(text):
    """{algo, verdict} or {} -- both, or neither.

    A verdict without its algo rating cannot be told apart from an
    agreement, and the disagreement is the whole reason to read this.
    """
    hit = _PAIR.search(str(text or ""))
    if not hit:
        return {}
    verdict = hit.group("verdict").upper()
    if verdict not in VERDICTS:
        return {}
    return {"algo": hit.group("algo").upper(), "verdict": verdict}


def overruled(pair):
    """True when the audit contradicts the algorithm's own grade.

    A WEAK quarter the audit cleared, or a GOOD one it failed. An OK
    or MIXED algo rating is not a position, so nothing can contradict
    it -- those return False rather than being forced into a verdict.
    """
    algo = (pair or {}).get("algo", "")
    verdict = (pair or {}).get("verdict", "")
    if verdict not in VERDICTS:
        return False
    if algo in ALGO_GOOD:
        return verdict == "MISS"
    if algo in ALGO_BAD:
        return verdict in ("MET", "BEAT")
    return False


def themes(text):
    """[{theme, status}] from the Tally Against Expectations table."""
    out, seen = [], set()
    for hit in _THEME.finditer(str(text or "")):
        name = " ".join(hit.group("theme").split()).strip(" -")
        status = hit.group("status").upper()
        key = name.upper()
        if len(name) < 4 or key in seen:
            continue
        # The column HEADING is "THEME STATUS DETAILS" -- it matches
        # the row shape and is not a company theme.
        if key in ("THEME", "STATUS", "DETAILS", "METRIC"):
            continue
        seen.add(key)
        out.append({"theme": name, "status": status})
    return out


def tally(rows):
    """{CONCERN: n, IMPROVING: n, ...}"""
    got = {}
    for row in rows or []:
        got[row["status"]] = got.get(row["status"], 0) + 1
    return got


def benchmarked(text):
    """Were there consensus estimates at all?

    The footer prints "Est x Exp v". A BEAT with no estimates behind it
    is a beat against nothing -- the card's own verdict text says so:
    "This is an un-benchmarked result with no consensus estimates, so
    the analysis is based on reported growth."

    Returns True, False, or None when the footer was not readable.
    """
    hit = _EST.search(str(text or ""))
    if not hit:
        return None
    return hit.group(1) in _YES


def summary(text, caption=None):
    """The chip line, or None.

    Leads with the disagreement when there is one, because that is the
    thing no other layer says. `caption` is the Telegram text, which
    carries real rupee signs -- the one-line result summary is taken
    from there and never from the picture.
    """
    pair = ratings(text)
    if not pair:
        return None
    algo, verdict = pair["algo"].title(), pair["verdict"]

    if overruled(pair):
        head = f"AI AUDIT OVERRULES: algo said {algo}, audit says {verdict}"
    else:
        head = f"AI AUDIT {verdict}: algo said {algo}"

    if benchmarked(text) is False:
        # Their own wording. A BEAT nobody set a bar for.
        head += " (no consensus estimates)"

    counts = tally(themes(text))
    if counts.get("CONCERN"):
        head += f" -- {counts['CONCERN']} concern" \
                + ("s" if counts["CONCERN"] > 1 else "")
    if counts.get("IMPROVING"):
        head += f", {counts['IMPROVING']} improving"

    line = _first_line(caption)
    if line:
        head += f" -- {line}"
    return head[:200]


def _first_line(caption):
    """The publisher's own one-line summary, from the CAPTION.

    Skips the hashtag/arrow header line and takes the sentence under
    it. Real text, real rupee signs, nothing OCR has touched.
    """
    body = str(caption or "").strip()
    if not body:
        return None
    for raw in body.splitlines()[1:]:
        line = raw.strip()
        if len(line) < 15 or line.startswith("#") or line.startswith("@"):
            continue
        return line[:110]
    return None
