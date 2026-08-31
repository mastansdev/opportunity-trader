"""---- A MAINTENANCE TOOL THAT NEEDED THE PATIENT ALIVE. 31 Aug 2026. ----

He was told to run:

    py tools/flatten_carried.py --close

to clear NCC and CDSL, carried since 21 August. He ran it. Nothing
happened, and the next `status` still showed both positions.

The tool read last prices from the running dashboard's snapshot and
returned {} when the snapshot was not there. main.py had already
exited -- which is the normal state after the close, and the obvious
time to do maintenance. Every position printed "no last price
available, cannot close" and the tool exited 0.

So it looked like a command that ran.

The dashboard is still tried first: freshest price, and the one he is
looking at if the process is up. The candle store is the fallback, and
it is on disk whether anything is running or not.
"""

import json
import sqlite3

import pytest

from tools import flatten_carried as fc


@pytest.fixture
def no_dashboard(monkeypatch):
    """The normal state of the machine after the close."""
    def _refused(*a, **k):
        raise OSError("[WinError 10061] target machine actively refused it")

    monkeypatch.setattr(fc.urllib.request, "urlopen", _refused)


def _candles(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE candles (date TEXT, symbol TEXT, "
                 "minute TEXT, o REAL, h REAL, l REAL, c REAL)")
    conn.executemany("INSERT INTO candles (date, symbol, minute, c) "
                     "VALUES (?,?,?,?)", rows)
    conn.commit()
    conn.close()


def test_prices_come_from_disk_when_nothing_is_running(tmp_path, monkeypatch,
                                                       no_dashboard):
    """The whole bug. No dashboard, and it still has a price."""
    db = tmp_path / "candles.db"
    _candles(db, [
        ("2026-08-28", "NCC", "2026-08-28T15:29", 150.40),
        ("2026-08-31", "NCC", "2026-08-31T15:00", 148.80),
        ("2026-08-31", "NCC", "2026-08-31T15:29", 148.25),   # newest
        ("2026-08-31", "CDSL", "2026-08-31T15:29", 1402.00),
    ])
    monkeypatch.setattr(fc, "CANDLES_DB", str(db))
    got = fc.last_prices(["NCC", "CDSL"])
    assert got == {"NCC": 148.25, "CDSL": 1402.00}


def test_it_takes_the_newest_minute_not_just_any_row(tmp_path, monkeypatch,
                                                     no_dashboard):
    """Closing at a stale price would book a number that never
    happened. Ordered by date THEN minute, both descending."""
    db = tmp_path / "candles.db"
    _candles(db, [
        ("2026-08-31", "NCC", "2026-08-31T09:16", 999.00),
        ("2026-08-31", "NCC", "2026-08-31T15:29", 148.25),
        ("2026-08-21", "NCC", "2026-08-21T15:29", 500.00),
    ])
    monkeypatch.setattr(fc, "CANDLES_DB", str(db))
    assert fc.last_prices(["NCC"])["NCC"] == 148.25


def test_the_dashboard_still_wins_when_it_is_up(tmp_path, monkeypatch):
    """It is the freshest price, and it is the number he is looking at.
    The store is a fallback, not a replacement."""
    db = tmp_path / "candles.db"
    _candles(db, [("2026-08-31", "NCC", "2026-08-31T15:29", 148.25)])
    monkeypatch.setattr(fc, "CANDLES_DB", str(db))

    class _Resp:
        def read(self):
            return json.dumps({"open_positions": [
                {"symbol": "NCC", "last_price": 148.50}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(fc.json, "load",
                        lambda *a, **k: {"open_positions": [
                            {"symbol": "NCC", "last_price": 148.50}]})
    monkeypatch.setattr(fc.urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert fc.last_prices(["NCC"])["NCC"] == 148.50


def test_a_symbol_with_no_price_anywhere_is_not_invented(tmp_path,
                                                         monkeypatch,
                                                         no_dashboard):
    """No price is a real answer. Closing at a guessed number would
    write a fictional trade into his history."""
    db = tmp_path / "candles.db"
    _candles(db, [("2026-08-31", "NCC", "2026-08-31T15:29", 148.25)])
    monkeypatch.setattr(fc, "CANDLES_DB", str(db))
    assert "DELISTED" not in fc.last_prices(["NCC", "DELISTED"])


def test_a_missing_candle_store_does_not_raise(tmp_path, monkeypatch,
                                               no_dashboard):
    monkeypatch.setattr(fc, "CANDLES_DB", str(tmp_path / "nope.db"))
    assert fc.last_prices(["NCC"]) == {}


# --------------------------------------------------- what it counts as carried

def test_only_positions_from_an_earlier_session_are_touched():
    """A position opened TODAY is simply open. Sweeping it up would
    close a live trade in the middle of its move."""
    state = {"open_positions": {
        "OLD": {"entry_time": "2026-08-21T12:41:57"},
        "TODAY": {"entry_time": "2026-08-31T10:16:00"},
    }}
    got = {s for s, _, _ in fc.carried(state, "2026-08-31")}
    assert got == {"OLD"}


def test_an_empty_book_is_not_an_error():
    assert fc.carried({"open_positions": {}}, "2026-08-31") == []
    assert fc.carried({}, "2026-08-31") == []
