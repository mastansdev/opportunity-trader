"""
==========================================================
A wall of logos, read by position
==========================================================

    "can u tell me how our bot will sorted this & update our
     watchlist?"
    "make sure the ocr is working properly what if i didn't asked you
     to tell me what our bot will do this image? we never know right"
                                    -- operator, 2 August 2026

He sent the 03 August TOMORROW'S CALENDAR card and asked what the bot
would do with it. Measured against the picture:

    the card lists            60 companies
    the bot filed             34
    of the 19 DURING names
        filed correctly        4    UPL, GLAXO, DHANUKA, CRIZAC
        filed as AFTER         9    ESCORTS, CAMS, PARKHOSPS, JAINREC,
                                    BLUEJET, ETHOSLTD, HUBTOWN,
                                    STOVEKRAFT, MOBIKWIK
        never read             6    KCP, AVADHSUGAR, VELJAN, HALDYNGL,
                                    KINETICENG, PANCHMAHQ

A stock reporting DURING the session is one to have on screen at
09:15. Filed as AFTER it is ignored until the next morning.

WHY IT HAPPENED
---------------
The card is a GRID of logos with the ticker printed under each.
Tesseract walks that column by column, so the flat transcript reads:

    DURING MARKET HOURS
    UPL GLAXO
    DHANUKA CRIZAC              <- 4 of the 19
    AFTER MARKET HOURS
    DLF SBIFUNDS
    ...
    During/After forecast ...   <- the FOOTER
    BLUEJET
    ETHOSLTD                    <- DURING names, dumped at the end
    AVADHSUGAR

Splitting THAT on the two headings is what put nine stocks in the
wrong bucket. A y-coordinate does not care what order anything was
read in.

AND THE PART THAT MATTERS MORE THAN THE FIX
-------------------------------------------
Nothing said so. The panel showed 34 names as though they were the
list. The card counts itself -- "03 Aug, 2026 - 60 Companies" -- and
reading that number turns a silent half-read into a warning.

MY OWN FIRST FIX WAS STILL ORDER-DEPENDENT
------------------------------------------
heading_y() originally looked for "MARKET" in words[i+1:i+4] -- the
next few entries in the LIST. That is the exact assumption the whole
function exists to escape, and the shuffled-input test below caught
it: it found no headings at all and returned nothing. Adjacency ON
THE PAGE, not in the list.

Author : H&M Opportunity Trader
==========================================================
"""

import random

import pytest

from core.recap_card import (AFTER, DURING, rows_from_grid, stated_count)

# The real card, at the y values read off his screenshot.
DUR_ROWS = [
    (435, ["UPL", "GLAXO", "ESCORTS", "CAMS", "PARKHOSPS", "JAINREC",
           "BLUEJET", "ETHOSLTD"]),
    (594, ["DHANUKA", "CRIZAC", "HUBTOWN", "STOVEKRAFT", "KCP",
           "MOBIKWIK", "AVADHSUGAR", "VELJAN"]),
    (753, ["HALDYNGL", "KINETICENG", "PANCHMAHQ"]),
]
AFT_ROWS = [
    (992, ["DLF", "SBIFUNDS", "TORNTPOWER", "JSL", "ATHERENERG", "KEI",
           "KIMS", "IREDA"]),
    (1150, ["GESHIP", "INOXINDIA", "KANSAINER", "DOMS", "NAZARA",
            "JMFINANCIL", "LOTUSDEV", "UNIMECH"]),
    (1308, ["KALPATARU", "GULFOILLUB", "THOMASCOOK", "RBA", "ARTEMISMED",
            "TEXRAIL", "SANATHAN", "SAMHI"]),
    (1466, ["BHAGCHEM", "SAMBHV", "GANECOS", "NOCIL", "DRAGARWQ",
            "AEROPLANE", "SAPL", "SIGNPOST"]),
    (1624, ["TEXINFRA", "BOROSCI", "GPTHEALTH", "BUTTERFLY", "INDIAHOMES",
            "FOSECOC", "CHEMCON", "MUNJALSHOW"]),
    (1782, ["BHARATGEAR"]),
]
TRUTH = {s: DURING for _, row in DUR_ROWS for s in row}
TRUTH.update({s: AFTER for _, row in AFT_ROWS for s in row})
KNOWN = set(TRUTH)


def card(seed=None, footer=True):
    """The word boxes Tesseract reports for that picture."""
    words = []

    def put(text, left, top):
        words.append({"text": text, "left": left, "top": top,
                      "width": 80, "height": 18, "conf": 90})

    put("TOMORROW'S", 700, 100); put("CALENDAR", 900, 100)
    put("03", 760, 155); put("Aug", 800, 155)
    put("60", 980, 155); put("Companies", 1020, 155)
    put(DURING, 40, 274); put("MARKET", 180, 274); put("HOURS", 300, 274)
    for y, row in DUR_ROWS:
        for i, t in enumerate(row):
            put(t, 225 + i * 205, y)
    put(AFTER, 40, 830); put("MARKET", 160, 830); put("HOURS", 280, 830)
    for y, row in AFT_ROWS:
        for i, t in enumerate(row):
            put(t, 225 + i * 205, y)
    if footer:
        put("During/After", 600, 1880); put("forecast", 720, 1880)
        put("@market_pulse_ai", 860, 1950)
    if seed is not None:
        random.seed(seed)
        random.shuffle(words)
    return words


def read(seed=None, **kw):
    return {r["symbol"]: r["when"]
            for r in rows_from_grid(card(seed, **kw), known=KNOWN)}


# ---------------------------------------------------------------
# 1. THE WHOLE CARD, CORRECTLY
# ---------------------------------------------------------------
def test_all_sixty_are_read():
    got = read()
    assert len(got) == 60
    assert not set(TRUTH) - set(got)


def test_every_one_lands_in_the_right_bucket():
    got = read()
    wrong = {s: (got[s], TRUTH[s]) for s in TRUTH if got.get(s) != TRUTH[s]}
    assert not wrong, f"wrong side of the close: {wrong}"


def test_the_nine_that_were_in_the_wrong_bucket():
    """Named, because these are the ones that would have been ignored
    until the next morning while they moved during the session."""
    got = read()
    for symbol in ("ESCORTS", "CAMS", "PARKHOSPS", "JAINREC", "BLUEJET",
                   "ETHOSLTD", "HUBTOWN", "STOVEKRAFT", "MOBIKWIK"):
        assert got[symbol] == DURING, symbol


def test_the_six_that_were_never_read():
    got = read()
    for symbol in ("KCP", "AVADHSUGAR", "VELJAN", "HALDYNGL",
                   "KINETICENG", "PANCHMAHQ"):
        assert got.get(symbol) == DURING, symbol


# ---------------------------------------------------------------
# 2. READING ORDER MUST NOT MATTER
# ---------------------------------------------------------------
@pytest.mark.parametrize("seed", [7, 42, 99, 1234, 20260802])
def test_the_answer_does_not_depend_on_the_order_tesseract_walked_in(seed):
    """MY OWN FIRST FIX FAILED THIS. heading_y() looked for "MARKET" in
    the next few LIST entries, which is reading order -- the exact
    assumption this function exists to escape. Shuffled, it found no
    headings and returned nothing."""
    got = read(seed)
    assert len(got) == 60
    assert all(got[s] == TRUTH[s] for s in TRUTH)


# ---------------------------------------------------------------
# 3. THE FOOTER IS NOT A COMPANY LIST
# ---------------------------------------------------------------
def test_the_small_print_is_dropped_by_position():
    """"During/After forecast is based on past behavior" sits below
    every logo. Anything under it is not a company."""
    words = card()
    words.append({"text": "UPL", "left": 900, "top": 2100,
                  "width": 80, "height": 18, "conf": 90})
    rows = rows_from_grid(words, known=KNOWN)
    assert len([r for r in rows if r["symbol"] == "UPL"]) == 1


def test_a_card_with_no_footer_still_reads():
    got = read(footer=False)
    assert len(got) == 60


# ---------------------------------------------------------------
# 4. IT REFUSES RATHER THAN GUESSES
# ---------------------------------------------------------------
def test_no_positions_means_fall_back_to_the_text_path():
    assert rows_from_grid([], known=KNOWN) == []
    assert rows_from_grid(None, known=KNOWN) == []


def test_no_master_means_nothing():
    """The mismatch rule. Every ticker is gated on the real NSE list."""
    assert rows_from_grid(card(), known=None) == []
    assert rows_from_grid(card(), known=set()) == []


def test_a_card_with_only_one_heading_is_refused():
    """Without both, in order, there is no way to say which side of the
    close anything is on -- and inventing DURING is the dangerous half."""
    words = [w for w in card() if w["text"] != AFTER]
    assert rows_from_grid(words, known=KNOWN) == []


def test_the_title_block_above_the_first_heading_is_ignored():
    got = read()
    assert "TOMORROW'S" not in got and "CALENDAR" not in got


# ---------------------------------------------------------------
# 5. THE SILENT FAILURE, CLOSED
# ---------------------------------------------------------------
def test_the_card_counts_itself():
    assert stated_count("03 Aug, 2026 - 60 Companies") == 60
    assert stated_count("02 Aug, 2026 - 2 Companies") == 2
    assert stated_count("TOMORROW'S CALENDAR") is None


def test_a_nonsense_count_is_ignored():
    assert stated_count("- 0 Companies") is None
    assert stated_count("- 9999 Companies") is None


def test_a_partial_read_is_reported_not_hidden():
    """     "what if i didn't asked you to tell me what our bot will do
             this image? we never know right"

    34 of 60, shown as though it were the list. The card states its own
    size; comparing the two costs nothing."""
    src = open("core/stock_events.py", encoding="utf-8").read()
    block = src[src.find("says = stated_count(body)"):]
    block = block[:block.find("out = [{")]
    assert "if says and rows and len(rows) < says:" in block
    assert "warn(" in block
    assert "NOT on the watchlist" in block


def test_the_grid_path_is_tried_before_the_text_path():
    src = open("core/stock_events.py", encoding="utf-8").read()
    block = src[src.find("rows = []"):]
    block = block[:block.find("says = stated_count")]
    assert block.find("grid_rows(word_boxes") < block.find("recap_rows(body")
    assert "if not rows:" in block, "and it must fall back, not replace"


def test_the_word_boxes_reach_the_classifier():
    feed = open("core/telegram_feed.py", encoding="utf-8").read()
    assert "words_with_positions(data)" in feed
    assert '"word_boxes": self._ocr_boxes.get(' in feed
    events = open("core/stock_events.py", encoding="utf-8").read()
    assert "word_boxes=None" in events


def test_the_box_cache_is_bounded_with_the_text_cache():
    """This process runs for a week. Word boxes are bulkier than the
    transcript they came from."""
    feed = open("core/telegram_feed.py", encoding="utf-8").read()
    block = feed[feed.find("if len(self._ocr_cache) > 500:"):]
    block = block[:block.find("return text")]
    assert "_ocr_boxes.clear()" in block
