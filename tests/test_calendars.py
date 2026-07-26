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
    """One result that slipped to 22:00 must not drag the estimate."""
    for day, hh, mm in [(10, 16, 0), (11, 16, 10), (12, 15, 50),
                        (13, 22, 0)]:
        results.remember("HABIT", date(2026, 1, day),
                         broadcast_at=datetime(2026, 1, day, hh, mm))
    t = results.typical_time("HABIT")
    assert t["samples"] == 4
    assert t["hhmm"] == "16:05"          # median of 950,960,970,1320
    assert t["spread_minutes"] == 370    # the outlier is still VISIBLE


def test_pulse_reads_in_plain_english(results):
    for day in (10, 11, 12):
        results.remember("TCS", date(2026, 1, day),
                         broadcast_at=datetime(2026, 1, day, 16, 0))
    assert "usually reports around 16:00" in results.pulse("TCS")
    assert "3 past results" in results.pulse("TCS")


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


def test_in_season_refreshes_daily(results):
    results.mark_refreshed(date(2026, 7, 26))
    assert results.needs_refresh(date(2026, 7, 26)) is False
    assert results.needs_refresh(date(2026, 7, 27)) is True


def test_off_season_refreshes_weekly(results):
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

    results.mark_refreshed(date(2026, 9, 1))
    rc.refresh(calendar=results, today=date(2026, 9, 3))
    assert calls == []                       # off-season, only 2 days on

    rc.refresh(calendar=results, today=date(2026, 9, 3), force=True)
    assert calls == ["bm", "fr"]
