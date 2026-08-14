"""
==========================================================
No event, no trade -- on BOTH lanes
==========================================================

    "Opportunity Trader Bot = only trades when an event or real
     opportunity arised in markets, NEVER in to random stocks"
                                -- operator, 12 August 2026

BOT_SPEC.md entry rule 2 has said "a written reason exists: no
mechanism, no trade" since it was written. Two paths in this bot can
reach Engine._enter(), and until 12 August only one of them enforced
it:

    ranker -> auto_entry    refused a stock with no mechanism
    engine ORB breakout     never asked

The engine's _capture_reason() had been gathering exactly this evidence
since 28 July -- to stamp on the position AFTERWARDS, so
core/trade_memory.py could learn from it. It recorded why it bought and
never required that there be a why.

These tests hold that door shut. The first one is the regression: a
clean ORB breakout, every other gate passing, on a stock nothing has
been published about.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import datetime

import pytest

from core.engine import Engine
from core.rules import is_a_reason


# ---------------------------------------------------------------
# THE SHARED DEFINITION
# ---------------------------------------------------------------
# NOT_A_REASON and the 15-character floor lived in core/ranker.py and
# nowhere else, which is precisely why the ORB lane could not apply
# them. They are in core/rules.py now and both lanes import them.

def test_a_matcher_lookup_is_not_a_reason():
    """core/news_impact.py writes this when a story merely NAMED a
    company. On the ranker's first real run it sailed through and
    ranked sixth."""
    assert not is_a_reason("matched on: INDGN")
    assert not is_a_reason("matched on: CRUDE, OIL")


def test_a_sentence_that_says_nothing_is_not_a_reason():
    assert not is_a_reason("")
    assert not is_a_reason(None)
    assert not is_a_reason("unknown")
    assert not is_a_reason("up 4%")            # under the 15-char floor


def test_a_real_mechanism_is_a_reason():
    assert is_a_reason("Q1 PAT up 24% QoQ on higher refining margins")
    assert is_a_reason("wins Rs 1,240 crore order from NHAI")


def test_the_ranker_and_the_engine_read_the_same_definition():
    """The whole point. If these ever stop being the same object, the
    two lanes have started to drift again."""
    from core import ranker, rules
    assert ranker.is_a_reason is rules.is_a_reason
    assert ranker.NOT_A_REASON is rules.NOT_A_REASON


# ---------------------------------------------------------------
# THE ENGINE LANE
# ---------------------------------------------------------------

class _Feed:
    """Stands in for core/news_watcher.py / announcement_watcher.py."""

    def __init__(self, items=None):
        self._items = items or {}

    def for_symbol(self, symbol):
        return self._items.get(str(symbol).upper())


@pytest.fixture
def engine():
    return Engine()


def test_a_stock_with_no_event_is_refused(engine):
    """The regression. Nothing published about NOEVENT today."""
    engine.news_feed = _Feed()
    engine.announcements = _Feed()
    engine.results_gate = None
    assert engine._no_reason_refusal("NOEVENT") is not None
    assert "no event behind it" in engine._no_reason_refusal("NOEVENT")


def test_a_classified_news_item_is_an_event(engine):
    engine.news_feed = _Feed({"ORDERCO": {
        "kind": "ORDER_WIN",
        "headline": "wins Rs 1,240 crore order from NHAI"}})
    engine.announcements = _Feed()
    engine.results_gate = None
    assert engine._no_reason_refusal("ORDERCO") is None


def test_an_exchange_filing_is_an_event(engine):
    engine.news_feed = _Feed()
    engine.announcements = _Feed({"FILEDCO": {"kind": "RESULTS"}})
    engine.results_gate = None
    assert engine._no_reason_refusal("FILEDCO") is None


def test_a_published_grade_is_an_event(engine):
    class _Gate:
        def _published_grade(self, symbol):
            return "EXCELLENT" if symbol == "GRADEDCO" else None

        def grade_for(self, symbol):
            return None

    engine.news_feed = _Feed()
    engine.announcements = _Feed()
    engine.results_gate = _Gate()
    assert engine._no_reason_refusal("GRADEDCO") is None
    assert engine._no_reason_refusal("OTHERCO") is not None


def test_a_broken_news_feed_does_not_halt_trading(engine):
    """Fail-OPEN on an ERROR, like every other bookkeeping read on this
    path. Distinct from an EMPTY feed, which is a real answer -- see
    the test below."""
    class _Broken:
        def for_symbol(self, symbol):
            raise RuntimeError("news store is locked")

    engine.news_feed = _Broken()
    engine.announcements = _Feed({"ANYCO": {"kind": "RESULTS"}})
    engine.results_gate = None
    # The filing still answers, so the trade stands.
    assert engine._no_reason_refusal("ANYCO") is None


def test_an_empty_feed_is_an_answer_not_an_error(engine):
    """A silent feed must NOT fail open. 'Nobody published anything'
    is exactly the case this rule exists for, and reading it as a data
    problem would reopen the door it closes."""
    engine.news_feed = _Feed()
    engine.announcements = _Feed()
    engine.results_gate = None
    assert engine._no_reason_refusal("SILENTCO") is not None


# ---------------------------------------------------------------
# "NO EQUIPMENT" IS NOT "NO NEWS"
# ---------------------------------------------------------------
# The first cut of this rule confused the two and turned 97 engine
# tests red -- every one of them builds a bare Engine() to measure
# something else entirely (liquidity, rotation, the sector gate) and
# attaches no news reader. Refusing there would not have made those
# safer; it would have made all of them measure this gate instead.

def test_an_engine_with_no_feeds_at_all_does_not_refuse(engine):
    engine.news_feed = None
    engine.announcements = None
    engine.results_gate = None
    assert engine._no_reason_refusal("ANYTHING") is None


def test_but_it_says_so_loudly_and_only_once(engine, caplog):
    """In production main.py builds every feed inside a try/except, so
    an unwired engine is also what a broken startup looks like. It must
    never be a silence -- and never a line per symbol per candle."""
    engine.news_feed = None
    engine.announcements = None
    engine.results_gate = None
    with caplog.at_level("WARNING"):
        for _ in range(5):
            engine._no_reason_refusal("ANYTHING")
    said = [r for r in caplog.records if "NO_REASON" in r.getMessage()]
    assert len(said) == 1, f"expected exactly one warning, got {len(said)}"
    assert "BUYING BREAKOUTS WITH NO REASON" in said[0].getMessage()


def test_one_wired_feed_is_enough_to_apply_the_rule(engine):
    """Equipment attached and silent -> the rule applies. This is the
    boundary the two tests above sit either side of."""
    engine.news_feed = _Feed()          # wired, and says nothing
    engine.announcements = None
    engine.results_gate = None
    assert engine._no_reason_refusal("SILENTCO") is not None


def test_the_switch_turns_it_off(engine, monkeypatch):
    """One line to reverse if it ever refuses a whole session."""
    import core.rules as rules
    monkeypatch.setattr(rules, "ENGINE_REQUIRE_REASON", False)
    engine.news_feed = _Feed()
    engine.announcements = _Feed()
    engine.results_gate = None
    assert engine._no_reason_refusal("NOEVENT") is None


def test_the_refusal_reaches_the_breakout_panel(engine):
    """A refused breakout is exactly as worth seeing as a taken one --
    the operator watched TVSMOTOR run on 28 July while his own bot had
    already spotted it and refused in silence."""
    noted = []

    class _Panel:
        def note_block(self, symbol, direction, reason):
            noted.append((symbol, direction, reason))

    engine.news_feed = _Feed()          # wired, and says nothing
    engine.announcements = _Feed()
    engine.results_gate = None
    engine.breakout_feed = _Panel()
    engine._note_breakout_block("NOEVENT", "LONG",
                                engine._no_reason_refusal("NOEVENT"))
    assert noted and "no event behind it" in noted[0][2]
