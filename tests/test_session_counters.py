"""
Per-day counters must survive a mid-session restart -- 29 July 2026.

Found in the integration check after the evening's work, not by a
failing test. Two counters lived only in memory:

    _rotations_today     the 5-swap daily cap. A restart reset it to 0,
                         so the bot could swap five times before lunch
                         and five more after -- ten swaps against a cap
                         of five, silently.

    _news_alerted        which filings had already been announced. A
                         restart re-announced every one of them.

Both are now saved with the rest of the session state, under the same
"today only" rule as everything else in core/state_store.py: yesterday's
rotation count must never carry into today.
"""

import json

import pytest

from core.engine import Engine
from core import state_store


def test_the_rotation_count_is_exported():
    engine = Engine()
    engine._rotations_today = 3
    assert engine.export_session_counters()["rotations_today"] == 3


def test_the_rotation_count_is_restored():
    """The real failure: five swaps before a restart, five more after,
    against a cap of five."""
    engine = Engine()
    engine.load_session_counters({"rotations_today": 5})
    assert engine._rotations_today == 5


def test_already_announced_news_is_not_announced_again(tmp_path):
    engine = Engine()
    engine._news_alerted.add(("PCBL", "filing", "14:19"))
    saved = engine.export_session_counters()

    fresh = Engine()
    fresh.load_session_counters(saved)
    assert ("PCBL", "filing", "14:19") in fresh._news_alerted


def test_manual_alerts_are_not_repeated_after_a_restart():
    engine = Engine()
    engine._manual_alerts_seen.add(("SMLMAH", "HELD"))
    fresh = Engine()
    fresh.load_session_counters(engine.export_session_counters())
    assert ("SMLMAH", "HELD") in fresh._manual_alerts_seen


def test_a_round_trip_through_the_state_file(tmp_path):
    path = str(tmp_path / "state.json")
    engine = Engine()
    engine._rotations_today = 4
    engine._news_alerted.add(("KAYNES", "news", "10:30"))

    state_store.save({}, {}, session_counters=engine.export_session_counters(),
                     path=path)
    restored = state_store.load_session_counters(path=path)

    fresh = Engine()
    fresh.load_session_counters(restored)
    assert fresh._rotations_today == 4
    assert ("KAYNES", "news", "10:30") in fresh._news_alerted


def test_yesterdays_counters_are_never_carried_into_today(tmp_path):
    """A rotation cap that carries overnight would start the day
    already spent."""
    path = str(tmp_path / "state.json")
    state_store.save({}, {}, session_counters={"rotations_today": 5},
                     path=path)
    payload = json.load(open(path, encoding="utf-8"))
    payload["date"] = "2020-01-01"
    json.dump(payload, open(path, "w", encoding="utf-8"))

    assert state_store.load_session_counters(path=path) == {}


def test_a_missing_or_corrupt_file_is_survivable(tmp_path):
    assert state_store.load_session_counters(path=str(tmp_path / "nope.json")) == {}
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert state_store.load_session_counters(path=str(bad)) == {}


def test_junk_counters_do_not_stop_a_restart():
    """Bad saved state must mean 'start that counter fresh', never
    'refuse to start'."""
    engine = Engine()
    for junk in (None, {}, {"rotations_today": "five"}, {"news_alerted": 7}):
        engine.load_session_counters(junk)
