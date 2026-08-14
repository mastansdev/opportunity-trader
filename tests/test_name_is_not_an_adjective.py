"""
==========================================================
A company name that was really an adjective
==========================================================

    "are we storing the results + order book (company receiving orders
     from whom and their size) + news attched to them?"
                                    -- operator, 1 August 2026

Checking that turned up this on the panel he clicks BUY from:

    symbol=AFCONS    Rs 900cr   "Afcons secures nearly Rs 900 crore..."
    symbol=URBANCO   Rs 900cr   "Afcons secures nearly Rs 900 crore..."

Urban Company was carrying Afcons's order.

HOW
---
_name_index() builds two ways to recognise a company in a screenshot:
a PAIR of the first two words, or a SOLO entry when the whole name is
one word. The solo branch guarded itself with

    elif len(tokens) == 1 and len(words[0]) >= 5:

and its own comment said "the whole name, not a rare fragment". But
`tokens` is the name AFTER _NAME_SUFFIX has been removed, and COMPANY
is in _NAME_SUFFIX:

    INDEGENE LIMITED        -> INDEGENE   a real one-word name
    URBAN COMPANY LIMITED   -> URBAN      an ADJECTIVE

So URBAN entered the index as a company name. Afcons's own
announcement says:

    "bolstering its position in India's URBAN infrastructure sector"

and the order was filed against URBANCO.

MEASURED, ON THE REAL STORE, BEFORE ANYTHING WAS CHANGED
--------------------------------------------------------
    messages tagged URBANCO          17
    genuinely name Urban Company      7
    FALSE                            10

The ten were Afcons (x2), a HUDCO concall, a Bajaj Finance one-off,
Aurionpro (x2), a CNBC margin item, a RedboxGlobal piece on Indian
cities, and an L&T Finance business update. Eight different companies.

WHY A DENYLIST AND NOT A RULE
-----------------------------
Of 392 solo entries only SIX are English words at all, and five of
those measured 100% genuine -- DOLLAR fired 37 times, every one a real
mention of Dollar Industries. A blanket rule against English-word
names would cost true matches to fix nothing. There is no offline
dictionary here to do better. So: an explicit set, and nothing enters
it that has not been counted first.

THE NAME IS NOT LOST
--------------------
Where suffix-stripping is what collapsed the name, the ORIGINAL first
two words are indexed as a pair instead. "Urban Company" still
matches; the bare adjective no longer does. That required fixing the
MATCHING side too -- names_in() strips _NAME_SUFFIX from the text as
well as from the name, so a pair ending in COMPANY was invisible to
it. Indexing a pair the matcher could never see would have been a fix
that silently did nothing.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.master_loader import MasterLoader
from core.telegram_feed import NOT_A_NAME, TelegramFeed


@pytest.fixture(scope="module")
def feed():
    loader = MasterLoader()
    loader.load()
    f = TelegramFeed.__new__(TelegramFeed)
    f.master_loader = loader
    for attr in ("_name_idx", "_names", "_name_cache",
                 "_symbols", "_symbols_tagged"):
        setattr(f, attr, None)
    return f


# The message that started it, verbatim from telegram.db.
AFCONS = ("Afcons Infrastr.\n"
          "Afcons Infrastructure secured two new projects\n"
          "worth nearly %900 crore in July, bolstering its\n"
          "position in India's urban infrastructure sector.\n"
          "This strategic win enhances the company's robust\n"
          "project portfolio and future growth prospects.")


# ---------------------------------------------------------------
# 1. THE BUG
# ---------------------------------------------------------------
def test_afcons_order_belongs_only_to_afcons(feed):
    """THE ONE THAT MATTERS. A Rs 900 crore order on the wrong stock,
    on the table he places real orders from."""
    got = feed.names_in(AFCONS)
    assert "AFCONS" in got
    assert "URBANCO" not in got, (
        "Urban Company is being matched from the word 'urban' in "
        "another company's announcement")


@pytest.mark.parametrize("prose", [
    "bolstering its position in India's urban infrastructure sector",
    "strengthens its position in urban transit technology across India",
    "Rural demand grew 170 basis points ahead of urban demand in Q1.",
    "the urban consumer is trading down",
])
def test_the_bare_adjective_never_names_a_company(feed, prose):
    assert "URBANCO" not in feed.names_in(prose)


# ---------------------------------------------------------------
# 2. THE COMPANY IS STILL FINDABLE
# ---------------------------------------------------------------
def test_the_full_name_still_matches(feed):
    """A fix that simply deleted the company would be a different bug.
    Both words, adjacent -- which is what tells the firm apart from
    the adjective."""
    assert "URBANCO" in feed.names_in(
        "Urban Company reports Q1 revenue up 22% YoY")


def test_the_pair_is_indexed_not_just_dropped(feed):
    idx = feed._name_index()
    assert idx["pairs"].get(("URBAN", "COMPANY")) == "URBANCO"
    assert "URBAN" not in idx["solo"]


def test_the_matcher_can_actually_see_a_suffix_ending_pair(feed):
    """names_in() strips _NAME_SUFFIX from the TEXT too, so a pair
    ending in COMPANY is invisible to the stripped word list. The
    first version of this fix indexed the pair and stopped there --
    the index was right and nothing matched."""
    assert "COMPANY" in TelegramFeed._NAME_SUFFIX
    assert "URBANCO" in feed.names_in("Urban Company Ltd Q1 results")


# ---------------------------------------------------------------
# 3. NOTHING ELSE WAS SWEPT UP
# ---------------------------------------------------------------
@pytest.mark.parametrize("symbol,text", [
    # Measured 37 fired, 37 genuine, 0 false. Must not be touched.
    ("DOLLAR", "Dollar Industries posts strong Q1"),
    # A real one-word name -- the case the solo branch exists for.
    ("INDGN", "Indegene Limited announces results"),
    ("TITAN", "Titan Company Q1 revenue up"),
    ("TRENT", "Trent reports strong same-store growth"),
])
def test_the_genuine_one_word_names_still_work(feed, symbol, text):
    assert symbol in feed.names_in(text), (
        f"{symbol} was collateral damage -- only URBAN measured false")


def test_two_word_names_are_unaffected(feed):
    assert "AARTIIND" in feed.names_in("Aarti Industries Ltd reports results")


def test_the_denylist_is_small_and_deliberate():
    """It is a denylist, and denylists grow by habit. This fails if
    somebody adds a word without the measurement that earns it -- the
    docstring above is where the count goes."""
    assert NOT_A_NAME == {"URBAN"}, (
        "a word was added to NOT_A_NAME. Every entry must be measured "
        "against the stored corpus first: of 392 one-word name entries "
        "only six are English words, and five of those were 100% "
        "genuine. Removing a real name to fix a hypothetical is a bad "
        "trade.")


# ---------------------------------------------------------------
# 4. THE CLEAN-UP TOOL
# ---------------------------------------------------------------
def test_the_purge_tool_re_runs_the_matcher_rather_than_guessing():
    src = open("tools/purge_bad_name_links.py", encoding="utf-8").read()
    assert "feed.symbols_in" in src and "feed.names_in" in src, (
        "the tool must decide with today's matcher, not a keyword")


def test_the_purge_tool_keeps_a_genuine_link():
    """7 of the 17 really did name Urban Company. A tool that removed
    all 17 would be the same class of error in the other direction."""
    src = open("tools/purge_bad_name_links.py", encoding="utf-8").read()
    assert "keep_msgs" in src
    assert "if symbol in fresh:" in src


def test_the_purge_tool_defaults_to_a_dry_run():
    src = open("tools/purge_bad_name_links.py", encoding="utf-8").read()
    assert '"--apply"' in src
    assert "DRY RUN" in src


def test_the_purge_tool_derives_its_targets_from_the_denylist():
    """Hardcoding URBANCO would mean the next word added to NOT_A_NAME
    silently leaves its bad rows behind."""
    src = open("tools/purge_bad_name_links.py", encoding="utf-8").read()
    assert "NOT_A_NAME" in src
    assert "def suspects" in src
