"""
==========================================================
Six finders, one brain, and every candidate says where it came from.
==========================================================

    "we will build all in different finders i.e = Opportunities from
     NEWS, RESULTS, EVENTS, structural moving stocks like all as a
     unique finders that report to trade brain engine which will sort
     the stocks & select best of best"

    "as a human i'm doing all of them & time delayed = stock movement
     over & thats where the bot trading came into force"
                                -- operator, 22 August 2026

WHY THIS SHAPE AND NOT A BIGGER RANKER

Everything used to funnel into one invented score. Measured over 15
sessions, that score ordered its OWN shortlist worse than a random
draw:

    highest volume x   +Rs 565/trade   62.2% up
    first to fire      -Rs  36         44.4%
    HIGHEST SCORE      -Rs  68         42.2%
    random draw        -Rs 226
    LOWEST volume x    -Rs 823         26.7%

A single number averaging signals of different kinds, with weights
nobody measured, cannot rank them. The fix is provenance: every
candidate carries `finder`, so each source can be judged on what its
own picks did. That one field is what makes the thing learnable.

The brain therefore orders by VOLUME -- money the exchange counted --
and never by anything this repository assigns itself. His rule:

    "these scores, grades were self assigned & neither stocks nor NSE
     works as per our scoring right?"

Author : H&M Opportunity Trader
==========================================================
"""

import datetime

from core.finder_set import (EventFinder, FilingFinder, MoversFinder,
                             OrderFinder, ResultsFinder, StructuralFinder,
                             build)
from core.finders import Finder, TradeBrain, candidate

TODAY = datetime.datetime.now().strftime("%Y-%m-%d")


class _Boom(Finder):
    name = "broken"

    def find(self, now=None):
        raise RuntimeError("this finder is having a bad day")


def _events(rows):
    return lambda d: rows if d == TODAY else []


# ---------------------------------------------------------------
# EVERY CANDIDATE SAYS WHERE IT CAME FROM
# ---------------------------------------------------------------

def test_a_candidate_carries_its_finder():
    """The whole point. Without this nothing downstream can measure
    which source is worth backing."""
    got = candidate("KRONOX", "orders", reason="wins Rs 190cr order",
                    volume_x=7.4)
    assert got["finder"] == "orders"
    assert got["symbol"] == "KRONOX"


def test_two_finders_naming_one_stock_are_both_remembered():
    """Agreement is worth measuring later. It gets NO bonus today --
    nothing has measured what agreement is worth, and inventing a
    weight for it is the mistake this module exists to stop."""
    brain = TradeBrain([
        MoversFinder(ranked_rows=[{"symbol": "BELRISE", "volume_x": 13.1}]),
        EventFinder(events_for=_events([
            {"symbol": "BELRISE", "kind": "NEWS", "headline": "expansion"}]),
            volume_of=lambda s: 13.1)])
    rows = brain.gather()
    assert len(rows) == 1
    assert set(rows[0]["finders"]) == {"movers", "events"}


# ---------------------------------------------------------------
# THE BRAIN ORDERS BY VOLUME, NOT BY ANYTHING WE INVENT
# ---------------------------------------------------------------

def test_the_heaviest_volume_is_backed_first():
    rows = [candidate("LOW", "movers", volume_x=1.2),
            candidate("HEAVY", "movers", volume_x=18.9)]
    assert [r["symbol"] for r in TradeBrain.order(rows)] == ["HEAVY", "LOW"]


def test_an_unmeasured_stock_sorts_LAST_not_first():
    """None means we could not measure it, never that it is quiet.
    Reading it as quiet is how an unmeasurable stock tops the list."""
    rows = [candidate("UNKNOWN", "movers", volume_x=None),
            candidate("KNOWN", "movers", volume_x=2.0)]
    assert [r["symbol"] for r in TradeBrain.order(rows)] == ["KNOWN", "UNKNOWN"]


def test_a_self_assigned_score_cannot_decide():
    """A high score on a thin stock must not beat volume. The score
    measured WORSE THAN RANDOM at this job."""
    rows = [candidate("THIN", "movers", volume_x=0.4, score=99.0),
            candidate("HEAVY", "movers", volume_x=9.0, score=1.0)]
    assert TradeBrain.order(rows)[0]["symbol"] == "HEAVY"


def test_only_the_seats_available_are_filled():
    brain = TradeBrain([MoversFinder(ranked_rows=[
        {"symbol": f"S{i}", "volume_x": float(i)} for i in range(10)])],
        seats=3)
    assert len(brain.pick()) == 3


# ---------------------------------------------------------------
# ONE FINDER FAILING MUST NOT SILENCE THE OTHERS
# ---------------------------------------------------------------

def test_a_broken_finder_does_not_stop_the_rest():
    brain = TradeBrain([_Boom(),
                        MoversFinder(ranked_rows=[{"symbol": "OK",
                                                   "volume_x": 5.0}])])
    assert [r["symbol"] for r in brain.gather()] == ["OK"]


def test_a_finder_with_nothing_wired_returns_nothing():
    """Every source is optional so this can go live before all of them
    are connected."""
    for f in (EventFinder(), FilingFinder(), OrderFinder(),
              ResultsFinder(), MoversFinder()):
        assert f.safe_find() == []


def test_junk_rows_are_dropped_not_crashed():
    brain = TradeBrain([MoversFinder(ranked_rows=[
        {"symbol": "GOOD", "volume_x": 3.0}, {}, None, {"volume_x": 9.9}])])
    assert [r["symbol"] for r in brain.gather()] == ["GOOD"]


# ---------------------------------------------------------------
# WHAT EACH FINDER IS FOR
# ---------------------------------------------------------------

def test_macro_names_no_company():
    """"RBI holds rates" explains why everything moved and identifies
    nothing. It must never become a candidate."""
    f = EventFinder(events_for=_events([
        {"symbol": "X", "kind": "MACRO", "headline": "RBI holds"},
        {"symbol": "Y", "kind": "NEWS", "headline": "order win"}]))
    assert [c["symbol"] for c in f.safe_find()] == ["Y"]


def test_the_order_finder_takes_only_order_wins():
    """Separated from events so its record reads on its own: ORDER
    measured -Rs 292 same-window against NEWS at +Rs 14, and averaged
    together they said nothing."""
    f = OrderFinder(events_for=_events([
        {"symbol": "A", "kind": "ORDER", "headline": "wins order"},
        {"symbol": "B", "kind": "NEWS", "headline": "news"}]))
    assert [c["symbol"] for c in f.safe_find()] == ["A"]


def test_the_results_finder_is_quiet_out_of_season():
    """'results season completed & will re occur on oct 2nd week'.
    It stays wired so it is not something nobody remembers to switch
    on in October."""
    f = ResultsFinder(events_for=_events([
        {"symbol": "A", "kind": "NEWS", "headline": "x"}]))
    assert f.safe_find() == []


def test_the_structural_finder_is_off_by_default():
    """His standing rule is 'an event or real opportunity ... NEVER in
    to random stocks', and this is the lane that argues with it."""
    rows = [{"symbol": "BREAKOUT", "volume_x": 9.0}]
    assert StructuralFinder(breakouts=rows).safe_find() == []
    assert StructuralFinder(breakouts=rows, enabled=True).safe_find()


# ---------------------------------------------------------------
# THE REPORT HE READS
# ---------------------------------------------------------------

def test_the_report_says_what_each_finder_contributed():
    brain = TradeBrain(build(
        ranked_rows=lambda: [{"symbol": "M", "volume_x": 4.0}],
        events_for=_events([{"symbol": "E", "kind": "ORDER",
                             "headline": "wins order"}]),
        volume_of=lambda s: 7.0), seats=2)
    got = brain.report()
    assert got["candidates"] == 2
    assert got["by_finder"]["movers"] == 1
    assert got["by_finder"]["orders"] == 1
    assert got["picked"][0] == "E"          # 7.0x beats 4.0x


def test_build_wires_the_six_he_named():
    made = build()
    assert [f.name for f in made] == [
        "movers", "events", "orders", "filings", "results", "structural"]
