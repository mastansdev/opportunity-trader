"""
News on a stock you HOLD -- 29 July 2026.

    "pcbl throwed us out & moved 3%"      -- operator, 29 July 2026

PCBL filed results at 14:19 while the position was open. The bot logged
the filing, exited on the trail minutes later, and the stock ran 12%.

THE OBVIOUS FIX WAS MEASURED AND REJECTED. Pausing or widening the stop
when news lands was tested against all 19 results filings that day:

    fell 2.5% or more after filing :  5
    rose 2.5% or more after filing :  8

The eight that rose never touched a 2.5% stop anyway. FOUR of the five
that fell kept falling -- SKMEGGPROD -6.39%, REFEX -6.07%, CARTRADE
-5.62%, BLACKBUCK -4.63% -- where the stop firing was correct and a
pause would have doubled the loss. Exactly one, REFEX, fell through a
stop and then recovered.

Saves you once in nineteen, hurts you four times in nineteen.

So this reports and changes nothing. The operator decides, which the
same day's numbers say he is better at: his own exits beat holding by
Rs 5,319 while the bot's trail cost Rs 47,324.
"""

from datetime import datetime

import pytest

from core.engine import (
    Engine, ENTRY_REASON_MANUAL_DASHBOARD, ENTRY_REASON_STRUCTURAL_LONG,
    LONG,
)


class _Feed:
    """Stands in for the news watcher / announcement watcher."""

    def __init__(self, items=None):
        self.items = items or {}

    def for_symbol(self, symbol):
        return self.items.get(symbol)


def _engine_holding(entry_reason=ENTRY_REASON_STRUCTURAL_LONG,
                    news=None, filings=None):
    engine = Engine(news_feed=_Feed(news), announcements=_Feed(filings))
    engine.open_positions["PCBL"] = {
        "symbol": "PCBL", "security_id": "1", "direction": LONG,
        "entry_price": 339.35, "qty": 294, "entry_reason": entry_reason,
        "initial_stop": 330.87, "fixed_target": None, "entry_time": None,
    }
    return engine


PCBL_RESULTS = {"kind": "RESULTS", "filed_at": "14:19",
                "headline": "Outcome of Board Meeting"}


# ---------------------------------------------------------------
# It reports
# ---------------------------------------------------------------

def test_a_filing_on_a_held_stock_is_announced():
    engine = _engine_holding(filings={"PCBL": PCBL_RESULTS})
    engine._check_news_on_holding("PCBL", engine.open_positions["PCBL"], 333.55)

    alerts = engine.get_manual_alerts()
    assert len(alerts) == 1
    message = alerts[0]["message"]
    assert "PCBL" in message
    assert "RESULTS" in message
    assert "294 shares" in message
    assert "339.35" in message
    assert "No action taken" in message


def test_the_current_move_is_shown():
    """He should not have to work out where the position stands."""
    engine = _engine_holding(filings={"PCBL": PCBL_RESULTS})
    engine._check_news_on_holding("PCBL", engine.open_positions["PCBL"], 333.55)
    assert "-1.71%" in engine.get_manual_alerts()[0]["message"]


def test_it_reports_on_the_bots_own_positions_too():
    """Not only manual trades. He wants to know either way."""
    engine = _engine_holding(entry_reason=ENTRY_REASON_STRUCTURAL_LONG,
                             filings={"PCBL": PCBL_RESULTS})
    engine._check_news_on_holding("PCBL", engine.open_positions["PCBL"], 333.55)
    assert len(engine.get_manual_alerts()) == 1


def test_news_and_filings_are_separate_sources():
    engine = _engine_holding(
        news={"PCBL": {"kind": "BROKER", "at": "14:30"}},
        filings={"PCBL": PCBL_RESULTS})
    engine._check_news_on_holding("PCBL", engine.open_positions["PCBL"], 333.55)
    kinds = " ".join(a["message"] for a in engine.get_manual_alerts())
    assert "RESULTS" in kinds and "BROKER" in kinds


# ---------------------------------------------------------------
# It says it ONCE
# ---------------------------------------------------------------

def test_the_same_filing_is_not_repeated_every_candle():
    """A filing stays in the feed all afternoon. One line, not 300."""
    engine = _engine_holding(filings={"PCBL": PCBL_RESULTS})
    for _ in range(300):
        engine._check_news_on_holding(
            "PCBL", engine.open_positions["PCBL"], 333.55)
    assert len(engine.get_manual_alerts()) == 1


def test_a_SECOND_different_filing_is_reported():
    """PCBL filed RESULTS at 14:19, then a DIVIDEND at 14:23 and a
    RECORD DATE at 14:25. Deduping on the symbol would have silenced
    the second and third."""
    engine = _engine_holding(filings={"PCBL": PCBL_RESULTS})
    position = engine.open_positions["PCBL"]
    engine._check_news_on_holding("PCBL", position, 333.55)

    engine.announcements.items["PCBL"] = {
        "kind": "PAYOUT", "filed_at": "14:23", "headline": "Dividend"}
    engine._check_news_on_holding("PCBL", position, 335.00)

    assert len(engine.get_manual_alerts()) == 2


# ---------------------------------------------------------------
# It changes NOTHING -- the whole point
# ---------------------------------------------------------------

def test_the_position_is_untouched():
    engine = _engine_holding(filings={"PCBL": PCBL_RESULTS})
    before = dict(engine.open_positions["PCBL"])
    engine._check_news_on_holding("PCBL", engine.open_positions["PCBL"], 333.55)
    assert engine.open_positions["PCBL"] == before
    assert engine.closed_positions == []


def test_the_stop_is_not_widened_by_news():
    """The measurement said so. Four of five stocks that fell after
    filing kept falling; widening would have doubled those losses."""
    engine = _engine_holding(filings={"PCBL": PCBL_RESULTS})
    engine._check_news_on_holding("PCBL", engine.open_positions["PCBL"], 333.55)
    assert engine.open_positions["PCBL"]["initial_stop"] == 330.87


# ---------------------------------------------------------------
# It can never break a tick
# ---------------------------------------------------------------

def test_no_feeds_wired_is_silent_not_fatal():
    engine = Engine()
    engine.open_positions["PCBL"] = {"entry_price": 339.35, "qty": 294}
    engine._check_news_on_holding("PCBL", engine.open_positions["PCBL"], 333.55)
    assert engine.get_manual_alerts() == []


def test_a_feed_that_raises_is_survivable():
    class Broken:
        def for_symbol(self, symbol):
            raise RuntimeError("watcher died")

    engine = Engine(news_feed=Broken(), announcements=Broken())
    engine.open_positions["PCBL"] = {"entry_price": 339.35, "qty": 294}
    engine._check_news_on_holding("PCBL", engine.open_positions["PCBL"], 333.55)


def test_a_malformed_item_does_not_crash():
    engine = _engine_holding(filings={"PCBL": {}})
    engine._check_news_on_holding("PCBL", engine.open_positions["PCBL"], 333.55)


def test_no_price_yet_is_survivable():
    engine = _engine_holding(filings={"PCBL": PCBL_RESULTS})
    engine._check_news_on_holding("PCBL", engine.open_positions["PCBL"], None)
    assert len(engine.get_manual_alerts()) == 1
