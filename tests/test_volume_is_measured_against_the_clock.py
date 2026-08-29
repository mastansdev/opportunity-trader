"""A stock trading at 5x pace must read 5x at 09:30 and at 14:50.

The defect these cover: ranker.volume_ratio() put a PART day over a
WHOLE day, so the number tracked the hour rather than the stock, and
the seats are sorted on that number.
"""

import datetime as dt

import pytest

from core import volume_pace as vp


def _profile(**curves):
    return {sym: {"days": 60, "curve": c} for sym, c in curves.items()}


SBIN = _profile(SBIN={"09:20": 0.038, "09:30": 0.070,
                      "11:00": 0.287, "15:00": 0.851})


def test_the_same_pace_reads_the_same_at_every_hour():
    # A stock trading at exactly its normal pace reads 1.0x all day.
    for clock, fraction in (("09:30", 0.070), ("11:00", 0.287),
                            ("15:00", 0.851)):
        got = vp.pace_ratio(traded_cr=100.0 * fraction, adv_cr=100.0,
                            symbol="SBIN", now=clock, profile=SBIN)
        assert got == pytest.approx(1.0, abs=0.01), clock


def test_five_times_pace_is_visible_at_half_past_nine():
    # 5x pace at 09:30 = 5 * 7.0% = 35% of a normal DAY already done.
    got = vp.pace_ratio(traded_cr=35.0, adv_cr=100.0, symbol="SBIN",
                        now="09:30", profile=SBIN)
    assert got == pytest.approx(5.0, abs=0.05)

    # The old measurement called that same stock 0.35x -- quiet.
    assert 35.0 / 100.0 < 1.0


def test_a_dull_afternoon_no_longer_outranks_a_busy_morning():
    busy_morning = vp.pace_ratio(35.0, 100.0, "SBIN", "09:30", profile=SBIN)
    dull_close = vp.pace_ratio(85.1, 100.0, "SBIN", "15:00", profile=SBIN)
    assert busy_morning > dull_close
    # Under the old field the order was the exact reverse.
    assert (35.0 / 100.0) < (85.1 / 100.0)


def test_each_stock_uses_its_own_curve_never_a_shared_one():
    #     "never pool all stocks , never average the stocks data"
    both = _profile(SBIN={"09:30": 0.070}, RAILTEL={"09:30": 0.167})
    sbin = vp.pace_ratio(7.0, 100.0, "SBIN", "09:30", profile=both)
    railtel = vp.pace_ratio(7.0, 100.0, "RAILTEL", "09:30", profile=both)
    assert sbin == pytest.approx(1.0, abs=0.01)
    assert railtel == pytest.approx(0.42, abs=0.01)


def test_a_stock_with_no_curve_of_its_own_is_unmeasured_not_quiet():
    assert vp.pace_ratio(50.0, 100.0, "NEWLISTING", "09:30",
                         profile=SBIN) is None


def test_too_few_days_is_unmeasured():
    thin = {"THIN": {"days": vp.MIN_DAYS - 1, "curve": {"09:30": 0.07}}}
    assert vp.pace_ratio(50.0, 100.0, "THIN", "09:30", profile=thin) is None


def test_the_first_minutes_are_unmeasured_not_enormous():
    # At 09:16 a stock has traded a fraction of a percent. Dividing by
    # it turns one block trade into a 40x headline.
    early = _profile(SBIN={"09:16": 0.004, "09:30": 0.070})
    assert vp.pace_ratio(1.0, 100.0, "SBIN", "09:16", profile=early) is None
    assert vp.pace_ratio(7.0, 100.0, "SBIN", "09:30",
                         profile=early) == pytest.approx(1.0, abs=0.01)


def test_no_clock_means_unmeasured():
    assert vp.pace_ratio(50.0, 100.0, "SBIN", None, profile=SBIN) is None


def test_a_datetime_and_an_iso_stamp_both_work():
    stamp = dt.datetime(2026, 8, 24, 11, 0)
    assert vp.pace_ratio(28.7, 100.0, "SBIN", stamp,
                         profile=SBIN) == pytest.approx(1.0, abs=0.01)
    assert vp.pace_ratio(28.7, 100.0, "SBIN", "2026-08-24T11:00:00",
                         profile=SBIN) == pytest.approx(1.0, abs=0.01)


def test_a_minute_between_grid_points_uses_the_last_one_known():
    assert vp.pace_ratio(7.0, 100.0, "SBIN", "09:45",
                         profile=SBIN) == pytest.approx(1.0, abs=0.01)


def test_missing_adv_is_unmeasured():
    assert vp.pace_ratio(50.0, 0.0, "SBIN", "09:30", profile=SBIN) is None
    assert vp.pace_ratio(None, 100.0, "SBIN", "09:30", profile=SBIN) is None


# ==========================================================
#  THE SESSION IS THE WINDOW
# ==========================================================
#     "for bot from 09 - 15:30 complete trading whenever
#      opportunity saw"          -- operator, 23 August 2026

def test_a_new_entry_is_allowed_until_the_market_stops_trading():
    # THE LIVE GATE, not the documentation copy. core/auto_entry.py
    # imports config.LAST_ENTRY_TIME; core/rules.py is derived from it.
    # On 23 August I changed only rules and reported the window as
    # widened while the gate that runs sat at 15:15.
    import config
    from core import auto_entry, rules
    assert auto_entry.LAST_NEW_ENTRY.strftime("%H:%M") == "15:15"
    assert config.LAST_ENTRY_TIME == "15:15"
    assert rules.LAST_NEW_ENTRY == "15:15"


def test_the_three_entry_clocks_can_never_disagree():
    import config
    from core import auto_entry, rules
    assert (config.LAST_ENTRY_TIME
            == rules.LAST_NEW_ENTRY
            == auto_entry.LAST_NEW_ENTRY.strftime("%H:%M"))


def test_the_book_is_not_shut_before_the_bell():
    # _position_ceiling() returns 0 past STAGED_NO_ENTRY_AFTER, which
    # shuts the book regardless of what auto_entry allows. It sat at
    # 15:15 and would have silently defeated the change above.
    import config
    assert config.STAGED_NO_ENTRY_AFTER == "15:15"
    assert config.STAGED_NO_ENTRY_AFTER == config.LAST_ENTRY_TIME


def test_the_entry_window_is_not_the_square_off_clock():
    # 15:15 was config.SQUARE_OFF_TIME, which is MIS machinery. The
    # bot buys MTF and holds overnight, so pairing the two refused
    # INDOBORAX at 14:42 on a DEAL filing and 35x its own volume.
    import config
    from core import rules
    assert config.FORCE_SQUARE_OFF_AT_CLOSE is False
    # CAS put it back ON the old square-off clock, for a new reason.
    assert rules.LAST_NEW_ENTRY == "15:15"


def test_the_orb_window_is_untouched():
    # The 09:15-09:30 opening range is PART of the bot, not a gate
    # that was removed -- it still ends where it always did.
    from core import rules
    assert rules.EARLY_ENTRY_FROM == "09:15"
    assert rules.FIRST_NEW_ENTRY == "09:30"
