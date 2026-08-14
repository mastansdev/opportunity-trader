"""
==========================================================
A result must reach the SCORE while the market is open
==========================================================

31 July 2026. Collecting a Telegram message and turning it into
something the score can read were two separate steps, and only the
first ran during the session.

The second was tools/build_stock_events.py -- a command typed by hand
after the close. Measured on the day's own data, every one of the 119
events was written in a single batch at 14:35:54:

    YASHO   Excellent Results   posted 12:19  ->  filed 14:35
    STAR    Good Results        posted 12:37  ->  filed 14:35
    BSE     Good Results        posted 12:47  ->  filed 14:35

    fastest 5 min | typical 91 min | worst 429 min

On an ordinary day the tool runs after 15:30, which means a result
posted at 12:19 first affects the ranking the NEXT MORNING.

    "if today result came excellent & if the stock moved high even
     though we get them in top gainers but without why cards. i cannot
     trust the price movement right? genuine gap between trusted &
     vague buying"

That is the requirement in one sentence. The gainers panel exists to
say WHY a stock moved. A stock at the top of it with no reason chip,
while the reason sat unread in our own database, is the panel failing
at the only job it has.

WHAT THIS FILE GUARDS
---------------------
1. The event is filed by the POLL, not by a nightly command.
2. Collection never depends on classification succeeding.
3. The live path and the nightly tool use the same rules.

Author : H&M Opportunity Trader
==========================================================
"""

import sqlite3

import pytest

from core.stock_events import StockEvents, events_from_message
from core.telegram_feed import TelegramFeed


class Matcher:
    """Just enough of a name index to resolve the tickers used here."""

    KNOWN = ("GAIL", "SHADOWFAX", "YASHO", "ASTRAMICRO", "HAL")

    def symbols_in(self, text):
        up = (text or "").upper()
        return [s for s in self.KNOWN if s in up]

    def names_in(self, text):
        return []


@pytest.fixture
def store(tmp_path):
    return StockEvents(db_path=str(tmp_path / "events.db"))


@pytest.fixture
def feed(tmp_path, store):
    """A feed with no network and no master database behind it.

    client=None and read_images=False, because this is about the wiring
    between collection and filing, not about Telegram or OCR.

    The name lookup is stubbed rather than left empty. events_from_message
    is handed the FEED ITSELF as the matcher -- deliberately, so the
    index that tagged the message also tags the event -- and with no
    master_loader that index resolves nothing, so every event would file
    as market-scope and the test would pass while proving nothing about
    symbols.
    """
    f = TelegramFeed(client=None, master_loader=None,
                     db_path=str(tmp_path / "telegram.db"),
                     read_images=False, stock_events=store)
    matcher = Matcher()
    f.symbols_in = matcher.symbols_in
    f.names_in = matcher.names_in
    return f


def _events(store):
    conn = sqlite3.connect(store.db_path)
    rows = conn.execute("select coalesce(symbol,'~'), kind, grade, headline "
                        "from events order by id").fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------
# 1. THE POLL FILES THE EVENT
# ---------------------------------------------------------------
def test_a_result_posted_now_is_scored_now(feed, store):
    """The whole point. No tool, no restart, no waiting for the close."""
    feed._store({"name": "Earnings Pulse", "handle": "x", "kind": "text"},
                [{"id": "1", "at": "2026-07-31T08:41:00",
                  "text": "#GAIL - Excellent Results - 22 seconds ago",
                  "hashtags": ["GAIL"]}])
    rows = _events(store)
    assert rows, "the poll collected the message but filed no event"
    assert ("GAIL", "RESULT", "EXCELLENT") == rows[0][:3]


def test_the_finai_card_is_filed_with_its_estimates(feed, store):
    """An image post carries the whole card in its OCR text. The
    comparison against consensus is the one thing this program cannot
    get anywhere else, so it must survive the trip."""
    feed.read_images = True
    feed._read_photo = lambda url=None, data=None: (
        "GAIL (india)\not Fv27 FinAl Rating : Strong Beat\n"
        "Metric Q0Q YoY Jun'26 Est AEst Mar'26 Jun'25\n"
        "Sales 16% 17% 41350.2 37688.3 +10% 35,706 35,429\n"
        "oP 388% 93% 7097.9 2287.7 +210% 1,454 3,669\n"
        "PAT 215% 96% 4671.0 1543.9 +203% 1,482 2,382\n")
    feed._store({"name": "Earnings Pulse", "handle": "x", "kind": "image"},
                [{"id": "2", "at": "2026-07-31T08:54:00", "text": "",
                  "photos": ["http://example/card.png"]}])
    rows = _events(store)
    assert rows and rows[0][1] == "RESULT"
    assert rows[0][2] == "EXCELLENT"
    assert "PAT +202% vs est" in rows[0][3]


def test_ordinary_chat_files_nothing(feed, store):
    """The filter has to stay severe. A panel full of non-events is the
    failure the previous news system was deleted for."""
    feed._store({"name": "Day Trader Telugu", "handle": "x", "kind": "text"},
                [{"id": "3", "at": "2026-07-31T09:00:00",
                  "text": "must watch this video, subscribe for more"}])
    assert _events(store) == []


# ---------------------------------------------------------------
# 2. FILING MUST NEVER COST US THE MESSAGE
# ---------------------------------------------------------------
def test_a_classifier_failure_does_not_stop_collection(feed, store,
                                                       monkeypatch):
    """This runs on a polling thread in a live session.

    Losing an event is recoverable -- the nightly tool re-derives the
    whole table from telegram.db. Losing the MESSAGE is not, because
    the channel only serves a rolling window of posts. So collection
    has to survive anything classification does.
    """
    import core.telegram_feed as feed_module

    def explode(*a, **k):
        raise RuntimeError("classifier blew up")

    monkeypatch.setattr(feed_module, "events_from_message", explode)
    added = feed._store(
        {"name": "Earnings Pulse", "handle": "x", "kind": "text"},
        [{"id": "4", "at": "2026-07-31T08:41:00",
          "text": "#GAIL - Excellent Results"}])
    assert added == 1, "the message must still be stored"
    assert _events(store) == [], "and no half-written event left behind"


def test_a_broken_event_database_does_not_stop_collection(feed, store):
    """Same rule, one layer down: the write itself failing."""
    def explode(**kwargs):
        raise RuntimeError("disk full")

    feed.stock_events.remember = explode
    added = feed._store(
        {"name": "Earnings Pulse", "handle": "x", "kind": "text"},
        [{"id": "7", "at": "2026-07-31T08:41:00",
          "text": "#GAIL - Excellent Results"}])
    assert added == 1


def test_no_event_store_is_a_supported_configuration(tmp_path):
    """stock_events=None means the nightly tool stays the only path.
    Every test that does not care about events runs this way, and so
    does a session where the events database cannot be opened."""
    feed = TelegramFeed(client=None, master_loader=None,
                        db_path=str(tmp_path / "t.db"), read_images=False)
    added = feed._store({"name": "Earnings Pulse", "handle": "x",
                         "kind": "text"},
                        [{"id": "5", "at": "2026-07-31T08:41:00",
                          "text": "#GAIL - Excellent Results"}])
    assert added == 1


# ---------------------------------------------------------------
# 3. RE-FILING IS FREE
# ---------------------------------------------------------------
def test_polling_the_same_message_again_adds_nothing(feed, store):
    """The poller re-reads a rolling window every 90 seconds, so it
    sees the same message ~20 times. Filing does not have to know which
    rows were new, because remember() is idempotent -- but that only
    holds if it actually is."""
    message = [{"id": "6", "at": "2026-07-31T08:41:00",
                "text": "#GAIL - Excellent Results - 22 seconds ago"}]
    channel = {"name": "Earnings Pulse", "handle": "x", "kind": "text"}
    for _ in range(20):
        feed._store(channel, message)
    assert len(_events(store)) == 1


# ---------------------------------------------------------------
# 4. ONE SET OF RULES, TWO CALLERS
# ---------------------------------------------------------------
def test_the_shared_function_is_what_both_paths_call():
    """tools/build_stock_events.py and the live poll must not be able
    to disagree about what an event is. They disagree the moment there
    are two copies of these rules."""
    events = events_from_message(
        Matcher(), text="#GAIL - Excellent Results", at="2026-07-31T08:41",
        channel="Earnings Pulse")
    assert [(e["symbol"], e["kind"], e["grade"]) for e in events] == \
        [("GAIL", "RESULT", "EXCELLENT")]


def test_the_customer_on_an_order_is_not_credited_with_winning_it():
    """"Astra Microwave secures Rs 2,205 Cr order from HAL" -- HAL is
    the buyer. One company won revenue, the other spent money."""
    events = events_from_message(
        Matcher(),
        text="ASTRAMICRO secures Rs 2,205 crore order from HAL",
        at="2026-07-31T10:00", channel="OrderBook Pulse")
    assert [e["symbol"] for e in events] == ["ASTRAMICRO"]
    assert events[0]["value_cr"] == 2205.0


def test_a_rupee_figure_outside_an_order_is_not_stored_as_a_value():
    """GAIL's results headline stored value_cr=1262 off "Vs 1,262 Cr" --
    last quarter's profit, filed as a contract win."""
    events = events_from_message(
        Matcher(),
        text="#GAIL reports its Q1 results; Net Profit At 4,292 Cr "
             "Vs 1,262 Cr (QoQ)",
        at="2026-07-31T08:57", channel="Day Trader Telugu")
    assert events and events[0]["kind"] != "ORDER"
    assert events[0]["value_cr"] is None


def test_a_message_about_three_companies_is_about_none_of_them():
    events = events_from_message(
        Matcher(), text="Stocks in news: GAIL, SHADOWFAX, YASHO report today",
        at="2026-07-31T03:00", channel="Day Trader Telugu")
    assert events == []
