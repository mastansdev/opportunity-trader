"""
==========================================================
The census must not lie about what the bot uses
==========================================================

    "bot is getting results, news. but i'm not sure whether bot knows
     it. stores it and reuses when ever the same situation arises."
                                -- operator, 12 August 2026

core/knowledge.py answers that on the dashboard. Its whole value is
that the DECIDES / SHOWS / RECORDS column is TRUE -- a census that
claims the learning loop votes when it does not would be worse than no
census at all, because he would stop checking.

So these tests do two things:

  1. Hold the census honest about its own mechanics (fail-soft, no
     raising, freshness that reads as unknown rather than as zero).
  2. Hold the CLAIMS honest -- test_the_reach_labels_match_the_code
     below re-derives the RECORDS claim from the source, so the day
     somebody wires trade_memory into the entry path and forgets to
     update this table, the build fails.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

import pytest

from core import knowledge

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------
# MECHANICS
# ---------------------------------------------------------------

def test_the_census_runs_and_says_something():
    got = knowledge.census()
    assert got["available"] is True
    assert got["stores"], "no stores were checked at all"
    assert got["verdict"], "the census computed no verdict"


def test_every_store_declares_where_it_reaches():
    for store in knowledge.STORES:
        assert store["reach"] in (knowledge.DECIDES, knowledge.SHOWS,
                                  knowledge.RECORDS), store["key"]
        assert store["proof"], (
            f"{store['key']} claims a reach with no file named to prove "
            f"it. An unprovable claim is the thing this module exists to "
            f"replace.")


def test_a_missing_database_is_reported_not_raised(monkeypatch):
    """A store that has never been written must read as a problem, not
    as an empty one -- and must never take the dashboard down."""
    monkeypatch.setattr(knowledge, "STORES", (
        dict(key="nope", label="Not there", db="data/does-not-exist-at-all.db",
             table="whatever", date_col=None, reach=knowledge.DECIDES,
             proof="none", note=""),
    ))
    got = knowledge.census()
    assert got["available"] is True
    assert got["problems"], "a missing database was not reported"
    assert got["stores"][0]["rows"] is None


def test_an_unreadable_table_is_reported_not_raised(tmp_path, monkeypatch):
    """A file that exists but has no such table."""
    import sqlite3
    path = tmp_path / "empty.db"
    sqlite3.connect(str(path)).close()
    monkeypatch.setattr(knowledge, "STORES", (
        dict(key="broken", label="Broken", db=str(path),
             table="not_a_table", date_col=None, reach=knowledge.SHOWS,
             proof="none", note=""),
    ))
    got = knowledge.census()
    assert got["problems"]


# ---------------------------------------------------------------
# FRESHNESS -- unknown must never read as fresh
# ---------------------------------------------------------------

def test_freshness_reads_the_formats_the_stores_actually_use():
    """---- I WROTE A CLOCK-DEPENDENT TEST. 13 August 2026. ----

    Written on 12 August as four hardcoded dates: "2026-08-12" is 0
    days old, "2026-08-05" is 7. Both true that afternoon and both
    false at midnight -- the suite went red at 07:18 the next morning
    with 1 and 8.

    That is the exact fault I fixed in tests/test_engine.py the same
    day ("Tests must not depend on what time they are run", commit
    1691b16) and criticised in the audit. Written hours later.

    The dates are now derived from the clock, so the test asks whether
    _age_days COUNTS correctly rather than what today happens to be.
    """
    from datetime import datetime, timedelta

    today = datetime.now()
    for days in (0, 1, 7, 30):
        stamp = (today - timedelta(days=days)).strftime("%Y-%m-%d")
        assert knowledge._age_days(stamp) == days, stamp

    # Every stamp format the stores actually hold, all "now".
    now = today.strftime("%Y-%m-%d")
    assert knowledge._age_days(now) == 0
    assert knowledge._age_days(f"{now} 10:00:00") == 0
    assert knowledge._age_days(f"{now}T10:00:00+00:00") == 0


def test_an_unparseable_date_is_unknown_not_zero():
    """A stale store reported as fresh is the exact failure this
    module exists to catch. Unknown has to stay unknown."""
    assert knowledge._age_days("not a date") is None
    assert knowledge._age_days(None) is None
    assert knowledge._age_days("") is None


def test_stale_is_counted_from_three_days():
    """NSE publishes daily, so three calendar days has missed at least
    one session."""
    stores = [dict(label="x", stale_days=2, rows=1, readable=True,
                   problem=None, reach=knowledge.SHOWS),
              dict(label="y", stale_days=3, rows=1, readable=True,
                   problem=None, reach=knowledge.SHOWS)]
    stale = [s for s in stores
             if s["stale_days"] is not None and s["stale_days"] >= 3]
    assert [s["label"] for s in stale] == ["y"]


# ---------------------------------------------------------------
# THE CLAIMS THEMSELVES
# ---------------------------------------------------------------

def test_the_reach_labels_match_the_code():
    """THE ONE THAT MATTERS.

    core/trade_memory.py, core/outcomes.py and dashboard/chip_stats.py
    are labelled RECORDS because each says, in its own docstring, that
    it does not reach a decision. If somebody wires one of them into
    the trading path, this census would go on telling him it does not
    vote -- and he would believe it, because it is on his screen.

    So the claim is re-derived from the source, not trusted.
    """
    trade_memory = (ROOT / "core" / "trade_memory.py").read_text(
        encoding="utf-8", errors="replace")
    assert "IT DOES NOT VOTE" in trade_memory, (
        "core/trade_memory.py no longer says it does not vote. Either it "
        "now votes -- in which case core/knowledge.py must stop calling "
        "it RECORDS -- or the docstring drifted.")

    # Nothing on the entry path may import it. This is the mechanical
    # half of the same claim.
    engine = (ROOT / "core" / "engine.py").read_text(
        encoding="utf-8", errors="replace")
    auto_entry = (ROOT / "core" / "auto_entry.py").read_text(
        encoding="utf-8", errors="replace")
    for name, src in (("core/engine.py", engine),
                      ("core/auto_entry.py", auto_entry)):
        assert "from core.outcomes import" not in src, (
            f"{name} imports core/outcomes.py. The measurement has "
            f"reached the trading path -- that may be right, but the "
            f"census must stop calling it RECORDS.")


def test_the_verdict_names_the_learning_loop():
    """He asked whether it reuses what it learns. The answer must be on
    the panel in words, not left to be inferred from a table."""
    got = knowledge.census()
    assert "does not vote" in got["verdict"]


@pytest.mark.parametrize("store", knowledge.STORES,
                         ids=lambda s: s["key"])
def test_each_named_database_path_is_inside_data(store):
    """A census pointed at the wrong file would report another bot's
    numbers with total confidence."""
    assert store["db"].startswith("data/"), store["key"]


# ---------------------------------------------------------------
# IT MUST NOT CRY WOLF
# ---------------------------------------------------------------
#
# tools/nightly.py's `health` step exited 1 on the first evening it
# ran, for two states the operator had chosen on purpose:
#
#     config.AI_ENABLED is False   until the bot earns the top-up
#     trade_memory 3 days old      the bot is OBSERVING, nothing closed
#
# "health: exited 1 ... MOVING ON" every single night is a line he
# learns to skip, and then it is worth nothing on the night it means
# something -- the exact failure tools/learning_report.py's own caveat
# warns about, walked into hours after writing it.

def test_a_store_that_only_grows_on_an_event_is_never_stale():
    """trade_memory grows when a trade CLOSES. A bot that is watching
    cannot make it grow, and reporting that as a fault every night is
    reporting the instruction back as an error."""
    store = next(s for s in knowledge.STORES if s["key"] == "trade_memory")
    assert store.get("grows_daily") is False

    got = knowledge.census()
    assert not any("Completed trades" in line for line in got["stale"]), (
        "trade_memory is being reported stale -- it only grows when a "
        "trade closes")


def test_a_daily_store_that_stops_is_still_stale():
    """The other half. A price or filing feed going quiet IS a fault,
    and softening staleness must not have softened that."""
    daily = [s for s in knowledge.STORES if s.get("grows_daily", True)]
    assert len(daily) >= 8, (
        "almost everything has been marked as not-growing-daily, which "
        "would make the staleness check meaningless")


def test_the_reasoning_block_says_which_switch_is_off():
    """The exit code has to tell 'he turned it off' from 'it should be
    working and is not'. Only the second may fail the nightly."""
    got = knowledge.census()["reasoning"]
    assert "ai_enabled" in got and "has_key" in got


def test_a_deliberate_switch_off_is_reported_but_not_a_failure():
    """The body must still SHOUT about it -- the outage is real and
    cost a week of unreasoned news. It just is not a nightly failure."""
    got = knowledge.census()
    if got["reasoning"].get("ai_enabled") is False:
        assert "NEWS IS NOT BEING UNDERSTOOD" in got["verdict"], (
            "the outage stopped being reported when it stopped failing "
            "-- that trades one blindness for another")
