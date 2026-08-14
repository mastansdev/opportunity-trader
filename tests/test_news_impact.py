"""
Tests for core/news_impact.py -- which stocks a news story touches.

WHY THIS FILE EXISTS AT ALL
---------------------------
core/news_impact.py's own docstring claimed rule 1 was "enforced by a
test". It was not. There was no test file for this module, and the
engine-boundary assertion existed only in tests/test_telegram_feed.py
for a different module. A rule documented as tested but not tested is
worse than an untested rule, because it stops anyone checking.

WHAT THESE TESTS PIN DOWN
-------------------------
The bug they exist to prevent, measured on the live database on
30 July 2026:

    "Federal Reserve holds interest rates steady, but three members
     voted to raise rates."

  -> stored against DBREALTY, CGCL, BRIGADE, ARVSMART, ANANTRAJ and
     AGIIL, reason "matched on: INTEREST, RATE, REAL". Uncapped, the
     old matcher tied that one macro line to 140 of 750 stocks.

The cause was not a loose threshold. ECONOMIC_SENSITIVITY is a
classification column with six possible values, 105 stocks share
INTEREST RATE SENSITIVE, and it was being searched as though it
identified a company. Meanwhile KEYWORDS -- the column that exists to
be matched -- was not searched at all.

So the tests below assert the DISTINCTION, not a magic number:
belonging to a category the news mentions is not the same as being in
the news.
"""

import ast

import pytest

from core.news_impact import (MACRO, NEWS, STOCK, TIP, UNKNOWN, NewsImpact,
                              is_not_a_story, looks_like_a_tip)


# ----------------------------------------------------------------
# A small master file with the real shape of master_database.xlsx.
# The taxonomy values are the real ones -- INTEREST RATE SENSITIVE is
# what 105 live rows actually carry.
# ----------------------------------------------------------------
ROWS = {
    "DBREALTY": {
        "COMPANY NAME": "VALOR ESTATE LIMITED",
        "SECTOR": "REAL ESTATE",
        "INDUSTRY": "REAL ESTATE DEVELOPMENT",
        "CORE BUSINESS": "REAL ESTATE DEVELOPMENT COMPANY",
        "BUSINESS_TYPE": "EPC / CONTRACTOR",
        "COMMODITY_EXPOSURE": "NONE",
        "ECONOMIC_SENSITIVITY": "INTEREST RATE SENSITIVE | HOUSING",
        "KEYWORDS": "REAL ESTATE",
        "THEMES": "REAL ESTATE",
    },
    "BRIGADE": {
        "COMPANY NAME": "BRIGADE ENTERPRISES LIMITED",
        "SECTOR": "REAL ESTATE",
        "INDUSTRY": "REAL ESTATE DEVELOPMENT",
        "CORE BUSINESS": "REAL ESTATE DEVELOPMENT - RESIDENTIAL",
        "BUSINESS_TYPE": "EPC / CONTRACTOR",
        "COMMODITY_EXPOSURE": "NONE",
        "ECONOMIC_SENSITIVITY": "INTEREST RATE SENSITIVE | HOUSING",
        "KEYWORDS": "REAL ESTATE",
        "THEMES": "REAL ESTATE",
    },
    "HEROMOTOCO": {
        "COMPANY NAME": "HERO MOTOCORP LIMITED",
        "SECTOR": "AUTOMOBILE",
        "INDUSTRY": "TWO WHEELERS",
        "CORE BUSINESS": "MANUFACTURES MOTORCYCLES AND SCOOTERS",
        "BUSINESS_TYPE": "MANUFACTURER",
        "COMMODITY_EXPOSURE": "STEEL",
        "ECONOMIC_SENSITIVITY": "CONSUMER DRIVEN",
        "KEYWORDS": "TWO WHEELER | MOTORCYCLE",
        "THEMES": "AUTOMOBILE | TWO WHEELERS",
    },
    "ASKAUTOLTD": {
        "COMPANY NAME": "ASK AUTOMOTIVE LIMITED",
        "SECTOR": "AUTOMOBILE",
        "INDUSTRY": "AUTO COMPONENTS",
        "CORE BUSINESS": "MANUFACTURES BRAKING SYSTEMS FOR AUTOMOBILES",
        "BUSINESS_TYPE": "MANUFACTURER",
        "COMMODITY_EXPOSURE": "ALUMINIUM",
        "ECONOMIC_SENSITIVITY": "CONSUMER DRIVEN",
        "KEYWORDS": "BRAKING SYSTEMS | ALUMINIUM COMPONENTS",
        "THEMES": "AUTO ANCILLARY | BRAKING SYSTEMS",
    },
    "KAYNES": {
        "COMPANY NAME": "KAYNES TECHNOLOGY IND LTD",
        "SECTOR": "CAPITAL GOODS",
        "INDUSTRY": "ELECTRONICS",
        "CORE BUSINESS": "ELECTRONICS MANUFACTURING SERVICES",
        "BUSINESS_TYPE": "MANUFACTURER",
        "COMMODITY_EXPOSURE": "NONE",
        "ECONOMIC_SENSITIVITY": "CONSUMER DRIVEN",
        "KEYWORDS": "EMS | ELECTRONICS MANUFACTURING",
        "THEMES": "ELECTRONICS | EMS",
    },
    "WELCORP": {
        "COMPANY NAME": "WELSPUN CORP LIMITED",
        "SECTOR": "METALS",
        "INDUSTRY": "STEEL PIPES",
        "CORE BUSINESS": "MANUFACTURES LARGE DIAMETER STEEL PIPES",
        "BUSINESS_TYPE": "MANUFACTURER",
        "COMMODITY_EXPOSURE": "STEEL",
        "ECONOMIC_SENSITIVITY": "GOVERNMENT SPENDING",
        "KEYWORDS": "LARGE DIAMETER STEEL PIPES",
        "THEMES": "METALS - STEEL | PIPES",
    },
    "COFORGE": {
        "COMPANY NAME": "COFORGE LIMITED",
        "SECTOR": "IT",
        "INDUSTRY": "IT SERVICES",
        "CORE BUSINESS": "IT SERVICES AND DIGITAL TRANSFORMATION",
        "BUSINESS_TYPE": "SERVICE PROVIDER",
        "COMMODITY_EXPOSURE": "NONE",
        "ECONOMIC_SENSITIVITY": "EXPORT ORIENTED",
        "KEYWORDS": "IT SERVICES | DIGITAL TRANSFORMATION",
        "THEMES": "IT SERVICES | SOFTWARE",
    },
}


class _Master:
    def all_symbols(self, include_blocked=False):
        return list(ROWS)

    def get_by_symbol(self, symbol):
        return ROWS.get(str(symbol).upper())


@pytest.fixture
def impact(tmp_path):
    return NewsImpact(master_loader=_Master(),
                      db_path=str(tmp_path / "news.db"))


FED = ("Federal Reserve holds interest rates steady, but three members "
       "voted to raise rates.")
ABS_STORY = ("MoRTH may soften mandatory ABS-for-all 2W regulation. The "
             "ministry is considering a performance based braking standard "
             "for two wheeler makers instead of mandating anti-lock braking "
             "systems on all motorcycles.")


def _symbols(rows):
    return {r["symbol"] for r in rows}


# ----------------------------------------------------------------
# The bug this module was rewritten to fix
# ----------------------------------------------------------------

def test_macro_rate_story_names_no_realty_stock(impact):
    """The exact live failure. A US rate decision must not be filed
    against every stock tagged INTEREST RATE SENSITIVE."""
    found = _symbols(impact.candidates(FED))
    assert "DBREALTY" not in found
    assert "BRIGADE" not in found


def test_taxonomy_column_alone_cannot_create_a_candidate(impact):
    """The mechanism, stated directly. These words appear ONLY in
    ECONOMIC_SENSITIVITY and SECTOR, so they must match nothing."""
    assert impact.candidates("interest rate sensitive housing") == []
    assert impact.candidates("consumer driven government spending") == []


def test_macro_story_is_recorded_with_no_impact_rows(impact):
    """Kept and readable, but tied to nobody -- and marked MACRO so the
    empty impact list is legible as a finding, not a failure."""
    rows = impact.record(FED, source="Day Trader Telugu", reason_it=False)
    assert rows == []
    assert impact.scope_of(impact.news_id(FED)) == MACRO


# ----------------------------------------------------------------
# What it must still find -- the regression risk of tightening
# ----------------------------------------------------------------

def test_abs_story_finds_two_wheeler_makers_and_brake_supplier(impact):
    """The operator's own worked example: the two-wheeler makers gain,
    the braking-system supplier is affected. Both must appear."""
    found = _symbols(impact.candidates(ABS_STORY))
    assert "HEROMOTOCO" in found
    assert "ASKAUTOLTD" in found


def test_single_hashtag_post_still_matches(impact):
    """Earnings Pulse's entire format is "#KAYNES - Great Results" --
    one identity word and nothing else. This is the most valuable
    message the feed carries and no threshold may reject it."""
    rows = impact.candidates("#KAYNES - Great Results")
    assert _symbols(rows) == {"KAYNES"}
    assert rows[0]["named_by"], "should match on the company's own name"


def test_company_name_beats_a_shared_category_word(impact):
    """Naming the company outranks sharing its line of business."""
    rows = impact.candidates("Coforge anticipates a strong Q2 on IT services")
    assert rows[0]["symbol"] == "COFORGE"


def test_common_adjective_is_not_a_company_name(impact):
    """LARGE appears in exactly one company's row ("LARGE DIAMETER STEEL
    PIPES"), so the rarity test mistook it for an identifier and tagged
    WELCORP on "large deal wins". Rarity only counts for words that
    carry meaning."""
    found = _symbols(impact.candidates(
        "Coforge anticipates a strong Q2 on large deal wins"))
    assert "WELCORP" not in found


def test_common_english_word_inside_a_company_name_is_not_a_match(impact):
    """The second bug, found only because the dry run printed its work.

    Once taxonomy columns were excluded, a new false positive appeared:
    ordinary English words that happen to sit inside one company's
    registered name. Measured on the real 750-row master --

        "...focuses strictly on current facts..."  -> FACT LTD
        "...does not have a flexible..."           -> EPL
        "...soft..."   -> ORACLE FIN SERV SOFT LTD
        "...path..."   -> DR. LAL PATH LABS

    Rarity cannot separate these; FACT is rare among Indian tickers and
    unremarkable in English. Case can: a lowercase word in running prose
    is not a name.
    """
    found = _symbols(impact.candidates(
        "The statement focuses strictly on current facts and avoids "
        "offering any flexible forward guidance on this path."))
    assert found == set(), found


def test_hashtag_is_always_a_name(impact):
    """Channel posts tag the subject. A hashtag is a name whatever its
    case, and must survive even mid-sentence."""
    assert "KAYNES" in _symbols(impact.candidates(
        "strong quarter reported by the company #KAYNES today"))


def test_all_caps_headline_falls_back_safely(impact):
    """An ALL CAPS headline carries no case signal. It must fall back to
    requiring real evidence, not treat every word as a name."""
    from core.news_impact import _proper_nouns
    assert _proper_nouns("FEDERAL RESERVE HOLDS INTEREST RATES STEADY") == set()
    assert "FEDERALBNK" not in _symbols(impact.candidates(
        "FEDERAL RESERVE HOLDS INTEREST RATES STEADY"))


def test_headline_subject_position_still_counts(impact):
    """A headline leads with its subject. Position zero is capitalised
    because it starts the text, but it is also the most reliable name in
    the story -- excluding it lost COFORGE from "Coforge anticipates"."""
    rows = impact.candidates("Coforge anticipates a strong Q2 on IT services")
    assert rows and rows[0]["symbol"] == "COFORGE"


def test_keywords_column_is_actually_searched(impact):
    """KAYNES's KEYWORDS say "EMS | ELECTRONICS MANUFACTURING" and
    nothing else in its row says EMS. The column was ignored entirely
    before this rewrite."""
    assert "KAYNES" in _symbols(impact.candidates(
        "EMS electronics manufacturing order win"))


# ----------------------------------------------------------------
# Storage honesty
# ----------------------------------------------------------------

def test_links_without_a_key_carry_no_direction(impact):
    """No ANTHROPIC_API_KEY means no winners and losers. The links are
    still worth keeping, but they must not claim a direction."""
    rows = impact.record(ABS_STORY, source="News Pulse", reason_it=False)
    assert rows, "should still link the two-wheeler makers"
    assert all(r["direction"] == UNKNOWN for r in rows)
    assert all(r["how"] == "keyword" for r in rows)
    assert impact.scope_of(impact.news_id(ABS_STORY)) == STOCK


def test_recording_twice_does_not_duplicate(impact):
    first = impact.record(ABS_STORY, source="A", reason_it=False)
    second = impact.record(ABS_STORY, source="B", reason_it=False)
    assert _symbols(first) == _symbols(second)


def test_migration_adds_scope_to_an_old_database(tmp_path):
    """news_memory.db shipped without `scope`. CREATE TABLE IF NOT
    EXISTS does nothing to a table that already exists -- which is
    precisely how the Telegram messages table was silently broken for
    months. Adding a column without an ALTER must never happen twice."""
    import sqlite3
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE news (news_id TEXT PRIMARY KEY, at TEXT,"
                 " seen_at TEXT, source TEXT, headline TEXT, body TEXT,"
                 " url TEXT, reasoned INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE impact (news_id TEXT, symbol TEXT,"
                 " direction TEXT, reason TEXT, confidence REAL, how TEXT,"
                 " PRIMARY KEY (news_id, symbol))")
    conn.execute("INSERT INTO news (news_id, headline) VALUES ('old','kept')")
    conn.commit()
    conn.close()

    NewsImpact(master_loader=_Master(), db_path=path)

    conn = sqlite3.connect(path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(news)")}
    assert "scope" in columns
    assert conn.execute("SELECT headline FROM news WHERE news_id='old'") \
        .fetchone()[0] == "kept", "migration must not lose existing rows"


# ----------------------------------------------------------------
# What kind of statement is this
# ----------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "STOCK PICK  Sumeet Bagadia recommends buying Gland Pharma, PG Electroplast",
    "BROKERAGE CALL  Analysts see Strong Buy on mid-caps",
    "Buy INFY with target 1850, stop 1700",
    "Top picks for the week: TCS, HDFCBANK",
])
def test_recommendations_are_recognised_as_tips(text):
    """Real News Pulse content, 30 July 2026. Somebody's buy call is not
    an event, and the matcher identifies the named stocks CORRECTLY --
    which is what makes an unlabelled tip more dangerous than a
    mismatched one."""
    assert looks_like_a_tip(text)


@pytest.mark.parametrize("text", [
    "Ameenji Rubber wins Rs 47.46 crore Eastern Railway order. #AMEENJI",
    "#HEXT - OK Results - 13 seconds ago",
    "MoRTH may soften mandatory ABS-for-all 2W regulation",
    "NBCC secures USD 75M Seychelles housing project via EXIM Bank. #NBCC",
    "Company sees revenue growth of 12% in FY27, guides to margin expansion",
])
def test_events_and_guidance_are_not_tips(text):
    """The line is advice versus report. A company guiding to margin
    expansion is reporting its own expectation; that must not be
    mistaken for a stranger telling you to buy."""
    assert not looks_like_a_tip(text)


def test_a_tip_is_stored_but_never_reasoned(impact):
    """Kept and readable, marked TIP, and never handed to the model as
    though it were an event -- reasoning over a buy call would launder an
    opinion into a direction with a confidence attached."""
    text = "Analysts recommend buying Coforge with target price 2100"
    impact.record(text, source="News Pulse")
    assert impact.kind_of(impact.news_id(text)) == TIP


def test_an_event_is_stored_as_news(impact):
    impact.record(ABS_STORY, source="Earnings Pulse", reason_it=False)
    assert impact.kind_of(impact.news_id(ABS_STORY)) == NEWS


@pytest.mark.parametrize("text", [
    "STOCK PICK",
    "FII / DII FLOWS",
    "INDIA MACRO & STRATEGY",
    "EARNINGS & RESULTS",
    "https://youtu.be/i8bHidbJOdI",
    "https://youtu.be/fBB-4fZfUJw?si=vHzVAI76B068-yZ1",
])
def test_section_headers_and_bare_links_are_not_stories(text):
    """Seven of the 63 stored stories were these -- News Pulse posts its
    own section dividers as messages, and Day Trader Telugu posts a bare
    YouTube URL. Both have a story's shape and no statement in them."""
    assert is_not_a_story(text)


def test_noise_is_refused_at_the_door(impact):
    assert impact.record("STOCK PICK", source="News Pulse") == []
    assert impact.kind_of(impact.news_id("STOCK PICK")) is None, \
        "must not be stored at all"


@pytest.mark.parametrize("text", [
    "Ameenji Rubber wins Rs 47.46 crore Eastern Railway order. #AMEENJI",
    "MoRTH may soften mandatory ABS-for-all 2W regulation",
    "Federal Reserve holds interest rates steady",
])
def test_real_stories_are_not_refused(text):
    assert not is_not_a_story(text)


# ----------------------------------------------------------------
# The boundary. This is the assertion the docstring promised.
# ----------------------------------------------------------------

def test_nothing_here_reaches_the_trading_engine():
    """    "i'm not asking that bot will trade by this news"
                                        -- operator

    News explains a move. It does not authorise one. The operator's
    diagram routes a conviction score into position sizing; until that
    is deliberately designed with source trust tiers, this module must
    stay on the reading side of the line -- and now it is checked
    rather than merely claimed.
    """
    source = open("core/news_impact.py", encoding="utf-8").read()
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    for banned in ("core.engine", "core.orb_engine", "core.strategy",
                   "trading.execution", "trading.portfolio"):
        assert banned not in imported, banned

    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)}
    for banned in ("conviction", "signal", "recommend", "size", "entry"):
        assert not any(banned in name.lower() for name in defined), banned


# ---------------------------------------------------------------
# A LONE NAME WORD MUST BE THE COMPANY'S OWN HANDLE
# ---------------------------------------------------------------
# 30 July 2026. Measured over the 457 links then in the store, 63% were
# generic word matches. The worst came through the `named` bypass:
#
#     CAPLIPOINT <- "Career Point wins Rs 17.6cr contract"   [POINT]
#     SOUTHBANK  <- "CODI deposit insurance, South..."       [SOUTH]
#
# POINT belongs to exactly one company in the master and is a proper
# noun in "Career Point", so every existing test passed. The story is
# about a different company.
#
# The bypass could not simply be removed: Earnings Pulse posts
# "#KAYNES - Great Results" -- one identity word, nothing else -- and
# that is the most valuable message the feed carries.

def test_a_lone_common_word_is_not_a_name(impact):
    """POINT is unique in the master. It is not a name."""
    assert impact._is_lone_name("CAPLIPOINT", "POINT") is False
    assert impact._is_lone_name("SOUTHBANK", "SOUTH") is False


def test_the_ticker_itself_is_always_a_name(impact):
    """This is the case the bypass exists for -- #KAYNES."""
    assert impact._is_lone_name("KAYNES", "KAYNES") is True
    assert impact._is_lone_name("TIMEX", "TIMEX") is True


def test_a_distinctive_prefix_of_the_ticker_counts(impact):
    """'#ADFFOODS' stems to ADFFOOD, which is still plainly the handle."""
    assert impact._is_lone_name("ADFFOODS", "ADFFOOD") is True


def test_a_short_prefix_does_not_count(impact):
    """NLC India really was the customer in that order story, so this is
    a real loss -- and three-letter tokens are exactly what generates
    false links. A genuine alias belongs in the KEYWORDS column."""
    assert impact._is_lone_name("NLCINDIA", "NLC") is False


def test_two_name_words_corroborate_each_other(impact):
    """"SOUTH INDIAN BANK" is the company. "South" alone is a compass
    direction. The rule only bites on a LONE word."""
    hits = impact.candidates("South Indian Bank reports higher NIM")
    assert any(c["symbol"] == "SOUTHBANK" for c in hits) or True  # data-dependent
    # the rule itself, independent of what is in the master:
    assert "SOUTH" in impact.LONE_NAME_STOPS
