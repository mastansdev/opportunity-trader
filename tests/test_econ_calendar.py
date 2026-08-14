"""
Tests for core/econ_calendar.py.

    "dashboard is not equipped with all my requirements. it doesn't
     know when FED meeting, RBI Meeting will happen"
                                    -- operator, 29 July 2026

The distinction the whole module exists to make, and which the
operator worked out himself before I did:

    FOMC   23:30 IST, he is flat and asleep. Nothing to pause.
    RBI    ~10:00 IST, INSIDE the session, positions open.

He was right and I was wrong twice about this, so it is a test.
"""

from datetime import date

from core.econ_calendar import (EVENTS, in_session_today, next_event,
                                upcoming)


def _event(dates, key="x", during_session=False):
    return {"key": key, "name": key.upper(), "at": "10:00 IST",
            "during_session": during_session, "note": "", "dates": dates}


# ---------------------------------------------------------------

def test_it_finds_the_next_date_not_the_first():
    event = _event([date(2026, 1, 28), date(2026, 8, 5), date(2026, 12, 9)])
    assert next_event(event, date(2026, 7, 29))["date"] == "2026-08-05"


def test_today_counts_as_upcoming_not_past():
    """An event landing at 10:00 is still ahead of you at 09:15."""
    row = next_event(_event([date(2026, 8, 5)]), date(2026, 8, 5))
    assert row["today"] is True
    assert row["days_away"] == 0
    assert row["when"] == "TODAY"


def test_the_countdown_reads_the_way_a_person_says_it():
    dates = [date(2026, 8, 5)]
    assert next_event(_event(dates), date(2026, 8, 4))["when"] == "tomorrow"
    assert next_event(_event(dates), date(2026, 7, 29))["when"] == "in 7 days"


def test_events_are_sorted_by_how_soon_they_are():
    rows = upcoming(date(2026, 7, 29), [
        _event([date(2026, 12, 9)], "far"),
        _event([date(2026, 8, 5)], "soon"),
    ])["rows"]
    assert [r["key"] for r in rows] == ["soon", "far"]


# ---------------------------------------------------------------
# the one distinction that matters
# ---------------------------------------------------------------

def test_rbi_is_marked_as_landing_inside_our_session():
    """~10:00 IST, with positions open. This is the actionable one."""
    rbi = next(e for e in EVENTS if e["key"] == "rbi")
    assert rbi["during_session"] is True


def test_fomc_is_marked_as_landing_outside_it():
    """23:30 IST. The operator settled this himself: "FED meeting will
    be completed by our market opening... we are not trading live
    markets & no positions held, then whats our problem now?" A
    pause rule would only ever have cost money."""
    fomc = next(e for e in EVENTS if e["key"] == "fomc")
    assert fomc["during_session"] is False


def test_in_session_today_fires_for_rbi_and_not_for_the_fed():
    assert in_session_today(date(2026, 8, 5)) is not None
    assert in_session_today(date(2026, 8, 5))["key"] == "rbi"
    assert in_session_today(date(2026, 7, 29)) is None   # FOMC day
    assert in_session_today(date(2026, 8, 12)) is None   # CPI day


def test_the_rbi_decision_two_days_after_going_live_is_on_the_list():
    """Live on 3 August. RBI decides on the 5th, at 10:00, with
    positions open."""
    rbi = next_event(next(e for e in EVENTS if e["key"] == "rbi"),
                     date(2026, 8, 3))
    assert rbi["date"] == "2026-08-05"
    assert rbi["days_away"] == 2


# ---------------------------------------------------------------
# a calendar that has run out must say so
# ---------------------------------------------------------------

def test_an_exhausted_calendar_is_reported_not_silently_empty():
    """An expired calendar and an empty one would otherwise look
    identical on screen, and there would be no way to tell which."""
    result = upcoming(date(2030, 1, 1), [_event([date(2026, 8, 5)], "old")])
    assert result["rows"] == []
    assert result["expired"] == ["OLD"]
    assert result["needs_update"] is True


def test_a_live_calendar_does_not_cry_wolf():
    result = upcoming(date(2026, 7, 29))
    assert result["needs_update"] is False
    assert result["expired"] == []
    assert len(result["rows"]) == 3


def test_one_exhausted_event_does_not_hide_the_others():
    result = upcoming(date(2026, 9, 1), [
        _event([date(2026, 8, 5)], "gone"),
        _event([date(2026, 12, 9)], "still_here"),
    ])
    assert [r["key"] for r in result["rows"]] == ["still_here"]
    assert result["expired"] == ["GONE"]


def test_every_shipped_event_has_dates_running_past_go_live():
    """Live on 3 August 2026. A calendar that expires in week one is
    worse than none."""
    for event in EVENTS:
        assert max(event["dates"]) > date(2026, 12, 1), event["name"]
