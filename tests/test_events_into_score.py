"""
The channels finally reach the score, and the card.

    "yes pls . we cannot throw away data just like that. upon clicking on
     stock name the box opening right now is not showing any data . by
     completing these 3 items we will see the end to end on stock"
                                        -- operator, 30 July 2026

Three gaps, closed together:

  1. Earnings Pulse posts a graded verdict SECONDS after a company
     files. quarterly_results only knows once the filing is parsed,
     hours later. The grade was collected all day and read by nothing.
  2. OrderBook Pulse posts contract wins with their value. Never read.
  3. StockCard was constructed without telegram, news_impact or
     signal_journal, so three of its eight sections could only return
     None -- and those three are the ones that answer "why is it
     moving". That is why the drawer opened empty.
"""

import pytest

from core.shortlist import ShortlistBuilder
from core.stock_card import StockCard
from core.stock_events import StockEvents, classify


class _Events:
    def __init__(self, rows):
        self.rows = rows

    def recent(self, limit=2000, hours=36, scope="STOCK"):
        return list(self.rows)

    def for_symbol(self, symbol, limit=20):
        return [r for r in self.rows if r.get("symbol") == symbol]


def _rank(events, symbol="X", **row):
    builder = ShortlistBuilder(stock_events=_Events(events))
    base = {"symbol": symbol, "sector": "S", "ltp": 100.0,
            "change_pct": 4.0, "volume": 100000}
    base.update(row)
    out = builder.rank([base], top=5)
    return out["rows"][0] if out["rows"] else None


# ---------------------------------------------------------------
# 1. EARNINGS PULSE -- the instant verdict
# ---------------------------------------------------------------

def test_an_instant_excellent_lifts_the_score():
    got = _rank([{"symbol": "X", "kind": "RESULT", "grade": "EXCELLENT"}])
    assert any("PULSE" in w for w in got["why"])
    assert got["score"] > 4.0


def test_an_instant_weak_pushes_it_down():
    """A verdict that cuts both ways is a verdict worth having. One that
    only ever adds points is a cheerleader.

    Moved 9% so both rows clear MIN_SCORE and can be compared -- on a 4%
    move the WEAK row scores below the cutoff and drops off the list
    entirely, which is the same point made more bluntly.
    """
    good = _rank([{"symbol": "X", "kind": "RESULT", "grade": "GOOD"}],
                 change_pct=9.0)
    weak = _rank([{"symbol": "X", "kind": "RESULT", "grade": "WEAK"}],
                 change_pct=9.0)
    assert weak["score"] < good["score"]
    assert weak["score"] < 9.0, "a weak result must cost, not merely not help"


def test_a_weak_verdict_can_drop_a_stock_off_the_list_entirely():
    """On a modest move it falls below MIN_SCORE, which is the strongest
    form of "this is not worth your attention"."""
    assert _rank([{"symbol": "X", "kind": "RESULT", "grade": "WEAK"}],
                 change_pct=4.0) is None


def test_an_ok_verdict_is_worth_nothing_either_way():
    """"OK results" is the channel saying it has no opinion."""
    plain = _rank([])
    okish = _rank([{"symbol": "X", "kind": "RESULT", "grade": "OK"}])
    assert okish["score"] == plain["score"]


def test_the_channel_is_worth_less_than_the_filed_numbers():
    """It arrives hours earlier, which is the whole reason to use it. It
    is still one word from a third party, not arithmetic on a filing."""
    assert max(ShortlistBuilder.PULSE_SCORE.values()) \
        < max(ShortlistBuilder.GRADE_SCORE.values())


# ---------------------------------------------------------------
# 2. ORDERBOOK PULSE -- a win, and how big
# ---------------------------------------------------------------

def test_an_order_win_reaches_the_why_chips():
    got = _rank([{"symbol": "X", "kind": "ORDER", "value_cr": 2205.23,
                  "counterparty": "HAL"}])
    chip = [w for w in got["why"] if "ORDER WIN" in w]
    assert chip, got["why"]
    assert "2,205" in chip[0] and "HAL" in chip[0], (
        "the size and the customer are the story")


def test_a_bigger_order_scores_higher():
    """Rs 2 crore and Rs 2,205 crore are not the same news. Treating
    them alike is how a screener starts lying."""
    small = _rank([{"symbol": "X", "kind": "ORDER", "value_cr": 2.0}])
    large = _rank([{"symbol": "X", "kind": "ORDER", "value_cr": 2205.0}])
    assert large["score"] > small["score"]


def test_an_order_with_no_figure_still_counts():
    """"HFCL wins optical fibre export order" is a real order."""
    got = _rank([{"symbol": "X", "kind": "ORDER", "value_cr": None}])
    assert any("ORDER WIN" in w for w in got["why"])
    assert got["score"] > 4.0


def test_a_stock_with_no_events_gets_no_credit():
    assert _rank([])["score"] == pytest.approx(4.0)


def test_one_order_is_counted_once():
    """A channel that reposts must not compound the score."""
    once = _rank([{"symbol": "X", "kind": "ORDER", "value_cr": 100.0}])
    twice = _rank([{"symbol": "X", "kind": "ORDER", "value_cr": 100.0},
                   {"symbol": "X", "kind": "ORDER", "value_cr": 100.0}])
    assert once["score"] == twice["score"]


def test_events_for_another_stock_do_not_leak():
    got = _rank([{"symbol": "OTHER", "kind": "ORDER", "value_cr": 5000.0}],
                symbol="X")
    assert got["score"] == pytest.approx(4.0)


def test_a_broken_event_store_costs_the_chips_not_the_shortlist():
    """A screener going quiet must degrade, never take the page down."""
    class Angry:
        def recent(self, **kw):
            raise RuntimeError("db gone")
    builder = ShortlistBuilder(stock_events=Angry())
    out = builder.rank([{"symbol": "X", "sector": "S", "ltp": 100.0,
                         "change_pct": 4.0, "volume": 1000}], top=5)
    assert out["rows"][0]["symbol"] == "X"


# ---------------------------------------------------------------
# A TIP SHEET IS NOT A RESULT
# ---------------------------------------------------------------
# Found on real data: "STOCK PICK NBCC, Hirect, Indo-MIM, Xtranet Tech,
# MOIL, MTAR Tech, Eicher Motors, Prestige Estates ... excellent" was
# recorded as REDINGTON RESULT grade=EXCELLENT, because the grade words
# were tested before the opinion words.

def test_a_recommendation_is_an_opinion_whatever_adjectives_it_uses():
    kind, _ = classify("STOCK PICK: analysts see excellent results ahead "
                       "for these names", has_symbol=True)
    assert kind == "OPINION", (
        "a tip sheet must never set a score the way an audited filing "
        "does")


def test_the_builder_skips_a_message_naming_several_companies():
    """is_digest() counts #HASHTAGS and the tip sheets list companies by
    NAME. The matched-symbol count does not care how they were written."""
    src = open("tools/build_stock_events.py", encoding="utf-8").read()
    assert "if len(symbols) >= 3:" in src


# ---------------------------------------------------------------
# 3. THE DRAWER
# ---------------------------------------------------------------

def test_the_card_reports_what_has_happened(tmp_path):
    store = StockEvents(db_path=str(tmp_path / "e.db"))
    store.remember("ASTRAMICRO", "2026-07-30T13:47", "ORDER",
                   "secures Rs 2205.23 Cr order from HAL",
                   value_cr=2205.23, counterparty="HAL",
                   source="OrderBook Pulse")
    card = StockCard(stock_events=store)
    section = card.build("ASTRAMICRO").get("events")
    assert section and section["count"] == 1
    row = section["rows"][0]
    assert row["kind"] == "ORDER"
    assert row["value_cr"] == 2205.23
    assert row["counterparty"] == "HAL"


def test_the_dashboard_hands_the_card_its_news_sources():
    """THE BUG. Three sections could only ever return None because the
    constructor was never given telegram, news_impact or the journal --
    and those three are the ones that answer 'why is it moving'."""
    src = open("dashboard/state.py", encoding="utf-8").read()
    block = src[src.find("self.stock_card = StockCard("):]
    block = block[:block.find(")\n")]
    for wanted in ("telegram=telegram", "news_impact=news_impact",
                   "signal_journal=", "stock_events="):
        assert wanted in block, f"StockCard is still built without {wanted}"


def test_a_missing_event_store_is_not_a_crash():
    card = StockCard(stock_events=None)
    assert card.build("ANYTHING").get("events") is None
