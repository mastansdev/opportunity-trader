"""
==========================================================
The word next to the symbol belongs to a publisher
==========================================================

    "then how bot dashboard shows me? and what are those chips of
     STRONG, MIXED, WEAK next to symbol?"
                                    -- operator, 2 August 2026

He asked because he assumed a PRO channel had said it. None had.

WHAT IT ACTUALLY WAS
--------------------
core/quarterly_results.grade() reading filed sales and PAT:

    both up strongly  -> STRONG        one up one down -> MIXED
    both up           -> GOOD          both down       -> WEAK

Our own arithmetic, in four words, two of which are also the
channels' words while meaning something different:

    Earnings Pulse    EXCELLENT  GREAT  GOOD  OK  WEAK  POOR
    ours              STRONG     GOOD   MIXED     WEAK

On CONCORDBIO, 2 August, the channel had said GOOD and the chip
beside the symbol said MIXED, with nothing on the row to say which
was whose. And grade()'s own docstring reads, in capitals, "NOT
VALIDATED AGAINST PRICE".

    "pls make sure to follow the pro channel way in building our own
     chips. we cannot deviate from NSE & PRO CHANNELS"

THE SWAP
--------
The chip is now the publisher's verdict, taken from the newest
RESULT event, with the publisher named on the hover. Our grade is
not deleted -- it still scores, it still appears in the collapsed
list, and it is still on the drill-down card -- but it now carries
the prefix OUR NUMBERS wherever it is written, and it is never
promoted into the channel's slot when the channel is silent.

    "pls make sure these chips & related stocks are never mis matched
     as they are the one we trust"

An empty chip is a fact: nobody has graded this yet.

Author : H&M Opportunity Trader
==========================================================
"""

import re

import pytest

from core.shortlist import ShortlistBuilder

HTML = "dashboard/static/index.html"
SHORTLIST = "core/shortlist.py"
STATE = "dashboard/state.py"


def src(path):
    return open(path, encoding="utf-8").read()


# ---------------------------------------------------------------
# 1. THE TWO VOCABULARIES ARE REALLY DIFFERENT
# ---------------------------------------------------------------
def test_the_words_overlap_which_is_why_this_was_confusing():
    """Not a style quibble. GOOD and WEAK are in BOTH lists and are
    computed by different things, so the same word on the same row
    could mean two different readings of two different quarters."""
    ours = set(ShortlistBuilder.GRADE_SCORE)
    theirs = set(ShortlistBuilder.PULSE_SCORE)
    assert ours & theirs == {"GOOD", "WEAK"}
    assert ours - theirs == {"STRONG", "MIXED"}


def test_our_grade_still_scores():
    """The swap is about the DISPLAY. Removing our arithmetic from the
    score would be a trading change nobody asked for."""
    assert ShortlistBuilder.GRADE_SCORE["STRONG"] > 0
    assert ShortlistBuilder.GRADE_SCORE["WEAK"] < 0


# ---------------------------------------------------------------
# 2. THE PANEL DRAWS THEIR WORD
# ---------------------------------------------------------------
def test_the_chip_class_map_carries_every_word_a_channel_uses():
    """MIXED is here and STRONG is not, and the difference is measured,
    not assumed: MIXED appears on 69 real cards from Earnings 360 and
    Earnings Pro. STRONG is only ever ours."""
    page = src(HTML)
    block = page[page.find("const GRADE_CLS"):]
    block = block[:block.find("const gradeChip")]
    for word in list(ShortlistBuilder.PULSE_SCORE) + ["MIXED"]:
        assert re.search(rf"\b{word}\s*:", block), \
            f"{word} missing from the chip colours"
    assert not re.search(r"\bSTRONG\s*:", block), \
        "STRONG is ours and must not be drawn beside the symbol"


def test_an_unscored_publisher_word_still_reaches_the_chip():
    """THE BUG IN THE FIRST VERSION OF THIS SWAP. Reading the chip off
    first_pulse looked right and would have blanked 69 rows, because
    first_pulse is only set for words PULSE_SCORE knows and MIXED is
    deliberately not one of them. Scoring nothing is not saying
    nothing."""
    assert "MIXED" not in ShortlistBuilder.PULSE_SCORE
    code = src(SHORTLIST)
    branch = code[code.find('if kind == "RESULT" and "RESULT" not in seen_kinds:'):]
    branch = branch[:branch.find("points = self.PULSE_SCORE.get(pulse)")]
    assert "channel_grade = pulse" in branch, \
        "the chip must be captured ABOVE the PULSE_SCORE lookup"


def test_both_tables_draw_the_channel_grade():
    """The shortlist table and the gainers/losers table. When only one
    was changed on a previous fix the two panels disagreed about the
    same stock, which is worse than either being wrong."""
    page = src(HTML)
    assert page.count("gradeChip(r)") == 2
    assert "GRADE_CLS[r.grade]" not in page, \
        "our grade is still being drawn as the symbol chip somewhere"


def test_the_publisher_is_named_on_the_hover():
    page = src(HTML)
    block = page[page.find("const gradeChip"):]
    block = block[:block.find("const breakoutRow")]
    assert "channel_grade_from" in block
    assert "r.channel_grade" in block


def test_a_missing_channel_grade_does_not_fall_back_to_ours():
    """The mismatch rule. A blank chip means no channel has called it;
    filling it with our arithmetic under their name is exactly what he
    ruled out."""
    page = src(HTML)
    block = page[page.find("const gradeChip"):]
    block = block[:block.find("const breakoutRow")]
    assert "r.grade" not in block


# ---------------------------------------------------------------
# 3. THE FIELD REACHES THE PANEL
# ---------------------------------------------------------------
def test_the_row_carries_the_channel_grade():
    code = src(SHORTLIST)
    assert '"channel_grade": channel_grade' in code
    assert '"channel_grade_from": channel_from' in code
    assert "channel_from = _source_name(event.get(\"source\"))" in code


def test_decorate_copies_it():
    """THE THIRD TIME. `support` on 31 July, `chain` on 2 August, both
    built and tested and invisible because this function copies fields
    one by one."""
    code = src(STATE)
    assert 'out["channel_grade"] = hit.get("channel_grade")' in code
    assert 'out["channel_grade_from"] = hit.get("channel_grade_from")' in code


def test_every_field_the_row_emits_survives_decorate():
    """The general form of the bug above, so the next new field is
    caught by this file rather than by the operator's eye."""
    code = src(SHORTLIST)
    block = code[code.find('ranked.append({'):]
    block = block[:block.find('ranked.sort(')]
    emitted = set(re.findall(r'"(chain\w*|channel_\w+)":', block))
    state = src(STATE)
    for field in sorted(emitted):
        assert f'out["{field}"] = hit.get("{field}")' in state, \
            f"{field} is built on the row and never copied to the panel"


# ---------------------------------------------------------------
# 4. OUR GRADE STILL SAYS IT IS OURS
# ---------------------------------------------------------------
def test_our_grade_chip_names_itself():
    code = src(SHORTLIST)
    assert 'label = f"OUR NUMBERS: {grade}"' in code


def test_the_drilldown_row_says_whose_grade_it_is():
    page = src(HTML)
    assert 'kv("Our grade (from the filing)"' in page
    assert 'kv("Grade"' not in page


# ---------------------------------------------------------------
# 5. FRESHNESS -- THE REASON THE CHANNEL WORD IS SAFER HERE
# ---------------------------------------------------------------
def test_the_channel_grade_comes_from_the_event_window():
    """APTUS carried a three-month-old GOOD beside "REPORTING TODAY".
    The channel verdict cannot do that: it is read from the same
    events list, which _events_for() bounds by EVENT_WINDOW_HOURS."""
    from core.shortlist import EVENT_WINDOW_HOURS
    assert 0 < EVENT_WINDOW_HOURS <= 24 * 14
    code = src(SHORTLIST)
    assert "hours=EVENT_WINDOW_HOURS" in code


def test_newest_wins_because_events_are_sorted_newest_first():
    """first_pulse is the FIRST RESULT event seen, so this only reads
    as "latest" while the query stays newest-first."""
    code = src(SHORTLIST)
    block = code[code.find("def _events_for"):]
    block = block[:block.find("AI_CHIP_ORDER")]
    assert "newest first" in block
