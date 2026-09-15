"""
==========================================================
An empty table on top of a full database
==========================================================

    "why dashboard is still showing empty ? it has todays complete data
     right? why it cant display them all stocks with their reasons"
                                -- operator, 12 August 2026

He was right. Measured at 23:08 on a freshly restarted main.py:

    tick_count            0          market shut since 15:30
    feed_alive            False
    advances / declines   0 / 0      1,314 read as "unchanged"
    gainers / losers      0 / 0
    shortlist             0 rows

and at that same moment data/daily_candles.db held today's close,
prev_close and volume for every one of those symbols:

    ARDEE      +26.64%      SINGERIND  +19.99%
    TCPLPACK   +19.56%      TDPOWERSYS +16.03%

A complete session, on disk, that no panel could see.

WHY
---
dashboard/state.py's _compute_gl_rows() reads circuit_monitor's REST
quote poll. That keeps answering after hours but stops carrying a
usable last price, so every row failed the "no_price" test and the
board drew an empty table.

THE RULE THIS ADDS
------------------
When the live path yields nothing, show the stored session -- and SAY
that is what it is. A closing price presented as a live one is worse
than a blank table, because a blank table is honestly empty and a stale
price is quietly wrong. Every fallback row carries `at_close` and its
date, the panel lifts both to the top, and board.html prints
"showing the 2026-08-12 CLOSE (not live)" where the clock goes.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib
import sqlite3

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BOARD = ROOT / "dashboard" / "static" / "board.html"


@pytest.fixture
def state(tmp_path, monkeypatch):
    """A DashboardState with only what the fallback touches."""
    from dashboard.state import DashboardState

    db = tmp_path / "daily_candles.db"
    conn = sqlite3.connect(str(db))
    conn.execute("create table daily_bars (id integer primary key, "
                 "date text, symbol text, series text, open real, "
                 "high real, low real, close real, prev_close real, "
                 "volume real)")
    rows = [
        ("2026-08-12", "BIGUP", 100.0, 127.0, 99.0, 126.0, 100.0, 5000),
        ("2026-08-12", "SMALL", 50.0, 51.0, 49.5, 50.5, 50.0, 900),
        ("2026-08-12", "DOWNER", 80.0, 80.0, 70.0, 71.0, 80.0, 4000),
        # A 2:10 split reads as -80% and must be refused, same as live.
        ("2026-08-12", "SPLITCO", 20.0, 21.0, 19.0, 20.0, 100.0, 700),
        # Yesterday -- must not be picked when today exists.
        ("2026-08-11", "BIGUP", 90.0, 100.0, 90.0, 100.0, 90.0, 1000),
    ]
    for d, s, o, h, lo, c, p, v in rows:
        conn.execute("insert into daily_bars (date, symbol, open, high, "
                     "low, close, prev_close, volume) values (?,?,?,?,?,?,?,?)",
                     (d, s, o, h, lo, c, p, v))
    conn.commit()
    conn.close()

    monkeypatch.chdir(tmp_path.parent)
    (tmp_path.parent / "data").mkdir(exist_ok=True)
    db.replace(tmp_path.parent / "data" / "daily_candles.db")

    st = DashboardState.__new__(DashboardState)
    st.master_loader = None
    return st


def test_it_reads_the_stored_close_when_there_are_no_live_prices(state):
    rows = state._gl_rows_from_the_close()
    by = {r["symbol"]: r for r in rows}
    assert "BIGUP" in by, "today's close produced no rows at all"
    assert by["BIGUP"]["change_pct"] == pytest.approx(26.0, abs=0.1)
    assert by["DOWNER"]["change_pct"] == pytest.approx(-11.25, abs=0.1)


def test_every_fallback_row_says_it_is_a_close(state):
    """THE WHOLE POINT. A closing price without this label is a stale
    price wearing a live one's clothes."""
    for row in state._gl_rows_from_the_close():
        assert row["at_close"] is True, row["symbol"]
        assert row["as_of"] == "2026-08-12", row["symbol"]


def test_it_uses_the_latest_session_not_an_older_one(state):
    rows = state._gl_rows_from_the_close()
    assert {r["as_of"] for r in rows} == {"2026-08-12"}
    big = next(r for r in rows if r["symbol"] == "BIGUP")
    assert big["ltp"] == 126.0, "picked an older session's close"


def test_a_split_artifact_is_refused_here_too(state, monkeypatch):
    """JLHL's 2:10 split read as -80% and is why core/stock_memory.py
    exists. The same fake move must not walk in through the back door.

    ---- THE FIRST GUARD WAS DECORATIVE. 12 August 2026. ----
    Written as _is_plausible_move(change_pct, prev, None, None). That
    helper fails OPEN when circuit limits are missing -- correctly, it
    is fail-open by design -- and the daily store carries no circuit
    bands, so it returned True for everything and SPLITCO walked onto
    the board at -80%.

    stock_memory answers the same question without needing bands, and
    it is the module built for this exact failure.
    """
    import core.stock_memory as sm

    class _Memory:
        def price_distorting_symbols(self, on_date=None, **kw):
            return {"SPLITCO": ["SPLIT (2:10)"]}

    monkeypatch.setattr(sm, "default_memory", lambda: _Memory())
    names = {r["symbol"] for r in state._gl_rows_from_the_close()}
    assert "SPLITCO" not in names, (
        "an -80% split artifact reached the table through the close "
        "fallback -- core/stock_memory.py knows it is a split")
    assert "BIGUP" in names, "the filter took the honest rows with it"


def test_a_broken_stock_memory_still_shows_the_close(state, monkeypatch):
    """The split filter is a nicety on this path. If it cannot be
    consulted, an honest table beats an empty one."""
    import core.stock_memory as sm

    def _boom():
        raise RuntimeError("memory store locked")

    monkeypatch.setattr(sm, "default_memory", _boom)
    assert state._gl_rows_from_the_close(), (
        "an unreadable stock memory emptied the whole table")


def test_a_missing_database_is_not_an_error(tmp_path, monkeypatch):
    from dashboard.state import DashboardState
    monkeypatch.chdir(tmp_path)
    st = DashboardState.__new__(DashboardState)
    st.master_loader = None
    assert st._gl_rows_from_the_close() == []


def test_the_panel_lifts_the_label_to_the_top():
    """Row-by-row inspection is not a label. The page reads one flag."""
    state_py = (ROOT / "dashboard" / "state.py").read_text(
        encoding="utf-8", errors="replace")
    assert '"at_close": at_close' in state_py
    assert '"at_close": stock.get("at_close", False)' in state_py, (
        "_build_gainers_losers drops the flag, so the page never sees it")


def test_live_data_is_never_overridden():
    """The fallback must only run when the live path produced nothing.
    Showing a close over working prices would be a serious regression."""
    import inspect
    from dashboard.state import DashboardState
    src = inspect.getsource(DashboardState._compute_gl_rows)
    assert "if not rows:" in src, (
        "the close fallback is not guarded by an empty live result")
