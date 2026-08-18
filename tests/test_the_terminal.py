"""
==========================================================
A command line, and an honest chain
==========================================================

    "i want a bloom berg terminal style data analysis"
    "which company is linked what sector, theme, which raw material
     provider, end user of the products every thing in as same as
     bloomberg"                      -- operator, 16 August 2026

WHAT WAS COPIED
---------------
The interaction model, which is the whole reason professionals are
fast on a Bloomberg: type a ticker, a short mnemonic, GO. No menus.
RELIANCE DES, RELIANCE CN, AAPL US Equity FA. That transfers exactly
and costs nothing.

WHAT WAS NOT COPIED
-------------------
A second page. Four dashboards were collapsed into two on 13 August,
and the watchlist, the run-up reading, delivery %, the AI spend and
the stock card were every one of them found stranded on a page he had
stopped opening. A separate "terminal" screen would recreate that
fault within a week. The command line drives /board instead.

THE HONEST LIMIT, AND WHY IT IS WRITTEN DOWN
--------------------------------------------
Bloomberg's SPLC is built from DISCLOSED supplier and customer
relationships -- contracts, revenue concentration, filings. There is
no such feed in this repo and none can be derived from what is here.

What data/master_stocks.csv does carry, across all 1,314 tradeable
names, is a classification on five axes:

    COMMODITY_EXPOSURE   1,807 tags   STEEL 241, CRUDE OIL 89
    THEMES               3,370 tags   966 distinct
    ECONOMIC_SENSITIVITY 1,442 tags   EXPORT ORIENTED, IMPORT DEPENDENT
    BUSINESS_TYPE        1,314 tags   MANUFACTURER 754, DISTRIBUTOR 51
    INDUSTRY               635 distinct

So "crude spikes -- who does that reach" is answered exactly, and
"who supplies Tata Steel" is refused rather than guessed. The tests
below hold that line: test_it_does_not_claim_a_supply_chain_it_cannot
_prove fails the build if the wording ever starts implying otherwise.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

import pytest

from core import sector_map

ROOT = pathlib.Path(__file__).resolve().parents[1]
BOARD = ROOT / "dashboard" / "static" / "board.html"


@pytest.fixture(scope="module")
def page():
    return BOARD.read_text(encoding="utf-8")


# ---------------------------------------------------------------
# THE INDEX
# ---------------------------------------------------------------

def test_a_raw_material_names_every_company_it_reaches():
    """THE ONE HE ASKED FOR. A tariff on steel, a crude spike -- the
    question is always "who does this touch", and it must be a list of
    names rather than a number."""
    got = sector_map.carrying("STEEL")
    assert got, "STEEL reaches nobody -- the index is not being built"
    biggest = got[0]
    assert biggest["column"] == "COMMODITY_EXPOSURE"
    assert len(biggest["symbols"]) > 100, (
        f"only {len(biggest['symbols'])} names carry STEEL")


def test_a_partial_tag_finds_the_masters_own_spelling():
    """He should not have to know the file's wording before he can ask
    a question. "crude" must find "CRUDE OIL"."""
    hits = sector_map.like("crude")
    assert hits
    assert any(h["tag"] == "CRUDE OIL" for h in hits)


def test_a_stock_lists_every_group_it_belongs_to():
    got = sector_map.links_of("RELIANCE")
    assert got["found"] is True
    axes = {g["column"] for g in got["groups"]}
    assert "SECTOR" in axes and "COMMODITY_EXPOSURE" in axes
    assert len(got["groups"]) >= 5


def test_the_narrowest_group_comes_first():
    """Sharing a 3-member theme says far more about two companies than
    sharing a 151-member sector, so it must not be buried under it."""
    groups = sector_map.links_of("RELIANCE")["groups"]
    counts = [g["count"] for g in groups]
    assert counts == sorted(counts), "groups are not narrowest-first"


def test_NONE_is_not_a_group():
    """665 rows carry COMMODITY_EXPOSURE=NONE. That is an answer, not a
    peer group, and listing it would bury every real one."""
    assert sector_map.carrying("NONE") == []


def test_an_unknown_tag_is_empty_not_an_error():
    assert sector_map.carrying("NO-SUCH-TAG-ANYWHERE") == []
    assert sector_map.carrying("") == []
    assert sector_map.links_of("")["found"] is False


def test_blocked_stocks_never_appear_in_a_group():
    """The index must agree with the tradeable universe. A T2T name
    listed as a peer is a name he cannot act on."""
    from core.master_loader import MasterLoader
    loader = MasterLoader()
    loader.load()
    blocked = set(loader.blocked_symbols())
    steel = sector_map.carrying("STEEL")[0]["symbols"]
    leaked = blocked & set(steel)
    assert not leaked, f"blocked names in a peer group: {sorted(leaked)[:5]}"


# ---------------------------------------------------------------
# THE COMMAND LINE
# ---------------------------------------------------------------

def test_the_board_has_a_command_line(page):
    assert 'id="cmd"' in page
    assert "function runCommand(" in page


def test_slash_focuses_it_and_escape_closes(page):
    """The keyboard is the half that makes it a terminal. A Bloomberg
    user never reaches for the mouse."""
    assert 'e.key === "/"' in page
    assert 'e.key === "Escape"' in page
    assert 'e.key === "Enter" && e.target && e.target.id === "cmd"' in page


def test_a_known_symbol_beats_a_tag(page):
    """RELIANCE is a company, not a theme. If the tag branch ran first
    the most common command on the terminal would do the wrong thing."""
    fn = page[page.find("async function runCommand"):page.find("function drawBrain")]
    assert "const known" in fn
    known_at = fn.find("const known")
    tag_at = fn.find("/api/tag/")
    assert known_at < tag_at, "the tag lookup is checked before the symbol"


def test_every_advertised_function_exists(page):
    """A function on the HELP list that does nothing teaches him the
    terminal lies. Each one must be dispatched."""
    fn = page[page.find("const FUNCTIONS = {"):page.find("function drawBrain")]
    for name in ("DES", "FA", "CN", "LINK", "SPLC", "OPP", "HELP"):
        assert f"{name}:" in fn or f'"{name}"' in fn, name


def test_a_tag_in_the_panel_is_clickable(page):
    """LINK lists the groups; clicking one lists its members. That is
    the chain walk, and without it every hop needs retyping."""
    assert "data-tagq=" in page
    assert 'closest("[data-tagq]")' in page


# ---------------------------------------------------------------
# THE LINE THAT MUST NOT MOVE
# ---------------------------------------------------------------

def test_it_does_not_claim_a_supply_chain_it_cannot_prove(page):
    """Bloomberg's SPLC uses disclosed supplier/customer relationships.
    This has classification tags. Both are useful; only one of them can
    answer "who supplies Tata Steel", and it is not this one.

    If the wording ever starts implying otherwise, he will act on a
    relationship the bot invented.
    """
    src = (ROOT / "core" / "sector_map.py").read_text(encoding="utf-8")
    assert "DISCLOSED supplier" in src, (
        "core/sector_map.py no longer states what it cannot prove")
    assert "supplies" in page.lower() or "disclosed contracts" in page.lower(), (
        "the HELP text no longer tells him the chain is not a real "
        "supplier->customer graph")


# ---------------------------------------------------------------
# WHY -- the question the refusal store cannot answer
# ---------------------------------------------------------------
#
#     "TVSMOTOR posted business updates & posted good quarterly
#      results, stock rallied more than 300 rs since business update &
#      as we all know markets price the future, so we / bot is no where
#      cashing that option why even after getting all the data?"
#                                     -- operator, 16 August 2026
#
# Traced end to end, and the bot did NOT miss the data:
#
#   03 Aug 03:31  Business Pulse "Monthly Business Update: TVS Motor"
#   03 Aug 03:32  "JULY TOTAL SALES 629,675 VS 456,350 (YOY); EST 510,000"
#   news_memory.impact:
#       TVSMOTOR | POSITIVE | 0.85 | how='reasoned'
#       "July sales surged 38% YoY and beat estimates, signaling
#        strong demand momentum."
#
# It read it, reasoned it, scored it 0.85, and never bought the stock,
# which went 3,876 -> 4,466 (+590 rs, +15.2%) over the following days.
#
# The gate is core/why_moving.py:238, and it is deliberate:
#
#       if on_date and not at.startswith(str(on_date)):
#           continue
#       "Yesterday's result is not why a stock is moving today"
#
# A catalyst is a reason for exactly ONE SESSION. On day two of a
# rally the stock has no reason at all and is refused as "no reason
# found" -- 562,427 of those recorded, the second commonest refusal.
#
# That is a design decision, not a bug, and changing it changes the
# entry rule. These tests hold the DIAGNOSIS visible so the decision
# gets made deliberately rather than forgotten again.

def test_why_is_on_the_function_list(page):
    assert "WHY:" in page
    assert "/api/why/" in page


def test_it_says_the_refusal_store_cannot_name_the_stock(page):
    """data/decisions.db refusals is (date, at, reason, n). No symbol.
    Any answer claiming to read a stock's refusal history would be
    invented, so WHY re-runs the gates live and says so."""
    # WHITESPACE NORMALISED. The phrase is wrapped across a line in the
    # docstring -- "with no\n        symbol column" -- so a raw
    # substring test failed on a sentence that says exactly the right
    # thing. Eighth time a test on this project has matched prose and
    # been wrong about it; the fix is to compare meaning, not layout.
    import re
    src = (ROOT / "dashboard" / "server.py").read_text(encoding="utf-8")
    block = src[src.find('@app.get("/api/why")'):src.find('@app.get("/api/links')]
    flat = re.sub(r"\s+", " ", block)
    assert "no symbol column" in flat or "carries no symbol" in flat, (
        "/api/why no longer states that the refusal store cannot name "
        "the stock -- an answer that implied otherwise would be invented")


def test_the_panel_explains_the_one_session_rule(page):
    """The single most useful sentence on the screen: why a stock in a
    two-week rally reads as 'no reason found' on day four."""
    assert "reason for exactly ONE session" in page
    assert "why_moving" in page


def test_the_freshness_gate_still_exists_and_is_deliberate():
    """If this ever changes, the diagnosis above stops being true and
    the note on the panel becomes a lie."""
    src = (ROOT / "core" / "why_moving.py").read_text(encoding="utf-8")
    assert "if on_date and not at.startswith(str(on_date)):" in src
    assert "not why a stock is moving today" in src


def test_the_live_path_actually_passes_todays_date():
    """The gate only bites because dashboard/state.py passes on_date.
    Without it the newest reason would win whenever it happened."""
    src = (ROOT / "dashboard" / "state.py").read_text(encoding="utf-8")
    assert 'on_date=datetime.now().strftime("%Y-%m-%d")' in src

# ---------------------------------------------------------------
# WHICH SIDE OF THE COMMODITY IS THIS COMPANY ON?
# ---------------------------------------------------------------
#
#     "THE PURPOSE OF BRAIN MEMORY IS NOT FULLY PREPARED ... bot needs
#      to know which companies are positive & negative . as of now
#      there is no distinction between them"
#                                 -- operator, 18 August 2026,
#                                    with a screenshot: "COPPER
#                                    COMPANIES WOULD BE IN FOCUS --
#                                    LME COPPER ONE-DAY SPREAD HITS
#                                    $110, THE HIGHEST SINCE 2021"
#
# The file proves him right against itself. 71 symbols carry
# COMMODITY_EXPOSURE = COPPER, and by BUSINESS_TYPE they are
# 67 MANUFACTURER, 3 EPC, 1 MINING. On a copper spike exactly one of
# those 71 is helped. carrying("COPPER") handed him all 71 with the
# liquid ones first -- and the liquid ones are the wrong 70.
#
# A tag says a company TOUCHES a commodity. It never said which END of
# it the company stands on, and a direction-free link is not an
# opportunity, it is a coin flip wearing a reason.


def test_the_copper_producer_is_told_apart_from_the_cable_makers():
    """HIS EXAMPLE, END TO END."""
    got = sector_map.sides("COPPER")
    producers = {r["symbol"] for r in got["producers"]}
    consumers = {r["symbol"] for r in got["consumers"]}
    assert "HINDCOPPER" in producers, "the one name copper helps"
    assert {"POLYCAB", "KEI"} <= consumers, (
        "cable makers BUY copper -- a spike is a cost, not a catalyst")
    assert not (producers & consumers), "a company on both sides"


def test_it_refuses_to_guess_where_the_data_cannot_say():
    """HINDALCO is the reason UNKNOWN exists. BUSINESS_TYPE is
    MANUFACTURER and CORE BUSINESS reads 'MANUFACTURES ALUMINIUM AND
    COPPER PRODUCTS'. It is a smelter -- a producer -- and nothing in
    the master says so. Calling it a CONSUMER because the word
    MANUFACTURES appears would be a confident wrong answer."""
    got = sector_map.stance("HINDALCO", "COPPER")
    assert got["stance"] == "UNKNOWN"
    assert got["why"], "an UNKNOWN he cannot interrogate is not useful"


def test_unknown_is_never_quietly_folded_into_either_side():
    got = sector_map.sides("COPPER")
    unknown = {r["symbol"] for r in got["unknown"]}
    assert "HINDALCO" in unknown
    assert got["counts"]["unknown"] == len(got["unknown"])


def test_a_company_with_no_exposure_gets_no_verdict():
    """Silence, not a CONSUMER by default. Defaulting would put every
    stock in the market on the wrong side of every commodity."""
    assert sector_map.stance("HINDCOPPER", "PALM OIL") is None
    assert sector_map.stance("NOTALISTEDCO", "COPPER") is None
    assert sector_map.stance("HINDCOPPER", "") is None


def test_every_side_carries_the_reason_it_was_put_there():
    """He has to be able to argue with it. A bucket with no reason is
    a rule nobody can check."""
    got = sector_map.sides("COPPER")
    for key in ("producers", "consumers", "unknown"):
        for row in got[key]:
            assert row.get("why"), f"{row['symbol']} has no reason"


def test_it_works_for_a_commodity_that_is_not_copper():
    """One worked example is a coincidence."""
    got = sector_map.sides("STEEL")
    assert got["counts"]["consumers"] > 100, (
        "steel is an input for most of the board and should say so")
    assert got["counts"]["producers"] >= 1


def test_a_commodity_nobody_carries_answers_empty_not_broken():
    got = sector_map.sides("UNOBTAINIUM")
    assert got["counts"] == {"producers": 0, "consumers": 0, "unknown": 0}
    assert sector_map.sides("")["counts"]["producers"] == 0


def test_the_split_reaches_the_screen_and_the_phone():
    src = (ROOT / "dashboard" / "server.py").read_text(encoding="utf-8")
    assert '"sides": sector_map.sides(tag)' in src, (
        "/api/tag still answers with a direction-free list")
    desk = (ROOT / "core" / "telegram_desk.py").read_text(encoding="utf-8")
    assert "def _sides" in desk
    assert "SIDES" in desk
