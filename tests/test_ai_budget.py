"""
==========================================================
The cap must be a refusal, not a comment
==========================================================

    "max .2500 per month is cap. & we need to use the best case of AI
     & trade by using the AI"          -- operator, 30 July 2026

config.AI_MONTHLY_BUDGET_RS has said 2500.0 since that day and nothing
read it. This file exists so that can never be true again.

WHAT IT IS ACTUALLY PROTECTING AGAINST
--------------------------------------
Not expense. At the measured volume -- 65 ungraded events a day -- the
whole thing costs about Rs 53 a month. The danger is a retry loop at
3am turning Rs 53 into Rs 25,000 on an account that also holds the
trading money, with nobody awake to see it.

THE DELIBERATE INVERSION
------------------------
Every other read in this codebase FAILS OPEN: a missing database
degrades one panel and never stops the session. This one FAILS
CLOSED. If the ledger cannot be read, no call is made.

Failing open on a spend meter means spending money you cannot see.
And the degraded state costs nothing real -- "no AI" is exactly how
the bot ran all of last week.

Author : H&M Opportunity Trader
==========================================================
"""

import sqlite3
from datetime import datetime

import pytest

from core.ai_budget import AiBudget, cost_usd, price_of


@pytest.fixture
def budget(tmp_path):
    return AiBudget(db_path=str(tmp_path / "spend.db"),
                    monthly_cap_rs=2500.0, usd_inr=88.0, warn_at_pct=0.75)


JULY = datetime(2026, 7, 31, 12, 0)
AUGUST = datetime(2026, 8, 1, 9, 0)


# ---------------------------------------------------------------
# 1. THE CAP IS ENFORCED
# ---------------------------------------------------------------
def test_calls_are_allowed_when_nothing_has_been_spent(budget):
    allowed, reason = budget.may_call(JULY)
    assert allowed is True
    assert reason is None


def test_calls_are_refused_at_the_cap(budget):
    """A refusal, not a warning. The bot already refuses to trade past
    DAILY_MAX_LOSS_RS; this is the same idea pointed at the API bill."""
    budget.record("claude-haiku-4-5", output_tokens=44_000_000, when=JULY)
    allowed, reason = budget.may_call(JULY)
    assert allowed is False
    assert "cap" in reason


def test_the_cap_is_per_calendar_month(budget):
    """A ceiling that never resets would silently switch the feature
    off forever a few months in."""
    budget.record("claude-haiku-4-5", output_tokens=44_000_000, when=JULY)
    assert budget.may_call(JULY)[0] is False
    assert budget.may_call(AUGUST)[0] is True, (
        "August must start clean -- the cap is monthly")


# ---------------------------------------------------------------
# 2. FAILS CLOSED -- THE ONE PLACE THIS CODEBASE DOES
# ---------------------------------------------------------------
def test_an_unreadable_ledger_stops_all_calls(budget, monkeypatch):
    """Spending money you cannot count is worse than not spending it.

    Note what the degraded state IS: the bot behaves exactly as it did
    last week, which is a state known to be safe.
    """
    monkeypatch.setattr(budget, "spent_this_month", lambda when=None: None)
    allowed, reason = budget.may_call()
    assert allowed is False
    assert "could not be read" in reason


def test_an_unreadable_ledger_is_not_treated_as_zero(budget, monkeypatch):
    """The subtle version of the same bug. If a failed read returned
    0.0 it would look like a clean month, every month, forever."""
    monkeypatch.setattr(budget, "spent_this_month", lambda when=None: 0.0)
    assert budget.may_call()[0] is True, "0.0 is a real answer"
    monkeypatch.setattr(budget, "spent_this_month", lambda when=None: None)
    assert budget.may_call()[0] is False, "None is not 0.0"


def test_a_broken_database_does_not_raise(tmp_path):
    """It is constructed during startup. It must not be able to stop
    the bot -- it only has to stop the AI."""
    bad = tmp_path / "not-a-db.db"
    bad.write_text("this is not sqlite", encoding="utf-8")
    meter = AiBudget(db_path=str(bad), monthly_cap_rs=2500.0)
    allowed, _ = meter.may_call()
    assert allowed is False


# ---------------------------------------------------------------
# 3. THE ARITHMETIC
# ---------------------------------------------------------------
def test_haiku_is_priced_as_published():
    """$1 per million in, $5 per million out."""
    assert cost_usd("claude-haiku-4-5", input_tokens=1_000_000) == 1.00
    assert cost_usd("claude-haiku-4-5", output_tokens=1_000_000) == 5.00


def test_cache_reads_are_a_tenth_of_the_input_rate():
    """Where most of the saving comes from -- the instruction block is
    identical on every news call."""
    assert cost_usd("claude-haiku-4-5",
                    cache_read_tokens=1_000_000) == pytest.approx(0.10)


def test_cache_writes_cost_more_than_plain_input():
    assert cost_usd("claude-haiku-4-5",
                    cache_write_tokens=1_000_000) == pytest.approx(1.25)


def test_an_unknown_model_is_priced_at_the_worst_rate():
    """A typo in config.AI_MODEL_SMART must never look cheap. Pricing
    the unknown at zero is how a cap gets bypassed by a config edit."""
    unknown = cost_usd("claude-something-new", output_tokens=1_000_000)
    known = cost_usd("claude-haiku-4-5", output_tokens=1_000_000)
    assert unknown > known


def test_a_dated_variant_is_priced_as_its_family():
    assert price_of("claude-haiku-4-5-20251001") == (1.00, 5.00)


def test_negative_token_counts_cannot_create_a_refund():
    """A garbled usage object must not be able to REDUCE the recorded
    spend and buy back headroom under the cap."""
    assert cost_usd("claude-haiku-4-5", input_tokens=-5_000_000) == 0.0


# ---------------------------------------------------------------
# 4. THE LEDGER IS THE AUDIT TRAIL
# ---------------------------------------------------------------
def test_every_call_is_recorded_with_what_it_was_for(budget):
    """In three weeks the question will be "what did the AI cost and
    what was it asked". That has to be a query, not a guess."""
    budget.record("claude-haiku-4-5", purpose="news_direction",
                  input_tokens=300, output_tokens=60, when=JULY)
    conn = sqlite3.connect(budget.db_path)
    row = conn.execute("select model, purpose, input_tokens, output_tokens, "
                       "rs from spend").fetchone()
    conn.close()
    assert row[0] == "claude-haiku-4-5"
    assert row[1] == "news_direction"
    assert (row[2], row[3]) == (300, 60)
    assert row[4] > 0


def test_the_measured_daily_volume_is_nowhere_near_the_cap(budget):
    """65 ungraded events a day, 21 trading days. If this ever fails,
    either the volume estimate or the pricing has moved and the whole
    plan needs re-costing."""
    for _ in range(65 * 21):
        budget.record("claude-haiku-4-5", purpose="news_direction",
                      input_tokens=50, cache_read_tokens=260,
                      output_tokens=60, when=JULY)
    spent = budget.spent_this_month(JULY)
    assert spent < 100, f"a month of news grading came to Rs {spent:,.2f}"
    assert budget.may_call(JULY)[0] is True


def test_status_reports_what_the_dashboard_needs(budget):
    budget.record("claude-haiku-4-5", input_tokens=1000, when=JULY)
    s = budget.status(JULY)
    assert s["month"] == "2026-07"
    assert s["calls"] == 1
    assert s["allowed"] is True
    assert s["cap_rs"] == 2500.0
    assert 0 <= s["pct"] < 1
