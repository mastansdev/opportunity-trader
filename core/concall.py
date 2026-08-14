"""
==========================================================
The concall card -- what management actually said
==========================================================

    "for live news from Day Trader Telugu , Business Pulse (conviction
     on business + confidence on management)"
                                    -- operator, 1 August 2026

He described the signal he wanted. Earnings 360 had been sending it,
in full, for every concall, and the bot was filing it as plain news:

    kind = NEWS      grade = None      ai_direction = None
    headline = "ADANIENSOL - Concall Summary Period: 2026-06-30
                SENTIMENT TONE = Positive Confid"

Cut off mid-word. Everything below that point discarded.

    79 concall cards received
    78 carry SENTIMENT TONE
     0 had the tone, guidance or red flags extracted

This is the Pulse-grid failure of 31 July repeating in a second place:
somebody has already listened to the call and written down what was
said, and the bot reads only the top line.

WHAT THE CARD CARRIES
---------------------
    SENTIMENT TONE      Positive, Confident
    GUIDE - GROWTH      Rising
    GUIDE - MARGINS     Expanding
    WHY                 why the tone reads that way
    TONE SIGNAL         the behaviour behind it -- "Unwavering
                        conviction; management avoided hedging"
    GUIDANCE            growth / margins / capex, in words and figures
    KEY TAKEAWAYS
    RED FLAGS           language and behaviour, not numbers
    WHAT CHANGED VS LAST QUARTER

The last two are the ones a human cannot get anywhere else. A filing
tells you what happened. RED FLAGS - LANGUAGE tells you that
management "hedged FY28 capex on Solapur success" -- which is a
sentence about confidence, not about profit.

HOW THE HEADER ROW READS
------------------------
The three gauges print side by side, so OCR returns the labels on one
line and their values on the next:

    SENTIMENT TONE GUIDE - GROWTH GUIDE - MARGINS
    = Positive Confident t Rising + Expanding

The leading "=", "t" and "+" are icons the reader turned into
letters. So the values are found by VOCABULARY, in order, rather than
by position -- position moves whenever the OCR drops or invents a
character, and a guidance direction on the wrong gauge is the same
class of error as a quarter against the wrong company.

WHAT THIS DOES NOT DO
---------------------
It does not decide whether a confident tone is worth buying. Nothing
has measured that. It puts the sentence management said in front of
the operator, next to the stock, and the outcome tracker can answer
the rest once there are samples.

Author : H&M Opportunity Trader
==========================================================
"""

import re

# The card announces itself two ways -- the caption Earnings 360 sends
# with the picture, and the gauge row inside the picture itself.
CONCALL_CARD = re.compile(r"CONCALL\s+SUMMARY|SENTIMENT\s+TONE", re.I)

# ---- THE THREE GAUGES ----
# Read by vocabulary, not by position. Every value seen across the 79
# stored cards, plus the obvious opposites the card must be able to
# print on a bad quarter.
_TONE_MOOD = ("POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL")
_TONE_MANNER = ("CONFIDENT", "CAUTIOUS", "DEFENSIVE", "EVASIVE",
                "GUARDED", "OPTIMISTIC", "MEASURED")
_GROWTH = ("RISING", "FALLING", "STABLE", "FLAT", "SLOWING",
           "ACCELERATING", "DECLINING")
_MARGINS = ("EXPANDING", "COMPRESSING", "STABLE", "FLAT", "IMPROVING",
            "CONTRACTING", "NARROWING")

_GAUGE_HEADER = re.compile(
    r"SENTIMENT\s+TONE.*?GUIDE\s*[-–]\s*GROWTH.*?GUIDE\s*[-–]\s*MARGINS",
    re.I | re.S)

# ---- THE PROSE SECTIONS ----
# OCR mangles the headings as reliably as it mangles everything else.
# "RED FLAGSANGUAGE - BEHAVIOR" is "RED FLAGS / LANGUAGE - BEHAVIOR"
# with the slash eaten, and it is that way on every single card.
_SECTIONS = (
    ("why", r"\bWHY\b"),
    ("tone_signal", r"\bTONE\s*SIGNAL\b"),
    ("guidance", r"GUIDANCE\s*[:.]?\s*INTERPRETED"),
    ("takeaways", r"KEY\s+TAKEAWAYS"),
    ("changed", r"WHAT\s+CHANGED\s+VS\s+LAST\s+QUARTER"),
    # The heading is "RED FLAGS / LANGUAGE - BEHAVIOR" and OCR eats the
    # slash on every card, giving "RED FLAGSANGUAGE - BEHAVIOR". The
    # "- BEHAVIOR" tail must be consumed BY the heading pattern -- the
    # first version stopped at "ANGUAGE" and every card came back with
    # "BEHAVIOR" as its first red flag, which is a heading fragment
    # being reported as a finding about the company.
    ("red_flags",
     r"RED\s+FLAGS?\s*L?ANGUAGE\s*[-–]?\s*BEHAVIOU?R|"
     r"RED\s+FLAGS?\s*L?ANGUAGE|RED\s+FLAGS?\b"),
    ("track_next", r"TRACK\s+NEXT\s+SIGNALS?(?:\s*[-–]?\s*NOT\s+METRICS)?"),
)
_ANY_SECTION = re.compile(
    "|".join(f"(?:{pat})" for _name, pat in _SECTIONS), re.I)

# A guidance line: "GROWTH  20% total revenue growth expected".
_GUIDE_LINE = re.compile(
    r"^\s*[^A-Za-z0-9]*\b(GROWTH|MARGINS?|CAPEX)\b\s*[:\-]?\s*(.+)$",
    re.I | re.M)

# Bullet leaders the reader turns icons into.
_BULLET = re.compile(r"^\s*[=\-•*_~>tT+↑↓]+\s*")

# The up/down/flat arrow in front of a guidance sentence, as OCR
# returns it. Anchored and bounded: "T 38% CAGR" loses the T, but
# "Tt 60-70% rooftop" loses only the arrow, and a real word like
# "Target stable returns" must survive intact -- hence the length cap
# and the requirement that a letter form be followed by a space.
_ARROW = re.compile(r"^\s*(?:[↑↓→~>—–\-]+|[tT]{1,2}[fF]?(?=\s))\s*")


def is_concall_card(text):
    """True when this message is a concall summary card."""
    return bool(text) and bool(CONCALL_CARD.search(str(text)))


def _first_of(words, line):
    """The first word from `words` appearing in `line`, or None."""
    best, at = None, len(line) + 1
    for word in words:
        hit = re.search(rf"\b{word}\b", line, re.I)
        if hit and hit.start() < at:
            best, at = word.title(), hit.start()
    return best


def gauges(text):
    """Tone, growth and margin direction, read off the header row.

    Returns {} rather than a half-filled dict when the header is not
    found -- a guidance direction attributed to the wrong gauge is
    worse than no guidance at all.
    """
    body = str(text or "")
    hit = _GAUGE_HEADER.search(body)
    if not hit:
        return {}
    # The values are on the line or two AFTER the header row. Two,
    # because a long "WHY" sometimes wraps into the gap.
    tail = body[hit.end():]
    lines = [ln for ln in tail.splitlines() if ln.strip()][:3]
    out = {}
    for line in lines:
        if "mood" not in out:
            mood = _first_of(_TONE_MOOD, line)
            manner = _first_of(_TONE_MANNER, line)
            if mood:
                out["mood"] = mood
                if manner:
                    out["manner"] = manner
        if "growth" not in out:
            growth = _first_of(_GROWTH, line)
            if growth:
                out["growth"] = growth
        if "margins" not in out:
            # STABLE and FLAT are in both lists. Whichever word sits
            # LATER on the line is the margin gauge, because the card
            # prints growth first -- and when only one is present it
            # belongs to growth, which is read above first.
            for word in _MARGINS:
                for m in re.finditer(rf"\b{word}\b", line, re.I):
                    g = out.get("growth", "")
                    if g and m.start() < line.upper().find(g.upper()):
                        continue
                    if word.title() == out.get("growth"):
                        continue
                    out["margins"] = word.title()
                    break
                if "margins" in out:
                    break
    return out


def sections(text):
    """The prose blocks, each trimmed at the next heading."""
    body = str(text or "")
    out = {}
    for name, pattern in _SECTIONS:
        hit = re.search(pattern, body, re.I)
        if not hit:
            continue
        rest = body[hit.end():]
        stop = _ANY_SECTION.search(rest)
        block = rest[:stop.start()] if stop else rest
        lines = []
        for raw in block.splitlines():
            line = _BULLET.sub("", raw).strip()
            if len(line) >= 4:
                lines.append(line)
        if lines:
            out[name] = lines
    return out


def guidance(text):
    """Growth, margins and capex as the card states them, with figures."""
    body = sections(text).get("guidance") or []
    out = {}
    for line in body:
        hit = _GUIDE_LINE.match(line)
        if not hit:
            continue
        key = hit.group(1).upper().rstrip("S")
        # The card prints a direction ARROW before the sentence. OCR
        # returns it as "T", "Tt", "Tf", "~", "~>", ">" or "—", so the
        # value came back as "T 38% India AI market CAGR". The arrow
        # duplicates the gauge that has already been read properly, and
        # a stray letter in front of a figure is how a number gets
        # misread later.
        value = _ARROW.sub("", hit.group(2)).strip(" .:-")
        if value and key.lower() not in out:
            out[key.lower()] = value
    return out


_SIDE_BY_SIDE = re.compile(
    r"RED\s+FLAGS?.{0,40}?TRACK\s+NEXT\s+SIGNALS?", re.I)


def columns_collide(text):
    """True when RED FLAGS and TRACK NEXT SIGNALS print on one line.

    The card is two columns. When the reader puts both headings on the
    same line, the bullets underneath belong to EITHER column and
    nothing in the text says which:

        RED FLAGSANGUAGE - BEHAVIOR   TRACK NEXT SIGNALS - NOT METRICS
        Hedged FY28 capex on Solapur success
        rCB facility commissioning by Oct

    The first is a red flag about management's LANGUAGE. The second is
    a date to watch. Calling the second a red flag would put a warning
    on a company for scheduling a commissioning -- inventing a concern
    the publisher never raised.
    """
    return bool(_SIDE_BY_SIDE.search(str(text or "")))


def columns_from_positions(words, headings=("RED", "TRACK"), stop_below=None):
    """(left_text, right_text) for a two-column block, by x position.

    ---- THE SECOND HALF OF THE SAME PROBLEM. 2 August 2026. ----

        "make sure to capture every data point with respective stock
         name. so pls do not miss or club one data to other stock."

    The concall brief prints FOUR blocks as two columns:

        KEY TAKEAWAYS      |  WHAT CHANGED VS LAST QUARTER
        RED FLAGS          |  TRACK NEXT SIGNALS

    Tesseract reads a two-column layout line by line ACROSS both, so
    the transcript interleaves them:

        Elevated working capital due to new = Execution of STEAG
        contracts initiatives

    "Elevated working capital" is a red flag. "Execution of STEAG
    cross-selling" is a thing to watch. Both halves of one text line.
    columns_collide() spotted this and did the honest thing -- refused
    to guess, and kept the block under mixed_observations(). On 68 of
    78 stored cards that meant NO red flags at all.

    A word's x-coordinate settles it. The two headings give the split
    point: everything left of the right-hand heading belongs to the
    left column, everything at or right of it to the right one.

    Returns ("", "") when the positions are missing or the headings
    cannot be found -- every caller then falls back to the text path
    exactly as before.
    """
    if not words:
        return "", ""
    # EXACT, and on the SAME LINE. startswith() was tried and it found
    # "reduction" for the heading "RED" -- a bullet in the right-hand
    # column, three rows down, which made the left heading appear to
    # the RIGHT of the right one and the whole block came back empty.
    # A heading is a whole word, and the two sit side by side.
    def whole(word, want):
        return word["text"].strip().strip(".,:;-").upper() == want

    pair = None
    for left_w in words:
        if not whole(left_w, headings[0]):
            continue
        line = max(14, left_w["height"]) * 1.4
        for right_w in words:
            if not whole(right_w, headings[1]):
                continue
            if abs(right_w["top"] - left_w["top"]) > line:
                continue
            if right_w["left"] <= left_w["left"]:
                continue
            if pair is None or left_w["top"] < pair[0]["top"]:
                pair = (left_w, right_w)
            break
    if pair is None:
        return "", ""
    left_head, right_head = pair
    # A word starting past this x is in the right column. Half a column
    # gap back from the right heading, so a bullet that starts slightly
    # left of its heading still lands on the correct side.
    split_x = right_head["left"] - (right_head["left"]
                                    - left_head["left"]) * 0.15
    # BELOW the heading line, not from it. Without this the heading's
    # own tail -- "LANGUAGE - BEHAVIOR", "SIGNALS - NOT METRICS" --
    # comes back as the column's first bullet, which is a heading
    # fragment reported as a finding about the company.
    head_bottom = max(left_head["top"] + left_head["height"],
                      right_head["top"] + right_head["height"])

    # And a TOP for the block below. The KEY TAKEAWAYS / WHAT CHANGED
    # pass has no natural end, so without a floor it swallows the RED
    # FLAGS block underneath and reports a warning as a takeaway.
    floor = stop_below
    if floor is None:
        below = [w["top"] for w in words
                 if w["top"] > head_bottom + 20
                 and w["text"].strip().upper() in
                 ("RED", "TRACK", "KEY", "WHAT", "FINAL")]
        floor = min(below) if below else None

    def gather(side):
        rows = {}
        for w in words:
            if w["top"] <= head_bottom:
                continue
            if floor is not None and w["top"] >= floor - 5:
                continue
            if (w["left"] >= split_x) != side:
                continue
            rows.setdefault(round(w["top"] / 12), []).append(w)
        out = []
        for _key in sorted(rows):
            line = " ".join(x["text"] for x in
                            sorted(rows[_key], key=lambda x: x["left"]))
            if line.strip():
                out.append(line.strip())
        return "\n".join(out)

    return gather(False), gather(True)


def red_flags(text):
    """What management's LANGUAGE gave away, not what the numbers did.

    This is the part with no substitute. A filing tells you profit
    fell; only this tells you guidance was "hedged on Solapur success".

    EMPTY WHEN THE COLUMNS COLLIDE. 68 of 78 stored cards put the two
    headings on one line, so this returns flags for 10. That is the
    honest number. Splitting the interleaved bullets by alternating
    them was tried against the cards and it is guesswork -- some cards
    alternate, some list one column then the other, and there is no
    marker to tell them apart. See mixed_observations() for the block
    itself, which is kept and labelled rather than thrown away.
    """
    if columns_collide(text):
        return []
    return sections(text).get("red_flags") or []


def read_columns(text, words):
    """{red_flags, track_next, takeaways, changed} using positions.

    The whole point of the word boxes: when the two headings share a
    text line, the bullets underneath are interleaved and NOTHING in
    the text says which column each belongs to. Their x does.

    Falls back to the text reading -- red_flags() empty, the block kept
    under mixed_observations() -- whenever the positions are missing or
    the headings cannot be located. Nothing is guessed.
    """
    out = {"red_flags": [], "track_next": [],
           "takeaways": [], "changed": []}
    if not words:
        return out
    for left_key, right_key, heads in (
            ("red_flags", "track_next", ("RED", "TRACK")),
            ("takeaways", "changed", ("KEY", "WHAT"))):
        left, right = columns_from_positions(words, headings=heads)
        if not left and not right:
            continue
        out[left_key] = _bullets(left)
        out[right_key] = _bullets(right)
    return out


# NOT _BULLET. That pattern includes t/T because the card's up-arrow
# OCRs as a lone "t" -- correct there, and destructive here: it ate the
# T from "Telecom sector outlook" and "Transformational acquisitions",
# turning findings into "elecom" and "ransformational". This strips a
# leading t/T only when it stands ALONE, which is what an arrow does.
_COL_BULLET = re.compile(r"^\s*(?:[=\-•*_~>»+↑↓]+|[tT](?=\s))\s*")

# A WRAPPED line, not merely a line ending in a letter. The card is
# narrow, so a finding runs on -- "Elevated working capital due to
# new" / "contracts". But "ending in a lowercase letter" describes
# almost every line, and using that joined the entire column into one
# paragraph. Two signals, both from the card itself:
#
#   the line ends with a hyphen        "enabling cross-" / "selling"
#   the NEXT line starts lowercase     "...due to new" / "contracts"
#
# A new bullet starts with a capital, a digit or a symbol. That is
# what tells the two apart.
_ENDS_HYPHEN = re.compile(r"[\-–]$")
_STARTS_LOWER = re.compile(r"^[a-z]")


def _bullets(block):
    """The findings of one column, unwrapped, headings removed."""
    lines = []
    for line in str(block or "").splitlines():
        line = _COL_BULLET.sub("", line).strip(" .;:").strip()
        if not line:
            continue
        # "LANGUAGE - BEHAVIOR" / "SIGNALS - NOT METRICS" are the tails
        # of the two headings, not findings about the company.
        if re.match(r"^(L?ANGUAGE|SIGNALS?|VS\b|NOT\s+METRICS)", line, re.I):
            continue
        lines.append(line)
    out = []
    for line in lines:
        if out and _ENDS_HYPHEN.search(out[-1]):
            out[-1] = _ENDS_HYPHEN.sub("", out[-1]) + line
        elif out and _STARTS_LOWER.match(line):
            out[-1] = f"{out[-1]} {line}"
        else:
            out.append(line)
    return [x for x in out if len(x) >= 8]


def mixed_observations(text):
    """The red-flag / track-next block when the two cannot be told apart.

    Kept, because the standing rule is not to throw away information we
    are receiving -- but under a name that does not claim each line is
    a warning.
    """
    if not columns_collide(text):
        return []
    # When both headings sit on one line, the RED FLAGS heading is
    # followed immediately by the TRACK NEXT heading, so the block
    # under "red_flags" comes back EMPTY -- sections() stops at the
    # next heading and the next heading is right there. The bullets
    # for BOTH columns fall below the second heading, so that is where
    # to read them. Without this the whole block was silently dropped
    # on 68 of 78 cards, which is the outcome this function exists to
    # prevent.
    got = sections(text).get("red_flags") or []
    return got or (sections(text).get("track_next") or [])


def summary(text, words=None):
    """One line for the panel, or None.

    Tone first, because that is the question the card answers that
    nothing else does. Guidance follows because a confident tone with
    compressing margins is a different trade from a confident tone
    with expanding ones.
    """
    g = gauges(text)
    if not g:
        return None
    mood = g.get("mood")
    if not mood:
        return None
    head = f"CONCALL {mood.upper()}"
    if g.get("manner"):
        head += f"/{g['manner'].upper()}"
    parts = []
    if g.get("growth"):
        parts.append(f"growth {g['growth'].lower()}")
    if g.get("margins"):
        parts.append(f"margins {g['margins'].lower()}")
    flags = read_columns(text, words).get("red_flags") or red_flags(text)
    if flags:
        parts.append(f"{len(flags)} red flag" + ("s" if len(flags) > 1 else ""))
    return head + (": " + ", ".join(parts) if parts else "")


def read_card(text, words=None):
    """Everything the card holds, or None when it is not one.

    ---- WORDS, 2 August 2026 ----

        "make sure to capture every data point with respective stock
         name ... so pls do not miss or club one data to other stock."

    The card prints four blocks in TWO COLUMNS. Tesseract reads across
    both, so the flat transcript pairs a red flag with the track-next
    item beside it:

        Elevated working capital due to new = Execution of STEAG
        contracts                             cross-selling initiatives

    red_flags() saw one heading immediately followed by the other,
    found nothing between them, and returned []. On the BLUSPRING card
    that lost three warnings and three things to watch -- not to a bug
    in the reader, but to the columns.

    With the word boxes the split is arithmetic: everything left of the
    right-hand heading's x belongs to the left column. Without them
    this behaves exactly as it did, which is why words is optional and
    the text keys stay populated either way.
    """
    if not is_concall_card(text):
        return None
    cols = read_columns(text, words)
    flags = cols.get("red_flags") or red_flags(text)
    return {
        "gauges": gauges(text),
        "guidance": guidance(text),
        "red_flags": flags,
        "track_next": cols.get("track_next") or [],
        "takeaways": cols.get("takeaways") or [],
        "changed": cols.get("changed") or [],
        # Only when the columns could NOT be told apart. With positions
        # they can, and repeating the same lines under a name that says
        # "we do not know which of these is a warning" would be worse
        # than useless -- it would double-count every finding.
        "mixed": [] if cols.get("red_flags") else mixed_observations(text),
        "sections": sections(text),
        "summary": summary(text, words),
    }
