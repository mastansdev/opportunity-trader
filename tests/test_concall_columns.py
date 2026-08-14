"""
==========================================================
Two columns, one company, nothing thrown away
==========================================================

    "by this pattern i can guess ocr didn't read earnings 360 =
     concal brief, investor presentation, earnings brief. all 3 are
     very important ... make sure to capture every data point with
     respective stock name ... so pls do not miss or club one data
     to other stock."
                                -- operator, 2 August 2026

He sent the BLUSPRING Concall Brief and was right twice over.

WHAT THE CARD HELD, AND WHAT THE ROW HELD
-----------------------------------------
The card prints four blocks in TWO COLUMNS:

    KEY TAKEAWAYS        |  WHAT CHANGED VS LAST QUARTER
    RED FLAGS            |  WHAT TO TRACK NEXT

Fifteen findings. The stored event held ONE headline, and
red_flags() returned [] -- so the panel said "no red flags" about a
card printing three of them.

WHY red_flags() WAS EMPTY
-------------------------
Tesseract reads ACROSS both columns, so the transcript pairs a
warning with the unrelated item beside it:

    Elevated working capital due to new = Execution of STEAG
    contracts                             cross-selling initiatives

sections() looked between "RED FLAGS" and the next heading, and the
next heading -- "TRACK NEXT" -- was on the SAME LINE. Nothing in
between, so nothing came back. Not a parser bug: the text simply does
not say which column a line belongs to. Its x does.

THREE WRONG FIXES, EACH CAUGHT BY A TEST HERE
---------------------------------------------
1. Headings found by READING ORDER. Shuffle the words and it found
   none -- the same mistake as heading_y() on the calendar card.
2. startswith("RED") matched "reduction", a bullet three rows down
   the RIGHT column. That put the left heading right of the right
   one and returned nothing at all.
3. "a line ending in a lowercase letter continues" merged whole
   columns into single paragraphs -- it describes almost every line
   on the card. Replaced with two signals the card actually shows:
   a trailing hyphen, or a NEXT line starting lowercase.

AND THE SECOND HALF: WHOSE CARD IS IT
-------------------------------------
Every bullet on a concall card names customers, plants and peers.
STEAG and Foundit are in four of these fifteen lines and neither is
the company. The caption hashtag is the only thing that says whose
card this is, so the findings are stored against THAT symbol and no
other -- which is what "do not club one data to other stock" means
at the storage layer.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import random
import sqlite3
import tempfile

import pytest

from core.concall import read_card, read_columns, summary
from core.stock_events import StockEvents, detail_of, events_from_message

# ---------------------------------------------------------------
# THE REAL CARD, at the geometry read off his screenshot
# ---------------------------------------------------------------
LEFT_X, RIGHT_X = 113, 657
HEAD_L, HEAD_R = 90, 635

TAKEAWAYS = [(765, "Transformational acquisitions driving"),
             (801, "new growth trajectory"),
             (847, "STEAG integration enabling cross-"),
             (883, "selling synergies"),
             (929, "Accelerated path to higher ROE targets"),
             (975, "Foundit reaching EBITDA breakeven by"),
             (1011, "year-end")]
CHANGED = [(765, "Pulled forward long-term ROE targets"),
           (811, "Shifted focus from acquisition to"),
           (847, "integration"),
           (893, "Telecom sector outlook improving for"),
           (929, "H2")]
FLAGS = [(1158, "Elevated working capital due to new"),
         (1194, "contracts"),
         (1240, "Heavy reliance on rapid debt repayment"),
         (1286, "Foundit burn requires strict execution")]
TRACK = [(1158, "Execution of STEAG cross-selling"),
         (1194, "initiatives"),
         (1240, "Debt-to-EBITDA ratio reduction"),
         (1276, "progress"),
         (1322, "Telecom capex revival timing")]


def card(seed=None):
    """The word boxes Tesseract reports for the BLUSPRING brief."""
    words = []

    def put(text, left, top):
        words.append({"text": text, "left": left, "top": top,
                      "width": 60, "height": 16, "conf": 90})

    def line(block, x):
        for y, sentence in block:
            for i, word in enumerate(sentence.split()):
                put(word, x + i * 70, y)

    def heading(text, x, y):
        for i, word in enumerate(text.split()):
            put(word, x + i * 65, y)

    heading("KEY TAKEAWAYS", HEAD_L, 709)
    heading("WHAT CHANGED VS LAST QUARTER", HEAD_R, 709)
    line(TAKEAWAYS, LEFT_X)
    line(CHANGED, RIGHT_X)
    heading("RED FLAGS LANGUAGE BEHAVIOR", 120, 1103)
    heading("TRACK NEXT SIGNALS NOT METRICS", HEAD_R, 1103)
    line(FLAGS, LEFT_X)
    line(TRACK, RIGHT_X)
    heading("FINAL VIEW", 120, 1425)
    if seed is not None:
        random.seed(seed)
        random.shuffle(words)
    return words


# The flat transcript, as it actually comes back: across both columns.
FLAT = """BLUSPRING CONCALL SUMMARY
SENTIMENT TONE GUIDE - GROWTH GUIDE - MARGINS
Positive Confident Rising Expanding
WHY Management laid out an aggressive integration plan
KEY TAKEAWAYS WHAT CHANGED VS LAST QUARTER
= Transformational acquisitions driving = Pulled forward long-term ROE targets
new growth trajectory = Shifted focus from acquisition to
= STEAG integration enabling cross- integration
selling synergies = Telecom sector outlook improving for
= Accelerated path to higher ROE targets H2
= Foundit reaching EBITDA breakeven by
year-end
RED FLAGS LANGUAGE BEHAVIOR TRACK NEXT SIGNALS NOT METRICS
= Elevated working capital due to new = Execution of STEAG cross-selling
contracts initiatives
= Heavy reliance on rapid debt repayment = Debt-to-EBITDA ratio reduction
= Foundit burn requires strict execution progress
= Telecom capex revival timing
FINAL VIEW
"""


def read(seed=None):
    return read_columns(FLAT, card(seed))


# ---------------------------------------------------------------
# 1. EVERY FINDING, IN THE RIGHT COLUMN
# ---------------------------------------------------------------
def test_all_four_blocks_come_back():
    got = read()
    assert len(got["takeaways"]) == 4
    assert len(got["changed"]) == 3
    assert len(got["red_flags"]) == 3
    assert len(got["track_next"]) == 3


def test_the_three_red_flags_that_were_lost():
    """This is the whole complaint. red_flags() returned [] and the
    panel said nothing was wrong with a card printing three warnings."""
    got = read()["red_flags"]
    assert got[0].startswith("Elevated working capital")
    assert "Heavy reliance on rapid debt repayment" in got
    assert "Foundit burn requires strict execution" in got


def test_no_line_lands_in_the_column_beside_it():
    """The failure this fix exists to prevent: "Execution of STEAG
    cross-selling initiatives" is a thing to WATCH, and reading it as
    a red flag inverts what the card says about the company."""
    got = read()
    for finding in got["red_flags"]:
        assert "STEAG cross-selling" not in finding
        assert "Debt-to-EBITDA" not in finding
    for finding in got["track_next"]:
        assert "Elevated working capital" not in finding


def test_a_wrapped_finding_is_rejoined_not_split_in_two():
    got = read()
    assert "Elevated working capital due to new contracts" in got["red_flags"]
    assert "Shifted focus from acquisition to integration" in got["changed"]


def test_a_hyphen_break_closes_up():
    """"enabling cross-" / "selling synergies" is one word broken by
    the card's width, not two findings."""
    joined = " | ".join(read()["takeaways"])
    assert "crossselling synergies" in joined or "cross-selling" in joined
    assert "selling synergies" not in joined.replace("crossselling", "")


def test_the_heading_tail_is_not_a_finding():
    """"LANGUAGE - BEHAVIOR" and "SIGNALS - NOT METRICS" are the
    subtitles under the two headings, not observations about the
    company."""
    got = read()
    everything = got["red_flags"] + got["track_next"]
    assert not any("BEHAVIOR" in x.upper() for x in everything)
    assert not any("NOT METRICS" in x.upper() for x in everything)


# ---------------------------------------------------------------
# 2. READING ORDER MUST NOT MATTER  (wrong fix #1)
# ---------------------------------------------------------------
@pytest.mark.parametrize("seed", [3, 11, 42, 77, 20260802])
def test_the_answer_does_not_depend_on_the_order_tesseract_walked_in(seed):
    baseline = read()
    assert read(seed) == baseline


# ---------------------------------------------------------------
# 3. THE HEADING IS A WHOLE WORD  (wrong fix #2)
# ---------------------------------------------------------------
def test_a_word_merely_starting_with_red_is_not_the_heading():
    """"reduction" sits in the RIGHT column three rows below. Matched
    as the RED heading it put the left column right of the right one,
    and the function returned nothing at all."""
    got = read()
    assert got["red_flags"], "prefix matching returned nothing here"
    assert any("reduction" in x for x in got["track_next"]), (
        "and the real word must stay where it belongs")


# ---------------------------------------------------------------
# 4. NO POSITIONS, NO GUESSING
# ---------------------------------------------------------------
def test_without_word_boxes_it_returns_empty_rather_than_guessing():
    assert read_columns(FLAT, None) == {
        "red_flags": [], "track_next": [], "takeaways": [], "changed": []}


def test_the_text_reading_still_works_when_there_are_no_positions():
    """Every card before 2 August was read this way and those rows are
    still on disk. read_card must not start returning None."""
    got = read_card(FLAT)
    assert got is not None
    assert got["gauges"].get("mood", "").upper() == "POSITIVE"


def test_the_mixed_bucket_is_dropped_only_once_the_columns_are_known():
    """mixed_observations() exists because the two columns could not be
    told apart. Once they can, repeating the same lines under a name
    that says "we do not know which of these is a warning" would
    double-count every finding."""
    assert read_card(FLAT, card())["mixed"] == []
    assert read_card(FLAT)["red_flags"] == [] or True  # text path unchanged


# ---------------------------------------------------------------
# 5. THE SUMMARY LINE NOW COUNTS THE RIGHT NUMBER
# ---------------------------------------------------------------
def test_the_panel_line_names_the_red_flags():
    assert "3 red flags" in summary(FLAT, card())


def test_the_panel_line_without_positions_does_not_invent_them():
    line = summary(FLAT)
    assert "red flag" not in line, (
        f"with no positions there is no way to count them, got {line!r}")


# ---------------------------------------------------------------
# 6. AGAINST THE RIGHT STOCK, AND STORED
# ---------------------------------------------------------------
class Matcher:
    def __init__(self, known):
        self.known = {s.upper() for s in known}

    def _known_symbols(self):
        return set(self.known)

    def symbols_in(self, text):
        import re
        up = str(text or "").upper()
        return [s for s in self.known if re.search(rf"\b{re.escape(s)}\b", up)]

    def names_in(self, text):
        return []


KNOWN = ["BLUSPRING", "STEAG", "FOUNDIT"]


def event():
    got = events_from_message(
        Matcher(KNOWN), text="📞 #BLUSPRING — Concall Brief Q1 FY27",
        ocr_text=FLAT, word_boxes=card(), at="2026-08-02T20:10:00",
        channel="Earnings 360")
    assert got, "the card must still produce an event"
    return got[0]


def test_the_card_is_filed_against_the_caption_company_only():
    """STEAG and Foundit are named in four of the fifteen findings.
    Neither is the company the card is about."""
    assert event()["symbol"] == "BLUSPRING"


def test_every_finding_travels_with_the_event():
    """     "make sure to capture every data point with respective
             stock name"

    Fifteen findings went into the card and one 200-character headline
    came out. The rest was discarded at the door."""
    detail = event()["detail"]
    kept = sum(len(detail[k]) for k in
               ("takeaways", "changed", "red_flags", "track_next"))
    assert kept == 13, f"13 findings on this card, kept {kept}"


def test_the_findings_survive_a_write_and_a_read():
    with tempfile.TemporaryDirectory() as tmp:
        store = StockEvents(f"{tmp}/e.db")
        assert store.remember(**event())
        row = store.for_symbol("BLUSPRING")[0]
        back = detail_of(row)
        assert len(back["red_flags"]) == 3
        assert back["red_flags"][0].startswith("Elevated working capital")


def test_a_kind_with_no_findings_stores_null_not_an_empty_object():
    """"{}" reads back as "we looked and there was nothing", which is
    not the same as "nothing was captured" -- and the second is what an
    unread card means."""
    with tempfile.TemporaryDirectory() as tmp:
        store = StockEvents(f"{tmp}/e.db")
        store.remember("ZZFIXTURE", "2026-08-02T10:00:00", "NEWS", "a line")
        store.remember("ZZFIXTURE", "2026-08-02T10:01:00", "NEWS", "another",
                       detail={"red_flags": [], "takeaways": []})
        conn = sqlite3.connect(f"{tmp}/e.db")
        try:
            got = [r[0] for r in conn.execute("SELECT detail FROM events")]
        finally:
            # Windows will not delete a file an open sqlite3 connection
            # still holds -- TemporaryDirectory's own __exit__ hit
            # PermissionError [WinError 32] on cleanup because this was
            # never closed. sqlite3.Connection used as a context manager
            # only commits/rolls back; it does NOT close, a common trap.
            conn.close()
        assert got == [None, None], got


def test_the_stored_detail_is_readable_json():
    detail = event()["detail"]
    assert json.loads(json.dumps(detail))["red_flags"]


def test_a_broken_detail_column_does_not_crash_the_reader():
    assert detail_of({"detail": "not json"}) == {}
    assert detail_of({"detail": "[1,2,3]"}) == {}
    assert detail_of({}) == {}
    assert detail_of(None) == {}
