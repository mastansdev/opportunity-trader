"""
Decision-correctness tests for the AI call budget cap. The
whole point of this module is that the cap cannot be evaded
by a restart, and cannot be exceeded silently.
"""

import json
import os

from news_bot.call_budget import CallBudget


def test_fresh_budget_starts_at_zero_and_allows_spending(tmp_path):
    path = os.path.join(str(tmp_path), "budget.json")
    budget = CallBudget(path=path, limit=5)

    assert budget.count_today() == 0
    assert budget.remaining() == 5
    assert budget.can_spend(1) is True


def test_record_call_increments_and_persists(tmp_path):
    path = os.path.join(str(tmp_path), "budget.json")
    budget = CallBudget(path=path, limit=5)

    budget.record_call()
    budget.record_call()

    assert budget.count_today() == 2
    assert budget.remaining() == 3

    # A fresh instance reading the same file must see the same count --
    # this is what makes the cap survive a restart.
    reloaded = CallBudget(path=path, limit=5)
    assert reloaded.count_today() == 2


def test_cannot_spend_past_the_limit(tmp_path):
    path = os.path.join(str(tmp_path), "budget.json")
    budget = CallBudget(path=path, limit=2)

    budget.record_call()
    budget.record_call()

    assert budget.can_spend(1) is False
    assert budget.remaining() == 0


def test_a_saved_count_from_a_previous_day_resets_to_zero(tmp_path):
    path = os.path.join(str(tmp_path), "budget.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"date": "1999-01-01", "count": 999}, f)

    budget = CallBudget(path=path, limit=5)

    assert budget.count_today() == 0
    assert budget.remaining() == 5


def test_corrupt_file_starts_clean_not_a_crash(tmp_path):
    path = os.path.join(str(tmp_path), "budget.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not valid json")

    budget = CallBudget(path=path, limit=5)

    assert budget.count_today() == 0
