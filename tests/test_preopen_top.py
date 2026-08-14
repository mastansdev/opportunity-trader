"""
==========================================================
Ten each side, with the order book showing
==========================================================

    "Pre-open is printing all universe stocks why? we want only the
     stocks with more gapups + Buyers waiting stocks ; gapdowns +
     sellers waiting in two tabs under Pre-market main tab"
    "Gap threshold - top 10 gainers /losers"
    "two sub-tabs be strict - yes with gapup + sellers shows the dual
     picture"
                                    -- operator, 3 August 2026

Measured on his real data/preopen file: 1,684 gap-ups, 337 gap-downs
and 203 unknown -- 2,224 rows, and not filtered to stocks he can trade.
Nobody reads that at 09:00.

THE DUAL PICTURE WAS HIS IDEA AND IT IS BETTER THAN MINE
--------------------------------------------------------
I proposed filtering each tab to rows where the queue AGREES with the
gap: gap-ups with buyers, gap-downs with sellers. He asked for the
disagreements to stay, and he is right. From his own file that morning:

    YASHO       +6.77%   1.2x more SELLERS waiting

YASHO is the stock that cost him Rs 11,000 on the first live day. It
gapped up, and NSE's own auction book was already saying the gap had
no buyers behind it. My filter would have deleted that row.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from dashboard.state import DashboardState


def row(symbol, gap, buy, sell):
    return {"symbol": symbol, "gap_pct": gap, "buy_qty": buy,
            "sell_qty": sell, "iep": 100.0, "prev_close": 100.0}


def top(ups=None, downs=None):
    st = DashboardState.__new__(DashboardState)
    snap = {"shown": 2224,
            "groups": {"mine": {"gap_up": ups or [], "gap_down": downs or []}}}
    return st._preopen_top(snap)


# ---------------------------------------------------------------
# 1. TEN, NOT TWO THOUSAND
# ---------------------------------------------------------------
def test_only_ten_a_side_reach_the_screen():
    ups = [row("U%d" % i, 5.0 - i * 0.1, 100, 50) for i in range(60)]
    downs = [row("D%d" % i, -5.0 + i * 0.1, 50, 100) for i in range(60)]
    got = top(ups, downs)
    assert len(got["gap_up"]) == 10
    assert len(got["gap_down"]) == 10


def test_the_biggest_gaps_are_the_ones_kept():
    """     "top 10 gainers /losers" -- the gap is the ranking."""
    ups = [row("SMALL", 0.4, 100, 50), row("BIG", 9.0, 100, 50),
           row("MID", 3.0, 100, 50)]
    got = top(ups)
    assert [r["symbol"] for r in got["gap_up"]] == ["BIG", "MID", "SMALL"]


def test_a_gap_down_is_ranked_by_size_not_by_sign():
    downs = [row("SMALL", -0.4, 50, 100), row("BIG", -9.0, 50, 100)]
    assert [r["symbol"] for r in top(None, downs)["gap_down"]] == ["BIG", "SMALL"]


def test_it_says_how_many_it_looked_at():
    """He should be able to see that 2,224 became 20, rather than
    wonder where everything went."""
    got = top([row("A", 1.0, 100, 50)])
    assert got["n_seen"] == 2224
    assert got["per_side"] == 10


# ---------------------------------------------------------------
# 2. THE DUAL PICTURE
# ---------------------------------------------------------------
def test_a_gap_up_with_sellers_queued_is_kept_not_dropped():
    """     "yes with gapup + sellers shows the dual picture"

    YASHO gapped +6.77% with more sellers waiting on the day it cost
    him Rs 11,000. Filtering it out -- which is what I proposed --
    would have deleted the most useful row on the screen."""
    got = top([row("YASHO", 6.77, 100, 120)])
    hit = got["gap_up"][0]
    assert hit["symbol"] == "YASHO"
    assert hit["waiting"] == "sellers"
    assert hit["agrees"] is False


def test_a_gap_up_with_buyers_queued_agrees():
    hit = top([row("BAJFINANCE", 3.08, 151326, 54066)])["gap_up"][0]
    assert hit["waiting"] == "buyers"
    assert hit["agrees"] is True
    assert hit["waiting_times"] == 2.8


def test_a_gap_down_being_bought_is_flagged_as_a_disagreement():
    hit = top(None, [row("MUTHOOTFIN", -7.81, 270, 100)])["gap_down"][0]
    assert hit["waiting"] == "buyers"
    assert hit["agrees"] is False


def test_the_ratio_is_the_only_thing_the_bot_computes():
    """buy_qty and sell_qty come straight from NSE's 09:00-09:12
    auction. Nothing is modelled."""
    hit = top([row("X", 2.0, 300, 100)])["gap_up"][0]
    assert hit["waiting_times"] == 3.0
    assert hit["buy_qty"] == 300 and hit["sell_qty"] == 100


def test_a_one_sided_book_does_not_divide_by_zero():
    up = top([row("NOSELL", 2.0, 500, 0)])["gap_up"][0]
    assert up["waiting"] == "buyers" and up["waiting_times"] is None
    down = top(None, [row("NOBUY", -2.0, 0, 500)])["gap_down"][0]
    assert down["waiting"] == "sellers"


def test_an_empty_book_says_nothing_rather_than_guessing():
    hit = top([row("QUIET", 2.0, 0, 0)])["gap_up"][0]
    assert hit["waiting"] is None
    assert hit["waiting_times"] is None


# ---------------------------------------------------------------
# 3. IT NEVER THROWS THE REST AWAY
# ---------------------------------------------------------------
def test_the_full_lists_are_still_in_the_payload():
    """     "never throw away any symbol that gets in either direction"

    The top ten is a VIEW. The complete groups stay beside it."""
    src = open("dashboard/state.py", encoding="utf-8").read()
    block = src[src.index("snapshot[\"groups\"] = groups"):]
    block = block[:block.index("except Exception")]
    assert 'snapshot["top"] = self._preopen_top(snapshot)' in block
    assert "del snapshot" not in block


def test_no_rows_at_all_is_survivable():
    got = top([], [])
    assert got["gap_up"] == [] and got["gap_down"] == []


# ---------------------------------------------------------------
# 3b. THE QUEUE IS A FACT. WHAT IT MEANS IS NOT KNOWN YET.
# ---------------------------------------------------------------
#
#     "MUTHOOTFIN gapped -7.81% with 2.7x more buyers queued - fell
#      like hell too"                 -- operator, 3 August 2026
#
# He was checking a claim I made about the imbalance. I could not check
# it back: data/preopen.json is OVERWRITTEN every morning, so one day
# exists at a time and every previous book has been deleted by the next
# one. An interpretation reached him that had never been scored against
# a single outcome and could not be.
def test_the_reading_is_marked_as_untested():
    hit = top(None, [row("MUTHOOTFIN", -7.81, 270, 100)])["gap_down"][0]
    assert hit["untested"] is True


def test_the_raw_quantities_survive_to_the_payload():
    """Whatever the ratio turns out to mean, NSE's own numbers are
    facts and must reach the screen unaltered."""
    hit = top([row("X", 2.0, 151326, 54066)])["gap_up"][0]
    assert hit["buy_qty"] == 151326 and hit["sell_qty"] == 54066


def test_the_book_is_archived_so_it_can_be_scored_later():
    """A dated copy costs about 600KB a day. Twenty sessions is enough
    to ask whether a queue predicts anything at all -- and the answer
    may well be no."""
    src = open("core/preopen.py", encoding="utf-8").read()
    assert "def _archive" in src
    block = src[src.index("def _save"):src.index("def _archive")]
    assert "self._archive(data)" in block
    arch = src[src.index("def _archive"):]
    arch = arch[:arch.index("\n    # ---")] if "\n    # ---" in arch else arch
    assert "preopen_history" in arch
    # A failed archive must never endanger the live save.
    assert "except Exception" in arch


def test_archiving_never_overwrites_a_day_already_kept(tmp_path):
    from core.preopen import PreOpen
    store = PreOpen(fetcher=None, store_path=str(tmp_path / "p.json"))
    book = {"date": "2026-08-04", "stocks": {"X": {}}}
    assert store._archive(book) is True
    assert store._archive(book) is False


# ---------------------------------------------------------------
# 4. THE WATCHLIST ORDER HE ASKED ME TO DECIDE
# ---------------------------------------------------------------
def test_the_watchlist_breaks_ties_on_traded_value_not_the_alphabet():
    """     "watchlist = you must suggest on that"

    Catalyst still leads and tier still beats call -- both of those
    were argued for and both still hold. What changed is the last
    tiebreak, which was the alphabet, and that is why 63MOONS kept
    appearing above TCS."""
    src = open("core/watchlist.py", encoding="utf-8").read()
    block = src[src.index("out.sort(key="):]
    block = block[:block.index("return out")]
    assert "-size.get(" in block
    # Catalyst and tier are untouched and still ahead of it.
    assert block.index("order.get") < block.index("-size.get(")
    assert block.index("tier_rank") < block.index("-size.get(")
    # The alphabet stays underneath, so the order is STABLE.
    assert block.index("-size.get(") < block.index('r["symbol"]))')


def test_the_watchlist_still_survives_without_the_liquidity_file():
    from core import watchlist
    assert callable(watchlist.build)
    rows = watchlist.build(extra=[
        {"symbol": "ZED", "catalyst": watchlist.RESULTS, "when": "today"},
        {"symbol": "ALPHA", "catalyst": watchlist.RESULTS, "when": "today"}])
    assert {r["symbol"] for r in rows} == {"ZED", "ALPHA"}
