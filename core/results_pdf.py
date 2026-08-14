"""
==========================================================
Read the numbers out of a results PDF
==========================================================

WHY THIS IS THE RIGHT SOURCE, AND THE OTHER TWO ARE NOT
--------------------------------------------------------
Three ways to learn what a company just reported, measured 2026-07-27:

  1. The ANNOUNCEMENT TEXT. Carries no figures at all. Seven real
     filings that evening -- BEL, TATAPOWER, SAGCEM, NORTHARC,
     KANPRPLA, TOKYOPLAST, BKMINDST -- each had 109 to 168 characters
     of boilerplate: "X Limited has submitted to the Exchange, the
     financial results for the period ended Jun 30, 2026." Nothing else.

  2. bse.resultsSnapshot(). LAGS, and is short. TMB reported that day
     and the snapshot still showed Mar-26 as its latest quarter while
     its own period_links already said Jun-26. It returns two quarters
     plus a full year -- enough for QoQ, never enough for YoY.

  3. THE PDF ATTACHED TO THE FILING. Everything, immediately:

        MOLD-TEK PACKAGING, filed 2026-07-27, in lakhs
                                 30-Jun-2026  31-Mar-2026  30-Jun-2025
        Revenue from operations     30045.20     23785.56     24055.84
        Profit for the period        2557.11      2064.06      2239.67
        EPS Basic                        7.70         6.21         6.74

     Current quarter, previous quarter AND the year-ago quarter, so QoQ
     and YoY both fall out at once. Full precision. Same minute as the
     filing. Cross-checks exactly against the operator's own earnings-
     pulse card: Rs 300.45cr / 237.86cr / 240.56cr.

WHAT MAKES THIS HARD
--------------------
These are scanned or generated PDFs and the text layer is dirty. From
that same real file:

    "248,03"     a comma where a decimal point belongs
    "166159"     1661.59 with the point lost entirely
    "(140.77)"   parentheses meaning negative, not brackets
    "2) Current tax"   OCR read "a)" as "2)"
    "31-Mar-2026" appears TWICE -- once as a quarter, once as the
                  YEAR ENDED column, and confusing them would store a
                  full year as a quarter and make the next comparison
                  read as a 73% collapse

So this parser is deliberately conservative: it returns what it is sure
of and None for the rest. A missing figure is recoverable. A wrong one
gets graded, ranked, and acted on.

Author : H&M Opportunity Trader
==========================================================
"""

import re
from datetime import datetime

from core.logger import diagnostic, warn

# Units the statement declares in its header, and the multiplier that
# converts to CRORES -- the unit core/quarterly_results.py stores in.
# The unit line is written a dozen ways, and "in <unit>" adjacent was
# only one of them. Real examples that were missed on 31 July 2026:
#
#     (Amount in Rs. million)          SYRMA
#     (₹ in Lakhs)                     several
#     (Rs. in Crores)
#     r~ In Lakhs1                     VOLTAMP -- a SCAN, OCR noise
#
# Anything between the currency word and the unit is allowed, up to a
# short distance, so "in Rs. million" and "in ₹ lakhs" both land. The
# ORDER still matters: crore before lakh would be wrong for "Rs in
# crores of lakhs", which does not exist, but lakh before million does
# matter because "million" never appears inside "lakh".
#
# Still refuses when it finds nothing. "Refusing to guess -- figures
# would be out by 100x" remains the right answer: a statement read in
# the wrong unit is a grade computed on numbers a hundred times too
# big, which is worse than no grade at all.
_UNIT_NEAR = r"(?:in|of)\b[^)\n]{0,14}?\b"
# (?![a-z]) rather than \b on the tail: a SCANNED filing reads
# "[Rs In Lakhs]" as "r~ In Lakhs1", and \b refuses to close a word
# against a digit. The unit word followed by OCR noise is still that
# unit; the unit word followed by more LETTERS is a different word.
UNIT_PATTERNS = [
    (re.compile(_UNIT_NEAR + r"lakh?s?(?![a-z])", re.I), 0.01),
    (re.compile(_UNIT_NEAR + r"crores?(?![a-z])", re.I), 1.0),
    (re.compile(_UNIT_NEAR + r"million?s?(?![a-z])", re.I), 0.1),
    (re.compile(_UNIT_NEAR + r"thousands?(?![a-z])", re.I), 0.0001),
]

# Line items worth having, and what they are called across filings.
# Ordered: the first pattern that matches a row wins, so the specific
# ones come before the generic.
LINE_ITEMS = [
    ("sales", re.compile(
        r"revenue\s+from\s+operations|net\s+sales|^\s*sales\b", re.I)),
    ("other_income", re.compile(r"other\s+income", re.I)),
    ("total_income", re.compile(r"total\s+(income|revenue)", re.I)),
    ("pat", re.compile(
        r"profit\s*/?\s*\(?loss\)?\s+for\s+the\s+period|"
        r"profit\s+for\s+the\s+(period|year)|net\s+profit", re.I)),
    ("pbt", re.compile(r"profit\s+before\s+tax", re.I)),
    ("eps", re.compile(r"^\s*[-.\s]*basic\b|earnings\s+per\s+.*basic", re.I)),
]

# ---------------------------------------------------------------
# THE DATE IN THE COLUMN HEADER
# ---------------------------------------------------------------
# This used to accept only a THREE-LETTER MONTH NAME:
#
#     (\d{1,2})[-/\s]([A-Za-z]{3})[-/\s](\d{2,4})
#
# 31 July 2026. APTUS reported, the stock fell 5.77%, and the panel
# showed "GOOD: PAT +10% QoQ" -- a grade of the MARCH quarter, because
# today's filing had never been read. The filing was downloaded fine
# and had a clean text layer. Its header said:
#
#     30.06.2026  31.03.2026  30.06.2025  31.03.2026
#
# Numeric month, dot separator. No match, so find_period_columns()
# returned [] and parse_statement() gave up before reading a single
# number. Measured across 30 stored filings: 10 used the named form,
# 6 used ONLY a numeric form and were silently unreadable.
#
# Two patterns now, tried named-first because it is unambiguous.
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun",
           "jul", "aug", "sep", "oct", "nov", "dec")
_MONTH_ALT = "|".join(_MONTHS)

# (?<!\d) ON THE DAY IS NOT OPTIONAL.
#
# The first version of this allowed "[A-Za-z]{3}[A-Za-z]*" so that
# "March" would match as well as "Mar". On a header that reads
#
#     June 30, 2026   March 31, 2026   June 30, 2025
#
# that let the pattern start on the "26" of "2026", swallow " March ",
# and finish on the "31" of the NEXT date -- producing 26 March 2031.
# 25 rows went into the store as Mar-31 and Jun-30 before it was
# noticed. The original three-letter-only pattern was accidentally safe
# here, because "Mar" had to be followed immediately by a separator and
# "March" is not.
#
# So: the day may not be preceded by a digit, and the month must be a
# REAL month rather than any three letters -- which also stops
# "Regulation 33 and 52" parsing as the 33rd of "and", 52.
# "(?:st|nd|rd|th)?" -- VOLTAMP files "QUARTER ENDED 30TH JUNE, 2026".
# An ordinal suffix is a rendering choice, not a different date.
_DATE_NAMED = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?[-/.\s]+({_MONTH_ALT})[a-z]*\.?"
    rf"[-/.\s,]+(\d{{2,4}})", re.I)

# "June 30, 2026" -- month first. A third layout, and the one AADHARHFC
# and CARTRADE file in.
_DATE_MONTH_FIRST = re.compile(
    rf"\b({_MONTH_ALT})[a-z]*\.?\s+(\d{{1,2}})\s*,?\s*(\d{{4}})\b", re.I)

_DATE_NUMERIC = re.compile(r"(?<!\d)(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})(?!\d)")


class _DateFinder:
    """findall() over both header layouts, returning (day, mon, year).

    A quarter-end is always the LAST day of a month -- 31 Mar, 30 Jun,
    30 Sep, 31 Dec -- so in a numeric date the first field is 28 or
    more and cannot be a month. That makes DD-MM-YYYY unambiguous here
    without having to assume a locale, and anything that does not look
    like a real month-end is dropped rather than guessed at.
    """

    pattern = "named + numeric"

    @staticmethod
    def findall(text):
        out = []
        text = text or ""
        for day, mon, year in _DATE_NAMED.findall(text):
            out.append((day, mon, year))
        for mon, day, year in _DATE_MONTH_FIRST.findall(text):
            out.append((day, mon, year))
        for a, b, year in _DATE_NUMERIC.findall(text):
            try:
                day, month = int(a), int(b)
            except ValueError:
                continue
            # A statement column is a period END. If the first field is
            # 12 or less this is either MM-DD (not an Indian filing) or
            # not a period end at all -- either way, not ours to read.
            if not (13 <= day <= 31 and 1 <= month <= 12):
                continue
            out.append((str(day), _MONTHS[month - 1], year))
        return out


_DATE_RE = _DateFinder()
_NUM_RE = re.compile(r"\(?-?[\d,]+\.?\d*\)?")

# ---------------------------------------------------------------
# NUMBERS THAT ARRIVE WITH A SPACE THROUGH THE MIDDLE
# ---------------------------------------------------------------
# pdfplumber reads the APTUS statement as:
#
#   VII Profit for the period  26,094.10  2 6,095.49  21,925.15  9 4,294.39
#   Finance costs             1 6,967.51   16,051.21  1 6,043.29    64,844.50
#
# Those are four columns, not six. The kerning in the filing's font
# puts a gap between the leading digit and the rest, and the extractor
# reports it as whitespace.
#
# THIS IS WHY IT MATTERED, 31 July 2026. Fixing the DATE bug alone made
# the parser read APTUS's quarter as PAT 60.95 against 219.25 -- a 72%
# collapse -- when the truth was 261 against 261, flat. The old
# "no rows" failure was ugly and SAFE; half the fix would have been
# silent and WRONG, and a wrong grade on a real filing is the worst
# thing this program could produce.
#
# NARROW ON BOTH SIDES, and the first attempt was not.
#
# A lookbehind of merely (?<=\d) is satisfied by the last digit of a
# COMPLETED number, so "6,095.49 21,925.15" -- two perfectly good
# figures -- was welded into "6,095.4921,925.15". Worse than the bug it
# was fixing.
#
# The left side must therefore be a SHORT, BARE digit run: one or two
# digits with no digit, comma or dot immediately before them, so it
# cannot be the tail of something already whole. The right side must be
# a properly comma-grouped figure. "12 345" is left alone. "1 6,967.51"
# is joined.
_SPLIT_THOUSANDS = re.compile(r"(?<![\d.,])(\d{1,2})\s+(\d{1,2},\d{3})")
_SPLIT_BEFORE_COMMA = re.compile(r"(?<![\d.,])(\d{1,2})\s+(,\d{3})")
# And the gap can fall before the DECIMAL POINT instead:
#
#   Basic (Amount in INR)  5.21  5 .22  4.39  18.84
#
# which read as five values -- 5.21, 5, 22, 4.39, 18.84 -- and put the
# year's figure in a quarter's column. Same shape, same rule: the left
# side must be a short bare run that cannot be the tail of a number
# already finished.
_SPLIT_BEFORE_POINT = re.compile(r"(?<![\d.,])(\d{1,3})\s+(\.\d{1,4})")


def repair_split_numbers(line):
    """Close up spaces that fell inside a single figure."""
    line = _SPLIT_THOUSANDS.sub(r"\1\2", line or "")
    line = _SPLIT_BEFORE_COMMA.sub(r"\1\2", line)
    return _SPLIT_BEFORE_POINT.sub(r"\1\2", line)


def _to_float(token):
    """'30045.20' -> 30045.2   '(140.77)' -> -140.77   '--' -> None

    A comma inside a decimal ('248,03') is a scan artifact, not Indian
    grouping -- Indian grouping never puts a comma two digits from the
    end. Repaired rather than dropped, but only in that exact shape.
    """
    t = str(token or "").strip()
    if not t or t in ("-", "--", "NA"):
        return None
    negative = t.startswith("(") and t.endswith(")")
    t = t.strip("()").strip()
    if re.fullmatch(r"\d+,\d{2}", t):
        t = t.replace(",", ".")
    t = t.replace(",", "")
    try:
        value = float(t)
    except ValueError:
        return None
    return -value if negative else value


def _parse_date(day, mon, year):
    year = int(year)
    year += 2000 if year < 100 else 0
    try:
        return datetime.strptime(f"{int(day):02d}-{mon[:3].title()}-{year}",
                                 "%d-%b-%Y").date()
    except ValueError:
        return None


def detect_unit(text):
    """Multiplier to convert the statement's figures into crores."""
    for pattern, mult in UNIT_PATTERNS:
        if pattern.search(text):
            return mult
    return None


def _is_plausible_quarter_end(d):
    """Could this date really be a column header in a filing?

    THE BELT TO THE REGEX'S BRACES. On 31 July 2026 a widened date
    pattern read "...2026 March 31, 2026..." as 26 March 2031 and put
    25 rows into quarterly_results.db dated Mar-31 and Jun-30. The
    regex is fixed, but a parser that can invent a date five years out
    should not be the only thing standing between a bad match and the
    store.

    Two rules, both from the shape of a real statement:

      - a period END is the last day of a month, so the 28th or later.
        Nothing legitimate in a column header is the 12th.
      - a filing cannot report a quarter that has not happened. Six
        months of slack covers a late annual report and a clock that
        disagrees; five years does not.

    Deliberately NOT anchored to "today" beyond that, so replaying an
    old session still parses its own filings.
    """
    if d is None:
        return False
    if d.day < 28:
        return False
    horizon = datetime.now().date()
    if (d - horizon).days > 190:
        return False
    # Nothing in this bot looks further back than a couple of years,
    # and a date before that in a results header is a misread.
    return (horizon - d).days < 1500


def find_period_columns(text):
    """The quarter-end dates, left to right, EXCLUDING the year-ended
    columns.

    The header of a SEBI statement reads:

        Quarter Ended                              Year Ended
        30-Jun-2026 | 31-Mar-2026 | 30-Jun-2025 | 31-Mar-2026

    so a date can appear twice with completely different meanings. Two
    rules, both conservative:
      - anything at or after the words "Year Ended" is not a quarter
      - a date that repeats is the year column, and is dropped
    """
    line = None
    for raw in text.splitlines():
        if len(_DATE_RE.findall(raw)) >= 2:
            line = raw
            break
    if line is None:
        return []

    cut = re.search(r"year\s+ended", line, re.I)
    head = line[:cut.start()] if cut else line

    dates, seen = [], set()
    for day, mon, year in _DATE_RE.findall(head):
        d = _parse_date(day, mon, year)
        if not _is_plausible_quarter_end(d):
            continue
        if d and d not in seen:
            seen.add(d)
            dates.append(d)
    # No "Year Ended" marker on this line: the standard layout is three
    # quarters then the year, so keep at most three.
    if cut is None and len(dates) > 3:
        dates = dates[:3]
    return dates


def parse_statement(text, symbol=None):
    """Pull quarterly figures out of the text of a results PDF.

    Returns [{period_end, sales, pat, eps, ...}] newest quarter first,
    or [] when the statement cannot be read confidently.
    """
    if not text:
        return []
    unit = detect_unit(text)
    periods = find_period_columns(text)
    if not periods:
        diagnostic(f"[PDF] {symbol or 'statement'}: no quarter-end columns "
                   f"found -- not parsed.")
        return []
    if unit is None:
        warn(f"[PDF] {symbol or 'statement'}: no unit declared (lakhs/crores). "
             f"Refusing to guess -- figures would be out by 100x.")
        return []

    found = {}
    for raw in text.splitlines():
        label = raw.strip()
        if not label:
            continue
        key = next((k for k, pat in LINE_ITEMS if pat.search(label)), None)
        if key is None or key in found:
            continue
        # Close up figures the extractor split with a stray space
        # ("2 6,095.49" is one number, not two). See
        # repair_split_numbers() -- without this the columns shift left
        # and every figure is attributed to the wrong quarter, which is
        # far worse than reading nothing.
        values = [_to_float(t) for t in
                  _NUM_RE.findall(repair_split_numbers(label))]
        # The row label itself can carry digits ("Sl No", "(5-6)",
        # "Face value of 5"). The figures always sit at the END of the
        # row, so align from the right.
        values = [v for v in values if v is not None]
        if len(values) < len(periods):
            continue
        # ALIGN FROM THE RIGHT, NOT THE LEFT.
        #
        # A SEBI statement is: three quarter columns then the year
        # column. Taking the last len(periods)+1 and then slicing from
        # its LEFT was correct only when exactly one extra number was
        # present; with two stray leading digits it silently handed
        # every column its neighbour's figure.
        #
        # Right-alignment is what the layout actually guarantees: the
        # final column is the year, the ones before it are the
        # quarters, and any junk from the label is at the front where
        # it gets dropped.
        if len(values) >= len(periods) + 1:
            window = values[-(len(periods) + 1):-1]
        else:
            window = values[-len(periods):]
        found[key] = window if len(window) == len(periods) else None

    if not found:
        return []

    out = []
    for i, period in enumerate(periods):
        record = {"period_end": period,
                  "period_label": period.strftime("%b-%y")}
        for key, values in found.items():
            if not values or i >= len(values) or values[i] is None:
                continue
            value = values[i]
            # EPS is per share; everything else is a money figure in the
            # statement's declared unit.
            record[key] = value if key == "eps" else round(value * unit, 2)
        if record.get("sales") is None and record.get("total_income") is not None:
            record["sales"] = record["total_income"]
        if len(record) > 2:
            out.append(record)

    # ---- LAST GATE: DOES THIS EVEN LOOK LIKE A STATEMENT? ----------
    #
    # 1 August 2026. Widening the unit and date patterns made eight
    # more filings "readable", and four of those eight were wrong:
    #
    #     ASHIKAG   sales=0.86     pat=36.97     profit 43x revenue
    #     AVL       sales=625.03   pat=2.00
    #
    # A row that parses is not a row that is right. Everything else in
    # this file is a rule about FINDING numbers; this is the only rule
    # about BELIEVING them, and it exists because the failure mode of
    # a half-read statement is a confident wrong grade -- the single
    # worst thing this program can emit.
    #
    # Deliberately loose. Holding companies really do earn more from
    # investments than from operations, so the test is not "profit
    # below revenue" but "profit not absurdly above it". A rule tight
    # enough to catch every mis-read would throw away real filings,
    # and this bot already has a habit of grading on data it should
    # have refused.
    return [r for r in out if _looks_like_a_real_quarter(r, symbol)]


def _looks_like_a_real_quarter(record, symbol=None):
    """Reject a parsed row that cannot be a real set of figures."""
    sales = record.get("sales")
    pat = record.get("pat")
    label = record.get("period_label")

    if sales is not None and sales < 0:
        diagnostic(f"[PDF] {symbol or '?'} {label}: negative revenue "
                   f"({sales}) -- not stored.")
        return False

    # 10x is well past any holding company and nowhere near the 43x
    # that ASHIKAG produced from a mangled column.
    if sales and pat is not None and abs(pat) > abs(sales) * 10:
        diagnostic(f"[PDF] {symbol or '?'} {label}: profit {pat} against "
                   f"revenue {sales} -- columns look misaligned, "
                   f"not stored.")
        return False

    return True


def parse_pdf(path, symbol=None, max_pages=24):
    """Read a results PDF from disk. Never raises."""
    try:
        import pdfplumber
    except ImportError:
        warn("[PDF] pdfplumber is not installed -- py -m pip install pdfplumber")
        return []
    try:
        chunks = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages[:max_pages]:
                t = page.extract_text() or ""
                if re.search(r"revenue|total\s+income|profit\s+for\s+the",
                             t, re.I):
                    chunks.append(t)
        return parse_statement("\n".join(chunks), symbol=symbol)
    except Exception as exc:                               # noqa: BLE001
        warn(f"[PDF] Could not read {path}: {exc}")
        return []
