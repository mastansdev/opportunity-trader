"""
==========================================================
Large, mid or small -- written down, deciding nothing
==========================================================

    "yes build them as it will help us in future"
                                -- the operator, 6 September 2026

He asked first whether it would change trading. It does not, and that
was the reason to build it:

    "does that brings any change in trading & overall outcome?"

There is no market-cap gate anywhere on the entry path -- core/rules,
core/ranker, core/auto_entry, core/engine and core/results_gate carry
zero references to size. The only size floor in the repo is the
Rs 2,000 cr one in core/centre.py, and nothing calls core/centre.py.

WHY WRITE IT DOWN THEN. Because on 6 September his own book could not
answer whether size predicts anything:

    from 29 August, under the rules running now
        LARGE     2 trades     2 up     0 down
        MID       3 trades     3 up     0 down
        SMALL    56 trades    25 up    31 down

Five non-small trades. The 139 trades before 29 August ran a different
stop, target and sizing, and his rule is that a new rule is never
tuned on trades from the old one. The question was unanswerable
because NOTHING WROTE THE SIZE DOWN -- so now every trade records it,
beside door, volume_x, jump_x and liveness.

TWO MEASURES, TWO STORES, NEVER SWAPPED
---------------------------------------
    core/market_cap.py     FREE FLOAT     what the order gate reads
    core/company_size.py   TOTAL          what SEBI's bands are made of

An order worth 47% of the FLOATING company is the fact that opens the
standing-order door. 47% of the total company is a different number
about a different question. Separate modules so a later edit cannot
quietly reach for the wrong one.

THE RANK IS NSE'S OWN. data/LIST_NSE.xlsx carries a Rank column,
verified on 6 September to be exactly the size order and contiguous
1..2,773. Recomputing it here would invent a second answer that drifts
from NSE's.

Author : H&M Opportunity Trader
==========================================================
"""

import io
import json
import os
import sqlite3
import tempfile
from datetime import datetime

import pytest

from core import company_size


@pytest.fixture()
def store(monkeypatch):
    """A size store holding a few known companies."""
    path = os.path.join(tempfile.mkdtemp(), "company_size.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"at": "2026-09-06T07:54:28",
                   "source": "LIST_NSE.xlsx",
                   "sizes": {
                       "RELIANCE":  {"cap_cr": 1970787.7, "rank": 1,
                                     "band": "LARGE"},
                       "DRREDDY":   {"cap_cr": 105170.0, "rank": 100,
                                     "band": "LARGE"},
                       "SHREECEM":  {"cap_cr": 104523.0, "rank": 101,
                                     "band": "MID"},
                       "TATAELXSI": {"cap_cr": 34604.1, "rank": 250,
                                     "band": "MID"},
                       "NLCINDIA":  {"cap_cr": 34428.6, "rank": 251,
                                     "band": "SMALL"},
                       "TEJASNET":  {"cap_cr": 9989.2, "rank": 554,
                                     "band": "SMALL"}}}, fh)
    monkeypatch.setattr(company_size, "STORE", path)
    company_size._CACHE.clear()
    return path


# ------------------------------------------------------------------
# SEBI's boundaries, at the exact edges
# ------------------------------------------------------------------

def test_the_bands_are_sebis_own():
    assert company_size.band_for_rank(1) == "LARGE"
    assert company_size.band_for_rank(100) == "LARGE"
    assert company_size.band_for_rank(101) == "MID"
    assert company_size.band_for_rank(250) == "MID"
    assert company_size.band_for_rank(251) == "SMALL"
    assert company_size.band_for_rank(2773) == "SMALL"


def test_no_rank_is_no_band():
    for bad in (None, 0, -3, "", "n/a", float("nan")):
        assert company_size.band_for_rank(bad) is None


def test_it_reads_the_real_edges(store):
    assert company_size.band_of("DRREDDY") == "LARGE"
    assert company_size.band_of("SHREECEM") == "MID"
    assert company_size.band_of("TATAELXSI") == "MID"
    assert company_size.band_of("NLCINDIA") == "SMALL"


# ------------------------------------------------------------------
# unknown is not small
# ------------------------------------------------------------------

def test_a_company_not_on_the_list_gets_nothing(store):
    """235 of his 1,976 are not on NSE's list, mostly listed after the
    filing period. Calling them SMALL would be a guess, and a guess is
    what this whole file exists to avoid."""
    assert company_size.of("NOSUCHCO") is None
    assert company_size.band_of("NOSUCHCO") is None
    assert company_size.label("NOSUCHCO") is None


def test_a_missing_store_is_quiet_not_an_error(monkeypatch):
    monkeypatch.setattr(company_size, "STORE",
                        os.path.join(tempfile.mkdtemp(), "nothing.json"))
    company_size._CACHE.clear()
    assert company_size.load() == {"at": None, "sizes": {}}
    assert company_size.band_of("RELIANCE") is None
    assert company_size.status()["available"] is False


def test_an_unreadable_store_is_quiet_too(monkeypatch):
    path = os.path.join(tempfile.mkdtemp(), "company_size.json")
    io.open(path, "w", encoding="utf-8").write("{not json")
    monkeypatch.setattr(company_size, "STORE", path)
    company_size._CACHE.clear()
    assert company_size.band_of("RELIANCE") is None


# ------------------------------------------------------------------
# what it says
# ------------------------------------------------------------------

def test_the_label_carries_the_size(store):
    assert company_size.label("TEJASNET") == "SMALL CAP, Rs 9,989 cr"


def test_many_at_once_agrees_with_one_at_a_time(store):
    many = company_size.bands_for(["RELIANCE", "TEJASNET", "NOSUCHCO"])
    assert many == {"RELIANCE": "LARGE", "TEJASNET": "SMALL"}
    for symbol, band in many.items():
        assert company_size.band_of(symbol) == band


def test_status_counts_the_bands(store):
    got = company_size.status()
    assert got["available"] is True
    assert (got["large"], got["mid"], got["small"]) == (2, 2, 2)
    assert got["basis"] == "total market cap"


# ------------------------------------------------------------------
# reading NSE's file
# ------------------------------------------------------------------

def test_refresh_skips_rows_with_no_figure(tmp_path, monkeypatch):
    """94 rows read "Not traded during the period" rather than a
    number. They are left out entirely."""
    pd = pytest.importorskip("pandas")
    pytest.importorskip("openpyxl")
    src = tmp_path / "LIST_NSE.xlsx"
    column = ("Average market capitalisation from July  01, 2025 to "
              "December 31, 2025 (Rs. In lakhs)")
    pd.DataFrame([
        {"Rank": 1, "Symbol": "RELIANCE", column: 197078768.99},
        {"Rank": 101, "Symbol": "SHREECEM", column: 10452300.0},
        {"Rank": 2866, "Symbol": "XLENERGY",
         column: "Not traded during the period"},
    ]).to_excel(src, index=False)

    out = tmp_path / "company_size.json"
    monkeypatch.setattr(company_size, "STORE", str(out))
    company_size._CACHE.clear()
    assert company_size.refresh(source=str(src), store=str(out)) == 2
    assert company_size.band_of("RELIANCE") == "LARGE"
    assert company_size.band_of("SHREECEM") == "MID"
    assert company_size.of("XLENERGY") is None


def test_lakhs_become_crore(tmp_path, monkeypatch):
    """NSE files the figure in LAKHS. Everything this bot says is in
    crore, and getting that wrong by 100x would put RELIANCE in the
    small-cap band."""
    pd = pytest.importorskip("pandas")
    pytest.importorskip("openpyxl")
    src = tmp_path / "LIST_NSE.xlsx"
    column = "Average market capitalisation (Rs. In lakhs)"
    pd.DataFrame([{"Rank": 1, "Symbol": "ACME", column: 100000.0}]
                 ).to_excel(src, index=False)
    out = tmp_path / "company_size.json"
    monkeypatch.setattr(company_size, "STORE", str(out))
    company_size._CACHE.clear()
    company_size.refresh(source=str(src), store=str(out))
    assert company_size.of("ACME")["cap_cr"] == 1000.0


def test_a_missing_source_leaves_the_store_alone(store):
    """The list is placed on disk by hand, not fetched. A refresh with
    no file must not empty what is already known."""
    before = company_size.band_of("RELIANCE")
    assert company_size.refresh(source="data/no_such_file.xlsx",
                                store=store) == 0
    company_size._CACHE.clear()
    assert company_size.band_of("RELIANCE") == before


# ------------------------------------------------------------------
# it reaches the book
# ------------------------------------------------------------------

def test_every_trade_records_the_band(store, tmp_path):
    from core.trade_memory import TradeMemory
    book = TradeMemory(f"sqlite:///{tmp_path / 'trade_memory.db'}")
    assert book.record({
        "symbol": "TEJASNET", "direction": "LONG",
        "entry_time": datetime(2026, 9, 7, 9, 30),
        "exit_time": datetime(2026, 9, 7, 10, 15),
        "entry_price": 100.0, "exit_price": 103.0, "qty": 10,
        "pnl": 30.0, "exit_reason": "TARGET", "door": "news",
    })
    row = sqlite3.connect(str(tmp_path / "trade_memory.db")).execute(
        "SELECT mcap_band, mcap_cr FROM trade_memory").fetchone()
    assert row == ("SMALL", 9989.2)


def test_a_stock_with_no_size_records_no_band(store, tmp_path):
    from core.trade_memory import TradeMemory
    book = TradeMemory(f"sqlite:///{tmp_path / 'trade_memory.db'}")
    book.record({
        "symbol": "NOSUCHCO", "direction": "LONG",
        "entry_time": datetime(2026, 9, 7, 9, 30),
        "exit_time": datetime(2026, 9, 7, 10, 15),
        "entry_price": 10.0, "exit_price": 11.0, "qty": 5, "pnl": 5.0,
        "exit_reason": "TARGET",
    })
    row = sqlite3.connect(str(tmp_path / "trade_memory.db")).execute(
        "SELECT mcap_band, mcap_cr FROM trade_memory").fetchone()
    assert row == (None, None)


def test_the_engine_may_stamp_it_instead(store, tmp_path):
    """Taken from the position first, so an engine that starts
    stamping the band at entry wins without a change in record()."""
    from core.trade_memory import TradeMemory
    book = TradeMemory(f"sqlite:///{tmp_path / 'trade_memory.db'}")
    book.record({
        "symbol": "TEJASNET", "direction": "LONG",
        "entry_time": datetime(2026, 9, 7, 9, 30),
        "exit_time": datetime(2026, 9, 7, 10, 15),
        "entry_price": 100.0, "exit_price": 103.0, "qty": 10,
        "pnl": 30.0, "exit_reason": "TARGET",
        "mcap_band": "MID", "mcap_cr": 40000.0,
    })
    row = sqlite3.connect(str(tmp_path / "trade_memory.db")).execute(
        "SELECT mcap_band, mcap_cr FROM trade_memory").fetchone()
    assert row == ("MID", 40000.0)


def test_the_column_is_added_to_a_book_that_predates_it(tmp_path):
    """create_all() creates missing TABLES, never columns. A live book
    keeps its old shape, and record() swallows exceptions by design --
    so a forgotten migration means nothing is ever recorded again and
    nobody notices."""
    from core.trade_memory import TradeMemory
    path = tmp_path / "trade_memory.db"
    old = sqlite3.connect(str(path))
    old.execute("CREATE TABLE trade_memory (id INTEGER PRIMARY KEY,"
                " symbol TEXT, direction TEXT, trade_date TEXT,"
                " entry_time TIMESTAMP)")
    old.commit()
    old.close()
    TradeMemory(f"sqlite:///{path}")
    columns = [d[1] for d in sqlite3.connect(str(path)).execute(
        "PRAGMA table_info(trade_memory)")]
    assert "mcap_band" in columns and "mcap_cr" in columns


# ------------------------------------------------------------------
# and it reaches the board, drawing nothing that decides anything
# ------------------------------------------------------------------

def test_the_board_stamps_the_row():
    src = io.open("dashboard/state.py", encoding="utf-8").read()
    assert "def _stamp_company_size" in src
    assert "self._stamp_company_size(" in src, \
        "the stamper exists and the payload never calls it"


def test_the_page_draws_it():
    page = io.open("dashboard/static/desk.html", encoding="utf-8").read()
    assert "function sizeOf" in page
    assert "+ sizeOf(r)" in page, "sizeOf() exists and no row calls it"
    assert ".tag.size{" in page


def test_the_refresh_tool_runs_the_way_he_runs_it():
    """---- IT FAILED ON HIS FIRST RUN. 6 September 2026. ----

        py tools/refresh_company_size.py
        ModuleNotFoundError: No module named 'core'

    I had only ever run it with PYTHONPATH set, so I never saw it, and
    then handed him the command. `py tools/x.py` puts tools/ on the
    path, not the project root. 101 of the tools in this repo already
    carry the fix; the new one did not.

    Anchored on __file__ rather than on ".", the shape
    tools/refresh_market_cap.py uses, so it works from any directory
    and not just from the project root.
    """
    src = io.open("tools/refresh_company_size.py", encoding="utf-8").read()
    assert "sys.path.insert" in src, \
        "run it from a shell and it cannot find core/"
    # The IMPORT STATEMENT, at the start of a line -- the comment above
    # the fix quotes the same words, and matching that made this test
    # fail against a file that was correct.
    assert src.index("sys.path.insert") < src.index("\nfrom core import"), \
        "the path is fixed AFTER the import that needs it"
    assert "os.path.abspath(__file__)" in src, \
        'anchored on the working directory -- breaks unless he happens '\
        'to be standing in the project root'


def test_no_gate_reads_the_size():
    """The whole promise of this change. If it is ever wired into a
    rule that must be a deliberate act with evidence behind it, not a
    drift -- and by then his own book will have the evidence."""
    for path in ("core/rules.py", "core/ranker.py", "core/auto_entry.py",
                 "core/engine.py", "core/results_gate.py",
                 "core/why_moving.py"):
        src = io.open(path, encoding="utf-8").read()
        assert "company_size" not in src, \
            "%s reads the size band -- that was never decided" % path


def test_the_free_float_store_is_untouched():
    """core/market_cap.py answers a different question and the
    standing-order gate depends on it. Nothing here may change it."""
    from core import market_cap
    assert market_cap.STORE.endswith("market_cap.json")
    assert company_size.STORE.endswith("company_size.json")
    assert market_cap.STORE != company_size.STORE
    src = io.open("core/company_size.py", encoding="utf-8").read()
    assert "market_cap" not in src.split('"""', 2)[2], \
        "company_size imports the free-float store"
