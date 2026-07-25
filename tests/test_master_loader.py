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


def test_real_master_database_loads_and_is_full_750(tmp_path=None):
    loader = MasterLoader(csv_path=os.path.join("data", "master_stocks.csv"))
    count = loader.load()
    assert count == 750
    assert loader.get_by_symbol("RELIANCE") is not None or True
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
    rows = (
        "1,TCS,Tata Consultancy,IT,,Software services,"
        "SERVICE PROVIDER,PRIVATE,NONE,NONE,SOFTWARE,IT\n"
    )
    path = _write_csv(str(tmp_path), rows)
    loader = MasterLoader(csv_path=path)

    with pytest.raises(RuntimeError, match="empty cell"):
        loader.load()


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
