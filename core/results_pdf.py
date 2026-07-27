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
UNIT_PATTERNS = [
    (re.compile(r"in\s+lakhs?", re.I), 0.01),
    (re.compile(r"in\s+crores?", re.I), 1.0),
    (re.compile(r"in\s+millions?", re.I), 0.1),
    (re.compile(r"in\s+thousands?", re.I), 0.0001),
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

_DATE_RE = re.compile(r"(\d{1,2})[-/\s]([A-Za-z]{3})[-/\s](\d{2,4})")
_NUM_RE = re.compile(r"\(?-?[\d,]+\.?\d*\)?")


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
        values = [_to_float(t) for t in _NUM_RE.findall(label)]
        # The row label itself can carry digits ("Sl No", "(5-6)",
        # "Face value of 5"). Take the LAST len(periods)+1 numbers and
        # drop anything beyond, then align to the columns from the left
        # of that tail -- the figures always sit at the end of the row.
        values = [v for v in values if v is not None]
        if len(values) < len(periods):
            continue
        tail = values[-(len(periods) + 1):] if len(values) > len(periods) else values
        found[key] = tail[:len(periods)] if len(tail) >= len(periods) else None

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
    return out


def parse_pdf(path, symbol=None, max_pages=12):
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
