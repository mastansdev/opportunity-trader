"""
==========================================================
Read the WHOLE card, not the headline
==========================================================

    "i want bot to read all of them , understand and sort the answer
     for me to trade. even i had the data but i can't read all the
     info in milli seconds & conclude right? bot must check all the
     sources recevd & update the chip next to the respective stock"
                                -- operator, 6 August 2026

WHAT WAS WRONG
--------------
core/result_tag.py read four things: a pulse phrase, a coloured dot,
a verdict word, and a substring match on "one-off". Measured on the
real traffic of 6 August 2026:

    images OCR'd from the PRO channels        1,242
    characters of text pulled out         1,497,848
    fields the parser extracted                  68

0.01%. And of 241 stocks that reported, the information sitting in
the images and thrown away was:

    PRE-RESULT EXPECTATION      80 stocks
    QoQ / YoY TABLE             64
    ACTUAL vs ESTIMATE / POLL  142      <- the cleanest signal there is
    MARGINS                    154
    CASH FLOW / QUALITY        104
    SEGMENTS                   115
    BEAR CASE / CAUTION        115
    STRATEGY / NARRATIVE        57

MOTHERSON is the case that showed it. Every number beat -- revenue
+26.5% on estimate, EBITDA +24.1%, PAT +9.2%, PAT owners +101.6% YoY,
quality clean, no flags -- and the chip read AVOID, because one card
carried the phrase "Weak Results". That phrase is a QoQ score against
a seasonal peak. The publisher's own AI card said, in writing, that
the rating was incorrect.

WHAT THIS DOES
--------------
read()  pulls every field the channels actually print, off the OCR
        text of EVERY image received for that symbol, from EVERY
        channel, across the whole arc -- the expectation published
        before the result, the result itself, and the analysis after.

score() turns those fields into ONE chip, with the evidence that
        produced it attached, so the reason is on the screen next to
        the answer and never has to be taken on trust.

THE WEIGHTING, AND WHY
----------------------
    "MADE TO LOOSE SMALL INCASE OF LOSS & WIN BIG ON WINNING STOCKS"

At a one-to-three day horizon a stock moves on the gap between what
was expected and what arrived. So:

    beat / miss against an estimate or a street poll   strongest
    YoY growth                                         strong
    margin direction YoY                               moderate
    earnings quality, distortion and red flags         moderate
    the publisher's own rating phrase                  weak
    QoQ                                                INFORMATIONAL

QoQ CANNOT VETO. It is the single change that would have prevented
the MOTHERSON call, and it is defensible on its own terms: a quarter
against the immediately preceding quarter is a seasonal comparison,
not a performance one, and no Indian retailer, tyre maker or sugar
company is judged on it.

NOTHING HERE LOOKS AT PRICE. This is the quality of the RESULT only.
core/ranker.py decides separately whether the stock is moving, whether
it is liquid enough, and whether he can actually get filled.

Author : H&M Opportunity Trader
==========================================================
"""

import re

EXCELLENT = "EXCELLENT"
GOOD = "GOOD"
WATCH = "WATCH"
AVOID = "AVOID"
# Said out loud rather than guessed at. A stock that reported and was
# never read is a question, not a verdict.
UNREAD = None


# =========================================================
# 1. THE PATTERNS -- every one read off real OCR text
# =========================================================

# "Pulse Rating : Great"   "Algo Pulse: Weak"   "FY27 Pulse Rating : Weak"
_PULSE = re.compile(
    r"(?:Algo\s+)?Pulse\s*Rating\s*:?\s*(Excellent|Great|Good|OK|Weak)"
    r"|Algo\s+Pulse\s*:?\s*(Excellent|Great|Good|OK|Weak)"
    r"|\b(Excellent|Great|Good|OK|Weak)\s+Results\b", re.I)

# "Verdict: BEAT"  "Verdict : MIXED"  "#SYMBOL - Strong Beat"
_VERDICT = re.compile(
    r"Verdict\s*:?\s*(Strong Beat|Strong Miss|Beat|Miss|Inline|Met|Mixed)\b"
    r"|[-–—]\s*(Strong Beat|Strong Miss|Beat|Miss|Inline|Met|Mixed)\b",
    re.I)

# The card published BEFORE the result. "Q1FY27 expectations / Bullish"
# THE VERDICT WORD IS ON ITS OWN LINE. The Earnings Pro card reads
#     TRENT
#     Q1FY27 expectations
#     Bullish
# so a pattern that refuses to cross a newline never sees it, and
# every pre-result expectation came back None.
_EXPECT = re.compile(
    r"expectations?\b[\s\S]{0,60}?\b(Bullish|Bearish|Neutral|Cautious|Mixed)\b"
    r"|\b(Bullish|Bearish|Neutral|Cautious)\b[\s\S]{0,40}?expectations?",
    re.I)

# A metric row in the QoQ/YoY grid.
#   "Sales        3%     17%    35,244  34,309  30,212"
#   "PAT        -31%     77%     1,076   1,562     606"
_ROW = re.compile(
    r"^[^A-Za-z0-9]{0,4}(Sales|Revenue|OP|EBITDA|PAT|Net Profit|Profit|OPM|"
    r"Operating Profit)\b[^\n%]{0,24}?"
    r"([+-]?\d{1,4}(?:\.\d+)?)\s*(%|bps)"
    r"(?:[^\n%]{0,12}?([+-]?\d{1,4}(?:\.\d+)?)\s*(?:%|bps))?",
    re.I | re.M)

# ---- THE GRID IS THE TRUTH. 6 August 2026. ----
#
#     "PAT FOR JUN-26 = 518 & MAR-26 = 413 JUN-25 = 425
#      JUN-26 vs MAR-26 = Quarterly growth
#      JUN-26 vs JUN-25 = YEAR ON YEAR GROWTH.
#      REALLY do i need to Spoon feed you? ... the img itself had all
#      numbers with %'s of growth too"
#
# He is right and the bug was mine. The Earnings Pulse card is a
# GROWTH GRID -- metric, QoQ%, YoY%, and the three absolute quarters:
#
#     Metric   QoQ    YoY   Jun'26  Mar'26  Jun'25
#     Sales    14%    18%    5,755   5,028   4,884
#     OP       22%    33%    1,129     928     848
#     OPM    117bps 226bps   19.6%   18.4%   17.4%
#     PAT      25%    22%      518     413     425
#
# There is NO estimate anywhere on it. The old _VS pattern was allowed
# to wander 26 characters looking for a number and 30 more looking for
# a second, so on TRENT it stitched the chart caption "PAT 0-518.1 Cr"
# to an unrelated 3,417.0 and printed
#
#     "PAT beat estimate by +3.0% (3,518.1 vs 3,417.0)"
#
# on his screen. A comparison that does not exist, against a consensus
# that was never published, off a card whose own footer reads
# "Low Accuracy -- figures pending XBRL reconciliation".
#
# So: read the grid, and DERIVE the growth from the absolutes rather
# than trusting a percentage that OCR may have mangled. Where both are
# present they are cross-checked against each other and a disagreement
# is recorded, not silently resolved.
_GRID = re.compile(
    r"^[^A-Za-z0-9]{0,4}(Sales|Revenue|Other Inc\.?|OP|OPM|EBITDA|PAT|"
    r"Net Profit|EPS|Operating Profit)\b"
    r"((?:[^\n]*?[-+]?[\d,]+(?:\.\d+)?\s*(?:%|bps|Cr)?){2,7})$",
    re.I | re.M)
_CELL = re.compile(r"([-+]?[\d,]+(?:\.\d+)?)\s*(%|bps)?")

# An estimate or poll comparison -- ONLY when the words sit right next
# to the numbers. No wandering.
_VS = re.compile(
    r"(Revenue|Sales|EBITDA|PAT|Net Profit|Profit)\s*"
    r"(?:At\s+)?[₹Rs.\s]{0,3}([\d,]+(?:\.\d+)?)\s*(?:Cr|crore)?\s*"
    r"\b(?:vs|v/s|Vs|VS)\b\s*"
    r"(?:[A-Za-z0-9\-]{0,14}\s+){0,2}"
    r"(?:est\.?|estimate[sd]?|poll\s*(?:of)?|street|consensus|expected)"
    r"\s*[₹Rs.\s]{0,3}([\d,]+(?:\.\d+)?)",
    re.I)

# ---- THE TALLY TABLE. The cleanest estimate source there is. ----
#
#     "Consolidated Revenue  MISS  Reported %5,754.7 Cr vs. Est. 5,833.1 Cr"
#     "Standalone EBITDA     BEAT  Calculated %1,140.7 Cr vs. Est. 71,014.2 Cr"
#     "Standalone PAT        BEAT  Reported %531.8 Cr vs. Est. 3499.7 Cr"
#
# Theme, status and both numbers on one line, published by the channel's
# own AI. Nothing has to be inferred.
_TALLY = re.compile(
    r"^[^A-Za-z]{0,4}((?:Standalone|Consolidated)\s+[A-Za-z ]{3,32}?)\s+"
    r"(BEAT|MISS|MET|INLINE|IN-LINE)\s+"
    r"(?:Reported|Calculated|EBITDA|Press release reported[^\d%¥$₹=*]{0,40})?"
    r"[^\d]{0,14}?([\d,]+(?:\.\d+)?)\s*(?:Cr|%)?"
    r"[^\n]{0,20}?(?:vs\.?|v/s)[^\n]{0,12}?(?:Est\.?|estimate|consensus)"
    r"[^\d]{0,6}?([\d,]+(?:\.\d+)?)",
    re.I | re.M)

# ---- THE RUPEE SIGN IS BEING OCR'd AS A DIGIT. 6 August 2026. ----
#
# Every one of these is the same number, "Rs 917.5 Cr", off the same
# card on the same day:
#
#     "vs. Est. 3917.5 Cr"        "vs. Est. $917.5 Cr"
#     "%1,149.0 Cr"               "71,014.2 Cr"
#     "34,761 Cr"                 "=5,666 Cr"        "2623 Cr"
#
# So the OCR is reading the TEXT well and mangling the CURRENCY GLYPH
# into the value. That is how "PAT beat estimate (3,518.1 vs 3,417.0)"
# reached his screen. Symbols are stripped outright; a glued leading
# DIGIT can only be detected by arithmetic, so it is undone only when
# the pair is otherwise impossible.
_GLYPH = re.compile(r"^[%¥$₹=*~^\s]+")


def _money(raw, partner=None):
    """A rupee figure with the OCR's currency damage undone.

    `partner` is the number it is being compared against. A quarterly
    estimate and a quarterly actual are within a factor of three of
    each other in every real case; when they are not, a leading digit
    was a rupee sign, and dropping it is checked before it is trusted.
    """
    text = _GLYPH.sub("", str(raw or "").strip())
    value = _num(text)
    if value is None or partner is None or partner <= 0 or value <= 0:
        return value
    ratio = value / partner
    if 0.33 <= ratio <= 3.0:
        return value
    digits = text.lstrip("0")
    if len(digits) > 1 and digits[0] in "23457":
        retry = _num(digits[1:])
        if retry and 0.33 <= (retry / partner) <= 3.0:
            return retry
    return value


# Every AI grade the channels publish. They run their own models and
# they do not always agree -- TRENT carried "Pulse Rating: Great",
# "FinAI Rating: Beat" and "Algo Pulse: Great | Verdict: MIXED" on the
# same day. All of them are kept; a disagreement is a fact about the
# result, not noise to be averaged away.
_AI_GRADE = re.compile(
    r"(FinAI|FinAl|Algo\s+Pulse|Pulse\s+Rating|Pulse|AI)\s*"
    r"(?:Rating)?\s*[:\-]\s*"
    r"(Excellent|Great|Good|OK|Weak|Beat|Strong Beat|Miss|Strong Miss|"
    r"Mixed|Inline|Met)\b", re.I)

# ---- THE OPERATING METRICS. WHAT ACTUALLY MOVES THE STOCK. ----
#
#     "in trent case the results were good but conviction on future
#      growth expected higher but results agreed but store growth &
#      some business updates not liked by investors as they are not
#      expecting lower mall counts."     -- operator, 6 August 2026
#
# He is describing the whole trade, and the reader had no concept of
# it. TRENT beat on PAT and the stock did not care, because the market
# went in on this, published at 03:58 BEFORE the print:
#
#     "Sustained format expansion across Zudio and Westside drives
#      double-digit revenue and profit growth."
#
# and got this, all of it captured by the bot and none of it scored:
#
#     "Total store footprint reaches 1,312 with 20 net additions"
#     "Like-for-like growth in low single digits"
#     "Growth depends on new, not existing, stores"
#     "Soft organic demand in mature stores"
#     "WEAK INTERNALS - LFL growth for our fashion portfolio"
#
# The P&L is the half of the page the reader could read. The reaction
# comes from the other half.
_OPS = re.compile(
    r"[^\n]{0,80}\b(store[s]?|"
    r"net addition[s]?|footprint|like[- ]for[- ]like|LFL|same[- ]store|"
    r"mall[s]?|order book|capacity|utilisation|utilization|realisation|"
    r"volume[s]?|guidance|outlook|occupancy|subscriber[s]?|AUM|"
    r"own brand[s]?|new store[s]?)\b[^\n]{0,80}", re.I)

# Words that make an operating line a WARNING rather than a boast.
_OPS_BAD = re.compile(
    r"\bsoft\b|\bweak\b|low single digit|declin|de-?grow|slow|muted|"
    r"depends on new|not existing|maturity lag|volatilit|pressure|"
    r"cut|lower|fewer|delay|capex[- ]heavy|drag|miss", re.I)
_OPS_GOOD = re.compile(
    r"\bstrong\b|record|highest|accelerat|expand|expansion|increas|"
    r"improv|robust|ahead of|double[- ]digit|scal(?:e|ing)|added", re.I)

# The publisher's own health warning. It belongs on the chip.
_LOW_ACC = re.compile(r"low\s+accuracy|pending\s+XBRL|verify\s+with\s+"
                      r"official\s+filing", re.I)

# Earnings 360's four judgement panels and the quality words.
_CLEAN = re.compile(r"\b(?:earnings\s+)?quality\s*[:|\-–—]?\s*"
                    r"(clean|good|strong|weak|poor|distorted)\b", re.I)
_NO_FLAGS = re.compile(r"(?:red\s+flags?|distortion[s]?|flags?)\s*:?\s*"
                       r"(?:none|nil|no\b|not\s+flagged|none\s+flagged)", re.I)

# ---- "RED FLAGS" IS A PANEL HEADING, NOT A FLAG. 6 August 2026. ----
#
# The first version matched the words and scored -1.5 on every
# Earnings 360 card, because every one of them prints the panel
# whether or not anything is in it. Both stocks I drove it on came
# back "red flags raised" and only one of them had any:
#
#   MOTHERSON  "&& RED FLAGSNUMERICAL / STRUCTURAL
#               IMPLIED OUTLOOK INFERRED FROM DATA"     <- empty
#   TRENT      "4. RED FLAGS NUMERICAL / STRUCTURAL
#               > Auditor notes non-reviewed
#                 subsidiaries/JVs"                     <- real
#
# So read the BODY of the panel -- everything between the heading and
# the next heading -- and judge that. A heading with nothing under it
# is a clean bill, and is scored as one.
_FLAG_PANEL = re.compile(
    r"RED\s*FLAGS?\s*(?:NUMERICAL|STRUCTURAL|/|\s)*\s*(.{0,260})",
    re.I | re.S)
# The card's other panel titles. The flag body ends where one begins.
_NEXT_PANEL = re.compile(
    r"IMPLIED\s+OUTLOOK|STRATEGY|STORYTYPE|GROWTH\b|MARGINS\b|CASH\s+FLOW|"
    r"QUALITY\b|SEGMENT|SUMMARY|SENTIMENT|SCORECARD|SOURCE|@|X\s", re.I)


def _flags_in(text):
    """True if a red-flag panel has something under it, False if it is
    empty, None if the card carries no such panel."""
    panel = _FLAG_PANEL.search(text or "")
    if not panel:
        return None
    body = panel.group(1)
    cut = _NEXT_PANEL.search(body)
    if cut:
        body = body[:cut.start()]
    if _NO_FLAGS.search(body):
        return False
    # Bullets and letters. Punctuation and OCR noise are not a flag.
    return bool(re.search(r"[A-Za-z]{4,}\s+[A-Za-z]{3,}", body))

# "one-off" is only a negative when it is NOT being denied. The card
# that triggered the MOTHERSON false positive said, in full:
#     "Growth driven by core operations, not one-offs"
#     "One-off items : None flagged"
_ONE_OFF = re.compile(r"one[- ]?offs?|exceptional item|tax credit|"
                      r"deferred tax|other income", re.I)
_ONE_OFF_DENIED = re.compile(
    r"(?:not|no|without|none|nil|excluding|ex[-\s])\s*"
    r"(?:\w+\s+){0,3}?(?:one[- ]?offs?|exceptional|flagged)"
    r"|one[- ]?offs?[^\n]{0,24}?(?:none|nil|not flagged|no\b)", re.I)

_BEAR = re.compile(
    r"weak internals|de-?growth|degrowth|margin (?:compression|contraction)|"
    r"guidance cut|concern[s]?\s*:|slowdown|pressure on|miss(?:ed)? on|"
    r"disappoint|lower than expected|below expectation", re.I)

_SEGMENT = re.compile(r"segment", re.I)
_STRATEGY = re.compile(r"STRATEGY|STORYTYPE|Growth agenda|investor "
                       r"presentation|IN PLAIN LANGUAGE", re.I)

_GREEN, _AMBER, _RED = "\U0001F7E2", "\U0001F7E1", "\U0001F534"

_METRIC = {"SALES": "sales", "REVENUE": "sales",
           "OP": "op", "OPERATING PROFIT": "op", "EBITDA": "op",
           "PAT": "pat", "NET PROFIT": "pat", "PROFIT": "pat",
           "OPM": "opm", "MARGIN": "opm", "EBITDA MARGIN": "opm"}


_ONE_OFF_PANEL = re.compile(
    r"(?:ACCOUNTING\s*[-–—|:]?\s*)?ONE[-\s]?OFFS?\s*[:|]?\s*(.{0,200})",
    re.I | re.S)


def _one_off_in(text):
    """True only when a one-off is actually CLAIMED.

    A heading that says ONE-OFFS with "None" under it is a clean bill,
    and so is "growth driven by core operations, not one-offs".
    """
    text = text or ""
    if not _ONE_OFF.search(text):
        return False
    if _ONE_OFF_DENIED.search(text):
        return False
    panel = _ONE_OFF_PANEL.search(text)
    if panel:
        body = panel.group(1)
        cut = _NEXT_PANEL.search(body)
        if cut:
            body = body[:cut.start()]
        # "> N" is OCR for "None". A body with no real words is empty.
        if not re.search(r"[A-Za-z]{4,}\s+[A-Za-z]{3,}", body):
            return False
        if re.search(r"\b(none|nil|no\b|not\s+flagged)", body, re.I):
            return False
    return True


def _num(text):
    try:
        return float(str(text).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _has_yoy_header(text):
    """Does this card's grid carry a YoY column at all?

    Earnings Pro prints a QoQ-only grid. Reading its single percentage
    as a YoY number would invent growth that was never published --
    the exact class of error that is not allowed here.
    """
    return bool(re.search(r"QoQ[^\n]{0,20}YoY|YoY[^\n]{0,20}QoQ", text, re.I))


# =========================================================
# 2. READ -- every field, from every image, from every channel
# =========================================================

def read(messages):
    """Everything the channels printed about ONE stock.

    `messages` is [(channel, text), ...] -- pass the OCR text of every
    image AND the message body, for every channel, for the whole day.
    Order does not matter; later cards do not silently overwrite
    earlier ones except where a field is genuinely single-valued.

    Every field may be None or empty. A silent source is not a
    negative one -- that rule is unchanged and deliberate.
    """
    out = {
        "pulse": None, "dot": None, "verdict": None, "expectation": None,
        "qoq": {}, "yoy": {},
        "quarters": {},          # {metric: {now, prev, year}} -- absolutes
        "printed_qoq": {}, "printed_yoy": {},   # what the card printed
        "ocr_mismatch": [],      # derived vs printed disagreed
        "low_accuracy": False,   # the card's own health warning
        "beats": [],            # [{metric, actual, est, pct, source}]
        "tally": [],            # [{theme, status, actual, est, pct, source}]
        "ai_grades": [],        # [{by, grade, channel}] -- ALL of them
        "quality": None,        # CLEAN / WEAK / ...
        "flags": None,          # True = red flags raised, False = none
        "one_off": False,
        "bear": [],             # verbatim cautions, deduped
        "operations": [],       # [{text, channel, tone}] -- the other half
        "segments": False, "strategy": False,
        "channels": [], "images": 0, "chars": 0,
    }
    seen_bear, seen_ops = set(), set()

    for channel, text in (messages or []):
        text = str(text or "")
        if not text.strip():
            continue
        out["images"] += 1
        out["chars"] += len(text)
        if channel and channel not in out["channels"]:
            out["channels"].append(channel)

        found = _PULSE.search(text)
        if found:
            out["pulse"] = next(g for g in found.groups() if g).upper()

        found = _VERDICT.search(text)
        if found and out["verdict"] is None:
            out["verdict"] = next(g for g in found.groups() if g).upper()

        found = _EXPECT.search(text)
        if found and out["expectation"] is None:
            out["expectation"] = next(g for g in found.groups() if g).upper()

        if _GREEN in text:
            out["dot"] = "GREEN"
        elif _AMBER in text:
            out["dot"] = "AMBER"
        elif _RED in text:
            out["dot"] = "RED"

        if _LOW_ACC.search(text):
            out["low_accuracy"] = True

        # ---- THE GROWTH GRID, READ AS A GRID ----
        two_columns = _has_yoy_header(text)
        for row in _GRID.finditer(text):
            key = _METRIC.get(row.group(1).upper().strip().rstrip("."))
            if not key:
                continue
            cells = [(_num(v), unit) for v, unit in
                     _CELL.findall(row.group(2)) if _num(v) is not None]
            if not cells:
                continue
            if key == "opm":
                # OPM's row is units all the way across:
                #     OPM   117 bps   226 bps   19.6%   18.4%   17.4%
                # The growth is in bps and the quarters are themselves
                # percentages, so splitting on "has a unit" found no
                # absolutes at all and the margin went unread.
                growth = [v for v, u in cells if u == "bps"]
                absolutes = [v for v, u in cells if u == "%"]
            else:
                growth = [v for v, u in cells if u in ("%", "bps")]
                absolutes = [v for v, u in cells if not u]

            # The three quarters, newest first: Jun'26, Mar'26, Jun'25.
            if len(absolutes) >= 3:
                now, prev, year = absolutes[0], absolutes[1], absolutes[2]
                out["quarters"].setdefault(
                    key, {"now": now, "prev": prev, "year": year})
                # DERIVED, not read. The numbers are on the card; the
                # percentages are just arithmetic on them, and doing the
                # arithmetic is immune to an OCR-mangled percent sign.
                if prev:
                    out["qoq"].setdefault(key, round((now - prev)
                                                     / abs(prev) * 100, 1))
                if year:
                    out["yoy"].setdefault(key, round((now - year)
                                                     / abs(year) * 100, 1))
                # OPM is a percentage already -- its "growth" is the
                # basis-point change, not a percent change.
                if key == "opm":
                    out["qoq"][key] = round((now - prev) * 100, 0)
                    out["yoy"][key] = round((now - year) * 100, 0)

            # The printed percentages, kept separately and checked.
            if len(growth) >= 2 and two_columns:
                out["printed_qoq"].setdefault(key, growth[0])
                out["printed_yoy"].setdefault(key, growth[1])
            elif len(growth) == 1:
                out["printed_qoq"].setdefault(key, growth[0])

            # Fall back to the printed numbers only when the absolutes
            # were not readable.
            if len(absolutes) < 3:
                if two_columns and len(growth) >= 2:
                    out["qoq"].setdefault(key, growth[0])
                    out["yoy"].setdefault(key, growth[1])
                elif growth:
                    out["qoq"].setdefault(key, growth[0])

        # ---- every AI grade the channel published ----
        for hit in _AI_GRADE.finditer(text):
            who = re.sub(r"\s+", " ", hit.group(1).strip().title())
            who = {"Final": "FinAI", "Finai": "FinAI"}.get(who, who)
            grade = hit.group(2).upper()
            if not any(g["by"] == who and g["grade"] == grade
                       for g in out["ai_grades"]):
                out["ai_grades"].append({"by": who, "grade": grade,
                                         "channel": channel})

        # ---- the tally table: theme, status, reported vs estimate ----
        for hit in _TALLY.finditer(text):
            theme = re.sub(r"\s+", " ", hit.group(1).strip())
            status = hit.group(2).upper().replace("IN-LINE", "INLINE")
            actual = _money(hit.group(3))
            est = _money(hit.group(4), partner=actual)
            if actual is None or not est:
                continue
            row = {"theme": theme, "status": status, "actual": actual,
                   "est": est, "pct": round((actual - est) / est * 100, 1),
                   "source": channel}
            # A later card from the same channel SUPERSEDES an earlier
            # one. The 08:28 TRENT card revised the 08:04 card from
            # "broad-based beat" to "bottom-line beat offset by weaker
            # operating margins" and added three MISS rows. Merging the
            # two produced a stock that both beat and missed the same
            # line. Messages arrive oldest-first, so overwrite.
            key = (theme.upper(), channel)
            out["tally"] = [t for t in out["tally"]
                            if (t["theme"].upper(), t["source"]) != key]
            out["tally"].append(row)

        # ---- actual against estimate or poll ----
        for hit in _VS.finditer(text):
            metric = _METRIC.get(hit.group(1).upper().strip())
            actual = _money(hit.group(2))
            est = _money(hit.group(3), partner=actual)
            if not metric or actual is None or not est:
                continue
            pct = round((actual - est) / est * 100.0, 1)
            # An OCR misread can produce a 900% "beat". Anything past
            # +/-60% is not a quarterly surprise, it is a bad read.
            if abs(pct) > 60:
                continue
            if not any(b["metric"] == metric for b in out["beats"]):
                out["beats"].append({"metric": metric, "actual": actual,
                                     "est": est, "pct": pct,
                                     "source": channel})

        found = _CLEAN.search(text)
        if found:
            out["quality"] = found.group(1).upper()
        panel = _flags_in(text)
        if panel is True:
            out["flags"] = True                 # a real one outranks a clean
        elif panel is False and out["flags"] is None:
            out["flags"] = False
        elif panel is None and _NO_FLAGS.search(text) and out["flags"] is None:
            out["flags"] = False

        # Same panel-heading trap as the red flags. Earnings 360 prints
        # "ACCOUNTING - ONE-OFFS" as a section title on every card, and
        # TRENT scored -1.5 for having the heading with "None" under it.
        if _one_off_in(text):
            out["one_off"] = True

        for hit in _BEAR.finditer(text):
            phrase = hit.group(0).strip().lower()
            if phrase not in seen_bear:
                seen_bear.add(phrase)
                out["bear"].append(hit.group(0).strip())

        # ---- the operating half of the page ----
        for hit in _OPS.finditer(text):
            line = " ".join(hit.group(0).split())[:150]
            if len(line) < 14 or line.lower() in seen_ops:
                continue
            seen_ops.add(line.lower())
            bad = bool(_OPS_BAD.search(line))
            good = bool(_OPS_GOOD.search(line))
            out["operations"].append({
                "text": line, "channel": channel,
                "tone": "negative" if bad and not good else
                        "positive" if good and not bad else "neutral"})

        if _SEGMENT.search(text):
            out["segments"] = True
        if _STRATEGY.search(text):
            out["strategy"] = True

    # ---- RECONCILE THE TALLY AGAINST THE GRID. ----
    #
    # When the rupee sign is misread as a digit on BOTH numbers of a
    # pair -- "Reported 3518.1 vs. Est. 3417.0" for Rs 518.1 vs Rs 417
    # -- the ratio between them stays sane and the pair looks fine. It
    # is only wrong against the GRID on the same card, which prints
    # PAT Jun'26 = 518. So the grid is the referee.
    for row in out["tally"]:
        metric = None
        for word, key in _METRIC.items():
            if word in row["theme"].upper():
                metric = key
                break
        truth = (out["quarters"].get(metric) or {}).get("now")
        if not truth or truth <= 0:
            continue
        for field in ("actual", "est"):
            value = row[field]
            if value and value / truth > 1.8:
                stripped = _num(str(value).replace(",", "").replace(".", "", 0)
                                [1:]) if len(str(int(value))) > 1 else None
                text = f"{value:g}".replace(",", "")
                stripped = _num(text[1:]) if len(text.split(".")[0]) > 1 \
                    else None
                if stripped and 0.5 <= stripped / truth <= 2.0:
                    row[field] = stripped
                    row["ocr_fixed"] = True
        if row["est"]:
            row["pct"] = round((row["actual"] - row["est"])
                               / row["est"] * 100, 1)

    # ---- IS THE OCR ACTUALLY RIGHT? CHECK IT AGAINST ITSELF. ----
    #
    #     "OCR working properly? i'm having doubt on that since we
    #      started"                          -- operator, 6 August 2026
    #
    # The card prints both the absolutes and the growth percentages.
    # They are the same fact twice, so they can be used to audit each
    # other: derive the growth from the absolutes and compare it with
    # what was printed. If they disagree, one of the two numbers was
    # misread and this stock's figures are not safe to act on.
    for key, printed in (out["printed_yoy"] or {}).items():
        derived = (out["yoy"] or {}).get(key)
        if derived is None or printed is None:
            continue
        tolerance = 60.0 if key == "opm" else 2.0   # bps vs percent
        if abs(derived - printed) > tolerance:
            out["ocr_mismatch"].append(
                f"{key}: card printed {printed:+.0f}"
                f"{'bps' if key == 'opm' else '%'} YoY, the quarters on the "
                f"same card work out to {derived:+.0f}"
                f"{'bps' if key == 'opm' else '%'}")
    return out


# =========================================================
# 3. SCORE -- one chip, with its reasons attached
# =========================================================

_STRONG = {"EXCELLENT", "GREAT"}
_POSITIVE = {"GOOD"}
_NEGATIVE = {"WEAK"}
_BEAT = {"STRONG BEAT", "BEAT"}
_MISS = {"STRONG MISS", "MISS"}

W_BEAT = 3.0        # actual vs estimate -- the gap that moves price
W_YOY = 2.0         # year on year growth
W_MARGIN = 1.5      # margin direction, YoY
W_QUALITY = 1.5     # clean earnings, no flags
W_PULSE = 1.0       # the publisher's own phrase -- demoted, on purpose
W_BEAR = 1.5        # a named caution from an analyst or the filing
W_ONEOFF = 1.5      # profit that will not repeat
W_OPS = 1.5         # store growth, LFL, order book, guidance

NICE = {"sales": "Revenue", "op": "Operating profit", "pat": "PAT",
        "opm": "Margin"}


def _mixed(fields):
    """Did any channel's AI call the result MIXED?"""
    if (fields.get("verdict") or "").upper() == "MIXED":
        return True
    return any(g["grade"] == "MIXED"
               for g in (fields.get("ai_grades") or []))


def score(fields):
    """{"chip", "score", "why", "against"} -- never a bare word.

    `why` and `against` are the evidence, in plain English, so the
    reason is on the screen beside the answer.
    """
    f = fields or {}
    points, why, against = 0.0, [], []

    # ---- 0. THE TALLY TABLE. The channel's own AI, line by line. ----
    tally = f.get("tally") or []
    beats = sum(1 for t in tally if t["status"] == "BEAT")
    misses = sum(1 for t in tally if t["status"] == "MISS")
    for t in tally:
        line = (f'{t["theme"]} {t["status"].lower()}: '
                f'{t["actual"]:,.1f} vs est {t["est"]:,.1f} '
                f'({t["pct"]:+.1f}%)')
        if t["status"] == "BEAT":
            points += W_BEAT
            why.append(line)
        elif t["status"] == "MISS":
            points -= W_BEAT
            against.append(line)
        else:
            why.append(line)
    if beats and misses:
        # Not a disqualification -- a fact. TRENT beat on PAT and
        # missed on operating EBITDA, and its publisher said exactly
        # that: "bottom-line beat offset by weaker-than-expected
        # operating margins".
        against.append(f"the tally is split -- {beats} beat, "
                       f"{misses} missed")

    # ---- 1. BEAT OR MISS AGAINST AN ESTIMATE. Heaviest. ----
    for b in f.get("beats") or []:
        name = NICE.get(b["metric"], b["metric"])
        if b["pct"] >= 2.0:
            points += W_BEAT
            why.append(f"{name} beat estimate by {b['pct']:+.1f}% "
                       f"({b['actual']:,.1f} vs {b['est']:,.1f})")
        elif b["pct"] <= -2.0:
            points -= W_BEAT
            against.append(f"{name} missed estimate by {b['pct']:+.1f}% "
                           f"({b['actual']:,.1f} vs {b['est']:,.1f})")
        else:
            why.append(f"{name} in line with estimate ({b['pct']:+.1f}%)")

    # ---- 2. YEAR ON YEAR. ----
    yoy = f.get("yoy") or {}
    for key in ("pat", "sales", "op"):
        val = yoy.get(key)
        if val is None:
            continue
        name = NICE.get(key, key)
        if val > 0:
            points += W_YOY * (1.0 if key == "pat" else 0.6)
            why.append(f"{name} {val:+.0f}% YoY")
        else:
            points -= W_YOY * (1.0 if key == "pat" else 0.6)
            against.append(f"{name} {val:+.0f}% YoY")

    # ---- 3. MARGIN DIRECTION, YoY ONLY. ----
    opm = yoy.get("opm")
    if opm is not None:
        if opm > 0:
            points += W_MARGIN
            why.append(f"margin expanded {opm:+.0f} bps YoY")
        else:
            points -= W_MARGIN
            against.append(f"margin contracted {opm:+.0f} bps YoY")

    # ---- 4. EARNINGS QUALITY. ----
    quality = (f.get("quality") or "").upper()
    if quality in ("CLEAN", "GOOD", "STRONG"):
        points += W_QUALITY
        why.append(f"earnings quality {quality.lower()}")
    elif quality in ("WEAK", "POOR", "DISTORTED"):
        points -= W_QUALITY
        against.append(f"earnings quality {quality.lower()}")
    if f.get("flags") is False:
        points += W_QUALITY / 2
        why.append("no red flags raised")
    elif f.get("flags") is True:
        points -= W_QUALITY
        against.append("red flags raised")

    if f.get("one_off"):
        points -= W_ONEOFF
        against.append("profit helped by a one-off")

    # ---- 5. THE PUBLISHER'S OWN WORD. Now worth one point. ----
    pulse = (f.get("pulse") or "").upper() or None
    if pulse in _STRONG:
        points += W_PULSE
        why.append(f"rated {pulse.title()}")
    elif pulse in _POSITIVE:
        points += W_PULSE / 2
        why.append(f"rated {pulse.title()}")
    elif pulse in _NEGATIVE:
        points -= W_PULSE
        against.append(f"rated {pulse.title()} (a QoQ score -- "
                       f"informational, it cannot veto)")

    verdict = (f.get("verdict") or "").upper() or None
    if verdict in _BEAT:
        points += W_PULSE
        why.append(f"verdict {verdict.title()}")
    elif verdict in _MISS:
        points -= W_BEAT
        against.append(f"verdict {verdict.title()}")

    dot = (f.get("dot") or "").upper()
    if dot == "GREEN":
        points += W_PULSE / 2
    elif dot == "RED":
        points -= W_BEAT
        against.append("red light from the publisher")

    # ---- 5b. THE OPERATING METRICS AGAINST THE BAR. ----
    #
    # A clean P&L with a soft operating story is the TRENT case, and it
    # is why a beat can go nowhere. These are weighted to matter but
    # not to overrule a genuine beat, because his horizon is one to
    # three days and the print still sets the direction.
    ops = f.get("operations") or []
    ops_bad = [o for o in ops if o["tone"] == "negative"]
    ops_good = [o for o in ops if o["tone"] == "positive"]
    for o in ops_bad[:4]:
        points -= W_OPS
        against.append(f'operations: "{o["text"]}"')
    for o in ops_good[:3]:
        points += W_OPS / 2
        why.append(f'operations: "{o["text"]}"')
    if ops_bad and (f.get("expectation") or "").upper() == "BULLISH":
        # The street went in expecting growth and the operating
        # detail did not deliver it. That gap is the trade.
        points -= W_OPS
        against.append("the street went in Bullish and the operating "
                       "detail came in softer -- that gap is what the "
                       "stock trades on, not the P&L")

    # ---- 6. A NAMED CAUTION. ----
    for phrase in (f.get("bear") or [])[:3]:
        points -= W_BEAR
        against.append(f'caution: "{phrase}"')

    # ---- 7. WHAT WAS EXPECTED BEFORE THE PRINT. ----
    # Context, not a score of its own -- it only says whether the
    # result had a bar to clear.
    expectation = (f.get("expectation") or "").upper()
    if expectation:
        why.append(f"street went in {expectation.title()}")

    # ---- QoQ IS RECORDED AND NEVER SCORED. ----
    qoq = f.get("qoq") or {}
    if qoq and not (f.get("yoy") or f.get("beats")):
        # Only a QoQ grid arrived. Not enough to grade a result on.
        for key, val in qoq.items():
            why.append(f"{NICE.get(key, key)} {val:+.0f}% QoQ "
                       f"(sequential -- not scored)")

    # ---- THE CHIP ----
    # ---- THE PUBLISHERS' OWN AI GRADES, AND WHETHER THEY AGREE ----
    #
    #     "the pro channels are also using AI to grade the results"
    #                             -- operator, 6 August 2026
    #
    # He is right, and it means their grades are evidence in their own
    # right rather than a headline to be replaced. TRENT carried three
    # on one day -- Great, Beat, and Great|MIXED. They are all kept and
    # a split between them is reported, because a split IS the finding.
    grades = f.get("ai_grades") or []
    if grades:
        shown = ", ".join(f'{g["by"]}: {g["grade"].title()}' for g in grades)
        good = {"EXCELLENT", "GREAT", "BEAT", "STRONG BEAT", "GOOD"}
        bad = {"WEAK", "MISS", "STRONG MISS"}
        votes_good = {g["grade"] for g in grades} & good
        votes_bad = {g["grade"] for g in grades} & bad
        if votes_good and votes_bad:
            against.append(f"the channels' AIs disagree -- {shown}")
        else:
            why.append(f"channel AI grades: {shown}")

    read_anything = bool(f.get("beats") or f.get("tally") or f.get("yoy")
                         or grades or pulse or verdict or quality)
    if not read_anything:
        chip = UNREAD
    elif points >= 6.0 and not (beats and misses) and not _mixed(f):
        chip = EXCELLENT
    elif points >= 6.0:
        # ---- A SPLIT RESULT IS NOT THE TOP GRADE. ----
        # TRENT scored 6.9 with three beats AND three misses, and its
        # own publisher revised the card to "bottom-line beat offset by
        # weaker-than-expected operating margins -- Verdict: MIXED".
        # Calling that EXCELLENT would be the bot overruling the source
        # that did the work.
        chip = GOOD
        against.append("capped below the top grade -- the result is "
                       "split, not clean")
    elif points >= 2.5:
        chip = GOOD
    elif points > -1.0:
        chip = WATCH
    else:
        chip = AVOID

    return {"chip": chip, "score": round(points, 1),
            "why": why, "against": against,
            "images": f.get("images", 0),
            "channels": list(f.get("channels") or [])}


def tag(messages):
    """The whole job in one call: messages in, chip and reasons out."""
    return score(read(messages))
