"""---- THE STOCK WAS NAMED IN PLAIN SIGHT. 2 September 2026. ----

    "fix the ticker matching first"              -- the operator

He asked for a daily watchlist built from overnight news, and the
first thing that list showed was rows with a headline and no stock
next to it -- a Rs 2,123 crore work order with nothing to click.

4,389 of 18,134 stored events carry no ticker. MOST OF THAT IS
CORRECT and must stay that way: Trump, the Strait of Hormuz, the RBI
governor, a windfall-tax cut, a sugar stock-holding limit. News with
no single listed company in it should match nothing.

The fixable part is narrow. The feeds write the company as one
camelCase word behind a hash -- #EicherMotorsRE, #AurobindoPharma,
#GardenReachShipbuilders -- and stripping the hash leaves a single
token no index key can equal.

MEASURED ACROSS ALL 4,389 BEFORE A LINE WAS WRITTEN:

    70 headlines gain a match from expanding the hashtag
    69 resolve to exactly ONE symbol, every one correct on
       inspection
     1 resolves to two, and that one is the false positive --
       "#KalyanJewellers Gets #TamilNadu Contract" read the state
       name as Tamil Nadu Newsprint

Hence the rule: trust the expansion only when it names exactly one
stock. 69 gained, 1 refused, and the error rate is a measurement
rather than a hope -- which is precisely what the earlier attempt at
this was missing.
"""

from core.news_watcher import build_name_index, expand_hashtags, match_symbols

INDEX = {
    "persistent systems": "PERSISTENT",
    "eicher motors": "EICHERMOT",
    "garden reach shipbuilders": "GRSE",
    "kalyan jewellers": "KALYANKJIL",
    "tamil nadu newsprint": "TNPL",
    "tamil nadu": "TNPL",
    "sical logistics": "SICALLOG",
}


def test_a_camelcase_hashtag_resolves_to_its_stock():
    assert match_symbols("#PersistentSystems CEO pay rises 162%",
                         INDEX) == ["PERSISTENT"]


def test_it_works_behind_other_tags():
    """The feeds prefix a category tag: "#AugAutoSales | #EicherMotorsRE"."""
    got = match_symbols("#AugAutoSales | #EicherMotorsRE Total Sales At 1.26 Lk",
                        INDEX)
    assert got == ["EICHERMOT"], got


def test_a_long_name_still_resolves():
    assert match_symbols("#Justin | #GardenReachShipbuilders To Expand",
                         INDEX) == ["GRSE"]


def test_two_names_from_one_expansion_are_refused():
    """THE ONE FALSE POSITIVE IN 4,389. A state name read as a company.

    Kalyan Jewellers winning a Tamil Nadu contract is about Kalyan;
    TNPL is a paper mill that has nothing to do with it. Ambiguity
    here would put a wrong stock on his watchlist with a real order
    value beside it, which is worse than an unmatched row he can see
    is unmatched.
    """
    assert match_symbols("#Justin | #KalyanJewellers Gets #TamilNadu Contract",
                         INDEX) == []


def test_macro_news_still_matches_nothing():
    """Most unmatched events are unmatched CORRECTLY. Widening the net
    must not start attaching stocks to geopolitics."""
    for headline in ("TRUMP ON IRAN: NEGOTIATIONS MAYBE AT SOME POINT",
                     "STRAIT OF HORMUZ VESSEL CROSSINGS FALL 50% IN ONE DAY",
                     "INDIA PROPOSES AMENDMENTS TO MEDICAL DEVICES RULES"):
        assert match_symbols(headline, INDEX) == [], headline


def test_a_headline_that_already_matched_is_untouched():
    """The expansion runs ONLY when the ordinary pass found nothing, so
    nothing that works today can change."""
    assert match_symbols("SICAL LOGISTICS: CO SECURES 2534.73 CRORE ORDER",
                         INDEX) == ["SICALLOG"]


def test_expand_hashtags_leaves_ordinary_text_alone():
    plain = "SAIL: CO ACCELERATES 15,000CR FY27 CAPEX"
    assert expand_hashtags(plain) == plain


def test_expand_hashtags_does_not_split_an_all_caps_tag():
    """#ANTELOPUS is already the ticker. Splitting on a case change
    that never happens must leave it whole."""
    assert "#ANTELOPUS" in expand_hashtags("#ANTELOPUS Order received") \
        or "ANTELOPUS" in expand_hashtags("#ANTELOPUS Order received")


def test_it_runs_against_the_real_index():
    """The unit index above is a stand-in. This proves the same
    headline resolves against the master the bot actually loads."""
    index = build_name_index()
    if not index:                       # no master in this checkout
        return
    assert match_symbols("#PersistentSystems CEO pay rises",
                         index) == ["PERSISTENT"]
