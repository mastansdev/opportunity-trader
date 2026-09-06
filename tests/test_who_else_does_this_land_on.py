"""
==========================================================
UltraTech walked into wires and cables
==========================================================

    "recent ultratech announced its wire & cables capex. then bot
     needs to check ultratech business (positive to neutral or non
     event too until the real business lands) + wires & cables business
     companies (for this sector its negative update) ... it will be
     recorded in memory that this day this sector is impacted by that
     company & impacted stocks performance on event day"

    "all details must saved in database with their respective stocks
     not in another stock or another info"
                                -- the operator, 6 September 2026

WHAT HAPPENED, 1 September 2026. "ULTRATECH CEMENT: CO. COMMENCES
COMMERCIAL PRODUCTION OF 11 LAKH KM WIRES & CABLES PLANT AT BHARUCH":

    ULTRACEMCO   -0.44%   the announcer -- a non-event, as he said
    KEI          -6.83%   high -2.30%, never green all day
    POLYCAB      -5.82%   high -2.50%, never green all day
    RRKABEL      -2.00%   and -8.34% the next day
    APARINDS     -1.71%   and -3.37% the next day
    DYCL         +9.98%   it had its own cable order that week

DYCL is why this records rather than concludes. Five of the seven
fell; one rose on news of its own. The memory holds what each stock
DID, per stock, and lets him read it.

THREE THINGS WERE WRONG BEFORE THIS PASSED, all found by running it
over three weeks of real events rather than the one example.

  A MENTION IS NOT AN ENTRY. The first rule was "a business named
  here that this company is not in". It produced TCS entering METRO,
  PURVA entering MUMBAI, SPECTRUM entering RURAL. I had said no list
  of expansion words was needed; his own headline carries one, and
  ENTRY_SIGNALS now requires it. 11,306 events, 55 entries.

  ADJACENT TAGS ARE ONE MARKET, DISTANT ONES ARE NOT. Taking every
  business named pulled his example from 7 companies to 30, because
  the headline ends "...WIRES & CABLES PLANT AT BHARUCH SUPPORTING
  INFRASTRUCTURE" and 23 infrastructure builders came with it.
  Keeping only the tightest tag went the other way and dropped the
  CABLES-only names. The text says which is which.

  A SPLIT IS NOT A FALL. The scan reported an incumbent down 50.45%.
  KIRLPNU went 1,534.30 to 760.20 on 18 August -- a 1:2 split with an
  unadjusted previous close. A wrong number in a memory the bot will
  reason from is worse than a missing one.

IT TRADES NOTHING, and a test below enforces that.

Author : H&M Opportunity Trader
==========================================================
"""

import io
import os
import sqlite3
import tempfile

import pytest

from core import sector_impact as si


HEADLINE = ("ULTRATECH CEMENT: CO. COMMENCES COMMERCIAL PRODUCTION OF "
            "11 LAKH KM WIRES & CABLES PLANT AT BHARUCH SUPPORTING "
            "INFRASTRUCTURE")


@pytest.fixture()
def store(tmp_path):
    return str(tmp_path / "sector_impact.db")


@pytest.fixture()
def daily(tmp_path):
    """A day of prices for the companies in his example."""
    path = str(tmp_path / "daily_candles.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE daily_bars (date TEXT, symbol TEXT, "
                 "close REAL, high REAL, low REAL, prev_close REAL)")
    rows = [("ULTRACEMCO", 99.56, 100.87, 99.48), ("KEI", 93.17, 97.70, 92.36),
            ("POLYCAB", 94.18, 97.50, 93.92), ("RRKABEL", 98.00, 101.76, 96.78),
            ("APARINDS", 98.29, 101.23, 97.73), ("DYCL", 109.98, 113.54, 98.07),
            ("KEC", 100.12, 101.20, 99.60), ("UNIVCABLES", 99.78, 102.84, 97.99)]
    for sym, close, high, low in rows:
        conn.execute("INSERT INTO daily_bars VALUES (?,?,?,?,?,?)",
                     ("2026-09-01", sym, close, high, low, 100.0))
    # a 1:2 split, prev_close never adjusted
    conn.execute("INSERT INTO daily_bars VALUES (?,?,?,?,?,?)",
                 ("2026-09-01", "SPLITCO", 50.0, 51.0, 49.0, 100.0))
    conn.commit()
    conn.close()
    return path


# ------------------------------------------------------------------
# the event he named
# ------------------------------------------------------------------

def test_it_names_the_entrant_and_the_incumbents():
    got = si.impact_of("ULTRACEMCO", HEADLINE)
    assert got is not None
    assert got["entrant"] == "ULTRACEMCO"
    assert set(got["incumbents"]) == {
        "APARINDS", "DYCL", "KEC", "KEI", "POLYCAB", "RRKABEL", "UNIVCABLES"}


def test_its_own_business_is_not_an_entry():
    """CEMENT is named in the same headline and UltraTech is a cement
    company. Dropping it needs no understanding of the words -- it is
    already in that business."""
    assert "CEMENT" not in si.entering("ULTRACEMCO", HEADLINE)


def test_a_distant_business_is_context_not_a_market():
    """"WIRES & CABLES" is one phrase. "SUPPORTING INFRASTRUCTURE" is
    twenty characters further on and brought 23 builders with it."""
    got = si.impact_of("ULTRACEMCO", HEADLINE)
    assert len(got["incumbents"]) == 7
    assert "JKIL" not in got["incumbents"]
    assert "PATELENG" not in got["incumbents"]


def test_a_mention_is_not_an_entry():
    """TCS entering METRO, PURVA entering MUMBAI -- the first version
    produced both."""
    assert si.impact_of("TCS", "TCS wins a metro rail IT contract") is None
    assert si.announces_an_entry("UltraTech may look at cables one day") \
        is False
    assert si.announces_an_entry(HEADLINE) is True


def test_a_company_already_in_the_business_is_not_entering_it():
    assert si.impact_of("KEI", HEADLINE) is None or \
        "WIRES" not in si.entering("KEI", HEADLINE)


# ------------------------------------------------------------------
# "with their respective stocks, not in another stock"
# ------------------------------------------------------------------

def test_every_stock_gets_its_own_row_and_its_own_numbers(store, daily):
    written = si.record("ULTRACEMCO", HEADLINE, "2026-09-01",
                        db_path=store, daily_db=daily)
    assert written == 8                      # the entrant and seven others
    rows = {r["symbol"]: r for r in si.recall(db_path=store)}
    assert rows["ULTRACEMCO"]["role"] == "ENTRANT"
    assert rows["KEI"]["role"] == "INCUMBENT"
    # each carries ITS OWN move, never the entrant's
    assert rows["KEI"]["move_pct"] == -6.83
    assert rows["POLYCAB"]["move_pct"] == -5.82
    assert rows["ULTRACEMCO"]["move_pct"] == -0.44
    assert rows["DYCL"]["move_pct"] == 9.98


def test_the_headline_is_the_link_not_the_stocks_own_news(store, daily):
    """The bug this is the opposite of: UltraTech's launch was filed
    ON KEI as if it were KEI's own story. Here it is context on a row
    that says plainly who acted and who was hit."""
    si.record("ULTRACEMCO", HEADLINE, "2026-09-01",
              db_path=store, daily_db=daily)
    kei = [r for r in si.recall(db_path=store) if r["symbol"] == "KEI"][0]
    assert kei["entrant"] == "ULTRACEMCO"
    assert kei["role"] == "INCUMBENT"
    assert "ULTRATECH" in kei["headline"].upper()


def test_recording_twice_does_not_duplicate(store, daily):
    for _ in range(3):
        si.record("ULTRACEMCO", HEADLINE, "2026-09-01",
                  db_path=store, daily_db=daily)
    rows = si.recall(db_path=store)
    assert len(rows) == len({(r["day"], r["symbol"]) for r in rows}) == 8


def test_a_split_is_never_recorded_as_a_fall(daily):
    assert si._day_move("SPLITCO", "2026-09-01", daily) is None
    assert si._day_move("KEI", "2026-09-01", daily)["move_pct"] == -6.83


def test_the_recall_groups_by_event_and_pools_nothing(store, daily):
    si.record("ULTRACEMCO", HEADLINE, "2026-09-01",
              db_path=store, daily_db=daily)
    lines = si.what_happened(db_path=store)
    assert len(lines) == 1
    line = lines[0]
    assert line["entrant"] == "ULTRACEMCO"
    assert line["entrant_move"] == -0.44
    assert line["incumbents"] == 7
    assert line["fell"] == 5           # DYCL and KEC rose
    assert line["worst"] == -6.83


# ------------------------------------------------------------------
# and it decides nothing
# ------------------------------------------------------------------

def test_nothing_in_the_trading_path_reads_this():
    for path in ("core/rules.py", "core/ranker.py", "core/auto_entry.py",
                 "core/engine.py", "core/why_moving.py",
                 "core/results_gate.py"):
        src = io.open(path, encoding="utf-8").read()
        assert "sector_impact" not in src, \
            f"{path} reads the sector memory -- that was never decided"


def test_it_never_raises_on_rubbish():
    assert si.impact_of(None, None) is None
    assert si.impact_of("", "") is None
    assert si.businesses_in(None) == []
    assert si.record("NOSUCH", "nothing here", "2026-09-01",
                     db_path=os.path.join(tempfile.mkdtemp(), "x.db")) == 0


def test_the_entry_gates_are_untouched():
    from core.rules import (MIN_MOVE_FROM_PREV_CLOSE_PCT, MIN_VOLUME_RATIO,
                            REQUIRE_A_REASON_ALWAYS)
    assert MIN_MOVE_FROM_PREV_CLOSE_PCT == 3.0
    assert MIN_VOLUME_RATIO == 2.5
    assert REQUIRE_A_REASON_ALWAYS is True
