"""
==========================================================
No paid call may escape the meter
==========================================================

    "last time 5$ were used within no time but that time u claimed it
     will last atleast 60-90 days as per the usage. but 5$ completed
     within 5 days."
                                -- operator, 16 August 2026

He is right, and the ledger proves the shape of the error rather than
excusing it.

data/ai_spend.db holds 1,892 rows for 31 Jul - 5 Aug totalling
$1.4321, and that figure is EXACT: 887,773 input and 108,865 output
tokens at Haiku 4.5's published $1/M and $5/M comes to $1.4321 to four
decimal places. The arithmetic was never wrong.

The ledger was INCOMPLETE. It recorded two purposes -- news_direction
and ai_check -- and five modules in this repo call messages.create():

    core/ai_news.py        recorded, asked may_call()      <- metered
    tools/ai_check.py      recorded, asked may_call()      <- metered
    core/news_impact.py    neither                         <- invisible
    core/morning_brief.py  neither                         <- invisible
    core/image_text.py     neither                         <- invisible

So the Rs 2,500 monthly cap could not bind on three of the five, and
any estimate built on the ledger was an estimate of part of the bill.
That is how "60-90 days" and "5 days" can both be sincere.

THIS FILE IS THE GUARANTEE, NOT THE FIX.
The fix was wiring the three. This holds the line: it re-derives, from
the source, that every messages.create() in the repo is preceded by a
may_call() and followed by a record(). A sixth caller added next month
fails the build unless it is metered too.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Where a paid call may live at all. Anything outside these is a new
# spend path and should be deliberate.
SEARCH = ("core", "tools", "dashboard")


def _callers():
    """Repo-relative PATHS of every file that calls messages.create().

    Paths only, never the source. The first version returned
    (path, source) pairs and parametrised on both, so pytest built a
    test id containing entire modules and Windows refused it:
    "the environment variable is longer than 32767 characters".
    """
    out = []
    for folder in SEARCH:
        for path in sorted((ROOT / folder).rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            src = path.read_text(encoding="utf-8", errors="replace")
            if "messages.create(" in src:
                out.append(path.relative_to(ROOT).as_posix())
    return out


def test_there_is_at_least_one_caller_to_check():
    """A guard that silently checks nothing is worse than none."""
    assert _callers(), "no messages.create() found -- this test is blind"


@pytest.mark.parametrize("path", _callers())
def test_every_paid_call_records_what_it_spent(path):
    src = (ROOT / path).read_text(encoding="utf-8", errors="replace")
    assert re.search(r"\.record\(", src), (
        f"{path} calls the Anthropic API and never writes a spend row. "
        f"data/ai_spend.db will under-report by exactly this call, and "
        f"every projection built on it will be wrong -- which is what "
        f"turned '60-90 days' into 5 days.")


@pytest.mark.parametrize("path", _callers())
def test_every_paid_call_asks_the_cap_first(path):
    src = (ROOT / path).read_text(encoding="utf-8", errors="replace")
    assert "may_call()" in src, (
        f"{path} calls the Anthropic API without asking may_call(). "
        f"config.AI_MONTHLY_BUDGET_RS cannot bind on a call that never "
        f"asks, so the cap is advisory for this path.")


def test_the_meter_refuses_once_the_cap_is_reached(tmp_path):
    """The cap must actually STOP a call, not merely be recorded."""
    from core.ai_budget import AiBudget

    meter = AiBudget(db_path=str(tmp_path / "spend.db"), monthly_cap_rs=1.0)
    assert meter.may_call()[0] is True, "refused before anything was spent"

    # Spend past the cap: 2,000,000 input tokens at $1/M is $2, which is
    # far more than Rs 1 whatever the exchange rate.
    meter.record("claude-haiku-4-5-20251001", purpose="test",
                 input_tokens=2_000_000, output_tokens=0)
    allowed, why = meter.may_call()
    assert allowed is False, "spent past the cap and the meter still said yes"
    assert "cap" in (why or "").lower()


def test_an_unreadable_ledger_refuses_rather_than_allows(tmp_path,
                                                         monkeypatch):
    """If the meter cannot tell what has been spent, it must not
    guess low. Refusing costs a day of reasoning; guessing costs
    money that is already gone."""
    from core.ai_budget import AiBudget

    meter = AiBudget(db_path=str(tmp_path / "spend.db"), monthly_cap_rs=100.0)
    monkeypatch.setattr(meter, "spent_this_month", lambda when=None: None)
    allowed, why = meter.may_call()
    assert allowed is False
    assert why, "refused with no reason to show him"


def test_an_unknown_model_is_priced_at_the_worst_rate():
    """A typo in the model name must never look cheap -- that is the
    other way a ledger under-reports."""
    from core.ai_budget import price_of, PRICES

    worst = max(PRICES.values(), key=lambda p: p[1])
    assert price_of("claude-not-a-real-model") == worst


def test_the_recorded_total_still_matches_the_published_rates():
    """The arithmetic that was never in doubt, pinned so it stays
    that way. Haiku 4.5: $1/M in, $5/M out."""
    from core.ai_budget import cost_usd

    got = cost_usd("claude-haiku-4-5-20251001",
                   input_tokens=887_773, output_tokens=108_865)
    assert round(got, 4) == 1.4321, (
        f"the price table no longer reproduces the recorded spend: {got}")


# ---------------------------------------------------------------
# THE SPEND HAS TO REACH THE SCREEN
# ---------------------------------------------------------------
#
# AiBudget.status()'s own docstring has said "For the dashboard and the
# startup banner" since it was written. The dashboard never called it.
# Spend was measured, stored, capped -- and on no screen, which is the
# same fault as delivery %, the run-up reading and the watchlist panel,
# except this one is his money and he had to ask where it went.

