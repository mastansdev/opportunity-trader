"""
==========================================================
A catalyst list that happens to be full of results
==========================================================

    "FIRST thing we need to focus on watchlist (which stocks reporting
     results during markets, after markets) as now results time. later
     this watchlist will carry the stocks which were sorted by news,
     orders, govt policy, fed, rbi, or any other things stocks/sector
     specifics like fda on pharmas, fed,rbi on banks, nbfcs,
     commodities - gold, silver, aluminium on their related stocks,
     steel = related stocks. (to be precise this is all your work
     before even i ask these you need to prepare)"
                                    -- operator, 2 August 2026

He is right that it should have been anticipated. So the watchlist is
keyed by CATALYST from the first line of code. Results is simply the
only catalyst firing today, because it is results season.

THE MAPPING WAS ALREADY IN THE MASTER
-------------------------------------
Nothing had to be researched. data/master.csv has carried
COMMODITY_EXPOSURE, ECONOMIC_SENSITIVITY and SECTOR on all 1,153
companies since the beginning, and no part of this project had ever
read them. Counted on the real file:

    gold moves           ->  23 names
    silver moves         ->  10 names
    aluminium moves      ->  58 names
    steel moves          -> 176 names
    RBI or the Fed       -> 157 interest-rate-sensitive names
    FDA news             ->  68 pharma names
    budget or capex      -> 216 government-spending names

Every example he gave, answerable today.

WHY THE TRIGGER IS NOT WIRED YET
--------------------------------
The mapping is clean; the trigger side is not. A plain search of the
617 stored MACRO events for "gold" returns a channel's own
gamification message -- "You're only 2.3 pts from GOLD!" -- next to
the real ones. Feeding that into a good mapping would fill the
watchlist with rubbish that looks authoritative.

So the fan-out is built and tested against real master data now, and
what fires it is a separate decision made later, deliberately.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.master_loader import MasterLoader
from core.watchlist import (AFTER, COMMODITY, DURING, ORDER, RATES, RESULTS,
                            SECTOR, build, by_catalyst, counts, exposed_to,
                            fan_out, from_results)


@pytest.fixture(scope="module")
def master():
    loader = MasterLoader()
    loader.load()
    return loader


VIEW = {
    "reporting_today": {
        DURING: [{"symbol": "AETHER", "call": "BUY"},
                 {"symbol": "MARUTI", "call": None}],
        AFTER: [{"symbol": "DIXON", "call": "AVOID"}],
    },
    "reporting_tomorrow": {
        DURING: [{"symbol": "TITAN", "call": None}],
        AFTER: [{"symbol": "SBIN", "call": None}],
    },
    "unpriced_from_last_close": [
        {"symbol": "CORONA", "on": "2026-07-31", "call": "BUY"},
    ],
}


# ---------------------------------------------------------------
# 1. THE RESULTS HALF -- LIVE TODAY
# ---------------------------------------------------------------
def test_every_reporter_becomes_a_watchlist_row():
    rows = from_results(VIEW)
    assert {r["symbol"] for r in rows} == {
        "AETHER", "MARUTI", "DIXON", "TITAN", "SBIN", "CORONA"}
    assert {r["catalyst"] for r in rows} == {RESULTS}


def test_the_side_of_the_close_is_carried():
    """The part that decides what you do: DURING happens while you are
    watching, AFTER cannot be traded until the next open."""
    rows = {r["symbol"]: r for r in from_results(VIEW)}
    assert rows["AETHER"]["theme"] == DURING
    assert "during the session" in rows["AETHER"]["detail"]
    assert rows["DIXON"]["theme"] == AFTER
    assert "after the close" in rows["DIXON"]["detail"]


def test_today_tomorrow_and_unpriced_are_kept_apart():
    rows = {r["symbol"]: r for r in from_results(VIEW)}
    assert rows["AETHER"]["when"] == "today"
    assert rows["TITAN"]["when"] == "tomorrow"
    assert rows["CORONA"]["when"] == "unpriced"


def test_the_call_rides_along():
    rows = {r["symbol"]: r for r in from_results(VIEW)}
    assert rows["AETHER"]["call"] == "BUY"
    assert rows["DIXON"]["call"] == "AVOID"
    assert rows["MARUTI"]["call"] is None


def test_today_sorts_above_tomorrow():
    order = [r["symbol"] for r in build(results_view=VIEW)]
    assert order.index("AETHER") < order.index("TITAN")
    assert order.index("CORONA") < order.index("TITAN")


# ---------------------------------------------------------------
# 2. THE FAN-OUT -- HIS "LATER", WORKING NOW
# ---------------------------------------------------------------
@pytest.mark.parametrize("theme,column,least", [
    ("GOLD", "COMMODITY_EXPOSURE", 20),
    ("SILVER", "COMMODITY_EXPOSURE", 8),
    ("ALUMINIUM", "COMMODITY_EXPOSURE", 40),
    ("STEEL", "COMMODITY_EXPOSURE", 150),
    ("INTEREST RATE SENSITIVE", "ECONOMIC_SENSITIVITY", 120),
    ("GOVERNMENT SPENDING", "ECONOMIC_SENSITIVITY", 180),
    ("PHARMACEUTICALS", "SECTOR", 60),
    ("BANKING", "SECTOR", 30),
])
def test_every_theme_he_named_maps_to_real_companies(master, theme,
                                                     column, least):
    """Against the real master, not a fixture. If the file changes and
    a theme stops mapping, this is where it is caught."""
    got = exposed_to(master, theme, column=column)
    assert len(got) >= least, f"{theme} fell to {len(got)}"
    assert got == sorted(set(got)), "duplicated or unsorted"


def test_a_multi_value_cell_counts_for_each_of_its_values(master):
    """"STEEL | ALUMINIUM | RUBBER" is exposed to steel AND aluminium.
    Counting whole cells gives STEEL 64 and is wrong -- the value
    inside the cell is what matters, which gives 176."""
    steel = set(exposed_to(master, "STEEL"))
    alum = set(exposed_to(master, "ALUMINIUM"))
    assert steel & alum, "no company is exposed to both -- the pipe " \
                         "split is not working"
    assert len(steel) > 150


def test_an_unknown_theme_returns_nothing_rather_than_everything(master):
    """A watchlist that quietly widens stops meaning anything."""
    assert exposed_to(master, "UNOBTANIUM") == []
    assert exposed_to(master, "") == []
    assert exposed_to(None, "GOLD") == []


def test_the_fan_out_produces_watchlist_rows(master):
    rows = fan_out(master, "GOLD", catalyst=COMMODITY)
    assert rows and all(r["catalyst"] == COMMODITY for r in rows)
    assert all(r["theme"] == "GOLD" for r in rows)
    assert all(r["call"] is None for r in rows), (
        "a commodity move is not a call on the stock")


def test_each_catalyst_reads_the_right_column(master):
    """RATES must look at ECONOMIC_SENSITIVITY, not COMMODITY_EXPOSURE.
    Reading the wrong column returns nothing and looks like no
    exposure, which is the quietest kind of wrong."""
    assert fan_out(master, "INTEREST RATE SENSITIVE", catalyst=RATES)
    assert fan_out(master, "PHARMACEUTICALS", catalyst=SECTOR)
    assert not fan_out(master, "INTEREST RATE SENSITIVE",
                       catalyst=COMMODITY)


# ---------------------------------------------------------------
# 3. THE TWO HALVES TOGETHER
# ---------------------------------------------------------------
def test_results_and_a_theme_live_on_one_list(master):
    rows = build(results_view=VIEW,
                 extra=fan_out(master, "GOLD", catalyst=COMMODITY))
    got = by_catalyst(rows)
    assert got[RESULTS] and got[COMMODITY]
    assert counts(rows)["total"] == len(rows)


def test_results_sort_above_a_commodity_theme(master):
    """A company reporting in two hours outranks one whose commodity
    moved -- the first is dated, the second is standing exposure."""
    rows = build(results_view=VIEW,
                 extra=fan_out(master, "GOLD", catalyst=COMMODITY))
    first_theme = next(i for i, r in enumerate(rows)
                       if r["catalyst"] == COMMODITY)
    last_result = max(i for i, r in enumerate(rows)
                      if r["catalyst"] == RESULTS)
    assert last_result < first_theme


def test_a_stock_may_appear_under_two_catalysts(master):
    """It reports today AND steel moved. Both are worth seeing, so
    neither is merged away."""
    rows = build(results_view=VIEW,
                 extra=[{"symbol": "AETHER", "catalyst": COMMODITY,
                         "theme": "STEEL", "detail": "steel exposure",
                         "when": None, "call": None}])
    aether = [r for r in rows if r["symbol"] == "AETHER"]
    assert len(aether) == 2
    assert {r["catalyst"] for r in aether} == {RESULTS, COMMODITY}


def test_the_same_row_twice_is_collapsed():
    twice = from_results(VIEW) + from_results(VIEW)
    assert len(build(extra=twice)) == len(from_results(VIEW))


def test_an_empty_view_is_an_empty_list():
    assert build() == []
    assert build(results_view={}) == []
    assert counts([])["total"] == 0


def test_a_row_with_no_symbol_is_dropped():
    assert build(extra=[{"symbol": None, "catalyst": ORDER}]) == []


# ---------------------------------------------------------------
# 4. IT REACHES THE PANEL
# ---------------------------------------------------------------
def test_the_panel_is_fed_a_catalyst_list_not_a_results_list():
    """The distinction he asked for by name. Results is the catalyst
    firing today, not the shape of the thing."""
    src = open("dashboard/state.py", encoding="utf-8").read()
    assert "watchlist_build(results_view=watch" in src
    assert '"by_catalyst"' in src


def test_the_watchlist_survives_the_json_encoder():
    """"A date object is not JSON. One un-encodable value here is a
    500 for the whole snapshot." -- dashboard/state.py"""
    import json
    rows = build(results_view=VIEW)
    json.dumps({"rows": rows, "counts": counts(rows)})
