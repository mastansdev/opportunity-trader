"""
==========================================================
Two rows for one symbol must never be resolved silently
==========================================================

    "BUT YOU NEED TO CHECK WITH NSE/CHROME FOR THE CHOLAFIN, ELECTCAST,
     MOTHERSON . ID'S & CHECK WITH DHAN DATABASE"
                                -- operator, 8 August 2026

WHAT WAS MEASURED
-----------------
tools/probe_silent.py, run against the live Dhan account on 8 August:

    HINDALCO   1363    1059.60   control -- the call works
    CHOLAFIN  19257        --    Dhan refuses to quote this id
    ELECTCAST 18116        --    Dhan refuses to quote this id
    MOTHERSON 25510        --    Dhan refuses to quote this id

Eleven other silent stocks came back WITH prices, proving the account,
the token and the segment were all fine in the same call.

All three refused ids had been passing tools/verify_master_database.py
as CORRECT, every night, for as long as it has been running.

WHY THE CHECK COULD NOT CATCH IT
--------------------------------
InstrumentMaster.resolve() ended in:

    security_id = str(match.iloc[0]["SEM_SMST_SECURITY_ID"])

iloc[0] takes the first matching row with no test that there is only
one. And tools/verify_master_database.py resolves through the SAME
function, so it compared a wrong id against itself and agreed.

    A check that shares its bug with the thing it checks cannot fail.

That is why the operator held 2,000 MOTHERSON shares for six sessions
with no price on his screen and nothing reported it.

THE RULE NOW
------------
    one NSE equity row            -> use it
    several, exactly one is EQ    -> use the EQ row, say so out loud
    several, no single EQ row     -> return None and refuse to guess

Refusing costs one stock. Guessing costs a position priced off the
wrong instrument, which nothing downstream can detect.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

pd = pytest.importorskip("pandas")

from core.instrument_master import InstrumentMaster        # noqa: E402


def _master(rows):
    im = InstrumentMaster.__new__(InstrumentMaster)
    im._security_id = {}
    im._df = pd.DataFrame(rows)
    return im


def _row(symbol, security_id, series="EQ", exch="NSE", kind="EQUITY"):
    return {"SEM_EXM_EXCH_ID": exch, "SEM_INSTRUMENT_NAME": kind,
            "SEM_TRADING_SYMBOL": symbol,
            "SEM_SMST_SECURITY_ID": security_id, "SEM_SERIES": series}


def test_a_single_row_resolves_normally():
    im = _master([_row("HINDALCO", 1363)])
    assert im.resolve("HINDALCO") == "1363"


def test_two_rows_prefer_the_EQ_series():
    """A cash listing trades in EQ. BE and BZ are restricted books and
    are not what the feed subscribes to."""
    im = _master([_row("DOUBLE", 25510, series="BE"),
                  _row("DOUBLE", 99999, series="EQ")])
    assert im.resolve("DOUBLE") == "99999"


def test_row_order_does_not_decide_it():
    """The whole bug was that pandas' ordering picked the answer."""
    im = _master([_row("DOUBLE", 99999, series="EQ"),
                  _row("DOUBLE", 25510, series="BE")])
    assert im.resolve("DOUBLE") == "99999"


def test_no_EQ_row_refuses_rather_than_guessing():
    """Refusing costs one stock. Guessing costs a position priced off
    the wrong instrument, and nothing downstream can detect that."""
    im = _master([_row("MESSY", 111, series="BE"),
                  _row("MESSY", 222, series="BZ")])
    assert im.resolve("MESSY") is None


def test_two_EQ_rows_also_refuse():
    im = _master([_row("TWINS", 111), _row("TWINS", 222)])
    assert im.resolve("TWINS") is None


def test_a_missing_symbol_still_returns_none():
    im = _master([_row("HINDALCO", 1363)])
    assert im.resolve("NOSUCH") is None


def test_non_NSE_and_non_equity_rows_are_ignored():
    """A BSE listing or a futures contract must not create a false
    ambiguity for the cash symbol."""
    im = _master([_row("HINDALCO", 1363),
                  _row("HINDALCO", 5555, exch="BSE"),
                  _row("HINDALCO", 7777, kind="FUTSTK")])
    assert im.resolve("HINDALCO") == "1363"


def test_the_ambiguity_is_announced_not_swallowed(caplog):
    """Silence about a second candidate is how MOTHERSON went six
    sessions with no price and nothing said so.

    core/logger.py routes through logging, not print, so caplog is the
    fixture that sees it -- capsys returns empty here and the first
    version of this test failed for that reason alone."""
    import logging
    im = _master([_row("DOUBLE", 25510, series="BE"),
                  _row("DOUBLE", 99999, series="EQ")])
    with caplog.at_level(logging.WARNING):
        im.resolve("DOUBLE")
    said = caplog.text
    assert "DOUBLE" in said, "the ambiguity was resolved in silence"
    assert "25510" in said and "99999" in said, (
        "it did not name both candidates -- he cannot check the choice")


def test_the_verifier_no_longer_shares_the_bug():
    """tools/verify_master_database.py resolves through this same
    function. With ambiguity returning None it now lands in the
    not_found bucket instead of silently agreeing with itself."""
    import inspect

    from core import instrument_master
    src = inspect.getsource(instrument_master.InstrumentMaster.resolve)
    assert "iloc[0]" in src, "the single-row path was removed entirely"
    assert "len(ids) > 1" in src, (
        "resolve() no longer checks for multiple matching rows -- the "
        "8 August MOTHERSON fault is back")
