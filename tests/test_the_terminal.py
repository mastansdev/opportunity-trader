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

# ---------------------------------------------------------------
# THE LINE THAT MUST NOT MOVE
# ---------------------------------------------------------------

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

def test_the_freshness_gate_still_exists_and_is_deliberate():
    """If this ever changes, the diagnosis above stops being true and
    the note on the panel becomes a lie."""
    src = (ROOT / "core" / "why_moving.py").read_text(encoding="utf-8")
    assert "if on_date and not at.startswith(str(on_date)):" in src
    assert "not why a stock is moving today" in src


def test_the_live_path_actually_passes_todays_date(monkeypatch):
    """The gate only bites because dashboard/state.py passes on_date.
    Without it the newest reason would win whenever it happened.

    ---- ASKED OF THE FUNCTION, NOT OF THE SOURCE. 29 Aug 2026 ----
    This used to grep state.py for the literal
    'on_date=datetime.now().strftime("%Y-%m-%d")'. On 29 August that
    expression moved into a `today` variable, because the reason cache
    added beside it needs the same date to key on -- identical
    behaviour, and the test failed anyway.

    Grepping source for a spelling is the fourth time this suite has
    broken on a refactor that changed nothing. So it now CALLS the
    live method and reads the date why() was handed.
    """
    from datetime import datetime

    from dashboard.state import DashboardState

    seen = {}

    def _spy(events=None, news_hits=None, symbol=None, filing=None,
             on_date=None):
        seen["on_date"] = on_date
        return None

    monkeypatch.setattr("core.why_moving.why", _spy)

    class _Stub(DashboardState):
        def __init__(self):
            self.stock_events = None
            self.news_impact = None
            self.announcement_watcher = None

    _Stub()._mechanism_for("TESTCO")
    assert seen["on_date"] == datetime.now().strftime("%Y-%m-%d"), (
        "the live reason lookup did not pass today's date, so a stale "
        "event would be accepted as the reason for today's move")

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
