"""
==========================================================
Security ids must match the exchange's own token numbers
==========================================================

    "nothing is impossible when you're more interested in finding a
     way than finding excuses."
                                -- operator, 8 August 2026

WHAT HAPPENED
-------------
MOTHERSON was subscribed, unblocked, and produced no price on any
session while the operator held 2,000 shares. tools/verify_master_
database.py reported its id CORRECT every night.

It could not do otherwise. That check fetched Dhan's scrip master and
resolved through core/instrument_master.py -- the same function that
had WRITTEN the id into data/master_stocks.csv. It compared a value
against itself.

    A check that shares its bug with the thing it checks cannot fail.

THE WAY THROUGH
---------------
NSE's UDiFF bhavcopy carries FinInstrmId: the exchange's own token,
which for NSE_EQ is exactly Dhan's SECURITY ID. Forty of those files
were already on disk. Measured against the 7 August file:

    1,498 agree
        3 WRONG -- MOTHERSON 25510 (真 4204)
                   CHOLAFIN  19257 (真 685)
                   ELECTCAST 18116 (真 928)

Those are the same three, and only those three, that Dhan's live quote
API refused in tools/probe_silent.py -- run separately, on his
machine, against a different service. Two unrelated sources agreeing
is evidence; one source agreeing with itself is not.

WHY EQ SERIES ONLY
------------------
ELECTCAST carries two NSE rows: EQ and W1, the warrant. That second
row is what made iloc[0] in core/instrument_master.py pick blind. The
cash series is the only one the feed subscribes to.

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import glob
import os

import pytest

BHAV_GLOB = os.path.join("data", "BhavCopy_NSE_CM_*.csv")


def _newest_bhavcopy():
    files = sorted(glob.glob(BHAV_GLOB))
    if not files:
        pytest.skip("no bhavcopy on disk")
    return files[-1]


def _exchange_tokens(path):
    """{symbol: token} for the cash series, dropping any duplicates."""
    out, dupes = {}, set()
    with open(path, newline="", encoding="utf-8", errors="ignore") as handle:
        for row in csv.DictReader(handle):
            if (row.get("SctySrs") or "").strip().upper() != "EQ":
                continue
            symbol = (row.get("TckrSymb") or "").strip().upper()
            token = (row.get("FinInstrmId") or "").strip()
            if not symbol or not token:
                continue
            if symbol in out and out[symbol] != token:
                dupes.add(symbol)
            out[symbol] = token
    for symbol in dupes:
        out.pop(symbol, None)
    return out


def test_the_bhavcopy_still_carries_the_token_column():
    """If NSE changes the format again this fails loudly, instead of
    the verifier quietly finding nothing to check."""
    path = _newest_bhavcopy()
    with open(path, newline="", encoding="utf-8", errors="ignore") as handle:
        columns = csv.DictReader(handle).fieldnames or []
    for needed in ("TckrSymb", "SctySrs", "FinInstrmId"):
        assert needed in columns, (
            f"{needed} has gone from the bhavcopy -- "
            f"tools/verify_ids_offline.py is now blind")


def test_every_subscribed_id_matches_the_exchange():
    """THE test. A wrong id here is a stock that silently never prices,
    or -- worse -- one that prices off another instrument."""
    from core.master_loader import MasterLoader

    tokens = _exchange_tokens(_newest_bhavcopy())
    if not tokens:
        pytest.skip("bhavcopy carried no EQ rows")

    loader = MasterLoader()
    loader.load()

    wrong = []
    for symbol in loader.all_symbols():
        ours = str(loader.security_id(symbol) or "").strip()
        theirs = tokens.get(symbol)
        if theirs is not None and ours != theirs:
            wrong.append(f"{symbol}: master {ours}, NSE {theirs}")

    assert not wrong, (
        "security ids disagree with the exchange's own tokens:\n  "
        + "\n  ".join(wrong)
        + "\n\nRun: py tools/verify_ids_offline.py --apply")


def test_the_three_that_were_broken_are_now_right():
    """Named explicitly. If a future master rebuild reintroduces the
    old values, this says which and why."""
    from core.master_loader import MasterLoader

    loader = MasterLoader()
    loader.load()
    for symbol, correct, was in (("MOTHERSON", "4204", "25510"),
                                 ("CHOLAFIN", "685", "19257"),
                                 ("ELECTCAST", "928", "18116")):
        got = str(loader.security_id(symbol) or "")
        assert got != was, (
            f"{symbol} is back on {was}, the id Dhan refuses to quote")
        assert got == correct, (
            f"{symbol} should be {correct} (NSE's token), got {got}")


def test_the_offline_check_does_not_depend_on_dhan():
    """The whole point. tools/verify_master_database.py needs a token,
    a static IP and a route to Dhan; this needs a file already on
    disk, so it can run in CI, on a plane, or in a sandbox."""
    import inspect
    import importlib.util

    path = os.path.join("tools", "verify_ids_offline.py")
    assert os.path.exists(path)
    spec = importlib.util.spec_from_file_location("verify_ids_offline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    src = inspect.getsource(module)
    for banned in ("dhanhq", "api.dhan.co", "images.dhan.co", "requests",
                   "urllib"):
        assert banned not in src, (
            f"the offline verifier reaches for {banned} -- it is no "
            f"longer independent of the source it is checking")
