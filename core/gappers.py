"""
==========================================================
The gapper card is a reason. Read it as one.
==========================================================

    "this image from Earnings Pulse at 09:08 . have we / bot recvd &
     read about today pre-opened stocks? ... those stocks were got
     their results last day"
                                -- operator, 6 August 2026

WHAT WAS WRONG
--------------
On 6 August the ranker refused all 1,118 stocks that had candles:

    513  not moving enough
    494  NO REASON FOUND          <-- this one
    111  too thin to trade our size
    ---
      0  passed

NAVINFLUOR was one of the 494. It opened 7,930 and closed 8,610 --
up 8.58% on Rs 119 crore, near its high. A textbook long.

And the bot was holding this, received at 03:38 UTC = 09:08 IST, from
Earnings Pulse, with all twelve symbols correctly linked:

    Pre-Open Earnings Gappers -- Yesterday's Results, 05 Aug 2026
    NAVINFLUOR   Quality: Great   MCap 39,079 Cr   Gap +4.5%

A named stock, a graded result, and a measured gap. That IS the
mechanism. core/why_moving.py returned None for it, because it looks
for a SENTENCE explaining a move and this card is a TABLE.

So the bot did not lack a source. He had already brought the source.
It could not read a table.

HOW THE CARD IS SHAPED
----------------------
The OCR comes out column by column, in order, and the columns line up:

    Symbol            Quality     MCap Cr     Gap %      [Close %  Read]
    -- Gapping Up (7)
    SANDESH           Weak            749     20.0%
    SOTL              Excellent     4,629     13.4%
    ...
    -- Gapping Down (5)
    NAHARPOLY         Weak            681    -10.7%

Twelve symbols, twelve qualities, twelve market caps, twelve gaps.
Read the blocks and zip them. Where a column is short -- OCR drops a
cell often enough -- that FIELD is left empty for that stock rather
than shifting every row below it. A misaligned row would put one
stock's result on another's name, which is the one thing he has
forbidden outright:

    "so pls do not miss or club one data to other stock"

THE SAME CARD COMES BACK AFTER THE CLOSE
----------------------------------------
Earnings Pulse republishes it with two more columns -- Close % and a
Read: "strong follow-through", "faded", "reversed", "held". That is a
scored outcome for every gap, published by his own channel, and it is
what turns this from a signal into a memory. Parsed here too; what
learns from it is a separate piece of work.

Author : H&M Opportunity Trader
==========================================================
"""

import re
import sqlite3

DB_PATH = "data/telegram.db"

# The two section headers. OCR mangles the little triangles into "A"
# and "WV" and sometimes drops them, so they are optional.
_UP = re.compile(r"Gapping\s+Up\s*\((\d+)\)", re.I)
_DOWN = re.compile(r"Gapping\s+Down\s*\((\d+)\)", re.I)

_QUALITY_WORD = re.compile(r"^(Excellent|Great|Good|OK|Weak)$", re.I)
_PCT = re.compile(r"^([+-]?\d{1,3}(?:\.\d+)?)\s*%$")
_NUMBER = re.compile(r"^([\d,]+(?:\.\d+)?)$")
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9&\-]{2,17}$")

# The card's own column headings, used as block separators.
_HEAD_QUALITY = re.compile(r"^Quality$", re.I)
_HEAD_MCAP = re.compile(r"^MCap(\s+Cr)?$", re.I)
_HEAD_GAP = re.compile(r"^Gap\s*%$", re.I)
_HEAD_CLOSE = re.compile(r"^Close\s*%$", re.I)
_HEAD_READ = re.compile(r"^Read$", re.I)

_IS_CARD = re.compile(r"Pre-?Open\s+Earnings\s+Gappers|Gapping\s+Up\s*\(",
                      re.I)

# Words that are NOT a stock even though they look like one in caps.
_NOT_A_SYMBOL = {
    "SYMBOL", "QUALITY", "MCAP", "GAP", "READ", "CLOSE", "TOTAL",
    "SUMMARY", "SOURCE", "NOTE", "AVG", "CR", "PRE", "OPEN", "EARNINGS",
    "GAPPERS", "YESTERDAY", "RESULTS", "STOCKS", "SIGNIFICANT", "GAPS",
}


def is_gapper_card(text):
    """Is this OCR block one of the gapper cards?"""
    return bool(_IS_CARD.search(str(text or "")))


def _lines(text):
    return [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]


def _block_after(lines, header, take, accept):
    """`take` values following `header`, each passing `accept`.

    Stops at the next column heading so a short column never eats the
    one after it.
    """
    out = []
    started = False
    for line in lines:
        if not started:
            if header.match(line):
                started = True
            continue
        if (_HEAD_QUALITY.match(line) or _HEAD_MCAP.match(line)
                or _HEAD_GAP.match(line) or _HEAD_CLOSE.match(line)
                or _HEAD_READ.match(line)):
            break
        value = accept(line)
        if value is not None:
            out.append(value)
        if len(out) >= take:
            break
    return out


def parse_card(text):
    """[{symbol, direction, quality, mcap_cr, gap_pct, close_pct, read}]

    Empty list if this is not a gapper card or the symbols cannot be
    read. Never guesses a value it did not see.
    """
    if not is_gapper_card(text):
        return []
    lines = _lines(text)

    up_at = down_at = None
    n_up = n_down = 0
    for i, line in enumerate(lines):
        found = _UP.search(line)
        if found and up_at is None:
            up_at, n_up = i, int(found.group(1))
        found = _DOWN.search(line)
        if found and down_at is None:
            down_at, n_down = i, int(found.group(1))

    def _symbols_from(start, count):
        got = []
        for line in lines[start + 1:]:
            if _UP.search(line) or _DOWN.search(line):
                break
            token = line.upper()
            if token in _NOT_A_SYMBOL:
                continue
            if _SYMBOL.match(token):
                got.append(token)
            if len(got) >= count:
                break
        return got

    symbols, directions = [], []
    if up_at is not None:
        found = _symbols_from(up_at, n_up)
        symbols += found
        directions += ["UP"] * len(found)
    if down_at is not None:
        found = _symbols_from(down_at, n_down)
        symbols += found
        directions += ["DOWN"] * len(found)
    if not symbols:
        return []

    total = len(symbols)
    quality = _block_after(
        lines, _HEAD_QUALITY, total,
        lambda s: s.upper() if _QUALITY_WORD.match(s) else None)
    gaps = _block_after(
        lines, _HEAD_GAP, total,
        lambda s: float(_PCT.match(s).group(1)) if _PCT.match(s) else None)
    mcaps = _block_after(
        lines, _HEAD_MCAP, total,
        lambda s: (float(_NUMBER.match(s).group(1).replace(",", ""))
                   if _NUMBER.match(s) else None))
    closes = _block_after(
        lines, _HEAD_CLOSE, total,
        lambda s: float(_PCT.match(s).group(1)) if _PCT.match(s) else None)
    reads = _block_after(
        lines, _HEAD_READ, total,
        lambda s: s if re.search(r"follow[- ]through|faded|reversed|held|"
                                 r"selloff|sell[- ]off|moved up|positive",
                                 s, re.I) else None)

    def at(column, index):
        # A SHORT COLUMN LEAVES A HOLE, IT DOES NOT SHIFT THE ROWS.
        # If OCR drops one cell, every stock below it would otherwise
        # inherit its neighbour's number.
        return column[index] if len(column) == total else None

    rows = []
    for i, symbol in enumerate(symbols):
        rows.append({
            "symbol": symbol,
            "direction": directions[i],
            "quality": at(quality, i),
            "mcap_cr": at(mcaps, i),
            "gap_pct": at(gaps, i),
            "close_pct": at(closes, i),
            "read": at(reads, i),
        })
    return rows


def reason_line(row):
    """One sentence a human would accept as the reason it is moving."""
    if not row or not row.get("symbol"):
        return None
    gap = row.get("gap_pct")
    quality = (row.get("quality") or "").title()
    where = "gapped up" if row.get("direction") == "UP" else "gapped down"
    bits = [f"{where} {abs(gap):.1f}% at the open" if gap is not None
            else f"{where} at the open"]
    bits.append("on yesterday's results")
    if quality:
        bits.append(f"result graded {quality}")
    if row.get("close_pct") is not None:
        bits.append(f"closed {row['close_pct']:+.0f}% from there")
    if row.get("read"):
        bits.append(str(row["read"]).lower())
    return ", ".join(bits)


def cards_since(cutoff_iso, db_path=DB_PATH):
    """Every gapper card in the store since `cutoff_iso`, parsed.

    Returns {symbol: row}, newest card winning -- the post-close card
    supersedes the pre-open one for the same stock, which is what
    carries Close % and the Read.
    """
    found = {}
    try:
        con = sqlite3.connect(db_path)
        rows = con.execute(
            "select at, ocr_text from messages "
            "where at >= ? and ocr_text is not null and ocr_text <> '' "
            "order by at asc", (cutoff_iso,)).fetchall()
        con.close()
    except Exception:                                      # noqa: BLE001
        return {}
    for at, text in rows:
        for row in parse_card(text):
            row["at"] = at
            found[row["symbol"]] = row
    return found


def row_for(symbol, cutoff_iso=None, db_path=DB_PATH, _cache={}):
    """The parsed gapper row for one stock, or None.

    Cached per cutoff so the ranker can call it once per symbol on
    every refresh without re-reading the store 1,100 times.
    """
    if not symbol:
        return None
    if cutoff_iso is None:
        from datetime import datetime, timedelta
        cutoff_iso = (datetime.now() - timedelta(hours=36)).isoformat()
    key = (cutoff_iso[:13], db_path)
    if key not in _cache:
        _cache.clear()
        _cache[key] = cards_since(cutoff_iso, db_path)
    return _cache[key].get(str(symbol).upper())


def reason_for(symbol, cutoff_iso=None, db_path=DB_PATH):
    """The gapper reason for one stock as a sentence, or None."""
    return reason_line(row_for(symbol, cutoff_iso, db_path))


# ===================================================================
# THE RECAP GRID -- every reporter, graded, in one image
# ===================================================================
#
#     "(SCI) not showed despite excellent"
#                                 -- operator, 7 August 2026
#
# SCI closed with an EXCELLENT result and never reached Row 1. It has
# NO individual poster in the store -- its only mention is inside the
# evening recap image, a five-row grid of symbol chips:
#
#     Rating / EXCELLENT / GREAT / GOOD / OK / WEAK
#     During Market            After Market
#     @ VHL  @ TAALTECH        @ SBCL  @ VISAKAIND  @ SCI
#     @ RATEGAIN               @ RAIN  @ IRMENERGY
#     @ GOODLUCK @ TRENT       @ INDRAMEDCO @ GRINFRA
#     ...
#
# The rating LABELS are printed once at the top, and the OCR gives no
# row boundaries. Guessing where EXCELLENT ends and GREAT begins would
# put a WEAK stock into Row 1 wearing an EXCELLENT badge, which is far
# worse than SCI being absent.
#
# SO IT IS NOT GUESSED. The OCR preserves LINES, and each line belongs
# to exactly one rating row. Many symbols on those lines already have
# a grade from their own poster -- TRENT is GREAT, MOTHERSON is WEAK,
# BAJAJELEC is GOOD, and core/pulse_ratings.py read those from the
# cards themselves. Those are ANCHORS.
#
#   * a line carrying an anchor takes that anchor's grade
#   * a line with no anchor inherits the line above it, because the
#     groups are contiguous and printed in a fixed order
#   * a line before ANY anchor is left ungraded -- there is nothing
#     to anchor it to, and an unanchored guess is exactly what this
#     is designed to avoid
#
# A symbol already graded by its own card is never overwritten here.
# The card is the better source; this only fills what the card layer
# could not reach.

_RECAP = re.compile(r"EARNINGS\s+PULSE\s+RECAP", re.I)
_ORDER = ("EXCELLENT", "GREAT", "GOOD", "OK", "WEAK")
# The chip glyphs OCR turns the little logos into.
_CHIP = re.compile(r"[@©«QÂ~,§=●○]+\s*([A-Z][A-Z0-9&_\-]{2,17})")


def is_recap_card(text):
    return bool(_RECAP.search(str(text or "")))


def parse_recap(text, known_grades=None):
    """{symbol: GRADE} from the evening recap grid.

    `known_grades` is {symbol: GRADE} read from individual posters --
    the anchors. Without at least one anchor nothing is returned,
    because there would be no way to know which row is which.
    """
    if not is_recap_card(text):
        return {}
    known = {str(k).upper(): str(v).upper()
             for k, v in (known_grades or {}).items()}
    if not known:
        return {}

    lines = [ln for ln in str(text).splitlines() if ln.strip()]
    # Everything before the During/After header is the legend.
    start = 0
    for i, ln in enumerate(lines):
        if re.search(r"During\s+Market", ln, re.I):
            start = i + 1
            break
    out, current = {}, None
    for ln in lines[start:]:
        syms = [s for s in _CHIP.findall(ln) if s not in
                ("EXCELLENT", "GREAT", "GOOD", "OK", "WEAK", "RECAP")]
        if not syms:
            continue
        # What do we already know about this line?
        votes = [known[s] for s in syms if s in known and known[s] in _ORDER]
        # ---- NO INHERITANCE ACROSS LINES. 7 August 2026. ----
        #
        # The first version let an unanchored line inherit the line
        # above it, on the reasoning that the groups are contiguous.
        # Measured against his own recap image that put WAKEFIT and
        # MANCREDIT -- both GREAT -- into EXCELLENT, because their line
        # sat just past the boundary and there was no anchor on it to
        # say so. 2 wrong out of 19.
        #
        # A wrong badge is worse than a missing one: he reads Row 1 and
        # buys from it. So a line WITHOUT an anchor now yields nothing
        # at all. Coverage drops; correctness does not.
        if not votes:
            current = None
            continue
        # ---- THE ANCHORS ON A LINE MUST AGREE. 7 August 2026. ----
        #
        # Taking the majority still put WAKEFIT (GREAT) into EXCELLENT,
        # because one anchor on its line was itself misread from a
        # poster. A row is one rating by construction -- if the
        # anchors on it disagree, at least one is wrong and there is
        # no way to tell which. So the line is skipped.
        #
        # This is the third narrowing of this rule and each one traded
        # coverage for correctness. That is the right direction: he
        # buys from Row 1.
        if len(set(votes)) > 1:
            current = None
            continue
        current = votes[0]
        for s in syms:
            if s not in known:            # never overwrite a real card
                out[s] = current
    return out
