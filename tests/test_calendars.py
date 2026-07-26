"""
Tests for the market calendar (trading holidays) and the results
calendar (who reports when, and the earnings pulse).

Operator, 2026-07-26: the bot should be "in complete awareness of
trading holidays", should know "which stock will release their quarterly
result on which date & time", and should be able to answer "how many
times stocks are releasing their results & dividend/buyback/splits".
"""

from datetime import date, datetime

import pytest

from core.market_calendar import MarketCalendar
from core.results_calendar import (
    ResultsCalendar, looks_like_results,
)
from core.stock_memory import StockMemory


# ===============================================================
# Market calendar
# ===============================================================

@pytest.fixture
def cal(tmp_path):
    return MarketCalendar(url=f"sqlite:///{tmp_path}/cal.db")


def test_weekends_are_never_trading_days(cal):
    assert cal.is_trading_day(date(2026, 7, 24)) is True    # Friday
    assert cal.is_trading_day(date(2026, 7, 25)) is False   # Saturday
    assert cal.is_trading_day(date(2026, 7, 26)) is False   # Sunday
    assert cal.is_trading_day(date(2026, 7, 27)) is True    # Monday
    assert cal.reason(date(2026, 7, 25)) == "weekend"


def test_an_unknown_weekday_defaults_to_OPEN(cal):
    """Fail-SAFE direction: the worst case of a wrong 'open' is the bot
    waits for ticks that never come. The worst case of a wrong 'closed'
    is a lost session."""
    assert cal.count() == 0
    assert cal.is_trading_day(date(2026, 7, 27)) is True
    assert cal.reason(date(2026, 7, 27)) is None


def test_a_recorded_holiday_closes_the_day(cal):
    # 2026-01-26 (Republic Day) is a MONDAY -- deliberately a weekday,
    # so the holiday record is what closes it, not the weekend rule.
    cal.add("2026-01-26", "Republic Day")
    assert cal.is_trading_day(date(2026, 1, 26)) is False
    assert cal.reason(date(2026, 1, 26)) == "Republic Day"


def test_nse_description_wins_over_an_inferred_record(cal):
    cal.add("2026-06-26", "no bhavcopy published", source="INFERRED")
    cal.add("2026-06-26", "Bakri Id", source="NSE")
    assert cal.reason(date(2026, 6, 26)) == "Bakri Id"
    # ...and not the other way round
    cal.add("2026-06-26", "no bhavcopy published", source="INFERRED")
    assert cal.reason(date(2026, 6, 26)) == "Bakri Id"


def test_previous_trading_day_skips_a_long_weekend(cal):
    """This is the one that silently corrupts gap maths: after a Friday
    holiday, 'yesterday's close' is Thursday's, not Sunday's."""
    cal.add("2026-06-26", "holiday")                 # a Friday
    # Monday 2026-06-29 -> back past the weekend AND the Friday holiday
    assert cal.previous_trading_day(date(2026, 6, 29)) == date(2026, 6, 25)


def test_next_trading_day_skips_holidays(cal):
    cal.add("2026-08-17", "holiday")                 # a Monday
    assert cal.next_trading_day(date(2026, 8, 14)) == date(2026, 8, 18)


def test_learn_from_missing_days_ignores_weekends(cal):
    n = cal.learn_from_missing_days(
        ["2026-06-26", "2026-06-27", "2026-06-28"])  # Fri, Sat, Sun
    assert n == 1
    assert cal.is_holiday(date(2026, 6, 26)) is True
    assert cal.is_holiday(date(2026, 6, 27)) is False


def test_trading_days_between_counts_correctly(cal):
    cal.add("2026-08-12", "midweek holiday")         # a Wednesday
    days = cal.trading_days_between(date(2026, 8, 10), date(2026, 8, 16))
    # Mon 10, Tue 11, [Wed 12 holiday], Thu 13, Fri 14, [Sat/Sun]
    assert days == [date(2026, 8, 10), date(2026, 8, 11),
                    date(2026, 8, 13), date(2026, 8, 14)]


def test_upcoming_lists_only_the_window(cal):
    cal.add("2026-08-12", "near")
    cal.add("2027-01-26", "far")
    upcoming = cal.upcoming(days=60, frm=date(2026, 7, 26))
    assert [d.isoformat() for d, _ in upcoming] == ["2026-08-12"]


def test_add_is_idempotent(cal):
    cal.add("2026-01-26", "Republic Day")
    cal.add("2026-01-26", "Republic Day")
    assert cal.count() == 1


def test_garbage_dates_are_refused_not_fatal(cal):
    assert cal.add("not-a-date") is False
    assert cal.count() == 0


# ===============================================================
# Results calendar
# ===============================================================

@pytest.fixture
def results(tmp_path):
    return ResultsCalendar(url=f"sqlite:///{tmp_path}/res.db")


def test_looks_like_results_matches_the_real_purposes():
    assert looks_like_results("Quarterly Results")
    assert looks_like_results("To consider unaudited financial results")
    assert looks_like_results("Audited Financial Statement")
    assert not looks_like_results("Fund Raising")
    assert not looks_like_results("Appointment of Director")
    assert not looks_like_results("")


def test_symbols_on_replaces_the_hardcoded_dict(results):
    results.remember("TCS", "2026-07-28")
    results.remember("INFY", "2026-07-28")
    results.remember("WIPRO", "2026-07-29")
    assert results.symbols_on(date(2026, 7, 28)) == {"TCS", "INFY"}


def test_as_calendar_dict_matches_config_shape(results):
    results.remember("TCS", "2026-07-28")
    out = results.as_calendar_dict(frm=date(2026, 7, 26), days=10)
    assert out == {"2026-07-28": {"TCS"}}


def test_a_broadcast_time_fills_in_a_previously_unknown_one(results):
    """The date is known in advance; the TIME only afterwards. A later
    row carrying a timestamp must enrich the existing row."""
    results.remember("TCS", "2026-07-28", purpose="Quarterly Results")
    assert results.history_for("TCS")[0]["broadcast_at"] is None

    results.remember("TCS", "2026-07-28",
                     broadcast_at=datetime(2026, 7, 28, 16, 5))
    assert results.history_for("TCS")[0]["broadcast_at"] == \
        datetime(2026, 7, 28, 16, 5)


def test_a_known_time_is_never_blanked_by_a_later_row(results):
    results.remember("TCS", "2026-07-28",
                     broadcast_at=datetime(2026, 7, 28, 16, 5))
    results.remember("TCS", "2026-07-28", purpose="Quarterly Results")
    assert results.history_for("TCS")[0]["broadcast_at"] == \
        datetime(2026, 7, 28, 16, 5)


def test_earnings_pulse_needs_history_before_it_says_anything(results):
    results.remember("NEWCO", "2026-07-28",
                     broadcast_at=datetime(2026, 7, 28, 16, 0))
    assert results.typical_time("NEWCO") is None          # 1 sample
    assert "no timing history" in results.pulse("NEWCO")


def test_earnings_pulse_uses_the_MEDIAN_not_the_mean(results):
    """One result that slipped to 22:00 must not drag the estimate.

    Four quarters, because observed_times() takes at most one sample per
    calendar quarter -- a company reports four times a year."""
    for month, hh, mm in [(1, 16, 0), (4, 16, 10), (7, 15, 50),
                          (10, 22, 0)]:
        results.remember("HABIT", date(2026, month, 10),
                         broadcast_at=datetime(2026, month, 10, hh, mm))
    t = results.typical_time("HABIT")
    assert t["samples"] == 4
    assert t["hhmm"] == "16:05"          # median of 950,960,970,1320
    assert t["spread_minutes"] == 370    # the outlier is still VISIBLE


def test_pulse_reads_in_plain_english(results):
    for month in (1, 4, 7):
        results.remember("TCS", date(2026, month, 10),
                         broadcast_at=datetime(2026, month, 10, 16, 0))
    assert "usually reports around 16:00" in results.pulse("TCS")
    assert "3 past results" in results.pulse("TCS")


def test_only_ONE_sample_counts_per_quarter(results):
    """
    INFY, real data 2026-07-26: fifteen "results" in 400 days, including
    2026-04-16, 04-23 and 04-24 -- three in one quarter. Those extras are
    follow-up filings; counting them would weight Q2 four times as
    heavily as any other quarter.
    """
    for day in (16, 23, 24):
        results.remember("INFY", date(2026, 4, day),
                         broadcast_at=datetime(2026, 4, day, 16 + day % 3, 0))
    results.remember("INFY", date(2026, 7, 23),
                     broadcast_at=datetime(2026, 7, 23, 16, 20))

    assert len(results.observed_times("INFY")) == 2      # Q2 and Q3
    # ...and the EARLIEST of the April cluster is the one kept
    assert results.observed_times("INFY")[0] == 17 * 60  # the 16th, 17:00


def test_the_earliest_broadcast_of_the_day_wins(results):
    """Results day carries several documents -- the numbers first, then
    the presentation and the transcript. The first is when the market
    learned."""
    results.remember("X", date(2026, 4, 10),
                     broadcast_at=datetime(2026, 4, 10, 20, 0))
    results.remember("X", date(2026, 4, 10),
                     broadcast_at=datetime(2026, 4, 10, 16, 5))
    results.remember("X", date(2026, 4, 10),
                     broadcast_at=datetime(2026, 4, 10, 22, 30))
    assert results.history_for("X")[0]["broadcast_at"] == \
        datetime(2026, 4, 10, 16, 5)


def test_follow_up_documents_are_not_treated_as_results():
    """The 15-INFY bug. Each of these contains 'result' but is filed
    hours or days after the numbers.

    Note what is NOT here: "Intimation of board meeting for results".
    That one SHOULD pass -- looks_like_results() is used for board-meeting
    purposes, where an intimation is precisely how the bot learns a
    forthcoming results DATE. Announcements are judged separately, by
    is_results_announcement(), which can see the category."""
    for noise in (
        "Newspaper Publication of Financial Results",
        "Investor Presentation on Q1 Results",
        "Transcript of Earnings Call on results",
        "Audio recording of the results conference call",
        "Press Release - Q2 Results",
        "Corrigendum to financial results",
    ):
        assert looks_like_results(noise) is False, noise

    # ...while the filing itself still passes
    for real in ("Financial Results", "Unaudited Financial Results",
                 "Audited Financial Statement for the quarter"):
        assert looks_like_results(real) is True, real


def test_events_without_a_time_are_excluded_from_the_pulse(results):
    results.remember("MIXED", date(2026, 1, 10),
                     broadcast_at=datetime(2026, 1, 10, 16, 0))
    results.remember("MIXED", date(2026, 4, 10))          # no time
    results.remember("MIXED", date(2026, 7, 10),
                     broadcast_at=datetime(2026, 7, 10, 16, 30))
    assert results.typical_time("MIXED")["samples"] == 2


def test_stats_counts_how_much_timing_data_we_have(results):
    results.remember("A", date(2026, 1, 10),
                     broadcast_at=datetime(2026, 1, 10, 16, 0))
    results.remember("B", date(2026, 1, 10))
    assert results.stats() == dict(events=2, symbols=2, with_time=1)


def test_remember_refuses_junk(results):
    assert results.remember("", "2026-07-28") is False
    assert results.remember("TCS", "not-a-date") is False
    assert results.stats()["events"] == 0


# ===============================================================
# Stock memory -- the counting views
# ===============================================================

@pytest.fixture
def memory(tmp_path):
    return StockMemory(url=f"sqlite:///{tmp_path}/mem.db")


def test_counts_for_one_symbol(memory):
    memory.remember("TCS", "DIVIDEND", date(2026, 1, 10), "Rs 10")
    memory.remember("TCS", "DIVIDEND", date(2026, 4, 10), "Rs 12")
    memory.remember("TCS", "BUYBACK", date(2026, 5, 10), "Rs 4150/sh")
    assert memory.counts_for("TCS") == {"DIVIDEND": 2, "BUYBACK": 1}


def test_event_counts_across_the_universe(memory):
    memory.remember("A", "DIVIDEND", date(2026, 1, 10))
    memory.remember("B", "DIVIDEND", date(2026, 1, 11))
    memory.remember("C", "SPLIT", date(2026, 1, 12))
    counts = memory.event_counts()
    assert counts["DIVIDEND"] == 2
    assert counts["SPLIT"] == 1


def test_history_for_is_oldest_first(memory):
    memory.remember("X", "DIVIDEND", date(2026, 4, 10))
    memory.remember("X", "SPLIT", date(2026, 1, 10))
    assert [r["ex_date"] for r in memory.history_for("X")] == [
        date(2026, 1, 10), date(2026, 4, 10)]


def test_busiest_symbols_ranks_by_activity(memory):
    for i in range(3):
        memory.remember("BUSY", "DIVIDEND", date(2026, 1, 10 + i))
    memory.remember("QUIET", "SPLIT", date(2026, 1, 10))
    assert memory.busiest_symbols(limit=2)[0] == ("BUSY", 3)


def test_date_range(memory):
    memory.remember("X", "SPLIT", date(2026, 1, 10))
    memory.remember("Y", "BONUS", date(2026, 9, 10))
    assert memory.date_range() == (date(2026, 1, 10), date(2026, 9, 10))


def test_empty_memory_answers_cleanly(memory):
    assert memory.event_counts() == {}
    assert memory.counts_for("ANY") == {}
    assert memory.history_for("ANY") == []
    assert memory.date_range() == (None, None)


# ===============================================================
# Refresh cadence -- rare events should not be polled daily
# ===============================================================
# Operator, 2026-07-26: "Holiday list is just one time event per whole
# year... the result part now this would be 4 times per year and around
# 4 months per year. so here too we need not check in after results
# sessions completed."

def test_holidays_are_not_refetched_once_the_year_is_covered(cal):
    cal.add("2026-01-26", "Republic Day", source="NSE")
    assert cal.covers_year(2026) is True
    assert cal.needs_refresh(date(2026, 7, 27)) is False


def test_an_empty_year_still_needs_a_fetch(cal):
    assert cal.needs_refresh(date(2026, 7, 27)) is True


def test_inferred_holidays_do_NOT_count_as_covering_the_year(cal):
    """Otherwise one inferred holiday would stop us ever downloading the
    real list, and we would never learn the actual dates."""
    cal.add("2026-06-26", "no bhavcopy published", source="INFERRED")
    assert cal.covers_year(2026) is False
    assert cal.needs_refresh(date(2026, 7, 27)) is True


def test_december_looks_ahead_to_next_year(cal):
    """NSE publishes the new list in December; the bot should know about
    1 January before it arrives."""
    cal.add("2026-01-26", "Republic Day", source="NSE")
    assert cal.needs_refresh(date(2026, 12, 10)) is True
    cal.add("2027-01-26", "Republic Day", source="NSE")
    assert cal.needs_refresh(date(2026, 12, 10)) is False


def test_refresh_from_nse_skips_the_download_when_covered(cal, monkeypatch):
    called = []
    monkeypatch.setattr(cal, "add", lambda *a, **k: called.append(a))
    cal.engine  # noqa -- keep the fixture explicit
    # pre-populate via a direct insert so `add` isn't the thing we patch
    MarketCalendar.add(cal, "2026-01-26", "Republic Day", source="NSE")
    assert cal.refresh_from_nse(today=date(2026, 7, 27)) == 0


# --- results season -------------------------------------------

def test_results_season_months():
    from core.results_calendar import in_results_season
    for month in (1, 2, 4, 5, 7, 8, 10, 11):
        assert in_results_season(date(2026, month, 15)) is True
    for month in (3, 6, 9, 12):
        assert in_results_season(date(2026, month, 15)) is False


def test_first_ever_run_always_refreshes(results):
    assert results.needs_refresh(date(2026, 9, 15)) is True


def _seed_a_timing(results):
    """The cadence rules only apply once the pulse has worked at least
    once -- zero timings always forces a refresh (see
    test_zero_timings_always_forces_a_refresh)."""
    results.remember("SEED", date(2025, 1, 10),
                     broadcast_at=datetime(2025, 1, 10, 16, 0))


def test_in_season_refreshes_daily(results):
    _seed_a_timing(results)
    results.mark_refreshed(date(2026, 7, 26))
    assert results.needs_refresh(date(2026, 7, 26)) is False
    assert results.needs_refresh(date(2026, 7, 27)) is True


def test_off_season_refreshes_weekly(results):
    _seed_a_timing(results)
    results.mark_refreshed(date(2026, 9, 1))          # September
    assert results.needs_refresh(date(2026, 9, 5)) is False
    assert results.needs_refresh(date(2026, 9, 7)) is False
    assert results.needs_refresh(date(2026, 9, 8)) is True


def test_mark_refreshed_is_idempotent(results):
    results.mark_refreshed(date(2026, 7, 26))
    results.mark_refreshed(date(2026, 7, 26))
    assert results.last_refreshed() == date(2026, 7, 26)


def test_refresh_skips_when_nothing_is_due(results, monkeypatch):
    import core.results_calendar as rc
    calls = []
    monkeypatch.setattr(rc, "fetch_board_meetings",
                        lambda *a, **k: calls.append("bm") or 0)
    monkeypatch.setattr(rc, "fetch_filed_results",
                        lambda *a, **k: calls.append("fr") or 0)

    _seed_a_timing(results)
    results.mark_refreshed(date(2026, 9, 1))
    rc.refresh(calendar=results, today=date(2026, 9, 3))
    assert calls == []                       # off-season, only 2 days on

    rc.refresh(calendar=results, today=date(2026, 9, 3), force=True)
    assert calls == ["bm", "fr"]


def test_zero_timings_always_forces_a_refresh(results):
    """A throttle must never throttle something that has never worked.
    On 2026-07-26 this gate skipped the run carrying the fix for the
    empty pulse, because it had 'already refreshed today'."""
    results.mark_refreshed(date(2026, 7, 26))
    assert results.stats()["with_time"] == 0
    assert results.needs_refresh(date(2026, 7, 26)) is True

    # Once a single timing exists, the normal cadence applies again.
    results.remember("TCS", date(2026, 7, 20),
                     broadcast_at=datetime(2026, 7, 20, 16, 0))
    assert results.needs_refresh(date(2026, 7, 26)) is False


# ===============================================================
# Category filtering -- the 598-minute-spread bug
# ===============================================================
# Real data, 2026-07-26. NSE's `desc` is the announcement CATEGORY, and
# all three of these mention "results" in the body:
#
#   Outcome of Board Meeting   13:58 14:06 14:11 15:05  <- the numbers
#   Shareholders meeting       21:15 23:27 23:56 19:39  <- AGM minutes
#   Updates                    15:19 16:27 21:02        <- misc
#
# Matching the body swept in AGM proceedings filed near midnight, which
# is how ASIANPAINT got a 598-minute "habit".

def test_board_meeting_outcome_is_the_results_filing():
    from core.results_calendar import is_results_announcement
    assert is_results_announcement(
        "Outcome of Board Meeting",
        "The Board of Directors at their meeting held today approved the "
        "unaudited financial results for the quarter") is True


def test_shareholders_meeting_is_never_the_results(  ):
    """ASIANPAINT 2025-06-26 21:15 and 2026-07-09 23:56 -- AGM minutes
    that mention results, filed near midnight."""
    from core.results_calendar import is_results_announcement
    assert is_results_announcement(
        "Shareholders meeting",
        "Please find enclosed herewith the Summary of proceedings ... "
        "financial results were adopted") is False


def test_updates_category_is_never_the_results():
    """INFY 2026-04-16 and 2025-07-15 -- 'Updates' rows that put three
    entries into a single quarter."""
    from core.results_calendar import is_results_announcement
    assert is_results_announcement(
        "Updates",
        "Infosys Limited has informed the Exchange regarding results") \
        is False


def test_a_board_meeting_about_something_else_is_not_results():
    """Board meetings also approve fundraising and appointments."""
    from core.results_calendar import is_results_announcement
    assert is_results_announcement(
        "Outcome of Board Meeting",
        "The Board approved raising of funds via NCDs") is False


def test_follow_up_documents_are_still_excluded():
    from core.results_calendar import is_results_announcement
    for desc in ("Investor Presentation", "Newspaper Publication",
                 "Analyst Meet", "Press Release"):
        assert is_results_announcement(desc, "financial results") is False, desc


def test_empty_input_is_not_results():
    from core.results_calendar import is_results_announcement
    assert is_results_announcement("", "") is False
    assert is_results_announcement(None, None) is False


# ===============================================================
# Reliability -- some companies genuinely have no habit
# ===============================================================

def test_exchange_clarifications_are_not_results():
    """NESCO carried three, ACI two. The exchange queries a filing days
    later and the company replies -- at any hour."""
    from core.results_calendar import is_results_announcement
    assert is_results_announcement(
        "Clarification - Financial Results",
        "The Exchange has sought clarification") is False
    assert is_results_announcement(
        "Reply to Clarification- Financial results",
        "The Exchange had sought clarification") is False


def test_a_tight_pattern_is_reliable(results):
    """TCS: 15:57 15:52 15:50 15:55 15:52 -- a 7-minute spread."""
    for month, hh, mm in [(1, 15, 50), (4, 15, 55), (7, 15, 52),
                          (10, 15, 57)]:
        results.remember("TCS", date(2026, month, 10),
                         broadcast_at=datetime(2026, month, 10, hh, mm))
    t = results.typical_time("TCS")
    assert t["reliable"] is True
    assert t["spread_minutes"] == 7
    assert "usually reports around" in results.pulse("TCS")


def test_a_scattered_pattern_is_NOT_reliable(results):
    """COFORGE: 21:54 16:10 23:35 16:58, all genuine board-meeting
    outcomes. A median of 17:06 is arithmetically true and useless."""
    for month, hh, mm in [(1, 21, 54), (4, 16, 10), (7, 23, 35),
                          (10, 16, 58)]:
        results.remember("COFORGE", date(2026, month, 10),
                         broadcast_at=datetime(2026, month, 10, hh, mm))
    t = results.typical_time("COFORGE")
    assert t["reliable"] is False
    assert t["spread_minutes"] > 120
    assert "NO reliable pattern" in results.pulse("COFORGE")
    assert "do not rely on it" in results.pulse("COFORGE")


def test_two_samples_is_never_reliable_however_tight(results):
    """Two quarters cannot establish a habit, even if identical."""
    for month in (1, 4):
        results.remember("THIN", date(2026, month, 10),
                         broadcast_at=datetime(2026, month, 10, 16, 0))
    t = results.typical_time("THIN")
    assert t["samples"] == 2
    assert t["spread_minutes"] == 0
    assert t["reliable"] is False
