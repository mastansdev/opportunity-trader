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


# ---------------------------------------------------------------
# THE SERIES GATE -- a rule that existed and was never enforced
# ---------------------------------------------------------------
#
# 16 August 2026. all_symbols()' own docstring promised that "a T2T /
# illiquid / ex-date stock never reaches the feed", and that was only
# true when a human remembered to mark it SUBSCRIBE=NO.
# core/universe_builder.py has defined TRADEABLE_SERIES = {"EQ"} since
# it was written and enforced it only in the tools that PROPOSE list
# changes -- core/engine.py, core/ranker.py, core/auto_entry.py and
# core/master_loader.py contained zero mentions of "series".
#
# The cost was concrete. 3IINFOLTD and SPECIALITY were SUBSCRIBE=YES,
# series BE, with security ids that exist nowhere in Dhan's master.
# Correcting the ids -- the obvious fix -- would have made two
# trade-to-trade stocks reachable: no intraday exit, no MTF, on a bot
# that sizes every position on a 2.5% stop. (It is NOT flat at 15:30
# -- FORCE_SQUARE_OFF_AT_CLOSE is False -- but a T2T name cannot be
# bought on margin or sold before settlement either way.)

_SERIES_HEADER = (
    "SECURITY ID,SYMBOL,SERIES,COMPANY NAME,SECTOR,INDUSTRY,CORE BUSINESS,"
    "BUSINESS_TYPE,OWNERSHIP,COMMODITY_EXPOSURE,ECONOMIC_SENSITIVITY,"
    "KEYWORDS,THEMES\n"
)


def _write_series_csv(tmp_path, rows):
    path = os.path.join(str(tmp_path), "series_master.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_SERIES_HEADER)
        f.write(rows)
    return path


def _row(sec_id, symbol, series):
    return (f"{sec_id},{symbol},{series},{symbol} Ltd,IT,Software,"
            f"Software services,SERVICE PROVIDER,PRIVATE,NONE,NONE,"
            f"SOFTWARE,IT\n")


def test_a_trade_to_trade_row_never_reaches_the_feed(tmp_path):
    """THE ONE THAT MATTERS. BE is trade-to-trade: compulsory
    delivery, no intraday square-off, no MTF."""
    path = _write_series_csv(tmp_path, _row(1, "GOODEQ", "EQ")
                             + _row(2, "BADBE", "BE"))
    loader = MasterLoader(csv_path=path)
    loader.load()

    assert "GOODEQ" in loader.all_symbols()
    assert "BADBE" not in loader.all_symbols(), (
        "a BE-series stock reached the subscription list -- this bot "
        "cannot exit it the same day")
    assert "BADBE" in loader.blocked_symbols()
    assert "BE" in loader.blocked_symbols()["BADBE"], (
        "blocked without saying which series, so nobody can tell it "
        "from a stock the operator excluded by hand")


@pytest.mark.parametrize("series", ["BE", "BZ", "SM", "ST", "RR", "IV", "SF"])
def test_every_non_eq_series_is_refused(series):
    """The real file carries all of these. Only EQ is tradeable."""
    import tempfile as _tf
    with _tf.TemporaryDirectory() as d:
        path = _write_series_csv(d, _row(1, "KEEPME", "EQ")
                                 + _row(2, "DROPME", series))
        loader = MasterLoader(csv_path=path)
        loader.load()
        assert "DROPME" not in loader.all_symbols(), series


def test_a_blank_series_is_unknown_not_untradeable(tmp_path):
    """FAIL-OPEN. A master file written before the SERIES column
    existed must load and trade exactly as it did. Absent means "not
    known", never "not EQ" -- silently dropping the whole universe
    because a column is missing is far worse than the fault it guards."""
    path = _write_series_csv(tmp_path, _row(1, "NOSERIES", ""))
    loader = MasterLoader(csv_path=path)
    loader.load()
    assert "NOSERIES" in loader.all_symbols()


def test_a_file_with_no_series_column_still_loads(tmp_path):
    """The older shape, unchanged."""
    rows = ("1,TCS,Tata Consultancy,IT,Software,Software services,"
            "SERVICE PROVIDER,PRIVATE,NONE,NONE,SOFTWARE,IT\n")
    loader = MasterLoader(csv_path=_write_csv(str(tmp_path), rows))
    loader.load()
    assert "TCS" in loader.all_symbols()


def test_the_rule_is_borrowed_not_copied():
    """core/universe_builder.py owns TRADEABLE_SERIES. A second copy
    in master_loader would be the exact sediment core/rules.py exists
    to prevent, and it has caused live bugs here before."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "core" / "master_loader.py").read_text(encoding="utf-8")
    assert "from core.universe_builder import TRADEABLE_SERIES" in src

    # Read the CODE, not the prose. The first version of this assert
    # matched the docstring that EXPLAINS why the rule is borrowed --
    # "universe_builder.py has owned TRADEABLE_SERIES = {"EQ"} since it
    # was written" -- and failed on the sentence describing the very
    # thing it was checking for. Same mistake, twice in one morning:
    # tests/test_opportunity_brain.py matched engine.py's docstring for
    # the word "opportunity".
    import ast
    tree = ast.parse(src)
    declared = [
        t.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Name)
    ]
    assert "TRADEABLE_SERIES" not in declared, (
        "master_loader declares its own copy of the series rule")


def test_the_live_file_has_a_series_for_every_tradeable_row():
    """Belt and braces against the real data: if the column ever stops
    being populated the gate silently stops guarding anything."""
    loader = MasterLoader()
    loader.load()
    missing = [s for s in loader.all_symbols()
               if not str((loader.get_by_symbol(s) or {}).get("SERIES")
                          or "").strip()]
    assert not missing, (
        f"{len(missing)} tradeable row(s) have no SERIES, so the T2T "
        f"gate cannot see them: {missing[:10]}")
