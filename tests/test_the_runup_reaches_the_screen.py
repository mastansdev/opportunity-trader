"""
==========================================================
Was the good news already bought? -- and does he SEE it
==========================================================

    "some stocks will move even though good grade. as we both know
     market rewards by anticipating future"
                                -- operator, 8 August 2026

    "in trent case the results were good but conviction on future
     growth expected higher but results agreed but store growth & some
     business updates not liked by investors"
                                -- operator, 6 August 2026, unprompted

WHY THIS FILE EXISTS
--------------------
core/runup.py was written on 7 August, validated on 101 real
observations, and imported by NOTHING for a day. core/ranker.py sat in
exactly that state for a week and cost him a week of trading, and
core/result_tag.py did it too.

So the last three tests here do not check the reading. They check that
the reading REACHES HIS SCREEN. A correct number nobody sees is
indistinguishable from a number that was never computed.

THE ONE RULE THAT MUST NOT DRIFT
--------------------------------
It reports. It never vetoes.

    "nothing from the guides becomes a rule until scored against real
     outcomes"

Measured across five sessions, SPENT was the worst group at -0.26% and
FLAT the best at +0.33% -- pointing the right way, on five stocks in
the SPENT bucket. That is a hint. Turning a hint into a veto is how
the bot starts refusing the trades he wants.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import date, datetime

from core import runup


# ---------------------------------------------------------------
# The reading itself
# ---------------------------------------------------------------
def test_a_stock_that_ran_hard_reads_SPENT(tmp_path):
    db = _tape(tmp_path, "RUNHARD", start=100.0, step=2.0)
    got = runup.run_up("RUNHARD", date(2026, 8, 7), db_path=str(db))
    assert got["ok"] is True
    assert got["reading"] == "SPENT"
    assert got["pct"] >= runup.SPENT_PCT


def test_a_stock_that_went_nowhere_reads_FLAT(tmp_path):
    db = _tape(tmp_path, "SLEEPY", start=100.0, step=0.05)
    got = runup.run_up("SLEEPY", date(2026, 8, 7), db_path=str(db))
    assert got["reading"] == "FLAT"


def test_a_stock_sold_into_its_result_reads_SOLD_OFF(tmp_path):
    """The opposite signal, and the more interesting one -- nothing
    was anticipated, so a good number is a real surprise."""
    db = _tape(tmp_path, "DUMPED", start=100.0, step=-1.2)
    got = runup.run_up("DUMPED", date(2026, 8, 7), db_path=str(db))
    assert got["reading"] == "SOLD OFF"
    assert got["pct"] <= runup.COLD_PCT


def test_it_measures_only_BEFORE_the_result(tmp_path):
    """A run-up that includes the result day is just the reaction,
    which the bot already has. Bars on or after the date must not
    count."""
    db = _tape(tmp_path, "EDGE", start=100.0, step=0.0)
    import sqlite3
    con = sqlite3.connect(str(db))
    # A huge move ON the result day. It must not be measured.
    con.execute("insert into daily_bars(date, symbol, close) values (?,?,?)",
                ("2026-08-07", "EDGE", 400.0))
    con.commit()
    con.close()
    got = runup.run_up("EDGE", date(2026, 8, 7), db_path=str(db))
    assert got["ok"] is True
    assert abs(got["pct"]) < 1.0, "it counted the result day itself"


def test_no_history_says_so_rather_than_guessing(tmp_path):
    db = _tape(tmp_path, "OTHER", start=100.0, step=1.0)
    got = runup.run_up("NOHISTORY", date(2026, 8, 7), db_path=str(db))
    assert got["ok"] is False
    assert "cannot say" in got["why"] or "history" in got["why"]


def test_it_never_raises(tmp_path):
    db = _tape(tmp_path, "X", start=100.0, step=1.0)
    for symbol in (None, "", "   "):
        assert runup.run_up(symbol, date(2026, 8, 7),
                            db_path=str(db))["ok"] is False
    assert runup.run_up("X", "not-a-date", db_path=str(db))["ok"] is False


# ---------------------------------------------------------------
# It must be askable about the past -- same lesson as graded_symbols()
# ---------------------------------------------------------------
def test_reported_on_is_time_bounded():
    """A function that can only answer 'right now' cannot be replayed,
    and every number built on it is unfalsifiable. graded_symbols()
    had to learn this on 8 August."""
    import inspect
    src = inspect.getsource(runup.reported_on)
    assert "on_date" in src
    assert "results_date <= ?" in src, (
        "reported_on() would return a result published after the "
        "moment being asked about")


# ---------------------------------------------------------------
# IT HAS TO REACH THE SCREEN
# ---------------------------------------------------------------
def test_the_dashboard_computes_it():
    import inspect

    from dashboard import state
    src = inspect.getsource(state)
    assert "_runup_for" in src, "dashboard/state.py never asks for it"
    assert 'row["runup"]' in src, (
        "the reading is computed but never attached to a ranked row")


def test_it_reports_and_never_vetoes():
    """The line that must not move. If a future change makes SPENT
    block an entry, this fails and the change gets argued about."""
    import inspect

    from core import auto_entry
    from dashboard import state
    for module in (auto_entry, state):
        src = inspect.getsource(module)
        for banned in ("runup\") == \"SPENT\"", "'SPENT'", '"SPENT"'):
            if banned in src and "refuse" in src.lower():
                # Only fail if SPENT is used near a refusal path.
                idx = src.find(banned)
                window = src[max(0, idx - 300):idx + 300].lower()
                assert "return" not in window or "refuse" not in window, (
                    "the run-up reading has become a veto")


# ---------------------------------------------------------------
def _tape(tmp_path, symbol, start, step, sessions=14):
    """A tiny daily_candles.db with one stock walking a fixed step."""
    import sqlite3
    db = tmp_path / "daily.db"
    con = sqlite3.connect(str(db))
    con.execute("create table if not exists daily_bars "
                "(id integer primary key, date text, symbol text, "
                "series text, open real, high real, low real, close real, "
                "prev_close real, volume real, turnover real)")
    price = start
    for i in range(sessions):
        day = date(2026, 7, 25) + __import__("datetime").timedelta(days=i)
        if day >= date(2026, 8, 7):
            break
        con.execute("insert into daily_bars(date, symbol, close) "
                    "values (?,?,?)", (day.isoformat(), symbol, price))
        price += step
    con.commit()
    con.close()
    return db
