"""The board shows the flow, the trend and the channels -- in english.

    "i want each one to be clean & displayed to me on dashboard.
     without visually seeing , how can i ask u or guide whats wrong or
     correct?"                          -- operator, 30 August 2026
    "i would love incase u used simpler words in whole dashboard like
     day to day usage words which doesn't disturb the actual meaning
     of the real trading terminology"   -- same message
    "keep both words, use exit, full numbers. build it"

Three things the bot had been computing and never showing, and one
vocabulary decision that applies to all of them.

    BUYING PRESSURE   core/order_flow.py has recorded what actually
                      traded -- buy against sell, off the real 5-level
                      depth -- since 29 August. The chip already on
                      the board, r.pressure, is a different thing:
                      core/tick_ohlc.py, the quantity RESTING in the
                      book, which anybody can pull.
    TREND             the 7-day structure has been here since 24
                      August as one chip among a dozen; today's shape
                      (core/intraday_shape.py) is new. He asked for
                      BOTH, so they share one column.
    TELEGRAM          a tab of its own. Every figure was already on
                      disk; he had asked twice what the bot last heard
                      and from where, and both times it came out of
                      SQLite by hand.

BOTH WORDS. Plain english leads and the real term sits under it in
grey -- his decision, so the screen reads at a glance without costing
him the vocabulary he needs in front of Dhan or a broker.

AND NO DUPLICATES. "Duplicates of data is not acceptable at all" (29
August). Giving trend its own column while leaving the old chip in
place printed the same fact twice on one row, which is exactly what
the first render showed.
"""

import io
import os
import re

import pytest
from fastapi.testclient import TestClient

from dashboard.server import build_app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = os.path.join(ROOT, "dashboard", "static", "board.html")


@pytest.fixture(scope="module")
def board():
    return io.open(BOARD, encoding="utf-8").read()


# ------------------------------------------------------ both words

# ------------------------------------------------- no duplicated fact

# --------------------------------------------------- the flow column

# --------------------------------------------------- the hard verdict

# -------------------------------------------------- the telegram tab

# ------------------------------------------------------ the endpoint

class _State:
    def __init__(self):
        self._snap = {"ready": True}

    def get_snapshot(self):
        return self._snap


class _Controller:
    def note_action(self, *a, **k):
        pass


class _Loader:
    def known_symbols(self):
        return {"RELIANCE"}

    def is_blocked(self, symbol):
        return False


@pytest.fixture
def client():
    return TestClient(build_app(_State(), _Controller(), _Loader()))


def test_the_flow_endpoint_answers_for_a_stock_with_no_data(client):
    """A machine that has never recorded a session must return an
    empty series, not a 500."""
    got = client.get("/api/flow/NOSUCHSTOCK")
    assert got.status_code == 200
    body = got.json()
    assert body["series"] == []
    assert body["diverged"] is None


# ------------------------------------------------ how old the reason is

def test_the_row_carries_the_age():
    import inspect

    from dashboard.state import DashboardState

    src = inspect.getsource(DashboardState)
    assert 'row["reason_age"] = self._reason_age_for(' in src


def test_the_age_is_written_in_words_not_hours():
    """"22 minutes ago" and "4 days old" -- not 0.36 or 96.0."""
    from datetime import datetime, timedelta

    from core.why_moving import age_text

    now = datetime.now()
    assert age_text((now - timedelta(minutes=22)).isoformat(),
                    now=now) == "22 minutes ago"
    assert age_text((now - timedelta(days=4)).isoformat(),
                    now=now) == "4 days old"
    assert age_text(None) is None


def test_two_clocks_disagreeing_says_nothing():
    """A stamp from the future means the two clocks disagree. "-3
    minutes ago" on the screen teaches him to distrust the column."""
    from datetime import datetime, timedelta

    from core.why_moving import age_text

    now = datetime.now()
    assert age_text((now + timedelta(minutes=5)).isoformat(), now=now) is None


# ------------------------------------------- what the state column means

def _row(held=10):
    return {"held": held}


def _ago(hours):
    from datetime import datetime, timedelta

    return (datetime.now() - timedelta(hours=hours)).isoformat()


def test_a_recent_post_that_arrived_slowly_is_late():
    """The only version of "late" he can act on."""
    from core.telegram_feed import TelegramFeed

    assert TelegramFeed._channel_state(
        "daily", False, _row(), 45, _ago(0.5)) == "late"


def test_a_recent_post_that_arrived_fast_is_live():
    from core.telegram_feed import TelegramFeed

    assert TelegramFeed._channel_state(
        "daily", False, _row(), 1, _ago(0.5)) == "live"


def test_a_lag_from_days_ago_is_not_todays_fault():
    """---- A STALE LAG IS NOT A LATE CHANNEL. 30 August 2026. ----

    First run against the real store, on a Sunday evening:

        Breakouts         last post 28 Aug 10:03   late 1043   LATE
        OrderBook Pulse   last post 29 Aug 15:59   late  126   LATE

    Both true, neither a fault to act on: 1,043 minutes is what a
    backfill looks like and 126 was Friday evening. He would have
    opened the board on Monday to two red flags describing last week.
    """
    from core.telegram_feed import TelegramFeed

    assert TelegramFeed._channel_state(
        "daily", False, _row(), 1043, _ago(40)) == "quiet"


def test_a_results_channel_out_of_season_is_not_a_fault():
    from core.telegram_feed import TelegramFeed

    assert TelegramFeed._channel_state(
        "results", False, _row(), 900, _ago(40)) == "off season"
    assert TelegramFeed._channel_state(
        "results", True, _row(), 1, _ago(0.2)) == "live"


def test_a_channel_with_nothing_in_it_says_so():
    from core.telegram_feed import TelegramFeed

    assert TelegramFeed._channel_state(
        "daily", False, {"held": 0}, None, None) == "nothing yet"


def test_an_unreadable_timestamp_does_not_crash_the_column():
    from core.telegram_feed import TelegramFeed

    assert TelegramFeed._channel_state(
        "daily", False, _row(), 2, "not-a-date") in ("live", "late", "quiet")
