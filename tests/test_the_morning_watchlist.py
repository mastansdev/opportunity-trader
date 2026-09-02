"""---- THE LIST HE READS AT 09:08. 2 September 2026. ----

    "create a watchlist each day & add the stocks which ever had
     something news/orders/govt scheme/results (during results
     season). once pre-open market completed by 09:08 . i'll check
     these watchlist stocks first & all stocks too. + volume also"
                                            -- the operator

core/watchlist_builder.py has existed since 7 August with THREE doors
-- graded results, reporting today, and already-moving -- and no news,
no orders, no schemes. So a stock only reached the list once the tape
had already moved it, which is the "no use of such movement, it
already ran" complaint wearing another costume.

WHAT THAT COST ON 2 SEPTEMBER, from the record:

    POWERGRID   Rs 3,244 cr order   published before the open
    SICALLOG    Rs 2,535 cr order   published before the open
    ANTELOPUS   order, 08:28        closed +20.0% on 181x volume
    INDOCO      Rs 764 cr land sale closed +12.3% on 329x volume

93 stocks had something published since the previous close. None of
them was in the pool BECAUSE of that news -- the two that ran fought
their way in on the tape, hours later. ANTELOPUS did not reach the
board until 11:21.

Nothing here takes a trade. Every gate downstream still has to be
cleared, and most of these will never move: 5 of 93 got any buying.
The list only gives them the chance to be judged, and it STAYS ALL
DAY on his instruction -- knowing at 14:00 that a morning order got
no buying is worth as much as the ones that ran.
"""

import os
import sqlite3

import pytest

from core import watchlist_builder as wb


@pytest.fixture
def events(tmp_path):
    """A stand-in stock_events.db with one of each shape."""
    path = tmp_path / "stock_events.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, symbol TEXT, "
                "at TEXT, kind TEXT, scope TEXT, grade TEXT, value_cr REAL, "
                "headline TEXT)")
    rows = [
        ("POWERGRID", "2026-09-02T03:31", "ORDER", "STOCK", None, 3244.0,
         "POWERGRID wins large Rajasthan transmission project"),
        ("BEML", "2026-09-02T03:27", "ORDER", "STOCK", None, 181.0,
         "BEML secures Rs 181 cr Vande Bharat order"),
        ("INDOCO", "2026-09-02T04:57", "NEWS", "STOCK", None, None,
         "Indoco Remedies executes deed for Mulgaon land, Rs 764 crore"),
        (None, "2026-09-02T03:14", "MACRO", "MARKET", None, None,
         "INDIA PROPOSES AMENDMENTS TO MEDICAL DEVICES RULES"),
        ("STALE", "2026-08-20T09:00", "ORDER", "STOCK", None, 900.0,
         "an order from a fortnight ago"),
    ]
    con.executemany("INSERT INTO events (symbol, at, kind, scope, grade, "
                    "value_cr, headline) VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return str(path)


def _filed(events, **kw):
    from datetime import datetime
    return wb.filed_symbols(db_path=events,
                            now=kw.pop("now", datetime(2026, 9, 2, 9, 8)),
                            **kw)


def test_an_order_published_overnight_is_on_the_list(events):
    got = _filed(events)
    assert "POWERGRID" in got, got
    assert got["POWERGRID"]["value_cr"] == 3244.0


def test_news_is_on_the_list_too(events):
    """The door that did not exist. INDOCO's land sale was published at
    04:57 and the stock closed +12.3% on 329x volume."""
    assert "INDOCO" in _filed(events)


def test_a_stock_does_not_have_to_have_moved(events):
    """The whole point. The list is built from what was PUBLISHED, not
    from what the tape has already done."""
    got = _filed(events)
    assert "BEML" in got and "POWERGRID" in got


def test_market_scope_never_gets_pinned_to_a_ticker(events):
    """A medical-devices rule change is real and names no company.
    Attaching it to a stock would be inventing a link that is not in
    the source -- it belongs on the screen as sector news."""
    for detail in _filed(events).values():
        assert "MEDICAL DEVICES" not in (detail["headline"] or "")


def test_the_window_ends_at_the_last_close(events):
    """A fortnight-old order is not this morning's news."""
    assert "STALE" not in _filed(events)


def test_an_order_is_not_overwritten_by_later_chatter(events, tmp_path):
    """A Rs 181 crore order is the reason. "Shares in focus" written
    about it an hour later is not, and must not replace it."""
    con = sqlite3.connect(events)
    con.execute("INSERT INTO events (symbol, at, kind, scope, headline) "
                "VALUES ('BEML','2026-09-02T05:00','NEWS','STOCK',"
                "'BEML shares in focus today')")
    con.commit()
    con.close()
    assert _filed(events)["BEML"]["kind"] == "ORDER"


def test_a_missing_store_is_not_a_crash(tmp_path):
    """This runs before the engine exists. A watchlist that needs a
    live object to build is a watchlist that is not there at 09:08."""
    assert wb.filed_symbols(db_path=str(tmp_path / "nope.db")) == {}


def test_the_builder_returns_the_new_rows_first():
    """ORDERED and FILED are why a stock is on the list before the tape
    says anything, so they are read first."""
    keys = [r["key"] for r in wb.build(movers=[], adv_of=lambda s: 50.0)["rows"]]
    assert keys[:2] == [wb.ORDERED, wb.FILED], keys


def test_every_row_has_a_title():
    for key in (wb.ORDERED, wb.FILED, wb.GRADED, wb.REPORTING, wb.MOVING):
        assert wb.ROW_TITLES.get(key), key


def test_the_pool_is_widened_by_the_filings():
    """THE JOIN. core/watchlist_builder.py sat unwired for the news
    doors exactly as core/ranker.py once sat unwired whole -- built,
    documented, and read by nothing. Asserted on the source because
    the failure is an absent call, which no mock can catch.
    """
    with open(os.path.join("dashboard", "state.py"), encoding="utf-8") as f:
        body = f.read()
    assert "watchlist_builder.filed_symbols()" in body, (
        "the pool seed does not read the filings -- news, orders and "
        "schemes give a stock no way into the pool")


def test_the_panel_is_on_the_snapshot():
    with open(os.path.join("dashboard", "state.py"), encoding="utf-8") as f:
        body = f.read()
    assert '"morning_watchlist"' in body
    assert "def build_morning_watchlist" in body


def test_the_watch_tab_draws_it():
    with open(os.path.join("dashboard", "static", "desk.html"),
              encoding="utf-8") as f:
        body = f.read()
    assert "morning_watchlist" in body, "the Watch tab never reads the list"
    assert 'id="morning"' in body
    assert 'id="sector"' in body, "sector and scheme news has nowhere to go"
