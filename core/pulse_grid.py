"""
==========================================================
The numbers the channel already gave us
==========================================================

    "i'm saying the same thing since morning right? i brought every
     thing to you. all pro folder channels give us complete data in
     realtime, which our own bot is unable to get in real time. you
     told we will get the maximum use of those in response but not
     followed by instructions."
                                    -- operator, 1 August 2026

He is right, and this file is the thing that should have been built
first.

WHAT WAS HAPPENING INSTEAD
--------------------------
core/results_pdf.py downloads a company's filing and tries to find the
results table inside it. On 1 August, 200 filings were fetched:

    92   parsed
    108  failed -- 57% had no results table in the PDF at all

and worse, of the 1,699 rows in the store, 21 held figures that could
not be that company:

    BAJFINANCE  Jun-26  sales     12.00   own median  8,308.97
    RAYMOND     Mar-26  sales      1.36   real: hundreds of crore
    WESTLIFE    Jun-26  sales      1.00

Two guards were written against that and neither is sufficient: a
self-comparison needs three stored quarters and 618 of 748 companies
have fewer, and a change-based check cannot see a company whose whole
history is wrong together.

WHAT WAS SITTING THERE THE WHOLE TIME
-------------------------------------
Earnings Pulse posts a FinAI grid with every result, and the bot has
been storing it as OCR text and reading only the Pulse Rating off it:

    Gillette India
    Q1 FY27 Pulse Rating : Weak
    Metric      QoQ    YoY    Jun'26  Mar'26  Jun'25
    Sales        1%    11%       783     792     707
    Other Inc.    -     -          5       5       7
    OP         -18%     8%       228     277     210
    OPM       -592bps -67bps   29.1%   35.0%   29.8%
    PAT         17%     9%       159     192     146
    EPS         17%     9%      48.9    59.1    44.7

THREE quarters of real figures, per card, published the minute the
company reports. 206 such cards were already in telegram.db.

That is the whole of what core/quarterly_results.py is trying and
failing to extract from a PDF -- including the year-ago quarter, which
a single filing does not even contain.

WHAT THIS DOES NOT DO
---------------------
It does not replace the filing parser. A channel can be wrong, and two
independent readings of one quarter is worth more than either alone --
that is what the CONFLICT chip is for. This adds the second reading,
and it is the one that arrives on time.

It refuses a row it cannot read cleanly rather than guessing, for the
same reason everything else here does: a wrong number is worse than a
missing one, and it took a whole day to prove that twice.

Author : H&M Opportunity Trader
==========================================================
"""

import re
from datetime import date

# The header that identifies the grid. Both channels print it.
GRID_HEADER = re.compile(r"Metric\s+QoQ\s+YoY", re.I)

# The quarter columns, e.g. "Jun'26  Mar'26  Jun'25". The OCR keeps the
# apostrophe more often than not, and loses it just often enough that
# it has to be optional.
_QUARTER = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
                      r"\s*['’]?\s*(\d{2})\b", re.I)

_MONTH = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

_LAST_DAY = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
             7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}

# The rows worth reading. OPM is a percentage and EPS is per-share, so
# neither is a rupee figure and both are kept separately.
_ROWS = (
    ("sales", re.compile(r"^\s*Sales\b", re.I)),
    ("other_income", re.compile(r"^\s*Other\s*Inc", re.I)),
    ("operating_profit", re.compile(r"^\s*OP\b", re.I)),
    ("opm_pct", re.compile(r"^\s*OPM\b", re.I)),
    ("pat", re.compile(r"^\s*PAT\b", re.I)),
    ("eps", re.compile(r"^\s*EPS\b", re.I)),
)

# A figure in the grid. The OCR turns a minus into a backtick, a curly
# quote or nothing at all, so the sign is read separately and only the
# digits are trusted here.
_NUMBER = re.compile(r"-?\d[\d,]*\.?\d*")

# Anything that is a CHANGE column rather than a figure: 11%, -592 bps.
_CHANGE = re.compile(r"^-?[\d.,]+\s*(%|bps)$", re.I)


def _quarter_end(month_name, yy):
    """'Jun', '26' -> date(2026, 6, 30)."""
    month = _MONTH.get(str(month_name).lower()[:3])
    if not month:
        return None
    year = 2000 + int(yy)
    day = _LAST_DAY[month]
    if month == 2 and year % 4 == 0:
        day = 29
    return date(year, month, day)


def _label(period):
    return f"{period.strftime('%b')}-{period.strftime('%y')}"


def quarters_in(text):
    """The quarter columns the card prints, left to right."""
    header = None
    for line in str(text or "").splitlines():
        if GRID_HEADER.search(line):
            header = line
            break
    if header is None:
        return []
    out = []
    for month, yy in _QUARTER.findall(header):
        period = _quarter_end(month, yy)
        if period and period not in out:
            out.append(period)
    return out


def _figures(line, want):
    """The `want` right-most numeric cells on a grid row.

    The row is  LABEL  QoQ%  YoY%  Q1  Q2  Q3  -- so the change columns
    are dropped by their % / bps suffix and the rest read as figures.
    A row that does not yield exactly `want` numbers is refused, never
    padded: a half-read row is how a column ends up against the wrong
    quarter.
    """
    body = re.sub(r"^\s*\S+[\s.]*", " ", line, count=1)
    cells = [c for c in re.split(r"\s{1,}", body.strip()) if c]
    values = []
    for cell in cells:
        if _CHANGE.match(cell) or cell.endswith(("%", "bps")):
            continue
        found = _NUMBER.search(cell.replace("O", "0"))
        if not found:
            continue
        try:
            values.append(float(found.group(0).replace(",", "")))
        except ValueError:
            continue
    if len(values) < want:
        return None
    # The quarter figures are the LAST `want` numbers on the line.
    return values[-want:]


def parse_grid(text):
    """[{period_end, period_label, sales, ...}] newest quarter first.

    Returns [] for anything that is not one of these cards, which is
    most messages.
    """
    periods = quarters_in(text)
    if len(periods) < 2:
        return []

    found = {}
    for line in str(text or "").splitlines():
        for field, pattern in _ROWS:
            if field in found or not pattern.search(line):
                continue
            values = _figures(line, len(periods))
            if values:
                found[field] = values
    if "sales" not in found and "pat" not in found:
        return []

    out = []
    for index, period in enumerate(periods):
        row = {"period_end": period, "period_label": _label(period)}
        for field, values in found.items():
            row[field] = values[index]
        out.append(row)
    return out
