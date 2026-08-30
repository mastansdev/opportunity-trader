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

def test_the_real_term_is_kept_under_the_plain_one(board):
    """"keep both words". A screen that only said "Buying pressure"
    would leave him unable to match it to anything on a broker
    terminal."""
    for plain, jargon in (("Price now", "CMP"),
                          ("Money traded", "turnover"),
                          ("Yesterday", "prev close"),
                          ("Buying pressure", "order flow / delta"),
                          ("Trend", "price action")):
        pattern = re.escape(plain) + r'<span class="jargon">' + \
            re.escape(jargon)
        assert re.search(pattern, board), f"{plain} lost its {jargon}"


def test_the_jargon_is_styled_as_a_second_line(board):
    assert ".jargon{" in board
    block = board.split(".jargon{")[1].split("}")[0]
    assert "font-size:10px" in block
    assert "var(--muted)" in block


# ------------------------------------------------- no duplicated fact

def test_the_seven_day_trend_is_printed_once(board):
    """It moved into the Trend column. Leaving the chip behind put
    "climbing / 3 higher highs" in one column and "strong up" in the
    next on the same row."""
    assert "7-day structure: " not in board, (
        "the old trend chip is still being added beside the new column")
    assert board.count("function trendCell") == 1


# --------------------------------------------------- the flow column

def test_the_flow_column_is_the_traded_one_not_the_resting_one(board):
    """r.pressure is core/tick_ohlc.py -- orders STANDING in the book,
    which can be pulled. r.flow is what was actually paid for."""
    assert "function flowCell" in board
    cell = board.split("function flowCell")[1].split("function trendCell")[0]
    assert "r.flow" in cell
    assert "r.pressure" not in cell


def test_full_numbers_not_lakh_shorthand(board):
    """"full numbers" -- his decision. 4,82,140, not +4.82 L."""
    assert 'toLocaleString("en-IN")' in board.split("function inr")[1][:300]


def test_an_estimated_reading_says_so_on_the_row(board):
    """The tick rule is 75-80% right. A guess must never look like a
    measurement on a screen he trades from."""
    cell = board.split("function flowCell")[1].split("function trendCell")[0]
    assert "mostly estimated" in cell
    assert "measured === false" in cell


# --------------------------------------------------- the hard verdict

def test_exit_is_only_said_when_it_was_measured(board):
    """The failure that would cost him money is a false exit: selling
    a winner because the tick rule guessed wrong."""
    fn = board.split("function exitLine")[1].split("\n}")[0]
    assert "d.measured" in fn
    assert "Exit" in fn


def test_it_is_the_word_he_chose(board):
    """"use exit" -- not "get out"."""
    fn = board.split("function exitLine")[1].split("\n}")[0]
    assert "Buyers have walked away" in fn
    assert "get out" not in fn.lower()


def test_the_exit_line_says_why(board):
    fn = board.split("function exitLine")[1].split("\n}")[0]
    # "buying did / not follow" wraps in the template literal, so the
    # sentence is not contiguous in the source.
    assert "new highs after" in fn and "not follow" in fn


# -------------------------------------------------- the telegram tab

def test_the_tab_exists_and_the_switcher_knows_it(board):
    """A button whose name is not in the switcher's list is a dead
    button -- the guard there was written after one blanked his
    screen."""
    assert 'data-tab="tg"' in board
    assert 'id="tg-pane"' in board
    switch = board.split('const name = b.dataset.tab;')[1][:400]
    assert '"tg"' in switch


def test_every_channel_column_carries_both_words(board):
    pane = board.split('id="tg-pane"')[1].split('id="brain-pane"')[0]
    for plain in ("Checked every", "Late by", "Messages kept",
                  "Pictures read", "Last post", "Bot read it"):
        assert plain in pane, plain


def test_one_date_format_in_both_time_columns(board):
    """"Last post" and "Bot read it" sit side by side. The first draft
    printed "30 Aug 09:45" and "08-30 09:47" -- two formats in
    adjacent columns is how a reader starts doubting both."""
    fn = board.split("function whenText")[1].split("function lateText")[0]
    assert fn.count("return raw.slice") == 1, (
        "a second raw-slice fallback is the two-format bug returning")
    assert "getUTCHours" in fn and "getHours" in fn


def test_the_banner_explains_the_slow_loop(board):
    """"why is Earnings Pulse on the 5 min loop" is answered before he
    asks it -- see the results-season promotion of 30 August."""
    fn = board.split("function drawTelegram")[1].split("function drawBrain")[0]
    assert "results season" in fn


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


def test_the_series_is_not_on_the_snapshot(board):
    """375 minutes per stock, for twenty rows, once a second down a
    websocket, to draw a chart nobody has opened."""
    assert "/api/flow/" in board
    assert "session_series" not in board


# ------------------------------------------------ how old the reason is

def test_the_reason_says_how_old_it_is(board):
    """core/why_moving.py drops a reason the card says is a day or more
    old -- correctly, a four-day-old order is not why a stock is moving
    this morning. It dropped it SILENTLY, so the stock appeared with no
    reason and looked identical to one nothing had been published
    about."""
    fn = board.split("function reasonChips")[1].split("return out.length")[0]
    assert "r.reason_age" in fn


def test_old_news_is_coloured_as_a_warning(board):
    """Past a day the age IS the warning, so it stops looking like
    ordinary metadata."""
    fn = board.split("function reasonChips")[1].split("return out.length")[0]
    block = fn.split("if (r.reason_age)")[1]
    assert "day|week|month" in block
    assert "--warn-bg" in block


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


def test_the_number_is_never_hidden(board):
    """The state may say quiet; the lag still has its own column, so
    nothing is lost by softening the word."""
    pane = board.split('id="tg-pane"')[1].split('id="brain-pane"')[0]
    assert "Late by" in pane


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
