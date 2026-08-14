"""
==========================================================
Delivery percentage -- the footprint before the move
==========================================================

    "by seeing them many FII/DII, retail Algos started to accumalte
     stocks even some weak stocks will get locked in upper citcuits"
                                -- operator, 7 August 2026

    "DELIVER % - YES"

WHAT THIS IS FOR
----------------
Everything else on the screen reacts to a move that has already
happened. Delivery percentage is the one published number that shows
stock being TAKEN OFF the market while the price is still quiet:

    three to five sessions of above-average delivery, in a tight price
    range, on falling volume

That is supply being absorbed without the price being chased.

WHY A SECOND DOWNLOAD WAS NEEDED
--------------------------------
The bot already pulls NSE's UDiFF bhavcopy nightly. Checked column by
column on the real 7 August file: OHLC, volume, turnover, trade count,
and no delivery figures at all -- Rsvd1 through Rsvd4 are empty. The
figures live in sec_bhavdata_full, a different published file.

THE RULE THAT MUST NOT DRIFT
----------------------------
It reports. It does not veto and it does not score. Same standing rule
as the run-up check:

    "nothing from the guides becomes a rule until scored against real
     outcomes"

Author : H&M Opportunity Trader
==========================================================
"""

import os
import tempfile
from datetime import date, timedelta

import pytest

from core import delivery


@pytest.fixture
def db():
    return os.path.join(tempfile.mkdtemp(), "delivery.db")


def _feed(db, symbol, series, start=date(2026, 7, 20)):
    """series is [(deliv_pct, close, volume), ...] oldest first."""
    for i, (pct, close, volume) in enumerate(series):
        delivery.store(start + timedelta(days=i),
                       [{"symbol": symbol, "close": close, "volume": volume,
                         "deliv_qty": volume * pct / 100.0,
                         "deliv_pct": pct}], db_path=db)


QUIET = [(40, 100, 900), (38, 101, 880), (42, 100, 860), (41, 101, 840),
         (39, 100, 820), (44, 101, 800)]


# ---------------------------------------------------------------
# Reading the NSE file
# ---------------------------------------------------------------
def test_it_survives_nses_padded_headers():
    """NSE writes ' SERIES' and ' DELIV_PER' with leading spaces. A
    naive dict lookup finds none of it."""
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "sec_bhavdata_full_07082026.csv")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, "
            "LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, "
            "TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
            "HINDALCO, EQ, 07-Aug-2026, 1050, 1052, 1060, 1048, 1059, "
            "1059.6, 1055, 5000000, 52800, 45000, 3100000, 62.00\n")
    rows = delivery.parse(path)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "HINDALCO"
    assert rows[0]["deliv_pct"] == 62.0
    assert rows[0]["close"] == 1059.6


def test_only_the_cash_series_is_kept():
    """A futures row carries a delivery figure that means nothing for
    the cash stock."""
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "x.csv")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("SYMBOL, SERIES, CLOSE_PRICE, TTL_TRD_QNTY, "
                     "DELIV_QTY, DELIV_PER\n"
                     "REAL, EQ, 100, 1000, 600, 60.00\n"
                     "REAL, BE, 100, 1000, 900, 90.00\n"
                     "FUT, FUTSTK, 1, 1, 1, 99.00\n")
    rows = delivery.parse(path)
    assert [r["symbol"] for r in rows] == ["REAL"]
    assert rows[0]["deliv_pct"] == 60.0


def test_a_missing_file_is_not_a_crash():
    assert delivery.parse("data/does_not_exist.csv") == []


# ---------------------------------------------------------------
# THE PATTERN
# ---------------------------------------------------------------
def test_quiet_absorption_reads_ACCUMULATION(db):
    """Delivery up, price flat, volume falling -- the one worth
    waiting for."""
    _feed(db, "ABSORB", QUIET + [(66, 100.5, 600), (68, 101, 560),
                                 (70, 100.8, 520)])
    got = delivery.reading("ABSORB", on_date=date(2026, 7, 28), db_path=db)
    assert got["reading"] == "ACCUMULATION"
    assert got["pct"] > got["avg"]


def test_delivery_up_with_price_up_is_only_BUYING(db):
    """Real, but not the quiet-absorption setup -- the price is
    already being chased."""
    _feed(db, "CHASED", QUIET + [(65, 116, 900), (67, 121, 900),
                                 (69, 126, 900)])
    got = delivery.reading("CHASED", on_date=date(2026, 7, 28), db_path=db)
    assert got["reading"] == "BUYING"


def test_delivery_up_with_price_down_is_DISTRIBUTION(db):
    """The mirror image, and the one that must never be confused for
    accumulation -- he trades long only."""
    _feed(db, "DISTRO", QUIET + [(66, 85, 900), (68, 82, 900),
                                 (70, 79, 900)])
    got = delivery.reading("DISTRO", on_date=date(2026, 7, 28), db_path=db)
    assert got["reading"] == "DISTRIBUTION"


def test_mostly_intraday_hands_reads_CHURN(db):
    _feed(db, "CHURN", QUIET + [(12, 100, 900), (11, 100, 900),
                                (10, 100, 900)])
    got = delivery.reading("CHURN", on_date=date(2026, 7, 28), db_path=db)
    assert got["reading"] == "CHURN"


def test_too_little_history_says_nothing(db):
    """A run needs sessions. One day of data must produce None, not a
    confident reading off a single number."""
    _feed(db, "NEW", [(70, 100, 900), (72, 101, 900)])
    assert delivery.reading("NEW", on_date=date(2026, 7, 28),
                            db_path=db) is None
    assert delivery.reading("NEVERSEEN", db_path=db) is None


def test_it_cannot_read_the_future(db):
    """Same discipline as graded_symbols() and catalysts: a reading
    asked for Monday must not use Tuesday's delivery."""
    _feed(db, "LATER", QUIET + [(66, 100, 600), (68, 101, 560),
                                (70, 100, 520)])
    early = delivery.reading("LATER", on_date=date(2026, 7, 22), db_path=db)
    assert early is None or early["sessions"] <= 3


# ---------------------------------------------------------------
# It must reach the screen, and it must not become a rule
# ---------------------------------------------------------------
def test_the_dashboard_computes_it():
    import inspect

    from dashboard import state
    src = inspect.getsource(state)
    assert "_delivery_for" in src
    assert 'row["delivery"]' in src, (
        "the reading is computed but never attached to a ranked row")


def test_the_page_renders_it():
    """---- IT WAS DRAWN ON A PAGE HE HAD LEFT. 13 Aug 2026. ----

        "DELIVER % - YES"          -- operator, 8 August 2026

    This checked dashboard/static/app.html. He moved to /board on
    9 August, so the reading he asked for was being drawn on a screen
    he no longer opened -- and when the four pages were collapsed to
    two on 13 August and app.html was deleted, it stopped being visible
    anywhere at all.

    Measured, stored, fresh (57,674 rows), and on no screen. That is
    the fault this project keeps repeating, and it is exactly what
    core/knowledge.py's SHOWS column exists to make obvious.

    Checked against the TRADING screen now, because that is the one he
    watches.
    """
    page = open("dashboard/static/board.html", encoding="utf-8").read()
    assert "r.delivery" in page, (
        "core/delivery.py is wired into the snapshot but /board does "
        "not draw it -- he still cannot see it")


def test_it_never_vetoes_an_entry():
    """The line that must not move."""
    import inspect

    from core import auto_entry, position_plan, ranker
    for module in (auto_entry, ranker, position_plan):
        src = inspect.getsource(module)
        assert "delivery" not in src.lower(), (
            f"{module.__name__} has started reading delivery -- it was "
            f"built to report, not to refuse")
