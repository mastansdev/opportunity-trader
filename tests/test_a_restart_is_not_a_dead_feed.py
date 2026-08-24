"""A minute of silence after a restart is not a dead feed.

    "i saw some stocks in terminal main.py run"   -- operator, 24 Aug

main.py restarted at 14:45 on 24 August. At 14:46:

    [FEED] 1162 of 1291 subscriptions have delivered NOTHING by 09:45
           (129 are live). Dhan is not sending these

All 1,291 went on to tick in that same process -- the log holds a
closed candle for every one. ATGL, ADANIENT, ADANIGREEN, ADANIPOWER
and 20MICRONS were named among the dead, which is what he saw and
reasonably read as "not tradeable".

129 live was exactly len(resolved) // 10 -- the 10% gate, cleared
sixty seconds after subscribing.
"""

from datetime import datetime, timedelta

import pytest

import core.feed_watch as fw
from core.feed_clock import IST


@pytest.fixture(autouse=True)
def _clean():
    fw._seen = set()
    fw._said = False
    fw._first_tick_at = None
    yield
    fw._seen = set()
    fw._said = False
    fw._first_tick_at = None


def _book(n):
    return {f"SYM{i}": str(i) for i in range(n)}


def _say(monkeypatch, minutes_listening, seen, book):
    """Run report() as if we had been listening this long."""
    said = []
    now = datetime(2026, 8, 24, 14, 46, tzinfo=IST)
    fw._first_tick_at = now - timedelta(minutes=minutes_listening)
    fw._seen = {str(i) for i in range(seen)}
    monkeypatch.setattr(fw, "now_ist", lambda: now, raising=False)
    monkeypatch.setattr("core.feed_clock.now_ist", lambda: now)
    return fw.report(book, log=lambda m, *a, **k: said.append(str(m))), said


def test_one_minute_after_a_restart_says_nothing(monkeypatch):
    silent, said = _say(monkeypatch, 1.0, 129, _book(1291))
    assert silent == []
    assert not said, said


def test_after_a_full_session_it_still_reports(monkeypatch):
    silent, said = _say(monkeypatch, 120.0, 129, _book(1291))
    assert silent, "a genuinely dead feed must still be reported"
    assert any("delivered NOTHING" in m for m in said)


def test_the_threshold_is_where_the_false_alarm_sat():
    # 129 of 1291 is exactly the 10% gate that let it through.
    assert 1291 // 10 == 129
    assert fw.MIN_LISTEN_MINUTES >= 30.0


def test_no_ticks_at_all_is_not_reported_as_silence(monkeypatch):
    # Nothing heard means the CONNECTION is the story, and this
    # message is about instruments. It must stay quiet.
    silent, said = _say(monkeypatch, 120.0, 0, _book(1291))
    assert silent == []
    assert not said


def test_a_healthy_book_says_all_delivering(monkeypatch):
    silent, said = _say(monkeypatch, 120.0, 1291, _book(1291))
    assert silent == []
    assert any("All 1291" in m for m in said)
