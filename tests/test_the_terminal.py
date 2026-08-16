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
