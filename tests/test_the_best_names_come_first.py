"""
==========================================================
Four names out of ninety, not buried in sixty
==========================================================

    "do u support your way of working? watchlist is just like bot
     decision first come = first serve. no & never. some stocks had
     exceptional chip, strong chip, Mixed, weak, Mixed buy, Mixed
     Wait, but no refining of these. in general Exceptional, Strong
     stocks will be in primary focus in any table or any where. buy in
     our watchlist nothing like that all are same. NEVER TREAT WEAK =
     EXCEPTIONAL OR STRONG. prioritise the stocks move by forwarding,
     highlighting those names."
                                    -- operator, 2 August 2026

He is right, and the defence for the old behaviour was that there
wasn't one. Every bucket sorted by SYMBOL:

    AADHARHFC  ABB  ABLBL  APLAPOLLO  BLUEDART ...   and DIVISLAB,
    the one EXCEPTIONAL name on a list of sixty, sat at position 24.

Nothing in this project asserted that order, which is why nothing
broke when it changed. It was never a decision -- it was the default.

THE ORDER, ONCE, USED BY EVERY LIST
-----------------------------------
    1  tier      EXCEPTIONAL  STRONG  MIXED  WEAK  (then unrated)
    2  call      BUY  WAIT  (unread)  AVOID
    3  the rest  recency where it applies, then symbol

TIER LEADS, on his instruction. The call settles ties inside a tier.

TWO THINGS DELIBERATELY NOT DONE
--------------------------------
AVOID is not hidden. It sorts last inside its tier and is drawn
quieter, so it cannot be mistaken for something to act on -- but an
answered question is information and throwing it away is the one rule
this project keeps.

A stock with NO tier does not sort as WEAK. The ratings export covers
90 names; the master holds 1,245. "Nobody has rated it" and "the three
frameworks disagree" are different facts and ranking them together
would be inventing a judgement nobody made.

WEAK IS ALSO NOT DIMMED
-----------------------
Their own guide: the tier counts how many of three frameworks AGREE.
WEAK means they disagree, not that the company is bad -- and their PDF
says a Weak-tagged stock with a green 360 brief can still be on the
ratings list. Fading it would assert something they do not.

Author : H&M Opportunity Trader
==========================================================
"""

import sqlite3

import pytest

from core.canslim import NO_TIER, TIERS, tier_rank
from core.chain import AVOID, BUY, WAIT, call_rank
from core.reporting import DURING, watchlist
from core.watchlist import RESULTS, build


# ---------------------------------------------------------------
# 1. THE ORDER ITSELF
# ---------------------------------------------------------------
def test_the_tiers_rank_in_their_own_order():
    ranks = [tier_rank(t) for t in TIERS]
    assert ranks == sorted(ranks)
    assert tier_rank("EXCEPTIONAL") < tier_rank("STRONG") < \
        tier_rank("MIXED") < tier_rank("WEAK")


def test_weak_is_never_treated_as_exceptional():
    """His sentence, as an assertion."""
    assert tier_rank("WEAK") != tier_rank("EXCEPTIONAL")
    assert tier_rank("WEAK") != tier_rank("STRONG")


def test_an_unrated_stock_sits_between_mixed_and_weak():
    """A JUDGEMENT, and it is documented as one in core/canslim.py.

    The export covers 90 names; the master holds 1,245. WEAK means the
    three frameworks examined the stock and CONFLICTED. Unrated means
    nobody looked. Ranking an examined-and-conflicted name above an
    unexamined one asserts something nobody measured -- so unrated
    sits above WEAK and below MIXED.

    The counter-argument is real and is written down beside the dict:
    that export is his own TradingView screen, so a missing name is a
    name his screen did not pick up. If he overrules this, TIER_ORDER
    is the only thing that changes and this test is where it is
    recorded."""
    assert tier_rank(None) == tier_rank("") == NO_TIER
    assert tier_rank("MIXED") < tier_rank(None) < tier_rank("WEAK")


def test_the_lookup_is_not_case_or_space_sensitive():
    assert tier_rank(" exceptional ") == 0


def test_a_buy_leads_and_an_avoid_sinks_below_an_unread_name():
    """An unread name is a question. An AVOID is an answer, and it is
    the one answer that must not sit at the top of a list he is
    scanning for something to buy."""
    assert call_rank(BUY) < call_rank(WAIT) < call_rank(None) < \
        call_rank(AVOID)


# ---------------------------------------------------------------
# 2. THE LISTS ACTUALLY USE IT
# ---------------------------------------------------------------
@pytest.fixture
def db(tmp_path):
    path = tmp_path / "events.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE events (symbol TEXT, kind TEXT, headline TEXT)")
    rows = [(s, "REPORTED", h) for s, h in [
        # deliberately alphabetical-worst: the good names sort last
        ("ZZWEAK", "REPORTS DURING THE SESSION (03 Aug) -- live today"),
        ("AAWEAK", "REPORTS DURING THE SESSION (03 Aug) -- live today"),
        ("MMTOP", "REPORTS DURING THE SESSION (03 Aug) -- live today"),
        ("NNSTRONG", "REPORTS DURING THE SESSION (03 Aug) -- live today"),
        ("AAUNRATED", "REPORTS DURING THE SESSION (03 Aug) -- live today"),
        ("AAEXC", "REPORTED AFTER CLOSE (30 Jul) -- not yet priced "
                  "by the market"),
        ("ZZEXC", "REPORTED AFTER CLOSE (31 Jul) -- not yet priced "
                  "by the market"),
        ("AAMIX", "REPORTED AFTER CLOSE (31 Jul) -- not yet priced "
                  "by the market"),
    ]]
    conn.executemany("INSERT INTO events VALUES (?,?,?)", rows)
    conn.commit()
    conn.close()
    return str(path)


TIERS_MAP = {"MMTOP": "EXCEPTIONAL", "NNSTRONG": "STRONG",
             "AAWEAK": "WEAK", "ZZWEAK": "WEAK",
             "AAEXC": "EXCEPTIONAL", "ZZEXC": "EXCEPTIONAL",
             "AAMIX": "MIXED"}


def test_the_forward_bucket_leads_with_the_best_tier(db):
    from datetime import date
    view = watchlist(events_db=db, on=date(2026, 8, 3), tiers=TIERS_MAP)
    got = [r["symbol"] for r in view["reporting_today"][DURING]]
    assert got[0] == "MMTOP", f"EXCEPTIONAL is not first: {got}"
    assert got[1] == "NNSTRONG"
    # the two WEAK names sort last, and alphabetically between them
    assert got[-2:] == ["AAWEAK", "ZZWEAK"]
    # unrated sits below STRONG and above the two WEAK names
    assert got.index("NNSTRONG") < got.index("AAUNRATED") < \
        got.index("AAWEAK")


def test_the_call_settles_a_tie_inside_one_tier(db):
    from datetime import date
    view = watchlist(events_db=db, on=date(2026, 8, 3), tiers=TIERS_MAP,
                     calls={"ZZWEAK": BUY, "AAWEAK": AVOID})
    got = [r["symbol"] for r in view["reporting_today"][DURING]]
    assert got.index("ZZWEAK") < got.index("AAWEAK"), (
        "a BUY must outrank an AVOID inside the same tier, whatever "
        "the alphabet says")


def test_the_unpriced_list_leads_with_the_tier_not_the_date(db):
    """THE ONE THAT MATTERS -- sixty names, and this is the list the
    operator scans before the open. AAEXC reported a day EARLIER than
    AAMIX and still comes first, because "most recent" is not the same
    as "worth looking at"."""
    from datetime import date
    view = watchlist(events_db=db, on=date(2026, 8, 3), tiers=TIERS_MAP)
    got = [r["symbol"] for r in view["unpriced_from_last_close"]]
    assert got[:2] == ["ZZEXC", "AAEXC"], got
    assert got[-1] == "AAMIX"


def test_recency_still_breaks_a_tie_within_one_tier(db):
    from datetime import date
    view = watchlist(events_db=db, on=date(2026, 8, 3), tiers=TIERS_MAP)
    rows = {r["symbol"]: r for r in view["unpriced_from_last_close"]}
    assert rows["ZZEXC"]["on"] > rows["AAEXC"]["on"], "fixture assumption"
    got = [r["symbol"] for r in view["unpriced_from_last_close"]]
    assert got.index("ZZEXC") < got.index("AAEXC"), (
        "inside one tier the newer report should still come first")


def test_the_catalyst_list_carries_the_same_order(db):
    from datetime import date
    view = watchlist(events_db=db, on=date(2026, 8, 3), tiers=TIERS_MAP)
    rows = [r for r in build(results_view=view) if r["when"] == "today"]
    got = [r["symbol"] for r in rows]
    assert got[0] == "MMTOP", got
    assert got.index("NNSTRONG") < got.index("AAWEAK")


def test_the_order_is_stable_between_refreshes(db):
    """The symbol is the last key on purpose. A list that reshuffles
    two equal names on every poll is a list nobody can learn."""
    from datetime import date
    a = watchlist(events_db=db, on=date(2026, 8, 3), tiers=TIERS_MAP)
    b = watchlist(events_db=db, on=date(2026, 8, 3), tiers=TIERS_MAP)
    assert ([r["symbol"] for r in a["reporting_today"][DURING]] ==
            [r["symbol"] for r in b["reporting_today"][DURING]])


# ---------------------------------------------------------------
# 3. THE PANEL FORWARDS AND HIGHLIGHTS
# ---------------------------------------------------------------
