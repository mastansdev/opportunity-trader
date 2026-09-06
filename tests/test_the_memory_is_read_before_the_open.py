"""
==========================================================
The one slow call was going to happen at 09:15
==========================================================

    "i want 0 lag & 0 errors from monday. can you confirm that pls"
                                -- the operator, 6 September 2026

He asked for a confirmation and the honest answer was no. The
standing-order gate that shipped on 5 September reads the event store
from inside core/why_moving.why(), which core/ranker.py calls for EVERY
candidate, which main.py's _route_entries() runs every second from the
open.

MEASURED, fresh process:

    first standing lookup               1,642 ms
    every lookup after it                   0 ms

So it was one slow call, not a slow path -- but it was going to be made
at 09:15, on a live decision, on the first stock with no fresh reason.
That is the worst second of the day to spend a second and a half in.

Three things were wrong and all three are cheap to fix.

  IT ASKED PER SYMBOL. standing_causes() has carried a note since the
  day it was written -- "asking per symbol would be 1,800 queries a
  cycle" -- and then the gate went in and did exactly that. The gate
  reads the same batch the board does now, so there is also only one
  answer for the two of them to give.

  IT RE-ASKED A QUESTION THAT CANNOT CHANGE. _headline_names() asks the
  live matcher whether a headline names a company: 86 ms a call,
  because names_in() compares the text against every company on the
  master list. The stored row is days old and the answer is the same
  every time, so it is remembered.

  IT LOADED THE MASTER LIST TWICE. main.py has had a loaded
  MasterLoader since line 307; _matcher() built a second one. warm()
  hands the live one over.

AFTER, measured the same way:

    warm(master_loader), at startup       692 ms
    every lookup in the entry loop       0.03 ms

And the steady-state cost of the gate over 300 symbols through why(),
warmed, alternating with the gate switched off: 0.155 ms a symbol,
which is noise.

A NOTE ON THE FIRST MEASUREMENT, because it was wrong. The run that
raised this reported 18.76 ms a symbol, by timing the gate on first and
the gate off second -- so every one-time load in the process was
charged to the gate. Warmed and alternated A/B/A/B, Friday's version
cost 0.22 ms a symbol. The fault was real and worth fixing; the number
was not. Time the second run, not the first.

Author : H&M Opportunity Trader
==========================================================
"""

import io
import os
import sqlite3
import tempfile
from datetime import date

import pytest

from core import cause_effect as ce


@pytest.fixture(autouse=True)
def _clean_caches():
    """Module state, so every test starts cold."""
    ce._STANDING_BATCH.clear()
    ce._NAMES_CACHE.clear()
    yield
    ce._STANDING_BATCH.clear()
    ce._NAMES_CACHE.clear()


def _events(rows):
    path = os.path.join(tempfile.mkdtemp(), "stock_events.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, symbol TEXT,"
                 " at TEXT, kind TEXT, value_cr REAL, headline TEXT)")
    for sym, at, kind, val, head in rows:
        conn.execute("INSERT INTO events (symbol, at, kind, value_cr,"
                     " headline) VALUES (?,?,?,?,?)",
                     (sym, at, kind, val, head))
    conn.commit()
    conn.close()
    return path


WELSPUN = ("WELCORP", "2026-08-21T03:23", "ORDER", 15840.0,
           "WELSPUN CORP: CO. SECURES LARGEST-EVER SINGLE ORDER IN "
           "COMPANY HISTORY VALUED AT APPROX USD 1.8 BILLION")
ON = date(2026, 9, 5)


def _boom(*_a, **_k):
    raise RuntimeError("the matcher could not be built")


# ------------------------------------------------------------------
# one query for the board, not one for each stock
# ------------------------------------------------------------------

def test_many_symbols_cost_one_pass(monkeypatch):
    builds = []

    def counted(**kw):
        builds.append(1)
        return {}

    monkeypatch.setattr(ce, "standing_causes", counted)
    for name in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG"):
        ce.standing_reason(name, on=ON)
    assert len(builds) == 1, \
        "asked the store %d times for 7 symbols" % len(builds)


def test_a_new_day_is_read_again(monkeypatch):
    builds = []

    def counted(**kw):
        builds.append(1)
        return {}

    monkeypatch.setattr(ce, "standing_causes", counted)
    ce.standing_reason("AAA", on=date(2026, 9, 4))
    ce.standing_reason("AAA", on=date(2026, 9, 7))
    assert len(builds) == 2, \
        "a process running past midnight served yesterday's board"


def test_a_datetime_does_not_defeat_the_cache(monkeypatch):
    """why() is called with a datetime as well as a date, and
    datetime.isoformat() carries the time. Used as the key it would
    miss on every call and rebuild the board every second -- the exact
    cost the cache exists to remove, arriving through the back door."""
    from datetime import datetime

    builds = []

    def counted(**kw):
        builds.append(1)
        return {}

    monkeypatch.setattr(ce, "standing_causes", counted)
    ce.standing_reason("AAA", on=datetime(2026, 9, 7, 9, 15, 0))
    ce.standing_reason("AAA", on=datetime(2026, 9, 7, 15, 1, 30))
    ce.standing_reason("AAA", on=date(2026, 9, 7))
    ce.standing_reason("AAA", on="2026-09-07")
    assert len(builds) == 1, \
        "the same session's date was read as %d different days" % len(builds)


def test_an_explicit_store_is_never_cached():
    """Tools and tests hand in their own file. Caching that would let
    one store answer another store's question."""
    a = ce.standing_reason("WELCORP", on=ON, events_db=_events([WELSPUN]))
    b = ce.standing_reason("WELCORP", on=ON, events_db=_events([]))
    assert a is not None
    assert b is None


def test_an_empty_board_is_not_held_for_five_minutes(monkeypatch):
    """standing_causes() returns {} both when nothing qualifies and
    when the read FAILED, and from here the two look the same. The
    collector writes this store from another process and the journal
    mode is `delete`, so a reader blocks during a write -- holding one
    locked moment for the full five minutes would silence every
    standing cause on the board."""
    monkeypatch.setattr(ce, "standing_causes", lambda **kw: {})
    ce.standing_reason("AAA", on=ON)
    expires_empty = ce._STANDING_BATCH[ON.isoformat()][0]

    ce._STANDING_BATCH.clear()
    monkeypatch.setattr(ce, "standing_causes",
                        lambda **kw: {"AAA": {"text": "x"}})
    ce.standing_reason("AAA", on=ON)
    expires_full = ce._STANDING_BATCH[ON.isoformat()][0]

    assert expires_empty < expires_full, \
        "an empty board is held as long as a real one"
    assert ce.EMPTY_RETRY_SECONDS < ce.STANDING_CACHE_SECONDS


def test_an_expired_board_is_served_not_waited_for(monkeypatch):
    """MEASURED, not assumed: with a writer holding the store a read
    waited 8.67 s and then returned the right answer. Correct, and
    completely wrong for a loop that runs every second. An expired
    board is handed over as it stands and rebuilt on a thread."""
    monkeypatch.setattr(ce, "standing_causes",
                        lambda **kw: {"WELCORP": {"text": "held"}})
    ce.standing_reason("WELCORP", on=ON)                   # first build
    key = ON.isoformat()

    import time as _time
    ce._STANDING_BATCH[key] = (_time.monotonic() - 1,
                               ce._STANDING_BATCH[key][1])

    started = []
    monkeypatch.setattr(ce, "_refresh_soon",
                        lambda today, k: started.append(k))
    got = ce._standing_batch(ON)
    assert got == {"WELCORP": {"text": "held"}}, \
        "the caller was made to wait for a rebuild"
    assert started == [key], "nothing was scheduled to refresh it"


def test_a_failed_rebuild_keeps_the_board_already_held(monkeypatch):
    """The collector writes this store all session. A locked moment
    must not blank every standing cause on the board."""
    key = ON.isoformat()
    import time as _time
    ce._STANDING_BATCH[key] = (_time.monotonic() + 999,
                               {"WELCORP": {"text": "held"}})
    monkeypatch.setattr(ce, "standing_causes", _boom)
    ce._REFRESHING.add(key)
    ce._rebuild(ON, key)
    assert ce._STANDING_BATCH[key][1] == {"WELCORP": {"text": "held"}}
    assert key not in ce._REFRESHING, "the refresh flag was left set"


def test_only_one_rebuild_runs_at_a_time(monkeypatch):
    key = ON.isoformat()
    made = []
    monkeypatch.setattr(ce.threading, "Thread",
                        lambda **kw: made.append(kw) or _NoThread())
    ce._refresh_soon(ON, key)
    ce._refresh_soon(ON, key)
    ce._refresh_soon(ON, key)
    assert len(made) == 1, "a rebuild was started %d times" % len(made)
    ce._REFRESHING.discard(key)


class _NoThread:
    def start(self):
        pass


def test_the_store_is_opened_read_only():
    """The trading process must never be able to write the store the
    collector owns, and it must WAIT for a writer rather than time out
    and report no standing cause -- a wrong answer, not a slow one."""
    src = io.open("core/cause_effect.py", encoding="utf-8").read()
    block = src[src.index("def standing_causes"):]
    block = block[:block.index("_SESSION_CACHE")]
    assert "?mode=ro" in block and "uri=True" in block, \
        "standing_causes writes-open the collector's store"
    assert "timeout=30" in block, \
        "a 5 s default timeout turns a busy collector into 'no reason'"


def test_the_gate_and_the_board_cannot_disagree():
    """They read the same pass now, which is half the point of it."""
    db = _events([WELSPUN])
    board = ce.standing_causes(on=ON, events_db=db)
    gate = ce.standing_reason("WELCORP", on=ON, events_db=db)
    assert gate["text"] == board["WELCORP"]["text"]


# ------------------------------------------------------------------
# the question that cannot change is asked once
# ------------------------------------------------------------------

def test_the_naming_answer_is_remembered():
    head = WELSPUN[4]
    first = ce._headline_names("WELCORP", head)
    assert ("WELCORP", head) in ce._NAMES_CACHE
    assert ce._headline_names("WELCORP", head) is first


def test_remembering_did_not_change_the_answer():
    """The memo must be invisible: same question, same answer, and a
    headline that names nobody is still refused the second time."""
    assert ce._headline_names("WELCORP", WELSPUN[4]) is True
    preamble = ("Pursuant to Regulation 30 of the SEBI (Listing "
                "Obligations and Disclosure Requirements) Regulations, "
                "2015, we wish to inform the Exchange of a landmark order")
    assert ce._headline_names("LANDMARK", preamble) is False
    assert ce._headline_names("LANDMARK", preamble) is False


def test_a_matcher_that_will_not_build_is_not_remembered(monkeypatch):
    """_headline_names fails OPEN, on purpose -- an unchecked sentence
    beats a lost one. Remembering that would make one bad moment
    permanent for the life of the process."""
    monkeypatch.setattr(ce, "_MATCHER", None)
    monkeypatch.setattr(ce, "_matcher", _boom)
    assert ce._headline_names("WELCORP", WELSPUN[4]) is True
    assert ce._NAMES_CACHE == {}, "a failure was remembered as an answer"


# ------------------------------------------------------------------
# and it is warmed where there is slack, not at the open
# ------------------------------------------------------------------

def test_warm_takes_the_loader_the_bot_already_has(monkeypatch):
    """Not a second copy of the master list."""
    monkeypatch.setattr(ce, "_MATCHER", None)
    loaded = []
    from core import master_loader as ml
    real_load = ml.MasterLoader.load

    def counted_load(self):
        loaded.append(1)
        return real_load(self)

    monkeypatch.setattr(ml.MasterLoader, "load", counted_load)

    class Feed:
        def __init__(self, master_loader=None):
            self.master_loader = master_loader

    monkeypatch.setattr("core.telegram_feed.TelegramFeed", Feed)
    sentinel = object()
    ce.warm(sentinel)
    assert ce._MATCHER.master_loader is sentinel
    assert not loaded, "warm() loaded the master list a second time"


def test_warm_never_raises(monkeypatch):
    monkeypatch.setattr(ce, "standing_causes", _boom)
    assert ce.warm(None) == 0


def test_main_actually_warms_it():
    """The fault this codebase keeps producing is machinery nothing
    calls -- the trading gate, surge(), the collector's listener, the
    dashboard's standing causes. This one gets a startup line."""
    src = io.open("main.py", encoding="utf-8").read()
    assert "warm(master_loader)" in src, \
        "main.py never warms the memory -- the 1.6 s lands at 09:15"
    assert src.index("warm(master_loader)") < src.index("def _route_entries"), \
        "the memory must be warmed before the entry loop can ask it"


def test_the_entry_loop_still_owns_the_decision():
    """None of this touched what the bot may buy."""
    from core.why_moving import STALE_REASON_HOURS
    from core.rules import (MIN_MOVE_FROM_PREV_CLOSE_PCT, MIN_VOLUME_RATIO,
                            REQUIRE_A_REASON_ALWAYS)
    assert STALE_REASON_HOURS == 24.0
    assert MIN_MOVE_FROM_PREV_CLOSE_PCT == 3.0
    assert MIN_VOLUME_RATIO == 2.5
    assert REQUIRE_A_REASON_ALWAYS is True
    assert ce.STANDING_GATE_MIN_PCT == 20.0
    assert ce.STANDING_GATE_SESSIONS == 14
