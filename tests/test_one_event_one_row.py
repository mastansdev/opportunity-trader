"""The same story on two channels is one event.

    "Duplicates of data is not acceptable at all & if it still do this
     is riducolus"                    -- operator, 29 August 2026

The unique index is (symbol, at, kind, headline), so a story posted by
two channels two minutes apart inserts twice -- different `at`, often
different wording, same event:

    10:53 RedboxGlobal   ACUTAAS CHEMICALS: APPROVAL RECEIVED ...
    10:55 Day Trader     ACUTAAS CHEMICALS: APPROVAL RECEIVED ...
    14:46 Day Trader     #HCC bags Rs 524 cr NHPC contract in J&K
    14:51 OrderBook      HCC secures Rs 524 crore NHPC contract in J&K

Day Trader Telugu re-posts RedboxGlobal on 73 stock-days since
18 August alone.

TWO EARLIER ATTEMPTS AT THIS WERE REVERTED, both for the same reason:
a key that did not identify one story. A bulk collapse tool offered to
delete "INDIA-EU FTA WILL BE A GAME CHANGER" as a duplicate of a solar
story. core/stock_events.remember() still carries that note.

So the rule cannot reach across symbols, days or kinds. Inside one
stock, one day and one kind it matches the story itself -- identical
normalised headline, or the same rupee amount. Measured on the whole
13,103-row store before shipping: 101 rows by headline, 164 by amount,
and every group inspected was one event on two channels.

What this file guards is the OTHER half: that a genuinely different
event is never swallowed. That is the failure mode with a cost.
"""

import os
import tempfile

import pytest

from core.stock_events import StockEvents

DAY = "2026-08-11T09:16:00+00:00"


@pytest.fixture
def store():
    return StockEvents(db_path=os.path.join(tempfile.mkdtemp(), "ev.db"))


# ------------------------------------------------- the duplicate goes

def test_the_same_headline_from_another_channel_is_not_stored_twice(store):
    line = "ACUTAAS CHEMICALS: APPROVAL RECEIVED UNDER ELECTRONICS COMPONENTS"
    assert store.remember("ACUTAAS", DAY, "NEWS", line, source="Redbox")
    assert not store.remember(
        "ACUTAAS", "2026-08-11T09:18:00+00:00", "NEWS", line,
        source="Day Trader Telugu")
    assert len(store.for_symbol("ACUTAAS")) == 1


def test_the_same_order_worded_differently_is_not_stored_twice(store):
    """The wording differs; "524 cr" does not.

    This is what the headline rule alone cannot catch, and it is the
    commonest shape of the overlap he reported.
    """
    assert store.remember("HCC", DAY, "ORDER",
                          "#Justin | #HCC bags Rs 524 cr NHPC contract in J&K",
                          source="Day Trader Telugu")
    assert not store.remember("HCC", "2026-08-11T09:21:00+00:00", "ORDER",
                              "HCC secures Rs 524 crore NHPC contract in J&K",
                              source="OrderBook Pulse")
    assert len(store.for_symbol("HCC")) == 1


def test_case_and_punctuation_and_a_leading_tag_do_not_make_it_new(store):
    assert store.remember("GOLDIAM", DAY, "ORDER",
                          "GOLDIAM INTERNATIONAL: CO WINS EXPORT ORDER", None)
    assert not store.remember("GOLDIAM", "2026-08-11T09:20:00+00:00", "ORDER",
                              "#GOLDIAM goldiam international - co wins "
                              "export order!", None)


# ------------------------- and a REAL event is never swallowed

def test_a_different_order_on_the_same_day_is_kept(store):
    """The failure mode that reverted this twice before.

    Two orders, same stock, same day, different money. Both are news.
    """
    store.remember("HCC", DAY, "ORDER",
                   "HCC bags Rs 524 cr NHPC contract in J&K", source="a")
    assert store.remember("HCC", "2026-08-11T11:00:00+00:00", "ORDER",
                          "HCC wins a separate Rs 890 crore metro contract",
                          source="b")
    assert len(store.for_symbol("HCC")) == 2


def test_the_same_amount_on_a_different_day_is_kept(store):
    store.remember("HCC", DAY, "ORDER",
                   "HCC secures Rs 524 crore NHPC contract", source="a")
    assert store.remember("HCC", "2026-08-12T09:16:00+00:00", "ORDER",
                          "HCC secures Rs 524 crore NHPC contract", source="b")
    assert len(store.for_symbol("HCC")) == 2


def test_a_different_kind_on_the_same_day_is_kept(store):
    """An order win and a results card are two events, whatever else
    they share."""
    store.remember("HCC", DAY, "ORDER",
                   "HCC secures Rs 524 crore contract", source="a")
    assert store.remember("HCC", DAY, "RESULT",
                          "HCC Q1 revenue Rs 524 crore", source="b")


def test_two_different_stories_never_collapse(store):
    """The FTA/solar case, stated as a test."""
    store.remember("NTPC", DAY, "NEWS",
                   "INDIA-EU FTA WILL BE A GAME CHANGER", source="a")
    assert store.remember("NTPC", "2026-08-11T10:00:00+00:00", "NEWS",
                          "NTPC commissions 300 MW solar plant in Rajasthan",
                          source="b")
    assert len(store.for_symbol("NTPC")) == 2


def test_a_headline_with_no_amount_and_no_words_is_still_stored(store):
    """Fail-open. A missing event costs a trade; a duplicate costs a
    row."""
    assert store.remember("TESTCO", DAY, "NEWS", "!!!", source="a")


# ------------------------------------------------- and it can be turned off

def test_it_can_be_disabled(store, monkeypatch):
    """Insert-only is what this was from 1 August, after two earlier
    dedupe attempts were reverted. One flag back."""
    import core.stock_events as module

    monkeypatch.setattr(module, "DEDUPE_EVENTS", False)
    line = "ACUTAAS CHEMICALS: APPROVAL RECEIVED"
    store.remember("ACUTAAS", DAY, "NEWS", line, source="a")
    assert store.remember("ACUTAAS", "2026-08-11T09:18:00+00:00", "NEWS",
                          line, source="b")
