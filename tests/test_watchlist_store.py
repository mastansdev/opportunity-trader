"""
==========================================================
The watchlist -- three groups, and two run themselves
==========================================================

    "WATCHLIST = MAINTAIN ONLY STOCKS WHICH WILL GET RESULTS TODAY
     DURING LIVE MARKETS & GIVE ME OPTION TO ADD SOME STOCKS ...
     AFTER MARKET STOCK RESULTS + NEXT DAY DURING MARKET RESULTS
     STOCK ON NEXT DAY."
    "LIST AS PER DURING , AFTER & OPTION TO ADD/REMOVE + BUTTONS TO
     BUY/SELL ALONG WITH QTY"
                                    -- operator, 4 August 2026

    "Watchlist = Still mess (bot clubbed all under same roof; why
     user needs to work hard)"      -- operator, 3 August 2026

The old one put breakouts, news mentions, shortlist candidates and
results in one list. A list that has to be sorted before it can be
read is not a watchlist.

THE THIRD BUCKET IS THE POINT
-----------------------------
core/results_calendar.py learns each company's habit and reports how
scattered it is:

    BASF    14:25   spread 18 min    reliable      -> DURING
    DIXON   16:07   spread 63 min    reliable      -> AFTER
    TITAN   17:07   spread 269 min   NOT reliable  -> UNKNOWN

TITAN has reported anywhere across four and a half hours. Filing it
under AFTER would invent a certainty the history does not support, and
he would stop trusting the split.

Author : H&M Opportunity Trader
==========================================================
"""

import json

import pytest

from core.watchlist_store import (AFTER, DURING, UNKNOWN, WatchlistStore,
                                  bucket_for)


# ---------------------------------------------------------------
# 1. WHEN IT REPORTS DECIDES WHERE IT GOES
# ---------------------------------------------------------------
def test_reporting_inside_market_hours_is_tradeable_today():
    assert bucket_for({"minutes": 865, "reliable": True}) == DURING   # 14:25


def test_reporting_after_the_close_carries_to_tomorrow():
    assert bucket_for({"minutes": 967, "reliable": True}) == AFTER    # 16:07


def test_reporting_before_the_open_is_not_during():
    """08:30 is tomorrow's-open material by the same logic as 17:00."""
    assert bucket_for({"minutes": 510, "reliable": True}) == AFTER


def test_the_boundaries_belong_to_during():
    assert bucket_for({"minutes": 9 * 60 + 15, "reliable": True}) == DURING
    assert bucket_for({"minutes": 15 * 60 + 30, "reliable": True}) == DURING


# ---------------------------------------------------------------
# 2. A SCATTERED HISTORY IS NOT AN ANSWER
# ---------------------------------------------------------------
def test_an_unreliable_time_is_never_filed_as_a_fact():
    """TITAN: 17:07 on average, 269 minutes of spread. The average is
    arithmetic, not a prediction."""
    assert bucket_for({"minutes": 1027, "reliable": False}) == UNKNOWN


def test_no_timing_at_all_is_unknown_not_during():
    """DURING is the group he trades from. Nothing may land there by
    default."""
    for empty in (None, {}, {"reliable": True}, "14:25", 865):
        assert bucket_for(empty) == UNKNOWN


def test_a_junk_minute_value_does_not_crash_the_panel():
    assert bucket_for({"minutes": "quarter past two", "reliable": True}) \
        == UNKNOWN


# ---------------------------------------------------------------
# 3. HIS ADDS ARE HIS, AND THEY SURVIVE A RESTART
# ---------------------------------------------------------------
@pytest.fixture
def store(tmp_path):
    return WatchlistStore(path=str(tmp_path / "wl.json"))


def test_add_and_remove(store):
    assert store.add("STYRENIX") is True
    assert store.symbols() == ["STYRENIX"]
    assert store.remove("STYRENIX") is True
    assert store.symbols() == []


def test_adding_twice_is_not_an_error(store):
    store.add("GAIL")
    assert store.add("GAIL") is True
    assert store.symbols() == ["GAIL"]


def test_removing_something_absent_says_so(store):
    assert store.remove("NOTTHERE") is False


def test_case_and_spaces_do_not_create_duplicates(store):
    store.add(" tcs ")
    store.add("TCS")
    assert store.symbols() == ["TCS"]


def test_an_empty_symbol_is_refused(store):
    assert store.add("") is False
    assert store.add(None) is False


def test_it_survives_a_restart(tmp_path):
    """He adds a name in the morning and restarts the bot at lunch."""
    path = str(tmp_path / "wl.json")
    WatchlistStore(path=path).add("APLAPOLLO")
    assert WatchlistStore(path=path).symbols() == ["APLAPOLLO"]


def test_a_note_is_kept_with_the_symbol(store):
    store.add("STYRENIX", note="order win Rs 500 cr")
    assert "order win" in store.note_for("STYRENIX")


def test_a_corrupt_file_costs_the_watchlist_not_the_session(tmp_path):
    path = tmp_path / "wl.json"
    path.write_text("{ not json", encoding="utf-8")
    store = WatchlistStore(path=str(path))
    assert store.symbols() == []
    assert store.add("TCS") is True          # still usable


def test_an_unwritable_path_does_not_raise(tmp_path):
    blocker = tmp_path / "notadir"
    blocker.write_text("x", encoding="utf-8")
    store = WatchlistStore(path=str(blocker / "wl.json"))
    assert store.add("TCS") is True          # live now, not persisted
    assert store.symbols() == ["TCS"]


def test_the_file_is_replaced_not_truncated(tmp_path):
    """A crash mid-write must not leave him with half a file and no
    watchlist."""
    src = open("core/watchlist_store.py", encoding="utf-8").read()
    assert "os.replace(" in src


# ---------------------------------------------------------------
# 4. IT IS ON THE SCREEN, AND IT IS HIS ALONE TO EDIT
# ---------------------------------------------------------------
# ---- THESE FOUR READ A PAGE THAT NO LONGER EXISTS. 16 August 2026 ----
#
# They opened dashboard/static/screen.html, which was deleted when four
# dashboards were collapsed into /board and /full. The panel was NOT
# ported -- and the store, the POST route and the s.watchlist key all
# survived, so the bot went on maintaining a watchlist he could not see
# or edit, and nothing said so.
#
# They did not go red on the day of the deletion because the full suite
# did not finish that day. A test that reads a file by name fails the
# moment it is actually run; the cost was the day in between.
#
# Repointed at /board, where the panel now lives as a fourth tab.

BOARD = "dashboard/static/board.html"


def _board():
    return open(BOARD, encoding="utf-8").read()


def test_editing_needs_the_operator_token():
    """It writes a file. A view-only visitor must not change what he
    is watching -- though it can never place an order either way.

    ---- IT MUST ACCEPT BOTH SPELLINGS. 16 August 2026. ----

    This asserted _token_matches(token) -- the query parameter alone.
    _require_operator() learned on 5 August to take the X-Operator-
    Token HEADER *or* ?token=..., because the page sent one and the
    server read the other; this route was missed.

    It matters now: the restored panel on /board sends the header, the
    same way BUY does. Under the query-only spelling every watchlist
    edit would answer "read-only link" the moment an operator token was
    actually set -- and it would look like the button was broken, not
    like a gate doing its job.
    """
    src = open("dashboard/server.py", encoding="utf-8").read()
    block = src[src.find('@app.post("/api/watchlist'):
                src.find('@app.get("/api/snapshot")')]
    assert "_token_matches(supplied)" in block
    assert 'headers.get("X-Operator-Token"' in block, (
        "the header spelling is not accepted -- /board sends it")
    assert 'query_params.get("token"' in block or "or token" in block, (
        "the query spelling is not accepted -- old links send it")
    assert "read-only link" in block


def test_only_nse_names_can_be_added():
    """     "pls make sure we will trade only NSE listed stocks"

    A typo would otherwise sit on the screen forever with no price."""
    src = open("dashboard/server.py", encoding="utf-8").read()
    block = src[src.find('@app.post("/api/watchlist'):
                src.find('@app.get("/api/snapshot")')]
    assert "master_loader.all_symbols(" in block


# ---------------------------------------------------------------
# 5. THE FAKE MUST MATCH THE REAL CLASS
# ---------------------------------------------------------------
#     "could not send: SyntaxError: Unexpected token 'I',
#      "Internal S"... is not valid JSON"
#                                     -- operator, 4 August 2026
#
# The endpoint 500'd on every add. I had written
# master_loader.known_symbols(); MasterLoader has all_symbols() and
# known_symbols() has never existed. The test passed because I ALSO
# wrote the fake loader it ran against and gave the fake the method I
# had invented -- so the test confirmed my own error.
#
# Third time on this project: tools/dhan_token.py, release_all(),
# InstrumentMaster.rows(). Naming from memory is the habit; a fake
# built from the same memory is what stops the test catching it.
def test_the_endpoint_calls_a_method_master_loader_actually_has():
    """Reads the REAL class, not a stand-in. This is the check that
    was missing."""
    import inspect
    import re

    from core.master_loader import MasterLoader

    src = open("dashboard/server.py", encoding="utf-8").read()
    block = src[src.find('@app.post("/api/watchlist'):
                src.find('@app.get("/api/snapshot")')]
    # COMMENTS STRIPPED. The note explaining this very bug contains
    # the words "master_loader.known_symbols()" -- matching prose would
    # make the test fail on its own explanation.
    code = "\n".join(line for line in block.splitlines()
                     if not line.strip().startswith("#"))
    called = set(re.findall(r"master_loader\.(\w+)\(", code))
    assert called, "the endpoint stopped checking the universe"
    real = {name for name, _ in inspect.getmembers(MasterLoader)
            if not name.startswith("_")}
    assert called <= real, called - real


def test_a_crash_is_a_readable_refusal_not_a_500():
    """It cannot place an order, so nothing it does is worth an
    unreadable crash page."""
    src = open("dashboard/server.py", encoding="utf-8").read()
    block = src[src.find('@app.post("/api/watchlist'):
                src.find('@app.get("/api/snapshot")')]
    body = block[block.find("symbol = "):]
    assert "except Exception" in body
    assert '"success": False' in body


# ---------------------------------------------------------------
# 6. IT CANNOT TAKE THE SNAPSHOT DOWN, AND IT CANNOT CALL A METHOD
#    THAT DOES NOT EXIST
# ---------------------------------------------------------------
#     AttributeError: 'DashboardState' object has no attribute
#     '_plain_headline'          -- main.py crash, 4 August 2026
#
# _plain_headline IS in state.py -- as a MODULE-LEVEL function taking
# text. I called it as a method taking a symbol. Wrong on both counts,
# and it took the whole snapshot with it: refresh() died and main.py
# died with it on shutdown.
#
# Fourth invented name in two days: known_symbols(),
# InstrumentMaster.rows(), release_all(), this. Every one of them was
# written from memory and every one passed review. So this checks the
# REAL class by reflection instead of trusting either of us.
def test_build_watchlist_only_calls_methods_that_exist():
    import inspect
    import re

    from dashboard.state import DashboardState

    for name in ("build_watchlist", "_reason_text", "_change_pct_for",
                 "_safe_watchlist"):
        assert hasattr(DashboardState, name), name

    src = "".join(inspect.getsource(getattr(DashboardState, name))
                  for name in ("build_watchlist", "_reason_text",
                               "_change_pct_for"))
    # DOCSTRINGS STRIPPED TOO, not just # lines. The docstring on
    # _reason_text explains this very bug and contains the words
    # "self._plain_headline()" -- so the test failed on its own
    # explanation. Sixth time prose has broken an assertion here.
    code = re.sub(r'""".*?"""', "", src, flags=re.S)
    code = "\n".join(line for line in code.splitlines()
                     if not line.strip().startswith("#"))
    called = set(re.findall(r"self\.(_?\w+)\(", code))
    real = {name for name, _ in inspect.getmembers(DashboardState)}
    assert called <= real, called - real


def test_a_failing_watchlist_costs_only_the_watchlist():
    """One panel must never be able to kill refresh(). Every sibling
    build_* returns a dict on failure; this one went in without the
    same guard and stopped the process."""
    import inspect

    from dashboard.state import DashboardState

    payload = inspect.getsource(DashboardState._build)
    assert '"watchlist": self._safe_watchlist()' in payload

    guard = inspect.getsource(DashboardState._safe_watchlist)
    assert "except Exception" in guard
    assert '"available": False' in guard


# ---------------------------------------------------------------
# THE EDIT HAS TO REACH THE SCREEN, NOT JUST THE FILE
# ---------------------------------------------------------------
#
#     "i'm unable to delete the stocks added in - Watch tab"
#                                 -- operator, 17 August 2026
#
# Every part of that path was already correct and it still looked
# broken:
#
#     the click handler        fires, confirms, POSTs
#     /api/watchlist/remove    returns {"success": true}
#     core/watchlist_store.py  drops the row and saves the file
#
# and the stock stayed on his screen. /api/snapshot serves the payload
# THE LIVE LOOP BUILDS -- deliberately, so the page and the engine can
# never disagree -- and build_watchlist() only runs inside a full
# _build(). Until the next one, the panel is the old list.
#
# Reproduced against a live server: the store had lost GAIL and the
# snapshot still listed GAIL, MARICO, AUROPHARMA and BHARTIARTL, three
# of them removed sessions earlier. So he pressed remove, nothing
# happened, and he pressed it again. Every press had worked.

def test_the_state_can_refresh_just_the_watchlist_panel():
    """A full _build() walks 1,314 symbols and takes seconds. Doing
    that on a click is how the dashboard went stale on 13 August, so
    this replaces one panel in the served snapshot."""
    src = open("dashboard/state.py", encoding="utf-8").read()
    assert "def refresh_watchlist_panel" in src
    body = src[src.find("def refresh_watchlist_panel"):]
    body = body[:body.find("\n    def ", 10)]
    assert "_safe_watchlist" in body, "it rebuilds more than the panel"
    assert "self._lock" in body, "the snapshot is swapped without the lock"


def test_both_add_and_remove_refresh_the_panel():
    """An add that does not show is the same bug wearing the other
    sign, and it was there too."""
    src = open("dashboard/server.py", encoding="utf-8").read()
    block = src[src.find('@app.post("/api/watchlist'):
                src.find('@app.get("/api/why")')]
    assert block.count("refresh_watchlist_panel") >= 2, (
        "only one of add/remove refreshes the screen")


def test_the_refresh_is_optional_so_a_bare_state_still_works():
    """getattr with a default: tests and tools build partial states,
    and a watchlist edit must not 500 because one lacks the method."""
    src = open("dashboard/server.py", encoding="utf-8").read()
    block = src[src.find('@app.post("/api/watchlist'):
                src.find('@app.get("/api/why")')]
    assert 'getattr(dashboard_state, "refresh_watchlist_panel"' in block
