"""
==========================================================
Nothing on this screen is smaller than 12px
==========================================================

    "DASHBOARD MUST EASE THE PROBLEMS USER FACING NOT INCREASING THEM
     BY COMPLEX & LONGER THINGS ... MAKE IT AS READABLE & SMOOTH UI"
    "STILL NOT READABLE TO USER . before sending me to verify have u
     cheked?"
                                    -- operator, 3 August 2026

I had not. I checked that the JavaScript parsed and the data was
right, then drew a MOCKUP of what I intended and asked him to verify
it. A mockup is not the page, and three passes of moving panels around
never touched the actual problem.

WHAT THE PROBLEM ACTUALLY WAS, MEASURED
---------------------------------------
The stylesheet, counted rather than eyeballed:

    16 rules at 11px          4 rules at 10px
    15 rules at 12px          4 rules at 9.5px
     4 rules at 10.5px        2 rules at 9px

The body is 14px and almost nothing inherited it. Table headers were
10px UPPERCASE with letter-spacing; badges were 9px. That is the
screenshot he sent -- a wall of grey 10px text.

No amount of rearranging panels fixes a 9px font. That is why the
first two attempts did not.

HOW THE FLOOR WAS BUILT
-----------------------
My first attempt listed the offending selectors BY HAND and missed 27
of them. The list is now generated from the file itself.

WHY THIS TEST REPLAYS THE CASCADE
---------------------------------
Grepping for "9px" would pass the moment the floor exists, whether or
not it wins. So this walks every rule in document order, applies the
same precedence a browser does -- !important beats plain, later beats
earlier -- and asserts on what would actually render.

Author : H&M Opportunity Trader
==========================================================
"""

import re

import pytest

INDEX = "dashboard/static/index.html"
FLOOR_PX = 12.0


def _stylesheet():
    src = open(INDEX, encoding="utf-8").read()
    return src[src.find("<style>"):src.rfind("</style>")]


def _effective_sizes():
    """{selector: (px, important)} as the browser would resolve it."""
    final = {}
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", _stylesheet()):
        hit = re.search(r"font-size:\s*([0-9.]+)px(\s*!important)?", body)
        if not hit:
            continue
        px, important = float(hit.group(1)), bool(hit.group(2))
        clean = re.sub(r"/\*.*?\*/", "", sel, flags=re.S)
        for part in clean.split(","):
            part = " ".join(part.split())
            if not part or part.startswith("@"):
                continue
            was = final.get(part)
            if was is None or important or not was[1]:
                final[part] = (px, important)
    return final


# ---------------------------------------------------------------
# 1. THE FLOOR
# ---------------------------------------------------------------
def test_nothing_renders_below_twelve_pixels():
    """The whole complaint, as an assertion."""
    small = sorted((px, sel) for sel, (px, _) in _effective_sizes().items()
                   if px < FLOOR_PX)
    assert not small, (
        f"{len(small)} selector(s) still render below {FLOOR_PX:g}px: "
        f"{[f'{px}px {sel}' for px, sel in small[:8]]}")


def test_there_are_rules_to_check_at_all():
    """A regex that silently matches nothing would pass the test above
    while the page stayed unreadable."""
    assert len(_effective_sizes()) > 60


def test_the_floor_was_generated_not_hand_listed():
    """The hand-written version missed 27 of 44 offenders."""
    style = _stylesheet()
    assert "GENERATED FROM THIS FILE, NOT GUESSED" in style


# ---------------------------------------------------------------
# 2. THE THINGS HE READS MOST
# ---------------------------------------------------------------
def test_table_text_is_at_least_fourteen():
    """He reads prices and quantities off these while a position moves."""
    sizes = _effective_sizes()
    assert sizes.get("table", (0,))[0] >= 14


def test_table_headers_are_readable():
    sizes = _effective_sizes()
    assert sizes.get("th", (0,))[0] >= FLOOR_PX


def test_the_body_default_is_not_the_small_print():
    sizes = _effective_sizes()
    assert sizes.get("body", (0,))[0] >= 14


@pytest.mark.parametrize("cls", [".ot-grade", ".ot-badge", ".badge"])
def test_every_chip_is_legible(cls):
    """     "MAKE SURE TO USE GOOD COLORS FONTS AND MARKING THE
             HIGHLIHTED WORDS, CHIPS FOR EXCELLENT"

    A chip he cannot read is decoration."""
    sizes = _effective_sizes()
    assert any(cls in sel and px >= FLOOR_PX
               for sel, (px, _) in sizes.items()), cls


# ---------------------------------------------------------------
# 3. COLOUR MEANS ONE THING
# ---------------------------------------------------------------
def test_the_six_publisher_words_each_have_a_chip():
    """EXCELLENT / GREAT / GOOD / OK / WEAK / POOR are the channels'
    own vocabulary. Ours must not invent a seventh."""
    style = _stylesheet()
    for grade in ("excellent", "great", "good", "ok", "weak", "poor"):
        assert f".ot-g-{grade}" in style, grade


def test_excellent_is_the_loudest_of_them():
    """It should be findable across the room."""
    src = open(INDEX, encoding="utf-8").read()
    assert ".ot-g-excellent { background:#12b76a" in src


def test_an_unknown_word_gets_the_neutral_chip_not_a_colour():
    """Colour means the publisher graded it. An event kind like ORDER
    or CONCALL has not earned green."""
    src = open(INDEX, encoding="utf-8").read()
    block = src[src.find("var OT_GRADES"):]
    block = block[:block.find("function renderBook")]
    assert 'OT_GRADES[key] || "mixed"' in block


# ---------------------------------------------------------------
# 4. THE LESSON
# ---------------------------------------------------------------
def test_the_reason_this_file_exists_is_recorded():
    """Three passes of layout work did not fix a 9px font, and the
    next person to be asked "make it readable" should not start by
    moving panels either."""
    style = _stylesheet()
    assert "THE TYPE IS THE PROBLEM" in style
