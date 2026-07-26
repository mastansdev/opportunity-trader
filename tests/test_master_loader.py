"""
Decision-correctness tests for MasterLoader: does it load
the real file cleanly, and does it actually REFUSE to run
on broken data instead of silently continuing.
"""

import os
import tempfile

import pytest

from core.master_loader import MasterLoader

_GOOD_HEADER = (
    "SECURITY ID,SYMBOL,COMPANY NAME,SECTOR,INDUSTRY,CORE BUSINESS,"
    "BUSINESS_TYPE,OWNERSHIP,COMMODITY_EXPOSURE,ECONOMIC_SENSITIVITY,"
    "KEYWORDS,THEMES\n"
)


def _write_csv(tmp_path, rows):
    path = os.path.join(tmp_path, "test_master.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_GOOD_HEADER)
        f.write(rows)
    return path


def test_real_master_database_loads(tmp_path=None):
    # NOT pinned to an exact row count any more. The morning tool
    # appends every new NSE listing (186 of them on 2026-07-26), so a
    # hardcoded 750 turned a normal pre-market run into a test failure
    # and hid the real regression underneath it.
    loader = MasterLoader(csv_path=os.path.join("data", "master_stocks.csv"))
    count = loader.load()
    assert count > 700
    # Every row must resolve a security id for its symbol.
    for symbol in loader.all_symbols():
        assert loader.security_id(symbol) not in (None, "", "nan")


def test_duplicate_symbol_is_rejected(tmp_path):
    rows = (
        "1,TCS,Tata Consultancy,IT,Software,Software services,"
        "SERVICE PROVIDER,PRIVATE,NONE,NONE,SOFTWARE,IT\n"
        "2,TCS,Tata Consultancy,IT,Software,Software services,"
        "SERVICE PROVIDER,PRIVATE,NONE,NONE,SOFTWARE,IT\n"
    )
    path = _write_csv(str(tmp_path), rows)
    loader = MasterLoader(csv_path=path)

    with pytest.raises(RuntimeError, match="Duplicate SYMBOL"):
        loader.load()


def test_duplicate_security_id_is_rejected(tmp_path):
    rows = (
        "1,TCS,Tata Consultancy,IT,Software,Software services,"
        "SERVICE PROVIDER,PRIVATE,NONE,NONE,SOFTWARE,IT\n"
        "1,INFY,Infosys,IT,Software,Software services,"
        "SERVICE PROVIDER,PRIVATE,NONE,NONE,SOFTWARE,IT\n"
    )
    path = _write_csv(str(tmp_path), rows)
    loader = MasterLoader(csv_path=path)

    with pytest.raises(RuntimeError, match="Duplicate SECURITY ID"):
        loader.load()


def test_empty_cell_is_rejected_not_silently_loaded(tmp_path):
    # No SUBSCRIBE column at all -> every row counts as tradeable, so a
    # blank SECTOR is still fatal.
    rows = (
        "1,TCS,Tata Consultancy,IT,,Software services,"
        "SERVICE PROVIDER,PRIVATE,NONE,NONE,SOFTWARE,IT\n"
    )
    path = _write_csv(str(tmp_path), rows)
    loader = MasterLoader(csv_path=path)

    with pytest.raises(RuntimeError, match="missing classification"):
        loader.load()


# ----------------------------------------------------------
# 2026-07-26 regression. tools/morning_universe.py queues new NSE
# listings into the master with identity only and SUBSCRIBE=NO
# ("awaiting sector classification"). load() demanded all twelve
# columns on every row, so the morning run added 186 such rows and made
# the file unloadable -- and main.py calls load() before anything else,
# so the bot would not have STARTED. Killed by rows it had itself
# decided not to trade.
# ----------------------------------------------------------

_SUBSCRIBE_HEADER = _GOOD_HEADER.rstrip("\n") + ",SUBSCRIBE,SUBSCRIBE_REASON\n"


def _write_csv_with_subscribe(tmp_path, rows):
    path = os.path.join(tmp_path, "test_master_subscribe.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_SUBSCRIBE_HEADER)
        f.write(rows)
    return path


def test_blocked_row_may_be_unclassified(tmp_path):
    rows = (
        "1,TCS,Tata Consultancy,IT,Software,Software services,"
        "SERVICE PROVIDER,PRIVATE,NONE,NONE,SOFTWARE,IT,YES,\n"
        # exactly what the morning tool writes for a new listing
        "2,SHADOWFAX,SHADOWFAX,,,,,,,,,,NO,new listing -- awaiting "
        "sector classification\n"
    )
    path = _write_csv_with_subscribe(str(tmp_path), rows)
    loader = MasterLoader(csv_path=path)

    assert loader.load() == 2
    assert loader.all_symbols() == ["TCS"]
    assert "SHADOWFAX" in loader.blocked_symbols()
    # It is still LOOKUP-able -- news matching and sector lookups want
    # blocked rows too.
    assert loader.get_by_symbol("SHADOWFAX") is not None


def test_tradeable_row_may_not_be_unclassified(tmp_path):
    # The half that must still fail: a stock the bot CAN trade with no
    # SECTOR would silently break the top-8 sector gate.
    rows = (
        "1,TCS,Tata Consultancy,IT,Software,Software services,"
        "SERVICE PROVIDER,PRIVATE,NONE,NONE,SOFTWARE,IT,YES,\n"
        "2,MYSTERY,Mystery Corp,,,,,,,,,,YES,\n"
    )
    path = _write_csv_with_subscribe(str(tmp_path), rows)
    loader = MasterLoader(csv_path=path)

    with pytest.raises(RuntimeError, match="missing classification"):
        loader.load()


def test_blank_identity_is_always_fatal(tmp_path):
    # Being blocked excuses a missing SECTOR. It does not excuse a
    # missing SECURITY ID -- that is corruption, not a to-do.
    rows = (
        "1,TCS,Tata Consultancy,IT,Software,Software services,"
        "SERVICE PROVIDER,PRIVATE,NONE,NONE,SOFTWARE,IT,YES,\n"
        ",NOID,No Id Corp,,,,,,,,,,NO,new listing\n"
    )
    path = _write_csv_with_subscribe(str(tmp_path), rows)
    loader = MasterLoader(csv_path=path)

    with pytest.raises(RuntimeError, match="missing identity"):
        loader.load()


def test_real_master_has_no_tradeable_row_missing_a_sector(tmp_path=None):
    # Guards the live file directly: whatever the morning tool did, no
    # stock the bot will actually trade may be missing its sector.
    loader = MasterLoader(csv_path=os.path.join("data", "master_stocks.csv"))
    loader.load()
    for symbol in loader.all_symbols():
        row = loader.get_by_symbol(symbol)
        sector = str(row.get("SECTOR") or "").strip()
        assert sector and sector.lower() != "nan", (
            f"{symbol} is subscribed but has no SECTOR"
        )


def test_missing_file_raises_a_clear_error(tmp_path):
    loader = MasterLoader(csv_path=os.path.join(str(tmp_path), "nope.csv"))

    with pytest.raises(RuntimeError, match="not found"):
        loader.load()


def test_lookup_by_symbol_and_security_id_agree(tmp_path):
    rows = (
        "500,TCS,Tata Consultancy,IT,Software,Software services,"
        "SERVICE PROVIDER,PRIVATE,NONE,NONE,SOFTWARE,IT\n"
    )
    path = _write_csv(str(tmp_path), rows)
    loader = MasterLoader(csv_path=path)
    loader.load()

    by_symbol = loader.get_by_symbol("TCS")
    by_id = loader.get_by_security_id("500")

    assert by_symbol["SECURITY ID"] == "500"
    assert by_id["SYMBOL"] == "TCS"
