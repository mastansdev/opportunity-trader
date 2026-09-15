"""
Friday, 31 July 2026 -- the first real order.

    "Friday . we planned 1 manual share buying & selling in MTF from our
     dashboard"
    "Rank before considering. Bot will place those stocks in alert box.
     we agreed bot will not trade"
                                        -- operator, 30 July 2026

Two things had to be true for that plan to work, and neither was.

  ONE SHARE   a manual dashboard BUY sizes itself by risk, which on a
              Rs 300 stock is hundreds of shares. Correct for real use,
              completely wrong for the first order this account has ever
              sent through the bot.

  RANKED      the engine raises an alert the instant a signal fires, so
              the box was in the order the tape produced them. That is
              the same first-come-first-served that took THYROCARE at
              0.03x volume while refusing KSB at 715x -- and an alert box
              read top-down reproduces it by eye.
"""

import pytest

import config
from dashboard.state import DashboardState


# ---------------------------------------------------------------
# ONE SHARE, BY HAND
# ---------------------------------------------------------------

def _engine():
    from core.engine import Engine
    return object.__new__(Engine)


def test_the_test_size_overrides_risk_sizing(monkeypatch):
    monkeypatch.setattr("core.engine.MANUAL_TEST_QTY", 1)
    assert _engine()._manual_qty(217) == 1


def test_without_it_risk_sizing_stands(monkeypatch):
    monkeypatch.setattr("core.engine.MANUAL_TEST_QTY", None)
    assert _engine()._manual_qty(217) == 217
    monkeypatch.setattr("core.engine.MANUAL_TEST_QTY", 0)
    assert _engine()._manual_qty(217) == 217


def test_a_junk_setting_falls_back_rather_than_placing_something_odd(monkeypatch):
    monkeypatch.setattr("core.engine.MANUAL_TEST_QTY", "one")
    assert _engine()._manual_qty(217) == 217
    monkeypatch.setattr("core.engine.MANUAL_TEST_QTY", -5)
    assert _engine()._manual_qty(217) == 217


def test_the_test_size_is_off_now_that_he_trades_for_real():
    """---- FRIDAY'S PLAN IS OVER. 1 August 2026. ----

    This test used to assert MANUAL_TEST_QTY == 1 and its own message
    said: "Change this back to None after the test -- a test size must
    not become the size you trade."

    It did exactly that job: the setting was changed and this test went
    red, which is how it should be found.

        "i'll trade with 1 lakh not 1 share of qty.. from dashboard"
                                    -- operator, 1 August 2026

    So a dashboard BUY is now sized by _risk_sized_qty(): Rs 1 lakh of
    HIS margin per position, share count asked of Dhan. On a 26.3%
    margin stock that is roughly Rs 3.8 lakh of stock and a Rs 3,794
    stop -- not the Rs 1,000 a single share risked.

    The assertion is kept, pointing the other way, so that a stray 1
    left in config after a day of testing cannot silently shrink every
    position to one share without anything going red.
    """
    assert config.MANUAL_TEST_QTY is None, (
        f"MANUAL_TEST_QTY is {config.MANUAL_TEST_QTY!r}. Every dashboard "
        f"BUY will place that many shares instead of the Rs 1 lakh "
        f"position. Set it to None unless today is a deliberate test.")


def test_only_manual_clicks_are_resized():
    """A test size must never quietly become the size the bot trades."""
    src = open("core/engine.py", encoding="utf-8").read()
    assert src.count("self._manual_qty(") == 2, (
        "exactly two call sites -- the dashboard BUY and the dashboard "
        "SHORT. Any third one means an automated path is using the test "
        "size.")
    for reason in ("ENTRY_REASON_MANUAL_DASHBOARD",
                   "ENTRY_REASON_MANUAL_SHORT_DASHBOARD"):
        block = src[src.find("_manual_qty("):]
        assert "MANUAL" in block[:2000]


def test_live_orders_go_out_as_mtf():
    """The plan says MTF. A CNC or INTRADAY order would settle
    differently and cost differently."""
    src = open("trading/live_execution.py", encoding="utf-8").read()
    assert "product_type=MTF" in src
    assert src.count("product_type=MTF") >= 2, "buy and sell both"


def test_alert_only_does_not_block_a_manual_click():
    """The bot is not trading tomorrow. The OPERATOR is. The alert even
    says so: 'Use the dashboard BUY if you want it.'"""
    src = open("core/engine.py", encoding="utf-8").read()
    manual = src[src.find("is_buy_requested(symbol)"):]
    manual = manual[:manual.find("is_short_requested")]
    assert "self.alert_only" not in manual, (
        "an operator override must not be gated by the bot's own "
        "alert-only mode")


# ---------------------------------------------------------------
# THE ALERT BOX IS RANKED
# ---------------------------------------------------------------

def _state(alerts, scores):
    st = object.__new__(DashboardState)

    class _Engine:
        def get_manual_alerts(self):
            return list(alerts)

    st.engine = _Engine()
    st._build_shortlist = lambda: {"rows": [
        {"symbol": s, "score": v} for s, v in scores.items()]}
    return st


