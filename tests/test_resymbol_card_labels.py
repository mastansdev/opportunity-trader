"""
==========================================================
Taking a symbol away, without losing a true one
==========================================================

    "still tagged CLEAN : 140"
                                    -- measured, 1 August 2026

CLEAN is Clean Science & Technology's real NSE ticker. It is also the
word every Earnings Brief prints when a quarter is honest:

    EARNINGS QUALITY | CLEAN

In capitals, so every guard in the matcher passed it, and 140 stored
messages carried a chemicals company's ticker -- among them D-Link's
Q1 card, NEUEON's, DEEPAKFERT's and NATIONALUM's.

core/telegram_feed.symbols_in() was fixed to strip the label before
matching. That fixes messages read AFTER the fix. This backfills the
ones already stored, and the backfill is the dangerous half.

WHY THE OBVIOUS FIX IS WRONG
----------------------------
tools/telegram_resymbol.py is ADD-ONLY, and says why:

    "A symbol already stored stays, whatever this pass thinks -- it may
     have come from a hashtag this text no longer carries, and losing a
     true link to fix a missing one is a bad trade."

That is right, and it is right about THIS too. Clean Science's own
news must survive:

    Clean Science inks 5-year supply deal with Kemin Industries. #CLEAN

Remove CLEAN wherever the label appears and that row loses its stock.

THE RULE THAT IS NARROW ENOUGH
------------------------------
A symbol is removed only when it DISAPPEARS once the card's own labels
are stripped. A real mention -- a hashtag, a name, the ticker anywhere
else in the message -- survives the strip, so it is never touched.

Measured on the store: 129 removed, 11 kept. Every one of the 129 is
another company's card. All 11 name Clean Science for real.

AND THE TRANSCRIPT COUNTS
-------------------------
The same pass read row["text"] only. Most results cards ARE the
picture -- caption on one line, numbers in the image -- so every
symbol named inside a card was invisible to it. 92 symbols recovered
by reading ocr_text as well.

Author : H&M Opportunity Trader
==========================================================
"""

import re

import pytest

from core.stock_events import _for_matching
from tools.telegram_resymbol import NOT_A_MENTION, symbols_for

KNOWN = {"CLEAN", "DLINKINDIA", "NEUEON", "DEEPAKFERT", "GHCL", "DOLLAR"}
TAGGED = {s for s in KNOWN if s not in NOT_A_MENTION}
PLAIN = {s for s in TAGGED if len(s) >= 3}


def artifacts(body):
    """The tool's rule, in one place so the test cannot drift from it."""
    if not body:
        return set()
    return (set(symbols_for(body, TAGGED, PLAIN))
            - set(symbols_for(_for_matching(body), TAGGED, PLAIN)))


def merged(before, body):
    """The tool's merge, deduped, in one place so this cannot drift."""
    gone = artifacts(body)
    after = symbols_for(_for_matching(body), TAGGED, PLAIN)
    out, seen = [], set()
    for symbol in list(before) + list(after):
        if symbol in gone or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


# ---------------------------------------------------------------
# 1. THE LABEL IS REMOVED
# ---------------------------------------------------------------
def test_a_card_label_is_not_a_company():
    """D-Link's Q1 card, filed against a chemicals company."""
    card = ("#DLINKINDIA - Q1 FY27 Solid start to the year.\n"
            "EARNINGS QUALITY | CLEAN DISTORTION FLAGS")
    assert artifacts(card) == {"CLEAN"}
    assert merged(["DLINKINDIA", "DLINKINDIA", "CLEAN"], card) == ["DLINKINDIA"]


@pytest.mark.parametrize("label", [
    "EARNINGS QUALITY | CLEAN",
    "EARNINGS QUALITY: CLEAN",
    "EARNINGS QUALITY - CLEAN",
    "EARNINGS QUALITY CLEAN",
    "Earnings Quality | CLEAN",
])
def test_the_label_is_recognised_however_it_is_punctuated(label):
    card = f"#NEUEON - Q1 FY27 Strong standalone.\n{label}\n"
    assert merged(["NEUEON", "CLEAN"], card) == ["NEUEON"]


def test_the_two_column_card_puts_the_verdict_on_the_next_line():
    """---- THE FIRST FIX MISSED THIS. 1 August 2026. ----

    The rule assumed the verdict sits beside its label. On a
    two-column card it does not -- the headings run along one line and
    the readings sit under them:

        EARNINGS QUALITY DISTORTION FLAGS ACCOUNTING - ONE-OFFS
        CLEAN

    so NITTAGELA's and PRICOLLTD's briefs were STILL filed against
    Clean Science after the backfill ran. Found only by reading all
    eleven survivors one at a time instead of trusting the count.

    This is the same mistake quality_signals() had already been taught
    not to make, and it was not carried across.
    """
    card = ("#NITTAGELA - Q1 FY27 Profit jumps 30% YoY.\n"
            "EARNINGS QUALITY DISTORTION FLAGS ACCOUNTING - ONE-OFFS\n"
            "CLEAN\n")
    assert artifacts(card) == {"CLEAN"}
    assert merged(["NITTAGELA", "CLEAN"], card) == ["NITTAGELA"]


def test_only_the_line_directly_beneath_counts():
    """A stray CLEAN three lines down is a different thing. Stripping
    it would be guessing, and guessing is how a true link is lost."""
    card = ("EARNINGS QUALITY DISTORTION FLAGS\n"
            "Some other reading entirely\n"
            "Another line here\n"
            "#CLEAN\n")
    assert artifacts(card) == set()


def test_a_lowercase_clean_was_never_the_problem():
    """"Earnings Quality | Clean" cannot have produced the tag in the
    first place -- symbols_for() requires capitals, which is what stops
    "dollar" becoming Dollar Industries. So there is nothing here to
    remove, and removing anything would be guessing."""
    card = "#NEUEON - Q1 FY27 Strong.\nEarnings Quality | Clean\n"
    assert artifacts(card) == set()


def test_the_duplicate_the_store_really_holds_is_collapsed():
    """The column holds "DLINKINDIA,DLINKINDIA" -- a card hashtagged
    twice. It means nothing extra, and downstream it broke the news
    table's de-duplication: ('X',) and ('X','X') are different
    tuples, so the same sentence printed twice in one row."""
    card = "#DLINKINDIA - Q1 FY27 Solid start.\n"
    assert merged(["DLINKINDIA", "DLINKINDIA"], card) == ["DLINKINDIA"]


# ---------------------------------------------------------------
# 2. A TRUE LINK IS NEVER LOST
# ---------------------------------------------------------------
def test_clean_sciences_own_news_keeps_its_stock():
    """THE ONE THAT MATTERS. Remove CLEAN wherever the label appears
    and this row loses the company it is about."""
    news = ("Clean Science inks 5-year supply deal with Kemin "
            "Industries. #CLEAN - 55 seconds ago")
    assert artifacts(news) == set()
    assert "CLEAN" in merged(["CLEAN"], news)


def test_clean_sciences_own_card_keeps_its_stock():
    """Its brief carries BOTH -- the hashtag and the label. The
    hashtag survives the strip, so the row survives."""
    card = ("#CLEAN - Q1 FY27 Profit down despite sales recovery.\n"
            "EARNINGS QUALITY | CLEAN\n")
    assert "CLEAN" in merged(["CLEAN"], card)


def test_a_digest_that_really_lists_the_stock_keeps_it():
    digest = ("Today Earnings - 01 Aug, 2026\n"
              "#GHCL #CLEAN #DLINKINDIA reporting today\n")
    assert "CLEAN" in merged(["GHCL", "CLEAN", "DLINKINDIA"], digest)


def test_an_unrelated_symbol_already_stored_is_left_alone():
    """ADD-ONLY still holds for everything that is not a proven label
    artifact -- a symbol may have come from a hashtag an edit removed."""
    body = "#GHCL - Q1 FY27 A good quarter.\n"
    assert "DEEPAKFERT" in merged(["GHCL", "DEEPAKFERT"], body)


# ---------------------------------------------------------------
# 3. THE TOOL READS THE PICTURE TOO
# ---------------------------------------------------------------
def test_the_backfill_reads_the_transcript_not_only_the_caption():
    """Most results cards ARE the picture. Reading row["text"] alone
    made every symbol named inside a card invisible -- 92 of them."""
    src = open("tools/telegram_resymbol.py", encoding="utf-8").read()
    body = src[src.index("def main("):]
    assert "ocr_text" in body, "the transcript is never read"
    assert "PRAGMA table_info" in body, (
        "an older store has no ocr_text column -- ask before selecting "
        "it, or the tool raises on the databases that need it most")


def test_the_removal_is_the_only_removal():
    """If this ever grows a second way to drop a symbol, the add-only
    promise stops being true and nobody will notice until a row loses
    its stock."""
    src = open("tools/telegram_resymbol.py", encoding="utf-8").read()
    body = src[src.index("def main("):]
    assert body.count("artifacts") >= 2
    assert "_label_artifacts" in body
    # The merge skips a symbol for exactly two reasons: it is a proven
    # label artifact, or it is already in the list. Anything else that
    # can drop a symbol has to be added here on purpose.
    assert "if symbol in artifacts or symbol in seen:" in body, (
        "the merge has grown another way to lose a symbol")


def test_a_message_with_no_text_at_all_does_not_raise():
    assert artifacts("") == set()
    assert artifacts(None) == set()
    assert merged([], "") == []
