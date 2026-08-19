"""
==========================================================
From the update to the next result
==========================================================

    "bot needs to know day to day updates & memory must be updated -
     tracked whether stock performed from the update to next result.
     still user doing manual updates/data maintainance which is not
     ideal to do so bot must maintain the complete record from event
     date, price on that date to movement on the event date to next
     result date + guidance from the company."
                                -- operator, 19 August 2026

He was keeping this by hand. All three inputs were already on disk
and no line of code joined them:

    data/stock_events.db      15,130 events, 1,727 symbols
    data/results_calendar.db   7,086 results dates
    data/daily_candles.db      1.1M daily bars back to 2016

WHY THE EXISTING MEASUREMENTS DID NOT COVER IT
core/outcomes.py measures the session AFTER an event. core/
opportunity.py measures a family's average next-session move. Both
answer "did the market react". His question is about a HOLDING
PERIOD: an order win in May is a claim about a quarter, and that
quarter ends when the company next reports. Grading it on the
following morning's candle judges the claim before the evidence
exists.

THE FOUR WAYS A LEDGER LIKE THIS LIES, AND A TEST FOR EACH
  1. Counting an unfinished window as a flat result, so a claim still
     waiting on its print drags an average toward zero.
  2. Reading the event's own day as the outcome.
  3. Dropping an event filed on a Saturday because no bar exists.
  4. Growing an opinion -- becoming a gate rather than a record.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib
import sqlite3

import pytest

from core import stock_memory as sm

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def books(tmp_path, monkeypatch):
    """Three tiny stores shaped exactly like the real ones."""
    events = tmp_path / "events.db"
    results = tmp_path / "results.db"
    daily = tmp_path / "daily.db"

    conn = sqlite3.connect(events)
    conn.execute("CREATE TABLE events (symbol TEXT, at TEXT, kind TEXT, "
                 "grade TEXT, value_cr REAL, headline TEXT, detail TEXT)")
    conn.executemany(
        "INSERT INTO events VALUES (?,?,?,?,?,?,?)", [
            # an order win, then a result four sessions later
            ("TESTCO", "2026-05-04T09:20:00+00:00", "ORDER", None, 450.0,
             "bags order worth Rs 450 crore", None),
            # filed on a SATURDAY -- must roll to Monday, not vanish
            ("TESTCO", "2026-05-09T11:00:00+00:00", "NEWS", None, None,
             "weekend filing", None),
            # management guidance
            ("TESTCO", "2026-05-05T09:20:00+00:00", "CONCALL", None, None,
             "concall", "management guided to 20% revenue growth"),
            # market-wide -- must never enter a company's ledger
            ("TESTCO", "2026-05-04T09:20:00+00:00", "MACRO", None, None,
             "RBI holds rates", None),
        ])
    conn.commit()
    conn.close()

    conn = sqlite3.connect(results)
    conn.execute("CREATE TABLE results_events (symbol TEXT, "
                 "results_date TEXT)")
    conn.execute("INSERT INTO results_events VALUES ('TESTCO', "
                 "'2026-05-08')")
    conn.commit()
    conn.close()

    conn = sqlite3.connect(daily)
    conn.execute("CREATE TABLE daily_bars (symbol TEXT, date TEXT, "
                 "close REAL, prev_close REAL)")
    conn.executemany("INSERT INTO daily_bars VALUES (?,?,?,?)", [
        ("TESTCO", "2026-05-04", 100.0, 98.0),    # event day, +2.04%
        ("TESTCO", "2026-05-05", 102.0, 100.0),
        ("TESTCO", "2026-05-06", 104.0, 102.0),
        ("TESTCO", "2026-05-07", 108.0, 104.0),
        ("TESTCO", "2026-05-08", 110.0, 108.0),   # results day
        ("TESTCO", "2026-05-11", 112.0, 110.0),   # the Monday
    ])
    conn.commit()
    conn.close()

    monkeypatch.setattr(sm, "EVENTS_DB", str(events))
    monkeypatch.setattr(sm, "RESULTS_DB", str(results))
    monkeypatch.setattr(sm, "DAILY_DB", str(daily))
    return tmp_path


# ---------------------------------------------------------------
# THE RECORD HE WAS KEEPING BY HAND
# ---------------------------------------------------------------

def test_it_carries_every_field_he_listed(books):
    """'event date, price on that date, movement on the event date,
    next result date' -- his words, checked one by one."""
    rows = sm.event_record("TESTCO")
    order = next(r for r in rows if r["kind"] == "ORDER")
    assert order["at"] == "2026-05-04"
    assert order["price_on_event"] == 100.0
    assert order["move_on_event_pct"] == pytest.approx(2.04, abs=0.01)
    assert order["next_results_date"] == "2026-05-08"
    assert order["price_at_next_results"] == 110.0
    assert order["move_to_results_pct"] == pytest.approx(10.0)
    assert order["still_open"] is False


def test_guidance_from_the_company_is_kept(books):
    """'+ guidance from the company' -- what management SAID, not only
    what it did."""
    rows = sm.event_record("TESTCO")
    concall = next(r for r in rows if r["kind"] == "CONCALL")
    assert "20% revenue growth" in concall["guidance"]


def test_the_sessions_held_are_counted(books):
    rows = sm.event_record("TESTCO")
    order = next(r for r in rows if r["kind"] == "ORDER")
    assert order["sessions_to_results"] == 4


# ---------------------------------------------------------------
# AN OPEN WINDOW IS NOT A ZERO
# ---------------------------------------------------------------

def test_an_event_awaiting_its_print_is_never_averaged_in(books):
    """The weekend filing lands AFTER the only results date, so its
    window is still open. Counting it flat would drag the average
    toward zero and make an unsettled claim look like a failed one --
    and with results season over until October, most of his ledger is
    in exactly that state."""
    rows = sm.event_record("TESTCO")
    later = next(r for r in rows if r["headline"] == "weekend filing")
    assert later["still_open"] is True
    assert later["move_to_results_pct"] is None

    got = sm.track_record("TESTCO")
    assert got["still_open"] >= 1
    assert got["settled"] == 2, "an unsettled window was counted"
    # Two windows close before the 8 May print: the order (100 -> 110,
    # +10.00%) and the concall the next session (102 -> 110, +7.84%).
    # 8.92 is their mean, and the open window is absent from it --
    # which is the whole assertion.
    assert got["avg_move_to_results_pct"] == pytest.approx(8.92, abs=0.01)
    assert got["delivered_pct"] == pytest.approx(100.0)


def test_an_open_window_still_reports_the_move_so_far(books):
    """Unsettled is not unknown. He needs to see where it stands."""
    rows = sm.event_record("TESTCO")
    later = next(r for r in rows if r["headline"] == "weekend filing")
    assert later["move_since_pct"] is not None


# ---------------------------------------------------------------
# A SATURDAY FILING IS ANSWERED BY MONDAY
# ---------------------------------------------------------------

def test_an_event_with_no_bar_that_day_rolls_forward(books):
    """9 May 2026 is a Saturday. Dropping it would silently lose every
    weekend and after-hours filing -- which is when most of them are
    actually made."""
    rows = sm.event_record("TESTCO")
    later = next(r for r in rows if r["headline"] == "weekend filing")
    assert later["price_on_event"] == 112.0, "the Monday close"


# ---------------------------------------------------------------
# MARKET-WIDE NEWS IS NOT THIS COMPANY'S CLAIM
# ---------------------------------------------------------------

def test_a_macro_event_never_enters_a_companys_ledger(books):
    """'RBI holds rates' is not a promise TESTCO has to answer for at
    its next print."""
    kinds = {r["kind"] for r in sm.event_record("TESTCO")}
    assert "MACRO" not in kinds


# ---------------------------------------------------------------
# IT NEVER RAISES AND NEVER WRITES
# ---------------------------------------------------------------

def test_a_missing_store_answers_empty(monkeypatch):
    monkeypatch.setattr(sm, "EVENTS_DB", "no-such-file.db")
    assert sm.event_record("TESTCO") == []
    assert sm.track_record("TESTCO")["events"] == 0


def test_junk_symbols_answer_empty(books):
    for junk in (None, "", "   ", "NEVERLISTEDCO"):
        assert sm.event_record(junk) == []


def test_every_store_is_opened_read_only():
    """It reads three databases the live bot WRITES. A reader holding
    a write lock on data/stock_events.db stalls the feed appending to
    it."""
    src = (ROOT / "core" / "stock_memory.py").read_text(encoding="utf-8")
    body = src[src.find("def _read_only("):src.find("def _day(")]
    assert "mode=ro" in body


def test_it_reads_the_real_stores_without_blowing_up():
    """Against the actual files, not a stub. 1,727 symbols carry
    events; if the schema moves under this, it fails here."""
    got = sm.track_record("SBIN")
    assert got["symbol"] == "SBIN"
    assert got["events"] >= 0
    assert isinstance(got["by_kind"], dict)


# ---------------------------------------------------------------
# IT IS A RECORD, NOT AN OPINION
# ---------------------------------------------------------------

def test_no_gate_consults_it():
    """THE LINE THAT MUST NOT MOVE. He asked to stop maintaining a
    ledger by hand, not for another voice in the entry decision. The
    day a number here earns a rule, that rule gets written and argued
    on its own -- the way the payoff tilt was on 19 August."""
    for name in ("auto_entry.py", "ranker.py", "engine.py"):
        src = (ROOT / "core" / name).read_text(encoding="utf-8")
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith("#"))
        for banned in ("event_record", "track_record"):
            assert banned not in code, (
                f"core/{name} is trading on the event ledger")
