"""A card posted today can describe news from three weeks ago.

    "i want the bot to see the stocks only gaining + reason behind
     that"                                    -- operator, 29 Aug 2026

The Breakouts and Earnings channels stamp a clock marker saying when
the thing they describe actually happened. The card is POSTED today,
so `at` is today and the previous-close window lets it through, while
the news inside it is weeks old.

61 such cards existed on 29 August 2026. 14 were being accepted as
today's reason -- every one of them carrying a RESULT grade, because
the "a scanner is not a news source" guard only covered the ungraded
branch. MARINE was the best trade in the 28 August reconstruction and
its stated reason was 21 days old.

No wall-clock dates here: every event carries its own `at` and the
matching `on_date` is passed explicitly, so this test reads the same
in six months as it does today.
"""

from core.why_moving import (
    STALE_REASON_HOURS,
    direction_of_grade,
    from_events,
    is_stale_reason,
    stated_age_hours,
)

CLOCK = "\U0001f552"
DAY = "2026-08-28"


def _event(headline, kind="NEWS", grade=None, at=DAY + "T10:33:00+00:00",
           source="Day Trader Telugu"):
    """One stored event.

    The source defaults to a normal PRO channel on purpose. An
    UNGRADED news item from Breakouts is already refused by the "a
    scanner is not a news source" guard of 8 August, so building the
    fixtures on that source would hide whether the age gate fired at
    all. The graded cases below pass source="Breakouts" explicitly,
    because the graded branch never consulted the source -- which is
    exactly the hole this file covers.
    """
    return {"symbol": "TESTCO", "at": at, "kind": kind,
            "grade": grade, "headline": headline, "source": source}


# ---------------------------------------------------------------- parsing

def test_it_reads_the_age_the_card_stamped():
    got = stated_age_hours(
        "#LAURUSLABS " + CLOCK + " Recent activity · 29d ago")
    assert got == 29 * 24.0


def test_hours_are_hours_and_days_are_days():
    assert stated_age_hours("#X " + CLOCK + " Order received 20h ago") == 20.0
    assert stated_age_hours("#X " + CLOCK + " News published 4d ago") == 96.0


def test_a_live_quote_widget_is_eight_minutes_not_eight_months():
    """The bug this parser was almost written with.

    "NSE - Live + 8m ago" carries no clock marker and means eight
    MINUTES. Reading a bare "m" as months made a fresh card look
    eight months stale.
    """
    line = "/TMPV TMPV +0.55% | NSE - Live + 8m ago"
    assert stated_age_hours(line) is None
    assert not is_stale_reason(line)


def test_a_card_that_states_no_age_is_not_called_stale():
    """None means "did not say", which is not the same as fresh.

    Those are left to the `at` window to judge, exactly as before.
    """
    line = "HERO MOTOCORP: CO.INVESTS RUPEES 960 CR IN ATHER ENERGY"
    assert stated_age_hours(line) is None
    assert not is_stale_reason(line)


# ---------------------------------------------------------------- the gate

def test_overnight_news_is_still_a_reason_this_morning():
    """20h ago is why it gaps. Hours stay; days do not."""
    line = "#SIGMAADV " + CLOCK + " Order received 20h ago"
    assert not is_stale_reason(line)
    assert from_events([_event(line, kind="ORDER")], on_date=DAY)


def test_a_day_old_recap_is_refused():
    line = "#CLSEL " + CLOCK + " Recent activity · 1d ago"
    assert stated_age_hours(line) == STALE_REASON_HOURS
    assert is_stale_reason(line)
    assert from_events([_event(line)], on_date=DAY) is None


def test_a_graded_recap_cannot_slip_past_the_scanner_guard():
    """The exact hole: 14 of 14 accepted cards carried a grade.

    The ungraded branch checks the source; the graded branch never
    did, so a RESULT recap bypassed it entirely.
    """
    line = "#LAURUSLABS " + CLOCK + " Recent activity · 29d ago"
    # Only grades that carry a DIRECTION reach the graded branch. "OK"
    # resolves to UNKNOWN and falls through to the ungraded one, where
    # the source guard already stops it -- so asking direction_of_grade
    # keeps this test aimed at the hole rather than at a grade list
    # that may grow later.
    graded = [g for g in ("EXCELLENT", "GREAT", "GOOD", "OK", "WEAK")
              if direction_of_grade(g) != "UNKNOWN"]
    assert graded, "no directional grades -- the fixture has gone stale"
    for grade in graded:
        event = _event(line, kind="RESULT", grade=grade, source="Breakouts")
        assert from_events([event], on_date=DAY) is None, grade
        # And the same card without the age stamp still IS a reason,
        # so this test is proving the gate rather than the source.
        fresh = _event("#LAURUSLABS Q1 revenue up 34% on API demand",
                       kind="RESULT", grade=grade, source="Breakouts")
        assert from_events([fresh], on_date=DAY) is not None, grade


def test_an_ai_verdict_on_stale_news_is_still_stale():
    """The verdict was written ABOUT the event. Old event, old verdict."""
    event = _event("#MARINE " + CLOCK + " Recent activity · 21d ago",
                   kind="ORDER")
    event["ai_reason"] = "Large order win lifts the revenue outlook"
    event["ai_direction"] = "POSITIVE"
    event["ai_confidence"] = 0.9
    assert from_events([event], on_date=DAY) is None


def test_the_fresh_card_beside_it_still_wins():
    """Refusing the recap must not cost the stock its real reason.

    ATHERENERG on 28 August held both: a 08:15 pre-market item worth
    Rs1,758 cr, and a 10:33 card saying "News published 2d ago".
    """
    real = ("STSCK IN NEWS To buy additional stake in Ather Energy for "
            "1,758 cr, shareholding would increase to up to ~32.8%")
    events = [
        _event("#ATHERENERG " + CLOCK + " News published 2d ago",
               at=DAY + "T10:33:00+00:00"),
        _event(real, at=DAY + "T08:15:00+00:00"),
    ]
    got = from_events(events, on_date=DAY)
    assert got is not None
    assert "1,758" in got["text"]
