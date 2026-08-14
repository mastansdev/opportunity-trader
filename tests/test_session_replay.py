"""
Tests for core/session_replay.py.

    "todays all data gone ?"
    "if possible show me all available data including news, events,
     trades and all we did today in this new dashboard"
                                    -- operator, 29 July 2026, night

The dashboard reads the live Engine's memory, and that memory dies
with the process at 15:30 -- while the day itself is still on disk in
five stores nothing read back. These tests hold the replay to the two
rules that make it trustworthy:

    1. It REPORTS, it never invents. Anything the bot did not write
       down comes back as a visible gap, not a plausible number.

    2. NSE's own close beats ours wherever one exists. Measured
       against the 27 July bhavcopy, our last minute candle is 0.15%
       out at the median and over 1% out on nine symbols, because the
       snapshot feed never sees the closing auction.
"""

import os
import sqlite3

import pytest

from core.session_replay import SessionReplay, _dt


# ---------------------------------------------------------------
# fixtures -- a tiny session written to a temp dir
# ---------------------------------------------------------------

@pytest.fixture
def session(tmp_path):
    candles = tmp_path / "candles.db"
    conn = sqlite3.connect(candles)
    conn.execute("CREATE TABLE candles (id INTEGER PRIMARY KEY, date TEXT, "
                 "symbol TEXT, minute TEXT, o REAL, h REAL, l REAL, "
                 "c REAL, v REAL)")
    rows = [
        # the previous session -- gives KAYNES its prev_close
        ("2026-07-28", "KAYNES", "2026-07-28T15:29", 3220, 3230, 3210, 3227.70, 900),
        # the day being replayed
        ("2026-07-29", "KAYNES", "2026-07-29T09:15", 3275, 3300, 3274.70, 3290, 500),
        ("2026-07-29", "KAYNES", "2026-07-29T15:29", 3600, 3684.70, 3590, 3660.20, 700),
        # a pytest fixture symbol that leaked into the real log
        ("2026-07-29", "TESTCO", "2026-07-29T09:15", 1, 1, 1, 1, 1),
    ]
    conn.executemany("INSERT INTO candles (date,symbol,minute,o,h,l,c,v) "
                     "VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()

    memory = tmp_path / "memory.db"
    conn = sqlite3.connect(memory)
    conn.execute(
        "CREATE TABLE trade_memory (id INTEGER PRIMARY KEY, symbol TEXT, "
        "direction TEXT, trade_date TEXT, entry_time TEXT, exit_time TEXT, "
        "entry_price REAL, exit_price REAL, qty INTEGER, pnl REAL, "
        "exit_reason TEXT, entry_reason TEXT, holding_minutes REAL, "
        "sector TEXT, news_kind TEXT, filing_kind TEXT, results_grade TEXT)")
    conn.execute(
        "INSERT INTO trade_memory (symbol,direction,trade_date,entry_time,"
        "exit_time,entry_price,exit_price,qty,pnl,exit_reason,entry_reason,"
        "holding_minutes,sector) VALUES "
        "('KAYNES','LONG','2026-07-29','2026-07-29 09:32:00',"
        "'2026-07-29 10:14:00',3338.0,3398.0,59,3540.0,'TRAILING_STOP',"
        "'STRUCTURAL_LONG_BREAKOUT',42.0,'CAPITAL GOODS')")
    conn.execute(
        "INSERT INTO trade_memory (symbol,direction,trade_date,entry_time,"
        "exit_time,entry_price,exit_price,qty,pnl,exit_reason,entry_reason,"
        "holding_minutes) VALUES "
        "('OLDTRADE','LONG','2026-07-28','2026-07-28 09:32:00',"
        "'2026-07-28 10:14:00',100.0,101.0,10,10.0,'X','Y',1.0)")
    conn.commit()
    conn.close()

    log = tmp_path / "diagnostics_1.log"
    log.write_text(
        "2026-07-29 10:20:22,084 [INFO] [NEWS] ASIANPAINT -- APPROVAL filed "
        "10:20:02 (2 min ago): Appointment\n"
        "2026-07-29 12:43:18,223 [INFO] [FILING] REFEX: read 3 quarters "
        "(3 new) -- STRONG: sales +76% QoQ, PAT +123% QoQ\n"
        "2026-07-29 09:37:11,584 [WARNING] WARNING: [NO_TRADE] KIRLPNU LONG "
        "skipped -- stopped out once today. No long trade for KIRLPNU today.\n"
        "2026-07-29 09:33:00,990 [DEBUG] [RESULTS_GATE] BALKRISIND blocked "
        "-- reports today, numbers not out yet.\n"
        "2026-07-29 09:31:00,000 [INFO] Signal\n"
        "ORB BREAKOUT   : JYOTHYLAB\n"
        "Breakout Close : 208.17\n"
        "2026-07-29 09:31:01,038 [INFO] PAPER BUY  JYOTHYLAB  qty=960 @ "
        "208.59 (STRUCTURAL_LONG_BREAKOUT)  [wanted 208.17, slipped 0.42 "
        "= Rs 403]\n"
        "2026-07-29 09:32:23,159 [WARNING] WARNING: [MISSED_STOP] CHOLAFIN "
        "LONG traded to 1791.10, through a stop of 1791.47 (by 0.37)\n"
        "2026-07-28 09:00:00,000 [INFO] [NEWS] YESTERDAY -- APPROVAL filed "
        "09:00:00 (1 min ago): Not today\n",
        encoding="utf-8")

    orders = tmp_path / "trade_log.csv"
    orders.write_text(
        "time,side,symbol,security_id,qty,price,reason\n"
        "2026-07-29 09:31:01,BUY,JYOTHYLAB,1,960,208.59,STRUCTURAL\n"
        "2026-07-28 09:31:01,BUY,YESTERDAY,2,10,100.00,STRUCTURAL\n",
        encoding="utf-8")

    return SessionReplay(
        "2026-07-29", candles_db=str(candles), trade_memory_db=str(memory),
        trade_log=str(orders), log_glob=str(tmp_path / "diagnostics*.log*"))


# ---------------------------------------------------------------
# trades
# ---------------------------------------------------------------

def test_the_days_trades_come_back(session):
    trades = session.closed_positions()
    assert len(trades) == 1
    assert trades[0]["symbol"] == "KAYNES"
    assert trades[0]["qty"] == 59


def test_another_days_trades_do_not(session):
    assert all(t["symbol"] != "OLDTRADE" for t in session.closed_positions())


def test_pnl_is_read_not_recomputed(session):
    """The bot's own recorded figure is the one that must appear. A
    second calculation would eventually disagree with the first and
    there would be no way to tell which screen was lying."""
    assert session.closed_positions()[0]["pnl"] == 3540.0


def test_times_are_datetimes_because_the_dashboard_calls_strftime(session):
    """dashboard/state.py's _fmt_time() calls .strftime() directly. A
    string here takes the whole closed-trades panel down."""
    trade = session.closed_positions()[0]
    assert trade["entry_time"].hour == 9
    assert trade["exit_time"].minute == 14
    assert trade["entry_time"].strftime("%H:%M") == "09:32"


def test_a_stop_that_was_never_recorded_is_None_not_zero(session):
    """None reads as unknown. Zero reads as a stop at zero rupees."""
    assert session.closed_positions()[0]["initial_stop"] is None


# ---------------------------------------------------------------
# prices
# ---------------------------------------------------------------

def test_the_day_is_rebuilt_from_its_own_minutes(session):
    quote = session.day_quotes()["KAYNES"]
    assert quote["open"] == 3275          # first minute's open
    assert quote["last_price"] == 3660.20  # last minute's close
    assert quote["high"] == 3684.70
    assert quote["low"] == 3274.70
    assert quote["volume"] == 1200


def test_previous_close_comes_from_the_previous_SESSION(session):
    """Not date minus one, which lands on a Sunday every weekend."""
    assert session.day_quotes()["KAYNES"]["prev_close"] == 3227.70


def test_circuit_bands_read_as_unknown_because_they_were_never_saved(session):
    """SMLMAH was bought at its upper circuit. Drawing that band at
    zero would be worse than drawing nothing."""
    quote = session.day_quotes()["KAYNES"]
    assert quote["upper_circuit_limit"] is None
    assert quote["lower_circuit_limit"] is None


def test_pytest_fixture_symbols_never_reach_the_screen(session):
    assert "TESTCO" not in session.day_quotes()


def test_nse_close_beats_ours_when_the_bhavcopy_is_there(session, tmp_path,
                                                         monkeypatch):
    """Our last minute candle is not the official close -- the snapshot
    feed never sees the closing auction."""
    daily = tmp_path / "daily_candles.db"
    conn = sqlite3.connect(daily)
    conn.execute("CREATE TABLE daily_bars (date TEXT, symbol TEXT, "
                 "series TEXT, close REAL)")
    conn.execute("INSERT INTO daily_bars VALUES "
                 "('2026-07-28','KAYNES','EQ',3230.55)")
    conn.commit()
    conn.close()
    monkeypatch.chdir(tmp_path)
    os.makedirs("data", exist_ok=True)
    os.replace(daily, os.path.join("data", "daily_candles.db"))

    quote = session.day_quotes()["KAYNES"]
    assert quote["prev_close"] == 3230.55        # NSE's, not our 3227.70
    assert "bhavcopy" in session.summary()["prev_close_source"]


# ---------------------------------------------------------------
# the log -- news, filings, refusals, breakouts, fills
# ---------------------------------------------------------------

def test_filings_seen_during_the_session_survive_the_process(session):
    """Neither watcher persists anything, so the log is the only
    record that outlives 15:30."""
    rows = session.news_rows()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "ASIANPAINT"
    assert rows[0]["kind"] == "APPROVAL"
    assert rows[0]["filed_at"] == "10:20:02"


def test_yesterdays_lines_are_not_todays(session):
    assert all(r["symbol"] != "YESTERDAY" for r in session.news_rows())
    assert all(r["symbol"] != "YESTERDAY" for r in session.actions())


def test_results_rows_carry_kind(session):
    """dashboard/state.py's shortlist reads row["kind"] directly. A row
    without it took the WHOLE shortlist panel down with a KeyError --
    found by running the replay, not by any test."""
    row = session.result_rows()[0]
    assert row["kind"] == "RESULTS"
    assert row["symbol"] == "REFEX"
    assert row["grade"] == "STRONG"


def test_both_kinds_of_refusal_are_recovered(session):
    reasons = {r["symbol"]: r["source"] for r in session.refusals()}
    assert reasons["KIRLPNU"] == "entry rule"
    assert reasons["BALKRISIND"] == "results gate"


def test_a_breakout_banner_with_no_timestamp_still_lands(session):
    """The ORB banner prints as a block and neither line starts with a
    date, so the first version of this module read zero breakouts on a
    day that had 29."""
    rows = session.breakouts()
    assert [r["symbol"] for r in rows] == ["JYOTHYLAB"]
    assert rows[0]["at"] == "09:31:00"


def test_slippage_is_added_up_at_last(session):
    """The bot has printed the slipped rupees on every fill all along.
    Nothing ever totalled them."""
    total = session.slippage_total()
    assert total["fills"] == 1
    assert total["total_rs"] == 403.0
    assert total["worst"]["symbol"] == "JYOTHYLAB"


def test_missed_stops_are_surfaced_not_buried(session):
    rows = session.missed_stops()
    assert rows[0]["symbol"] == "CHOLAFIN"
    assert rows[0]["traded_to"] == 1791.10


def test_orders_come_from_the_order_log(session):
    rows = session.actions()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "JYOTHYLAB"
    assert rows[0]["action"] == "BUY"


# ---------------------------------------------------------------
# it reports, it never invents
# ---------------------------------------------------------------

def test_a_missing_store_is_a_visible_gap_not_an_exception(tmp_path):
    replay = SessionReplay(
        "2026-07-29", candles_db=str(tmp_path / "nope.db"),
        trade_memory_db=str(tmp_path / "nope.db"),
        trade_log=str(tmp_path / "nope.csv"),
        log_glob=str(tmp_path / "nothing*.log"))
    summary = replay.summary()
    assert summary["trades"] == 0
    assert summary["symbols_priced"] == 0
    what = {n["what"] for n in summary["not_recovered"]}
    assert "closed trades" in what and "prices" in what


def test_a_date_with_no_session_says_so(session):
    replay = SessionReplay("2026-07-30", candles_db=session.candles_db,
                           trade_memory_db=session.trade_memory_db,
                           trade_log=session.trade_log,
                           log_glob=session.log_glob)
    assert replay.summary()["symbols_priced"] == 0
    assert any("no candles" in n["why"] for n in replay.notes())


def test_the_summary_counts_match_the_parts(session):
    summary = session.summary()
    assert summary["trades"] == len(session.closed_positions())
    assert summary["filings"] == len(session.news_rows())
    assert summary["refusals"] == len(session.refusals())
    assert summary["breakouts"] == len(session.breakouts())
    assert summary["orders"] == len(session.actions())


def test_it_opens_every_database_read_only(session, monkeypatch):
    """The live bot may be running. A replay that could write to the
    trade record would be far worse than a blank panel."""
    import core.session_replay as module
    opened = []
    real = module._ro

    def spy(path):
        opened.append(path)
        return real(path)

    monkeypatch.setattr(module, "_ro", spy)
    session.closed_positions()
    session.day_quotes()
    assert opened, "no database was opened at all"
    # Assert the BEHAVIOUR, not the source text -- the first version
    # grepped _ro's source for "mode=ro" and broke the moment that
    # string moved into a helper, while the guarantee was untouched.
    for path in opened:
        assert "mode=ro" in module._sqlite_uri(path)
    connection = real(opened[0])
    with pytest.raises(sqlite3.OperationalError):
        connection.execute("CREATE TABLE nope (x)")


def test_dt_parses_every_shape_the_stores_use():
    assert _dt("2026-07-29 09:22:32.000000").second == 32
    assert _dt("2026-07-29 09:22:32").minute == 22
    assert _dt(None) is None
    assert _dt("not a time") is None


def test_the_read_only_uri_survives_a_path_with_a_space():
    """This project lives at "D:\\Opportunity Trader". A raw
    f"file:{path}" leaves the space unescaped, which is not a legal
    URI. (Backslashes themselves are fine -- SQLite's Windows build
    accepts them, as core/shortlist.py proves every morning -- but
    percent-escaping is still the only correct form.)"""
    from core.session_replay import _sqlite_uri
    uri = _sqlite_uri(os.path.join("data", "trade_memory.db"))
    assert uri.startswith("file:///")
    assert uri.endswith("?mode=ro")
    assert " " not in uri
    assert "\\" not in uri
